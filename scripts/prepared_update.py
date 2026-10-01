#!/usr/bin/env python3
"""Discover unproposed public source tags without running Renovate or Formula code."""

import argparse
import base64
import json
from pathlib import Path
import re
import sys

from approved_bottles import CandidateError, GitHub

SOURCE_REPOSITORY = "lynnswap/PrivateHeaderKit"
FORMULA = "Formula/privateheaderkit.rb"
SOURCE_PREFIX = f"https://github.com/{SOURCE_REPOSITORY}/archive/refs/tags/"


def stable_version(tag):
    match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", tag)
    return tuple(map(int, match.groups())) if match else None


def source_tag(entry):
    formula = base64.b64decode(entry["content"]).decode("utf-8")
    urls = re.findall(r'''^  url ["']([^"'\n]+)["'](?:\s+#.*)?$''', formula, re.MULTILINE)
    if len(urls) != 1 or not urls[0].startswith(SOURCE_PREFIX) or not urls[0].endswith(".tar.gz"):
        raise CandidateError("PrivateHeaderKit discovery requires a literal public tag-archive URL.")
    tag = urls[0][len(SOURCE_PREFIX):-len(".tar.gz")]
    if stable_version(tag) is None:
        raise CandidateError("The maintained Formula must name a stable source tag.")
    return tag


def candidate(tap, source):
    current = source_tag(tap.api(f"contents/{FORMULA}?ref=main"))
    tags = [item["ref"].removeprefix("refs/tags/")
            for item in source.api("git/matching-refs/tags/v")]
    stable = [tag for tag in tags if stable_version(tag) is not None]
    latest = max(stable, key=stable_version) if stable else current
    value = dict(current=current, latest=latest, update=False)
    if stable_version(latest) <= stable_version(current):
        return dict(value, reason="The published Formula already covers the available stable tags.")
    for pull in tap.pages("pulls?state=open&base=main"):
        if not any(item["filename"] == FORMULA for item in tap.pages(f"pulls/{pull['number']}/files")):
            continue
        head = pull["head"]
        if head["repo"] is None:
            continue
        proposed = GitHub(head["repo"]["full_name"]).api(f"contents/{FORMULA}?ref={head['sha']}")
        try:
            proposed_tag = source_tag(proposed)
        except CandidateError:
            continue
        if proposed_tag == latest:
            return dict(value, pull_request=pull["number"], reason="The source update already has an open Formula PR.")
    return dict(value, update=True, reason="A public stable source tag needs a Formula proposal.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--maintenance", action="store_true")
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    try:
        value = (dict(update=True, reason="Regular or manually requested Renovate maintenance.")
                 if args.maintenance else candidate(GitHub(args.repo), GitHub(SOURCE_REPOSITORY)))
        if args.github_output:
            with args.github_output.open("a") as output:
                output.write(f"update={'true' if value['update'] else 'false'}\n")
        print(json.dumps(value))
        return 0
    except (CandidateError, KeyError, ValueError, UnicodeError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
