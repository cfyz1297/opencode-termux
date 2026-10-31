#!/usr/bin/env bash
# Build opencode-pty, the persistent PTY helper OpenCode 2 embeds, from source
# as a static musl executable: upstream's own aarch64-unknown-linux-musl release
# build (anomalyco/opencode, packages/process-daemon,
# .github/workflows/release-process-daemon.yml).
#
# It is a separate program OpenCode starts, not a library it loads. A static
# executable needs neither glibc nor the Bionic linker, so the upstream target
# runs on Android; it reads the shell from $SHELL, not /etc/passwd. The one
# change (patches/opencode-pty-termux.patch) moves its sockets out of /tmp,
# which Android does not have.
#
# Runs on a glibc AArch64 Linux host with rustup and musl-tools (musl-gcc).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${1:-$ROOT/work/native/opencode-pty}"
mkdir -p "$OUT_DIR" "$ROOT/work/toolchains"

[ "$(uname -s)-$(uname -m)" = Linux-aarch64 ] && [ ! -e /system/bin/linker64 ] || {
  echo "build-opencode-pty: run this on a glibc AArch64 Linux host" >&2
  exit 1
}
for command_name in curl git cargo rustup musl-gcc; do
  command -v "$command_name" >/dev/null || { echo "build-opencode-pty: $command_name is required" >&2; exit 1; }
done

# work/natives.json: what tools/resolve_natives.py found for the OpenCode source (make resolve-natives).
NATIVES="${NATIVES_JSON:-$ROOT/work/natives.json}"
[ -f "$NATIVES" ] || { echo "build-opencode-pty: $NATIVES is missing; run make resolve-natives" >&2; exit 1; }
read -r VERSION SOURCE_URL SOURCE_SHA SOURCE_DIR TARGET ZIG_VERSION ZIG_URL ZIG_SHA < <(
  python3 - "$ROOT/versions.json" "$NATIVES" <<'PY'
import json, sys
x = json.load(open(sys.argv[1]))
p, z = json.load(open(sys.argv[2]))["opencode_pty"], x["zig"]
print(p["version"], p["source_url"], p["source_sha256"], p["source_dir"], p["target"],
      z["version"], z["aarch64_linux_url"], z["aarch64_linux_sha256"])
PY
)

if [ -x "$OUT_DIR/opencode-pty" ] && "$OUT_DIR/opencode-pty" --version 2>/dev/null | grep -q "^opencode-pty $VERSION "; then
  printf 'build-opencode-pty: up to date: %s\n' "$OUT_DIR/opencode-pty"
  exit 0
fi

fetch() {
  local url="$1" expected="$2" output="$3"
  if [ -f "$output" ] && [ "$(sha256sum "$output" | cut -d' ' -f1)" = "$expected" ]; then
    return
  fi
  curl -fL --show-error --retry 5 --retry-all-errors -o "$output.new" "$url"
  printf '%s  %s\n' "$expected" "$output.new" | sha256sum -c - >/dev/null
  mv -f "$output.new" "$output"
}

SOURCE_ARCHIVE="$OUT_DIR/opencode-pty-$VERSION.tar.gz"
ZIG_ARCHIVE="$ROOT/work/toolchains/zig-$ZIG_VERSION.tar.xz"
fetch "$SOURCE_URL" "$SOURCE_SHA" "$SOURCE_ARCHIVE"
fetch "$ZIG_URL" "$ZIG_SHA" "$ZIG_ARCHIVE"

STAGE="$(mktemp -d "$OUT_DIR/.build.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/source" "$STAGE/zig"
# The archive is OpenCode's whole monorepo: extract only the package, without
# the archive's top directory and $SOURCE_DIR's own components.
STRIP=$(( $(tr -cd / <<<"$SOURCE_DIR" | wc -c) + 2 ))
tar -xzf "$SOURCE_ARCHIVE" -C "$STAGE/source" --strip-components="$STRIP" --wildcards "*/$SOURCE_DIR"
tar -xJf "$ZIG_ARCHIVE" -C "$STAGE/zig" --strip-components=1
patch -d "$STAGE/source" -p1 --fuzz=0 --batch < "$ROOT/patches/opencode-pty-termux.patch"

# Upstream's wrapper: `zig build` for a baseline CPU, so Ghostty's VT library
# does not pick up the build machine's CPU features.
export OPENCODE_REAL_ZIG="$STAGE/zig/zig"
export PATH="$STAGE/source/script/release-bin:$PATH"
chmod +x "$STAGE/source/script/release-bin/zig"
export CARGO_TARGET_DIR="$STAGE/target"

cd "$STAGE/source"
# rust-toolchain.toml pins the toolchain; add the musl target to it.
rustup target add "$TARGET" >/dev/null
cargo build --locked --release --target "$TARGET"
BINARY="$CARGO_TARGET_DIR/$TARGET/release/opencode-pty"

python3 - "$ROOT/tools" "$BINARY" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
from elf_native import inspect_elf
info = inspect_elf(open(sys.argv[2], "rb").read())
if info.interpreter or info.needed:
    raise SystemExit(f"build-opencode-pty: not static: interpreter={info.interpreter} needed={info.needed}")
PY
"$BINARY" --version | grep -q "^opencode-pty $VERSION " || {
  echo "build-opencode-pty: unexpected version: $("$BINARY" --version)" >&2
  exit 1
}
install -m 755 "$BINARY" "$OUT_DIR/.opencode-pty.new"
mv -f "$OUT_DIR/.opencode-pty.new" "$OUT_DIR/opencode-pty"
sha256sum "$OUT_DIR/opencode-pty" | cut -d' ' -f1 > "$OUT_DIR/opencode-pty.sha256"
printf 'build-opencode-pty: OK: %s\n' "$OUT_DIR/opencode-pty"
