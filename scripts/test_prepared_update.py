import base64
import contextlib
import io
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import prepared_update as discovery


def formula(tag):
    return dict(content=base64.b64encode(
        f'class Privateheaderkit < Formula\n  url "https://github.com/lynnswap/PrivateHeaderKit/archive/refs/tags/{tag}.tar.gz"\nend\n'.encode()
    ).decode())


class FakeGitHub:
    repository = "lynnswap/PrivateHeaderKit"
    def __init__(self, tag="v0.7.0", tags=None, pulls=None):
        self.formula = formula(tag)
        self.tags = tags or ["v0.7.1"]
        self.pulls = pulls or []
        self.calls = []

    def api(self, path):
        self.calls.append(path)
        if path.startswith("contents/"):
            return self.formula
        if path == "git/matching-refs/tags/v":
            return [dict(ref="refs/tags/" + tag) for tag in self.tags]
        raise AssertionError(path)

    def pages(self, path):
        self.calls.append(path)
        if path.startswith("pulls?"):
            return self.pulls
        return [dict(filename="Formula/privateheaderkit.rb", status="modified")]


def candidate(tap, source):
    return discovery.candidate(tap, source, "Formula/privateheaderkit.rb")


class PreparedUpdateTests(unittest.TestCase):
    def test_public_tag_can_be_proposed_before_stable_release_exists(self):
        tap, source = FakeGitHub(), FakeGitHub()
        value = candidate(tap, source)
        self.assertTrue(value["update"])
        self.assertEqual(value["latest"], "v0.7.1")
        self.assertEqual(source.calls, ["git/matching-refs/tags/v"])

    def test_current_formula_and_older_tags_do_not_start_writer(self):
        for tags in (["v0.7.0"], ["v0.6.0"], ["v0.8.0-beta.1", "v0.7.0"]):
            with self.subTest(tags=tags):
                tap = FakeGitHub()
                self.assertFalse(candidate(tap, FakeGitHub(tags=tags))["update"])
                self.assertNotIn("pulls?state=open&base=main", tap.calls)

    def test_tag_order_is_semantic_and_prereleases_are_excluded(self):
        source = FakeGitHub(tags=["v0.9.0", "v0.10.0", "v9.0.0-rc.1", "dev"])
        self.assertEqual(candidate(FakeGitHub(), source)["latest"], "v0.10.0")

    def test_existing_latest_proposal_waits_for_review_without_starting_writer(self):
        pull = dict(number=18, head=dict(sha="a" * 40, repo=dict(full_name="lynnswap/homebrew-tap")))
        with patch.object(discovery, "GitHub", return_value=FakeGitHub(tag="v0.7.1")):
            value = candidate(FakeGitHub(pulls=[pull]), FakeGitHub())
        self.assertFalse(value["update"])
        self.assertEqual(value["pull_request"], 18)

    def test_older_proposal_does_not_hide_a_newer_tag(self):
        pull = dict(number=18, head=dict(sha="a" * 40, repo=dict(full_name="lynnswap/homebrew-tap")))
        with patch.object(discovery, "GitHub", return_value=FakeGitHub(tag="v0.7.1")):
            value = candidate(FakeGitHub(pulls=[pull]), FakeGitHub(tags=["v0.7.2"]))
        self.assertTrue(value["update"])

    def test_unrelated_source_recipe_does_not_block_discovery(self):
        pull = dict(number=18, head=dict(sha="a" * 40, repo=dict(full_name="lynnswap/homebrew-tap")))
        proposed = FakeGitHub()
        proposed.formula = dict(content=base64.b64encode(
            '  url "https://github.com/lynnswap/PrivateHeaderKit/archive/refs/tags/v0.7.0.zip"\n'.encode()).decode())
        with patch.object(discovery, "GitHub", return_value=proposed):
            self.assertTrue(candidate(FakeGitHub(pulls=[pull]), FakeGitHub())["update"])

    def test_deleted_proposal_repository_does_not_block_discovery(self):
        pull = dict(number=18, head=dict(sha="a" * 40, repo=None))
        self.assertTrue(candidate(FakeGitHub(pulls=[pull]), FakeGitHub())["update"])

    def test_formula_removal_is_not_an_existing_source_proposal(self):
        tap = FakeGitHub(pulls=[dict(number=18)])
        original_pages = tap.pages
        tap.pages = lambda path: ([dict(filename="Formula/privateheaderkit.rb", status="removed")]
                                 if path.endswith("/files") else original_pages(path))
        self.assertTrue(candidate(tap, FakeGitHub())["update"])

    def test_invalid_encoded_or_binary_proposals_do_not_block_discovery(self):
        pull = dict(number=18, head=dict(sha="a" * 40, repo=dict(full_name="lynnswap/homebrew-tap")))
        for content in ("A", base64.b64encode(b"\xff").decode()):
            proposed = FakeGitHub()
            proposed.formula = dict(content=content)
            with patch.object(discovery, "GitHub", return_value=proposed):
                self.assertTrue(candidate(FakeGitHub(pulls=[pull]), FakeGitHub())["update"])

    def test_large_matching_namespace_keeps_the_highest_stable_tag(self):
        tags = [f"v0.{version}.0" for version in range(201)]
        source = FakeGitHub(tags=tags)
        self.assertEqual(candidate(FakeGitHub(), source)["latest"], "v0.200.0")

    def test_binary_published_formula_is_still_reported_as_an_error(self):
        tap = FakeGitHub()
        tap.formula = dict(content=base64.b64encode(b"\xff").decode())
        with self.assertRaises(discovery.CandidateError):
            candidate(tap, FakeGitHub())

    def test_non_file_proposals_are_not_source_updates(self):
        pull = dict(number=18, head=dict(sha="a" * 40, repo=dict(full_name="lynnswap/homebrew-tap")))
        entries = [dict(type="symlink", target="missing.rb"), dict(type="submodule"), [], dict(content=None)]
        for entry in entries:
            proposed = FakeGitHub()
            proposed.formula = entry
            with patch.object(discovery, "GitHub", return_value=proposed):
                self.assertTrue(candidate(FakeGitHub(pulls=[pull]), FakeGitHub())["update"])
            tap = FakeGitHub()
            tap.formula = entry
            with self.assertRaises(discovery.CandidateError):
                candidate(tap, FakeGitHub())

    def test_unrelated_pr_does_not_read_or_evaluate_its_formula(self):
        pull = dict(number=7)
        tap = FakeGitHub(pulls=[pull])
        original_pages = tap.pages
        tap.pages = lambda path: ([dict(filename="README.md")] if path.endswith("/files") else original_pages(path))
        self.assertTrue(candidate(tap, FakeGitHub())["update"])

    def test_invalid_formula_and_api_failures_are_not_reported_as_no_update(self):
        self.assertIsNone(discovery.source_tag(formula("v0.7.1-beta.1"), "lynnswap/PrivateHeaderKit"))
        tap = FakeGitHub()
        with patch.object(tap, "api", side_effect=discovery.CandidateError("Forbidden")):
            with self.assertRaisesRegex(discovery.CandidateError, "Forbidden"):
                candidate(tap, FakeGitHub())


