# Third-party components

The generated executable is compiled from, or links, the following upstream work:

- [OpenCode](https://github.com/anomalyco/opencode), MIT
- [Bun](https://github.com/oven-sh/bun), MIT
- [OpenTUI](https://github.com/anomalyco/opentui), MIT
- [FFF](https://github.com/dmtrKovalenko/fff), MIT
- [@parcel/watcher](https://github.com/parcel-bundler/watcher), MIT
- [bun-pty](https://github.com/sursaone/bun-pty), MIT
- [portable-pty](https://github.com/wezterm/wezterm/tree/main/pty), MIT
- [opencode-pty](https://github.com/anomalyco/opencode/tree/dev/packages/process-daemon), MIT, with
  [Ghostty](https://github.com/ghostty-org/ghostty)'s VT library, MIT, linked in

The build also contains transitive Rust, Zig, C and C++ dependencies under
their respective upstream licenses. The versions follow OpenCode's lockfile;
the versions, commits and archive hashes each release was built from are
recorded in its `BUILD-MANIFEST.json` (`natives`).

Releases up to v1.18.35-r1 were not compiled from source: they grafted the
official build's module graph onto the Android Bun with `tools/revive_patch.py`,
vendored from [Hope2333/opencode-termux](https://github.com/Hope2333/opencode-termux),
MIT (with a fix sent upstream as Hope2333/opencode-termux#34). The current
build no longer contains it.
