**Archived 2026-08-27 — shipped.** This is the plan as written *before*
implementation; the code as merged may differ. The change lives in `tests/`
(rewritten, fixture-isolated, opt-in via `ABLETONOSC_LIVE_TESTS=1`),
`tests_unit/` (the permanent Live-free gate, now including
`test_live_suite_inert.py`'s tripwire), and `client/client.py` (loopback-only
bind), plus the new `pytest.ini`, `requirements-dev.txt`, and
`.github/workflows/test.yml`; no `API.md` rows — no address, request-shape,
or reply-shape changed. Live verification checks 1 and 2 ran and passed;
checks 3 and 4 (the full opt-in run, audio-recording skip honesty) stayed
deferred — they need Seshat stopped and the Remote Scripts copy reinstalled,
both out of bounds for this environment — and remain open, unassigned to any
roadmap item.

# Plan: Make the test suite safe, isolated, and usable as a regression gate

Roadmap item: **Make the test suite safe, isolated, and usable as a
regression gate** (source: `issues.md`, same title, High). No dependencies;
roadmap's device-listener, DeviceParameter and notes-extended items depend
on this one. This item also reopens — and resolves — the Declined entry
"The Python test harness reloads AbletonOSC on import" (`issues.md`
§ Declined), whose reconsider condition is exactly this work.

## Context

The repository has two test trees with opposite characters:

- **`tests_unit/`** — 68 passing, Live-free tests driving the real
  `osc_server.py`, `handler.py` and `track_callback.py` through
  `conftest.py`'s synthetic-root loader. It already exercises all four
  clauses of the roadmap Goal's contract layer: routing
  (`test_osc_server.py` wildcard/dispatch), validation and error envelopes
  (`test_handler_envelope.py`, the fan-out isolation tests), reply shapes
  (tuple/list/None contracts), and listener bookkeeping
  (`test_handler_lifecycle.py`, `test_track_callback.py`). Research
  finding: the "unit/contract layer" half of this item is already built —
  it accreted over the previous fork PRs. What it lacks is *standing*:
  nothing makes it the default suite, nothing runs it automatically, and
  nothing stops the dangerous tree from being collected by accident.

- **`tests/`** — upstream's 30 Live-integration tests. `tests/__init__.py`
  constructs an `AbletonOSCClient` and sends `/live/api/reload` **at module
  scope**, so `pytest --collect-only` from the repo root mutates a running
  Live. The client binds `0.0.0.0:11001` — wider than the fork's
  loopback-only policy, and a collision with Seshat, which owns that port
  whenever it is running. The tests hard-code a blank default set (exactly
  4 tracks, 8 scenes, empty slots, no devices on track 0), leave mutated
  state behind on failure (tempo, names, created clips/scenes), and one
  fixture records live audio (arms track 2 and fires an empty slot).
  `CONTRIBUTING.md` tells contributors to run bare `pytest`, which today
  collects both trees and fires the reload.

There is no dependency manifest (pytest is the only requirement and it is
documented only in a comment in `tests_unit/__init__.py`) and no CI —
`.github/` holds only issue and PR templates.

Key constraints research surfaced:

- **`tests_unit/` must keep its name and invocation.** `python3 -m pytest
  tests_unit/` is cited as the gate by `SESHAT.md`'s merge hazards, the
  archived plans, and the repo's own workflow tooling. The earlier note in
  `tests_unit/__init__.py` that this item "owns folding this into a
  restructured tests/ tree" is superseded: the two-tree layout is the
  decision, and that comment is updated by this plan (Part 4).
- **The live suite can only ever run when Seshat is down**, because
  AbletonOSC replies to `127.0.0.1:11001` unconditionally
  (`osc_server.py`'s `remote_addr` default) and Seshat's `beam.smp` holds
  that port. This is a feature: the port conflict *is* the interlock that
  prevents the suite from stealing Seshat's listeners (the
  `stop_listen`-on-tempo hazard). The client fixture turns the bind
  failure into an explicit skip instead of an error.
