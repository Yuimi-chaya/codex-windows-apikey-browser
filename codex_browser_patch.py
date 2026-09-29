#!/usr/bin/env python3
"""Patch one verified Windows CUA browser callback, with reversible local backups."""

import argparse
from contextlib import contextmanager
import csv
from dataclasses import dataclass
import hashlib
import json
import msvcrt
import ntpath
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile


SERVICE = "bin/node_modules/@oai/browser-desktop/scripts/browser-service.mjs"
ENTRY = "bin/node_modules/@oai/cua-repl/bin/cua-repl.mjs"
ENTRY_SHA = "992174a5e637645aeb444adfdb1bae688e997bb84d7db07532f68e358e60f278"
MAX_SERVICE = 32 * 1024 * 1024
MAX_COMPONENT = 128 * 1024 * 1024
KEY_RE = re.compile(r"^[0-9a-fA-F]{16}$")
OWNER = b'{"schema":1,"tool":"codex-windows-apikey-browser"}'

# Exact native bytes, not package version labels, determine compatibility.
CONTRACTS = {
    "ba3691b0717b6df8064c3841a75c784e8af9633c7b47f2fdb56d8de099efe6fc": {
        "version": "0.0.11",
        "service": "3e6fd4a8cf09f57549d63f2c9cbfa2abf42f0a6b0c09c3d6605fe07c8ba09e4a",
        "worker": "ef53f8f0d957b7cf437020499b6b9d880dee381214788930107b549237f7949c",
        "node": "be14417b6c4b4a5af06be7c16bda58730f26b912c3e8c6489d12392ef08f35bf",
        "anchor": "new nf(r,this.clientApi,()=>ze(this.runtime),this.turnEndedTracker,cD)",
        "binding": "new nf(r,this.clientApi,()=>ze(this.runtime),this.turnEndedTracker,"
                   "cppNativeIdentificationReader(this.runtime,cD,ze,{path}))",
    },
    "2c8ea57bfab596fb3b9cf78673b62a763f8d484aa8d380e341324354ce9e90e8": {
        "version": "0.0.24",
        "service": "fc0660ba45e6c10b532d8faa0c1bac704d987dad3d4b74478f49fdd82bf90086",
        "worker": "e42e0d846b9c1e5da3ec7b5e069fdae3643df590f4e304f433cfaa7fbd8732a7",
        "node": "d3c3c290b11d55ef747e63f5a63538e0d8ca95f3f9668bb6a8081a25ba2befab",
        "anchor": "new eh(r,this.clientApi,()=>je(this.runtime),this.turnEndedTracker,sv)",
        "binding": "new eh(r,this.clientApi,()=>je(this.runtime),this.turnEndedTracker,"
                   "cppNativeIdentificationReader(this.runtime,sv,je,{path}))",
    },
}


class Refused(Exception):
    pass


@dataclass(frozen=True)
class PatchStatus:
    code: str
    detail: str
    version: str = ""
    home: str = ""
    service: str = ""
    can_apply: bool = False
    can_restore: bool = False
    recovery_count: int = 0


def require(condition, message):
    if not condition:
        raise Refused(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def plain(path):
    path = Path(path)
    text = str(path)
    require(path.is_absolute() and not text.startswith("\\\\"), "Expected an absolute local drive path")
    require(".." not in re.split(r"[\\/]", text), "Parent traversal is unsupported")
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        require(not info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT,
                "Linked or reparse paths are unsupported: " + str(item))
    return path


def read_regular(path, limit):
    path = plain(path)
    with path.open("rb") as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and
                not info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT and
                info.st_size <= limit, "Unexpected file type or size: " + str(path))
        data = stream.read(limit + 1)
    require(len(data) <= limit, "File grew beyond the size limit: " + str(path))
    return data


def file_sha(path, limit=MAX_COMPONENT):
    path = plain(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and
                not info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT and
                info.st_size <= limit, "Unexpected file type or size: " + str(path))
        size = 0
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(block)
            require(size <= limit, "File grew beyond the size limit: " + str(path))
            digest.update(block)
    return digest.hexdigest()


def same_path(left, right):
    return ntpath.normcase(ntpath.normpath(str(left))) == ntpath.normcase(ntpath.normpath(str(right)))


def outside_runtime(runtime_root, state_root):
    try:
        parent = ntpath.commonpath((str(runtime_root), str(state_root)))
    except ValueError:  # Different drive letters cannot be nested.
        return True
    return not same_path(parent, runtime_root)


