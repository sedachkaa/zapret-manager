"""
Модуль управления настройками приложения.

Читает и сохраняет config.json, лежащий в корне проекта.
Предоставляет значения по умолчанию, если файл отсутствует
или какие-то ключи в нём не заданы.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


# --- Пути ---------------------------------------------------------------

def get_project_root() -> Path:
    """
    Возвращает путь к корню проекта.

    - При запуске из исходников: родительская папка относительно этого файла
      (т.е. вверх на два уровня: app/core/config.py -> app/core -> app -> корень).
    - При запуске из собранного PyInstaller .exe: папка, где лежит сам .exe.
    """
    if getattr(sys, "frozen", False):
        # Приложение собрано в .exe — корень рядом с исполняемым файлом
        return Path(sys.executable).parent
    # Запуск из исходников
    return Path(__file__).resolve().parent.parent.parent


PROJECT_ROOT = get_project_root()
CONFIG_PATH = PROJECT_ROOT / "config.json"


# --- Значения по умолчанию ----------------------------------------------

DEFAULT_CONFIG: dict[str, Any] = {
    "exclude_from_update": [
        "zapret/lists/list-general-user.txt",
        "zapret/lists/list-exclude-user.txt",
        "zapret/lists/ipset-exclude-user.txt",
        "tgproxy/config.json",
    ],
    "zapret_path": "zapret/service.bat",
    "tgproxy_path": "tgproxy/TgWsProxy_windows.exe",
    "github_repo": "sedachkaa/zapret-manager",
    "auto_check_updates_on_start": True,
    "theme": "dark",
}


# --- Класс Config --------------------------------------------------------

class Config:
    """
    Обёртка над config.json.

    Использование:
        cfg = Config()
        repo = cfg.get("github_repo")
        cfg.set("theme", "light")
        cfg.save()
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path: Path = path or CONFIG_PATH
        self._data: dict[str, Any] = {}
        self.load()

    # --- I/O -----------------------------------------------------------

    def load(self) -> None:
        """
        Загружает config.json. Если файла нет, он повреждён или каких-то
        ключей не хватает — подставляет значения по умолчанию.
        """
        data: dict[str, Any] = {}

        if self.path.exists():
            try:
                with self.path.open("r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    data = loaded
                else:
                    print(f"[config] Предупреждение: {self.path} содержит не объект JSON, использую значения по умолчанию.")
            except (json.JSONDecodeError, OSError) as e:
                print(f"[config] Ошибка чтения {self.path}: {e}. Использую значения по умолчанию.")

        # Дополняем недостающие ключи значениями по умолчанию
        for key, value in DEFAULT_CONFIG.items():
            data.setdefault(key, value)

        self._data = data

    def save(self) -> None:
        """Сохраняет текущие настройки в config.json."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except OSError as e:
            print(f"[config] Не удалось сохранить {self.path}: {e}")

    # --- Доступ --------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """Возвращает значение по ключу."""
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Устанавливает значение. Не сохраняет автоматически — вызови save()."""
        self._data[key] = value

    def all(self) -> dict[str, Any]:
        """Возвращает копию всего конфига."""
        return dict(self._data)

    # --- Удобные свойства ----------------------------------------------

    @property
    def exclude_from_update(self) -> list[str]:
        """Список относительных путей, которые не перезаписываются при обновлении."""
        value = self._data.get("exclude_from_update", [])
        return value if isinstance(value, list) else []

    @property
    def github_repo(self) -> str:
        """Репозиторий обёртки в формате owner/name."""
        return str(self._data.get("github_repo", ""))

    @property
    def zapret_path(self) -> Path:
        """Полный путь к service.bat."""
        return PROJECT_ROOT / str(self._data.get("zapret_path", ""))

    @property
    def tgproxy_path(self) -> Path:
        """Полный путь к TgWsProxy_windows.exe."""
        return PROJECT_ROOT / str(self._data.get("tgproxy_path", ""))


# --- Быстрый тест при прямом запуске ------------------------------------

if __name__ == "__main__":
    cfg = Config()
    print("PROJECT_ROOT:", PROJECT_ROOT)
    print("CONFIG_PATH :", cfg.path)
    print("Repo        :", cfg.github_repo)
    print("Zapret      :", cfg.zapret_path)
    print("TG Proxy    :", cfg.tgproxy_path)
    print("Исключения  :")
    for item in cfg.exclude_from_update:
        print("   -", item)