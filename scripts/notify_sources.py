#!/usr/bin/env python3
"""Notify registered source repositories after their bottles are published."""

import argparse
import json
from pathlib import Path
import sys

from approved_bottles import CandidateError, GitHub

SOURCES = {
    "Formula/xcode-mcpkit.rb": ("lynnswap/XcodeMCPKit", "resume-release.yml"),
    "Formula/privateheaderkit.rb": ("lynnswap/PrivateHeaderKit", "resume-release.yml"),
    "Formula/custom-xcode-build-service.rb": (
        "lynnswap/swift-build", "custom-xcode-build-service-resume.yml"),
}


def repositories(formula_paths):
    return sorted({SOURCES[path][0] for path in formula_paths if path in SOURCES})


def source_workflow(repository):
    for source, workflow in SOURCES.values():
        if source == repository:
            return dict(repository=source.split("/", 1)[1], workflow=workflow)
    raise CandidateError("Notify a registered source repository only.")


def dispatch(github):
    target = source_workflow(github.repository)
    github.api(f"actions/workflows/{target['workflow']}/dispatches", "POST", dict(ref="main"))
    return dict(repository=github.repository, workflow=target["workflow"], status="dispatched")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    targets = commands.add_parser("targets")
    targets.add_argument("--formula-paths", required=True)
    targets.add_argument("--github-output", type=Path, required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--repo", required=True)
    prepare.add_argument("--github-output", type=Path, required=True)
    notify = commands.add_parser("dispatch")
    notify.add_argument("--repo", required=True)
    args = parser.parse_args()
    try:
        if args.command == "targets":
            value = dict(repositories=repositories(json.loads(args.formula_paths)))
            outputs = dict(repositories=json.dumps(value["repositories"]))
        elif args.command == "prepare":
            value = outputs = source_workflow(args.repo)
        else:
            print(json.dumps(dispatch(GitHub(args.repo))))
            return 0
        with args.github_output.open("a") as output:
            for key, content in outputs.items():
                output.write(f"{key}={content}\n")
        print(json.dumps(value))
        return 0
    except (CandidateError, KeyError, ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
