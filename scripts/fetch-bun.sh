#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

# fetch-bun.sh [OUT_DIR] [KEY]
#   KEY=base_bun  the Android Bun every release is built on (default)
#   KEY=host_bun  the same Bun version for glibc AArch64, which compiles it
# The version is the one OpenCode's package.json asks for; the archive is checked
# against the release's SHASUMS256.txt (tools/resolve_natives.py).
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${1:-$ROOT/work/bun-android}"
KEY="${2:-base_bun}"
mkdir -p "$OUT_DIR"
# work/natives.json: what tools/resolve_natives.py found for the OpenCode source (make resolve-natives).
NATIVES="${NATIVES_JSON:-$ROOT/work/natives.json}"
[ -f "$NATIVES" ] || { echo "fetch-bun: $NATIVES is missing; run make resolve-natives" >&2; exit 1; }
read -r URL ARCHIVE_SHA < <(
  python3 - "$NATIVES" "$KEY" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))[sys.argv[2]]
print(doc["url"], doc["archive_sha256"])
PY
)
BUN="$OUT_DIR/bun"
# bun.archive.sha256 records which archive the binary came from.
if [ -x "$BUN" ] && [ "$(cat "$OUT_DIR/bun.archive.sha256" 2>/dev/null)" = "$ARCHIVE_SHA" ]; then
  printf '%s\n' "$BUN"
  exit 0
fi
ARCHIVE="$OUT_DIR/bun.zip.new"
STAGE="$OUT_DIR/bun.new"
curl -fL --show-error --retry 3 -o "$ARCHIVE" "$URL"
printf '%s  %s\n' "$ARCHIVE_SHA" "$ARCHIVE" | sha256sum -c - >/dev/null
unzip -p "$ARCHIVE" '*/bun' > "$STAGE"
chmod 755 "$STAGE"
if [ "${SKIP_RUN:-0}" != 1 ]; then
  "$STAGE" --revision >/dev/null
fi
mv -f "$STAGE" "$BUN"
printf '%s\n' "$ARCHIVE_SHA" > "$OUT_DIR/bun.archive.sha256"
rm -f "$ARCHIVE"
printf '%s\n' "$BUN"
