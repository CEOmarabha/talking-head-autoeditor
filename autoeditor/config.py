"""Brand + path configuration.

Everything visual lives here so the engine stays generic. Edit `brand.yaml` in
the repo root (or set the env vars). Never edit the pipeline to change a
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

    Deliberately dependency-free. The project installs with ffmpeg and pip,
    and nothing more exotic than that.
    """
    out: dict = {}
    if not path.exists():
        return out

    def _strip_comment(s: str) -> str:
        """Remove a trailing # comment without eating quoted '#RRGGBB'."""
        in_q = None
        for i, ch in enumerate(s):
            if in_q:
                if ch == in_q:
                    in_q = None
            elif ch in "'\"":
                in_q = ch
            elif ch == "#" and (i == 0 or s[i - 1] in " \t"):
                return s[:i]
        return s

    section = None
    for raw in path.read_text().splitlines():
        line = _strip_comment(raw).rstrip()
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
    banned_chars: tuple = ()        # characters QA should reject on screen

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
    """Editorial policy: the decisions that make an edit feel authored."""
    # cutting
    min_pause_long: float = 0.90    # silence >= this is removable (lessons)
    min_pause_short: float = 0.55   # same, for vertical/short-form
    pad_head: float = 0.30          # keep this much air BEFORE a word
    pad_tail: float = 0.35          # and after it. Cuts never land inside a word.
    retake_min_words: int = 3       # repeated run that counts as a retake
    retake_max_gap: float = 14.0    # seconds between the two attempts
    # verification gates (see docs/VERIFICATION.md)
    sync_tolerance_ms: int = 25
    word_integrity_min: float = 0.96
    require_script_gate: bool = True
    target_lufs: float = -14.0


@dataclass
class Config:
    brand: Brand = field(default_factory=Brand)
    rules: Rules = field(default_factory=Rules)
    profile_id: str | None = None
    # per-style caption/pacing overrides from the profile, e.g.
    # style: { default_style: short, short_cap_scale: 0.065, ... }
    style: dict = field(default_factory=dict)
    # Creator-specific editorial direction passed to the DeepSeek director and
    # critic. These values describe observable edit choices, not timing data;
    # deterministic validation still owns every event time and release gate.
    creative: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None = None,
             profile: str | None = None) -> "Config":
        """Load config from an explicit path, a profile package, or the
        legacy repo-root brand.yaml (in that priority order)."""
        profile = profile or os.environ.get("AUTOEDITOR_PROFILE") or None
        src = path
        if src is None and profile:
            from .profiles import profile_dir
            src = profile_dir(profile) / "profile.yaml"
        data = _parse_yamlish(src or ROOT / "brand.yaml")
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
        style = {}
        for k, v in (data.get("style") or {}).items():
            try:
                style[k] = float(v) if "." in str(v) else int(v)
            except (TypeError, ValueError):
                style[k] = v
        creative = {
            str(k): str(v)
            for k, v in (data.get("creative") or {}).items()
        }
        return cls(
            brand=b, rules=r, profile_id=profile,
            style=style, creative=creative,
        )


def font_file(brand: Brand, profile_id: str | None = None) -> tuple[str, bool]:
    """(path, is_brand_font). Captions are rendered as PNGs, so we need a real
    font FILE, because minimal ffmpeg builds have no libass or drawtext.

    Search order: profile asset fonts, then user/system font dirs on macOS,
    Linux AND Windows, then the configured fallbacks, then any bundled font
    shipped inside a packaged desktop build ($AUTOEDITOR_BUNDLED_FONTS)."""
    search: list[Path] = []
    if profile_id:
        from .profiles import assets_dir
        ad = assets_dir(profile_id)
        if ad:
            search.append(ad / "fonts")
            search.append(ad)
    bundled = os.environ.get("AUTOEDITOR_BUNDLED_FONTS")
    if bundled:
        search.append(Path(bundled))
    search += [
        Path.home() / "Library/Fonts", Path("/Library/Fonts"),
        Path("/System/Library/Fonts/Supplemental"),
        Path("/usr/share/fonts"), Path.home() / ".fonts",
        Path(os.environ.get("WINDIR", "C:\\Windows")) / "Fonts",
        Path(os.environ.get("LOCALAPPDATA", "")) /
        "Microsoft" / "Windows" / "Fonts",
    ]
    for d in search:
        if not d or not d.exists():
            continue
        hits = sorted(d.glob(f"**/{brand.font_pattern}*"))
        if hits:
            return str(hits[0]), True
    for fb in brand.font_fallbacks:
        if Path(fb).exists():
            return fb, False
    # last resort: ship-anything policy inside a packaged build
    for d in search:
        if d and d.exists():
            any_font = sorted(list(d.glob("**/*.ttf")) +
                              list(d.glob("**/*.otf")) +
                              list(d.glob("**/*.ttc")))
            if any_font:
                return str(any_font[0]), False
    return "", False
