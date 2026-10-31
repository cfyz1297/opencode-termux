#!/usr/bin/env bash
# Compile OpenCode from source into the Android Bun.
#
# Runs on a glibc AArch64 Linux host (the GitHub ARM runner), not in Termux:
# `bun build --compile` resolves process.platform at build time, and the
# Android Bun reports "android", which OpenTUI, FFF and @parcel/watcher do not
# know. The glibc Bun of the same version builds for linux-arm64 exactly like
# upstream's release, and embeds the bundle into the Android Bun instead.
#
# Output: dist/.opencode.new and dist/compile.json. scripts/verify.sh runs the
# candidate inside Termux and promotes it to dist/opencode.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE="${OPENCODE_SOURCE:-$ROOT/work/upstream/opencode-src}"
SOURCE_JSON="$(dirname "$SOURCE")/source.json"
BUN="${BUN:-$ROOT/work/bun-android/bun}"
HOST_BUN="${HOST_BUN:-$ROOT/work/bun-host/bun}"
NATIVE="${NATIVE_DIR:-$ROOT/work/native}"
WORK="$ROOT/work/build"
DIST="$ROOT/dist"
SRC="$WORK/src"
mkdir -p "$WORK" "$DIST"

exec 9>"$ROOT/.build.lock"
flock -n 9 || { echo "compile: another build is running" >&2; exit 1; }
[ -f "$SOURCE/packages/cli/script/build.ts" ] || {
  echo "compile: OpenCode source is missing: $SOURCE (make fetch-source)" >&2
  exit 1
}
[ -f "$BUN" ] || { echo "compile: Android Bun is missing: $BUN" >&2; exit 1; }
[ "$("$HOST_BUN" -e 'process.stdout.write(process.platform + "-" + process.arch)' 2>/dev/null)" = linux-arm64 ] || {
  echo "compile: $HOST_BUN must be the glibc Bun on a Linux AArch64 host" >&2
  exit 1
}
# Both Buns come from the release OpenCode's package.json names (work/natives.json).
# The host cannot run the Android one, so its version is the resolved one.
NATIVES="${NATIVES_JSON:-$ROOT/work/natives.json}"
[ -f "$NATIVES" ] || { echo "compile: $NATIVES is missing; run make resolve-natives" >&2; exit 1; }
BASE_VERSION="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["base_bun"]["version"])' "$NATIVES")"
HOST_VERSION="$("$HOST_BUN" --version)"
[ "$HOST_VERSION" = "$BASE_VERSION" ] || {
  echo "compile: host Bun $HOST_VERSION cannot compile for Android Bun $BASE_VERSION" >&2
  exit 1
}
VERSION="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["version"])' "$SOURCE_JSON")"

echo "::group::Patch OpenCode $VERSION"
rm -rf "$SRC"
cp -a "$SOURCE" "$SRC"
# Numbered: patches/opencode-pty-*.patch belongs to scripts/build-opencode-pty.sh.
for patch in "$ROOT"/patches/opencode-[0-9]*.patch; do
  patch -p1 --fuzz=0 --batch --forward --no-backup-if-mismatch -d "$SRC" -i "$patch" >/dev/null || {
    echo "compile: $(basename "$patch") does not apply to OpenCode $VERSION" >&2
    exit 1
  }
  echo "applied $(basename "$patch")"
done
echo "::endgroup::"

# build.ts also runs `bun` for the web UI, and install scripts call it.
export PATH="$(dirname "$HOST_BUN"):$PATH"

echo "::group::bun install"
# The desktop app's Electron download is not needed for the CLI.
(cd "$SRC" && ELECTRON_SKIP_BINARY_DOWNLOAD=1 bun install)
echo "::endgroup::"

echo "::group::Swap in the Bionic native assets"
python3 "$ROOT/tools/swap_native_assets.py" "$SRC" --versions "$NATIVES" \
  --opentui "$NATIVE/opentui/libopentui.so" \
  --watcher "$NATIVE/watcher/watcher.node" \
  --fff "$NATIVE/fff/libfff_c.so" \
  --rust-pty "$NATIVE/bun-pty/librust_pty_arm64.so" \
  --opencode-pty "$NATIVE/opencode-pty/opencode-pty" \
  --report "$WORK/swap.json"
echo "::endgroup::"

echo "::group::bun build --compile"
# --single builds the host's linux-arm64 target; --skip-install keeps the
# swapped assets (build.ts would otherwise reinstall the platform packages).
(cd "$SRC/packages/cli" \
  && OPENCODE_VERSION="$VERSION" OPENCODE_CHANNEL=latest OPENCODE_TERMUX_BUN="$BUN" \
     bun script/build.ts --single --skip-install)
echo "::endgroup::"

CANDIDATE="$DIST/.opencode.new"
install -m 755 "$SRC/packages/cli/dist/cli-linux-arm64/bin/opencode" "$CANDIDATE"
python3 "$ROOT/tools/extract_graph.py" "$CANDIDATE" "$WORK/opencode.graph" > "$WORK/extract.json"
python3 "$ROOT/tools/audit_native_assets.py" "$WORK/opencode.graph" \
  --report "$WORK/native-assets.json" --require-bionic >/dev/null || {
    echo "compile: a native asset in the binary is not Bionic; inspect $WORK/native-assets.json" >&2
    exit 1
  }

python3 - "$DIST/compile.json" "$ROOT" "$SOURCE_JSON" "$CANDIDATE" "$BUN" "$HOST_BUN" "$WORK" "$NATIVES" <<'PY'
import hashlib, json, pathlib, sys
out, root, source, candidate, bun, host_bun, work, natives = sys.argv[1:]
root, work = pathlib.Path(root), pathlib.Path(work)
sha = lambda p: hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
load = lambda p: json.loads(pathlib.Path(p).read_text())
resolved = load(natives)
def bun_info(key, path):
    # fetch-bun.sh records which archive the binary came from; an override is recorded as such.
    stamp = pathlib.Path(path).with_name("bun.archive.sha256")
    archive = stamp.read_text().strip() if stamp.exists() else ""
    ours = archive == resolved[key]["archive_sha256"]
    return {"version": resolved[key]["version"] if ours else "unresolved",
            "archive_sha256": archive, "binary_sha256": sha(path)}
src = load(source)
doc = {
    "opencode": src["version"],
    "tag_name": "v" + src["version"],
    "source": src,
    "output_sha256": sha(candidate),
    "base_bun": bun_info("base_bun", bun),
    "host_bun": bun_info("host_bun", host_bun),
    "patches": {p.name: sha(p) for p in sorted((root / "patches").glob("*.patch"))},
    "natives": {k: v for k, v in resolved.items() if k != "opencode"},
    "swapped": load(work / "swap.json"),
    "extract": load(work / "extract.json"),
    "native_assets": load(work / "native-assets.json"),
}
pathlib.Path(out).write_text(json.dumps(doc, indent=2) + "\n")
PY
echo "compile: OK: $CANDIDATE (v$VERSION)"
