# Blind spots — what the gap measurement cannot see

_Companion to [FORK_GAPS.md](FORK_GAPS.md). That file is a diff: what the
installed Live Object Model has, minus what this fork addresses. A diff is
only as good as its left-hand side, and the left-hand side is built by
`abletonosc/introspection.py` walking Live and `tools/lom_gaps.py` rendering
the result. This file records the surfaces that pipeline **structurally
cannot report**, so that absence from FORK_GAPS.md is never again read as
absence from Live._

**The rule this file exists to state:** FORK_GAPS.md is authoritative for
what it reports and silent — not negative — everywhere else. Six categories of
Live surface could not appear in it at all, no matter how much of Live they
carried. Three are fixed or re-scoped, one is half shut and half migrated, and
two are open, so "it is not in FORK_GAPS.md" is evidence only as far as the
Status table below says it is.

Blind spots 1–3 were found by reading the reporting pipeline. Blind spots 4–6
were found by asking the next question — *why is the walk not exhaustive?* —
and measuring each answer rather than ranking it. **The walk is exhaustive of
`dir(Live)`, and `dir(Live)` was read from a running Live and is exactly the 43
modules the walk covers.** Blind spot 4's method channel is measured shut; its
property channel turned out to be statically unanswerable and moved into blind
spot 5. What is left open is 5 and 6, and neither is a defect in the walker —
one is below it (instance shape) and one is the other side of it (what Live
calls on us). **Every static channel is now exhausted**, so 5 is the only
remaining way to check the walked class list for completeness.

## Status

| | state |
|---|---|
| 1 · report filter drops 90 of 134 walked entries | **fixed** — `tools/lom_gaps.py` renders them in *Walked but not diffed*, with the enum/vector exclusion written down as a named rule; `tests_unit/test_lom_gaps.py` pins the exclusions, module tables, signatures, constants and totals |
| 2 · walker drops module-level members | **fixed and verified** — measured against Live 12.4.5 on 2026-08-30; **7 modules carrying 33 free functions**, none of which had ever appeared in any inventory |
| 3 · everything outside the `Live` module is unwalked | **re-scoped; its conclusion now verified directly, its original method retired** — "the walker misses no `Live` submodule" is **true**: `dir(Live)` was read from a running Live 12.4.5 on 2026-08-30 and is exactly the 43 walked modules, zero difference either way. The `Live.X` grep that first produced that number could not have proved it, and a binary-only module (`TestUtilities`) shows why. See the correction below |
| 4 · the walk follows names, not types | **half closed, half migrated** — the *method* channel is measured shut (61 type names, 56 walked, 4 of the 5 remaining are parse noise). The *property* channel is not closed, it is **statically unanswerable**: all 894 have a getter and none carries a docstring, so a class reachable only as some property's value type stays invisible to any static walk. That question is now blind spot 5's |
| 5 · a class walk cannot see an instance | **open, ranked** — `dir(cls)` is the static registration; which parameters *this* Wavetable carries, which `View` *this* device type has, and **which classes appear only as a property's value type**, are runtime facts no class walk holds. Now the only remaining channel for the type question blind spot 4 could not answer |
| 6 · the inbound Remote Script contract is not walkable | **open, and not a walking problem** — the walk sees what a client calls on Live. What Live calls on the script (`create_instance`, `build_midi_map`, `receive_midi`, `suggest_input_port`) is real capability and is structurally invisible to any `dir(Live)` |

The counts and tables below are the measurement that motivated the fixes, taken
before them. They are the record of what was hidden and for how long, not a
description of the tool's present behaviour: entries described here as
"never reported" are now reported.

## What the fixed walker found

Measured 2026-08-30 against the same running Live 12.4.5, with the fixed walker
installed: **141 entries — 134 classes and 7 modules** where the old walker saw
134 classes and no modules. The seven modules carry **33 free functions**, none
of which had ever appeared in `lom_dump.json`, `FORK_GAPS.md`, the apiref, or
Max for Live's `LomTypes` tables. They are now in the generated inventory, with
their signatures, which for a Boost.Python free function is the whole of the
documentation.

