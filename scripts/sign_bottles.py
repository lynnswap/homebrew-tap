#!/usr/bin/env python3
"""Sign and notarize the tested XcodeMCPKit bottle without executing its payload."""
from __future__ import annotations

import argparse
import base64
import binascii
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile

SECRET_NAMES = ("DEVELOPER_ID_P12_BASE64", "DEVELOPER_ID_P12_PASSWORD", "NOTARY_API_PRIVATE_KEY")
HOST_IDENTIFIER = "com.lynnswap.XcodeMCPNativeHost"
MACHO_MAGICS = {bytes.fromhex(value) for value in (
    "feedface", "cefaedfe", "feedfacf", "cffaedfe", "cafebabe", "bebafeca", "cafebabf", "bfbafeca",
)}

class ReleaseError(Exception):
    """An actionable failure whose message contains no native command or credentials."""


@dataclass
class NativeResult:
    stdout: bytes
    stderr: bytes
    returncode: int | None


class NativeTools:
    """Own child environments and keep command arguments out of error reporting."""

    def __init__(self):
        self.redactions: list[str] = []

    def run(self, arguments: list[str], operation: str, *, allow_failure=False, timeout=300) -> NativeResult:
        environment = {name: os.environ[name] for name in os.environ if name not in SECRET_NAMES}
        try:
            completed = subprocess.run(arguments, capture_output=True, env=environment, timeout=timeout)
            result = NativeResult(completed.stdout, completed.stderr, completed.returncode)
        except subprocess.TimeoutExpired as error:
            result = NativeResult(error.stdout or b"", error.stderr or b"", None)
        except OSError:
            raise ReleaseError(f"{operation}: could not start the native tool.") from None
        if not allow_failure and result.returncode != 0:
            reason = "timed out" if result.returncode is None else f"failed with exit code {result.returncode}"
            detail = " ".join(self.redact(result.stderr.decode("utf-8", errors="replace")).split())[:4000]
            raise ReleaseError(f"{operation}: {reason}." + (f" {detail}" if detail else "")) from None
        return result

    def redact(self, value):
        if isinstance(value, str):
            for secret in self.redactions:
                value = value.replace(secret, "[REDACTED]")
                value = value.replace(json.dumps(secret)[1:-1], "[REDACTED]")
            return value
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        if isinstance(value, dict):
            return {self.redact(key): self.redact(item) for key, item in value.items()}
        return value


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


@dataclass(frozen=True)
class SigningCredentials:
    keychain: Path | None
    certificate_sha1: str
    notary_key: Path


def signing_identity(output: bytes, team: str) -> str:
    text = output.decode("utf-8", errors="replace")
    identities = re.findall(r'^\s*\d+\)\s+([A-Fa-f0-9]{40})\s+"([^"\r\n]+)"\s*$', text, re.MULTILINE)
    if (len(identities) != 1 or not re.search(r"^\s*1 valid identities found\s*$", text, re.MULTILINE)
            or not identities[0][1].startswith("Developer ID Application: ")
            or not identities[0][1].endswith(f" ({team})")):
        raise ReleaseError("The temporary keychain must contain exactly one valid Developer ID Application identity for APPLE_TEAM_ID.")
    return identities[0][0].upper()


@contextmanager
def searchable_keychain(tools: NativeTools, keychain: Path):
    original = shlex.split(tools.run(
        ["/usr/bin/security", "list-keychains", "-d", "user"], "Read keychain search list",
    ).stdout.decode("utf-8"))
    try:
        # An explicit codesign --keychain still requires membership in the user's search list.
        tools.run([
            "/usr/bin/security", "list-keychains", "-d", "user", "-s", *original, str(keychain),
        ], "Include temporary signing keychain")
        yield
    finally:
        original_error = sys.exception()
        try:
            tools.run([
                "/usr/bin/security", "list-keychains", "-d", "user", "-s", *original,
            ], "Restore keychain search list")
        except Exception as cleanup:
            if original_error:
                raise BaseExceptionGroup("Signing and keychain restoration failed", [original_error, cleanup])
            raise


