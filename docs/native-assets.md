# Native asset ledger

编译前替换进 `node_modules` 的 Bionic 资产（`tools/swap_native_assets.py`）：

| npm 包里的文件 | 上游源码 | `DT_NEEDED` |
|---|---:|---|
| `@opentui/core-linux-arm64/libopentui.so` | OpenTUI | `libm.so`, `libc.so`, `libdl.so` |
| `@ff-labs/fff-bin-linux-arm64-gnu/libfff_c.so` | FFF | `libz.so`, `libdl.so`, `libm.so`, `libc.so` |
| `@parcel/watcher-linux-arm64-glibc/watcher.node` | `@parcel/watcher` | `liblog.so`, `libdl.so`, `libm.so`, `libc.so` |
| `bun-pty/rust-pty/target/release/librust_pty_arm64.so` | `bun-pty` | `libdl.so`, `libc.so` |
| `bun-pty/rust-pty/target/release/librust_pty_arm64_musl.so` | 同上，同一个文件 | `libdl.so`, `libc.so` |
| `@number0/iroh-linux-arm64-gnu/iroh.linux-arm64-gnu.node` | `@number0/iroh-android-arm64` | `libdl.so`, `libm.so`, `libc.so` |

iroh 是 OpenCode 2.4 起「machine link」用的 binding：`bun build --compile` 通过
`iroh-binding` 插件把目标平台的 `.node` 嵌进二进制，在 ARM64 主机上就是 glibc 那个。
它没有源码可编译，`scripts/fetch-iroh.sh` 直接取同一版本的 android-arm64 预编译包替换。

bun-pty 0.4.10 起在 Linux 上同时内嵌 musl 版，只在 ld-musl 下加载。它只依赖 `libc.so`，
与 Android 的同名，`--require-bionic` 审计分不出来，所以同样换成 Bionic 库。

## 版本从哪来

每个组件编译哪个版本，由要编译的 OpenCode 决定：`tools/resolve_natives.py` 读它的
`bun.lock`，取上表这些 npm 包装上的版本（同一组件的几个包必须是同一个版本，也只能装一份），
再按 `versions.json` 里的配方找源码，写进 `work/natives.json`，所有编译脚本都读这个文件：

- GitHub 源码（OpenTUI、FFF、bun-pty、opencode-pty）：按配方的 tag 格式（如 `v{version}`、
  `process-daemon-v{version}`）用 `git ls-remote` 解析出 commit，按 commit 下载归档，记下
  commit 和 SHA-256。
- npm 源码（`@parcel/watcher`、它装上的 `node-addon-api` 和 iroh 的 android-arm64 包）：registry 的 tarball，对照
  `bun.lock` 里的 sha512 integrity。
- Bun 底座和编译用的 Bun：版本取 OpenCode `package.json` 的 `packageManager`，归档对照该
  Release 的 `SHASUMS256.txt`。
- Zig 是我们选的工具链，不是 OpenCode 装的依赖：`versions.json` 的 `zig` 按版本登记
  归档地址和 SHA-256，用 Zig 编译的组件（OpenTUI、opencode-pty）在自己的配方里写明用哪个，
  两者可以不同。解析时检查它们是否满足源码的要求：OpenTUI 只接受 `build.zig.zon`
  里 `minimum_zig_version` 那个确切版本（`build.zig` 按 major/minor/patch 全等比较）；
  opencode-pty 要和上游 `release-process-daemon.yml`
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

## free() 杀掉带截断标签的指针（TUI 出现后立刻 Aborted）

和上面同一类根源，但炸在释放而不是转换。链条是这样的：OpenTUI 把 context 和
Yoga 句柄按 `u64` 读出来，`toPointer`/`toSafeNumberPointer` 转成 Number 交给
`bun:ffi`（bun:ffi 只收数字指针）；本仓库的
`scripts/patch-opentui-pointer.mjs` 把高位标签掩掉
（`pointer & 0x00ffffffffffffffn`，否则 TBI 下超出 `MAX_SAFE_INTEGER` 会抛错）；
这个去标签后的数字又原样回到原生所有权手里，`ot_context_destroy` / `yogaNodeFree`
对它的 `free()` 就撞上 bionic 的 `MaybeUntagAndCheckPointer`：

```
Pointer tag for 0x7bdd4b6070 was truncated, see 'https://source.android.com/devices/tech/debug/tagged-pointers'.
Aborted
```

所以 TUI 能画出来，几秒后才死（打开 `Ctrl+P` 会创建并销毁 renderable，最快复现）。
注意这**不是**「OpenTUI 的 bug」：没有 pointer 补丁时 `toSafeNumberPointer` 会抛
`POINTER_UNSAFE`，是全进程 abort 换成了一个 JS 错误——两个补丁必须一起看。

为什么在设备上必现、在 CI 里看不到：

- bionic 的默认是 `M_HEAP_TAGGING_LEVEL_NONE`（`libc/bionic/heap_tagging.cpp`），
  真正打开它的是 init/zygote，Android 14（targetSdk 34）起对应用默认开启。
  进程从那个父进程继承了 `initial_heap_tagging_level`，所以设备上的 OpenCode
  一开始就带标签。
- `termux-docker` 里**也是 Bionic**，但没有 init/zygote，级别停在默认的 `NONE`，
  所以 verify 阶段碰不到这条路径。
- 同一台设备上 Bun 1.2.13 的 `malloc` 返回 `0x7ef1e5f580`（它自己关了），
  而 `bun-linux-aarch64-android` 1.4.4 返回 `0xb400007c763f3940`——学会了不关。

因此 `patches/opencode-0004-heap-tagging-off.patch` 把这一步要回来：在
`packages/cli/src/index.ts` 导入之后调用
`mallopt(M_BIONIC_SET_HEAP_TAGGING_LEVEL, M_HEAP_TAGGING_LEVEL_NONE)`。这是 bionic
官方 opt-out，且对已经带标签的指针安全：`tests/heap_tagging_level_test.cpp` 专门
验证「切换后释放被抹掉标签的指针」是正常的。它对 `opencode serve` 同样生效。

两处容易写错的细节：

- `M_BIONIC_SET_HEAP_TAGGING_LEVEL` 是 **-204**（不是 -4），`M_HEAP_TAGGING_LEVEL_NONE` 是 0。
- **这个调用不能加 `process.platform` 判断。** `bun build --compile` 按**构建机**把该常量
  写死，而构建走的是宿主 glibc Bun（`scripts/compile.sh`），打包进去的永远是 `"linux"`。
  任何平台判断在这里都是编译期 `false`，`minify` 会把整块连同 `bun:ffi` 一起删掉，
  修复会从发布物里静默消失。所以调用无条件执行，靠 `try/catch` 吸收
  `dlopen("libc.so")` 抛错的非 Bionic libc。

代价：`M_HEAP_TAGGING_LEVEL_NONE` 不可逆，并且会顺带关掉 Scudo 的 MTE 检查（如果进程
本来有）。这是有意接受的——另一条路是改 OpenTUI 的指针路线（保留 BigInt 指针），
在设备上未经验证。写在这里，而不是让它变成后来的猜测。

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
