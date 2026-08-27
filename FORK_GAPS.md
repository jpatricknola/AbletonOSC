# Fork gaps — LOM members Live exposes that this fork does not

_Living list. A **fork gap** is a capability present in the installed Live
Object Model but with no OSC address in this repository. It is neither a
Live limit nor a Seshat tool-layer gap, and it must never be planned as UI
scripting — closing one is a handler here (one commit in this repo, one
submodule pin bump in Seshat, `mix abletonosc.install`, Live restart),
documented in Seshat's `docs/abletonosc-api-docs.md` and tripwired by
Seshat's `vendored_addresses_test`._

## How to use this file

- **Add an entry** whenever research, a plan, or a review finds a LOM
  member the fork lacks — Seshat's `/evaluate` skill (§2.3) produces these;
  so does reading Live's shipped Python for anything. Verify against the
  installed `_MxDCore/LomTypes.pyc` (string dump) or the Cycling '74 apiref
  before recording; note which and when.
- **Remove an entry** when the fork gains the address. Don't leave it
  marked done — the address docs are the record of what exists.
- **Nothing here is prioritised.** A gap enters Seshat's `docs/ROADMAP.md`
  only when a feature needs it; until then it is inventory. Say in the
  entry what would consume it, so a plan can find the prerequisite.
- **Object-valued members** (`Clip.groove`, `Song.cue_points`, `slices`)
  are the usual reason a member was skipped: the generic `properties_r/rw`
  machinery serialises scalars only. Closing such a gap means a
  hand-written handler that takes or returns an index, a name, or a
  flattened tuple — say which in the entry.
- Seshat's `docs/evaluating/lom-to-fork-gap-audit.md` is the full
  object-by-object audit taken 2026-07-31 against Live 12.4.3. It is a
  snapshot, not this list; entries below cite it where it already named the
  gap.

## Evidence tiers

State which one each entry rests on; only the last means "works."

1. **Name present** — `strings` on `LomTypes.pyc` matched. Proves the
   member exists somewhere in the LOM type table, not its owner class or
   signature (`export_to_clip_slot` matched this way and belonged to
   Looper).
2. **Documented** — apiref page or Ableton release notes name the owner,
   access mode and version.
3. **Called from a Remote Script** — this fork's own code, Live's shipped
   Python, or a probe handler run through the rig in Seshat's
   `.claude/docs/ableton-osc-reference.md` ("Measuring the Live API without
   building the feature first"), with the answer read out of `Log.txt`.

Every entry below as of 2026-08-27 is tier 1 or 2. None has been run.

## Open gaps

### `Clip.groove` — assign a Groove Pool groove to a clip

- **LOM:** `Clip.groove` get/set/observe (Live 11+); `Clip.has_groove`;
  `Song.groove_pool.grooves` (list, observable); `Groove.base`,
  `timing_amount`, `random_amount`, `velocity_amount`,
  `quantization_amount`. Tier 2 (apiref Clip, GroovePool); names verified in
  12.4.3 `LomTypes.pyc`, 2026-08-27.
- **Fork today:** `abletonosc/clip.py` lists `has_groove` and comments
  `groove` out (`## if other than None, says "Error handling OSC message:
  Infered arg_value type is not supported"`) — the object can't ride the
  generic setter. `song.py` exposes only the scalar `groove_amount`.
- **Shape to build:** `/live/song/get/groove_pool` → indexed names and
  amounts; `/live/clip/set/groove <track> <clip> <pool_index | -1>`;
  `/live/clip/get/groove` → index or -1. Whether a `.agr` browser item can
  be loaded *into the pool* through `browser.load_item` is unmeasured and
  decides whether ~3,000 shipped grooves are reachable without the user
  dragging one in.
- **Consumers:** Seshat's generation epic — feel transfer and
  existing-context timing (`docs/evaluating/generative features/live-native-options.md`
  §2.5); makes `set_groove_amount` meaningful on plain MIDI (Seshat's
  CLAUDE.md currently says it can't assign — that sentence goes when this
  closes).
- **Also in:** July audit, "Groove Pool enumeration and clip assignment",
  medium–low.

### `Song.cue_points` — Arrangement locators

- **LOM:** `Song.cue_points` (list, observable), `CuePoint.name`, `.time`,
  `.jump()`; `Song.set_or_delete_cue`, `jump_to_next_cue`,
  `jump_to_prev_cue`, `can_jump_to_next_cue`/`_prev_cue`,
  `is_cue_point_selected`. Tier 2 (apiref Song); names verified 2026-08-27.
- **Fork today:** nothing under `/live/song/` for cue points.
- **Shape to build:** `/live/song/get/cue_points` → flattened
  `(name, time)*` tuples; `/live/song/start_listen/cue_points`; the three
  jump/set methods are plain method entries.
- **Consumers:** live-improv section scheduling
  (`docs/evaluating/generative features/live-improv-exploration.md` §9 said
  "not in the fork" and used scene names instead); arrangement-aware
  anything.
- **Also in:** July audit, `Song` state/guards list.

### `DrumChain.in_note` and rack chain insertion — read the Drum Rack pad map

- **LOM:** `DrumChain.in_note` get/set/observe (12.3; -1 = All Notes),
  `DrumChain.out_note`, `RackDevice.insert_chain(index)` (12.3),
  `Track.insert_device` / `Chain.insert_device` (12.3),
  `SimplerDevice.replace_sample(path)` (12.2). Tier 2 (Live 12.2/12.3
  release notes); names verified 2026-08-27.
- **Fork today:** device addresses stop at top-level regular-track
  devices; no chain or drum-pad traversal at all.
- **Shape to build:** `/live/device/get/drum_pads <track> <device>` →
  `(chain_index, in_note, name)*`; `insert_chain` and `in_note` setters
  for building a kit programmatically.
- **Consumers:** one-Drum-Rack output for generated drums
  (`docs/evaluating/generative features/midi-generation-options.md` § Open
  work listed the pad map as unreadable — it is not); per-lane pitch
  normalisation.

### `SimplerDevice` slicing — slice a loaded sample from the bridge

- **LOM:** `SimplerDevice.playback_mode` (2 = Slicing),
  `slicing_playback_mode`, `slices` (list of times), `insert_slice`,
  `remove_slice`, `clear_slices`, `reset_slices`, `move_slice`,
  `selected_slice`, `sample`, `replace_sample`. **Tier 1 for the slice
  members** — present in 12.4.3 `LomTypes.pyc`; the apiref page lists only
  `playback_mode`, `slicing_playback_mode` and `sample`. Verify each
  member's owner and signature in Live's shipped Python before building.
- **Fork today:** no Simpler-specific addresses.
- **Shape to build:** `replace_sample`, `playback_mode` setter, `slices`
  getter; Seshat would write the trigger clip itself from the slice times
  via `write_midi_notes`, standing in for Live's UI-only *Slice to New MIDI
  Track*.
- **Consumers:** "generate audio, keep it editable" output shape
  (`docs/evaluating/generative features/live-native-options.md` §2.4).

### `Application` dialog members — see the July audit

- `open_dialog_count`, `current_dialog_message`,
  `current_dialog_button_count`, `press_current_dialog_button`. Tier 2.
  Recorded in Seshat's `docs/evaluating/ui-scripting-options.md` and the
  July audit; listed here so the inventory is in one place. Consumer: any
  UI-only command driven over AX that can raise a dialog (Stem
  Separation's mode chooser).

## Closed

_None yet. Move entries here only in the same commit that lands the
address, then delete them at the next tidy — the address docs are the
permanent record._
