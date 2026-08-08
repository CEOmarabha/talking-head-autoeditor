"""Executable web project types and the DeepSeek revision contract.

This module is intentionally narrower than the product vocabulary. Every
project default, preset parameter, and revision operation must resolve to an
actual engine CLI option. Unsupported product promises fail before rendering.
"""
from __future__ import annotations


class UnsupportedProjectTypeError(ValueError):
    """The selected product type has no complete engine implementation."""


GENERIC_PROFILE_IDS = (
    "generic_short",
    "generic_long",
    "generic_commercial",
    "generic_podcast",
    "generic_course",
    "generic_custom",
)


# The engine has two edit grammars. Profiles make supported products distinct
# through real cutting, caption, and DeepSeek creative-direction settings.
# `engine_behavior` is executable-contract documentation for tests and callers.
PROJECT_TYPES = {
    "short": {
        "supported": True,
        "style": "short",
        "aspects": "9x16",
        "profile": "generic_short",
        "engine_behavior": "social short/reel profile, short grammar, 9:16",
    },
    "long": {
        "supported": True,
        "style": "long",
        "aspects": "16x9",
        "profile": "generic_long",
        "engine_behavior": "long talking-head profile, long grammar, 16:9",
    },
    "commercial": {
        "supported": True,
        "style": "short",
        "aspects": "9x16",
        "profile": "generic_commercial",
        "engine_behavior": "commercial/ad profile, short grammar, 9:16",
    },
    "podcast": {
        "supported": True,
        "style": "long",
        "aspects": "16x9",
        "profile": "generic_podcast",
        "engine_behavior": "podcast/interview profile, long grammar, 16:9",
    },
    "course": {
        "supported": True,
        "style": "long",
        "aspects": "16x9",
        "profile": "generic_course",
        "engine_behavior": "course/lesson profile, long grammar, 16:9",
    },
    "clips": {
        "supported": False,
        "style": None,
        "aspects": None,
        "profile": None,
        "engine_behavior": (
            "unsupported: the engine cannot select moments and emit multiple "
            "independently gated clips"
        ),
    },
    "custom": {
        "supported": True,
        "style": "auto",
        "aspects": "auto",
        "profile": "generic_custom",
        "engine_behavior": "generic custom profile, automatic grammar/aspect",
    },
}


_PRESET_CHOICES = {
    "style": ("auto", "short", "long"),
    "aspects": ("auto", "9x16", "16x9"),
    "caption_mode": ("burned", "sidecar"),
    "visual_mode": ("full", "baseline"),
    "profile": GENERIC_PROFILE_IDS,
}


def _engine_options(project_type: str,
                    preset_params: dict | None) -> dict[str, str]:
    if project_type not in PROJECT_TYPES:
        raise ValueError(f"unknown project type: {project_type!r}")
    project = PROJECT_TYPES[project_type]
    if not project["supported"]:
        raise UnsupportedProjectTypeError(
            f"project type {project_type!r} is not executable: "
            f"{project['engine_behavior']}")
    if preset_params is None:
        preset_params = {}
    if not isinstance(preset_params, dict):
        raise ValueError("preset parameters must be an object")
    unknown = sorted(set(preset_params) - set(_PRESET_CHOICES))
    if unknown:
        raise ValueError(
            "unsupported preset parameter(s): " + ", ".join(unknown))

    options = {
        "style": str(project["style"]),
        "aspects": str(project["aspects"]),
        "caption_mode": "burned",
        "visual_mode": "full",
        "profile": str(project["profile"]),
    }
    for name, value in preset_params.items():
        if value not in _PRESET_CHOICES[name]:
            choices = ", ".join(_PRESET_CHOICES[name])
            raise ValueError(
                f"preset {name} must be one of: {choices}")
        options[name] = value
    return options


def engine_args(project_type: str, preset_params: dict | None) -> list[str]:
    """Resolve a product and preset to exact supported engine CLI arguments."""
    options = _engine_options(project_type, preset_params)
    args = [
        "--style", options["style"],
        "--aspects", options["aspects"],
        "--profile", options["profile"],
    ]
    if options["caption_mode"] == "sidecar":
        args.append("--no-burn")
    if options["visual_mode"] == "baseline":
        args.append("--no-premium")
    return args


