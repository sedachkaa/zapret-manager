"""
Мастер первого запуска Zapret Manager.

Показывается один раз — при первом старте собранного .exe,
если в config.json first_launch_done = False.

Что делает:
    1. Скачивает последний релиз zapret-discord-youtube.
    2. Устанавливает службу zapret с дефолтной стратегией.
    3. Скачивает tg-ws-proxy.
    4. Сохраняет флаг first_launch_done = true.
    5. Перезапускает приложение.

Если на каком-то шаге ошибка — показывает её и предлагает
повторить или пропустить (тогда флаг всё равно ставится,
чтобы не мучить пользователя при каждом запуске).
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from tkinter import messagebox
from typing import Callable

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


# --- Перезапуск --------------------------------------------------------

def restart_app(delay_seconds: int = 2) -> None:
    """
    Перезапускает приложение через указанное число секунд.

    Работает и для собранного .exe, и для запуска из исходников:
        - .exe (frozen): запускаем sys.executable без аргументов.
        - исходники: перезапускаем `python -m app.main`.
    """
    if getattr(sys, "frozen", False):
        exe = sys.executable
        args = sys.argv[1:]
    else:
        exe = sys.executable
        args = ["-m", "app.main"] + sys.argv[1:]

    # Собираем команду
    cmd_parts = [f'"{exe}"']
    for a in args:
        if " " in a or "\t" in a:
            cmd_parts.append(f'"{a}"')
        else:
            cmd_parts.append(a)
    cmd = " ".join(cmd_parts)

    # Отложенный запуск через cmd: наш процесс успеет завершиться,
    # а затем новый стартует в свежей оболочке.
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


# --- Описание шагов ----------------------------------------------------

@dataclass
class Step:
    key: str
    title: str
    icon: str


STEPS: list[Step] = [
    Step("download_zapret", "Скачать zapret-discord-youtube", "⬇️"),
    Step("install_service", "Установить службу zapret (general)", "🛡"),
    Step("download_tgproxy", "Скачать tg-ws-proxy", "✈️"),
]


# --- Диалог ------------------------------------------------------------

class FirstLaunchDialog(ctk.CTkToplevel):
    """
    Модальное окно установки компонентов при первом запуске.
    """

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

        self.title("Zapret Manager — первый запуск")
        self.geometry("620x560")
        self.resizable(False, False)

        # Модальное окно
        self.transient(master)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._on_close_attempt)
        self.lift()
        self.focus_force()

        # Состояние
        self._step_statuses: dict[str, str] = {s.key: "pending" for s in STEPS}
        self._current_step: str = ""
        self._lock_actions = False

        self._build_ui()

    # --- UI ------------------------------------------------------------

    def _build_ui(self) -> None:
        # Заголовок
        header = ctk.CTkFrame(self, height=64, corner_radius=0)
        header.pack(fill="x")
        ctk.CTkLabel(
            header, text="🚀  Первый запуск",
            font=ctk.CTkFont(size=22, weight="bold"),
        ).pack(padx=24, pady=(16, 4), anchor="w")
        ctk.CTkLabel(
            header,
            text="Установим компоненты, которые нужны для работы приложения.",
            font=ctk.CTkFont(size=12),
            text_color=("gray45", "gray60"),
        ).pack(padx=24, pady=(0, 12), anchor="w")

        # Карточка шагов
        body = ctk.CTkFrame(self, corner_radius=10,
                            fg_color=CARD_FG, border_width=1, border_color=CARD_BORDER)
        body.pack(fill="x", padx=20, pady=(0, 12))

        ctk.CTkLabel(
            body, text="Будет установлено:",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(padx=16, pady=(14, 8), anchor="w")

        self._step_widgets: dict[str, tuple[ctk.CTkLabel, ctk.CTkLabel]] = {}
        for step in STEPS:
            row = ctk.CTkFrame(body, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=4)
            row.grid_columnconfigure(1, weight=1)

            status_icon = ctk.CTkLabel(
                row, text="○",
                font=ctk.CTkFont(size=16),
                width=24,
                text_color=STATUS_NEUTRAL,
            )
            status_icon.grid(row=0, column=0, padx=(0, 8), sticky="w")

            title_text = f"{step.icon}  {step.title}"
            title_label = ctk.CTkLabel(
                row, text=title_text, anchor="w",
                font=ctk.CTkFont(size=12),
            )
            title_label.grid(row=0, column=1, sticky="ew")

            self._step_widgets[step.key] = (status_icon, title_label)

        # Прогресс-бар и статус
        progress_frame = ctk.CTkFrame(self, fg_color="transparent")
        progress_frame.pack(fill="x", padx=20, pady=(0, 8))

        self._progress = ctk.CTkProgressBar(progress_frame, height=12)
        self._progress.pack(fill="x", pady=(0, 8))
        self._progress.set(0)

        self._status_label = ctk.CTkLabel(
            progress_frame, text="Готово к установке",
            anchor="w", font=ctk.CTkFont(size=11),
            text_color=("gray45", "gray60"),
        )
        self._status_label.pack(fill="x")

        # Кнопки
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=20, pady=(8, 20))

        self._skip_button = ctk.CTkButton(
            buttons, text="Пропустить",
            command=self._on_skip,
            width=160, height=40,
            fg_color=("gray75", "gray28"),
            hover_color=("gray65", "gray35"),
        )
        self._skip_button.pack(side="left")

        self._install_button = ctk.CTkButton(
            buttons, text="⬇  Установить",
            command=self._on_install,
            width=220, height=40,
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self._install_button.pack(side="right")

    # --- Обработчики кнопок --------------------------------------------

    def _on_close_attempt(self) -> None:
        """Крестик: если установка идёт — не закрываем. Иначе — пропустить."""
        if self._lock_actions:
            return
        self._on_skip()

    def _on_skip(self) -> None:
        """Пользователь отказался от установки. Ставим флаг и закрываем окно."""
        if self._lock_actions:
            return
        self.cfg.set("first_launch_done", True)
        self.cfg.save()
        self.grab_release()
        self.destroy()

    def _on_install(self) -> None:
        """Запуск установки в фоновом потоке."""
        if self._lock_actions:
            return

        self._lock_actions = True
        self._install_button.configure(state="disabled")
        self._skip_button.configure(state="disabled")
        self._progress.set(0)

        threading.Thread(target=self._run_all_steps, daemon=True).start()

    # --- Установка -----------------------------------------------------

    def _run_all_steps(self) -> None:
        """Проходит по всем шагам последовательно."""
        total = len(STEPS)
        for i, step in enumerate(STEPS):
            self.after(0, lambda s=step: self._mark_running(s.key))

            ok, message = self._execute_step(step.key)

            self.after(0, lambda s=step, ok=ok, msg=message:
                       self._mark_done(s.key, ok, msg))

            if not ok:
                # Ошибка — показываем и останавливаемся.
                self.after(0, lambda s=step, msg=message: self._show_error(s, msg))
                return

            # Прогресс-бар
            progress = (i + 1) / total
            self.after(0, lambda p=progress: self._progress.set(p))

        # Всё готово
        self.after(0, self._on_success)

    def _execute_step(self, key: str) -> tuple[bool, str]:
        """Выполняет один шаг. Возвращает (успех, сообщение)."""
        try:
            if key == "download_zapret":
                return self._step_download_zapret()
            if key == "install_service":
                return self._step_install_service()
            if key == "download_tgproxy":
                return self._step_download_tgproxy()
        except Exception as e:
            import traceback as tb
            tb.print_exc()
            return (False, f"Ошибка: {e}")
        return (False, "Неизвестный шаг")

    # --- Реализация шагов ----------------------------------------------

    def _step_download_zapret(self) -> tuple[bool, str]:
        # Если уже установлено — ничего не качаем
        if self.zapret.is_installed():
            return (True, "zapret уже установлен")

        release = updater.check_zapret_update(self.cfg)
        if release is None:
            return (False, "Не удалось получить информацию о релизе zapret")

        written, skipped = updater.apply_release(
            release,
            target_dir=self.zapret.zapret_dir,
            excludes=self.cfg.exclude_from_update,
        )
        return (True, f"zapret {release.tag} — скачано {written} файлов")

    def _step_install_service(self) -> tuple[bool, str]:
        # Если служба уже работает — пропускаем
        if self.zapret.is_service_running():
            return (True, "служба zapret уже работает")

        strategies = self.zapret.list_strategies()
        if not strategies:
            return (False, "Не найдены .bat-стратегии — возможно, zapret не скачался")

        # Ищем general.bat без суффиксов
        strategy_bat = None
        for s in strategies:
            if s.stem.lower() == "general":
                strategy_bat = s
                break
        if strategy_bat is None:
            strategy_bat = strategies[0]

        res = self.zapret.install_service(strategy_bat)
        if not res.ok:
            return (False, res.message)
        return (True, f"служба zapret запущена со стратегией {strategy_bat.stem}")

    def _step_download_tgproxy(self) -> tuple[bool, str]:
        if self.tgproxy.is_installed():
            return (True, "tg-ws-proxy уже установлен")

        res = self.tgproxy.apply_update()
        if not res.ok:
            return (False, res.message)
        return (True, res.message)

    # --- Обновление UI из главного потока ------------------------------

    def _mark_running(self, key: str) -> None:
        self._step_statuses[key] = "running"
        icon, title = self._step_widgets[key]
        icon.configure(text="◔", text_color=STATUS_WARN)
        self._current_step = key
        title_text = next((s.title for s in STEPS if s.key == key), key)
        self._status_label.configure(text=f"Выполняется: {title_text}…")

    def _mark_done(self, key: str, ok: bool, message: str) -> None:
        self._step_statuses[key] = "done" if ok else "error"
        icon, _ = self._step_widgets[key]
        if ok:
            icon.configure(text="✓", text_color=STATUS_OK)
            self._status_label.configure(text=message)
        else:
            icon.configure(text="✗", text_color=STATUS_ERROR)
            self._status_label.configure(text=f"Ошибка: {message}")

    def _show_error(self, step: Step, message: str) -> None:
        self._lock_actions = False
        self._install_button.configure(text="↻  Повторить", state="normal")
        self._skip_button.configure(text="Пропустить", state="normal")

        messagebox.showerror(
            "Ошибка установки",
            f"Шаг «{step.title}» не выполнен:\n\n{message}\n\n"
            f"Нажмите «Повторить», чтобы попробовать снова, "
            f"или «Пропустить», чтобы продолжить без этого компонента.",
            parent=self,
        )

    def _on_success(self) -> None:
        self._progress.set(1.0)
        self._status_label.configure(
            text="Всё установлено! Перезапуск приложения через пару секунд…",
            text_color=STATUS_OK,
        )

        # Убираем кнопки — они больше не нужны
        self._install_button.pack_forget()
        self._skip_button.pack_forget()

        # Ставим флаг, что мастер пройден
        self.cfg.set("first_launch_done", True)
        self.cfg.save()

        # Перезапуск
        self.after(2000, lambda: restart_app(delay_seconds=2))