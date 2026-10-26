#!/usr/bin/env python3
"""Finalize an already healthy Desktop Commander activation, keeping exact rollback.

Only revision-named, reproducible release trees may be removed. All other
files (data, backup, staging, gateway binaries and private config) are outside
the deletion boundary.
"""
import argparse
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
from urllib.request import urlopen

BASE = Path.home() / ".local/opt/desktop-commander"
REVISION = re.compile(r"[a-f0-9]{40}\Z")


def process_references():
    scan = subprocess.run(["ps", "-axo", "pid=,command="], check=True,
                          capture_output=True, text=True, timeout=12)
    rows = []
    for line in scan.stdout.splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) == 2 and parts[0].isdigit():
            pid = int(parts[0])
            if pid not in (os.getpid(), os.getppid()):
                rows.append((pid, parts[1]))
    return rows


def open_file_references():
    # lsof uses file descriptors rather than executable command arguments.
    # Fail closed if the host cannot prove that old files are unused.
    scan = subprocess.run(["lsof", "-n", "-P", "-F", "n"], check=True,
                          capture_output=True, text=True, timeout=25)
    return [line[1:].split(" (deleted)")[0] for line in scan.stdout.splitlines()
            if line.startswith("n/")]


def _consumer_paths(host, home):
    if host == "studio":
        return [home / "Library/LaunchAgents/it.domenico.desktop-commander.plist"]
    return [home / ".config/desktop-commander/mcp.json",
            home / ".config/systemd/user/desktop-commander.service",
            home / ".config/desktop-commander/tunnel-profiles/computer-mcp/config.json"]


def runtime_health(host, selected, home):
    """Require a running service with a real process and projected selected revision."""
    processes = process_references()
    if not any(str(selected / "dist/index.js") in cmd for _, cmd in processes):
        raise RuntimeError("missing-running-process-for-selected-revision")
    if host == "studio":
        plist_path = home / "Library/LaunchAgents/it.domenico.desktop-commander.plist"
        plist = plistlib.loads(plist_path.read_bytes())
        if str(selected / "dist/index.js") not in str(plist["ProgramArguments"]):
            raise RuntimeError("studio-unit-does-not-select-revision")
        status = subprocess.run(["launchctl", "print",
                                 "gui/" + str(os.getuid()) + "/it.domenico.desktop-commander"],
                                check=True, capture_output=True, text=True, timeout=12)
        if "state = running" not in status.stdout:
            raise RuntimeError("studio-unit-not-running")
    elif host == "minipc":
        config = json.loads((home / ".config/desktop-commander/mcp.json").read_text())
        args = config["mcpServers"]["minipc"]["args"]
        if str(selected / "dist/index.js") not in args:
            raise RuntimeError("minipc-config-does-not-select-revision")
        status = subprocess.run(
            ["systemctl", "--user", "show", "desktop-commander.service",
             "-p", "ActiveState", "-p", "MainPID"], check=True,
            capture_output=True, text=True, timeout=12).stdout
        if "ActiveState=active" not in status or "MainPID=0" in status:
            raise RuntimeError("minipc-unit-not-running")
        with urlopen("http://127.0.0.1:8498/readyz", timeout=5) as response:
            if response.status != 200:
                raise RuntimeError("minipc-tunnel-not-ready")
    else:
        raise ValueError("unsupported-host:" + host)


def _selector(base, name, releases):
    link = base / name
    if not link.is_symlink():
        if link.exists():
            raise RuntimeError("invalid-selector:" + name)
        return None
    try:
        target = link.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise RuntimeError("broken-selector:" + name) from exc
    if target.parent != releases.resolve() or not REVISION.fullmatch(target.name):
        raise RuntimeError("foreign-selector:" + name)
    return target.name


def _point(base, label, release):
    link = base / label
    temporary = base / ("." + label + ".new")
    if temporary.exists() or temporary.is_symlink():
        raise RuntimeError("pending-selector-update:" + label)
    temporary.symlink_to(Path("releases") / release)
    temporary.replace(link)


