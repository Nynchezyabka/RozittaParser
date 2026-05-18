#!/usr/bin/env python3
"""
tools/metrics.py — актуальные метрики качества кода Rozitta Parser.

Запускать из корня проекта:
    python tools/metrics.py

Требуемые зависимости (устанавливаются один раз):
    pip install radon pytest pytest-cov mypy

Что считает:
    1. Покрытие тестами        — pytest + pytest-cov
    2. Цикломатическая сложность — radon cc
    3. Дублирование кода        — radon raw (приблизительно)
    4. Типизация (type hints)   — mypy --ignore-missing-imports
"""

from __future__ import annotations

import subprocess
import sys
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC_DIRS = ["core", "features", "ui"]  # папки с исходниками

SEP = "─" * 60


def run(cmd: list[str], cwd: Path = ROOT) -> tuple[int, str]:
    result = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return result.returncode, result.stdout + result.stderr


def check_tool(name: str) -> bool:
    code, _ = run([sys.executable, "-m", name, "--version"])
    if code != 0:
        print(f"  ⚠️  {name} не установлен. Запустите: pip install {name}")
        return False
    return True


# ─────────────────────────────────────────────────────────────────────────────
# 1. Покрытие тестами
# ─────────────────────────────────────────────────────────────────────────────

def coverage() -> str:
    print(f"\n{SEP}")
    print("📊 1. ПОКРЫТИЕ ТЕСТАМИ (pytest --cov)")
    print(SEP)

    if not (ROOT / "tests").exists():
        print("  ⚠️  Папка tests/ не найдена")
        return "—"

    src_args = []
    for d in SRC_DIRS:
        if (ROOT / d).exists():
            src_args += ["--cov=" + d]

    code, out = run([
        sys.executable, "-m", "pytest",
        *src_args,
        "--cov-report=term-missing",
        "--cov-report=json:.coverage.json",
        "-q", "--tb=no",
        "tests/",
    ])

    # Итоговый процент из JSON-отчёта
    cov_json = ROOT / ".coverage.json"
    total = "—"
    if cov_json.exists():
        try:
            data = json.loads(cov_json.read_text(encoding="utf-8"))
            pct = data.get("totals", {}).get("percent_covered", None)
            if pct is not None:
                total = f"{pct:.1f}%"
                status = "✅" if pct >= 80 else ("🟡" if pct >= 50 else "🔴")
                print(f"\n  Итого: {total} {status}  (норма >80%)")
        except Exception:
            pass

    # Модули с низким покрытием
    print("\n  Модули ниже 50%:")
    if cov_json.exists():
        try:
            data = json.loads(cov_json.read_text(encoding="utf-8"))
            files = data.get("files", {})
            low = [
                (f, v["summary"]["percent_covered"])
                for f, v in files.items()
                if v["summary"]["percent_covered"] < 50
            ]
            low.sort(key=lambda x: x[1])
            if low:
                for f, p in low[:10]:
                    rel = Path(f).relative_to(ROOT) if Path(f).is_absolute() else Path(f)
                    print(f"    {p:5.1f}%  {rel}")
            else:
                print("    нет модулей ниже 50% 🎉")
        except Exception:
            pass

    return total


# ─────────────────────────────────────────────────────────────────────────────
# 2. Цикломатическая сложность
# ─────────────────────────────────────────────────────────────────────────────

def complexity() -> str:
    print(f"\n{SEP}")
    print("🔀 2. ЦИКЛОМАТИЧЕСКАЯ СЛОЖНОСТЬ (radon cc)")
    print(SEP)

    src_paths = [str(ROOT / d) for d in SRC_DIRS if (ROOT / d).exists()]
    code, out = run([sys.executable, "-m", "radon", "cc", *src_paths, "-a", "-s"])

    # Средняя сложность из последней строки вывода
    avg = "—"
    for line in out.splitlines():
        m = re.search(r"Average complexity: ([A-F]) \(([\d.]+)\)", line)
        if m:
            grade, value = m.group(1), float(m.group(2))
            avg = f"{value:.1f} ({grade})"
            status = "✅" if float(value) < 10 else "🔴"
            print(f"\n  Средняя: {avg} {status}  (норма <10)")

    # Функции с высокой сложностью (C и выше = >5)
    print("\n  Функции со сложностью C+ (>5):")
    high = [l for l in out.splitlines() if re.match(r"\s+[C-F] ", l)]
    if high:
        for line in high[:10]:
            print(f"   {line.strip()}")
    else:
        print("    нет функций со сложностью >5 🎉")

    return avg


