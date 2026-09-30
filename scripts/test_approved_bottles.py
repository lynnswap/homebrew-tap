import contextlib
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import approved_bottles as guard

SHA = "a" * 40


class FakeGitHub:
    repository = "lynnswap/homebrew-tap"

    def __init__(self):
        self.pull = {"state": "open", "draft": False, "base": {"ref": "main"}, "head": {"sha": SHA}}
        self.files = [{"filename": "Formula/privateheaderkit.rb", "status": "modified"}]
        self.run = {"id": 100, "run_attempt": 1, "workflow_id": 40, "head_sha": SHA,
                    "event": "pull_request", "status": "completed", "conclusion": "success",
                    "pull_requests": [{"number": 3}]}
        self.runs = [self.run]
        self.artifacts = [{"id": 7, "name": "bottles_macos-arm64_100_1", "expired": False,
                           "digest": "sha256:" + "c" * 64}]
        self.calls = []
        self.associated = [dict(self.pull, number=3)]

    def api(self, path):
        self.calls.append(path)
        if path == "pulls/3":
            return copy.deepcopy(self.pull)
        if path == "actions/workflows/tests.yml":
            return {"id": 40}
        if path.startswith("actions/workflows/40/runs?"):
            return {"workflow_runs": copy.deepcopy(self.runs)}
        if path == "actions/runs/100":
            return copy.deepcopy(self.run)
        raise AssertionError(path)

    def pages(self, path, field=None):
        self.calls.append(path)
        if path == "pulls/3/files":
            return copy.deepcopy(self.files)
        if path == "actions/runs/100/artifacts" and field == "artifacts":
            return copy.deepcopy(self.artifacts)
        if path == f"commits/{SHA}/pulls":
            return copy.deepcopy(self.associated)
        raise AssertionError((path, field))


