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

## #1 · B-1 · Notes extended

**Plan:** [docs/PLAN_notes_extended.md](docs/PLAN_notes_extended.md)

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
- The LOM call needs no change: `/live/clip/get/notes` already calls
  `clip.get_notes_extended` (`clip.py:173`) and throws the extra fields away
  when it flattens to five. Only the reply shape and the new addresses are
  new work — which also means the old five-field addresses stay byte-identical
  by construction, not by care.
- Shape PR: the wire form is the review subject.
- No dependencies.

## #2 · A-3 · Return / master `Track` parity

**Goal:** `/live/return_track/*` and `/live/master/*` reach the regular-track
address set — colour, routing, meters, `has_*_input/output`, every
`start_listen`, `insert_device`, `mixer_device.sends` on returns.

**Why:** returns and master have the mixer surface (volume, panning, mute,
solo, name, cue volume) and a device subset, and almost nothing else — no
colour, no routing, no meters, no `has_*_input/output`, no `insert_device`, no
`mixer_device.sends` on returns. Every return/master feature downstream trips
over the difference.

**Planner notes:**
- Source: `CLOSING_THE_GAPS.md`, row **A-3**; closes the FORK_GAPS Track
  addressing gap and the `MixerDevice` gap on returns/master.
- **The "107 / 20 / 15" address counts in the FORK_GAPS heading and the A-3
  row predate the fork's return/master work and are no longer accurate** —
  `return_track.py` alone now registers about thirty addresses, including the
  `name`/`volume`/`panning`/`mute`/`solo` listen pairs that FORK_GAPS still
  describes as missing. Recount from the code before sizing the PR, and
  regenerate or correct those figures as part of it.
- Prefer a shared track resolver over three copies of the handler table.
- No dependencies.

## #3 · C-1 · `Song` remainder

**Goal:** the remaining scalar `Song` members through the generic property
loop — count-in, automation state, scale mode/intervals, tempo follower, Link
start/stop, `file_path`, exclusive arm/solo, and the rest listed in the bucket.

**Why:** cheap generic-loop batch; slot in whenever a quick win is wanted.

**Planner notes:**
- Source: `CLOSING_THE_GAPS.md`, row **C-1**.
- Audited 2026-08-27: none of the row's members are registered yet, so the
  row can be taken as written. Note that neighbouring members already exist
  and are *not* this item — `root_note`, `scale_name`,
  `is_ableton_link_enabled`, `clip_trigger_quantization`
  (`song.py:63-78`) — so the scale and Link work here is `scale_mode`,
  `scale_intervals` and `is_ableton_link_start_stop_sync_enabled` only.
- No dependencies.

## #4 · D-2 · Groove

**Goal:** `/live/song/get/groove_pool` (indexed names and amounts), `Groove.*`
amounts get/set, `/live/clip/get|set/groove` by pool index or `-1`.

**Why:** named consumer — Seshat's generation work — and the curated
`Clip.groove` entry in FORK_GAPS is the one gap that keeps
`groove_amount` from having an effect on plain MIDI.

**Planner notes:**
- Source: `CLOSING_THE_GAPS.md`, row **D-2**.
- `Clip.groove` is already known to be unreachable through the generic
  property loop and is commented out in place with the reason
  (`clip.py:123`: "Infered arg_value type is not supported") — that
  commented line is the concrete thing this item replaces. The object-read
  pattern it needs (index-or-`-1`, resolvers in `track_identity.py`) has
  shipped and is available to use directly — see `API.md` § "Object-valued
  reads".
  `song.groove_amount` (`song.py:65`) and `clip.has_groove`
  (`clip.py:110`) already work and stay as they are.
- Measure whether `browser.load_item` can load an `.agr` into the pool.
- No dependencies.

## #5 · One `/live/song/undo` does not revert an OSC-created scene

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
- Not a regression from any shipped item.
  `tests/test_song.py::test_song_undo_redo` has carried the one-undo
  assumption since it was written; the regression-gate item only replaced its
  hard-coded `8`/`9` with a discovered baseline and left the single `undo`
  between the assertions untouched (`tests/test_song.py:256-278`). Nothing in
  the five items shipped before it goes near undo. The suite simply never ran
  before, so the assumption was never tested.
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

## #6 · Make a failed live code reload safe and reported

**Goal:** a reload that raises does not activate a partially reloaded module
graph — `/live/api/reload` either preserves a usable previous API or fails in a
clearly reported, recoverable state, and the failure reaches the client rather
than only the log file.

**Why:** `Manager.reload_imports` wraps the whole reload sequence in one
`try`, logs the traceback at warning level, and then falls through to
`clear_api()` / `init_api()` regardless (`manager.py:196-202`). A module that
failed to reload stays at its previous definition while its siblings advance,
that mixture becomes the live API, and the caller who sent `/live/api/reload`
is told nothing went wrong.

**Planner notes:**
- Source: `issues.md`, "Make live code reload ordered and failure-safe"
  (Medium-high). **The ordering half of that entry has shipped** with "Fix
  base handler initialization order": `reload_imports` now reloads
  `osc_server` and `handler` before every subclass module, `track_callback`
  before `track`, and `track_identity` before `view`, with the reasoning
  written into the code (`manager.py:152-195`). Only failure-safety remains —
  narrow that `issues.md` entry to the remainder at ship time rather than
  deleting it.