class MultipleToolDiscoveryTests(unittest.TestCase):
    def test_plain_service_tags_are_detected_and_legacy_tags_are_ignored(self):
        source = FakeGitHub(tags=["custom-v9.0.0", "v0.3.0", "v0.4.0-beta.1"])
        source.repository = "lynnswap/PrivateHeaderKit"
        tap = FakeGitHub()
        tap.formula = dict(content=base64.b64encode(
            b'  url "https://github.com/lynnswap/PrivateHeaderKit/archive/refs/tags/v0.2.7.tar.gz"\n').decode())
        value = discovery.candidate(tap, source, "Formula/privateheaderkit.rb")
        self.assertTrue(value["update"])
        self.assertEqual(value["latest"], "v0.3.0")

    def test_first_recipe_can_be_added_after_the_source_release(self):
        tap = FakeGitHub()
        tap.api = lambda path: [dict(path="Formula/privateheaderkit.rb")]
        with patch.object(discovery, "GitHub") as github, patch.object(discovery, "candidate", return_value=dict(update=False)) as check:
            self.assertFalse(discovery.candidates(tap)["update"])
            github.assert_called_once_with("lynnswap/PrivateHeaderKit")
            self.assertEqual(check.call_args.args[2], "Formula/privateheaderkit.rb")

    def test_one_tool_update_starts_maintenance_for_the_configured_tools(self):
        tap = FakeGitHub()
        tap.api = lambda path: [dict(path=name) for name in discovery.SOURCES]
        with patch.object(discovery, "GitHub"), patch.object(discovery, "candidate", return_value=dict(update=True)):
            result = discovery.candidates(tap)
            self.assertTrue(result["update"])
            self.assertEqual(set(result["formulae"]), set(discovery.SOURCES))


