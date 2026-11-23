#!/usr/bin/env python3

import hashlib
import pathlib
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from elf_native import ElfInfo
from graph_format import Graph, TRAILER


def synthetic_graph():
    return graph_with(b"\x7fELFold-asset"), b"\x7fELFold-asset"


def bionic_elf(payload=b""):
    """An ELF64 aarch64 with no program headers: no interpreter, no DT_NEEDED."""
    header = bytearray(64)
    header[:4] = b"\x7fELF"
    header[4] = 2  # ELFCLASS64
    header[5] = 1  # little endian
    header[6] = 1  # version
    struct.pack_into("<H", header, 16, 3)       # ET_DYN
    struct.pack_into("<H", header, 18, 0xB7)    # EM_AARCH64
    struct.pack_into("<Q", header, 32, 64)      # e_phoff
    struct.pack_into("<H", header, 54, 56)      # e_phentsize
    struct.pack_into("<H", header, 56, 0)       # e_phnum
    return bytes(header) + payload


def graph_with(contents):
    name = b"/$bunfs/root/libopentui-test.so"
    data = bytearray(name + contents)
    modules_at = len(data)
    record = bytearray(52)
    struct.pack_into("<II", record, 0, 0, len(name))
    struct.pack_into("<II", record, 8, len(name), len(contents))
    data.extend(record)
    offsets_at = len(data)
    data.extend(struct.pack("<QIIIIII", offsets_at, modules_at, 52, 0, 0, 0, 0))
    data.extend(TRAILER)
    return bytes(data)


class GraphTests(unittest.TestCase):
    def test_module_metadata(self):
        graph = Graph(synthetic_graph()[0])
        module = graph.module(0)
        self.assertEqual(module.index, 0)
        self.assertEqual(module.display_name, "/$bunfs/root/libopentui-test.so")
        self.assertEqual(graph.module_count, 1)


class ElfPolicyTests(unittest.TestCase):
    def test_glibc_sonames_are_rejected(self):
        info = ElfInfo(
            machine=0xB7,
            interpreter="/lib/ld-linux-aarch64.so.1",
            needed=("libc.so.6", "libgcc_s.so.1", "libutil.so.1"),
        )
        self.assertEqual(
            info.glibc_dependencies,
            (
                "/lib/ld-linux-aarch64.so.1",
                "libc.so.6",
                "libgcc_s.so.1",
                "libutil.so.1",
            ),
        )

    def test_bionic_sonames_pass(self):
        info = ElfInfo(
            machine=0xB7,
            interpreter=None,
            needed=("libc.so", "libm.so", "libdl.so"),
        )
        self.assertEqual(info.glibc_dependencies, ())
        self.assertEqual(info.unbundled_dependencies, ())

    def test_shared_cxx_runtime_requires_bundling(self):
        info = ElfInfo(
            machine=0xB7,
            interpreter=None,
            needed=("libc.so", "libc++_shared.so"),
        )
        self.assertEqual(info.glibc_dependencies, ())
        self.assertEqual(info.unbundled_dependencies, ("libc++_shared.so",))


class RequiredAssetTests(unittest.TestCase):
    """--require-asset is what proves the swap reached the binary."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.graph = pathlib.Path(self.tmp.name) / "opencode.graph"

    def audit(self, contents, digest, strict="--require-bionic"):
        self.graph.write_bytes(graph_with(contents))
        return subprocess.run(
            [sys.executable, str(ROOT / "tools" / "audit_native_assets.py"), str(self.graph),
             *([strict] if strict else []), "--require-asset", digest],
            text=True, capture_output=True,
        )

    def test_a_swapped_asset_that_reached_the_binary_passes(self):
        contents = bionic_elf(b"iroh addon")
        result = self.audit(contents, hashlib.sha256(contents).hexdigest())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"result": "pass"', result.stdout)

    def test_a_missing_asset_fails_even_when_the_rest_is_bionic(self):
        result = self.audit(bionic_elf(b"some other asset"), hashlib.sha256(b"absent").hexdigest())
        self.assertEqual(result.returncode, 1)
        self.assertIn('"result": "fail"', result.stdout)

    def test_require_asset_alone_is_strict(self):
        result = self.audit(bionic_elf(b"x"), hashlib.sha256(b"absent").hexdigest(), strict=None)
        self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
