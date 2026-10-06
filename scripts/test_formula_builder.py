import unittest

from approved_bottles import CandidateError
from formula_builder import builder


class FormulaBuilderTests(unittest.TestCase):
    def test_xcodemcpkit_uses_xcode_27_and_selects_its_own_installation_checks(self):
        value = builder([dict(filename="Formula/xcode-mcpkit.rb", status="added")])
        self.assertEqual(value["runner"], "xcode-27")
        self.assertEqual(value["custom_service"], "false")
        self.assertEqual(value["xcode_mcpkit"], "true")
        self.assertEqual(builder([dict(filename="Formula/custom-xcode-build-service.rb", status="modified")])["custom_service"], "true")

    def test_custom_service_installs_the_upstream_binary_on_macos_26(self):
        self.assertEqual(builder([dict(filename="Formula/custom-xcode-build-service.rb", status="added")])["runner"], "macos-26")

    def test_existing_privateheaderkit_delivery_keeps_its_macos_26_bottle(self):
        self.assertEqual(builder([dict(filename="Formula/privateheaderkit.rb", status="modified")])["runner"], "macos-26")

    def test_mixed_build_environments_require_separate_formula_prs(self):
        with self.assertRaises(CandidateError):
            builder([dict(filename=f"Formula/{name}.rb", status="modified")
                     for name in ("privateheaderkit", "custom-xcode-build-service")])

    def test_removals_and_non_formula_changes_do_not_select_a_builder(self):
        self.assertEqual(builder([dict(filename="Formula/custom-xcode-build-service.rb", status="removed"),
                                  dict(filename="README.md", status="modified")])["runner"], "macos-26")
