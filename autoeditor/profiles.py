"""Creator profile packages.

A profile is a folder containing `profile.yaml` plus optional assets
(fonts, overlays, sfx). It carries everything creator-specific: brand
colours, caption geometry, cutting rules, and style defaults. The engine
stays generic; profiles make it personal.

Resolution order for the profiles root:
  1. $AUTOEDITOR_PROFILES_DIR   (set by the desktop app when packaged)
  2. <repo root>/profiles

Profile selection order:
  1. --profile CLI flag
  2. $AUTOEDITOR_PROFILE
  3. none -> legacy single-brand behaviour (brand.yaml at repo root)
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def profiles_root() -> Path:
    env = os.environ.get("AUTOEDITOR_PROFILES_DIR")
    return Path(env) if env else ROOT / "profiles"


def profile_dir(profile_id: str) -> Path:
    d = profiles_root() / profile_id
    if not (d / "profile.yaml").exists():
        raise FileNotFoundError(
            f"profile '{profile_id}' not found (looked in {d})")
    return d


def list_profiles() -> list[dict]:
    """Every installed profile with its display metadata."""
    from .config import _parse_yamlish
    out = []
    root = profiles_root()
    if not root.exists():
        return out
    for d in sorted(root.iterdir()):
        y = d / "profile.yaml"
        if not y.exists():
            continue
        data = _parse_yamlish(y)
        meta = data.get("meta") or {}
        out.append({
            "id": d.name,
            "display_name": meta.get("display_name", d.name),
            "status": meta.get("status", "provisional"),
            "description": meta.get("description", ""),
            "default_style": (data.get("style") or {}).get(
                "default_style", "auto"),
        })
    return out


def assets_dir(profile_id: str | None) -> Path | None:
    if not profile_id:
        return None
    d = profiles_root() / profile_id / "assets"
    return d if d.exists() else None
