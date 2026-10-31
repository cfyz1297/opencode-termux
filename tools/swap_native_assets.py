#!/usr/bin/env python3
"""Put the Bionic native assets into an installed OpenCode source tree.

`bun build --compile` embeds the native libraries of the platform packages it
resolves, the glibc linux-arm64 ones on the build host. This replaces those
files in node_modules with the Bionic builds before compiling, and applies the
patches of dependencies that need one on Android.

Every package must be installed at the version work/natives.json names: the
Bionic assets are built from those sources (tools/resolve_natives.py reads them
from the same bun.lock), so a mismatch fails here instead of shipping a
mismatched library. Files are replaced, never written in
place, because Bun hardlinks node_modules to its global cache.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

# (natives.json key, npm package, file inside the package); tools/resolve_natives.py
# reads each key's version from bun.lock under these package names.
ASSETS = [
    ("opentui", "@opentui/core-linux-arm64", "libopentui.so"),
    ("watcher", "@parcel/watcher-linux-arm64-glibc", "watcher.node"),
    ("fff", "@ff-labs/fff-bin-linux-arm64-gnu", "libfff_c.so"),
    ("rust_pty", "bun-pty", "rust-pty/target/release/librust_pty_arm64.so"),
    # bun-pty also embeds its musl build on Linux, loaded only under ld-musl. It
    # needs `libc.so` like Bionic does, so the audit cannot tell it apart.
    ("rust_pty", "bun-pty", "rust-pty/target/release/librust_pty_arm64_musl.so"),
    # A static executable OpenCode starts, see scripts/build-opencode-pty.sh.
    ("opencode_pty", "@opencode/pty-linux-arm64-gnu", "bin/opencode-pty"),
]
# (natives.json key, npm package, patch file under patches/)
PATCHES = [
    ("fff", "@ff-labs/fff-bun", "fff-bun-android.patch"),
]


class SwapError(Exception):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _scan_node_modules(node_modules: str, name: str, found: set[str]) -> None:
    """Find `name` in a node_modules tree: hoisted, nested or Bun's .bun store."""
    candidate = os.path.join(node_modules, name)
    if os.path.isfile(os.path.join(candidate, "package.json")):
        found.add(os.path.realpath(candidate))
    try:
        entries = list(os.scandir(node_modules))
    except OSError:
        return
    for entry in entries:
        if not entry.is_dir(follow_symlinks=False):
            continue
        if entry.name == ".bun":
            for store in os.scandir(entry.path):
                if store.is_dir(follow_symlinks=False):
                    _scan_node_modules(os.path.join(store.path, "node_modules"), name, found)
        elif entry.name.startswith("@"):
            for package in os.scandir(entry.path):
                if package.is_dir(follow_symlinks=False):
                    _scan_node_modules(os.path.join(package.path, "node_modules"), name, found)
        else:
            _scan_node_modules(os.path.join(entry.path, "node_modules"), name, found)


def find_packages(root: Path, name: str) -> list[Path]:
    """Real directories of every installed copy of `name` under the workspace."""
    found: set[str] = set()
    stack = [str(root)]
    while stack:
        directory = stack.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir(follow_symlinks=False) or entry.name in (".git", "dist"):
                continue
            if entry.name == "node_modules":
                _scan_node_modules(entry.path, name, found)
            else:
                stack.append(entry.path)
    return sorted(Path(path) for path in found)


def package_version(package: Path) -> str:
    return json.loads((package / "package.json").read_text())["version"]


def pinned(root: Path, name: str, version: str) -> list[Path]:
    copies = find_packages(root, name)
    matching = [package for package in copies if package_version(package) == version]
    if not matching:
        installed = sorted({package_version(package) for package in copies}) or ["none"]
        raise SwapError(
            f"{name}: natives.json names {version}, installed: {', '.join(installed)}"
        )
    return matching


def replace_file(target: Path, source: Path) -> None:
    mode = target.stat().st_mode & 0o7777
    target.unlink()
    shutil.copyfile(source, target)
    target.chmod(mode)


def unshare(path: Path) -> None:
    """Give `path` its own inode, so editing it cannot reach Bun's cache."""
    data = path.read_bytes()
    mode = path.stat().st_mode & 0o7777
    path.unlink()
    path.write_bytes(data)
    path.chmod(mode)


def patched_files(patch: Path) -> list[str]:
    return re.findall(r"^\+\+\+ b/(\S+)", patch.read_text(), re.MULTILINE)


def swap(root: Path, versions: dict, replacements: dict[str, Path], patches_dir: Path) -> dict:
    report: dict = {"assets": [], "patches": []}
    for key, name, relative in ASSETS:
        source = replacements[key]
        if not source.is_file():
            raise SwapError(f"{key}: Bionic asset is missing: {source}")
        for package in pinned(root, name, versions[key]["version"]):
            target = package / relative
            if not target.is_file():
                raise SwapError(f"{name}: package has no {relative}")
            original = sha256(target)
            replace_file(target, source)
            report["assets"].append({
                "package": f"{name}@{versions[key]['version']}",
                "file": relative,
                "path": str(target.relative_to(root)) if target.is_relative_to(root) else str(target),
                "original_sha256": original,
                "sha256": sha256(target),
            })
    for key, name, patch_name in PATCHES:
        patch = patches_dir / patch_name
        for package in pinned(root, name, versions[key]["version"]):
            for relative in patched_files(patch):
                unshare(package / relative)
            result = subprocess.run(
                ["patch", "-p1", "--fuzz=0", "--batch", "--forward", "--no-backup-if-mismatch",
                 "-d", str(package), "-i", str(patch)],
                text=True, capture_output=True,
            )
            if result.returncode != 0:
                raise SwapError(f"{patch_name} does not apply to {name}:\n{result.stdout}{result.stderr}")
            report["patches"].append({
                "package": f"{name}@{versions[key]['version']}",
                "patch": patch_name,
                "sha256": sha256(patch),
            })
    return report


def main() -> int:
    tools = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="installed OpenCode source tree")
    parser.add_argument("--versions", type=Path, default=tools.parent / "work" / "natives.json")
    parser.add_argument("--patches", type=Path, default=tools.parent / "patches")
    keys = list(dict.fromkeys(key for key, _, _ in ASSETS))
    for key in keys:
        parser.add_argument(f"--{key.replace('_', '-')}", type=Path, required=True,
                            help=f"Bionic replacement for the {key} asset")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    versions = json.loads(args.versions.read_text())
    replacements = {key: getattr(args, key) for key in keys}
    try:
        report = swap(args.source.resolve(), versions, replacements, args.patches)
    except SwapError as error:
        parser.exit(1, f"swap_native_assets: {error}\n")
    encoded = json.dumps(report, indent=2) + "\n"
    if args.report:
        args.report.write_text(encoded)
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
