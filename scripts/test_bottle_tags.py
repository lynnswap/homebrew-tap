import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from bottle_tags import register_bottles


class BottleTagTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def bottle(self, name="custom-xcode-build-service", tag="arm64_golden_gate", rebuild=0):
        suffix = f".{rebuild}" if rebuild else ""
        filename = f"{name}--0.3.1.{tag}.bottle{suffix}.tar.gz"
        content = b"unchanged tested bottle bytes"
        (self.directory / filename).write_bytes(content)
        entry = {
            "formula": {"name": name, "tap_git_revision": "a" * 40},
            "bottle": {
                "root_url": "https://github.com/lynnswap/homebrew-tap/releases/download/custom-xcode-build-service-0.3.1",
                "rebuild": rebuild,
                "tags": {tag: {
                    "filename": filename.replace("--", "-"),
                    "local_filename": filename,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "tab": {"built_on": {"os_version": "macOS 27"}},
                }},
            },
        }
        metadata = {f"lynnswap/tap/{name}": entry}
        path = self.directory / f"{name}--0.3.1.{tag}.bottle.json"
        path.write_text(json.dumps(metadata))
        return path, metadata

    def test_service_bottle_keeps_tested_bytes_and_build_record_under_macos_26_tag(self):
        path, original = self.bottle()
        old_tag = original["lynnswap/tap/custom-xcode-build-service"]["bottle"]["tags"]["arm64_golden_gate"]
        content = (self.directory / old_tag["local_filename"]).read_bytes()
        register_bottles(self.directory)

        entry = json.loads(next(self.directory.glob("*.bottle.json")).read_text())["lynnswap/tap/custom-xcode-build-service"]
        tag = entry["bottle"]["tags"]["arm64_tahoe"]
        self.assertEqual((self.directory / tag["local_filename"]).read_bytes(), content)
        self.assertEqual(tag["sha256"], hashlib.sha256(content).hexdigest())
        self.assertEqual(tag["tab"], old_tag["tab"])
        self.assertEqual(entry["formula"], original["lynnswap/tap/custom-xcode-build-service"]["formula"])
        self.assertEqual(tag["filename"], "custom-xcode-build-service-0.3.1.arm64_tahoe.bottle.tar.gz")
        self.assertFalse(path.exists())
        self.assertFalse((self.directory / old_tag["local_filename"]).exists())

    def test_existing_baseline_bottle_is_unchanged(self):
        path, _ = self.bottle(tag="arm64_tahoe")
        content = path.read_bytes()
        register_bottles(self.directory)
        self.assertEqual(path.read_bytes(), content)

    def test_service_bottle_preserves_its_rebuild_number(self):
        self.bottle(rebuild=1)
        register_bottles(self.directory)
        entry = json.loads(next(self.directory.glob("*.bottle.json")).read_text())["lynnswap/tap/custom-xcode-build-service"]
        tag = entry["bottle"]["tags"]["arm64_tahoe"]
        self.assertEqual(entry["bottle"]["rebuild"], 1)
        self.assertEqual(tag["filename"], "custom-xcode-build-service-0.3.1.arm64_tahoe.bottle.1.tar.gz")
        self.assertEqual((self.directory / tag["local_filename"]).read_bytes(), b"unchanged tested bottle bytes")

    def test_other_formula_bottles_keep_their_tags(self):
        path, _ = self.bottle(name="privateheaderkit")
        content = path.read_bytes()
        register_bottles(self.directory)
        self.assertEqual(path.read_bytes(), content)
