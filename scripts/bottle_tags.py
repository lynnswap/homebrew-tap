#!/usr/bin/env python3
"""Register the custom service bottle for its supported macOS baseline."""

import argparse
import json
from pathlib import Path


def register_bottles(directory):
    for path in directory.glob("*.bottle.json"):
        metadata = json.loads(path.read_text())
        for entry in metadata.values():
            if entry["formula"]["name"] != "custom-xcode-build-service":
                continue
            tags = entry["bottle"]["tags"]
            for tag in list(tags):
                if tag == "arm64_tahoe":
                    continue
                bottle = tags.pop(tag)
                old_filename = bottle["local_filename"]
                # The payload targets macOS 26; the receipt still records the build OS.
                old_suffix = f".{tag}.bottle"
                for field in ("filename", "local_filename"):
                    bottle[field] = bottle[field].replace(old_suffix, ".arm64_tahoe.bottle")
                (directory / old_filename).rename(directory / bottle["local_filename"])
                tags["arm64_tahoe"] = bottle
                path.write_text(json.dumps(metadata, indent=2) + "\n")
                path.rename(path.with_name(path.name.replace(old_suffix, ".arm64_tahoe.bottle")))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    register_bottles(parser.parse_args().directory)
