# Shared fixtures and helpers for the OpenSSL installer test suite.
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import winreg
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from urllib.parse import urlunparse

import pytest
import requests
import yaml


# Switch COM apartment to multi-threaded (MTA) before any pywinauto.uia import.
# pywinauto defaults to STA, which trips RPC_E_CANTCALLOUT_ININPUTSYNCCALL
# (0x8001010d) on Windows Server 2022/2025 when modal dialogs transition while
# pytest is mid-call. This assignment runs while conftest loads — test_gui.py
# (the only file that imports pywinauto) loads later, so the flag is in place
# by the time pywinauto initializes COM.
sys.coinit_flags = 0  # type: ignore[attr-defined]


CONFIG_PATH = Path(__file__).parent / "config.yaml"


SCREENSHOTS_DIR = Path(__file__).parent / "_screenshots"


def pytest_addoption(parser):
    parser.addoption(
        "--installer",
        action="store",
        default=None,
        help=(
            "Filesystem path OR http(s) URL of the OpenSSL installer "
            "(.exe bootstrapper, or .msi for legacy artifacts). "
            "URLs are downloaded to a cross-session ETag-cached temp dir. "
            "Basic-auth credentials may be embedded as https://user:token@host/..."
        ),
    )


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """On any failure of a `gui`-marked test, save a full-screen screenshot.

    Covers setup, call, and teardown — the connect() ElementNotFound failure
    happens in setup, so call-phase-only would miss it. When the screenshot
    can't be taken (typical cause: Session 0 isolation, e.g. pytest invoked
    over SSH/WinRM), the failure message points at running from RDP/console.
    """
    outcome = yield
    report = outcome.get_result()
    if report.failed and "gui" in item.keywords:
        _capture_screenshot(f"{item.name}_{report.when}")


def _capture_screenshot(label: str) -> None:
    SCREENSHOTS_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = SCREENSHOTS_DIR / f"{label}_{ts}.png"
    try:
        from PIL import ImageGrab

        ImageGrab.grab(all_screens=True).save(path)
        print(f"[diag] screenshot: {path}", flush=True)
    except Exception as e:
        sess_id = _current_session_id()
        print(f"[diag] screenshot failed ({e}); pytest session id={sess_id}", flush=True)
        if sess_id == 0:
            print("[diag] session 0 — no interactive desktop. Run via RDP/console, not SSH.", flush=True)


def _current_session_id() -> int:
    import ctypes

    sess = ctypes.c_uint()
    kernel32 = ctypes.windll.kernel32
    kernel32.ProcessIdToSessionId(kernel32.GetCurrentProcessId(), ctypes.byref(sess))
    return sess.value


@dataclass(frozen=True)
class InstallerInfo:
    path: Path
    version: str  # "4.0.0"
    major: str  # "4"
    minor: str  # "0"
    patch: str  # "0"
    short: str  # "4.0" — also the registry_version


@pytest.fixture(scope="session")
def config() -> dict:
    with CONFIG_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _is_url(s: str) -> bool:
    return s.startswith(("http://", "https://"))


def _cache_dir() -> Path:
    """Cross-session cache for downloaded MSIs. Override with
    OPENSSL_INSTALLER_CACHE_DIR; defaults to %LOCALAPPDATA%."""
    override = os.environ.get("OPENSSL_INSTALLER_CACHE_DIR")
    if override:
        return Path(override)
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base / "openssl-installer-tests"