def _obstructions(base, release, consumer_paths):
    name = release.name
    evidence = []
    protected = {"data", "backup", "backups", "state", "staging",
                 "venv", ".venv", "_local", "private"}
    try:
        entries = list(release.iterdir())
        if any(entry.name.lower() in protected for entry in entries):
            evidence.append("protected-payload:" + name)
        allowed = {"dist", "hosting", "node_modules", "package.json", "vendor"}
        if any(entry.name not in allowed for entry in entries):
            evidence.append("unrecognized-content:" + name)
        manifest = release / "package.json"
        try:
            if json.loads(manifest.read_text())["name"] != "@wonderwhy-er/desktop-commander":
                evidence.append("unrecognized-package:" + name)
        except (OSError, ValueError, KeyError):
            evidence.append("unverified-package:" + name)
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
    except (OSError, subprocess.SubprocessError) as exc:
        evidence.append("open-file-scan-unavailable:" + type(exc).__name__)
    # Selectors and any other symlink directly below the installed product
    # may outlive a renamed service. Never remove their targets.
    # Bounded search in the product and the native consumer's config/bin dirs.
    folders = {base, base / "hosting", base.parent.parent / "bin"}
    folders.update(path.parent for path in consumer_paths)
    for folder in folders:
        if not folder.is_dir():
            continue
        for link in folder.iterdir():
            if not link.is_symlink():
                continue
            if link == base / "retired":
                continue  # Native pending-retirement marker is not a consumer.
            try:
                target = link.resolve(strict=True)
            except (OSError, RuntimeError):
                evidence.append("unresolved-symlink:" + link.name)
                continue
            if target == release.resolve() or release.resolve() in target.parents:
                evidence.append("symlink:" + link.name + ":" + name)
    for path in consumer_paths:
        try:
            if path.is_file() and str(release) in path.read_text(errors="replace"):
                evidence.append("unit-or-config:" + path.name + ":" + name)
        except OSError:
            evidence.append("unreadable-consumer:" + path.name)
    return evidence


def promote(revision, *, host, base=BASE, consumer_paths=None):
    """Commit a healthy revision, keep its exact predecessor and prune proven-unused ones.

    Returns a result with detailed blockers. A deletion blocker does not undo
    activation: selectors remain correct and the candidate remains available.
    """
    base = Path(base)
    releases = base / "releases"
    if base.is_symlink() or releases.is_symlink() or not REVISION.fullmatch(revision):
        raise RuntimeError("unsafe-release-root-or-revision")
    selected = releases / revision
    if selected.is_symlink() or not (selected / "dist/index.js").is_file():
        raise RuntimeError("missing-immutable-release:" + revision)
    old = _selector(base, "current", releases)
    previous = _selector(base, "rollback", releases)
    pending = _selector(base, "retired", releases)
    if previous == old and previous is not None and not pending:
        raise RuntimeError("invalid-duplicate-rollback")
    if pending and old != revision and previous not in (pending, old):
        raise RuntimeError("retirement-pending:" + pending)
    retiring = pending or (previous if old != revision else None)
    # Health is proven before mutating a selector or touching a release.
    runtime_health(host, selected, Path.home())
    if old != revision:
        if retiring and not pending:
            _point(base, "retired", retiring)
        if old is not None:
            _point(base, "rollback", old)
        _point(base, "current", revision)
    keep = {revision}
    rollback = old if old and old != revision else previous
    if rollback:
        keep.add(rollback)
    paths = list(_consumer_paths(host, Path.home()) if consumer_paths is None
                 else consumer_paths)
    candidates = []
    blockers = []
    for path in releases.iterdir():
        if path.is_symlink():
            blockers.append("uncertain-revision:" + path.name)
        elif path.is_dir() and (path / "dist/index.js").is_file():
            if not REVISION.fullmatch(path.name):
                blockers.append("uncertain-revision:" + path.name)
            elif path.name == retiring:
                # Only a previously healthy rollback is eligible for retirement.
                candidates.append(path)
            elif path.name not in keep:
                blockers.append("unproven-history:" + path.name)
    for release in candidates:
        blockers.extend(_obstructions(base, release, paths))
    removed = []
    if not blockers:
        for release in candidates:
            # Recheck immediately before each potentially destructive operation.
            fresh = _obstructions(base, release, paths)
            if fresh:
                blockers.extend(fresh)
                break
            shutil.rmtree(release)
            removed.append(release.name)
            if (base / "retired").is_symlink():
                (base / "retired").unlink()
    return {"selected": revision, "rollback": rollback, "removed": removed,
            "blocked": sorted(set(blockers))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", choices=["studio", "minipc"])
    parser.add_argument("--release", required=True, help="40-character installed revision")
    args = parser.parse_args()
    result = promote(args.release, host=args.host)
    print(json.dumps(result, sort_keys=True))
    return 2 if result["blocked"] else 0


if __name__ == "__main__":
    sys.exit(main())
