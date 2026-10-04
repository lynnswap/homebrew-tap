#!/usr/bin/env python3
"""Discover unproposed public source tags without running Renovate or Formula code."""

import argparse
import base64
import json
from pathlib import Path
import re
import sys

from approved_bottles import CandidateError, GitHub

SOURCES = {
    "Formula/privateheaderkit.rb": "lynnswap/PrivateHeaderKit",
    "Formula/custom-xcode-build-service.rb": "lynnswap/swift-build",
}


def stable_version(tag):
    match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", tag)
    return tuple(map(int, match.groups())) if match else None


def source_tag(entry, repository):
    prefix = f"https://github.com/{repository}/archive/refs/tags/"
    if not isinstance(entry, dict) or not isinstance(entry.get("content"), str):
        return None
    try:
        formula = base64.b64decode(entry["content"]).decode("utf-8")
    except (ValueError, UnicodeError):
        return None
    urls = re.findall(r'''^  url ["']([^"'\n]+)["'](?:\s+#.*)?$''', formula, re.MULTILINE)
    if len(urls) != 1 or not urls[0].startswith(prefix) or not urls[0].endswith(".tar.gz"):
        return None
    tag = urls[0][len(prefix):-len(".tar.gz")]
    return tag if stable_version(tag) is not None else None


def candidate(tap, source, formula, requested_tag=None):
    current = source_tag(tap.api(f"contents/{formula}?ref=main"), source.repository)
    if current is None:
        raise CandidateError("The published Formula must name a literal public stable tag-archive URL.")
    # Matching references returns the full namespace without paging parameters.
    tags = [item["ref"].removeprefix("refs/tags/")
            for item in source.api("git/matching-refs/tags/v")]
    if requested_tag is not None and requested_tag not in tags:
        raise CandidateError("The notified stable source tag is not public.")
    stable = [tag for tag in tags if stable_version(tag) is not None]
    latest = max(stable, key=stable_version) if stable else current
    value = dict(current=current, latest=latest, update=False)
    if stable_version(latest) <= stable_version(current):
        return dict(value, reason="The published Formula already covers the available stable tags.")
    for pull in tap.pages("pulls?state=open&base=main"):
        if not any(item["filename"] == formula and item["status"] != "removed"
                   for item in tap.pages(f"pulls/{pull['number']}/files")):
            continue
        head = pull["head"]
        if head["repo"] is None:
            continue
        proposed = GitHub(head["repo"]["full_name"]).api(f"contents/{formula}?ref={head['sha']}")
        if source_tag(proposed, source.repository) == latest:
            return dict(value, pull_request=pull["number"], reason="The source update already has an open Formula PR.")
    return dict(value, update=True, reason="A public stable source tag needs a Formula proposal.")


def candidates(tap):
    available = {entry["path"] for entry in tap.api("contents/Formula?ref=main")}
    # A new tool joins discovery after its first released recipe is installed.
    values = {formula: candidate(tap, GitHub(repository), formula)
              for formula, repository in SOURCES.items() if formula in available}
    return dict(update=any(value["update"] for value in values.values()), formulae=values)


def notified_candidate(tap, repository, tag):
    formula = next((path for path, source in SOURCES.items() if source == repository), None)
    if formula is None or not tag or stable_version(tag) is None:
        raise CandidateError("Notify a configured source repository and a stable vX.Y.Z tag.")
    value = candidate(tap, GitHub(repository), formula, requested_tag=tag)
    return dict(update=value["update"], priority_update=True, formulae={formula: value})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--maintenance", action="store_true")
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--source-repository")
    parser.add_argument("--source-tag")
    args = parser.parse_args()
    try:
        if args.source_repository or args.source_tag:
            value = notified_candidate(GitHub(args.repo), args.source_repository, args.source_tag)
        else:
            value = (dict(update=True, reason="Regular or manually requested Renovate maintenance.")
                     if args.maintenance else candidates(GitHub(args.repo)))
        if args.github_output:
            with args.github_output.open("a") as output:
                output.write(f"update={'true' if value['update'] else 'false'}\n")
                output.write(f"priority_update={'true' if value.get('priority_update') else 'false'}\n")
        print(json.dumps(value))
        return 0
    except (CandidateError, KeyError, ValueError, UnicodeError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