def _download_installer(url: str) -> Path:
    """Fetch an installer (.exe or .msi) from `url`, using an ETag /
    Last-Modified cache.

    Cache layout: <cache_dir>/<sha256(url)[:16]>/{filename, meta.json}.
    Sends If-None-Match / If-Modified-Since on subsequent fetches; a 304
    response reuses the cached file.
    """
    filename = url.rstrip("/").rsplit("/", 1)[-1].split("?", 1)[0]
    if not filename.lower().endswith((".exe", ".msi")):
        pytest.exit(f"URL does not end in an .exe or .msi filename: {url}", returncode=2)

    bucket = _cache_dir() / hashlib.sha256(url.encode()).hexdigest()[:16]
    bucket.mkdir(parents=True, exist_ok=True)
    cached = bucket / filename
    meta_path = bucket / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}

    headers = {}
    if cached.exists():
        if meta.get("etag"):
            headers["If-None-Match"] = meta["etag"]
        if meta.get("last_modified"):
            headers["If-Modified-Since"] = meta["last_modified"]

    try:
        resp = requests.get(url, headers=headers, stream=True, timeout=60)
    except requests.RequestException as e:
        pytest.exit(f"Failed to fetch {url}: {e}", returncode=2)

    if resp.status_code == 304 and cached.exists():
        print(f"Using cached installer (304 Not Modified): {cached}", flush=True)
        return cached

    if not resp.ok:
        pytest.exit(f"Fetch failed: {url} -> HTTP {resp.status_code}", returncode=2)

    print(f"Downloading {url} -> {cached}", flush=True)
    tmp = cached.with_suffix(cached.suffix + ".part")
    with tmp.open("wb") as f:
        for chunk in resp.iter_content(chunk_size=64 * 1024):
            if chunk:
                f.write(chunk)
    tmp.replace(cached)

    meta_path.write_text(
        json.dumps(
            {
                # Strip embedded basic-auth credentials before persisting.
                # The cache key already hashed the full URL (userinfo included),
                # so this stays self-consistent — meta.json is just for humans.
                "url": _strip_url_credentials(url),
                "etag": resp.headers.get("ETag"),
                "last_modified": resp.headers.get("Last-Modified"),
                "filename": filename,
            },
            indent=2,
        )
    )
    return cached


def _strip_url_credentials(url: str) -> str:
    """Return `url` with any user:password@ removed from netloc."""
    parsed = urlparse(url)
    if not parsed.username and not parsed.password:
        return url
    netloc = parsed.hostname or ""
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


@pytest.fixture(scope="session")
def installer(request) -> InstallerInfo:
    arg = request.config.getoption("--installer")
    if not arg:
        pytest.exit("--installer <path-or-url-to-exe-or-msi> is required", returncode=2)

    if _is_url(arg):
        path = _download_installer(arg)
    else:
        path = Path(arg).resolve()
        if not path.exists():
            pytest.exit(f"Installer not found: {path}", returncode=2)

    if path.suffix.lower() not in (".exe", ".msi"):
        pytest.exit(f"Installer must be .exe or .msi, got: {path.name}", returncode=2)
    m = re.search(r"(\d+\.\d+\.\d+)\.(?:exe|msi)$", path.name, re.IGNORECASE)
    if not m:
        pytest.exit(f"Cannot parse version from installer filename: {path.name}", returncode=2)
    assert m is not None  # pytest.exit above raises; this narrows for mypy
    version = m.group(1)
    major, minor, patch = version.split(".")
    return InstallerInfo(
        path=path,
        version=version,
        major=major,
        minor=minor,
        patch=patch,
        short=f"{major}.{minor}",
    )


@pytest.fixture(scope="session")
def install_dir(installer, config) -> Path:
    return Path(config["paths"]["install_root"]) / f"openssl-{installer.short}"


@pytest.fixture(scope="session", autouse=True)
def clean_machine() -> Iterator[None]:
    """Uninstall every OpenSSL Library product at session start and end.

    Belt-and-suspenders sweep to handle leftovers from manual
    troubleshooting or interrupted prior runs. Per-test `clean_install`
    relies on the same product-code enumeration.
    """
    _uninstall_all_openssl_products()
    yield
    _uninstall_all_openssl_products()


def _uninstall_all_openssl_products() -> None:
    for product_code, display_name in _find_installed_openssl_products():
        print(f"clean_machine: removing {display_name} ({product_code})", flush=True)
        _msiexec(["/x", product_code, "/qn"], check=False)


