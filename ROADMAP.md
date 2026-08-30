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

## #1 · Stop masking Remote Script import failures

**Goal:** a failed import of `Manager` inside Live surfaces the original
exception at startup, and the Live-free test layer imports what it needs
without a blanket `ImportError` guard in the Remote Script entry point.

**Why:** the package root swallows every `ImportError` so pytest can import it
without Live's modules; in Live the same guard hides a real missing dependency
or programming error, and `create_instance()` then fails with a `NameError` on
the undefined `Manager` instead of the actionable cause. Every handler PR here
is debugged through that startup path.

**Moved to the head of the queue on 2026-08-30, on a measured cost rather than
an argument.** An interrupted `mix abletonosc.install` left the install missing
`manager.py` and all of `pythonosc/`. Live's only report, across three restarts
and two distinct missing pieces, was:

```
error: RemoteScriptError:   File ".../AbletonOSC/__init__.py", line 9, in create_instance
error: RemoteScriptError: NameError: name 'Manager' is not defined
```

The same six words for a missing module and for a missing vendored package.
Both were found by diffing the install against the repo, never from the error.
The guard discards the one line that names the file, and the failure it hides
is not hypothetical — it is the ordinary outcome of an install that stops
part-way, which is a thing that now demonstrably happens.

**Planner notes:**
- Source: `issues.md`, "Stop masking Remote Script import failures" (Medium),
  plus the 2026-08-30 incident above.
- Small: root `__init__.py` plus whatever `tests_unit/conftest.py` needs to
  keep loading modules without Live. Check how the loader there imports today
  before choosing the guard's replacement.
- The guard exists for pytest, and that need is real — do not simply delete it.
  What it must stop doing is discarding the exception: log or re-raise with the
  original message and the module that failed, so the two cases above read
  differently.
- **A partial install is worth detecting on its own**, and cheaply: `manager.py`
  and `pythonosc/` are the last things `mix abletonosc.install` copies, so
  their absence is the signature of an interrupted run. A startup check that
  names them beats any improvement to the traceback. The install task's lack of
  atomicity is a Seshat defect and belongs in that repository, not here — but
  the bridge should still fail legibly when handed a half-installed tree.
- No dependencies.

## #2 · One `/live/song/undo` does not revert an OSC-created scene

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

## #3 · Walk a live instance graph, not only the class graph

**Plan:** [docs/PLAN_lom_instance_walk.md](docs/PLAN_lom_instance_walk.md) —
planned 2026-08-30 as one item merged with the read-half sweep in
[docs/HANDOFF_tier_2_measurement.md](docs/HANDOFF_tier_2_measurement.md).

**Goal:** a dump taken by traversing real Live objects — from
`get_application()` and `song` through tracks, devices, chains, drum pads and
parameters — recording each object's **actual type** and members, against a set
holding one of every device. Its output answers two questions the class walk
cannot: which classes appear only as some property's value type, and what
surface a given device type actually carries.

**Why:** `dir(cls)` returns the static Boost.Python registration. Two things
this repository needs are not in it.

**First, it is now the only remaining check on the walked class list.** Every
static channel is exhausted: `dir(Live)` was read from a running Live 12.4.5 on
2026-08-30 and is exactly the 43 modules the walk covers; method signature
types resolve 56 of 61; and the shipped binary turned out to be a *superset* of
the Python API rather than a source of missed surface. The one hole none of
those can reach is a class reachable only as a **property's** value type —
because properties carry no type information anywhere in the interpreter
(`Q1 properties=894 with_fget=894 fget_doc=0`). `Song.tracks` documents itself
as *"Const access to a list of all Player Tracks"*: prose, no type. The only
way to learn what it holds is to hold a `Song` and look.

**Second, member-level coverage is not object-level coverage.**
`Live.Device.Device` being fully covered does not make every device fully
reachable, and the coverage goal is stated in terms of the second. Which
`DeviceParameter`s a Wavetable carries, which `View` members a given device
type exposes, which racks have chains or drum pads, and the value set of
`class_name` — the list of device types Live ships — appear nowhere in any
inventory this repository generates.

**Planner notes:**
- Source: BLIND_SPOTS.md blind spot 5, which carries the probe output and
  records blind spot 4's unanswered half migrating here.
- **The curated set is the deliverable's precondition, and it is the expensive
  part.** A walk over the user's working set measures that set, not Live.
  Decide what "one of every device" means, how the set is version-controlled or
  described, and what the dump records about which set produced it — a dump
  that does not name its set cannot be compared against the next one.