# DeepSeek may propose only operations with exact mappings above. There is no
# speech-cut operation here. The engine's word-protection and QA gates remain
# responsible for every automatic speech decision.
ALLOWED_OPS = {
    "set_edit_style": {
        "params": {"style": ["auto", "short", "long"]},
        "approval": False,
        "human": "Use {style} edit pacing",
    },
    "set_aspect_ratio": {
        "params": {"aspect": ["auto", "9x16", "16x9"]},
        "approval": False,
        "human": "Deliver in {aspect}",
    },
    "set_caption_mode": {
        "params": {"mode": ["burned", "sidecar"]},
        "approval": False,
        "human": "Use {mode} captions",
    },
    "set_visual_mode": {
        "params": {"mode": ["full", "baseline"]},
        "approval": False,
        "human": "Use the {mode} visual treatment",
    },
    "set_edit_profile": {
        "params": {"profile_id": list(GENERIC_PROFILE_IDS)},
        "approval": False,
        "human": "Use the {profile_id} edit profile",
    },
}


def validate_proposal(raw: dict) -> tuple[dict, bool, list[str]]:
    """Validate a model proposal without partially accepting any operation."""
    if not isinstance(raw, dict):
        return {}, False, ["proposal must be an object"]
    ops_in = raw.get("operations")
    if not isinstance(ops_in, list) or not ops_in:
        return {}, False, ["proposal has no operations list"]
    if len(ops_in) > 8:
        return {}, False, ["too many operations in one proposal (max 8)"]

    errors: list[str] = []
    clean: list[dict] = []
    needs_approval = False
    seen: set[str] = set()
    for index, operation in enumerate(ops_in):
        if not isinstance(operation, dict) or "op" not in operation:
            errors.append(f"operation {index} is malformed")
            continue
        name = operation["op"]
        spec = ALLOWED_OPS.get(name)
        if not spec:
            errors.append(
                f"operation {name!r} is not in the executable contract")
            continue
        if name in seen:
            errors.append(f"operation {name!r} appears more than once")
            continue
        seen.add(name)
        allowed_keys = {"op", "human", *spec["params"]}
        extra_keys = sorted(set(operation) - allowed_keys)
        if extra_keys:
            errors.append(
                f"operation {name!r} has unsupported field(s): "
                + ", ".join(extra_keys))
            continue

        params = {}
        valid = True
        for param_name, choices in spec["params"].items():
            value = operation.get(param_name)
            if value not in choices:
                errors.append(
                    f"{name}.{param_name} must be one of {choices}")
                valid = False
            else:
                params[param_name] = value
        if not valid:
            continue
        clean.append({
            "op": name,
            **params,
            "human": spec["human"].format(**params),
        })
        needs_approval = needs_approval or bool(spec["approval"])

    if errors:
        return {}, False, errors
    return {
        "operations": clean,
        "summary": str(raw.get("summary") or "")[:400],
    }, needs_approval, []


def revision_engine_args(project_type: str, preset_params: dict | None,
                         proposal: dict) -> list[str]:
    """Apply a validated approved proposal to the project's engine options."""
    clean, needs_approval, errors = validate_proposal(proposal)
    if errors:
        raise ValueError("revision proposal rejected: " + "; ".join(errors))
    if needs_approval:
        raise ValueError("revision proposal still requires approval")

    params = dict(preset_params or {})
    for operation in clean["operations"]:
        name = operation["op"]
        if name == "set_edit_style":
            params["style"] = operation["style"]
        elif name == "set_aspect_ratio":
            params["aspects"] = operation["aspect"]
        elif name == "set_caption_mode":
            params["caption_mode"] = operation["mode"]
        elif name == "set_visual_mode":
            params["visual_mode"] = operation["mode"]
        elif name == "set_edit_profile":
            params["profile"] = operation["profile_id"]
        else:  # pragma: no cover - validate_proposal owns this invariant
            raise ValueError(f"no engine mapping for operation {name!r}")
    return engine_args(project_type, params)


PROPOSAL_PROMPT = """You are the edit planner for a verified video editor.
The user asked: {request!r}

Video context: type={ptype}, duration={duration}s.
Transcript excerpt: {transcript}

Respond with ONLY a JSON object:
{{"summary": "<one sentence of what you will change>",
  "operations": [{{"op": "<name>", ...params}}]}}

Allowed operations and params (use ONLY these):
{contract}

Rules: max 8 operations and never repeat an operation. These operations can
change edit pacing, delivery framing, caption delivery, the complete visual
layer, or the generic edit profile. They cannot delete speech, target a new
duration, split clips, acquire a specific asset, resize captions, apply a
grade, or tune individual punch-ins or b-roll. If the request cannot be
expressed exactly, return
{{"summary": "cannot", "operations": []}}."""
