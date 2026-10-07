"""Exercise binary workflow authentication against a local Git HTTP remote."""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import unittest

from test_workflow_secrets import job_body


class BinaryWorkflowTests(unittest.TestCase):
    def git_http_checkout(self, homebrew_git_token):
        headers = []

        class Remote(SimpleHTTPRequestHandler):
            def do_GET(self):
                authorization = self.headers.get_all("Authorization", [])
                headers.append(authorization)
                if len(authorization) > 1:
                    self.send_error(400, "Duplicate Authorization header")
                else:
                    super().do_GET()

            def log_message(self, *args):
                pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = {key: value for key, value in os.environ.items()
                           if not key.startswith("GIT_")}
            environment.update(GIT_CONFIG_GLOBAL=str(root / "global.gitconfig"),
                               GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")

            def git(*arguments, check=True):
                return subprocess.run(["git", *arguments], env=environment, check=check,
                                      text=True, capture_output=True)

            git("init", "--bare", str(root / "remote.git"))
            git("-C", str(root / "remote.git"), "update-server-info")
            git("init", str(root / "checkout"))
            server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Remote, directory=directory))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}/"
                key = f"http.{base}.extraheader"
                # setup-homebrew's pinned action persists its `token` globally;
                # checkout independently supplies its own repository credential.
                if homebrew_git_token:
                    git("config", "--global", key, "Authorization: basic mock-homebrew")
                git("-C", str(root / "checkout"), "config", key,
                    "Authorization: basic mock-checkout")
                result = git("-C", str(root / "checkout"), "ls-remote",
                             base + "remote.git", check=False)
            finally:
                server.shutdown()
                thread.join()
                server.server_close()
        return result, headers

    def test_old_shared_git_token_reproduces_duplicate_authorization(self):
        result, headers = self.git_http_checkout("mock-token")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(headers)
        self.assertEqual(len(headers[0]), 2)
        self.assertIn("400", result.stderr)

    def test_workflow_keeps_api_token_without_duplicate_git_authorization(self):
        body = job_body("test-binary-formula.yml", "install")
        setup = re.search(r"uses: Homebrew/actions/setup-homebrew@[^\n]+\n"
                          r"\s+with:\n((?: {10}[^\n]+\n)+)", body)[1]
        inputs = dict(re.findall(r"^ {10}([\w-]+): (.+)$", setup, re.MULTILINE))
        self.assertEqual(inputs["brew-gh-api-token"], "${{ github.token }}")
        result, headers = self.git_http_checkout(inputs.get("token", ""))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(headers)
        self.assertTrue(all(values == ["basic mock-checkout"] for values in headers))

    def test_publication_waits_for_read_only_verification(self):
        merge = job_body("update-formula.yml", "merge-binary")
        self.assertIn("needs: [update, verify-binary]", merge)
        self.assertIn('--head "$HEAD_SHA"', merge)
        verify = job_body("update-formula.yml", "verify-binary")
        self.assertIn("contents: read", verify)
        self.assertNotIn(": write", verify)


if __name__ == "__main__":
    unittest.main()