- **The live suite is not runnable in this development environment right
  now** (Seshat holds 11001, and the install/restart cycle is out of
  bounds), so the `tests/` rewrite ships verified by inspection plus the
  Live-free inertness checks, with the full live run documented as the
  deferred verification step. The *skip* paths, by contrast, are all
  verifiable here.

## Wire contract

**No address is added, changed, or removed.** No `API.md` rows. The suite
relies on existing addresses exactly as documented; the ones the new
harness code (fixtures, discovery, restore helpers) depends on, all
unchanged:

| Address | Use in the harness |
|---|---|
| `/live/test` | liveness probe in the session fixture (reply `["ok"]`) |
| `/live/api/reload` | sent once per opted-in session, from the fixture, no longer at import |
| `/live/song/get/num_tracks`, `/live/song/get/num_scenes` | set-shape discovery (replace hard-coded 4/8) |
| `/live/return_track/get/count` | send-count discovery for the sends test |
| `/live/track/get/has_midi_input`, `/live/track/get/has_audio_input` | picking a MIDI/audio track for clip fixtures |
| `/live/clip_slot/get/has_clip` | empty-slot discovery and recording verification |
| `/live/error` | still the error channel; `tests/test_application.py` asserts its envelope |

The client's reply-port contract is untouched: AbletonOSC always answers to
`127.0.0.1:11001`; the client's default `client_port=11001` stays. The only
client change is the *bind address* (`0.0.0.0` → `127.0.0.1`), which is
invisible on the wire for a loopback server.

## Parts

### Part 1 — Defuse `tests/` and gate it behind an explicit opt-in

Files: `tests/__init__.py`, new `tests/conftest.py`, new `pytest.ini`.

- `tests/__init__.py`: delete the module-scope `AbletonOSCClient()`
  construction and `/live/api/reload` send, and the `client` fixture (it
  moves to `conftest.py`). Keep `wait_one_tick()` and the `TICK_DURATION`
  re-export — they are pure, and every test module imports them from the
  package. Replace `sys.path.append(".")` (cwd-dependent) with an insertion
  of the repo root derived from `__file__`, **in `tests/__init__.py` itself,
  above the `from ..client import` line** — not in `conftest.py`: pytest
  imports `tests/conftest.py` as a submodule of the `tests` package, so
  `tests/__init__.py` (whose `..client` import pulls in the vendored
  `pythonosc`) executes before any conftest code runs (verified empirically
  at plan review, 2026-08-27). `conftest.py` therefore carries no path
  logic; it imports the client via the package
  (`from . import AbletonOSCClient` or `from ..client import ...`).
