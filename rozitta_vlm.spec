# -*- mode: python ; coding: utf-8 -*-
"""
rozitta_vlm.spec — сборка компонента «Распознавание изображений».

    pyinstaller rozitta_vlm.spec --noconfirm

Собирается onedir, а НЕ onefile (COMPONENTS.md §2): меньше ложных
срабатываний антивирусов и нет распаковки в %TEMP% при каждом запуске.
Компонент зовут пачками по несколько сотен картинок — распаковывать
полсотни мегабайт на каждый запуск незачем.

Что НЕ входит в сборку:

  * приложение Розитты — компонент не импортирует ни core/, ни features/,
    ни Qt; это закреплено тестом test_component_does_not_import_the_app;
  * бинарники llama.cpp — их кладёт рядом workflow, качая из релизов
    ggml-org: пересобирать их незачем, а версию видно по имени папки;
  * веса модели — они едут отдельными файлами релиза, потому что у GitHub
    предел 2 ГиБ на файл (§3.1.1).

Итог — десятки мегабайт: Python, Pillow и наш код. Всё тяжёлое лежит
рядом и обновляется независимо.
"""

import os

block_cipher = None

REPO_ROOT = os.path.abspath(os.getcwd())

a = Analysis(
    ["component_vlm/entry.py"],
    pathex=[REPO_ROOT],
    binaries=[],
    datas=[],
    hiddenimports=[
        # Pillow подтягивает плагины форматов динамически — без явного
        # указания PyInstaller их не находит, и компонент падает на первом
        # же JPEG с «cannot identify image file».
        "PIL._imaging",
        "PIL.JpegImagePlugin",
        "PIL.PngImagePlugin",
        "PIL.WebPImagePlugin",
        "PIL.BmpImagePlugin",
        "PIL.GifImagePlugin",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Явно выбрасываем всё, что могло приехать транзитивно. Список — не
    # перестраховка: он ловит случай, когда кто-то добавит в компонент
    # импорт из приложения и не заметит, что сборка выросла втрое.
    excludes=[
        "PySide6", "PyQt5", "PyQt6", "shiboken6",
        "telethon", "docx", "frontmatter",
        "core", "features", "ui", "config",
        "tkinter", "matplotlib", "numpy", "scipy", "pandas",
        "torch", "transformers",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RozittaVLM",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX ломает подпись и злит антивирусы
    console=True,       # компонент общается через stdout/stderr (§4)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="RozittaVLM",
)
