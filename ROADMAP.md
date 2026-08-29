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

**The goal is full Live Object Model coverage.** Every gap in
[FORK_GAPS.md](FORK_GAPS.md) is work this repository intends to do, and
[CLOSING_THE_GAPS.md](CLOSING_THE_GAPS.md) holds the bucket queue it comes off
in. Items arrive here as their bucket comes up; nothing is out of scope for
want of a downstream consumer asking for it. The one standing exception is
surface held out on **safety** grounds, which stays out on its own argument.

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

## #1 · The clip↔groove assignment contract is broken in both directions

**Plan:** [docs/PLAN_clip_groove_assignment_contract.md](docs/PLAN_clip_groove_assignment_contract.md)

**Goal:** `/live/clip/get/groove` distinguishes "no groove assigned" from
"pool index 0", and `/live/clip/set/groove` either clears an assignment or
stops claiming it can. API.md's "one sanctioned exception to `-1` is an
answer, never an argument" is then either true as written or withdrawn.

**Why:** measured against Live 12.4.5 on 2026-08-29, both halves of the
contract shipped in the Groove item fail:

- `set/groove -1` raises rather than clearing. `clip.groove = None` is
  rejected by Live — `Boost.Python.ArgumentError: ... did not match C++
  signature: None(TPyHandle<AClip>, TPyHandle<AAbstractGroove>)` — so the
  clear answers `/live/error` and the clip keeps its groove
  (`abletonosc/clip.py:494`). Live's setter wants a groove handle and has no
  known spelling for "none".
- `get/groove` never answers `-1`. A freshly created clip with no groove
  reads `0`, the same value as a clip explicitly assigned to pool index `0`;
  confirmed on two clips, before and after an explicit `set/groove 0`.
  `groove_index`'s `==` scan (`abletonosc/groove.py`) matches the absent
  groove against `grooves[0]`, so `NO_INDEX` is unreachable.

Together these make `get/groove` → `set/groove` actively harmful rather than
merely lossy: replaying a read taken from an ungrooved clip **assigns** it
pool groove 0. The Groove item's stated purpose was making `Song.groove_amount`
mean something on sets where no human had dragged a groove onto a clip, and a
consumer doing that from a mirror will groove clips it never meant to touch.