# ─────────────────────────────────────────────────────────────────────────────
# 3. Объём и дублирование (приблизительно через radon raw + hal)
# ─────────────────────────────────────────────────────────────────────────────

def raw_stats() -> None:
    print(f"\n{SEP}")
    print("📏 3. ОБЪЁМ КОДА (radon raw)")
    print(SEP)

    src_paths = [str(ROOT / d) for d in SRC_DIRS if (ROOT / d).exists()]
    code, out = run([sys.executable, "-m", "radon", "raw", *src_paths, "-s"])

    # Итоговые строки
    for line in out.splitlines():
        if line.strip().startswith("Total"):
            print(f"  {line.strip()}")

    print("\n  (Для точного анализа дублирования используйте pylint --duplicate-code)")


# ─────────────────────────────────────────────────────────────────────────────
# 4. Типизация
# ─────────────────────────────────────────────────────────────────────────────

def type_hints() -> str:
    print(f"\n{SEP}")
    print("🔷 4. ТИПИЗАЦИЯ (mypy)")
    print(SEP)

    src_paths = [str(ROOT / d) for d in SRC_DIRS if (ROOT / d).exists()]
    code, out = run([
        sys.executable, "-m", "mypy",
        *src_paths,
        "--ignore-missing-imports",
        "--no-error-summary",
        "--pretty",
    ])

    errors = [l for l in out.splitlines() if ": error:" in l]
    notes  = [l for l in out.splitlines() if "Found" in l or "Success" in l]

    if notes:
        for n in notes:
            print(f"  {n.strip()}")

    if errors:
        print(f"\n  Первые 10 ошибок типизации:")
        for e in errors[:10]:
            # Сделать путь относительным для читаемости
            e = e.replace(str(ROOT) + "/", "").replace(str(ROOT) + "\\", "")
            print(f"    {e.strip()}")
        status = "🟡" if len(errors) < 20 else "🔴"
        print(f"\n  Всего ошибок: {len(errors)} {status}")
    else:
        print("  ✅ Ошибок типизации не найдено")

    return f"{len(errors)} ошибок"


# ─────────────────────────────────────────────────────────────────────────────
# Итоговая таблица
# ─────────────────────────────────────────────────────────────────────────────

def summary(cov: str, cx: str, mypy: str) -> None:
    print(f"\n{SEP}")
    print("📋 ИТОГОВАЯ ТАБЛИЦА ДЛЯ PROJECT_ANALYSIS.md")
    print(SEP)
    print()
    print("| Метрика                       | Значение  | Норма | Инструмент  |")
    print("|-------------------------------|-----------|-------|-------------|")
    print(f"| Покрытие тестами              | {cov:<9} | >80%  | pytest-cov  |")
    print(f"| Цикломатическая сложность avg | {cx:<9} | <10   | radon cc    |")
    print(f"| Типизация (mypy ошибок)       | {mypy:<9} | 0     | mypy        |")
    print()
    print("Скопируйте таблицу в PROJECT_ANALYSIS.md → раздел 8.")


# ─────────────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    print("🔍 Rozitta Parser — метрики качества кода")
    print(f"   Корень проекта: {ROOT}")

    missing = []
    for tool in ["radon", "pytest", "mypy"]:
        if not check_tool(tool):
            missing.append(tool)

    if missing:
        print(f"\n❌ Установите недостающие инструменты:")
        print(f"   pip install {' '.join(missing)}")
        sys.exit(1)

    cov  = coverage()
    cx   = complexity()
    raw_stats()
    mypy = type_hints()
    summary(cov, cx, mypy)


if __name__ == "__main__":
    main()
