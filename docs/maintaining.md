# 维护手册

给维护者（包括以后的自己）。构建和验收都在 CI 里完成；手机上做的是改补丁和工具、跑测试，最多帮着验证一下单个组件。

```bash
make test                        # 回归测试，几秒，不联网
```

## 上游发新版本

每天 03:17 UTC 的 CI 会发现新版本，构建、在 termux-docker 里验收通过后自动发布，不需要人工操作。OpenCode 升级 OpenTUI、FFF、watcher、bun-pty、opencode-pty 或 Bun 也一样：版本从它的 `bun.lock` 和 `package.json` 读出，构建自动从对应版本的源码编译（见 [native-assets.md](native-assets.md#版本从哪来)）。只有补丁打不上、包改了名这类真正的上游变化才需要人工处理。构建失败时按失败的步骤处理：

| 失败在 | 通常意味着 | 怎么办 |
| --- | --- | --- |
| `opencode-000N-*.patch does not apply` | 上游改了补丁涉及的代码 | 在新 tag 的源码上重做这个补丁（见下文），补丁一律 fuzz 0 |
| `resolve_natives: X is not in bun.lock` | 上游改了原生包的名字或不再用它 | 在 `tools/swap_native_assets.py` 改包名，源码仓库或 tag 格式变了再改 `versions.json` 的配方 |
| `resolve_natives: tag ... not found in ...` | 组件的 tag 命名变了 | 改 `versions.json` 里这个组件的 `tag` 格式 |
| `resolve_natives: expected one version` | 同一组件装了两个版本，或几个包的版本对不上 | 看 `bun.lock`，通常是上游升级到一半；等上游修好，或在 `swap_native_assets.py` 里处理 |
| `OpenTUI X needs Zig Y` / `opencode-pty X needs Zig Y` | 组件要求另一个 Zig | 在 `versions.json` 的 `zig` 里加上这个版本（URL 和 SHA-256 见 ziglang.org 的 `download/index.json`），再把该组件的 `zig` 改成它。两者各用各的：OpenTUI 只接受它 `build.zig` 列出的确切版本，opencode-pty 内的 Ghostty 只接受上游发布时用的那个次版本（`release-process-daemon.yml` 的 `ZIG_VERSION`）。不再被引用的 Zig 可以删掉 |
| `versions.json gives X Zig Y but has no such entry` | 组件指向的 Zig 没登记 | 在 `zig` 里加上它，或改回已登记的版本 |
| `opentui-android.patch` / `opencode-pty-termux.patch` / `bun-pty-android.patch` 打不上 | 组件的新版本改了补丁涉及的代码 | 在新版本源码上重做补丁（`work/natives.json` 里有 commit），补丁一律 fuzz 0 |
| `fff-bun-android.patch does not apply` | FFF 的 Bun wrapper 变了 | 重做补丁，`src/ffi.ts` 和 `dist/index.js` 都要改；手机上可以用 Release 里的 `libfff_c.so` 直接测 wrapper |
| `a native asset in the binary is not Bionic` | 产物里出现了新的原生模块 | 看 `work/build/native-assets.json`，见 [native-assets.md](native-assets.md) |
| `host Bun ... cannot compile for Android Bun ...` | 编译用的 Bun 和底座不是同一个版本 | 两者都从 `work/natives.json` 取，通常是本地 `work/bun-host` 里留着旧的；删掉重下 |
| verify 里的 `update` / 文件搜索 / TUI 冒烟 | 运行时问题 | 看 `work/build/*-smoke.log`（CI 的日志里有输出） |

手动重跑：`gh workflow run build.yml -f version=<版本>`。要在分支上验证而不发布，用一个已经发布过的版本、`recut=false`（见 [ci.md](ci.md)）。

## 重做 OpenCode 补丁

```bash
make fetch-source VERSION=<新版本>          # work/upstream/opencode-src，不联网编译
cd work/upstream/opencode-src && git init -q && git add -A && git commit -qm upstream
patch -p1 --merge < ../../../patches/opencode-0002-update-from-termux-releases.patch
# 解决冲突后
git add -A && git diff --cached > ../../../patches/opencode-0002-update-from-termux-releases.patch
```

改完的 TypeScript 可以用 `work/bun-android/bun build --no-bundle <文件>` 检查语法；`src/installation/termux.ts` 这种不依赖上游模块的文件可以直接用 Android Bun 运行。

## Bun 底座

底座是 Bun 官方 Release 里的 `bun-linux-aarch64-android.zip`，编译用的是同一个 Release 的 `bun-linux-aarch64.zip`。版本跟着 OpenCode `package.json` 的 `packageManager` 走，归档对照该 Release 的 `SHASUMS256.txt`，不用手动改。

某个 Bun 版本在 Android 上有问题、需要临时换一个版本时，在 `versions.json` 的 `bun` 里加 `"version": "X.Y.Z"`，它优先于 `packageManager`（新版本要满足 OpenCode 构建脚本要求的范围）。问题解决后删掉这一行。

原生组件编译时不依赖 Bun，Bun 只用来跑它们的冒烟测试，所以换底座不需要改组件。

## 发版

- `vX.Y.Z`：一个 OpenCode 版本第一次通过验收时自动发布。
- `vX.Y.Z-rN`：工具链（Bun 底座、补丁、原生组件、`tools/`、`scripts/`）改了但 OpenCode 版本没变时，手动重新发布：

  ```bash
  gh workflow run build.yml -f version=latest -f recut=true
  ```

  不急的话，改动会随下一个 OpenCode 版本自然发布。
- 只有最高的 OpenCode 版本会成为 Latest，所以重新发布旧版本不会让安装回退。
- 发布说明列出相对上一个 Release 的工具链变更（不含 `docs/`、`tests/` 和 Markdown）。
- 推送到 `main` 会触发完整的 Bionic 构建；只改文档时在提交信息里写 `[skip ci]`。有构建正在发布时别推会触发构建的提交。

## 兼容约束

已经装在用户手机上的 `opencode` 会在 `upgrade` 时从 `main` 下载 `install.sh` 来运行，所以下面这些对它们是接口：

- `install.sh` 的环境变量 `VERSION`（`latest`、`X.Y.Z`，或 `X.Y.Z-rN`）、`PREFIX`、`OPENCODE_TERMUX_REPO`，以及 OpenCode 2 传的参数 `--version X.Y.Z --no-modify-path`。已安装的版本只会传 `X.Y.Z`，它表示这个版本最新的那次构建；
- Release 附件名 `opencode-termux-v<版本>-android-aarch64.zip`、`.zip.sha256` 和 `build-manifest.json`，`-rN` 重发时附件名里仍是不带 `-rN` 的版本；
- 清单字段 `tag_name`（更新检查读它，必须保持 `vX.Y.Z`，带上 `-rN` 会让 TUI 每次都认为有新版本）和 `output_sha256`（`install.sh` 和 `upgrade` 按它判断是否同一个构建）。

还装着 OpenCode 1 的用户也走这套接口：1.18.33 到 1.19.0 的 `upgrade` 读同一个清单，看到 2.x 就会升级；1.18.32 及更早的更新器还指向官方，要重新运行一次安装命令。

## 踩过的坑

- **Android 版 Bun 不能用来编译 OpenCode。** `bun build --compile` 把 `process.platform` 写死成编译用 Bun 的平台，Android 版写的是 `android`，原生包都按 `linux` 选，产物启动时找不到 OpenTUI。所以编译放在 glibc 主机上，用 `compile.executablePath` 嵌进 Android Bun。
- **Bun 把 `node_modules` 硬链接到全局缓存。** 原地改文件会改坏缓存，之后别的项目装到的也是改过的版本；`swap_native_assets.py` 都是删掉再写新文件。Android 上没有硬链接（Termux 的 Python 甚至没有 `os.link`），相关测试在 Termux 里跳过。
- **FFF 在 Android 上崩溃。** 堆指针高字节带 tag，`read.ptr()` 返回的 number 丢了这些位。用 Release 里的 `libfff_c.so` 和未打补丁的 wrapper 就能在手机上复现。
- **termux-docker 里没有 `/usr/bin/env`。** `make test` 也会在 Bionic 容器里跑，测试造的假命令要用 `sys.executable` 或 `shutil.which("bash")` 的绝对路径做解释器。
- **api.github.com 匿名每小时 60 次。** 手机常在运营商 NAT 后面，很快用完；安装器和更新检查都只用 Release 页面的跳转和 Release 附件，它们不受这个限制。
- **补丁要打在 Bun 实际打包的文件上。** `@ff-labs/fff-bun` 的 `exports` 有 `bun` 条件，指向 `src/index.ts`；只补 `dist/index.js` 时补丁照样按 fuzz 0 应用、编译照样通过，产物一搜索就崩。OpenCode 2 最初的构建就是这样，用 `grep -a` 在产物里找补丁删掉的代码（比如 `fff_mixed_search_result_get_item(`）能确认打包的是哪一份。
- **OpenCode 2 只在 git 仓库里用 FFF。** 其他目录走 ripgrep，所以 `serve_smoke.py` 先 `git init`，并确认服务端把它认作 git 项目；verify 容器因此要装 git。
- **FFF 的搜索要等扫描。** 大目录里扫描还没完成搜索就返回空，所以 `serve_smoke.py` 用一个只有两个文件的小目录，并且重试到超时。
- **opencode-pty 把 socket 放在 `/tmp`。** Android 没有 `/tmp`，daemon 一启动就退出（`Permission denied`）；补丁改到 `$PREFIX/tmp`。用 `proot -b $PREFIX/tmp:/tmp` 运行上游的二进制可以在手机上对照验证。
- **Zig 0.17 的 libc 文件要写全字段。** 缺了新加的 `darwin_sdk_dir` 就解析失败；Linux 目标（Android 也算）的 `crtbegin_so.o`/`crtend_so.o` 改从 `cc_dir`（旧名 `gcc_dir`）找，它空着也会失败。`opentui-android.patch` 让它和 `crt_dir` 指向同一个 NDK 目录。这类问题补丁照样按 fuzz 0 打上，要到链接时才报错；在手机上用 `zig build-lib -dynamic -target aarch64-linux-android.28 --libc <文件>` 链接一个小库就能先验证（`zig build` 和 `zig translate-c` 在 Termux 里跑不起来：Zig 为本机编译的辅助程序一启动就 SIGILL）。另外 0.17 的 `zig build` 去掉了 `--global-cache-dir`，全局缓存只能用环境变量 `ZIG_GLOBAL_CACHE_DIR` 指定。
- Android 上 `/tmp` 不可写，临时文件放 `$TMPDIR`。
