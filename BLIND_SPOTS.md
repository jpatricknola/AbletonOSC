# Blind spots — what the gap measurement cannot see

_Companion to [FORK_GAPS.md](FORK_GAPS.md). That file is a diff: what the
installed Live Object Model has, minus what this fork addresses. A diff is
only as good as its left-hand side, and the left-hand side is built by
`abletonosc/introspection.py` walking Live and `tools/lom_gaps.py` rendering
the result. This file records the surfaces that pipeline **structurally
cannot report**, so that absence from FORK_GAPS.md is never again read as
absence from Live._

**The rule this file exists to state:** FORK_GAPS.md is authoritative for
the classes it reports and silent — not negative — everywhere else. Three
categories of Live surface can never appear in it, no matter how much of
Live they carry. Until the fixes below land, "it is not in FORK_GAPS.md" is
not evidence of anything.

## Status

| | state |
|---|---|
| 1 · report filter drops 90 of 134 walked entries | **fixed** — `tools/lom_gaps.py` renders them in *Walked but not diffed*, with the enum/vector exclusion written down as a named rule |
| 2 · walker drops module-level members | **fixed in code, unverified against Live** — `_visit_module` records them; proving it needs a fresh `dump_lom` from a running Live |
| 3 · everything outside the `Live` module is unwalked | **open** — no decision recorded |

The counts and tables below are the measurement that motivated the fixes, taken
before them. They are the record of what was hidden and for how long, not a
description of the tool's present behaviour: entries described here as
"never reported" are now reported. Item 2 is why the numbers are not simply
regenerated — the next dump taken inside Live will move them, and that dump is
the acceptance test for the walker fix.

**Measured 2026-08-30, Live 12.4.5 Suite, macOS, fork at `58ac7f0`,** from a
`/live/application/dump_lom` taken against a running Live: 545 KB,
134 classes walked, 786 fork addresses registered. Every claim below is read
out of that dump or out of the shipped Live binary's registration table.
Tier 1 evidence throughout — names, kinds and docstrings read from the
running Live. **Nothing here has been called.**

## Blind spot 1 — the report filter drops 90 of the 134 walked classes

`render()` in [tools/lom_gaps.py](tools/lom_gaps.py) builds its report from
two sources and no others:

```python
ordered = [c for c in CORE if c in classes]
others  = sorted(c for c in m4l if c in classes and c not in CORE)
```

`CORE` is the hand-written list at the top of that file; `m4l` is Max for
Live's `AVAILABLE_TYPE_PROPERTIES` table. A class that the walker found but
which appears in neither is dropped silently — no row, no count, no note
that it was seen and skipped.

| | classes |
|---|---|
| walked by `walk_live()` | 134 |
| reported in FORK_GAPS.md | **44** |
| never reported | **90** |

The 44 is the same 44 CLOSING_THE_GAPS.md sizes its buckets against. The
whole plan of attack is drawn on a third of the walked surface.

Most of the 90 is genuine noise and should stay out — but by a stated rule,
not by accident:

- **43 Boost.Python enums** (`Live.Song.Quantization`,
  `Live.Clip.WarpMode`, `Live.Conversions.AudioToMidiType`, …). Their
  members are `int` methods; the useful content is the value table, which
  belongs in `API.md` prose next to the address that takes it.
- **16 `*Vector` container shims** (`Live.Base.IntVector`,
  `Live.Clip.MidiNoteVector`, …). `append`/`extend` only.

That leaves **31 classes** that are neither, listed in full below.

### The clearest single case: a whole device class

Eighteen device classes are reported. Exactly one is not:

**`Live.CcControlDevice.CcControlDevice` — 41 members**, docstring "This
class represents a CcControl device." It carries the full inherited `Device`
surface (`class_name`, `parameters`, `is_active`, `latency_in_samples`,
`can_have_chains`, …) plus 25 `custom_*_target` members of its own, most of
them settable and observable, and a `resend` method.

It is dropped for one reason: it is absent from Max for Live's exposure
table. Every other device class this fork knows about happens to be in that
table, so the omission has never been visible. This is not a judgement that
CC Control is low value — no judgement was ever made.

### A gap the dump already answered while API.md called it unmeasured

`Live.Application.Variants` — docstring "Holds strings representing what
type of Live is running" — holds six string constants:

```
BETA 'Beta'   INTRO 'Intro'   LITE 'Lite'
STANDARD 'Standard'   SUITE 'Suite'   TRIAL 'Trial'
```

