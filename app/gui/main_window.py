"""
Главное окно приложения Zapret Manager.
"""

from __future__ import annotations

import os
import threading
import traceback
from datetime import datetime
from pathlib import Path
from tkinter import filedialog
from typing import Callable

import customtkinter as ctk

from app.core import autostart, updater
from app.core.config import PROJECT_ROOT, Config
from app.core.tgproxy_manager import TgProxyManager
from app.core.zapret_manager import ZapretManager


WINDOW_TITLE = "Zapret Manager"
WINDOW_SIZE = "1100x820"
MIN_SIZE = (940, 700)
APP_VERSION = "0.1.0"
AUTO_REFRESH_MS = 3000

CARD_FG = ("gray92", "gray17")
CARD_BORDER = ("gray80", "gray25")
STATUS_OK = ("#1f7a1f", "#4cd964")
STATUS_WARN = ("#c47f00", "#ffb340")
STATUS_NEUTRAL = ("gray45", "gray60")


class MainWindow(ctk.CTk):
    def __init__(self, cfg: Config) -> None:
        super().__init__()

        self.cfg = cfg
        self.zapret = ZapretManager(cfg)
        self.tgproxy = TgProxyManager(cfg)

        # ---- журнал в файл ----
        self.log_dir = PROJECT_ROOT / "logs"
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            self.log_dir = Path(os.environ.get("TEMP", ".")) / "zapret-manager-logs"
            self.log_dir.mkdir(parents=True, exist_ok=True)
        self._session_start = datetime.now()
        self.log_file = self.log_dir / self._session_start.strftime("session_%Y-%m-%d_%H-%M-%S.log")

        ctk.set_appearance_mode(cfg.get("theme", "dark"))
        ctk.set_default_color_theme("blue")

        self.title(f"{WINDOW_TITLE} v{APP_VERSION}")
        self.geometry(WINDOW_SIZE)
        self.minsize(*MIN_SIZE)
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._build_header()

        self.tabview = ctk.CTkTabview(self, corner_radius=12)
        self.tabview.grid(row=1, column=0, padx=16, pady=(0, 8), sticky="nsew")

        self.tab_zapret = self.tabview.add("🛡  Zapret")
        self.tab_tgproxy = self.tabview.add("✈  Telegram Proxy")
        self.tab_updates = self.tabview.add("⬇  Обновления")
        self.tab_settings = self.tabview.add("⚙  Настройки")

        self._build_zapret_tab()
        self._build_tgproxy_tab()
        self._build_updates_tab()
        self._build_settings_tab()
        self._build_status_bar()
        self.set_status(f"Готово. Репозиторий: {cfg.github_repo}")

        self.log("updates", f"=== Сессия запущена: {self._session_start:%Y-%m-%d %H:%M:%S} ===")
        self.log("updates", f"Файл журнала: {self.log_file}")

        self.after(300, self._auto_refresh)

    # ============================================================
    #  Хедер / статус-бар
    # ============================================================

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, height=64, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        title_block = ctk.CTkFrame(header, fg_color="transparent")
        title_block.grid(row=0, column=0, padx=20, pady=12, sticky="w")
        ctk.CTkLabel(title_block, text="Zapret Manager",
                     font=ctk.CTkFont(size=22, weight="bold")).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(title_block, text="обёртка для zapret-discord-youtube и tg-ws-proxy",
                     font=ctk.CTkFont(size=11),
                     text_color=("gray45", "gray60")).grid(row=1, column=0, sticky="w")

        ctk.CTkLabel(header, text=f"v{APP_VERSION}",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=("gray45", "gray60")).grid(row=0, column=2, padx=20, pady=12, sticky="e")

    def _build_status_bar(self) -> None:
        bar = ctk.CTkFrame(self, height=32, corner_radius=0, fg_color=("gray88", "gray14"))
        bar.grid(row=2, column=0, sticky="ew")
        bar.grid_columnconfigure(0, weight=1)
        self.status_bar = ctk.CTkLabel(bar, text="", anchor="w",
                                        text_color=("gray35", "gray70"),
                                        font=ctk.CTkFont(size=11))
        self.status_bar.grid(row=0, column=0, padx=16, pady=4, sticky="ew")

        ctk.CTkButton(bar, text="📂 Открыть журнал", command=self._open_logs_folder,
                      width=150, height=22,
                      font=ctk.CTkFont(size=11)).grid(
            row=0, column=1, padx=(0, 8), pady=3, sticky="e")

    def set_status(self, text: str) -> None:
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
                     font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=0, column=0, padx=16, pady=(12, 6), sticky="ew")
        body = ctk.CTkFrame(card, fg_color="transparent")
        body.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="ew")
        body.grid_columnconfigure(0, weight=1)
        return card, body

    # ============================================================
    #  Автообновление статусов
    # ============================================================

    def _auto_refresh(self) -> None:
        try:
            self._refresh_zapret_status()
            self._refresh_zapret_toggles()
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
        tab.grid_rowconfigure(1, weight=1)

        status_card = ctk.CTkFrame(tab, corner_radius=10, fg_color=CARD_FG,
                                    border_width=1, border_color=CARD_BORDER)
        status_card.grid(row=0, column=0, padx=8, pady=(8, 6), sticky="ew")
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

        scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent", corner_radius=0)
        scroll.grid(row=1, column=0, padx=0, pady=0, sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)

        self.zapret_buttons: list[ctk.CTkButton] = []

        # --- ЗАПУСК И СЛУЖБА (умные кнопки) ---
        card, body = self._make_card(scroll, title="🛡  Управление zapret")
        card.grid(row=0, column=0, padx=8, pady=6, sticky="ew")

        row = ctk.CTkFrame(body, fg_color="transparent")
        row.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(row, text="Стратегия:").grid(row=0, column=0, padx=(4, 6), pady=4, sticky="w")

        # Подтягиваем сохранённую стратегию
        strategies = [p.stem for p in self.zapret.list_strategies()]
        last = self.cfg.last_strategy
        if last and last in strategies:
            default_strategy = last
        else:
            default_strategy = strategies[0] if strategies else "—"

        self.strategy_var = ctk.StringVar(value=default_strategy)
        self.strategy_menu = ctk.CTkOptionMenu(
            row,
            values=strategies or ["—"],
            variable=self.strategy_var,
            width=280,
            command=self._on_strategy_changed,
        )
        self.strategy_menu.grid(row=0, column=1, padx=4, pady=4, sticky="w")

        # Умные кнопки
        for i, (label, cmd) in enumerate([
            ("▶  Запустить", self._on_zapret_start),
            ("⏹  Остановить", self._on_zapret_stop),
            ("⟳  Перезапустить", self._on_zapret_restart),
        ]):
            btn = ctk.CTkButton(row, text=label, command=cmd, width=170, height=34,
                                 font=ctk.CTkFont(size=12, weight="bold"))
            btn.grid(row=0, column=i + 2, padx=4, pady=4, sticky="w")
            self.zapret_buttons.append(btn)

        # --- ФИЛЬТРЫ ---
        card, body = self._make_card(scroll, title="🎛  Фильтры")
        card.grid(row=1, column=0, padx=8, pady=6, sticky="ew")
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.grid(row=0, column=0, sticky="ew")

        ctk.CTkLabel(row, text="Game Filter:").grid(row=0, column=0, padx=(4, 6), pady=4, sticky="w")
        self.game_filter_var = ctk.StringVar(value="disabled")
        self.game_filter_menu = ctk.CTkOptionMenu(
            row, values=["disabled", "all (TCP+UDP)", "TCP only", "UDP only"],
            variable=self.game_filter_var, width=200)
        self.game_filter_menu.grid(row=0, column=1, padx=4, pady=4, sticky="w")
        btn = ctk.CTkButton(row, text="Применить", command=self._on_zapret_apply_game_filter,
                            width=140, height=32)
        btn.grid(row=0, column=2, padx=4, pady=4, sticky="w")
        self.zapret_buttons.append(btn)

        ctk.CTkLabel(row, text="IPSet:").grid(row=0, column=3, padx=(20, 6), pady=4, sticky="w")
        self.ipset_status_label = ctk.CTkLabel(row, text="?", width=80, anchor="w",
                                                font=ctk.CTkFont(weight="bold"))
        self.ipset_status_label.grid(row=0, column=4, padx=(0, 6), pady=4, sticky="w")
        btn = ctk.CTkButton(row, text="Toggle", command=self._on_zapret_toggle_ipset,
                            width=100, height=32)
        btn.grid(row=0, column=5, padx=4, pady=4, sticky="w")
        self.zapret_buttons.append(btn)

        # --- FAKES ---
        card, body = self._make_card(scroll, title="🎭  Активные fakes")
        card.grid(row=2, column=0, padx=8, pady=6, sticky="ew")
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.grid(row=0, column=0, sticky="ew")

        ctk.CTkLabel(row, text="Тип:").grid(row=0, column=0, padx=(4, 6), pady=4, sticky="w")
        self.fake_type_var = ctk.StringVar(value="Discord UDP")
        self.fake_type_menu = ctk.CTkOptionMenu(
            row, values=["Discord UDP", "GameFilter UDP"],
            variable=self.fake_type_var, width=170)
        self.fake_type_menu.grid(row=0, column=1, padx=4, pady=4, sticky="w")
        ctk.CTkLabel(row, text="Файл:").grid(row=0, column=2, padx=(20, 6), pady=4, sticky="w")
        self.fake_file_var = ctk.StringVar(value="—")
        self.fake_file_menu = ctk.CTkOptionMenu(
            row, values=["—"], variable=self.fake_file_var, width=280)
        self.fake_file_menu.grid(row=0, column=3, padx=4, pady=4, sticky="w")
        btn = ctk.CTkButton(row, text="Заменить", command=self._on_zapret_replace_fake,
                            width=140, height=32)
        btn.grid(row=0, column=4, padx=4, pady=4, sticky="w")
        self.zapret_buttons.append(btn)

        # --- ИНСТРУМЕНТЫ ---
        card, body = self._make_card(scroll, title="🛠  Инструменты")
        card.grid(row=3, column=0, padx=8, pady=6, sticky="ew")
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.grid(row=0, column=0, sticky="ew")
        for i, (label, cmd) in enumerate([
            ("ℹ Check Status", self._on_zapret_status),
            ("🩺 Diagnostics", self._on_zapret_diagnostics),
            ("🧪 Run Tests", self._on_zapret_run_tests),
        ]):
            btn = ctk.CTkButton(row, text=label, command=cmd, width=170, height=32)
            btn.grid(row=0, column=i, padx=4, pady=4, sticky="w")
            self.zapret_buttons.append(btn)

        row2 = ctk.CTkFrame(body, fg_color="transparent")
        row2.grid(row=1, column=0, pady=(4, 0), sticky="ew")
        for i, (label, cmd) in enumerate([
            ("📁 Папка zapret", self._on_zapret_open_folder),
            ("📁 Папка lists", self._on_zapret_open_lists),
            ("📝 list-general.txt", self._on_zapret_edit_main_list),
            ("📝 user-листы", self._on_zapret_edit_lists),
        ]):
            btn = ctk.CTkButton(row2, text=label, command=cmd, width=210, height=32)
            btn.grid(row=0, column=i, padx=4, pady=4, sticky="w")
            self.zapret_buttons.append(btn)

        # Журнал
        ctk.CTkLabel(tab, text="Журнал:", anchor="w",
                     font=ctk.CTkFont(size=12, weight="bold")).grid(
            row=2, column=0, padx=16, pady=(8, 0), sticky="w")
        self.zapret_log = ctk.CTkTextbox(tab, wrap="word", height=140)
        self.zapret_log.grid(row=3, column=0, padx=8, pady=(4, 8), sticky="nsew")
        tab.grid_rowconfigure(3, weight=1)

        self._refresh_zapret_toggles()
        self._refresh_fake_menu()

    # ---- обработчик смены стратегии ----

    def _on_strategy_changed(self, value: str) -> None:
        """Сохраняем последнюю выбранную стратегию в config.json."""
        if not value or value == "—":
            return
        self.cfg.set("last_strategy", value)
        self.cfg.save()
        self.set_status(f"Стратегия сохранена: {value}")

    # ---- обновление UI Zapret ----

    def _refresh_zapret_status(self) -> None:
        if not self.zapret.is_installed():
            self.zapret_status.configure(text="не установлен", text_color=STATUS_WARN)
            self.zapret_version_label.configure(text="")
            self.zapret_strategy_label.configure(text="")
            self.zapret_indicator.configure(text_color=("gray60", "gray50"))
            return

        if self.zapret.is_service_running():
            text, color = "Служба zapret работает", STATUS_OK
        elif self.zapret.is_our_process():
            pid = self.zapret.get_winws_pid()
            text = f"Standalone запущен (PID {pid})"
            color = STATUS_OK
        elif self.zapret.is_winws_running():
            pid = self.zapret.get_winws_pid()
            text = f"winws.exe запущен внешне (PID {pid})"
            color = STATUS_OK
        else:
            text, color = "Не активен", STATUS_NEUTRAL

        self.zapret_status.configure(text=text, text_color=color)
        self.zapret_indicator.configure(text_color=color)
        self.zapret_version_label.configure(text=f"v{self.zapret.get_local_version()}")

        strat = self.zapret.get_active_strategy_name()
        if strat and self.zapret.is_active():
            self.zapret_strategy_label.configure(text=f"Активная стратегия: {strat}")
        else:
            self.zapret_strategy_label.configure(text="")

    def _refresh_zapret_toggles(self) -> None:
        gf = self.zapret.get_game_filter_status()
        mapping = {"disabled": "disabled", "all": "all (TCP+UDP)",
                   "tcp": "TCP only", "udp": "UDP only"}
        self.game_filter_var.set(mapping.get(gf, "disabled"))

        ipset = self.zapret.get_ipset_status()
        self.ipset_status_label.configure(text=ipset)
        color = STATUS_OK if ipset == "loaded" else STATUS_NEUTRAL
        self.ipset_status_label.configure(text_color=color)

    def _refresh_fake_menu(self) -> None:
        fakes = [p.name for p in self.zapret.list_fakes()]
        if fakes:
            self.fake_file_menu.configure(values=fakes)
            self.fake_file_var.set(fakes[0])
        else:
            self.fake_file_menu.configure(values=["—"])
            self.fake_file_var.set("—")

    # ---- Умные кнопки ----

    def _on_zapret_start(self) -> None:
        name = self.strategy_var.get()
        strategy_bat = self.zapret.zapret_dir / f"{name}.bat"
        if not strategy_bat.exists():
            self.log("zapret", f"✗ файл стратегии не найден: {strategy_bat}")
            return

        if self.zapret.is_service_running():
            self.log("zapret",
                     f"→ Служба zapret уже запущена (стратегия: "
                     f"{self.zapret.get_active_strategy_name() or '?'})")
            self.set_status("Уже запущено")
            return

        self._run_zapret_op(f"Запуск {name}",
                            lambda: self.zapret.start_smart(strategy_bat),
                            with_details=True)

    def _on_zapret_stop(self) -> None:
        if not self.zapret.is_active():
            self.log("zapret", "→ zapret не запущен")
            return
        self._run_zapret_op("Остановка zapret",
                            lambda: self.zapret.stop_smart(),
                            with_details=True)

    def _on_zapret_restart(self) -> None:
        name = self.strategy_var.get()
        strategy_bat = self.zapret.zapret_dir / f"{name}.bat"
        if not strategy_bat.exists():
            self.log("zapret", f"✗ файл стратегии не найден: {strategy_bat}")
            return
        self._run_zapret_op(f"Перезапуск {name}",
                            lambda: self.zapret.restart_smart(strategy_bat),
                            with_details=True)

    # ---- Служебные кнопки ----

    def _on_zapret_status(self) -> None:
        self._run_zapret_op("Check Status",
                            lambda: self.zapret.get_service_status(),
                            with_details=True)

    def _on_zapret_apply_game_filter(self) -> None:
        label = self.game_filter_var.get()
        mode = {"disabled": "disabled", "all (TCP+UDP)": "all",
                "TCP only": "tcp", "UDP only": "udp"}.get(label, "disabled")
        res = self.zapret.set_game_filter(mode)
        self.log("zapret", f"→ {res.summary()}")
        self._refresh_zapret_toggles()

    def _on_zapret_toggle_ipset(self) -> None:
        res = self.zapret.toggle_ipset()
        self.log("zapret", f"→ {res.summary()}")
        if res.details:
            self.log("zapret", res.details)
        self._refresh_zapret_toggles()

    def _on_zapret_replace_fake(self) -> None:
        type_label = self.fake_type_var.get()
        active = "discord" if type_label.startswith("Discord") else "game"
        fname = self.fake_file_var.get()
        if fname == "—":
            self.log("zapret", "✗ не выбран fake-файл")
            return
        source = self.zapret.bin_dir / fname
        res = self.zapret.replace_active_fake(active, source)
        self.log("zapret", f"→ {res.summary()}")

    def _on_zapret_diagnostics(self) -> None:
        self._run_zapret_op("Diagnostics",
                            lambda: self.zapret.run_diagnostics(),
                            with_details=True)

    def _on_zapret_run_tests(self) -> None:
        res = self.zapret.run_tests()
        self.log("zapret", f"→ {res.summary()}")
        if res.details:
            self.log("zapret", res.details)

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

    def _on_zapret_edit_main_list(self) -> None:
        if self.zapret.edit_main_list():
            info = self.zapret.get_main_list_info()
            self.log("zapret", f"→ Открыт list-general.txt ({info.get('lines', 0)} доменов)")
        else:
            self.log("zapret", "✗ Не удалось открыть list-general.txt")

    def _on_zapret_edit_lists(self) -> None:
        if self.zapret.edit_user_lists():
            self.log("zapret", "→ Открыт list-general-user.txt")
        else:
            self.log("zapret", "✗ Не удалось открыть файл")

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
        self._refresh_zapret_toggles()
        self._refresh_fake_menu()
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
        status_card.grid(row=0, column=0, padx=8, pady=(8, 6), sticky="ew")
        status_card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(status_card, text="●", font=ctk.CTkFont(size=18),
                     text_color=("gray60", "gray50")).grid(row=0, column=0, padx=(14, 6), pady=10, sticky="w")
        self.tgproxy_status = ctk.CTkLabel(status_card, text="проверка...", anchor="w",
                                            font=ctk.CTkFont(size=13, weight="bold"))
        self.tgproxy_status.grid(row=0, column=1, padx=(0, 12), pady=10, sticky="ew")

        card, body = self._make_card(tab, title="Управление")
        card.grid(row=1, column=0, padx=8, pady=6, sticky="ew")
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.grid(row=0, column=0, sticky="ew")

        self.tgproxy_buttons: list[ctk.CTkButton] = []
        for i, (label, cmd) in enumerate([
            ("▶  Запустить", self._on_tgproxy_start),
            ("⏹  Остановить", self._on_tgproxy_stop),
            ("⟳  Перезапустить", self._on_tgproxy_restart),
        ]):
            btn = ctk.CTkButton(row, text=label, command=cmd, width=180, height=36)
            btn.grid(row=0, column=i, padx=4, pady=4, sticky="w")
            self.tgproxy_buttons.append(btn)

        ctk.CTkLabel(tab, text="Журнал:", anchor="w",
                     font=ctk.CTkFont(size=12, weight="bold")).grid(
            row=2, column=0, padx=16, pady=(8, 0), sticky="w")
        self.tgproxy_log = ctk.CTkTextbox(tab, wrap="word")
        self.tgproxy_log.grid(row=3, column=0, padx=8, pady=(4, 8), sticky="nsew")

    def _refresh_tgproxy_status(self) -> None:
        if not self.tgproxy.is_installed():
            self.tgproxy_status.configure(text="не установлен", text_color=STATUS_WARN)
            return
        if self.tgproxy.is_running():
            pid = self.tgproxy.pid
            text = f"Запущен (PID {pid})" if self.tgproxy.is_our_process() \
                else f"Запущен внешне (PID {pid})"
            self.tgproxy_status.configure(text=text, text_color=STATUS_OK)
        else:
            version = self.tgproxy.get_version() or "?"
            self.tgproxy_status.configure(text=f"Остановлен (v{version})",
                                          text_color=STATUS_NEUTRAL)

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

    # ============================================================
    #  ВКЛАДКА ОБНОВЛЕНИЯ
    # ============================================================

    def _build_updates_tab(self) -> None:
        tab = self.tab_updates
        tab.grid_columnconfigure(0, weight=1)

        top = ctk.CTkFrame(tab, corner_radius=10, fg_color=CARD_FG,
                           border_width=1, border_color=CARD_BORDER)
        top.grid(row=0, column=0, padx=8, pady=(8, 6), sticky="ew")
        top.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(top, text="⬇  Обновления компонентов", anchor="w",
                     font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=0, column=0, padx=16, pady=(12, 4), sticky="w")
        ctk.CTkLabel(top, text="Проверьте наличие новых версий и обновите компоненты в один клик.",
                     anchor="w", font=ctk.CTkFont(size=11),
                     text_color=("gray45", "gray60")).grid(
            row=1, column=0, padx=16, pady=(0, 8), sticky="w")

        btns = ctk.CTkFrame(top, fg_color="transparent")
        btns.grid(row=2, column=0, padx=12, pady=(0, 12), sticky="ew")

        self.updates_buttons: list[ctk.CTkButton] = []
        btn = ctk.CTkButton(btns, text="🔍  Проверить всё",
                            command=self._on_check_all, width=200, height=36,
                            font=ctk.CTkFont(size=13, weight="bold"))
        btn.grid(row=0, column=0, padx=4, pady=4, sticky="w")
        self.updates_buttons.append(btn)

        btn = ctk.CTkButton(btns, text="⬇  Обновить всё",
                            command=self._on_update_all, width=200, height=36,
                            font=ctk.CTkFont(size=13, weight="bold"))
        btn.grid(row=0, column=1, padx=4, pady=4, sticky="w")
        self.updates_buttons.append(btn)

        cards = ctk.CTkFrame(tab, fg_color="transparent")
        cards.grid(row=1, column=0, padx=8, pady=6, sticky="ew")
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
            row=2, column=0, padx=16, pady=(8, 0), sticky="w")
        self.updates_log = ctk.CTkTextbox(tab, wrap="word", height=180)
        self.updates_log.grid(row=3, column=0, padx=8, pady=(4, 8), sticky="nsew")
        tab.grid_rowconfigure(3, weight=1)

    def _make_update_card(self, parent, *, key: str, title: str, col: int, current: str) -> None:
        card = ctk.CTkFrame(parent, corner_radius=10, fg_color=CARD_FG,
                            border_width=1, border_color=CARD_BORDER)
        card.grid(row=0, column=col, padx=6, pady=4, sticky="nsew")
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(card, text=title, anchor="w",
                     font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=0, column=0, padx=14, pady=(12, 4), sticky="ew")

        row_cur = ctk.CTkFrame(card, fg_color="transparent")
        row_cur.grid(row=1, column=0, padx=14, pady=2, sticky="ew")
        row_cur.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(row_cur, text="Установлено:", anchor="w",
                     text_color=("gray45", "gray60"), font=ctk.CTkFont(size=11)).grid(
            row=0, column=0, sticky="w")
        cur_lbl = ctk.CTkLabel(row_cur, text=current, anchor="e",
                                font=ctk.CTkFont(size=12, weight="bold"))
        cur_lbl.grid(row=0, column=1, sticky="e")

        row_new = ctk.CTkFrame(card, fg_color="transparent")
        row_new.grid(row=2, column=0, padx=14, pady=2, sticky="ew")
        row_new.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(row_new, text="Последняя:", anchor="w",
                     text_color=("gray45", "gray60"), font=ctk.CTkFont(size=11)).grid(
            row=0, column=0, sticky="w")
        new_lbl = ctk.CTkLabel(row_new, text="—", anchor="e",
                                font=ctk.CTkFont(size=12))
        new_lbl.grid(row=0, column=1, sticky="e")

        status_lbl = ctk.CTkLabel(card, text="○  Не проверено", text_color=STATUS_NEUTRAL,
                                   font=ctk.CTkFont(size=11))
        status_lbl.grid(row=3, column=0, padx=14, pady=(8, 4), sticky="w")

        btn = ctk.CTkButton(card, text="⬇  Обновить", width=140, height=32,
                            command=lambda k=key: self._on_update_single(k))
        btn.grid(row=4, column=0, padx=14, pady=(4, 14), sticky="ew")
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
        try:
            result["wrapper"] = updater.fetch_latest_release(self.cfg.github_repo) \
                if self.cfg.github_repo else None
        except Exception as e:
            print("wrapper check error:", e)
            result["wrapper"] = None
        try:
            result["zapret"] = updater.fetch_latest_release("Flowseal/zapret-discord-youtube")
        except Exception as e:
            print("zapret check error:", e)
            result["zapret"] = None
        try:
            result["tgproxy"] = updater.fetch_latest_release("Flowseal/tg-ws-proxy")
        except Exception as e:
            print("tgproxy check error:", e)
            result["tgproxy"] = None
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
                    card["status_label"].configure(text="●  Доступно обновление",
                                                    text_color=STATUS_WARN)
                    card["update_btn"].configure(state="normal")
                    card["release"] = rel
                    self.log("updates",
                             f"{key}: доступна {rel.tag} (у вас {current}) — {rel.html_url}")
            else:
                card["latest_label"].configure(text="—")
                if key == "wrapper":
                    card["status_label"].configure(text="○  Релизов ещё нет",
                                                    text_color=STATUS_NEUTRAL)
                else:
                    card["status_label"].configure(text="○  Нет данных",
                                                    text_color=STATUS_NEUTRAL)
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
                written, skipped = updater.apply_release(
                    release, target_dir=PROJECT_ROOT,
                    excludes=self.cfg.exclude_from_update)
                return (key, f"обёртка обновлена до {release.tag} "
                             f"(w:{written}, s:{skipped}); перезапустите приложение")
            if key == "zapret":
                stop_res = self.zapret.stop_before_update()
                print(f"[update zapret] {stop_res.summary()}")
                written, skipped = updater.apply_release(
                    release, target_dir=self.zapret.zapret_dir,
                    excludes=self.cfg.exclude_from_update)
                return (key, f"zapret обновлён до {release.tag} "
                             f"(w:{written}, s:{skipped}). {stop_res.message}.")
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

        if key == "zapret":
            new_ver = self.zapret.get_local_version()
            self.update_cards["zapret"]["current_label"].configure(text=new_ver)
            self.update_cards["zapret"]["status_label"].configure(
                text="○  Обновлено, требуется переустановка службы",
                text_color=STATUS_WARN)
        elif key == "tgproxy":
            self.tgproxy.clear_version_cache()
            new_ver = self.tgproxy.get_version() or "—"
            self.update_cards["tgproxy"]["current_label"].configure(text=new_ver)
            self.update_cards["tgproxy"]["status_label"].configure(
                text="○  Обновлено", text_color=STATUS_OK)
        elif key == "wrapper":
            self.update_cards["wrapper"]["current_label"].configure(text=APP_VERSION)

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
                stop_res = self.zapret.stop_before_update()
                print(f"[update all] {stop_res.summary()}")
                written, skipped = updater.apply_release(
                    rel, target_dir=self.zapret.zapret_dir,
                    excludes=self.cfg.exclude_from_update)
                log.append(f"zapret → {rel.tag} (w:{written}, s:{skipped})")
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
            text="○  Обновлено, требуется переустановка службы",
            text_color=STATUS_WARN)
        self.tgproxy.clear_version_cache()
        self.update_cards["tgproxy"]["current_label"].configure(
            text=self.tgproxy.get_version() or "—")
        self.set_status("Готово")

    # ============================================================
    #  ВКЛАДКА НАСТРОЙКИ
    # ============================================================

    def _build_settings_tab(self) -> None:
        tab = self.tab_settings
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        # --- Исключения при обновлении ---
        info_card, info_body = self._make_card(tab, title="⚙  Исключения при обновлении")
        info_card.grid(row=0, column=0, padx=8, pady=(8, 6), sticky="ew")
        ctk.CTkLabel(
            info_body,
            text=("Файлы и папки из списка НЕ перезаписываются при обновлении, "
                  "если уже существуют на диске.\nПути — относительно корня проекта, "
                  "через прямой слэш. Для папки — с завершающим '/'."),
            anchor="w", justify="left", wraplength=940,
            text_color=("gray45", "gray60"), font=ctk.CTkFont(size=11)).grid(
            row=0, column=0, padx=4, pady=(0, 4), sticky="w")

        self.settings_excludes = ctk.CTkTextbox(tab, wrap="none", height=240,
                                                 font=ctk.CTkFont(size=12, family="Consolas"))
        self.settings_excludes.grid(row=1, column=0, padx=8, pady=6, sticky="nsew")
        self.settings_excludes.insert("1.0", "\n".join(self.cfg.exclude_from_update))

        # --- Автозапуск с Windows ---
        auto_card, auto_body = self._make_card(tab, title="🚀  Автозапуск с Windows")
        auto_card.grid(row=2, column=0, padx=8, pady=6, sticky="ew")

        self.autostart_var = ctk.BooleanVar(value=autostart.is_enabled())
        self.autostart_checkbox = ctk.CTkCheckBox(
            auto_body,
            text="Запускать Zapret Manager при входе в Windows",
            variable=self.autostart_var,
            command=self._on_toggle_autostart,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.autostart_checkbox.grid(row=0, column=0, padx=4, pady=(0, 6), sticky="w")

        ctk.CTkLabel(
            auto_body,
            text=("Приложение будет запускаться автоматически при входе в систему "
                  "(без окна консоли).\nНастройка хранится в реестре "
                  "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run."),
            anchor="w", justify="left", wraplength=940,
            text_color=("gray45", "gray60"), font=ctk.CTkFont(size=11),
        ).grid(row=1, column=0, padx=4, pady=0, sticky="w")

        # --- Действия ---
        actions_card, actions = self._make_card(tab, title="Действия")
        actions_card.grid(row=3, column=0, padx=8, pady=(0, 8), sticky="ew")

        row = ctk.CTkFrame(actions, fg_color="transparent")
        row.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(row, text="📄 Добавить файл…", command=self._on_add_exclude_file,
                      width=180, height=32).grid(row=0, column=0, padx=4, pady=4, sticky="w")
        ctk.CTkButton(row, text="📁 Добавить папку…", command=self._on_add_exclude_folder,
                      width=180, height=32).grid(row=0, column=1, padx=4, pady=4, sticky="w")
        ctk.CTkButton(row, text="🗑 Удалить выбранную строку",
                      command=self._on_remove_exclude_line, width=240, height=32).grid(
            row=0, column=2, padx=4, pady=4, sticky="w")

        row2 = ctk.CTkFrame(actions, fg_color="transparent")
        row2.grid(row=1, column=0, pady=(4, 0), sticky="ew")
        ctk.CTkButton(row2, text="💾 Сохранить", command=self._on_save_settings,
                      width=160, height=32, font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, padx=4, pady=4, sticky="w")
        ctk.CTkButton(row2, text="↺ Сбросить к дефолтным",
                      command=self._on_reset_settings, width=200, height=32).grid(
            row=0, column=1, padx=4, pady=4, sticky="w")
        ctk.CTkButton(row2, text="📄 Открыть config.json",
                      command=self._on_show_config, width=200, height=32).grid(
            row=0, column=2, padx=4, pady=4, sticky="w")

    # ---- Автозапуск ----

    def _on_toggle_autostart(self) -> None:
        """Включает/выключает автозапуск при старте Windows."""
        desired = self.autostart_var.get()
        if desired:
            ok = autostart.enable()
            if ok:
                self.log("updates", "→ Автозапуск включён")
                self.set_status("Автозапуск включён")
            else:
                self.autostart_var.set(False)
                self.log("updates", "✗ Не удалось включить автозапуск")
                self.set_status("Не удалось включить автозапуск")
        else:
            ok = autostart.disable()
            if ok:
                self.log("updates", "→ Автозапуск выключен")
                self.set_status("Автозапуск выключен")
            else:
                self.autostart_var.set(True)
                self.log("updates", "✗ Не удалось выключить автозапуск")
                self.set_status("Не удалось выключить автозапуск")

    # ---- Работа с исключениями ----

    def _get_exclude_lines(self) -> list[str]:
        raw = self.settings_excludes.get("1.0", "end")
        return [line.strip() for line in raw.splitlines() if line.strip()]

    def _set_exclude_lines(self, lines: list[str]) -> None:
        self.settings_excludes.delete("1.0", "end")
        self.settings_excludes.insert("1.0", "\n".join(lines))

    def _to_relative(self, abs_path: str) -> str | None:
        try:
            rel = Path(abs_path).resolve().relative_to(PROJECT_ROOT.resolve())
            return str(rel).replace("\\", "/")
        except ValueError:
            return None

    def _on_add_exclude_file(self) -> None:
        path = filedialog.askopenfilename(title="Выберите файл для исключения",
                                          initialdir=str(PROJECT_ROOT))
        if not path:
            return
        rel = self._to_relative(path)
        if rel is None:
            self.set_status("✗ Файл должен быть внутри папки проекта")
            return
        lines = self._get_exclude_lines()
        if rel in lines:
            self.set_status(f"Уже в списке: {rel}")
            return
        lines.append(rel)
        self._set_exclude_lines(lines)
        self.set_status(f"Добавлено: {rel} (не забудь сохранить)")

    def _on_add_exclude_folder(self) -> None:
        path = filedialog.askdirectory(title="Выберите папку для исключения",
                                       initialdir=str(PROJECT_ROOT))
        if not path:
            return
        rel = self._to_relative(path)
        if rel is None:
            self.set_status("✗ Папка должна быть внутри папки проекта")
            return
        rel = rel.rstrip("/") + "/"
        lines = self._get_exclude_lines()
        if rel in lines:
            self.set_status(f"Уже в списке: {rel}")
            return
        lines.append(rel)
        self._set_exclude_lines(lines)
        self.set_status(f"Добавлено: {rel} (не забудь сохранить)")

    def _on_remove_exclude_line(self) -> None:
        try:
            index = self.settings_excludes.index("insert")
            line_no = int(str(index).split(".")[0])
        except Exception:
            self.set_status("Не удалось определить строку")
            return
        lines = self._get_exclude_lines()
        if 1 <= line_no <= len(lines):
            removed = lines.pop(line_no - 1)
            self._set_exclude_lines(lines)
            self.set_status(f"Удалено: {removed} (не забудь сохранить)")
        else:
            self.set_status("Строка пустая или вне диапазона")

    def _on_save_settings(self) -> None:
        lines = self._get_exclude_lines()
        self.cfg.set("exclude_from_update", lines)
        self.cfg.save()
        self.log("updates", f"→ Настройки сохранены ({len(lines)} исключений)")
        self.set_status("Настройки сохранены")

    def _on_reset_settings(self) -> None:
        from app.core.config import DEFAULT_CONFIG
        defaults = DEFAULT_CONFIG["exclude_from_update"]
        self._set_exclude_lines(list(defaults))
        self.set_status("Сброшено к дефолтным (не забудь сохранить)")

    def _on_show_config(self) -> None:
        try:
            os.startfile(str(self.cfg.path))
        except Exception:
            try:
                import subprocess
                subprocess.Popen(["notepad", str(self.cfg.path)])
            except Exception as e:
                self.set_status(f"Не удалось открыть: {e}")

    # ============================================================
    #  Общие утилиты
    # ============================================================

    def log(self, tab: str, message: str) -> None:
        """Пишет строку в UI и в файл logs/session_*.log."""
        ts = datetime.now().strftime("%H:%M:%S")

        target = {"zapret": self.zapret_log, "tgproxy": self.tgproxy_log,
                  "updates": self.updates_log}.get(tab)
        if target is not None:
            target.insert("end", message + "\n")
            target.see("end")
        else:
            print(f"[log/{tab}] {message}")

        try:
            with self.log_file.open("a", encoding="utf-8") as f:
                # многострочные сообщения пишем с таймстампом на каждой строке
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