#!/usr/bin/env python3
"""Generate concise GitHub release notes from the Bionic build manifest.

  release_notes.py <out.md> --manifest M --tag vX.Y.Z[-rN] --commit SHA
                            --predecessor TAG|- --changelog FILE
"""
import argparse
import json
import re

INSTALL = "curl -fsSL https://raw.githubusercontent.com/cfyz1297/opencode-termux/main/install.sh | bash"


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def release_notes(manifest, tag, commit, predecessor, changelog):
    m = manifest
    ver = m.get("opencode", "?")
    bun = m.get("base_bun") or {}
    source = m.get("source") or {}
    names = {"opentui": "OpenTUI", "fff": "FFF", "watcher": "watcher", "rust_pty": "bun-pty",
             "opencode_pty": "opencode-pty"}
    natives = m.get("natives") or {}
    components = " · ".join(f"{label} {natives[key]['version']}" for key, label in names.items()
                            if key in natives)
    accepted = (
        m.get("release_eligible") is True
        and m.get("tui_smoke") == "pass"
        and (m.get("native_assets") or {}).get("result") == "pass"
    )
    bad = ((m.get("release_eligible") is not True)
           or (m.get("tui_smoke") != "pass")
           or ((m.get("native_assets") or {}).get("result") != "pass"))
    if not bad:
        verification = {
            "en": ("Verified: built from the OpenCode sources; the Termux Bionic container ran the "
                   "native ELF audit, the FFF / watcher / PTY smoke tests and the real TUI launch."),
            "ru": ("Приёмка: собрано из исходников OpenCode; в контейнере Termux Bionic пройдены "
                   "ELF-аудит нативных компонентов, FFF / watcher / PTY smoke и запуск настоящего TUI."),
            "zh": ("验收：从 OpenCode 源码编译；Termux Bionic 容器内原生组件 ELF 审计、"
                   "FFF / watcher / PTY 冒烟和真实 TUI 启动全部通过。"),
        }
    else:
        verification = {
            "en": "⚠️ The Bionic acceptance run did not complete.",
            "ru": "⚠️ Приёмка Bionic не завершена.",
            "zh": "⚠️ 未完成 Bionic 运行验收。",
        }

    what = {"en": "", "ru": "", "zh": ""}
    recut = re.search(r"-r(\d+)$", tag)
    if recut:
        what = {
            "en": (f"\nRe-cut {recut.group(1)} of {ver}: the OpenCode version is the same, the build "
                   "toolchain is newer. `opencode upgrade` compares the binary hash and installs it; "
                   "the old build's own `opencode upgrade` skips the same version, so run the install "
                   "command below once.\n"),
            "ru": (f"\nЭто {recut.group(1)}-я пересборка {ver}: версия OpenCode та же, инструментальный "
                   "набор обновлён. `opencode upgrade` сравнивает хэш бинаря и установит сборку; "
                   "старый сборочный `opencode upgrade` ту же версию пропустит — один раз запустите "
                   "команду установки ниже.\n"),
            "zh": (f"\n这是 {ver} 的第 {recut.group(1)} 次重新发布：OpenCode 版本不变,构建工具有更新。"
                   "`opencode upgrade` 按二进制哈希判断，会识别并安装；旧版本自带的 `opencode upgrade` "
                   "会跳过同一版本，请重新运行一次下面的安装命令。\n"),
        }
    if predecessor and predecessor != "-":
        scope = {
            "en": f"Toolchain changes since `{predecessor}`:",
            "ru": f"Инструментальные изменения относительно `{predecessor}`:",
            "zh": f"相对 `{predecessor}` 的工具链变更：",
        }
    else:
        scope = {
            "en": "Toolchain changes:",
            "ru": "Инструментальные изменения:",
            "zh": "工具链变更：",
        }

    install = {
        "en": f"Install or update:\n\n```bash\n{INSTALL}\n```\n\nAlready installed: run `opencode upgrade`.",
        "ru": f"Установка или обновление:\n\n```bash\n{INSTALL}\n```\n\nУже установленным достаточно `opencode upgrade`.",
        "zh": f"安装或更新：\n\n```bash\n{INSTALL}\n```\n\n已安装的可运行 `opencode upgrade`。",
    }
    blank = {"en": "## English", "ru": "## Русский", "zh": "## 中文"}

    table = f"""## Build

| Field | Value |
|---|---|
| OpenCode source | `{source.get("tag", "?")}` · `{source.get("commit", "?")[:12]}` |
| opencode binary SHA-256 | `{m.get("output_sha256", "?")}` |
| Bun base | `{bun.get("version", "?")}` |
| Native components (from OpenCode's bun.lock) | {components or "?"} |
| Toolchain commit | `{commit[:12] or "?"}` |
"""

    return f"""# OpenCode {ver} · Termux

{blank['en']}

{verification['en']}
{what['en']}
{install['en']}

{blank['ru']}

{verification['ru']}
{what['ru']}
{install['ru']}

{blank['zh']}

{verification['zh']}
{what['zh']}
{install['zh']}

{table}
{scope['en']} / {scope['ru']} / {scope['zh']}

{changelog.strip() or "-"}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--commit", required=True)
    ap.add_argument("--predecessor", default="-")
    ap.add_argument("--changelog", required=True)
    a = ap.parse_args()

    try:
        with open(a.changelog, encoding="utf-8") as f:
            changelog = f.read()
    except OSError:
        changelog = ""
    notes = release_notes(load(a.manifest), a.tag, a.commit, a.predecessor, changelog)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(notes)
    print(f"wrote {a.out} ({len(notes)} bytes)")


if __name__ == "__main__":
    main()