| module | free functions | what it is |
|---|---|---|
| `Live.MidiMap` | 10 | The MIDI mapping API — `map_midi_cc`, `map_midi_note`, `map_midi_pitchbend`, each with a `_with_feedback_map` variant, plus `forward_midi_cc` / `_note` / `_pitchbend` and `send_feedback_for_parameter` |
| `Live.Conversions` | 7 | Audio-to-MIDI and the Simpler/Drum Rack conversions. See below |
| `Live.Licensing` | 6 | URLs, unlock directory, `launch_web_browser`. **Safety exclusion**, rule 5 |
| `Live.Application` | 5 | `get_application` (already used), `get_random_int`, `combine_apcs`, two dongle-challenge functions |
| `Live.Base` | 3 | `log`, `get_text`, `subst_args` — Live's own logging and localisation |
| `Live.SimplerDevice` | 1 | `get_available_voice_numbers() -> IntVector` |
| `Live.Song` | 1 | `get_all_scales_ordered() -> tuple` — the full ordered scale list |

**The signatures corrected an assumption.** Every `Live.Conversions` function
takes the `Song` as its first argument, which nothing in the binary's string
table showed and which the issue proposing these addresses did not assume:

```
audio_to_midi_clip( (Song)song, (Clip)audio_clip, (int)audio_to_midi_type) -> None
is_convertible_to_midi( (Song)song, (Clip)audio_clip) -> bool
sliced_simpler_to_drum_rack( (Song)song, (SimplerDevice)simpler) -> None
create_midi_track_with_simpler( (Song)song, (Clip)audio_clip) -> None
create_drum_rack_from_audio_clip( (Song)song, (Clip)audio_clip) -> None
create_midi_track_from_drum_pad( (Song)song, (DrumPad)drum_pad) -> None
move_devices_on_track_to_new_drum_rack_pad( (Song)song, (int)track_index) -> LomObject
```

`audio_to_midi_clip` returns `None`, so a handler that wants to tell a client
where the new track landed must read it back itself; `audio_to_midi_type` is
declared `int`, not the enum type; and `move_devices_on_track_to_new_drum_rack_pad`
is the only member of the seven that returns anything at all.

This is what "the fix is also the measurement" meant. Still tier 1 — read from
the running interpreter, **nothing has been called**. A declared signature is
not proof of behaviour: whether `audio_to_midi_clip` is synchronous, and where
the track it creates lands, remain unmeasured and need a probe.

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

## Blind spot 3 — measured, and it is not what this section assumed

The text below is kept as filed. It framed the packages beside `Live` as an
unmeasured surface of the same kind as blind spots 1 and 2 — "nobody knows what
declining it would cost". That framing was challenged, correctly, on the
grounds that it was the last remaining version of the mistake this file
documents. So it was measured rather than ranked. Two of its three worries
close, and the residue is a different and smaller thing.

**The walker misses no `Live` submodule.** Live's binary string table carries
module names in the form `Live.X`, and all 43 walked modules appear in exactly
that form — which is what validates the method. Grepping for that form yields
44 candidates; the only one not walked is `Live.BasH`, a garbled `Live.Base`,
which *is* walked. So `dir(Live)` in a live session shows everything the host
registers. The caveat in `introspection.py` — "Boost.Python submodules can be
absent from `dir(Live)` until imported" — is real but is not currently costing
anything. Evidence, not proof: a module registered under a name that never
appears as a standalone string would escape this. Every known one does appear.

**The discovery channel that found `Live.Conversions` is exhausted.** Every
`.pyc` Ableton ships was grepped for `Live.*` references: twelve modules, all
already walked, nothing new. Note that `Conversions` is itself referenced as a
bare name (`from Live import Conversions`), so the original find needed a human
reading Push2's source — a grep would not have produced it. That does not
weaken the result, but it bounds it.

**And the packages are categorically different from `Live`.** `Live` is the
host's C++ Boost.Python API — its actual capability surface. `_Framework`,
`ableton.v2`, `ableton.v3`, `pushbase`, `Push2`, `Push`, `Move`, `_Generic` are
Python libraries shipped as Remote Scripts: they are *other clients of the same
API*, not more of it. Everything they do, they do by calling `Live.*`, which is
walked. Exposing `_Framework.ButtonElement` over OSC would not add a Live
capability; it would add Ableton's helper classes for writing control surfaces.
"Walk them like we walk `Live`" is therefore the wrong shape of work, and the
absence of a walk is not the same defect as blind spots 1 and 2.

