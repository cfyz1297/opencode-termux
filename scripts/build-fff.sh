#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${1:-$ROOT/work/native/fff}"
DISTRO="${ANDROID_BUILD_DISTRO:-android-build}"
mkdir -p "$OUT_DIR"

for command_name in curl proot-distro clang; do
  command -v "$command_name" >/dev/null || { echo "build-fff: $command_name is required" >&2; exit 1; }
done

# work/natives.json: what tools/resolve_natives.py found for the OpenCode source (make resolve-natives).
NATIVES="${NATIVES_JSON:-$ROOT/work/natives.json}"
[ -f "$NATIVES" ] || { echo "build-fff: $NATIVES is missing; run make resolve-natives" >&2; exit 1; }
read -r VERSION SOURCE_URL SOURCE_SHA < <(
  python3 - "$NATIVES" <<'PY'
import json, sys
x = json.load(open(sys.argv[1]))["fff"]
print(x["version"], x["source_url"], x["source_sha256"])
PY
)

ARCHIVE="$OUT_DIR/fff-$VERSION.tar.gz"
if [ ! -f "$ARCHIVE" ] || [ "$(sha256sum "$ARCHIVE" | cut -d' ' -f1)" != "$SOURCE_SHA" ]; then
  curl -fL --show-error --retry 3 -o "$ARCHIVE.new" "$SOURCE_URL"
  printf '%s  %s\n' "$SOURCE_SHA" "$ARCHIVE.new" | sha256sum -c - >/dev/null
  mv -f "$ARCHIVE.new" "$ARCHIVE"
fi

STAGE="$(mktemp -d "$OUT_DIR/.build.XXXXXX")"
trap 'rm -rf "$STAGE" "$OUT_DIR/.libfff_c.new.so"' EXIT
mkdir -p "$STAGE/source" "$STAGE/target"
tar -xzf "$ARCHIVE" -C "$STAGE/source" --strip-components=1
clang -c -fPIC "$ROOT/native/tls-align.S" -o "$STAGE/tls-align.o"

proot-distro login --bind /system:/system "$DISTRO" -- \
  bash "$ROOT/scripts/build-fff-inner.sh" \
  "$ROOT" "$STAGE/source" "$STAGE/target" "$STAGE/tls-align.o" \
  "$OUT_DIR/.libfff_c.new.so"

# libz-sys hardcodes libz.so.1 for Android even though Bionic exports libz.so.
python3 "$ROOT/tools/rewrite_needed.py" "$OUT_DIR/.libfff_c.new.so" \
  "$OUT_DIR/.libfff_c.new.so" libz.so.1 libz.so
python3 "$ROOT/tools/elf_native.py" "$OUT_DIR/.libfff_c.new.so" >/dev/null
"$ROOT/work/bun-android/bun" "$ROOT/tools/fff_smoke.ts" \
  "$OUT_DIR/.libfff_c.new.so" "$ROOT" > "$OUT_DIR/smoke.json"
mv -f "$OUT_DIR/.libfff_c.new.so" "$OUT_DIR/libfff_c.so"
sha256sum "$OUT_DIR/libfff_c.so" | cut -d' ' -f1 > "$OUT_DIR/libfff_c.so.sha256"
printf 'build-fff: OK: %s\n' "$OUT_DIR/libfff_c.so"