`API.md` ships `/live/application/get/variant` with **⚠️ The exact strings
Live returns are unmeasured**, and repeats it in the still-unmeasured list
further down. The set of strings Live defines has been sitting in every dump
taken. Two filters hid it: `Variants` is in neither `CORE` nor the M4L
table, and its members are `kind: "value"`, which `members()` does not
render even for a reported class.

Strictly, this does not close the ⚠️ — nothing has called `get_variant()`,
and Live defining these six is not proof it returns exactly one of them. It
moves the question from "unknown" to "here is the candidate set, confirm it
with one call."

### The 31 non-enum, non-vector classes never reported

Member counts exclude `canonical_parent`, `_live_ptr`, `View` and the
`add_*_listener`/`remove_*_listener` pairs, matching how the generated
inventory counts. `*` marks an observable member.

| class | members | what it carries |
|---|---|---|
| `Live.CcControlDevice.CcControlDevice` | 41 | A whole device class. See above |
| `Live.Licensing.PythonLicensingBridge` | 21 | Licensing internals. **Excluded on safety grounds** — see below |
| `Live.Application.ControlSurfaceProxy` | 12 | Raw MIDI in/out and control grabbing. See below |
| `Live.Clip.MidiNote` | 9 | `pitch`, `start_time`, `duration`, `velocity`, `mute`, `probability`, `release_velocity`, `velocity_deviation`, `note_id` — the object `get_notes_extended` returns |
| `Live.Licensing.UnlockStatus` | 7 | Authorization state. Excluded on safety grounds |
| `Live.Envelope.Envelope` | 6 | Automation read **and** write. See below |
| `Live.MidiMap.CCFeedbackRule` | 5 | `cc_no`, `cc_value_map`, `channel`, `delay_in_ms`, `enabled` |
| `Live.MidiMap.NoteFeedbackRule` | 5 | `note_no`, `vel_map`, `channel`, `delay_in_ms`, `enabled` |
| `Live.MidiMap.PitchBendFeedbackRule` | 4 | `value_pair_map`, `channel`, `delay_in_ms`, `enabled` |
| `Live.Song.BeatTime` | 4 | `bars`, `beats`, `sub_division`, `ticks` — a return shape |
| `Live.Song.SmptTime` | 4 | `hours`, `minutes`, `seconds`, `frames` — a return shape |
| `Live.Envelope.EnvelopeEventControlCoefficients` | 4 | `x1`, `y1`, `x2`, `y2` — automation curve handles |
| `Live.Base.Timer` | 4 | `start`, `stop`, `restart`, `running`. "A timer that will trigger a callback after a certain interval" |
| `Live.Envelope.EnvelopeEvent` | 3 | `time`, `value`, `control_coefficients` — one automation breakpoint |
| `Live.Track.RoutingType` | 3 | `display_name`, `category`, `attached_object` |
| `Live.TuningSystem.ReferencePitch` | 3 | `frequency`, `index_in_octave`, `octave` |
| `Live.Listener.ListenerHandle` | 3 | `disconnect`, `listener_func`, `listener_self` |
| `Live.Licensing.ProgressDialog` | 3 | Modal dialog control. Excluded on safety grounds |
| `Live.Licensing.StartupDialog…` | 3 | Modal dialog control. Excluded on safety grounds |
| `Live.Track.RoutingChannel` | 2 | `display_name`, `layout` |
| `Live.TuningSystem.PitchClassAndOctave` | 2 | `index_in_octave`, `octave` |
| `Live.Clip.WarpMarker` | 2 | `beat_time`, `sample_time` |
| `Live.CcControlDevice.CcControlDevice.View` | 1 | `is_collapsed`* |
| `Live.Base.Text` | 1 | `text`. "A translatable, immutable string" |
| `Live.Application.ControlDescription` | 1 | `id` |
| `Live.Base.LimitationError` | 2 | A Python exception type, not a LOM object |
| `Live.Application.Variants` | 0 | Six string constants. See above |
| `Live.Clip.MidiNoteSpecification` | 0 | "An object specifying the data for creating a MIDI note" — the argument type for `add_new_notes` |
| `Live.Track.DeviceContainer` | 0 | "This class is a common super class of Track and Chain" |
| `Live.LomObject.LomObject` | 0 | "the base class for an object that is accessible via the LOM" |
| `Live.Browser.BrowserItemIterator` | 0 | "iterates over children of another BrowserItem" |

