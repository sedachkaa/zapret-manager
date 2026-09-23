"""
Самообновление обёртки Zapret Manager через Inno Setup installer.

Работает ТОЛЬКО для собранного .exe (PyInstaller frozen).

Алгоритм:
    1. check_for_update() — есть ли новая версия на GitHub.
    2. download_release() — скачиваем ZapretManager-Setup-X.Y.Z.exe
       во временную папку (с прогрессом).
    3. apply_update() — запускаем installer в silent-режиме:
           ZapretManager-Setup-X.Y.Z.exe /SILENT /NORESTART /CLOSEAPPLICATIONS
       Inno Setup сам:
           - закроет работающий ZapretManager.exe через Restart Manager,
           - заменит файлы,
           - обновит ярлыки,
           - запустит новую версию (см. [Run] в setup.iss).
    4. Приложение после успешного apply_update() вызывает os._exit(0),
       чтобы installer смог заменить exe-файл.
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
    Скачивает installer (.exe) релиза во временную папку.
    Возвращает путь к скачанному файлу или None.
    """
    if not release.asset_url or not release.asset_name:
        print("[self_update] у релиза нет подходящего ассета")
        return None

    # Ожидаем installer или хотя бы exe.
    # Если прилетел zip — это ошибка конфигурации релиза,
    # сообщаем понятно.
    if release.asset_type not in ("installer", "exe"):
        print(f"[self_update] неверный тип ассета: {release.asset_type}")
        return None

    tmp_dir = Path(tempfile.gettempdir()) / "zapret-manager-update"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out = tmp_dir / release.asset_name

    # Если файл уже есть и не изменялся — перезапишем
    try:
        if out.exists():
            out.unlink()
    except OSError:
        pass

    try:
        gh_updater.download_file(release.asset_url, out, progress_cb=progress_cb)
        return out
    except Exception as e:
        print(f"[self_update] download failed: {e}")
        return None


def apply_update(installer_path: Path) -> SelfUpdateResult:
    """
    Запускает installer в silent-режиме.
    После успеха приложение должно вызвать os._exit(0).
    """
    if not is_supported():
        return SelfUpdateResult(
            "self_update", False,
            "самообновление доступно только для .exe (не из исходников)",
        )

    if not installer_path.exists():
        return SelfUpdateResult("self_update", False, f"installer не найден: {installer_path}")

    if not installer_path.name.lower().endswith(".exe"):
        return SelfUpdateResult(
            "self_update", False,
            f"installer должен быть .exe, получено: {installer_path.name}",
        )

    installer_str = str(installer_path)

    # Флаги Inno Setup:
    #   /SILENT             — тихая установка с прогресс-баром, но без вопросов
    #   /NORESTART          — не перезагружать компьютер
    #   /CLOSEAPPLICATIONS  — закрыть запущенные приложения через Restart Manager
    #   /SUPPRESSMSGBOXES   — подавить все диалоги
    args = [
        installer_str,
        "/SILENT",
        "/NORESTART",
        "/CLOSEAPPLICATIONS",
        "/SUPPRESSMSGBOXES",
    ]

    creationflags = 0
    if os.name == "nt":
        creationflags = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )

    try:
        subprocess.Popen(
            args,
            cwd=str(installer_path.parent),
            creationflags=creationflags,
            close_fds=True,
        )
    except OSError as e:
        return SelfUpdateResult("self_update", False, f"не удалось запустить installer: {e}")

    return SelfUpdateResult(
        "self_update", True,
        "установка началась; приложение закроется, установка завершится автоматически",
    )