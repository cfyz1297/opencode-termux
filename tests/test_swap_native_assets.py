#!/usr/bin/env python3
"""tools/swap_native_assets.py against fake node_modules trees."""

import json
import os
import pathlib
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import swap_native_assets as swap  # noqa: E402

VERSIONS = {
    "opentui": {"version": "0.4.5"},
    "watcher": {"version": "2.5.1"},
    "fff": {"version": "0.9.4"},
    "rust_pty": {"version": "0.4.8"},
    "opencode_pty": {"version": "0.2.0"},
}
# Android, and so Termux's Python, has no hard links.
HARDLINKS = hasattr(os, "link")
FFI_BEFORE = "const handlePtr = read.ptr(resultPtr, RES_HANDLE);\n"
FFI_AFTER = "const handlePtr = read.u64(resultPtr, RES_HANDLE);\n"
FFF_PATCH = f"""diff --git a/src/ffi.ts b/src/ffi.ts
--- a/src/ffi.ts
+++ b/src/ffi.ts
@@ -1 +1 @@
-{FFI_BEFORE}+{FFI_AFTER}"""


def package(directory, name, version, files):
    directory.mkdir(parents=True)
    (directory / "package.json").write_text(json.dumps({"name": name, "version": version}))
    for relative, contents in files.items():
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)
    return directory


class SwapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = pathlib.Path(self.tmp.name)
        self.src = base / "src"
        self.cache = base / "cache"
        self.cache.mkdir()
        modules = self.src / "node_modules"

        # Bun's isolated linker: the store holds the package, node_modules links to it.
        store = modules / ".bun" / "@opentui+core-linux-arm64@0.4.5" / "node_modules" / "@opentui"
        self.opentui = package(store / "core-linux-arm64", "@opentui/core-linux-arm64", "0.4.5",
                               {"libopentui.so": "glibc opentui"})
        (modules / "@opentui").mkdir(parents=True)
        (modules / "@opentui" / "core-linux-arm64").symlink_to(self.opentui)
        # Bun hardlinks node_modules files to its global cache.
        if HARDLINKS:
            os.link(self.opentui / "libopentui.so", self.cache / "libopentui.so")

        package(modules / "@parcel" / "watcher-linux-arm64-glibc", "@parcel/watcher-linux-arm64-glibc",
                "2.5.1", {"watcher.node": "glibc watcher"})
        package(modules / "@ff-labs" / "fff-bin-linux-arm64-gnu", "@ff-labs/fff-bin-linux-arm64-gnu",
                "0.9.4", {"libfff_c.so": "glibc fff"})
        self.fff_bun = package(modules / "@ff-labs" / "fff-bun", "@ff-labs/fff-bun", "0.9.4",
                               {"src/ffi.ts": FFI_BEFORE})
        if HARDLINKS:
            os.link(self.fff_bun / "src" / "ffi.ts", self.cache / "ffi.ts")
        # A workspace's own node_modules.
        self.pty = package(self.src / "packages" / "core" / "node_modules" / "bun-pty", "bun-pty", "0.4.8",
                           {"rust-pty/target/release/librust_pty_arm64.so": "glibc pty",
                            "rust-pty/target/release/librust_pty_arm64_musl.so": "musl pty"})
        self.opencode_pty = package(modules / "@opencode" / "pty-linux-arm64-gnu",
                                    "@opencode/pty-linux-arm64-gnu", "0.2.0",
                                    {"bin/opencode-pty": "glibc opencode-pty"})
        (self.opencode_pty / "bin" / "opencode-pty").chmod(0o755)

        self.patches = base / "patches"
        self.patches.mkdir()
        (self.patches / "fff-bun-android.patch").write_text(FFF_PATCH)
        self.replacements = {}
        for key in VERSIONS:
            path = base / f"{key}.bionic"
            path.write_text(f"bionic {key}")
            self.replacements[key] = path

    def tearDown(self):
        self.tmp.cleanup()

    def run_swap(self, versions=VERSIONS):
        return swap.swap(self.src, versions, self.replacements, self.patches)

    def test_replaces_every_asset_and_patches_the_wrapper(self):
        report = self.run_swap()
        self.assertEqual((self.opentui / "libopentui.so").read_text(), "bionic opentui")
        self.assertEqual(
            (self.src / "node_modules/@parcel/watcher-linux-arm64-glibc/watcher.node").read_text(),
            "bionic watcher")
        self.assertEqual(
            (self.src / "node_modules/@ff-labs/fff-bin-linux-arm64-gnu/libfff_c.so").read_text(),
            "bionic fff")
        self.assertEqual((self.pty / "rust-pty/target/release/librust_pty_arm64.so").read_text(),
                         "bionic rust_pty")
        self.assertEqual((self.pty / "rust-pty/target/release/librust_pty_arm64_musl.so").read_text(),
                         "bionic rust_pty")
        self.assertEqual((self.fff_bun / "src" / "ffi.ts").read_text(), FFI_AFTER)
        opencode_pty = self.opencode_pty / "bin" / "opencode-pty"
        self.assertEqual(opencode_pty.read_text(), "bionic opencode_pty")
        self.assertTrue(os.access(opencode_pty, os.X_OK), "the replaced executable must stay executable")
        self.assertEqual(len(report["assets"]), 6)
        self.assertEqual(report["patches"][0]["package"], "@ff-labs/fff-bun@0.9.4")

    def test_symlinked_and_stored_copies_count_once(self):
        self.assertEqual(swap.find_packages(self.src, "@opentui/core-linux-arm64"), [self.opentui])

    @unittest.skipUnless(HARDLINKS, "no hard links on Android")
    def test_bun_cache_is_left_alone(self):
        self.run_swap()
        self.assertEqual((self.cache / "libopentui.so").read_text(), "glibc opentui")
        self.assertEqual((self.cache / "ffi.ts").read_text(), FFI_BEFORE)

    def test_version_mismatch_fails(self):
        bumped = dict(VERSIONS, watcher={"version": "2.6.0"})
        with self.assertRaisesRegex(swap.SwapError, r"names 2\.6\.0, installed: 2\.5\.1"):
            self.run_swap(bumped)

    def test_missing_package_fails(self):
        (self.src / "packages" / "core" / "node_modules" / "bun-pty" / "package.json").unlink()
        with self.assertRaisesRegex(swap.SwapError, "bun-pty: .*installed: none"):
            self.run_swap()

    def test_patch_that_no_longer_applies_fails(self):
        (self.fff_bun / "src" / "ffi.ts").write_text("upstream changed this\n")
        with self.assertRaisesRegex(swap.SwapError, "does not apply"):
            self.run_swap()



if __name__ == "__main__":
    unittest.main()
