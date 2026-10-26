"""Fail-closed proof that a sealed native release has no remaining consumers.

The interface takes the process and file-descriptor adapters supplied by the
retention coordinator so test seams match the public promotion operation.
"""
import json
import os
from pathlib import Path
import re
import subprocess

from release_manifest import verify as verify_release_manifest


def _references_release(path, release):
    """Read native scripts and executable binaries without loading them into RAM."""
    signature = re.compile(rb"(?<!\w)releases/" + release.name.encode()
                           + rb"(?![a-f0-9])")
    tail = b""
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            data = tail + block
            if str(release).encode() in data or signature.search(data):
                return True
            tail = data[-(len(str(release)) + 48):]
    return False


def obstructions(base, release, consumer_paths, *, process_references, open_file_references):
    name = release.name
    evidence = []
    protected = {"data", "backup", "backups", "state", "staging",
                 "venv", ".venv", "_local", "private"}
    try:
        entries = list(release.iterdir())
        if any(entry.name.lower() in protected for entry in entries):
            evidence.append("protected-payload:" + name)
        allowed = {"dist", "hosting", "node_modules", "package.json", "vendor",
                   ".retention-manifest.json"}
        if any(entry.name not in allowed for entry in entries):
            evidence.append("unrecognized-content:" + name)
        # Runtime archives have nested directories. Guard private paths inside
        # an otherwise permitted top-level folder before removing its tree.
        # dist/data and dependency "state" folders are native build output.
        nested_protected = protected - {"data", "state"}
        for folder, directories, files in os.walk(release, followlinks=False,
                                                   onerror=lambda exc: evidence.append(
                                                       "unreadable-release:" + name)):
            if Path(folder) == release:
                continue
            if any(part.lower() in nested_protected for part in directories + files):
                evidence.append("protected-payload:" + name)
                break
        manifest = release / "package.json"
        try:
            if json.loads(manifest.read_text())["name"] != "@wonderwhy-er/desktop-commander":
                evidence.append("unrecognized-package:" + name)
        except (OSError, ValueError, KeyError):
            evidence.append("unverified-package:" + name)
        if not verify_release_manifest(release):
            evidence.append("unverified-release-payload:" + name)
    except OSError:
        evidence.append("unreadable-release:" + name)
    try:
        for pid, cmd in process_references():
            if str(release) in cmd:
                evidence.append("pid:" + str(pid) + ":" + name)
    except (OSError, subprocess.SubprocessError) as exc:
        evidence.append("process-scan-unavailable:" + type(exc).__name__)
    try:
        for path in open_file_references():
            if path == str(release) or path.startswith(str(release) + os.sep):
                evidence.append("open-file:" + name)
                break
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        detail = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        evidence.append("open-file-scan-unavailable:" + detail)
    # The live current/rollback trees may still load dependencies by symlink
    # even when no process holds an open descriptor during this scan.
    live_roots = set()
    for selector in (base / "current", base / "rollback"):
        if selector.is_symlink():
            try:
                live_roots.add(selector.resolve(strict=True))
            except (OSError, RuntimeError):
                evidence.append("unresolved-live-selector:" + selector.name)
    retired_root = release.resolve(strict=True)
    for live in live_roots - {retired_root}:
        for folder, directories, files in os.walk(
                live, followlinks=False,
                onerror=lambda exc: evidence.append("unreadable-live-release:" + live.name)):
            for filename in directories + files:
                path = Path(folder) / filename
                if path.is_symlink():
                    try:
                        target = path.resolve(strict=True)
                    except (OSError, RuntimeError):
                        evidence.append("unresolved-live-symlink:" + path.name)
                        continue
                    if target == retired_root or retired_root in target.parents:
                        evidence.append("live-release-symlink:" + path.name + ":" + name)
                    elif path.is_dir() and target != live and live not in target.parents:
                        evidence.append("unscanned-live-symlink-directory:" + path.name)
                elif path.is_file():
                    try:
                        if _references_release(path, release):
                            evidence.append("live-release-reference:" + path.name + ":" + name)
                    except OSError:
                        evidence.append("unreadable-live-file:" + path.name)
    # Scan native consumer directories including other units and drop-ins, not
    # only today's known service filename. Keep the release tree out of the
    # consumer scan; its complete content is checked against its build seal.
    native_bin = base.parent.parent / "bin"
    folders = {base, native_bin}
    folders.update(path if path.is_dir() else path.parent for path in consumer_paths)
    folders = {folder for folder in folders if not any(
        other != folder and other in folder.parents for other in folders)}
    native_suffixes = {".plist", ".json", ".service", ".conf", ".socket",
                       ".timer", ".target", ".yaml", ".yml", ".toml",
                       ".sh", ".bash", ".zsh", ".fish", ".py", ".rb", ".pl",
                       ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}
    for folder in folders:
        if not folder.is_dir():
            continue
        if folder.is_symlink():
            evidence.append("unverified-native-root:" + folder.name)
            continue
        for current, directories, files in os.walk(
                folder, followlinks=False,
                onerror=lambda exc: evidence.append("unreadable-native-config:" + name)):
            if Path(current) == base:
                directories[:] = [item for item in directories if item != "releases"]
            for filename in directories + files:
                path = Path(current) / filename
                if path == base / "retired":
                    continue  # Managed pending-retirement marker.
                if path.is_symlink():
                    try:
                        target = path.resolve(strict=True)
                    except (OSError, RuntimeError):
                        evidence.append("unresolved-symlink:" + path.name)
                        continue
                    if target == release.resolve() or release.resolve() in target.parents:
                        evidence.append("symlink:" + path.name + ":" + name)
                    elif path.is_dir() and path not in (base / "current", base / "rollback"):
                        # os.walk intentionally does not follow link directories.
                        # An unvisited alias may contain a hidden consumer.
                        evidence.append("unscanned-symlink-directory:" + path.name)
                # Native bin wrappers frequently have no suffix. Their argv
                # may reference a historical SHA even while they are idle.
                if path.is_file() and (path.suffix in native_suffixes
                                       or os.access(path, os.X_OK)
                                       or native_bin in path.parents):
                    try:
                        if _references_release(path, release):
                            evidence.append("unit-or-config:" + path.name + ":" + name)
                    except OSError:
                        evidence.append("unreadable-native-config:" + path.name)
    for path in consumer_paths:
        try:
            if path.is_file():
                if _references_release(path, release):
                    evidence.append("unit-or-config:" + path.name + ":" + name)
        except OSError:
            evidence.append("unreadable-consumer:" + path.name)
    return evidence
