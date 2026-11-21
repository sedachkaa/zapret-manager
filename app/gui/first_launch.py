"""
Автоматическая подготовка Zapret Manager при первом запуске.

Окно показывает прогресс и сразу начинает установку без вопросов:
    1. Скачивает последний релиз zapret-discord-youtube.
    2. Устанавливает единственный рабочий конфиг и списки.
    3. Скачивает tg-ws-proxy.
    4. Сохраняет флаг first_launch_done и перезапускает приложение.

Если шаг не удался — предлагает повторить или закрыть окно.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from dataclasses import dataclass

import customtkinter as ctk

from app.core import updater
from app.core.config import Config
from app.core.tgproxy_manager import TgProxyManager
from app.core.zapret_manager import ZapretManager


CARD_FG = ("gray92", "gray17")
CARD_BORDER = ("gray80", "gray25")
STATUS_OK = ("#1f7a1f", "#4cd964")
STATUS_WARN = ("#c47f00", "#ffb340")
STATUS_ERROR = ("#b91c1c", "#ef4444")
STATUS_NEUTRAL = ("gray45", "gray60")


def restart_app(delay_seconds: int = 2) -> None:
    """Перезапускает приложение через указанное число секунд."""
    if getattr(sys, "frozen", False):
        exe = sys.executable
        args = sys.argv[1:]
    else:
        exe = sys.executable
        args = ["-m", "app.main"] + sys.argv[1:]

    cmd_parts = [f'"{exe}"']
    for a in args:
        if " " in a or "\t" in a:
            cmd_parts.append(f'"{a}"')
        else:
            cmd_parts.append(a)
    cmd = " ".join(cmd_parts)

    full = f'cmd /c "timeout /t {delay_seconds} /nobreak >nul & start "" {cmd}"'

    try:
        subprocess.Popen(
            full,
            shell=True,
            creationflags=(
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "DETACHED_PROCESS", 0)
            ),
        )
    except Exception as e:
        print(f"[first_launch] не удалось перезапустить: {e}")

    os._exit(0)


@dataclass
class Step:
    key: str
    title: str


STEPS: list[Step] = [
    Step("download_zapret", "Скачивание zapret-discord-youtube"),
    Step("install_config", "Установка рабочего конфига"),
    Step("download_tgproxy", "Скачивание tg-ws-proxy"),
]


class FirstLaunchDialog(ctk.CTkToplevel):
    """Модальное окно автоматической установки компонентов."""

    def __init__(
        self,
        master,
        cfg: Config,
        zapret: ZapretManager,
        tgproxy: TgProxyManager,
    ) -> None:
        super().__init__(master)

        self.cfg = cfg
        self.zapret = zapret
        self.tgproxy = tgproxy

        self.title("Zapret Manager — подготовка")
        self.geometry("560x420")
        self.resizable(False, False)

        self.transient(master)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._on_close_attempt)
        self.lift()
        self.focus_force()

        self._step_statuses: dict[str, str] = {s.key: "pending" for s in STEPS}
        self._lock_actions = False

        self._build_ui()
        self.after(150, self._start_install)

    # --- UI ------------------------------------------------------------

    def _build_ui(self) -> None:
        header = ctk.CTkFrame(self, height=72, corner_radius=0)
        header.pack(fill="x")
        ctk.CTkLabel(
            header, text="Подготовка к работе",
            font=ctk.CTkFont(size=22, weight="bold"),
        ).pack(padx=24, pady=(16, 2), anchor="w")
        ctk.CTkLabel(
            header,
            text="Компоненты скачиваются автоматически. Это займёт минуту.",
            font=ctk.CTkFont(size=12),
            text_color=("gray45", "gray60"),
        ).pack(padx=24, pady=(0, 12), anchor="w")

        body = ctk.CTkFrame(self, corner_radius=10,
                            fg_color=CARD_FG, border_width=1, border_color=CARD_BORDER)
        body.pack(fill="x", padx=20, pady=(0, 12))

        self._step_widgets: dict[str, ctk.CTkLabel] = {}
        for step in STEPS:
            row = ctk.CTkFrame(body, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=5)
            row.grid_columnconfigure(1, weight=1)

            status_icon = ctk.CTkLabel(
                row, text="○", width=24,
                font=ctk.CTkFont(size=16),
                text_color=STATUS_NEUTRAL,
            )
            status_icon.grid(row=0, column=0, padx=(0, 8), sticky="w")

            ctk.CTkLabel(
                row, text=step.title, anchor="w",
                font=ctk.CTkFont(size=12),
            ).grid(row=0, column=1, sticky="ew")

            self._step_widgets[step.key] = status_icon

        progress_frame = ctk.CTkFrame(self, fg_color="transparent")
        progress_frame.pack(fill="x", padx=20, pady=(0, 8))

        self._progress = ctk.CTkProgressBar(progress_frame, height=12)
        self._progress.pack(fill="x", pady=(0, 8))
        self._progress.set(0)

        self._status_label = ctk.CTkLabel(
            progress_frame, text="Подготовка…",
            anchor="w", font=ctk.CTkFont(size=11),
            text_color=("gray45", "gray60"),
        )
        self._status_label.pack(fill="x")

        self._buttons = ctk.CTkFrame(self, fg_color="transparent")
        self._buttons.pack(fill="x", padx=20, pady=(8, 20))

        self._close_button = ctk.CTkButton(
            self._buttons, text="Закрыть",
            command=self._on_close_attempt,
            width=160, height=40,
            fg_color=("gray75", "gray28"),
            hover_color=("gray65", "gray35"),
        )
        self._retry_button = ctk.CTkButton(
            self._buttons, text="Повторить",
            command=self._start_install,
            width=200, height=40,
            font=ctk.CTkFont(size=13, weight="bold"),
        )

    # --- Управление ----------------------------------------------------

    def _on_close_attempt(self) -> None:
        if self._lock_actions:
            return
        self.cfg.set("first_launch_done", True)
        self.cfg.save()
        self.grab_release()
        self.destroy()

    def _start_install(self) -> None:
        if self._lock_actions:
            return

        self._lock_actions = True
        self._retry_button.pack_forget()
        self._close_button.pack_forget()
        self._progress.set(0)
        self._status_label.configure(text="Подготовка…", text_color=("gray45", "gray60"))

        for step in STEPS:
            self._step_statuses[step.key] = "pending"
            self._step_widgets[step.key].configure(text="○", text_color=STATUS_NEUTRAL)

        threading.Thread(target=self._run_all_steps, daemon=True).start()

    # --- Установка -----------------------------------------------------

    def _run_all_steps(self) -> None:
        total = len(STEPS)
        for i, step in enumerate(STEPS):
            self.after(0, lambda s=step: self._mark_running(s.key))

            ok, message = self._execute_step(step.key)

            self.after(0, lambda s=step, ok=ok, msg=message:
                       self._mark_done(s.key, ok, msg))

            if not ok:
                self.after(0, lambda msg=message: self._show_error(msg))
                return

            progress = (i + 1) / total
            self.after(0, lambda p=progress: self._progress.set(p))

        self.after(0, self._on_success)

    def _execute_step(self, key: str) -> tuple[bool, str]:
        try:
            if key == "download_zapret":
                return self._step_download_zapret()
            if key == "install_config":
                res = self.zapret.install_bundled_config()
                return (res.ok, res.message)
            if key == "download_tgproxy":
                return self._step_download_tgproxy()
        except Exception as e:
            import traceback as tb
            tb.print_exc()
            return (False, f"Ошибка: {e}")
        return (False, "Неизвестный шаг")

    def _step_download_zapret(self) -> tuple[bool, str]:
        if self.zapret.is_installed():
            return (True, "zapret уже установлен")

        release = updater.check_zapret_update(self.cfg)
        if release is None:
            return (
                False,
                "Не удалось получить релиз zapret с GitHub. "
                "Проверьте подключение к интернету и нажмите «Повторить».",
            )

        try:
            written, skipped = updater.apply_release(
                release,
                target_dir=self.zapret.zapret_dir,
                excludes=self.cfg.exclude_from_update,
            )
        except Exception as e:
            return (False, f"Не удалось скачать или распаковать zapret: {e}")

        return (True, f"zapret {release.tag} — скачано {written} файлов")

    def _step_download_tgproxy(self) -> tuple[bool, str]:
        if self.tgproxy.is_installed():
            return (True, "tg-ws-proxy уже установлен")

        res = self.tgproxy.apply_update()
        if not res.ok:
            return (False, res.message)
        return (True, res.message)

    # --- Обновление UI -------------------------------------------------

    def _mark_running(self, key: str) -> None:
        self._step_statuses[key] = "running"
        self._step_widgets[key].configure(text="◔", text_color=STATUS_WARN)
        title = next((s.title for s in STEPS if s.key == key), key)
        self._status_label.configure(text=f"{title}…")

    def _mark_done(self, key: str, ok: bool, message: str) -> None:
        self._step_statuses[key] = "done" if ok else "error"
        if ok:
            self._step_widgets[key].configure(text="✓", text_color=STATUS_OK)
            self._status_label.configure(text=message)
        else:
            self._step_widgets[key].configure(text="✗", text_color=STATUS_ERROR)
            self._status_label.configure(text=f"Ошибка: {message}", text_color=STATUS_ERROR)

    def _show_error(self, message: str) -> None:
        self._lock_actions = False
        self._status_label.configure(text=f"Ошибка: {message}", text_color=STATUS_ERROR)
        self._retry_button.pack(side="right")
        self._close_button.pack(side="left")

    def _on_success(self) -> None:
        self._progress.set(1.0)
        self._status_label.configure(
            text="Готово. Перезапуск приложения…",
            text_color=STATUS_OK,
        )

        self.cfg.set("first_launch_done", True)
        self.cfg.save()

        self.after(1800, lambda: restart_app(delay_seconds=2))
