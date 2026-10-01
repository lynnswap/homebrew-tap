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


def merge_main(paths, base):
    if not paths or not all(formula_path(path) for path in paths):
        raise CandidateError("Supply the Formula paths verified before bottle upload.")
    changed = git("diff", "--name-only", "-z", base, "origin/main").stdout.split("\0")[:-1]
    formula_changes = sorted(set(changed).intersection(paths))
    if formula_changes:
        raise CandidateError(f"Published Formula changed on main: {', '.join(formula_changes)}. Rebuild and approve new bottles.")
    git("merge", "--no-edit", "origin/main")
    unrelated = [path for path in changed if path not in paths]
    if unrelated and git("diff", "--name-only", "origin/main", "HEAD", "--", *unrelated).stdout.strip():
        raise CandidateError("Concurrent main changes were not preserved; inspect the PR ancestry before retrying.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("directory", type=Path)
    check = commands.add_parser("merge-main")
    check.add_argument("paths", help="JSON Formula paths emitted before upload")
    check.add_argument("base", help="Main commit recorded before the publication merge")
    args = parser.parse_args()
    try:
        if args.command == "verify":
            paths = verify_recipes(args.directory)
            if output := os.environ.get("GITHUB_OUTPUT"):
                with Path(output).open("a") as file:
                    file.write(f"formula_paths={json.dumps(paths)}\n")
        else:
            merge_main(json.loads(args.paths), args.base)
        return 0
    except (CandidateError, KeyError, ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
