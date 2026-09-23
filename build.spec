# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec для Zapret Manager.

Собирает onedir-билд (папка с exe и зависимостями) — это надёжнее, быстрее
стартует и не блокируется антивирусами так агрессивно, как onefile.

Собирается командой:
    pyinstaller build.spec
Результат в dist/ZapretManager/.
"""

import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Иконка — если положишь app/assets/icon.ico, она автоматически подхватится.
icon_path = "app/assets/icon.ico"
icon = icon_path if os.path.exists(icon_path) else None

# Данные customtkinter (JSON-темы, шрифты)
ctk_data = collect_data_files("customtkinter")
ctk_hidden = collect_submodules("customtkinter")

# Данные certifi — корневые сертификаты для HTTPS.
# Без них в собранном .exe не работает проверка SSL → ошибка
# certificate verify failed при обращении к api.github.com.
certifi_data = collect_data_files("certifi")

a = Analysis(
    ["app/main.py"],
    pathex=["."],
    binaries=[],
    datas=ctk_data + certifi_data + [
        ("app/assets", "app/assets"),
    ],
    hiddenimports=ctk_hidden + ["PIL._tkinter_finder"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Отрезаем всё, что не используем — сильно уменьшает размер билда.
    excludes=[
        "matplotlib", "numpy", "scipy", "pandas",
        "PyQt5", "PyQt6", "PySide2", "PySide6",
        "wx", "IPython", "jupyter", "notebook",
        "pytest", "unittest",
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
    name="ZapretManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,             # UPX иногда триггерит антивирусы, отключаем
    console=False,         # без окна консоли
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ZapretManager",
)