### Correction, 2026-08-30 — `TestUtilities`, and what "43 of 43" was worth

This section is a correction twice over: first of blind spot 3's method, then
of the correction itself. Both halves are kept, because the second is the more
useful one.

**What the binary holds.** Live's registration table contains a module the walk
has never produced. Between the `Live.TakeLane` marker and the next class
block:

```
TestUtilities
get_base_reference          Returns the given object as base reference.
get_song_reference          Returns the given object as a song reference.
get_track_reference         Returns the given object as a track reference.
…
get_automation_envelope_reference
                            Returns the given object as an automation envelope reference.
```

43 free functions, one per LOM type, each documented. The module name appears
only as the bare string `TestUtilities`, never as `Live.TestUtilities`, so the
`Live.X` grep that produced "43 of 43" could not have seen it. Two further
names turned up the same way: `last_played_level`, with a full
`add_`/`remove_`/`_has_listener` triplet, and `can_select_scene_on_launch`, in
the `Live.Scene` block between `fire` and `fire_as_selected`.

**This was first written up here as falsifying the "43 of 43" claim. It does
not.** A probe against a running Live 12.4.5, the same day:

```
Q2 'TestUtilities' in dir(Live): False
Q2 import Live.TestUtilities FAILED: ModuleNotFoundError("No module named 'Live.TestUtilities'")
Q3 last_played_level hits: NONE in any walked class
Q4 hasattr(Scene, 'can_select_scene_on_launch'): False
Q2 dir(Live) submodules: 43 names
```

`dir(Live)` is **exactly** the 43 modules the walk covers — no module in
`dir(Live)` is unwalked, and no walked module is absent from `dir(Live)`. The
conclusion blind spot 3 reached is correct, and is now held on direct evidence
from the interpreter rather than on a grep over a string table.

**What was actually wrong was the method, and separately, this file's first
reading of the result.** The `Live.X` grep could only ever confirm modules that
name themselves in the form it searched for; it happened to reach the right
answer. Then the binary find was written up here as a falsification before
anything had been called — tier 1 evidence read as a conclusion, which is the
exact error the closing section of this file warns about, committed inside the
document that warns about it.

**The finding worth keeping is the one neither draft set out to make: Live's
registration table is a superset of Live's Python API.** The binary carries
names — a whole module, an observable member, an argument literal — that the
interpreter does not expose. So "present in the binary, absent from the walk"
is not evidence of a hole in the walk; it is, on the only three cases yet
tested, evidence of something Live chose not to expose. That result is what
demoted the binary-inventory item from the head of ROADMAP.md to its tail, and
it is a better reason for confidence in `FORK_GAPS.md` than either draft of
this section provided: the walk's boundary was checked from outside and held.

What survives as work is narrow and is about addresses already shipped:
Boost.Python synthesises signatures at runtime and drops the `arg()` names, so
the binary is the only source for them. ROADMAP.md, "Recover Live's argument
names from the shipped binary".

### What the look found anyway — `_MxDCore/Conversions/`

`_MxDCore` is the one package that is not a helper library: it is Max for
Live's bridge, and this fork already reads its `LomTypes` tables. It ships a
directory that had never been examined:

```
_MxDCore/Conversions/
    EnvelopeEvents.pyc   Routings.pyc   TuningSystem.pyc
    WarpMarkers.pyc      Utils.pyc      __init__.pyc
```

Converters for exactly the object-valued types this fork has open **shape
gaps** on — `EnvelopeEvent`, routings, tuning, warp markers. That is not
capability and does not belong in `FORK_GAPS.md`. It is a **reference
implementation of how Ableton themselves flatten those objects onto a wire**,
which is the genuinely hard part of the `Live.Envelope` work identified above,
and the question the "object-valued members" shape gap has no answer for.

