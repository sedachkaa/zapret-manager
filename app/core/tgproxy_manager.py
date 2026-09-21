"""
Управление tg-ws-proxy.

Модуль предоставляет:
    - TgProxyManager — обёртка над процессом TgWsProxy_windows.exe;
    - TgProxyResult — результат операции;
    - проверку статуса, запуск, остановку, обновление.

tg-ws-proxy — GUI-приложение (работает в трее), поэтому:
    - Запускаем через subprocess.Popen, без захвата stdout/stderr.
    - Не ждём завершения — оно живёт, пока пользователь не выключит.
    - Останавливаем через terminate() с fallback на taskkill /F.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from app.core import updater
from app.core.config import PROJECT_ROOT, Config


# --- Результат операции --------------------------------------------------

@dataclass
class TgProxyResult:
    """Результат операции над tg-ws-proxy."""
    action: str
    ok: bool
    message: str = ""

    def summary(self) -> str:
        prefix = "OK" if self.ok else "ОШИБКА"
        return f"[{self.action}] {prefix}: {self.message}" if self.message else f"[{self.action}] {prefix}"


# --- Менеджер ------------------------------------------------------------

class TgProxyManager:
    """
    Управляет tg-ws-proxy.

    Пример:
        cfg = Config()
        t = TgProxyManager(cfg)
        if not t.is_installed():
            print("Не установлен")
        else:
            t.start()
            print("PID:", t.pid)
    """

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._proc: subprocess.Popen | None = None  # храним ссылку на процесс

    # --- Пути ----------------------------------------------------------

    @property
    def exe_path(self) -> Path:
        """
        Полный путь к exe.
        В config.json сейчас указан 'tgproxy/TgWsProxy_windows.exe',
        но реальный файл называется так же, поэтому путь совпадает.
        """
        return self.cfg.tgproxy_path

    @property
    def tgproxy_dir(self) -> Path:
        """Папка tgproxy/."""
        return PROJECT_ROOT / "tgproxy"

    # --- Проверки ------------------------------------------------------

    def is_installed(self) -> bool:
        """True, если exe-файл на месте."""
        return self.exe_path.exists()

    def is_running(self) -> bool:
        """
        True, если процесс жив. Использует сохранённый Popen и проверяет
        poll() — None означает «работает».
        """
        if self._proc is None:
            return False
        return self._proc.poll() is None

    @property
    def pid(self) -> int | None:
        """PID работающего процесса или None."""
        if self._proc is None:
            return None
        return self._proc.pid

    # --- Запуск / остановка --------------------------------------------

    def start(self) -> TgProxyResult:
        """Запускает tg-ws-proxy. Если уже запущен — ничего не делает."""
        if not self.is_installed():
            return TgProxyResult(
                "start", False,
                f"Не найден exe: {self.exe_path}",
            )

        if self.is_running():
            return TgProxyResult("start", True, f"Уже запущен (PID {self.pid})")

        creationflags = 0
        if os.name == "nt":
            # DETACHED_PROCESS — приложение живёт отдельно от нашего
            # CREATE_NEW_PROCESS_GROUP — чтобы его можно было мягко тормознуть
            creationflags = (
                getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            )

        try:
            self._proc = subprocess.Popen(
                [str(self.exe_path)],
                cwd=str(self.tgproxy_dir),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
                close_fds=True,
            )
        except OSError as e:
            self._proc = None
            return TgProxyResult("start", False, f"Не удалось запустить: {e}")

        return TgProxyResult("start", True, f"Запущен (PID {self._proc.pid})")

    def stop(self) -> TgProxyResult:
        """Останавливает tg-ws-proxy. Сначала мягко, потом принудительно."""
        if not self.is_running():
            self._proc = None
            return TgProxyResult("stop", True, "Не был запущен")

        pid = self._proc.pid  # type: ignore[union-attr]

        # 1. Мягкая попытка
        try:
            self._proc.terminate()  # type: ignore[union-attr]
            self._proc.wait(timeout=5)  # type: ignore[union-attr]
            self._proc = None
            return TgProxyResult("stop", True, f"Остановлен (PID {pid})")
        except subprocess.TimeoutExpired:
            pass
        except Exception as e:
            print(f"[tgproxy] terminate не удался: {e}")

        # 2. Жёсткая — через taskkill
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                timeout=10,
            )
            self._proc = None
            return TgProxyResult("stop", True, f"Убит через taskkill (PID {pid})")
        except Exception as e:
            return TgProxyResult("stop", False, f"Не удалось убить: {e}")

    def restart(self) -> TgProxyResult:
        """Останавливает и запускает заново."""
        self.stop()
        return self.start()

    # --- Версия --------------------------------------------------------

    def get_version(self) -> str | None:
        """
        Возвращает FileVersion установленного exe (через PowerShell).
        None, если получить не удалось.
        """
        if not self.is_installed():
            return None
        try:
            completed = subprocess.run(
                [
                    "powershell", "-NoProfile", "-Command",
                    f"(Get-Item -LiteralPath '{self.exe_path}').VersionInfo.FileVersion",
                ],
                capture_output=True,
                timeout=10,
                text=True,
            )
            version = completed.stdout.strip()
            return version or None
        except Exception as e:
            print(f"[tgproxy] не удалось узнать версию: {e}")
            return None

    # --- Обновление ----------------------------------------------------

    def check_update(self) -> updater.ReleaseInfo | None:
        """Последний релиз tg-ws-proxy на GitHub."""
        return updater.check_tgproxy_update(self.cfg)

    def apply_update(self, release: updater.ReleaseInfo | None = None,
                     *, progress_cb=None) -> TgProxyResult:
        """
        Скачивает и устанавливает релиз.
        Если приложение запущено — сначала останавливает, потом обновляет,
        потом снова запускает (если было запущено).
        """
        if release is None:
            release = self.check_update()
        if release is None:
            return TgProxyResult("update", False, "Релиз не найден")

        was_running = self.is_running()
        if was_running:
            stop_res = self.stop()
            if not stop_res.ok:
                return TgProxyResult("update", False, f"Не смог остановить: {stop_res.message}")

        try:
            written, skipped = updater.apply_release(
                release,
                target_dir=self.tgproxy_dir,
                excludes=self.cfg.exclude_from_update,
                progress_cb=progress_cb,
            )
        except Exception as e:
            if was_running:
                self.start()
            return TgProxyResult("update", False, f"Ошибка распаковки: {e}")

        if was_running:
            self.start()

        return TgProxyResult(
            "update", True,
            f"Обновлено до {release.tag} (записано: {written}, пропущено: {skipped})",
        )


# --- Быстрый тест при прямом запуске ------------------------------------

if __name__ == "__main__":
    cfg = Config()
    t = TgProxyManager(cfg)

    print("exe         :", t.exe_path)
    print("Существует  :", t.is_installed())
    print("Запущен     :", t.is_running())
    print("Версия      :", t.get_version())
    print()

    if t.is_installed():
        print("Пробую запустить...")
        res = t.start()
        print(res.summary())
        print("PID         :", t.pid)
        print("Запущен     :", t.is_running())
        print()

        print("Пробую остановить...")
        res = t.stop()
        print(res.summary())
        print("Запущен     :", t.is_running())
    else:
        print("tg-ws-proxy ещё не скачан. Скачаем через updater:")
        rel = t.check_update()
        if rel:
            print(f"  Релиз: {rel.tag}, ассет: [{rel.asset_type}] {rel.asset_name}")
            print("  Применяю...")
            res = t.apply_update(rel)
            print(" ", res.summary())
            print("  Существует:", t.is_installed())