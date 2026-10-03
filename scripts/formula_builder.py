#!/usr/bin/env python3
"""Select the hosted build environment required by the changed Formula."""

import argparse
import json
from pathlib import Path
import sys

from approved_bottles import CandidateError, GitHub, formula_path

BUILDERS = {
    "macos-26": "/Applications/Xcode_26.6.app/Contents/Developer",
    "xcode-27": "/Applications/Xcode_27.0.app/Contents/Developer",
}


def builder(files):
    runners = {
        "xcode-27" if item["filename"] == "Formula/custom-xcode-build-service.rb" else "macos-26"
        for item in files if formula_path(item["filename"]) and item["status"] != "removed"
    }
    if len(runners) > 1:
        raise CandidateError("Submit Formulae requiring different build environments in separate PRs.")
    runner = next(iter(runners), "macos-26")
    return dict(runner=runner, developer_dir=BUILDERS[runner])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", type=int)
    parser.add_argument("--head")
    parser.add_argument("--github-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        files = []
        if args.pr:
            github = GitHub(args.repo)
            if github.api(f"pulls/{args.pr}")["head"]["sha"] != args.head:
                raise CandidateError("The PR head changed before selecting its build environment.")
            files = github.pages(f"pulls/{args.pr}/files")
        selected = builder(files)
        with args.github_output.open("a") as output:
            for key, value in selected.items():
                output.write(f"{key}={value}\n")
        print(json.dumps(selected))
        return 0
    except (CandidateError, KeyError, ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