class ApprovedBottlesTests(unittest.TestCase):
    def test_candidate_pins_reviewed_head_and_exact_tested_artifact(self):
        github = FakeGitHub()
        value = guard.candidate(github, 3, SHA)
        self.assertEqual(value, {
            "repository": github.repository, "pull_request": 3, "head_sha": SHA,
            "ci_run_id": 100, "ci_attempt": 1, "artifact_id": 7,
            "artifact_name": "bottles_macos-arm64_100_1", "artifact_digest": "sha256:" + "c" * 64,
        })
        guard.verify_approved(value, guard.fingerprint(value))

    def test_unrelated_pr_metadata_does_not_change_publication_identity(self):
        github = FakeGitHub()
        value = guard.candidate(github, 3, SHA)
        github.pull.update(title="Edited title", body="Edited discussion")
        guard.verify_approved(guard.candidate(github, 3, SHA), guard.fingerprint(value))

    def test_changed_head_or_non_formula_files_cannot_publish(self):
        changes = [
            lambda g: g.pull["head"].update(sha="b" * 40),
            lambda g: g.pull.update(draft=True),
            lambda g: g.pull.update(state="closed"),
            lambda g: g.pull["base"].update(ref="other"),
            lambda g: g.files.append({"filename": ".github/workflows/tests.yml", "status": "modified"}),
            lambda g: g.files[0].update(status="removed"),
            lambda g: g.files.clear(),
        ]
        for mutation in changes:
            with self.subTest(mutation=mutation):
                github = FakeGitHub()
                mutation(github)
                with self.assertRaises(guard.CandidateError):
                    guard.candidate(github, 3, SHA)

    def test_failed_incomplete_or_unrelated_ci_cannot_publish(self):
        changes = [
            lambda g: g.runs.clear(),
            lambda g: g.run.update(status="in_progress", conclusion=None),
            lambda g: g.run.update(conclusion="failure"),
            lambda g: g.run.update(head_sha="b" * 40),
            lambda g: g.run.update(workflow_id=99),
            lambda g: g.run.update(event="push"),
            lambda g: g.run.update(pull_requests=[{"number": 9}]),
        ]
        for mutation in changes:
            with self.subTest(mutation=mutation):
                github = FakeGitHub()
                mutation(github)
                with self.assertRaises(guard.CandidateError):
                    guard.candidate(github, 3, SHA)

    def test_older_success_does_not_override_the_latest_failed_run(self):
        github = FakeGitHub()
        old = copy.deepcopy(github.run)
        old["id"] = 99
        github.runs.append(old)
        github.run["conclusion"] = "failure"
        with self.assertRaisesRegex(guard.CandidateError, "latest bottle CI"):
            guard.candidate(github, 3, SHA)

    def test_missing_expired_unhashed_or_duplicate_artifacts_cannot_publish(self):
        changes = [
            lambda g: g.artifacts.clear(),
            lambda g: g.artifacts[0].update(expired=True),
            lambda g: g.artifacts[0].update(digest=None),
            lambda g: g.artifacts[0].update(name="bottles_macos-arm64_100_2"),
            lambda g: g.artifacts.append(copy.deepcopy(g.artifacts[0])),
        ]
        for mutation in changes:
            with self.subTest(mutation=mutation):
                github = FakeGitHub()
                mutation(github)
                with self.assertRaises(guard.CandidateError):
                    guard.candidate(github, 3, SHA)

    def test_changed_artifacts_or_ci_attempt_require_new_approval(self):
        github = FakeGitHub()
        expected = guard.fingerprint(guard.candidate(github, 3, SHA))
        for field, new_value in [("id", 8), ("digest", "sha256:" + "d" * 64)]:
            with self.subTest(field=field):
                github = FakeGitHub()
                github.artifacts[0][field] = new_value
                with self.assertRaisesRegex(guard.CandidateError, "approval was pending"):
                    guard.verify_approved(guard.candidate(github, 3, SHA), expected)
        github = FakeGitHub()
        github.run["run_attempt"] = 2
        github.artifacts[0]["name"] = "bottles_macos-arm64_100_2"
        with self.assertRaises(guard.CandidateError):
            guard.verify_approved(guard.candidate(github, 3, SHA), expected)

    def test_obsolete_completion_event_does_not_select_a_newer_run(self):
        with self.assertRaisesRegex(guard.CandidateError, "newer bottle CI"):
            guard.candidate(FakeGitHub(), 3, SHA, event_run_id=99)

    def test_fork_ci_without_embedded_pr_uses_verified_commit_association(self):
        github = FakeGitHub()
        github.run["pull_requests"] = []
        self.assertEqual(guard.candidate(github, 3, SHA)["pull_request"], 3)
        github.associated[0]["number"] = 9
        with self.assertRaisesRegex(guard.CandidateError, "not associated"):
            guard.candidate(github, 3, SHA)

    def test_fork_completion_can_prepare_an_approval(self):
        github = FakeGitHub()
        github.run["pull_requests"] = []
        with tempfile.TemporaryDirectory() as directory:
            event = Path(directory) / "event.json"
            output = Path(directory) / "output.txt"
            event.write_text(json.dumps({"workflow_run": github.run}))
            args = ["guard", "--repo", github.repository, "--event-file", str(event), "--github-output", str(output)]
            with patch("sys.argv", args), patch.object(guard, "GitHub", return_value=github), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(guard.main(), 0)
            self.assertIn("eligible=true\n", output.read_text())
            self.assertIn("pull_request=3\n", output.read_text())

    def test_non_formula_completion_skips_publication_and_outputs(self):
        github = FakeGitHub()
        github.files = [{"filename": "README.md", "status": "modified"}]
        with tempfile.TemporaryDirectory() as directory:
            event = Path(directory) / "event.json"
            output = Path(directory) / "output.txt"
            event.write_text(json.dumps({"workflow_run": github.run}))
            args = ["guard", "--repo", github.repository, "--event-file", str(event), "--github-output", str(output)]
            with patch("sys.argv", args), patch.object(guard, "GitHub", return_value=github), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(guard.main(), 0)
            self.assertEqual(output.read_text(), "eligible=false\n")
            self.assertNotIn("actions/workflows/tests.yml", github.calls)

    def test_approval_outputs_and_summary_identify_the_tested_candidate(self):
        github = FakeGitHub()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output.txt"
            summary = Path(directory) / "summary.md"
            args = ["guard", "--repo", github.repository, "--pr", "3", "--head", SHA, "--github-output", str(output)]
            with patch("sys.argv", args), patch.object(guard, "GitHub", return_value=github), patch.dict("os.environ", GITHUB_STEP_SUMMARY=str(summary)), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(guard.main(), 0)
            self.assertIn("eligible=true\n", output.read_text())
            self.assertIn("artifact_id=7\n", output.read_text())
            self.assertIn(SHA, summary.read_text())
            self.assertIn("sha256:" + "c" * 64, summary.read_text())

    def test_transport_only_reads_and_preserves_api_errors(self):
        with patch.object(guard.subprocess, "run") as run:
            run.return_value = type("Result", (), {"returncode": 0, "stdout": '{"id": 7}', "stderr": ""})()
            self.assertEqual(guard.GitHub("owner/tap").api("actions/artifacts/7"), {"id": 7})
            self.assertEqual(run.call_args.args[0][1:5], ["api", "--method", "GET", "repos/owner/tap/actions/artifacts/7"])
            run.return_value.returncode = 1
            run.return_value.stderr = "permission denied"
            with self.assertRaisesRegex(guard.CandidateError, "permission denied"):
                guard.GitHub("owner/tap").api("actions/artifacts/7")


