#!/usr/bin/env python3
"""Dispatch read-only native Formula CI from trusted main for pinned bot proposals."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

from approved_bottles import CandidateError, GitHub, formula_changes, matching_runs, needs_bottles


def native_branch(branch):
    return branch.startswith("renovate/") or bool(re.fullmatch(
        r"codex/release-(?:xcode-mcpkit|custom-xcode-build-service)-v[0-9]+\.[0-9]+\.[0-9]+", branch))


def native_proposal(github, number, head_sha):
    pull = github.api(f"pulls/{number}")
    if (pull["state"] != "open" or pull.get("draft") or pull["base"]["ref"] != "main"
            or pull["user"]["login"] != "github-actions[bot]"
            or not native_branch(pull["head"]["ref"])
            or pull["head"]["repo"] is None or pull["head"]["repo"]["full_name"] != github.repository):
        raise CandidateError("Automatic CI accepts an open native same-repository Formula proposal only.")
    if not re.fullmatch(r"[0-9a-f]{40}", head_sha) or pull["head"]["sha"] != head_sha:
        raise CandidateError("The proposed head changed; inspect its current revision.")
    files = github.pages(f"pulls/{number}/files")
    if not formula_changes(files):
        raise CandidateError("Automatic CI accepts only added or modified Formula files.")
    return files


def dispatch(github, dry_run=False, number=None, head_sha=None):
    workflow = github.api("actions/workflows/tests.yml")
    values = []
    requested_head = head_sha
    specific = number is not None
    pulls = [github.api(f"pulls/{number}")] if number is not None else github.pages("pulls?state=open&base=main")
    for pull in pulls:
        if not specific and (pull["user"]["login"] != "github-actions[bot]" or not native_branch(pull["head"]["ref"])):
            continue
        number = pull["number"]
        head_sha = requested_head if specific else pull["head"]["sha"]
        try:
            files = native_proposal(github, number, head_sha)
        except CandidateError as error:
            if specific:
                raise
            values.append(dict(pull_request=number, head_sha=head_sha, status="ineligible", reason=str(error)))
            continue
        if not needs_bottles(files):
            values.append(dict(pull_request=number, head_sha=head_sha, status="upstream-binary-update"))
            continue
        runs = matching_runs(github, workflow["id"], number, head_sha)
        if runs and runs[0]["conclusion"] != "action_required":
            status = (publish(github, number, head_sha, runs[0], dry_run)
                      if runs[0]["status"] == "completed" and runs[0]["conclusion"] == "success"
                      else "existing-ci")
            values.append(dict(pull_request=number, head_sha=head_sha, status=status))
            continue
        if not dry_run:
            github.api(f"actions/workflows/{workflow['id']}/dispatches", "POST",
                       dict(ref="main", inputs=dict(pull_request=str(number), head_sha=head_sha)))
        values.append(dict(pull_request=number, head_sha=head_sha, status="ready" if dry_run else "dispatched"))
    return values


def publish(github, number, head_sha, ci_run, dry_run):
    workflow = github.api("actions/workflows/publish.yml")
    titles = {f"Publish bottles for PR {number} at {head_sha}",
              f"Publish bottles from CI {ci_run['id']} attempt {ci_run['run_attempt']}"}
    runs = github.pages(f"actions/workflows/{workflow['id']}/runs", "workflow_runs")
    for run in runs:
        if run["workflow_id"] != workflow["id"] or run.get("head_branch") != "main":
            continue
        if run["display_title"] == "brew pr-pull":
            if run["created_at"] < ci_run["created_at"]:
                continue
            jobs = github.pages(f"actions/runs/{run['id']}/jobs", "jobs")
            validation = next((job for job in jobs if job["name"] == "validate"), None)
            if validation and validation["status"] != "completed":
                return "existing-publication"
            values = []
            if validation and validation["conclusion"] == "success":
                for line in github.job_log(validation["id"]).splitlines():
                    try:
                        value = json.loads(line.partition(" ")[2])
                    except ValueError:
                        continue
                    if isinstance(value, dict) and {"repository", "pull_request", "head_sha", "ci_run_id", "artifact_digest"} <= value.keys():
                        values.append(value)
            if len(values) > 1:
                raise CandidateError("The earlier publication has ambiguous validation metadata.")
            if not values:
                if any(job["name"] == "pr-pull" and job["conclusion"] != "skipped" for job in jobs):
                    raise CandidateError("An earlier protected publisher has no identifiable validated candidate.")
                continue
            value = values[0]
            if value["repository"] != github.repository or value["pull_request"] != number or value["head_sha"] != head_sha:
                continue
        elif run["display_title"] not in titles:
            continue
        if run["status"] != "completed":
            return "existing-publication"
        jobs = github.pages(f"actions/runs/{run['id']}/jobs", "jobs")
        if run["conclusion"] != "success" or any(
                job["name"] == "pr-pull" and job["conclusion"] != "skipped" for job in jobs):
            return "existing-publication"
    # A previously blocked bot-PR run can complete after its initial completion
    # event was skipped. Repair a missing publisher without rerunning bottle CI.
    if not dry_run:
        github.api(f"actions/workflows/{workflow['id']}/dispatches", "POST",
                   dict(ref="main", inputs=dict(pull_request=str(number), head_sha=head_sha)))
    return "publication-ready" if dry_run else "publication-dispatched"


def prepare(github, number, head_sha, tap_root):
    files = native_proposal(github, number, head_sha)
    subprocess.run(["git", "-C", str(tap_root), "fetch", "origin", f"refs/pull/{number}/head"], check=True)
    fetched = subprocess.check_output(["git", "-C", str(tap_root), "rev-parse", "FETCH_HEAD"], text=True).strip()
    if fetched != head_sha:
        raise CandidateError("The fetched Formula head no longer matches the dispatched candidate.")
    subprocess.run(["git", "-C", str(tap_root), "checkout", "--detach", head_sha], check=True)
    owner, repository = github.repository.split("/", 1)
    tap = f"{owner}/{repository.removeprefix('homebrew-')}"
    names = [(f"{tap}/{Path(item['filename']).stem}", item["status"]) for item in files]
    return dict(formulae=[name for name, _ in names],
                added_formulae=[name for name, status in names if status == "added"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    propose = commands.add_parser("dispatch")
    propose.add_argument("--dry-run", action="store_true")
    propose.add_argument("--pr", type=int)
    propose.add_argument("--head")
    pin = commands.add_parser("prepare")
    pin.add_argument("--pr", type=int, required=True)
    pin.add_argument("--head", required=True)
    pin.add_argument("--tap-root", type=Path, required=True)
    pin.add_argument("--github-output", type=Path, required=True)
    for command in (propose, pin):
        command.add_argument("--repo", required=True)
    args = parser.parse_args()
    try:
        github = GitHub(args.repo)
        if args.command == "dispatch":
            if (args.pr is None) != (args.head is None):
                raise CandidateError("Supply both --pr and --head for a specific proposal.")
            print(json.dumps(dispatch(github, args.dry_run, args.pr, args.head)))
        else:
            formulae = prepare(github, args.pr, args.head, args.tap_root)
            with args.github_output.open("a") as output:
                for key, names in formulae.items():
                    output.write(key + "=" + ",".join(names) + "\n")
        return 0
    except (CandidateError, KeyError, ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