**Read `_MxDCore/Conversions/` before designing the envelope addresses.** That
is the whole of what remains of this section, and it is a reading task, not a
tooling one.

### As originally filed


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

## Blind spot 4 — the walk follows names, not types

`_visit_module` iterates `dir(mod)` and recurses into submodules and classes;
`_visit_class` iterates `dir(cls)` and recurses into nested classes. Both are
**reachability from a namespace**. Nothing follows a *type* edge.

So a Boost.Python class that Live only ever hands back from a method, or only
ever accepts as an argument, and never binds as an attribute of a `Live`
module, is not reachable by any path the walker takes. It has no row, no count
and no note — the same silence blind spot 1 existed to end, arriving through a
different door.

Live declares these types, in the dump we already take. The Boost.Python
docstrings carry the signature, and the signature names the type:

```
move_devices_on_track_to_new_drum_rack_pad( (Song)song, (int)track_index) -> LomObject
events_in_range( (Envelope), (float), (float) ) -> EnvelopeEventVector
create_event( (Envelope), (EnvelopeEvent) ) -> None
create_midi_track_from_drum_pad( (Song)song, (DrumPad)drum_pad) -> None
```

Every one of those type names is an edge, sitting in `lom_dump.json` as an
unparsed string. A closure over them — parse, resolve, walk anything new,
repeat to a fixed point — is the difference between "every type bound to a
name" and "every type the API can hand a client".

**The `_MxDCore.LomTypes` sweep in `walk_live()` is a partial patch on this
hole, and its limit is already documented above.** It walks
`AVAILABLE_TYPE_PROPERTIES`, which is Max for Live's exposure table — and blind
spot 1 is the record of that table dropping real surface:
`Live.CcControlDevice.CcControlDevice`, 41 members, absent for exactly the
reason that Ableton did not choose to expose it to M4L. A patch built from
someone else's inclusion list cannot be the general answer.

#### Measured 2026-08-30, and it closed the item

The closure was prototyped before being planned, on this file's own rule. **It
has nothing to work with.** Both channels were measured; both are empty.

**Methods.** Of the type names Live puts in its signatures:

| | |
|---|---|
| distinct type names | 61 |
| already resolve to a walked entry | 56 |
| do not resolve | 5 — `RGB`, and four parse artefacts (`note`, `tb`, `un`, `StartupDialogServes`) |

**Properties — where the hypothesis was, and where it died.** Signatures exist
for 329 methods and for none of the 894 properties, which are the majority of
the LOM surface and where every object-valued member lives. `Song.tracks`
documents itself as *"Const access to a list of all Player Tracks in the Live
Song"*: prose, no type. The hypothesis was that the type is one attribute away
— that `_classify()` reads `attr.__doc__` while Boost.Python keeps the getter's
signature on `attr.fget.__doc__`. A probe against a running Live 12.4.5
answered it:

```
Q1 properties=894 with_fget=894 fget_doc=0 fget_signature=0
```

Every property has a getter and **not one of them carries a docstring**. There
is no hidden type edge; the type information simply is not in the running
interpreter for a property. A walker cannot follow an edge that Boost.Python
never wrote down.

**What that closes, and what it does not.** It closes the *method* channel: the
edges exist, they were followed, and 56 of 61 were already walked. It does not
close the question the property channel was asked to answer. `fget_doc=0` means
**statically unanswerable**, not *nothing there* — a class that appears only as
the value of some property, and is never bound as a module attribute, remains
invisible, and no amount of work on the static walker can find it, because the
information is not in the interpreter to be read.

That question does not disappear; it **migrates to blind spot 5**. The only way
to learn the type of `Song.tracks`' elements is to hold a `Song` and look at
what comes back. So the static form of this item is declined in ROADMAP.md
under "Walk the type graph, not the namespace", with the reopen condition
there, and the live form is ranked as the instance walk.

An earlier draft of this section recorded blind spot 4 as "closed by
measurement — no action". That was an overstatement of a real negative result,
and this paragraph is the correction.

## Blind spot 5 — a class walk cannot see an instance

`dir(cls)` returns the static Boost.Python registration. A large part of what
Live can do is not in the registration; it is in the object graph at runtime.

