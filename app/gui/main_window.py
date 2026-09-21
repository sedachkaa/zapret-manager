"""
Главное окно приложения.
"""

from __future__ import annotations

import threading
import traceback
from pathlib import Path
from tkinter import filedialog
from typing import Callable

import customtkinter as ctk

from app.core import updater
from app.core.config import PROJECT_ROOT, Config
from app.core.tgproxy_manager import TgProxyManager
from app.core.zapret_manager import ZapretManager


WINDOW_TITLE = "Zapret Manager"
WINDOW_SIZE = "1000x720"
MIN_SIZE = (820, 580)
APP_VERSION = "0.1.0"

# Интервал автоматического обновления статусов (мс)
AUTO_REFRESH_MS = 3000


class MainWindow(ctk.CTk):
    """Главное окно приложения."""

    def __init__(self, cfg: Config) -> None:
        super().__init__()

        self.cfg = cfg
        self.zapret = ZapretManager(cfg)
        self.tgproxy = TgProxyManager(cfg)

        ctk.set_appearance_mode(cfg.get("theme", "dark"))
        ctk.set_default_color_theme("blue")

        self.title(f"{WINDOW_TITLE} v{APP_VERSION}")
        self.geometry(WINDOW_SIZE)
        self.minsize(*MIN_SIZE)

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._build_header()

        self.tabview = ctk.CTkTabview(self, corner_radius=10)
        self.tabview.grid(row=1, column=0, padx=16, pady=(0, 8), sticky="nsew")

        self.tab_zapret = self.tabview.add("Zapret")
        self.tab_tgproxy = self.tabview.add("Telegram Proxy")
        self.tab_updates = self.tabview.add("Обновления")
        self.tab_settings = self.tabview.add("Настройки")

        self._build_zapret_tab()
        self._build_tgproxy_tab()
        self._build_updates_tab()
        self._build_settings_tab()

        self._build_status_bar()
        self.set_status(f"Готово. Репозиторий: {cfg.github_repo}")

        # Первое обновление и запуск таймера
        self.after(300, self._auto_refresh)

    # ============================================================
    #  Верхняя панель / статус-бар
    # ============================================================

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, height=56, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            header, text="Zapret Manager",
            font=ctk.CTkFont(size=20, weight="bold"),
        ).grid(row=0, column=0, padx=16, pady=12, sticky="w")

        ctk.CTkLabel(
            header,
            text="обёртка для zapret-discord-youtube и tg-ws-proxy",
            font=ctk.CTkFont(size=12),
            text_color=("gray40", "gray70"),
        ).grid(row=0, column=1, padx=8, pady=12, sticky="w")

    def _build_status_bar(self) -> None:
        self.status_bar = ctk.CTkLabel(
            self, text="", anchor="w", height=24, text_color=("gray40", "gray70")
        )
        self.status_bar.grid(row=2, column=0, padx=12, pady=(0, 8), sticky="ew")

    def set_status(self, text: str) -> None:
        self.status_bar.configure(text=text)

    # ============================================================
    #  Автообновление статусов
    # ============================================================

    def _auto_refresh(self) -> None:
        """Периодически (каждые 3 сек) обновляет статусы."""
        try:
            self._refresh_zapret_status()
            self._refresh_tgproxy_status()
        except Exception as e:
            print("[auto_refresh] error:", e)
        self.after(AUTO_REFRESH_MS, self._auto_refresh)

    # ============================================================
    #  Вкладка Zapret
    # ============================================================

    def _build_zapret_tab(self) -> None:
        tab = self.tab_zapret
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(5, weight=1)

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

        # Главная кнопка
        main_btn_frame = ctk.CTkFrame(tab, fg_color="transparent")
        main_btn_frame.grid(row=1, column=0, padx=8, pady=(8, 4), sticky="ew")
        main_btn_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(
            main_btn_frame,
            text="🔧  Открыть service.bat (все настройки)",
            command=self._on_zapret_open_console,
            height=40,
            font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=0, column=0, padx=4, pady=4, sticky="ew")

        buttons_row2 = ctk.CTkFrame(tab, fg_color="transparent")
        buttons_row2.grid(row=2, column=0, padx=8, pady=2, sticky="ew")

        self.zapret_buttons: list[ctk.CTkButton] = []
        for i, (label, cmd) in enumerate([
            ("Проверить статус", self._on_zapret_status),
            ("Игровой фильтр", self._on_zapret_game_filter),
            ("Загрузить user-списки", self._on_zapret_load_user_lists),
            ("Проверить обновления", self._on_zapret_check_updates),
        ]):
            btn = ctk.CTkButton(buttons_row2, text=label, command=cmd, width=190)
            btn.grid(row=0, column=i, padx=4, pady=4, sticky="w")
            self.zapret_buttons.append(btn)

        buttons_row3 = ctk.CTkFrame(tab, fg_color="transparent")
        buttons_row3.grid(row=3, column=0, padx=8, pady=2, sticky="ew")

        for i, (label, cmd) in enumerate([
            ("Папка zapret", self._on_zapret_open_folder),
            ("Папка lists", self._on_zapret_open_lists),
            ("Редактировать user-листы", self._on_zapret_edit_lists),
            ("Открыть с админом", self._on_zapret_console_admin),
        ]):
            btn = ctk.CTkButton(buttons_row3, text=label, command=cmd, width=190)
            btn.grid(row=0, column=i, padx=4, pady=4, sticky="w")
            self.zapret_buttons.append(btn)

        ctk.CTkLabel(tab, text="Журнал:", anchor="w").grid(
            row=4, column=0, padx=12, pady=(8, 0), sticky="w"
        )
        self.zapret_log = ctk.CTkTextbox(tab, wrap="word")
        self.zapret_log.grid(row=5, column=0, padx=8, pady=(0, 8), sticky="nsew")

    def _refresh_zapret_status(self) -> None:
        if not self.zapret.is_installed():
            self.zapret_status.configure(
                text="не установлен", text_color=("orange", "orange")
            )
            return
        if self.zapret.is_active():
            self.zapret_status.configure(
                text="активен ✓", text_color=("green", "lightgreen")
            )
        else:
            self.zapret_status.configure(
                text="установлен, не активен", text_color=("gray40", "gray70")
            )

    def _on_zapret_status(self) -> None:
        self._run_async(
            "Проверка статуса zapret",
            work=lambda: self.zapret.get_status(),
            on_done=self._after_zapret_status,
            tab="zapret",
        )

    def _after_zapret_status(self, res) -> None:
        self.log("zapret", f"→ {res.summary()}")
        if res.stdout.strip():
            self.log("zapret", res.stdout.strip())
        if res.stderr.strip():
            self.log("zapret", f"stderr: {res.stderr.strip()}")
        # Дополнительно покажем системный статус
        active = self.zapret.is_active()
        self.log("zapret", f"→ winws.exe запущен: {self.zapret.is_winws_running()}")
        self.log("zapret", f"→ служба zapret работает: {self.zapret.is_service_running()}")
        self.log("zapret", f"→ итог: {'АКТИВЕН' if active else 'не активен'}")
        self._refresh_zapret_status()
        self.set_status("Готово")

    def _on_zapret_game_filter(self) -> None:
        self._run_async(
            "Переключение игрового фильтра",
            work=lambda: self.zapret.load_game_filter(),
            on_done=lambda res: self._after_simple_zapret(res, "Игровой фильтр"),
            tab="zapret",
        )

    def _on_zapret_load_user_lists(self) -> None:
        self._run_async(
            "Загрузка user-списков",
            work=lambda: self.zapret.load_user_lists(),
            on_done=lambda res: self._after_simple_zapret(res, "User-списки"),
            tab="zapret",
        )

    def _on_zapret_check_updates(self) -> None:
        self._run_async(
            "Проверка обновлений (bat)",
            work=lambda: self.zapret.check_updates(),
            on_done=lambda res: self._after_simple_zapret(res, "Проверка обновлений"),
            tab="zapret",
        )

    def _after_simple_zapret(self, res, title: str) -> None:
        self.log("zapret", f"→ {title}: {res.summary()}")
        if res.stdout.strip():
            self.log("zapret", res.stdout.strip())
        if res.stderr.strip():
            self.log("zapret", f"stderr: {res.stderr.strip()}")
        self.set_status("Готово")

    def _on_zapret_open_console(self) -> None:
        try:
            ok = self.zapret.open_console()
            self.log(
                "zapret",
                "→ Открыто окно service.bat (с правами админа)"
                if ok else "✗ UAC отклонён",
            )
        except Exception as e:
            self.log("zapret", f"✗ Ошибка: {e}")

    def _on_zapret_console_admin(self) -> None:
        try:
            ok = self.zapret.open_console_as_admin()
            self.log(
                "zapret",
                "→ Открыто окно service.bat с правами админа"
                if ok else "✗ UAC отклонён",
            )
        except Exception as e:
            self.log("zapret", f"✗ Ошибка: {e}")

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

    def _on_zapret_edit_lists(self) -> None:
        if self.zapret.edit_user_lists():
            self.log("zapret", "→ Открыт list-general-user.txt в редакторе")
        else:
            self.log("zapret", "✗ Не удалось открыть файл")

    # ============================================================
    #  Вкладка Telegram Proxy
    # ============================================================

    def _build_tgproxy_tab(self) -> None:
        tab = self.tab_tgproxy
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(4, weight=1)

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

        buttons_frame = ctk.CTkFrame(tab, fg_color="transparent")
        buttons_frame.grid(row=1, column=0, padx=8, pady=4, sticky="ew")

        self.tgproxy_buttons: list[ctk.CTkButton] = []
        for i, (label, cmd) in enumerate([
            ("Запустить", self._on_tgproxy_start),
            ("Остановить", self._on_tgproxy_stop),
            ("Перезапустить", self._on_tgproxy_restart),
            ("Обновить", self._on_tgproxy_update),
        ]):
            btn = ctk.CTkButton(buttons_frame, text=label, command=cmd, width=150)
            btn.grid(row=0, column=i, padx=4, pady=4, sticky="w")
            self.tgproxy_buttons.append(btn)

        ctk.CTkLabel(tab, text="Журнал:", anchor="w").grid(
            row=3, column=0, padx=12, pady=(8, 0), sticky="w"
        )
        self.tgproxy_log = ctk.CTkTextbox(tab, wrap="word")
        self.tgproxy_log.grid(row=4, column=0, padx=8, pady=(0, 8), sticky="nsew")

    def _refresh_tgproxy_status(self) -> None:
        if not self.tgproxy.is_installed():
            self.tgproxy_status.configure(
                text="не установлен", text_color=("orange", "orange")
            )
            return

        running = self.tgproxy.is_running()
        if running:
            pid = self.tgproxy.pid
            if self.tgproxy.is_our_process():
                text = f"запущен (PID {pid})"
            else:
                text = f"запущен внешне (PID {pid})"
            self.tgproxy_status.configure(text=text, text_color=("green", "lightgreen"))
        else:
            version = self.tgproxy.get_version() or "?"
            self.tgproxy_status.configure(
                text=f"остановлен (v{version})", text_color=("gray40", "gray70")
            )

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

    def _on_tgproxy_update(self) -> None:
        self._run_async(
            "Обновление tg-ws-proxy",
            work=lambda: self.tgproxy.apply_update(),
            on_done=self._after_tgproxy_update,
            tab="tgproxy",
        )

    def _after_tgproxy_update(self, res) -> None:
        self.log("tgproxy", f"→ {res.summary()}")
        self._refresh_tgproxy_status()
        self.set_status("Готово")

    # ============================================================
    #  Вкладка Обновления
    # ============================================================

    def _build_updates_tab(self) -> None:
        tab = self.tab_updates
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(3, weight=1)

        info = ctk.CTkFrame(tab)
        info.grid(row=0, column=0, padx=8, pady=(8, 4), sticky="ew")
        info.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(info, text="Проверка обновлений компонентов",
                     font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, columnspan=2, padx=12, pady=(10, 6), sticky="w"
        )

        self.update_labels: dict[str, ctk.CTkLabel] = {}
        for i, (name, key) in enumerate([
            ("Обёртка", "wrapper"),
            ("zapret-discord-youtube", "zapret"),
            ("tg-ws-proxy", "tgproxy"),
        ], start=1):
            ctk.CTkLabel(info, text=f"{name}:").grid(
                row=i, column=0, padx=(12, 6), pady=4, sticky="w"
            )
            lbl = ctk.CTkLabel(info, text="—", text_color=("gray40", "gray70"))
            lbl.grid(row=i, column=1, padx=(0, 12), pady=4, sticky="w")
            self.update_labels[key] = lbl

        btns = ctk.CTkFrame(tab, fg_color="transparent")
        btns.grid(row=1, column=0, padx=8, pady=4, sticky="ew")

        self.updates_buttons: list[ctk.CTkButton] = []
        for i, (label, cmd) in enumerate([
            ("Проверить всё", self._on_check_all),
            ("Обновить всё", self._on_update_all),
        ]):
            btn = ctk.CTkButton(btns, text=label, command=cmd, width=160)
            btn.grid(row=0, column=i, padx=4, pady=4, sticky="w")
            self.updates_buttons.append(btn)

        ctk.CTkLabel(tab, text="Журнал:", anchor="w").grid(
            row=2, column=0, padx=12, pady=(8, 0), sticky="w"
        )
        self.updates_log = ctk.CTkTextbox(tab, wrap="word")
        self.updates_log.grid(row=3, column=0, padx=8, pady=(0, 8), sticky="nsew")

    def _on_check_all(self) -> None:
        self._run_async(
            "Проверка обновлений",
            work=self._work_check_all,
            on_done=self._after_check_all,
            tab="updates",
        )

    def _work_check_all(self):
        result = {}
        try:
            result["wrapper"] = updater.check_wrapper_update(APP_VERSION, self.cfg)
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
            lbl = self.update_labels[key]
            if rel:
                lbl.configure(text=f"доступна {rel.tag}", text_color=("green", "lightgreen"))
                self.log("updates", f"{key}: доступна {rel.tag} ({rel.html_url})")
            else:
                lbl.configure(text="нет релизов", text_color=("gray40", "gray70"))
                self.log("updates", f"{key}: релизов не найдено")
        self.set_status("Готово")

    def _on_update_all(self) -> None:
        self._run_async(
            "Обновление компонентов",
            work=self._work_update_all,
            on_done=self._after_update_all,
            tab="updates",
        )

    def _work_update_all(self):
        log: list[str] = []
        try:
            rel = updater.check_zapret_update(self.cfg)
            if rel:
                written, skipped = updater.apply_release(
                    rel,
                    target_dir=self.zapret.zapret_dir,
                    excludes=self.cfg.exclude_from_update,
                )
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
        self.set_status("Готово")

    # ============================================================
    #  Вкладка Настройки
    # ============================================================

    def _build_settings_tab(self) -> None:
        tab = self.tab_settings
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(
            tab, text="Список исключений (один путь на строку):", anchor="w"
        ).grid(row=0, column=0, padx=12, pady=(12, 4), sticky="w")

        ctk.CTkLabel(
            tab,
            text=(
                "Файлы и папки из списка НЕ перезаписываются при обновлении, "
                "если уже существуют на диске. Пути — относительно корня проекта, "
                "через прямой слэш. Для папки — с завершающим '/'."
            ),
            anchor="w",
            text_color=("gray40", "gray70"),
            font=ctk.CTkFont(size=12),
            wraplength=900,
            justify="left",
        ).grid(row=1, column=0, padx=12, pady=(0, 6), sticky="w")

        self.settings_excludes = ctk.CTkTextbox(tab, wrap="none", height=200)
        self.settings_excludes.grid(row=3, column=0, padx=8, pady=(0, 8), sticky="nsew")
        self.settings_excludes.insert("1.0", "\n".join(self.cfg.exclude_from_update))

        # Кнопки — в 2 ряда, чтобы всё влезло
        btns1 = ctk.CTkFrame(tab, fg_color="transparent")
        btns1.grid(row=4, column=0, padx=8, pady=(4, 0), sticky="ew")

        ctk.CTkButton(
            btns1, text="📄 Добавить файл…", command=self._on_add_exclude_file, width=180
        ).grid(row=0, column=0, padx=4, pady=4, sticky="w")
        ctk.CTkButton(
            btns1, text="📁 Добавить папку…", command=self._on_add_exclude_folder, width=180
        ).grid(row=0, column=1, padx=4, pady=4, sticky="w")
        ctk.CTkButton(
            btns1, text="Удалить выбранную строку", command=self._on_remove_exclude_line, width=220
        ).grid(row=0, column=2, padx=4, pady=4, sticky="w")

        btns2 = ctk.CTkFrame(tab, fg_color="transparent")
        btns2.grid(row=5, column=0, padx=8, pady=(0, 8), sticky="ew")

        ctk.CTkButton(
            btns2, text="💾 Сохранить", command=self._on_save_settings, width=140
        ).grid(row=0, column=0, padx=4, pady=4, sticky="w")
        ctk.CTkButton(
            btns2, text="Сбросить к дефолтным", command=self._on_reset_settings, width=180
        ).grid(row=0, column=1, padx=4, pady=4, sticky="w")
        ctk.CTkButton(
            btns2, text="Показать текущий config.json", command=self._on_show_config, width=220
        ).grid(row=0, column=2, padx=4, pady=4, sticky="w")

    # --- вспомогательные для настроек ----------------------------------

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
        path = filedialog.askopenfilename(
            title="Выберите файл для исключения",
            initialdir=str(PROJECT_ROOT),
        )
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
        path = filedialog.askdirectory(
            title="Выберите папку для исключения",
            initialdir=str(PROJECT_ROOT),
        )
        if not path:
            return
        rel = self._to_relative(path)
        if rel is None:
            self.set_status("✗ Папка должна быть внутри папки проекта")
            return
        # Для папки храним путь с завершающим слэшем
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
            # Индекс курсора вида "N.M" → строка N
            index = self.settings_excludes.index("insert")
            line_no = int(str(index).split(".")[0])
        except Exception:
            self.set_status("Не удалось определить строку")
            return
        lines = self._get_exclude_lines()
        # line_no — 1-based
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
            os.startfile(str(self.cfg.path))  # type: ignore[attr-defined]
        except Exception:
            # открыть в блокноте
            try:
                import subprocess
                subprocess.Popen(["notepad", str(self.cfg.path)])
            except Exception as e:
                self.set_status(f"Не удалось открыть: {e}")

    # ============================================================
    #  Утилиты: логи, асинхронные задачи
    # ============================================================

    def log(self, tab: str, message: str) -> None:
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

    def _set_buttons_state(self, tab: str, enabled: bool) -> None:
        buttons_map = {
            "zapret": getattr(self, "zapret_buttons", []),
            "tgproxy": getattr(self, "tgproxy_buttons", []),
            "updates": getattr(self, "updates_buttons", []),
        }
        for btn in buttons_map.get(tab, []):
            btn.configure(state="normal" if enabled else "disabled")

    def _run_async(self, description: str, work: Callable, on_done: Callable, tab: str) -> None:
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