One row is verbatim from Live, not a typo here: the dump's key for the
startup dialog is `Live.Licensing.StartupDialogServes as an entry point for
the user to authorize Live on first launch.` — Live's own Boost.Python
registration concatenates the class name with its docstring. Abbreviated to
`StartupDialog…` in the table above.

The five zero-member entries carry no readable class-level members but are
not empty of meaning: `MidiNoteSpecification` is the object the note-writing
API takes, and `DeviceContainer` names the Track/Chain relationship the
device-path resolver bucket in CLOSING_THE_GAPS.md has to model.

### The three worth acting on

**`Live.Envelope.Envelope` — clip automation, read and write.** Docstring:
"This class represents an automation or modulation envelope in Live."

```
value_at_time( (Envelope), (float) ) -> float
events_in_range( (Envelope), (float), (float) ) -> EnvelopeEventVector
create_event( (Envelope), (EnvelopeEvent) ) -> None
insert_step( (Envelope), (float), (float), (float) ) -> None
delete_events_in_range( (Envelope), (float), (float) ) -> None
parameter                                          # ro, the controlled parameter
```

With `EnvelopeEvent` (`time`, `value`, `control_coefficients`) and
`EnvelopeEventControlCoefficients` (`x1`, `y1`, `x2`, `y2`), that is
breakpoint-level automation editing including curve shape.

FORK_GAPS.md § "`Clip` envelopes — the flag ships, the contents do not"
already records the *Clip*-side gap honestly, and the generated `Clip` table
lists `automation_envelope`, `automation_envelopes`,
`create_automation_envelope`, `clear_envelope` and `clear_all_envelopes` as
gaps. What no part of the file says is what you can do once you hold an
`Envelope` — the entry describes a closed door without describing the room.
Anyone sizing that work from FORK_GAPS.md alone would size it wrong.

**`Live.Application.ControlSurfaceProxy` — 12 members.** `send_midi`,
`fetch_received_midi_messages`, `fetch_received_values`, `grab_control`,
`release_control`, `subscribe_to_control`, `unsubscribe_from_control`,
`send_value`, `enable_receive_midi`, `control_descriptions`, `type_name`,
`pad_layout`*. Class docstring: "Represents a control surface running in a
different process. For use by M4L."

Corroborated from the other side by `EXTRA_CS_FUNCTIONS` in the same dump's
`_MxDCore.LomTypes` tables: `get_control`, `get_control_names`,
`grab_control`, `grab_midi`, `release_control`, `release_midi`, `send_midi`,
`send_receive_sysex`. Two independent tables describing a MIDI I/O surface
this fork has never listed as a gap.

**`Live.Track.RoutingType.attached_object`.** The fork already ships
`available_input_routing_types` and friends as display strings. `RoutingType`
carries `category` and `attached_object` — "Live object associated with the
routing type" — which is the identity behind the string. Small, and it sits
directly against work already shipped.

### Excluded, and now excluded on the record

`Live.Licensing` (`PythonLicensingBridge`, `UnlockStatus`, `ProgressDialog`,
`StartupDialog…`) is **34 members that stay shut** — authorization,
`request_exit`, `save_current_set`, modal dialog loops. That is rule 5 in
[CLOSING_THE_GAPS.md](CLOSING_THE_GAPS.md), the safety exclusion. It is
listed here so the exclusion is a decision on the record rather than a class
that silently fell off a list, which is what it has been until now.

## Blind spot 2 — module-level members are dropped by the walker

`visit_module()` in [abletonosc/introspection.py](abletonosc/introspection.py)
recurses into submodules and visits classes. Anything else — a
Boost.Python free function registered directly on a `Live` submodule — is
discarded with no record that it existed.

The known instance is `Live.Conversions`, which holds Live's audio-to-MIDI
conversion. The dump's only entry for it is
`Live.Conversions.AudioToMidiType`, because an enum is a class. Absent, while
present in the Live 12.4.5 binary's registration table with full docstrings:
`audio_to_midi_clip`, `is_convertible_to_midi`,
`create_midi_track_with_simpler`, `create_drum_rack_from_audio_clip`,
`sliced_simpler_to_drum_rack`, `create_midi_track_from_drum_pad`,
`move_devices_on_track_to_new_drum_rack_pad`.

