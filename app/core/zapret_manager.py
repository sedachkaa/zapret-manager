"""
Управление zapret-discord-youtube через service.bat.

Модуль предоставляет:
    - ZapretManager — обёртка над service.bat;
    - ZapretResult — результат выполнения команды;
    - утилиты для проверки прав администратора и запуска с UAC.

Основные возможности:
    - is_installed(): установлен ли zapret (есть service.bat и winws.exe);
    - run(action): запуск service.bat с произвольным аргументом;
    - get_status(), check_updates(), admin() — обёртки над известными командами;
    - open_console(): открыть интерактивное меню service.bat в отдельном окне cmd;
    - run_as_admin(): перезапустить команду с повышением прав (UAC).
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
    error: str | None = None  # текст ошибки Python (не bat)

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
    """
    Пытается декодировать вывод bat-файла.
    На Windows bat-скрипты с кириллицей обычно пишут в cp866 или cp1251,
    современные (с chcp 65001) — в utf-8. Пробуем по очереди.
    """
    for enc in ("utf-8", "cp866", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


# --- Менеджер ------------------------------------------------------------

class ZapretManager:
    """
    Управляет zapret-discord-youtube через service.bat.

    Пример:
        cfg = Config()
        z = ZapretManager(cfg)
        if not z.is_installed():
            print("zapret не установлен — сначала скачайте релиз")
        else:
            print(z.get_status())
    """

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    # --- Пути ----------------------------------------------------------

    @property
    def bat_path(self) -> Path:
        """Полный путь к service.bat."""
        return self.cfg.zapret_path

    @property
    def zapret_dir(self) -> Path:
        """Папка zapret/."""
        return PROJECT_ROOT / "zapret"

    @property
    def winws_path(self) -> Path:
        """Полный путь к winws.exe (основной бинарник zapret)."""
        return self.zapret_dir / "bin" / "winws.exe"

    # --- Проверки ------------------------------------------------------

    def is_installed(self) -> bool:
        """Есть ли service.bat и winws.exe."""
        return self.bat_path.exists() and self.winws_path.exists()

    # --- Запуск --------------------------------------------------------

    def run(
        self,
        action: str,
        *,
        timeout: int = 60,
        cwd: Path | None = None,
    ) -> ZapretResult:
        """
        Запускает service.bat с указанным аргументом.
        Захватывает stdout/stderr.
        Автоматически отвечает на возможный 'pause' (подаёт EOF через DEVNULL).
        При таймауте корректно убивает дерево процессов.
        """
        if not self.bat_path.exists():
            return ZapretResult(
                action=action,
                returncode=-1,
                error=f"service.bat не найден: {self.bat_path}",
            )

        work_dir = cwd or self.zapret_dir

        # CREATE_NO_WINDOW подавляет мигание окна консоли
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            proc = subprocess.Popen(
                ["cmd", "/c", str(self.bat_path), action],
                cwd=str(work_dir),
                stdin=subprocess.DEVNULL,   # pause получит EOF и завершится
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=creationflags,
            )
        except OSError as e:
            return ZapretResult(
                action=action,
                returncode=-1,
                error=f"Не удалось запустить: {e}",
            )

        try:
            stdout_b, stderr_b = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Убиваем дерево процессов
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
        """Убивает процесс и всех его потомков (Windows: taskkill /T /F)."""
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                timeout=10,
            )
        except Exception:
            pass

    # --- Готовые обёртки -----------------------------------------------

    def get_status(self) -> ZapretResult:
        """Статус службы zapret."""
        return self.run("status_zapret", timeout=20)

    def check_updates(self) -> ZapretResult:
        """Проверка обновлений IPSet/hosts через сам bat."""
        return self.run("check_updates", timeout=120)

    def admin_mode(self) -> ZapretResult:
        """Перезапуск service.bat с правами админа (сам bat вызывает UAC)."""
        return self.run("admin", timeout=60)

    # --- Интерактивное меню --------------------------------------------

    def open_console(self) -> None:
        """
        Открывает service.bat в отдельном окне cmd с интерактивным меню.
        Удобно для операций установки/удаления службы,
        диагностики, тестов и т.п.
        """
        if not self.bat_path.exists():
            raise FileNotFoundError(f"service.bat не найден: {self.bat_path}")
        subprocess.Popen(
            ["cmd", "/c", "start", "Zapret service.bat", str(self.bat_path)],
            cwd=str(self.zapret_dir),
            shell=False,
        )

    # --- Повышение прав ------------------------------------------------

    @staticmethod
    def run_as_admin(exe: str, params: str = "", cwd: Path | None = None) -> bool:
        """
        Перезапускает программу с UAC (ShellExecuteW "runas").
        Возвращает True, если пользователь подтвердил UAC.
        Stdout/stderr при этом НЕ захватываются — команда идёт «в отдельном окне».
        """
        try:
            res = ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                exe,
                params,
                str(cwd) if cwd else None,
                1,  # SW_SHOWNORMAL
            )
            # ShellExecuteW возвращает >32 при успехе
            return int(res) > 32
        except Exception:
            return False

    def open_console_as_admin(self) -> bool:
        """Открыть service.bat в отдельном окне с правами администратора."""
        if not self.bat_path.exists():
            raise FileNotFoundError(f"service.bat не найден: {self.bat_path}")
        return self.run_as_admin(
            exe="cmd.exe",
            params=f'/k "{self.bat_path}"',
            cwd=self.zapret_dir,
        )


# --- Быстрый тест при прямом запуске ------------------------------------

if __name__ == "__main__":
    cfg = Config()
    z = ZapretManager(cfg)

    print("service.bat :", z.bat_path)
    print("winws.exe   :", z.winws_path)
    print("Существует  :", z.bat_path.exists())
    print("Установлен  :", z.is_installed())
    print("Админ       :", is_admin())
    print()

    if z.is_installed():
        print("Пробую status_zapret (timeout=20)...")
        res = z.get_status()
        print(res.summary())
        print("--- stdout ---")
        print(res.stdout)
        if res.stderr:
            print("--- stderr ---")
            print(res.stderr)
    else:
        print("zapret ещё не установлен — сначала скачайте релиз через updater.")