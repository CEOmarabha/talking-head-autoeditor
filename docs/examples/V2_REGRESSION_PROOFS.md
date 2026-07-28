# v2 regression proofs

These are the small cases behind the v2 release claims. Each one names the
input that used to pass and the result required now.

## 1. A wrong offset cannot certify itself

Input:

```text
RAW certification: 0ms
requested correction: -200ms
```

Old behavior:

```text
master compared with corrected cut
measured: -200ms
intended: -200ms
PASS
```

Version 2:

```text
requested -200ms does not match certified 0ms
FAIL before source probes
```

The sidecar also stores the RAW SHA-256. A replacement file with the same name
fails certification.

Covered by:

```text
test_gate_rejects_applied_value_that_is_not_certified
test_uncertified_offset_is_rejected_before_render
test_calibration_is_bound_to_raw_hash
```

## 2. Decimal cut boundaries cannot move a frame

Input:

```json
[
  {"s": 0.067, "e": 0.133},
  {"s": 0.267, "e": 0.333}
]
```

These two cut windows leave three kept ranges. Serializing snapped seconds to
three decimal places used to change frame admission and produced 65ms of
audio/video mismatch.

Version 2 builds video trims from integer frame indices and audio trims from
the same indices times 1,600 samples. The encoded stream-duration difference
must stay at or below 2ms.

Covered by:

```text
test_integer_cut_graph_keeps_stream_durations_aligned
```

## 3. A real quote cannot carry an invented diagram

Spoken input:

```text
This city story explains architecture with a concrete lesson for everyone
watching the example today.
```

Rejected plan:

```json
{
  "anchor_quote": "This city story explains architecture with a concrete",
  "viz": {
    "template": "steps",
    "title": "THREE SIGNALS",
    "items": ["SUPERIORITY", "AUTONOMY", "CERTAINTY"]
  }
}
```

The anchor is real. The diagram copy is absent from nearby speech, so the plan
fails before asset rendering.

Covered by:

```text
test_fabricated_visual_copy_cannot_hide_behind_a_real_anchor
test_fabricated_stat_number_cannot_reach_the_renderer
```

## 4. A model cannot excuse a removed sentence

Script:

```text
Alpha opening sentence has six clear words.
Critical missing sentence contains the actual promise.
Omega closing sentence has six clear words.
```

Delivered transcript:

```text
Alpha opening sentence has six clear words.
Omega closing sentence has six clear words.
```

Splice ledger:

```text
1.8s to 2.4s removed across the missing sentence
```

Even a semantic response of `FINE` cannot clear the loss. The result is
mechanically damaged and delivery stays blocked.

Covered by:

```text
test_whole_sentence_removed_by_large_splice_cannot_be_judged_fine
```

## 5. A cache filename is not media evidence

Inputs covered by the cache tests:

- metadata says a cached MP4 has enough duration, but the file is truncated;
- the file decodes, but its orientation is wrong for the requested event;
- one local catalog row has invalid duration before a later valid row;
- a b-roll asset is shorter than the event it is meant to cover;
- a rejected family row points at an otherwise valid local file.

Version 2 decodes the candidate, checks geometry and duration, and keeps
downloads temporary until validation succeeds. Invalid files are removed
before a network retry.

Covered by:

```text
test_invalid_cached_visual_is_removed_before_network_retry
test_valid_metadata_cannot_hide_a_truncated_cached_visual
test_one_bad_catalog_duration_does_not_hide_later_clips
test_short_broll_asset_cannot_freeze_through_planned_window
test_rejected_or_unclassified_catalog_rows_never_reenter
```

## 6. A correct crop with different audio fails

The test builds two three-second sources with FFmpeg:

- a 320x180 landscape source exported as a 1080x1920 center crop;
- a 180x320 portrait source exported inside a 1920x1080 pillarbox.

Both geometry paths pass against their native master. The test then copies the
valid cropped video and replaces its audio with a 1,200 Hz tone. The frames
still match. The decoded audio hash does not, so delivery fails.

Covered by:

```text
test_aspect_derivatives_bind_both_geometry_paths_and_audio
```

## Run them

```bash
make test
```

The suite creates temporary media, destroys it after each case, and never
needs a DeepSeek key. The separate
[`scripts/smoke_deepseek_v4.py`](../../scripts/smoke_deepseek_v4.py) fixture
covers the real V4 Pro transport and critic loop.
