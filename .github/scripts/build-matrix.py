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
# Each row carries the OpenSSL branch under test and the FIPS-validated branch
# to build alongside it (looked up from fips.validated_branches in config.yaml).
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import yaml


CONFIG = Path(__file__).resolve().parents[2] / "tests" / "config.yaml"


def major_minor(ref_name: str, branches_table: dict) -> str:
    """Map a ref name like 'openssl-3.5' or 'master' to a major.minor key.
    Falls back to the highest configured key for 'master'."""
    if ref_name.startswith("openssl-"):
        return ref_name.removeprefix("openssl-")
    # master: pick the largest configured key
    return max(branches_table.keys(), key=lambda v: tuple(int(x) for x in v.split(".")))


def select_refs(cfg: dict, event: str, override: str) -> list[str]:
    all_names = [r["name"] for r in cfg["openssl"]["refs"]]
    if override.strip():
        wanted = [r.strip() for r in override.split(",") if r.strip()]
        unknown = [w for w in wanted if w not in all_names]
        if unknown:
            sys.exit(f"unknown openssl refs requested: {unknown}; known: {all_names}")
        return wanted
    if event in ("schedule", "workflow_dispatch"):
        return all_names
    return cfg["openssl"]["pr_subset"]


def main() -> None:
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    override = os.environ.get("REFS_INPUT", "")
    selected = select_refs(cfg, event, override)

    branches = {r["name"]: r["branch"] for r in cfg["openssl"]["refs"]}
    fips_branches = cfg["fips"]["validated_branches"]

    include = []
    for name in selected:
        mm = major_minor(name, fips_branches)
        if mm not in fips_branches:
            sys.exit(f"no FIPS validated branch configured for major.minor {mm!r}")
        include.append(
            {
                "openssl-ref": name,
                "openssl-branch": branches[name],
                "fips-ref": fips_branches[mm],
            }
        )

    payload = json.dumps({"include": include})
    print(payload)
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"refs={payload}\n")


if __name__ == "__main__":
    main()
