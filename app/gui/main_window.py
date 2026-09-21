"""
Главное окно приложения.

Содержит 4 вкладки:
    - Zapret — управление zapret-discord-youtube;
    - Telegram Proxy — управление tg-ws-proxy;
    - Обновления — проверка и установка обновлений;
    - Настройки — редактирование config.json.

На этом этапе — каркас без полной логики. Кнопки подключаются постепенно.
"""

from __future__ import annotations

import customtkinter as ctk

from app.core.config import Config


# Константы внешнего вида
WINDOW_TITLE = "Zapret Manager"
WINDOW_SIZE = "1000x700"
MIN_SIZE = (800, 560)


class MainWindow(ctk.CTk):
    """Главное окно приложения."""

    def __init__(self, cfg: Config) -> None:
        super().__init__()

        self.cfg = cfg

        # Настройки темы из конфига
        ctk.set_appearance_mode(cfg.get("theme", "dark"))
        ctk.set_default_color_theme("blue")

        # Параметры окна
        self.title(WINDOW_TITLE)
        self.geometry(WINDOW_SIZE)
        self.minsize(*MIN_SIZE)

        # Сетка: строка 0 — заголовок, строка 1 — вкладки (растягиваются)
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Заголовок
        self._build_header()

        # Вкладки
        self.tabview = ctk.CTkTabview(self, corner_radius=10)
        self.tabview.grid(row=1, column=0, padx=16, pady=(0, 16), sticky="nsew")

        self.tab_zapret = self.tabview.add("Zapret")
        self.tab_tgproxy = self.tabview.add("Telegram Proxy")
        self.tab_updates = self.tabview.add("Обновления")
        self.tab_settings = self.tabview.add("Настройки")

        self._build_zapret_tab()
        self._build_tgproxy_tab()
        self._build_updates_tab()
        self._build_settings_tab()

        # Статус-бар внизу
        self._build_status_bar()

        # Подсказка в статус-баре
        self.set_status(f"Готово. Репозиторий: {cfg.github_repo}")

    # --- Верхняя панель -------------------------------------------------

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, height=56, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        title = ctk.CTkLabel(
            header,
            text="Zapret Manager",
            font=ctk.CTkFont(size=20, weight="bold"),
        )
        title.grid(row=0, column=0, padx=16, pady=12, sticky="w")

        self.header_subtitle = ctk.CTkLabel(
            header,
            text="обёртка для zapret-discord-youtube и tg-ws-proxy",
            font=ctk.CTkFont(size=12),
            text_color=("gray40", "gray70"),
        )
        self.header_subtitle.grid(row=0, column=1, padx=8, pady=12, sticky="w")

    # --- Вкладка Zapret -------------------------------------------------

    def _build_zapret_tab(self) -> None:
        tab = self.tab_zapret
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(2, weight=1)

        # Строка статуса
        status_frame = ctk.CTkFrame(tab)
        status_frame.grid(row=0, column=0, padx=8, pady=(8, 4), sticky="ew")
        status_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(status_frame, text="Статус:", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, padx=(12, 6), pady=10, sticky="w"
        )
        self.zapret_status = ctk.CTkLabel(
            status_frame, text="проверка...", text_color=("gray40", "gray70")
        )
        self.zapret_status.grid(row=0, column=1, padx=(0, 12), pady=10, sticky="w")

        # Кнопки управления
        buttons_frame = ctk.CTkFrame(tab, fg_color="transparent")
        buttons_frame.grid(row=1, column=0, padx=8, pady=4, sticky="ew")

        actions = [
            ("Проверить статус", self._on_zapret_status),
            ("Открыть service.bat", self._on_zapret_open_console),
            ("Меню от админа", self._on_zapret_console_admin),
            ("Проверить обновления", self._on_zapret_check_updates),
        ]
        for i, (label, cmd) in enumerate(actions):
            btn = ctk.CTkButton(buttons_frame, text=label, command=cmd, width=180)
            btn.grid(row=0, column=i, padx=4, pady=4, sticky="w")

        # Лог
        log_label = ctk.CTkLabel(tab, text="Журнал:", anchor="w")
        log_label.grid(row=3, column=0, padx=12, pady=(8, 0), sticky="w")

        self.zapret_log = ctk.CTkTextbox(tab, wrap="word")
        self.zapret_log.grid(row=4, column=0, padx=8, pady=(0, 8), sticky="nsew")
        tab.grid_rowconfigure(4, weight=1)

    # --- Вкладка Telegram Proxy -----------------------------------------

    def _build_tgproxy_tab(self) -> None:
        tab = self.tab_tgproxy
        tab.grid_columnconfigure(0, weight=1)

        # Статус
        status_frame = ctk.CTkFrame(tab)
        status_frame.grid(row=0, column=0, padx=8, pady=(8, 4), sticky="ew")
        status_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(status_frame, text="Статус:", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, padx=(12, 6), pady=10, sticky="w"
        )
        self.tgproxy_status = ctk.CTkLabel(
            status_frame, text="проверка...", text_color=("gray40", "gray70")
        )
        self.tgproxy_status.grid(row=0, column=1, padx=(0, 12), pady=10, sticky="w")

        # Кнопки управления
        buttons_frame = ctk.CTkFrame(tab, fg_color="transparent")
        buttons_frame.grid(row=1, column=0, padx=8, pady=4, sticky="ew")

        actions = [
            ("Запустить", self._on_tgproxy_start),
            ("Остановить", self._on_tgproxy_stop),
            ("Перезапустить", self._on_tgproxy_restart),
            ("Обновить", self._on_tgproxy_update),
        ]
        for i, (label, cmd) in enumerate(actions):
            btn = ctk.CTkButton(buttons_frame, text=label, command=cmd, width=150)
            btn.grid(row=0, column=i, padx=4, pady=4, sticky="w")

        # Лог
        ctk.CTkLabel(tab, text="Журнал:", anchor="w").grid(
            row=3, column=0, padx=12, pady=(8, 0), sticky="w"
        )
        self.tgproxy_log = ctk.CTkTextbox(tab, wrap="word")
        self.tgproxy_log.grid(row=4, column=0, padx=8, pady=(0, 8), sticky="nsew")
        tab.grid_rowconfigure(4, weight=1)

    # --- Вкладка Обновления ---------------------------------------------

    def _build_updates_tab(self) -> None:
        tab = self.tab_updates
        tab.grid_columnconfigure(0, weight=1)

        info = ctk.CTkFrame(tab)
        info.grid(row=0, column=0, padx=8, pady=(8, 4), sticky="ew")
        info.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            info, text="Проверка обновлений компонентов", font=ctk.CTkFont(weight="bold")
        ).grid(row=0, column=0, columnspan=2, padx=12, pady=(10, 6), sticky="w")

        rows = [
            ("Обёртка", "check_wrapper"),
            ("zapret-discord-youtube", "check_zapret"),
            ("tg-ws-proxy", "check_tgproxy"),
        ]
        for i, (name, key) in enumerate(rows, start=1):
            ctk.CTkLabel(info, text=f"{name}:").grid(
                row=i, column=0, padx=(12, 6), pady=4, sticky="w"
            )
            lbl = ctk.CTkLabel(info, text="—", text_color=("gray40", "gray70"))
            lbl.grid(row=i, column=1, padx=(0, 12), pady=4, sticky="w")
            setattr(self, f"upd_{key}", lbl)

        btns = ctk.CTkFrame(tab, fg_color="transparent")
        btns.grid(row=1, column=0, padx=8, pady=4, sticky="ew")

        ctk.CTkButton(btns, text="Проверить всё", command=self._on_check_all, width=160).grid(
            row=0, column=0, padx=4, pady=4, sticky="w"
        )
        ctk.CTkButton(btns, text="Обновить всё", command=self._on_update_all, width=160).grid(
            row=0, column=1, padx=4, pady=4, sticky="w"
        )

        ctk.CTkLabel(tab, text="Журнал:", anchor="w").grid(
            row=2, column=0, padx=12, pady=(8, 0), sticky="w"
        )
        self.updates_log = ctk.CTkTextbox(tab, wrap="word")
        self.updates_log.grid(row=3, column=0, padx=8, pady=(0, 8), sticky="nsew")
        tab.grid_rowconfigure(3, weight=1)

    # --- Вкладка Настройки ----------------------------------------------

    def _build_settings_tab(self) -> None:
        tab = self.tab_settings
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(
            tab,
            text="Список исключений (один путь на строку):",
            anchor="w",
        ).grid(row=0, column=0, padx=12, pady=(12, 4), sticky="w")

        hint = ctk.CTkLabel(
            tab,
            text="Файлы из списка не перезаписываются при обновлении, если уже существуют.",
            anchor="w",
            text_color=("gray40", "gray70"),
            font=ctk.CTkFont(size=12),
        )
        hint.grid(row=1, column=0, padx=12, pady=(0, 6), sticky="w")

        self.settings_excludes = ctk.CTkTextbox(tab, wrap="none", height=200)
        self.settings_excludes.grid(row=3, column=0, padx=8, pady=(0, 8), sticky="nsew")

        # Заполняем текущими значениями
        current = self.cfg.exclude_from_update
        self.settings_excludes.insert("1.0", "\n".join(current))

        btns = ctk.CTkFrame(tab, fg_color="transparent")
        btns.grid(row=4, column=0, padx=8, pady=4, sticky="ew")

        ctk.CTkButton(btns, text="Сохранить", command=self._on_save_settings, width=140).grid(
            row=0, column=0, padx=4, pady=4, sticky="w"
        )
        ctk.CTkButton(
            btns, text="Сбросить к дефолтным", command=self._on_reset_settings, width=180
        ).grid(row=0, column=1, padx=4, pady=4, sticky="w")

    # --- Статус-бар -----------------------------------------------------

    def _build_status_bar(self) -> None:
        self.status_bar = ctk.CTkLabel(
            self, text="", anchor="w", height=24, text_color=("gray40", "gray70")
        )
        self.status_bar.grid(row=2, column=0, padx=12, pady=(0, 8), sticky="ew")

    def set_status(self, text: str) -> None:
        """Обновляет нижний статус-бар."""
        self.status_bar.configure(text=text)

    # --- Логи (вспомогательные) -----------------------------------------

    def log(self, tab: str, message: str) -> None:
        """
        Пишет сообщение в лог указанной вкладки.
        tab: "zapret" | "tgproxy" | "updates"
        """
        target = {
            "zapret": self.zapret_log,
            "tgproxy": self.tgproxy_log,
            "updates": self.updates_log,
        }.get(tab)
        if target is None:
            print(f"[log/{tab}] {message}")
            return
        target.insert("end", message + "\n")
        target.see("end")

    # --- Заглушки обработчиков (наполним позже) -------------------------

    def _on_zapret_status(self) -> None:
        self.log("zapret", "[stub] Проверить статус zapret")

    def _on_zapret_open_console(self) -> None:
        self.log("zapret", "[stub] Открыть service.bat")

    def _on_zapret_console_admin(self) -> None:
        self.log("zapret", "[stub] Открыть service.bat от админа")

    def _on_zapret_check_updates(self) -> None:
        self.log("zapret", "[stub] Проверить обновления через bat")

    def _on_tgproxy_start(self) -> None:
        self.log("tgproxy", "[stub] Запустить tg-ws-proxy")

    def _on_tgproxy_stop(self) -> None:
        self.log("tgproxy", "[stub] Остановить tg-ws-proxy")

    def _on_tgproxy_restart(self) -> None:
        self.log("tgproxy", "[stub] Перезапустить tg-ws-proxy")

    def _on_tgproxy_update(self) -> None:
        self.log("tgproxy", "[stub] Обновить tg-ws-proxy")

    def _on_check_all(self) -> None:
        self.log("updates", "[stub] Проверить все обновления")

    def _on_update_all(self) -> None:
        self.log("updates", "[stub] Обновить всё")

    def _on_save_settings(self) -> None:
        self.log("updates", "[stub] Сохранить настройки")

    def _on_reset_settings(self) -> None:
        self.log("updates", "[stub] Сбросить настройки к дефолтным")