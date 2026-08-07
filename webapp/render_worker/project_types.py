"""Project types -> engine invocation, and the typed edit-proposal contract.

Everything DeepSeek can propose is enumerated here. The daemon validates
every proposal against ALLOWED_OPS deterministically; anything outside the
schema is rejected before it can touch a render. Ops that change speech,
duration, licensing, or spend are flagged approval_required and the UI
must collect an explicit OK first.
"""
from __future__ import annotations

# ---------------------------------------------------------- project types
# type -> engine args. Internal creator profiles stay available for
# compatibility, but web projects use the generic mapping + the user's
# style preset parameters.
PROJECT_TYPES = {
    "short":      {"style": "short", "aspects": "9x16"},
    "long":       {"style": "long",  "aspects": "16x9"},
    "commercial": {"style": "short", "aspects": "9x16"},
    "podcast":    {"style": "long",  "aspects": "16x9"},
    "course":     {"style": "long",  "aspects": "16x9"},
    "clips":      {"style": "short", "aspects": "9x16"},
    "custom":     {"style": "auto",  "aspects": "auto"},
}


def engine_args(project_type: str, preset_params: dict | None) -> list[str]:
    t = PROJECT_TYPES.get(project_type, PROJECT_TYPES["custom"])
    args = ["--style", t["style"], "--aspects", t["aspects"]]
    return args


# ---------------------------------------------------------- proposal ops
# op -> (params spec, approval_required, human template)
# params spec: name -> (type, min, max) for numbers, or list of choices
ALLOWED_OPS = {
    "faster_hook": {
        "params": {"factor": (float, 1.0, 2.0)},
        "approval": False,
        "human": "Tighten the opening (about {factor}x faster pacing)",
    },
    "remove_segment": {
        "params": {"start": (float, 0.0, 36000.0),
                   "end": (float, 0.0, 36000.0)},
        "approval": True,   # deletes speech
        "human": "Remove the section from {start}s to {end}s",
    },
    "fewer_punchins": {
        "params": {}, "approval": False,
        "human": "Use fewer punch-ins",
    },
    "more_punchins": {
        "params": {}, "approval": False,
        "human": "Use more punch-ins",
    },
    "caption_scale": {
        "params": {"scale": (float, 0.03, 0.09)},
        "approval": False,
        "human": "Set caption size to {scale} of frame height",
    },
    "broll_density": {
        "params": {"level": ["less", "normal", "more"]},
        "approval": False,
        "human": "Use {level} b-roll",
    },
    "cinematic_grade": {
        "params": {}, "approval": False,
        "human": "Apply a more cinematic look",
    },
    "retarget_duration": {
        "params": {"seconds": (float, 10.0, 3600.0)},
        "approval": True,   # changes which speech survives
        "human": "Re-cut the video to about {seconds} seconds",
    },
    "split_into_clips": {
        "params": {"count": (int, 1, 10)},
        "approval": True,   # produces new deliverables
        "human": "Create {count} clips from this video",
    },
    "acquire_asset": {
        "params": {"query": (str, 1, 120),
                   "kind": ["broll", "music", "sfx", "image"]},
        "approval": True,   # licensing surface: always show first
        "human": "Find licensed {kind}: \"{query}\"",
    },
}


def validate_proposal(raw: dict) -> tuple[dict, bool, list[str]]:
    """Deterministically validate a DeepSeek proposal.

    Returns (clean_proposal, needs_approval, errors). A proposal with any
    error is unusable; the caller must not partially apply it.
    """
    errors: list[str] = []
    ops_in = raw.get("operations")
    if not isinstance(ops_in, list) or not ops_in:
        return {}, False, ["proposal has no operations list"]
    if len(ops_in) > 8:
        return {}, False, ["too many operations in one proposal (max 8)"]
    clean, needs_approval = [], False
    for i, op in enumerate(ops_in):
        if not isinstance(op, dict) or "op" not in op:
            errors.append(f"operation {i} is malformed")
            continue
        name = op["op"]
        spec = ALLOWED_OPS.get(name)
        if not spec:
            errors.append(f"operation '{name}' is not in the contract")
            continue
        params = {}
        ok = True
        for pname, pspec in spec["params"].items():
            val = op.get(pname)
            if isinstance(pspec, list):
                if val not in pspec:
                    errors.append(f"{name}.{pname} must be one of {pspec}")
                    ok = False
            else:
                ptype, lo, hi = pspec
                try:
                    val = ptype(val)
                except (TypeError, ValueError):
                    errors.append(f"{name}.{pname} missing or wrong type")
                    ok = False
                    continue
                if ptype in (int, float) and not (lo <= val <= hi):
                    errors.append(f"{name}.{pname}={val} outside "
                                  f"[{lo}, {hi}]")
                    ok = False
                if ptype is str and not (lo <= len(val) <= hi):
                    errors.append(f"{name}.{pname} length outside bounds")
                    ok = False
            params[pname] = val
        if not ok:
            continue
        if name == "remove_segment" and params["end"] <= params["start"]:
            errors.append("remove_segment end must be after start")
            continue
        human = spec["human"].format(**params) if params else spec["human"]
        clean.append({"op": name, **params, "human": human})
        needs_approval = needs_approval or spec["approval"]
    if errors:
        return {}, False, errors
    return {"operations": clean,
            "summary": raw.get("summary", "")[:400]}, needs_approval, []


PROPOSAL_PROMPT = """You are the edit planner for a verified video editor.
The user asked: {request!r}

Video context: type={ptype}, duration={duration}s.
Transcript excerpt: {transcript}

Respond with ONLY a JSON object:
{{"summary": "<one sentence of what you will change>",
  "operations": [{{"op": "<name>", ...params}}]}}

Allowed operations and params (use ONLY these):
{contract}

Rules: max 8 operations. Prefer the smallest change that satisfies the
request. If the request cannot be expressed with these operations, return
{{"summary": "cannot", "operations": []}}."""
