# Handoff: codebase review + live contract testing (2026-08-03)

A full review of this fork was done on 2026-08-03, combined with targeted
contract probes against a live Ableton instance. This file records what was
found, what was verified, how to reproduce the live-testing setup, and what to
do next. The review did not change source code or the Ableton project; this
handoff document is the only review artifact added to the working tree.

## What this repo is

`jpatricknola/AbletonOSC`, the Seshat fork of ideoforms/AbletonOSC. Read
[SESHAT.md](SESHAT.md) first: it lists every divergence from upstream and the
merge hazards, and is the file to keep current when a commit lands here.

## How the live tests were run (reproducible)

These were targeted OSC contract probes, not a run of the repository's pytest
suite. The running Live instance loads the *installed copy* at
`~/Music/Ableton/User Library/Remote Scripts/AbletonOSC` — `diff -rq` it
against this repo first; on 2026-08-03 they were identical (only `.github`,
`.gitignore`, `tests`, and this untracked handoff are unshipped, plus runtime
logs and bytecode exist only in the installed copy).

Replies cannot be captured directly: every reply goes to `127.0.0.1:11001`,
which is held by Seshat's `beam.smp` (no SO_REUSEPORT on its socket, so the
port cannot be shared; no sudo available for tcpdump or loopback aliases).
Instead, verify through the installed script's log:

- Send OSC to `127.0.0.1:11000` from a plain UDP socket (the vendored
  `pythonosc` builds messages: `OscMessageBuilder(addr).add_arg(x).build().dgram`).
- Read new bytes of
  `~/Music/Ableton/User Library/Remote Scripts/AbletonOSC/logs/abletonosc.log`
  after each send. `_get_property` / `_set_property` / `_call_method` log values;
  error paths log the offending address.
- Ok-paths of the custom handlers (return_track getters, browser get/items,
  is_view_visible) log **nothing** — probe counts via deliberate bad-index
  requests, whose error messages embed the count
  ("this set has N return track(s)").

Rules observed, and to keep observing:

- Wrap every mutation in `/live/song/begin_undo_step` / `end_undo_step` and
  restore state (tempo was set 120→97.5→120; a return track was created and
  deleted; the test export file was removed afterwards).
- Never `stop_listen` a property Seshat subscribes to — it holds song listeners
  on tempo, signature_numerator/denominator, is_playing, root_note, scale_name,
  groove_amount, swing_amount, tracks, return_tracks, and the master mixer
  params (grep the log for "Adding listener" to re-check). `metronome` was free
  and used for the listener round-trip.
- Stray replies land on Seshat's socket; keep test volume low.

### Why the committed pytest suite was not run

- `pytest` was not installed in the review environment.
- More importantly, the test client binds the fixed response port
  `0.0.0.0:11001`, which was already correctly held by Seshat. The port cannot
  be shared.
- Merely importing `tests` sends `/live/api/reload` at module scope, so even
  collection is not read-only.

The repository contains 54 pytest test functions, but they are stateful Live
integration tests rather than isolated unit tests. Do not describe the targeted
log-observed probes below as a full pass of those 54 tests.

## Confirmed bugs (verified against the running instance)

