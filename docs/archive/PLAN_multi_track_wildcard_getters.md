**Archived 2026-08-27 — shipped.** This is the plan as written *before*
implementation; the code as merged may differ. The change lives in
`abletonosc/track_callback.py` (the extracted `create_track_callback`
factory) and `abletonosc/osc_server.py` (`OSCServer._dispatch`'s
list-of-tuples reply contract), documented in `API.md` § Track API under
"The track-index argument wildcard (`*`)" and § Status Messages. The two
open questions this plan left (a ≥2-track live confirmation, and whether a
Live set can reach zero regular tracks) were still open at ship time; no
follow-up roadmap entry was added for them — see the PR for the reasoning.

# Plan: Define and repair multi-track wildcard getter responses

Roadmap item: **#1 · Define and repair multi-track wildcard getter responses**
(source: `issues.md`, "Define and repair multi-track wildcard getter
responses", Critical). No dependencies.

## Context

`abletonosc/track.py` registers every `/live/track/...` address through one
closure factory, `create_track_callback`. That wrapper accepts `"*"` in the
track-index slot and iterates all regular tracks — but its loop body ends in
`return (track_index, *rv)` the moment a callback produces a value, so any
**getter** sent with `*` answers for track 0 only. Setters, methods and
listener registrations survive the loop only because their callbacks return
`None`.

Confirmed against a running Live twice:

- 2026-08-03 code review (issues.md): `/live/track/get/name *` produced
  exactly one getter invocation, for track 0, on a multi-track set.
- 2026-08-27, Live 12.4.3, installed copy code-identical to this checkout
  (docs-only diff): `/live/track/get/name *` and `/live/track/get/mute *`
  each produced exactly one `Getting property for track:` log line. The
  session set had only one regular track, so this re-run confirms the wire
  is alive and the path is the logged one, but could not by itself
  distinguish the defect from correct behaviour; a mutating two-track probe
  was not run (see Open questions).

The intended multi-track contract has never been stated anywhere — API.md's
Track section defines `*` only for listeners ("`*` in place of the index
subscribes every track"). So this item is two things in one PR: **choose and
document the contract**, then **make the code honour it**.

Constraints that shaped the contract choice:

- README § Wildcard queries (fork-authored) already defines the address-level
  doctrine: *a wildcard request is a fan-out, not a query* — one reply per
  match, errors correlated on what the client sent, one bad match never
  silences the rest. The roadmap entry explicitly points here.
- Listener subscriptions made with `*` already push **one datagram per track**
  on the concrete `/live/track/get/<prop>` address, payload
  `(track_index, value)`. Whatever the getter contract is, disagreeing with
  the shape the listener path has shipped for years would give one address
  two reply grammars.
- Several wildcard-capable getters are variable-length per track
  (`clips/name` returns one value per clip slot, `devices/name` one per
  device, the routing `available_*` lists arbitrary counts). A single flat
  aggregate datagram `(t0, v0..., t1, v1...)` is undecodable for these — no
  parser can find the track boundaries.
- Seshat is the only known consumer. Its `Transport.query/3` awaits exactly
  one reply correlated by address, so *any* multi-reply shape is unusable
  through it — which is already the documented position for address
  wildcards ("wildcards must not be sent through `Transport.query/3`;
  `query_batch/2` over concrete addresses is the answer"), and SESHAT.md
  records that **nothing in Seshat sends a wildcard today**. No shape we
  pick can break an existing Seshat call.

**Decision: per-track fan-out replies** — the argument wildcard behaves like
the address wildcard: one reply datagram per regular track, each identical in
shape to the single-track reply. The aggregate-single-reply alternative was
rejected on the variable-length getters alone, and it would also have made
`*` getters diverge from `*` listener pushes on the same addresses.

**Decision: all-or-nothing on error.** Within one endpoint the fan-out
members are homogeneous (the same property read off every track, all indices
valid by construction), unlike the heterogeneous endpoints of an address
fan-out — a mid-loop failure indicates a systemic problem, not per-member
inapplicability, and realistic per-track getter failures are near-nonexistent
(`_get_property` already converts inapplicable-property `RuntimeError` to a
`nil` value). So a failure during collection produces **zero replies and one
correlated `/live/error`** naming the failing track, rather than a partial
fan-out plus an invented multi-error scheme. Deterministic, cheap to
implement, and a client can fall back to per-index queries to isolate.

Mechanically, replies stay in the dispatcher: `OSCServer._dispatch` learns
that a callback may return a **list of tuples**, meaning one reply per
element. The alternative — the track handler sending datagrams itself via
`osc_server.send` — would bypass `_dispatch`'s reply addressing
(`(remote_hostname, response_port)`) and scatter reply policy across files.
`_dispatch` is a named merge hazard (SESHAT.md § Merge hazards), so its
change is small, validated, tested, and recorded.

## Wire contract

### Changed: `/live/track/get/...` with track index `*`

Applies to **every** getter registered through `create_track_callback` — the
scalar property loop (`can_be_armed`, `fired_slot_index`, `has_audio_input`,
`has_audio_output`, `has_midi_input`, `has_midi_output`, `is_foldable`,
`is_grouped`, `is_visible`, `output_meter_level`, `output_meter_left`,
`output_meter_right`, `playing_slot_index`, `arm`, `color`, `color_index`,
`current_monitoring_state`, `fold_state`, `mute`, `solo`, `name`), the mixer
pair (`volume`, `panning`), `send`, the composite getters (`clips/name`,
`clips/length`, `clips/color`, `arrangement_clips/name`,
`arrangement_clips/length`, `arrangement_clips/start_time`, `num_devices`,
`devices/name`, `devices/type`, `devices/class_name`,
`devices/can_have_chains`), and the routing getters
(`available_input_routing_types`, `available_input_routing_channels`,
`available_output_routing_types`, `available_output_routing_channels`,
`input_routing_type`, `input_routing_channel`, `output_routing_type`,
`output_routing_channel`).

- **Request:** the concrete address with `"*"` (OSC string) in the
  track-index slot; any further arguments as for the single-track form
  (e.g. `/live/track/get/send * 0`).
- **Reply:** one datagram **per regular track** (`song.tracks` — audio and
  MIDI tracks; returns and master are out of this namespace entirely), each
  on the **concrete request address**, each with the exact single-track
  payload: `(track_index, ...values)`. Datagrams are built and sent in
  ascending `track_index` order within a single tick; UDP offers no delivery
  ordering guarantee, so clients correlate on the leading `track_index`, not
  arrival order.
- **Empty set:** zero regular tracks → zero replies, no error. (Believed
  unreachable in practice — see Open questions.)
- **Error:** if reading any track raises, the request produces **no replies**
  and exactly one structured error naming the failing track in the detail:
  `/live/error ["request", "/live/track/get/<prop>", "wildcard fan-out failed
  at track <i>: <detail>", arg_count, "*", ...]`. Collection happens before
  any send, so a failure never yields a partial fan-out. The re-raise
  **preserves the original exception class** (mechanism in Part 2) — only the
  message gains the track prefix — so `_is_wildcard_skip`'s class-based
  skip/report decision is unchanged for composed address-pattern requests.
- A wildcard **address** pattern combined with the `*` argument
  (`/live/track/get/* *`) composes: each matched endpoint fans out per
  track under the existing skip/error rules of README § Wildcard queries.
  This is exactly why the class-preserving re-raise above matters: an
  arg-mismatch endpoint like `send` fails its first per-track call with
  `ValueError` (unpacking empty params), and `_is_wildcard_skip` must still
  see a `ValueError` to skip it silently — a `RuntimeError` wrapper would
  turn every such documented skip into a per-endpoint error datagram.

### Unchanged but relied on (regression-pinned)

- `/live/track/get/<prop> <int>` — single-track getters: one reply,
  `(track_index, ...values)`, byte-identical to today.
- `/live/track/set/<prop> * <value>` and the methods/`delete_clip` with `*`
  — iterate every regular track, silent on success, exactly as today.
- `/live/track/start_listen/<prop> *` / `stop_listen` — subscribe/unsubscribe
  every track; pushes remain per-track `(track_index, value)` on
  `/live/track/get/<prop>` (API.md already documents this).
- Failures in the single-track form keep today's behaviour: the exception
  propagates to `_dispatch` and returns as
  `/live/error ["request", address, detail, arg_count, *args]`.

### Changed: dispatcher reply-type contract (`OSCServer._dispatch`)

- A callback may now return, in addition to a tuple or `None`: a **list of
  tuples**, meaning one reply datagram per element, sent in list order on
  the reply address. An empty list means no reply (same as `None`).
- Validation happens **before any send**: a list containing a non-tuple
  element raises the same `TypeError` → structured-error path as a non-tuple
  return does today, and none of the list is sent.
- The documented "four failures" wording ("a handler returning something
  that is neither a tuple nor `None`") becomes "neither a tuple, a list of
  tuples, nor `None`" wherever it appears (API.md, README, SESHAT.md).

No address is added, renamed or removed. No listener payload changes.

## Numbered parts

### Part 1 — dispatcher: list-of-tuples means one reply per element

Files: `abletonosc/osc_server.py`, `tests_unit/test_osc_server.py`,
`API.md`, `README.md`, `SESHAT.md`.

1. In `OSCServer._dispatch`, extend the post-callback validation: `rv` may
   be `None`, a `tuple`, or a `list` whose every element is a `tuple`;
   anything else (including a list with a non-tuple element) raises the
   existing explicit `TypeError` naming `callback_address`, which lands on
   the structured-error path unchanged. Validate the whole list before
   sending anything. The invalid-list detail must still contain the word
   `list` (name `list` and, if useful, the offending element's type):
   `test_direct_non_tuple_return_is_structured_error` returns `[120]` and
   asserts `"list" in` the detail — under the new contract that value is a
   list with a non-tuple element and must stay a structured error that this
   existing test passes against unmodified.
2. Reply sending: for a tuple, exactly today's single send; for a non-empty
   list, one `send` per element in order, all to
   `(remote_hostname, self._response_port)`; for `None` or `[]`, no send.
3. Tests (`tests_unit/test_osc_server.py`, via the existing `dispatch`
   helper and the `server`/`receiver` fixtures): list return → N datagrams on the reply address in order;
   empty list → no datagram; list containing a non-tuple → single
   `/live/error ("request", ...)` envelope and zero replies; list return
   through address-wildcard dispatch replies on the concrete address.
4. Documentation, same commit:
   - `API.md` § Status Messages / error handling: update the "four
     failures" sentence's return-type wording; add one sentence beside the
     reply-type validation note that a list of tuples is N replies.
   - `README.md` § Error handling: its current text says only "a handler
     returning an invalid value" — no tuple wording, so this may need no
     edit; change it only if a return-type sentence is actually there.
   - `SESHAT.md`: update the divergence entry titled **"Reply validation
     replaced the `assert`"** and the scope sentence earlier in the file
     that reads "invalid (non-tuple, non-`None`) handler return values" —
     both carry the return-type wording; and extend the `_dispatch` bullet
     in § Merge hazards to name the multi-reply contract as fork-only code
     a merge would drop.

### Part 2 — track fan-out: collect every track, extract the wrapper for Live-free tests

Files: `abletonosc/track_callback.py` (new), `abletonosc/track.py`,
`manager.py`, `tests_unit/test_track_callback.py` (new), `API.md`,
`README.md`, `SESHAT.md`.

1. New module `abletonosc/track_callback.py`, importing nothing but
   `typing` (so `tests_unit/`'s synthetic-package loader can import it
   without Live). It holds the factory, lifted from `init_api` with its
   signature extended to take the track source:

   ```python
   def create_track_callback(get_tracks, func, *args, include_track_id=False)
   ```

   `get_tracks` is a zero-argument callable returning the live track vector
   (`TrackHandler` passes `lambda: self.song.tracks`, preserving the
   current per-dispatch resolution of `self.song`). Inside the returned
   `track_callback(params)`:
   - `params[0] == "*"` → wildcard branch: iterate
     `range(len(get_tracks()))` ascending; per track, call `func` exactly
     as today (`include_track_id` prepends the index to the params tuple);
     collect `(track_index, *rv)` for every non-`None` `rv` into a list.
     Wrap the per-track call so an exception `e` at track `i` re-raises
     **with its class preserved** and its message prefixed
     `"wildcard fan-out failed at track %d: "` — the dispatcher's envelope
     then names the track. Mechanism: set
     `e.args = ("wildcard fan-out failed at track %d: %s" % (i, e),)` and
     bare-`raise` the same exception object (or reconstruct with
     `type(e)(msg)` guarded by a `RuntimeError` fallback if construction
     fails). Preserving the class is load-bearing:
     `OSCServer._is_wildcard_skip` classifies by exception class, and a
     composed request (`/live/track/get/* *`) must still skip arg-mismatch
     endpoints (`send` raising `ValueError`, a listener raising
     `AttributeError`) silently — a plain `RuntimeError` wrapper would
     report them all as errors. Return the collected list if non-empty,
     else `None` (setters/methods/listeners collect nothing and stay
     silent).
   - single-index branch: byte-for-byte today's behaviour —
     `int(params[0])`, one call, return `(track_index, *rv)` or `None`.
2. `abletonosc/track.py`: delete the nested factory; import
   `create_track_callback` from `.track_callback`; every registration site
   passes `lambda: self.song.tracks` as the first argument (a small local
   `partial`/helper keeps the diff readable). No registration list changes.
3. `manager.py`: add `importlib.reload(abletonosc.track_callback)` to
   `reload_imports`, **before** the `abletonosc.track` line, so
   `/live/api/reload` picks up wrapper changes (track.py's `from` import
   rebinds on its own reload).
4. Tests (`tests_unit/test_track_callback.py`, new): import the real
   production factory through `conftest.load_module` and register its
   callbacks on the real `OSCServer` from the fixtures — this is the actual
   shipped wrapper under test, not a replica. Fake tracks are plain Python
   objects; `get_tracks` returns a plain list. Cases:
   - single-index getter: one reply `(1, value)` — unchanged shape;
   - wildcard getter over 3 tracks: three datagrams on the concrete
     address, ascending track index, single-track payload each;
   - wildcard getter with a pass-through argument (send-style `func`):
     argument reaches every per-track call, replies carry it;
   - wildcard setter-style `func` (returns `None`): invoked once per
     track, zero datagrams;
   - `include_track_id=True` (listener-style): per-track invocation
     receives `(track_index, *rest)`, zero datagrams;
   - zero tracks: zero datagrams, zero errors;
   - one track's `func` raises: exactly one `/live/error`
     `("request", ...)` whose detail contains `wildcard fan-out failed at
     track 1`, and zero replies;
   - the re-raise preserves the exception class: a per-track `ValueError`
     surfaces to the dispatcher as `ValueError`, not `RuntimeError`;
   - composed address + argument wildcard (`/live/track/get/* *` with a
     scalar getter and a send-style endpoint both registered): the scalar
     getter fans out one reply per track on its concrete address, the
     send-style endpoint (whose `func` raises `ValueError` unpacking empty
     params) is skipped silently — zero `/live/error` datagrams;
   - non-wildcard failure (bad index `99`, `get_tracks` returning a plain
     list raising `IndexError`): today's envelope, pinned.
5. Documentation, same commit:
   - `API.md` § Track API: replace the two-line wildcard paragraph
     (currently listener-only) with the full argument-wildcard contract
     from § Wire contract above — getters fan out one reply per track,
     ascending, all-or-nothing on error; setters/methods iterate silently;
     listeners subscribe every track (unchanged). Record the measurements,
     dated and Live-version-stamped: the 2026-08-03 defect confirmation,
     the 2026-08-27 single-track log probe (this plan), and the
     post-implementation two-track verification once run.
   - `README.md` § Wildcard queries: add a short paragraph defining the
     track-index argument wildcard and stating it is the same fan-out
     doctrine as address patterns (README's API tables stay untouched —
     they are upstream's).
   - `SESHAT.md`: add a divergence entry (track getter fan-out repair, the
     new `track_callback` module, the `manager.py` reload line); extend the
     "Wildcards are a fan-out, not a query" client note to cover the
     argument wildcard — `* ` getters also must not go through
     `Transport.query/3`; `query_batch/2` over concrete indices remains the
     answer; nothing in Seshat sends `*` today.

`FORK_GAPS.md` is untouched (this is a defect in existing surface, not a
gap — no inventory rows exist for it, nothing to regenerate). `issues.md`'s
source entry is removed at `/ship` time, not here.

## Testing

`python3 -m pytest tests_unit/` is the only gate, all Live-free through
`conftest.py`'s synthetic-package loader and `dispatch` fixture:

- Part 1 pins the dispatcher's new reply-type contract (multi-reply order,
  empty list, validation failure, wildcard-address interaction) in
  `test_osc_server.py`.
- Part 2 exercises the **production** `create_track_callback` end to end
  through `OSCServer.process_message` in `test_track_callback.py` — the
  first tests_unit coverage of shipped handler-side code rather than a
  shape-replica, made possible by the extraction.
- Existing suites (`test_osc_server.py`, `test_handler_envelope.py`,
  `test_import.py`) must pass unmodified except for added cases — they pin
  the single-reply and error-envelope behaviour this change must not move.

Not covered Live-free, by design: `TrackHandler` itself (imports
`ableton.v2`; the `lambda: self.song.tracks` glue and registration lists run
only inside Live), real LOM property behaviour, and reply routing on the real
socket. `tests/` mutates a running Live on import and is not part of the
gate; it is not touched here.

## Live verification

Precondition for every check: the Remote Scripts copy equals this checkout
byte for byte (`diff -rq`, code files) **and** Live has been restarted since
it was copied. Method: `API.md` § "The no-probe variant" — send to
`127.0.0.1:11000` fire-and-forget, read evidence from the installed
`logs/abletonosc.log`; never bind 11001 (Seshat's). Wrap mutations in
`/live/song/begin_undo_step` / `end_undo_step` and restore everything.

1. **The repaired fan-out, ≥2 tracks.** If the set has one track, create a
   temporary MIDI track (`/live/song/create_midi_track -1`) inside an undo
   bracket. Send `/live/track/get/name *`. Evidence: one
   `Getting property for track: name = <value>` log line **per regular
   track**, distinct values, same tick. Delete the temporary track
   (`/live/song/delete_track <last>`) and confirm restoration
   (`/live/track/get/name <last>` → `Index out of range` error line).
2. **Mixer path.** `/live/track/get/volume *` → one
   `Getting property for track: volume` line per track (the mixer getter
   logs through `_get_mixer_property`).
3. **Single-track regression.** `/live/track/get/name 0` → exactly one log
   line, and no behaviour change.
4. **Setter regression.** `/live/track/set/mute * 0` (with mutes already 0,
   inside an undo bracket) → one `Setting property for track: mute` line
   per track; read back `/live/track/get/mute <i>` per index.
5. **Error case.** `/live/track/get/send * 99` (send index past the return
   count) → a single `Error handling OSC message /live/track/get/send`
   line whose detail names the failing track, and no `Getting property`
   reply lines for that request.

6. **Reload picks up the wrapper.** `manager.py` now reloads
   `abletonosc.track_callback` before `abletonosc.track`. Edit a log line in
   the installed `abletonosc/track_callback.py`, send `/live/api/reload`, then
   `/live/track/get/name 0`, and confirm the edited line appears — the
   reload-ordering bug's symptom is that it does not.

**Implementation-phase status, 2026-08-27 (Live 12.4.3 running, PID 70216).**
None of checks 1–6 could be run, and none is claimed. The precondition fails
by construction: the installed copy is still the *pre-change* code (`diff -rq`
of `abletonosc/`, `__pycache__`/`logs` excluded, reports exactly
`osc_server.py` and `track.py` differing plus `track_callback.py` missing),
and the implementation phase may not install into Live or restart it. What was
run, read-only via § "The no-probe variant" (four `/live/track/get/name <i>`
sends to 11000, evidence from the installed `logs/abletonosc.log`):

- **The set still holds exactly one regular track** ("1-MIDI"): index 0 logged
  `Getting property for track: name = 1-MIDI`; indices 1, 2 and 3 each logged
  `Error handling OSC message /live/track/get/name: Index out of range`. So
  **Open question 1 remains open** — a ≥2-track confirmation needs a mutating
  probe (temporary MIDI track under an undo bracket), which this phase is not
  permitted to run either.
- **The installed copy is confirmed pre-change**: its traceback names
  `track.py", line 21, in track_callback` — the nested closure with the early
  `return`, which no longer exists in this checkout.

Remains uncovered by log-based verification and stated as such: the actual
reply **datagrams** (composite getters like `clips/name` log nothing, and
replies go to 11001 which only Seshat may hold) — their count, order and
payload are covered Live-free by `tests_unit/`, and end-to-end only by a
future Seshat-side check if Seshat ever consumes `*`. The all-or-nothing
zero-reply guarantee on error is likewise pinned by unit tests only.

**Review-phase status, 2026-08-27 (pr-review).** Checks 1-6: **all skipped by
environment**, independently re-confirmed rather than taken on the
implementer's word. The precondition fails at the first clause: `diff -rq
--exclude=__pycache__ abletonosc "$HOME/Music/Ableton/User Library/Remote
Scripts/AbletonOSC/abletonosc"` reports `osc_server.py` differs, `track.py`
differs, and `track_callback.py` is present only in the checkout - so the
installed copy is the pre-change code. Live is running (PID 70216), but this
phase may not install into the Remote Scripts directory, restart Live, or bind
11001, so the gap cannot be closed here. No probe of any kind was sent; no
result is claimed for any check.

- Check 1 (repaired fan-out, >=2 tracks) - **skipped by environment**: needs
  the repaired code installed *and* a Live restart, plus a mutating
  create/delete-track probe. Open question 1 stays open.
- Check 2 (mixer path) - **skipped by environment**: same precondition.
- Check 3 (single-track regression) - **skipped by environment**: same
  precondition. Pinned Live-free by
  `tests_unit/test_track_callback.py::test_single_index_getter_replies_once`.
- Check 4 (setter regression) - **skipped by environment**: same precondition,
  and mutating.
- Check 5 (error case) - **skipped by environment**: same precondition.
- Check 6 (reload picks up the wrapper) - **skipped by environment**: same
  precondition, and `/live/api/reload` under a live session is a user action.

## Downstream

**Pin bump only.** Verified against SESHAT.md: nothing in Seshat sends a
track-index `*` today (its API doc and the fan-out note steer everything
through `query_batch/2` over concrete indices); no address is added, renamed
or removed, so `vendored_addresses_test` needs no new tripwire; single-index
reply shapes, setter silence and listener pushes are byte-identical. The
SESHAT.md client-guidance update (argument wildcards are fan-outs too — never
through `Transport.query/3`) rides in this repo and reaches Seshat with the
bump. If Seshat later wants one-round-trip multi-track reads, that is a new
consumer decision (its `Transport` would need a fan-out-aware receive path),
not an obligation of this change.

## Out of scope

- Argument wildcards for other namespaces (`/live/clip/...`,
  `/live/device/...`, `/live/scene/...`, `/live/clip_slot/...`) — no such
  support exists today (the `"*"` branch lives only in track.py's wrapper);
  adding it is new surface for the roadmap, and this item's contract is the
  precedent it would follow.
- Return/master tracks under `*` — `/live/track/...` is regular-tracks-only
  by the documented namespace contract; selected-track identity is roadmap
  item "Define selected-track identity across regular, return, and master
  tracks".
- Negative track indices (`int(params[0])` accepts `-1` and Python-indexes
  from the end) — undocumented today, behaviour unchanged, left undocumented.
- Partial-error fan-out (per-track error datagrams) — rejected above;
  revisit only if a consumer demonstrates a need to salvage partial reads.
- An aggregate batched-read endpoint (one datagram, all tracks) — a new
  address if ever wanted; belongs on the roadmap as its own item.
- The experimental `/live/clips/filter` / `unfilter` pair ("no arguments =
  every track") — documented do-not-use; untouched.

## Open questions

1. **Two-track live confirmation is still owed.** Today's session set had a
   single regular track, and the mutating probe (temporary track under an
   undo bracket) was denied by the run's permission gate — so this plan's
   own measurement (one invocation for `name *`/`mute *`, 2026-08-27,
   Live 12.4.3) confirms the logged path but cannot alone distinguish the
   defect from correct behaviour. Assumed meanwhile: the defect is real —
   the early `return` inside the loop is unambiguous in source, and the
   2026-08-03 review measured exactly one invocation on a multi-track set.
   Live verification check 1 closes this; the implementer should run it
   first.
2. **Can a Live set have zero regular tracks?** ⚠️ Unverified — deleting
   down to zero tracks in the user's live session was not an acceptable
   probe, and the LOM docs don't state a minimum. Assumed meanwhile: the
   contract defines zero tracks → zero replies, which is safe whether or
   not the state is reachable.
