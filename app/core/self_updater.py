"""
Самообновление обёртки Zapret Manager.

Работает ТОЛЬКО для собранного .exe (PyInstaller frozen).
При запуске из исходников функция отключена — там обновляйся через git pull.

Алгоритм:
    1. check_for_update() — есть ли новая версия на GitHub.
    2. download_release() — скачиваем zip-ассет во временную папку.
    3. apply_update() — создаём helper .bat, который:
        - ждёт 3 секунды (пока приложение закроется),
        - распаковывает zip поверх папки приложения,
        - запускает новый ZapretManager.exe,
        - удаляет zip и сам себя.
    4. Приложение должно вызвать os._exit(0) СРАЗУ после успешного apply_update().
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.core import updater as gh_updater
from app.core.config import Config


@dataclass
class SelfUpdateResult:
    action: str
    ok: bool
    message: str = ""
    details: str = ""

    def summary(self) -> str:
        prefix = "OK" if self.ok else "ОШИБКА"
        s = f"[{self.action}] {prefix}"
        if self.message:
            s += f": {self.message}"
        return s


def is_supported() -> bool:
    """Самообновление доступно только для собранного .exe."""
    return bool(getattr(sys, "frozen", False))


def check_for_update(current_version: str, cfg: Config) -> gh_updater.ReleaseInfo | None:
    """Возвращает релиз, если доступна новая версия обёртки."""
    return gh_updater.check_wrapper_update(current_version, cfg)


def download_release(
    release: gh_updater.ReleaseInfo,
    *,
    progress_cb: Callable[[float], None] | None = None,
) -> Path | None:
    """
    Скачивает zip-ассет релиза во временную папку.
    progress_cb(percent: float) — необязательный callback для прогресса.
    Возвращает путь к zip.
    """
    if not release.asset_url or not release.asset_name:
        print("[self_update] у релиза нет подходящего ассета")
        return None

    tmp_dir = Path(tempfile.gettempdir()) / "zapret-manager-update"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out = tmp_dir / release.asset_name

    try:
        gh_updater.download_file(release.asset_url, out, progress_cb=progress_cb)
        return out
    except Exception as e:
        print(f"[self_update] download failed: {e}")
        return None


def apply_update(zip_path: Path) -> SelfUpdateResult:
    """
    Создаёт и запускает helper .bat, который заменит файлы приложения
    после его завершения. Приложение должно вызвать os._exit(0)
    через 1–2 секунды после успешного вызова.
    """
    if not is_supported():
        return SelfUpdateResult(
            "self_update", False,
            "самообновление доступно только для .exe (не из исходников)",
        )

    if not zip_path.exists():
        return SelfUpdateResult("self_update", False, f"zip не найден: {zip_path}")

    exe_path = Path(sys.executable).resolve()
    app_dir = exe_path.parent
    exe_name = exe_path.name

    tmp_dir = Path(tempfile.gettempdir()) / "zapret-manager-update"
    helper = tmp_dir / "apply_update.bat"

    zip_str = str(zip_path)
    app_dir_str = str(app_dir)
    exe_path_str = str(exe_path)

    # Helper-скрипт. Используем CRLF и cp866 — стандартные для .bat на Windows.
    content = (
        "@echo off\r\n"
        "echo Waiting for app to close...\r\n"
        "timeout /t 3 /nobreak > nul\r\n"
        "\r\n"
        f'cd /d "{app_dir_str}"\r\n'
        "\r\n"
        "echo Unpacking update...\r\n"
        f'powershell -NoProfile -ExecutionPolicy Bypass -Command "'
        f"Expand-Archive -LiteralPath '{zip_str}' -DestinationPath '{app_dir_str}' -Force"
        f'"\r\n'
        "\r\n"
        "if errorlevel 1 (\r\n"
        "    echo ERROR: failed to extract archive.\r\n"
        "    pause\r\n"
        "    exit /b 1\r\n"
        ")\r\n"
        "\r\n"
        "echo Launching updated application...\r\n"
        f'start "" "{exe_path_str}"\r\n'
        "\r\n"
        "echo Cleanup...\r\n"
        f'del /f /q "{zip_str}" > nul 2>&1\r\n'
        "\r\n"
        # Самоудаление через отдельный cmd с задержкой
        'start "" cmd /c "timeout /t 2 > nul & del /f /q \\"%~f0\\""\r\n'
    )

    try:
        helper.write_text(content, encoding="cp866")
    except OSError as e:
        return SelfUpdateResult("self_update", False, f"не удалось создать helper: {e}")

    try:
        subprocess.Popen(
            ["cmd.exe", "/c", str(helper)],
            cwd=str(app_dir),
            creationflags=(
                getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            ),
            close_fds=True,
        )
    except OSError as e:
        return SelfUpdateResult("self_update", False, f"не удалось запустить helper: {e}")

    return SelfUpdateResult(
        "self_update", True,
        "обновление запущено; приложение сейчас закроется и перезапустится",
    )