**Planner notes:**
- A regression introduced by the Groove item (PR #22, merged 2026-08-29), not
  a pre-existing gap. The plan listed `clip.groove = None` as an open question
  and the PR review accepted it as documented-but-unmeasured; the first Live
  run disproved it.
- Two separable fixes, and the read is the more urgent: a wrong "which groove"
  answer silently corrupts sets through the round trip, while a failing clear
  is at least loud. Do not fix only the setter.
- For the read, establish what `clip.groove` actually returns for an ungrooved
  clip before choosing an approach — whether it is a null handle that compares
  equal to any pool member, or a distinct "empty groove" object. `==` on
  Boost.Python proxies is the suspect; identity (`is`) against pool members, or
  a truthiness/None check before the scan, are the obvious candidates. Whether
  a set with several pool grooves changes the picture is worth one probe: the
  measured set had exactly one.
- For the clear, find out whether Live accepts anything as "no groove" — an
  empty `AAbstractGroove` handle, a pool sentinel — before deciding. If
  nothing works, the honest outcome is withdrawing `-1` as an argument,
  deleting the exception from API.md § "Object-valued reads", and saying
  plainly that assignment is one-way over this bridge.
- Whatever lands, the `tests_unit/` fakes need to stop modelling
  `clip.groove = None` as working, since they are what made this look green.
- Source: the Live verification run of 2026-08-29, recorded in API.md's Clip
  and Groove sections.

## #2 · `/live/application/get/has_option` documents a contract Live does not implement

**Goal:** `/live/application/get/has_option` either answers a question a caller
can actually ask, or is removed. API.md stops describing it as an Options.txt
query.

**Why:** it was shipped as "whether an Options.txt option is active", with the
option name handed to Live unmodified. Measured against Live 12.4.5 on
2026-08-29, `Application.has_option` is not that function at all: it accepts
**exactly 64 hexadecimal characters** and nothing else. A non-hex string raises
`Key contains non-hex characters`; a hex string of any other length — 63, 40,
32, 16, 8 — raises `basic_string`. Both reach the client as `/live/error`. No
Options.txt name is expressible, so every documented use of this address fails,
and a client following API.md gets an error for a correctly formed request.

**Planner notes:**
- A defect introduced by the Application dialogs and versions item (PR #18,
  merged 2026-08-29). The plan flagged "what form `has_option` expects" as an
  open question and shipped the guess as documentation.
- Establish what the 64-hex key *is* before deciding the address's fate — the
  shape (32 bytes, hex) and the "Key" wording in Live's own error suggest a
  hash or licence/feature key rather than anything a Remote Script caller can
  compose. If a caller cannot construct one, the address is not useful and
  removing it beats documenting a trap.
- If it stays, the argument needs validating at the handler rather than
  passed through to a C++ exception: 64 hex characters or a structured
  `/live/error` naming the requirement.
- Whatever lands, the ⚠️ correction already in API.md's Application table must
  be replaced by the real contract, and `tests_unit/test_application.py`'s
  `has_option` cases pin only the echo shape today — they pass against a
  function that can never succeed.
- Source: the Live verification run of 2026-08-29, recorded in API.md's
  Application section.

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

## #4 · Make a failed live code reload safe and reported

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
- Every gap-closing PR (see `CLOSING_THE_GAPS.md`) uses reload during
  development; move this up if a future one hits it. The fork-gaps series
  that motivated this note is finished — `CLOSING_THE_GAPS.md`'s Tiers A–D
  still have open rows, but none is currently ranked in this file.
- No dependencies.

## #5 · Stop masking Remote Script import failures

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

## #6 · Remove the process-global and shared-file risks from song structure export

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

## #7 · Add bounded log retention

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

## #8 · Document `song` in the handler constructor contract

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

## #9 · Verify wildcard fan-out against Seshat's `/live/device/` usage

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

## #10 · `stop_listen` can leave a listener stranded when its collection shrinks

**Goal:** stopping a listen on an indexed family (`/live/groove/stop_listen/*`,
`/live/scene/stop_listen/*`, and any future one built the same way) always
unbinds the actually-subscribed listener, even when the index named in the
`stop_listen` call has since moved past the end of a collection that shrank
after `start_listen` — instead of raising `/live/error` before unbinding runs
and leaving the listener registered with no address left able to remove it.

**Why:** flagged in pr-review of `feat/groove` (2026-08-29). Every one of
these handlers resolves-then-unbinds: the index is validated against the
collection's current size first, and only then does `_stop_listen` look up
the real subscribed object in `listener_objects` (which is index-independent
once bound). If the collection has shrunk below the subscribed index in the
meantime, validation raises before `_stop_listen` ever runs, so the listener
that started when the index was valid can never be stopped through that
address again — a subscription leak. Confirmed present in `groove.py` and
`scene.py`; not a groove-specific regression, so out of scope for the D-2
Groove PR that surfaced it.

**Planner notes:**
- Source: pr-review nit on `feat/groove` (2026-08-29), non-blocking, declined
  for that PR as fork-wide and beyond a single item's scope — recorded here
  rather than fixed blind in one family.
- Reproduce Live-free first: `/live/groove/start_listen/name <index>`, pop
  grooves from the pool until `<index>` is past the end, then
  `/live/groove/stop_listen/name <index>` — expect `/live/error` and the
  listener still bound. Check `scene.py`'s equivalent for the same shape
  before concluding it's one bug rather than two independent copies.
- Likely fix is an order-of-operations change in the shared `_stop_listen`
  path (or its callers): attempt the unbind by identity first, and only
  surface a validation error if there is nothing registered to unbind under
  that key. Verify this doesn't change behaviour for the legitimate
  never-started case, which should still be a no-op or an error as today.
- No dependencies.

---

## Deliberately not planned

Work weighed and declined, each with the condition that would reopen it.
**Coverage buckets are not listed here** — every gap in `FORK_GAPS.md` is in
scope, and the order they are worked in is `CLOSING_THE_GAPS.md`'s, headed by
the device path resolver (alone, no scalar padding), then the Arrangement and
take-lane clip resolver. A bucket appears in this file as a numbered item when
it is picked up, not before.

- **`Application.press_current_dialog_button`** — the one piece of Live API
  surface held out of the coverage goal, and held out on safety: a dialog on
  screen may be guarding unsaved work, and pressing its buttons blind is not
  recoverable. The same decision is why the two `show_*` addresses raise
  OK-only dialogs. **Reopens when** a separately reviewed, non-file use case
  proves it safe.
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
  value forever and that Seshat would have to tripwire for no return. Not a
  coverage gap: `Song.master_track` is already reachable, so this is address
  redundancy, not missing surface. **Reopens when** the identity convention
  changes such that the reply is no longer a constant; a five-line follow-up.
