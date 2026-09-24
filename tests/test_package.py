# Package-structure tests: facts about the installer's MSI database that a
# silent install can't observe. They read the package (or the MSI extracted
# from the .exe bootstrapper) and never install it.
from __future__ import annotations

import re
from pathlib import Path

import pytest
from conftest import InstallerInfo

# Component table: msidbComponentAttributes64bit
_COMPONENT_64BIT = 0x100
# Upgrade table: msidbUpgradeAttributesOnlyDetect
_UPGRADE_ONLY_DETECT = 0x2

# Platform field of the Template summary property per installer architecture.
# Advanced Installer leaves it empty for 32-bit packages, which Windows
# Installer reads as Intel.
_EXPECTED_PLATFORMS = {"x64": {"x64"}, "arm64": {"Arm64"}, "x86": {"", "Intel"}}

_AIP = Path(__file__).parent.parent / "windows-installer" / "openssl.aip"


def test_platform_matches_architecture(installer: InstallerInfo, package_facts: dict) -> None:
    """The package must declare the platform its binaries are built for.
    Windows Installer rejects an unknown platform with error 1633 before
    running anything (an Advanced Installer build once wrote "x86")."""
    template = package_facts["template"]
    platform = template.split(";", 1)[0]
    expected = _EXPECTED_PLATFORMS[installer.arch]
    assert platform in expected, f"{installer.arch} package declares Template {template!r}, expected platform {sorted(expected)}"


def test_x86_package_has_no_64bit_components(installer: InstallerInfo, package_facts: dict) -> None:
    """A 32-bit package must not contain 64-bit components: 32-bit Windows
    refuses them, and on 64-bit Windows their registry values land in the
    64-bit view instead of Wow6432Node."""
    if installer.arch != "x86":
        pytest.skip("64-bit packages may legitimately contain 32-bit components")
    offenders = sorted(c["name"] for c in package_facts["components"] if c["attributes"] & _COMPONENT_64BIT)
    assert not offenders, f"x86 package contains 64-bit components: {offenders}"


def test_detects_newer_installed_version(installer: InstallerInfo, package_facts: dict) -> None:
    """The Upgrade table must detect an installed newer version, so an older
    package cannot silently install over it. Advanced Installer's GUI has
    dropped this row before without any visible change in the project."""
    rows = [u for u in package_facts["upgrade"] if u["action_property"] == "AI_NEWERPRODUCTFOUND"]
    assert rows, f"no AI_NEWERPRODUCTFOUND row in the Upgrade table: {package_facts['upgrade']}"
    assert any(
        u["attributes"] & _UPGRADE_ONLY_DETECT and u["version_min"] == installer.version for u in rows
    ), f"AI_NEWERPRODUCTFOUND must be a detect-only row starting at {installer.version}, got {rows}"


def test_sdk_dialog_updates_every_conditioned_feature(package_facts: dict) -> None:
    """The SDK dialog's Next button hands UpdateFeaturesInstallStates the list
    of features whose install level depends on INSTALL_APP / INSTALL_SDK.
    Advanced Installer silently omits that list when a sub-feature of a
    conditioned feature has no condition of its own, and then the dialog's
    choices stop applying. GUI tests don't run in CI, so check the table.
    (Prerequisite features carry Advanced Installer's own conditions and are
    not driven by the dialog, hence the property filter.)"""
    present = set(package_facts["features"])
    conditioned = sorted(
        {c["feature"] for c in package_facts["feature_conditions"] if re.search(r"\bINSTALL_(APP|SDK)\b", c["condition"])}
        & present
    )
    assert conditioned, "no features conditioned on INSTALL_APP / INSTALL_SDK; the SDK dialog has nothing to drive"
    lists = package_facts["sdk_next_custom_action_data"]
    assert lists, f"SDKDlg Next passes no feature list to UpdateFeaturesInstallStates; conditioned features: {conditioned}"
    listed = set(" ".join(lists).split())
    missing = [f for f in conditioned if f not in listed]
    assert not missing, f"conditioned features missing from the SDK dialog's feature list: {missing}"


def test_prerequisite_searches_read_their_runtime_registry_view() -> None:
    """A VC++ redistributable prerequisite is installed when its registry
    search finds no runtime. The x86 runtime records its version in the 32-bit
    registry view and the x64 runtime in the 64-bit one, so each search must
    read the view of the runtime it detects (Platform="1" = Advanced
    Installer's "Use 64-bit locations" option). A 64-bit search for the x86
    runtime finds the x64 runtime instead and skips a needed install. This
    lives in the bootstrapper configuration, not the MSI, so it is read from
    the project file."""
    src = _AIP.read_text(encoding="utf-8")
    runtime_arch = {}
    for row in re.findall(r"<ROW PrereqKey=[^>]*>", src):
        arch = re.search(r"VC_redist\.(x86|x64|arm64)\.exe", row)
        key = re.search(r'PrereqKey="([^"]*)"', row)
        if arch and key:
            runtime_arch[key.group(1)] = arch.group(1)
    assert runtime_arch, f"no VC++ redistributable prerequisites found in {_AIP}"
    problems = []
    for row in re.findall(r"<ROW SearchKey=[^>]*>", src):
        match = re.search(r'Prereq="([^"]*)"', row)
        prereq = match.group(1) if match else ""
        if prereq not in runtime_arch:
            continue
        wants_64bit = runtime_arch[prereq] != "x86"
        reads_64bit = 'Platform="1"' in row
        if wants_64bit != reads_64bit:
            view = "64-bit" if reads_64bit else "32-bit"
            problems.append(f"{prereq} ({runtime_arch[prereq]} runtime) searches the {view} registry view")
    assert not problems, "; ".join(problems)
