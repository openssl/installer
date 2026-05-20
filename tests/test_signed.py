# Authenticode signature tests for the signed MSI artifact.
#
# All tests carry the `signed` marker and are skipped by default
# (see addopts in pyproject.toml). Run with:
#
#     uv run pytest -m signed --installer path\to\signed.msi
from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

import pytest
from conftest import install
from conftest import InstallerInfo
from conftest import uninstall


pytestmark = pytest.mark.signed


_AUTHENTICODE_SCRIPT = Path(__file__).parent / "authenticode.ps1"


@lru_cache(maxsize=64)
def _authenticode(file_path: str) -> dict:
    """Return Get-AuthenticodeSignature output as a dict.

    Includes Status as the enum *string* (e.g. "Valid"), the StatusMessage,
    the SignerCertificate (Subject, Issuer, NotAfter, Thumbprint), and
    TimeStamperCertificate when an RFC 3161 timestamp is present.

    The PowerShell logic lives in authenticode.ps1; the file path is passed
    as a parameter so it doesn't have to be string-interpolated into a
    command line (which would break on paths containing apostrophes).
    """
    res = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(_AUTHENTICODE_SCRIPT),
            "-FilePath",
            file_path,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(res.stdout)


@pytest.fixture(scope="session")
def signature(installer: InstallerInfo) -> dict:
    return _authenticode(str(installer.path))


def test_signature_status_valid(signature: dict) -> None:
    """Authenticode Status must be Valid — anything else (NotSigned,
    HashMismatch, NotTrusted, UnknownError) is a release blocker."""
    assert signature["Status"] == "Valid", f"Authenticode status: {signature['Status']}"


def test_publisher_matches_expected(signature: dict, config: dict) -> None:
    """SignerCertificate subject must contain the configured CN."""
    cert = signature.get("SignerCert")
    assert cert is not None, "no signer certificate found"
    subject = cert["Subject"]
    expected = config["signing"]["publisher_subject_cn"]
    assert expected.lower() in subject.lower(), f"publisher CN {expected!r} not found in subject {subject!r}"


def test_signature_has_timestamp(signature: dict, config: dict) -> None:
    """A timestamped signature stays verifiable after the signing
    certificate expires."""
    if not config["signing"].get("timestamp_required", False):
        pytest.skip("timestamp not required by config")
    ts = signature.get("TimeStamperCert")
    assert ts is not None, "expected an RFC 3161 timestamp on the signature"


def test_msi_file_is_msi(installer: InstallerInfo) -> None:
    """Sanity check: the file is actually an MSI (cabinet header)."""
    with open(installer.path, "rb") as f:
        header = f.read(8)
    # MSI files are OLE Compound Documents — magic D0 CF 11 E0 A1 B1 1A E1.
    assert header == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", f"file does not look like an MSI: {header!r}"


@pytest.fixture(scope="session")
def installed_artifact(installer: InstallerInfo) -> Iterator[None]:
    """Install the MSI with every component so the file tree contains every
    binary the product can ship — then uninstall at session end. Used by tests
    that walk the install dir."""
    install(
        installer,
        [
            "INSTALL_APP=1",
            "INSTALL_SDK=1",
            "INSTALL_FIPS=1",
            "INSTALL_FIPS_TYPE=validated",
        ],
    )
    yield
    uninstall(installer)


@pytest.mark.usefixtures("installed_artifact")
def test_installed_binaries_signed(install_dir: Path, config: dict) -> None:
    """Every .exe and .dll laid down by the installer must be Authenticode-
    Valid and signed by the expected publisher. Collects all failures so a
    single run reports every offender."""
    expected = config["signing"]["publisher_subject_cn"]
    binaries = sorted({*install_dir.rglob("*.exe"), *install_dir.rglob("*.dll")})
    assert binaries, f"no .exe or .dll files found under {install_dir}"

    problems: list[str] = []
    for binary in binaries:
        sig = _authenticode(str(binary))
        status = sig["Status"]
        if status != "Valid":
            # Skip sig.StatusMessage — for NotSigned it returns a misleading
            # "execution policy" hint that has nothing to do with the actual
            # cause (the file genuinely lacks an Authenticode signature).
            problems.append(f"{binary}: {status}")
            continue
        cert = sig.get("SignerCert") or {}
        subject = cert.get("Subject", "")
        if expected.lower() not in subject.lower():
            problems.append(f"{binary}: unexpected publisher: {subject!r}")

    if problems:
        raise AssertionError("Binary signature problems:\n" + "\n".join(f"  - {p}" for p in problems))
