import base64
import io
import contextlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import sign_bottles as signer


CONFIGURATION = {'APPLE_TEAM_ID': 'TESTTEAM01', 'NOTARY_API_KEY_ID': 'TESTKEY001',
                 'NOTARY_API_ISSUER_ID': 'test-issuer'}
SECRET_FIXTURES = {
    'DEVELOPER_ID_P12_BASE64': base64.b64encode(b'fake certificate for unit tests').decode(),
    'DEVELOPER_ID_P12_PASSWORD': 'fake certificate password',
    'NOTARY_API_PRIVATE_KEY': '-----BEGIN PRIVATE KEY-----\nfake test key\n-----END PRIVATE KEY-----',
}


class SigningCommandStub:
    """Replace only subprocess execution; exercise real credential and archive handling."""
    def __init__(self, case, *, accepted=True):
        self.case = case
        self.accepted = accepted
        self.calls = []
        self.credential_paths = []

    def __call__(self, arguments, **kwargs):
        self.calls.append(arguments)
        self.case.assertTrue(set(signer.SECRET_NAMES).isdisjoint(kwargs['env']))
        stdout, stderr = b'', b''
        command = arguments[:2]
        if command == ['/usr/bin/security', 'import']:
            certificate = Path(arguments[2])
            self.case.assertEqual(certificate.read_bytes(), b'fake certificate for unit tests')
            self.case.assertEqual(certificate.stat().st_mode & 0o777, 0o600)
            self.credential_paths.append(certificate)
        elif command == ['/usr/bin/security', 'find-identity']:
            stdout = (f'  1) {"A" * 40} "Developer ID Application: Test ({CONFIGURATION["APPLE_TEAM_ID"]})"\n'
                      '  1 valid identities found\n').encode()
        elif command == ['/usr/bin/security', 'list-keychains']:
            stdout = b'"/Users/test/Library/Keychains/login.keychain-db"'
        elif arguments[0] == '/usr/bin/security' and arguments[1] in (
            'create-keychain', 'set-keychain-settings', 'unlock-keychain',
            'set-key-partition-list', 'delete-keychain',
        ):
            pass
        elif command == ['/usr/bin/codesign', '--force']:
            target = Path(arguments[-1])
            if target.suffix == '.app':
                (target / 'Contents/CodeResources').write_text('fake signature')
        elif command == ['/usr/bin/codesign', '--verify']:
            pass
        elif command == ['/usr/bin/codesign', '-d']:
            stderr = (f'TeamIdentifier={CONFIGURATION["APPLE_TEAM_ID"]}\n'
                      f'Identifier={signer.HOST_IDENTIFIER}\n'
                      'Authority=Developer ID Application: Test\n'
                      'flags=0x10000(runtime)\nTimestamp=test timestamp\n').encode()
        elif command == ['/usr/bin/ditto', '-c']:
            Path(arguments[-1]).write_bytes(b'fake notarization zip')
        elif arguments[:3] == ['/usr/bin/xcrun', 'notarytool', 'submit']:
            key = Path(arguments[arguments.index('--key') + 1])
            self.case.assertEqual(key.read_text().strip(), SECRET_FIXTURES['NOTARY_API_PRIVATE_KEY'])
            self.case.assertEqual(key.stat().st_mode & 0o777, 0o600)
            self.credential_paths.append(key)
            stdout = json.dumps({'id': 'test-submission',
                                 'status': 'Accepted' if self.accepted else 'Invalid'}).encode()
        elif arguments[:3] == ['/usr/bin/xcrun', 'notarytool', 'log']:
            stdout = json.dumps({'message': 'test rejection',
                                 'detail': SECRET_FIXTURES['NOTARY_API_PRIVATE_KEY']}).encode()
        elif arguments[:3] == ['/usr/bin/xcrun', 'stapler', 'staple']:
            (Path(arguments[-1]) / 'Contents/ticket').write_text('fake ticket')
        else:
            self.case.fail(f'Unexpected native command: {command}')
        return subprocess.CompletedProcess(arguments, 0, stdout, stderr)


class BottleSigningTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'input'
        self.source.mkdir()
        self.prefix = self.root / 'content/xcode-mcpkit/1.2.3'
        self.app = self.prefix / 'libexec/XcodeMCPNativeHost.app'
        contents = self.app / 'Contents'
        (contents / 'MacOS').mkdir(parents=True)
        (contents / 'Info.plist').write_bytes(plistlib.dumps({
            'CFBundleIdentifier': 'com.apple.dt.mcp-server',
            'CFBundleExecutable': 'xcode-mcp-native-host',
        }))
        for path in [contents / 'MacOS/xcode-mcp-native-host',
                     self.prefix / 'libexec/xcode-mcp-proxy',
                     self.prefix / 'libexec/xcode-mcp-proxy-server']:
            path.write_bytes(bytes.fromhex('cffaedfe') + b'executable fixture')
        (self.prefix / 'bin').mkdir()
        (self.prefix / 'bin/xcode-mcp-proxy').symlink_to('../libexec/xcode-mcp-proxy')
        self.archive = self.source / 'xcode-mcpkit--1.2.3.arm64_tahoe.bottle.tar.gz'
        self.metadata = self.source / 'xcode-mcpkit--1.2.3.arm64_tahoe.bottle.json'
        self.pack()

    def pack(self):
        with tarfile.open(self.archive, 'w:gz') as tar:
            tar.add(self.prefix.parent, arcname='xcode-mcpkit')
        self.value = {'lynnswap/tap/xcode-mcpkit': {
            'formula': {'name': 'xcode-mcpkit', 'tap_git_revision': 'a' * 40, 'tap_git_path': 'Formula/xcode-mcpkit.rb'},
            'bottle': {'cellar': 'any_skip_relocation', 'tags': {'arm64_tahoe': {
                'local_filename': self.archive.name, 'sha256': signer.digest(self.archive),
                'all_files': [], 'installed_size': 0}}}}}
        self.metadata.write_text(json.dumps(self.value))

    def test_signing_rewrites_only_payload_checksum_and_preserves_other_formulae(self):
        other = self.source / 'another--1.0.arm64_tahoe.bottle.tar.gz'
        other.write_bytes(b'other tested bottle')
        original = json.loads(self.metadata.read_text())
        def sign(tools, root, prefix, credentials, configuration):
            (prefix / 'libexec/XcodeMCPNativeHost.app/Contents/CodeResources').write_text('signed')
            return 'accepted-submission'
        output = self.root / 'signed'
        with patch.object(signer, 'sign_archive', side_effect=sign), contextlib.redirect_stdout(io.StringIO()):
            signer.sign_bottle(self.source, output, {}, signer.SigningCredentials(None, 'local', self.root/'key'))
        result = json.loads((output / self.metadata.name).read_text())
        expected = original['lynnswap/tap/xcode-mcpkit']['bottle']['tags']['arm64_tahoe']
        expected['sha256'] = signer.digest(output / self.archive.name)
        actual = result['lynnswap/tap/xcode-mcpkit']['bottle']['tags']['arm64_tahoe']
        self.assertIn('libexec/XcodeMCPNativeHost.app/Contents/CodeResources', actual['all_files'])
        self.assertGreater(actual['installed_size'], 0)
        expected.update(all_files=actual['all_files'], installed_size=actual['installed_size'])
        self.assertEqual(result, original)
        self.assertEqual((output / other.name).read_bytes(), other.read_bytes())
        self.assertNotEqual(signer.digest(self.archive), signer.digest(output / self.archive.name))

    def test_changed_input_or_relocatable_bottle_cannot_be_signed(self):
        self.archive.write_bytes(self.archive.read_bytes() + b'changed')
        with self.assertRaisesRegex(signer.ReleaseError, 'tested metadata'):
            signer.bottle_entries(self.source)
        self.pack()
        self.value['lynnswap/tap/xcode-mcpkit']['bottle']['cellar'] = 'any'
        self.metadata.write_text(json.dumps(self.value))
        with self.assertRaisesRegex(signer.ReleaseError, 'skip relocation'):
            signer.bottle_entries(self.source)

    def test_archive_cannot_escape_before_credentials_are_imported(self):
        for name, target in [('../outside', None), ('/outside', None), ('escape', '../../outside')]:
            with self.subTest(name=name):
                with tarfile.open(self.archive, 'w:gz') as tar:
                    entry = tarfile.TarInfo(name)
                    if target:
                        entry.type, entry.linkname = tarfile.SYMTYPE, target
                        tar.addfile(entry)
                    else:
                        entry.size = 1
                        tar.addfile(entry, io.BytesIO(b'x'))
                self.value['lynnswap/tap/xcode-mcpkit']['bottle']['tags']['arm64_tahoe']['sha256'] = signer.digest(self.archive)
                self.metadata.write_text(json.dumps(self.value))
                with patch.object(signer, 'temporary_credentials') as credentials:
                    with self.assertRaises((signer.ReleaseError, tarfile.FilterError)):
                        signer.sign_bottle(self.source, self.root/'output', {})
                    credentials.assert_not_called()

    def test_nested_swift_libraries_are_included_and_extra_code_is_rejected(self):
        library = self.app / 'Contents/Frameworks/libswift_Concurrency.dylib'
        library.parent.mkdir()
        library.write_bytes(bytes.fromhex('cffaedfe'))
        _, _, code = signer.payload_code(self.prefix)
        self.assertIn(library, code)
        extra = self.prefix / 'share/unexpected-tool'
        extra.parent.mkdir()
        extra.write_bytes(bytes.fromhex('cffaedfe'))
        with self.assertRaisesRegex(signer.ReleaseError, 'outside the supported'):
            signer.payload_code(self.prefix)

    def test_native_tools_remove_secrets_from_child_environment_and_errors(self):
        tools = signer.NativeTools()
        tools.redactions = ['password value']
        with patch.dict(os.environ, {name: 'password value' for name in signer.SECRET_NAMES}):
            with patch.object(signer.subprocess, 'run') as run:
                run.return_value.stdout = b''
                run.return_value.stderr = b'error password value'
                run.return_value.returncode = 1
                with self.assertRaisesRegex(signer.ReleaseError, r'error \[REDACTED\]'):
                    tools.run(['/usr/bin/security'], 'Import key')
                self.assertTrue(set(signer.SECRET_NAMES).isdisjoint(run.call_args.kwargs['env']))

    def test_cleanup_failure_retains_the_original_signing_failure(self):
        tools = signer.NativeTools()
        response = signer.NativeResult(b'"/Users/test/Library/Keychains/login.keychain-db"', b'', 0)
        cleanup = signer.ReleaseError('Restore keychain search list failed')
        with patch.object(tools, 'run', side_effect=[response, response, cleanup]):
            with self.assertRaises(BaseExceptionGroup) as result:
                with signer.searchable_keychain(tools, self.root / 'temporary.keychain-db'):
                    raise signer.ReleaseError('Signing failed')
        self.assertEqual([str(error) for error in result.exception.exceptions],
                         ['Signing failed', 'Restore keychain search list failed'])

    def test_signing_requires_the_expected_developer_id_team(self):
        identity = b'  1) ' + b'A' * 40 + b' "Developer ID Application: Test (58KPFKMJJW)"\n  1 valid identities found\n'
        self.assertEqual(signer.signing_identity(identity, '58KPFKMJJW'), 'A' * 40)
        with self.assertRaises(signer.ReleaseError):
            signer.signing_identity(identity, 'WRONGTEAM1')

    def test_missing_environment_secret_fails_before_native_commands(self):
        for missing in signer.SECRET_NAMES:
            with self.subTest(secret=missing), patch.dict(os.environ, {**SECRET_FIXTURES, missing: ''}):
                with patch.object(signer.subprocess, 'run') as run:
                    with self.assertRaisesRegex(signer.ReleaseError, f'{missing} is required for release signing'):
                        signer.sign_bottle(self.source, self.root / 'signed', CONFIGURATION)
                    run.assert_not_called()
                self.assertTrue(set(signer.SECRET_NAMES).isdisjoint(os.environ))
                self.assertFalse((self.root / 'signed').exists())

    def test_ci_credentials_flow_through_signing_and_are_removed(self):
        commands = SigningCommandStub(self)
        output = self.root / 'signed'
        report = io.StringIO()
        with patch.dict(os.environ, SECRET_FIXTURES), patch.object(signer.subprocess, 'run', side_effect=commands):
            with contextlib.redirect_stdout(report):
                signer.sign_bottle(self.source, output, CONFIGURATION)
            self.assertTrue(set(signer.SECRET_NAMES).isdisjoint(os.environ))
        self.assertEqual(json.loads(report.getvalue())['notarization_id'], 'test-submission')
        self.assertEqual(commands.calls[-2][0:2], ['/usr/bin/security', 'list-keychains'])
        self.assertEqual(commands.calls[-2][-1], '/Users/test/Library/Keychains/login.keychain-db')
        self.assertEqual(commands.calls[-1][0:2], ['/usr/bin/security', 'delete-keychain'])
        self.assertTrue(commands.credential_paths)
        self.assertTrue(all(not path.parent.exists() for path in commands.credential_paths))
        with tarfile.open(output / self.archive.name) as archive:
            names = archive.getnames()
            self.assertIn('xcode-mcpkit/1.2.3/libexec/XcodeMCPNativeHost.app/Contents/ticket', names)
            self.assertFalse(any(name.endswith(('.p8', '.p12', '.keychain-db')) for name in names))
        for secret in SECRET_FIXTURES.values():
            self.assertNotIn(secret, report.getvalue())

    def test_notarization_rejection_cleans_credentials_and_does_not_publish_output(self):
        commands = SigningCommandStub(self, accepted=False)
        output = self.root / 'signed'
        with patch.dict(os.environ, SECRET_FIXTURES), patch.object(signer.subprocess, 'run', side_effect=commands):
            with self.assertRaisesRegex(signer.ReleaseError, 'Notarization rejected') as result:
                signer.sign_bottle(self.source, output, CONFIGURATION)
            self.assertTrue(set(signer.SECRET_NAMES).isdisjoint(os.environ))
        self.assertEqual(commands.calls[-1][0:2], ['/usr/bin/security', 'delete-keychain'])
        self.assertTrue(all(not path.parent.exists() for path in commands.credential_paths))
        self.assertFalse(output.exists())
        self.assertIn('[REDACTED]', str(result.exception))
        for secret in SECRET_FIXTURES.values():
            self.assertNotIn(secret, str(result.exception))


if __name__ == '__main__':
    unittest.main()
