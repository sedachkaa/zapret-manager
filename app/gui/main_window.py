"""
Главное окно приложения Zapret Manager.
"""

from __future__ import annotations

import os
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from tkinter import messagebox
from typing import Callable

import customtkinter as ctk

from app.core import autostart, self_updater, updater
from app.core.config import APP_DATA_DIR, APP_INSTALL_DIR, Config
from app.core.tgproxy_manager import TgProxyManager
from app.core.zapret_manager import ZapretManager
from app.version import __version__ as APP_VERSION


WINDOW_TITLE = "Zapret Manager"
WINDOW_SIZE = "1180x880"
MIN_SIZE = (1000, 740)
AUTO_REFRESH_MS = 5000
WRAPPER_CHECK_INTERVAL = 3600
MAX_LOG_LINES = 500

CARD_FG = ("gray92", "gray17")
CARD_BORDER = ("gray80", "gray25")
TILE_FG = ("gray86", "gray20")
STATUS_OK = ("#1f7a1f", "#4cd964")
STATUS_WARN = ("#c47f00", "#ffb340")
STATUS_ERROR = ("#b91c1c", "#ef4444")
STATUS_NEUTRAL = ("gray45", "gray60")

PAD_SECTION = 10
PAD_CARD = 14
PAD_BTN = 6


