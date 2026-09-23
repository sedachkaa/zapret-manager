"""
Создание/удаление ярлыка Zapret Manager на рабочем столе.

Использует PowerShell и COM-объект WScript.Shell — это стандартный
способ создания .lnk-файлов в Windows без сторонних зависимостей.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from app.core.config import APP_INSTALL_DIR


SHORTCUT_NAME = "Zapret Manager.lnk"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def _desktop_dir() -> Path | None:
    """Путь к рабочему столу пользователя."""
    profile = os.environ.get("USERPROFILE")
    if profile:
        d = Path(profile) / "Desktop"
        if d.exists():
            return d
    # OneDrive-вариант рабочего стола
    onedrive = os.environ.get("OneDrive")
    if onedrive:
        d = Path(onedrive) / "Desktop"
        if d.exists():
            return d
    # Публичный рабочий стол (запасной вариант)
    public = os.environ.get("PUBLIC")
    if public:
        d = Path(public) / "Desktop"
        if d.exists():
            return d
    return None


def shortcut_path() -> Path | None:
    """Полный путь к ярлыку на рабочем столе (или None, если стол не найден)."""
    d = _desktop_dir()
    if d is None:
        return None
    return d / SHORTCUT_NAME


def is_exists() -> bool:
    """True, если ярлык уже есть на рабочем столе."""
    p = shortcut_path()
    return bool(p and p.exists())


def _target_exe() -> Path:
    """Что должно запускать ярлык."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    # Из исходников ярлык не имеет смысла, но вернём корень проекта — на случай теста
    return APP_INSTALL_DIR


def create() -> tuple[bool, str]:
    """
    Создаёт ярлык. Возвращает (успех, сообщение).
    """
    sp = shortcut_path()
    if sp is None:
        return False, "рабочий стол не найден"

    target = _target_exe()
    if not target.exists():
        return False, f"исполняемый файл не найден: {target}"

    # Экранируем одинарные кавычки для PowerShell (путей с ' быть не должно, но на всякий)
    def ps_quote(s: str) -> str:
        return s.replace("'", "''")

    ps_script = (
        f"$ws = New-Object -ComObject WScript.Shell; "
        f"$sc = $ws.CreateShortcut('{ps_quote(str(sp))}'); "
        f"$sc.TargetPath = '{ps_quote(str(target))}'; "
        f"$sc.WorkingDirectory = '{ps_quote(str(target.parent))}'; "
        f"$sc.IconLocation = '{ps_quote(str(target))},0'; "
        f"$sc.Description = 'Zapret Manager'; "
        f"$sc.Save(); "
        f"Write-Output 'OK'"
    )

    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            capture_output=True, text=True, timeout=15,
            creationflags=CREATE_NO_WINDOW,
        )
        if result.returncode == 0 and sp.exists():
            return True, str(sp)
        err = (result.stderr or result.stdout or "").strip()
        return False, err or "неизвестная ошибка PowerShell"
    except subprocess.TimeoutExpired:
        return False, "таймаут PowerShell"
    except Exception as e:
        return False, str(e)


def remove() -> tuple[bool, str]:
    """Удаляет ярлык. Возвращает (успех, сообщение)."""
    p = shortcut_path()
    if p is None:
        return False, "рабочий стол не найден"
    if not p.exists():
        return True, "ярлыка не было"
    try:
        p.unlink()
        return True, "ярлык удалён"
    except OSError as e:
        return False, str(e)


# --- Быстрый тест --------------------------------------------------------

if __name__ == "__main__":
    print("frozen          :", getattr(sys, "frozen", False))
    print("Рабочий стол    :", _desktop_dir())
    print("Путь ярлыка     :", shortcut_path())
    print("Существует      :", is_exists())
    print("Целевой exe     :", _target_exe())