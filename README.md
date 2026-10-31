# opencode-termux

让官方 [OpenCode](https://github.com/anomalyco/opencode) 2 在 Termux 原生运行。

从 OpenCode 源码编译，原生组件也全部从源码重建为 Bionic 版本，最终产物由 Android linker 直接加载，无需 glibc、proot 或其他兼容层。

[![build](https://github.com/wmdhs12138/opencode-termux/actions/workflows/build.yml/badge.svg)](https://github.com/wmdhs12138/opencode-termux/actions/workflows/build.yml)
[![release](https://img.shields.io/github/v/release/wmdhs12138/opencode-termux?display_name=tag&sort=semver)](https://github.com/wmdhs12138/opencode-termux/releases/latest)

## 安装

要求：AArch64、Android 9（API 28）或更高版本。

```bash
curl -fsSL https://raw.githubusercontent.com/wmdhs12138/opencode-termux/main/install.sh | bash
```

安装器会下载最新 Release、校验 SHA-256，并安装到 `$PREFIX/bin/opencode`；已装的就是这个构建时不重复下载。

安装指定版本：

```bash
curl -fsSL https://raw.githubusercontent.com/wmdhs12138/opencode-termux/main/install.sh | VERSION=2.0.28 bash
```

`VERSION=X.Y.Z` 安装该版本最新的一次构建，`VERSION=X.Y.Z-rN` 安装指定的那一次。

也可以从 [GitHub Releases](https://github.com/wmdhs12138/opencode-termux/releases) 手动下载。

## 更新

```bash
opencode upgrade   # 也可以写成 opencode update
```

使用本项目经过 Bionic CI 验证的 Release，不会下载官方版本。重复运行安装命令也可以完成更新。

同一 OpenCode 版本因构建工具链更新（例如 Bun 底座）重新发布时，tag 是 `vX.Y.Z-rN`。`upgrade` 按二进制哈希判断，能识别这种重新发布。

### 从 OpenCode 1 升级

本项目已跟随上游切换到 OpenCode 2，不再发布 OpenCode 1。已安装 1.x 的直接运行 `opencode upgrade`（1.18.32 及更早的版本请重新运行一次安装命令）。OpenCode 2 首次启动时会迁移 1.x 的会话和登录凭据；配置格式有变化，见 [OpenCode 2 文档](https://opencode.ai/v2/docs)。

## 实现

从 OpenCode 的 release tag 源码编译，方式与上游发布 Linux 版相同：在 glibc AArch64 主机上执行上游的 `script/build.ts`；区别是可执行文件嵌入的是官方 Android 版 Bun，而不是 glibc 版。

```text
OpenCode vX.Y.Z 源码
        │ Android 补丁（patches/opencode-NNNN-*.patch）
        │ bun install
        │ 换入从源码编译的原生组件（Bionic 库，静态 opencode-pty）
        ▼
bun build --compile（glibc 主机，嵌入官方 Android Bun）
        │ 在 Termux 里运行验收
        ▼
   dist/opencode
```

编译不能放在 Termux 里做：Android 版 Bun 打包时把 `process.platform` 定为 `android`，OpenTUI、FFF 和 `@parcel/watcher` 都不认这个平台。详见 [架构说明](docs/architecture.md)。

原生组件和 Bun 的版本不在本仓库写死，而是跟着 OpenCode 自己的 `bun.lock` 和 `package.json` 走：OpenCode 升级 OpenTUI 之类的依赖时，构建自动从对应版本的源码编译（GitHub 源码按 commit 下载，npm 包对照 lockfile 的 integrity，Bun 对照 Release 的 `SHASUMS256.txt`），不需要人工改版本号。补丁按 fuzz 0 应用；上游改动导致补丁打不上时，构建会直接失败，而不是产出未经验证的文件。

## CI

GitHub Actions 在 ARM64 runner 上完成构建，Bionic 部分都在官方 Termux Docker 环境里：

- PR：运行工具、安装器、发布流程与补丁工具的回归测试；
- 推送至 `main`：完整构建与验收；最新版还没有 Release 时自动发布；
- 每天：检查官方最新版，通过全部测试后自动发布；
- 手动运行：构建指定版本；勾选 `recut` 在工具链变化后重新发布同一版本（`vX.Y.Z-rN`）。

一次构建分三步：Termux 里编译原生组件，runner 上从源码编译 OpenCode，再回到 Termux 里运行验收（`--version`、`update`、文件搜索和真实 TUI 启动）。详见 [CI 文档](docs/ci.md)、[原生组件说明](docs/native-assets.md) 和 [维护手册](docs/maintaining.md)。

## 从源码构建

推荐直接用 CI。本地要分两种环境：

```bash
# Termux：原生组件
make build-native

# glibc AArch64 Linux（ARM64 服务器，或 proot-distro 里的 Ubuntu），同一个仓库目录
make fetch-source VERSION=2.0.28
make compile

# Termux：验收，通过后得到 dist/opencode
make verify
```

Termux 侧需要 `clang`、`proot-distro`、`ndk-multilib`、`ndk-multilib-native-static`、`curl`、`patch` 和 Python，Rust/Zig 的 Android 交叉编译使用 proot 里的 Ubuntu。编译 OpenCode 的一侧需要 Node.js 22+、Python、`patch` 和 C/C++ 编译器（上游依赖的安装脚本会用到 node-gyp）。

第三方组件及许可见 [THIRD_PARTY.md](THIRD_PARTY.md)。
