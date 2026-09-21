"""
Управление zapret-discord-youtube через service.bat.

Аргументы, которые понимает service.bat:
    - status_zapret    — проверка статуса службы и TCP
    - check_updates    — проверка обновлений IPSet/hosts
    - load_game_filter — применить игровой фильтр
    - load_user_lists  — принудительно загрузить user-списки
    - admin            — открыть интерактивное меню от админа

Активность zapret определяется через tasklist (winws.exe).
service.bat status_zapret возвращает пустой stdout, поэтому
использовать его для отображения статуса бесполезно.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.core.config import PROJECT_ROOT, Config


# --- Результат выполнения ------------------------------------------------

@dataclass
class ZapretResult:
    """Результат вызова service.bat."""
    action: str
    returncode: int
    stdout: str = ""
    stderr: str = ""
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.error is None and self.returncode == 0

    def summary(self) -> str:
        if self.error:
            return f"[{self.action}] ОШИБКА: {self.error}"
        return f"[{self.action}] код={self.returncode}"


# --- Утилиты -------------------------------------------------------------

def is_admin() -> bool:
    """True, если текущий процесс запущен с правами администратора."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _decode_console_output(raw: bytes) -> str:
    for enc in ("utf-8", "cp866", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _tasklist_has(image_name: str) -> bool:
    """True, если в системе есть запущенный процесс с таким именем."""
    try:
        completed = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/NH"],
            capture_output=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        out = _decode_console_output(completed.stdout).lower()
        # tasklist при отсутствии процессов пишет "INFO: No tasks..."
        return image_name.lower() in out
    except Exception:
        return False


# --- Менеджер ------------------------------------------------------------

class ZapretManager:
    """Управляет zapret-discord-youtube через service.bat."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    # --- Пути ----------------------------------------------------------

    @property
    def bat_path(self) -> Path:
        return self.cfg.zapret_path

    @property
    def zapret_dir(self) -> Path:
        return PROJECT_ROOT / "zapret"

    @property
    def winws_path(self) -> Path:
        return self.zapret_dir / "bin" / "winws.exe"

    @property
    def lists_dir(self) -> Path:
        return self.zapret_dir / "lists"

    # --- Проверки ------------------------------------------------------

    def is_installed(self) -> bool:
        """Есть ли service.bat и winws.exe на диске."""
        return self.bat_path.exists() and self.winws_path.exists()

    def is_winws_running(self) -> bool:
        """Запущен ли процесс winws.exe (признак активного zapret)."""
        return _tasklist_has("winws.exe")

    def is_service_running(self) -> bool:
        """Запущена ли служба 'zapret' в Windows."""
        try:
            completed = subprocess.run(
                ["sc", "query", "zapret"],
                capture_output=True,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            out = _decode_console_output(completed.stdout)
            return "RUNNING" in out
        except Exception:
            return False

    def is_active(self) -> bool:
        """Активен ли zapret — winws.exe запущен или служба работает."""
        return self.is_winws_running() or self.is_service_running()

    # --- Запуск --------------------------------------------------------

    def run(self, action: str, *, timeout: int = 60, cwd: Path | None = None) -> ZapretResult:
        if not self.bat_path.exists():
            return ZapretResult(
                action=action,
                returncode=-1,
                error=f"service.bat не найден: {self.bat_path}",
            )

        work_dir = cwd or self.zapret_dir
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

        try:
            proc = subprocess.Popen(
                ["cmd", "/c", str(self.bat_path), action],
                cwd=str(work_dir),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=creationflags,
            )
        except OSError as e:
            return ZapretResult(action=action, returncode=-1, error=f"Не удалось запустить: {e}")

        try:
            stdout_b, stderr_b = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._kill_process_tree(proc.pid)
            try:
                stdout_b, stderr_b = proc.communicate(timeout=5)
            except Exception:
                stdout_b, stderr_b = b"", b""
            return ZapretResult(
                action=action,
                returncode=-1,
                stdout=_decode_console_output(stdout_b),
                stderr=_decode_console_output(stderr_b),
                error=f"Таймаут {timeout} сек — процесс убит",
            )

        return ZapretResult(
            action=action,
            returncode=proc.returncode,
            stdout=_decode_console_output(stdout_b),
            stderr=_decode_console_output(stderr_b),
        )

    @staticmethod
    def _kill_process_tree(pid: int) -> None:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, timeout=10,
            )
        except Exception:
            pass

    # --- Готовые обёртки над аргументами --------------------------------

    def get_status(self) -> ZapretResult:
        return self.run("status_zapret", timeout=20)

    def check_updates(self) -> ZapretResult:
        return self.run("check_updates", timeout=180)

    def load_game_filter(self) -> ZapretResult:
        return self.run("load_game_filter", timeout=30)

    def load_user_lists(self) -> ZapretResult:
        return self.run("load_user_lists", timeout=30)

    # --- Интерактивное меню --------------------------------------------

    def open_console(self) -> bool:
        """
        Открывает service.bat в отдельном окне cmd С ПРАВАМИ АДМИНА.
        Сам bat требует админа, поэтому открывать без UAC нет смысла —
        иначе он всё равно перезапустится через PowerShell, что даёт
        мигание двух окон. Открываем сразу через ShellExecuteW 'runas'.
        """
        return self.open_console_as_admin()

    def open_console_as_admin(self) -> bool:
        """Открывает service.bat через cmd /k с повышением прав (UAC)."""
        if not self.bat_path.exists():
            raise FileNotFoundError(f"service.bat не найден: {self.bat_path}")
        try:
            res = ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                "cmd.exe",
                f'/k "{self.bat_path}"',
                str(self.zapret_dir),
                1,  # SW_SHOWNORMAL
            )
            return int(res) > 32
        except Exception as e:
            print(f"[zapret] runas failed: {e}")
            return False

    # --- Проводник и списки --------------------------------------------

    def open_folder(self) -> bool:
        if not self.zapret_dir.exists():
            return False
        try:
            os.startfile(str(self.zapret_dir))  # type: ignore[attr-defined]
            return True
        except OSError:
            return False

    def open_lists_folder(self) -> bool:
        if not self.lists_dir.exists():
            return False
        try:
            os.startfile(str(self.lists_dir))  # type: ignore[attr-defined]
            return True
        except OSError:
            return False

    def edit_user_lists(self) -> bool:
        target = self.lists_dir / "list-general-user.txt"
        if not target.exists():
            try:
                self.lists_dir.mkdir(parents=True, exist_ok=True)
                target.write_text(
                    "# Список доменов для обхода (по одному на строку)\n",
                    encoding="utf-8",
                )
            except OSError:
                return False
        try:
            os.startfile(str(target))  # type: ignore[attr-defined]
            return True
        except OSError:
            return False


# --- Быстрый тест --------------------------------------------------------

if __name__ == "__main__":
    cfg = Config()
    z = ZapretManager(cfg)
    print("service.bat       :", z.bat_path)
    print("Установлен        :", z.is_installed())
    print("winws запущен     :", z.is_winws_running())
    print("Служба работает   :", z.is_service_running())
    print("Активен           :", z.is_active())
    print("Админ             :", is_admin())