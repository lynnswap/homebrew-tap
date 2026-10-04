import base64
import copy
import hashlib
import io
import unittest
from unittest.mock import patch

from approved_bottles import CandidateError
import update_formula as update

SHA = "a" * 40
MAIN = "b" * 40
TAG = "v1.2.3"
TEMPLATE = ('class XcodeMcpkit < Formula\n'
            '  url "https://github.com/__REPOSITORY__/archive/refs/tags/v__VERSION__.tar.gz"\n'
            '__EXPLICIT_VERSION__\n  sha256 "__SHA256__"\nend\n')
ARCHIVE = b"approved public archive"
SOURCE_DIGEST = hashlib.sha256(ARCHIVE).hexdigest()
FORMULA = (TEMPLATE.replace("__EXPLICIT_VERSION__\n", "").replace("__REPOSITORY__", update.SOURCE)
           .replace("__VERSION__", "1.2.3").replace("__SHA256__", SOURCE_DIGEST))
DIGEST = hashlib.sha256(FORMULA.encode()).hexdigest()


class Source:
    repository = update.SOURCE

    def __init__(self):
        self.sha = SHA

    def api(self, path):
        if path == "git/ref/tags/" + TAG:
            return dict(object=dict(type="commit", sha=self.sha))
        if path == f"contents/Homebrew/xcode-mcpkit.rb.in?ref={SHA}":
            return dict(content=base64.b64encode(TEMPLATE.encode()).decode())
        raise AssertionError(path)


class Tap:
    repository = "lynnswap/homebrew-tap"

    def __init__(self, current=None):
        self.current = current
        self.branch = None
        self.proposed = None
        self.pulls = []
        self.writes = []

    def pages(self, path):
        if path.startswith("pulls?state=all&base=main&head="):
            return copy.deepcopy(self.pulls)
        raise AssertionError(path)

    def api(self, path, method="GET", data=None):
        if method != "GET":
            self.writes.append((path, method, data))
        if path == "git/ref/heads/main":
            return dict(object=dict(sha=MAIN))
        if path.startswith("contents/Formula?ref="):
            value = self.current if path.endswith(MAIN) else self.proposed
            return [dict(path=update.FORMULA)] if value else []
        if path.startswith("contents/Formula/xcode-mcpkit.rb?ref="):
            value = self.current if path.endswith(MAIN) else self.proposed
            return dict(sha="c" * 40, content=base64.b64encode(value.encode()).decode())
        if path.startswith("git/matching-refs/heads/"):
            return [dict(ref="refs/heads/" + update.BRANCH_PREFIX + TAG,
                         object=dict(sha=self.branch))] if self.branch else []
        if path == "git/refs" and method == "POST":
            self.branch = data["sha"]
            return {}
        if path == "contents/" + update.FORMULA and method == "PUT":
            self.proposed = base64.b64decode(data["content"]).decode()
            self.branch = SHA
            return {}
        if path == "pulls" and method == "POST":
            pull = dict(number=7, state="open", draft=False, user=dict(login="github-actions[bot]"),
                        head=dict(sha=SHA))
            self.pulls.append(pull)
            return copy.deepcopy(pull)
        raise AssertionError((path, method))


class UpdateFormulaTests(unittest.TestCase):
    def prepared(self, source=None, tag=TAG, sha=SHA, source_digest=SOURCE_DIGEST, formula_digest=DIGEST):
        with patch.object(update, "urlopen", return_value=io.BytesIO(ARCHIVE)):
            return update.prepared_formula(source or Source(), tag, sha, source_digest, formula_digest)

    def test_recipe_comes_from_the_approved_source_and_both_digests_are_checked(self):
        self.assertEqual(self.prepared(), FORMULA)
        for arguments in (dict(source_digest="0" * 64), dict(formula_digest="0" * 64)):
            with self.subTest(arguments=arguments), self.assertRaises(CandidateError):
                self.prepared(**arguments)

    def test_other_repositories_unstable_tags_and_moved_tags_cannot_propose(self):
        source = Source()
        source.repository = "other/repository"
        for arguments in (dict(source=source), dict(tag="v1.2.3-rc.1"), dict(tag="main"), dict(sha="d" * 40)):
            with self.subTest(arguments=arguments), self.assertRaises(CandidateError):
                self.prepared(**arguments)

    def test_first_formula_is_added_once_and_same_notification_reuses_the_pr(self):
        github = Tap()
        result = update.propose(github, TAG, SHA, FORMULA)
        self.assertEqual(result, dict(status="created-pr", pull_request=7, head_sha=SHA))
        self.assertEqual(github.proposed, FORMULA)
        writes = len(github.writes)
        self.assertEqual(update.propose(github, TAG, SHA, FORMULA)["status"], "existing-pr")
        self.assertEqual(len(github.writes), writes)

    def test_upgrade_replaces_the_recipe_and_drops_old_bottle_metadata(self):
        old = FORMULA.replace("v1.2.3", "v1.2.2").replace("end\n", '\n  bottle do\n    root_url "old"\n  end\nend\n')
        github = Tap(old)
        update.propose(github, TAG, SHA, FORMULA)
        self.assertEqual(github.proposed, FORMULA)
        contents = next(data for path, method, data in github.writes if method == "PUT")
        self.assertEqual(contents["sha"], "c" * 40)

    def test_an_interrupted_branch_or_commit_resumes_without_rewriting_history(self):
        for completed_commit in (False, True):
            github = Tap(FORMULA.replace("v1.2.3", "v1.2.2"))
            github.branch = SHA if completed_commit else MAIN
            github.proposed = FORMULA if completed_commit else github.current
            result = update.propose(github, TAG, SHA, FORMULA)
            self.assertEqual(result["status"], "created-pr")
            self.assertFalse(any(path == "git/refs" for path, _, _ in github.writes))
            self.assertEqual(any(method == "PUT" for _, method, _ in github.writes), not completed_commit)

    def test_published_recipe_is_not_reproposed_but_newer_versions_are_not_downgraded(self):
        github = Tap(FORMULA.replace("end\n", '\n  bottle do\n    root_url "bottles"\n  end\nend\n'))
        self.assertEqual(update.propose(github, TAG, SHA, FORMULA)["status"], "already-published")
        self.assertEqual(github.writes, [])
        github.current = FORMULA.replace("v1.2.3", "v2.0.0")
        with self.assertRaises(CandidateError):
            update.propose(github, TAG, SHA, FORMULA)
        self.assertEqual(github.writes, [])

    def test_changed_or_closed_proposal_is_not_overwritten(self):
        for closed in (False, True):
            github = Tap()
            update.propose(github, TAG, SHA, FORMULA)
            if closed:
                github.pulls[0]["state"] = "closed"
            else:
                github.proposed += "# changed recipe\n"
            writes = len(github.writes)
            with self.assertRaises(CandidateError):
                update.propose(github, TAG, SHA, FORMULA)
            self.assertEqual(len(github.writes), writes)


if __name__ == "__main__":
    unittest.main()
