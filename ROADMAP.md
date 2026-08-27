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

## #1 · Define and repair multi-track wildcard getter responses

**Goal:** a wildcard track getter (`/live/track/get/name *`) reports every
selected track under a stated wire contract, and single-track requests and
wildcard setters keep their existing behaviour.

**Why:** confirmed live protocol defect — the track callback wrapper returns on
the first getter result, so `/live/track/get/name *` answers for track 0 only.
Every consumer that reads more than one track at once is silently getting one.

**Planner notes:**
- Source: `issues.md`, "Define and repair multi-track wildcard getter
  responses" (Critical).
- The contract has to be *chosen* before the fix: per-track replies vs one
  aggregate, ordering, empty set, partial error. The `/live/error` fan-out
  rules already documented in `README.md` § Wildcard queries constrain it —
  a wildcard request is a fan-out, not a query.
- Check Seshat compatibility before picking a shape; it is the only known
  consumer and its `Transport` correlates by address.
- No dependencies.

## #2 · Fix base handler initialization order

**Goal:** every handler enters route registration with `listener_functions`,
`listener_objects` and `class_identifier` already set, and subclass-owned
initialization has an explicit lifecycle.

**Why:** `AbletonOSCHandler.__init__` calls the overridable `init_api()` before
creating the base invariants, so every subclass registers against a partially
built object — `BrowserHandler` already carries a workaround. Every gap PR below
adds handlers on top of this; fix it before piling on.

**Planner notes:**
- Source: `issues.md`, "Fix base handler initialization order" (High).
- Must preserve current route registration, listener cleanup, reload behaviour
  and the fork's handler overrides — `tests_unit/` is the net for the dispatch
  half; the reload half has no test yet.
- No dependencies.

## #3 · Make the test suite safe, isolated, and usable as a regression gate

**Goal:** a unit/contract layer that exercises routing, validation, reply
shapes and listener bookkeeping without Live; Live-dependent tests opt-in,
fixture-isolated and self-restoring; a tracked dev-dependency manifest and CI.

**Why:** nothing below ships protected without it. `tests/` mutates a running
Live on *import* (`/live/api/reload` at module scope), binds `0.0.0.0:11001`
(collides with Seshat, wider than the loopback policy), and assumes a specific
blank set. `tests_unit/` is the seed of the Live-free layer and is what this
item grows.

**Planner notes:**
- Source: `issues.md`, "Make the test suite safe, isolated, and usable as a
  regression gate" (High).
- Reopens the declined "The Python test harness reloads AbletonOSC on import"
  — its reconsider condition is exactly this item.
- Seshat's end-to-end coverage stays distinct: it owns the fixed reply port and
  the long-lived listeners.
- No dependencies; items #4, #7 and #9 depend on it.

## #4 · Device listener identity — parameter indices and property listeners

**Goal:** device parameter listeners key on normalized integer identifiers, and
device *property* listeners (`name`, `type`, `class_name`) push with their track
and device indices and subscribe per device instead of one per property
process-wide.

**Why:** two listener-key bugs in the same file with the same lifecycle tests:
float-valued OSC arguments leak listeners, and property listeners collapse to
`(prop, ())` so a second device's subscription silently replaces the first.

**Planner notes:**
- Sources: `issues.md`, "Normalize device parameter listener identifiers" (High)
  **and** "Give device property listeners their identity back" (Medium) — one
  PR, both entries close together.
- The property-listener half is a wire-contract change (push gains two leading
  indices). Seshat subscribes to none of these today and its API doc warns
  against building on them; coordinate the doc removal in the pin bump.
- Depends on #3 for the listener-lifecycle tests.

## #5 · Define selected-track identity across regular, return, and master tracks

**Goal:** one unambiguous representation of a selected regular, return or master
track that selection, view, device and state-mirroring addresses all agree on;
view setters and getters agree on whether setters are silent.

**Why:** the fork's own `/live/return_track/select` and `/live/master/select`
break `/live/view/get/selected_track`, which only knows `song.tracks`. The
representation chosen here is a prerequisite for the return/master parity and
object-read buckets, so it must be decided before they are built.

**Planner notes:**
- Source: `issues.md`, "Define selected-track identity across regular, return,
  and master tracks" (High).
- `/live/view/set/selected_device` currently replies despite being documented
  silent — settle it here.
- Assess consumers expecting a single regular-track index (Seshat's
  `Session.State`).
- No dependencies; #6 and the A-3 bucket depend on it.

## #6 · A-4 · Object-valued read helpers

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
- Depends on #5 for the track-identity representation.

## #7 · B-2 · DeviceParameter rich reply

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
- Depends on #2 (handler lifecycle) and #3 (tests).

## #8 · C-3 · Application dialogs and versions

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
- Depends on #2.

## #9 · B-1 · Notes extended

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
- Depends on #3.

## #10 · Make live code reload ordered and failure-safe

**Goal:** `/live/api/reload` produces a coherent module graph whose handlers
share the current base classes, and a failed reload preserves a usable previous
API or fails in a clearly reported, recoverable state.

**Why:** `Manager.reload_imports` reloads concrete handler modules before their
`handler` base and activates the result even after an exception. Every gap PR
uses reload during development; move this up if it bites during #6–#9.

**Planner notes:**
- Source: `issues.md`, "Make live code reload ordered and failure-safe"
  (Medium-high).
- No dependencies.

## #11 · Stop masking Remote Script import failures

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

## #12 · Remove the process-global and shared-file risks from song structure export

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

## #13 · Add bounded log retention

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

## #14 · A-3 · Return / master `Track` parity

**Goal:** `/live/return_track/*` and `/live/master/*` reach the regular-track
address set — colour, routing, meters, `has_*_input/output`, every
`start_listen`, `insert_device`, `mixer_device.sends` on returns.

**Why:** regular tracks have 107 addresses, returns 20, master 15; every
return/master feature downstream trips over the difference.

**Planner notes:**
- Source: `CLOSING_THE_GAPS.md`, row **A-3**; closes the FORK_GAPS Track
  addressing gap and the `MixerDevice` gap on returns/master.
- Prefer a shared track resolver over three copies of the handler table.
- Depends on #5.

## #15 · C-1 · `Song` remainder

**Goal:** the remaining scalar `Song` members through the generic property
loop — count-in, automation state, scale mode/intervals, tempo follower, Link
start/stop, `file_path`, exclusive arm/solo, and the rest listed in the bucket.

**Why:** cheap generic-loop batch; slot in whenever a quick win is wanted.

**Planner notes:**
- Source: `CLOSING_THE_GAPS.md`, row **C-1**.
- Depends on #2.

## #16 · D-2 · Groove

**Goal:** `/live/song/get/groove_pool` (indexed names and amounts), `Groove.*`
amounts get/set, `/live/clip/get|set/groove` by pool index or `-1`.

**Why:** named consumer — Seshat's generation work — and the curated
`Clip.groove` entry in FORK_GAPS is the one gap that keeps
`groove_amount` from having an effect on plain MIDI.

**Planner notes:**
- Source: `CLOSING_THE_GAPS.md`, row **D-2**.
- Measure whether `browser.load_item` can load an `.agr` into the pool.
- Depends on #6 (object-read pattern).

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
  are the inventory and the tripwire today; a generated, machine-checked
  one is only worth building once the test-suite item above has a
  contract layer to check it against. **Reopens when** that item ships and
  a doc/code drift is found that the unit layer didn't catch.
- The defect-shaped declines — the import-time reload in `tests/`, the
  `pythonosc` escape sequence — are in `issues.md` § Declined with their
  reopen conditions.