1. **Wildcard regex is unanchored — patterns match address prefixes.**
   [abletonosc/osc_server.py:142](abletonosc/osc_server.py#L142) uses
   `re.match` with no `$`. Verified: `/live/*/get/tempo 0` fired
   `/live/scene/get/tempo_enabled` as well as the two tempo handlers.
   `/live/track/get/*` likewise reaches `/live/track/get/clips/name`.
   Fix: `re.fullmatch` (and `re.escape` the literal segments).

2. **Wildcard fan-out aborts on the first `IndexError`.**
   [abletonosc/osc_server.py:147-158](abletonosc/osc_server.py#L147-L158)
   swallows only `ValueError`/`AttributeError`. Verified: `/live/*/get/tempo`
   with no args ran the song handler, then the scene handler's
   `int(params[0])` raised `IndexError`, aborting the remaining matched
   callbacks and landing in the legacy uncorrelated error path. Fix: add
   `IndexError` to the swallowed set (or catch `Exception` and continue).

3. **`/live/track/get/<prop>` with track id `"*"` returns only track 0.**
   [abletonosc/track.py:20-28](abletonosc/track.py#L20-L28) `return`s on the
   first non-None result. Verified: `/live/track/get/name *` produced exactly
   one invocation. Setters are unaffected (they return None). Fix: reply once
   per track inside the loop, or aggregate.

## Contract and architecture findings (not yet fixed)

4. **Error responses are only partly structured.** Direct callback exceptions
   become `["request", address, detail, arg_count, *args]`, but `_call_method`
   and `_set_property` catch their own exceptions
   ([abletonosc/handler.py:26-45](abletonosc/handler.py#L26-L45)). Those failures
   go through the legacy `["log", message]` relay without request correlation.
   Put endpoint exception handling at the dispatcher boundary so all failures
   share one contract.

5. **Reply validation can escape that error boundary.** The
   `assert isinstance(rv, tuple)` in
   [abletonosc/osc_server.py:134-135](abletonosc/osc_server.py#L134-L135) sits
   outside the try that produces the structured `/live/error`. Replace runtime
   asserts with explicit validation inside the boundary.

6. **Handler initialization is inverted.** `AbletonOSCHandler.__init__` calls
   the overridable `init_api()` before `listener_functions`, `listener_objects`,
   and `class_identifier` exist
   ([abletonosc/handler.py:13-16](abletonosc/handler.py#L13-L16)). Browser carries
   a workaround comment. Complete base initialization before registering routes.

7. **Regular, return, and master tracks do not share a coherent identity
   contract.** The fork can select a return or master track, but
   `/live/view/get/selected_track` looks only in `song.tracks`
   ([abletonosc/view.py:62-69](abletonosc/view.py#L62-L69)). It can therefore
   fail after a valid `/live/return_track/select` or `/live/master/select`.
   Define an explicit tagged identity such as `regular|return|master` plus index.
   Also note that `/live/view/set/selected_device` returns a tuple even though
   setters are documented as silent.

8. **Device parameter listener indices are not normalized.** The listener path
   never int-casts `params[2]`
   ([abletonosc/device.py:112-132](abletonosc/device.py#L112-L132)); a float index
   raises, and listener keys for `2` and `2.0` do not match reliably across
   start/stop calls.

9. **The old song-structure export mutates process-global state and uses a
   shared predictable file.**
   [abletonosc/song.py:214-225](abletonosc/song.py#L214-L225) sets
   `os.environ["TMPDIR"] = ""` for the whole Live process and writes a fixed
   path in shared tmp. Align it with browser.py's private-directory/`mkstemp`
   design, or remove it if Seshat does not use it.

10. **Reload can leave a mixed class graph.** `reload_imports` reloads
    `application`, `clip`, `clip_slot`, and `device` before their `handler` base
    ([manager.py:150-165](manager.py#L150-L165)). Reload `osc_server` and
    `handler` first. A reload exception is also logged and then followed by
    `clear_api()`/`init_api()` anyway, which can activate a partially reloaded
    graph; failure should leave the current API intact.

11. **The root import guard can mask the real Live startup failure.** The root
    [__init__.py:1-9](__init__.py#L1-L9) suppresses every `ImportError`, then
    `create_instance()` may reference an undefined `Manager`. Limit the pytest
    workaround to the known absent Live dependency or move test imports away
    from the Remote Script package root.

12. **Input validation uses asserts.** `set_log_level` uses `assert` and changes
    only the file handler ([manager.py:99-103](manager.py#L99-L103)). Asserts can
    disappear with optimized Python and invalid client input needs a normal
    structured error.

13. **Stray startup send.**
    [abletonosc/application.py:20](abletonosc/application.py#L20) sends an empty
    `/live/application/get/average_process_usage` datagram at startup. It looks
    like a malformed unsolicited reply; delete it.

14. **No log rotation.** `logs/abletonosc.log` was ~855KB at the end of review
    and grows on every getter. Use `RotatingFileHandler` in
    `Manager.start_logging`.

15. **Dead or experimental code increases the supported surface.**
    `introspection.py` is unused, contains a Python-2-era property check, and has
    a malformed logging call. `/live/clips/filter` and `unfilter`
    ([abletonosc/clip.py:195-246](abletonosc/clip.py#L195-L246)) have a cache that
    is never invalidated and a `note_name_to_midi` helper that returns pitch
    class rather than MIDI note. Delete these if Seshat does not use them.

16. Smaller: cue-point jump by an unknown name is a silent no-op while a bad
    numeric index errors; `osc_server.send` catches `BuildError` but not
    `OSError` from `sendto`.

## Test-suite findings

The current suite needs work before it can serve as a regression gate:

- [tests/__init__.py:30-32](tests/__init__.py#L30-L32) reloads the running
  Remote Script at import time. Move this into an explicit fixture or setup
  command.
- [client/client.py:29](client/client.py#L29) binds `0.0.0.0:11001`. Bind
  loopback, allow a configurable/dynamic port where the server contract permits,
  and make fixed-port ownership explicit for Seshat integration runs.
- [tests/test_application.py:14-17](tests/test_application.py#L14-L17) expects
  the old unstructured error payload and is stale after the structured-error
  change.
- [tests/test_clip_slot.py:32](tests/test_clip_slot.py#L32) stops a clip-slot
  listener with only the track index; the clip index is missing, so the test can
  leak that listener until reload.
- Tests assume exactly four tracks and eight scenes, modify playback and undo
  history, and require a configured audio input. Discover state, create uniquely
  named fixtures, wrap mutations in undo steps, restore in `finally`, and keep
  destructive live tests opt-in.
- The fork's browser, return/master-track, song-structure, swing, undo-step, and
  view extensions have little or no committed automated coverage.
- There is no dependency manifest or CI workflow. Add a `pyproject.toml` with
  pinned development dependencies.

Recommended test architecture:

1. Fast unit/contract tests with fake Live objects for dispatch, validation,
   reply shapes, wildcard behavior, and listener bookkeeping.
2. A small opt-in live smoke suite that discovers and restores current state.
3. Seshat end-to-end tests for fixed-port ownership, request correlation, and
   long-lived listeners.

## Documentation and organization findings

- CONTRIBUTING.md says `/live/reload`; the real address is `/live/api/reload`.
- README's install link downloads upstream `ideoforms/AbletonOSC`, not this fork,
  and it does not explain the loopback-only security policy.
- A static comparison found 75 of 139 literal registered addresses absent from
  README, including nearly all browser, return-track, master-track, and fork view
  endpoints. Dynamically generated routes make the true gap larger or harder to
  measure.
- README describes the track API as covering regular, return, and master tracks,
  while the implementation now exposes separate contracts.
- The API contract is duplicated across route registration, README, SESHAT.md,
  tests, and client assumptions. Introduce a declarative endpoint manifest from
  which documentation and basic contract tests can be generated.
- `browser.py` and `return_track.py` are large but well-commented. Before adding
  more endpoints, split protocol validation, Live-object lookup, and response
  serialization into focused helpers.

## Verified working (no action needed)

Loopback-only bind (Live on `127.0.0.1:11000`, Seshat on
`127.0.0.1:11001`, verified via lsof), song tempo/swing/playback getters,
track-name and clip-slot getters, the clip_slot logger fix (PR #213), structured
invalid-index logging with the offending address, unknown-address logging,
return_track error envelopes with counts, begin/end_undo_step round-trip, and a
metronome listener add→initial push→remove through the fixed base bookkeeping.

Earlier probes in the same review also verified tracks/return_tracks structure
listeners on create/delete and the browser export end-to-end (obsolete-argument
rejection without writing; 7 categories walked in ~300ms; 8,289 items; 0600
file; valid JSON). Note: browser.py's "UI may be unresponsive for several
seconds" comment overstates the measured cost at this library size.

## Suggested order of work

1. Fix confirmed items 1–3 and add fake-dispatcher regression tests for each.
   Define the multi-track wildcard reply shape before changing item 3.
2. Unify exception handling and reply validation (items 4–5), then update the
   stale error test to assert the one canonical envelope.
3. Fix base initialization and listener-index normalization (items 6 and 8),
   with listener lifecycle tests that cover renumbering and float OSC inputs.
4. Make the test harness safe and split unit, live-smoke, and Seshat end-to-end
   layers. This is what will keep the protocol fixes from regressing.
5. Harden or remove the old export (item 9), make reload failure-safe (item 10),
   and fix the import guard (item 11).
6. Correct the README/CONTRIBUTING material and establish a generated or
   declarative endpoint inventory. Add log rotation at the same time.
7. Resolve the selected return/master track identity contract before adding
   more view endpoints. Remove dead/experimental surface opportunistically.

Update SESHAT.md for every change that diverges further from upstream, per that
file's own rule. Commit this handoff or move its durable findings into tracked
issues/docs; while it remains untracked it is easy to lose.