def _find_installed_openssl_products() -> list[tuple[str, str]]:
    """Return [(product_code, display_name), ...] for every installed
    "OpenSSL Library*" product across the 64-bit and Wow6432Node hives."""
    results: list[tuple[str, str]] = []
    for hive_path in (
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        r"SOFTWARE\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
    ):
        try:
            hive = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, hive_path)
        except FileNotFoundError:
            continue
        with hive:
            i = 0
            while True:
                try:
                    subkey_name = winreg.EnumKey(hive, i)
                except OSError:
                    break
                i += 1
                if not subkey_name.startswith("{"):
                    # Not an MSI product code; skip (e.g. EXE-installed apps).
                    continue
                with winreg.OpenKey(hive, subkey_name) as subkey:
                    try:
                        display_name = winreg.QueryValueEx(subkey, "DisplayName")[0]
                    except FileNotFoundError:
                        continue
                    if display_name.startswith("OpenSSL Library"):
                        results.append((subkey_name, display_name))
    return results


@pytest.fixture
def clean_install(installer):
    """Make sure no install is present going in, and clean up going out."""
    uninstall(installer)
    yield
    uninstall(installer)


# --- install / uninstall / repair --------------------------------------
#
# Install: invoke the installer artifact directly. For .exe (the AI
# bootstrapper) we use /exenoui /qn; MSI properties (e.g. INSTALL_FIPS=1)
# are passed through to the inner MSI. For .msi we fall back to
# msiexec /i — only relevant when testing pre-bootstrapper builds.
#
# Uninstall / repair: route through msiexec by product code, NOT by
# installer path. After install the inner MSI is cached in Windows
# Installer's database (C:\Windows\Installer\*.msi) and addressable by
# product code, which works whether the original installer was .exe or
# .msi. Using the path with /x would refuse for the .exe-bootstrapper
# artifact (the inner MSI's LaunchCondition rejects standalone msiexec).


def _msiexec(args: list[str], check: bool) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["msiexec", *args],
        check=check,
        capture_output=True,
        text=True,
    )


def install(info: InstallerInfo, properties: list[str] | None = None, check: bool = True):
    props = properties or []
    if info.path.suffix.lower() == ".exe":
        return subprocess.run(
            [str(info.path), "/exenoui", "/qn", *props],
            check=check,
            capture_output=True,
            text=True,
        )
    return _msiexec(["/i", str(info.path), "/qn", *props], check=check)


def uninstall(info: InstallerInfo) -> None:
    """Best-effort uninstall via product-code lookup. OK if nothing is installed."""
    _uninstall_all_openssl_products()


def repair(info: InstallerInfo) -> None:
    """msiexec /fa by product code — Windows Installer reinstalls from its cache."""
    products = _find_installed_openssl_products()
    if not products:
        raise RuntimeError("no OpenSSL Library product installed to repair")
    for product_code, _ in products:
        _msiexec(["/fa", product_code, "/qn"], check=True)


# --- expected-file checks ----------------------------------------------


def _expand(name: str, info: InstallerInfo) -> str:
    return name.format(major=info.major, minor=info.minor, patch=info.patch)


def expected_files(config: dict, info: InstallerInfo, active_flags: tuple[str, ...]) -> tuple[list[Path], list[Path]]:
    """Return (should-exist, should-not-exist) absolute file paths."""
    root = Path(config["paths"]["install_root"]) / f"openssl-{info.short}"
    flags = set(active_flags) | {"all"}
    yes: list[Path] = []
    no: list[Path] = []
    for rel_dir, entries in config["files"].items():
        target_dir = root / rel_dir if rel_dir else root
        for entry in entries:
            target = target_dir / _expand(entry["name"], info)
            (yes if entry["flags"] in flags else no).append(target)
    return yes, no


def check_files(config: dict, info: InstallerInfo, active_flags: tuple[str, ...]):
    yes, no = expected_files(config, info, active_flags)
    missing = [str(p) for p in yes if not p.exists()]
    stray = [str(p) for p in no if p.exists()]
    if missing or stray:
        lines: list[str] = []
        lines.extend(f"  missing:    {p}" for p in missing)
        lines.extend(f"  unexpected: {p}" for p in stray)
        raise AssertionError("File manifest mismatch:\n" + "\n".join(lines))


# --- post-uninstall residue check --------------------------------------


def check_post_uninstall(config: dict, install_dir: Path):
    for rel_dir, files in config.get("post_uninstall_keep", {}).items():
        d = install_dir / rel_dir if rel_dir else install_dir
        for name in files:
            target = d / name
            assert target.exists(), f"file should remain after uninstall: {target}"


