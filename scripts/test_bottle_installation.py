"""Exercise workflow artifact selection when both native Formulae share an artifact."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


class BottleInstallationTests(unittest.TestCase):
    def test_each_installation_job_selects_only_its_own_bottle_and_recipe(self):
        workflow = (Path(__file__).resolve().parents[1]/".github/workflows/tests.yml").read_text()
        for job, name in (("install-custom-service", "custom-xcode-build-service"),
                          ("install-xcodemcpkit", "xcode-mcpkit")):
            with self.subTest(job=job), tempfile.TemporaryDirectory(prefix="bottle selection ") as directory:
                root = Path(directory)
                bottles = root/"bottles"
                bottles.mkdir()
                for formula in ("custom-xcode-build-service", "xcode-mcpkit"):
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
