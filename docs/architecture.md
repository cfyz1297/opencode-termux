# Architecture

## 从源码编译

本项目构建 OpenCode 2（npm 包 `@opencode/cli`，上游的 v2 分支）。上游发布 Linux 版的方式
是：在 Linux 主机上执行 `packages/cli/script/build.ts`，由 `bun build --compile` 把 bundle
嵌进目标平台的 Bun（上游用 `BUN_COMPILE_RELEASE` 指定那个 Bun）。本项目走同一条路，只换掉
被嵌入的 Bun：

```text
OpenCode vX.Y.Z（tag 对应的提交）
   │ patches/opencode-NNNN-*.patch（fuzz 0）
   │ bun install
   │ tools/swap_native_assets.py：从源码编译的原生组件替换 node_modules 里的 glibc 版
   │ bun build --compile --target bun-linux-arm64，executablePath = Android Bun
   ▼
dist/opencode = 官方 bun-linux-aarch64-android + OpenCode bundle
```

编译主机是 glibc AArch64 Linux，用与底座同版本的官方 Bun（`work/natives.json` 的
`host_bun` 与 `base_bun`，版本取 OpenCode `package.json` 的 `packageManager`）。两者版本必须
一致，因为 bundle 的格式由编译用的 Bun 决定。

## 为什么不在 Termux 里编译

`bun build --compile` 在打包时把 `process.platform` 和 `process.arch` 写死成常量。
Android 版 Bun 写进去的是 `android`，而 OpenTUI（`$8[platform]`）、FFF（`fff-bin-linux-*`）
和 `@parcel/watcher`（`watcher-${platform}-${arch}`）都按平台名挑原生包，只认
`linux`。glibc 主机上的 Bun 写的是 `linux`，和上游发布的二进制完全一致；运行时 Android
Bun 照常执行这些已经写死的分支。

## Android 补丁

| 补丁 | 改什么 |
| --- | --- |
| `opencode-0001-compile-on-android-bun` | `build.ts` 的 `compileExecutable()` 从 `OPENCODE_TERMUX_BUN` 取被嵌入的 Bun |
| `opencode-0002-update-from-termux-releases` | 更新服务（`services/updater.ts`）：`$PREFIX/bin` 识别为 curl 安装，最新版读本项目 Release 的 `build-manifest.json`，安装脚本换成本项目的 `install.sh`；`upgrade`（别名 `update`）遇到同版本时按二进制哈希判断（`src/termux.ts`） |
| `opencode-0003-ripgrep-from-termux` | 找不到 `rg` 时不再下载 ripgrep 的官方 glibc 版，提示 `pkg install ripgrep`；`install.sh` 会装上 Termux 打包的 ripgrep |
| `fff-bun-android` | FFF 的 Bun wrapper 用 `read.u64` 读指针并以 bigint 运算：Android AArch64 的堆指针高字节带 tag，JavaScript number 存不下。Bun 按 `bun` 导出条件打包 `src/ffi.ts`，`dist/index.js` 也一并修补 |
| `opencode-pty-termux` | opencode-pty 的 socket 目录从 `/tmp`（Android 没有）改到 `$PREFIX/tmp` |
| `opentui-android`、`bun-pty-android` | 原生组件本身的 Android 构建，见 [native-assets.md](native-assets.md) |

OpenCode 的补丁按 fuzz 0 应用；上游改了相关代码时构建直接失败，不会悄悄打偏。

## 原生组件

`bun install` 在 glibc 主机上装的是 linux-arm64 的平台包。`swap_native_assets.py` 在编译前
把这些文件换成从源码编译的版本：前五个是 Termux 里编译的 Bionic 库，opencode-pty 是
OpenCode 启动的独立程序，按上游 musl 版的方式编成静态可执行文件，不经过任何动态链接器：

| npm 包 | 文件 |
| --- | --- |
| `@opentui/core-linux-arm64` | `libopentui.so` |
| `@parcel/watcher-linux-arm64-glibc` | `watcher.node` |
| `@ff-labs/fff-bin-linux-arm64-gnu` | `libfff_c.so` |
| `bun-pty` | `rust-pty/target/release/librust_pty_arm64.so` |
| `bun-pty` | `rust-pty/target/release/librust_pty_arm64_musl.so`（同一个 Bionic 库） |
| `@opencode/pty-linux-arm64-gnu` | `bin/opencode-pty` |

装上的版本必须等于原生组件实际编译的版本（`work/natives.json`）。这些版本由
`tools/resolve_natives.py` 从同一份 `bun.lock` 读出，所以正常情况下必然一致；不一致说明解析
或安装出了问题，构建失败。替换是删掉再写新文件，因为 Bun 把 `node_modules` 硬链接到全局缓存。

编译后仍从产物里提取模块图，用 `audit_native_assets.py --require-bionic` 审计：任何一个
内嵌 ELF 带 glibc 依赖都不会进入发布（静态的 opencode-pty 没有解释器和 `DT_NEEDED`）。

## 发布门禁

正式产物必须同时满足：

1. 补丁全部按 fuzz 0 应用，原生组件版本与 OpenCode 的 `bun.lock` 一致（`work/natives.json`）；
2. 产物模块图里的内嵌 ELF 都是 AArch64，且没有 glibc 依赖；
3. `--version` 与源码 tag 一致；
4. `opencode serve` 的文件搜索接口在 git 仓库里（OpenCode 只在仓库里用 FFF）经由打过补丁的 FFF wrapper 找到文件，服务端搜索后和退出时都不崩溃（`tools/serve_smoke.py`）；
5. TUI 在隔离 HOME 中渲染真实帧；
6. opencode-pty 在 Termux 里跑通一个真实 shell 会话；
7. 原生组件各自的 FFF / watcher / PTY 冒烟通过（在组件编译时）。

1、2 在编译主机上检查（`scripts/compile.sh`），3 到 6 在 termux-docker 里运行
（`scripts/verify.sh`）。只有全部通过，候选文件才会成为 `dist/opencode`。
