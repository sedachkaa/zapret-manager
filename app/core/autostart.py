"""
Управление автозапуском Zapret Manager вместе с Windows.

Использует ветку реестра HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run,
поэтому не требует прав администратора.

Для двух сценариев запуска:
    - Из собранного .exe (PyInstaller): в реестр пишется путь к этому .exe.
    - Из исходников: создаётся вспомогательный autostart.bat в корне проекта,
      который запускает pythonw.exe -m app.main; в реестр пишется путь к bat.

pythonw.exe запускается без окна консоли — пользователь не увидит лишних окон.
"""

from __future__ import annotations

import sys
from pathlib import Path

from app.core.config import PROJECT_ROOT

# winreg доступен только на Windows
try:
    import winreg  # type: ignore
except ImportError:  # pragma: no cover
    winreg = None  # type: ignore


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "ZapretManager"
AUTOSTART_BAT = PROJECT_ROOT / "autostart.bat"


# --- Внутренние утилиты --------------------------------------------------

def _is_supported() -> bool:
    """True, если ОС поддерживает автозапуск через реестр (Windows)."""
    return winreg is not None


def _build_launch_command() -> str | None:
    """
    Возвращает строку-команду для реестра.
    - .exe (PyInstaller): "C:\\path\\to\\app.exe"
    - исходники: "C:\\path\\to\\autostart.bat"
    None — если подготовка не удалась.
    """
    # 1. Собранный PyInstaller .exe
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'

    # 2. Исходники — создаём bat-обёртку
    python_exe = Path(sys.executable)
    # pythonw.exe — тот же интерпретатор, но без окна консоли
    pythonw = python_exe.with_name("pythonw.exe")
    if not pythonw.exists():
        pythonw = python_exe  # fallback

    content = (
        "@echo off\r\n"
        f'cd /d "{PROJECT_ROOT}"\r\n'
        f'start "" /min "{pythonw}" -m app.main\r\n'
    )

    try:
        AUTOSTART_BAT.write_text(content, encoding="cp866")
    except OSError as e:
        print(f"[autostart] не удалось создать {AUTOSTART_BAT}: {e}")
        return None

    return f'"{AUTOSTART_BAT}"'


# --- Публичное API -------------------------------------------------------

def is_enabled() -> bool:
    """True, если автозапуск включён (есть запись в реестре)."""
    if not _is_supported():
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            try:
                winreg.QueryValueEx(key, APP_NAME)
                return True
            except FileNotFoundError:
                return False
    except OSError as e:
        print(f"[autostart] не удалось прочитать реестр: {e}")
        return False


def enable() -> bool:
    """Включает автозапуск. Возвращает True при успехе."""
    if not _is_supported():
        print("[autostart] автозапуск поддерживается только на Windows")
        return False

    command = _build_launch_command()
    if not command:
        return False

    try:
        # CREATE, чтобы не падать, если ключ отсутствует
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command)
        print(f"[autostart] включён: {command}")
        return True
    except OSError as e:
        print(f"[autostart] не удалось записать в реестр: {e}")
        return False


def disable() -> bool:
    """Выключает автозапуск и удаляет вспомогательный bat."""
    if not _is_supported():
        return False

    ok = True
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            try:
                winreg.DeleteValue(key, APP_NAME)
                print("[autostart] запись удалена из реестра")
            except FileNotFoundError:
                # Записи и не было — это не ошибка
                pass
    except OSError as e:
        print(f"[autostart] не удалось удалить запись: {e}")
        ok = False

    # Удаляем вспомогательный .bat, если он был
    try:
        if AUTOSTART_BAT.exists():
            AUTOSTART_BAT.unlink()
            print(f"[autostart] удалён {AUTOSTART_BAT}")
    except OSError as e:
        print(f"[autostart] не удалось удалить {AUTOSTART_BAT}: {e}")

    return ok


# --- Быстрый тест --------------------------------------------------------

if __name__ == "__main__":
    print("Поддерживается :", _is_supported())
    print("Включён сейчас :", is_enabled())
    print("Команда        :", _build_launch_command())