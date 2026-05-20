# Lifecycle tests: PATH env, repair, reinstall, upgrade (TODO).
from __future__ import annotations

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
