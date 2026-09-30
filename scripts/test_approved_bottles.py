import contextlib
import copy
import io
import json
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