- `abletonosc.midimap` is deliberately absent from the reload list, so
  `MidiMapHandler` keeps subclassing whatever `AbletonOSCHandler` was current
  at Live startup, across every reload (`manager.py:163-169`). Harmless today
  because `midimap`'s `init_api()` reads neither `class_identifier` nor a
  listener dict — decide in this item whether to close it or record it as
  accepted, since the code comment currently points here for the answer.
- Every gap PR uses reload during development; move this up if it bites
  during #1–#4.
- No dependencies.

## #7 · Stop masking Remote Script import failures

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

## #8 · Remove the process-global and shared-file risks from song structure export

**Goal:** `/live/song/export/structure` has a private, collision-safe export
contract — or is deleted if nothing consumes it.

**Why:** it clears `os.environ['TMPDIR']` for the whole Live process and writes
a fixed predictable filename in the shared temp directory — exactly what the
browser exporter was hardened against.

**Planner notes:**
- Source: `issues.md`, "Remove the process-global and shared-file risks from
  song structure export" (Medium-high).
- **The code is in `song.py:210-231`** (`song_export_structure`), *not* in
  `abletonosc/song_structure.py` — that module is unrelated track and
  return-track listener code that shares only the name. Do not start by
  opening the file the item sounds like.
- The behaviour is documented, so deleting or changing it is an API.md edit
  too: `API.md:598-603` describes the reply and names the `TMPDIR` blanking.
- Check Seshat consumers first: if the address is unused, deletion is a
  five-line PR that can go any time.
- Depends on that consumer audit only.

## #9 · Add bounded log retention

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

## #10 · Document `song` in the handler constructor contract

**Goal:** `abletonosc/handler.py`'s `AbletonOSCHandler` "Constructor
contract" docstring lists `song` alongside the other invariants (`logger`,
`manager`, `osc_server`, the three listener dicts) that `init_api()` may
rely on already being set.

**Why:** the docstring's step 2 enumerates what step 4 (`init_api()`) may
read, but omits `song` even though `SongHandler.init_api` and
`ViewHandler.init_api` both bind `self.song` / `self.song.view` into
`partial()`s while the constructor is still registering addresses —
exactly the invariant the docstring exists to name. A future handler
author reading only the docstring would not learn that `song` is
available that early, or that `tests_unit/conftest.py`'s `bind_song()`
is how the test harness models it (see `SESHAT.md`'s test-harness entry).
Comment-only; no behaviour changes.

**Planner notes:**
- Source: pr-review finding on `object-read-glue-tests`, 2026-08-28
  (observation, not a blocking or applied finding — flagged as a future
  comment-only addition, deliberately outside that item's file list).
- `abletonosc/handler.py` only. Verify with a `git diff --stat` showing
  no non-comment line, same as the A-4 `track_identity.py` precedent.
- No dependencies.

## #11 · Verify wildcard fan-out against Seshat's `/live/device/` usage

**Goal:** confirm whether Seshat ever sends an OSC address *pattern* (not a
literal address) under `/live/device/`, and if so, record what changes for
it: `/live/device/get/parameters/*` now fans out to eleven replies instead of
five (harmless — each carries its own `callback_address`), and
`/live/device/set/parameter/* <t> <d> <p> <float>` now also matches
`set/parameter/display_value` alongside `set/parameter/value` — a float
assigned to Live's string setter, which if Live raises a Boost
`ArgumentError` (a `TypeError` subclass) is **not** skipped by
`_is_wildcard_skip` (`osc_server.py:105`), so the client gains a
`/live/error` it did not previously get.

**Why:** flagged in pr-review of "DeviceParameter rich reply" (2026-08-29).
`OSCServer.process_message` (`osc_server.py:241`) fans an address pattern out
over every matching registration, so that PR's "pin bump only" downstream
claim holds for direct dispatch but is unmeasured for wildcard sends —
the reviewer could not check Seshat's handlers from this repo, and neither
could the nit-triage pass that declined fixing it inline.

**Planner notes:**
- Source: pr-review finding on `feat/device-parameter-rich-reply`, 2026-08-29
  (non-blocking nit, declined for that PR as speculative and unverifiable
  from this repo — recorded here rather than fixed blind).
- Check Seshat's own OSC address construction (`lib/seshat/tools/handlers.ex`
  and anywhere else it sends to this bridge) for any address containing a
  wildcard character (`*`, `?`, `[`, `{`) under `/live/device/`. If none
  exists, this closes with that finding recorded and no code change here.
- If one does exist, decide whether the fix belongs in this fork (narrow
  `set/parameter/*`'s effective family, or extend `_is_wildcard_skip` to
  recognise the Boost `ArgumentError` case) or in how Seshat builds the
  address.
- No dependencies; verification-only, and may resolve to "no action" without
  ever becoming a Python change here.

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
  ideoforms, and the README track section predates the return/master split.
  (The `CONTRIBUTING.md` `/live/reload` typo this bullet used to name was
  fixed by the regression-gate item; that file says `/live/api/reload`
  throughout now.) Opportunistic: fix a line when a PR already touches that file, and
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
- **`/live/song/get/master_track`.** Named in the object-valued read helpers
  item's original Goal, deliberately not delivered: `Song.master_track` is
  already reached under `/live/master/*` (never a FORK_GAPS row), and under
  the shipped `(category, index)` identity convention the reply could only
  ever be the constant `("master", 0)` — a wire address that answers one
  value forever and that Seshat would have to tripwire for no return.
  **Reopens when** a consumer actually needs the constant; a five-line
  follow-up.
