# Roadmap

The single living list of what to do next — defects and missing Live Object
Model surface in one ranked queue. The top item is the biggest win, work top to
bottom. One item = one PR.

Each entry is self-contained: a **Goal** (the required outcome, checkable
against a diff), a **Why** (the defect or the consumer that makes it worth
doing now), and **Planner notes** (what the plan author must know before
starting — constraints, dependencies, consumers). An entry may also cite a
*Source* — a longer write-up elsewhere in the repo, or the per-member rows of
the generated inventory in [FORK_GAPS.md](FORK_GAPS.md) for a gap — but the
entry must stand on its own if that write-up is gone.

**Adding an item to the roadmap**
An item must state its goal and why it is worth doing, and give the plan author
enough context to start — a roadmap entry is **not** an implementation plan.
Plans get written per item (the `/plan` skill) when the work is picked up.

Ranking is **impact-per-effort**: a protocol defect that every later PR builds
on outranks a large gap bucket, and a small bucket that sets a convention the
rest reuse outranks a big one that doesn't. Place the new item in the order its
priority earns.

**Removing an item from the roadmap**
Item numbers are ranks, not stable identifiers — when something ships, delete
all trace of it here and let the rest renumber (the `/ship` skill handles this),
remove or update whatever source write-up the entry cited, and move its plan
doc to [docs/archive/](docs/archive/) with a status banner. Nothing
else about a ship stays here — this file documents future work only; ship
history lives in git, `SESHAT.md`, and the archived plan. **Outside this file, cite
an item by its title, never by its rank.** A rank is correct only until the
next ship, and a stale one doesn't look stale — it silently points at a
different item. The `Depends on` notes below are the one place ranks are used,
and `/ship` renumbers them with the entries.

