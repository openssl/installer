# Lifecycle tests: PATH env, repair, reinstall, upgrade (TODO).
from __future__ import annotations

import re
import subprocess
import winreg
from pathlib import Path

import pytest
from conftest import install
from conftest import InstallerInfo
from conftest import repair
from conftest import uninstall


ENV_KEY_PATH = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"


def _read_system_path() -> str:
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, ENV_KEY_PATH) as key:
        value, _ = winreg.QueryValueEx(key, "Path")
    return value


def _bin_dir_entry(install_dir: Path) -> str:
    # The installer writes the bin path with a trailing backslash.
    return f"{install_dir}\\bin\\"


def test_path_env_added_and_removed(installer: InstallerInfo, install_dir: Path) -> None:
    """The bin directory should be added to system PATH on install and
    removed on uninstall."""
    uninstall(installer)
    baseline = _read_system_path()
    bin_entry = _bin_dir_entry(install_dir)
    assert bin_entry not in baseline, f"bin dir {bin_entry!r} already in PATH before install — clean machine assumption violated"

    install(installer)
    try:
        after_install = _read_system_path()
        assert bin_entry in after_install, f"expected {bin_entry!r} in PATH after install:\n{after_install}"
    finally:
        uninstall(installer)

    after_uninstall = _read_system_path()
    assert bin_entry not in after_uninstall, f"{bin_entry!r} should be removed from PATH after uninstall:\n{after_uninstall}"


@pytest.mark.usefixtures("clean_install")
def test_repair_restores_deleted_files(installer: InstallerInfo, install_dir: Path) -> None:
    """msiexec /fa should restore a file that was manually deleted."""
    install(installer)
    exe = install_dir / "bin" / "openssl.exe"
    assert exe.exists(), f"expected file not installed: {exe}"
    exe.unlink()
    assert not exe.exists()

    repair(installer)
    assert exe.exists(), f"repair did not restore: {exe}"


@pytest.mark.usefixtures("clean_install")
def test_reinstall_over_existing(installer: InstallerInfo, install_dir: Path) -> None:
    """Running the installer twice in a row should succeed."""
    install(installer)
    exe = install_dir / "bin" / "openssl.exe"
    assert exe.exists()
    # Reinstall — msiexec returns 0 even when the product is already installed.
    install(installer)
    assert exe.exists()


@pytest.mark.skip(reason="upgrade fixtures TODO — needs a prior MSI version available in CI")
def test_upgrade_from_previous_version(installer: InstallerInfo) -> None:
    """Install a prior version, then run this MSI as an upgrade.

    Pending: decide how prior-version MSIs are sourced (GitHub Release of the
    installer repo? separate fixtures repo?) and wire them into the workflow.
    """


# Minimum VC++ runtime version the .aip's PreReqSearch enforces. If the
# installer's prereq mechanism works, this version (or newer) is on the
# machine after install — either because it was already there or because
# the MSI downloaded https://aka.ms/vs/17/release/vc_redist.x64.exe and
# installed it silently.
_VCRUNTIME_KEY = r"SOFTWARE\Microsoft\DevDiv\VC\Servicing\14.0\RuntimeMinimum"
_VCRUNTIME_MIN = (14, 40, 33816)


def _version_tuple(s: str, length: int) -> tuple[int, ...]:
    parts = [int(p) for p in s.split(".")]
    while len(parts) < length:
        parts.append(0)
    return tuple(parts[:length])


@pytest.mark.usefixtures("clean_install")
def test_vc_runtime_present_after_install(installer: InstallerInfo) -> None:
    """After install, the VC++ 2015-2022 x64 runtime must satisfy the .aip's
    declared minimum (>= 14.40.33816). The MSI either uses an already-installed
    runtime or downloads + installs vc_redist.x64.exe during install."""
    install(installer)
    _assert_vc_runtime_meets_minimum()


def _read_vc_runtime_version() -> str | None:
    """Return the VC++ runtime version string, or None if not installed."""
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _VCRUNTIME_KEY)
    except FileNotFoundError:
        return None
    with key:
        return winreg.QueryValueEx(key, "Version")[0]


def _assert_vc_runtime_meets_minimum() -> None:
    version = _read_vc_runtime_version()
    if version is None:
        raise AssertionError(
            f"VC++ runtime registry key missing: HKLM\\{_VCRUNTIME_KEY}.\n"
            "The MSI's prereq should have installed VC++ Redistributable."
        )
    actual = _version_tuple(version, len(_VCRUNTIME_MIN))
    required_str = ".".join(map(str, _VCRUNTIME_MIN))
    assert actual >= _VCRUNTIME_MIN, f"VC++ runtime version {version!r} < required {required_str!r}"


# Matches "Microsoft Visual C++ 2015/2017/2019/2022 (- ... -)? Redistributable (x64) ..."
# in DisplayName. Older Visual C++ families (2008/2010/2012/2013) live on
# different servicing branches and aren't what our installer requires, so
# we leave them alone.
_VC_REDIST_X64_PATTERN = re.compile(r"visual c\+\+ 20(15|17|19|22).*x64", re.IGNORECASE)


def _find_vc_redist_x64_products() -> list[tuple[str, str]]:
    """Return [(product_code, display_name)] for installed VC++ 2015-2022 x64
    redistributables — the family our MSI's prereq targets."""
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
                    continue
                with winreg.OpenKey(hive, subkey_name) as subkey:
                    try:
                        display_name = winreg.QueryValueEx(subkey, "DisplayName")[0]
                    except FileNotFoundError:
                        continue
                    if _VC_REDIST_X64_PATTERN.search(display_name):
                        results.append((subkey_name, display_name))
    return results


@pytest.mark.destructive
@pytest.mark.usefixtures("clean_install")
def test_msi_installs_vc_runtime_when_missing(installer: InstallerInfo) -> None:
    """Aggressive variant of test_vc_runtime_present_after_install: forcibly
    remove every Visual C++ 2015-2022 x64 redistributable on the machine,
    then install the MSI and verify the runtime is back at the required
    version.

    This proves the .aip's PreReqComponent actually downloads and installs
    https://aka.ms/vs/17/release/vc_redist.x64.exe — not just relies on a
    machine that happened to already have it.

    Gated by the `destructive` marker (run with `pytest -m destructive`)
    because it temporarily breaks any other software on the machine that
    depends on VC++ runtime. The MSI's prereq mechanism restores it.
    """
    found = _find_vc_redist_x64_products()
    if not found:
        pytest.skip("no VC++ 2015-2022 x64 redistributable present to remove; cannot verify download")

    for product_code, display_name in found:
        print(f"removing {display_name} ({product_code})", flush=True)
        result = subprocess.run(
            ["msiexec", "/x", product_code, "/qn", "/norestart"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode not in (0, 1605):  # 1605 = product not installed (already gone)
            raise AssertionError(f"failed to uninstall {display_name}: exit {result.returncode}\n" f"stderr: {result.stderr}")

    # Confirm the runtime is genuinely absent (or below the minimum) before
    # we install our MSI — otherwise the test wouldn't prove anything.
    version = _read_vc_runtime_version()
    if version is not None:
        actual = _version_tuple(version, len(_VCRUNTIME_MIN))
        if actual >= _VCRUNTIME_MIN:
            pytest.skip(
                f"VC++ runtime is still {version!r} after uninstall — likely a non-removable "
                "system component or a newer redistributable kept it. Cannot verify the prereq download."
            )

    # Install our MSI. The PreReqComponent should download + install VC++ redist.
    install(installer)

    _assert_vc_runtime_meets_minimum()
