# CI architecture

The `bionic` job runs on a GitHub ARM64 runner and alternates between the
runner and the official [`termux/termux-docker`](https://github.com/termux/termux-docker)
AArch64 image, which supplies Bionic libc, `/system/bin/linker64`, AOSP
libraries and a Termux filesystem layout.

```text
ubuntu-24.04-arm GitHub runner
├── termux-docker (pinned): bionic-build.sh natives
│   ├── make test
│   ├── Termux clang + Android NDK libraries
│   ├── Ubuntu proot (host-side Rust 1.90 only)
│   ├── build watcher, FFF and bun-pty for Bionic, with their smoke tests
│   └── export the Android sysroot to the workspace
├── runner (glibc): make fetch-source && make compile
│   ├── OpenTUI with the Zig it requires (0.17) against that sysroot
│   ├── opencode-pty as a static musl executable with upstream's Zig (0.16), as upstream builds it
│   ├── OpenCode source of the tag's commit + patches/opencode-NNNN-*.patch
│   ├── bun install, the native assets swapped into node_modules
│   └── bun build --compile, embedded into the pinned Android Bun
└── termux-docker (pinned): bionic-build.sh verify
    ├── --version, OpenTUI load, FFF search in a git repo through `opencode serve`
    ├── an opencode-pty session and the real OpenCode TUI smoke test
    └── package
```

Before anything is built, `make resolve-natives` reads the native dependency
versions and the Bun version from the OpenCode source being built (its
`bun.lock` and `package.json`) into `work/natives.json`; nothing native is
pinned in this repository (see [native-assets.md](native-assets.md#版本从哪来)).
The Termux-built assets (watcher, FFF, bun-pty and the exported sysroot) are
cached under a key that hashes every input they are built from: their resolved
entries in `work/natives.json`, `versions.json`, their scripts, patches and
smoke tests. A run whose inputs match an earlier one
restores them and only runs the tests in that phase; any change rebuilds them.

OpenCode is compiled on the runner because the Android Bun bakes
`process.platform === "android"` into a bundle, and OpenCode's native
dependencies only know `linux` (see [architecture.md](architecture.md)).
Nothing built on the runner is trusted until it has run inside Termux.

The Ubuntu proot is a compiler host, not the runtime under test. Every native
library and the final `opencode` executable are loaded by Bionic inside the
Termux container.

This is a real Bionic userspace, but not a complete Android device: it has no
Dalvik/ART, Android framework services or app sandbox. OpenCode only needs the
native libc/dl/m/log/z, filesystem, PTY and inotify surface covered by the
smoke tests. A physical-device run remains the final reference when changing
the Bun base, NDK generation or native ABI patches.

## Triggers

| Trigger | What runs |
| --- | --- |
| Pull request | `resolve` and the regression tests only |
| Push to `main` | Full Bionic build and tests of the latest OpenCode; published only if that version has no release yet |
| Daily (03:17 and 15:17 UTC) | Checks the official latest release; a version without a release is built, tested and published |
| `workflow_dispatch` | Builds the given version; `recut=true` re-releases an already released version as `vX.Y.Z-rN` |

Add `[skip ci]` to a commit message to skip the push build, then re-release
with `gh workflow run build.yml -f version=latest -f recut=true` if needed.

Only `main` publishes. Dispatching a branch runs the build and every acceptance
step for any version, released or not, and skips the release job:

```bash
gh workflow run build.yml --ref <branch> -f version=latest
```

## Releases

- Tags are `vX.Y.Z`. A re-release of the same OpenCode version after toolchain
  changes (Bun base, patches, native assets) is `vX.Y.Z-rN`.
- The release job only creates releases; it never edits or re-uploads one.
  With immutable releases enabled in the repository settings, GitHub also
  enforces this and reserves a published tag name forever, so a yanked
  release is re-cut as the next `-rN`; the release job does that
  automatically when GitHub rejects a reserved name.
- The tag is created with `--target` on the commit the run built.
- Only the highest OpenCode version may be marked Latest, so re-cutting an
  older version never rolls `install.sh` users back.
- Release notes list the toolchain commits since the previous release
  (excluding `docs/`, `tests/` and Markdown).
- `build-manifest.json` keeps `tag_name` as `vX.Y.Z` even for a re-cut: the
  bundled `Installation.latest()`, and the TUI's automatic update check behind
  it, compares versions. `opencode update`, `opencode upgrade` and
  `install.sh` compare `output_sha256` with the installed binary instead, so a
  re-cut is offered explicitly but never reinstalled in the background.

## Trust boundaries

- The Termux image is pinned by OCI digest, not a mutable tag.
- OpenCode source is fetched by the commit its tag points to; the commit and
  the archive's SHA-256 are recorded in `build-manifest.json`.
- Both Bun builds and all native source archives are checked against pinned
  SHA-256 values.
- The build job has read-only repository permission.
- Only the release job receives `contents: write`.
- A release is never created when the TUI smoke is skipped or fails.
