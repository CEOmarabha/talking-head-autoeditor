"""Brand + path configuration.

Everything visual lives here so the engine stays generic. Edit `brand.yaml` in
the repo root (or set the env vars) -- never edit the pipeline to change a
colour.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME_DATA = Path(os.environ.get("AUTOEDITOR_HOME",
                                Path.home() / ".autoeditor"))
CACHE = HOME_DATA / "broll_cache"
SFX_DIR = HOME_DATA / "sfx"
VIZ_PROJECT = HOME_DATA / "remotion-viz"


def _parse_yamlish(path: Path) -> dict:
    """Tiny flat YAML reader (key: value, one level of nesting).

    Deliberately dependency-free -- the whole point of this project is that it
    installs with ffmpeg + pip and nothing exotic.
    """
    out: dict = {}
    if not path.exists():
        return out
    section = None
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indented = line[0] in " \t"
        key, _, val = line.strip().partition(":")
        key, val = key.strip(), val.strip().strip("'\"")
        if not val:
            section = key
            out[section] = {}
            continue
        if indented and section:
            out[section][key] = val
        else:
            out[key] = val
            section = None
    return out


@dataclass
class Brand:
    """Visual identity applied to captions, cards and generated visuals."""
    accent: str = "#E8C7A7"        # highlight / active caption word
    text: str = "#FFFFFF"
    background: str = "#000000"
    font_pattern: str = "WorkSans"  # matched against installed font files
    font_fallbacks: tuple = (
        "/System/Library/Fonts/Supplemental/Arial Black.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    )
    caption_scale: float = 0.045    # fraction of frame height
    caption_words: int = 4          # words per caption chunk
    banned_chars: tuple = ()        # e.g. ("—",) to forbid em dashes

    @property
    def accent_rgb(self) -> tuple:
        h = self.accent.lstrip("#")
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) + (255,)

    @property
    def text_rgb(self) -> tuple:
        h = self.text.lstrip("#")
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) + (255,)


@dataclass
class Rules:
    """Editorial policy -- the decisions that make an edit feel authored."""
    # cutting
    min_pause_long: float = 0.90    # silence >= this is removable (lessons)
    min_pause_short: float = 0.55   # ...and for vertical/short-form
    pad_head: float = 0.30          # keep this much air BEFORE a word
    pad_tail: float = 0.35          # ...and AFTER it. Never cut inside a word.
    retake_min_words: int = 3       # repeated run that counts as a retake
    retake_max_gap: float = 14.0    # seconds between the two attempts
    # verification gates (see docs/VERIFICATION.md)
    sync_tolerance_ms: int = 25
    word_integrity_min: float = 0.97
    require_script_gate: bool = True
    # source repair
    av_offset_ms: int = 0           # + delays audio; measure yours once
    target_lufs: float = -14.0


@dataclass
class Config:
    brand: Brand = field(default_factory=Brand)
    rules: Rules = field(default_factory=Rules)

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        data = _parse_yamlish(path or ROOT / "brand.yaml")
        b, r = Brand(), Rules()
        for k, v in (data.get("brand") or {}).items():
            if hasattr(b, k):
                cur = getattr(b, k)
                setattr(b, k, type(cur)(v) if not isinstance(cur, tuple) else v)
        for k, v in (data.get("rules") or {}).items():
            if hasattr(r, k):
                cur = getattr(r, k)
                setattr(r, k, type(cur)(v) if isinstance(cur, (int, float, str))
                        and not isinstance(cur, bool)
                        else str(v).lower() in ("1", "true", "yes"))
        return cls(brand=b, rules=r)


def font_file(brand: Brand) -> tuple[str, bool]:
    """(path, is_brand_font). Captions are rendered as PNGs, so we need a real
    font FILE -- minimal ffmpeg builds have no libass/drawtext."""
    for d in (Path.home() / "Library/Fonts", Path("/Library/Fonts"),
              Path("/usr/share/fonts"), Path.home() / ".fonts"):
        if not d.exists():
            continue
        hits = sorted(d.glob(f"**/{brand.font_pattern}*"))
        if hits:
            return str(hits[0]), True
    for fb in brand.font_fallbacks:
        if Path(fb).exists():
            return fb, False
    return "", False