**[Deliberately not planned](#deliberately-not-planned)**
The section at the end records work weighed and declined, each with the
condition that would reopen it. Check it before proposing or re-proposing
work; add to it when rejecting a proposal.

---

## #1 · Verify handler `class_identifier` and lifecycle invariants without Live

**Goal:** a Live-free test walks every `AbletonOSCHandler` subclass in
`abletonosc/*.py` and asserts each declares a class-level `class_identifier`
matching an expected address-prefix map, and that none defines its own
`__init__`.

**Why:** `tests_unit/test_handler_lifecycle.py` only ever constructs local
`Probe` subclasses defined in the test file — the production subclasses
(`TrackHandler` and the rest) import `Live` at module scope and are out of
reach there. A typo in a class attribute (e.g. `class_identifier = "clipslot"`
on the wrong handler) or a merge that restores a subclass `__init__` assigning
`self.class_identifier` both pass every test green today; SESHAT.md's
merge-hazard note for `AbletonOSCHandler.__init__` now says as much for the
subclass case.

**Planner notes:**
- Source: pr-review of "Fix base handler initialization order"
  (`docs/archive/PLAN_base_handler_init_order.md`), nits 2 and 3 — one
  `ast`-based test closes both.
- No Live and no construction needed: parse `abletonosc/*.py` with `ast`,
  find every class whose bases include `AbletonOSCHandler`, and check its
  body for a `class_identifier` assignment (value matches the expected map)
  and the absence of a `def __init__`.
- Once this lands, tighten SESHAT.md's `AbletonOSCHandler.__init__`
  merge-hazard note to point at the new test for the subclass-`__init__`
  case instead of describing it as uncovered.
- No dependencies.

## #2 · Normalize listener argument identity in track.py and return_track.py

**Goal:** `track_callback.py`'s `include_track_id` branch and
`return_track.py`'s hand-rolled per-property `start_listen`/`stop_listen`
pairs (including the index-less master triple) truncate their identity to
exactly the arguments that are part of it — the same rule "Normalize listener
argument identity in scene.py, clip.py, clip_slot.py, and the device.py
property pair" established everywhere else: arguments past a subscription's
identity are dropped from the bookkeeping key and the push, not merely
appended after the cast indices.

**Why:** `track_callback.py:89` builds `tuple([track_index] + params[1:])` —
the index is already an int (the wildcard fan-out generates ints too), but
nothing bounds `params[1:]`, so `start_listen/<prop> <index> <extra>` keys
`(prop, (index, extra))` while the well-formed `stop_listen/<prop> <index>`
keys `(prop, (index,))` — the identical extra-arg leak the sibling item fixed
in `device.py`, `scene.py`, `clip.py`, and `clip_slot.py`, reachable here by
the same shape of malformed request. `return_track.py`'s per-property pairs
(`name`, `volume`, `panning`, `mute`, `solo`, plus the parameterless master
`volume`/`panning`/`cue_volume`) don't share `track_callback.py`'s helper at
all — they are separate hand-rolled code with their own identity handling —
so this is a second fix in that file, not a side effect of the first.

**Planner notes:**
- Source: `docs/archive/PLAN_listener_identity_normalization.md`, "Out of scope"
  (both bullets), and that item's pr-review (branch
  `listener-identity-normalization`, round 2, nit 4's third bullet) —
  explicitly named there as real but deliberately excluded from that item's
  diff to keep it to the four files its title named.
- `track_callback.py`'s `include_track_id` path is shared by the mixer listen
  pair too (`_start_mixer_listen`/`_stop_mixer_listen` in `track.py`) — fix
  and test both, not just the plain property pair.
- `return_track.py` needs its own audit: enumerate every
  `_start_listen_<prop>`/`_stop_listen_<prop>` method (and the master trio)
  and confirm each one's identity-building line, since there is no shared
  wrapper to point at.
- Verified 2026-08-27 against `/Users/patrick/seshat`:
  `lib/seshat/session/state.ex` sends `/live/track/start_listen/<prop>
  <index>`, `/live/return_track/start_listen/<prop> <index>`, and
  `/live/master/start_listen/<prop>` with exactly the documented argument
  count, always an Elixir (int32) index, never floats or extras — so today's
  only known caller is unaffected either way; the gap is reachable only by a
  malformed or hand-crafted client. Re-confirm this before assuming "pin bump
  only" if `lib/` has changed since.
- No dependencies.

## #3 · One `/live/song/undo` does not revert an OSC-created scene

**Goal:** establish how many undo steps an OSC-driven mutation actually
registers in Live, document the real contract for `/live/song/undo` and
`/live/song/redo` in API.md, and either fix the cause or pin the measured
behaviour in `tests/test_song.py::test_song_undo_redo` — which is currently
left failing on purpose rather than adjusted to match.

**Why:** measured against Live 12.4 on 2026-08-27, the first time the live
suite had ever run: baseline 8 scenes -> `/live/song/create_scene` -> 9 ->
`/live/song/undo` -> **still 9** -> a second `undo` -> 8. No error is emitted
either way, so a client that undoes once believes it has reverted and has not.
Every consumer driving Live through this bridge and relying on undo to unwind
its own writes is exposed, and the fork's `begin/end_undo_step` addresses make
that a documented usage pattern rather than a hypothetical one.

**Planner notes:**
- Not a regression from any shipped item. The pre-change test at `ea6b719`
  carries the identical one-undo assumption (hard-coded `8`/`9` instead of a
  discovered baseline), and nothing in the five items shipped above touches
  undo. The suite simply never ran before, so the assumption was never tested.
- Source: the live-verification run recorded in
  `docs/archive/PLAN_test_suite_regression_gate.md` (2026-08-27).
- First thing to establish: what the extra undo step *is*. Candidates worth
  ruling out in order — the selection change that accompanies scene creation,
  Live coalescing two steps for a single API call, and this fork's own
  `begin_undo_step`/`end_undo_step` wrapping leaving an extra entry on the
  stack. The answer decides whether this is a Live fact to document or a fork
  defect to fix, and those lead to opposite outcomes for the test.
- Reproduce with the probe pattern in API.md's measurement section; a scene is
  the cheapest mutation, but confirm against a second kind (a track, a clip
  property) before concluding it is general.
- If it proves to be a Live fact, the fix is an API.md contract paragraph plus
  a test that asserts the measured step count with the reason written down --
  not a silent bump from one `undo` to two.

## #4 · A-4 · Object-valued read helpers

**Goal:** index-returning handlers for `Song.master_track`,
`Song.appointed_device` (get/set/listen), `Track.group_track`, `ClipSlot.clip`,
`Song.View.selected_chain`, `selected_parameter`, `mod_mapping_device` /
`mod_mapping_parameter`, with `-1` for none.

**Why:** small, and it establishes the object-read pattern every later PR uses
— the generic property loop returns `None` for object-valued members today.
Unblocks the groove bucket.

**Planner notes:**
- Source: `CLOSING_THE_GAPS.md`, row **A-4**; closes FORK_GAPS
  "Object-valued reads returned as `None`".
- No dependencies.

## #5 · B-2 · DeviceParameter rich reply

**Goal:** one richer `parameters` reply plus per-parameter addresses —
`value_items`, `short_value_items`, `display_value` (get/set), `str_for_value`,
`state`, `is_enabled`, `automation_state`, `default_value`, `original_name`,
`begin_gesture` / `end_gesture`.

**Why:** the integration audit's Medium–high, with no dependencies on other
gaps and a named consumer (enum labels, disabled/automated state). First real
gap PR — it proves the batching conventions the rest reuse: handlers +
`API.md` rows + FORK_GAPS entry removal + inventory regeneration + Seshat pin.

**Planner notes:**
- Source: `CLOSING_THE_GAPS.md`, row **B-2**; closes FORK_GAPS "Device
  parameters — numeric only".
- Shape PR: the wire form is the review subject.
- No dependencies.

## #6 · C-3 · Application dialogs and versions

**Goal:** read-only dialog state (`open_dialog_count`,
`current_dialog_message`, `current_dialog_button_count`, listen where
observable) plus `get_bugfix_version`, `get_build_id`, `get_variant`,
`get_version_string`, `has_option`, `peak_process_usage`,
`unavailable_features`, `number_of_push_apps_running`, `show_message`,
`show_on_the_fly_message`, `control_surfaces` (names only).

**Why:** the audit's top High, and tiny. `press_current_dialog_button` stays
out unless a separately reviewed, non-file use case proves it safe — a
dialog may guard unsaved work.

**Planner notes:**
- Source: `CLOSING_THE_GAPS.md`, row **C-3**.
- Fold in `issues.md`, "Remove the unsolicited average-process-usage startup
  datagram" (Medium-low): `ApplicationHandler.init_api` sends an empty
  `/live/application/get/average_process_usage` at startup that nothing
  requested. Same file, same PR; remove that entry at ship time too.
- No dependencies.

## #7 · B-1 · Notes extended

**Goal:** `/live/clip/get/notes_extended` and `/live/clip/add/notes_extended`
carrying `note_id`, `probability`, `velocity_deviation`, `release_velocity`,
old five-field addresses unchanged; then the ID-keyed members
(`apply_note_modifications`, `get_notes_by_id`, `duplicate_notes_by_id`,
`select_notes_by_id`, `get_selected_notes(_extended)`, `select_all_notes`,
`deselect_all_notes`, `replace_selected_notes`, `set_notes`).

**Why:** the largest-value gap PR and self-contained; it is what Seshat's
"Modify a note in place" roadmap item needs.

**Planner notes:**
- Source: `CLOSING_THE_GAPS.md`, row **B-1**; closes FORK_GAPS "Notes —
  `/live/clip/get/notes` flattens to five fields".
- Shape PR: the wire form is the review subject.
- No dependencies.

## #8 · Make live code reload ordered and failure-safe

**Goal:** `/live/api/reload` produces a coherent module graph whose handlers
share the current base classes, and a failed reload preserves a usable previous
API or fails in a clearly reported, recoverable state.

**Why:** `Manager.reload_imports` reloads concrete handler modules before their
`handler` base and activates the result even after an exception. Every gap PR
uses reload during development; move this up if it bites during #4–#7.

**Planner notes:**
- Source: `issues.md`, "Make live code reload ordered and failure-safe"
  (Medium-high).
- No dependencies.

## #9 · Stop masking Remote Script import failures

**Goal:** a failed import of `Manager` inside Live surfaces the original
exception at startup, and the Live-free test layer imports what it needs
without a blanket `ImportError` guard in the Remote Script entry point.

**Why:** the package root swallows every `ImportError` so pytest can import it
without Live's modules; in Live the same guard hides a real missing dependency
or programming error, and `create_instance()` then fails with a `NameError` on
the undefined `Manager` instead of the actionable cause. Every handler PR
above is debugged through that startup path.

**Planner notes:**
- Source: `issues.md`, "Stop masking Remote Script import failures" (Medium).
- Small: root `__init__.py` plus whatever `tests_unit/conftest.py` needs to
  keep loading modules without Live. Check how the loader there imports today
  before choosing the guard's replacement.
- No dependencies.

## #10 · Remove the process-global and shared-file risks from song structure export

**Goal:** `/live/song/export/structure` has a private, collision-safe export
contract — or is deleted if nothing consumes it.

**Why:** it clears `os.environ['TMPDIR']` for the whole Live process and writes
a fixed predictable filename in the shared temp directory — exactly what the
browser exporter was hardened against.

**Planner notes:**
- Source: `issues.md`, "Remove the process-global and shared-file risks from
  song structure export" (Medium-high).
- Check Seshat consumers first: if the address is unused, deletion is a
  five-line PR that can go any time.
- Depends on that consumer audit only.

## #11 · Add bounded log retention

**Goal:** the installed `logs/abletonosc.log` has an explicit size ceiling
with documented rotation, and `/live/api/reload` and disconnect neither stack
duplicate handlers nor leak file descriptors.

**Why:** `Manager.start_logging` uses an unbounded `FileHandler` and every
getter request is logged, so a long-lived Seshat session grows the file
without limit (≈855 KB at the time of the audit, still growing).

**Planner notes:**
- Source: `issues.md`, "Add bounded log retention" (Medium).
- `manager.py` only, but `logs/abletonosc.log` is also the evidence channel
  for `API.md` § "The no-probe variant" — rotation must not lose the tail a
  reviewer is reading; name the rotated filenames in `API.md`.
- No dependencies.

## #12 · A-3 · Return / master `Track` parity

**Goal:** `/live/return_track/*` and `/live/master/*` reach the regular-track
address set — colour, routing, meters, `has_*_input/output`, every
`start_listen`, `insert_device`, `mixer_device.sends` on returns.

**Why:** regular tracks have 107 addresses, returns 20, master 15; every
return/master feature downstream trips over the difference.

**Planner notes:**
- Source: `CLOSING_THE_GAPS.md`, row **A-3**; closes the FORK_GAPS Track
  addressing gap and the `MixerDevice` gap on returns/master.
- Prefer a shared track resolver over three copies of the handler table.
- No dependencies.

## #13 · C-1 · `Song` remainder

**Goal:** the remaining scalar `Song` members through the generic property
loop — count-in, automation state, scale mode/intervals, tempo follower, Link
start/stop, `file_path`, exclusive arm/solo, and the rest listed in the bucket.

**Why:** cheap generic-loop batch; slot in whenever a quick win is wanted.

**Planner notes:**
- Source: `CLOSING_THE_GAPS.md`, row **C-1**.
- No dependencies.

## #14 · D-2 · Groove

**Goal:** `/live/song/get/groove_pool` (indexed names and amounts), `Groove.*`
amounts get/set, `/live/clip/get|set/groove` by pool index or `-1`.

**Why:** named consumer — Seshat's generation work — and the curated
`Clip.groove` entry in FORK_GAPS is the one gap that keeps
`groove_amount` from having an effect on plain MIDI.

**Planner notes:**
- Source: `CLOSING_THE_GAPS.md`, row **D-2**.
- Measure whether `browser.load_item` can load an `.agr` into the pool.
- Depends on #4 (object-read pattern).

---

## Deliberately not planned

- **A-1 device path resolver and A-2 Arrangement clip resolver.** The two
  biggest, riskiest changes in `CLOSING_THE_GAPS.md` (a dispatch refactor
  each), and FORK_GAPS marks their payoffs — racks, Arrangement — as declined
  until a workflow needs them. **Reopens when** D-1 or an Arrangement feature is
  scheduled; A-1 lands first, alone, with no scalar padding.
- **Device-specific classes** (Drift, Wavetable, Looper, …, ~130 members).
  One PR each, only when a feature names it; D-4 sets the pattern for a device
  subclass PR. Never blanket parity work.
- **Low-priority issues** — clip filtering, transport inconsistencies, module
  splits, the `dump_lom` path bound, the log-level assert. Opportunistic: fold
  into a PR that already touches the same file rather than ranking them.
- **Correct and complete the public API documentation** (`issues.md`,
  Medium). `API.md` is the fork's canonical contract and every address PR
  adds its rows there, which is the substance of this item; what remains is
  upstream-file housekeeping — the README download link points at
  ideoforms, `CONTRIBUTING.md` says `/live/reload` instead of
  `/live/api/reload`, the README track section predates the return/master
  split. Opportunistic: fix a line when a PR already touches that file, and
  never rewrite README's address tables (they are upstream's, kept for merge
  fidelity). **Reopens when** `API.md` is found to disagree with the code.
- **Establish a single authoritative endpoint contract inventory**
  (`issues.md`, Medium). `API.md` plus Seshat's `vendored_addresses_test`
  are the inventory and the tripwire today; the test suite now has a
  contract layer (`tests_unit/`) to check a generated one against, but
  building it is still not worth it on its own. **Reopens when** a
  doc/code drift is found that the unit layer didn't catch.
- The defect-shaped declines — the `pythonosc` escape sequence — are in
  `issues.md` § Declined with its reopen condition.
