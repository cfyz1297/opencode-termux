# opencode-termux

Official [OpenCode](https://github.com/anomalyco/opencode) 2 running natively in Termux.

Built from OpenCode sources with every native component rebuilt for Bionic; the result is loaded directly by the Android linker — no glibc, no proot, no compatibility layer.

[![build](https://github.com/cfyz1297/opencode-termux/actions/workflows/build.yml/badge.svg)](https://github.com/cfyz1297/opencode-termux/actions/workflows/build.yml)
[![release](https://img.shields.io/github/v/release/cfyz1297/opencode-termux?display_name=tag&sort=semver)](https://github.com/cfyz1297/opencode-termux/releases/latest)

English · [Русский](#русский)

## English

### Installation

Requirements: AArch64, Android 9 (API 28) or newer.

```bash
curl -fsSL https://raw.githubusercontent.com/cfyz1297/opencode-termux/main/install.sh | bash
```

The installer downloads the latest release, verifies its SHA-256 and installs it to `$PREFIX/bin/opencode`; if that exact build is already there, nothing is downloaded again.

Installing a specific version:

```bash
curl -fsSL https://raw.githubusercontent.com/cfyz1297/opencode-termux/main/install.sh | VERSION=2.2.5 bash
```

`VERSION=X.Y.Z` installs the newest build of that version, `VERSION=X.Y.Z-rN` that exact build.

You can also download manually from [GitHub Releases](https://github.com/cfyz1297/opencode-termux/releases).

### Updating

```bash
opencode upgrade   # `opencode update` works too
```

Upgrades use this repository's releases, which are verified in the Bionic CI, not the official builds. Re-running the install command updates as well.

When the same OpenCode version is published again because the toolchain changed (a new Bun base, for example), the tag becomes `vX.Y.Z-rN`. `upgrade` compares the binary hash, so it recognises those republishes too.

### Upgrading from OpenCode 1

This project followed upstream to OpenCode 2 and no longer publishes OpenCode 1. If 1.x is installed, run `opencode upgrade` (for 1.18.32 and older, re-run the install command). On first start OpenCode 2 migrates 1.x sessions and login credentials; the configuration format changed, see the [OpenCode 2 documentation](https://opencode.ai/v2/docs).

### Mobile client

[cfyz1297/opencode-mobile](https://github.com/cfyz1297/opencode-mobile) is the Android client for the server this project installs: an Expo/React Native app on OpenCode API V2 with live SSE streaming, sessions, models, offline history, a tablet layout and Cloudflare/ngrok tunnel wizard. Point it at `opencode serve --hostname 0.0.0.0 --port 4096` running here; the app's README covers the connection (`opencode:<password>` Basic auth).

### How it works

The build starts from the sources of the OpenCode release tag and follows upstream's Linux build: its `script/build.ts` runs on a glibc AArch64 host, except that the executable embeds the official Android build of Bun instead of the glibc one.

```text
OpenCode vX.Y.Z sources
        │ Android patches (patches/opencode-NNNN-*.patch)
        │ bun install
        │ swap in native components built from source (Bionic libraries, static opencode-pty)
        ▼
bun build --compile (glibc host, embeds the official Android Bun)
        │ acceptance run inside Termux
        ▼
   dist/opencode
```

The build cannot run inside Termux: the Android Bun reports `process.platform` as `android`, which OpenTUI, FFF and `@parcel/watcher` do not know. See the [architecture notes](docs/architecture.md).

Versions of the native components and of Bun are not pinned in this repository, they follow OpenCode's own `bun.lock` and `package.json`: when upstream bumps a dependency such as OpenTUI, the build compiles that version from source automatically (GitHub sources fetched by commit, npm packages checked against the lockfile integrity, Bun against the release `SHASUMS256.txt`) with no manual version edits. Patches are applied at fuzz 0: if an upstream change breaks a patch, the build fails instead of shipping an unverified binary.

### Android 17 and tagged heap pointers

Android 17 tags heap pointers in the top byte (TBI). OpenTUI converts the context pointer from `ot_context_create` into a JS number and throws `Pointer exceeds safe integer range` once the tagged value is above `Number.MAX_SAFE_INTEGER`, so the TUI never starts. Rebuilding the native library does not help: the check lives in OpenTUI's JavaScript, and it is the same in 0.7.x. The build masks the tag (`scripts/patch-opentui-pointer.mjs`, see [native assets](docs/native-assets.md#opentui-pointer-boundary)).

If `opencode` exits with that message on such a device, the installed build predates the fix: re-run the install command, or run `opencode upgrade`.

### CI


GitHub Actions builds on ARM64 runners, and every Bionic step runs inside the official Termux Docker image:

- pull requests: regression tests for the tooling, installer, release flow and patch helper;
- push to `main`: full build with acceptance, published when the latest version has no release yet;
- daily: check the latest official version and publish automatically once all tests pass;
- manual: build a given version; ticking `recut` republishes the same version after a toolchain change (`vX.Y.Z-rN`).

A build has three steps: native components compiled in Termux, OpenCode compiled from source on the runner, then acceptance back in Termux (`--version`, `update`, file search and a real TUI start). Details in the [CI documentation](docs/ci.md), [native component notes](docs/native-assets.md) and the [maintainer guide](docs/maintaining.md).

### Building from source

CI is recommended. A local build needs two environments:

```bash
# Termux: native components
make build-native

# glibc AArch64 Linux (ARM64 server, or Ubuntu in proot-distro), same repository directory
make fetch-source VERSION=2.2.5
make compile

# Termux: acceptance, leaves dist/opencode
make verify
```

The Termux side needs `clang`, `proot-distro`, `ndk-multilib`, `ndk-multilib-native-static`, `curl`, `patch` and Python; Rust/Zig Android cross-compilation goes through Ubuntu in proot. The OpenCode build side needs Node.js 22+, Python, `patch` and a C/C++ compiler (used by upstream dependency install scripts through node-gyp).

Third-party components and their licences are listed in [THIRD_PARTY.md](THIRD_PARTY.md).

## Русский

Официальный [OpenCode](https://github.com/anomalyco/opencode) 2, работающий в Termux нативно.

Собирается из исходников OpenCode, все нативные компоненты пересобраны под Bionic, готовый бинарь загружается Android-линкером напрямую — без glibc, proot и прочих слоёв совместимости.

### Установка

Требования: AArch64, Android 9 (API 28) и новее.

```bash
curl -fsSL https://raw.githubusercontent.com/cfyz1297/opencode-termux/main/install.sh | bash
```

Установщик скачивает последний релиз, проверяет SHA-256 и ставит в `$PREFIX/bin/opencode`; если установлен уже этот же бинарь, повторно ничего не качается.

Установка конкретной версии:

```bash
curl -fsSL https://raw.githubusercontent.com/cfyz1297/opencode-termux/main/install.sh | VERSION=2.2.5 bash
```

`VERSION=X.Y.Z` — последняя сборка этой версии, `VERSION=X.Y.Z-rN` — точно указанная сборка.

Можно также скачать вручную со страницы [GitHub Releases](https://github.com/cfyz1297/opencode-termux/releases).

### Обновление

```bash
opencode upgrade   # можно и `opencode update`
```

Обновление берёт релизы этого репозитория, прошедшие проверку в Bionic CI, а не официальные сборки. Повторный запуск команды установки тоже обновляет.

Когда та же версия OpenCode публикуется заново из-за изменений в инструментарии (например, новой базы Bun), тег получает вид `vX.Y.Z-rN`. `upgrade` сравнивает хеш бинаря, поэтому такие переиздания тоже распознаёт.

### Переход с OpenCode 1

Проект перешёл на OpenCode 2 вслед за апстримом и OpenCode 1 больше не публикует. Если установлен 1.x, достаточно выполнить `opencode upgrade` (для 1.18.32 и старше — заново запустить команду установки). При первом запуске OpenCode 2 переносит сессии и учётные данные 1.x; формат конфигурации изменился, см. [документацию OpenCode 2](https://opencode.ai/v2/docs).

### Мобильный клиент

[cfyz1297/opencode-mobile](https://github.com/cfyz1297/opencode-mobile) — Android-клиент к тому серверу, который ставит этот проект: приложение на Expo/React Native под OpenCode API V2, с живым потоком по SSE, сессиями, моделями, офлайн-историей, планшетной раскладкой и мастером туннелей Cloudflare/ngrok. Подключается к `opencode serve --hostname 0.0.0.0 --port 4096`, запущенному здесь; как именно — описано в README приложения (Basic-аутентификация `opencode:<пароль>`).

### Как это устроено

Сборка идёт из исходников release-тега OpenCode так же, как у апстрима собирается Linux-версия: на glibc-хосте AArch64 запускается его `script/build.ts`; отличие в том, что в исполняемый файл встраивается официальный Android-сборка Bun, а не glibc-версия.

```text
исходники OpenCode vX.Y.Z
        │ Android-патчи (patches/opencode-NNNN-*.patch)
        │ bun install
        │ подмена нативных компонентов на собранные из исходников (Bionic, статический opencode-pty)
        ▼
bun build --compile (glibc-хост, встраивается официальный Android Bun)
        │ проверка запуском в Termux
        ▼
   dist/opencode
```

Собирать внутри Termux нельзя: Android-сборка Bun при упаковке задаёт `process.platform` как `android`, а OpenTUI, FFF и `@parcel/watcher` этот платформы не знают. Подробнее — в [описании архитектуры](docs/architecture.md).

Версии нативных компонентов и Bun не зафиксированы в этом репозитории, а берутся из `bun.lock` и `package.json` самого OpenCode: когда апстрим обновляет OpenTUI или другой зависимый пакет, сборка автоматически компилирует соответствующую версию из исходников (исходники GitHub скачиваются по commit, npm-пакеты сверяются с integrity из lockfile, Bun — с `SHASUMS256.txt` релиза), без ручной правки номеров версий. Патчи применяются с fuzz 0: если изменения апстрима ломают патч, сборка падает, а не выпускает непроверенный файл.

### Android 17 и тегированные указатели

Android 17 тегирует указатели кучи в старшем байте (TBI). OpenTUI конвертирует указатель контекста из `ot_context_create` в JS-number и, когда тегированное значение больше `Number.MAX_SAFE_INTEGER`, бросает `Pointer exceeds safe integer range` — TUI не стартует. Пересборка нативной библиотеки не помогает: проверка живёт в JavaScript OpenTUI и в 0.7.x она та же. Сборка срезает тег (`scripts/patch-opentui-pointer.mjs`, см. [нативные компоненты](docs/native-assets.md#opentui-pointer-boundary)).

Если `opencode` завершается с этим сообщением на таком устройстве, установленная сборка старше исправления: перезапустите команду установки или `opencode upgrade`.

### CI


GitHub Actions собирает на ARM64-раннере, часть с Bionic выполняется в официальном Docker-образе Termux:

- PR: регрессионные тесты инструментов, установщика, публикации и утилит для патчей;
- пуш в `main`: полная сборка с приёмкой; публикация, если для последней версии ещё нет релиза;
- ежедневно: проверка последней официальной версии и автоматическая публикация после прохождения всех тестов;
- вручную: сборка указанной версии; с флагом `recut` — переиздание той же версии после изменений в инструментарии (`vX.Y.Z-rN`).

Сборка идёт в три шага: компиляция нативных компонентов в Termux, компиляция OpenCode из исходников на раннере, затем приёмка в Termux (`--version`, `update`, поиск по файлам и реальный запуск TUI). Подробности — в [документации CI](docs/ci.md), [описании нативных компонентов](docs/native-assets.md) и [руководстве по сопровождению](docs/maintaining.md).

### Сборка из исходников

Рекомендуется использовать CI. Для локальной сборки нужны два окружения:

```bash
# Termux: нативные компоненты
make build-native

# glibc AArch64 Linux (ARM64-сервер или Ubuntu в proot-distro), тот же каталог репозитория
make fetch-source VERSION=2.2.5
make compile

# Termux: приёмка, после неё получается dist/opencode
make verify
```

На стороне Termux нужны `clang`, `proot-distro`, `ndk-multilib`, `ndk-multilib-native-static`, `curl`, `patch` и Python; кросс-компиляция Rust/Zig под Android идёт через Ubuntu в proot. На стороне сборки OpenCode нужны Node.js 22+, Python, `patch` и компилятор C/C++ (его используют установочные скрипты зависимостей апстрима через node-gyp).

Сторонние компоненты и их лицензии — в [THIRD_PARTY.md](THIRD_PARTY.md).
