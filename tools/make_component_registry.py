# -*- coding: utf-8 -*-
"""
tools/make_component_registry.py — собирает components_registry.json.

    python tools/make_component_registry.py \
        --name vlm --version 1.0.0 --protocol 1 \
        --zip dist/RozittaVLM-win64-1.0.0.zip \
        --zip-url https://github.com/.../RozittaVLM-win64-1.0.0.zip \
        --weights-dir weights --weights-base https://github.com/.../ \
        --previous current_registry.json \
        --out components_registry.json

Зачем отдельный скрипт, а не полсотни строк в YAML: реестр — это контракт
между приложением и компонентом (COMPONENTS.md §3.1), и ошибка в нём даёт
неверный sha256, из-за которого установка отказывается работать у всех
разом. Такое хочется читать и править как код, а не как строку шелла.

**Про `--previous`.** Веса весят три гигабайта и меняются редко, сборка —
тридцать мегабайт и меняется часто. Поэтому обычный выпуск новой сборки
веса не пересобирает: их описание переносится из текущего реестра. Без
этого каждая правка бинарника означала бы перезалив трёх гигабайт.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import List, Optional


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def describe_file(path: Path, url: str) -> dict:
    return {
        "file":       path.name,
        "size_bytes": path.stat().st_size,
        "sha256":     sha256_of(path),
        "urls":       [url],
    }


def collect_weights(weights_dir: Optional[Path], base_url: str) -> List[dict]:
    """
    Описывает файлы весов из папки.

    Порядок в списке ни на что не влияет: менеджер качает все файлы, а
    воркер берёт нужный по имени из MODEL_FILES. Сортировка нужна только
    ради воспроизводимого вывода — чтобы два прогона на одних файлах дали
    побайтово одинаковый реестр и diff показывал настоящие изменения.

    (Первая версия комментария утверждала, что первый кусок обязан идти
    первым. Это было неправдой, и проверка её показала: на Windows пути
    сравниваются без учёта регистра, `mmproj-` встаёт раньше `Qwen…`, —
    а компонент от этого не сломался.)
    """
    if weights_dir is None:
        return []
    files = sorted(p for p in weights_dir.iterdir()
                   if p.is_file() and p.suffix == ".gguf")
    if not files:
        raise SystemExit(f"в {weights_dir} нет .gguf — нечего описывать")
    return [describe_file(p, base_url.rstrip("/") + "/" + p.name)
            for p in files]


def previous_weights(path: Optional[Path], name: str,
                     ) -> List[dict]:
    """
    Достаёт описание весов из прежнего реестра.

    Берётся из `latest`-версии: она и есть та, на которую сейчас смотрят
    установки. Если прежнего реестра нет или в нём нет весов — пусто, и
    вызывающий об этом узнает.
    """
    if path is None or not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"прежний реестр не читается: {exc}")

    entry = (data.get("components") or {}).get(name) or {}
    versions = entry.get("versions") or {}
    prev = versions.get(entry.get("latest")) or {}
    return list(prev.get("models") or [])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--protocol", type=int, default=1)
    ap.add_argument("--min-app-version", default="1.9.0")
    ap.add_argument("--zip", required=True, type=Path)
    ap.add_argument("--zip-url", required=True)
    ap.add_argument("--weights-dir", type=Path, default=None)
    ap.add_argument("--weights-base", default="")
    ap.add_argument("--previous", type=Path, default=None)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    if not args.zip.is_file():
        raise SystemExit(f"нет архива: {args.zip}")

    if args.weights_dir is not None:
        if not args.weights_base:
            raise SystemExit("--weights-dir задан без --weights-base")
        models = collect_weights(args.weights_dir, args.weights_base)
        source = "собраны заново"
    else:
        models = previous_weights(args.previous, args.name)
        source = "перенесены из прежнего реестра"

    if not models:
        # Не падаем: компонент без весов — законный случай (COMPONENTS.md
        # §3.1). Но если это vlm, о таком надо знать громко.
        print(f"!! внимание: у «{args.name}» нет описания весов",
              file=sys.stderr)

    registry = {
        "registry_version": 1,
        "components": {
            args.name: {
                "latest": args.version,
                "versions": {
                    args.version: {
                        "protocol":        args.protocol,
                        "min_app_version": args.min_app_version,
                        "size_bytes":      args.zip.stat().st_size,
                        "sha256":          sha256_of(args.zip),
                        "urls":            [args.zip_url],
                        **({"models": models} if models else {}),
                    }
                },
            }
        },
    }

    args.out.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")

    total = args.zip.stat().st_size + sum(m["size_bytes"] for m in models)
    print(f"реестр записан: {args.out}")
    print(f"  компонент {args.name} {args.version}, протокол {args.protocol}")
    print(f"  сборка: {args.zip.stat().st_size / 1e6:.0f} МБ")
    print(f"  веса: {len(models)} файлов, {source}")
    for m in models:
        print(f"    {m['size_bytes'] / 1e6:8.0f} МБ  {m['file']}")
    print(f"  всего к скачиванию: {total / 1e9:.2f} ГБ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