- Read-only by construction and it must stay that way: `type()`, `dir()` and
  attribute reads only, no instantiation, no loading devices from the browser
  mid-walk. Reading `master_track.mute` raises `RuntimeError` rather than
  returning falsy, so every read needs its own `try`/`except` — `hasattr` is
  not a safe feature test on LOM objects. That rule is in API.md's measurement
  section and this walk will hit it constantly.
- Recursion needs a cycle guard on `id()` and a depth bound: the object graph
  has `canonical_parent` back-edges the class walk never had to handle.
- Output has to merge with the existing inventory rather than replace it —
  `tools/lom_gaps.py` and `tests_unit/test_lom_gaps.py` both key off the
  current dump shape, and the walked totals move again.
- The probe rig in API.md § "Measuring the Live API without building the
  feature first" is the delivery channel for the first run. Note issue #35 on
  its state, and note that a broken or partial install reports as
  `NameError: name 'Manager' is not defined` and nothing more — see the item on
  masked import failures.
- Depends on nothing, but is worth far more after the masked-import item lands,
  because this is the item most likely to be developed through repeated
  install-and-reload cycles.

## #4 · Make a failed live code reload safe and reported

**Mostly shipped.** The reporting half landed with the `introspection` reload
abort fix; what remains is narrow and is recorded below rather than deleted.

**What shipped:** `reload_imports` names its modules as strings through a local
`_reload()` helper and tracks the one in flight, so a failure is logged at
`error` level naming the module it stopped at, and a partial reload is reported
as partial instead of as `Reloaded code`. Because `start_logging()` attaches
`LiveOSCErrorLogHandler` to the `abletonosc` logger at `ERROR` level, that log
line is also what carries the failure to the client, as `/live/error`
`"log", ...` — the "reaches the client rather than only the log file" half of
the original goal, with no change to `/live/api/reload`'s wire contract.
`tests_unit/test_reload_list.py` is the Live-free tripwire for the list's
shape.

**The exempt-module question is answered:** `abletonosc.midimap` stays
unreloaded for the class-identity reason recorded beside `RELOAD_EXEMPT` in
`manager.py`. `abletonosc.constants` is also explicitly restart-only:
`OSCServer` copies the listen and response ports into instance state and binds
its socket in `Manager.__init__`, and `reload_imports()` never replaces that
server. Reloading `constants` before `osc_server` would update class defaults
but leave both ports of the running instance unchanged while reporting
success. A port edit therefore requires a Remote Script restart.

**What remains:** the original goal's first clause — "a reload that raises does
not activate a partially reloaded module graph". It is **not achievable as
written** and should be re-scoped or closed rather than planned: `importlib.reload`
mutates module objects in place, so once the sequence has run part-way there is
no previous graph left to preserve; `clear_api()` / `init_api()` still run,
deliberately, because a server with no handlers registered is strictly worse
than one built from a mixture (see the second problem under `API.md`'s
`/live/api/reload` warning — a teardown that raises leaves zero addresses and
no way to re-register them). A genuine fix would have to reload into a scratch
namespace and swap on success, which is a much larger change than this item
describes. Decide whether that is worth doing; if not, close the item.

**Planner notes:**
- Source: `issues.md`, "Make live code reload ordered and failure-safe"
  (Medium-high). Both the ordering half and the reporting half have now
  shipped; narrow that `issues.md` entry to the scratch-namespace question
  above at ship time rather than deleting it.
- Every gap-closing PR (see `CLOSING_THE_GAPS.md`) uses reload during
  development; move this up if a future one hits it.
- No dependencies.

## #5 · Remove the process-global and shared-file risks from song structure export

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

## #6 · Add bounded log retention

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

## #7 · Document `song` in the handler constructor contract

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

