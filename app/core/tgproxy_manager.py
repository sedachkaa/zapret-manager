"""
Управление tg-ws-proxy.

Кэш и быстрый режим:
    - _find_processes_by_names(fast=True) использует ТОЛЬКО tasklist —
      быстро (~50 мс), работает без прав и без PowerShell.
    - _find_processes_by_names(fast=False) добавляет Get-CimInstance —
      даёт путь и время старта, но занимает ~1 сек.
    - В авто-обновлении GUI используется fast=True.
    - При явном клике «Обновить статус» — fast=False.
    - Результат кэшируется на CACHE_TTL секунд.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.core import updater
from app.core.config import PROJECT_ROOT, Config


EXE_NAME = "TgWsProxy_windows.exe"

PROCESS_NAMES = [
    "TgWsProxy_windows.exe",
    "tg-ws-proxy.exe",
]

# Время жизни кэша результатов поиска (секунды).
CACHE_TTL = 2.5


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


@dataclass
class ProcessInfo:
    pid: int
    name: str
    exe_path: str = ""
    start_time: str = ""


# --- Утилиты -------------------------------------------------------------

def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "cp866", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _format_cim_date(raw: str) -> str:
    if not raw:
        return ""
    if raw.startswith("/Date(") and raw.endswith(")/"):
        try:
            from datetime import datetime
            ms = int(raw[6:-2])
            return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return raw
    return raw


def _find_processes_by_names(names: list[str], *, fast: bool = True) -> list[ProcessInfo]:
    """
    Возвращает список процессов с указанными именами.

    fast=True  — только tasklist (быстро, без пути и времени).
    fast=False — плюс Get-CimInstance (медленно, но с путём и временем).
    """
    proc_infos: dict[int, ProcessInfo] = {}

    # --- Базовый список через tasklist ---
    for raw_name in names:
        try:
            completed = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {raw_name}", "/FO", "CSV", "/NH"],
                capture_output=True,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as e:
            print(f"[tgproxy] tasklist failed for {raw_name}: {e}")
            continue

        out = _decode(completed.stdout)
        for line in out.splitlines():
            line = line.strip()
            if not line or line.startswith("INFO") or line.startswith("ИНФОРМАЦИЯ"):
                continue
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) < 2:
                continue
            name = parts[0]
            try:
                pid = int(parts[1])
            except ValueError:
                continue
            proc_infos[pid] = ProcessInfo(pid=pid, name=name)

    if fast or not proc_infos:
        return list(proc_infos.values())

    # --- Обогащение через Get-CimInstance (только в full-режиме) ---
    try:
        filter_clause = " OR ".join(f"Name='{n}'" for n in names)
        ps_cmd = (
            f"Get-CimInstance Win32_Process -Filter \"{filter_clause}\" "
            f"| ForEach-Object {{ "
            f"\"$($_.ProcessId)|$($_.ExecutablePath)|"
            f"$($_.CreationDate)\" }}"
        )
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
            capture_output=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        out = _decode(completed.stdout)
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split("|")
            if len(parts) < 3:
                continue
            try:
                pid = int(parts[0])
            except ValueError:
                continue
            if pid in proc_infos:
                proc_infos[pid].exe_path = parts[1].strip()
                proc_infos[pid].start_time = _format_cim_date(parts[2].strip())
    except Exception as e:
        print(f"[tgproxy] CIM enrich skipped: {e}")

    return list(proc_infos.values())


def _taskkill_by_pid(pid: int) -> bool:
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True
    except Exception as e:
        print(f"[tgproxy] taskkill {pid} failed: {e}")
        return False


# --- Менеджер ------------------------------------------------------------

class TgProxyManager:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._proc: subprocess.Popen | None = None
        self._cached_version: str | None = None

        # Кэш процессов: список + момент времени, когда получен.
        self._proc_cache: list[ProcessInfo] = []
        self._proc_cache_time: float = 0.0

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

    def _system_processes(self, *, full: bool = False) -> list[ProcessInfo]:
        """
        Возвращает список процессов с кэшированием.
        full=False (по умолчанию) — быстрый режим, только tasklist.
        full=True — расширенный, с путями и временем (через PowerShell).
        """
        # Кэш работает только для быстрого режима — полный всегда свежий.
        if not full:
            now = time.time()
            if now - self._proc_cache_time < CACHE_TTL:
                return self._proc_cache
            procs = _find_processes_by_names(PROCESS_NAMES, fast=True)
            self._proc_cache = procs
            self._proc_cache_time = now
            return procs

        # full=True — запрашиваем свежие данные, обновляем кэш
        procs = _find_processes_by_names(PROCESS_NAMES, fast=False)
        self._proc_cache = procs
        self._proc_cache_time = time.time()
        return procs

    def _invalidate_cache(self) -> None:
        """Сбрасывает кэш, чтобы следующий запрос был свежим."""
        self._proc_cache_time = 0.0

    def is_running(self) -> bool:
        if self._proc is not None:
            if self._proc.poll() is None:
                return True
            self._proc = None
        return bool(self._system_processes())

    @property
    def pid(self) -> Optional[int]:
        procs = self._system_processes()
        if not procs:
            return None
        for p in procs:
            if p.name.lower() == "tg-ws-proxy.exe":
                return p.pid
        if self._proc is not None and self._proc.poll() is None:
            return self._proc.pid
        return procs[0].pid

    def is_our_process(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # --- Подробный статус ----------------------------------------------

    def get_process_info(self, *, full: bool = False) -> list[ProcessInfo]:
        """
        Список процессов. full=True — с путями и временем.
        """
        return self._system_processes(full=full)

    def get_status_summary(self, *, full: bool = False) -> str:
        """
        Многострочный статус для GUI.
        full=True — запрашивает пути и время (медленно, но информативно).
        full=False — быстро, только PID и имя.
        """
        procs = self.get_process_info(full=full)
        if not procs:
            if self.is_installed():
                return "Остановлен"
            return "Не установлен"

        lines: list[str] = []
        if len(procs) == 1:
            p = procs[0]
            lines.append(f"Запущен (PID {p.pid}) — {p.name}")
            if p.exe_path:
                lines.append(f"Путь: {p.exe_path}")
            if p.start_time:
                lines.append(f"Запущен: {p.start_time}")
        else:
            lines.append(f"Запущено процессов: {len(procs)}")
            for p in procs[:5]:
                lines.append(f"  PID {p.pid} — {p.name}")
        return "\n".join(lines)

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

        time.sleep(2.0)
        self._invalidate_cache()

        if self._proc.poll() is not None:
            code = self._proc.returncode
            self._proc = None
            return TgProxyResult(
                "start", False,
                f"процесс сразу завершился (код {code})",
            )

        return TgProxyResult("start", True, f"Запущен (PID {self._proc.pid})")

    def stop(self) -> TgProxyResult:
        if not self.is_running():
            self._proc = None
            return TgProxyResult("stop", True, "Не был запущен")

        our_pid = self._proc.pid if (self._proc is not None and self._proc.poll() is None) else None

        if our_pid is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            except Exception as e:
                print(f"[tgproxy] terminate failed: {e}")
            self._proc = None

        # Всегда получаем свежий список для stop — кэш обходим
        procs = _find_processes_by_names(PROCESS_NAMES, fast=True)
        if not procs:
            self._invalidate_cache()
            return TgProxyResult("stop", True, "Остановлен")

        killed = 0
        for p in procs:
            if _taskkill_by_pid(p.pid):
                killed += 1

        time.sleep(0.3)
        self._invalidate_cache()
        remaining = _find_processes_by_names(PROCESS_NAMES, fast=True)
        if remaining:
            return TgProxyResult(
                "stop", False,
                f"убито {killed}, но осталось {len(remaining)} процессов",
            )
        return TgProxyResult("stop", True, f"Остановлено ({killed} процессов)")

    def restart(self) -> TgProxyResult:
        self.stop()
        time.sleep(0.5)
        return self.start()

    # --- Версия --------------------------------------------------------

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
            time.sleep(0.5)

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
        self._invalidate_cache()

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
    print()
    print("Быстрый статус:")
    print(t.get_status_summary(full=False))
    print()
    print("Полный статус (с путями):")
    print(t.get_status_summary(full=True))