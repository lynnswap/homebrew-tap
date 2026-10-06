#!/usr/bin/env python3
"""Verify and merge the custom service's upstream binary Formula."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from approved_bottles import CandidateError, GitHub, formula_proposal
from dispatched_ci import native_proposal
from update_formula import BINARY_ARCHIVE, BINARY_FORMULA, BINARY_SOURCE, published_binary


def require_binary_only(files):
    if len(files) != 1 or files[0]["filename"] != BINARY_FORMULA:
        raise CandidateError("The binary installation workflow accepts only the custom build service Formula.")


def verify(github, number, head, tap_root):
    require_binary_only(formula_proposal(github, number, head))
    subprocess.run(["git", "-C", str(tap_root), "fetch", "origin", f"refs/pull/{number}/head"], check=True)
    actual = subprocess.check_output(["git", "-C", str(tap_root), "rev-parse", "FETCH_HEAD"], text=True).strip()
    if actual != head:
        raise CandidateError("The Formula changed before installation verification.")
    subprocess.run(["git", "-C", str(tap_root), "checkout", "--detach", head], check=True)
    owner, repository = github.repository.split("/", 1)
    formula = f"{owner}/{repository.removeprefix('homebrew-')}/custom-xcode-build-service"
    environment = dict(os.environ, HOMEBREW_NO_AUTO_UPDATE="1", HOMEBREW_NO_INSTALL_CLEANUP="1")
    def brew(*arguments, capture=False):
        return subprocess.run(["brew", *arguments], env=environment, check=True, text=True, capture_output=capture)
    brew("trust", "--formula", formula)
    info = json.loads(brew("info", "--json=v2", formula, capture=True).stdout)["formulae"][0]
    tag = "v" + info["versions"]["stable"]
    source = GitHub(BINARY_SOURCE)
    item, assets = published_binary(source, tag)
    asset = assets[BINARY_ARCHIVE]
    if (info["urls"]["stable"]["url"] != asset["browser_download_url"]
            or "sha256:" + info["urls"]["stable"]["checksum"] != asset["digest"]):
        raise CandidateError("The Formula must install the published binary URL and checksum.")
    brew("style", formula)
    brew("install", formula)
    brew("test", formula)
    prefix = Path(brew("--prefix", formula, capture=True).stdout.strip())
    manifest = json.loads((prefix / "libexec/manifest.json").read_text())
    if manifest["version"] != tag or manifest["sourceRevision"] != item["target_commitish"]:
        raise CandidateError("The installed binary does not match the published version and source commit.")
    print(f"Verified {formula} {tag} from {asset['browser_download_url']}.")


def merge(github, number, head):
    pull = github.api(f"pulls/{number}")
    if pull.get("merged") and pull["head"]["sha"] == head:
        return dict(status="already-merged")
    require_binary_only(native_proposal(github, number, head))
    result = github.api(f"pulls/{number}/merge", "PUT", dict(sha=head, merge_method="merge"))
    if not result.get("merged"):
        raise CandidateError(result.get("message", "The tested Formula could not be merged."))
    return dict(status="merged", sha=result["sha"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("verify", "merge"))
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--tap-root", type=Path)
    args = parser.parse_args()
    try:
        github = GitHub(args.repo)
        if args.command == "verify":
            if args.tap_root is None:
                parser.error("verify requires --tap-root")
            verify(github, args.pr, args.head, args.tap_root)
        else:
            print(json.dumps(merge(github, args.pr, args.head)))
        return 0
    except (CandidateError, KeyError, ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
