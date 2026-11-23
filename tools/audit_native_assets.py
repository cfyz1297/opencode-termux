#!/usr/bin/env python3
"""Inventory embedded ELF assets and reject glibc leakage."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys

from elf_native import ElfError, inspect_elf
from graph_format import Graph, GraphError


def audit(graph: Graph) -> dict:
    assets = []
    for module in graph.modules():
        if not module.contents.startswith(b"\x7fELF"):
            continue
        try:
            info = inspect_elf(module.contents)
            item = {
                "module_index": module.index,
                "module_name": module.display_name,
                "bytes": len(module.contents),
                "sha256": hashlib.sha256(module.contents).hexdigest(),
                "machine": info.machine,
                "aarch64": info.is_aarch64,
                "interpreter": info.interpreter,
                "needed": list(info.needed),
                "glibc_dependencies": list(info.glibc_dependencies),
                "unbundled_dependencies": list(info.unbundled_dependencies),
            }
        except ElfError as exc:
            item = {
                "module_index": module.index,
                "module_name": module.display_name,
                "bytes": len(module.contents),
                "error": str(exc),
            }
        assets.append(item)
    return {
        "module_count": graph.module_count,
        "entry_point": graph.entry,
        "flags": f"0x{graph.flags:x}",
        "elf_assets": assets,
        "elf_asset_count": len(assets),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("graph")
    parser.add_argument("--report")
    parser.add_argument("--require-bionic", action="store_true")
    parser.add_argument("--require-asset", action="append", default=[], metavar="SHA256",
                        help="fail when the binary does not embed the asset with this digest")
    args = parser.parse_args()
    try:
        report = audit(Graph.from_path(args.graph))
    except (OSError, GraphError) as exc:
        print(f"audit-native-assets: {exc}", file=sys.stderr)
        return 2
    violations = []
    for asset in report["elf_assets"]:
        if asset.get("error"):
            violations.append(
                f"{asset['module_name']}: unreadable ELF: {asset['error']}"
            )
        elif not asset["aarch64"]:
            violations.append(f"{asset['module_name']}: not AArch64")
        elif asset["glibc_dependencies"]:
            violations.append(
                f"{asset['module_name']}: glibc dependencies "
                + ", ".join(asset["glibc_dependencies"])
            )
        elif asset["unbundled_dependencies"]:
            violations.append(
                f"{asset['module_name']}: dependencies are not bundled or Android-system "
                + ", ".join(asset["unbundled_dependencies"])
            )
    # A missing swap is silent: the binary keeps working without the feature,
    # so the digest the swap wrote must be inside it.
    embedded = {asset.get("sha256") for asset in report["elf_assets"]}
    for digest in args.require_asset:
        if digest not in embedded:
            violations.append(f"no embedded asset hashes to {digest}")
    report["required_assets"] = args.require_asset
    report["strict"] = strict = args.require_bionic or bool(args.require_asset)
    report["result"] = "fail" if strict and violations else (
        "warn" if violations else "pass"
    )
    report["policy_violations"] = violations
    encoded = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.report:
        with open(args.report, "w", encoding="utf-8") as stream:
            stream.write(encoded)
    print(encoded, end="")
    return 1 if strict and violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
