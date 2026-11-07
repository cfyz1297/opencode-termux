#!/usr/bin/env python3
"""Resolve the native dependencies to build for one OpenCode source tree.

OpenCode's bun.lock decides which version of each native package `bun install`
puts into node_modules, and package.json's packageManager which Bun builds it.
The Bionic replacements must be built from exactly those versions, so they are
read from the source being built rather than pinned by hand; versions.json only
says where each one's source lives:

- GitHub sources: the tag is resolved to its commit with `git ls-remote` and the
  archive is fetched by commit, as scripts/fetch-source.sh does for OpenCode.
- npm sources: the registry tarball, checked against bun.lock's integrity hash.
- Bun: the release assets, checked against the release's SHASUMS256.txt.

Zig is a toolchain we choose, not a dependency OpenCode installs: each component
built with it names one of versions.json's "zig" entries, and resolving fails
when the component's source asks for a Zig that entry cannot be.

Writes work/natives.json with the fields the build scripts read for each
component (version, source_url, source_sha256, ...) and where each came from.

  resolve_natives.py SOURCE [--versions versions.json] [--out work/natives.json]
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from swap_native_assets import ASSETS, PATCHES  # noqa: E402

BUN_RELEASES = "https://github.com/oven-sh/bun/releases/download"


class ResolveError(Exception):
    pass


def parse_bun_lock(text: str) -> dict:
    """bun.lock is JSON with trailing commas; drop those outside strings."""
    out = []
    in_string = escaped = False
    i = 0
    while i < len(text):
        c = text[i]
        if in_string:
            out.append(c)
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                in_string = False
        elif c == '"':
            in_string = True
            out.append(c)
        elif c == ",":
            j = i + 1
            while j < len(text) and text[j] in " \t\r\n":
                j += 1
            if j == len(text) or text[j] not in "}]":
                out.append(c)
        else:
            out.append(c)
        i += 1
    return json.loads("".join(out))


def lock_entries(lock: dict, name: str) -> list[tuple[str, str, list]]:
    """(lock key, version, entry) of every installed copy of `name`."""
    found = []
    for key, entry in lock.get("packages", {}).items():
        if entry and isinstance(entry[0], str):
            spec_name, _, version = entry[0].rpartition("@")
            if spec_name == name:
                found.append((key, version, entry))
    return found


def single_version(lock: dict, names: list[str]) -> str:
    """The one version all of `names` are installed at."""
    versions = {}
    for name in names:
        found = {version for _, version, _ in lock_entries(lock, name)}
        if not found:
            raise ResolveError(
                f"{name} is not in bun.lock: did upstream rename or drop it? "
                "Update tools/swap_native_assets.py and versions.json.")
        versions[name] = found
    every = set().union(*versions.values())
    if len(every) != 1:
        raise ResolveError(f"expected one version, bun.lock has {versions}")
    return every.pop()


def integrity(lock: dict, name: str, version: str) -> str:
    for _, found, entry in lock_entries(lock, name):
        if found == version and isinstance(entry[-1], str) and entry[-1].startswith("sha512-"):
            return entry[-1]
    raise ResolveError(f"bun.lock has no sha512 integrity for {name}@{version}")


def installed_dependency(lock: dict, parent: str, dependency: str) -> str:
    """The version of `dependency` that `parent` gets: its nested copy, else the hoisted one."""
    packages = lock.get("packages", {})
    for key in (f"{parent}/{dependency}", dependency):
        entry = packages.get(key)
        if entry:
            return entry[0].rpartition("@")[2]
    raise ResolveError(f"bun.lock does not install {dependency} for {parent}")


def npm_tarball_url(name: str, version: str) -> str:
    return f"https://registry.npmjs.org/{name}/-/{name.rpartition('/')[2]}-{version}.tgz"


class Network:
    """Downloads and git queries, with the retries this flaky network needs."""

    def fetch(self, url: str) -> bytes:
        with tempfile.NamedTemporaryFile() as out:
            subprocess.run(["curl", "-fsSL", "--retry", "5", "--retry-all-errors", "-o", out.name, url],
                           check=True)
            return Path(out.name).read_bytes()

    def tag_commit(self, repo: str, tag: str) -> str:
        refs = subprocess.run(
            ["git", "ls-remote", f"https://github.com/{repo}.git", f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"],
            check=True, capture_output=True, text=True).stdout
        lines = [line.split() for line in refs.splitlines() if line.strip()]
        # An annotated tag lists its commit as the peeled refs/tags/X^{} entry.
        peeled = [sha for sha, ref in lines if ref.endswith("^{}")]
        commit = (peeled or [sha for sha, _ in lines] or [""])[0]
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise ResolveError(f"tag {tag} not found in {repo}: check its tag pattern in versions.json")
        return commit


def check_sha512(data: bytes, expected: str, what: str) -> None:
    if base64.b64encode(hashlib.sha512(data).digest()).decode() != expected.removeprefix("sha512-"):
        raise ResolveError(f"{what} does not match bun.lock's integrity hash")


def resolve_github(net: Network, recipe: dict, version: str) -> tuple[dict, bytes]:
    tag = recipe["tag"].format(version=version)
    commit = net.tag_commit(recipe["github"], tag)
    url = f"https://codeload.github.com/{recipe['github']}/tar.gz/{commit}"
    data = net.fetch(url)
    return {"tag": tag, "commit": commit, "source_url": url,
            "source_sha256": hashlib.sha256(data).hexdigest()}, data


def resolve_npm(net: Network, lock: dict, name: str, version: str) -> dict:
    url = npm_tarball_url(name, version)
    data = net.fetch(url)
    check_sha512(data, integrity(lock, name, version), f"{name}@{version}")
    return {"source_url": url, "source_sha256": hashlib.sha256(data).hexdigest()}


def archive_text(archive: bytes, path: str) -> str | None:
    """`path` in a GitHub source archive, below the archive's top directory."""
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for member in tar:
            if member.isfile() and member.name.partition("/")[2] == path:
                return tar.extractfile(member).read().decode()
    return None