- Which `DeviceParameter`s a device carries is a property of *that* device.
  `Live.Device.Device.parameters` is one walked member; the parameter set of a
  Wavetable, an Operator and a third-party VST are three different capability
  surfaces reachable through it, and the walk holds none of them.
- `View` is registered per class, but which device types have which view
  members, and which racks expose chains or drum pads, is instance shape.
- `class_name` is a walked member whose *values* — the set of device types Live
  ships — never appear anywhere in the inventory.

FORK_GAPS.md is a member-level diff and this is not member-level surface, so
this is not an argument that the inventory is wrong. It is the boundary of what
a member-level inventory can mean: **`Live.Device.Device` being fully covered
does not make every device fully reachable**, and the coverage goal is stated
in terms of the second.

**Blind spot 4's unanswered half now lands here too.** Properties carry no type
information anywhere in the running interpreter, so the only way to learn what
`Song.tracks` holds, or whether some class exists that is reachable *only* as a
property's value, is to hold a real object and read `type()` off what comes
back. That makes this the last channel through which the walked class list can
be checked for completeness at all — the static ones are now all exhausted.

Closing it means a **runtime instance walk** — traverse from
`get_application()` and `song` through tracks, devices, chains, drum pads and
parameters, recording each object's actual type and members — run against a set
containing one of every device. That needs Live and a curated set. Ranked in
ROADMAP.md as "Walk a live instance graph, not only the class graph".

### Measured 2026-08-30, Live 12.4.5 — how much of this is callable at all

Planned as one item with the read-half sweep
(`docs/PLAN_lom_instance_walk.md`). The sweep's method predicate — a method is
read-shaped when its name starts `get_`/`is_`/`has_`/`can_` **and** its
Boost.Python docstring parses to a signature taking only the receiver — was
probed against a running Live before being planned:

```
PROBE2 totals methods=589 prefixed=44 selected=18 unparsed=0
```

**The read sweep's method half is 18 calls, not 589.** 44 methods carry one of
the prefixes; 18 of those are zero-argument. So the surface an automated
read-only pass can convert from tier 1 to tier 2 is **894 properties + 18
methods**, and the other 571 methods remain tier 1 until something demands one
of them individually. The arity parser met no docstring it could not parse.

Three of the 18 are `Live.Licensing.PythonLicensingBridge` —
`get_progress_dialog`, `get_session_id`, `get_trial_time_left` — which the
"Reachable is not desirable" rule above shuts. They are denylisted in the
sweep, which is the first case of this file's policy having to override a
syntactic rule.

This measures which methods are *selectable*, not that calling the remaining 15
is harmless. That is what the first instance walk tests.

### Run 1 of the instance walk — 2026-08-30, Live 12.4.5

Shipped as `/live/application/dump_lom_instances` and run against the set that
was open: **1 track, 0 return tracks, 8 scenes, no devices, never saved.** A
thin set, and the numbers below are that set's, not Live's.

```
13 types, 42 objects, 647 reads, 11 calls, 43 errors, 0.018s
cycle_hits 52 · depth_truncations 0 · listeners recorded-never-called 1143
```

**Does a class exist that is reachable only as a property's value?** On this
set, **no** — every type the walk reached is already in `lom_dump.json`. An
empty difference is a result and is recorded as one; it is not evidence for
Live in general, because a set with no devices cannot produce device-only
types. Three entries (`Live.Application.View`, `Live.Song.View`,
`Live.Track.View`) *appear* to be new and are **not**: the class walk keys a
nested class by its owner (`Live.Song.Song.View`) while Boost.Python's
`__qualname__` for it is the bare `View`, so the two key sets need normalising
before they can be compared. Writing those three up as a discovery would have
repeated this file's `TestUtilities` mistake exactly.

**What the run did produce is the first tier-2 evidence in this repository:**
21 distinct measured failure contracts, none of which appears in any
inventory here, because "what raises" is not a member-level fact. A sample:

