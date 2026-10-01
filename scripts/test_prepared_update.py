import base64
import unittest
from unittest.mock import patch

import prepared_update as discovery


def formula(tag):
    return dict(content=base64.b64encode(
        f'class Privateheaderkit < Formula\n  url "{discovery.SOURCE_PREFIX}{tag}.tar.gz"\nend\n'.encode()
    ).decode())


class FakeGitHub:
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
        return [dict(filename=discovery.FORMULA, status="modified")]


class PreparedUpdateTests(unittest.TestCase):
    def test_public_tag_can_be_proposed_before_stable_release_exists(self):
        tap, source = FakeGitHub(), FakeGitHub()
        value = discovery.candidate(tap, source)
        self.assertTrue(value["update"])
        self.assertEqual(value["latest"], "v0.7.1")
        self.assertEqual(source.calls, ["git/matching-refs/tags/v"])

    def test_current_formula_and_older_tags_do_not_start_writer(self):
        for tags in (["v0.7.0"], ["v0.6.0"], ["v0.8.0-beta.1", "v0.7.0"]):
            with self.subTest(tags=tags):
                tap = FakeGitHub()
                self.assertFalse(discovery.candidate(tap, FakeGitHub(tags=tags))["update"])
                self.assertNotIn("pulls?state=open&base=main", tap.calls)

    def test_tag_order_is_semantic_and_prereleases_are_excluded(self):
        source = FakeGitHub(tags=["v0.9.0", "v0.10.0", "v9.0.0-rc.1", "dev"])
        self.assertEqual(discovery.candidate(FakeGitHub(), source)["latest"], "v0.10.0")

    def test_existing_latest_proposal_waits_for_review_without_starting_writer(self):
        pull = dict(number=18, head=dict(sha="a" * 40, repo=dict(full_name="lynnswap/homebrew-tap")))
        with patch.object(discovery, "GitHub", return_value=FakeGitHub(tag="v0.7.1")):
            value = discovery.candidate(FakeGitHub(pulls=[pull]), FakeGitHub())
        self.assertFalse(value["update"])
        self.assertEqual(value["pull_request"], 18)

    def test_older_proposal_does_not_hide_a_newer_tag(self):
        pull = dict(number=18, head=dict(sha="a" * 40, repo=dict(full_name="lynnswap/homebrew-tap")))
        with patch.object(discovery, "GitHub", return_value=FakeGitHub(tag="v0.7.1")):
            value = discovery.candidate(FakeGitHub(pulls=[pull]), FakeGitHub(tags=["v0.7.2"]))
        self.assertTrue(value["update"])

    def test_unrelated_source_recipe_does_not_block_discovery(self):
        pull = dict(number=18, head=dict(sha="a" * 40, repo=dict(full_name="lynnswap/homebrew-tap")))
        proposed = FakeGitHub()
        proposed.formula = dict(content=base64.b64encode(
            f'  url "{discovery.SOURCE_PREFIX}v0.7.0.zip"\n'.encode()).decode())
        with patch.object(discovery, "GitHub", return_value=proposed):
            self.assertTrue(discovery.candidate(FakeGitHub(pulls=[pull]), FakeGitHub())["update"])

    def test_deleted_proposal_repository_does_not_block_discovery(self):
        pull = dict(number=18, head=dict(sha="a" * 40, repo=None))
        self.assertTrue(discovery.candidate(FakeGitHub(pulls=[pull]), FakeGitHub())["update"])

    def test_formula_removal_is_not_an_existing_source_proposal(self):
        tap = FakeGitHub(pulls=[dict(number=18)])
        original_pages = tap.pages
        tap.pages = lambda path: ([dict(filename=discovery.FORMULA, status="removed")]
                                 if path.endswith("/files") else original_pages(path))
        self.assertTrue(discovery.candidate(tap, FakeGitHub())["update"])

    def test_invalid_encoded_or_binary_proposals_do_not_block_discovery(self):
        pull = dict(number=18, head=dict(sha="a" * 40, repo=dict(full_name="lynnswap/homebrew-tap")))
        for content in ("A", base64.b64encode(b"\xff").decode()):
            proposed = FakeGitHub()
            proposed.formula = dict(content=content)
            with patch.object(discovery, "GitHub", return_value=proposed):
                self.assertTrue(discovery.candidate(FakeGitHub(pulls=[pull]), FakeGitHub())["update"])

    def test_large_matching_namespace_keeps_the_highest_stable_tag(self):
        tags = [f"v0.{version}.0" for version in range(201)]
        source = FakeGitHub(tags=tags)
        self.assertEqual(discovery.candidate(FakeGitHub(), source)["latest"], "v0.200.0")

    def test_binary_published_formula_is_still_reported_as_an_error(self):
        tap = FakeGitHub()
        tap.formula = dict(content=base64.b64encode(b"\xff").decode())
        with self.assertRaises(UnicodeError):
            discovery.candidate(tap, FakeGitHub())

    def test_unrelated_pr_does_not_read_or_evaluate_its_formula(self):
        pull = dict(number=7)
        tap = FakeGitHub(pulls=[pull])
        original_pages = tap.pages
        tap.pages = lambda path: ([dict(filename="README.md")] if path.endswith("/files") else original_pages(path))
        self.assertTrue(discovery.candidate(tap, FakeGitHub())["update"])

    def test_invalid_formula_and_api_failures_are_not_reported_as_no_update(self):
        with self.assertRaises(discovery.CandidateError):
            discovery.source_tag(formula("v0.7.1-beta.1"))
        tap = FakeGitHub()
        with patch.object(tap, "api", side_effect=discovery.CandidateError("Forbidden")):
            with self.assertRaisesRegex(discovery.CandidateError, "Forbidden"):
                discovery.candidate(tap, FakeGitHub())


if __name__ == "__main__":
    unittest.main()
