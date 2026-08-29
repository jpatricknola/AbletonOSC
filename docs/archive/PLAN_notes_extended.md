# Plan: Notes extended (B-1)

**Archived 2026-08-29 — shipped.** This is the plan as written *before*
implementation; the code as merged may differ. The change lives in
`abletonosc/clip.py` (the "Clip: Extended notes" block, twelve new
addresses) and `API.md` § "Extended notes (note ids)". The Live
verification section's seven checks did not run — the installed Remote
Scripts copy was not this checkout during the run (see its Results
subsection) — so every ⚠️ marker in `API.md` stands and all six Open
questions below stay open for whoever verifies against a running Live next.

Roadmap item: **#1 · B-1 · Notes extended** — from `CLOSING_THE_GAPS.md` row
B-1, closing FORK_GAPS "Notes — `/live/clip/get/notes` flattens to five
fields" and the curated "Extended note identity and modification" row.
Planned 2026-08-29.

## Context

`/live/clip/get/notes` already calls `clip.get_notes_extended`
(`abletonosc/clip.py`, `clip_get_notes`) and then throws away most of what it
got: each `MidiNote` in the returned vector carries `note_id`, `probability`,
`velocity_deviation` and `release_velocity` alongside the five fields the
reply flattens to (`pitch, start_time, duration, velocity, mute`).
`/live/clip/add/notes` likewise builds `Live.Clip.MidiNoteSpecification`s
from five fields, so probability, deviation and release velocity cannot be
written at all. And without `note_id` on the wire, the whole ID-keyed half of
Live's modern note API — `apply_note_modifications`, `get_notes_by_id`,
`duplicate_notes_by_id`, `select_notes_by_id` — is unusable from a client
even where an address exists: `/live/clip/remove_notes_by_id` is registered
today and `API.md` has to warn that nothing in this API yields an id to pass
it.

Why now: it is the largest-value gap PR that is still self-contained (no
resolver work, one handler module), and it is exactly what Seshat's "Modify a
note in place" roadmap item needs — Seshat's `edit_notes` currently composes
remove + add keyed on the five-field reply, which destroys probability,
deviation and release velocity as a side effect of every edit
(`FORK_GAPS.md` curated row, "Extended note identity and modification").

Key constraints research surfaced:

- **The LOM call needs no change for the read.** The roadmap entry is right:
  `clip_get_notes` already holds the extended vector; only the reply shape is
  new work. The old five-field addresses therefore stay byte-identical by
  construction — the new addresses are separate registrations, and the
  existing `clip_get_notes` / `clip_add_notes` / `clip_remove_notes`
  functions are not touched.
- **This is Live's own documented note surface.** Live 12's shipped Push
  code (`pushbase/note_editor_component.pyc`,
  `ableton/v3/control_surface/components/note_editor.pyc` in the app bundle)
  drives `get_notes_extended` → mutate → `apply_note_modifications`, and
  constructs `MidiNoteSpecification`s while handling `probability` and
  `velocity_deviation` — read 2026-08-29 from the bundle's bytecode strings
  (tier-2 evidence: names present in the same compiled module, not calls
  observed). The M4L note API documents the same field set. The probe rig
  could not be run this session (see Open questions), so every claim about
  call behaviour below that isn't Live's own docstring carries ⚠️.
- **Signatures are tier-1 where the inventory has them.** From the
  `FORK_GAPS.md` generated inventory (read off the running Live):
  `apply_note_modifications((Clip), (MidiNoteVector)) -> None`,
  `get_notes_by_id((Clip), (object)note_ids) -> MidiNoteVector`,
  `duplicate_notes_by_id((Clip)self, (object)note_ids [,
  (object)destination_time=None [, (int)transposition_amount=0]]) ->
  IntU64Vector`, `select_notes_by_id((Clip), (object)) -> None`,
  `get_selected_notes((Clip)) -> tuple`,
  `get_selected_notes_extended((Clip)) -> MidiNoteVector`,
  `select_all_notes/deselect_all_notes((Clip)) -> None`,
  `replace_selected_notes((Clip), (tuple)) -> None`,
  `set_notes((Clip), (tuple)) -> None`.