def zig_needed(key: str, archive: bytes) -> str | None:
    """The Zig a component's source asks for, where it says so."""
    if key == "opentui":
        # The oldest Zig OpenTUI's build accepts.
        text = archive_text(archive, "packages/native/build.zig.zon")
        pattern = r'\.minimum_zig_version\s*=\s*"([^"]+)"'
    elif key == "opencode_pty":
        # The Zig upstream releases opencode-pty with: the Ghostty it builds
        # accepts no other minor version.
        text = archive_text(archive, ".github/workflows/release-process-daemon.yml")
        pattern = r'^\s*ZIG_VERSION:\s*"?(\d[^"\s]*)"?\s*$'
    else:
        return None
    match = text and re.search(pattern, text, re.MULTILINE)
    return match.group(1) if match else None


def version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version.split("-")[0]))


def check_zig(versions: dict, key: str, version: str, archive: bytes) -> None:
    """Fail now, not after an hour of building, when the Zig versions.json gives a component cannot build it."""
    pinned = versions[key].get("zig")
    if pinned is None:
        return
    if pinned not in versions["zig"]:
        raise ResolveError(f"versions.json gives {key} Zig {pinned} but has no such entry under \"zig\"")
    needed = zig_needed(key, archive)
    if not needed:
        return
    label = {"opentui": "OpenTUI", "opencode_pty": "opencode-pty"}[key]
    needed_v, pinned_v = version_tuple(needed), version_tuple(pinned)
    fits = needed_v <= pinned_v
    if key == "opencode_pty":
        # Ghostty's requireZig: the same minor version, at least that patch.
        fits = fits and needed_v[:2] == pinned_v[:2]
    if not fits:
        raise ResolveError(f"{label} {version} needs Zig {needed}; versions.json gives it {pinned}")


def resolve_bun(net: Network, recipe: dict, package_json: dict) -> dict:
    # versions.json may name a version to use instead, while one has a problem on Android.
    version = recipe.get("version")
    if not version:
        spec = package_json.get("packageManager", "")
        match = re.fullmatch(r"bun@(\d+\.\d+\.\d+)", spec)
        if not match:
            raise ResolveError(f"package.json packageManager is {spec!r}, not an exact bun@X.Y.Z")
        version = match.group(1)
    base = f"{BUN_RELEASES}/bun-v{version}"
    sums = {}
    for line in net.fetch(f"{base}/SHASUMS256.txt").decode().splitlines():
        parts = line.split()
        if len(parts) == 2:
            sums[parts[1]] = parts[0]
    out = {}
    for key, asset in (("base_bun", recipe["android_asset"]), ("host_bun", recipe["host_asset"])):
        if asset not in sums:
            raise ResolveError(f"Bun {version} publishes no {asset}")
        out[key] = {"version": version, "url": f"{base}/{asset}", "archive_sha256": sums[asset]}
    return out


def resolve(source: Path, versions: dict, net: Network) -> dict:
    lock = parse_bun_lock((source / "bun.lock").read_text())
    package_json = json.loads((source / "package.json").read_text())
    doc = resolve_bun(net, versions["bun"], package_json)

    names: dict[str, list[str]] = {}
    for key, name, _ in ASSETS + PATCHES:
        names.setdefault(key, [])
        if name not in names[key]:
            names[key].append(name)

    for key, packages in names.items():
        recipe = versions[key]
        version = single_version(lock, packages)
        entry = {"version": version, "packages": packages}
        entry.update({k: v for k, v in recipe.items() if k not in ("github", "tag", "npm", "node_addon_api")})
        if "github" in recipe:
            found, archive = resolve_github(net, recipe, version)
            entry.update(found)
            check_zig(versions, key, version, archive)
        else:
            npm = recipe["npm"]
            if single_version(lock, [npm]) != version:
                raise ResolveError(f"{npm} and {packages} are installed at different versions")
            entry.update(resolve_npm(net, lock, npm, version))
            if "node_addon_api" in recipe:
                dependency = recipe["node_addon_api"]
                addon = installed_dependency(lock, npm, dependency)
                found = resolve_npm(net, lock, dependency, addon)
                entry.update({"node_addon_api_version": addon,
                              "node_addon_api_url": found["source_url"],
                              "node_addon_api_sha256": found["source_sha256"]})
        doc[key] = entry
    return doc


def main() -> int:
    tools = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="OpenCode source tree (make fetch-source)")
    parser.add_argument("--versions", type=Path, default=tools.parent / "versions.json")
    parser.add_argument("--out", type=Path, default=tools.parent / "work" / "natives.json")
    args = parser.parse_args()
    try:
        doc = resolve(args.source, json.loads(args.versions.read_text()), Network())
    except (ResolveError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"resolve_natives: {error}\n")
    source_json = args.source.parent / "source.json"
    if source_json.exists():
        doc = {"opencode": json.loads(source_json.read_text()), **doc}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, indent=2) + "\n")
    for key, entry in doc.items():
        if key != "opencode":
            print(f"{key:13} {entry['version']:10} {entry.get('tag') or entry.get('source_url') or entry.get('url')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
