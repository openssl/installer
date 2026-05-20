# Silent-install (msiexec /qn) test cases, ported from test.py.
from __future__ import annotations

import subprocess  # used by pytest.raises(subprocess.CalledProcessError)
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
    """User-edited config files must remain after uninstall."""
    install(installer)
    uninstall(installer)
    check_post_uninstall(config, install_dir)