| member | what it raises |
|---|---|
| `Track.mute` | `RuntimeError: Main track has no 'mute' property!` |
| `Track.arm` | `RuntimeError: Main and Return Tracks have no 'Arm' state!` |
| `Track.input_meter_left` | `RuntimeError: MIDI tracks have no 'input_meter_left' property!` |
| `MixerDevice.crossfader` | `RuntimeError: Only the main track has a crossfader!` |
| `DeviceParameter.value_items` | `RuntimeError: Only quantized parameters have value items` |
| `DeviceParameter.default_value` | `RuntimeError: There is no default value available for this type of parameter` |

Each is a precondition on an address this fork already ships, stated by Live
itself in a sentence no docstring carries.

**Two defects the run found in the walker, both of which had passed the
Live-free suite.** They are recorded here because each is a way a walk can
report success while measuring nothing:

1. **`__module__` is the leaf name.** `type(song).__module__` is `"Song"`, not
   `"Live.Song"`. A `"Live."` prefix test therefore matched *nothing*, and run
   1 walked 2 objects, reported 0 errors and finished in 4ms — a clean, empty,
   entirely wrong result. The discriminator is now `LomObject` in the MRO,
   which every walkable object has and no vector does.
2. **`id()` is not identity for a LOM object.** Boost.Python returns a **fresh
   Python wrapper on every property access**, so
   `song.groove_pool.canonical_parent is song` is `False`. An `id()`-keyed
   cycle guard never fires: the walk recorded one `Song` 11 times, spent its
   entire depth budget on
   `groove_pool.canonical_parent.groove_pool.canonical_parent…`, never reached
   `Song.tracks`, and again reported 0 errors. Worse, the short-lived wrappers
   are collected and their addresses reused, so 54 of the "cycle hits" that
   run were false — an id-keyed guard *skips* objects it has never seen. The
   guard now keys on `_live_ptr`, Live's own pointer to the underlying C++
   object, which is a stable int on every LomObject.

Both are pinned by `tests_unit/test_instance_walk.py`. Neither could have been
caught there first: a synthetic Python object graph has honest `__module__`
values and stable `id()`s, which is precisely why the Live-free suite went
green on a walk that measured nothing.

**Still open after this run:** whether a curated set holding one of every
device produces types the class walk lacks. That is the same tool against a
better set, and it needs no code.

## Blind spot 6 — the inbound contract is not a walkable surface

Every blind spot above is about what a client can call on Live. The Remote
Script interface runs in the other direction: `create_instance`,
`build_midi_map`, `receive_midi`, `suggest_input_port`, `can_lock_to_devices`
and the rest are functions **Live calls on us**. They are capability — MIDI
mapping, port suggestion, control grabbing — and no `dir(Live)` walk can ever
produce one of them, because they are not members of `Live`.

Blind spot 3 concluded that the non-`Live` packages are "clients of the same
API, not more of it". That is right for `_Framework.ButtonElement` and it is
the reason walking those packages stays out of scope. It is **not** right for
the base-class contract inside them: `_Framework` and `ableton.v3` are also
where the inbound protocol is written down, and reading them for that is the
only channel there is. This fork already implements part of the contract in
`manager.py` and `abletonosc/midimap.py`, discovered by need rather than by
enumeration.

This is a reading task with a written output, like the `_MxDCore/Conversions/`
item blind spot 3 ended on — not a tooling one, and not a walk. It is filed
here so that the absence of these functions from every inventory is on the
record as a known category rather than an oversight.

## Two standing limits, which no tool closes

**Everything is tier 1.** Names, kinds and docstrings, read from a running
Live. A declared signature is not behaviour, and this has already cost
something concrete: `audio_to_midi_clip` declares `-> None`, and that it is
*asynchronous* — which decides the entire shape of any handler built on it —
was learnt only by calling it. Argument domains, which enum values are legal in
which context, what raises, and what a call does to the undo stack are all
outside every inventory this repository generates. The probe rig in `API.md` §
"Measuring the Live API without building the feature first" is the channel for
that, and it was exercised successfully on 2026-08-30 (Live 12.4.5):
`/live/api/reload` worked repeatedly across a fresh session. Issue #35 is
closed.

