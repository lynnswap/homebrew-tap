import unittest

from approved_bottles import CandidateError
from notify_sources import dispatch, repositories, source_workflow


class GitHubStub:
    def __init__(self, repository, error=None):
        self.repository = repository
        self.error = error
        self.calls = []

    def api(self, path, method="GET", data=None):
        self.calls.append((path, method, data))
        if self.error:
            raise self.error


class SourceNotificationTests(unittest.TestCase):
    def test_only_published_registered_formulae_select_notification_repositories(self):
        self.assertEqual(repositories([
            "Formula/xcode-mcpkit.rb", "Formula/custom-xcode-build-service.rb",
            "Formula/unrelated.rb", "README.md", "Formula/xcode-mcpkit.rb",
        ]), ["lynnswap/XcodeMCPKit"])
        self.assertEqual(repositories(["Formula/unrelated.rb", "Formula/custom-xcode-build-service.rb"]), [])

    def test_each_source_dispatches_its_existing_resume_workflow_on_main(self):
        for repository, workflow in (
            ("lynnswap/XcodeMCPKit", "resume-release.yml"),
            ("lynnswap/PrivateHeaderKit", "resume-release.yml"),
        ):
            with self.subTest(repository=repository):
                github = GitHubStub(repository)
                self.assertEqual(source_workflow(repository)["repository"], repository.split("/")[1])
                self.assertEqual(dispatch(github)["status"], "dispatched")
                self.assertEqual(github.calls, [
                    (f"actions/workflows/{workflow}/dispatches", "POST", dict(ref="main")),
                ])

    def test_unknown_destinations_are_rejected_before_dispatch(self):
        github = GitHubStub("someone/PrivateHeaderKit")
        with self.assertRaises(CandidateError):
            dispatch(github)
        self.assertEqual(github.calls, [])
        with self.assertRaises(CandidateError):
            source_workflow("lynnswap/unregistered")

    def test_notification_failure_is_reported_without_republishing_bottles(self):
        github = GitHubStub("lynnswap/XcodeMCPKit", CandidateError("dispatch unavailable"))
        with self.assertRaisesRegex(CandidateError, "dispatch unavailable"):
            dispatch(github)
        self.assertEqual(github.calls, [
            ("actions/workflows/resume-release.yml/dispatches", "POST", dict(ref="main")),
        ])


if __name__ == "__main__":
    unittest.main()
