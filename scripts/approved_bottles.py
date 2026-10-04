#!/usr/bin/env python3
"""Pin and revalidate a tested Homebrew PR before protected publication."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


class CandidateError(Exception):
    pass


class GitHub:
    def __init__(self, repository):
        self.repository = repository

    def api(self, path, method="GET", data=None):
        command = ["gh", "api", "--method", method, f"repos/{self.repository}/{path}"]
        if data is not None:
            command += ["--input", "-"]
        result = subprocess.run(
            command, input=json.dumps(data) if data is not None else None,
            capture_output=True, text=True, check=False,
        )
        if result.returncode:
            raise CandidateError(result.stderr.strip() or f"Could not read {path}.")
        return json.loads(result.stdout) if result.stdout.strip() else None

    def pages(self, path, field=None):
        values = []
        page = 1
        while True:
            separator = "&" if "?" in path else "?"
            response = self.api(f"{path}{separator}per_page=100&page={page}")
            items = response[field] if field else response
            values.extend(items)
            if len(items) < 100:
                return values
            page += 1

    def job_log(self, job_id):
        # Runner images can ship an older gh; newer versions require this opt-in
        # for raw job logs containing GitHub's ANSI-colored command output.
        help_result = subprocess.run(["gh", "api", "--help"], capture_output=True, text=True, check=False)
        if help_result.returncode:
            raise CandidateError(help_result.stderr.strip() or "Could not inspect gh api options.")
        command = ["gh", "api"]
        if "--allow-escape-sequences" in help_result.stdout:
            command.append("--allow-escape-sequences")
        command.append(f"repos/{self.repository}/actions/jobs/{job_id}/logs")
        result = subprocess.run(
            command,
            capture_output=True, text=True, check=False,
        )
        if result.returncode:
            raise CandidateError(result.stderr.strip() or "Could not read the publication validation log.")
        return result.stdout


def formula_path(path):
    return bool(re.fullmatch(r"Formula/(?:[A-Za-z0-9_-]+/)?[A-Za-z0-9+_.@-]+\.rb", path))


def formula_changes(files):
    return bool(files) and all(
        formula_path(item["filename"])
        and item["status"] in ("added", "modified")
        for item in files
    )


def associated_pulls(github, run):
    dispatched = dispatched_pull(run)
    if dispatched:
        return [dispatched[0]]
    if run["pull_requests"]:
        return [item["number"] for item in run["pull_requests"]]
    # GitHub omits pull_requests for some fork runs. Resolve their head through
    # the base repository instead of treating an empty event field as failure.
    return [item["number"] for item in github.pages(f"commits/{run['head_sha']}/pulls")
            if item["state"] == "open" and not item.get("draft")
            and item["base"]["ref"] == "main" and item["head"]["sha"] == run["head_sha"]]


def dispatched_pull(run):
    if run["event"] != "workflow_dispatch" or run.get("head_branch") != "main":
        return None
    match = re.fullmatch(r"Bottle CI for PR ([0-9]+) at ([0-9a-f]{40})", run.get("display_title", ""))
    return (int(match[1]), match[2]) if match else None


def matching_runs(github, workflow_id, number, head_sha):
    pulls = github.api(
        f"actions/workflows/{workflow_id}/runs?event=pull_request&head_sha={head_sha}&per_page=100"
    )["workflow_runs"]
    dispatches = github.pages(f"actions/workflows/{workflow_id}/runs?event=workflow_dispatch", "workflow_runs")
    runs = {run["id"]: run for run in pulls + dispatches
            if run["workflow_id"] == workflow_id and (
                (run["event"] == "pull_request" and run["head_sha"] == head_sha)
                or dispatched_pull(run) == (number, head_sha))}
    return sorted(runs.values(), key=lambda run: (run["created_at"], run["id"]), reverse=True)


def candidate(github, number, head_sha, event_run_id=None):
    if not re.fullmatch(r"[0-9a-f]{40}", head_sha):
        raise CandidateError("Supply the reviewed full lowercase PR-head SHA.")
    pull = github.api(f"pulls/{number}")
    if pull["state"] != "open" or pull.get("draft"):
        raise CandidateError("Select an open, ready Formula pull request.")
    if (pull["user"]["login"] not in ("lynnswap", "github-actions[bot]")
            or pull["head"].get("repo") is None
            or pull["head"]["repo"]["full_name"] != github.repository):
        raise CandidateError("Bottle publication accepts only same-repository PRs from lynnswap or GitHub Actions.")
    if pull["base"]["ref"] != "main":
        raise CandidateError("The Formula pull request must target main.")
    if pull["head"]["sha"] != head_sha:
        raise CandidateError("The PR head changed; review and approve its current revision.")
    if not formula_changes(github.pages(f"pulls/{number}/files")):
        raise CandidateError("Bottle publication accepts only added or modified Formula files.")

    workflow = github.api("actions/workflows/tests.yml")
    runs = matching_runs(github, workflow["id"], number, head_sha)
    if not runs:
        raise CandidateError("No bottle CI run exists for the reviewed head.")
    latest = runs[0]
    if event_run_id is not None and latest["id"] != event_run_id:
        raise CandidateError("A newer bottle CI run replaced this completion event.")
    run = github.api(f"actions/runs/{latest['id']}")
    if run["workflow_id"] != workflow["id"] or not (
        (run["event"] == "pull_request" and run["head_sha"] == head_sha)
        or dispatched_pull(run) == (number, head_sha)
    ):
        raise CandidateError("The selected CI run does not test this Formula head.")
    if run["status"] != "completed" or run["conclusion"] != "success":
        raise CandidateError("The latest bottle CI run must finish successfully before publication.")
    if number not in associated_pulls(github, run):
        raise CandidateError("The CI run is not associated with the requested pull request.")

    name = f"bottles_macos-arm64_{run['id']}_{run['run_attempt']}"
    artifacts = [item for item in github.pages(f"actions/runs/{run['id']}/artifacts", "artifacts")
                 if item["name"] == name]
    if len(artifacts) != 1:
        raise CandidateError("The successful CI run must have one uniquely named bottle artifact.")
    artifact = artifacts[0]
    if artifact["expired"]:
        raise CandidateError("The tested bottle artifact expired; rebuild and approve new artifacts.")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", artifact.get("digest") or ""):
        raise CandidateError("The tested bottle artifact has no verifiable SHA-256 digest.")
    return {
        "repository": github.repository,
        "pull_request": number,
        "head_sha": head_sha,
        "ci_run_id": run["id"],
        "ci_attempt": run["run_attempt"],
        "artifact_id": artifact["id"],
        "artifact_name": name,
        "artifact_digest": artifact["digest"],
    }


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def verify_approved(value, expected_digest):
    if fingerprint(value) != expected_digest:
        raise CandidateError("The tested head or artifacts changed after validation; prepare a new publication candidate.")


def write_outputs(path, value):
    if path:
        with path.open("a") as output:
            output.write(f"eligible={'true' if value else 'false'}\n")
            if value:
                for key, item in value.items():
                    output.write(f"{key}={item}\n")
                output.write(f"candidate_digest={fingerprint(value)}\n")


def summarize(value):
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        repository = value["repository"]
        with Path(path).open("a") as summary:
            summary.write("## Tested bottles ready for automatic publication\n\n")
            summary.write(f"[Formula PR #{value['pull_request']}](https://github.com/{repository}/pull/{value['pull_request']})\n\n")
            summary.write(f"Reviewed head: `{value['head_sha']}`\n\n")
            summary.write(f"[Successful CI run](https://github.com/{repository}/actions/runs/{value['ci_run_id']}) (attempt {value['ci_attempt']})\n\n")
            summary.write(f"[Bottle artifact](https://github.com/{repository}/actions/runs/{value['ci_run_id']}/artifacts/{value['artifact_id']})\n\n")
            summary.write(f"Artifact digest: `{value['artifact_digest']}`\n\n")
            summary.write("The publisher revalidates this same-repository maintainer/bot Formula revision and exact tested artifact before automatic publication.\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", type=int)
    parser.add_argument("--head")
    parser.add_argument("--event-file", type=Path)
    parser.add_argument("--candidate-digest")
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    github = GitHub(args.repo)
    try:
        event_run_id = None
        if args.event_file:
            run = json.loads(args.event_file.read_text())["workflow_run"]
            numbers = associated_pulls(github, run) if run["event"] in ("pull_request", "workflow_dispatch") and run["conclusion"] == "success" else []
            if len(numbers) != 1:
                write_outputs(args.github_output, None)
                print("This CI completion does not require bottle publication.")
                return 0
            number = numbers[0]
            dispatched = dispatched_pull(run)
            head_sha = dispatched[1] if dispatched else run["head_sha"]
            event_run_id = run["id"]
            pull = github.api(f"pulls/{number}")
            if pull["state"] != "open" or pull.get("draft") or pull["head"]["sha"] != head_sha:
                write_outputs(args.github_output, None)
                print("The completed CI no longer describes an open publication candidate.")
                return 0
            if not formula_changes(github.pages(f"pulls/{number}/files")):
                write_outputs(args.github_output, None)
                print("This pull request does not require bottle publication.")
                return 0
        else:
            if args.pr is None or args.head is None:
                raise CandidateError("Supply a Formula PR and its reviewed head SHA.")
            number, head_sha = args.pr, args.head
        value = candidate(github, number, head_sha, event_run_id)
        if args.candidate_digest:
            verify_approved(value, args.candidate_digest)
        else:
            summarize(value)
        write_outputs(args.github_output, value)
        print(json.dumps(value, sort_keys=True))
        return 0
    except (CandidateError, KeyError, ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