**One build, one edition.** Every measurement in this file is Live 12.4.5
Suite, macOS. Intro, Lite and Standard gate features; other Live versions add
and remove members. The inventory is a snapshot presented as if it were the
API, and nothing in the pipeline records which parts are edition-gated. Closing
this is a matrix run — the same `dump_lom` against other editions and one older
version, diffed — and it is bounded by licences rather than by work.

**And the ceiling above all of it:** Live's GUI does more than its Python
binding exposes. No introspection makes an unbound feature appear. *Exhaustive
of Live's Python API* is reachable and is what blind spots 4–6 are for.
*Exhaustive of what Live can do* is not reachable from this direction at all,
and any claim in that form should be read as the first thing.

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
  planning against any of it. The rig itself works: issue #35 is closed, and
  it was exercised on 2026-08-30 against Live 12.4.5.

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
3. ~~**Regenerate and re-read.**~~ Done, 2026-08-30, against a running Live
   12.4.5 with this branch installed. `Live.Conversions` appears in
   `FORK_GAPS.md` with all seven members and their signatures; the inventory
   header reads `134 Live classes and 7 Live modules walked`. The question this
   item existed to answer — how many other `Live` submodules carry free
   functions — is answered above: six more, 26 further functions.
4. ~~**Decide on blind spot 3 explicitly.**~~ Measured, and re-scoped — see
   that section. Walking the non-`Live` packages is out of scope, with the
   reason recorded: they are clients of the `Live` API, not more of it. What
   replaced it is narrower and concrete: **read `_MxDCore/Conversions/` before
   designing the `Live.Envelope` addresses**, because it is Ableton's own
   answer to the object-valued wire-shape question those addresses raise.

5. ~~**Close the reachability gap by following type edges (blind spot 4).**~~
   Measured and declined for the method channel — 56 of 61 types already
   walked. The property channel has no edges to follow at all
   (`fget_doc=0`), so it is not a walker change; it became item 7.
6. ~~**Check the walk against something that is not the walk.**~~ Done, and it
   returned the opposite of what was expected: the binary's registration table
   is a **superset** of Live's Python API, carrying a module, a member and
   argument literals the interpreter does not expose. The walk's boundary was
   checked from outside and held. What survives is argument-name recovery,
   ranked last in ROADMAP.md.
7. **Walk a live instance graph, not only the class graph (blind spot 5).**
   Ranked in ROADMAP.md. Now carries blind spot 4's unanswered half as well:
   with every static channel exhausted, this is the only remaining way to test
   whether the walked class list is complete.
8. **Read and write down the inbound Remote Script contract (blind spot 6).**
   Unranked; a reading task in `_Framework` / `ableton.v3`, with `manager.py`
   and `abletonosc/midimap.py` as the partial implementation to check against.

Items 1–6 are closed, declined or answered; 7 is ranked in ROADMAP.md; 8 is
open and unranked.

The lesson worth keeping is procedural, and items 5–8 exist because it was
applied a second time: item 4 was ranked low on an argument, and the argument
was sound but incomplete — looking took twenty minutes and turned up
`_MxDCore/Conversions/`, which the argument would have cost. Rank by
measurement, not by reasoning about what a measurement would show. **The
closing of items 1–4 was then read as "the walk is now exhaustive", which it
never was and which no item here had claimed.** That reading is what blind
spots 4–6 are on the record to prevent: a fixed pipeline is not a complete one,
and this file is closed only when something outside the walk has confirmed the
walk.

## Documentation obligations

- The counts (134 / 44 / 90 / 31) describe the pre-fix report. The post-fix
  inventory is 141 entries, 44 reported in the two diffed sections and 38 in
  *Walked but not diffed* after the enum and vector exclusions.
- `FORK_GAPS.md` should carry one line near its "Three kinds of gap"
  framing pointing here, so a reader reaching for the generated inventory
  learns its boundary before trusting a silence.
- Any member promoted out of this file into a shipped address leaves here
  and enters `API.md` and the normal FORK_GAPS lifecycle in the same commit.
- **`ROADMAP.md` items #1 and #2 restate these counts when they land.** Both
  change the walked total, and the totals in this file and the pinned counts in
  `tests_unit/test_lom_gaps.py` must move with them in the same commit — a
  restated count is how a reader tells a measured inventory from a remembered
  one.
