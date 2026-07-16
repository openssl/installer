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
from conftest import HYBRID_BUILD_NAMES
from conftest import imported_dlls
from conftest import install
from conftest import InstallerInfo
from conftest import msi_fips_ui_facts
from conftest import supported_fips_type
from conftest import uninstall
from conftest import validated_option_disabled
from conftest import VCRUNTIME_DLLS
from conftest import VS_BUILD_NAMES


# The validated FIPS module (3.1.2) is only offered by the VS installers.
# Commit 63b0a77 removed the option from the hybrid installers' UI because the
# validated module is VC-WIN64A (it would pull the VC++ runtime into an
# otherwise-HybridCRT install, deviating from the module's Security Policy).
_HYBRID_VALIDATED_SKIP = (
    "validated 3.1.2 FIPS module is not offered in hybrid installers "
    "(commit 63b0a77 hides the UI option); see test_fips_validated_option_disabled_in_hybrid"
)


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
    if installer.flavor == "hybrid":
        pytest.skip(_HYBRID_VALIDATED_SKIP)
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
    expected = config["fips"]["validated_versions"]
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
    to generate fipsmodule.cnf during install.

    Flavor-independent: the app requirement is enforced regardless of module
    type, so hybrid uses "current" (its only offered type) rather than the
    hybrid-disabled "validated"."""
    with pytest.raises(subprocess.CalledProcessError):
        install(
            installer,
            [
                "INSTALL_FIPS=1",
                f"INSTALL_FIPS_TYPE={supported_fips_type(installer)}",
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
    if installer.flavor == "hybrid":
        pytest.skip(_HYBRID_VALIDATED_SKIP)
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
    assert "[fips_sect]" in content, f"missing [fips_sect] in fipsmodule.cnf:\n{content}"
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


# --- CRT flavor -------------------------------------------------------------


@pytest.mark.usefixtures("clean_install")
def test_crt_flavor_import_table(installer: InstallerInfo, install_dir: Path) -> None:
    """The installed binaries' PE import table must match the packaged CRT
    flavor. This is the direct, runner-independent proof that a hybrid
    installer actually ships HybridCRT binaries: GitHub runners have the VC++
    runtime pre-installed, so a plain "does it run" check passes on either
    flavor. Checked binaries all come from the main OpenSSL tree, so they
    reflect the installer's flavor (the shared validated FIPS module is always
    VC-WIN64A and is intentionally excluded here)."""
    install(installer, ["INSTALL_APP=1", "INSTALL_SDK=1"])
    major = installer.major
    binaries = [
        install_dir / "bin" / "openssl.exe",
        install_dir / "bin" / f"libcrypto-{major}-x64.dll",
        install_dir / "bin" / f"libssl-{major}-x64.dll",
        install_dir / "lib" / "ossl-modules" / "legacy.dll",
    ]
    problems: list[str] = []
    for binary in binaries:
        if not binary.exists():
            problems.append(f"{binary}: expected binary not installed")
            continue
        dlls = imported_dlls(binary)
        vc_imports = sorted(dlls & set(VCRUNTIME_DLLS))
        if installer.flavor == "hybrid":
            # HybridCRT: static vcruntime + UCRT via api-ms-win-crt-* forwarders.
            if vc_imports:
                problems.append(f"{binary.name}: hybrid build must not import the dynamic VC++ runtime, but imports {vc_imports}")
        else:
            # VS / VC-WIN64A: dynamic VC++ runtime -> vcruntime140.dll present.
            # (msvcp140.dll is the C++ stdlib, which C-only OpenSSL doesn't pull
            # in, so vcruntime140.dll is the reliable dynamic-CRT marker.)
            if "vcruntime140.dll" not in dlls:
                problems.append(f"{binary.name}: VS build must import vcruntime140.dll, imports {sorted(dlls)}")
    if problems:
        msg = "CRT import-table mismatch:\n" + "\n".join(f"  - {p}" for p in problems)
        if installer.flavor == "hybrid":
            msg += (
                "\nHybridCRT binaries link vcruntime statically; a dynamic-runtime import means this "
                "tree wasn't fully (re)built with VC-WIN64A-HYBRIDCRT. If only some binaries are dirty, "
                "the tree is mixed — do a clean build (fresh dir / nmake clean) per flavor."
            )
        raise AssertionError(msg)


@pytest.mark.fips
@pytest.mark.usefixtures("clean_install")
def test_fips_validated_option_disabled_in_hybrid(installer: InstallerInfo) -> None:
    """The validated FIPS option must be offered only by the VS installers.

    Introspects the installer's own MSI database (commit 63b0a77's mechanism is
    UI-only and gated on AI_BUILD_NAME, so a silent install can't observe it):
      * hybrid -> RadioButtonGroup_1 hidden AND INSTALL_FIPS_TYPE forced to
        "current" for this build name -> the user can never pick "validated";
      * vs     -> neither, and INSTALL_FIPS_TYPE still defaults to "validated".
    """
    # The .exe bootstrapper's inner MSI is only readable once cached by an
    # install; a bare .msi is read directly. A default install satisfies both.
    if installer.path.suffix.lower() == ".exe":
        install(installer)

    facts = msi_fips_ui_facts(installer)
    disabled = validated_option_disabled(facts)
    build_name = facts["build_name"]
    default_type = facts["default_type"]

    if installer.flavor == "hybrid":
        assert build_name in HYBRID_BUILD_NAMES, f"unexpected hybrid AI_BUILD_NAME: {build_name!r}"
        assert disabled, (
            "hybrid installer must disable the validated FIPS option, but the UI gating does not "
            f"cover build {build_name!r}.\n"
            f"  RadioButtonGroup_1 Hide condition: {facts['hide_condition']!r}\n"
            f"  INSTALL_FIPS_TYPE=current force condition: {facts['force_current_condition']!r}"
        )
    else:
        assert build_name in VS_BUILD_NAMES, f"unexpected vs AI_BUILD_NAME: {build_name!r}"
        assert not disabled, f"VS installer must keep the validated FIPS option, but build {build_name!r} is UI-gated off"
        assert default_type == "validated", f"VS should default INSTALL_FIPS_TYPE to 'validated', got {default_type!r}"
