#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PREFIX_PATH="${PREFIX:-/data/data/com.termux/files/usr}"
OUT_DIR="${1:-$ROOT/work/native/bun-pty}"
DISTRO="${ANDROID_BUILD_DISTRO:-android-build}"
mkdir -p "$OUT_DIR" "$ROOT/work/native"

for command_name in curl patch proot-distro clang; do
  command -v "$command_name" >/dev/null || { echo "build-rust-pty: $command_name is required" >&2; exit 1; }
done

# work/natives.json: what tools/resolve_natives.py found for the OpenCode source (make resolve-natives).
NATIVES="${NATIVES_JSON:-$ROOT/work/natives.json}"
[ -f "$NATIVES" ] || { echo "build-rust-pty: $NATIVES is missing; run make resolve-natives" >&2; exit 1; }
read -r VERSION SOURCE_URL SOURCE_SHA < <(
  python3 - "$NATIVES" <<'PY'
import json, sys
x = json.load(open(sys.argv[1]))["rust_pty"]
print(x["version"], x["source_url"], x["source_sha256"])
PY
)
ARCHIVE="$OUT_DIR/bun-pty-$VERSION.tar.gz"
if [ ! -f "$ARCHIVE" ] || [ "$(sha256sum "$ARCHIVE" | cut -d' ' -f1)" != "$SOURCE_SHA" ]; then
  curl -fL --show-error --retry 3 -o "$ARCHIVE.new" "$SOURCE_URL"
  printf '%s  %s\n' "$SOURCE_SHA" "$ARCHIVE.new" | sha256sum -c - >/dev/null
  mv -f "$ARCHIVE.new" "$ARCHIVE"
fi

STAGE="$(mktemp -d "$OUT_DIR/.build.XXXXXX")"
trap 'rm -rf "$STAGE" "$ROOT/work/native/rust-pty.new.so"' EXIT
mkdir -p "$STAGE/source" "$STAGE/target"
tar -xzf "$ARCHIVE" -C "$STAGE/source" --strip-components=1
patch -d "$STAGE/source" -p1 < "$ROOT/patches/bun-pty-android.patch"
clang -c -fPIC "$ROOT/native/tls-align.S" -o "$STAGE/tls-align.o"

proot-distro login --bind /system:/system "$DISTRO" -- \
  bash "$ROOT/scripts/build-rust-pty-inner.sh" \
  "$ROOT" "$STAGE/source" "$STAGE/target" "$STAGE/tls-align.o"

python3 "$ROOT/tools/elf_native.py" "$ROOT/work/native/rust-pty.new.so" >/dev/null
"$ROOT/work/bun-android/bun" "$ROOT/tools/rust_pty_smoke.ts" \
  "$ROOT/work/native/rust-pty.new.so" > "$OUT_DIR/smoke.json"
mv -f "$ROOT/work/native/rust-pty.new.so" "$OUT_DIR/librust_pty_arm64.so"
sha256sum "$OUT_DIR/librust_pty_arm64.so" | cut -d' ' -f1 > "$OUT_DIR/librust_pty_arm64.so.sha256"
printf 'build-rust-pty: OK: %s\n' "$OUT_DIR/librust_pty_arm64.so"
