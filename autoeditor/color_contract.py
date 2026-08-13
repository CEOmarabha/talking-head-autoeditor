"""Closed source-color validation and deterministic SDR delivery conversion.

This module is intentionally pure: it accepts already-probed FFprobe facts,
returns one explicit FFmpeg filter, and never invokes a process.  Delivery
metadata alone cannot transform pixel values, so every caller must place the
returned ``colorspace`` filter on each source branch before concat/composite.
"""
from __future__ import annotations

import re


SDR_COLOR_SPACES = frozenset({"bt709", "bt470bg", "smpte170m"})
SDR_COLOR_TRANSFERS = frozenset({
    "bt709", "bt470bg", "smpte170m", "gamma22", "gamma28",
})
SDR_COLOR_PRIMARIES = frozenset({
    "bt709", "bt470bg", "smpte170m", "smpte240m",
})
COLOR_RANGES = frozenset({"tv", "pc"})
LEGACY_SDR_PIXEL_FORMATS = frozenset({
    "yuv420p", "yuv422p", "yuv444p",
})
LEGACY_MJPEG_PIXEL_FORMATS = frozenset({
    "yuvj420p", "yuvj422p", "yuvj444p",
})
BT601_FAMILY_COLOR_SPACES = frozenset({"bt470bg", "smpte170m"})
UNDECLARED_COLOR_VALUES = frozenset({"unknown", "unspecified"})

# Floyd-Steinberg dithering carries error state between pixels.  Bind the
# relevant FFmpeg filter pool to one worker anywhere the production conversion
# below is executed so identical inputs cannot be partitioned differently.
DETERMINISTIC_COLOR_FILTER_ARGS = ("-filter_threads", "1")
DETERMINISTIC_COLOR_COMPLEX_FILTER_ARGS = ("-filter_complex_threads", "1")

_TECHNICAL_TOKEN = re.compile(r"^[a-z0-9_]{1,32}$", re.ASCII)


class ColorContractError(ValueError):
    """The probed source color cannot be converted without guessing."""


def _technical_token(value: object, label: str) -> str:
    if type(value) is not str or _TECHNICAL_TOKEN.fullmatch(value) is None:
        raise ColorContractError(
            f"{label} must be a lowercase FFprobe technical token"
        )
    return value


def validate_source_color(
    value: object, label: str = "source video color",
) -> dict[str, str]:
    """Validate and resolve one non-HDR source-color declaration.

    The general inference is an all-untagged, 8-bit planar-YUV legacy source,
    treated as BT.709 limited range. A second narrow compatibility rule covers
    full-range legacy MJPEG whose YUVJ pixel format and BT.601-family matrix
    are declared but transfer and primaries are absent; those two values are
    inferred from the matrix. Every other partial declaration, BT.2020/HDR,
    high-bit-depth, or ambiguous pixel format fails closed.
    """
    if type(value) is not dict:
        raise ColorContractError(f"{label} must be an object")
    codec_name = _technical_token(
        value.get("codec_name"), f"{label}.codec_name"
    )
    pixel_format = _technical_token(value.get("pix_fmt"), f"{label}.pix_fmt")
    color_range = _technical_token(
        value.get("color_range"), f"{label}.color_range"
    )
    space = _technical_token(value.get("color_space"), f"{label}.color_space")
    transfer = _technical_token(
        value.get("color_transfer"), f"{label}.color_transfer"
    )
    primaries = _technical_token(
        value.get("color_primaries"), f"{label}.color_primaries"
    )
    inferred_untagged = (
        all(item in UNDECLARED_COLOR_VALUES
            for item in (space, transfer, primaries))
        and color_range in UNDECLARED_COLOR_VALUES.union({"tv"})
        and pixel_format in LEGACY_SDR_PIXEL_FORMATS
    )
    inferred_mjpeg = (
        codec_name == "mjpeg"
        and pixel_format in LEGACY_MJPEG_PIXEL_FORMATS
        and color_range == "pc"
        and space in BT601_FAMILY_COLOR_SPACES
        and transfer in UNDECLARED_COLOR_VALUES
        and primaries in UNDECLARED_COLOR_VALUES
    )
    if inferred_untagged:
        effective_space = effective_transfer = effective_primaries = "bt709"
        effective_range = "tv"
        mode = "inferred_legacy_untagged_sdr_bt709_tv"
    elif inferred_mjpeg:
        effective_space = effective_transfer = effective_primaries = space
        effective_range = "pc"
        mode = "inferred_legacy_mjpeg_bt601_full_range"
    else:
        if space not in SDR_COLOR_SPACES:
            raise ColorContractError(
                f"{label}.color_space is unsupported, unknown, or HDR"
            )
        if transfer not in SDR_COLOR_TRANSFERS:
            raise ColorContractError(
                f"{label}.color_transfer is unsupported, unknown, or HDR"
            )
        if primaries not in SDR_COLOR_PRIMARIES:
            raise ColorContractError(
                f"{label}.color_primaries is unsupported, unknown, or HDR"
            )
        if color_range not in COLOR_RANGES:
            raise ColorContractError(
                f"{label}.color_range is unsupported or unknown"
            )
        if pixel_format not in LEGACY_SDR_PIXEL_FORMATS:
            raise ColorContractError(
                f"{label}.pix_fmt must be supported 8-bit planar YUV"
            )
        effective_space = space
        effective_transfer = transfer
        effective_primaries = primaries
        effective_range = color_range
        mode = "declared_sdr_to_bt709_tv"
    return {
        "codec_name": codec_name,
        "pix_fmt": pixel_format,
        "color_range": color_range,
        "color_space": space,
        "color_transfer": transfer,
        "color_primaries": primaries,
        "effective_range": effective_range,
        "effective_space": effective_space,
        "effective_transfer": effective_transfer,
        "effective_primaries": effective_primaries,
        "mode": mode,
    }


def source_color_conversion_filter(value: object) -> str:
    """Return a real pixel conversion from validated SDR into BT.709 TV."""
    color = validate_source_color(value)
    return (
        f"colorspace=ispace={color['effective_space']}:"
        f"itrc={color['effective_transfer']}:"
        f"iprimaries={color['effective_primaries']}:"
        f"irange={color['effective_range']}:"
        "all=bt709:range=tv:format=yuv420p:fast=0:dither=fsb"
    )


def source_color_normalization_mode(value: object) -> str:
    """Return the declared-versus-inferred decision for audit surfaces."""
    return validate_source_color(value)["mode"]