def validate_locations(runtime_root, state_root):
    cpp_root = Path.home() / ".codex-session-delete/native-browser-identification"
    require(outside_runtime(runtime_root, state_root),
            "Recovery must be outside the runtime cache")
    require(outside_runtime(cpp_root, state_root) and outside_runtime(state_root, cpp_root),
            "Recovery must not overlap Codex++ native browser state")


def owns_state(state_root):
    marker = state_root / "owner.json"
    return marker.exists() and read_regular(marker, 256) == OWNER


def establish_owner(state_root):
    if (state_root / "owner.json").exists():
        require(owns_state(state_root), "Recovery directory belongs to another tool")
    else:
        require({entry.name for entry in state_root.iterdir()} <= {"owner.lock"},
                "Nonempty recovery directory has no ownership marker")
        write_new(state_root / "owner.json", OWNER)


def disable_owned_control(state_root):
    if state_root.exists() and owns_state(state_root):
        with locked(state_root):
            atomic_write(state_root / "control.json", control_bytes(False))


def control_is_recognizable(state_root):
    control = state_root / "control.json"
    if not control.exists():
        return False
    try:
        value = json.loads(read_regular(control, 1024))
        return (isinstance(value, dict) and set(value) == {"schema", "requireIdentification"}
                and value["schema"] == 1 and type(value["requireIdentification"]) is bool)
    except (Refused, OSError, ValueError):
        return False


def disable_recognizable_control(state_root):
    if control_is_recognizable(state_root):
        with locked(state_root):
            atomic_write(state_root / "control.json", control_bytes(False))