class SourceNotificationTests(unittest.TestCase):
    def setUp(self):
        self.tap = FakeGitHub()
        self.tap.formula = dict(content=base64.b64encode(
            b'  url "https://github.com/lynnswap/PrivateHeaderKit/archive/refs/tags/v0.3.3.tar.gz"\n').decode())
        self.source = FakeGitHub(tags=["v0.3.4"])
        self.source.repository = "lynnswap/PrivateHeaderKit"

    def test_registered_public_stable_tag_starts_an_immediate_update(self):
        with patch.object(discovery, "GitHub", return_value=self.source) as github:
            result = discovery.notified_candidate(self.tap, self.source.repository, "v0.3.4")
        github.assert_called_once_with("lynnswap/PrivateHeaderKit")
        self.assertTrue(result["update"])
        self.assertTrue(result["priority_update"])
        self.assertEqual(set(result["formulae"]), {"Formula/privateheaderkit.rb"})

    def test_unregistered_source_and_unstable_or_missing_tags_never_access_source(self):
        for repo, tag in (("other/project", "v0.3.4"), ("lynnswap/swift-build", "v0.4.0"), ("lynnswap/PrivateHeaderKit", "v0.3.5-rc.1"),
                          ("lynnswap/PrivateHeaderKit", "custom-v0.3.4"), ("lynnswap/PrivateHeaderKit", None)):
            with self.subTest(repo=repo, tag=tag), patch.object(discovery, "GitHub") as github:
                with self.assertRaises(discovery.CandidateError):
                    discovery.notified_candidate(self.tap, repo, tag)
                github.assert_not_called()

    def test_missing_public_tag_and_api_failures_do_not_enable_priority_updates(self):
        with patch.object(discovery, "GitHub", return_value=self.source):
            with self.assertRaisesRegex(discovery.CandidateError, "not public"):
                discovery.notified_candidate(self.tap, self.source.repository, "v0.3.5")
            with patch.object(self.source, "api", side_effect=discovery.CandidateError("Forbidden")):
                with self.assertRaisesRegex(discovery.CandidateError, "Forbidden"):
                    discovery.notified_candidate(self.tap, self.source.repository, "v0.3.4")

    def test_repeated_notification_of_an_already_published_formula_does_not_start_writer(self):
        self.tap.formula = dict(content=base64.b64encode(
            b'  url "https://github.com/lynnswap/PrivateHeaderKit/archive/refs/tags/v0.3.4.tar.gz"\n').decode())
        with patch.object(discovery, "GitHub", return_value=self.source):
            self.assertFalse(discovery.notified_candidate(self.tap, self.source.repository, "v0.3.4")["update"])

    def test_cli_emits_priority_only_after_public_tag_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "outputs"
            args = ["prepared_update", "--repo", "lynnswap/homebrew-tap", "--source-repository",
                    "lynnswap/PrivateHeaderKit", "--source-tag", "v0.3.4", "--github-output", str(output)]
            with patch("sys.argv", args), patch.object(discovery, "GitHub", side_effect=[self.tap, self.source]), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(discovery.main(), 0)
            self.assertEqual(output.read_text(), "update=true\npriority_update=true\n")
            output.unlink()
            self.source.tags = []
            with patch("sys.argv", args), patch.object(discovery, "GitHub", side_effect=[self.tap, self.source]), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(discovery.main(), 1)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
