#!/usr/bin/env python3
"""Seal an immutable build before activation, and prove its complete payload on retirement.

The seal is created in the build staging area by the native installer, before
the release is used or given private runtime state. Never seal a live release.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat

NAME = ".retention-manifest.json"
REVISION = re.compile(r"[a-f0-9]{40}\Z")
ALLOWED = {"dist", "hosting", "node_modules", "package.json", "vendor"}
PACKAGE = "@wonderwhy-er/desktop-commander"


def snapshot(root):
    """Record every child, without following links outside the release boundary."""
    root = Path(root)
    result = {}

    def walk(folder):
        with os.scandir(folder) as listing:
            for entry in sorted(listing, key=lambda item: item.name):
                path = Path(entry.path)
                relative = path.relative_to(root).as_posix()
                if relative == NAME:
                    continue
                metadata = path.lstat()
                if stat.S_ISLNK(metadata.st_mode):
                    result[relative] = ["symlink", os.readlink(path)]
                elif stat.S_ISDIR(metadata.st_mode):
                    result[relative] = ["directory"]
                    walk(path)
                elif stat.S_ISREG(metadata.st_mode):
                    digest = hashlib.sha256()
                    with path.open("rb") as stream:
                        for block in iter(lambda: stream.read(1024 * 1024), b""):
                            digest.update(block)
                    result[relative] = ["file", digest.hexdigest()]
                else:
                    raise ValueError("unsupported-file-type")

    walk(root)
    return result


def seal(root):
    """Called once after packaging from trusted source, before first activation."""
    root = Path(root)
    if root.is_symlink() or not REVISION.fullmatch(root.name) or root.parent.name != "releases":
        raise ValueError("invalid-immutable-build-root")
    manifest = root / NAME
    if manifest.exists() or manifest.is_symlink():
        raise ValueError("already-sealed")
    if not (root / "dist/index.js").is_file():
        raise ValueError("missing-compiled-entrypoint")
    if json.loads((root / "package.json").read_text()).get("name") != PACKAGE:
        raise ValueError("unverified-package")
    if {path.name for path in root.iterdir()} - ALLOWED:
        raise ValueError("unexpected-top-level-payload")
    files = snapshot(root)
    protected = {"backup", "backups", "staging", "_local", "private", "venv", ".venv"}
    if any(set(path.lower().split("/")) & protected for path in files):
        raise ValueError("protected-build-payload")
    if any(path.startswith("hosting/data/") or path.startswith("hosting/state/")
           for path in files):
        raise ValueError("runtime-data-inside-build")
    temp = root / (NAME + ".new")
    try:
        with temp.open("x", encoding="utf-8") as output:
            json.dump({"format": 1, "revision": root.name, "files": files}, output,
                      sort_keys=True, separators=(",", ":"))
            output.flush()
            os.fsync(output.fileno())
        temp.replace(manifest)
    finally:
        if temp.exists():
            temp.unlink()


def verify(root):
    root = Path(root)
    try:
        with (root / NAME).open(encoding="utf-8") as stream:
            manifest = json.load(stream)
        if (manifest.get("format") != 1 or manifest.get("revision") != root.name
                or not isinstance(manifest.get("files"), dict)):
            return False
        return snapshot(root) == manifest["files"]
    except (OSError, ValueError, TypeError, RecursionError):
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal", required=True, type=Path,
                        help="Trusted staged SHA directory before first activation")
    args = parser.parse_args()
    seal(args.seal)
    print("sealed=" + args.seal.name)