## #8 · Verify wildcard fan-out against Seshat's `/live/device/` usage

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
- The device family gained one more pattern match since this item was
  written: `/live/device/replace_sample` is the only address a bare
  `/live/device/* <track> <device>` pattern matches, and on a non-Simpler it
  is a silent `_is_wildcard_skip` by design (the handler binds the Simpler
  method before it resolves the file name — `API.md` § "Handlers that name a
  file to read"). Include it in the audit rather than assuming the family is
  still only the parameter addresses.
- No dependencies; verification-only, and may resolve to "no action" without
  ever becoming a Python change here.

## #9 · `stop_listen` can leave a listener stranded when its collection shrinks

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

## #10 · Recover Live's argument names from the shipped binary

**Goal:** a tool that extracts the `arg()` name literals from Live's
Boost.Python registration table in the shipped binary, and a decision, per
address this fork already ships, about which of them belong in `API.md`.

**Why:** Boost.Python synthesises its signatures at runtime from C++ type info,
and the argument names are not in them. The dump therefore renders
`events_in_range( (Envelope), (float), (float) )` — three anonymous floats — for
a call whose parameters Live's own source names `from_time`, `from_pitch`,
`time_span`, `pitch_span`. The binary keeps those literals. This is the one
category of API information measured to exist in the binary and **not** to be
recoverable from a running Live, which is the whole of what is left of this
item.

**It is ranked last deliberately, and the measurement is why.** This entry
began as the #2 item, on the argument that a second inventory built by an
unrelated method could find surface the walk cannot reach. The prototype found
three candidates — a `TestUtilities` module with 43 free functions,
`last_played_level` with a full listener triplet, and
`can_select_scene_on_launch` — and a probe against Live 12.4.5 on 2026-08-30
found that **none of the three is reachable from Python**:

```
Q2 'TestUtilities' in dir(Live): False
Q2 import Live.TestUtilities FAILED: ModuleNotFoundError
Q3 last_played_level hits: NONE in any walked class
Q4 hasattr(Scene, 'can_select_scene_on_launch'): False
```

The registration table contains names Live does not expose to the Python API.
The premise "a name in the binary that the walk missed is a hole in the walk"
is therefore false in the general case, and the yield of a binary diff is much
lower than it appeared. Argument names survive as a real result because they
are about addresses the fork already ships, not about reaching new ones.

**Planner notes:**
- Source: BLIND_SPOTS.md blind spot 3 and its 2026-08-30 correction, which
  carries the probe output and the prototype's method.
- Method that worked, and its numbers: `strings -a` over
  `/Applications/Ableton Live 12 Suite.app/Contents/MacOS/Live` (universal
  binary — every string appears twice). Segmenting on `Live.X` markers fails;
  there are 30 markers for 43 modules and the big blocks over-absorb, yielding
  9,350 names of Python-stdlib and OpenSSL noise. Locality-anchoring works:
  anchor on the 2,354 lines matching a name the walk already knows, grow
  regions while anchors stay within 25 lines, report unknown identifiers
  inside. 16 regions, 173 names, most of them the `arg()` literals this item
  now exists to harvest.
- The 25-line gap and 40-line region floor were picked to make the output
  readable. Sweep them and report what changes rather than shipping the first
  values that produced a tidy list.
- **Attribution is the hard part and adjacency does not give it.** The block
  ending at the `Live.WavetableDevice` marker holds names that are plainly not
  Wavetable's; Boost.Python string layout is per-translation-unit, not
  per-module. Any name this tool emits must be tied to an address by a human
  reading the surrounding docstrings, which is why the deliverable is a review
  queue and a set of `API.md` edits, not a generated table.
- Everything it emits is tier 1 and must be confirmed against a running Live
  before it reaches `API.md` — the three findings above are the standing
  demonstration of why.
- No dependencies. Small, and worth doing only when someone is already editing
  the argument documentation for a family of addresses.

---

## Deliberately not planned

Work weighed and declined, each with the condition that would reopen it.
**Coverage buckets are not listed here** — every gap in `FORK_GAPS.md` is in
scope, and the order they are worked in is `CLOSING_THE_GAPS.md`'s, headed by
the device path resolver (alone, no scalar padding), then the Arrangement and
take-lane clip resolver. A bucket appears in this file as a numbered item when
it is picked up, not before.

- **Walk the type graph, not the namespace.** Proposed 2026-08-30 as the head
  of this queue, on the argument that the walker reaches types by name and so
  cannot see a class Live only ever returns or accepts. Measured before
  planning, and declined on the measurement. Two channels, both empty:
  **methods** — Live names 61 distinct types in its signatures, 56 already
  resolve to a walked entry, and 4 of the remaining 5 are parse artefacts
  (`note`, `tb`, `un`, `StartupDialogServes`); **properties** — the hypothesis
  was that Boost.Python keeps the getter's return type on `fget.__doc__`, where
  `_classify()` never looks. A probe against Live 12.4.5 on 2026-08-30 killed
  it outright: `Q1 properties=894 with_fget=894 fget_doc=0 fget_signature=0`.
  Every property has a getter and **not one carries a docstring**, so there is
  no type edge to follow for the 894 members that make up most of the LOM
  surface. There is nothing for a closure to close. **Reopens when** a Live
  version ships property getters that carry docstrings — re-run the same four
  counts to check — or when a class is found that is genuinely reachable only
  through a return value, which would be evidence the method channel is not as
  closed as the 56-of-61 says.
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