class MainWindow(ctk.CTk):
    def __init__(self, cfg: Config) -> None:
        super().__init__()

        self.cfg = cfg
        self.zapret = ZapretManager(cfg)
        self.tgproxy = TgProxyManager(cfg)

        # ---- журнал в файл ----
        self.log_dir = APP_DATA_DIR / "logs"
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            self.log_dir = Path(os.environ.get("TEMP", ".")) / "zapret-manager-logs"
            self.log_dir.mkdir(parents=True, exist_ok=True)
        self._session_start = datetime.now()
        self.log_file = self.log_dir / self._session_start.strftime("session_%Y-%m-%d_%H-%M-%S.log")

        # ---- кэш для оптимизации ----
        self._last_zapret_text: str = ""
        self._last_zapret_color: tuple | None = None
        self._last_tgproxy_text: str = ""
        self._last_tgproxy_color: tuple | None = None
        self._last_tgproxy_details: str = ""
        self._last_status_text: str = ""

        ctk.set_appearance_mode(cfg.get("theme", "dark"))
        ctk.set_default_color_theme("blue")

        self.title(f"{WINDOW_TITLE} v{APP_VERSION}")
        self.geometry(WINDOW_SIZE)
        self.minsize(*MIN_SIZE)

        self.after(50, self._maximize_window)

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(1, weight=1)

        self._build_sidebar()
        self._build_header()

        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=1, column=1, padx=16, pady=(0, 8), sticky="nsew")
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        self.tab_zapret = ctk.CTkFrame(self.content, fg_color="transparent")
        self.tab_tgproxy = ctk.CTkFrame(self.content, fg_color="transparent")
        self.tab_updates = ctk.CTkFrame(self.content, fg_color="transparent")
        self.tab_settings = ctk.CTkFrame(self.content, fg_color="transparent")

        self._pages = {
            "zapret": self.tab_zapret,
            "tgproxy": self.tab_tgproxy,
            "updates": self.tab_updates,
            "settings": self.tab_settings,
        }
        for frame in self._pages.values():
            frame.grid(row=0, column=0, sticky="nsew")

        self._build_zapret_tab()
        self._build_tgproxy_tab()
        self._build_updates_tab()
        self._build_settings_tab()
        self._build_status_bar()
        self._show_page("zapret")
        self.set_status(f"Готово. Репозиторий: {cfg.github_repo}")

        self.log("updates", f"=== Сессия запущена: {self._session_start:%Y-%m-%d %H:%M:%S} ===")
        self.log("updates", f"Файл журнала: {self.log_file}")
        self.log("updates", f"Версия: {APP_VERSION}, frozen: {self_updater.is_supported()}")
        self.log("updates", f"GitHub-токен: {'настроен' if updater.has_github_token() else 'не настроен'}")

        self.after(300, self._auto_refresh)
        self.after(800, self._check_first_launch)
        self.after(2500, self._ensure_bundled_config)
        self.after(2000, self._check_wrapper_update_on_start)

    # ============================================================
    #  Управление окном
    # ============================================================

    def _maximize_window(self) -> None:
        try:
            self.state("zoomed")
        except Exception as e:
            print(f"[gui] не удалось максимизировать окно: {e}")

    # ============================================================
    #  Хедер / статус-бар
    # ============================================================

    def _build_sidebar(self) -> None:
        sidebar = ctk.CTkFrame(self, width=210, corner_radius=0,
                               fg_color=("gray90", "gray12"))
        sidebar.grid(row=0, column=0, rowspan=3, sticky="ns")
        sidebar.grid_propagate(False)
        sidebar.grid_rowconfigure(7, weight=1)

        ctk.CTkLabel(sidebar, text="Zapret", anchor="w",
                     font=ctk.CTkFont(size=22, weight="bold")).grid(
            row=0, column=0, padx=20, pady=(22, 0), sticky="ew")
        ctk.CTkLabel(sidebar, text="MANAGER", anchor="w",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=("gray45", "gray60")).grid(
            row=1, column=0, padx=20, pady=(0, 18), sticky="ew")

        self._nav_buttons: dict[str, ctk.CTkButton] = {}
        items = [
            ("zapret", "Zapret"),
            ("tgproxy", "Telegram Proxy"),
            ("updates", "Обновления"),
            ("settings", "Настройки"),
        ]
        for i, (key, label) in enumerate(items, start=2):
            btn = ctk.CTkButton(
                sidebar, text=label, anchor="w",
                command=lambda k=key: self._show_page(k),
                height=40, corner_radius=8,
                fg_color="transparent",
                hover_color=("gray80", "gray22"),
                text_color=("gray20", "gray85"),
                font=ctk.CTkFont(size=13),
            )
            btn.grid(row=i, column=0, padx=12, pady=2, sticky="ew")
            self._nav_buttons[key] = btn

        ctk.CTkLabel(sidebar, text=f"v{APP_VERSION}", anchor="w",
                     text_color=("gray45", "gray60"),
                     font=ctk.CTkFont(size=11)).grid(
            row=8, column=0, padx=20, pady=(0, 16), sticky="w")

    def _show_page(self, name: str) -> None:
        for key, frame in self._pages.items():
            if key == name:
                frame.tkraise()
        for key, btn in self._nav_buttons.items():
            if key == name:
                btn.configure(fg_color=("#2563eb", "#2563eb"),
                              text_color="white")
            else:
                btn.configure(fg_color="transparent",
                              text_color=("gray20", "gray85"))

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, height=64, corner_radius=0)
        header.grid(row=0, column=1, sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        title_block = ctk.CTkFrame(header, fg_color="transparent")
        title_block.grid(row=0, column=0, padx=20, pady=12, sticky="w")
        ctk.CTkLabel(title_block, text="Zapret Manager",
                     font=ctk.CTkFont(size=20, weight="bold")).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(title_block, text="обёртка для zapret-discord-youtube и tg-ws-proxy",
                     font=ctk.CTkFont(size=11),
                     text_color=("gray45", "gray60")).grid(row=1, column=0, sticky="w")

        ctk.CTkLabel(header, text=f"v{APP_VERSION}",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=("gray45", "gray60")).grid(
            row=0, column=2, padx=20, pady=12, sticky="e")

    def _build_status_bar(self) -> None:
        bar = ctk.CTkFrame(self, height=32, corner_radius=0, fg_color=("gray88", "gray14"))
        bar.grid(row=2, column=1, sticky="ew")
        bar.grid_columnconfigure(0, weight=1)
        self.status_bar = ctk.CTkLabel(bar, text="", anchor="w",
                                        text_color=("gray35", "gray70"),
                                        font=ctk.CTkFont(size=11))
        self.status_bar.grid(row=0, column=0, padx=16, pady=4, sticky="ew")

        ctk.CTkLabel(bar, text="by KSD",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=("gray45", "gray55")).grid(
            row=0, column=1, padx=(0, 12), pady=3, sticky="e")

        ctk.CTkButton(bar, text="📂 Открыть журнал", command=self._open_logs_folder,
                      width=150, height=22,
                      font=ctk.CTkFont(size=11)).grid(
            row=0, column=2, padx=(0, 8), pady=3, sticky="e")

    def set_status(self, text: str) -> None:
        if text == self._last_status_text:
            return
        self._last_status_text = text
        self.status_bar.configure(text=text)

    def _open_logs_folder(self) -> None:
        try:
            os.startfile(str(self.log_dir))
        except Exception as e:
            self.set_status(f"Не удалось открыть: {e}")

    def _make_card(self, parent, *, title: str):
        card = ctk.CTkFrame(parent, corner_radius=10, fg_color=CARD_FG,
                            border_width=1, border_color=CARD_BORDER)
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(card, text=title, anchor="w",
                     font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=0, column=0, padx=PAD_CARD + 4, pady=(PAD_CARD, 8), sticky="ew")
        body = ctk.CTkFrame(card, fg_color="transparent")
        body.grid(row=1, column=0, padx=PAD_CARD, pady=(0, PAD_CARD), sticky="ew")
        body.grid_columnconfigure(0, weight=1)
        return card, body

    # ============================================================
    #  Автообновление статусов
    # ============================================================

    def _auto_refresh(self) -> None:
        try:
            self._refresh_zapret_status()
            self._refresh_tgproxy_status()
        except Exception as e:
            print("[auto_refresh] error:", e)
        self.after(AUTO_REFRESH_MS, self._auto_refresh)

    # ============================================================
    #  ВКЛАДКА ZAPRET
    # ============================================================

    def _build_zapret_tab(self) -> None:
        tab = self.tab_zapret
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(4, weight=1)

        status_card = ctk.CTkFrame(tab, corner_radius=10, fg_color=CARD_FG,
                                    border_width=1, border_color=CARD_BORDER)
        status_card.grid(row=0, column=0, padx=PAD_SECTION, pady=(PAD_SECTION, 4), sticky="ew")
        status_card.grid_columnconfigure(1, weight=1)

        self.zapret_indicator = ctk.CTkLabel(
            status_card, text="●", font=ctk.CTkFont(size=18),
            text_color=("gray60", "gray50"))
        self.zapret_indicator.grid(row=0, column=0, padx=(14, 6), pady=(10, 2), sticky="w")

        self.zapret_status = ctk.CTkLabel(
            status_card, text="проверка...", anchor="w",
            font=ctk.CTkFont(size=13, weight="bold"))
        self.zapret_status.grid(row=0, column=1, padx=(0, 12), pady=(10, 2), sticky="ew")

        self.zapret_version_label = ctk.CTkLabel(
            status_card, text="", text_color=("gray45", "gray60"),
            font=ctk.CTkFont(size=12))
        self.zapret_version_label.grid(row=0, column=2, padx=(0, 16), pady=(10, 2), sticky="e")

        self.zapret_strategy_label = ctk.CTkLabel(
            status_card, text="", anchor="w", text_color=("gray45", "gray60"),
            font=ctk.CTkFont(size=11))
        self.zapret_strategy_label.grid(row=1, column=0, columnspan=3,
                                         padx=16, pady=(0, 10), sticky="w")

        self.zapret_buttons: list[ctk.CTkButton] = []

        card, body = self._make_card(tab, title="Управление zapret")
        card.grid(row=1, column=0, padx=PAD_SECTION, pady=4, sticky="ew")

        row = ctk.CTkFrame(body, fg_color="transparent")
        row.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(row, text="Стратегия:", font=ctk.CTkFont(size=12)).grid(
            row=0, column=0, padx=(0, 8), pady=PAD_BTN, sticky="w")

        strategies = [p.stem for p in self.zapret.list_strategies()]
        last = self.cfg.last_strategy
        default_strategy = last if (last and last in strategies) else (strategies[0] if strategies else "—")

        self.strategy_var = ctk.StringVar(value=default_strategy)
        self.strategy_menu = ctk.CTkOptionMenu(
            row, values=strategies or ["—"], variable=self.strategy_var,
            width=200, command=self._on_strategy_changed)
        self.strategy_menu.grid(row=0, column=1, padx=(0, 12), pady=PAD_BTN, sticky="w")

        for i, (label, cmd) in enumerate([
            ("▶  Запустить", self._on_zapret_start),
            ("⏹  Остановить", self._on_zapret_stop),
            ("⟳  Перезапустить", self._on_zapret_restart),
        ]):
            btn = ctk.CTkButton(row, text=label, command=cmd, width=140, height=34,
                                 font=ctk.CTkFont(size=12, weight="bold"))
            btn.grid(row=0, column=i + 2, padx=4, pady=PAD_BTN, sticky="w")
            self.zapret_buttons.append(btn)

        card, body = self._make_card(tab, title="service.bat и папки")
        card.grid(row=2, column=0, padx=PAD_SECTION, pady=4, sticky="ew")

        row = ctk.CTkFrame(body, fg_color="transparent")
        row.grid(row=0, column=0, sticky="ew")

        btn = ctk.CTkButton(
            row, text="⚙  Открыть service.bat", command=self._on_zapret_open_service_bat,
            width=240, height=38, font=ctk.CTkFont(size=13, weight="bold"))
        btn.grid(row=0, column=0, padx=4, pady=PAD_BTN, sticky="w")
        self.zapret_buttons.append(btn)

        for i, (label, cmd) in enumerate([
            ("📁 Папка zapret", self._on_zapret_open_folder),
            ("📁 Папка lists", self._on_zapret_open_lists),
        ]):
            btn = ctk.CTkButton(row, text=label, command=cmd, width=190, height=38)
            btn.grid(row=0, column=i + 1, padx=4, pady=PAD_BTN, sticky="w")
            self.zapret_buttons.append(btn)

        ctk.CTkLabel(tab, text="Журнал:", anchor="w",
                     font=ctk.CTkFont(size=12, weight="bold")).grid(
            row=3, column=0, padx=PAD_SECTION + 6, pady=(6, 0), sticky="w")
        self.zapret_log = ctk.CTkTextbox(tab, wrap="word")
        self.zapret_log.grid(row=4, column=0, padx=PAD_SECTION, pady=(4, PAD_SECTION), sticky="nsew")

    def _on_strategy_changed(self, value: str) -> None:
        if not value or value == "—":
            return
        self.cfg.set("last_strategy", value)
        self.cfg.save()
        self.set_status(f"Стратегия сохранена: {value}")

    def _refresh_strategies_menu(self) -> None:
        try:
            strategies = [p.stem for p in self.zapret.list_strategies()]
            current = self.strategy_var.get()

            self.strategy_menu.configure(values=strategies or ["—"])

            if current not in strategies:
                last = self.cfg.last_strategy
                if last and last in strategies:
                    self.strategy_var.set(last)
                else:
                    self.strategy_var.set(strategies[0] if strategies else "—")
        except Exception as e:
            print(f"[gui] не удалось обновить список стратегий: {e}")

    def _refresh_zapret_status(self) -> None:
        installed = self.zapret.is_installed()
        service_running = self.zapret.is_service_running()
        our_process = self.zapret.is_our_process()
        winws_running = self.zapret.is_winws_running()

        if service_running:
            text, color = "Служба zapret работает", STATUS_OK
        elif our_process:
            pid = self.zapret.get_winws_pid()
            text = f"Standalone запущен (PID {pid})"
            color = STATUS_OK
        elif winws_running:
            pid = self.zapret.get_winws_pid()
            text = f"winws.exe запущен внешне (PID {pid})"
            color = STATUS_OK
        elif not installed:
            text, color = "Не установлен", STATUS_WARN
        else:
            text, color = "Не активен", STATUS_NEUTRAL

        if text != self._last_zapret_text or color != self._last_zapret_color:
            self._last_zapret_text = text
            self._last_zapret_color = color
            self.zapret_status.configure(text=text, text_color=color)
            self.zapret_indicator.configure(text_color=color)

        ver = f"v{self.zapret.get_local_version()}" if installed else ""
        if self.zapret_version_label.cget("text") != ver:
            self.zapret_version_label.configure(text=ver)

        strat = self.zapret.get_active_strategy_name()
        new_strat_text = f"Активная стратегия: {strat}" if (strat and (service_running or winws_running)) else ""
        if self.zapret_strategy_label.cget("text") != new_strat_text:
            self.zapret_strategy_label.configure(text=new_strat_text)

    def _on_zapret_start(self) -> None:
        name = self.strategy_var.get()
        strategy_bat = self.zapret.zapret_dir / f"{name}.bat"
        if not strategy_bat.exists():
            self.log("zapret", f"✗ файл стратегии не найден: {strategy_bat}")
            return
        if self.zapret.is_service_running():
            self.log("zapret", f"→ Служба уже запущена ({self.zapret.get_active_strategy_name() or '?'})")
            self.set_status("Уже запущено")
            return
        self._run_zapret_op(f"Запуск {name}",
                            lambda: self.zapret.start_smart(strategy_bat),
                            with_details=True)

    def _on_zapret_stop(self) -> None:
        if not self.zapret.is_active():
            self.log("zapret", "→ zapret не запущен")
            return
        self._run_zapret_op("Остановка zapret", lambda: self.zapret.stop_smart(), with_details=True)

    def _on_zapret_restart(self) -> None:
        name = self.strategy_var.get()
        strategy_bat = self.zapret.zapret_dir / f"{name}.bat"
        if not strategy_bat.exists():
            self.log("zapret", f"✗ файл стратегии не найден: {strategy_bat}")
            return
        self._run_zapret_op(f"Перезапуск {name}",
                            lambda: self.zapret.restart_smart(strategy_bat), with_details=True)

    def _on_zapret_open_folder(self) -> None:
        if self.zapret.open_folder():
            self.log("zapret", "→ Открыта папка zapret/")
        else:
            self.log("zapret", "✗ Папка zapret/ не найдена")

    def _on_zapret_open_lists(self) -> None:
        if self.zapret.open_lists_folder():
            self.log("zapret", "→ Открыта папка lists/")
        else:
            self.log("zapret", "✗ Папка lists/ не найдена")

    def _on_zapret_open_service_bat(self) -> None:
        res = self.zapret.open_service_bat()
        self.log("zapret", f"→ {res.summary()}")

    def _run_zapret_op(self, title: str, work: Callable,
                       with_details: bool = False,
                       on_done_extra: Callable | None = None) -> None:
        self._run_async(title, work=work,
                        on_done=lambda res: self._after_zapret_op(res, with_details, on_done_extra),
                        tab="zapret")

    def _after_zapret_op(self, res, with_details: bool, on_done_extra: Callable | None) -> None:
        self.log("zapret", f"→ {res.summary()}")
        if with_details and getattr(res, "details", ""):
            self.log("zapret", res.details)
        if on_done_extra:
            try:
                on_done_extra()
            except Exception as e:
                self.log("zapret", f"✗ Ошибка пост-обработки: {e}")
        self._refresh_zapret_status()
        self._refresh_strategies_menu()
        self.set_status("Готово")

    # ============================================================
    #  ВКЛАДКА TELEGRAM PROXY
    # ============================================================

    def _build_tgproxy_tab(self) -> None:
        tab = self.tab_tgproxy
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(3, weight=1)

        status_card = ctk.CTkFrame(tab, corner_radius=10, fg_color=CARD_FG,
                                    border_width=1, border_color=CARD_BORDER)
        status_card.grid(row=0, column=0, padx=PAD_SECTION, pady=(PAD_SECTION, 4), sticky="ew")
        status_card.grid_columnconfigure(1, weight=1)

        self.tgproxy_indicator = ctk.CTkLabel(
            status_card, text="●", font=ctk.CTkFont(size=18),
            text_color=("gray60", "gray50"))
        self.tgproxy_indicator.grid(row=0, column=0, padx=(14, 6), pady=(10, 2), sticky="w")

        self.tgproxy_status = ctk.CTkLabel(
            status_card, text="проверка...", anchor="w",
            font=ctk.CTkFont(size=13, weight="bold"))
        self.tgproxy_status.grid(row=0, column=1, padx=(0, 12), pady=(10, 2), sticky="ew")

        self.tgproxy_details = ctk.CTkLabel(
            status_card, text="", anchor="w", justify="left",
            text_color=("gray45", "gray60"),
            font=ctk.CTkFont(size=11),
            wraplength=1000,
        )
        self.tgproxy_details.grid(row=1, column=0, columnspan=2,
                                   padx=16, pady=(0, 10), sticky="w")

        card, body = self._make_card(tab, title="Управление")
        card.grid(row=1, column=0, padx=PAD_SECTION, pady=4, sticky="ew")
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.grid(row=0, column=0, sticky="ew")

        self.tgproxy_buttons: list[ctk.CTkButton] = []
        for i, (label, cmd) in enumerate([
            ("▶  Запустить", self._on_tgproxy_start),
            ("⏹  Остановить", self._on_tgproxy_stop),
            ("⟳  Перезапустить", self._on_tgproxy_restart),
            ("🔄  Обновить статус", self._on_tgproxy_refresh),
        ]):
            btn = ctk.CTkButton(row, text=label, command=cmd, width=190, height=36,
                                 font=ctk.CTkFont(size=12, weight="bold"))
            btn.grid(row=0, column=i, padx=4, pady=PAD_BTN, sticky="w")
            self.tgproxy_buttons.append(btn)

        ctk.CTkLabel(tab, text="Журнал:", anchor="w",
                     font=ctk.CTkFont(size=12, weight="bold")).grid(
            row=2, column=0, padx=PAD_SECTION + 6, pady=(6, 0), sticky="w")
        self.tgproxy_log = ctk.CTkTextbox(tab, wrap="word")
        self.tgproxy_log.grid(row=3, column=0, padx=PAD_SECTION, pady=(4, PAD_SECTION), sticky="nsew")

    def _refresh_tgproxy_status(self) -> None:
        running = self.tgproxy.is_running()
        installed = self.tgproxy.is_installed()

        if running:
            pid = self.tgproxy.pid
            first = f"Запущен (PID {pid})" if pid else "Запущен"
            color = STATUS_OK
        elif not installed:
            first = "Не установлен"
            color = STATUS_WARN
        else:
            version = self.tgproxy.get_version() or "?"
            first = f"Остановлен (v{version})"
            color = STATUS_NEUTRAL

        if first != self._last_tgproxy_text or color != self._last_tgproxy_color:
            self._last_tgproxy_text = first
            self._last_tgproxy_color = color
            self.tgproxy_status.configure(text=first, text_color=color)
            self.tgproxy_indicator.configure(text_color=color)

    def _on_tgproxy_start(self) -> None:
        res = self.tgproxy.start()
        self.log("tgproxy", f"→ {res.summary()}")
        self._refresh_tgproxy_status()

    def _on_tgproxy_stop(self) -> None:
        res = self.tgproxy.stop()
        self.log("tgproxy", f"→ {res.summary()}")
        self._refresh_tgproxy_status()

    def _on_tgproxy_restart(self) -> None:
        res = self.tgproxy.restart()
        self.log("tgproxy", f"→ {res.summary()}")
        self._refresh_tgproxy_status()

    def _on_tgproxy_refresh(self) -> None:
        self.set_status("Обновление статуса tg-ws-proxy…")
        self._set_buttons_state("tgproxy", False)

        def work():
            return self.tgproxy.get_process_info(full=True)

        def done(procs):
            self._set_buttons_state("tgproxy", True)

            if not procs:
                self._last_tgproxy_details = ""
                self.tgproxy_details.configure(text="")
                self.log("tgproxy", "→ Процессы не найдены")
                self.set_status("Готово")
                return

            lines: list[str] = []
            for p in procs:
                entry = f"PID {p.pid} — {p.name}"
                if p.exe_path:
                    entry += f" | {p.exe_path}"
                if p.start_time:
                    entry += f" | старт: {p.start_time}"
                lines.append(entry)
                self.log("tgproxy", "→ " + entry)

            details_text = "  •  ".join(lines)
            self._last_tgproxy_details = details_text
            self.tgproxy_details.configure(text=details_text)
            self.set_status("Статус обновлён")

        def runner():
            try:
                result = work()
                self.after(0, lambda: done(result))
            except Exception as e:
                err = str(e)
                self.after(0, lambda: self._tgproxy_refresh_error(err))

        threading.Thread(target=runner, daemon=True).start()

    def _tgproxy_refresh_error(self, err: str) -> None:
        self._set_buttons_state("tgproxy", True)
        self.log("tgproxy", f"✗ Ошибка обновления статуса: {err}")
        self.set_status("Ошибка обновления статуса")

    # ============================================================
    #  ВКЛАДКА ОБНОВЛЕНИЯ
    # ============================================================

    def _build_updates_tab(self) -> None:
        tab = self.tab_updates
        tab.grid_columnconfigure(0, weight=1)

        top = ctk.CTkFrame(tab, corner_radius=10, fg_color=CARD_FG,
                           border_width=1, border_color=CARD_BORDER)
        top.grid(row=0, column=0, padx=PAD_SECTION, pady=(PAD_SECTION, 4), sticky="ew")
        top.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(top, text="⬇  Обновления компонентов", anchor="w",
                     font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=0, column=0, padx=PAD_CARD + 4, pady=(PAD_CARD, 4), sticky="w")
        ctk.CTkLabel(top, text="Проверьте наличие новых версий и обновите компоненты в один клик.",
                     anchor="w", font=ctk.CTkFont(size=11),
                     text_color=("gray45", "gray60")).grid(
            row=1, column=0, padx=PAD_CARD + 4, pady=(0, 8), sticky="w")

        btns = ctk.CTkFrame(top, fg_color="transparent")
        btns.grid(row=2, column=0, padx=PAD_CARD, pady=(0, PAD_CARD), sticky="ew")

        self.updates_buttons: list[ctk.CTkButton] = []
        btn = ctk.CTkButton(btns, text="🔍  Проверить всё",
                            command=self._on_check_all, width=200, height=36,
                            font=ctk.CTkFont(size=13, weight="bold"))
        btn.grid(row=0, column=0, padx=4, pady=PAD_BTN, sticky="w")
        self.updates_buttons.append(btn)

        btn = ctk.CTkButton(btns, text="⬇  Обновить всё",
                            command=self._on_update_all, width=200, height=36,
                            font=ctk.CTkFont(size=13, weight="bold"))
        btn.grid(row=0, column=1, padx=4, pady=PAD_BTN, sticky="w")
        self.updates_buttons.append(btn)

        cards = ctk.CTkFrame(tab, fg_color="transparent")
        cards.grid(row=1, column=0, padx=PAD_SECTION, pady=4, sticky="ew")
        cards.grid_columnconfigure((0, 1, 2), weight=1, uniform="cards")

        self.update_cards: dict[str, dict] = {}
        self._make_update_card(cards, key="wrapper", title="📦  Обёртка",
                                col=0, current=APP_VERSION)
        self._make_update_card(cards, key="zapret", title="🛡  zapret-discord-youtube",
                                col=1, current=self.zapret.get_local_version())
        self._make_update_card(cards, key="tgproxy", title="✈  tg-ws-proxy",
                                col=2, current=self.tgproxy.get_version() or "—")

        ctk.CTkLabel(tab, text="Журнал:", anchor="w",
                     font=ctk.CTkFont(size=12, weight="bold")).grid(
            row=2, column=0, padx=PAD_SECTION + 6, pady=(6, 0), sticky="w")
        self.updates_log = ctk.CTkTextbox(tab, wrap="word", height=200)
        self.updates_log.grid(row=3, column=0, padx=PAD_SECTION, pady=(4, PAD_SECTION), sticky="nsew")
        tab.grid_rowconfigure(3, weight=1)

    def _make_update_card(self, parent, *, key: str, title: str, col: int, current: str) -> None:
        card = ctk.CTkFrame(parent, corner_radius=10, fg_color=CARD_FG,
                            border_width=1, border_color=CARD_BORDER)
        card.grid(row=0, column=col, padx=6, pady=4, sticky="nsew")
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(card, text=title, anchor="w",
                     font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=0, column=0, padx=PAD_CARD, pady=(PAD_CARD, 6), sticky="ew")

        row_cur = ctk.CTkFrame(card, fg_color="transparent")
        row_cur.grid(row=1, column=0, padx=PAD_CARD, pady=2, sticky="ew")
        row_cur.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(row_cur, text="Установлено:", anchor="w",
                     text_color=("gray45", "gray60"), font=ctk.CTkFont(size=11)).grid(
            row=0, column=0, sticky="w")
        cur_lbl = ctk.CTkLabel(row_cur, text=current, anchor="e",
                                font=ctk.CTkFont(size=12, weight="bold"))
        cur_lbl.grid(row=0, column=1, sticky="e")

        row_new = ctk.CTkFrame(card, fg_color="transparent")
        row_new.grid(row=2, column=0, padx=PAD_CARD, pady=2, sticky="ew")
        row_new.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(row_new, text="Последняя:", anchor="w",
                     text_color=("gray45", "gray60"), font=ctk.CTkFont(size=11)).grid(
            row=0, column=0, sticky="w")
        new_lbl = ctk.CTkLabel(row_new, text="—", anchor="e",
                                font=ctk.CTkFont(size=12))
        new_lbl.grid(row=0, column=1, sticky="e")

        status_lbl = ctk.CTkLabel(card, text="○  Не проверено", text_color=STATUS_NEUTRAL,
                                   font=ctk.CTkFont(size=11))
        status_lbl.grid(row=3, column=0, padx=PAD_CARD, pady=(8, 4), sticky="w")

        btn = ctk.CTkButton(card, text="⬇  Обновить", width=140, height=32,
                            command=lambda k=key: self._on_update_single(k))
        btn.grid(row=4, column=0, padx=PAD_CARD, pady=(4, PAD_CARD), sticky="ew")
        btn.configure(state="disabled")

        self.update_cards[key] = {
            "current_label": cur_lbl,
            "latest_label": new_lbl,
            "status_label": status_lbl,
            "update_btn": btn,
            "release": None,
        }

    def _get_current_version(self, key: str) -> str:
        if key == "wrapper":
            return APP_VERSION
        if key == "zapret":
            return self.zapret.get_local_version()
        if key == "tgproxy":
            return self.tgproxy.get_version() or ""
        return ""

    def _on_check_all(self) -> None:
        self._run_async("Проверка обновлений", work=self._work_check_all,
                        on_done=self._after_check_all, tab="updates")

    def _work_check_all(self):
        result = {}
        for key, repo in (("wrapper", self.cfg.github_repo),
                          ("zapret", "Flowseal/zapret-discord-youtube"),
                          ("tgproxy", "Flowseal/tg-ws-proxy")):
            try:
                result[key] = updater.fetch_latest_release(repo) if repo else None
            except Exception as e:
                print(f"{key} check error:", e)
                result[key] = None
        return result

    def _after_check_all(self, result: dict) -> None:
        for key, rel in result.items():
            card = self.update_cards[key]
            current = self._get_current_version(key)

            if rel:
                card["latest_label"].configure(text=rel.tag)
                if current and updater.version_matches(current, rel.tag):
                    card["status_label"].configure(text="●  Актуальная версия",
                                                    text_color=STATUS_OK)
                    card["update_btn"].configure(state="disabled")
                    card["release"] = None
                    self.log("updates", f"{key}: актуальная версия {rel.tag}")
                else:
                    if key == "wrapper" and not self_updater.is_supported():
                        card["status_label"].configure(
                            text="●  Доступно (только для .exe)", text_color=STATUS_WARN)
                        card["update_btn"].configure(state="disabled")
                        card["release"] = None
                        self.log("updates", f"{key}: доступна {rel.tag}, но обновление только для .exe")
                    else:
                        card["status_label"].configure(text="●  Доступно обновление",
                                                        text_color=STATUS_WARN)
                        card["update_btn"].configure(state="normal")
                        card["release"] = rel
                        self.log("updates",
                                 f"{key}: доступна {rel.tag} (у вас {current}) — {rel.html_url}")
            else:
                card["latest_label"].configure(text="—")
                msg = "○  Релизов ещё нет" if key == "wrapper" else "○  Нет данных"
                card["status_label"].configure(text=msg, text_color=STATUS_NEUTRAL)
                card["update_btn"].configure(state="disabled")
                card["release"] = None
                self.log("updates", f"{key}: релизов не найдено")
        self.set_status("Проверка завершена")

    def _on_update_single(self, key: str) -> None:
        card = self.update_cards[key]
        release = card.get("release")
        if not release:
            self.log("updates", f"✗ {key}: нет данных о релизе")
            return
        self._run_async(f"Обновление {key}",
                        work=lambda: self._work_update_single(key, release),
                        on_done=self._after_update_single, tab="updates")

    def _work_update_single(self, key: str, release) -> tuple[str, str]:
        try:
            if key == "wrapper":
                if not self_updater.is_supported():
                    return (key, "обновление обёртки доступно только для .exe")
                installer_path = self_updater.download_release(release)
                if not installer_path:
                    return (key, "не удалось скачать обновление")
                res = self_updater.apply_update(installer_path)
                if not res.ok:
                    return (key, res.message)
                return (key, res.message)
            if key == "zapret":
                stop_res = self.zapret.stop_before_update()
                written, skipped = updater.apply_release(
                    release, target_dir=self.zapret.zapret_dir,
                    excludes=self.cfg.exclude_from_update)
                config_res = self.zapret.install_bundled_config()
                return (key, f"zapret обновлён до {release.tag} "
                             f"(w:{written}, s:{skipped}). {stop_res.message}. "
                             f"{config_res.message}")
            if key == "tgproxy":
                res = self.tgproxy.apply_update(release)
                return (key, res.message)
            return (key, "неизвестный компонент")
        except Exception as e:
            import traceback as tb
            tb.print_exc()
            return (key, f"ОШИБКА: {e}")

    def _after_update_single(self, result: tuple[str, str]) -> None:
        key, msg = result
        self.log("updates", f"{key}: {msg}")

        if key == "wrapper":
            if "установка началась" in msg:
                self.set_status("Установка началась. Приложение закроется...")
                self.after(1000, lambda: os._exit(0))
            else:
                self.set_status("Обновление обёртки не удалось")
            return

        if key == "zapret":
            new_ver = self.zapret.get_local_version()
            self.update_cards["zapret"]["current_label"].configure(text=new_ver)
            self.update_cards["zapret"]["status_label"].configure(
                text="○  Обновлено, требуется переустановка службы",
                text_color=STATUS_WARN)
            self._refresh_strategies_menu()
        elif key == "tgproxy":
            self.tgproxy.clear_version_cache()
            new_ver = self.tgproxy.get_version() or "—"
            self.update_cards["tgproxy"]["current_label"].configure(text=new_ver)
            self.update_cards["tgproxy"]["status_label"].configure(
                text="○  Обновлено", text_color=STATUS_OK)

        self._refresh_zapret_status()
        self._refresh_tgproxy_status()
        self.set_status("Готово")

    def _on_update_all(self) -> None:
        self._run_async("Обновление компонентов", work=self._work_update_all,
                        on_done=self._after_update_all, tab="updates")

    def _work_update_all(self):
        log: list[str] = []
        try:
            rel = updater.fetch_latest_release("Flowseal/zapret-discord-youtube")
            if rel:
                self.zapret.stop_before_update()
                written, skipped = updater.apply_release(
                    rel, target_dir=self.zapret.zapret_dir,
                    excludes=self.cfg.exclude_from_update)
                config_res = self.zapret.install_bundled_config()
                log.append(f"zapret → {rel.tag} (w:{written}, s:{skipped}); "
                           f"{config_res.message}")
            else:
                log.append("zapret → релиз не найден")
        except Exception as e:
            log.append(f"zapret → ОШИБКА: {e}")

        try:
            res = self.tgproxy.apply_update()
            log.append(f"tgproxy → {res.message}")
        except Exception as e:
            log.append(f"tgproxy → ОШИБКА: {e}")
        return log

    def _after_update_all(self, log: list[str]) -> None:
        for line in log:
            self.log("updates", "→ " + line)
        self._refresh_zapret_status()
        self._refresh_tgproxy_status()
        self.update_cards["zapret"]["current_label"].configure(
            text=self.zapret.get_local_version())
        self.update_cards["zapret"]["status_label"].configure(
            text="○  Обновлено, требуется переустановка службы", text_color=STATUS_WARN)
        self.tgproxy.clear_version_cache()
        self.update_cards["tgproxy"]["current_label"].configure(
            text=self.tgproxy.get_version() or "—")
        self._refresh_strategies_menu()
        self.set_status("Готово")

    # ============================================================
    #  МАСТЕР ПЕРВОГО ЗАПУСКА
    # ============================================================

    def _check_first_launch(self) -> None:
        if self.cfg.get("first_launch_done", False):
            return

        try:
            if self.zapret.is_installed() and self.tgproxy.is_installed():
                self.cfg.set("first_launch_done", True)
                self.cfg.save()
                self._ensure_bundled_config()
                self.log("updates", "Компоненты уже установлены — подготовка пропущена")
                return
        except Exception as e:
            print(f"[first_launch] ошибка проверки: {e}")

        try:
            from app.gui.first_launch import FirstLaunchDialog
            FirstLaunchDialog(self, self.cfg, self.zapret, self.tgproxy)
            self.log("updates", "Автоматическая подготовка компонентов запущена")
        except Exception as e:
            self.log("updates", f"✗ Не удалось запустить подготовку: {e}")
            self.cfg.set("first_launch_done", True)
            self.cfg.save()

    # ============================================================
    #  АВТОМАТИЧЕСКИЙ РАБОЧИЙ КОНФИГ
    # ============================================================

    def _ensure_bundled_config(self) -> None:
        if not self.cfg.get("first_launch_done", False):
            return
        if not self.zapret.is_installed():
            return
        if self.cfg.get("last_creator_config_version") == APP_VERSION:
            return

        try:
            res = self.zapret.install_bundled_config()
            self.log("zapret", f"→ {res.summary()}")
            if res.ok:
                self._refresh_strategies_menu()
            self.set_status("Рабочий конфиг обновлён")
        except Exception as e:
            self.log("zapret", f"✗ Ошибка установки конфига: {e}")

    # ============================================================
    #  САМООБНОВЛЕНИЕ ОБЁРТКИ
    # ============================================================

    def _check_wrapper_update_on_start(self, *, force: bool = False) -> None:
        if not self_updater.is_supported():
            self.log("updates", "ℹ Обновление обёртки недоступно (запуск из исходников)")
            return

        if not force:
            last_check = self.cfg.get("last_wrapper_check", 0)
            if time.time() - last_check < WRAPPER_CHECK_INTERVAL:
                return

        def work():
            return self_updater.check_for_update(APP_VERSION, self.cfg)

        def done(release):
            self.cfg.set("last_wrapper_check", time.time())
            self.cfg.save()
            if release:
                self._prompt_self_update(release)

        self._run_async("Проверка обновления обёртки", work=work,
                        on_done=done, tab="updates")

    def _prompt_self_update(self, release) -> None:
        msg = (
            f"Доступна новая версия Zapret Manager: {release.tag}\n"
            f"У вас установлена {APP_VERSION}.\n\n"
            f"Обновить сейчас?\n\n"
            f"Приложение закроется, установщик сам заменит файлы "
            f"и запустит новую версию."
        )
        if not messagebox.askyesno("Обновление обёртки", msg, parent=self):
            self.log("updates", f"→ Обновление до {release.tag} отклонено")
            return
        self._run_async(
            "Загрузка обновления",
            work=lambda: self_updater.download_release(
                release,
                progress_cb=self._on_download_progress,
            ),
            on_done=self._after_download_release,
            tab="updates",
        )

    def _on_download_progress(self, percent: float) -> None:
        try:
            self.after(0, lambda p=percent: self.set_status(f"Загрузка обновления: {p:5.1f}%"))
        except Exception:
            pass

    def _after_download_release(self, installer_path) -> None:
        if not installer_path:
            self.log("updates", "✗ Не удалось скачать обновление")
            self.set_status("Ошибка загрузки обновления")
            return

        res = self_updater.apply_update(installer_path)
        self.log("updates", f"→ {res.summary()}")

        if res.ok:
            self.set_status("Установка началась. Приложение закроется...")
            self.after(1000, lambda: os._exit(0))
        else:
            self.set_status("Ошибка обновления — подробности в журнале")

    # ============================================================
    #  ВКЛАДКА НАСТРОЙКИ
    # ============================================================

    def _build_settings_tab(self) -> None:
        tab = self.tab_settings
        tab.grid_columnconfigure(0, weight=1)

        card, body = self._make_card(tab, title="Рабочие папки")
        card.grid(row=0, column=0, padx=PAD_SECTION, pady=(PAD_SECTION, 4), sticky="ew")

        tiles = ctk.CTkFrame(body, fg_color="transparent")
        tiles.grid(row=0, column=0, sticky="ew")
        tiles.grid_columnconfigure((0, 1), weight=1, uniform="tiles")

        self._make_path_tile(
            tiles, col=0,
            icon="📂",
            title="Рабочая папка",
            subtitle="config, logs, zapret, tgproxy",
            path=APP_DATA_DIR,
            command=self._on_open_data_dir,
        )
        self._make_path_tile(
            tiles, col=1,
            icon="💾",
            title="Папка приложения",
            subtitle="exe и библиотеки",
            path=APP_INSTALL_DIR,
            command=self._on_open_install_dir,
        )

        card, body = self._make_card(tab, title="Автозапуск с Windows")
        card.grid(row=1, column=0, padx=PAD_SECTION, pady=4, sticky="ew")

        self.autostart_var = ctk.BooleanVar(value=autostart.is_enabled())
        self.autostart_checkbox = ctk.CTkCheckBox(
            body, text="Запускать Zapret Manager при входе в Windows",
            variable=self.autostart_var, command=self._on_toggle_autostart,
            font=ctk.CTkFont(size=12, weight="bold"))
        self.autostart_checkbox.grid(row=0, column=0, padx=4, pady=(0, 8), sticky="w")

        ctk.CTkLabel(
            body,
            text=("Приложение будет запускаться автоматически при входе в систему. "
                  "Настройка хранится в HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run."),
            anchor="w", justify="left", wraplength=900,
            text_color=("gray45", "gray60"), font=ctk.CTkFont(size=11)).grid(
            row=1, column=0, padx=4, pady=0, sticky="w")

    def _make_path_tile(self, parent, *, col, icon, title, subtitle, path, command) -> None:
        tile = ctk.CTkFrame(parent, corner_radius=10, fg_color=TILE_FG,
                            border_width=1, border_color=CARD_BORDER)
        tile.grid(row=0, column=col, padx=6, pady=4, sticky="nsew")
        tile.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(tile, text=icon, font=ctk.CTkFont(size=26)).grid(
            row=0, column=0, rowspan=2, padx=(14, 10), pady=(14, 0), sticky="n")

        ctk.CTkLabel(tile, text=title, anchor="w",
                     font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=0, column=1, padx=(0, 14), pady=(14, 2), sticky="ew")
        ctk.CTkLabel(tile, text=subtitle, anchor="w",
                     text_color=("gray45", "gray60"), font=ctk.CTkFont(size=10)).grid(
            row=1, column=1, padx=(0, 14), pady=(0, 8), sticky="ew")

        ctk.CTkLabel(tile, text=str(path), anchor="w", justify="left",
                     font=ctk.CTkFont(size=10, family="Consolas"),
                     text_color=("gray30", "gray70"),
                     wraplength=400).grid(
            row=2, column=0, columnspan=2, padx=14, pady=(0, 10), sticky="ew")

        ctk.CTkButton(tile, text="Открыть папку", command=command,
                      width=180, height=32).grid(
            row=3, column=0, columnspan=2, padx=14, pady=(0, 14), sticky="w")

    # ---- Автозапуск ----

    def _on_toggle_autostart(self) -> None:
        desired = self.autostart_var.get()
        if desired:
            ok = autostart.enable()
            if ok:
                self.log("updates", "→ Автозапуск включён")
                self.set_status("Автозапуск включён")
            else:
                self.autostart_var.set(False)
                self.set_status("Не удалось включить автозапуск")
        else:
            ok = autostart.disable()
            if ok:
                self.log("updates", "→ Автозапуск выключен")
                self.set_status("Автозапуск выключен")
            else:
                self.autostart_var.set(True)
                self.set_status("Не удалось выключить автозапуск")

    def _on_open_data_dir(self) -> None:
        try:
            os.startfile(str(APP_DATA_DIR))
        except Exception as e:
            self.set_status(f"Не удалось открыть: {e}")

    def _on_open_install_dir(self) -> None:
        try:
            os.startfile(str(APP_INSTALL_DIR))
        except Exception as e:
            self.set_status(f"Не удалось открыть: {e}")

    # ============================================================
    #  Общие утилиты
    # ============================================================

    def log(self, tab: str, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")

        target = {"zapret": self.zapret_log, "tgproxy": self.tgproxy_log,
                  "updates": self.updates_log}.get(tab)
        if target is not None:
            target.insert("end", message + "\n")
            try:
                total = int(target.index("end-1c").split(".")[0])
                if total > MAX_LOG_LINES:
                    target.delete("1.0", f"{total - MAX_LOG_LINES}.0")
            except Exception:
                pass
            target.see("end")
        else:
            print(f"[log/{tab}] {message}")

        try:
            with self.log_file.open("a", encoding="utf-8") as f:
                for line in message.splitlines() or [""]:
                    f.write(f"[{ts}] [{tab}] {line}\n")
        except OSError as e:
            print(f"[log] не удалось записать в файл: {e}")

    def _set_buttons_state(self, tab: str, enabled: bool) -> None:
        buttons_map = {
            "zapret": getattr(self, "zapret_buttons", []),
            "tgproxy": getattr(self, "tgproxy_buttons", []),
            "updates": getattr(self, "updates_buttons", []),
        }
        for btn in buttons_map.get(tab, []):
            try:
                btn.configure(state="normal" if enabled else "disabled")
            except Exception:
                pass

    def _run_async(self, description: str, work: Callable,
                   on_done: Callable, tab: str) -> None:
        self.set_status(f"{description}...")
        self._set_buttons_state(tab, False)

        def runner() -> None:
            try:
                result = work()
                self.after(0, lambda: self._finish_async(tab, on_done, result, None))
            except Exception as e:
                err = "".join(traceback.format_exception_only(type(e), e)).strip()
                self.after(0, lambda: self._finish_async(tab, on_done, None, err))

        threading.Thread(target=runner, daemon=True).start()

    def _finish_async(self, tab: str, on_done: Callable, result, error: str | None) -> None:
        self._set_buttons_state(tab, True)
        if error:
            self.log(tab, f"✗ Ошибка: {error}")
            self.set_status("Ошибка — подробности в журнале")
            return
        try:
            on_done(result)
        except Exception as e:
            self.log(tab, f"✗ Ошибка обработчика: {e}")
            self.set_status("Ошибка — подробности в журнале")
