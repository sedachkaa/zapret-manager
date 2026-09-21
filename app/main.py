"""
Точка входа приложения Zapret Manager.

При старте проверяет права администратора. Если их нет — перезапускает
себя с UAC и выходит. Это нужно, потому что:
    1. service.bat требует админа для установки/удаления службы;
    2. без админ-прав Windows UIPI блокирует любое взаимодействие
       с админскими окнами (в т.ч. автоклавиши).

Если пользователь отказывается от UAC — приложение продолжит работу
без админ-прав, но некоторые функции будут недоступны.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys


def is_admin() -> bool:
    """True, если текущий процесс запущен с правами администратора."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> bool:
    """
    Перезапускает текущий процесс с правами администратора (UAC).
    Возвращает True, если элевированный процесс успешно запущен.
    """
    if getattr(sys, "frozen", False):
        # Собранный PyInstaller .exe
        exe = sys.executable
        params = subprocess.list2cmdline(sys.argv[1:])
    else:
        # Запуск из исходников через python -m app.main
        exe = sys.executable
        params = subprocess.list2cmdline(["-m", "app.main"] + sys.argv[1:])

    try:
        res = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            exe,
            params,
            os.getcwd(),
            1,  # SW_SHOWNORMAL
        )
        return int(res) > 32
    except Exception as e:
        print(f"[main] не удалось повысить права: {e}")
        return False


def main() -> int:
    # Автоэлевация: если не админ — перезапускаемся с UAC
    if not is_admin():
        print("[main] нет прав админа, пробую перезапуститься с UAC...")
        if relaunch_as_admin():
            print("[main] элевированный процесс запущен, завершаю текущий")
            return 0
        print("[main] пользователь отказался от UAC или ошибка — продолжаю без админа")

    # Импортируем GUI только после элевации (чтобы не тянуть CustomTkinter зря)
    from app.core.config import Config
    from app.gui.main_window import MainWindow

    cfg = Config()
    app = MainWindow(cfg)
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())