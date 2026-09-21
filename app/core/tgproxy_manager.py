"""
Управление tg-ws-proxy.

Процесс может быть запущен как нами (через Popen), так и внешне
(пользователь кликнул exe сам, или предыдущий запуск уцелел после
перезапуска GUI). Поэтому:
    - is_running() сначала проверяет Popen-handle,
      затем спрашивает tasklist по имени образа;
    - stop() умеет убивать как наш процесс, так и внешний
      (через taskkill /IM).
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.core import updater
from app.core.config import PROJECT_ROOT, Config


EXE_NAME = "TgWsProxy_windows.exe"


# --- Результат операции --------------------------------------------------

@dataclass
class TgProxyResult:
    action: str
    ok: bool
    message: str = ""

    def summary(self) -> str:
        prefix = "OK" if self.ok else "ОШИБКА"
        if self.message:
            return f"[{self.action}] {prefix}: {self.message}"
        return f"[{self.action}] {prefix}"


# --- Утилиты -------------------------------------------------------------

def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "cp866", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _find_pids_by_image(image_name: str) -> list[int]:
    """Возвращает список PID процессов с заданным именем образа."""
    try:
        completed = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/FO", "CSV", "/NH"],
            capture_output=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        out = _decode(completed.stdout)
        pids: list[int] = []
        for line in out.splitlines():
            line = line.strip()
            if not line or line.startswith("INFO"):
                continue
            # CSV: "name","pid","session","sess#","mem"
            parts = [p.strip('" ') for p in line.split('","')]
            if len(parts) >= 2 and parts[0].lower() == image_name.lower():
                try:
                    pids.append(int(parts[1]))
                except ValueError:
                    pass
        return pids
    except Exception:
        return []


# --- Менеджер ------------------------------------------------------------

class TgProxyManager:
    """Управляет tg-ws-proxy."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._proc: subprocess.Popen | None = None
        self._cached_version: str | None = None

    # --- Пути ----------------------------------------------------------

    @property
    def exe_path(self) -> Path:
        return self.cfg.tgproxy_path

    @property
    def tgproxy_dir(self) -> Path:
        return PROJECT_ROOT / "tgproxy"

    # --- Проверки ------------------------------------------------------

    def is_installed(self) -> bool:
        return self.exe_path.exists()

    def is_running(self) -> bool:
        """
        True, если процесс TgWsProxy_windows.exe есть в системе.
        Не важно, кто его запустил — мы или пользователь.
        """
        # 1. Наш handle
        if self._proc is not None and self._proc.poll() is None:
            return True
        # 2. Системный поиск
        pids = _find_pids_by_image(EXE_NAME)
        if not pids:
            # процесса больше нет — обнулим handle
            self._proc = None
            return False
        return True

    @property
    def pid(self) -> int | None:
        """PID: сначала из нашего handle, потом из tasklist."""
        if self._proc is not None and self._proc.poll() is None:
            return self._proc.pid
        pids = _find_pids_by_image(EXE_NAME)
        return pids[0] if pids else None

    def is_our_process(self) -> bool:
        """True, если процесс запущен именно нами в этой сессии."""
        return self._proc is not None and self._proc.poll() is None

    # --- Запуск / остановка --------------------------------------------

    def start(self) -> TgProxyResult:
        if not self.is_installed():
            return TgProxyResult("start", False, f"Не найден exe: {self.exe_path}")

        if self.is_running():
            return TgProxyResult("start", True, f"Уже запущен (PID {self.pid})")

        creationflags = 0
        if os.name == "nt":
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
        """
        Останавливает процесс. Если он наш — terminate() с fallback на taskkill.
        Если внешний — taskkill по всем найденным PID.
        """
        if not self.is_running():
            self._proc = None
            return TgProxyResult("stop", True, "Не был запущен")

        our_pid = self._proc.pid if (self._proc is not None and self._proc.poll() is None) else None

        # 1. Если это наш — мягкая попытка
        if our_pid is not None:
            try:
                self._proc.terminate()  # type: ignore[union-attr]
                self._proc.wait(timeout=5)  # type: ignore[union-attr]
                self._proc = None
                return TgProxyResult("stop", True, f"Остановлен (PID {our_pid})")
            except subprocess.TimeoutExpired:
                pass
            except Exception as e:
                print(f"[tgproxy] terminate не удался: {e}")

        # 2. Жёстко — taskkill по всем найденным PID (своим или внешним)
        pids = _find_pids_by_image(EXE_NAME)
        if not pids:
            self._proc = None
            return TgProxyResult("stop", True, "Процесс уже завершён")

        killed = 0
        for pid in pids:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True, timeout=10,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                killed += 1
            except Exception as e:
                print(f"[tgproxy] taskkill {pid} не удался: {e}")

        self._proc = None
        return TgProxyResult("stop", True, f"Остановлен принудительно ({killed} процессов)")

    def restart(self) -> TgProxyResult:
        self.stop()
        return self.start()

    # --- Версия (с кэшем) ----------------------------------------------

    def get_version(self, *, use_cache: bool = True) -> str | None:
        if use_cache and self._cached_version is not None:
            return self._cached_version
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
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            version = (completed.stdout or "").strip()
            if version:
                self._cached_version = version
                return version
        except Exception as e:
            print(f"[tgproxy] не удалось узнать версию: {e}")
        return None

    def clear_version_cache(self) -> None:
        self._cached_version = None

    # --- Обновление ----------------------------------------------------

    def check_update(self) -> updater.ReleaseInfo | None:
        return updater.check_tgproxy_update(self.cfg)

    def apply_update(self, release: updater.ReleaseInfo | None = None, *, progress_cb=None) -> TgProxyResult:
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

        self.clear_version_cache()

        if was_running:
            self.start()

        return TgProxyResult(
            "update", True,
            f"Обновлено до {release.tag} (записано: {written}, пропущено: {skipped})",
        )


# --- Быстрый тест --------------------------------------------------------

if __name__ == "__main__":
    cfg = Config()
    t = TgProxyManager(cfg)
    print("exe         :", t.exe_path)
    print("Существует  :", t.is_installed())
    print("Запущен     :", t.is_running())
    print("PID         :", t.pid)
    print("Версия      :", t.get_version())