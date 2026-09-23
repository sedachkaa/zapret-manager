"""
Модуль управления настройками приложения.

Разделяет два понятия:
    - APP_INSTALL_DIR — где лежит приложение (exe или корень проекта).
      Сюда попадают: ZapretManager.exe, _internal/.
    - APP_DATA_DIR — где хранятся данные пользователя:
      config.json, logs/, zapret/, tgproxy/.

При запуске из исходников обе папки совпадают — это корень проекта.
При запуске из собранного .exe:
    APP_INSTALL_DIR — папка с exe (например, C:\\Program Files\\ZapretManager).
    APP_DATA_DIR    — %LOCALAPPDATA%\\ZapretManager (или папка с exe,
                      если рядом лежит пустой файл portable.txt).

Дополнительно: get_asset_path() — путь к встроенным ресурсам (app/assets/).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


# --- Определение путей --------------------------------------------------

def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def get_install_dir() -> Path:
    """
    Папка, где лежит приложение.
    - .exe (frozen): папка с ZapretManager.exe.
    - исходники: корень проекта.
    """
    if _is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def get_data_dir() -> Path:
    """
    Папка с данными пользователя.
    - .exe (frozen) + portable.txt рядом: папка с exe.
    - .exe (frozen) без portable.txt: %LOCALAPPDATA%\\ZapretManager.
    - исходники: корень проекта.
    """
    if not _is_frozen():
        return Path(__file__).resolve().parent.parent.parent

    exe_dir = Path(sys.executable).resolve().parent

    # Portable-режим: маркер рядом с exe
    if (exe_dir / "portable.txt").exists():
        return exe_dir

    # Обычный режим — LOCALAPPDATA
    localappdata = os.environ.get("LOCALAPPDATA")
    if localappdata:
        return Path(localappdata) / "ZapretManager"

    # Запасной вариант, если LOCALAPPDATA почему-то нет
    return Path.home() / "ZapretManager"


def get_asset_path(name: str) -> Path:
    """
    Возвращает путь к файлу внутри app/assets/.

    - Из исходников: <корень_проекта>/app/assets/<name>
    - Из собранного PyInstaller .exe: <_MEIPASS>/app/assets/<name>

    Если файл не найден во встроенных ресурсах, проверяет также
    <APP_INSTALL_DIR>/app/assets/<name> (полезно при ручной распаковке).
    """
    if _is_frozen():
        # PyInstaller распаковывает datas в sys._MEIPASS
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            p = Path(meipass) / "app" / "assets" / name
            if p.exists():
                return p
        # Фолбэк — рядом с exe
        return Path(sys.executable).resolve().parent / "app" / "assets" / name

    return Path(__file__).resolve().parent.parent / "assets" / name


APP_INSTALL_DIR = get_install_dir()
APP_DATA_DIR = get_data_dir()

# PROJECT_ROOT в коде используется для config.json, zapret/, tgproxy/, logs/ —
# это всё данные, поэтому равен APP_DATA_DIR.
PROJECT_ROOT = APP_DATA_DIR
CONFIG_PATH = APP_DATA_DIR / "config.json"


# --- Значения по умолчанию ----------------------------------------------

DEFAULT_CONFIG: dict[str, Any] = {
    "exclude_from_update": [
        "zapret/lists/list-general.txt",
        "zapret/lists/list-general-user.txt",
        "zapret/lists/list-exclude-user.txt",
        "zapret/lists/ipset-exclude-user.txt",
        "zapret/lists/ipset-all.txt",
        "zapret/lists/ipset-all.txt.backup",
        "tgproxy/config.json",
    ],
    "zapret_path": "zapret/service.bat",
    "tgproxy_path": "tgproxy/TgWsProxy_windows.exe",
    "github_repo": "sedachkaa/zapret-manager",
    "auto_check_updates_on_start": True,
    "theme": "dark",
    "last_strategy": "",
    "shortcut_prompted": False,
}


# --- Класс Config --------------------------------------------------------

class Config:
    """
    Обёртка над config.json.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path: Path = path or CONFIG_PATH
        self._data: dict[str, Any] = {}
        self.load()

    # --- I/O -----------------------------------------------------------

    def load(self) -> None:
        data: dict[str, Any] = {}

        if self.path.exists():
            try:
                with self.path.open("r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    data = loaded
                else:
                    print(f"[config] Предупреждение: {self.path} содержит не объект JSON.")
            except (json.JSONDecodeError, OSError) as e:
                print(f"[config] Ошибка чтения {self.path}: {e}")

        for key, value in DEFAULT_CONFIG.items():
            data.setdefault(key, value)

        self._data = data

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except OSError as e:
            print(f"[config] Не удалось сохранить {self.path}: {e}")

    # --- Доступ --------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def all(self) -> dict[str, Any]:
        return dict(self._data)

    # --- Удобные свойства ----------------------------------------------

    @property
    def exclude_from_update(self) -> list[str]:
        value = self._data.get("exclude_from_update", [])
        return value if isinstance(value, list) else []

    @property
    def github_repo(self) -> str:
        return str(self._data.get("github_repo", ""))

    @property
    def zapret_path(self) -> Path:
        return PROJECT_ROOT / str(self._data.get("zapret_path", ""))

    @property
    def tgproxy_path(self) -> Path:
        return PROJECT_ROOT / str(self._data.get("tgproxy_path", ""))

    @property
    def last_strategy(self) -> str:
        return str(self._data.get("last_strategy", "") or "")


# --- Быстрый тест при прямом запуске ------------------------------------

if __name__ == "__main__":
    cfg = Config()
    print("frozen           :", _is_frozen())
    print("APP_INSTALL_DIR  :", APP_INSTALL_DIR)
    print("APP_DATA_DIR     :", APP_DATA_DIR)
    print("CONFIG_PATH      :", cfg.path)
    print("Repo             :", cfg.github_repo)
    print("Zapret           :", cfg.zapret_path)
    print("TG Proxy         :", cfg.tgproxy_path)
    print("Last strategy    :", cfg.last_strategy or "(не задана)")
    print("Asset (list)     :", get_asset_path("list-general.txt"))
    print("Asset exists     :", get_asset_path("list-general.txt").exists())