@contextmanager
def temporary_credentials(tools: NativeTools, parent: Path, configuration: dict[str, str]):
    with tempfile.TemporaryDirectory(prefix="credentials-", dir=parent) as directory:
        root = Path(directory)
        keychain = root / "signing.keychain-db"
        created = False
        try:
            values = {}
            for name in SECRET_NAMES:
                value = os.environ.pop(name, "")
                if not value:
                    raise ReleaseError(f"{name} is required for release signing.")
                values[name] = value
                tools.redactions.append(value)
            try:
                encoded_p12 = "".join(values["DEVELOPER_ID_P12_BASE64"].split())
                if not encoded_p12:
                    raise ReleaseError("DEVELOPER_ID_P12_BASE64 is empty.")
                tools.redactions.append(encoded_p12)
                p12_bytes = base64.b64decode(encoded_p12, validate=True)
            except (ValueError, binascii.Error):
                raise ReleaseError("DEVELOPER_ID_P12_BASE64 must contain valid base64.") from None
            pem = values["NOTARY_API_PRIVATE_KEY"].strip()
            if not (pem.startswith("-----BEGIN PRIVATE KEY-----\n") and pem.endswith("\n-----END PRIVATE KEY-----")):
                raise ReleaseError("NOTARY_API_PRIVATE_KEY must contain a PKCS#8 PEM private key.")
            tools.redactions.append(pem)
            p12 = root / "identity.p12"
            notary_key = root / "notary.p8"
            for path, data in ((p12, p12_bytes), (notary_key, (pem + "\n").encode())):
                with path.open("xb") as output:
                    path.chmod(0o600)
                    output.write(data)
            password = secrets.token_urlsafe(48)
            tools.redactions.append(password)
            tools.run(["/usr/bin/security", "create-keychain", "-p", password, str(keychain)], "Create temporary signing keychain")
            created = True
            tools.run(["/usr/bin/security", "set-keychain-settings", "-lut", "21600", str(keychain)], "Configure temporary signing keychain")
            tools.run(["/usr/bin/security", "unlock-keychain", "-p", password, str(keychain)], "Unlock temporary signing keychain")
            tools.run([
                "/usr/bin/security", "import", str(p12), "-k", str(keychain), "-f", "pkcs12", "-x",
                "-P", values["DEVELOPER_ID_P12_PASSWORD"], "-T", "/usr/bin/codesign",
            ], "Import release signing identity")
            p12.unlink()
            identity = signing_identity(tools.run([
                "/usr/bin/security", "find-identity", "-v", "-p", "codesigning", str(keychain),
            ], "Validate imported signing identity").stdout, configuration["APPLE_TEAM_ID"])
            tools.run([
                "/usr/bin/security", "set-key-partition-list", "-S", "apple-tool:,apple:,codesign:",
                "-s", "-k", password, str(keychain),
            ], "Authorize codesign for the imported key")
            with searchable_keychain(tools, keychain):
                yield SigningCredentials(keychain, identity, notary_key)
        finally:
            original_error = sys.exception()
            try:
                if created or keychain.exists():
                    tools.run(["/usr/bin/security", "delete-keychain", str(keychain)], "Delete temporary signing keychain")
            except Exception as cleanup:
                if original_error:
                    raise BaseExceptionGroup("Signing and keychain cleanup failed", [original_error, cleanup])
                raise
            finally:
                for name in SECRET_NAMES:
                    os.environ.pop(name, None)



def bottle_entries(directory):
    entries = []
    for path in directory.glob('*.bottle.json'):
        metadata = json.loads(path.read_text())
        for entry in metadata.values():
            if entry['formula']['name'] != 'xcode-mcpkit':
                continue
            for tag in entry['bottle']['tags'].values():
                name = tag['local_filename']
                if Path(name).name != name or not name.endswith('.tar.gz'):
                    raise ReleaseError('Bottle filename must be a local tar archive.')
                archive = directory / name
                if archive.is_symlink() or not archive.is_file() or digest(archive) != tag['sha256']:
                    raise ReleaseError('Bottle bytes do not match the tested metadata.')
                if tag.get('cellar', entry['bottle'].get('cellar')) != 'any_skip_relocation':
                    raise ReleaseError('Developer ID bottles must skip relocation so Homebrew preserves their signatures.')
                entries.append((path, metadata, tag, archive))
    if len(entries) != 1:
        raise ReleaseError('Expected one XcodeMCPKit bottle and platform tag.')
    return entries[0]


def extract(archive, root):
    with tarfile.open(archive, 'r:gz') as tar:
        for member in tar.getmembers():
            name = PurePosixPath(member.name)
            if name.is_absolute() or '..' in name.parts:
                raise ReleaseError('Bottle contains a path outside its extraction root.')
        tar.extractall(root, filter='data')
    roots = list(root.iterdir())
    if len(roots) != 1 or roots[0].name != 'xcode-mcpkit' or roots[0].is_symlink():
        raise ReleaseError('Bottle must contain only its XcodeMCPKit keg.')
    versions = list(roots[0].iterdir())
    if len(versions) != 1 or not versions[0].is_dir() or versions[0].is_symlink():
        raise ReleaseError('Bottle must contain one XcodeMCPKit version directory.')
    return versions[0]


