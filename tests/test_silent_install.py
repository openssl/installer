# Silent-install (no-UI) test cases.
from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

import pytest
from conftest import check_files
from conftest import check_fips_provider
from conftest import check_legacy_provider
from conftest import check_openssl_version
from conftest import check_post_uninstall
from conftest import check_registry
from conftest import install
from conftest import InstallerInfo
from conftest import uninstall


@pytest.mark.usefixtures("clean_install")
def test_default(installer: InstallerInfo, install_dir: Path, config: dict) -> None:
    install(installer)
    check_files(config, installer, ("app", "sdk"))
    check_openssl_version(install_dir, installer.version)
    check_registry(config, installer, install_dir)
    check_legacy_provider(install_dir)


@pytest.mark.usefixtures("clean_install")
def test_app_only(installer: InstallerInfo, config: dict) -> None:
    install(installer, ["INSTALL_APP=1", "INSTALL_SDK=0"])
    check_files(config, installer, ("app",))


@pytest.mark.usefixtures("clean_install")
def test_sdk_only(installer: InstallerInfo, config: dict) -> None:
    install(installer, ["INSTALL_APP=0", "INSTALL_SDK=1"])
    check_files(config, installer, ("sdk",))


@pytest.mark.usefixtures("clean_install")
def test_app_and_sdk(installer: InstallerInfo, config: dict) -> None:
    install(installer, ["INSTALL_APP=1", "INSTALL_SDK=1"])
    check_files(config, installer, ("app", "sdk"))


@pytest.mark.fips
@pytest.mark.usefixtures("clean_install")
def test_fips_validated(installer: InstallerInfo, install_dir: Path, config: dict) -> None:
    install(
        installer,
        [
            "INSTALL_FIPS=1",
            "INSTALL_FIPS_TYPE=validated",
            "INSTALL_APP=1",
            "INSTALL_SDK=1",
        ],
    )
    check_files(config, installer, ("app", "sdk", "fips", "fips_sdk"))
    expected = config["fips"]["validated_versions"].get(installer.short)
    if expected is None:
        pytest.skip(f"no validated FIPS version configured for OpenSSL {installer.short}")
    check_fips_provider(install_dir, expected)


@pytest.mark.fips
@pytest.mark.usefixtures("clean_install")
def test_fips_current(installer: InstallerInfo, install_dir: Path) -> None:
    install(installer, ["INSTALL_FIPS=1", "INSTALL_FIPS_TYPE=current"])
    # The "current" FIPS module version equals the OpenSSL version.
    check_fips_provider(install_dir, installer.version)


@pytest.mark.fips
@pytest.mark.usefixtures("clean_install")
def test_fips_requires_app(installer: InstallerInfo) -> None:
    """FIPS install without openssl.exe must fail — the app is required
    to generate fipsmodule.cnf during install."""
    with pytest.raises(subprocess.CalledProcessError):
        install(
            installer,
            [
                "INSTALL_FIPS=1",
                "INSTALL_FIPS_TYPE=validated",
                "INSTALL_APP=0",
                "INSTALL_SDK=1",
            ],
        )


@pytest.mark.usefixtures("clean_install")
def test_config_files_survive_uninstall(installer: InstallerInfo, install_dir: Path, config: dict) -> None:
    """User edits to openssl.cnf must survive uninstall — the whole point of
    `post_uninstall_keep` is preserving user-customized configuration. Append
    a unique sentinel line, uninstall, and verify the line is still there."""
    install(installer)
    cnf = install_dir / "config" / "openssl.cnf"
    sentinel = f"# test sentinel {uuid.uuid4().hex}"
    with cnf.open("a", encoding="utf-8") as f:
        f.write("\n" + sentinel + "\n")
    uninstall(installer)
    check_post_uninstall(config, install_dir)
    after = cnf.read_text(encoding="utf-8")
    assert sentinel in after, f"user edit lost after uninstall — sentinel {sentinel!r} not found in cnf"


@pytest.mark.fips
@pytest.mark.usefixtures("clean_install")
def test_fipsinstall_runs_during_install(installer: InstallerInfo, install_dir: Path) -> None:
    """During FIPS install, the MSI's LaunchFile custom action runs
    `openssl fipsinstall` to generate config/fipsmodule.cnf — the file that
    holds the integrity MAC of the FIPS provider and lets openssl load it
    at runtime. Verify the file exists, has the expected sections, and that
    `openssl fipsinstall -verify` succeeds: recomputing the MAC against the
    shipped fips.dll and matching it to the cnf proves the in-install
    command ran and produced a usable config (not just a stale leftover)."""
    install(
        installer,
        [
            "INSTALL_FIPS=1",
            "INSTALL_FIPS_TYPE=validated",
            "INSTALL_APP=1",
            "INSTALL_SDK=1",
        ],
    )
    cnf_path = install_dir / "config" / "fipsmodule.cnf"
    assert cnf_path.exists(), f"{cnf_path} missing — `openssl fipsinstall` did not run during install"

    content = cnf_path.read_text(encoding="utf-8")
    assert "[fipsmodule_sect]" in content, f"missing [fipsmodule_sect] in fipsmodule.cnf:\n{content}"
    assert "module-mac" in content, f"missing module-mac in fipsmodule.cnf:\n{content}"

    exe = install_dir / "bin" / "openssl.exe"
    fips_dll = install_dir / "lib" / "ossl-modules" / "fips.dll"
    res = subprocess.run(
        [str(exe), "fipsinstall", "-verify", "-module", str(fips_dll), "-in", str(cnf_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        raise AssertionError(
            f"openssl fipsinstall -verify failed (exit {res.returncode}) — "
            f"fipsmodule.cnf's MAC does not match the installed fips.dll, "
            f"meaning the install-time fipsinstall command produced an inconsistent config.\n"
            f"stdout:\n{res.stdout}\n"
            f"stderr:\n{res.stderr}"
        )
