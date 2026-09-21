"""
Главное окно приложения.

4 вкладки:
    - Zapret — управление zapret-discord-youtube;
    - Telegram Proxy — управление tg-ws-proxy;
    - Обновления — проверка и установка обновлений;
    - Настройки — редактирование config.json.

Все длительные операции выполняются в фоновых потоках,
чтобы не блокировать GUI. Результат возвращается в главный поток
через self.after(0, callback).
"""

from __future__ import annotations

import threading
import traceback
from typing import Callable

import customtkinter as ctk

from app.core import updater
from app.core.config import Config
from app.core.tgproxy_manager import TgProxyManager
from app.core.zapret_manager import ZapretManager


# --- Константы внешнего вида --------------------------------------------

WINDOW_TITLE = "Zapret Manager"
WINDOW_SIZE = "1000x700"
MIN_SIZE = (800, 560)

# Текущая версия обёртки. Меняется при релизах.
APP_VERSION = "0.1.0"


class MainWindow(ctk.CTk):
    """Главное окно приложения."""

    def __init__(self, cfg: Config) -> None:
        super().__init__()

        self.cfg = cfg
        self.zapret = ZapretManager(cfg)
        self.tgproxy = TgProxyManager(cfg)

        # Настройки темы
        ctk.set_appearance_mode(cfg.get("theme", "dark"))
        ctk.set_default_color_theme("blue")

        # Параметры окна
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

        # Начальное обновление статусов
        self.after(300, self._refresh_zapret_status)
        self.after(400, self._refresh_tgproxy_status)

    # ============================================================
    #  Верхняя панель и статус-бар
    # ============================================================

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, height=56, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            header,
            text="Zapret Manager",
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
    #  Вкладка Zapret
    # ============================================================

    def _build_zapret_tab(self) -> None:
        tab = self.tab_zapret
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(4, weight=1)

        # Статус
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

        # Кнопки
        buttons_frame = ctk.CTkFrame(tab, fg_color="transparent")
        buttons_frame.grid(row=1, column=0, padx=8, pady=4, sticky="ew")

        self.zapret_buttons: list[ctk.CTkButton] = []
        actions = [
            ("Проверить статус", self._on_zapret_status),
            ("Открыть service.bat", self._on_zapret_open_console),
            ("Меню от админа", self._on_zapret_console_admin),
            ("Обновить zapret", self._on_zapret_update),
        ]
        for i, (label, cmd) in enumerate(actions):
            btn = ctk.CTkButton(buttons_frame, text=label, command=cmd, width=180)
            btn.grid(row=0, column=i, padx=4, pady=4, sticky="w")
            self.zapret_buttons.append(btn)

        ctk.CTkLabel(tab, text="Журнал:", anchor="w").grid(
            row=3, column=0, padx=12, pady=(8, 0), sticky="w"
        )
        self.zapret_log = ctk.CTkTextbox(tab, wrap="word")
        self.zapret_log.grid(row=4, column=0, padx=8, pady=(0, 8), sticky="nsew")

    def _refresh_zapret_status(self) -> None:
        installed = self.zapret.is_installed()
        if installed:
            self.zapret_status.configure(
                text="установлен ✓", text_color=("green", "lightgreen")
            )
        else:
            self.zapret_status.configure(
                text="не установлен", text_color=("orange", "orange")
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
        self.set_status("Готово")

    def _on_zapret_open_console(self) -> None:
        try:
            self.zapret.open_console()
            self.log("zapret", "→ Открыто окно service.bat")
        except Exception as e:
            self.log("zapret", f"✗ Ошибка: {e}")

    def _on_zapret_console_admin(self) -> None:
        try:
            ok = self.zapret.open_console_as_admin()
            self.log(
                "zapret",
                "→ Открыто окно service.bat с правами админа" if ok else "✗ UAC отклонён",
            )
        except Exception as e:
            self.log("zapret", f"✗ Ошибка: {e}")

    def _on_zapret_update(self) -> None:
        self._run_async(
            "Обновление zapret",
            work=self._work_zapret_update,
            on_done=self._after_zapret_update,
            tab="zapret",
        )

    def _work_zapret_update(self):
        release = updater.check_zapret_update(self.cfg)
        if release is None:
            return ("no_release", None, None)
        written, skipped = updater.apply_release(
            release,
            target_dir=self.zapret.zapret_dir,
            excludes=self.cfg.exclude_from_update,
        )
        return ("ok", release, (written, skipped))

    def _after_zapret_update(self, result) -> None:
        kind, release, stats = result
        if kind == "no_release":
            self.log("zapret", "✗ Не удалось получить релиз")
        else:
            written, skipped = stats
            self.log(
                "zapret",
                f"→ Обновлён до {release.tag}. Записано: {written}, пропущено: {skipped}",
            )
            self._refresh_zapret_status()
        self.set_status("Готово")

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
        actions = [
            ("Запустить", self._on_tgproxy_start),
            ("Остановить", self._on_tgproxy_stop),
            ("Перезапустить", self._on_tgproxy_restart),
            ("Обновить", self._on_tgproxy_update),
        ]
        for i, (label, cmd) in enumerate(actions):
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
        if self.tgproxy.is_running():
            pid = self.tgproxy.pid
            self.tgproxy_status.configure(
                text=f"запущен (PID {pid})", text_color=("green", "lightgreen")
            )
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

        ctk.CTkLabel(
            info, text="Проверка обновлений компонентов", font=ctk.CTkFont(weight="bold")
        ).grid(row=0, column=0, columnspan=2, padx=12, pady=(10, 6), sticky="w")

        rows = [
            ("Обёртка", "wrapper"),
            ("zapret-discord-youtube", "zapret"),
            ("tg-ws-proxy", "tgproxy"),
        ]
        self.update_labels: dict[str, ctk.CTkLabel] = {}
        for i, (name, key) in enumerate(rows, start=1):
            ctk.CTkLabel(info, text=f"{name}:").grid(
                row=i, column=0, padx=(12, 6), pady=4, sticky="w"
            )
            lbl = ctk.CTkLabel(info, text="—", text_color=("gray40", "gray70"))
            lbl.grid(row=i, column=1, padx=(0, 12), pady=4, sticky="w")
            self.update_labels[key] = lbl

        btns = ctk.CTkFrame(tab, fg_color="transparent")
        btns.grid(row=1, column=0, padx=8, pady=4, sticky="ew")

        self.updates_buttons: list[ctk.CTkButton] = []
        for i, (label, cmd) in enumerate(
            [("Проверить всё", self._on_check_all), ("Обновить всё", self._on_update_all)]
        ):
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

        # Обёртка
        try:
            rel = updater.check_wrapper_update(APP_VERSION, self.cfg)
            result["wrapper"] = rel
        except Exception as e:
            print("wrapper check error:", e)
            result["wrapper"] = None

        # Zapret
        try:
            rel = updater.fetch_latest_release("Flowseal/zapret-discord-youtube")
            result["zapret"] = rel
        except Exception as e:
            print("zapret check error:", e)
            result["zapret"] = None

        # TG proxy
        try:
            rel = updater.fetch_latest_release("Flowseal/tg-ws-proxy")
            result["tgproxy"] = rel
        except Exception as e:
            print("tgproxy check error:", e)
            result["tgproxy"] = None

        return result

    def _after_check_all(self, result: dict) -> None:
        for key, rel in result.items():
            lbl = self.update_labels[key]
            if rel:
                lbl.configure(
                    text=f"доступна {rel.tag}",
                    text_color=("green", "lightgreen"),
                )
                self.log("updates", f"{key}: доступна {rel.tag} ({rel.html_url})")
            else:
                lbl.configure(text="—", text_color=("gray40", "gray70"))
                self.log("updates", f"{key}: нет данных")
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

        # Zapret
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

        # TG proxy
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
            text="Файлы из списка не перезаписываются при обновлении, если уже существуют.",
            anchor="w",
            text_color=("gray40", "gray70"),
            font=ctk.CTkFont(size=12),
        ).grid(row=1, column=0, padx=12, pady=(0, 6), sticky="w")

        self.settings_excludes = ctk.CTkTextbox(tab, wrap="none", height=200)
        self.settings_excludes.grid(row=3, column=0, padx=8, pady=(0, 8), sticky="nsew")
        self.settings_excludes.insert("1.0", "\n".join(self.cfg.exclude_from_update))

        btns = ctk.CTkFrame(tab, fg_color="transparent")
        btns.grid(row=4, column=0, padx=8, pady=4, sticky="ew")

        ctk.CTkButton(btns, text="Сохранить", command=self._on_save_settings, width=140).grid(
            row=0, column=0, padx=4, pady=4, sticky="w"
        )
        ctk.CTkButton(
            btns, text="Сбросить к дефолтным", command=self._on_reset_settings, width=180
        ).grid(row=0, column=1, padx=4, pady=4, sticky="w")

    def _on_save_settings(self) -> None:
        raw = self.settings_excludes.get("1.0", "end")
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        self.cfg.set("exclude_from_update", lines)
        self.cfg.save()
        self.log("updates", f"→ Настройки сохранены ({len(lines)} исключений)")
        self.set_status("Настройки сохранены")

    def _on_reset_settings(self) -> None:
        from app.core.config import DEFAULT_CONFIG

        defaults = DEFAULT_CONFIG["exclude_from_update"]
        self.settings_excludes.delete("1.0", "end")
        self.settings_excludes.insert("1.0", "\n".join(defaults))
        self.set_status("Сброшено к дефолтным (не забудь сохранить)")

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
        """Включает/выключает кнопки вкладки, чтобы не запускать параллельно."""
        buttons_map = {
            "zapret": getattr(self, "zapret_buttons", []),
            "tgproxy": getattr(self, "tgproxy_buttons", []),
            "updates": getattr(self, "updates_buttons", []),
        }
        for btn in buttons_map.get(tab, []):
            btn.configure(state="normal" if enabled else "disabled")

    def _run_async(
        self,
        description: str,
        work: Callable,
        on_done: Callable,
        tab: str,
    ) -> None:
        """
        Запускает work() в фоновом потоке.
        Пока идёт — блокирует кнопки вкладки, пишет статус.
        После — вызывает on_done(result) в главном потоке.
        """
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

    def _finish_async(
        self,
        tab: str,
        on_done: Callable,
        result,
        error: str | None,
    ) -> None:
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