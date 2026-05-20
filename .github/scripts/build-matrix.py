#!/usr/bin/env python3
# Emit the GitHub Actions build/test matrix from tests/config.yaml.
#
# Selection rules:
#   - workflow_dispatch with `refs` input: that exact comma-separated list
#   - schedule or workflow_dispatch without input: full openssl.refs list
#   - everything else (pull_request, push): openssl.pr_subset
#
# Outputs to $GITHUB_OUTPUT:
#   refs={"include":[{"openssl-ref":"openssl-3.5","fips-ref":"openssl-3.1.2"},...]}
#
# Each row carries the OpenSSL ref under test and the FIPS-source ref to
# build alongside it. The FIPS ref is derived from fips.validated_versions:
# if the OpenSSL major.minor has an explicit entry, that version is used;
# otherwise the newest configured FIPS version (which also covers `master`).
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import yaml


CONFIG = Path(__file__).resolve().parents[2] / "tests" / "config.yaml"


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def fips_source_ref(openssl_ref: str, validated_versions: dict[str, str]) -> str:
    """Return the openssl ref to build for the validated FIPS provider.

    For refs of the form 'openssl-X.Y' with an explicit X.Y entry in
    validated_versions, that version's ref is used. Otherwise (including
    `master` and unmapped openssl-X.Y) we fall back to the newest version
    in the map.
    """
    if openssl_ref.startswith("openssl-"):
        major_minor = openssl_ref.removeprefix("openssl-")
        if major_minor in validated_versions:
            return f"openssl-{validated_versions[major_minor]}"
    newest = max(validated_versions.values(), key=_version_key)
    return f"openssl-{newest}"


def select_refs(cfg: dict, event: str, override: str) -> list[str]:
    all_refs = list(cfg["openssl"]["refs"])
    if override.strip():
        wanted = [r.strip() for r in override.split(",") if r.strip()]
        unknown = [w for w in wanted if w not in all_refs]
        if unknown:
            sys.exit(f"unknown openssl refs requested: {unknown}; known: {all_refs}")
        return wanted
    if event in ("schedule", "workflow_dispatch"):
        return all_refs
    return list(cfg["openssl"]["pr_subset"])


def main() -> None:
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    override = os.environ.get("REFS_INPUT", "")
    selected = select_refs(cfg, event, override)
    validated_versions = cfg["fips"]["validated_versions"]
    if not validated_versions:
        sys.exit("fips.validated_versions is empty — at least one entry is required")

    include = [
        {
            "openssl-ref": ref,
            "fips-ref": fips_source_ref(ref, validated_versions),
        }
        for ref in selected
    ]

    payload = json.dumps({"include": include})
    print(payload)
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"refs={payload}\n")


if __name__ == "__main__":
    main()
