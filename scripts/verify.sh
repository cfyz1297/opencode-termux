#!/data/data/com.termux/files/usr/bin/bash
# Run the compiled candidate inside Termux and promote it to dist/opencode.
#
# scripts/compile.sh builds on a glibc host that cannot execute the Android
# binary; this is where it runs for the first time: version, a file search
# through its own server (the bundled, patched FFF wrapper), the real TUI, and
# the opencode-pty helper it embeds.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="$ROOT/dist"
WORK="$ROOT/work/build"
CANDIDATE="$DIST/.opencode.new"
SMOKE_SECONDS="${SMOKE_SECONDS:-15}"
mkdir -p "$WORK"

[ -x "$CANDIDATE" ] && [ -f "$DIST/compile.json" ] || {
  echo "verify: no compiled candidate in $DIST (scripts/compile.sh)" >&2
  exit 1
}
[ -e /system/bin/linker64 ] || { echo "verify: run this inside Termux" >&2; exit 1; }
VERSION="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["opencode"])' "$DIST/compile.json")"
SHA="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["output_sha256"])' "$DIST/compile.json")"
[ "$(sha256sum "$CANDIDATE" | cut -d' ' -f1)" = "$SHA" ] || {
  echo "verify: $CANDIDATE is not the binary compile.json describes" >&2
  exit 1
}

# Fail with the smoke test's own output, so it shows in the CI log.
fail() {
  echo "verify: $1" >&2
  tail -n 60 "$2" | sed 's/^/  | /' >&2
  exit 1
}

REPORTED="$("$CANDIDATE" --version)"
[[ " $REPORTED " == *[[:space:]v]"$VERSION"[[:space:]]* ]] || {
  echo "verify: --version reports '$REPORTED', expected $VERSION" >&2
  exit 1
}
# OpenTUI is built on the glibc host; this is where Bionic first loads it.
"$ROOT/work/bun-android/bun" "$ROOT/tools/opentui_smoke.ts" "$ROOT/work/native/opentui/libopentui.so" \
  > "$WORK/opentui-smoke.log" 2>&1 || fail "libopentui.so does not load" "$WORK/opentui-smoke.log"
if python3 -c 'import json, sys; sys.exit("iroh" not in json.load(open(sys.argv[1]))["natives"])' "$DIST/compile.json"; then
  IROH_BINDING="$WORK/iroh.android-arm64.node" timeout 30 "$ROOT/work/bun-android/bun" -e '
    const builder = require(process.env.IROH_BINDING).Endpoint.builder()
    builder.applyMinimal()
    builder.bindAddr("127.0.0.1:0")
    const endpoint = await builder.bind()
    await endpoint.close()
  ' > "$WORK/iroh-smoke.log" 2>&1 || fail "Iroh could not open a local QUIC endpoint" "$WORK/iroh-smoke.log"
fi
python3 "$ROOT/tools/serve_smoke.py" "$CANDIDATE" 120 > "$WORK/fff-smoke.log" 2>&1 ||
  fail "file search through the server failed" "$WORK/fff-smoke.log"
python3 "$ROOT/tools/tui_smoke.py" "$CANDIDATE" "$SMOKE_SECONDS" > "$WORK/tui-smoke.log" 2>&1 ||
  fail "the TUI did not render" "$WORK/tui-smoke.log"

# The PTY helper OpenCode embeds, run the way its own release smoke does.
PTY="$ROOT/work/native/opencode-pty/opencode-pty"
PTY_RUNTIME="$WORK/pty-smoke"
rm -rf "$PTY_RUNTIME"
printf 'new %s -c "printf termux-smoke; sleep 1"\nwait 250\nquit\n' "${PREFIX:-/data/data/com.termux/files/usr}/bin/sh" \
  | timeout 60 "$PTY" play --runtime-dir "$PTY_RUNTIME" --name smoke > "$WORK/pty-smoke.log" 2>&1 || true
grep -q termux-smoke "$WORK/pty-smoke.log" && grep -q checkpoint "$WORK/pty-smoke.log" ||
  fail "opencode-pty did not run a session" "$WORK/pty-smoke.log"

python3 - "$DIST/compile.json" "$DIST/build-manifest.json.new" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
doc["smoke"] = {"version": "pass", "opentui": "pass", "file_search": "pass", "pty": "pass"}
if "iroh" in doc["natives"]:
    doc["smoke"]["iroh"] = "pass"
doc["tui_smoke"] = "pass"
doc["structurally_verified"] = doc["native_assets"].get("result") == "pass"
doc["release_eligible"] = doc["structurally_verified"]
with open(sys.argv[2], "w") as f:
    json.dump(doc, f, indent=2)
    f.write("\n")
PY
mv -f "$DIST/build-manifest.json.new" "$DIST/build-manifest.json"
mv -f "$CANDIDATE" "$DIST/opencode"
echo "verify: OK: $DIST/opencode (v$VERSION)"
