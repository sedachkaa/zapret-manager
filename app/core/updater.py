"""
Модуль самообновления приложения и сторонних проектов.
"""

from __future__ import annotations

import json
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


# --- Структуры данных ---------------------------------------------------

@dataclass
class ReleaseInfo:
    tag: str
    version: Version
    name: str
    asset_url: str | None
    asset_name: str | None
    asset_type: str | None
    html_url: str

    @property
    def version_str(self) -> str:
        return str(self.version)


# --- Утилиты ------------------------------------------------------------

def _normalize_version(tag: str) -> Version | None:
    cleaned = tag.lstrip("vV").strip()
    try:
        return Version(cleaned)
    except InvalidVersion:
        return None


def _normalize_version_string(s: str) -> str:
    """
    Нормализует строку версии для сравнения:
        'v1.10.4'   → '1.10.4'
        '1.10.4.0'  → '1.10.4'
        '1.10'      → '1.10'
    """
    s = s.lstrip("vV").strip()
    parts = s.split(".")
    # Убираем завершающие ".0" (но оставляем минимум два компонента)
    while len(parts) > 2 and parts[-1] == "0":
        parts.pop()
    return ".".join(parts)


def version_matches(a: str, b: str) -> bool:
    """True, если версии эквивалентны с учётом нормализации '1.10.4.0' == '1.10.4'."""
    if not a or not b:
        return False
    return _normalize_version_string(a) == _normalize_version_string(b)


def is_newer_than(current: str, candidate: str) -> bool:
    """True, если candidate строго новее current."""
    ca = _normalize_version(current)
    cb = _normalize_version(candidate)
    if ca is None or cb is None:
        return False
    return cb > ca


def _http_get_json(url: str) -> dict:
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
    for asset in assets:
        name = asset.get("name", "")
        if name.lower().endswith(".zip"):
            return (asset.get("browser_download_url"), name, "zip")

    exe_assets = [a for a in assets if a.get("name", "").lower().endswith(".exe")]
    for asset in exe_assets:
        if "windows" in asset.get("name", "").lower():
            return (asset.get("browser_download_url"), asset["name"], "exe")
    if exe_assets:
        a = exe_assets[0]
        return (a.get("browser_download_url"), a["name"], "exe")

    return (None, None, None)


# --- Публичные функции --------------------------------------------------

def fetch_latest_release(owner_repo: str, *, include_prerelease: bool = False) -> ReleaseInfo | None:
    url = f"{GITHUB_API}/repos/{owner_repo}/releases/latest"
    if include_prerelease:
        url = f"{GITHUB_API}/repos/{owner_repo}/releases"

    try:
        data = _http_get_json(url)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise

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
    normalized = rel_path.replace("\\", "/")
    for ex in excludes:
        ex_norm = ex.replace("\\", "/").lstrip("./")
        if not ex_norm:
            continue
        if normalized == ex_norm or normalized.startswith(ex_norm.rstrip("/") + "/"):
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
    excludes = excludes or []
    written = 0
    skipped = 0

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
    print()
    print("Тесты сравнения версий:")
    print("  version_matches('1.10.4.0', 'v1.10.4') =", version_matches("1.10.4.0", "v1.10.4"))
    print("  version_matches('1.10.3', '1.10.3')    =", version_matches("1.10.3", "1.10.3"))
    print("  is_newer_than('1.10.3', '1.10.4')       =", is_newer_than("1.10.3", "1.10.4"))
    print("  is_newer_than('1.10.4', '1.10.3')       =", is_newer_than("1.10.4", "1.10.3"))