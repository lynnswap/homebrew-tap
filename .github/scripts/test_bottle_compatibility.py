import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import bottle_compatibility as compatibility


class BottleCompatibilityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.formula = "lynnswap/tap/privateheaderkit"
        self.contents = b"unchanged bottle archive"
        self.archive = self.root / "privateheaderkit--1.2.3.arm64_tahoe.bottle.tar.gz"
        self.archive.write_bytes(self.contents)
        self.metadata = self.root / "privateheaderkit--1.2.3.arm64_tahoe.bottle.json"
        self.entry = {
            "formula": {"name": "privateheaderkit", "pkg_version": "1.2.3"},
            "bottle": {"tags": {"arm64_tahoe": {
                "filename": "privateheaderkit-1.2.3.arm64_tahoe.bottle.tar.gz",
                "local_filename": self.archive.name,
                "sha256": hashlib.sha256(self.contents).hexdigest(),
                "tab": {"built_on": {"os_version": "macOS 26"}},
                "sbom": {"creationInfo": {"creators": ["Tool: Xcode 27"]}},
            }}},
        }
        self.metadata.write_text(json.dumps({self.formula: self.entry}))
        self.policy = {"privateheaderkit": {"tag": "arm64_sequoia",
                                           "runners": ["macos-15", "macos-26"]}}

    def test_registration_preserves_archive_checksum_and_build_provenance(self):
        original = self.entry["bottle"]["tags"]["arm64_tahoe"]
        matrix = compatibility.prepare(self.root, self.policy)
        new_metadata = self.root / matrix["include"][0]["bottle_json"]
        new = json.loads(new_metadata.read_text())[self.formula]["bottle"]["tags"]["arm64_sequoia"]
        self.assertEqual((self.root / new["local_filename"]).read_bytes(), self.contents)
        self.assertEqual(new["filename"], "privateheaderkit-1.2.3.arm64_sequoia.bottle.tar.gz")
        for key in ("sha256", "tab", "sbom"):
            self.assertEqual(new[key], original[key])
        self.assertFalse(self.archive.exists())
        self.assertFalse(self.metadata.exists())
        self.assertEqual([item["runner"] for item in matrix["include"]], ["macos-15", "macos-26"])

    def test_other_formulae_keep_their_original_platform(self):
        before = self.metadata.read_bytes()
        self.assertEqual(compatibility.prepare(self.root, {}), {"include": []})
        self.assertEqual(self.metadata.read_bytes(), before)
        self.assertEqual(self.archive.read_bytes(), self.contents)

    def test_corrupt_archive_is_rejected_before_registration(self):
        self.archive.write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            compatibility.prepare(self.root, self.policy)
        self.assertTrue(self.metadata.exists())

    def test_installation_uses_normal_selection_and_checks_the_receipt(self):
        for poured in (True, False):
            with self.subTest(poured=poured):
                receipt = {"formulae": [{"installed": [
                    {"version": "1.2.3", "poured_from_bottle": poured}]}]}
                with patch.object(compatibility, "output", side_effect=[
                        str(self.root / "cache/archive.tar.gz"), json.dumps(receipt)]), \
                     patch.object(compatibility.subprocess, "run") as run:
                    if poured:
                        compatibility.test_bottle(self.metadata, self.formula)
                        run.assert_any_call(["brew", "test", self.formula], check=True)
                    else:
                        with self.assertRaisesRegex(RuntimeError, "installed from the tested bottle"):
                            compatibility.test_bottle(self.metadata, self.formula)
                    run.assert_any_call(["brew", "install", self.formula], check=True)
                    self.assertFalse(any("--force-bottle" in call.args[0] for call in run.call_args_list))


if __name__ == "__main__":
    unittest.main()
