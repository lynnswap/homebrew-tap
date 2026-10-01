#!/usr/bin/env python3
"""Keep bottle publication attached to the recipes Homebrew actually tested."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from approved_bottles import CandidateError, formula_path


def git(*arguments, check=True):
    result = subprocess.run(["git", *arguments], capture_output=True, text=True)
    if check and result.returncode:
        raise CandidateError(result.stderr.strip() or "Git could not verify the tested recipe.")
    return result


def verify_recipes(directory):
    paths = set()
    for metadata in directory.glob("*.bottle.json"):
        for bottle in json.loads(metadata.read_text()).values():
            formula = bottle["formula"]
            path, revision = formula["tap_git_path"], formula["tap_git_revision"]
            if not formula_path(path) or not re.fullmatch(r"[0-9a-f]{40}", revision):
                raise CandidateError(f"Invalid tested recipe metadata in {metadata.name}.")
            # pr-upload reads `path` relative to Homebrew, not tap_git_path.
            expected = f"Library/Taps/{os.environ['GITHUB_REPOSITORY'].lower()}/{path}"
            if formula["path"] != expected:
                raise CandidateError(f"Bottle recipe path does not belong to this tap: {metadata.name}.")
            if git("cat-file", "-e", f"{revision}^{{commit}}", check=False).returncode:
                git("fetch", "origin", revision)
            tested = git("rev-parse", f"{revision}:{path}").stdout.strip()
            current = git("hash-object", "--", path).stdout.strip()
            if tested != current:
                raise CandidateError(f"{path} differs from the CI-tested recipe. Rebuild and approve new bottles.")
            paths.add(path)
    if not paths:
        raise CandidateError("The approved artifact has no tested bottle recipe metadata.")
    return sorted(paths)


def check_main(paths):
    if not paths or not all(formula_path(path) for path in paths):
        raise CandidateError("Supply the Formula paths verified before bottle upload.")
    base = git("merge-base", "HEAD", "origin/main").stdout.strip()
    changed = git("diff", "--name-only", base, "origin/main", "--", *paths).stdout.strip()
    if changed:
        raise CandidateError(f"Published Formula changed on main: {changed}. Rebuild and approve new bottles.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("directory", type=Path)
    check = commands.add_parser("check-main")
    check.add_argument("paths", help="JSON Formula paths emitted before upload")
    args = parser.parse_args()
    try:
        if args.command == "verify":
            paths = verify_recipes(args.directory)
            if output := os.environ.get("GITHUB_OUTPUT"):
                with Path(output).open("a") as file:
                    file.write(f"formula_paths={json.dumps(paths)}\n")
        else:
            check_main(json.loads(args.paths))
        return 0
    except (CandidateError, KeyError, ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