**How many other of the 43 walked `Live` submodules carry free functions is
unknown.** Nothing has ever looked. That is the second reason to fix the
walker: the fix is also the measurement.

Tracked as issue #36, with the audio-to-MIDI surface itself as #34.

## Blind spot 3 — everything outside the `Live` module is unwalked

`walk_live()` walks `Live` and reads the `_MxDCore.LomTypes` tables. These
packages ship with Live, are importable from the same interpreter this
Remote Script runs in, and are walked by nothing:

`_MxDCore`, `_Framework`, `_Generic`, `_Tools`, `ableton/v2`, `ableton/v3`,
`pushbase`, `Push2`, `Push`, `Move`, `MaxForLive`

This is not hypothetical reach. `Live.Conversions` was found because Live's
own `Push2/convert.pyc` imports `Conversions` and calls
`is_convertible_to_midi` and `audio_to_midi_clip` — Ableton's shipped scripts
are a standing existence proof of what a Remote Script may call, and nothing
in this repository reads them systematically.

No claim is made here that any of it should be exposed. The claim is only
that it has never been enumerated, so nobody knows what declining it would
cost.

## What this file does not claim

- **Volume is not value.** 90 dropped classes is mostly enums and vector
  shims. The argument is not "90 missed features"; it is that the
  include/exclude decision is currently made as a side effect of a
  hand-written `CORE` list and Ableton's M4L table, and is invisible.
- **Reachable is not desirable.** `Live.Licensing` is reachable and stays
  shut.
- **Nothing here has been called.** Every member above is tier 1 evidence:
  name, kind and docstring read from a running Live or from the shipped
  binary's registration table. Argument order, return shapes and whether any
  of it raises are unmeasured. Use the probe rig in `API.md` §
  "Measuring the Live API without building the feature first" before
  planning against any of it — and note that the rig itself is currently
  broken on a fresh session (issue #35).

## What closes this file

1. ~~**Report the dropped classes.**~~ Done. `render()` emits a third section,
   *Walked but not diffed*, for every walked entry in neither `CORE` nor the
   M4L table. Enums and `*Vector` shims are excluded by `is_enum_entry()` and
   `is_vector_entry()` — named rules with the reason above them, rather than
   an accident of the `CORE` list. `members()` also renders `kind: "value"`
   now, which is what makes `Live.Application.Variants` legible. The existing
   two sections are byte-identical across the change; only the header, the
   totals line and the legend differ, so nothing in `CLOSING_THE_GAPS.md` moved
   for a reason unrelated to the fork's reach.
2. ~~**Record module-level members.**~~ Done in code. `_visit_class` and
   `_visit_module` are module-level functions taking their state explicitly,
   so `tests_unit/test_introspection_walk.py` drives them over synthetic
   modules without Live; a module that carries members of its own is recorded
   under its qualname with `"kind": "module"`.
3. **Regenerate and re-read** — **outstanding, and Live-gated.** The dump in
   hand was taken with the old walker, so the inventory currently reports
   `0 Live modules walked` and `Live.Conversions` is still absent from
   `FORK_GAPS.md`. Send `/live/application/dump_lom` in a Live running the
   installed copy of this branch, rerun `tools/lom_gaps.py --write`, and
   confirm `Live.Conversions` appears with `audio_to_midi_clip` and
   `is_convertible_to_midi`. That is the acceptance test for item 2, and it is
   also a measurement: how many other of the 43 walked `Live` submodules carry
   free functions is still unknown.
4. **Decide on blind spot 3 explicitly** — enumerate the non-`Live`
   packages once and record the disposition, or record that walking them is
   out of scope and why. Either is fine; silence is not.

Item 3 needs the script reloaded into a running Live. That is now safe to do
from a fresh session: the reload abort this file's companion issue described is
fixed, so `/live/api/reload` no longer stops before `introspection`.

## Documentation obligations

- The counts (134 / 44 / 90 / 31) describe the pre-fix report and the dump in
  hand. Re-take them from the first dump produced by the fixed walker, and
  when they are re-taken say so — the interesting number is how many *modules*
  turn out to carry free functions, which no measurement has ever produced.
- `FORK_GAPS.md` should carry one line near its "Three kinds of gap"
  framing pointing here, so a reader reaching for the generated inventory
  learns its boundary before trusting a silence.
- Any member promoted out of this file into a shipped address leaves here
  and enters `API.md` and the normal FORK_GAPS lifecycle in the same commit.