# --- openssl.exe-driven checks -----------------------------------------


def check_openssl_version(install_dir: Path, expected_version: str):
    exe = install_dir / "bin" / "openssl.exe"
    res = subprocess.run([str(exe), "version"], check=True, capture_output=True, text=True)
    # Strip any -dev / -beta suffix from the reported version.
    reported = res.stdout.split()[1].split("-")[0]
    assert reported == expected_version, f"openssl version mismatch: expected {expected_version}, got {reported}"


def check_legacy_provider(install_dir: Path):
    exe = install_dir / "bin" / "openssl.exe"
    res = subprocess.run(
        [str(exe), "list", "-providers", "-provider=legacy"],
        check=False,
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        raise AssertionError(
            f"openssl list -provider=legacy failed (exit {res.returncode})\n" f"stdout:\n{res.stdout}\n" f"stderr:\n{res.stderr}"
        )


def check_fips_provider(install_dir: Path, expected_fips_version: str):
    """List the FIPS provider using a temporary openssl.cnf.

    The installed openssl.cnf is never modified — we read it, apply the
    FIPS-enabling tweaks in memory, write the result to a tempfile, and
    point openssl at it via OPENSSL_CONF. A crash mid-test cannot leave
    the installed config in a partially-patched state.
    """
    src_cnf = install_dir / "config" / "openssl.cnf"
    content = src_cnf.read_text(encoding="utf-8")
    fips_inc = f".include {install_dir}\\config\\fipsmodule.cnf"
    content = content.replace("# .include fipsmodule.cnf", fips_inc)
    content = content.replace("# fips = fips_sect", "fips = fips_sect")
    content = content.replace("# activate = 1", "activate = 1")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".cnf", delete=False, encoding="utf-8") as tf:
        tf.write(content)
        temp_cnf = tf.name
    try:
        exe = install_dir / "bin" / "openssl.exe"
        env = {**os.environ, "OPENSSL_CONF": temp_cnf}
        res = subprocess.run(
            [str(exe), "list", "-providers", "-provider=fips"],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        if res.returncode != 0:
            raise AssertionError(
                f"openssl list -provider=fips failed (exit {res.returncode})\n"
                f"OPENSSL_CONF={temp_cnf}\n"
                f"stdout:\n{res.stdout}\n"
                f"stderr:\n{res.stderr}"
            )
        m = re.search(r"fips[\s\S]*?version:\s*(\S+)", res.stdout)
        assert m, f"could not find FIPS version in output:\n{res.stdout}"
        assert m.group(1) == expected_fips_version, f"FIPS version mismatch: expected {expected_fips_version}, got {m.group(1)}"
    finally:
        os.unlink(temp_cnf)


# --- registry checks ---------------------------------------------------


def _path_eq_winsafe(actual: str, expected: str) -> bool:
    """Compare two Windows paths: drive letter case-insensitive, rest exact."""
    if ":\\" not in actual or ":\\" not in expected:
        return actual.lower() == expected.lower()
    a_drv, a_rest = actual.split(":\\", 1)
    e_drv, e_rest = expected.split(":\\", 1)
    return a_drv.lower() == e_drv.lower() and a_rest == e_rest


def check_registry(config: dict, info: InstallerInfo, install_dir: Path):
    fmt = {
        "registry_version": info.short,
        "install_dir": str(install_dir).rstrip("\\"),
    }
    expected_values = {k: v.format(**fmt) for k, v in config["registry"]["values"].items()}
    for path_template in config["registry"]["paths"]:
        path = path_template.format(**fmt)
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path)
        except FileNotFoundError as e:
            raise AssertionError(
                f"registry key not found: HKLM\\{path}\n" f"  expected the MSI's RegistryKeys component to write it"
            ) from e
        with key:
            for name, expected in expected_values.items():
                try:
                    actual, _ = winreg.QueryValueEx(key, name)
                except FileNotFoundError as e:
                    raise AssertionError(f"registry value missing: HKLM\\{path}::{name}") from e
                assert _path_eq_winsafe(actual, expected), f"HKLM\\{path}::{name}: expected {expected!r}, got {actual!r}"
