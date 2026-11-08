# Native asset ledger

编译前替换进 `node_modules` 的 Bionic 资产（`tools/swap_native_assets.py`）：

| npm 包里的文件 | 上游源码 | `DT_NEEDED` |
|---|---:|---|
| `@opentui/core-linux-arm64/libopentui.so` | OpenTUI | `libm.so`, `libc.so`, `libdl.so` |
| `@ff-labs/fff-bin-linux-arm64-gnu/libfff_c.so` | FFF | `libz.so`, `libdl.so`, `libm.so`, `libc.so` |
| `@parcel/watcher-linux-arm64-glibc/watcher.node` | `@parcel/watcher` | `liblog.so`, `libdl.so`, `libm.so`, `libc.so` |
| `bun-pty/rust-pty/target/release/librust_pty_arm64.so` | `bun-pty` | `libdl.so`, `libc.so` |
| `bun-pty/rust-pty/target/release/librust_pty_arm64_musl.so` | 同上，同一个文件 | `libdl.so`, `libc.so` |

bun-pty 0.4.10 起在 Linux 上同时内嵌 musl 版，只在 ld-musl 下加载。它只依赖 `libc.so`，
与 Android 的同名，`--require-bionic` 审计分不出来，所以同样换成 Bionic 库。

## 版本从哪来

每个组件编译哪个版本，由要编译的 OpenCode 决定：`tools/resolve_natives.py` 读它的
`bun.lock`，取上表这些 npm 包装上的版本（同一组件的几个包必须是同一个版本，也只能装一份），
再按 `versions.json` 里的配方找源码，写进 `work/natives.json`，所有编译脚本都读这个文件：

- GitHub 源码（OpenTUI、FFF、bun-pty、opencode-pty）：按配方的 tag 格式（如 `v{version}`、
  `process-daemon-v{version}`）用 `git ls-remote` 解析出 commit，按 commit 下载归档，记下
  commit 和 SHA-256。
- npm 源码（`@parcel/watcher` 和它装上的 `node-addon-api`）：registry 的 tarball，对照
  `bun.lock` 里的 sha512 integrity。
- Bun 底座和编译用的 Bun：版本取 OpenCode `package.json` 的 `packageManager`，归档对照该
  Release 的 `SHASUMS256.txt`。
- Zig 是我们选的工具链，不是 OpenCode 装的依赖：`versions.json` 的 `zig` 按版本登记
  归档地址和 SHA-256，用 Zig 编译的组件（OpenTUI、opencode-pty）在自己的配方里写明用哪个，
  两者可以不同。解析时检查它们是否满足源码的要求：OpenTUI 的 `build.zig.zon` 里的
  `minimum_zig_version` 不能比它用的新；opencode-pty 要和上游 `release-process-daemon.yml`
  的 `ZIG_VERSION` 同一个次版本，patch 不低于它（它编译的 Ghostty 只接受这个次版本）。
  不满足时构建在解析这一步就失败。

某次构建实际用的版本、commit 和哈希都记在 Release 的 `BUILD-MANIFEST.json`
（`natives`）里。产物里的模块名带 Bun 生成的哈希后缀，如 `libopentui-x8k2b6xk.so`。
原生输出可能包含构建目录或 build-id，所以每次构建的实际 SHA-256 也由
`dist/build-manifest.json` 记录，不把它误当作源码身份。

## FFF pointer boundary

Bionic 的 tagged heap pointer 可能大于 JavaScript 的安全整数上限。FFF 的 Bun wrapper
使用 `read.ptr()` 并以 `number` 做地址运算，实例创建后执行文件搜索会丢失地址位并崩溃
（`Segmentation fault at address 0x7FFFFFFFFFFFFFFF`），销毁实例时也一样。
`patches/fff-bun-android.patch` 在编译前修补 `@ff-labs/fff-bun`：指针字段改用
`read.u64()`，地址以 `bigint` 保存，数组步进也使用 `BigInt`；目录和混合搜索不再逐项
调用返回 number 的 getter，而是从结果结构体读取数组基址。

Bun 解析这个包时走 `exports` 的 `bun` 条件，打包的是 `src/ffi.ts` 而不是
`dist/index.js`，补丁两处都改。文件、目录和混合搜索已在真机上通过；发布验收由
`tools/serve_smoke.py` 在 git 仓库里经 `opencode serve` 再测一次打包后的 wrapper，非
仓库目录 OpenCode 用 ripgrep，测不到 FFF。

## OpenTUI pointer boundary

Android 17 тегирует указатели кучи в старшем байте (TBI): `malloc(64)` отдаёт
`0xb400007a3a41e380`, а адрес в этом указателе — `0x7a3a41e380`. Значение
`0xb4…` больше `Number.MAX_SAFE_INTEGER`, а OpenTUI конвертирует указатель
контекста из `ot_context_create` в JS-number и падает с
`Pointer exceeds safe integer range` — то есть TUI не стартует на первом же
нативном вызове. CI этого не ловит: в `termux-docker` нет tagged-address ABI,
поэтому теги там не появляются.

`scripts/patch-opentui-pointer.mjs` перед сборкой находит
`toSafeNumberPointer` в `node_modules/@opentui/core` и срезает старший байт:
если значение больше `2^53−1`, берётся `pointer & 0x00ffffffffffffffn`, и только
потом `Number(...)`. Тег не входит в адрес, а `bun:ffi` принимает только
числовые указатели, поэтому сохранить `bigint` вместо маски нельзя.

Скрипт идемпотентен, проверяет себя флагом `--self-test` (тегированный указатель
превращается в адрес, обычный остаётся как есть, мусор отклоняется) и падает,
если в новой версии OpenTUI такой функции нет: молчаливая сборка бинаря без TUI
хуже явной ошибки. Проверка живёт в `scripts/compile.sh` между `bun install` и
`bun build --compile`.

## Watcher

`@parcel/watcher-android-arm64@2.5.1` 的预编译文件依赖 `libc++_shared.so`，在 Android
linker namespace 下不能作为独立单文件可靠加载。本项目从相同官方源码重建并静态链接
C++ runtime；监听功能 smoke 已通过。

## PTY

v1.18.32 内嵌的 FFI PTY 来自 `bun-pty` 0.4.8。其 `portable-pty` 0.8.1 不支持 Android，
项目更新到兼容的 0.9.0 后交叉编译，真实 PTY 输出与退出码 smoke 已通过。

Rust 原生资产链接 `native/tls-align.S`，确保 Android AArch64 动态链接器可接受的 TLS
alignment。OpenTUI 构建同样注入该 alignment anchor。
