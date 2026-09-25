"""
Модуль самообновления приложения и сторонних проектов.

Работает с GitHub Releases API:
    https://api.github.com/repos/{owner}/{repo}/releases/latest

Типы ассетов (поле asset_type в ReleaseInfo):
    - "installer" — наш ZapretManager-Setup-*.exe. Используется для
      самообновления обёртки через Inno Setup в silent-режиме.
    - "zip" — обычный zip-архив (например, zapret-discord-youtube) —
      распаковывается поверх текущей установки с учётом exclude_from_update;
    - "exe" — прямой исполняемый файл (например, tg-ws-proxy) —
      просто скачивается и заменяет существующий файл.

Авторизация GitHub API:
    По умолчанию лимит — 60 запросов/час на IP. Если задана переменная
    окружения GITHUB_TOKEN, лимит становится 5000/час.

    Токен читается ТОЛЬКО из переменной окружения — в config.json его
    нет, чтобы случайно не показать в GUI или не закоммитить в репозиторий.

ВАЖНО: игнорируем автоматически прикреплённые GitHub-архивы
"Source code (zip)" / "Source code (tar.gz)" — у них URL содержит
/archive/, а у наших релизных ассетов — /releases/download/.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from packaging.version import InvalidVersion, Version

from app.core.config import PROJECT_ROOT, Config


GITHUB_API = "https://api.github.com"
USER_AGENT = "zapret-manager-updater/1.0"

# Имя переменной окружения, в которой ищется токен.
GITHUB_TOKEN_ENV = "GITHUB_TOKEN"


# --- Структуры данных ---------------------------------------------------

@dataclass
class ReleaseInfo:
    tag: str
    version: Version
    name: str
    asset_url: str | None
    asset_name: str | None
    asset_type: str | None       # "installer" | "zip" | "exe"
    html_url: str

    @property
    def version_str(self) -> str:
        return str(self.version)


# --- Токен GitHub --------------------------------------------------------

def _get_github_token() -> str | None:
    """
    Возвращает GitHub-токен ТОЛЬКО из переменной окружения GITHUB_TOKEN.
    Если переменная не задана — None (работаем анонимно, лимит 60/час).

    Мы намеренно НЕ читаем токен из config.json: этот файл открывается
    через GUI в настройках и легко может утечь.
    """
    token = os.environ.get(GITHUB_TOKEN_ENV, "").strip()
    return token or None


def has_github_token() -> bool:
    """True, если GITHUB_TOKEN задан в переменных окружения."""
    return _get_github_token() is not None


def _auth_headers() -> dict[str, str]:
    """Заголовки для GitHub API. С токеном — если он есть."""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = _get_github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


# --- Утилиты версий ------------------------------------------------------

def _normalize_version(tag: str) -> Version | None:
    cleaned = tag.lstrip("vV").strip()
    try:
        return Version(cleaned)
    except InvalidVersion:
        return None


def _normalize_version_string(s: str) -> str:
    """'v1.10.4' → '1.10.4', '1.10.4.0' → '1.10.4'."""
    s = s.lstrip("vV").strip()
    parts = s.split(".")
    while len(parts) > 2 and parts[-1] == "0":
        parts.pop()
    return ".".join(parts)


def version_matches(a: str, b: str) -> bool:
    if not a or not b:
        return False
    return _normalize_version_string(a) == _normalize_version_string(b)


def is_newer_than(current: str, candidate: str) -> bool:
    ca = _normalize_version(current)
    cb = _normalize_version(candidate)
    if ca is None or cb is None:
        return False
    return cb > ca


# --- HTTP ---------------------------------------------------------------

def _http_get_json(url: str) -> dict:
    """GET-запрос к GitHub API с авторизацией (если есть токен)."""
    req = urllib.request.Request(url, headers=_auth_headers())
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def _is_source_archive(url: str) -> bool:
    """True, если URL ведёт на автоматически прикреплённый GitHub-архив."""
    return "/archive/" in (url or "")


def _pick_asset(assets: list[dict]) -> tuple[str | None, str | None, str | None]:
    """
    Выбирает подходящий ассет из списка релиза.
    Приоритет: installer > zip > exe (windows > остальные).
    Игнорирует авто-архивы Source code.
    """
    def _valid(a: dict) -> bool:
        return not _is_source_archive(a.get("browser_download_url", "") or "")

    # 1. Installer (ZapretManager-Setup-*.exe)
    for asset in assets:
        if not _valid(asset):
            continue
        name = asset.get("name", "")
        lower = name.lower()
        if lower.endswith(".exe") and "setup" in lower:
            return (asset.get("browser_download_url"), name, "installer")

    # 2. Обычный zip
    for asset in assets:
        if not _valid(asset):
            continue
        name = asset.get("name", "")
        if name.lower().endswith(".zip"):
            return (asset.get("browser_download_url"), name, "zip")

    # 3. Прочие exe
    exe_assets = [a for a in assets if _valid(a) and a.get("name", "").lower().endswith(".exe")]
    for asset in exe_assets:
        if "windows" in asset.get("name", "").lower():
            return (asset.get("browser_download_url"), asset["name"], "exe")
    if exe_assets:
        a = exe_assets[0]
        return (a.get("browser_download_url"), a["name"], "exe")

    return (None, None, None)


# --- Публичные функции --------------------------------------------------

def fetch_latest_release(owner_repo: str, *, include_prerelease: bool = False) -> ReleaseInfo | None:
    """
    Возвращает информацию о последнем релизе репозитория {owner}/{name}.
    При 403 (rate limit) и 404 (не найдено) — None, без исключения.
    """
    url = f"{GITHUB_API}/repos/{owner_repo}/releases/latest"
    if include_prerelease:
        url = f"{GITHUB_API}/repos/{owner_repo}/releases"

    try:
        data = _http_get_json(url)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        if e.code == 403:
            has_token = has_github_token()
            hint = (
                "Токен не указан — лимит 60 запросов/час на IP. "
                "Задай GITHUB_TOKEN, чтобы увеличить лимит до 5000/час."
                if not has_token else
                "Токен указан, но лимит исчерпан — проверь токен."
            )
            print(f"[updater] GitHub rate limit для {owner_repo}. {hint}")
            return None
        raise
    except Exception as e:
        print(f"[updater] ошибка запроса к GitHub для {owner_repo}: {e}")
        return None

    if include_prerelease:
        if not isinstance(data, list) or not data:
            return None
        data = data[0]
    elif isinstance(data, dict) and data.get("message") == "Not Found":
        return None

    tag = str(data.get("tag_name", "")).strip()
    version = _normalize_version(tag)
    if version is None:
        return None

    asset_url, asset_name, asset_type = _pick_asset(data.get("assets", []))

    return ReleaseInfo(
        tag=tag,
        version=version,
        name=data.get("name") or tag,
        asset_url=asset_url,
        asset_name=asset_name,
        asset_type=asset_type,
        html_url=data.get("html_url", ""),
    )


def is_newer(remote: ReleaseInfo, current_version: str) -> bool:
    cur = _normalize_version(current_version)
    if cur is None:
        return False
    return remote.version > cur


def download_file(url: str, dest: Path, *, progress_cb=None) -> Path:
    """
    Скачивает файл по URL в dest.
    progress_cb(percent: float) — необязательный callback для прогресса.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)

    headers = {"User-Agent": USER_AGENT}
    token = _get_github_token()
    if token and "github" in url.lower():
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as resp:
        total = int(resp.headers.get("Content-Length", 0) or 0)
        chunk = 64 * 1024
        received = 0
        with dest.open("wb") as f:
            while True:
                buf = resp.read(chunk)
                if not buf:
                    break
                f.write(buf)
                received += len(buf)
                if progress_cb and total:
                    try:
                        progress_cb(received / total * 100)
                    except Exception:
                        pass
    return dest