def payload_code(prefix):
    payload = prefix / 'libexec'
    app = payload / 'XcodeMCPNativeHost.app'
    host = app / 'Contents/MacOS/xcode-mcp-native-host'
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    if info.get('CFBundleIdentifier') != 'com.apple.dt.mcp-server' or info.get('CFBundleExecutable') != host.name:
        raise ReleaseError('Bottle does not contain the native host bundle contract.')
    required = {host, payload / 'xcode-mcp-proxy', payload / 'xcode-mcp-proxy-server'}
    code = []
    for path in prefix.rglob('*'):
        if path.is_symlink():
            if not path.resolve().is_relative_to(prefix.resolve()):
                raise ReleaseError('Bottle contains a link outside its version directory.')
            continue
        if not path.is_file():
            continue
        with path.open('rb') as stream:
            macho = stream.read(4) in MACHO_MAGICS
        if not macho:
            continue
        library = path.suffix == '.dylib' and path.parent in (
            payload / 'xcode-mcp-runtime', app / 'Contents/Frameworks')
        if path not in required and not library:
            raise ReleaseError('Bottle contains code outside the supported CLI, helper, and Swift library layout.')
        code.append(path)
    if not required <= set(code):
        raise ReleaseError('Bottle is missing a required native executable.')
    return app, host, code


def native_entitlements(tools):
    developer = Path(os.environ.get('DEVELOPER_DIR') or tools.run(
        ['/usr/bin/xcode-select', '-p'], 'Select Xcode').stdout.decode().strip())
    paths = [developer / 'Library/Xcode/Agents/Xcode Service.app', developer / 'usr/bin/mcpbridge']
    def merge(left, right):
        if isinstance(left, dict) and isinstance(right, dict):
            result = dict(left)
            for key, value in right.items():
                result[key] = merge(result[key], value) if key in result else value
            return result
        if isinstance(left, list) and isinstance(right, list):
            return left + [item for item in right if item not in left]
        if type(left) is type(right) and left == right:
            return left
        raise ReleaseError('Selected Xcode service and bridge entitlements conflict.')
    result = {}
    for path in paths:
        data = tools.run(['/usr/bin/codesign', '-d', '--entitlements', ':-', str(path)],
                         'Read selected Xcode entitlements').stdout
        result = merge(result, plistlib.loads(data))
    result['com.apple.security.cs.allow-dyld-environment-variables'] = True
    return result


def verify_signature(tools, path, team, identifier=None):
    tools.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(path)], 'Verify signature')
    info = tools.run(['/usr/bin/codesign', '-d', '--verbose=4', str(path)], 'Inspect signature').stderr.decode()
    flags = re.search(r'flags=0x([a-fA-F0-9]+)', info)
    fields = info.splitlines()
    if (f'TeamIdentifier={team}' not in fields or 'Authority=Developer ID Application: ' not in info
            or not flags or not int(flags[1], 16) & 0x10000
            or not any(line.startswith('Timestamp=') and line not in ('Timestamp=none', 'Timestamp=') for line in fields)
            or (identifier and f'Identifier={identifier}' not in fields)):
        raise ReleaseError('Missing expected Developer ID, Team ID, signing identifier, timestamp, or hardened runtime.')


def verify_install(prefix, team):
    tools = NativeTools()
    app, host, code = payload_code(prefix)
    for path in code:
        verify_signature(tools, path, team, HOST_IDENTIFIER if path == host else None)
    tools.run(['/usr/bin/xcrun', 'stapler', 'validate', str(app)], 'Validate notarization ticket')
    tools.run(['/usr/sbin/spctl', '--assess', '--type', 'execute', str(app)], 'Assess notarized app')


