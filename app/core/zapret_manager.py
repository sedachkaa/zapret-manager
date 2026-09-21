"""
Нативное управление zapret-discord-youtube.

Standalone запускает winws.exe с аргументами из:
    1) ImagePath установленной службы (самый надёжный);
    2) парсинга .bat стратегии с поддержкой set "VAR=value",
       многострочных команд через ^, %~dp0, %BIN%, %LISTS%,
       %GameFilterTCP% / %GameFilterUDP%.

Умные кнопки:
    start_smart()    — сам решает, что делать (служба/установка/запуск);
    stop_smart()     — агрессивно останавливает всё, что может держать обход;
    restart_smart()  — стоп + старт.
"""

from __future__ import annotations

import ctypes
import os
import re
import shutil
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.core.config import PROJECT_ROOT, Config


GITHUB_VERSION_URL = "https://raw.githubusercontent.com/Flowseal/zapret-discord-youtube/main/.service/version.txt"
GITHUB_IPSET_URL = "https://raw.githubusercontent.com/Flowseal/zapret-discord-youtube/refs/heads/main/.service/ipset-service.txt"
GITHUB_HOSTS_URL = "https://raw.githubusercontent.com/Flowseal/zapret-discord-youtube/refs/heads/main/.service/hosts"
GITHUB_RELEASE_URL = "https://github.com/Flowseal/zapret-discord-youtube/releases/tag/"

SERVICE_NAME = "zapret"
USER_AGENT = "zapret-manager/1.0"

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


@dataclass
class ZapretResult:
    action: str
    ok: bool
    message: str = ""
    details: str = ""

    def summary(self) -> str:
        prefix = "OK" if self.ok else "ОШИБКА"
        s = f"[{self.action}] {prefix}"
        if self.message:
            s += f": {self.message}"
        return s


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _run(cmd, *, timeout: int = 30, shell: bool = False) -> tuple[int, str, str]:
    try:
        if isinstance(cmd, str):
            shell = True
        proc = subprocess.run(
            cmd, shell=shell, capture_output=True, timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
        return proc.returncode, _decode(proc.stdout), _decode(proc.stderr)
    except subprocess.TimeoutExpired:
        return -1, "", f"Таймаут {timeout} сек"
    except Exception as e:
        return -1, "", str(e)


def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "cp866", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _tasklist_has(image_name: str) -> bool:
    rc, out, _ = _run(["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/NH"], timeout=5)
    if rc != 0:
        return False
    low = out.lower()
    return image_name.lower() in low and "no tasks" not in low


def _tasklist_pid(image_name: str) -> Optional[int]:
    rc, out, _ = _run(["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/FO", "CSV", "/NH"], timeout=5)
    if rc != 0:
        return None
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) >= 2 and parts[0].lower() == image_name.lower():
            try:
                return int(parts[1])
            except ValueError:
                pass
    return None


def _sc_query_status(service: str) -> Optional[str]:
    rc, out, _ = _run(["sc", "query", service], timeout=5)
    if rc != 0:
        return None
    m = re.search(r"STATE\s*:\s*\d+\s+(\w+)", out)
    return m.group(1) if m else None


def _sc_query_exit_code(service: str) -> Optional[int]:
    rc, out, _ = _run(["sc", "query", service], timeout=5)
    if rc != 0:
        return None
    m = re.search(r"WIN32_EXIT_CODE\s*:\s*(\d+)", out)
    return int(m.group(1)) if m else None


def _http_get(url: str, *, timeout: int = 15) -> Optional[str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"[zapret] http get failed: {e}")
        return None


def _http_download(url: str, dest: Path, *, timeout: int = 30) -> bool:
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=timeout) as resp, dest.open("wb") as f:
            shutil.copyfileobj(resp, f)
        return True
    except Exception as e:
        print(f"[zapret] http download failed: {e}")
        return False


def _tokenize_args(s: str) -> list[str]:
    """
    Правильный парсер аргументов Windows-командной строки.
    Убирает кавычки где угодно (в т.ч. внутри токена), собирает соседние
    фрагменты без пробела в один аргумент.
    """
    result: list[str] = []
    cur: list[str] = []
    in_quote = False
    for ch in s:
        if ch == '"':
            in_quote = not in_quote
            continue
        if ch.isspace() and not in_quote:
            if cur:
                result.append("".join(cur))
                cur = []
            continue
        cur.append(ch)
    if cur:
        result.append("".join(cur))
    return result


def _parse_imagepath(image_path: str) -> tuple[str, list[str]]:
    s = image_path.strip()
    if s.startswith('"'):
        end = s.find('"', 1)
        if end == -1:
            return s.strip('"'), []
        exe = s[1:end]
        rest = s[end + 1:].strip()
    else:
        sp = s.find(" ")
        if sp == -1:
            return s, []
        exe = s[:sp]
        rest = s[sp + 1:].strip()
    return exe, _tokenize_args(rest)