def require_offline(runtime_root):
    local = os.environ.get("LOCALAPPDATA")
    if not local or not same_path(runtime_root, Path(local) / "OpenAI/Codex/runtimes/cua_node"):
        return  # Relocated fixture: never inspect unrelated live processes.
    try:
        result = subprocess.run(["tasklist.exe", "/fo", "csv", "/nh"], capture_output=True,
                                text=True, errors="replace", timeout=10, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise Refused("Cannot verify that Codex and Codex++ are stopped") from exc
    names = {row[0].casefold() for row in csv.reader(result.stdout.splitlines()) if row}
    blocking = names & {
        "codex.exe", "chatgpt.exe", "codex-plus-plus.exe",
        "codex-plus-plus-manager.exe", "node_repl.exe", "codex-computer-use-swift.exe",
    }
    require(not blocking, "Exit Codex and Codex++ before changing the live runtime: " +
            ", ".join(sorted(blocking)))


def require_no_codexpp_state(runtime_root):
    local = os.environ.get("LOCALAPPDATA")
    if local and same_path(runtime_root, Path(local) / "OpenAI/Codex/runtimes/cua_node"):
        require(not (Path.home() / ".codex-session-delete/native-browser-identification").exists(),
                "Codex++ native browser state appeared during preparation; refusing to write")


@contextmanager
def codexpp_guard(runtime_root, key=None):
    local = os.environ.get("LOCALAPPDATA")
    if not local or not same_path(runtime_root, Path(local) / "OpenAI/Codex/runtimes/cua_node"):
        yield
        return
    cpp_root = Path.home() / ".codex-session-delete/native-browser-identification"
    if not cpp_root.exists():
        yield
        return
    plain(cpp_root)
    if key is not None:
        raise Refused("Codex++ native browser state exists; use its built-in option instead")
    monitor = cpp_root / "monitor.lock"
    if not monitor.exists():
        yield
        return
    plain(monitor)
    try:
        stream = monitor.open("r+b")
    except OSError as exc:
        raise Refused("Cannot verify Codex++ monitor is stopped") from exc
    with stream:
        try:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise Refused("Codex++ native browser monitor is active; exit Codex++ first") from exc
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def descriptor_key(data, runtime_root):
    try:
        server = data["mcpServers"]["cua_repl"]
        command = server["command"]
        args = server["args"]
        env = server["env"]
        require(isinstance(command, str) and isinstance(args, list) and isinstance(env, dict),
                "Incomplete CUA descriptor")
        plain(command)
        relative = ntpath.relpath(command, str(runtime_root))
        parts = re.split(r"[\\/]", relative)
        require(len(parts) == 3 and KEY_RE.fullmatch(parts[0]) is not None and
                [part.lower() for part in parts[1:]] == ["bin", "node.exe"],
                "CUA descriptor does not select a runtime in the expected cache")
        key = parts[0]
        base = runtime_root / key
        require(same_path(command, base / "bin/node.exe") and
                same_path(env["NODE_REPL_NODE_PATH"], command) and
                same_path(env["CUA_REPL_NODE_REPL_PATH"], base / "bin/node_repl.exe") and
                len(args) == 1 and same_path(args[0], base / ENTRY),
                "Conflicting CUA runtime paths")
        for field in (env["NODE_REPL_NODE_PATH"], env["CUA_REPL_NODE_REPL_PATH"], args[0]):
            plain(field)
        services = json.loads(env["NODE_REPL_TRUSTED_SERVICES"])
        require(services["browser"] == "@oai/browser-desktop/service" and
                env["CUA_REPL_ENABLED_SURFACES"] == "browser",
                "Unsupported CUA browser service selection")
        return key
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise Refused("Invalid CUA descriptor") from exc


def discover(home, runtime_root):
    descriptors = plain(home / "plugins/cache/openai-bundled/unified-computer-use")
    if not descriptors.exists():
        return None
    keys = set()
    entries = list(descriptors.iterdir())
    require(len(entries) <= 64, "Too many plugin cache entries")
    for entry in entries:
        plain(entry)
        if not entry.is_dir():
            continue
        descriptor = entry / ".mcp.json"
        if descriptor.exists():
            data = json.loads(read_regular(descriptor, 1024 * 1024))
            keys.add(descriptor_key(data, runtime_root))
    require(len(keys) <= 1, "Ambiguous CUA runtime selection")
    return next(iter(keys), None)


def find_runtime(homes, runtime_root):
    choices = {(key, str(home)) for home in homes if (key := discover(home, runtime_root))}
    keys = {key for key, _ in choices}
    require(len(keys) <= 1, "Different Codex homes select different CUA runtimes; use --codex-home")
    if not choices:
        return None
    key = next(iter(keys))
    return key, sorted(home for selected, home in choices if selected == key)[0]


def select_contract(runtime):
    manifest = file_sha(runtime / "manifest.json", 1024 * 1024)
    require(manifest in CONTRACTS, "Unsupported CUA manifest fingerprint (no files changed)")
    contract = CONTRACTS[manifest]
    for relative, expected in (
        ("bin/node.exe", contract["node"]),
        ("bin/node_repl.exe", contract["worker"]),
        (ENTRY, ENTRY_SHA),
    ):
        require(file_sha(runtime / relative) == expected,
                "Unsupported CUA component: " + relative)
    return contract


def transform(original, contract, control):
    require(sha(original) == contract["service"], "Unsupported browser service fingerprint")
    text = original.decode("utf-8")
    anchor = contract["anchor"]
    require(text.count(anchor) == 1 and "cppNativeIdentificationReader" not in text,
            "Unknown or ambiguous callback binding")
    path_literal = json.dumps(str(control), ensure_ascii=False)
    helper = (Path(__file__).parent / "require-identification.mjs").read_text(encoding="utf-8")
    return (text.replace(anchor, contract["binding"].format(path=path_literal), 1) +
            "\n" + helper).encode("utf-8")


def write_new(path, data):
    plain(path)
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def atomic_write(path, data, mtime_ns=None):
    plain(path)
    fd, name = tempfile.mkstemp(prefix=".browser-patch-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if mtime_ns is not None:
            os.utime(name, ns=(mtime_ns, mtime_ns))
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def control_bytes(enabled):
    return json.dumps({"schema": 1, "requireIdentification": enabled},
                      separators=(",", ":")).encode("utf-8")


@contextmanager
def locked(state_root):
    plain(state_root)
    state_root.mkdir(parents=True, exist_ok=True)
    lock_path = plain(state_root / "owner.lock")
    with lock_path.open("a+b") as lock:
        try:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise Refused("Another browser patch transaction is active") from exc
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def recovery(state_root, key):
    directory = plain(state_root / key)
    record = json.loads(read_regular(directory / "journal.json", 4096))
    require(set(record) == {"schema", "original_sha", "candidate_sha", "mtime_ns"} and
            record["schema"] == 1 and type(record["mtime_ns"]) is int and
            0 <= record["mtime_ns"] < 2**63 and
            record["original_sha"] in {item["service"] for item in CONTRACTS.values()} and
            isinstance(record["candidate_sha"], str) and
            re.fullmatch("[0-9a-f]{64}", record["candidate_sha"]) is not None,
            "Invalid recovery journal")
    original = read_regular(directory / "original.mjs", MAX_SERVICE)
    candidate = read_regular(directory / ("candidate-" + record["candidate_sha"] + ".mjs"),
                             MAX_SERVICE)
    require(sha(original) == record["original_sha"] and sha(candidate) == record["candidate_sha"],
            "Recovery files differ from their journal")
    return record, original, candidate


def records(state_root):
    if not state_root.exists():
        return []
    plain(state_root)
    result = []
    for entry in state_root.iterdir():
        plain(entry)
        if KEY_RE.fullmatch(entry.name) and entry.is_dir() and (entry / "journal.json").exists():
            result.append(entry.name)
    return sorted(result)


def recoverable_without_owner(state_root):
    keys = records(state_root)
    if not keys:
        return False
    try:
        for key in keys:
            recovery(state_root, key)
        return True
    except (Refused, OSError, ValueError):
        return False


def apply(runtime_root, state_root, selection):
    validate_locations(runtime_root, state_root)
    try:
        require_offline(runtime_root)
        with codexpp_guard(runtime_root, selection[0] if selection else None):
            _apply(runtime_root, state_root, selection)
    except Exception as error:
        try:
            disable_owned_control(state_root)
        except Exception as disable_error:
            raise Refused(f"{error}; also failed to disable local control: {disable_error}") from disable_error
        raise


def _apply(runtime_root, state_root, selection):
    require(selection is not None, "No generated CUA browser descriptor found; start Codex once first")
    key, home = selection
    if state_root.exists() and not owns_state(state_root):
        require(not any(state_root.iterdir()), "Nonempty recovery directory belongs to another tool")
    runtime = plain(runtime_root / key)
    target = plain(runtime / SERVICE)
    contract = select_contract(runtime)
    current = read_regular(target, MAX_SERVICE)
    original_sha = contract["service"]
    if sha(current) != original_sha and key not in records(state_root):
        raise Refused("Browser service is already modified; this tool will not replace another adapter")
    with locked(state_root):
        establish_owner(state_root)
        control = state_root / "control.json"
        try:
            for other in records(state_root):
                if other != key and (runtime_root / other / SERVICE).exists():
                    _, old_original, old_candidate = recovery(state_root, other)
                    old_bytes = read_regular(runtime_root / other / SERVICE, MAX_SERVICE)
                    require(old_bytes == old_original, "Restore the previous cache before applying a new one"
                            if old_bytes == old_candidate else "Previous cache has an external change")
            current = read_regular(target, MAX_SERVICE)
            directory = plain(state_root / key)
            directory.mkdir(exist_ok=True)
            backup = directory / "original.mjs"
            journal = directory / "journal.json"
            if journal.exists():
                record, original, candidate = recovery(state_root, key)
                require(record["original_sha"] == original_sha,
                        "Existing journal belongs to a different runtime")
                require(current in (original, candidate), "Browser service changed outside this tool")
            else:
                require(sha(current) == original_sha, "Unsupported or already modified browser service")
                original = current
                candidate = transform(original, contract, control)
                require(len(candidate) <= MAX_SERVICE, "Candidate browser service is too large")
                if backup.exists():
                    require(read_regular(backup, MAX_SERVICE) == original,
                            "Unjournaled original backup conflict")
                else:
                    write_new(backup, original)
                candidate_path = directory / ("candidate-" + sha(candidate) + ".mjs")
                if candidate_path.exists():
                    require(read_regular(candidate_path, MAX_SERVICE) == candidate,
                            "Candidate backup conflict")
                else:
                    write_new(candidate_path, candidate)
            require(candidate == transform(original, contract, control),
                    "Stored adapter differs; restore first, then apply the new version")
            if current == original:
                mtime_ns = target.stat().st_mtime_ns
                require(read_regular(target, MAX_SERVICE) == original, "Concurrent runtime change")
                record = {"schema": 1, "original_sha": original_sha,
                          "candidate_sha": sha(candidate), "mtime_ns": mtime_ns}
                atomic_write(journal, json.dumps(record, separators=(",", ":")).encode("utf-8"))
                atomic_write(control, control_bytes(False))
                require_offline(runtime_root)
                require_no_codexpp_state(runtime_root)
                atomic_write(target, candidate)
                require(read_regular(target, MAX_SERVICE) == candidate, "Browser service verification failed")
            atomic_write(control, control_bytes(True))
        except Exception:
            if state_root.exists():
                atomic_write(control, control_bytes(False))
            raise
    print("Prepared CUA " + contract["version"] + " from " + home)
    print("Modified only: " + str(target))
    print("Original and recovery journal: " + str(state_root / key))
    print("Restart Codex and use a fresh browser tool context to test. This is not a connectivity test.")


def refuse_orphaned_services(runtime_root, known_keys):
    if not runtime_root.exists():
        return
    plain(runtime_root)
    entries = list(runtime_root.iterdir())
    require(len(entries) <= 64, "Too many CUA runtime directories")
    for entry in entries:
        plain(entry)
        if not entry.is_dir() or not KEY_RE.fullmatch(entry.name):
            continue
        service = entry / SERVICE
        if service.exists() and entry.name not in known_keys:
            current = read_regular(service, MAX_SERVICE)
            require(b"cppNativeIdentificationReader" not in current,
                    "Modified browser service has no matching recovery journal: " + str(service))


def restore(runtime_root, state_root):
    validate_locations(runtime_root, state_root)
    require_offline(runtime_root)
    with codexpp_guard(runtime_root):
        if not state_root.exists():
            refuse_orphaned_services(runtime_root, set())
            print("No standalone patch state found; nothing to restore.")
            return
        if not owns_state(state_root) and not recoverable_without_owner(state_root):
            disable_recognizable_control(state_root)
            raise Refused("Recovery ownership and journal cannot be verified; local control was disabled if recognizable")
        with locked(state_root):
            atomic_write(state_root / "control.json", control_bytes(False))
            if not owns_state(state_root):
                marker = state_root / "owner.json"
                require(not marker.exists(), "Ownership marker conflicts; local control is disabled")
                write_new(marker, OWNER)
            keys = records(state_root)
            refuse_orphaned_services(runtime_root, set(keys))
            pending = []
            for key in keys:
                target = plain(runtime_root / key / SERVICE)
                if not target.exists():
                    continue  # Codex removed this cache; do not recreate it.
                record, original, candidate = recovery(state_root, key)
                current = read_regular(target, MAX_SERVICE)
                require(current in (original, candidate),
                        "External modification prevents restoration: " + str(target))
                if current == candidate:
                    pending.append((target, record["mtime_ns"], original, candidate))
            # Preflight every existing cache before the first service write.
            for target, mtime_ns, original, candidate in pending:
                require(read_regular(target, MAX_SERVICE) == candidate, "Concurrent runtime change")
                require_offline(runtime_root)
                atomic_write(target, original, mtime_ns)
                require(read_regular(target, MAX_SERVICE) == original, "Restoration verification failed")
    print("Restored " + str(len(pending)) + " browser service(s); recovery files were retained.")
    print("The browser extension may retain request identification until changed in the extension.")


def inspect_status(runtime_root, state_root, selection):
    """Read-only disk diagnosis; action flags are hints, never a substitute for write guards."""
    validate_locations(runtime_root, state_root)
    keys = records(state_root)
    owned = state_root.exists() and owns_state(state_root)
    marker = state_root / "owner.json"
    recoverable = bool(keys) and (
        owned or (not marker.exists() and recoverable_without_owner(state_root)))
    conflict = (bool(keys) and not recoverable or
                state_root.exists() and not owned and
                (marker.exists() or any(state_root.iterdir())) and not recoverable)
    version = ""
    home = selection[1] if selection else ""
    service = ""
    code = "missing"
    detail = "No generated CUA browser descriptor found. Start Codex once, then refresh."
    can_apply = False
    if selection:
        key, _ = selection
        target = runtime_root / key / SERVICE
        service = str(target)
        try:
            contract = select_contract(runtime_root / key)
            version = contract["version"]
            current = read_regular(target, MAX_SERVICE)
            if sha(current) == contract["service"]:
                code = "original"
                detail = "Supported original service. Ready to apply after Codex is closed."
                can_apply = True
            elif owned and key in keys:
                _, _, candidate = recovery(state_root, key)
                if current == candidate:
                    control = json.loads(read_regular(state_root / "control.json", 1024))
                    require(set(control) == {"schema", "requireIdentification"} and
                            control["schema"] == 1 and
                            type(control["requireIdentification"]) is bool,
                            "Invalid local control state")
                    code = "patched" if control["requireIdentification"] else "disabled"
                    detail = ("Patch present on disk; browser connectivity has not been tested."
                              if code == "patched" else
                              "Patch present, but local request identification is disabled.")
                    can_apply = code == "disabled"
                else:
                    code = "conflict"
                    detail = "Browser service has changed outside this tool."
            else:
                code = "conflict"
                detail = "Browser service was changed by another tool or has an unknown fingerprint."
        except (Refused, OSError, ValueError, UnicodeError) as exc:
            code = "unsupported"
            detail = str(exc)
    if conflict:
        code = "conflict"
        detail = "Recovery ownership or journal cannot be verified."
        can_apply = False
    elif recoverable:
        for old_key in keys:
            try:
                recovery(state_root, old_key)
            except (Refused, OSError, ValueError, UnicodeError) as exc:
                code, detail, conflict = "conflict", str(exc), True
                can_apply = False
                break
    can_restore = recoverable and not conflict
    if not conflict:
        try:
            refuse_orphaned_services(runtime_root, set(keys))
        except (Refused, OSError, ValueError, UnicodeError) as exc:
            code, detail, can_apply = "conflict", str(exc), False
            can_restore = False
    local = os.environ.get("LOCALAPPDATA")
    if (code == "conflict" and not keys and local and
            same_path(runtime_root, Path(local) / "OpenAI/Codex/runtimes/cua_node") and
            (Path.home() / ".codex-session-delete/native-browser-identification").exists()):
        detail += " Codex++ native browser state also exists; use its built-in option."
    if can_apply:
        try:
            require_no_codexpp_state(runtime_root)
        except (Refused, OSError) as exc:
            code, detail, can_apply = "conflict", str(exc), False
    if can_apply or can_restore:
        try:
            require_offline(runtime_root)
        except (Refused, OSError) as exc:
            detail = str(exc)
            code = "running"
            can_apply = can_restore = False
    return PatchStatus(code, detail, version, home, service,
                       can_apply, can_restore, len(keys))


def status(runtime_root, state_root, selection):
    print("CUA runtime root: " + str(runtime_root))
    print("Recovery root: " + str(state_root))
    snapshot = inspect_status(runtime_root, state_root, selection)
    if selection:
        print("Selected by " + snapshot.home + ": " + selection[0])
    print("Patch status: " + snapshot.code + "; " + snapshot.detail)
    if snapshot.version:
        print("CUA fingerprint: " + snapshot.version)
    for key in records(state_root):
        print("Retained recovery: " + key)


def main():
    if sys.platform != "win32":
        raise Refused("Windows only")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("status", "apply", "restore"), default="status")
    parser.add_argument("--codex-home", type=Path, help="Codex home containing plugin cache")
    parser.add_argument("--runtime-root", type=Path, help="CUA runtime cache root")
    parser.add_argument("--state-root", type=Path, help="Standalone backup and control directory")
    args = parser.parse_args()
    local = os.environ.get("LOCALAPPDATA")
    require(local, "LOCALAPPDATA is missing")
    runtime_root = plain(args.runtime_root or Path(local) / "OpenAI/Codex/runtimes/cua_node")
    state_root = plain(args.state_root or Path(local) / "CodexWinApiBrowserPatch")
    validate_locations(runtime_root, state_root)
    homes = ([plain(args.codex_home)] if args.codex_home else
             [plain(Path(os.environ["CODEX_HOME"]))] if os.environ.get("CODEX_HOME") else [])
    if not args.codex_home:
        fallback = plain(Path.home() / ".codex")
        if all(not same_path(home, fallback) for home in homes):
            homes.append(fallback)
    if args.action == "restore":
        restore(runtime_root, state_root)
    else:
        try:
            selection = find_runtime(homes, runtime_root)
        except Exception as error:
            if args.action == "apply":
                try:
                    disable_owned_control(state_root)
                except Exception as disable_error:
                    raise Refused(f"{error}; also failed to disable local control: {disable_error}") from disable_error
            raise
        if args.action == "apply":
            apply(runtime_root, state_root, selection)
        else:
            status(runtime_root, state_root, selection)


if __name__ == "__main__":
    try:
        main()
    except (Refused, OSError, ValueError, UnicodeError) as error:
        print("Refused: " + str(error), file=sys.stderr)
        sys.exit(2)
