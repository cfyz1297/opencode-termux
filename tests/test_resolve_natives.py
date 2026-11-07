#!/usr/bin/env python3
"""tools/resolve_natives.py against a fake bun.lock and a fake network."""

import base64
import hashlib
import io
import json
import pathlib
import sys
import tarfile
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import resolve_natives as resolver  # noqa: E402

VERSIONS = json.loads((ROOT / "versions.json").read_text())


def sha512(data):
    return "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode()


def source_archive(top, files):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tar:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(f"{top}/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return out.getvalue()


WATCHER = b"watcher tarball"
ADDON = b"node-addon-api tarball"
SHASUMS = b"""aaaa  bun-linux-aarch64-android.zip
bbbb  bun-linux-aarch64.zip
cccc  bun-darwin-aarch64.zip
"""


def lock_text(**overrides):
    """A bun.lock in Bun's text format: JSON with trailing commas."""
    packages = {
        "@opentui/core-linux-arm64": ["@opentui/core-linux-arm64@0.8.0", "", {"os": "linux"}, "sha512-x"],
        "@parcel/watcher": ["@parcel/watcher@2.5.1", "", {"dependencies": {"node-addon-api": "^7.0.0"}},
                            sha512(WATCHER)],
        "@parcel/watcher-linux-arm64-glibc": ["@parcel/watcher-linux-arm64-glibc@2.5.1", "", {}, "sha512-x"],
        "node-addon-api": ["node-addon-api@7.1.1", "", {}, sha512(ADDON)],
        "@ff-labs/fff-bin-linux-arm64-gnu": ["@ff-labs/fff-bin-linux-arm64-gnu@0.10.5", "", {}, "sha512-x"],
        "@ff-labs/fff-bun": ["@ff-labs/fff-bun@0.10.5", "", {}, "sha512-x"],
        "bun-pty": ["bun-pty@0.4.11", "", {}, "sha512-x"],
        "@opencode/pty-linux-arm64-gnu": ["@opencode/pty-linux-arm64-gnu@0.4.0", "", {}, "sha512-x"],
        "unrelated": ["unrelated@1.0.0", "", {"description": "a,] b"}, "sha512-x"],
    }
    packages.update(overrides)
    body = json.dumps({"lockfileVersion": 1, "packages": packages}, indent=2)
    # Bun writes a comma after every last element.
    return body.replace("\n}", ",\n}").replace('"\n  }', '",\n  }').replace("]\n", "],\n")


def zig_zon(version):
    return f'.{{ .minimum_zig_version = "{version}", }}'


def process_daemon_workflow(zig):
    return f"env:\n  CARGO_TERM_COLOR: always\n  ZIG_VERSION: {zig}\n  GNU_GLIBC_VERSION: \"2.30\"\n"


def newer_minor(version):
    major, minor, _ = resolver.version_tuple(version)
    return f"{major}.{minor + 1}.0"


class FakeNetwork:
    def __init__(self, files=None, tags=None):
        self.opentui = source_archive("opentui-abc", {
            "packages/native/build.zig.zon": zig_zon(VERSIONS["opentui"]["zig"])})
        self.opencode = source_archive("opencode-abc", {
            ".github/workflows/release-process-daemon.yml": process_daemon_workflow(VERSIONS["opencode_pty"]["zig"]),
            "packages/process-daemon/Cargo.toml": "[package]\n"})
        self.files = {
            "https://github.com/oven-sh/bun/releases/download/bun-v1.4.4/SHASUMS256.txt": SHASUMS,
            "https://registry.npmjs.org/@parcel/watcher/-/watcher-2.5.1.tgz": WATCHER,
            "https://registry.npmjs.org/node-addon-api/-/node-addon-api-7.1.1.tgz": ADDON,
        }
        self.files.update(files or {})
        self.tags = {
            ("anomalyco/opentui", "v0.8.0"): "1" * 40,
            ("dmtrKovalenko/fff", "v0.10.5"): "2" * 40,
            ("sursaone/bun-pty", "v0.4.11"): "3" * 40,
            ("anomalyco/opencode", "process-daemon-v0.4.0"): "4" * 40,
        }
        self.tags.update(tags or {})

    def fetch(self, url):
        if url.startswith("https://codeload.github.com/anomalyco/opentui/"):
            return self.opentui
        if url.startswith("https://codeload.github.com/anomalyco/opencode/"):
            return self.opencode
        if url.startswith("https://codeload.github.com/"):
            return url.encode()
        return self.files[url]

    def tag_commit(self, repo, tag):
        if (repo, tag) not in self.tags:
            raise resolver.ResolveError(f"tag {tag} not found in {repo}")
        return self.tags[(repo, tag)]


class ResolveTests(unittest.TestCase):
    def resolve(self, lock=None, package_manager="bun@1.4.4", net=None, versions=VERSIONS):
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp)
            (source / "bun.lock").write_text(lock if lock is not None else lock_text())
            (source / "package.json").write_text(json.dumps({"packageManager": package_manager}))
            return resolver.resolve(source, versions, net or FakeNetwork())

    def test_versions_come_from_the_lock(self):
        doc = self.resolve()
        self.assertEqual({k: doc[k]["version"] for k in doc}, {
            "base_bun": "1.4.4", "host_bun": "1.4.4", "opentui": "0.8.0", "watcher": "2.5.1",
            "fff": "0.10.5", "rust_pty": "0.4.11", "opencode_pty": "0.4.0"})

    def test_github_sources_are_fetched_by_commit(self):
        net = FakeNetwork()
        doc = self.resolve(net=net)
        pty = doc["opencode_pty"]
        self.assertEqual(pty["tag"], "process-daemon-v0.4.0")
        self.assertEqual(pty["source_url"], "https://codeload.github.com/anomalyco/opencode/tar.gz/" + "4" * 40)
        self.assertEqual(pty["source_sha256"], hashlib.sha256(net.opencode).hexdigest())
        rust_pty = doc["rust_pty"]
        self.assertEqual(rust_pty["source_sha256"], hashlib.sha256(rust_pty["source_url"].encode()).hexdigest())
        # Recipe fields the build scripts read pass through.
        self.assertEqual((pty["source_dir"], pty["target"]),
                         ("packages/process-daemon", "aarch64-unknown-linux-musl"))
        self.assertEqual(doc["fff"]["packages"],
                         ["@ff-labs/fff-bin-linux-arm64-gnu", "@ff-labs/fff-bun"])

    def test_npm_sources_are_checked_against_the_lock(self):
        watcher = self.resolve()["watcher"]
        self.assertEqual(watcher["source_sha256"], hashlib.sha256(WATCHER).hexdigest())
        self.assertEqual(watcher["node_addon_api_version"], "7.1.1")
        self.assertEqual(watcher["node_addon_api_sha256"], hashlib.sha256(ADDON).hexdigest())
        tampered = FakeNetwork({"https://registry.npmjs.org/@parcel/watcher/-/watcher-2.5.1.tgz": b"evil"})
        with self.assertRaisesRegex(resolver.ResolveError, "integrity"):
            self.resolve(net=tampered)

    def test_watcher_gets_its_nested_node_addon_api(self):
        nested = ["node-addon-api@8.0.0", "", {}, sha512(b"eight")]
        net = FakeNetwork({"https://registry.npmjs.org/node-addon-api/-/node-addon-api-8.0.0.tgz": b"eight"})
        watcher = self.resolve(lock_text(**{"@parcel/watcher/node-addon-api": nested}), net=net)["watcher"]
        self.assertEqual(watcher["node_addon_api_version"], "8.0.0")

    def test_bun_follows_package_manager_and_its_checksums(self):
        doc = self.resolve()
        self.assertEqual(doc["base_bun"], {
            "version": "1.4.4", "archive_sha256": "aaaa",
            "url": "https://github.com/oven-sh/bun/releases/download/bun-v1.4.4/bun-linux-aarch64-android.zip"})
        self.assertEqual(doc["host_bun"]["archive_sha256"], "bbbb")

    def test_bun_version_in_versions_json_wins(self):
        net = FakeNetwork({"https://github.com/oven-sh/bun/releases/download/bun-v1.4.5/SHASUMS256.txt": SHASUMS})
        doc = self.resolve(net=net, versions=dict(VERSIONS, bun=dict(VERSIONS["bun"], version="1.4.5")))
        self.assertEqual(doc["host_bun"]["version"], "1.4.5")

    def test_bun_range_is_not_enough(self):
        with self.assertRaisesRegex(resolver.ResolveError, "packageManager"):
            self.resolve(package_manager="bun@^1.4.4")

    def test_two_versions_of_a_native_package_fail(self):
        second = ["@opentui/core-linux-arm64@0.7.0", "", {}, "sha512-x"]
        with self.assertRaisesRegex(resolver.ResolveError, "expected one version"):
            self.resolve(lock_text(**{"some/@opentui/core-linux-arm64": second}))

    def test_packages_that_disagree_fail(self):
        older = ["@ff-labs/fff-bun@0.10.4", "", {}, "sha512-x"]
        with self.assertRaisesRegex(resolver.ResolveError, "expected one version"):
            self.resolve(lock_text(**{"@ff-labs/fff-bun": older}))

    def test_renamed_package_says_so(self):
        text = lock_text().replace("@opencode/pty-linux-arm64-gnu", "@opencode/pty2-linux-arm64-gnu")
        with self.assertRaisesRegex(resolver.ResolveError, "@opencode/pty-linux-arm64-gnu is not in bun.lock"):
            self.resolve(text)

    def test_missing_tag_points_at_versions_json(self):
        net = FakeNetwork()
        del net.tags[("sursaone/bun-pty", "v0.4.11")]
        with self.assertRaisesRegex(resolver.ResolveError, "v0.4.11 not found in sursaone/bun-pty"):
            self.resolve(net=net)

    def test_zig_built_components_say_which_zig(self):
        doc = self.resolve()
        # build-opentui.sh and build-opencode-pty.sh look this up in versions.json's "zig".
        self.assertEqual(doc["opentui"]["zig"], VERSIONS["opentui"]["zig"])
        self.assertEqual(doc["opencode_pty"]["zig"], VERSIONS["opencode_pty"]["zig"])
        self.assertNotIn("zig", doc["fff"])

    def test_opentui_needing_a_newer_zig_fails_early(self):
        newer = newer_minor(VERSIONS["opentui"]["zig"])
        net = FakeNetwork()
        net.opentui = source_archive("opentui-abc", {"packages/native/build.zig.zon": zig_zon(newer)})
        with self.assertRaisesRegex(resolver.ResolveError, f"OpenTUI 0.8.0 needs Zig {newer}"):
            self.resolve(net=net)

    def test_opentui_on_an_older_zig_resolves(self):
        net = FakeNetwork()
        net.opentui = source_archive("opentui-abc", {"packages/native/build.zig.zon": zig_zon("0.1.0")})
        self.assertEqual(self.resolve(net=net)["opentui"]["version"], "0.8.0")

    def test_opencode_pty_on_another_zig_minor_fails_early(self):
        pinned = VERSIONS["opencode_pty"]["zig"]
        major, minor, _ = resolver.version_tuple(pinned)
        # Ghostty takes neither a newer nor an older minor version.
        for other in (newer_minor(pinned), f"{major}.{minor - 1}.0"):
            net = FakeNetwork()
            net.opencode = source_archive("opencode-abc", {
                ".github/workflows/release-process-daemon.yml": process_daemon_workflow(other)})
            with self.subTest(other=other), self.assertRaisesRegex(
                    resolver.ResolveError, f"opencode-pty 0.4.0 needs Zig {other}; versions.json gives it {pinned}"):
                self.resolve(net=net)

    def test_opencode_pty_needing_a_newer_patch_fails_early(self):
        major, minor, patch = resolver.version_tuple(VERSIONS["opencode_pty"]["zig"])
        newer = f"{major}.{minor}.{patch + 1}"
        net = FakeNetwork()
        net.opencode = source_archive("opencode-abc", {
            ".github/workflows/release-process-daemon.yml": process_daemon_workflow(f'"{newer}"')})
        with self.assertRaisesRegex(resolver.ResolveError, f"needs Zig {newer}"):
            self.resolve(net=net)

    def test_a_source_that_does_not_say_is_not_checked(self):
        net = FakeNetwork()
        net.opencode = source_archive("opencode-abc", {"packages/process-daemon/Cargo.toml": "[package]\n"})
        self.assertEqual(self.resolve(net=net)["opencode_pty"]["version"], "0.4.0")

    def test_a_zig_versions_json_does_not_list_fails(self):
        versions = dict(VERSIONS, opentui=dict(VERSIONS["opentui"], zig="9.9.9"))
        with self.assertRaisesRegex(resolver.ResolveError, "gives opentui Zig 9.9.9 but has no such entry"):
            self.resolve(versions=versions)


