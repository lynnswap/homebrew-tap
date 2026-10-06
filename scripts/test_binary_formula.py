import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from approved_bottles import CandidateError
import binary_formula
import dispatched_ci
from test_dispatched_ci import FakeNative, SHA
from test_update_formula import BinarySource, TAG, SOURCE_DIGEST


class BinaryTap(FakeNative):
    def __init__(self):
        super().__init__()
        self.pull["head"]["ref"] = "codex/release-custom-xcode-build-service-v1.2.3"
        self.files = [dict(filename=binary_formula.BINARY_FORMULA, status="modified")]
        self.merge_success = True

    def api(self, path, method="GET", data=None):
        if path == "pulls/3/merge" and method == "PUT":
            self.writes.append((path, data))
            if self.merge_success and self.pull["head"]["sha"] == data["sha"]:
                self.pull.update(merged=True, state="closed")
                return dict(merged=True, sha="f" * 40)
            return dict(merged=False, message="Head changed before merge.")
        return super().api(path, method, data)


class BinaryFormulaTests(unittest.TestCase):
    def test_binary_updates_do_not_start_bottle_ci_or_bottle_publication(self):
        tap = BinaryTap()
        self.assertEqual(dispatched_ci.dispatch(tap)[0]["status"], "upstream-binary-update")
        self.assertEqual(tap.writes, [])

    def test_merge_is_bound_to_the_tested_head_and_retries_do_not_remerge(self):
        tap = BinaryTap()
        self.assertEqual(binary_formula.merge(tap, 3, SHA)["status"], "merged")
        self.assertEqual(tap.writes, [("pulls/3/merge", dict(sha=SHA, merge_method="merge"))])
        self.assertEqual(binary_formula.merge(tap, 3, SHA)["status"], "already-merged")
        self.assertEqual(len(tap.writes), 1)

    def test_changed_head_fork_or_extra_files_cannot_merge(self):
        for mutation in (lambda t: t.pull["head"].update(sha="c" * 40),
                         lambda t: t.pull["head"]["repo"].update(full_name="someone/tap"),
                         lambda t: t.files.append(dict(filename="Formula/privateheaderkit.rb", status="modified"))):
            tap = BinaryTap()
            mutation(tap)
            with self.subTest(mutation=mutation), self.assertRaises(CandidateError):
                binary_formula.merge(tap, 3, SHA)
            self.assertEqual(tap.writes, [])

    def test_a_merge_rejected_after_validation_is_reported(self):
        tap = BinaryTap()
        tap.merge_success = False
        with self.assertRaisesRegex(CandidateError, "Head changed"):
            binary_formula.merge(tap, 3, SHA)
        self.assertEqual(len(tap.writes), 1)

    def test_install_checks_the_public_archive_and_installed_manifest(self):
        source = BinarySource()
        asset = source.release["assets"][0]
        info = dict(versions=dict(stable="1.2.3"), urls=dict(stable=dict(
            url=asset["browser_download_url"], checksum=SOURCE_DIGEST)))
        for corruption in (None, "checksum", "manifest"):
            with self.subTest(corruption=corruption), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "libexec").mkdir()
                (root / "libexec/manifest.json").write_text(json.dumps(dict(
                    version=TAG, sourceRevision="b" * 40 if corruption == "manifest" else SHA)))
                metadata = copy.deepcopy(info)
                if corruption == "checksum":
                    metadata["urls"]["stable"]["checksum"] = "0" * 64
                commands = []
                def run(command, **kwargs):
                    commands.append(command)
                    output = ""
                    if command[0:3] == ["brew", "info", "--json=v2"]:
                        output = json.dumps(dict(formulae=[metadata]))
                    elif command[0:2] == ["brew", "--prefix"]:
                        output = str(root)
                    return subprocess.CompletedProcess(command, 0, stdout=output)
                with patch.object(binary_formula, "GitHub", return_value=source), \
                        patch.object(binary_formula.subprocess, "check_output", return_value=SHA), \
                        patch.object(binary_formula.subprocess, "run", side_effect=run):
                    if corruption:
                        with self.assertRaises(CandidateError):
                            binary_formula.verify(BinaryTap(), 3, SHA, root)
                    else:
                        binary_formula.verify(BinaryTap(), 3, SHA, root)
                installs = [command for command in commands if command[0:2] == ["brew", "install"]]
                self.assertEqual(bool(installs), corruption != "checksum")
                self.assertFalse(any("bottle" in command for command in commands))

    def test_release_dispatched_installation_keeps_the_requested_tag_and_commit(self):
        for mismatch in (None, "tag", "commit"):
            with self.subTest(mismatch=mismatch), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = BinarySource()
                item = source.release
                if mismatch == "commit":
                    item["target_commitish"] = "b" * 40
                (root / "libexec").mkdir()
                (root / "libexec/manifest.json").write_text(json.dumps(dict(
                    version=TAG, sourceRevision=item["target_commitish"])))
                metadata = dict(versions=dict(stable="1.2.3"), urls=dict(stable=dict(
                    url=item["assets"][0]["browser_download_url"], checksum=SOURCE_DIGEST)))
                commands = []
                def run(command, **kwargs):
                    commands.append(command)
                    output = ""
                    if command[0:3] == ["brew", "info", "--json=v2"]:
                        output = json.dumps(dict(formulae=[metadata]))
                    elif command[0:2] == ["brew", "--prefix"]:
                        output = str(root)
                    return subprocess.CompletedProcess(command, 0, stdout=output)
                with patch.object(binary_formula, "GitHub", return_value=source), \
                        patch.object(binary_formula.subprocess, "check_output", return_value=SHA), \
                        patch.object(binary_formula.subprocess, "run", side_effect=run):
                    def verify():
                        binary_formula.verify(BinaryTap(), 3, SHA, root,
                                              source_tag="v1.3.0" if mismatch == "tag" else TAG,
                                              source_sha=SHA)
                    if mismatch:
                        with self.assertRaisesRegex(CandidateError, "requested release|approved commit"):
                            verify()
                    else:
                        verify()
                self.assertEqual(any(command[0:2] == ["brew", "install"] for command in commands), mismatch is None)


if __name__ == "__main__":
    unittest.main()
