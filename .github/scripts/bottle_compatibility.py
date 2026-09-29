#!/usr/bin/env python3
"""Register unchanged bottles for tested platforms and verify ordinary installation."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


def archive_path(directory, name):
    if Path(name).name != name:
        raise ValueError(f"Bottle filename must be a basename: {name}")
    return directory / name


def verify_archive(path, expected):
    digest = hashlib.sha256()
    with path.open("rb") as archive:
        for chunk in iter(lambda: archive.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise ValueError(f"Bottle checksum mismatch: {path}")


def prepare(directory, configuration):
    matrix = []
    for json_path in sorted(directory.glob("*.bottle.json")):
        document = json.loads(json_path.read_text())
        for formula, entry in document.items():
            policy = configuration.get(entry["formula"]["name"])
            if policy is None:
                continue
            tags = entry["bottle"]["tags"]
            if len(tags) != 1:
                raise ValueError(f"Expected one build-platform bottle for {formula}")
            old_tag, bottle = next(iter(tags.items()))
            new_tag = policy["tag"]
            archive = archive_path(directory, bottle["local_filename"])
            verify_archive(archive, bottle["sha256"])
            if old_tag != new_tag:
                old_suffix, new_suffix = f".{old_tag}.bottle", f".{new_tag}.bottle"
                renamed = archive_path(directory, archive.name.replace(old_suffix, new_suffix))
                renamed_json = json_path.with_name(json_path.name.replace(old_suffix, new_suffix))
                if renamed == archive or renamed_json == json_path:
                    raise ValueError(f"Bottle filenames do not contain {old_tag}: {json_path}")
                if renamed.exists() or renamed_json.exists():
                    raise FileExistsError(f"Bottle target already exists: {renamed}")
                archive.rename(renamed)
                bottle["local_filename"] = renamed.name
                bottle["filename"] = bottle["filename"].replace(old_suffix, new_suffix)
                entry["bottle"]["tags"] = {new_tag: bottle}
                # Keep tab.built_on and the SBOM: the build still happened on the original host.
                renamed_json.write_text(json.dumps(document, indent=2) + "\n")
                json_path.unlink()
                json_path = renamed_json
            matrix.extend({"runner": runner, "bottle_json": json_path.name,
                           "formula": formula}
                          for runner in policy["runners"])
    return {"include": matrix}


def output(arguments):
    return subprocess.check_output(arguments, text=True).strip()


def test_bottle(json_path, formula):
    entry = json.loads(json_path.read_text())[formula]
    bottle, = entry["bottle"]["tags"].values()
    archive = archive_path(json_path.parent, bottle["local_filename"])
    verify_archive(archive, bottle["sha256"])
    subprocess.run(["brew", "trust", "--formula", formula], check=True)
    subprocess.run(["brew", "bottle", "--merge", "--write", "--no-commit", str(json_path)], check=True)
    cache = Path(output(["brew", "--cache", formula]))
    cache.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(archive, cache)
    # Do not force a bottle: this checks the same selection a normal installation uses.
    subprocess.run(["brew", "install", formula], check=True)
    info = json.loads(output(["brew", "info", "--json=v2", formula]))["formulae"][0]
    version = entry["formula"]["pkg_version"]
    if not any(item["version"] == version and item["poured_from_bottle"]
               for item in info["installed"]):
        raise RuntimeError(f"Expected {formula} {version} to be installed from the tested bottle")
    subprocess.run(["brew", "test", formula], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("--directory", type=Path, default=Path("."))
    prepare_parser.add_argument("--config", type=Path, required=True)
    prepare_parser.add_argument("--github-output", type=Path)
    test_parser = commands.add_parser("test")
    test_parser.add_argument("--json", type=Path, required=True)
    test_parser.add_argument("--formula", required=True)
    args = parser.parse_args()
    if args.operation == "prepare":
        matrix = prepare(args.directory, json.loads(args.config.read_text()))
        serialized = json.dumps(matrix, separators=(",", ":"))
        print(serialized)
        if args.github_output:
            with args.github_output.open("a") as target:
                target.write(f"matrix={serialized}\n")
                target.write(f"has_bottles={str(bool(matrix['include'])).lower()}\n")
                target.write(f"has_artifacts={str(any(args.directory.glob('*.bottle.json'))).lower()}\n")
    else:
        os.environ.update(HOMEBREW_NO_AUTO_UPDATE="1", HOMEBREW_NO_INSTALL_CLEANUP="1",
                          HOMEBREW_NO_AUTOREMOVE="1")
        test_bottle(args.json.resolve(), args.formula)


if __name__ == "__main__":
    main()
