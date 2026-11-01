#!/usr/bin/env python3
"""scripts/patch-opentui-pointer.mjs: tag mask, idempotence, loud failure.

The fixture reproduces the shape of @opentui/core's bundled chunk, which is the
only thing the patcher matches on.
"""

import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "patch-opentui-pointer.mjs"
RUNTIME = shutil.which("bun") or shutil.which("node")

ORIGINAL = """var POINTER_NEGATIVE = "Pointer must be non-negative";
var POINTER_UNSAFE = "Pointer exceeds safe integer range";
function toSafeNumberPointer(pointer) {
  if (pointer < 0n) {
    throw new Error(POINTER_NEGATIVE);
  }
  if (pointer > BigInt(Number.MAX_SAFE_INTEGER)) {
    throw new Error(POINTER_UNSAFE);
  }
  return Number(pointer);
}
"""


def write_package(root: pathlib.Path, text: str = ORIGINAL) -> pathlib.Path:
    package = root / "node_modules" / "@opentui" / "core"
    package.mkdir(parents=True)
    chunk = package / "chunk-bun-fixture.js"
    chunk.write_text(text)
    (package / "index.bun.js").write_text("export const x = 1;\n")
    return chunk


class PatchOpenTuiPointerTest(unittest.TestCase):
    @unittest.skipIf(RUNTIME is None, "bun or node is required")
    def run_patcher(self, root: pathlib.Path, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [RUNTIME, str(SCRIPT), str(root), *extra],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_masks_the_tag_and_keeps_plain_pointers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            chunk = write_package(root)
            result = self.run_patcher(root, "--self-test")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("self-test: ok", result.stdout)
            patched = chunk.read_text()
            self.assertIn("const untagged = pointer & 0x00ffffffffffffffn;", patched)
            self.assertNotIn(
                "if (pointer > BigInt(Number.MAX_SAFE_INTEGER)) {\n    throw new Error(POINTER_UNSAFE);",
                patched,
            )

    def test_second_run_is_a_no_op(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            chunk = write_package(root)
            self.assertEqual(self.run_patcher(root).returncode, 0)
            first = chunk.read_text()
            again = self.run_patcher(root, "--self-test")
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertIn("0 file(s) patched", again.stdout)
            self.assertEqual(chunk.read_text(), first)

    def test_fails_when_openui_changed_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            write_package(root, "export const unrelated = 1;\n")
            result = self.run_patcher(root)
            self.assertEqual(result.returncode, 1)
            self.assertIn("no toSafeNumberPointer", result.stderr)

    def test_fails_without_installed_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_patcher(pathlib.Path(tmp))
            self.assertEqual(result.returncode, 1)
            self.assertIn("is missing", result.stderr)


if __name__ == "__main__":
    unittest.main()
