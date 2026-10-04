import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import dispatched_ci as ci
from test_approved_bottles import FakeGitHub, SHA


class FakeNative(FakeGitHub):
    def __init__(self):
        super().__init__()
        self.pull.update(number=3, user=dict(login="github-actions[bot]"))
        self.pull["head"].update(ref="renovate/privateheaderkit", repo=dict(full_name=self.repository))
        self.runs = []
        self.writes = []
        self.publications = []
        self.publication_jobs = []
        self.logs = ""

    def job_log(self, job_id):
        return self.logs

    def pages(self, path, field=None):
        if path == "pulls?state=open&base=main":
            return [copy.deepcopy(self.pull)]
        if path == "actions/workflows/41/runs":
            return copy.deepcopy(self.publications)
        if path == "actions/runs/101/jobs":
            return copy.deepcopy(self.publication_jobs)
        return super().pages(path, field)

    def api(self, path, method="GET", data=None):
        if method == "POST":
            self.writes.append((path, data))
            return None
        if path == "actions/workflows/publish.yml":
            return dict(id=41)
        return super().api(path)


class DispatchedCITests(unittest.TestCase):
    def test_explicit_dispatch_does_not_adopt_a_head_that_changes_between_reads(self):
        github = FakeNative()
        original = github.api
        reads = 0
        def api(path, method="GET", data=None):
            nonlocal reads
            if path == "pulls/3":
                reads += 1
                if reads == 2:
                    github.pull["head"]["sha"] = "b" * 40
            return original(path, method, data)
        github.api = api
        with self.assertRaises(ci.CandidateError):
            ci.dispatch(github, number=3, head_sha=SHA)
        self.assertEqual(github.writes, [])

    def test_direct_release_proposal_uses_the_existing_pinned_bottle_ci(self):
        github = FakeNative()
        github.pull["head"]["ref"] = "codex/release-xcode-mcpkit-v1.2.3"
        github.files = [dict(filename="Formula/xcode-mcpkit.rb", status="added")]
        self.assertEqual(ci.dispatch(github, number=3, head_sha=SHA)[0]["status"], "dispatched")
        self.assertEqual(github.writes[0][1]["inputs"], dict(pull_request="3", head_sha=SHA))
        with self.assertRaises(ci.CandidateError):
            ci.dispatch(github, number=3, head_sha="b" * 40)

    def test_native_proposal_gets_trusted_main_dispatch_with_pinned_inputs(self):
        github = FakeNative()
        self.assertEqual(ci.dispatch(github)[0]["status"], "dispatched")
        self.assertEqual(github.writes, [("actions/workflows/40/dispatches",
                                         dict(ref="main", inputs=dict(pull_request="3", head_sha=SHA)))])

    def test_active_successful_and_real_failed_ci_are_not_repeated(self):
        for status, conclusion in (("queued", None), ("in_progress", None), ("completed", "failure")):
            github = FakeNative()
            github.runs = [dict(github.run, status=status, conclusion=conclusion)]
            self.assertEqual(ci.dispatch(github)[0]["status"], "existing-ci")
            self.assertEqual(github.writes, [])

    def test_approval_required_native_event_uses_dispatch_and_dry_run_does_not_write(self):
        github = FakeNative()
        github.runs = [dict(github.run, conclusion="action_required")]
        self.assertEqual(ci.dispatch(github, dry_run=True)[0]["status"], "ready")
        self.assertEqual(github.writes, [])
        self.assertEqual(ci.dispatch(github)[0]["status"], "dispatched")

    def test_forks_non_native_workflow_changes_and_changed_heads_cannot_dispatch(self):
        changes = [lambda g: g.pull["head"]["repo"].update(full_name="other/tap"),
                   lambda g: g.files.append(dict(filename=".github/workflows/tests.yml", status="modified")),
                   lambda g: g.pull["head"].update(sha="b" * 40)]
        for change in changes:
            github = FakeNative()
            change(github)
            with self.assertRaises(ci.CandidateError):
                ci.native_proposal(github, 3, SHA)
            self.assertEqual(github.writes, [])

    def test_fetched_sha_is_checked_before_checkout(self):
        github = FakeNative()
        with patch.object(ci.subprocess, "run") as run, patch.object(ci.subprocess, "check_output", return_value="b" * 40):
            with self.assertRaises(ci.CandidateError):
                ci.prepare(github, 3, SHA, Path("/tap"))
        self.assertEqual(len(run.call_args_list), 1)
        self.assertIn("fetch", run.call_args_list[0].args[0])

    def test_draft_proposal_does_not_block_another_ready_proposal(self):
        github = FakeNative()
        draft = dict(copy.deepcopy(github.pull), number=4, draft=True)
        pages, api = github.pages, github.api
        github.pages = lambda path, field=None: [draft, github.pull] if path == "pulls?state=open&base=main" else pages(path, field)
        github.api = lambda path, method="GET", data=None: draft if path == "pulls/4" else api(path, method, data)
        self.assertEqual([item["status"] for item in ci.dispatch(github)], ["ineligible", "dispatched"])
        self.assertEqual(len(github.writes), 1)
        self.assertEqual(github.writes[0][1]["inputs"]["pull_request"], "3")

    def test_successful_ci_starts_missing_publication_without_rebuilding(self):
        github = FakeNative()
        github.runs = [github.run]
        self.assertEqual(ci.dispatch(github, dry_run=True)[0]["status"], "publication-ready")
        self.assertEqual(github.writes, [])
        self.assertEqual(ci.dispatch(github)[0]["status"], "publication-dispatched")
        self.assertEqual(github.writes[0][0], "actions/workflows/41/dispatches")

    def test_pending_completed_or_failed_publication_does_not_repeat_approval(self):
        for status, conclusion in (("waiting", None), ("completed", "success"), ("completed", "failure")):
            github = FakeNative()
            github.runs = [github.run]
            github.publications = [dict(id=101, workflow_id=41, head_branch="main", status=status,
                                       conclusion=conclusion, display_title=f"Publish bottles for PR 3 at {SHA}")]
            github.publication_jobs = [dict(name="pr-pull", conclusion="success")]
            self.assertEqual(ci.dispatch(github)[0]["status"], "existing-publication")
            self.assertEqual(github.writes, [])

    def test_skipped_completion_event_does_not_hide_later_successful_bottle_ci(self):
        github = FakeNative()
        github.runs = [github.run]
        github.publications = [dict(id=101, workflow_id=41, head_branch="main", status="completed",
                                   conclusion="success", display_title="Publish bottles from CI 100 attempt 1")]
        github.publication_jobs = [dict(name="pr-pull", conclusion="skipped")]
        self.assertEqual(ci.dispatch(github)[0]["status"], "publication-dispatched")

    def test_legacy_publication_is_identified_from_its_trusted_validation_log(self):
        for status, conclusion in (("waiting", None), ("completed", "failure")):
            github = FakeNative()
            github.runs = [github.run]
            github.publications = [dict(id=101, workflow_id=41, head_branch="main", status=status,
                                       conclusion=conclusion, display_title="brew pr-pull",
                                       created_at="2026-10-01T00:00:01Z")]
            github.publication_jobs = [dict(id=11, name="validate", status="completed", conclusion="success"),
                                       dict(name="pr-pull", conclusion=conclusion)]
            value = dict(repository=github.repository, pull_request=3, head_sha=SHA, ci_run_id=100, artifact_digest="sha256:x")
            github.logs = "2026-10-01T00:00:00Z " + json.dumps(value)
            self.assertEqual(ci.dispatch(github)[0]["status"], "existing-publication")
            self.assertEqual(github.writes, [])
            value["pull_request"] = 4
            github.logs = "2026-10-01T00:00:00Z " + json.dumps(value)
            self.assertEqual(ci.dispatch(github)[0]["status"], "publication-dispatched")

    def test_added_and_modified_formulae_preserve_native_classification(self):
        github = FakeNative()
        github.files.append(dict(filename="Formula/new-tool.rb", status="added"))
        with patch.object(ci.subprocess, "run"), patch.object(ci.subprocess, "check_output", return_value=SHA):
            self.assertEqual(ci.prepare(github, 3, SHA, Path("/tap")), dict(
                formulae=["lynnswap/tap/privateheaderkit", "lynnswap/tap/new-tool"],
                added_formulae=["lynnswap/tap/new-tool"]))


if __name__ == "__main__":
    unittest.main()
