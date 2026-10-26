#!/usr/bin/env python3
"""Finalize an already healthy Desktop Commander activation, keeping exact rollback.

Only revision-named, reproducible release trees may be removed. All other
files (data, backup, staging, gateway binaries and private config) are outside
the deletion boundary.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
from urllib.request import urlopen

from consumer_proof import obstructions as inspect_obstructions

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
    path = shutil.which("lsof")
    if path not in ("/usr/sbin/lsof", "/usr/bin/lsof"):
        raise RuntimeError("incomplete-lsof-scan:unverified-scanner")
    command = [path, "-n", "-P", "-F", "n"]
    # Keep service checks and selectors under the owner account. Delegate
    # only read-only FD enumeration to privileged lsof; sudo -n never prompts.
    if os.geteuid() != 0:
        command = ["/usr/bin/sudo", "-n", *command]
    scan = subprocess.run(command, check=True,
                          capture_output=True, text=True, timeout=25)
    if scan.stderr.strip():
        raise RuntimeError("incomplete-lsof-scan")
    return [line[1:].split(" (deleted)")[0] for line in scan.stdout.splitlines()
            if line.startswith("n/")]


def _process_tree():
    scan = subprocess.run(["ps", "-axo", "pid=,ppid=,command="], check=True,
                          capture_output=True, text=True, timeout=12)
    rows = []
    for line in scan.stdout.splitlines():
        parts = line.strip().split(maxsplit=2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            rows.append((int(parts[0]), int(parts[1]), parts[2]))
    return rows


def _selected_node_is_child(selected, root_pid, processes):
    by_pid = {pid: (parent, command) for pid, parent, command in processes}
    entry = str(selected / "dist/index.js")
    for pid, (parent, command) in by_pid.items():
        try:
            args = shlex.split(command)
        except ValueError:
            continue
        if len(args) < 2 or Path(args[0]).name not in ("node", "nodejs") or entry not in args[1:]:
            continue
        seen = {pid}
        while parent in by_pid and parent not in seen:
            if parent == root_pid:
                return True
            seen.add(parent)
            parent = by_pid[parent][0]
        if parent == root_pid:
            return True
    return False


def _consumer_paths(host, home):
    if host == "studio":
        return [home / "Library/LaunchAgents",
                home / "Library/LaunchAgents/it.domenico.desktop-commander.plist"]
    return [home / ".config/desktop-commander/mcp.json",
            home / ".config/systemd/user/desktop-commander.service",
            home / ".config/desktop-commander/tunnel-profiles/computer-mcp/config.json",
            home / ".config/desktop-commander", home / ".config/systemd/user"]


def runtime_health(host, selected, home):
    """Require a running service with a real process and projected selected revision."""
    processes = _process_tree()
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
        match = re.search(r"\bpid = (\d+)", status.stdout)
        if not match or not _selected_node_is_child(selected, int(match.group(1)), processes):
            raise RuntimeError("missing-studio-node-child-for-selected-revision")
        # A live gateway command is not a health proof: the actual private MCP
        # server must initialize and answer tools/list on the running transport.
        subprocess.run(["node", str(Path(__file__).with_name("health_probe.mjs")),
                        str(selected), host], capture_output=True, text=True,
                       check=True, timeout=20)
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
        match = re.search(r"MainPID=(\d+)", status)
        if not match or not _selected_node_is_child(selected, int(match.group(1)), processes):
            raise RuntimeError("missing-minipc-node-child-for-selected-revision")
        with urlopen("http://127.0.0.1:8498/readyz", timeout=5) as response:
            if response.status != 200:
                raise RuntimeError("minipc-tunnel-not-ready")
        with urlopen("http://127.0.0.1:8498/health/mcp", timeout=5) as response:
            if response.status != 200:
                raise RuntimeError("minipc-mcp-not-ready")
        # Check actual MCP initialize and tools/list against the exact build,
        # independently of the tunnel listener's readyz response.
        subprocess.run(["node", str(Path(__file__).with_name("health_probe.mjs")),
                        str(selected), host], capture_output=True, text=True,
                       check=True, timeout=20)
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
    target = Path("releases") / release
    if temporary.is_symlink() and temporary.readlink() == target:
        # A crash can leave the exact pending atomic update. It is safe to
        # repeat only this exact operation, never an unrelated stale update.
        temporary.unlink()
    elif temporary.exists() or temporary.is_symlink():
        raise RuntimeError("pending-selector-update:" + label)
    temporary.symlink_to(target)
    temporary.replace(link)


def _retired(base, releases, selected, rollback):
    """Recover a completed removal whose retired marker was not yet cleared."""
    try:
        return _selector(base, "retired", releases)
    except RuntimeError as exc:
        if not str(exc).startswith("broken-selector:retired"):
            raise
        marker = base / "retired"
        if not marker.is_symlink():
            raise
        target = marker.readlink()
        if (len(target.parts) != 2 or target.parts[0] != "releases"
                or not REVISION.fullmatch(target.parts[1])
                or target.parts[1] in (selected, rollback)
                or (releases / target.parts[1]).exists()):
            raise
        marker.unlink()
        return None


def _obstructions(base, release, consumer_paths):
    return inspect_obstructions(base, release, consumer_paths,
                                process_references=process_references,
                                open_file_references=open_file_references)


def _promote_locked(revision, *, host, base=BASE, consumer_paths=None):
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
    # Check the selected native consumer before any recovery can repoint the
    # previous rollback or clear an interrupted retirement marker.
    runtime_health(host, selected, Path.home())
    old = _selector(base, "current", releases)
    previous = _selector(base, "rollback", releases)
    pending = _retired(base, releases, old, previous)
    if pending and old == revision and previous in (old, pending):
        # B is still active after a failed B->C activation. Restore the exact
        # prior healthy rollback A before clearing the retirement intent.
        if not (releases / pending / "dist/index.js").is_file():
            raise RuntimeError("incomplete-retirement:" + pending)
        if previous == old:
            _point(base, "rollback", pending)
        (base / "retired").unlink()
        previous, pending = pending, None
    elif pending and previous == old and old is not None:
        # Resume B->C after an interruption before current=C was published.
        # A is the true previous rollback, held by the pending marker until
        # C is proven healthy and becomes current.
        previous = pending
    if previous == old and previous is not None and not pending:
        # The previous attempt can have published rollback=A then crashed
        # before publishing current=B. Do not mistake A for an old rollback
        # eligible for retirement while A is still the current release.
        if old == revision:
            raise RuntimeError("invalid-duplicate-rollback")
        previous = None
    if old is None and previous:
        raise RuntimeError("orphan-rollback")
    if (pending and old != revision and previous not in (pending, old)
            and revision != previous):
        raise RuntimeError("retirement-pending:" + pending)
    # A rollback can itself become selected during an explicit revert. Such a
    # release must never be marked retired, even transiently.
    retiring = pending or (previous if old != revision and previous != revision else None)
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
    if pending and (releases / pending).is_dir() and not (
            releases / pending / "dist/index.js").is_file():
        blockers.append("incomplete-retirement:" + pending)
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
            if (not getattr(shutil.rmtree, "avoids_symlink_attacks", False)
                    or release.is_symlink() or release.name in keep):
                blockers.append("unsafe-remove-target:" + release.name)
                break
            identity = release.stat(follow_symlinks=False)
            if (_selector(base, "current", releases) != revision
                    or _selector(base, "rollback", releases) != rollback
                    or _selector(base, "retired", releases) != release.name):
                blockers.append("changed-selector-before-prune:" + release.name)
                break
            try:
                runtime_health(host, selected, Path.home())
            except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as exc:
                blockers.append("consumer-health-changed:" + type(exc).__name__)
                break
            fresh = _obstructions(base, release, paths)
            if fresh:
                blockers.extend(fresh)
                break
            if (release.is_symlink() or
                    release.stat(follow_symlinks=False) != identity):
                blockers.append("changed-release-before-prune:" + release.name)
                break
            shutil.rmtree(release)
            removed.append(release.name)
            if (base / "retired").is_symlink():
                (base / "retired").unlink()
    return {"selected": revision, "rollback": rollback, "removed": removed,
            "blocked": sorted(set(blockers))}


def promote(revision, *, host, base=BASE, consumer_paths=None):
    """Serialize the entire selector transaction and guarded retirement per host."""
    base = Path(base)
    if not base.is_dir() or base.is_symlink():
        raise RuntimeError("unsafe-release-root")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(base / ".retention.lock", flags, 0o600)
    with os.fdopen(descriptor, "r+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        return _promote_locked(revision, host=host, base=base,
                               consumer_paths=consumer_paths)


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