def _is_excluded(rel_from_root: str, excludes: list[str]) -> bool:
    normalized = rel_from_root.replace("\\", "/").lstrip("./")
    for ex in excludes:
        ex_norm = ex.replace("\\", "/").lstrip("./").rstrip("/")
        if not ex_norm:
            continue
        if normalized == ex_norm or normalized.startswith(ex_norm + "/"):
            return True
    return False


def _detect_common_prefix(names: list[str]) -> str:
    if not names:
        return ""
    split = [n.replace("\\", "/").strip("/").split("/") for n in names]
    split = [s for s in split if s]
    if not split:
        return ""
    first = split[0][0]
    if any(len(s) < 2 for s in split):
        return ""
    if all(s[0] == first for s in split):
        return first + "/"
    return ""


def extract_zip_with_exclusions(
    zip_path: Path,
    target_dir: Path,
    *,
    excludes: list[str] | None = None,
    verbose: bool = True,
) -> tuple[int, int]:
    """
    Распаковывает zip в target_dir, пропуская файлы,
    которые есть в excludes И уже существуют на диске.
    """
    excludes = excludes or []
    written = 0
    skipped = 0

    try:
        project_root_resolved = PROJECT_ROOT.resolve()
    except OSError:
        project_root_resolved = PROJECT_ROOT

    with zipfile.ZipFile(zip_path, "r") as z:
        file_names = [i.filename for i in z.infolist() if not i.is_dir()]
        prefix = _detect_common_prefix(file_names)

        if verbose and prefix:
            print(f"[updater] общий префикс архива: {prefix} — срезаю")

        for info in z.infolist():
            if info.is_dir():
                continue
            rel = info.filename.replace("\\", "/")
            if prefix and rel.startswith(prefix):
                rel = rel[len(prefix):]
            if not rel:
                continue

            target_file = target_dir / rel

            try:
                abs_target = target_file.resolve()
                rel_from_root = str(abs_target.relative_to(project_root_resolved)).replace("\\", "/")
            except (ValueError, OSError):
                rel_from_root = rel

            if target_file.exists() and _is_excluded(rel_from_root, excludes):
                if verbose:
                    print(f"[updater] сохраняю {rel_from_root} (в исключениях)")
                skipped += 1
                continue

            target_file.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info, "r") as src, target_file.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            written += 1

    return written, skipped


