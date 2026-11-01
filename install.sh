#!/data/data/com.termux/files/usr/bin/bash
# Install or update OpenCode for Termux from this project's Bionic-verified
# releases. `opencode upgrade` downloads this script from main and runs it:
# OpenCode 1 with VERSION set, OpenCode 2 with `--version X.Y.Z
# --no-modify-path`. Both interfaces (and PREFIX, OPENCODE_TERMUX_REPO) must
# keep working for every installed binary.
#
#   VERSION=latest     the latest release
#   VERSION=X.Y.Z      the newest build of OpenCode X.Y.Z: vX.Y.Z, or its
#                      highest re-cut vX.Y.Z-rN
#   VERSION=X.Y.Z-rN   exactly that release
#
# Releases are compared by binary hash, not version, so a re-cut is picked up
# and an install that already matches is left alone. OPENCODE_TERMUX_FORCE=1
# reinstalls anyway.
set -euo pipefail

REPOSITORY="${OPENCODE_TERMUX_REPO:-cfyz1297/opencode-termux}"
REQUESTED_VERSION="${VERSION:-latest}"
PREFIX_PATH="${PREFIX:-/data/data/com.termux/files/usr}"
FORCE="${OPENCODE_TERMUX_FORCE:-0}"
RELEASES="https://github.com/$REPOSITORY/releases"

die() {
  printf 'opencode-termux: %s\n' "$*" >&2
  exit 1
}

while [ $# -gt 0 ]; do
  case "$1" in
    --version) [ $# -ge 2 ] || die "--version needs a value"; REQUESTED_VERSION="$2"; shift 2 ;;
    --version=*) REQUESTED_VERSION="${1#--version=}"; shift ;;
    --no-modify-path) shift ;;  # it installs into $PREFIX/bin, which is on PATH
    *) die "unknown option: $1" ;;
  esac
done

[ "$(uname -m)" = "aarch64" ] || die "only Android AArch64 is supported"
[ -d "$PREFIX_PATH/bin" ] || die "run this installer inside Termux"
command -v curl >/dev/null || die "curl is required (pkg install curl)"
# OpenCode searches files with ripgrep and would otherwise download the
# official build, which needs glibc. Termux packages a native one.
command -v rg >/dev/null || {
  printf 'Installing the ripgrep dependency...\n'
  pkg install -y ripgrep
}

api_level="$(getprop ro.build.version.sdk 2>/dev/null || true)"
if [[ "$api_level" =~ ^[0-9]+$ ]] && [ "$api_level" -lt 28 ]; then
  die "Android API 28 or newer is required (device API: $api_level)"
fi

stage="$(mktemp -d "${TMPDIR:-$PREFIX_PATH/tmp}/opencode-termux.XXXXXX")"
trap 'rm -rf "$stage"' EXIT

# The release page redirect and release assets have no API rate limit, unlike
# api.github.com (60 calls an hour per IP, which carrier NAT exhausts).
latest_tag() {
  local url
  url="$(curl -fsSL --retry 3 -o /dev/null -w '%{url_effective}' "$RELEASES/latest")" || return 1
  printf '%s\n' "${url##*/}"
}

fetch_manifest() {  # fetch_manifest <tag> <file>
  curl -fsSL --retry 3 -o "$2" "$RELEASES/download/$1/build-manifest.json" 2>/dev/null
}

if [ "$REQUESTED_VERSION" = "latest" ]; then
  tag="$(latest_tag)" || die "could not reach $RELEASES"
else
  wanted="${REQUESTED_VERSION#v}"
  [[ "$wanted" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-r[0-9]+)?$ ]] || \
    die "bad version '$REQUESTED_VERSION' (expected X.Y.Z or X.Y.Z-rN)"
  tag="v$wanted"
  if [[ "$wanted" != *-r* ]]; then
    # The newest build of a version: usually the latest release, otherwise the
    # highest re-cut that exists.
    latest="$(latest_tag || true)"
    if [[ "$latest" =~ ^v${wanted//./\\.}(-r[0-9]+)?$ ]]; then
      tag="$latest"
    else
      n=1
      while fetch_manifest "v$wanted-r$n" "$stage/probe.json"; do
        tag="v$wanted-r$n"
        n=$((n + 1))
      done
    fi
  fi
fi
[[ "$tag" =~ ^v([0-9]+\.[0-9]+\.[0-9]+)(-r[0-9]+)?$ ]] || \
  die "could not resolve a valid release (got '$tag')"
version="${BASH_REMATCH[1]}"

fetch_manifest "$tag" "$stage/build-manifest.json" || die "release $tag not found"
# grep, not python: the installer must run on a fresh Termux.
want_sha="$(grep -m1 -o '"output_sha256": *"[0-9a-f]\{64\}"' "$stage/build-manifest.json" \
  | grep -o '[0-9a-f]\{64\}' || true)"
[ -n "$want_sha" ] || die "release $tag has no binary hash in build-manifest.json"

target="$PREFIX_PATH/bin/opencode"
if [ "$FORCE" != "1" ] && [ -f "$target" ] \
   && [ "$(sha256sum "$target" | cut -d' ' -f1)" = "$want_sha" ]; then
  printf 'OpenCode %s is already up to date (%s)\n' "$version" "$tag"
  exit 0
fi

command -v unzip >/dev/null || {
  printf 'Installing the unzip dependency...\n'
  pkg install -y unzip
}

package="opencode-termux-v${version}-android-aarch64"
printf 'Downloading OpenCode %s (%s) for Termux...\n' "$version" "$tag"
curl -fL --retry 5 --retry-all-errors --retry-delay 2 -C - \
  --progress-bar -o "$stage/$package.zip" \
  "$RELEASES/download/$tag/$package.zip"
curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 \
  -o "$stage/$package.zip.sha256" \
  "$RELEASES/download/$tag/$package.zip.sha256"

(
  cd "$stage"
  sha256sum -c "$package.zip.sha256" >/dev/null
  unzip -q "$package.zip"
)
[ "$(sha256sum "$stage/$package/opencode" | cut -d' ' -f1)" = "$want_sha" ] || \
  die "the downloaded binary does not match build-manifest.json of $tag"

install -m 755 "$stage/$package/opencode" "$PREFIX_PATH/bin/.opencode.new"
mv -f "$PREFIX_PATH/bin/.opencode.new" "$target"
printf 'Installed: %s (%s)\n' "$target" "$tag"
"$target" --version
