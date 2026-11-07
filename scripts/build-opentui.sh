#!/usr/bin/env bash
# Build OpenTUI's native library for Android from source with Zig.
#
# Runs on a glibc AArch64 Linux host, cross-compiling against the Android
# sysroot that scripts/export-android-sysroot.sh copies out of Termux. Zig
# works in neither of the other places: in Termux it sees a Bionic host and
# cannot build its own build runner for it (0.17's crashes with an illegal
# instruction), and under proot Zig 0.16's atomic file writes (linkat with
# AT_EMPTY_PATH) fail with EINVAL, which it aborts on.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${1:-$ROOT/work/native/opentui}"
NDK="${ANDROID_NDK_HOME:-$ROOT/work/android-ndk}"
mkdir -p "$OUT_DIR" "$ROOT/work/toolchains"

[ "$(uname -s)-$(uname -m)" = Linux-aarch64 ] && [ ! -e /system/bin/linker64 ] || {
  echo "build-opentui: run this on a glibc AArch64 Linux host" >&2
  exit 1
}
for command_name in curl patch; do
  command -v "$command_name" >/dev/null || { echo "build-opentui: $command_name is required" >&2; exit 1; }
done
[ -d "$NDK/toolchains/llvm/prebuilt/linux-x86_64/sysroot/usr/lib/aarch64-linux-android" ] || {
  echo "build-opentui: no Android sysroot at $NDK (scripts/export-android-sysroot.sh in Termux)" >&2
  exit 1
}

# work/natives.json: what tools/resolve_natives.py found for the OpenCode source (make resolve-natives).
NATIVES="${NATIVES_JSON:-$ROOT/work/natives.json}"
[ -f "$NATIVES" ] || { echo "build-opentui: $NATIVES is missing; run make resolve-natives" >&2; exit 1; }
read -r VERSION SOURCE_URL SOURCE_SHA ZIG_VERSION ZIG_URL ZIG_SHA API < <(
  python3 - "$ROOT/versions.json" "$NATIVES" <<'PY'
import json, sys
x = json.load(open(sys.argv[1]))
p = json.load(open(sys.argv[2]))["opentui"]
z = x["zig"][p["zig"]]
print(p["version"], p["source_url"], p["source_sha256"],
      p["zig"], z["aarch64_linux_url"], z["aarch64_linux_sha256"], x["android_ndk"]["api"])
PY
)
# The NDK headers refuse a target without an API level.
TARGET="aarch64-linux-android.$API"

fetch() {
  local url="$1" expected="$2" output="$3"
  if [ -f "$output" ] && [ "$(sha256sum "$output" | cut -d' ' -f1)" = "$expected" ]; then
    return
  fi
  curl -fL --show-error --retry 5 --retry-all-errors -C - -o "$output.new" "$url"
  printf '%s  %s\n' "$expected" "$output.new" | sha256sum -c - >/dev/null
  mv -f "$output.new" "$output"
}

SOURCE_ARCHIVE="$OUT_DIR/opentui-$VERSION.tar.gz"
ZIG_ARCHIVE="$ROOT/work/toolchains/zig-$ZIG_VERSION.tar.xz"
fetch "$SOURCE_URL" "$SOURCE_SHA" "$SOURCE_ARCHIVE"
fetch "$ZIG_URL" "$ZIG_SHA" "$ZIG_ARCHIVE"

STAGE="$(mktemp -d "$OUT_DIR/.build.XXXXXX")"
trap 'rm -rf "$STAGE" "$OUT_DIR/.libopentui.new.so"' EXIT
mkdir -p "$STAGE/source" "$STAGE/zig"
tar -xzf "$SOURCE_ARCHIVE" -C "$STAGE/source" --strip-components=1
tar -xJf "$ZIG_ARCHIVE" -C "$STAGE/zig" --strip-components=1
patch -d "$STAGE/source" -p1 --fuzz=0 --batch < "$ROOT/patches/opentui-android.patch"
# The Zig dependencies are vendored in the archive; this is all
# packages/native/scripts/prepare-zig-deps.sh does, minus its hard-link lock.
NATIVE="$STAGE/source/packages/native"
mkdir -p "$NATIVE/zig-deps"
tar -xzf "$NATIVE/src/vendor/zig-deps.tar.gz" -C "$NATIVE/zig-deps"

(
  cd "$NATIVE"
  export ANDROID_NDK_HOME="$NDK"
  export OPENCODE_TERMUX_TLS_ALIGN="$ROOT/native/tls-align.S"
  # Zig 0.17's `zig build` takes the global cache from the environment only.
  export ZIG_GLOBAL_CACHE_DIR="$ROOT/work/toolchains/zig-cache"
  timeout --kill-after=60 2700 "$STAGE/zig/zig" build --cache-dir "$STAGE/cache" \
    -Dlibrary-target="$TARGET" -Doptimize=ReleaseFast --summary failures
)
cp -L "$NATIVE/lib/$TARGET/libopentui.so" "$OUT_DIR/.libopentui.new.so"

# Loaded in Termux by scripts/verify.sh (tools/opentui_smoke.ts and the TUI).
python3 "$ROOT/tools/elf_native.py" "$OUT_DIR/.libopentui.new.so" > "$OUT_DIR/elf.json"
mv -f "$OUT_DIR/.libopentui.new.so" "$OUT_DIR/libopentui.so"
sha256sum "$OUT_DIR/libopentui.so" | cut -d' ' -f1 > "$OUT_DIR/libopentui.so.sha256"
printf 'build-opentui: OK: %s\n' "$OUT_DIR/libopentui.so"
