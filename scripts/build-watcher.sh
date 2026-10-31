#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PREFIX_PATH="${PREFIX:-/data/data/com.termux/files/usr}"
OUT_DIR="${1:-$ROOT/work/native/watcher}"
BUN="${BUN:-$ROOT/work/bun-android/bun}"
mkdir -p "$OUT_DIR"

command -v clang++ >/dev/null || { echo "build-watcher: clang++ is required" >&2; exit 1; }
[ -x "$BUN" ] || { echo "build-watcher: Bionic Bun is missing: $BUN" >&2; exit 1; }
STATIC_DIR="$PREFIX_PATH/aarch64-linux-android/lib"
for library in libc++_static.a libc++abi.a libunwind.a; do
  [ -f "$STATIC_DIR/$library" ] || {
    echo "build-watcher: $STATIC_DIR/$library is missing; install ndk-multilib-native-static" >&2
    exit 1
  }
done

# work/natives.json: what tools/resolve_natives.py found for the OpenCode source (make resolve-natives).
NATIVES="${NATIVES_JSON:-$ROOT/work/natives.json}"
[ -f "$NATIVES" ] || { echo "build-watcher: $NATIVES is missing; run make resolve-natives" >&2; exit 1; }
read -r VERSION SOURCE_URL SOURCE_SHA NAPI_VERSION NAPI_URL NAPI_SHA < <(
  python3 - "$NATIVES" <<'PY'
import json, sys
w = json.load(open(sys.argv[1]))["watcher"]
print(w["version"], w["source_url"], w["source_sha256"],
      w["node_addon_api_version"], w["node_addon_api_url"],
      w["node_addon_api_sha256"])
PY
)

fetch() {
  local url="$1" expected="$2" output="$3"
  if [ -f "$output" ] && [ "$(sha256sum "$output" | cut -d' ' -f1)" = "$expected" ]; then
    return
  fi
  curl -fL --show-error --retry 3 -o "$output.new" "$url"
  printf '%s  %s\n' "$expected" "$output.new" | sha256sum -c - >/dev/null
  mv -f "$output.new" "$output"
}

SOURCE_ARCHIVE="$OUT_DIR/watcher-$VERSION.tgz"
NAPI_ARCHIVE="$OUT_DIR/node-addon-api-$NAPI_VERSION.tgz"
fetch "$SOURCE_URL" "$SOURCE_SHA" "$SOURCE_ARCHIVE"
fetch "$NAPI_URL" "$NAPI_SHA" "$NAPI_ARCHIVE"

STAGE="$(mktemp -d "$OUT_DIR/.build.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/source" "$STAGE/node-addon-api"
tar -xzf "$SOURCE_ARCHIVE" -C "$STAGE/source" --strip-components=1
tar -xzf "$NAPI_ARCHIVE" -C "$STAGE/node-addon-api" --strip-components=1

cd "$STAGE/source"
CANDIDATE="$OUT_DIR/.watcher.new.node"
clang++ -std=c++17 -O2 -fPIC -fexceptions \
  -DNAPI_DISABLE_CPP_EXCEPTIONS -DWATCHMAN -DINOTIFY -DBRUTE_FORCE \
  -I"$PREFIX_PATH/include/node" -I"$STAGE/node-addon-api" \
  src/binding.cc src/Watcher.cc src/Backend.cc src/DirTree.cc src/Glob.cc \
  src/Debounce.cc src/watchman/BSER.cc src/watchman/WatchmanBackend.cc \
  src/shared/BruteForceBackend.cc src/linux/InotifyBackend.cc src/unix/legacy.cc \
  -shared -nostdlib++ -Wl,--exclude-libs,ALL \
  "$STATIC_DIR/libc++_static.a" "$STATIC_DIR/libc++abi.a" "$STATIC_DIR/libunwind.a" \
  -llog -ldl -lm -o "$CANDIDATE"

python3 "$ROOT/tools/elf_native.py" "$CANDIDATE" >/dev/null
"$BUN" "$ROOT/tools/watcher_smoke.js" "$CANDIDATE" \
  > "$OUT_DIR/smoke.json"
mv -f "$CANDIDATE" "$OUT_DIR/watcher.node"
sha256sum "$OUT_DIR/watcher.node" | cut -d' ' -f1 > "$OUT_DIR/watcher.node.sha256"
printf 'build-watcher: OK: %s\n' "$OUT_DIR/watcher.node"
