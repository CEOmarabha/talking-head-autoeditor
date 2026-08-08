"""Generic product profiles must change real engine configuration."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from autoeditor.config import Config, _parse_yamlish
from autoeditor.profiles import profile_dir, profile_sha256
from webapp.render_worker.project_types import GENERIC_PROFILE_IDS


def test_every_generic_profile_is_approved_loadable_and_hashed():
    for profile_id in GENERIC_PROFILE_IDS:
        path = profile_dir(profile_id) / "profile.yaml"
        metadata = _parse_yamlish(path)["meta"]
        config = Config.load(profile=profile_id)
        assert metadata["status"] == "approved"
        assert config.profile_id == profile_id
        assert config.creative["mode"]
        assert len(profile_sha256(profile_id)) == 64


def test_generic_profiles_have_real_distinct_contracts():
    short = Config.load(profile="generic_short")
    commercial = Config.load(profile="generic_commercial")
    long_form = Config.load(profile="generic_long")
    podcast = Config.load(profile="generic_podcast")
    course = Config.load(profile="generic_course")
    custom = Config.load(profile="generic_custom")

    assert short.style["default_style"] == "short"
    assert commercial.style["default_style"] == "short"
    assert commercial.rules.min_pause_short < short.rules.min_pause_short
    assert commercial.creative["mode"] != short.creative["mode"]
    assert podcast.rules.min_pause_long > long_form.rules.min_pause_long
    assert podcast.brand.caption_words == 5
    assert course.creative["mode"] != long_form.creative["mode"]
    assert custom.style["default_style"] == "auto"