class LockParserTests(unittest.TestCase):
    def test_trailing_commas_are_dropped_outside_strings(self):
        doc = resolver.parse_bun_lock('{"a": [1, 2,], "b": {"c": "x,]", "d": "\\",}",},}')
        self.assertEqual(doc, {"a": [1, 2], "b": {"c": "x,]", "d": '",}'}})

    def test_reads_opencode_s_lockfile_format(self):
        lock = resolver.parse_bun_lock(lock_text())
        self.assertEqual([v for _, v, _ in resolver.lock_entries(lock, "bun-pty")], ["0.4.11"])
        self.assertEqual(resolver.lock_entries(lock, "pty"), [])


class RecipeTests(unittest.TestCase):
    def test_every_swapped_package_has_a_recipe(self):
        for key, _, _ in resolver.ASSETS + resolver.PATCHES:
            recipe = VERSIONS[key]
            self.assertTrue(("github" in recipe and "{version}" in recipe["tag"]) or "npm" in recipe, key)
            self.assertNotIn("version", recipe, f"{key}: versions come from bun.lock")

    def test_bun_recipe_names_both_assets(self):
        self.assertEqual(set(VERSIONS["bun"]), {"android_asset", "host_asset"})

    def test_zig_built_components_name_a_listed_zig(self):
        for key in ("opentui", "opencode_pty"):
            self.assertIn(VERSIONS[key]["zig"], VERSIONS["zig"], key)

    def test_zig_entries_are_that_release(self):
        for version, zig in VERSIONS["zig"].items():
            self.assertRegex(version, r"^\d+\.\d+\.\d+$")
            for arch in ("aarch64", "x86_64"):
                self.assertEqual(zig[f"{arch}_linux_url"],
                                 f"https://ziglang.org/download/{version}/zig-{arch}-linux-{version}.tar.xz")
                self.assertRegex(zig[f"{arch}_linux_sha256"], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
