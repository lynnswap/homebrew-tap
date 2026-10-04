import io
import contextlib
import json
import os
from pathlib import Path
import plistlib
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import sign_bottles as signer


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


if __name__ == '__main__':
    unittest.main()