class ZapretManager:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._proc: subprocess.Popen | None = None
        self._strategy_name: str = ""

    # --- Пути ----------------------------------------------------------

    @property
    def zapret_dir(self) -> Path:
        return PROJECT_ROOT / "zapret"

    @property
    def bin_dir(self) -> Path:
        return self.zapret_dir / "bin"

    @property
    def lists_dir(self) -> Path:
        return self.zapret_dir / "lists"

    @property
    def utils_dir(self) -> Path:
        return self.zapret_dir / "utils"

    @property
    def winws_path(self) -> Path:
        return self.bin_dir / "winws.exe"

    @property
    def ipset_path(self) -> Path:
        return self.lists_dir / "ipset-all.txt"

    @property
    def ipset_backup_path(self) -> Path:
        return self.lists_dir / "ipset-all.txt.backup"

    @property
    def game_filter_flag(self) -> Path:
        return self.utils_dir / "game_filter.enabled"

    @property
    def check_updates_flag(self) -> Path:
        return self.utils_dir / "check_updates.enabled"

    # --- Проверки ------------------------------------------------------

    def is_installed(self) -> bool:
        return self.winws_path.exists() and self.bin_dir.exists()

    def is_winws_running(self) -> bool:
        if self._proc is not None and self._proc.poll() is None:
            return True
        return _tasklist_has("winws.exe")

    def is_service_running(self) -> bool:
        return _sc_query_status(SERVICE_NAME) == "RUNNING"

    def is_service_installed(self) -> bool:
        return _sc_query_status(SERVICE_NAME) is not None

    def is_active(self) -> bool:
        return self.is_winws_running() or self.is_service_running()

    def is_our_process(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def get_winws_pid(self) -> Optional[int]:
        if self._proc is not None and self._proc.poll() is None:
            return self._proc.pid
        return _tasklist_pid("winws.exe")

    def get_local_version(self) -> str:
        bat = self.zapret_dir / "service.bat"
        if bat.exists():
            try:
                text = bat.read_text(encoding="cp866", errors="replace")
                m = re.search(r'LOCAL_VERSION=([\d.]+)', text)
                if m:
                    return m.group(1)
            except OSError:
                pass
        return "?"

    def get_active_strategy_name(self) -> str:
        if self.is_our_process() and self._strategy_name:
            return self._strategy_name
        if self.is_service_running() or self.is_service_installed():
            rc, out, _ = _run([
                "reg", "query",
                rf"HKLM\System\CurrentControlSet\Services\{SERVICE_NAME}",
                "/v", "zapret-discord-youtube"
            ], timeout=5)
            if rc == 0:
                m = re.search(r"zapret-discord-youtube\s+REG_SZ\s+(.+)", out)
                if m:
                    return m.group(1).strip()
        return ""

    # ================================================================
    #  Умные кнопки
    # ================================================================

    def _wait_until_stable(self, *, timeout: float = 20.0,
                           stable_for: float = 2.0) -> bool:
        """
        Ждёт, пока служба zapret продержится в состоянии RUNNING
        минимум `stable_for` секунд подряд. Защищает от ложного «успеха»,
        когда служба мигает RUNNING → STOPPED из-за падения winws.exe.
        """
        deadline = time.time() + timeout
        run_started: float | None = None
        while time.time() < deadline:
            if self.is_service_running():
                if run_started is None:
                    run_started = time.time()
                elif time.time() - run_started >= stable_for:
                    return True
            else:
                run_started = None
            time.sleep(0.3)
        return False

    def start_smart(self, strategy_bat: Path) -> ZapretResult:
        """
        Умный запуск:
        - служба стабильно работает → уже запущено;
        - служба установлена, стратегия та же → sc start; если не стабилизируется,
          принудительно переустанавливаем;
        - служба установлена с другой стратегией → переустановка;
        - службы нет → установка.
        """
        if not is_admin():
            return ZapretResult("start", False, "нужны права администратора")
        if not strategy_bat.exists():
            return ZapretResult("start", False, f"стратегия не найдена: {strategy_bat}")

        # 1. Служба реально работает
        if self.is_service_running() and self.is_winws_running():
            return ZapretResult(
                "start", True,
                f"служба zapret уже запущена (стратегия: {self.get_active_strategy_name() or '?'})",
            )

        # 2. Служба установлена с той же стратегией — пробуем быстрый sc start
        if self.is_service_installed():
            current_strat = self.get_active_strategy_name()
            if current_strat == strategy_bat.stem:
                print(f"[zapret] start_smart: служба с нужной стратегией, пробую sc start")
                _run(["sc", "start", SERVICE_NAME], timeout=25)
                if self._wait_until_stable(timeout=20.0, stable_for=2.0):
                    return ZapretResult(
                        "start", True,
                        f"служба zapret запущена (стратегия: {current_strat})",
                    )
                print("[zapret] start_smart: sc start не дал стабильного результата, переустанавливаю службу")
                return self.install_service(strategy_bat)

            # Стратегия другая — переустановка
            print(f"[zapret] start_smart: стратегия изменилась ({current_strat} → {strategy_bat.stem}), переустанавливаю")
            return self.install_service(strategy_bat)

        # 3. Службы нет — установить
        print(f"[zapret] start_smart: служба не установлена, устанавливаю {strategy_bat.stem}")
        return self.install_service(strategy_bat)

    def stop_smart(self) -> ZapretResult:
        """
        Умная остановка (агрессивная, без early-return):
        - наш standalone → terminate;
        - служба → net stop + добить winws.exe + сбросить стратегию из реестра;
        - любые внешние winws.exe → taskkill /T /F;
        - драйвер WinDivert → попытка выгрузить.
        """
        lines: list[str] = []

        if self.is_our_process():
            r = self.stop_standalone()
            lines.append(r.message)

        if self.is_service_running() or _sc_query_status(SERVICE_NAME) is not None:
            r = self._stop_service_only()
            lines.append(r.message)

        killed = self._kill_all_winws()
        if killed:
            lines.append(f"убито: {', '.join(killed)}")

        drv = self._unload_windivert()
        if drv:
            lines.append("; ".join(drv))

        if not lines:
            return ZapretResult("stop", True, "не был запущен")
        return ZapretResult("stop", True, "; ".join(lines))

    def restart_smart(self, strategy_bat: Path) -> ZapretResult:
        """Стоп + старт."""
        self.stop_smart()
        time.sleep(0.8)
        return self.start_smart(strategy_bat)

    # ================================================================
    #  Служба — статус и управление
    # ================================================================

    def get_service_status(self) -> ZapretResult:
        lines: list[str] = []
        svc = _sc_query_status(SERVICE_NAME)
        wd = _sc_query_status("WinDivert")
        lines.append(f"Служба {SERVICE_NAME}: {svc or 'не установлена'}")
        lines.append(f"Служба WinDivert: {wd or 'не найдена'}")

        if svc == "STOPPED":
            code = _sc_query_exit_code(SERVICE_NAME)
            if code == 1067:
                lines.append("⚠ Последний exit code службы: 1067 (PROCESS_ABORTED) "
                             "— winws.exe упал при старте")
            elif code and code != 0:
                lines.append(f"⚠ Последний exit code службы: {code}")

        if self.is_winws_running():
            pid = self.get_winws_pid()
            lines.append(f"winws.exe: ЗАПУЩЕН (PID {pid}) ✓")
        else:
            lines.append("winws.exe: не запущен ✗")

        if svc == "RUNNING":
            strat = self.get_active_strategy_name()
            if strat:
                lines.append(f"Стратегия: {strat}")

        rc, out, _ = _run(["driverquery", "/FO", "CSV", "/NH"], timeout=15)
        if rc == 0:
            wd_drv = [l for l in out.splitlines() if "windivert" in l.lower()]
            if wd_drv:
                lines.append(f"Драйвер WinDivert загружен: {wd_drv[0].strip()}")
            else:
                lines.append("Драйвер WinDivert: не загружен ✓")
        else:
            lines.append("driverquery недоступен")

        suspects = self._list_bypass_processes()
        if suspects:
            lines.append("Процессы-обходчики: " + "; ".join(suspects))
        else:
            lines.append("Процессы-обходчики: не найдены ✓")

        rc, out, _ = _run(["netsh", "interface", "tcp", "show", "global"], timeout=10)
        if "timestamps" in out.lower() and "enabled" in out.lower():
            lines.append("TCP timestamps: включены ✓")
        else:
            lines.append("TCP timestamps: выключены")

        if not list(self.bin_dir.glob("*.sys")):
            lines.append("WinDivert64.sys: НЕ найден ✗")

        return ZapretResult("status", True, "статус получен", "\n".join(lines))

    def enable_tcp_timestamps(self) -> ZapretResult:
        rc, out, _ = _run(["netsh", "interface", "tcp", "show", "global"], timeout=10)
        if "timestamps" in out.lower() and "enabled" in out.lower():
            return ZapretResult("tcp", True, "уже включены")
        rc, out, err = _run(["netsh", "interface", "tcp", "set", "global", "timestamps=enabled"], timeout=15)
        if rc == 0:
            return ZapretResult("tcp", True, "включены")
        return ZapretResult("tcp", False, "не удалось включить", err)

    def list_strategies(self) -> list[Path]:
        if not self.zapret_dir.exists():
            return []
        bats = [
            p for p in self.zapret_dir.glob("*.bat")
            if not p.name.lower().startswith("service")
        ]

        def sort_key(p: Path):
            return [int(x) if x.isdigit() else x.lower() for x in re.split(r"(\d+)", p.name)]

        return sorted(bats, key=sort_key)

    # ---- парсинг bat --------------------------------------------------

    def _game_filter_args(self) -> dict[str, str]:
        mode = self.get_game_filter_status()
        if mode == "all":
            return {"GameFilter": "1024-65535", "GameFilterTCP": "1024-65535", "GameFilterUDP": "1024-65535"}
        if mode == "tcp":
            return {"GameFilter": "1024-65535", "GameFilterTCP": "1024-65535", "GameFilterUDP": "12"}
        if mode == "udp":
            return {"GameFilter": "1024-65535", "GameFilterTCP": "12", "GameFilterUDP": "1024-65535"}
        return {"GameFilter": "12", "GameFilterTCP": "12", "GameFilterUDP": "12"}

    def _collect_bat_variables(self, text: str) -> dict[str, str]:
        variables: dict[str, str] = {}
        for line in text.splitlines():
            line = line.strip()
            m = re.match(r'^set\s+"?([A-Za-z_~][A-Za-z0-9_~]*)=(.*?)"?\s*$', line, re.IGNORECASE)
            if m:
                variables[m.group(1).upper()] = m.group(2)
        for line in text.splitlines():
            line = line.strip()
            m = re.match(r'^set\s+/a\s+"?([A-Za-z_][A-Za-z0-9_]*)=(.*?)"?\s*$', line, re.IGNORECASE)
            if m:
                variables.setdefault(m.group(1).upper(), m.group(2))
        return variables

    @staticmethod
    def _join_continuation_lines(text: str) -> list[str]:
        result: list[str] = []
        buf = ""
        for raw in text.splitlines():
            line = raw.rstrip()
            if line.endswith("^"):
                buf += line[:-1] + " "
            else:
                buf += line
                result.append(buf)
                buf = ""
        if buf:
            result.append(buf)
        return result

    def _substitute(self, s: str, variables: dict[str, str], *, max_passes: int = 6) -> str:
        for _ in range(max_passes):
            prev = s
            for name, value in variables.items():
                s = s.replace(f"%{name}%", value)
            if s == prev:
                break
        s = re.sub(r"%[A-Za-z_~][A-Za-z0-9_~]*%", "", s)
        return s

    def _parse_strategy_bat(self, bat_file: Path) -> Optional[list[str]]:
        try:
            text = bat_file.read_text(encoding="cp866", errors="replace")
        except OSError as e:
            print(f"[zapret] не прочитать {bat_file}: {e}")
            return None

        variables = self._collect_bat_variables(text)

        zapret_str = str(self.zapret_dir)
        bin_str = str(self.bin_dir)
        lists_str = str(self.lists_dir)

        variables["~DP0"] = zapret_str + "\\"
        variables["BIN"] = bin_str + "\\"
        variables["LISTS"] = lists_str + "\\"
        variables["QUOTE"] = ""
        variables["~N0"] = bat_file.stem

        variables.update(self._game_filter_args())

        logical_lines = self._join_continuation_lines(text)

        for line in logical_lines:
            low = line.lower()
            if "winws.exe" not in low:
                continue

            idx = low.index("winws.exe") + len("winws.exe")
            rest = line[idx:].lstrip()
            if rest.startswith('"'):
                rest = rest[1:]

            rest = rest.replace("%~dp0", zapret_str + "\\")
            rest = rest.replace("..\\", zapret_str + "\\")
            rest = self._substitute(rest, variables)

            tokens = _tokenize_args(rest)
            if tokens:
                skip = {"1>nul", "2>nul", "1>NUL", "2>NUL", ">nul", ">NUL",
                        "&", "&&", "||", "|", ">", "1>", "2>"}
                tokens = [t for t in tokens if t not in skip]
                if tokens:
                    return tokens
        return None

    # ---- ImagePath из реестра -----------------------------------------

    def _get_service_image_path(self) -> Optional[str]:
        rc, out, _ = _run([
            "reg", "query",
            rf"HKLM\System\CurrentControlSet\Services\{SERVICE_NAME}",
            "/v", "ImagePath"
        ], timeout=5)
        if rc != 0:
            return None
        m = re.search(r"ImagePath\s+REG_(?:EXPAND_)?SZ\s+(.+)", out)
        return m.group(1).strip() if m else None

    def _get_service_args(self) -> Optional[list[str]]:
        image_path = self._get_service_image_path()
        if not image_path:
            return None
        exe, args = _parse_imagepath(image_path)
        if Path(exe).name.lower() != "winws.exe":
            print(f"[zapret] ImagePath exe не winws.exe: {exe}")
        return args or None

    # ---- install / remove ---------------------------------------------

    def install_service(self, strategy_bat: Path) -> ZapretResult:
        if not is_admin():
            return ZapretResult("install", False, "нужны права администратора")
        if not strategy_bat.exists():
            return ZapretResult("install", False, f"стратегия не найдена: {strategy_bat}")

        args = self._parse_strategy_bat(strategy_bat)
        if not args:
            return ZapretResult("install", False,
                                f"не удалось распарсить {strategy_bat.name}",
                                "проверьте, что в файле есть строка с winws.exe")

        winws = str(self.winws_path)
        args_joined = " ".join(f'"{a}"' if " " in a else a for a in args)
        image_path = f'"{winws}" {args_joined}'

        print(f"[zapret] ImagePath = {image_path}")

        # Полная зачистка перед установкой
        _run(["net", "stop", SERVICE_NAME], timeout=20)
        _run(["sc", "delete", SERVICE_NAME], timeout=15)
        _run(["taskkill", "/F", "/T", "/IM", "winws.exe"], timeout=10)
        time.sleep(0.5)

        rc, out, err = _run(
            ["sc", "create", SERVICE_NAME,
             "binPath=", "placeholder.exe",
             "DisplayName=", "zapret",
             "start=", "auto"],
            timeout=20,
        )
        if rc != 0:
            return ZapretResult("install", False, "sc create failed", err or out)

        rc, out, err = _run([
            "reg", "add",
            rf"HKLM\SYSTEM\CurrentControlSet\Services\{SERVICE_NAME}",
            "/v", "ImagePath", "/t", "REG_SZ", "/d", image_path, "/f",
        ], timeout=10)
        if rc != 0:
            return ZapretResult("install", False, "reg add ImagePath failed", err or out)

        _run(["sc", "description", SERVICE_NAME, "Zapret DPI bypass software"], timeout=10)
        _run([
            "reg", "add",
            rf"HKLM\System\CurrentControlSet\Services\{SERVICE_NAME}",
            "/v", "zapret-discord-youtube", "/t", "REG_SZ",
            "/d", strategy_bat.stem, "/f",
        ], timeout=10)

        _run(["sc", "start", SERVICE_NAME], timeout=25)

        # Ждём СТАБИЛЬНОГО RUNNING (≥2 сек подряд), иначе winws мог упасть
        if self._wait_until_stable(timeout=20.0, stable_for=2.0):
            return ZapretResult("install", True,
                                f"служба установлена со стратегией {strategy_bat.stem}")

        rc2, out2, _ = _run(["sc", "query", SERVICE_NAME], timeout=5)
        exit_code = _sc_query_exit_code(SERVICE_NAME)
        hint = ""
        if exit_code == 1067:
            hint = " — winws.exe упал при старте. Возможно, неверные аргументы в .bat."
        return ZapretResult(
            "install", False,
            f"служба не удержалась в RUNNING{hint}",
            f"ImagePath:\n{image_path}\n\nsc query:\n{out2}",
        )

    def remove_service(self) -> ZapretResult:
        if not is_admin():
            return ZapretResult("remove", False, "нужны права администратора")
        lines: list[str] = []

        rc, _, _ = _run(["sc", "query", SERVICE_NAME], timeout=5)
        if rc == 0:
            _run(["net", "stop", SERVICE_NAME], timeout=20)
            _run(["sc", "delete", SERVICE_NAME], timeout=15)
            lines.append(f"служба {SERVICE_NAME} удалена")
        else:
            lines.append(f"служба {SERVICE_NAME} не установлена")

        if _tasklist_has("winws.exe"):
            _run(["taskkill", "/IM", "winws.exe", "/F"], timeout=10)
            lines.append("winws.exe остановлен")

        for name in ("WinDivert", "WinDivert14"):
            rc, _, _ = _run(["sc", "query", name], timeout=5)
            if rc == 0:
                _run(["net", "stop", name], timeout=15)
                _run(["sc", "delete", name], timeout=10)
                lines.append(f"служба {name} удалена")

        self._proc = None
        self._strategy_name = ""
        return ZapretResult("remove", True, "готово", "\n".join(lines))

    # ================================================================
    #  Standalone (низкоуровневые)
    # ================================================================

    def start_standalone(self, strategy_bat: Path, *, force: bool = False) -> ZapretResult:
        if not is_admin():
            return ZapretResult("start", False, "нужны права администратора")
        if not strategy_bat.exists():
            return ZapretResult("start", False, f"стратегия не найдена: {strategy_bat}")

        if self._proc is not None and self._proc.poll() is None:
            self.stop_standalone()

        if self.is_service_running() or _sc_query_status(SERVICE_NAME) in ("START_PENDING", "STOP_PENDING"):
            if not force:
                return ZapretResult(
                    "start", False,
                    "служба zapret уже работает",
                    "Нажмите «Остановить» или согласитесь остановить её автоматически.",
                )
            stop_res = self._stop_service_only()
            print(f"[zapret] auto-stop service before standalone: {stop_res.summary()}")

        if _tasklist_has("winws.exe"):
            _run(["taskkill", "/IM", "winws.exe", "/F"], timeout=10)
            time.sleep(0.5)

        args: Optional[list[str]] = None
        source = "bat"

        if self.is_service_installed():
            svc_args = self._get_service_args()
            if svc_args:
                joined = " ".join(svc_args)
                if "--wf-tcp" in joined or "--wf-udp" in joined:
                    args = svc_args
                    source = "service"

        if not args:
            args = self._parse_strategy_bat(strategy_bat)

        if not args:
            return ZapretResult("start", False,
                                "не удалось получить аргументы",
                                "Ни из ImagePath службы, ни из .bat-файла.")

        cmd = [str(self.winws_path)] + args
        print(f"[zapret] start_standalone (source={source}): {' '.join(cmd)[:300]}...")

        try:
            self._proc = subprocess.Popen(
                cmd,
                cwd=str(self.bin_dir),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW,
                close_fds=True,
            )
        except OSError as e:
            self._proc = None
            return ZapretResult("start", False, f"не удалось запустить: {e}")

        self._strategy_name = strategy_bat.stem
        time.sleep(1.5)

        if self._proc.poll() is not None:
            code = self._proc.returncode
            try:
                out_b, err_b = self._proc.communicate(timeout=2)
                err_text = _decode(err_b)
                out_text = _decode(out_b)
            except Exception:
                err_text = ""
                out_text = ""

            self._proc = None
            self._strategy_name = ""

            details = f"источник аргументов: {source}\n"
            if err_text.strip():
                details += f"stderr:\n{err_text.strip()}\n\n"
            if out_text.strip():
                details += f"stdout:\n{out_text.strip()}"
            return ZapretResult("start", False,
                                f"winws.exe завершился с кодом {code}", details)

        return ZapretResult("start", True,
                            f"запущено (PID {self._proc.pid}, стратегия: {strategy_bat.stem})")

    def stop_standalone(self) -> ZapretResult:
        killed = False
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3)
                killed = True
            except Exception:
                try:
                    self._proc.kill()
                    self._proc.wait(timeout=2)
                    killed = True
                except Exception as e:
                    print(f"[zapret] terminate/kill failed: {e}")
            self._proc = None

        if _tasklist_has("winws.exe"):
            _run(["taskkill", "/IM", "winws.exe", "/F"], timeout=10)
            killed = True

        self._strategy_name = ""
        if killed:
            return ZapretResult("stop", True, "winws.exe остановлен")
        return ZapretResult("stop", True, "не был запущен")

    def restart_standalone(self, strategy_bat: Path, *, force: bool = False) -> ZapretResult:
        self.stop_standalone()
        time.sleep(0.5)
        return self.start_standalone(strategy_bat, force=force)

    def _stop_service_only(self) -> ZapretResult:
        lines: list[str] = []
        if _sc_query_status(SERVICE_NAME) is not None:
            _run(["net", "stop", SERVICE_NAME], timeout=25)
            lines.append("служба zapret остановлена")
        for name in ("WinDivert", "WinDivert14"):
            if _sc_query_status(name) is not None:
                _run(["net", "stop", name], timeout=10)
                lines.append(f"служба {name} остановлена")
        if self._clear_strategy_registry():
            lines.append("стратегия сброшена")
        killed = self._kill_all_winws()
        if killed:
            lines.append(f"убито: {', '.join(killed)}")
        return ZapretResult("stop_service", True,
                            "; ".join(lines) if lines else "нечего останавливать")

    def _clear_strategy_registry(self) -> bool:
        rc, _, _ = _run([
            "reg", "delete",
            rf"HKLM\SYSTEM\CurrentControlSet\Services\{SERVICE_NAME}",
            "/v", "zapret-discord-youtube", "/f",
        ], timeout=5)
        return rc == 0

    def _kill_all_winws(self) -> list[str]:
        killed: list[str] = []

        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.kill()
                killed.append("наш процесс")
            except Exception:
                pass
        self._proc = None
        self._strategy_name = ""

        had_before = _tasklist_has("winws.exe")

        if had_before:
            _run(["taskkill", "/F", "/T", "/IM", "winws.exe"], timeout=15)
            time.sleep(0.4)

        if _tasklist_has("winws.exe"):
            _run(["taskkill", "/F", "/IM", "winws.exe"], timeout=10)
            time.sleep(0.4)

        still = _tasklist_has("winws.exe")
        if still:
            killed.append("winws.exe (НЕ УБИТ!)")
        elif had_before:
            killed.append("winws.exe")
        return killed

    def _unload_windivert(self) -> list[str]:
        lines: list[str] = []
        for name in ("WinDivert", "WinDivert1.4", "WinDivert14"):
            st = _sc_query_status(name)
            if st is None:
                continue
            if st == "RUNNING":
                _run(["sc", "stop", name], timeout=10)
                time.sleep(0.4)
                st2 = _sc_query_status(name) or "не найдена"
                lines.append(f"{name}: {st} → {st2}")
            else:
                lines.append(f"{name}: {st}")
        return lines

    def _list_bypass_processes(self) -> list[str]:
        patterns = ("winws", "windivert", "goodbyedpi", "zapret", "byedpi", "spoofdpi")
        rc, out, _ = _run(["tasklist", "/FO", "CSV", "/NH"], timeout=10)
        found: list[str] = []
        if rc == 0:
            for line in out.splitlines():
                low = line.lower()
                if any(p in low for p in patterns):
                    parts = [p.strip('"') for p in line.split('","')]
                    if len(parts) >= 2:
                        found.append(f"{parts[0]} (PID {parts[1]})")
        return found

    def stop_before_update(self) -> ZapretResult:
        lines: list[str] = []
        rc, _, _ = _run(["sc", "query", SERVICE_NAME], timeout=5)
        if rc == 0:
            _run(["net", "stop", SERVICE_NAME], timeout=20)
            lines.append("служба zapret остановлена")
        for name in ("WinDivert", "WinDivert14"):
            rc, _, _ = _run(["sc", "query", name], timeout=5)
            if rc == 0:
                _run(["net", "stop", name], timeout=10)
                lines.append(f"служба {name} остановлена")
        if _tasklist_has("winws.exe"):
            _run(["taskkill", "/IM", "winws.exe", "/F"], timeout=10)
            lines.append("winws.exe убит")
        self._proc = None
        self._strategy_name = ""
        time.sleep(0.5)
        return ZapretResult("stop_before_update", True,
                            "; ".join(lines) if lines else "нечего останавливать")

    # ================================================================
    #  Game Filter / IPSet / Auto-Update
    # ================================================================

    def get_game_filter_status(self) -> str:
        if not self.game_filter_flag.exists():
            return "disabled"
        try:
            mode = self.game_filter_flag.read_text(encoding="utf-8").strip().lower()
        except OSError:
            return "disabled"
        return mode if mode in ("all", "tcp", "udp") else "disabled"

    def set_game_filter(self, mode: str) -> ZapretResult:
        mode = mode.lower().strip()
        if mode not in ("disabled", "all", "tcp", "udp"):
            return ZapretResult("game_filter", False, f"неизвестный режим: {mode}")
        try:
            if mode == "disabled":
                if self.game_filter_flag.exists():
                    self.game_filter_flag.unlink()
                return ZapretResult("game_filter", True, "игровой фильтр выключен")
            self.utils_dir.mkdir(parents=True, exist_ok=True)
            self.game_filter_flag.write_text(mode + "\n", encoding="utf-8")
            return ZapretResult("game_filter", True, f"игровой фильтр: {mode}")
        except OSError as e:
            return ZapretResult("game_filter", False, "ошибка записи", str(e))

    def get_ipset_status(self) -> str:
        if not self.ipset_path.exists():
            return "unknown"
        try:
            text = self.ipset_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return "unknown"
        s = text.strip()
        if not s:
            return "any"
        if s == "203.0.113.113/32":
            return "none"
        return "loaded"

    def toggle_ipset(self) -> ZapretResult:
        status = self.get_ipset_status()
        try:
            if status == "loaded":
                if self.ipset_path.exists():
                    shutil.copy2(self.ipset_path, self.ipset_backup_path)
                self.ipset_path.write_text("203.0.113.113/32\n", encoding="utf-8")
                return ZapretResult("ipset", True, "IPSet → none")
            elif status == "none":
                self.ipset_path.write_text("", encoding="utf-8")
                return ZapretResult("ipset", True, "IPSet → any")
            elif status == "any":
                if self.ipset_backup_path.exists():
                    shutil.copy2(self.ipset_backup_path, self.ipset_path)
                    return ZapretResult("ipset", True, "IPSet → loaded (из backup)")
                return ZapretResult("ipset", False, "нет backup для восстановления")
            return ZapretResult("ipset", False, f"неизвестный статус: {status}")
        except OSError as e:
            return ZapretResult("ipset", False, "ошибка", str(e))

    def update_ipset(self) -> ZapretResult:
        if not _http_download(GITHUB_IPSET_URL, self.ipset_path):
            return ZapretResult("update_ipset", False, "не удалось скачать")
        return ZapretResult("update_ipset", True, "ipset-all.txt обновлён")

    def get_auto_update_status(self) -> str:
        return "enabled" if self.check_updates_flag.exists() else "disabled"

    def toggle_auto_update(self) -> ZapretResult:
        try:
            self.utils_dir.mkdir(parents=True, exist_ok=True)
            if self.check_updates_flag.exists():
                self.check_updates_flag.unlink()
                return ZapretResult("auto_update", True, "выключено")
            self.check_updates_flag.write_text("ENABLED\n", encoding="utf-8")
            return ZapretResult("auto_update", True, "включено")
        except OSError as e:
            return ZapretResult("auto_update", False, "ошибка", str(e))

    def check_hosts_status(self) -> ZapretResult:
        etalon = _http_get(GITHUB_HOSTS_URL)
        if not etalon:
            return ZapretResult("hosts", False, "не удалось скачать эталон")
        hosts_path = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "drivers" / "etc" / "hosts"
        if not hosts_path.exists():
            return ZapretResult("hosts", False, "системный hosts не найден")
        try:
            current = hosts_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return ZapretResult("hosts", False, "не прочитать hosts", str(e))
        etalon_lines = [l for l in etalon.splitlines() if l.strip()]
        if not etalon_lines:
            return ZapretResult("hosts", False, "пустой эталон")
        first, last = etalon_lines[0], etalon_lines[-1]
        if first in current and last in current:
            return ZapretResult("hosts", True, "hosts актуален")
        return ZapretResult("hosts", False, "hosts требует обновления",
                            f"нужно вручную скопировать из:\n{GITHUB_HOSTS_URL}")

    def open_hosts_editor(self) -> ZapretResult:
        etalon = _http_get(GITHUB_HOSTS_URL)
        if not etalon:
            return ZapretResult("hosts_open", False, "не удалось скачать эталон")
        try:
            tmp = Path(os.environ.get("TEMP", ".")) / "zapret_hosts_new.txt"
            tmp.write_text(etalon, encoding="utf-8")
            os.startfile(str(tmp))
            hosts = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "drivers" / "etc" / "hosts"
            _run(["explorer", "/select,", str(hosts)], timeout=10)
            return ZapretResult("hosts_open", True, f"открыт эталон: {tmp}")
        except OSError as e:
            return ZapretResult("hosts_open", False, "ошибка", str(e))

    def check_updates(self) -> ZapretResult:
        version = _http_get(GITHUB_VERSION_URL)
        if not version:
            return ZapretResult("check_updates", False, "не удалось получить версию с GitHub")
        version = version.strip()
        local = self.get_local_version()
        if local == version:
            return ZapretResult("check_updates", True, f"последняя версия уже установлена: {local}")
        return ZapretResult("check_updates", True,
                            f"доступна новая версия: {version} (у вас {local})",
                            GITHUB_RELEASE_URL + version)

    def list_fakes(self) -> list[Path]:
        if not self.bin_dir.exists():
            return []
        return sorted([
            p for p in self.bin_dir.glob("*.bin")
            if not p.name.upper().startswith("ACTIVE_")
        ])

    def replace_active_fake(self, active: str, source: Path) -> ZapretResult:
        if active not in ("discord", "game"):
            return ZapretResult("fake", False, "active должен быть 'discord' или 'game'")
        if not source.exists() or source.parent != self.bin_dir:
            return ZapretResult("fake", False, f"source не в bin/: {source}")
        target_name = "ACTIVE_DISCORD_UDP.bin" if active == "discord" else "ACTIVE_GAME_UDP.bin"
        target = self.bin_dir / target_name
        try:
            shutil.copy2(source, target)
            return ZapretResult("fake", True, f"{active} → {source.name}")
        except OSError as e:
            return ZapretResult("fake", False, "ошибка копирования", str(e))

    def run_diagnostics(self) -> ZapretResult:
        lines: list[str] = []
        if _sc_query_status("BFE") == "RUNNING":
            lines.append("✓ Base Filtering Engine запущен")
        else:
            lines.append("✗ Base Filtering Engine не запущен (нужен для zapret)")

        rc, out, _ = _run(["netsh", "interface", "tcp", "show", "global"], timeout=10)
        if "timestamps" in out.lower() and "enabled" in out.lower():
            lines.append("✓ TCP timestamps включены")
        else:
            lines.append("? TCP timestamps выключены — можно включить")

        if re.search(r"[а-яА-ЯёЁ]", str(self.zapret_dir)):
            lines.append("? Путь содержит кириллицу — может мешать")
        else:
            lines.append("✓ Путь без кириллицы")

        onedrive = os.environ.get("OneDrive", "")
        if onedrive and str(self.zapret_dir).lower().startswith(onedrive.lower()):
            lines.append("✗ zapret в OneDrive — может мешать")
        else:
            lines.append("✓ Не в OneDrive")

        if _tasklist_has("AdguardSvc.exe"):
            lines.append("✗ Adguard запущен — может конфликтовать")
        else:
            lines.append("✓ Adguard не запущен")

        if not list(self.bin_dir.glob("*.sys")):
            lines.append("✗ WinDivert64.sys не найден в bin/")
        else:
            lines.append("✓ WinDivert64.sys на месте")

        return ZapretResult("diagnostics", True, "готово", "\n".join(lines))

    def run_tests(self) -> ZapretResult:
        script = self.utils_dir / "test zapret.ps1"
        if not script.exists():
            return ZapretResult("tests", False, f"не найден {script}")
        try:
            subprocess.Popen(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                cwd=str(self.zapret_dir),
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            )
            return ZapretResult("tests", True, "тесты запущены в отдельном окне")
        except OSError as e:
            return ZapretResult("tests", False, "не удалось запустить", str(e))

    def open_folder(self) -> bool:
        if not self.zapret_dir.exists():
            return False
        try:
            os.startfile(str(self.zapret_dir))
            return True
        except OSError:
            return False

    def open_lists_folder(self) -> bool:
        if not self.lists_dir.exists():
            return False
        try:
            os.startfile(str(self.lists_dir))
            return True
        except OSError:
            return False

    def edit_user_lists(self) -> bool:
        target = self.lists_dir / "list-general-user.txt"
        if not target.exists():
            try:
                self.lists_dir.mkdir(parents=True, exist_ok=True)
                target.write_text("# Список доменов для обхода\n", encoding="utf-8")
            except OSError:
                return False
        try:
            os.startfile(str(target))
            return True
        except OSError:
            return False

    def edit_main_list(self) -> bool:
        target = self.lists_dir / "list-general.txt"
        if not target.exists():
            try:
                self.lists_dir.mkdir(parents=True, exist_ok=True)
                target.write_text("# Список доменов для обхода\n", encoding="utf-8")
            except OSError:
                return False
        try:
            os.startfile(str(target))
            return True
        except OSError:
            return False

    def get_main_list_info(self) -> dict[str, int]:
        target = self.lists_dir / "list-general.txt"
        if not target.exists():
            return {"exists": 0, "lines": 0, "size": 0}
        try:
            data = target.read_text(encoding="utf-8", errors="replace")
            non_empty = sum(
                1 for line in data.splitlines()
                if line.strip() and not line.strip().startswith("#")
            )
            return {"exists": 1, "lines": non_empty, "size": target.stat().st_size}
        except OSError:
            return {"exists": 0, "lines": 0, "size": 0}


if __name__ == "__main__":
    cfg = Config()
    z = ZapretManager(cfg)
    print("zapret_dir       :", z.zapret_dir)
    print("Установлен       :", z.is_installed())
    print("winws запущен    :", z.is_winws_running())
    print("Служба работает  :", z.is_service_running())
    print("Служба установл. :", z.is_service_installed())
    print("Активен          :", z.is_active())
    print("Стратегия        :", z.get_active_strategy_name())
    print("PID winws        :", z.get_winws_pid())
    print("Админ            :", is_admin())
    print("Локальная версия :", z.get_local_version())