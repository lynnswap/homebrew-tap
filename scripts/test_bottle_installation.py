"""Exercise workflow artifact selection when both native Formulae share an artifact."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest


class BottleInstallationTests(unittest.TestCase):
    def test_signed_bottle_command_checks_accept_current_and_legacy_layouts(self):
        workflow = (Path(__file__).resolve().parents[1]/'.github/workflows/publish.yml').read_text()
        commands = re.search(r'--prefix "\$prefix"\n(.*?)^          if \[\[ "\$RUN_NATIVE_SMOKE"',
                             workflow, re.MULTILINE | re.DOTALL)[1]
        for legacy, server in ((False, True), (True, True), (True, False)):
            with self.subTest(legacy=legacy, server=server), tempfile.TemporaryDirectory(prefix='signed commands ') as directory:
                prefix = Path(directory)
                (prefix/'bin').mkdir()
                for name, present in (('xcode-mcp-proxy', legacy), ('xcode-mcp-proxy-server', server)):
                    if not present:
                        continue
                    executable = prefix/'bin'/name
                    executable.write_text('#!/bin/sh\nprintf "%s\\n" "' + name + ' $*" >> "$COMMAND_LOG"\n'
                                          'case "$1" in\n  --version) echo v0.23.0;;\n'
                                          '  --host) echo "xcode-mcp-proxy-server --listen 127.0.0.1:0";;\n'
                                          '  *) exit 64;;\nesac\n')
                    executable.chmod(0o755)
                log = prefix/'calls'
                env = dict(os.environ, prefix=str(prefix), version='0.23.0', COMMAND_LOG=str(log))
                result = subprocess.run(['bash', '-eu', '-c', textwrap.dedent(commands)],
                                        env=env, capture_output=True, text=True)
                if not server:
                    self.assertNotEqual(result.returncode, 0)
                    continue
                self.assertEqual(result.returncode, 0, result.stderr)
                expected = ['xcode-mcp-proxy-server --version']
                if legacy:
                    expected.append('xcode-mcp-proxy --version')
                calls = log.read_text().splitlines()
                self.assertCountEqual(calls[:-1], expected)
                self.assertEqual(calls[-1], 'xcode-mcp-proxy-server --host 127.0.0.1 --port 0 --dry-run')

    def test_each_installation_job_selects_only_its_own_bottle_and_recipe(self):
        for workflow_name, job, name in (("tests.yml", "install-xcodemcpkit", "xcode-mcpkit"),
                                         ("publish.yml", "verify-signed-xcodemcpkit", "xcode-mcpkit")):
            workflow = (Path(__file__).resolve().parents[1]/".github/workflows"/workflow_name).read_text()
            with self.subTest(job=job), tempfile.TemporaryDirectory(prefix="bottle selection ") as directory:
                root = Path(directory)
                bottles = root/"bottles"
                bottles.mkdir()
                for formula in ("privateheaderkit", "xcode-mcpkit"):
                    (bottles/f"{formula}--1.2.3.arm64_tahoe.bottle.tar.gz").write_text(formula)
                    (bottles/f"{formula}--1.2.3.arm64_tahoe.bottle.json").write_text("{}")
                bin_dir = root/"bin"
                bin_dir.mkdir()
                brew = bin_dir/"brew"
                brew.write_text(f"#!{sys.executable}\nimport json, os, pathlib, sys\n"
                                "pathlib.Path(os.environ['BREW_CALLS']).write_text(json.dumps(sys.argv[1:]))\n")
                brew.chmod(0o755)
                body = re.search(rf"^  {job}:\n(.*?)(?=^  [a-z][\w-]*:|\Z)", workflow, re.MULTILINE | re.DOTALL)[1]
                commands = [line.strip() for line in body.splitlines()
                            if line.strip().startswith(('brew bottle --merge', 'cp "$RUNNER_TEMP/bottles/'))]
                self.assertEqual(len(commands), 2)
                cache = root/"cached bottle.tar.gz"
                env = dict(os.environ, PATH=str(bin_dir) + os.pathsep + os.environ["PATH"],
                           RUNNER_TEMP=str(root), cache=str(cache), BREW_CALLS=str(root/"calls"))
                subprocess.run(["bash", "-eu", "-c", "\n".join(commands)], env=env,
                               capture_output=True, text=True, check=True)
                self.assertEqual(cache.read_text(), name)
                files = [value for value in json.loads((root/"calls").read_text()) if value.endswith(".bottle.json")]
                self.assertEqual(files, [str(bottles/f"{name}--1.2.3.arm64_tahoe.bottle.json")])


if __name__ == "__main__":
    unittest.main()
