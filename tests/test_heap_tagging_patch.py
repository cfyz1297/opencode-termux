#!/usr/bin/env python3
"""patches/opencode-0004-heap-tagging-off.patch: the Bionic heap-tag opt-out.

This cannot be exercised in CI. `termux-docker` is Bionic too, but it has no
init/zygote to raise the level, so bionic stays at its default
M_HEAP_TAGGING_LEVEL_NONE and the crash the patch prevents only happens on a real
device — where it is deterministic (alloc returns 0xb400…, the tag is dropped,
free() aborts). The test therefore guards what a silent mistake would break,
including the one that already happened while writing it.
"""

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PATCH = ROOT / "patches" / "opencode-0004-heap-tagging-off.patch"

# bionic: #define M_BIONIC_SET_HEAP_TAGGING_LEVEL (-204); HeapTaggingLevel NONE = 0
MALLOPT_OPTION = "-204"


class HeapTaggingPatchTests(unittest.TestCase):
    def setUp(self):
        self.text = PATCH.read_text()

    def test_the_patch_exists_and_reaches_the_cli_entry(self):
        self.assertIn("+++ b/packages/cli/src/index.ts", self.text)

    def test_it_disables_bionic_heap_tagging(self):
        calls = re.findall(r"symbols\.mallopt\(\s*(-?\d+)\s*,\s*(\d+)\s*\)", self.text)
        self.assertEqual(calls, [(MALLOPT_OPTION, "0")],
                         "the opt-out must pass M_BIONIC_SET_HEAP_TAGGING_LEVEL and NONE")

    def test_it_loads_the_bionic_libc_soname(self):
        # On Android the soname is libc.so. Any other name throws inside the
        # catch, and the fix becomes a silent no-op exactly like the guard below.
        self.assertIn('dlopen("libc.so"', self.text)

    def test_it_is_not_guarded_by_process_platform(self):
        # `bun build --compile` bakes process.platform from the build host, which
        # is glibc Linux, so any such guard is a compile-time false and the whole
        # block is dropped. This is not a style rule: it is the bug that shipped.
        code = [line for line in self.text.splitlines()
                if line.startswith("+") and not line.startswith("+//")]
        self.assertFalse([line for line in code if "process.platform" in line],
                         "a platform guard here is baked from the build host and always false")

    def test_a_failure_to_dlopen_cannot_break_startup(self):
        self.assertIn("+} catch {", self.text)


if __name__ == "__main__":
    unittest.main()
