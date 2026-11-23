#!/usr/bin/env python3
"""scripts/fetch-iroh.sh against a fake registry: the hash gate and the swap name.

The fakes use an absolute interpreter path because `make test` also runs inside
termux-docker, which has no /usr/bin/env.
"""

import hashlib
import io
import json
import os
import pathlib
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "fetch-iroh.sh"
BASH = shutil.which("bash")

FAKE_CURL = f"""#!{sys.executable}
# Copies $FAKE_IROH_TARBALL to the -o path.
import os, shutil, sys
args, out = sys.argv[1:], None
for i, arg in enumerate(args):
    if arg == "-o":
        out = args[i + 1]
if not out:
    sys.exit("fake curl: no -o")
shutil.copyfile(os.environ["FAKE_IROH_TARBALL"], out)
"""


def bionic_elf():
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
    return bytes(header)


def tarball(addon=bionic_elf()):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tar:
        for name, data in (("package/package.json", b'{"name":"@number0/iroh-android-arm64"}'),
                           ("package/iroh.android-arm64.node", addon)):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return out.getvalue()


class FetchIrohTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.fake = self.tmp / "fake-bin"
        self.fake.mkdir()
        (self.fake / "curl").write_text(FAKE_CURL)
        (self.fake / "curl").chmod(0o755)
        self.out = self.tmp / "native" / "iroh"
        self.archive = self.tmp / "iroh.tgz"
        self.archive.write_bytes(tarball())
        self.natives = self.tmp / "natives.json"

    def natives_for(self, digest):
        self.natives.write_text(json.dumps({"iroh": {
            "version": "1.2.0",
            "source_url": "https://registry.npmjs.org/@number0/iroh-android-arm64/-/iroh-android-arm64-1.2.0.tgz",
            "source_sha256": digest,
        }}))

    def run_fetch(self):
        env = dict(os.environ, PATH=f"{self.fake}:{os.environ['PATH']}",
                   NATIVES_JSON=str(self.natives), FAKE_IROH_TARBALL=str(self.archive),
                   TMPDIR=str(self.tmp))
        return subprocess.run([BASH, str(SCRIPT), str(self.out)], env=env, text=True,
                              capture_output=True)

    def test_unpacks_the_addon_under_the_swapped_name(self):
        self.natives_for(hashlib.sha256(self.archive.read_bytes()).hexdigest())
        result = self.run_fetch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.out / "libiroh.node").read_bytes(), bionic_elf())
        self.assertFalse((self.out / "iroh.android-arm64.node").exists())

    def test_a_wrong_hash_stops_before_unpacking(self):
        self.natives_for("0" * 64)
        result = self.run_fetch()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.out / "libiroh.node").exists())


    def test_a_non_elf_addon_stops_the_build(self):
        self.archive.write_bytes(tarball(b"not an ELF"))
        self.natives_for(hashlib.sha256(self.archive.read_bytes()).hexdigest())
        result = self.run_fetch()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not a clean Bionic aarch64 ELF", result.stderr)

    def test_a_natives_json_without_iroh_says_what_to_run(self):
        self.natives.write_text('{"watcher": {}}')
        result = self.run_fetch()
        self.assertEqual(result.returncode, 1)
        self.assertIn("run make resolve-natives", result.stderr)


if __name__ == "__main__":
    unittest.main()
