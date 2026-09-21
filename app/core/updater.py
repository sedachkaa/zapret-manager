"""
Модуль самообновления приложения и сторонних проектов.

Работает с GitHub Releases API:
    https://api.github.com/repos/{owner}/{repo}/releases/latest

Поддерживает два типа ассетов:
    - zip-архивы (например, zapret-discord-youtube) — распаковываются
      поверх текущей установки с учётом exclude_from_update;
    - прямые .exe-файлы (например, tg-ws-proxy) — просто скачиваются
      и заменяют существующий файл.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from packaging.version import InvalidVersion, Version

from app.core.config import PROJECT_ROOT, Config


GITHUB_API = "https://api.github.com"
USER_AGENT = "zapret-manager-updater/1.0"


# --- Структуры данных ---------------------------------------------------

@dataclass
class ReleaseInfo:
    """Информация о релизе с GitHub."""
    tag: str                      # например, "v1.2.3" или "1.2.3"
    version: Version              # нормализованная версия для сравнения
    name: str                     # человекочитаемое имя релиза
    asset_url: str | None         # URL на выбранный ассет
    asset_name: str | None        # имя файла ассета
    asset_type: str | None        # "zip" или "exe"
    html_url: str                 # ссылка на страницу релиза

    @property
    def version_str(self) -> str:
        return str(self.version)


# --- Утилиты ------------------------------------------------------------

def _normalize_version(tag: str) -> Version | None:
    """Превращает "v1.2.3" или "1.2.3" в Version. Возвращает None при ошибке."""
    cleaned = tag.lstrip("vV").strip()
    try:
        return Version(cleaned)
    except InvalidVersion:
        return None


def _http_get_json(url: str) -> dict:
    """GET-запрос с заголовками GitHub API. Возвращает распарсенный JSON."""
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def _pick_asset(assets: list[dict]) -> tuple[str | None, str | None, str | None]:
    """
    Выбирает подходящий ассет из списка релиза.
    Приоритет: .zip > .exe (windows > остальные).
    Возвращает (url, name, type) или (None, None, None).
    """
    # 1. Ищем .zip
    for asset in assets:
        name = asset.get("name", "")
        if name.lower().endswith(".zip"):
            return (
                asset.get("browser_download_url"),
                name,
                "zip",
            )

    # 2. Ищем .exe — сначала windows, потом любой
    exe_assets = [a for a in assets if a.get("name", "").lower().endswith(".exe")]
    for asset in exe_assets:
        if "windows" in asset.get("name", "").lower():
            return (
                asset.get("browser_download_url"),
                asset["name"],
                "exe",
            )
    if exe_assets:
        a = exe_assets[0]
        return (a.get("browser_download_url"), a["name"], "exe")

    return (None, None, None)


# --- Публичные функции --------------------------------------------------

def fetch_latest_release(owner_repo: str, *, include_prerelease: bool = False) -> ReleaseInfo | None:
    """
    Возвращает информацию о последнем релизе репозитория {owner}/{name}.
    Если релизов нет — None.
    """
    url = f"{GITHUB_API}/repos/{owner_repo}/releases/latest"
    if include_prerelease:
        url = f"{GITHUB_API}/repos/{owner_repo}/releases"

    data = _http_get_json(url)

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
    """True, если remote-версия строго новее current_version."""
    cur = _normalize_version(current_version)
    if cur is None:
        return False
    return remote.version > cur


def download_file(url: str, dest: Path, *, progress_cb=None) -> Path:
    """Скачивает файл по URL в dest."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
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
                    progress_cb(received / total * 100)
    return dest


def _is_excluded(rel_path: str, excludes: list[str]) -> bool:
    """True, если относительный путь файла подпадает под одно из исключений."""
    normalized = rel_path.replace("\\", "/")
    for ex in excludes:
        ex_norm = ex.replace("\\", "/").lstrip("./")
        if not ex_norm:
            continue
        if normalized == ex_norm or normalized.startswith(ex_norm.rstrip("/") + "/"):
            return True
    return False


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
    Возвращает (записано, пропущено).
    """
    excludes = excludes or []
    written = 0
    skipped = 0

    with zipfile.ZipFile(zip_path, "r") as z:
        for info in z.infolist():
            if info.is_dir():
                continue

            rel = info.filename.replace("\\", "/")
            target_file = target_dir / rel

            if _is_excluded(rel, excludes) and target_file.exists():
                if verbose:
                    print(f"[updater] сохраняю {rel} (в исключениях)")
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
    """
    Полный цикл: скачать ассет релиза → распаковать (если zip)
    или заменить файл (если exe).
    Возвращает (записано, пропущено).
    """
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

        # Прямой .exe — просто копируем поверх
        target_file = target_dir / release.asset_name
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(downloaded, target_file)
        return (1, 0)


# --- Обёртки для конкретных источников ---------------------------------

def check_wrapper_update(current_version: str, cfg: Config) -> ReleaseInfo | None:
    """Проверяет обновление самой обёртки (репозиторий из config.json)."""
    if not cfg.github_repo:
        return None
    release = fetch_latest_release(cfg.github_repo)
    if release and is_newer(release, current_version):
        return release
    return None


def check_zapret_update(cfg: Config) -> ReleaseInfo | None:
    """Последний релиз Flowseal/zapret-discord-youtube."""
    return fetch_latest_release("Flowseal/zapret-discord-youtube")


def check_tgproxy_update(cfg: Config) -> ReleaseInfo | None:
    """Последний релиз Flowseal/tg-ws-proxy."""
    return fetch_latest_release("Flowseal/tg-ws-proxy")


# --- Быстрый тест при прямом запуске ------------------------------------

if __name__ == "__main__":
    print("Проверяю релизы...")
    for repo in ("Flowseal/zapret-discord-youtube", "Flowseal/tg-ws-proxy"):
        try:
            rel = fetch_latest_release(repo)
            if rel:
                print(f"  {repo}: {rel.tag}  ->  [{rel.asset_type}] {rel.asset_name}")
                print(f"      URL: {rel.asset_url}")
            else:
                print(f"  {repo}: релизов нет или не найден")
        except Exception as e:
            print(f"  {repo}: ОШИБКА {e}")