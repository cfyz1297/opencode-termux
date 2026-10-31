SHELL := bash
VERSION ?= latest

# glibc host: fetch-source, resolve-natives (first: everything below reads work/natives.json)
# Termux:     fetch-bun, build-native (exports the Android sysroot), verify
# glibc host: fetch-host-bun, build-opentui, build-opencode-pty, compile
# (scripts/compile.sh explains why compiling cannot happen inside Termux.)

.PHONY: fetch-source resolve-natives fetch-bun fetch-host-bun build-watcher build-opentui build-fff build-rust-pty export-android-sysroot build-native build-opencode-pty compile verify smoke audit test clean

fetch-source:
	bash scripts/fetch-source.sh $(VERSION)

# The native dependencies and Bun of that source: tools/resolve_natives.py.
resolve-natives: fetch-source
	python3 tools/resolve_natives.py work/upstream/opencode-src

fetch-bun:
	bash scripts/fetch-bun.sh

fetch-host-bun:
	bash scripts/fetch-bun.sh work/bun-host host_bun

build-watcher: fetch-bun
	bash scripts/build-watcher.sh

build-opentui:
	bash scripts/build-opentui.sh

build-fff: fetch-bun
	bash scripts/build-fff.sh

build-rust-pty: fetch-bun
	bash scripts/build-rust-pty.sh

export-android-sysroot:
	bash scripts/export-android-sysroot.sh

build-native: build-watcher build-fff build-rust-pty export-android-sysroot

build-opencode-pty:
	bash scripts/build-opencode-pty.sh

compile: fetch-host-bun build-opentui build-opencode-pty
	SKIP_RUN=1 bash scripts/fetch-bun.sh
	bash scripts/compile.sh

verify:
	bash scripts/verify.sh

smoke:
	python3 tools/tui_smoke.py dist/opencode 15

audit:
	python3 tools/extract_graph.py dist/opencode work/audit.graph > work/audit-extract.json
	python3 tools/audit_native_assets.py work/audit.graph --report work/audit-native.json

test:
	python3 -m unittest discover -s tests -v
	python3 -m py_compile tools/*.py
	bash -n install.sh scripts/*.sh .github/ci/*.sh

clean:
	flock -n .build.lock -c 'rm -rf work/build work/audit.graph work/audit-*.json dist/.opencode.new dist/compile.json'
