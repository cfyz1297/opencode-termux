# opencode-termux

Официальный [OpenCode](https://github.com/anomalyco/opencode) 2, работающий в Termux нативно.

Собирается из исходников OpenCode, все нативные компоненты пересобраны под Bionic, готовый бинарь загружается Android-линкером напрямую — без glibc, proot и прочих слоёв совместимости.

[![build](https://github.com/cfyz1297/opencode-termux/actions/workflows/build.yml/badge.svg)](https://github.com/cfyz1297/opencode-termux/actions/workflows/build.yml)
[![release](https://img.shields.io/github/v/release/cfyz1297/opencode-termux?display_name=tag&sort=semver)](https://github.com/cfyz1297/opencode-termux/releases/latest)

## Установка

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

## Обновление

```bash
opencode upgrade   # можно и `opencode update`
```

Обновление берёт релизы этого репозитория, прошедшие проверку в Bionic CI, а не официальные сборки. Повторный запуск команды установки тоже обновляет.

Когда та же версия OpenCode публикуется заново из-за изменений в инструментарии (например, новой базы Bun), тег получает вид `vX.Y.Z-rN`. `upgrade` сравнивает хеш бинаря, поэтому такие переиздания тоже распознаёт.

### Переход с OpenCode 1

Проект перешёл на OpenCode 2 вслед за апстримом и OpenCode 1 больше не публикует. Если установлен 1.x, достаточно выполнить `opencode upgrade` (для 1.18.32 и старше — заново запустить команду установки). При первом запуске OpenCode 2 переносит сессии и учётные данные 1.x; формат конфигурации изменился, см. [документацию OpenCode 2](https://opencode.ai/v2/docs).

## Как это устроено

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

## CI

GitHub Actions собирает на ARM64-раннере, часть с Bionic выполняется в официальном Docker-образе Termux:

- PR: регрессионные тесты инструментов, установщика, публикации и утилит для патчей;
- пуш в `main`: полная сборка с приёмкой; публикация, если для последней версии ещё нет релиза;
- ежедневно: проверка последней официальной версии и автоматическая публикация после прохождения всех тестов;
- вручную: сборка указанной версии; с флагом `recut` — переиздание той же версии после изменений в инструментарии (`vX.Y.Z-rN`).

Сборка идёт в три шага: компиляция нативных компонентов в Termux, компиляция OpenCode из исходников на раннере, затем приёмка в Termux (`--version`, `update`, поиск по файлам и реальный запуск TUI). Подробности — в [документации CI](docs/ci.md), [описании нативных компонентов](docs/native-assets.md) и [руководстве по сопровождению](docs/maintaining.md).

## Сборка из исходников

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
