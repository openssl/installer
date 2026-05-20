#!/usr/bin/env python
# Build the OpenSSL MSI for local development.
#
# CI builds the MSI via workflow steps (see .github/workflows/test-installer.yml).
# This script is a local-developer equivalent: stage OpenSSL sources at the
# location windows-installer/openssl.aip expects (../openssl and ../openssl-fips),
# build them, then invoke Advanced Installer.
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
AIP_PATH = REPO_ROOT / "windows-installer" / "openssl.aip"
OPENSSL_DIR = REPO_ROOT / "openssl"
OPENSSL_FIPS_DIR = REPO_ROOT / "openssl-fips"
OUTPUT_DIR = REPO_ROOT / "build-target" / "Installer64" / "DefaultBuild"

DEFAULT_ADVINST = r"C:\Program Files (x86)\Caphyon\Advanced Installer 23.5.1\bin\x86\AdvancedInstaller.com"
ADVINST = os.environ.get("ADVINST", DEFAULT_ADVINST)

OPENSSL_REMOTE = "https://github.com/openssl/openssl.git"

DESCRIPTION = """\
Build the OpenSSL MSI for local development.

CI builds the MSI via workflow steps. This script stages OpenSSL sources at
../openssl and ../openssl-fips (where openssl.aip expects them), builds them,
then invokes Advanced Installer.

Examples:
    # From local pre-built OpenSSL checkouts (junctioned into place):
    python build_msi.py --openssl-path C:\\src\\openssl \\
                        --openssl-fips-path C:\\src\\openssl-fips

    # Clone refs from openssl/openssl and build them:
    python build_msi.py --openssl-ref openssl-3.5 --fips-ref openssl-3.1.2

Prerequisites:
    - Advanced Installer 23.5.1+ installed.
      Set ADVINST env var if not at the default install location.
    - Visual Studio build tools, Strawberry Perl, NASM on PATH (for source builds).
"""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    main = p.add_mutually_exclusive_group(required=True)
    main.add_argument("--openssl-ref", help="git ref of openssl/openssl to clone and build")
    main.add_argument("--openssl-path", type=Path, help="path to a pre-built OpenSSL tree")

    p.add_argument("--fips-ref", help="git ref for the validated FIPS source build")
    p.add_argument("--openssl-fips-path", type=Path, help="path to a pre-built FIPS-source OpenSSL tree")

    p.add_argument("--build-name", default="DefaultBuild", help="AI build name (default: DefaultBuild)")
    p.add_argument(
        "--keep-staged", action="store_true", help="leave ../openssl and ../openssl-fips junctions in place after the build"
    )
    return p.parse_args()


def stage(target: Path, *, ref: str | None, path: Path | None, label: str) -> None:
    """Place an OpenSSL source tree at `target` — by junction (path mode) or
    by `git clone` (ref mode). Refuses to overwrite an existing real directory."""
    if target.exists() or target.is_symlink():
        if target.is_symlink() or _is_junction(target):
            target.unlink()
        else:
            sys.exit(f"refusing to overwrite existing directory: {target}")

    if path is not None:
        src = path.resolve()
        if not src.is_dir():
            sys.exit(f"{label} source path is not a directory: {src}")
        run(["cmd", "/c", "mklink", "/J", str(target), str(src)])
    else:
        assert ref is not None, "either ref or path must be provided"
        run(["git", "clone", "--depth=1", "--branch", ref, OPENSSL_REMOTE, str(target)])
        build_openssl(target)


def _is_junction(p: Path) -> bool:
    # Path.is_junction() exists from 3.12; fall back for 3.11.
    try:
        return p.is_junction()  # type: ignore[attr-defined]
    except AttributeError:
        try:
            return bool(p.lstat().st_reparse_tag)
        except (OSError, AttributeError):
            return False


def build_openssl(src: Path) -> None:
    """Configure + nmake an OpenSSL checkout. Caller must be in a VS dev shell."""
    run(["perl", "Configure", "VC-WIN64A", "enable-fips"], cwd=src)
    run(["nmake"], cwd=src)
    run(["nmake", "build_docs"], cwd=src)


def build_msi(build_name: str) -> Path:
    if not Path(ADVINST).exists():
        sys.exit(f"AdvancedInstaller.com not found at {ADVINST!r}. Set $ADVINST.")
    run([ADVINST, "/build", str(AIP_PATH), "-buildslist", build_name])
    msis = list(OUTPUT_DIR.glob("*.msi"))
    if not msis:
        sys.exit(f"no MSI produced under {OUTPUT_DIR}")
    if len(msis) > 1:
        sys.exit(f"expected one MSI, found: {msis}")
    return msis[0]


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print(f"+ {' '.join(cmd)}{f'  (in {cwd})' if cwd else ''}", flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def cleanup_staged() -> None:
    for d in (OPENSSL_DIR, OPENSSL_FIPS_DIR):
        if d.exists() and (d.is_symlink() or _is_junction(d)):
            d.unlink()


def main() -> None:
    args = parse_args()
    if not (args.fips_ref or args.openssl_fips_path):
        sys.exit("one of --fips-ref / --openssl-fips-path is required")

    try:
        stage(OPENSSL_DIR, ref=args.openssl_ref, path=args.openssl_path, label="OpenSSL")
        stage(OPENSSL_FIPS_DIR, ref=args.fips_ref, path=args.openssl_fips_path, label="FIPS OpenSSL")
        msi = build_msi(args.build_name)
        print(f"MSI: {msi}")
    finally:
        if not args.keep_staged:
            cleanup_staged()


if __name__ == "__main__":
    main()
