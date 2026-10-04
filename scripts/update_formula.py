#!/usr/bin/env python3
"""Propose the Formula prepared by an approved XcodeMCPKit release."""

import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import quote
from urllib.request import urlopen

from approved_bottles import CandidateError, GitHub

SOURCE = "lynnswap/XcodeMCPKit"
FORMULA = "Formula/xcode-mcpkit.rb"
BRANCH_PREFIX = "codex/release-xcode-mcpkit-"


def prepared_formula(source, tag, sha, source_digest, formula_digest):
    if source.repository != SOURCE or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
        raise CandidateError("Supply an XcodeMCPKit stable source tag.")
    if not re.fullmatch(r"[0-9a-f]{40}", sha) or any(
            not re.fullmatch(r"[0-9a-f]{64}", value) for value in (source_digest, formula_digest)):
        raise CandidateError("Supply the approved commit and source/Formula SHA-256 digests.")
    obj = source.api("git/ref/tags/" + quote(tag, safe=""))["object"]
    while obj["type"] == "tag":
        obj = source.api("git/tags/" + obj["sha"])["object"]
    if obj["type"] != "commit" or obj["sha"] != sha:
        raise CandidateError("The public source tag differs from the approved commit.")
    url = f"https://github.com/{SOURCE}/archive/refs/tags/{tag}.tar.gz"
    with urlopen(url, timeout=60) as response:
        digest = hashlib.file_digest(response, "sha256").hexdigest()
    if digest != source_digest:
        raise CandidateError("The public source archive differs from the prepared archive.")
    entry = source.api(f"contents/Homebrew/xcode-mcpkit.rb.in?ref={sha}")
    template = base64.b64decode(entry["content"]).decode("utf-8")
    formula = (template.replace("__EXPLICIT_VERSION__\n", "")
               .replace("__VERSION__", tag.removeprefix("v"))
               .replace("__REPOSITORY__", SOURCE).replace("__SHA256__", source_digest))
    if hashlib.sha256(formula.encode()).hexdigest() != formula_digest:
        raise CandidateError("The source recipe differs from the approved Formula.")
    return formula


def read_formula(github, ref):
    entries = github.api(f"contents/Formula?ref={ref}")
    if not any(item["path"] == FORMULA for item in entries):
        return None
    entry = github.api(f"contents/{FORMULA}?ref={ref}")
    return dict(sha=entry["sha"], text=base64.b64decode(entry["content"]).decode("utf-8"))


def recipe(formula):
    # Bottle metadata belongs to tap CI, while the source owns the build recipe.
    return re.sub(r"\n  bottle do\n.*?^  end\n", "", formula, flags=re.MULTILINE | re.DOTALL)


def propose(github, tag, source_sha, formula):
    main = github.api("git/ref/heads/main")["object"]["sha"]
    current = read_formula(github, main)
    if current and recipe(current["text"]) == formula:
        return dict(status="already-published")
    if current:
        match = re.search(r"/archive/refs/tags/v([0-9]+)\.([0-9]+)\.([0-9]+)\.tar\.gz", current["text"])
        requested = tuple(map(int, tag[1:].split(".")))
        if match and tuple(map(int, match.groups())) > requested:
            raise CandidateError("A newer Formula is already published; the tap was not downgraded.")

    branch = BRANCH_PREFIX + tag
    pulls = github.pages(f"pulls?state=all&base=main&head={github.repository.split('/')[0]}:{branch}")
    if pulls:
        pull = pulls[0]
        if pull["state"] != "open" or pull.get("draft") or pull["user"]["login"] != "github-actions[bot]":
            raise CandidateError("The release proposal was closed or changed; inspect it before retrying.")
        existing = read_formula(github, pull["head"]["sha"])
        if not existing or existing["text"] != formula:
            raise CandidateError("The existing release PR differs from the prepared Formula.")
        return dict(status="existing-pr", pull_request=pull["number"], head_sha=pull["head"]["sha"])

    refs = github.api("git/matching-refs/heads/" + branch)
    ref = next((item for item in refs if item["ref"] == "refs/heads/" + branch), None)
    if ref is None:
        github.api("git/refs", "POST", dict(ref="refs/heads/" + branch, sha=main))
        existing = current
    else:
        existing = read_formula(github, ref["object"]["sha"])
        # Resume a request interrupted after the Formula commit, without rewriting it.
        if existing and existing["text"] != formula and ref["object"]["sha"] != main:
            raise CandidateError("The release branch contains a different Formula; inspect it before retrying.")
    if existing is None or existing["text"] != formula:
        data = dict(message=f"feat: release xcode-mcpkit {tag}", branch=branch,
                    content=base64.b64encode(formula.encode()).decode())
        if existing:
            data["sha"] = existing["sha"]
        github.api(f"contents/{FORMULA}", "PUT", data)
    pull = github.api("pulls", "POST", dict(
        title=f"Release xcode-mcpkit {tag}", head=branch, base="main",
        body=(f"Install XcodeMCPKit {tag} from its approved source recipe.\n\n"
              f"Source: https://github.com/{SOURCE}/commit/{source_sha}\n\n"
              "Bottle CI must build and test this Formula before the tap publisher merges it.\n")))
    return dict(status="created-pr", pull_request=pull["number"], head_sha=pull["head"]["sha"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--source-repository", required=True)
    parser.add_argument("--source-tag", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--formula-sha256", required=True)
    parser.add_argument("--github-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        formula = prepared_formula(GitHub(args.source_repository), args.source_tag, args.source_sha,
                                   args.source_sha256, args.formula_sha256)
        result = propose(GitHub(args.repo), args.source_tag, args.source_sha, formula)
        with args.github_output.open("a") as output:
            for key, value in result.items():
                output.write(f"{key}={value}\n")
        print(json.dumps(result))
        return 0
    except (CandidateError, KeyError, ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
