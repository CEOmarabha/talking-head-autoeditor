"""Frozen entry point for the all-in-one local AutoEditor app.

The Electron shell supplies bundled runtime paths and optional provider keys
through the child environment. Video inputs and finished outputs stay on the
user's computer. The legacy polling mode remains only for older installations.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


MAX_LOCAL_REQUEST_BYTES = 1_000_000
MAX_LOCAL_SCRIPT_CHARS = 200_000
MAX_CHAT_TEXT_CHARS = 4_000
LOCAL_PROJECT_TYPES = frozenset({
    "short", "long", "commercial", "podcast", "course", "custom",
})


def _emit_local(payload: dict) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")),
          flush=True)


def _read_local_request() -> dict:
    raw = sys.stdin.buffer.read(MAX_LOCAL_REQUEST_BYTES + 1)
    if not raw or len(raw) > MAX_LOCAL_REQUEST_BYTES:
        raise ValueError("local request is empty or too large")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("local request is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("local request must be an object")
    return value


def _bounded_text(value: object, name: str, maximum: int,
                  *, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError(f"{name} must be text")
    value = value.strip()
    if required and not value:
        raise ValueError(f"{name} is required")
    if len(value) > maximum:
        raise ValueError(f"{name} is too long")
    return value


def _project_type(value: object) -> str:
    if not isinstance(value, str) or value not in LOCAL_PROJECT_TYPES:
        raise ValueError("project type is not supported")
    return value


def _local_render_request(value: dict) -> dict:
    allowed = {"inputs", "outputDir", "projectType", "script", "proposal"}
    extra = sorted(set(value) - allowed)
    if extra:
        raise ValueError("local render request has unsupported fields")
    raw_inputs = value.get("inputs")
    if not isinstance(raw_inputs, list) or not 1 <= len(raw_inputs) <= 20:
        raise ValueError("select between 1 and 20 videos")
    inputs: list[Path] = []
    seen: set[str] = set()
    for item in raw_inputs:
        if not isinstance(item, str) or not item or "\x00" in item:
            raise ValueError("video path is invalid")
        path = Path(item).expanduser().resolve()
        key = os.path.normcase(str(path))
        if key in seen:
            raise ValueError("the same video was selected more than once")
        if not path.is_file():
            raise ValueError("a selected video is no longer available")
        seen.add(key)
        inputs.append(path)
    raw_output = value.get("outputDir")
    if not isinstance(raw_output, str) or not raw_output or "\x00" in raw_output:
        raise ValueError("choose an output folder")
    output = Path(raw_output).expanduser().resolve()
    if not output.is_dir():
        raise ValueError("the output folder is no longer available")
    proposal = value.get("proposal")
    if proposal is not None and not isinstance(proposal, dict):
        raise ValueError("the DeepSeek change proposal is invalid")
    return {
        "inputs": inputs,
        "output": output,
        "project_type": _project_type(value.get("projectType")),
        "script": _bounded_text(
            value.get("script"), "script", MAX_LOCAL_SCRIPT_CHARS),
        "proposal": proposal,
    }


def _local_chat_request(value: dict) -> dict:
    allowed = {"text", "projectType", "transcript", "history"}
    if set(value) - allowed:
        raise ValueError("local chat request has unsupported fields")
    raw_history = value.get("history") or []
    if not isinstance(raw_history, list) or len(raw_history) > 12:
        raise ValueError("chat history is invalid")
    history: list[dict[str, str]] = []
    total = 0
    for item in raw_history:
        if not isinstance(item, dict) or set(item) != {"role", "content"}:
            raise ValueError("chat history is invalid")
        role = item.get("role")
        if role not in {"user", "assistant"}:
            raise ValueError("chat history role is invalid")
        content = _bounded_text(item.get("content"), "chat message", 2_000,
                                required=True)
        total += len(content)
        if total > 12_000:
            raise ValueError("chat history is too long")
        history.append({"role": role, "content": content})
    return {
        "text": _bounded_text(value.get("text"), "message",
                              MAX_CHAT_TEXT_CHARS, required=True),
        "project_type": _project_type(value.get("projectType")),
        "transcript": _bounded_text(
            value.get("transcript"), "transcript", 20_000),
        "history": history,
    }


def _local_engine_command(args: list[str]) -> list[str]:
    engine = os.environ.get("AUTOEDITOR_ENGINE", "").strip()
    if not engine or not Path(engine).is_file():
        raise RuntimeError("the built-in editing engine is missing")
    return [engine, *args]


def _run_local_engine(args: list[str]) -> tuple[int, dict | None]:
    install_root = os.environ.get("AUTOEDITOR_INSTALL_ROOT", "")
    cwd = Path(install_root).resolve() if install_root else Path.cwd()
    env = {
        **os.environ,
        "AUTOEDITOR_PACKAGED": "1",
        "AUTOEDITOR_PROGRESS_JSON": "1",
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    proc = subprocess.Popen(
        _local_engine_command(args), cwd=cwd, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    result = None
    assert proc.stdout is not None
    for raw_line in proc.stdout:
        line = raw_line.rstrip()
        if not line:
            continue
        event = None
        if line.startswith("{"):
            try:
                candidate = json.loads(line)
                if isinstance(candidate, dict):
                    event = candidate
            except ValueError:
                event = None
        if event and event.get("event") == "result":
            result = event
        elif event:
            _emit_local({
                "event": "local-progress",
                "stage": str(event.get("event") or "working")[:80],
            })
        else:
            _emit_local({"event": "local-progress", "line": line[:300]})
    return proc.wait(), result


def _join_local_inputs(inputs: list[Path], project_type: str,
                       work: Path) -> Path:
    if len(inputs) == 1:
        return inputs[0]
    ffmpeg = os.environ.get("AUTOEDITOR_FFMPEG", "").strip()
    if not ffmpeg or not Path(ffmpeg).is_file():
        raise RuntimeError("the built-in FFmpeg is missing")
    portrait = project_type in {"short", "commercial"}
    width, height = (1080, 1920) if portrait else (1920, 1080)
    arguments: list[str] = []
    filters: list[str] = []
    labels: list[str] = []
    for index, path in enumerate(inputs):
        arguments.extend(["-i", str(path)])
        filters.append(
            f"[{index}:v]scale={width}:{height}:"
            "force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
            f"setsar=1,fps=30[v{index}]"
        )
        filters.append(f"[{index}:a]aresample=48000[a{index}]")
        labels.append(f"[v{index}][a{index}]")
    filters.append(
        "".join(labels) + f"concat=n={len(inputs)}:v=1:a=1[v][a]")
    output = work / "joined-input.mp4"
    completed = subprocess.run(
        [ffmpeg, "-y", *arguments, "-filter_complex", ";".join(filters),
         "-map", "[v]", "-map", "[a]", "-c:v", "libx264",
         "-preset", "fast", "-crf", "18", "-c:a", "aac", str(output)],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
    )
    if completed.returncode != 0 or not output.is_file():
        raise RuntimeError("the selected videos could not be joined")
    return output


def local_render() -> int:
    from webapp.render_worker.project_types import (
        engine_args, revision_engine_args,
    )

    request = _local_render_request(_read_local_request())
    work_root = Path(os.environ.get("WORK_DIR") or tempfile.gettempdir())
    work_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="local-edit-", dir=work_root) as raw:
        work = Path(raw)
        source = _join_local_inputs(
            request["inputs"], request["project_type"], work)
        script = request["script"]
        if not script:
            transcript_dir = work / "transcript"
            code, _ = _run_local_engine([
                str(source), "--transcribe-only", "--out", str(transcript_dir),
            ])
            transcript_file = transcript_dir / "TRANSCRIPT.txt"
            if code != 0 or not transcript_file.is_file():
                raise RuntimeError("the built-in transcription failed")
            script = transcript_file.read_text(encoding="utf-8").strip()
        script_file = work / "script.txt"
        script_file.write_text(script or " ", encoding="utf-8")
        if request["proposal"] is None:
            mapped = engine_args(request["project_type"], None)
        else:
            mapped = revision_engine_args(
                request["project_type"], None, request["proposal"])
        args = [
            str(source), "--script", str(script_file),
            "--out", str(request["output"]), *mapped,
        ]
        deepseek = bool(os.environ.get("DEEPSEEK_API_KEY", "").strip())
        if not deepseek and "--no-premium" not in args:
            args.append("--no-llm")
        code, result = _run_local_engine(args)
        if (code != 0 or result is None) and deepseek and "--no-premium" not in args:
            _emit_local({
                "event": "local-progress",
                "line": "DeepSeek was unavailable. Using the deterministic editor.",
            })
            code, result = _run_local_engine([*args, "--no-llm"])
        if code != 0 or result is None:
            raise RuntimeError("the editing engine did not finish")
        if result.get("qa_pass") is not True:
            raise RuntimeError("the edit did not pass its built-in quality checks")
        outputs = result.get("outputs")
        if not isinstance(outputs, dict) or not outputs:
            raise RuntimeError("the editing engine returned no finished video")
        finished: dict[str, str] = {}
        output_root = request["output"]
        for name, value in outputs.items():
            path = Path(str(value)).resolve()
            try:
                path.relative_to(output_root)
            except ValueError as exc:
                raise RuntimeError("the output escaped the selected folder") from exc
            if not path.is_file():
                raise RuntimeError("the finished video is missing")
            finished[str(name)] = str(path)
        _emit_local({
            "event": "local-result",
            "outputs": finished,
            "output": next(iter(finished.values())),
            "qaReport": str(result.get("qa_report") or ""),
            "projectType": request["project_type"],
            "transcript": script[:20_000],
        })
    return 0


def local_chat() -> int:
    if not os.environ.get("DEEPSEEK_API_KEY", "").strip():
        raise RuntimeError("add a DeepSeek API key in Accounts first")
    request = _local_chat_request(_read_local_request())
    from autoeditor import providers
    from webapp.render_worker.project_types import (
        ALLOWED_OPS, PROPOSAL_PROMPT, validate_proposal,
    )

    contract = json.dumps({
        name: {key: list(values) for key, values in spec["params"].items()}
        for name, spec in ALLOWED_OPS.items()
    }, sort_keys=True)
    conversation = "\n".join(
        f"{item['role']}: {item['content']}" for item in request["history"]
    )
    current_request = request["text"]
    if conversation:
        current_request = (
            f"Recent conversation:\n{conversation}\n"
            f"Current request: {current_request}"
        )
    prompt = PROPOSAL_PROMPT.format(
        request=current_request,
        ptype=request["project_type"],
        duration="unknown",
        transcript=request["transcript"][:1_200],
        contract=contract,
    )
    raw = providers.llm_json(prompt, timeout=120, provider="deepseek")
    clean, needs_approval, errors = validate_proposal(raw or {})
    if errors or not clean.get("operations"):
        _emit_local({
            "event": "local-chat",
            "message": "I couldn't map that safely. Ask me to change pacing, aspect ratio, captions, visual treatment, or edit profile.",
            "proposal": {"operations": []},
            "canApply": False,
        })
        return 0
    _emit_local({
        "event": "local-chat",
        "message": clean.get("summary") or "Here is what I can change.",
        "proposal": clean,
        "canApply": not needs_approval,
    })
    return 0


def revision_contract_check() -> bool:
    """Prove the frozen daemon contains the executable revision contract."""
    from webapp.render_worker.project_types import (
        ALLOWED_OPS,
        GENERIC_PROFILE_IDS,
        PROJECT_TYPES,
        revision_engine_args,
    )

    expected_ops = {
        "set_edit_style",
        "set_aspect_ratio",
        "set_caption_mode",
        "set_visual_mode",
        "set_edit_profile",
    }
    expected_profiles = (
        "generic_short",
        "generic_long",
        "generic_commercial",
        "generic_podcast",
        "generic_course",
        "generic_custom",
    )
    supported_projects = {
        name for name, contract in PROJECT_TYPES.items()
        if contract.get("supported")
    }
    mapped = revision_engine_args("custom", None, {
        "operations": [
            {"op": "set_edit_style", "style": "short"},
            {"op": "set_aspect_ratio", "aspect": "9x16"},
            {"op": "set_caption_mode", "mode": "sidecar"},
            {"op": "set_visual_mode", "mode": "baseline"},
            {"op": "set_edit_profile", "profile_id": "generic_commercial"},
        ],
    })
    return (
        set(ALLOWED_OPS) == expected_ops
        and tuple(GENERIC_PROFILE_IDS) == expected_profiles
        and supported_projects == {
            "short", "long", "commercial", "podcast", "course", "custom",
        }
        and PROJECT_TYPES.get("clips", {}).get("supported") is False
        and mapped == [
            "--style", "short", "--aspects", "9x16",
            "--profile", "generic_commercial", "--no-burn", "--no-premium",
        ]
    )


def smoke_test() -> int:
    required = {
        "engine": os.environ.get("AUTOEDITOR_ENGINE", ""),
        "ffmpeg": os.environ.get("AUTOEDITOR_FFMPEG", ""),
        "ffprobe": os.environ.get("AUTOEDITOR_FFPROBE", ""),
        "small_model": os.environ.get("AUTOEDITOR_WHISPER_SMALL", ""),
        "medium_model": os.environ.get("AUTOEDITOR_WHISPER_MEDIUM", ""),
        "profiles": os.environ.get("AUTOEDITOR_PROFILES_DIR", ""),
        "fonts": os.environ.get("AUTOEDITOR_BUNDLED_FONTS", ""),
        "ca_bundle": os.environ.get("SSL_CERT_FILE", ""),
        "node": os.environ.get("AUTOEDITOR_NODE", ""),
        "hyperframes_cli": os.environ.get("AUTOEDITOR_HYPERFRAMES_CLI", ""),
        "hyperframes_project": os.environ.get(
            "AUTOEDITOR_HYPERFRAMES_PROJECT", ""),
        "remotion_cli": os.environ.get("AUTOEDITOR_REMOTION_CLI", ""),
        "remotion_project": os.environ.get("AUTOEDITOR_REMOTION_PROJECT", ""),
        "browser": os.environ.get("AUTOEDITOR_BROWSER", ""),
    }
    checks = {name: bool(value) and Path(value).exists()
              for name, value in required.items()}
    checks["utf8_mode"] = (
        not getattr(sys, "frozen", False) or sys.flags.utf8_mode == 1
    )
    try:
        from autoeditor import asr

        checks["pyav_not_bundled"] = asr.pyav_payload_absent()
    except Exception:
        checks["pyav_not_bundled"] = False
    try:
        checks["typed_deepseek_revision_contract"] = revision_contract_check()
    except Exception:
        checks["typed_deepseek_revision_contract"] = False
    print(json.dumps({"event": "helper-daemon-smoke", "checks": checks}))
    return 0 if all(checks.values()) else 1


def creative_smoke_test() -> int:
    """Render tiny real assets through the installed creative stack."""
    from autoeditor import premium

    with tempfile.TemporaryDirectory(prefix="autoeditor-creative-smoke-") as raw:
        work = Path(raw)
        premium.BROLL_CACHE = work
        hf_ok = premium._hf_render_graphic(
            "keyword", {"text": "READY"}, 1.2, 320, 568,
            work / "hyperframes-sequence",
        )
        remotion_required = os.environ.get("AUTOEDITOR_REQUIRE_REMOTION") == "1"
        remotion_ok = True
        if remotion_required:
            remotion_ok = bool(premium._remotion_viz(
                {"template": "flow", "title": "READY", "items": ["ONE", "TWO"]},
                2.5, 320, 568,
            ))
        checks = {"hyperframes_render": hf_ok, "remotion_render": remotion_ok}
        print(json.dumps({"event": "helper-creative-smoke", "checks": checks}))
        return 0 if all(checks.values()) else 1


def main() -> None:
    if len(sys.argv) == 2 and sys.argv[1] in {"--local-render", "--local-chat"}:
        try:
            code = local_render() if sys.argv[1] == "--local-render" else local_chat()
        except Exception as exc:
            _emit_local({
                "event": "local-error",
                "error": str(exc)[:500] or type(exc).__name__,
            })
            raise SystemExit(1) from None
        raise SystemExit(code)
    if os.environ.get("AUTOEDITOR_HELPER_SMOKE_TEST") == "1":
        raise SystemExit(smoke_test())
    if os.environ.get("AUTOEDITOR_CREATIVE_SMOKE_TEST") == "1":
        raise SystemExit(creative_smoke_test())
    from webapp.render_worker.render_worker import main as run
    run()


if __name__ == "__main__":
    main()
