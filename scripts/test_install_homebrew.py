"""Exercise the distributed /bin/sh entry point with isolated installations."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ENGINE = Path(__file__).with_name("install-homebrew.sh").read_text()


def installer(formula):
    return "#!/bin/sh\nexec /bin/bash -c " + shlex.quote(ENGINE) + " install.sh " + shlex.quote(formula) + ' "$@"\n'


class InstallerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="migration with spaces ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "home"
        self.bin = self.home / ".local/bin"
        self.bin.mkdir(parents=True)
        self.tools = self.root / "tools"
        self.tools.mkdir()
        self.brew = self.root / "brew"
        self.opt = self.brew / "opt/xcode-mcpkit"
        (self.opt / "bin").mkdir(parents=True)
        (self.opt / "libexec/XcodeMCPNativeHost.app").mkdir(parents=True)
        self.log = self.root / "calls"
        self.env = dict(os.environ, HOME=str(self.home), PATH=f"{self.tools}:/usr/bin:/bin", BREW_ROOT=str(self.brew),
                        FORMULA_OPT=str(self.opt), CALL_LOG=str(self.log))
        self.env.pop("PREFIX", None)
        self.env.pop("BINDIR", None)
        self.script("brew", 'echo "$*" >> "$CALL_LOG"\ncase "$*" in --prefix) echo "$BREW_ROOT";; --prefix\\ *) echo "$FORMULA_OPT";; esac')
        self.script("codesign", 'echo "Identifier=$(cat "$2/identity" 2>/dev/null || cat "$2")" >&2')
        for name in ("xcode-mcp-proxy", "xcode-mcp-proxy-server", "privateheaderkit", "custom-xcode-build-service"):
            target = self.opt / "bin" / name
            version_check = '[ "$1" = --tool-version ] || exit 64\n' if name == "privateheaderkit" else ""
            target.write_text('#!/bin/sh\n' + version_check + 'echo "' + name + ' $*" >> "$CALL_LOG"\nexit "${CLI_STATUS:-0}"\n')
            target.chmod(0o755)

    def script(self, name, body):
        path = self.tools / name
        path.write_text("#!/bin/sh\n" + body + "\n")
        path.chmod(0o755)

    def run_installer(self, formula="xcode-mcpkit", args=(), file=False):
        content = installer(formula)
        if file:
            path = self.root / "install.sh"
            path.write_text(content)
            command = ["/bin/sh", str(path), *args]
        else:
            command = ["/bin/sh", "-s", "--", *args]
        return subprocess.run(command, input=content, env=self.env, text=True, capture_output=True)

    def old_xcode(self):
        for name in ("xcode-mcp-proxy", "xcode-mcp-proxy-server"):
            (self.bin / name).write_text(name)
        app = self.bin / "XcodeMCPNativeHost.app"
        app.mkdir()
        (app / "identity").write_text("com.lynnswap.XcodeMCPNativeHost")

    def test_pipe_migrates_entry_points_and_retains_backup(self):
        self.old_xcode()
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ("xcode-mcp-proxy", "xcode-mcp-proxy-server", "XcodeMCPNativeHost.app"):
            self.assertTrue((self.bin / name).is_symlink())
        backups = list(self.bin.glob(".xcode-mcpkit-standalone-backup.*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "xcode-mcp-proxy").read_text(), "xcode-mcp-proxy")
        result = self.run_installer(file=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(list(self.bin.glob(".*backup.*"))), 1)

    def test_dry_run_has_no_side_effects(self):
        self.old_xcode()
        result = self.run_installer(args=("--dry-run",))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(self.bin / "xcode-mcp-proxy"), result.stdout)
        self.assertFalse(self.log.exists())
        self.assertFalse((self.bin / "xcode-mcp-proxy").is_symlink())

    def test_new_install_does_not_create_legacy_aliases(self):
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(self.bin.iterdir()), [])

    def test_failed_new_cli_leaves_old_installation(self):
        self.old_xcode()
        self.env["CLI_STATUS"] = "9"
        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.bin / "xcode-mcp-proxy").is_symlink())
        self.assertEqual(len(list(self.bin.iterdir())), 3)

    def test_unrelated_entry_prevents_partial_migration(self):
        self.old_xcode()
        (self.bin / "xcode-mcp-proxy-server").write_text("unrelated wrapper")
        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unrecognized", result.stderr)
        self.assertFalse((self.bin / "xcode-mcp-proxy").is_symlink())

    def test_failed_link_rolls_back_prior_replacements(self):
        self.old_xcode()
        self.script("ln", 'case "$3" in *xcode-mcp-proxy-server) exit 7;; esac\nexec /bin/ln "$@"')
        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Restoring", result.stderr)
        self.assertEqual((self.bin / "xcode-mcp-proxy").read_text(), "xcode-mcp-proxy")
        self.assertFalse((self.bin / "xcode-mcp-proxy-server").is_symlink())
        self.assertFalse((self.bin / ".lynnswap-homebrew-migration.lock").exists())

    def test_cohort_link_migrates_even_when_old_payload_is_missing(self):
        (self.bin / "privateheaderkit").symlink_to("../libexec/privateheaderkit/current/privateheaderkit")
        data = self.home / "PrivateHeaderKit/generated-headers/test.h"
        data.parent.mkdir(parents=True)
        data.write_text("generated")
        result = self.run_installer("privateheaderkit")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.bin / "privateheaderkit").resolve(), (self.opt / "bin/privateheaderkit").resolve())
        self.assertEqual(data.read_text(), "generated")

    def test_unrelated_symlink_is_retained(self):
        (self.bin / "privateheaderkit").symlink_to("/unrelated/privateheaderkit")
        result = self.run_installer("privateheaderkit")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(os.readlink(self.bin / "privateheaderkit"), "/unrelated/privateheaderkit")

    def test_payloads_remain_at_their_original_paths(self):
        payload = self.home / ".local/libexec/privateheaderkit/current/privateheaderkit"
        payload.parent.mkdir(parents=True)
        payload.write_text("old executable")
        (self.bin / "privateheaderkit").symlink_to("../libexec/privateheaderkit/current/privateheaderkit")
        result = self.run_installer("privateheaderkit", args=("--bindir", str(self.bin)))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload.read_text(), "old executable")

    def test_rollback_failure_reports_recoverable_backup(self):
        self.old_xcode()
        self.script("ln", 'exit 7')
        self.script("mv", 'case "$1" in *backup*) exit 8;; esac\nexec /bin/mv "$@"')
        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Rollback could not restore", result.stderr)
        backups = list(self.bin.glob(".*backup.*"))
        self.assertEqual((backups[0] / "xcode-mcp-proxy").read_text(), "xcode-mcp-proxy")

    def test_custom_directory_and_prefix(self):
        old = self.root / "custom prefix/bin"
        old.mkdir(parents=True)
        (old / "privateheaderkit").symlink_to("../libexec/privateheaderkit/current/privateheaderkit")
        result = self.run_installer("privateheaderkit", args=("--prefix", str(old.parent)), file=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((old / "privateheaderkit").resolve(), (self.opt / "bin/privateheaderkit").resolve())

    def test_custom_service_delegates_to_owner_cli(self):
        result = self.run_installer("custom-xcode-build-service")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("custom-xcode-build-service __migrate-standalone", self.log.read_text())

    def test_environment_bindir_is_retained_and_option_can_override_it(self):
        self.old_xcode()
        self.env["BINDIR"] = str(self.bin)
        self.env["PREFIX"] = "/not/the/installation"
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.bin / "xcode-mcp-proxy").is_symlink())
        result = self.run_installer(args=("--bindir", str(self.root / "absent"), "--dry-run"))
        self.assertIn(str(self.root / "absent"), result.stdout)

    def test_signal_after_move_restores_the_current_entry(self):
        self.old_xcode()
        self.script("mv", '/bin/mv "$@" || exit $?\ncase "$1" in *backup*) ;; *) kill -TERM "$PPID";; esac')
        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.bin / "xcode-mcp-proxy").read_text(), "xcode-mcp-proxy")
        self.assertFalse((self.bin / "xcode-mcp-proxy").is_symlink())

    def test_old_commands_in_homebrew_bin_are_retired_before_linking(self):
        self.bin = self.brew / "bin"
        self.bin.mkdir()
        self.old_xcode()
        self.script("brew", '''echo "$*" >> "$CALL_LOG"
case "$*" in
  --prefix) echo "$BREW_ROOT";;
  --prefix\\ *) echo "$FORMULA_OPT";;
  install\\ --skip-link\\ *) ;;
  install\\ *) exit 11;;
  link\\ *) for name in xcode-mcp-proxy xcode-mcp-proxy-server; do
    /bin/ln -s "$FORMULA_OPT/bin/$name" "$BREW_ROOT/bin/$name" || exit 12
  done;;
esac''')
        result = self.run_installer(args=("--bindir", str(self.bin)))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.bin / "xcode-mcp-proxy").is_symlink())

    def test_linker_signed_release_identity_is_recognized(self):
        self.old_xcode()
        (self.bin / "xcode-mcp-proxy").write_text("xcode-mcp-proxy-555549449cbb4e5e77f634a589d66569a9cb2199")
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.bin / "xcode-mcp-proxy").is_symlink())

    def test_already_linked_homebrew_still_recreates_retired_paths(self):
        self.bin = self.brew / "bin"
        self.bin.mkdir()
        self.old_xcode()
        result = self.run_installer(args=("--bindir", str(self.bin)))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.bin / "xcode-mcp-proxy").is_symlink())

    def test_privateheaderkit_prefix_overrides_environment_bindir(self):
        self.env["BINDIR"] = "/old/bin"
        result = self.run_installer("privateheaderkit", args=("--prefix", "/new", "--dry-run"))
        self.assertIn("Would inspect: /new/bin", result.stdout)
        self.assertNotIn("/old/bin", result.stdout)

    def test_early_source_installed_helper_identity_is_recognized(self):
        self.old_xcode()
        (self.bin / "XcodeMCPNativeHost.app/identity").write_text("com.apple.dt.mcp-server")
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.bin / "XcodeMCPNativeHost.app").is_symlink())

    def test_homebrew_keg_cannot_be_changed(self):
        keg = self.brew / "Cellar/xcode-mcpkit/1/bin"
        keg.mkdir(parents=True)
        (keg / "xcode-mcp-proxy").write_text("xcode-mcp-proxy")
        result = self.run_installer(args=("--bindir", str(keg)))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Refusing to change Homebrew", result.stderr)


if __name__ == "__main__":
    unittest.main()
