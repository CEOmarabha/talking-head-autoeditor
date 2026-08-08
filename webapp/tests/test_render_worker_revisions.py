"""Executable checks for the daemon's approved-revision boundary."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from webapp.render_worker import render_worker


def _job(payload: dict) -> dict:
    return {
        "id": "revision_apply_rev123",
        "claim_token": "claim123",
        "payload_json": json.dumps(payload),
    }


def test_revision_requires_worker_bound_approved_proposal(monkeypatch):
    monkeypatch.setattr(render_worker, "handle_make", lambda *_a, **_kw: None)
    with pytest.raises(RuntimeError, match="approved proposal"):
        render_worker.handle_revision(
            _job({"revision_id": "rev123"}),
            {"type": "short"}, [], "secret", None, object())


def test_revision_applies_proposal_as_exact_engine_args(monkeypatch):
    captured = {}

    def fake_make(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs

    monkeypatch.setattr(render_worker, "handle_make", fake_make)
    proposal = {
        "summary": "make it vertical and use short pacing",
        "operations": [
            {"op": "set_edit_style", "style": "short"},
            {"op": "set_aspect_ratio", "aspect": "9x16"},
        ],
    }
    render_worker.handle_revision(
        _job({"revision_id": "rev123", "proposal": proposal}),
        {"type": "custom"}, [], "secret",
        {"params_json": json.dumps({"caption_mode": "sidecar"})}, object())

    assert captured["kwargs"]["revision_id"] == "rev123"
    assert captured["kwargs"]["engine_args_override"] == [
        "--style", "short", "--aspects", "9x16",
        "--profile", "generic_custom", "--no-burn",
    ]


def test_revision_rejects_unexecutable_operation_before_render(monkeypatch):
    rendered = False

    def fake_make(*_args, **_kwargs):
        nonlocal rendered
        rendered = True

    monkeypatch.setattr(render_worker, "handle_make", fake_make)
    with pytest.raises(ValueError, match="not in the executable contract"):
        render_worker.handle_revision(
            _job({
                "revision_id": "rev123",
                "proposal": {
                    "operations": [{"op": "cinematic_grade"}],
                },
            }),
            {"type": "short"}, [], "secret", None, object())
    assert rendered is False


def test_revision_accepts_canonical_proposal_json_string(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        render_worker, "handle_make",
        lambda *_a, **kw: captured.update(kw))
    proposal = {
        "operations": [{"op": "set_caption_mode", "mode": "sidecar"}],
    }
    render_worker.handle_revision(
        _job({
            "revision_id": "rev123",
            "proposal_json": json.dumps(proposal),
        }),
        {"type": "long"}, [], "secret", None, object())
    assert captured["engine_args_override"] == [
        "--style", "long", "--aspects", "16x9",
        "--profile", "generic_long", "--no-burn",
    ]
