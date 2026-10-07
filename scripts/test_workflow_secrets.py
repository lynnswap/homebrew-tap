"""Protect the secret handoffs that local signing/API mocks cannot exercise."""
from pathlib import Path
import re
import unittest


WORKFLOWS = Path(__file__).resolve().parents[1] / '.github/workflows'


def job_body(workflow, job):
    return re.search(rf'^  {job}:\n(.*?)(?=^  [a-z][\w-]*:|\Z)',
                     (WORKFLOWS / workflow).read_text(), re.MULTILINE | re.DOTALL)[1]


class WorkflowSecretTests(unittest.TestCase):
    def test_signing_and_notification_calls_inherit_secrets_at_each_boundary(self):
        for workflow, job, called in (
            ('tests.yml', 'publish-tested-bottles', 'publish.yml'),
            ('publish.yml', 'notify-sources', 'notify-source.yml'),
        ):
            with self.subTest(workflow=workflow, job=job):
                body = job_body(workflow, job)
                self.assertIn(f'    uses: ./.github/workflows/{called}\n', body)
                # Environment binding alone left these secrets empty in the called job.
                self.assertRegex(body, r'(?m)^    secrets: inherit$')

    def test_secret_consumers_keep_their_own_approval_environments(self):
        for workflow, job, environment, secrets in (
            ('publish.yml', 'sign-xcodemcpkit', 'release-signing',
             ('DEVELOPER_ID_P12_BASE64', 'DEVELOPER_ID_P12_PASSWORD', 'NOTARY_API_PRIVATE_KEY')),
            ('notify-source.yml', 'notify', 'source-notification', ('SOURCE_DISPATCH_APP_PRIVATE_KEY',)),
        ):
            with self.subTest(workflow=workflow, job=job):
                body = job_body(workflow, job)
                self.assertIn(f'    environment: {environment}\n', body)
                self.assertIn('ref: ${{ github.workflow_sha }}', body)
                for name in secrets:
                    self.assertIn('${{ secrets.' + name + ' }}', body)


if __name__ == '__main__':
    unittest.main()