class PublishBottlesTests(unittest.TestCase):
    def run_command(self, command, directory, **kwargs):
        return subprocess.run(command, cwd=directory, capture_output=True, text=True, check=True, **kwargs).stdout.strip()

    def prepare_repository(self, directory):
        remote = directory / "remote.git"
        source = directory / "source"
        tap = directory / "tap"
        self.run_command(["git", "init", "--bare", "--initial-branch=main", str(remote)], directory)
        self.run_command(["git", "clone", str(remote), str(source)], directory)
        for key, value in [("user.name", "Fixture"), ("user.email", "fixture@example.test")]:
            self.run_command(["git", "config", key, value], source)
        (source / "Formula").mkdir()
        (source / "Formula/tool.rb").write_text("old formula\n")
        self.run_command(["git", "add", "."], source)
        self.run_command(["git", "commit", "-m", "Initial"], source)
        self.run_command(["git", "push", "origin", "main"], source)
        self.run_command(["git", "switch", "-c", "formula"], source)
        (source / "Formula/tool.rb").write_text("reviewed formula\n")
        self.run_command(["git", "commit", "-am", "Update Formula"], source)
        head = self.run_command(["git", "rev-parse", "HEAD"], source)
        self.run_command(["git", "push", "origin", "HEAD:refs/pull/3/head"], source)
        self.run_command(["git", "switch", "main"], source)
        (source / "README.md").write_text("New main documentation\n")
        self.run_command(["git", "add", "."], source)
        self.run_command(["git", "commit", "-m", "Unrelated main change"], source)
        self.run_command(["git", "push", "origin", "main"], source)
        self.run_command(["git", "clone", str(remote), str(tap)], directory)
        for key, value in [("user.name", "Fixture"), ("user.email", "fixture@example.test")]:
            self.run_command(["git", "config", key, value], tap)
        bottles = directory / "approved-bottles"
        bottles.mkdir()
        (bottles / "tool.bottle.json").write_text("approved metadata")
        binary = directory / "bin"
        binary.mkdir()
        brew = binary / "brew"
        brew.write_text('#!/bin/bash\nset -euo pipefail\n[[ "$*" == "pr-upload --debug" ]]\nprintf "%s\\n" "$PWD" > "$UPLOAD_RECORD"\ncat tool.bottle.json >> "$UPLOAD_RECORD"\n')
        brew.chmod(0o755)
        environment = dict(os.environ, PATH=f"{binary}:{os.environ['PATH']}", UPLOAD_RECORD=str(directory / "upload.txt"))
        return tap, head, bottles, environment

    def test_publication_consumes_verified_local_files_and_preserves_current_main(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            tap, head, bottles, environment = self.prepare_repository(directory)
            script = Path(__file__).with_name("publish_bottles.sh")
            self.run_command(["bash", str(script), "3", head, str(bottles)], tap, env=environment)
            self.assertEqual((tap / "Formula/tool.rb").read_text(), "reviewed formula\n")
            self.assertEqual((tap / "README.md").read_text(), "New main documentation\n")
            self.assertIn("Closes #3.", self.run_command(["git", "log", "-1", "--format=%B"], tap))
            self.assertEqual((directory / "upload.txt").read_text(), f"{bottles}\napproved metadata")

    def test_changed_pr_ref_stops_before_upload_or_local_merge(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            tap, _, bottles, environment = self.prepare_repository(directory)
            original = self.run_command(["git", "rev-parse", "HEAD"], tap)
            result = subprocess.run(["bash", str(Path(__file__).with_name("publish_bottles.sh")), "3", SHA, str(bottles)],
                                    cwd=tap, env=environment, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("head changed after approval", result.stderr)
            self.assertEqual(self.run_command(["git", "rev-parse", "HEAD"], tap), original)
            self.assertFalse((directory / "upload.txt").exists())


if __name__ == "__main__":
    unittest.main()