- New `tests/conftest.py`:
  - `pytest_addoption` is not needed; the gate is the environment variable
    **`ABLETONOSC_LIVE_TESTS=1`** — it works identically for `pytest
    tests/`, bare `pytest tests`, and IDE runners, with no rootdir
    subtleties.
  - A **session-scoped `client` fixture** that, in order: skips the whole
    session unless `ABLETONOSC_LIVE_TESTS=1` is set (reason names the
    variable); constructs `AbletonOSCClient()`, translating a bind
    `OSError` on 11001 into a skip naming the likely holder ("reply port
    11001 in use — stop Seshat or whatever holds it; Seshat's e2e suite
    owns this port when it is running"); probes liveness with
    `query("/live/test")` and skips on timeout ("Live not running, or
    AbletonOSC not installed / not loaded"); then sends `/live/api/reload`
    and re-probes `/live/test` until it answers again (the reload tears the
    server down and rebinds). Teardown stops the client. Every test in
    `tests/` reaches the network only through this fixture, so the gate
    covers the entire tree.
- New `pytest.ini` at the repo root:

      [pytest]
      testpaths = tests_unit

  Bare `pytest` from the repo root now collects only the Live-free gate.
  `pytest tests/` still works (explicit args override `testpaths`) and is
  itself inert without the environment variable.
- Documentation, same commit: `SESHAT.md` § Divergences gains a "Test
  harness" entry covering the `tests/` restructure (upstream files edited:
  `tests/__init__.py` and every `tests/test_*.py`; new fork files:
  `tests/conftest.py`, `pytest.ini`) and § Merge hazards gains a bullet:
  *anything touching `tests/__init__.py`* — a merge that takes upstream's
  version restores the import-time reload; the Part 4 tripwire test fails
  loudly on it. Also `API.md` § "Measuring the Live API without building the
  feature first": rewrite its final bullet ("The committed pytest suite is
  not this: its client binds `0.0.0.0:11001` … See `issues.md`, …") to
  describe the *new* state — loopback bind, import-inert, opt-in via
  `ABLETONOSC_LIVE_TESTS=1`, still not a substitute for the log-file probe
  method — since the current text documents the defect this item removes and
  cites the `issues.md` entry that ship deletes.

### Part 2 — Loopback-only client bind

Files: `client/client.py`, `SESHAT.md`.

- `AbletonOSCClient.__init__`: bind `ThreadingOSCUDPServer` to
  `("127.0.0.1", client_port)` instead of `("0.0.0.0", client_port)`. The
  server only ever sends to loopback, so nothing is lost; the fork's
  loopback-only policy (SESHAT.md's security section) now holds for the
  bundled client too. Let the bind `OSError` propagate — Part 1's fixture
  is the place that turns it into a skip; `run-console.py` users get the
  raw, accurate error.
- Documentation, same commit: `SESHAT.md` divergence entry (edit to an
  upstream file), folded into the Part 1 "Test harness" entry.

### Part 3 — Fixture isolation, discovery, and self-restoration in `tests/`

Files: `tests/conftest.py` (helpers), `tests/test_song.py`,
`tests/test_track.py`, `tests/test_clip.py`, `tests/test_clip_slot.py`,
`tests/test_view.py`, `tests/test_application.py`, `tests/test_bundle.py`.

Shared harness in `tests/conftest.py`:

- **Discovery fixtures**: `num_tracks`, `num_scenes` (session-scoped
  queries), and a `require(condition, reason)` helper that calls
  `pytest.skip` — tests state their preconditions instead of assuming the
  blank template.
- **`restored_song_property(client, name)` / `restored_track_property
  (client, track_id, name)`** context managers: query the current value
  first, yield, restore it in `finally`. The `_test_song_property` /
  `_test_track_property` / `_test_clip_property` loops run inside them, so
  a failing assertion no longer strands the set at the test value.
- **Clip fixtures** replacing `test_clip.py`'s module-scoped autouse
  `_create_test_clips`:
  - `midi_clip` — find the first track with `has_midi_input` true and an
    empty slot 0..N (via `has_clip`), create a clip there, yield
    `(track_id, clip_id)`, delete it in teardown. Skip if no such slot.
  - `audio_clip` — find a track with `has_audio_input` true and an empty
    slot; save the track's `arm` state, arm, fire the slot, wait, stop
    playback and all clips, restore `arm`; then **verify `has_clip`** and
    skip ("audio recording did not produce a clip — check audio input
    device and Count-In preference") if it didn't. Teardown deletes the
    clip if present. Only `test_clip_property_gain` / `pitch_coarse` /
    `pitch_fine` request it; the MIDI-only tests no longer depend on audio
    recording at all (today the autouse fixture makes every clip test
    require it).
- **No global undo-step wrapper.** `begin_undo_step`/`end_undo_step`
  around each test was considered and rejected: `test_song_undo_redo`
  drives `undo`/`redo` itself and an open undo step would interact with it
  unpredictably. Restoration is per-fixture `finally` logic instead —
  deterministic and assertion-failure-safe.

Per-file rewrites (mechanical, preserving each test's substance):

- `test_song.py`: `num_tracks`/`num_scenes` assertions become
  relative-to-baseline (query before, assert `baseline + 1` after create,
  delete in `finally`). `test_song_duplicate_scene` derives its scene index
  from `num_scenes` and cleans up in `finally`. Property tests run under
  `restored_song_property`. `test_song_undo_redo` deletes the created scene
  in `finally` guarded by a fresh `num_scenes` query.
- `test_track.py`: `require(num_tracks >= 3)` where track 2 is used;
  the sends test discovers `/live/return_track/get/count` and skips below
  2; `test_track_clips` builds its expected tuple from `num_scenes` and
  deletes clips in `finally`; `test_track_devices` asserts the reply
  envelope (`(track_id, n)` with `n >= 0`) instead of the blank-set `0`;
  the `playing_slot_index` listener test stops both listeners and deletes
  its clips in `finally`, and restores `clip_trigger_quantization` (it
  currently leaves 1/16 quantize behind).
- `test_clip.py` / `test_clip_slot.py`: use the clip fixtures; indices come
  from the fixtures, not literals; each create is paired with a delete in
  `finally`; `test_clip_slot_duplicate` picks its destination slot by
  `has_clip` discovery.
- `test_view.py`: query the current selection first and restore it in
  `finally`; choose selectable indices from discovery
  (`require(num_scenes >= 2)` etc.); `test_selected_clip` selects a clip
  created via `midi_clip` rather than assuming `(3, 4)` holds one.
- `test_application.py`, `test_bundle.py`: already read-only; only the
  import of the removed `client` symbol changes (the fixture now resolves
  from `conftest.py`).

Documentation, same commit: covered by the Part 1 SESHAT.md entry (these
are the "every `tests/test_*.py`" edits it names).

### Part 4 — Live-free inertness tripwire and `tests_unit/` header update

Files: new `tests_unit/test_live_suite_inert.py`, `tests_unit/__init__.py`.

- New test, `ast`-based (no import of `tests/`, no sockets): parse every
  `tests/*.py` and assert that no **module-scope** statement (descending
  into top-level expressions but not into `def`/`class` bodies) contains a
  call to `AbletonOSCClient`, nor an attribute call named `send_message`,
  `send_bundle`, `query`, or `await_message`. This is the regression guard
  for the exact defect this item removes: an upstream merge that restores
  `tests/__init__.py`'s import-time reload turns the Live-free gate red.
  (Technique mirrors the roadmap's planned `ast` check for handler
  `class_identifier`s; the two tests can share style but not code.)
- `tests_unit/__init__.py`: replace the "The test-suite item in issues.md
  owns folding this into a restructured tests/ tree" sentence with the
  settled layout: `tests_unit/` is the permanent Live-free gate;
  `tests/` is the opt-in live-integration suite, gated by
  `ABLETONOSC_LIVE_TESTS=1`.
- Documentation, same commit: the Part 1 merge-hazard bullet points at this
  test by name.

### Part 5 — Dependency manifest and CI

Files: new `requirements-dev.txt`, new `.github/workflows/test.yml`.

- `requirements-dev.txt`:

      pytest>=7,<9

  pytest is the suite's only dependency beyond the standard library (the
  `tests_unit/__init__.py` comment already records the verified versions).
  ruff is *not* introduced: the repo has no lint config or lint gate, and
  inventing one here is scope creep (see Out of scope).
- `.github/workflows/test.yml`: on `push` to `master` and `pull_request`;
  matrix Python `3.11` (Live 12's bundled major.minor) and `3.12` (the
  locally verified version); steps: checkout, setup-python,
  `pip install -r requirements-dev.txt`, then three commands that are each
  a distinct guarantee:
  1. `python -m pytest tests_unit/` — the gate itself.
  2. `python -m pytest` — proves bare `pytest` collects only `tests_unit/`
     (the `pytest.ini` guarantee).
  3. `python -m pytest tests/ -q` — with no `ABLETONOSC_LIVE_TESTS` set,
     must exit 0 with every test skipped on a Live-less runner: proves the
     live tree imports cleanly and stays inert without opt-in.
- Documentation, same commit: SESHAT.md "Test harness" divergence entry
  notes the two new fork-only files.

### Part 6 — Contributor documentation

Files: `CONTRIBUTING.md`.

Rewrite the Tests section around the two suites:

- `python3 -m pytest tests_unit/` — the default, Live-free gate; run it
  before every commit and on every upstream merge; needs only
  `pip install -r requirements-dev.txt`.
- `ABLETONOSC_LIVE_TESTS=1 python3 -m pytest tests/` — the opt-in live
  suite; preconditions listed honestly: Live running with AbletonOSC
  installed *and current* (files on disk are not code in memory — restart
  or `/live/api/reload` after copying), reply port 11001 free (stop
  Seshat), a set you are willing to have mutated, and — for the three
  audio-clip tests only — a configured audio input device (Count-In ≠ None
  makes the recording fixture skip, no longer fail).
- Fix the `/live/reload` → `/live/api/reload` line in the Live-reloading
  section (the "Deliberately not planned" doc item licenses exactly this:
  a line fixed in passing by a PR already touching the file).
- Documentation, same commit: the CONTRIBUTING.md edit is itself an
  upstream-file edit — named in the Part 1 SESHAT.md divergence entry.

## Testing

`python3 -m pytest tests_unit/` remains the only gate and must stay green
(68 tests today, 69+ after Part 4). What it covers of this item:

- The new inertness tripwire (Part 4) — the only production-shaped code
  this item adds to the gate.
- Everything it already covered — routing, validation, reply shapes,
  listener bookkeeping — untouched by this item.

What it does not cover: the rewritten `tests/` bodies and `client/client.py`
are live-only code by nature. Two of their properties *are* verifiable
Live-free, and the implementer runs both locally (they are CI steps 2 and 3):
bare `python3 -m pytest` collects only `tests_unit/`, and
`python3 -m pytest tests/ -q` without the environment variable exits 0,
all-skipped, sending nothing — safe to run even with Live up, which is
precisely the point of the change. As always, `tests/` handler code against
real LOM objects is untested here, and `tests/` is not part of the gate.

## Live verification

Precondition for all checks: the Remote Scripts copy equals this checkout
byte for byte and Live has been restarted since it was copied.

1. **Port-busy skip path** (runnable now, Seshat holding 11001):
   `ABLETONOSC_LIVE_TESTS=1 python3 -m pytest tests/ -q` → every test
   skips with the "reply port 11001 in use" reason. Evidence: pytest skip
   summary; no line appended to `logs/abletonosc.log` (no datagram was
   sent).

   **Observed 2026-08-27, PASS.** Live 12 running (pid 70216), Seshat's
   `beam.smp` bound to `127.0.0.1:11001`. `54 skipped in 0.02s`; every
   skip reason is "reply port 11001 is in use, so no reply can be
   received … ([Errno 48] Address already in use)". The installed copy's
   `logs/abletonosc.log` stayed at 209 lines across the run.
2. **Opt-out inertness with Live running** (runnable now):
   `python3 -m pytest tests/ -q` with the variable unset → all skipped,
   and `logs/abletonosc.log` gains no new lines during the run.

   **Observed 2026-08-27, PASS.** Same Live session. `54 skipped in
   0.04s`, exit status 0; `logs/abletonosc.log` unchanged at 209 lines.
   Bare `python3 -m pytest` from the repo root collected only
   `tests_unit/` (79 passed), confirming the `pytest.ini` guarantee that
   is CI step 2.
3. **The full opt-in run** (deferred until Seshat can be stopped): stop
   Seshat, `ABLETONOSC_LIVE_TESTS=1 python3 -m pytest tests/` against a
   scratch set. Evidence: the pytest report itself, plus post-run
   restoration checks — tempo, track 2's name/panning/volume/color,
   `clip_trigger_quantization`, selection, `num_tracks`/`num_scenes` all
   equal their pre-run values (each is a `query` before and after), and no
   `Adding listener` line in `logs/abletonosc.log` without a matching
   `Removing listener`.
4. **Audio-recording skip honesty** (same deferred run, audio input
   unplugged or Count-In set): the three audio-clip tests skip with the
   recording-failed reason instead of failing.

Remains uncovered until check 3 can run: the rewritten test bodies against
a real Live — shipped verified by inspection plus checks 1–2, which is an
accepted gap because the *default* path (what every contributor and CI
touches) is fully verified Live-free, and the opt-in path can only improve
on today's suite, which nobody can run safely at all.

## Downstream

**Pin bump only.** No address, request shape, reply shape, or listener
behaviour changes. Seshat's `vendored_addresses_test` greps unchanged
names. Seshat's own e2e coverage keeps sole ownership of port 11001 and
long-lived listeners — this item makes that boundary structural: the fork's
live suite now *skips itself* when Seshat holds the port. Nothing for
Seshat to change; the pin bump is bookkeeping.

At ship time (not Seshat, but recorded here so `/ship` sees it): remove
`issues.md`'s "Make the test suite safe, isolated, and usable as a
regression gate" entry **and** the Declined entry "The Python test harness
reloads AbletonOSC on import", which this item resolves. ROADMAP's
"Deliberately not planned" closing bullet ("The defect-shaped declines — the
import-time reload in `tests/`, the `pythonosc` escape sequence — …") must
drop its "import-time reload in `tests/`" mention in the same edit, or it
points at a Declined entry that no longer exists.

## Out of scope

- **ruff / lint gate** — no lint config exists; introducing a linter is a
  separate decision, not smuggled into a test item. Stays unranked unless
  someone proposes it.
- **Growing `tests_unit/` handler coverage** (production subclasses,
  `class_identifier` walk) — that is the roadmap's own next item ("Verify
  handler `class_identifier` and lifecycle invariants without Live");
  Part 4's `ast` test deliberately does not absorb it.
- **The root `__init__.py` blanket `ImportError` guard** — roadmap item
  "Stop masking Remote Script import failures" owns it; nothing here
  changes how `tests_unit/conftest.py` loads modules.
- **`/live/api/reload` ordering/failure-safety** — its own roadmap item;
  the session fixture uses reload as-is.
- **A generated endpoint-contract inventory** — "Deliberately not
  planned"; its reopen condition starts ticking once this item ships.
- **Making the live suite pass on arbitrary sets in this run** — the
  rewrite targets discovery and skips, but the deferred full run (Live
  verification, check 3) is where residual set assumptions surface; any
  found there are fixed in that follow-up, not padded for now.

## Open questions

1. ⚠️ **The full opt-in live run cannot be executed during this item's
   development** — Seshat holds 11001 and the install/restart cycle is out
   of bounds for this environment. Unresolvable now by policy, not by
   ignorance. The plan assumes the rewrite is correct by inspection,
   verified Live-free via CI steps 2–3 and the two runnable skip-path
   checks; Live verification check 3 is the deferred proof. Implementer:
   do run checks 1 and 2 — they need no port and no mutation. (Premise
   verified at planning time, 2026-08-27: `lsof -nP -iUDP:11001` shows
   Seshat's `beam.smp` bound to `127.0.0.1:11001`, so check 1's skip path
   is exercisable during implementation.)
2. ⚠️ **Whether firing an empty audio slot reliably records a clip on the
   user's setup** (audio input configured? Count-In?) cannot be verified
   without the deferred run. The plan removes the assumption instead: the
   `audio_clip` fixture verifies `has_clip` after firing and skips the
   three dependent tests when recording did not happen.
3. ~~GitHub Actions may need one manual enable on the fork~~ — **resolved
   at planning time** (2026-08-27): `gh api
   repos/jpatricknola/AbletonOSC/actions/permissions` returns
   `{"enabled": true, "allowed_actions": "all"}`, so the workflow will run
   on the first push/PR with no settings change.
