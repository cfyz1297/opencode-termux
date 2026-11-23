#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

# @number0/iroh-android-arm64 is a prebuilt N-API addon: nothing to compile,
# only to fetch. It replaces the glibc build bun install puts on an ARM64 host.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${1:-$ROOT/work/native/iroh}"
mkdir -p "$OUT_DIR"

for command_name in curl tar python3; do
  command -v "$command_name" >/dev/null || { echo "fetch-iroh: $command_name is required" >&2; exit 1; }
done

# work/natives.json: what tools/resolve_natives.py found for the OpenCode source (make resolve-natives).
NATIVES="${NATIVES_JSON:-$ROOT/work/natives.json}"
[ -f "$NATIVES" ] || { echo "fetch-iroh: $NATIVES is missing; run make resolve-natives" >&2; exit 1; }
RESOLVED="$(
  python3 - "$NATIVES" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
entry = doc.get("iroh")
if not entry:
    sys.exit("fetch-iroh: work/natives.json has no iroh entry; run make resolve-natives")
print(entry["version"], entry["source_url"], entry["source_sha256"])
PY
)" || exit 1
read -r VERSION SOURCE_URL SOURCE_SHA <<<"$RESOLVED"

ARCHIVE="$OUT_DIR/iroh-$VERSION.tgz"
if [ ! -f "$ARCHIVE" ] || [ "$(sha256sum "$ARCHIVE" | cut -d' ' -f1)" != "$SOURCE_SHA" ]; then
  curl -fL --show-error --retry 5 --retry-all-errors -o "$ARCHIVE.new" "$SOURCE_URL"
  printf '%s  %s\n' "$SOURCE_SHA" "$ARCHIVE.new" | sha256sum -c - >/dev/null
  mv -f "$ARCHIVE.new" "$ARCHIVE"
fi

# swap_native_assets.py replaces the file under the name the glibc package uses.
tar -xzf "$ARCHIVE" -C "$OUT_DIR" --strip-components=1 --wildcards 'package/*.node'
mv -f "$OUT_DIR/iroh.android-arm64.node" "$OUT_DIR/libiroh.node"

python3 "$ROOT/tools/elf_native.py" "$OUT_DIR/libiroh.node" >/dev/null \
  || { echo "fetch-iroh: the addon is not a clean Bionic aarch64 ELF" >&2; exit 1; }
echo "fetch-iroh: $VERSION -> $OUT_DIR/libiroh.node"