def sign_archive(tools, root, prefix, credentials, configuration):
    app, host, code = payload_code(prefix)
    entitlements = root / 'native-entitlements.plist'
    entitlements.write_bytes(plistlib.dumps(native_entitlements(tools)))
    common = ['/usr/bin/codesign', '--force', '--sign', credentials.certificate_sha1,
              '--timestamp', '--options', 'runtime']
    if credentials.keychain:
        common += ['--keychain', str(credentials.keychain)]
    for path in code:
        if path == host:
            continue
        identifier = f'com.lynnswap.XcodeMCPKit.{path.name}'
        tools.run([*common, '--identifier', identifier, str(path)], 'Sign nested code or CLI')
    tools.run([*common, '--identifier', HOST_IDENTIFIER, '--entitlements', str(entitlements), str(app)], 'Sign native host')
    for path in code:
        verify_signature(tools, path, configuration['APPLE_TEAM_ID'], HOST_IDENTIFIER if path == host else None)
    archive = root / 'notarization.zip'
    tools.run(['/usr/bin/ditto', '-c', '-k', '--keepParent', str(prefix), str(archive)], 'Prepare notarization archive')
    authentication = ['--key', str(credentials.notary_key), '--key-id', configuration['NOTARY_API_KEY_ID'],
                      '--issuer', configuration['NOTARY_API_ISSUER_ID']]
    result = tools.run(['/usr/bin/xcrun', 'notarytool', 'submit', str(archive), *authentication,
                        '--wait', '--output-format', 'json'], 'Submit for notarization', timeout=1800)
    report = json.loads(result.stdout)
    if report.get('status') != 'Accepted':
        # Apple logs describe code validation, never payload execution.
        log = tools.run(['/usr/bin/xcrun', 'notarytool', 'log', report['id'], *authentication], 'Read notarization rejection')
        raise ReleaseError('Notarization rejected: ' + tools.redact(log.stdout.decode())[:8000])
    tools.run(['/usr/bin/xcrun', 'stapler', 'staple', str(app)], 'Staple native host ticket')
    return report['id']


def sign_bottle(source, output, configuration, local_credentials=None):
    metadata_path, metadata, tag, archive = bottle_entries(source)
    if output.exists() and any(output.iterdir()):
        raise ReleaseError('Use an empty output directory for signed bottles.')
    tools = NativeTools()
    with tempfile.TemporaryDirectory(prefix='xcodemcp-sign-') as temporary:
        root = Path(temporary)
        content = root / 'content'
        content.mkdir()
        prefix = extract(archive, content)
        payload_code(prefix)  # Validate paths before importing any private key.
        if local_credentials:
            submission = sign_archive(tools, root, prefix, local_credentials, configuration)
        else:
            with temporary_credentials(tools, root, configuration) as credentials:
                submission = sign_archive(tools, root, prefix, credentials, configuration)
        # No imported credentials or payload execution is needed to package the result.
        output.mkdir(parents=True, exist_ok=True)
        for path in source.glob('*.bottle.*'):
            if path not in (metadata_path, archive):
                shutil.copy2(path, output / path.name)
        target = output / archive.name
        with tarfile.open(target, 'w:gz') as tar:
            for path in sorted(content.iterdir()):
                tar.add(path, arcname=path.name)
        tag['sha256'] = digest(target)
        if 'all_files' in tag:
            tag['all_files'] = sorted(str(path.relative_to(prefix)) for path in prefix.rglob('*') if path.is_file())
        if 'installed_size' in tag:
            sizes = {}
            for path in [prefix, *prefix.rglob('*')]:
                info = path.lstat()
                sizes[info.st_dev, info.st_ino] = info.st_size
            tag['installed_size'] = sum(sizes.values())
        (output / metadata_path.name).write_text(json.dumps(metadata, indent=2) + '\n')
        print(json.dumps({'notarization_id': submission, 'bottle': target.name, 'sha256': tag['sha256']}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    sign = commands.add_parser('sign')
    sign.add_argument('--input', type=Path, required=True)
    sign.add_argument('--output', type=Path, required=True)
    sign.add_argument('--identity', help='Local keychain identity for manual verification')
    sign.add_argument('--notary-key', type=Path, help='Existing local API key; never copied')
    verify = commands.add_parser('verify-install')
    verify.add_argument('--prefix', type=Path, required=True)
    args = parser.parse_args()
    try:
        names = ['APPLE_TEAM_ID']
        if args.command == 'sign':
            names += ['NOTARY_API_KEY_ID', 'NOTARY_API_ISSUER_ID']
        configuration = {name: os.environ[name] for name in names}
        if args.command == 'verify-install':
            verify_install(args.prefix, configuration['APPLE_TEAM_ID'])
        else:
            if bool(args.identity) != bool(args.notary_key):
                raise ReleaseError('Local signing requires both --identity and --notary-key.')
            credentials = SigningCredentials(None, args.identity, args.notary_key) if args.identity else None
            sign_bottle(args.input, args.output, configuration, credentials)
        return 0
    except (ReleaseError, OSError, ValueError, KeyError, tarfile.TarError) as error:
        print(f'error: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