- **Everything rides `create_clip_callback`** — the fork-normalised wrapper
  (SESHAT.md § Merge hazards): indices cast to int, callee gets
  `tuple(params[2:])`, replies get `(track_index, clip_index, *rv)`
  prepended, failures become the structured
  `/live/error ["request", address, message, argc, *args]` envelope via
  `OSCServer._dispatch`. No listeners are involved anywhere in this item
  (notes are methods, not observable properties), so the
  `pass_clip_index=True` identity machinery is untouched.
- **A pythonosc edge on ids**: the vendored builder tags a Python int as
  int32 unless `bit_length() > 32`. A note id in `[2^31, 2^32)` would fail
  `struct.pack(">i", ...)` and the reply would be dropped with a logged
  BuildError; an id ≥ 2^32 goes out int64-tagged (`h`). Live note ids are
  small monotonic ints in practice; this is documented, not worked around.

## Wire contract

**Canonical extended note group — nine fields, in this order:**

    pitch, start_time, duration, velocity, mute, probability, velocity_deviation, release_velocity, note_id

The first five are exactly the existing five-field order, so a client
upgrades by widening its stride; `note_id` is last so the *add* form is the
same group truncated to eight (Live assigns ids). Reply type notes, matching
the measured behaviour of the old addresses (`API.md` § "Note windows match
by start…"): `mute` goes out as an OSC boolean (`T`/`F`) but is accepted as
`0`/`1` int on requests; `velocity`, `probability`, `velocity_deviation`,
`release_velocity` are floats; `pitch` and `note_id` ints.

### New addresses

| Address | Request | Reply | Notes |
|---|---|---|---|
| `/live/clip/get/notes_extended` | `track_id, clip_id [, start_pitch, pitch_span, start_time, time_span]` | `track_id, clip_id, <9 fields per note>...` | Range args all-or-nothing (0 or 4), same rule and same `ValueError` text pattern as `get/notes`; no-args default is the same `0, 127, -8192, 16384` window. Calls `get_notes_extended`. |
| `/live/clip/add/notes_extended` | `track_id, clip_id, <8 fields per note>...` | *silent* | Fields = canonical order minus `note_id`. `(len(params) - 2)` must be a non-zero multiple of 8, else `ValueError` naming the stride → `/live/error`. Builds `MidiNoteSpecification(..., probability=, velocity_deviation=, release_velocity=)` ⚠️ and calls `add_new_notes`. No reply even if Live returns the new ids (⚠️ return unmeasured); read ids back with `get/notes_extended`. |
| `/live/clip/get/selected_notes_extended` | `track_id, clip_id` | `track_id, clip_id, <9 fields per note>...` | Calls `get_selected_notes_extended`. Empty selection → just the two indices. ⚠️ whether selection exists when the clip is not in the detail view is unmeasured. |
| `/live/clip/get/selected_notes` | `track_id, clip_id` | `track_id, clip_id, <5 fields per note>...` | Five-field flattening of `get_selected_notes_extended` — the same flattening `get/notes` applies, covering the deprecated `get_selected_notes` member without calling it. |
| `/live/clip/get_notes_by_id` | `track_id, clip_id, note_id...` (≥ 1 id) | `track_id, clip_id, <9 fields per note>...` | Calls `get_notes_by_id`. Reply order is the vector Live returns ⚠️ (assumed request order). Zero ids → `ValueError` → `/live/error`. Unknown ids: whatever Live does arrives as either a shorter reply or a structured `/live/error` ⚠️. |
| `/live/clip/apply_note_modifications` | `track_id, clip_id, <9 fields per note>...` | *silent* | Stride-checked (non-zero multiple of 9). Handler fetches the cited ids via `get_notes_by_id`, sets the eight value fields on each returned `MidiNote` ⚠️ (attribute writability unmeasured; Push does exactly this), and calls `apply_note_modifications` with the vector. Any requested id missing from Live's answer → `ValueError` naming it → `/live/error`; nothing is applied in that case. |
| `/live/clip/duplicate_notes_by_id` | `track_id, clip_id, destination_time, transposition_amount, note_id...` (≥ 1 id) | `track_id, clip_id, new_note_id...` | `destination_time` float; **any negative value** → Live's `None` default (duplicate in place) — `-1` is the documented sentinel, and negative destination times are therefore unreachable through this address (documented in the API.md row; notes can start at negative beats, but duplicating *to* one is out of scope). `transposition_amount` int, `0` = none. Reply is the `IntU64Vector` of new ids the LOM signature documents. |
| `/live/clip/select_notes_by_id` | `track_id, clip_id, note_id...` (≥ 1 id) | *silent* | Pass-through. |
| `/live/clip/select_all_notes` | `track_id, clip_id` | *silent* | Generic methods loop. |
| `/live/clip/deselect_all_notes` | `track_id, clip_id` | *silent* | Generic methods loop. |
| `/live/clip/replace_selected_notes` | `track_id, clip_id, <5 fields per note>...` | *silent* | Deprecated tuple API, exposed as Live ships it: handler groups the five-field runs into the `((pitch, start, dur, vel, mute), ...)` tuple the member takes. Stride-checked (non-zero multiple of 5). ⚠️ semantics (replace selection) unmeasured — Live's docstring carries no description. |
| `/live/clip/set_notes` | `track_id, clip_id, <5 fields per note>...` | *silent* | Same deprecated tuple form. ⚠️ semantics unmeasured — the pre-Live-11 API's "set notes" *added* notes rather than replacing; documented as deprecated with `add/notes` / `add/notes_extended` as the recommended path. |

Error behaviour for every address: malformed argument counts raise
`ValueError` inside the callee, bad indices raise `IndexError` at the
`create_clip_callback` boundary, notes calls against an audio clip raise in
Live — all arrive as the structured
`/live/error ["request", <address>, <message>, argc, *args]` envelope. All
setters/mutators are silent on success (fire-and-forget), per the fork norm.

### Changed

- `/live/clip/remove_notes_by_id` — **behaviour unchanged**, documentation
  changed: the `API.md` row's ⚠️ "nothing in this API yields an id to pass"
  is now false and is replaced by a pointer to `get/notes_extended`.

### Unchanged but relied on

- `/live/clip/get/notes`, `/live/clip/add/notes`, `/live/clip/remove/notes`
  — byte-identical: their handler functions are not edited. A regression
  test pins the five-field reply shape.

## Numbered parts

### Part 1 — `abletonosc/clip.py`: the addresses

One fork-owned block after the existing notes handlers ("Clip: Extended
notes" comment header, mirroring device.py's "Describe parameters" block),
all registered through `create_clip_callback`:

- Module-level canonical field order: a tuple
  `EXTENDED_NOTE_FIELDS = ("pitch", "start_time", "duration", "velocity",
  "mute", "probability", "velocity_deviation", "release_velocity")` (id
  handled separately, always last) plus two small helpers — one flattening a
  `MidiNote` to the 9-field group, one parsing wire params into fixed-stride
  groups with the shared stride/`ValueError` wording. The get/selected/by-id
  repliers and both parsers use them, so reply order can never drift between
  addresses.
- `clip_get_notes_extended` — same 0-or-4 range validation as
  `clip_get_notes` (same error message style), `get_notes_extended`, 9-field
  flatten.
- `clip_add_notes_extended` — stride-8 parse; per group build
  `Live.Clip.MidiNoteSpecification(pitch=int(...), start_time=float(...),
  duration=float(...), velocity=float(...), mute=bool(int(...)),
  probability=float(...), velocity_deviation=float(...),
  release_velocity=float(...))`; `clip.add_new_notes(tuple(specs))`; return
  `None`.
- `clip_get_selected_notes_extended` / `clip_get_selected_notes` — the
  extended call, 9- and 5-field flattens.
- `clip_get_notes_by_id` — ids → `tuple(int(i) for i in params)`,
  `ValueError` on empty; 9-field flatten of the returned vector.
- `clip_apply_note_modifications` — stride-9 parse; `get_notes_by_id` on the
  cited ids; map `note_id → MidiNote`; `ValueError` naming any requested id
  not returned (checked *before* mutating anything); set the eight fields on
  each note object; `apply_note_modifications` with the fetched vector.
- `clip_duplicate_notes_by_id` — first two args `destination_time`
  (`float`; `< 0` → `None`) and `transposition_amount` (`int`), then ≥ 1
  ids; reply = tuple of the returned new ids.
- `clip_select_notes_by_id` — ids parse, pass-through, silent.
- `clip_replace_selected_notes` / `clip_set_notes` — stride-5 parse into the
  `((pitch, start_time, duration, velocity, mute), ...)` tuple. Coerce
  explicitly per the canonical field types — `int(pitch)`,
  `float(start_time)`, `float(duration)`, `float(velocity)`,
  `bool(int(mute))`, the same coercions as the extended add parser (note
  `clip_add_notes` itself performs *no* coercion; do not copy that — the
  deprecated members' element typing is unmeasured, and explicit coercion
  keeps float-typed TouchOSC args from depending on it). Pass to the
  deprecated member, silent.
  A comment marks both as deprecated pass-throughs kept for LOM parity.
- `select_all_notes` and `deselect_all_notes` join the existing `methods`
  list (they take no extra args, return nothing — exactly what
  `_call_method` handles).
- Registrations: `get/notes_extended`, `add/notes_extended`,
  `get/selected_notes_extended`, `get/selected_notes` under the verb forms;
  `get_notes_by_id`, `apply_note_modifications`, `duplicate_notes_by_id`,
  `select_notes_by_id`, `replace_selected_notes`, `set_notes` as bare
  member-named addresses (the `remove_notes_by_id` precedent, and what the
  inventory's segment-equality coverage counts automatically).

No listener work, no changes to existing functions, no other files' code.

### Part 2 — `tests_unit/test_clip_notes.py` (new) and conftest doc updates

New test module built exactly like `test_listener_identity.py`'s clip half:
`load_clip_module()`, local `FakeManager`/`FakeSong`/`FakeTrack`/
`FakeClipSlot`/`FakeClip` fakes, dispatched through `conftest.dispatch` with
replies drained off `receiver`. The `FakeClip` grows fake
`get_notes_extended` / `get_notes_by_id` / `apply_note_modifications` /
`duplicate_notes_by_id` / etc. methods returning `FakeMidiNote` objects, and
records every call for assertion.

For `add/notes_extended` the test monkeypatches a `Clip` namespace onto the
process-global empty `Live` stub
(`monkeypatch.setattr(sys.modules["Live"], "Clip", fake_ns, raising=False)`)
carrying a recording `MidiNoteSpecification` — the application.py-seam
pattern's image for a call-time dereference. **conftest.py's docstrings must
be updated in the same commit**: the module docstring and
`load_clip_module()`'s both currently state that no test in the suite
dispatches an address that dereferences `Live.Clip.MidiNoteSpecification`,
and that stops being true here (module docstring ¶"two narrow exceptions",
and the `load_clip_module` docstring).

Coverage list is in **Testing** below.

### Part 3 — `API.md`: the rows

Same commit as Parts 1–2:

- New subsection under "Clip API" — "Extended notes (note ids)" — with the
  canonical group order stated once, the address table above, the
  request/reply type asymmetry (`mute` in/out, floats), the deprecation
  notes on `set_notes` / `replace_selected_notes`, the negative
  `destination_time` → `None` sentinel (`-1` documented, any negative
  treated the same, negative destinations unreachable), the int32/int64 id
  edge, and ⚠️ markers on
  everything listed under Open questions (they stay until the Live
  verification below runs).
- Edit the `/live/clip/remove_notes_by_id` row: drop the "nothing yields an
  id" warning, point at `get/notes_extended`.
- Extend the "what the round trip cannot preserve" sentence in § "Note
  windows match by start…" with a pointer to the extended addresses.

### Part 4 — `FORK_GAPS.md` and `tools/lom_gaps.py`

Same commit:

- Curated row "Extended note identity and modification" → **Landed**,
  pointing at the new Closed entry (the B-2 device-parameters row is the
  template).
- Move "### Notes — `/live/clip/get/notes` flattens to five fields" out of
  Shape gaps into the Closed group as "### Notes — flattened to five fields
  — closed 2026-08-29" (following the B-2 closed-entry style): what the gap
  was, the addresses that closed it, the members this closes
  (`apply_note_modifications`, `get_notes_by_id`, `duplicate_notes_by_id`,
  `select_notes_by_id`, `get_selected_notes`, `get_selected_notes_extended`,
  `select_all_notes`, `deselect_all_notes`, `replace_selected_notes`,
  `set_notes` — ten inventory rows), and the standing note that the
  generated inventory still lists them as gaps until a
  `/live/application/dump_lom` is taken against a Live running the installed
  post-change copy (B-2 precedent — no dump can be taken without
  installing, which this repo's gate forbids).
- `tools/lom_gaps.py` `ALIASES["Live.Clip.Clip"]`: add
  `get_selected_notes: "/live/clip/get/selected_notes"` and
  `get_selected_notes_extended: "/live/clip/get/selected_notes_extended"`
  (verb-form addresses whose segments don't equal the member names); update
  the `get_notes_extended` / `add_new_notes` / `get_all_notes_extended`
  alias strings to also name the `notes_extended` addresses. The bare
  member-named addresses (`get_notes_by_id`, `apply_note_modifications`,
  `duplicate_notes_by_id`, `select_notes_by_id`, `replace_selected_notes`,
  `set_notes`, `select_all_notes`, `deselect_all_notes`) are covered by
  segment equality and need no alias.

### Part 5 — `SESHAT.md`

Same commit: one entry under "Additions to upstream's code" — the clip.py
extended-notes block: the address list, the canonical field order and why
`note_id` is last (add = same group truncated), the deliberate silence of
`add/notes_extended`, the two deprecated pass-throughs, and the note that
everything rides the already-hazard-listed `create_clip_callback` (no new
merge hazard section needed; the existing create_clip_callback hazard entry
covers the wrapper).

### Part 6 — Live verification results back into `API.md`

Deferred until the checks below can run (installed copy ≠ this checkout
today, and installing is out of this repo's gate). When they run, their
measured facts replace the ⚠️ markers from Part 3, dated and
Live-version-stamped. Not a blocker for the PR: the ⚠️ markers *are* the
documented state, exactly as B-2 shipped.

## Testing (`tests_unit/`, the only gate)

All Live-free, through `conftest.dispatch` against the real `ClipHandler` on
the real `OSCServer`:

1. **Registration** — every address in the table dispatches (no "Unknown OSC
   address" log), driven through the production registration loop.
2. **`get/notes_extended`** — reply address and `(track, clip, *groups)`
   shape; 9-field order matches the canonical tuple; 0-arg default window
   and 4-arg window forwarded to the fake verbatim; 1–3 range args →
   `/live/error` with the structured envelope.
3. **`add/notes_extended`** — the fake `MidiNoteSpecification` records
   kwargs: all eight per group, `mute` coerced to bool, floats coerced;
   multi-group parse; stride 7/9/0 extra args → `/live/error`, and
   `add_new_notes` not called; no reply datagram on success.
4. **`get/selected_notes_extended` and `get/selected_notes`** — 9- vs
   5-field flattening of the same fake vector; empty selection replies bare
   indices.
5. **`get_notes_by_id`** — ids forwarded as ints (float-typed wire ids
   truncate, TouchOSC rule), reply groups; zero ids → `/live/error`.
6. **`apply_note_modifications`** — fake notes fetched by id get all eight
   fields assigned and the same objects passed to the fake
   `apply_note_modifications`; a group citing an id the fake doesn't return
   → `/live/error` naming it and no apply call; stride errors as in add.
7. **`duplicate_notes_by_id`** — `-1` (and another negative value, e.g.
   `-0.5`) destination becomes `None`, non-negative floats pass through;
   transposition int; reply carries the fake's returned ids.
8. **Deprecated pass-throughs** — `set_notes` / `replace_selected_notes`
   build the exact nested tuple with the coerced element types
   (`int` pitch, `float` times/velocity, `bool` mute) from float-typed wire
   args; stride errors.
9. **Old addresses pinned** — `/live/clip/get/notes` against a fake whose
   notes carry extended fields still replies exactly five fields per note;
   `/live/clip/add/notes` still constructs five-kwarg specifications. This
   is the "byte-identical by construction" claim made checkable.
10. **Bad indices** — one representative address (e.g. `get/notes_extended`)
    with an out-of-range track → structured `/live/error` (the
    `create_clip_callback` boundary, same as existing suites).

Explicitly *not* covered here: any behaviour of real LOM objects —
attribute writability on real `MidiNote`s, `MidiNoteSpecification`'s real
kwargs, selection semantics, deprecated-method semantics. `tests/` (the
live suite) mutates a running Live and is not part of the gate.

## Live verification

Precondition for every check: the Remote Scripts copy equals this checkout
byte for byte **and** Live has been restarted since it was copied. Neither
holds today (installed copy predates the last three ships), and this
lifecycle run may not install or restart — so these are specified for the
next verification session, per the B-2 precedent. Method: `API.md` § "The
no-probe variant" (send to 11000, read the installed `logs/abletonosc.log`;
11001 is Seshat's). Every mutation bracketed in
`/live/song/begin_undo_step` / `end_undo_step` on a scratch MIDI clip
created for the run and deleted after; nothing here touches listeners.

1. **Extended round trip**: `add/notes_extended` one note with
   `probability 0.25, velocity_deviation 10.0, release_velocity 32.0`;
   evidence: `get/notes_extended` reply logged by `_get...`/handler log
   lines shows the three fields back (not Live's defaults `1.0/0.0/64.0`),
   plus a nonzero `note_id`. Decides ⚠️ spec kwargs.
2. **Modify in place**: take that id, `apply_note_modifications` changing
   only `velocity_deviation`; evidence: `get_notes_by_id` shows the new
   value with the *same* id, other fields untouched. Decides ⚠️ attribute
   writability.
3. **Duplicate**: `duplicate_notes_by_id -1 0 <id>`; evidence: reply logged
   with new id(s); `get/notes_extended` count +1. Then with
   `destination_time 4.0` — new note starts at 4.0.
4. **Unknown id**: `get_notes_by_id` with `999999999`; evidence: either a
   `/live/error` line naming the address or an empty reply — record which,
   into `API.md`. Decides ⚠️ unknown-id behaviour.
5. **Selection**: `select_all_notes` then `get/selected_notes_extended`
   with the clip *not* opened in detail view; evidence: reply count vs the
   clip's note count. Decides ⚠️ detail-view dependence.
6. **Deprecated semantics**: on a scratch clip holding two notes, `set_notes`
   with one different note; evidence: `get/notes` afterwards shows add vs
   replace. Same for `replace_selected_notes` after `select_all_notes`.
   Decides ⚠️ deprecated semantics; results become the API.md description.
7. **add return value** (bonus, needs the probe rig, not just no-probe):
   log `clip.add_new_notes(...)`'s return; if it is a vector of
   ids/MidiNotes, file a follow-up roadmap note to give
   `add/notes_extended` a reply — the address stays silent in this item
   regardless.

Remains uncovered even after these: behaviour on take-lane/arrangement
clips (no resolver exists — Session clips only, as for every `/live/clip/*`
address) and ids' stability across undo (out of scope, roadmap #5 owns undo
semantics).

### Results — checks 1-7 **skipped by environment** (pr-review, 2026-08-29)

Recorded by the review of branch `feat/notes-extended`. No check was run, and
no result below is approximated or inferred.

The section's own precondition fails. Live 12 *is* running (PID 78577), but
the installed Remote Scripts copy is not this checkout:

    diff -rq --exclude=__pycache__ abletonosc \
        "$HOME/Music/Ableton/User Library/Remote Scripts/AbletonOSC/abletonosc"
    Files abletonosc/application.py ... differ
    Files abletonosc/clip.py ... differ
    Files abletonosc/device.py ... differ
    Files abletonosc/track_identity.py ... differ

`clip.py` differing is decisive on its own: none of the twelve new addresses
exist in the copy Live loaded, so every check would report an unknown address
and prove nothing about this branch. Closing the gap needs the copy replaced
*and* Live restarted, and this lifecycle may do neither.

| Check | Status | Reason |
|---|---|---|
| 1 extended round trip | skipped by environment | installed copy is not this checkout — Open question 1 (`MidiNoteSpecification` kwargs) stays open |
| 2 modify in place | skipped by environment | as above — Open question 2 (`MidiNote` attribute writability) stays open |
| 3 duplicate | skipped by environment | as above |
| 4 unknown id | skipped by environment | as above — Open question 3 stays open |
| 5 selection vs detail view | skipped by environment | as above — Open question 5 stays open |
| 6 deprecated semantics | skipped by environment | as above — Open question 4 stays open |
| 7 `add_new_notes` return value | skipped by environment | as above, and it additionally needs the probe rig, whose write into the installed copy this environment refuses — Open question 6 stays open |

Consequence for the shipped state: every ⚠️ marker in `API.md` § "Extended
notes (note ids)" stands as written, and all six Open questions above stay
open. Nothing in the Live-free gate is affected — `python3 -m pytest
tests_unit/` is green at 462 passed (52 of them this item's).

## Downstream

**Pin bump only.** Every address is new; no existing reply, push, or error
changes shape; no listener is added or changed. `vendored_addresses_test`
gains tripwires only when Seshat starts using the new addresses.

Worth stating for the Seshat side when it adopts:

- `edit_notes` can move from remove+add to
  `get/notes_extended` → `apply_note_modifications`, which is the Seshat
  roadmap item this feeds.
- Reply decoding: `mute` arrives as OSC `T`/`F` (same asymmetry as
  `get/notes`, already handled), and a note id ≥ 2^32 would arrive
  int64-tagged (`h`) — Seshat's decoder should tolerate `h` before adopting
  (ids that large have not been observed).
- Wildcard fan-out (the roadmap "Verify wildcard fan-out" item's concern,
  restated for `/live/clip/`): a pattern like `/live/clip/get/*  t c` now
  also matches `notes_extended`, `selected_notes`,
  `selected_notes_extended` — three more replies per fan-out, each on its
  own concrete address. Harmless for direct dispatch; unmeasured for any
  Seshat pattern sends, same as the device case.

## Out of scope

- **A reply for `add/notes_extended`** (new ids) — depends on the
  unmeasured `add_new_notes` return; Live check 7 decides whether to file
  it as a follow-up. Clients read ids back with one `get/notes_extended`.
- **Arrangement/take-lane note editing** — needs the A-2 resolver
  (Deliberately-not-planned tier); everything here is Session clips via
  `(track_index, clip_index)`.
- **A `notes` listener** — Live's notes-changed observation
  (`add_notes_listener`) is not in the roadmap Goal and touches the
  listener machinery this item otherwise avoids; stays in the B-1 bucket's
  source row if ever wanted.
- **Fixing the `[2^31, 2^32)` id BuildError edge** in the vendored
  pythonosc — documented in API.md instead; a fix belongs to an
  osc-server-owned item if a real id ever gets there.
- **`/live/clip/get/notes` gaining extended fields in place** — explicitly
  rejected by the FORK_GAPS entry (old shape stays stable); the regression
  test pins it.

## Open questions

The probe rig (`API.md` § "Measuring the Live API…") could not be run this
session: writing the temporary probe into the installed Remote Scripts copy
was denied by the environment's permission policy, and no local Python 3.11
exists to decompile Live's shipped bytecode beyond string evidence. Each
question below therefore stays open with the plan's working assumption; all
are resolvable by the Live verification checks (or the one probe) above.

1. **Does `MidiNoteSpecification` accept `probability`,
   `velocity_deviation`, `release_velocity` kwargs?** Unknown exactly;
   assumed yes — the M4L note-specification documents the fields and
   Live 12's own `pushbase` bytecode uses these names around
   `MidiNoteSpecification`. If the constructor rejects them, fallback is
   setting them as attributes on the spec before `add_new_notes`; the
   handler isolates construction in one helper so the fix is one line.
   (Live check 1.)
2. **Are `MidiNote` attributes writable from Remote Script Python?**
   Assumed yes (Push's editor mutates-and-applies). If not, the modify
   handler has no non-destructive fallback — remove+add changes ids — so
   this would come back to the roadmap. (Live check 2.)
3. **`get_notes_by_id` behaviour on unknown ids** — raise vs shorter
   vector, and reply ordering vs request order. The handler's own
   missing-id `ValueError` in `apply_note_modifications` makes the modify
   path deterministic either way; the plain getter documents whichever
   Live does. (Live check 4.)
4. **`set_notes` / `replace_selected_notes` semantics** — Live's docstrings
   carry no description; the pre-Live-11 "set notes" *added* notes.
   Exposed as documented-deprecated pass-throughs with ⚠️ on semantics.
   (Live check 6.)
5. **Selection API vs detail view** — whether `get_selected_notes_extended`
   / `select_all_notes` require the clip in the detail view. Documented
   with ⚠️ until measured. (Live check 5.)
6. **`add_new_notes` return value** — decides only the out-of-scope
   follow-up, not this wire contract (the add address is silent by
   design). (Live check 7.)
