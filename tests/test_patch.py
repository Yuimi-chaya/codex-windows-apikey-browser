import json
import msvcrt
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import codex_browser_patch as patch
import browser_unlocker_gui as gui


KEY = "0123456789abcdef"
ANCHOR = "new eh(r,this.clientApi,()=>je(this.runtime),this.turnEndedTracker,sv)"


def descriptor(root, key=KEY):
    base = root / key
    node = base / "bin/node.exe"
    return {"mcpServers": {"cua_repl": {
        "command": str(node),
        "args": [str(base / patch.ENTRY)],
        "env": {
            "NODE_REPL_NODE_PATH": str(node),
            "CUA_REPL_NODE_REPL_PATH": str(base / "bin/node_repl.exe"),
            "NODE_REPL_TRUSTED_SERVICES": json.dumps(
                {"browser": "@oai/browser-desktop/service"}),
            "CUA_REPL_ENABLED_SURFACES": "browser",
        },
    }}}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="browser-patch-test-")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.home = root / "home"
        self.runtime_root = root / "runtime"
        self.state = root / "state"
        self.cpp = root / "cpp-state"
        self.runtime = self.runtime_root / KEY
        self.service = self.runtime / patch.SERVICE
        self.original = ("prefix;" + ANCHOR + ";suffix").encode()
        files = {
            "manifest.json": b"fixture-manifest",
            "bin/node.exe": b"fixture-node",
            "bin/node_repl.exe": b"fixture-worker",
            patch.ENTRY: b"fixture-entry",
            patch.SERVICE: self.original,
        }
        for name, contents in files.items():
            target = self.runtime / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(contents)
        self.descriptor_dir = self.home / "plugins/cache/openai-bundled/unified-computer-use/test"
        self.descriptor_dir.mkdir(parents=True)
        (self.descriptor_dir / ".mcp.json").write_text(
            json.dumps(descriptor(self.runtime_root)), encoding="utf-8")
        self.contract = {
            "version": "fixture",
            "service": patch.sha(self.original),
            "worker": patch.sha(files["bin/node_repl.exe"]),
            "node": patch.sha(files["bin/node.exe"]),
            "anchor": ANCHOR,
            "binding": "new eh(r,this.clientApi,()=>je(this.runtime),this.turnEndedTracker,"
                       "cppNativeIdentificationReader(this.runtime,sv,je,{path}))",
        }
        self.pins = mock.patch.multiple(
            patch, CONTRACTS={patch.sha(files["manifest.json"]): self.contract},
            ENTRY_SHA=patch.sha(files[patch.ENTRY]))
        self.pins.start()
        self.addCleanup(self.pins.stop)
        self.selection = (KEY, str(self.home))

    def cpp_state(self, enabled=False):
        self.cpp.mkdir(exist_ok=True)
        (self.cpp / "owner.lock").touch()
        (self.cpp / "monitor.lock").write_text(json.dumps({
            "schema": 1, "generation": "00000000-0000-0000-0000-000000000001",
            "state": "restored",
        }), encoding="utf-8")
        (self.cpp / "control.json").write_bytes(patch.control_bytes(enabled))

    def cpp_journal(self, enabled=True):
        self.cpp_state(enabled)
        candidate = patch.transform(self.original, self.contract, self.cpp / "control.json")
        directory = self.cpp / KEY
        directory.mkdir(exist_ok=True)
        (directory / "original.mjs").write_bytes(self.original)
        (directory / ("candidate-" + patch.sha(candidate) + ".mjs")).write_bytes(candidate)
        seconds, nanos = divmod(self.service.stat().st_mtime_ns, 1_000_000_000)
        (directory / "journal.json").write_text(json.dumps({
            "schema": 1, "originalSha": patch.sha(self.original),
            "candidateSha": patch.sha(candidate),
            "modifiedSecs": seconds, "modifiedNanos": nanos,
        }), encoding="utf-8")
        return candidate

    def test_unified_cpp_roundtrip_and_read_only_inspection(self):
        self.cpp_state()
        before = self.service.stat().st_mtime_ns
        snapshot, selection = gui.inspect(self.home, self.runtime_root, self.state, self.cpp)
        self.assertEqual(self.selection, selection)
        self.assertEqual(("original", "Codex++"), (snapshot.code, snapshot.owner))
        self.assertEqual(str(self.cpp), snapshot.recovery_root)
        self.assertTrue(snapshot.can_apply)
        self.assertEqual("restored", json.loads((self.cpp / "monitor.lock").read_text())
                         ["state"])
        self.assertEqual(0, (self.cpp / "owner.lock").stat().st_size)
        self.assertFalse(self.state.exists())
        patch.apply_unified(self.runtime_root, self.state, self.selection, self.cpp)
        candidate = patch.transform(self.original, self.contract, self.cpp / "control.json")
        self.assertEqual(candidate, self.service.read_bytes())
        self.assertFalse(self.state.exists())
        self.assertTrue(json.loads((self.cpp / "control.json").read_text())
                        ["requireIdentification"])
        patched, _ = gui.inspect(self.home, self.runtime_root, self.state, self.cpp)
        self.assertEqual("patched", patched.code)
        self.assertTrue(patched.can_restore)
        self.assertIn("launcher", gui.detail_text(patched))
        patch.apply_unified(self.runtime_root, self.state, self.selection, self.cpp)
        (self.cpp / "control.json").write_bytes(patch.control_bytes(False))
        disabled = patch.inspect_status(self.runtime_root, self.state, self.selection, self.cpp)
        self.assertEqual("disabled", disabled.code)
        self.assertTrue(disabled.can_apply)
        patch.restore_unified(self.runtime_root, self.state, self.cpp)
        self.assertEqual(self.original, self.service.read_bytes())
        self.assertEqual(before, self.service.stat().st_mtime_ns)
        self.assertFalse(json.loads((self.cpp / "control.json").read_text())
                         ["requireIdentification"])
        patch.apply_unified(self.runtime_root, self.state, self.selection, self.cpp)
        self.assertEqual(candidate, self.service.read_bytes())

    def test_unified_existing_cpp_journal_and_component_drift_restoration(self):
        candidate = self.cpp_journal()
        self.service.write_bytes(candidate)
        snapshot = patch.inspect_status(self.runtime_root, self.state, self.selection, self.cpp)
        self.assertEqual("patched", snapshot.code)
        (self.runtime / "bin/node_repl.exe").write_bytes(b"new worker")
        snapshot = patch.inspect_status(self.runtime_root, self.state, self.selection, self.cpp)
        self.assertEqual("unsupported", snapshot.code)
        self.assertFalse(snapshot.can_apply)
        self.assertTrue(snapshot.can_restore)
        patch.restore_unified(self.runtime_root, self.state, self.cpp)
        self.assertEqual(self.original, self.service.read_bytes())

    def test_unified_cpp_tamper_and_orphan_refuse_writes(self):
        candidate = self.cpp_journal()
        self.service.write_bytes(candidate)
        (self.cpp / KEY / "journal.json").write_text("{}", encoding="utf-8")
        snapshot = patch.inspect_status(self.runtime_root, self.state, self.selection, self.cpp)
        self.assertEqual("conflict", snapshot.code)
        self.assertFalse(snapshot.can_restore)
        with self.assertRaises(patch.Refused):
            patch.restore_unified(self.runtime_root, self.state, self.cpp)
        self.assertEqual(candidate, self.service.read_bytes())
        self.assertTrue(json.loads((self.cpp / "control.json").read_text())
                        ["requireIdentification"])
        (self.cpp / KEY / "journal.json").unlink()
        with self.assertRaises(patch.Refused):
            patch.restore_unified(self.runtime_root, self.state, self.cpp)
        self.assertEqual(candidate, self.service.read_bytes())

    def test_unified_cpp_monitor_blocks_and_status_does_not_write(self):
        self.cpp_state()
        monitor = self.cpp / "monitor.lock"
        with monitor.open("w+b") as stream:
            stream.write(b"x")
            stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            try:
                snapshot = patch.inspect_status(
                    self.runtime_root, self.state, self.selection, self.cpp)
                self.assertEqual("running", snapshot.code)
                self.assertFalse(snapshot.can_apply)
                with self.assertRaises(patch.Refused):
                    patch.apply_unified(self.runtime_root, self.state, self.selection, self.cpp)
                self.assertEqual(self.original, self.service.read_bytes())
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)

    def test_unified_cpp_missing_monitor_is_not_created(self):
        self.cpp_state()
        (self.cpp / "monitor.lock").unlink()
        snapshot = patch.inspect_status(self.runtime_root, self.state, self.selection, self.cpp)
        self.assertEqual("conflict", snapshot.code)
        self.assertFalse(snapshot.can_apply)
        with self.assertRaisesRegex(patch.Refused, "no monitor lock"):
            patch.apply_unified(self.runtime_root, self.state, self.selection, self.cpp)
        self.assertFalse((self.cpp / "monitor.lock").exists())
        self.assertEqual(self.original, self.service.read_bytes())

    def test_unified_unfinished_monitor_receipt_is_refused(self):
        self.cpp_state()
        receipt = self.cpp / "monitor.lock"
        for contents in (b"", b'{"schema":1,"generation":"bad","state":"restored"}',
                         b'{"schema":1,"generation":"00000000-0000-0000-0000-000000000001",'
                         b'"state":"active"}'):
            receipt.write_bytes(contents)
            snapshot = patch.inspect_status(self.runtime_root, self.state, self.selection, self.cpp)
            self.assertEqual("conflict", snapshot.code)
            with self.assertRaises(patch.Refused):
                patch.apply_unified(self.runtime_root, self.state, self.selection, self.cpp)
            self.assertEqual(contents, receipt.read_bytes())
            self.assertEqual(self.original, self.service.read_bytes())

    def test_unified_cpp_transaction_lock_blocks_actions(self):
        self.cpp_state()
        with (self.cpp / "owner.lock").open("r+b") as stream:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            try:
                snapshot = patch.inspect_status(
                    self.runtime_root, self.state, self.selection, self.cpp)
                self.assertEqual("running", snapshot.code)
                with self.assertRaises(patch.Refused):
                    patch.apply_unified(self.runtime_root, self.state, self.selection, self.cpp)
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        self.assertEqual(self.original, self.service.read_bytes())

    def test_unified_cpp_write_failure_keeps_control_disabled(self):
        self.cpp_state()
        real_write = patch.atomic_write

        def fail_service(path, data, mtime_ns=None):
            if path == self.service:
                raise OSError("simulated service lock")
            return real_write(path, data, mtime_ns)

        with mock.patch.object(patch, "atomic_write", side_effect=fail_service):
            with self.assertRaises(OSError):
                patch.apply_unified(self.runtime_root, self.state, self.selection, self.cpp)
        self.assertEqual(self.original, self.service.read_bytes())
        self.assertFalse(json.loads((self.cpp / "control.json").read_text())
                         ["requireIdentification"])
        patch.apply_unified(self.runtime_root, self.state, self.selection, self.cpp)
        self.assertNotEqual(self.original, self.service.read_bytes())

    def test_unified_reapply_uses_new_original_timestamp(self):
        self.cpp_state()
        patch.apply_unified(self.runtime_root, self.state, self.selection, self.cpp)
        patch.restore_unified(self.runtime_root, self.state, self.cpp)
        updated = self.service.stat().st_mtime_ns - 2_000_000_000
        os.utime(self.service, ns=(updated, updated))
        patch.apply_unified(self.runtime_root, self.state, self.selection, self.cpp)
        patch.restore_unified(self.runtime_root, self.state, self.cpp)
        self.assertEqual(updated, self.service.stat().st_mtime_ns)

    def test_unified_standalone_restore_after_cpp_state_appears(self):
        patch.apply(self.runtime_root, self.state, self.selection)
        candidate = self.service.read_bytes()
        self.cpp_state()
        snapshot = patch.inspect_status(self.runtime_root, self.state, self.selection, self.cpp)
        self.assertEqual("standalone", snapshot.owner)
        self.assertTrue(snapshot.can_restore)
        self.assertFalse(snapshot.can_apply)
        patch.restore_unified(self.runtime_root, self.state, self.cpp)
        self.assertEqual(self.original, self.service.read_bytes())
        patch.apply_unified(self.runtime_root, self.state, self.selection, self.cpp)
        self.assertNotEqual(candidate, self.service.read_bytes())
        self.assertEqual(self.original, (self.state / KEY / "original.mjs").read_bytes())

    def test_unified_two_active_owners_or_external_change_refused(self):
        patch.apply(self.runtime_root, self.state, self.selection)
        standalone_candidate = self.service.read_bytes()
        self.cpp_journal()
        snapshot = patch.inspect_status(self.runtime_root, self.state, self.selection, self.cpp)
        self.assertEqual("conflict", snapshot.code)
        self.assertFalse(snapshot.can_restore)
        with self.assertRaises(patch.Refused):
            patch.restore_unified(self.runtime_root, self.state, self.cpp)
        self.assertEqual(standalone_candidate, self.service.read_bytes())
        patch.restore(self.runtime_root, self.state)
        self.service.write_bytes(b"foreign")
        snapshot = patch.inspect_status(self.runtime_root, self.state, self.selection, self.cpp)
        self.assertEqual("conflict", snapshot.code)
        with self.assertRaises(patch.Refused):
            patch.apply_unified(self.runtime_root, self.state, self.selection, self.cpp)
        self.assertEqual(b"foreign", self.service.read_bytes())

    def test_unified_process_guard_precedes_locked_service_read(self):
        self.cpp_state()
        with mock.patch.object(patch, "require_offline",
                               side_effect=patch.Refused("Codex process is running")):
            with mock.patch.object(patch, "read_regular",
                                   side_effect=AssertionError("must not read a locked service")):
                snapshot = patch.inspect_status(
                    self.runtime_root, self.state, self.selection, self.cpp)
        self.assertEqual("running", snapshot.code)
        self.assertIn("Codex process", snapshot.detail)

    def test_unified_missing_descriptor_keeps_cpp_restore(self):
        candidate = self.cpp_journal()
        self.service.write_bytes(candidate)
        (self.descriptor_dir / ".mcp.json").write_text("{bad", encoding="utf-8")
        snapshot, selection = gui.inspect(self.home, self.runtime_root, self.state, self.cpp)
        self.assertIsNone(selection)
        self.assertEqual("Codex++", snapshot.owner)
        self.assertTrue(snapshot.can_restore)
        self.assertFalse(snapshot.can_apply)
        patch.restore_unified(self.runtime_root, self.state, self.cpp)
        self.assertEqual(self.original, self.service.read_bytes())

    def test_unified_malformed_descriptor_does_not_mask_running_state(self):
        self.cpp_state()
        (self.descriptor_dir / ".mcp.json").write_text("{bad", encoding="utf-8")
        with mock.patch.object(patch, "require_offline",
                               side_effect=patch.Refused("Codex process is running")):
            snapshot, selection = gui.inspect(
                self.home, self.runtime_root, self.state, self.cpp)
        self.assertIsNone(selection)
        self.assertEqual("running", snapshot.code)
        self.assertIn("descriptor", snapshot.detail)

    def test_unified_missing_control_can_be_restored(self):
        candidate = self.cpp_journal()
        self.service.write_bytes(candidate)
        (self.cpp / "control.json").unlink()
        snapshot = patch.inspect_status(self.runtime_root, self.state, self.selection, self.cpp)
        self.assertEqual("disabled", snapshot.code)
        self.assertTrue(snapshot.can_restore)
        patch.restore_unified(self.runtime_root, self.state, self.cpp)
        self.assertEqual(self.original, self.service.read_bytes())

    def test_unified_restored_standalone_record_then_cpp_owner(self):
        patch.apply(self.runtime_root, self.state, self.selection)
        patch.restore(self.runtime_root, self.state)
        self.cpp_state()
        snapshot = patch.inspect_status(self.runtime_root, self.state, self.selection, self.cpp)
        self.assertEqual("Codex++", snapshot.owner)
        self.assertTrue(snapshot.can_apply)
        patch.apply_unified(self.runtime_root, self.state, self.selection, self.cpp)
        self.assertEqual("patched", patch.inspect_status(
            self.runtime_root, self.state, self.selection, self.cpp).code)

    def test_unified_cpp_unknown_entry_and_failure_leave_control_unchanged(self):
        candidate = self.cpp_journal()
        self.service.write_bytes(candidate)
        (self.cpp / "unexpected.txt").write_text("foreign", encoding="utf-8")
        snapshot = patch.inspect_status(self.runtime_root, self.state, self.selection, self.cpp)
        self.assertEqual("conflict", snapshot.code)
        self.assertFalse(snapshot.can_restore)
        with self.assertRaises(patch.Refused):
            patch.restore_unified(self.runtime_root, self.state, self.cpp)
        self.assertEqual(candidate, self.service.read_bytes())
        self.assertTrue(json.loads((self.cpp / "control.json").read_text())
                        ["requireIdentification"])

    def test_status_is_read_only_and_roundtrip_is_idempotent(self):
        patch.status(self.runtime_root, self.state, self.selection)
        self.assertFalse(self.state.exists())
        before_mtime = self.service.stat().st_mtime_ns
        patch.apply(self.runtime_root, self.state, self.selection)
        modified = self.service.read_bytes()
        self.assertEqual(modified, patch.transform(self.original, self.contract,
                                                   self.state / "control.json"))
        self.assertEqual(self.original,
                         (self.state / KEY / "original.mjs").read_bytes())
        self.assertTrue(json.loads((self.state / "control.json").read_text())
                        ["requireIdentification"])
        patch.apply(self.runtime_root, self.state, self.selection)
        self.assertEqual(modified, self.service.read_bytes())
        patch.restore(self.runtime_root, self.state)
        self.assertEqual(self.original, self.service.read_bytes())
        self.assertEqual(before_mtime, self.service.stat().st_mtime_ns)
        self.assertFalse(json.loads((self.state / "control.json").read_text())
                         ["requireIdentification"])
        patch.restore(self.runtime_root, self.state)
        patch.apply(self.runtime_root, self.state, self.selection)
        patch.restore(self.runtime_root, self.state)
        self.assertEqual(self.original, self.service.read_bytes())

    def test_gui_status_transitions_are_read_only(self):
        missing, selection = gui.inspect(self.home, self.runtime_root, self.state)
        self.assertEqual(self.selection, selection)
        self.assertEqual("original", missing.code)
        self.assertEqual("fixture", missing.version)
        self.assertTrue(missing.can_apply)
        self.assertFalse(missing.can_restore)
        self.assertFalse(self.state.exists())

        patch.apply(self.runtime_root, self.state, self.selection)
        prepared, _ = gui.inspect(self.home, self.runtime_root, self.state)
        self.assertEqual("patched", prepared.code)
        self.assertFalse(prepared.can_apply)
        self.assertTrue(prepared.can_restore)

        (self.state / "control.json").write_bytes(patch.control_bytes(False))
        disabled, _ = gui.inspect(self.home, self.runtime_root, self.state)
        self.assertEqual("disabled", disabled.code)
        self.assertTrue(disabled.can_apply)
        self.assertTrue(disabled.can_restore)
        patch.restore(self.runtime_root, self.state)
        restored, _ = gui.inspect(self.home, self.runtime_root, self.state)
        self.assertEqual("original", restored.code)
        self.assertTrue(restored.can_apply)
        self.assertTrue(restored.can_restore)

    def test_gui_status_refuses_foreign_or_corrupt_state(self):
        self.state.mkdir()
        (self.state / "foreign.txt").write_text("leave alone", encoding="utf-8")
        state = patch.inspect_status(self.runtime_root, self.state, self.selection)
        self.assertEqual("conflict", state.code)
        self.assertFalse(state.can_apply)
        self.assertFalse(state.can_restore)
        self.assertEqual(b"fixture-manifest", (self.runtime / "manifest.json").read_bytes())

    def test_gui_status_tracks_orphan_and_corrupt_owner(self):
        patch.apply(self.runtime_root, self.state, self.selection)
        (self.state / "owner.json").unlink()
        recoverable = patch.inspect_status(self.runtime_root, self.state, self.selection)
        self.assertTrue(recoverable.can_restore)
        self.assertFalse(recoverable.can_apply)
        (self.state / "owner.json").write_bytes(b"foreign")
        conflict = patch.inspect_status(self.runtime_root, self.state, self.selection)
        self.assertEqual("conflict", conflict.code)
        self.assertFalse(conflict.can_restore)

    def test_gui_status_unknown_component_and_external_change(self):
        self.service.write_bytes(b"foreign adapter")
        changed = patch.inspect_status(self.runtime_root, self.state, self.selection)
        self.assertEqual("conflict", changed.code)
        self.assertFalse(changed.can_apply)
        self.service.write_bytes(self.original)
        (self.runtime / "bin/node_repl.exe").write_bytes(b"different")
        unknown = patch.inspect_status(self.runtime_root, self.state, self.selection)
        self.assertEqual("unsupported", unknown.code)
        self.assertFalse(unknown.can_apply)

    def test_gui_status_blocks_live_write_while_running(self):
        with mock.patch.object(patch, "require_offline",
                               side_effect=patch.Refused("Codex is still running")):
            state = patch.inspect_status(self.runtime_root, self.state, self.selection)
        self.assertEqual("running", state.code)
        self.assertFalse(state.can_apply)
        self.assertFalse(state.can_restore)

    def test_gui_no_descriptor_keeps_verified_recovery(self):
        patch.apply(self.runtime_root, self.state, self.selection)
        snapshot = patch.inspect_status(self.runtime_root, self.state, None)
        self.assertEqual("missing", snapshot.code)
        self.assertTrue(snapshot.can_restore)

    def test_gui_malformed_descriptor_does_not_hide_restore(self):
        patch.apply(self.runtime_root, self.state, self.selection)
        (self.descriptor_dir / ".mcp.json").write_bytes(b"{broken")
        snapshot, selection = gui.inspect(self.home, self.runtime_root, self.state)
        self.assertIsNone(selection)
        self.assertIn("descriptor", snapshot.detail)
        self.assertTrue(snapshot.can_restore)
        self.assertFalse(snapshot.can_apply)

    def test_gui_status_disables_restore_when_another_cache_is_orphaned(self):
        patch.apply(self.runtime_root, self.state, self.selection)
        other = self.runtime_root / "fedcba9876543210" / patch.SERVICE
        other.parent.mkdir(parents=True)
        other.write_bytes(b"cppNativeIdentificationReader orphan")
        snapshot = patch.inspect_status(self.runtime_root, self.state, self.selection)
        self.assertEqual("conflict", snapshot.code)
        self.assertFalse(snapshot.can_restore)
        self.assertIn("no matching recovery journal", snapshot.detail)

    def test_unknown_component_never_writes(self):
        (self.runtime / "bin/node_repl.exe").write_bytes(b"changed")
        with self.assertRaises(patch.Refused):
            patch.apply(self.runtime_root, self.state, self.selection)
        self.assertFalse(self.state.exists())
        self.assertEqual(self.original, self.service.read_bytes())

    def test_component_drift_disables_previously_enabled_control(self):
        patch.apply(self.runtime_root, self.state, self.selection)
        candidate = self.service.read_bytes()
        (self.runtime / "bin/node_repl.exe").write_bytes(b"replaced worker")
        with self.assertRaises(patch.Refused):
            patch.apply(self.runtime_root, self.state, self.selection)
        self.assertEqual(candidate, self.service.read_bytes())
        self.assertFalse(json.loads((self.state / "control.json").read_text())
                         ["requireIdentification"])

    def test_unknown_or_other_adapter_is_refused(self):
        self.service.write_bytes(self.original + b"// external patch")
        with self.assertRaises(patch.Refused):
            patch.apply(self.runtime_root, self.state, self.selection)
        self.assertEqual(self.original + b"// external patch", self.service.read_bytes())
        self.assertFalse(self.state.exists())

    def test_external_change_blocks_restore_and_disables_control(self):
        patch.apply(self.runtime_root, self.state, self.selection)
        self.service.write_bytes(b"external edit")
        with self.assertRaises(patch.Refused):
            patch.restore(self.runtime_root, self.state)
        self.assertEqual(b"external edit", self.service.read_bytes())
        self.assertFalse(json.loads((self.state / "control.json").read_text())
                         ["requireIdentification"])
        self.assertEqual(self.original, (self.state / KEY / "original.mjs").read_bytes())

    def test_tampered_backup_blocks_restoration(self):
        patch.apply(self.runtime_root, self.state, self.selection)
        candidate = self.service.read_bytes()
        (self.state / KEY / "original.mjs").write_bytes(b"bad backup")
        with self.assertRaises(patch.Refused):
            patch.restore(self.runtime_root, self.state)
        self.assertEqual(candidate, self.service.read_bytes())

    def test_ambiguous_descriptors_and_path_escape(self):
        data = descriptor(self.runtime_root)
        data["mcpServers"]["cua_repl"]["command"] = str(
            self.runtime_root / KEY / "bin/../bin/node.exe")
        with self.assertRaises(patch.Refused):
            patch.descriptor_key(data, self.runtime_root)
        other = self.descriptor_dir.parent / "other"
        other.mkdir()
        (other / ".mcp.json").write_text(
            json.dumps(descriptor(self.runtime_root, "fedcba9876543210")), encoding="utf-8")
        with self.assertRaises(patch.Refused):
            patch.discover(self.home, self.runtime_root)
        self.assertFalse(self.state.exists())

    def test_removed_runtime_is_not_recreated(self):
        patch.apply(self.runtime_root, self.state, self.selection)
        self.service.unlink()
        patch.restore(self.runtime_root, self.state)
        self.assertFalse(self.service.exists())

    def test_recovery_can_live_on_another_drive_but_not_in_cache(self):
        self.assertTrue(patch.outside_runtime(Path("C:/cache"), Path("D:/backups")))
        self.assertFalse(patch.outside_runtime(Path("C:/cache"), Path("C:/cache/backups")))
        self.assertFalse(patch.outside_runtime(Path("C:/cache"), Path("C:/cache")))
        self.assertTrue(patch.outside_runtime(Path("C:/cache"), Path("C:/other")))
        cpp_state = Path.home() / ".codex-session-delete/native-browser-identification"
        with self.assertRaises(patch.Refused):
            patch.validate_locations(self.runtime_root, cpp_state)
        with self.assertRaises(patch.Refused):
            patch.validate_locations(self.runtime_root, cpp_state / "nested")

    def test_wrong_recovery_root_or_missing_journal_is_not_reported_as_restored(self):
        patch.apply(self.runtime_root, self.state, self.selection)
        candidate = self.service.read_bytes()
        wrong = self.state.parent / "wrong-state"
        with self.assertRaises(patch.Refused):
            patch.restore(self.runtime_root, wrong)
        self.assertFalse(wrong.exists())
        self.assertEqual(candidate, self.service.read_bytes())
        (self.state / KEY / "journal.json").unlink()
        with self.assertRaises(patch.Refused):
            patch.restore(self.runtime_root, self.state)
        self.assertEqual(candidate, self.service.read_bytes())
        self.assertFalse(json.loads((self.state / "control.json").read_text())
                         ["requireIdentification"])

    def test_foreign_recovery_directory_is_not_claimed(self):
        self.state.mkdir()
        (self.state / "foreign.txt").write_text("do not touch", encoding="utf-8")
        with self.assertRaises(patch.Refused):
            patch.apply(self.runtime_root, self.state, self.selection)
        self.assertEqual(["foreign.txt"], [item.name for item in self.state.iterdir()])
        self.assertEqual(self.original, self.service.read_bytes())

    def test_live_process_guard_refuses_running_app(self):
        actual_root = Path(os.environ["LOCALAPPDATA"]) / "OpenAI/Codex/runtimes/cua_node"
        result = subprocess.CompletedProcess(
            ["tasklist.exe"], 0, '"ChatGPT.exe","123","Console","1","100 K"\n')
        with mock.patch.object(patch.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(patch.Refused, "chatgpt.exe"):
                patch.require_offline(actual_root)
        with mock.patch.object(patch.subprocess, "run",
                               side_effect=FileNotFoundError("tasklist")):
            with self.assertRaises(patch.Refused):
                patch.require_offline(actual_root)

    def test_missing_owner_marker_can_recover_from_verified_journal(self):
        patch.apply(self.runtime_root, self.state, self.selection)
        (self.state / "owner.json").unlink()
        patch.restore(self.runtime_root, self.state)
        self.assertEqual(self.original, self.service.read_bytes())
        self.assertTrue(patch.owns_state(self.state))
        self.assertFalse(json.loads((self.state / "control.json").read_text())
                         ["requireIdentification"])

    def test_corrupt_owner_or_missing_journal_disables_recognizable_control(self):
        patch.apply(self.runtime_root, self.state, self.selection)
        candidate = self.service.read_bytes()
        (self.state / "owner.json").write_bytes(b"wrong owner")
        with self.assertRaises(patch.Refused):
            patch.restore(self.runtime_root, self.state)
        self.assertEqual(candidate, self.service.read_bytes())
        self.assertFalse(json.loads((self.state / "control.json").read_text())
                         ["requireIdentification"])
        (self.state / "owner.json").unlink()
        (self.state / KEY / "journal.json").unlink()
        (self.state / "control.json").write_bytes(patch.control_bytes(True))
        with self.assertRaises(patch.Refused):
            patch.restore(self.runtime_root, self.state)
        self.assertFalse(json.loads((self.state / "control.json").read_text())
                         ["requireIdentification"])

    def test_codexpp_monitor_and_existing_journal_are_refused(self):
        fake_home = Path(self.temp.name) / "fake-user"
        cpp_root = fake_home / ".codex-session-delete/native-browser-identification"
        cpp_root.mkdir(parents=True)
        local = Path(os.environ["LOCALAPPDATA"])
        actual_root = local / "OpenAI/Codex/runtimes/cua_node"
        with mock.patch.object(patch.Path, "home", return_value=fake_home):
            with mock.patch.dict(os.environ, {"LOCALAPPDATA": str(local)}):
                with self.assertRaisesRegex(patch.Refused, "Codex\\+\\+ native browser state"):
                    with patch.codexpp_guard(actual_root, KEY):
                        pass
                with self.assertRaises(patch.Refused):
                    patch.require_no_codexpp_state(actual_root)
                with (cpp_root / "monitor.lock").open("w+b") as stream:
                    stream.write(b"x")
                    stream.flush()
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    try:
                        with self.assertRaises(patch.Refused):
                            with patch.codexpp_guard(actual_root, KEY):
                                pass
                    finally:
                        stream.seek(0)
                        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                journal = cpp_root / KEY / "journal.json"
                journal.parent.mkdir()
                journal.write_text("{}", encoding="utf-8")
                with self.assertRaises(patch.Refused):
                    with patch.codexpp_guard(actual_root, KEY):
                        pass

    def test_legacy_binding_roundtrip(self):
        anchor = "new nf(r,this.clientApi,()=>ze(this.runtime),this.turnEndedTracker,cD)"
        self.original = ("prefix;" + anchor + ";suffix").encode()
        self.service.write_bytes(self.original)
        self.contract.update({
            "version": "fixture-legacy",
            "service": patch.sha(self.original),
            "anchor": anchor,
            "binding": "new nf(r,this.clientApi,()=>ze(this.runtime),this.turnEndedTracker,"
                       "cppNativeIdentificationReader(this.runtime,cD,ze,{path}))",
        })
        patch.apply(self.runtime_root, self.state, self.selection)
        self.assertIn(b"cppNativeIdentificationReader(this.runtime,cD,ze,",
                      self.service.read_bytes())
        patch.restore(self.runtime_root, self.state)
        self.assertEqual(self.original, self.service.read_bytes())

    def test_restore_preflights_all_caches(self):
        patch.apply(self.runtime_root, self.state, self.selection)
        first_candidate = self.service.read_bytes()
        other_key = "fedcba9876543210"
        other_service = self.runtime_root / other_key / patch.SERVICE
        other_service.parent.mkdir(parents=True)
        other_service.write_bytes(b"external edit")
        shutil.copytree(self.state / KEY, self.state / other_key)
        with self.assertRaises(patch.Refused):
            patch.restore(self.runtime_root, self.state)
        self.assertEqual(first_candidate, self.service.read_bytes())
        self.assertEqual(b"external edit", other_service.read_bytes())


@unittest.skipUnless(os.environ.get("CODEX_BROWSER_FIXTURE_RUNTIME") and
                     os.environ.get("CODEX_BROWSER_FIXTURE_DESCRIPTOR"),
                     "Set both pinned native fixture paths to run the genuine-byte test")
class GenuineNativeFixture(unittest.TestCase):
    def test_pinned_runtime_copy_roundtrip(self):
        runtime = Path(os.environ["CODEX_BROWSER_FIXTURE_RUNTIME"])
        original_descriptor = Path(os.environ["CODEX_BROWSER_FIXTURE_DESCRIPTOR"])
        original_service = Path(os.environ.get("CODEX_BROWSER_FIXTURE_SERVICE",
                                               str(runtime / patch.SERVICE)))
        original = json.loads(patch.read_regular(original_descriptor, 1024 * 1024))
        original_root = runtime.parent
        self.assertEqual(runtime.name, patch.descriptor_key(original, original_root))
        test_temp = os.environ.get("CODEX_BROWSER_TEST_TEMP")
        with tempfile.TemporaryDirectory(prefix="browser-patch-real-", dir=test_temp) as temp:
            root = Path(temp)
            runtime_root = root / "runtime"
            copied = runtime_root / runtime.name
            home = root / "home"
            state = root / "state"
            for relative in ("manifest.json", "bin/node.exe", "bin/node_repl.exe",
                             patch.ENTRY, patch.SERVICE):
                dest = copied / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(original_service if relative == patch.SERVICE
                             else runtime / relative, dest)
            cache = home / "plugins/cache/openai-bundled/unified-computer-use/test"
            cache.mkdir(parents=True)
            (cache / ".mcp.json").write_text(
                json.dumps(descriptor(runtime_root, runtime.name)), encoding="utf-8")
            selection = patch.find_runtime([home], runtime_root)
            self.assertEqual(selection[0], runtime.name)
            before = (copied / patch.SERVICE).read_bytes()
            before_mtime = (copied / patch.SERVICE).stat().st_mtime_ns
            patch.apply(runtime_root, state, selection)
            self.assertNotEqual(before, (copied / patch.SERVICE).read_bytes())
            patch.restore(runtime_root, state)
            self.assertEqual(before, (copied / patch.SERVICE).read_bytes())
            self.assertEqual(before_mtime, (copied / patch.SERVICE).stat().st_mtime_ns)
            cpp = root / "cpp-state"
            cpp.mkdir()
            (cpp / "owner.lock").touch()
            (cpp / "monitor.lock").write_text(json.dumps({
                "schema": 1, "generation": "00000000-0000-0000-0000-000000000001",
                "state": "restored",
            }), encoding="utf-8")
            (cpp / "control.json").write_bytes(patch.control_bytes(False))
            patch.apply_unified(runtime_root, state, selection, cpp)
            adapted = (copied / patch.SERVICE).read_bytes()
            self.assertEqual(patch.sha(adapted),
                             json.loads((cpp / runtime.name / "journal.json").read_text())
                             ["candidateSha"])
            self.assertNotEqual(before, adapted)
            patch.restore_unified(runtime_root, state, cpp)
            self.assertEqual(before, (copied / patch.SERVICE).read_bytes())
            self.assertEqual(before_mtime, (copied / patch.SERVICE).stat().st_mtime_ns)


if __name__ == "__main__":
    unittest.main()