def apply_release(
    release: ReleaseInfo,
    target_dir: Path,
    *,
    excludes: list[str] | None = None,
    progress_cb=None,
) -> tuple[int, int]:
    if not release.asset_url or not release.asset_name or not release.asset_type:
        raise RuntimeError(f"У релиза {release.tag} нет подходящего ассета")

    with tempfile.TemporaryDirectory(prefix="zapret-mgr-") as tmp:
        tmp_path = Path(tmp)
        downloaded = tmp_path / release.asset_name
        download_file(release.asset_url, downloaded, progress_cb=progress_cb)

        if release.asset_type == "zip":
            return extract_zip_with_exclusions(
                downloaded, target_dir, excludes=excludes
            )

        target_file = target_dir / release.asset_name
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(downloaded, target_file)
        return (1, 0)


# --- Обёртки для конкретных источников ---------------------------------

def check_wrapper_update(current_version: str, cfg: Config) -> ReleaseInfo | None:
    if not cfg.github_repo:
        return None
    release = fetch_latest_release(cfg.github_repo)
    if release and is_newer(release, current_version):
        return release
    return None


def check_zapret_update(cfg: Config) -> ReleaseInfo | None:
    return fetch_latest_release("Flowseal/zapret-discord-youtube")


def check_tgproxy_update(cfg: Config) -> ReleaseInfo | None:
    return fetch_latest_release("Flowseal/tg-ws-proxy")


# --- Быстрый тест --------------------------------------------------------

if __name__ == "__main__":
    print(f"Токен ({GITHUB_TOKEN_ENV}): {'настроен' if has_github_token() else 'НЕ настроен (лимит 60/час)'}")
    print()
    print("Проверяю релизы...")
    for repo in ("Flowseal/zapret-discord-youtube", "Flowseal/tg-ws-proxy"):
        try:
            rel = fetch_latest_release(repo)
            if rel:
                print(f"  {repo}: {rel.tag}  ->  [{rel.asset_type}] {rel.asset_name}")
            else:
                print(f"  {repo}: релизов нет или не найден")
        except Exception as e:
            print(f"  {repo}: ОШИБКА {e}")