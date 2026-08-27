**Archived 2026-08-27 — shipped.** This is the plan as written *before*
implementation; the code as merged may differ. The change lives in
`abletonosc/device.py` (`create_device_callback`, the parameter-listener
pair, and the property `start_listen`/`stop_listen` registration loop) and
`API.md` § Device API → "Device: Listening". The follow-up gaps its own
review raised — `scene.py`, `clip.py`, `clip_slot.py` never int-casting
their listener args, and the property pair not truncating trailing
arguments — were fixed in
[docs/archive/PLAN_listener_identity_normalization.md](PLAN_listener_identity_normalization.md),
which also left a further follow-up (`track.py` / `return_track.py`),
closed in turn by
[docs/archive/PLAN_track_callback_listener_identity.md](PLAN_track_callback_listener_identity.md):
`track_callback.py` fixed, `return_track.py` audited clean.

# Plan: Device listener identity — parameter indices and property listeners

Roadmap item: **Device listener identity — parameter indices and property
listeners** (sources: `issues.md`, "Normalize device parameter listener
identifiers", High, **and** "Give device property listeners their identity
back", Medium — one PR, both entries close together at ship time). No
dependencies.

## Context

Two listener-key defects live in `abletonosc/device.py`, in the same
registration helper, with the same lifecycle test needs:

**1. Parameter listeners key and echo raw OSC values.** The individual
parameter getters/setters int-cast their indices (`int(params[0])`, added for
TouchOSC, which sends floats by default — upstream issue #33), but the
listener path does not. `create_device_callback(..., include_ids=True)` passes
`params[0:]` raw to `device_get_parameter_value_listener`, which then:

- indexes `device.parameters[params[2]]` with the raw value — a float raises
  `TypeError` inside the callback, so a float-sending client cannot subscribe
  at all;
- keys the bookkeeping as `("value", tuple(params))` with the raw values, so
  `start_listen` with `(0, 0, 1)` and `stop_listen` with `(0.0, 0.0, 1.0)`
  address *different* keys — the stop misses, and the listener leaks until
  reload;
- echoes `(*params, value)` in the push, so a float-indexed subscription (were
  it to survive) would push float indices while the query reply for the same
  parameter echoes ints (`API.md` documents this asymmetry today and tells
  clients "Send ints").

The wrapper does int-cast track/device for the *lookup*
(`self.song.tracks[int(params[0])].devices[int(params[1])]`), so the raw
values only survive into the callee's `params` — the key, the LOM parameter
index, and the echo.

**2. Property listeners have no identity.** The generic loop registers
`/live/device/start_listen/{class_name,name,type}` through
`create_device_callback(self._start_listen, prop)` **without**
`include_ids=True`, so the wrapper strips the two indices before
`_start_listen` sees them (`params[2:]` → `()`). Consequences:

- the push on `/live/device/get/<prop>` carries the **bare value** — no track
  or device echo, so a client cannot tell which device changed;
- the listener key collapses to `(prop, ())` for every device, so subscribing
  a second device to the same property silently stops and replaces the first —
  one subscription per property, process-wide.

`start_listen/parameter/value` already registers with `include_ids=True`; the
property listeners need the same treatment plus the normalization from defect
1, giving both halves one consistent identity rule: **listener identity is a
tuple of ints, normalized at the callback boundary, used identically for the
LOM lookup, the bookkeeping key, and the push echo.**

### What research changed about the obvious approach

The roadmap entry says the three property listeners (`name`, `type`,
`class_name`) should "push with their track and device indices and subscribe
per device". Measurement says only one of the three *can*:

> **Measured 2026-08-27, Live 12.4.3**, via `/live/application/dump_lom`
> (`introspection.py`, run against the installed copy; dump inspected and then
> deleted): `Live.Device.Device` offers `add_name_listener`,
> `add_parameters_listener`, `add_is_active_listener`,
> `add_is_using_compare_preset_b_listener`, `add_latency_in_ms_listener`,
> `add_latency_in_samples_listener` — and **no `add_type_listener` or
> `add_class_name_listener`**. `type` and `class_name` are plain
> non-observable read-only properties.

So `/live/device/start_listen/type` and `.../class_name` have **never
worked**, hobbled keying aside: `_start_listen` builds
`getattr(target, "add_type_listener")`, which raises `AttributeError`, which
`_dispatch` converts to a structured `/live/error`. This is true today and
stays true after this change; what changes is only that the error becomes
documented behaviour instead of an undocumented surprise. (The error's
request echo is `message.params` from `_dispatch` — the raw args as sent —
so it carried both indices before this change too; `include_ids` never
affected it.) The registration stays uniform
(all three through the loop) — deregistering two of the three would be a
larger wire change (address removal) for no behavioural gain, and would
diverge the loop from upstream's shape for nothing.

This also means the only *working* per-device property push this item
delivers is `name` — which is fine: `name` is the one of the three that can
actually change (it is the only settable one; a device's `type` and
`class_name` are fixed for the life of the device).

### Constraints research surfaced

- `device.py` imports only `typing` and `.handler` — **no `Live` import** —
  so unlike `track.py`/`song.py` it can be imported and its handler
  constructed under `tests_unit/`'s synthetic root with the existing
  `load_handler_module()` Component stub. This is the first production
  handler subclass the unit gate can drive end to end; the tests in Part 3
  rely on it. (`tests_unit/conftest.py`'s docstring currently says all
  production subclasses are out of reach — Part 3 corrects that sentence.)
- `_start_listen`/`_stop_listen`/`_clear_listeners` in `handler.py` already
  do the right thing given a consistent key: the stored-object unbind, the
  idempotent restart, the warning-not-error on a missing stop. Nothing in
  `handler.py` changes.
- `SESHAT.md` § Merge hazards names nothing in `device.py`'s registration
  loop today; the existing deliberate-changes bullet "`device.py` — parameter
  listeners join the same bookkeeping" is where the fork's device-listener
  story lives and gets extended.
- Seshat (checked at `/Users/patrick/seshat`, 2026-08-27): no code under
  `lib/` sends any `/live/device/start_listen|stop_listen` address; its
  `vendored_addresses_test.exs` doc-shape map lists
  `/live/device/{start,stop}_listen/<property>` as *patterns*, which this
  change keeps valid (no address added or removed). The "API doc warning"
  the issues.md entry says to remove is the hobbled-listeners paragraph in
  **this repo's** `API.md`, vendored into Seshat at `priv/AbletonOSC/API.md`
  — it updates with the pin bump automatically.

## Wire contract

No address is added or removed. All changes below are to push shape, error
shape, and subscription identity.

**Changed — `/live/device/start_listen/<prop>` for `name`, `type`,
`class_name`** (request: `track_id, device_id`; no direct reply):

- Registration gains `include_ids=True`; indices are int-normalized by the
  wrapper.
- `name`: subscribes **per device**, keyed `("name", (track_id, device_id))`.
  On subscribe and on every change, pushes on `/live/device/get/name` with
  `(track_id, device_id, name)` — the same shape as a query reply (was: bare
  `(name,)` with no indices, one subscription process-wide). Bad indices →
  structured `/live/error ("request", address, detail, argc, track_id,
  device_id)` (unchanged mechanics).
- `type`, `class_name`: **not observable in Live** (measured above — the LOM
  offers no `add_type_listener`/`add_class_name_listener`). Subscribing
  answers with a structured `/live/error` naming the `AttributeError`; no
  listener is registered and no bookkeeping entry is left behind. This is
  what already happens today; it becomes documented. The addresses stay
  registered for uniformity and an accurate error.

**Changed — `/live/device/stop_listen/<prop>`** (request: `track_id,
device_id`; no reply): gains `include_ids=True`; stops exactly the
`(prop, (track_id, device_id))` subscription. Float indices find the same key
as int indices. Stopping a never-started listener stays a logged warning,
silent on the wire (matches every other handler). For `type`/`class_name`
there is never a key to find, so the warning path is the outcome.

**Changed (behavioural) — `/live/device/start_listen/parameter/value` and
`/live/device/stop_listen/parameter/value`** (request: `track_id, device_id,
parameter_id`; no direct reply):

- All three indices are normalized to `int` before the LOM lookup, the
  bookkeeping key (`("value", (track_id, device_id, parameter_id))` — exactly
  three ints, arguments past the third ignored), and the push echo. A
  float-sending client (TouchOSC) can now subscribe, and mixed-type
  start/stop pairs address the same listener — no leak.
- Each change still pushes **two** datagrams: `/live/device/get/parameter/value`
  with `(track_id, device_id, parameter_id, value)` and
  `/live/device/get/parameter/value_string` with `(track_id, device_id,
  parameter_id, value_string)` — but the echoed indices are now always ints
  (was: echoed as sent, so floats came back as floats). `API.md`'s "Send
  ints" caveat is replaced by the normalization statement.

**Unchanged but relied on:**

- `/live/device/get/name|type|class_name` `(track_id, device_id)` →
  `(track_id, device_id, value)` — the query reply shape the fixed `name`
  push now matches.
- `/live/device/get/parameter/value` query reply
  `(track_id, device_id, parameter_id, value)` (already int-cast).
- Subscribing pushes the current value immediately (`_start_listen` invokes
  the callback once on registration) — unchanged, now documented for the
  device addresses.

## Parts

### Part 1 — parameter listener normalization (`abletonosc/device.py`)

1. In `create_device_callback`, the `include_ids` branch passes the
   already-int-cast indices instead of the raw params:

   ```python
   if include_ids:
       rv = func(device, *args, (track_index, device_index, *params[2:]))
   ```

   (`track_index`/`device_index` are the locals the wrapper already computes
   for the lookup.)
2. `device_get_parameter_value_listener` and
   `device_get_parameter_remove_value_listener` normalize the full identity
   once at the top — `params = (int(params[0]), int(params[1]),
   int(params[2]))` — and use that tuple for the parameter lookup, the
   `("value", params)` key, and the push echo. The closure captures the
   normalized tuple, so both pushes echo ints.
3. Documentation, same commit: `API.md` § Device API — rewrite the
   parameter-listener paragraph: indices are normalized to ints in lookup,
   bookkeeping, and push; float indices from TouchOSC-style clients are
   accepted; the "push echoes as sent / Send ints" caveat is deleted and
   replaced by a dated note (2026-08-27) that both reply and push echo ints.

### Part 2 — property listener identity (`abletonosc/device.py`)

1. In the generic properties loop, register the listen pair with ids:

   ```python
   self.osc_server.add_handler("/live/device/start_listen/%s" % prop,
                               create_device_callback(self._start_listen, prop, include_ids=True))
   self.osc_server.add_handler("/live/device/stop_listen/%s" % prop,
                               create_device_callback(self._stop_listen, prop, include_ids=True))
   ```

   `get/` (and the empty `set/` loop) stay as they are — their reply
   envelope already carries the indices via the wrapper's
   `(track_index, device_index, *rv)`.
2. Documentation, same commit:
   - `API.md` § Device API: replace the ⚠️ "hobbled as registered" paragraph
     with the real contract — `start_listen/name <track_id> <device_id>`
     subscribes per device, pushes `(track_id, device_id, name)` on
     `/live/device/get/name` immediately and on every change;
     `stop_listen/name` with the same two indices ends it; **`type` and
     `class_name` are not observable** — subscribing answers a structured
     `/live/error` — with the 2026-08-27 / Live 12.4.3 `dump_lom`
     measurement of `Live.Device.Device`'s listener surface recorded beside
     it (the full add_*_listener list from the Context section above, so the
     next person doesn't re-derive it from the apiref).
   - `SESHAT.md`: extend the deliberate-changes bullet for `device.py` (or
     add a sibling bullet): property listen pairs now registered
     `include_ids=True`, identity normalized to int tuples, push shape
     matches the query reply; note that upstream's registration is the
     hobbled form, so a merge that takes upstream's loop reverts it
     **silently** — add a line to § Merge hazards naming
     `tests_unit/test_device_listeners.py` as the tripwire.
   - `FORK_GAPS.md`: nothing to delete and no inventory regeneration — this
     is a defect fix; no address or LOM member coverage changes.
   - `issues.md`: both source entries are removed at **ship** time with the
     ROADMAP entry (this run's convention: the ship commit owns source
     write-up removal), not in the implement commit.

### Part 3 — Live-free lifecycle tests (`tests_unit/test_device_listeners.py`, new)

Driven through `conftest.py`'s `dispatch` helper (a plain function —
`from .conftest import dispatch`, as `test_handler_lifecycle.py` does, not a
pytest fixture) against the production
`OSCServer` and the production `DeviceHandler`:

- Module loading: `load_handler_module()` then
  `load_module("abletonosc.device")` (add a `load_device_module()` helper
  beside `load_handler_module()` in `conftest.py` if that reads better).
  Correct the conftest docstring sentence claiming every production subclass
  imports Live at module scope — `device.py` is now the counterexample the
  suite depends on.
- Fakes local to the test file: `FakeSong` (`tracks`), `FakeTrack`
  (`devices`), `FakeDevice` (`name` settable, `type`, `class_name`,
  `parameters`, `add_name_listener`/`remove_name_listener`, **deliberately no
  `add_type_listener`/`add_class_name_listener`** — mirroring the measured
  LOM), `FakeParameter` (`value`, `name`, `str_for_value`,
  `add_value_listener`/`remove_value_listener`). Construct
  `DeviceHandler(FakeManager(server))`, then assign `handler.song = fake_song`
  (callbacks read `self.song` at dispatch time, not at registration).

Cases, each checkable against the wire or the bookkeeping dicts:

1. **Float parameter subscribe works and normalizes.**
   `start_listen/parameter/value 0.0 0.0 1.0` → exactly one callback on
   `tracks[0].devices[0].parameters[1]`; key `("value", (0, 0, 1))`; initial
   pushes on `.../parameter/value` `(0, 0, 1, value)` and
   `.../parameter/value_string` `(0, 0, 1, str)` — indices are Python ints.
2. **Mixed-type start/stop pairs don't leak.** Start with floats, stop with
   ints (and the reverse): parameter object holds no listener afterwards,
   both dicts empty, nothing on `/live/error`.
3. **Restart is idempotent.** Two starts (one float-, one int-indexed) leave
   exactly one registered callback and one key.
4. **`clear_api()` after a float-indexed subscribe** empties both dicts and
   unbinds the parameter — the reload-regression the SESHAT.md bullet
   describes.
5. **Parameter change push.** Fire the fake parameter's stored callback after
   changing `value`: both datagrams arrive with int indices and current
   value / `str_for_value` string.
6. **`name` subscribes per device.** `start_listen/name 0 0` then
   `start_listen/name 0 1`: two keys `("name", (0, 0))`, `("name", (0, 1))`,
   both fake devices hold a listener (second subscribe must **not** stop the
   first); initial push for each is `(track, device, name)` on
   `/live/device/get/name`.
7. **`name` change push carries identity.** Change fake device 1's name and
   fire its listener: push `(0, 1, new_name)`; device 0's listener untouched.
8. **`stop_listen/name` stops only its device**, and float indices on
   start/stop resolve to the same key as ints.
9. **`type`/`class_name` subscribe errors are structured and clean.**
   `start_listen/type 0 0` → one `/live/error` with
   `("request", "/live/device/start_listen/type", <detail mentioning
   add_type_listener>, 2, 0, 0)` and empty bookkeeping dicts. Same for
   `class_name`.
10. **Query regression.** `get/name 0 0` still replies
    `(0, 0, name)`; `get/parameter/value 0 0 1` still replies
    `(0, 0, 1, value)`.

## Testing

`python3 -m pytest tests_unit/` is the gate and covers everything in Part 3:
dispatch through the production server, index normalization, bookkeeping
keys, push shapes, error envelopes — all Live-free. What it cannot cover:
whether the *real* `Live.Device.Device` and `DeviceParameter` behave as the
fakes do (`add_name_listener` semantics, `str_for_value` output, the
measured absence of `add_type_listener`/`add_class_name_listener` staying
absent in future Live versions). `tests/` (the opt-in live suite) mutates a
running Live and stays out of the gate; no changes to it here.

## Live verification

> **Status, pr-review 2026-08-27: all five checks SKIPPED BY ENVIRONMENT.**
> The precondition fails. Live 12.4.3 is running (PID 70216), but
> `diff -rq --exclude=__pycache__ abletonosc "$HOME/Music/Ableton/User
> Library/Remote Scripts/AbletonOSC/abletonosc"` reports **14 differing
> files** — `application.py`, `browser.py`, `clip.py`, `clip_slot.py`,
> `device.py`, `handler.py`, `midimap.py`, `osc_server.py`,
> `return_track.py`, `scene.py`, `song.py`, `song_structure.py`,
> `track.py`, `view.py` — plus `track_callback.py` present only in the
> checkout. The installed copy is an older install, not this branch, and
> the review may not install, restart Live or bind the reply port. Any
> datagram sent now would exercise that older `device.py`, so no result
> would mean anything about this change set. Checks 1–5 below therefore
> remain **unrun**; whoever installs this branch and restarts Live owns
> them. Nothing was sent to Live and nothing in the set was touched.

Precondition for all checks: the Remote Scripts copy equals this checkout
byte for byte **and** Live has been restarted since it was copied. Method:
`API.md` § "The no-probe variant" — send fire-and-forget UDP to
`127.0.0.1:11000`, read the new bytes of the installed
`logs/abletonosc.log`; replies cannot be captured (Seshat holds 11001).
A device on a regular track is required (at measurement time, 2026-08-27,
the open set had none on tracks 0–7 — load one manually first, or use a set
that has one). Wrap in `/live/song/begin_undo_step` / `end_undo_step` and
restore every change. Device properties are not in Seshat's subscribed set
(grep the log for "Adding listener"), so start/stop here is safe.

1. **Per-device name subscribe.** Send `/live/device/start_listen/name t d`
   for two different devices. Evidence: two log lines
   `Adding listener for device (t, d), property: name` with **distinct**
   index tuples, and no `Removing listener` between them (the collapse bug
   would remove the first).
2. **Push carries identity.** Rename one device in Live's UI. Evidence: log
   line `Property name changed of device (t, d): (<new name>,)` naming the
   right tuple. (Rename it back; it's inside the undo step regardless.)
3. **type/class_name error.** Send `/live/device/start_listen/class_name t d`.
   Evidence: an `Error handling OSC message /live/device/start_listen/class_name`
   log line whose traceback names `add_class_name_listener`, and no
   `Adding listener` line.
4. **Float parameter identity.** Send `start_listen/parameter/value` with
   float args, then `stop_listen/parameter/value` with the equivalent ints.
   Evidence: `Adding listener for device parameter (t, d, p)` with an
   **int** tuple, then `Removing listener` for the same tuple — no
   `No listener function found` warning.
5. **Cleanup.** `stop_listen/name` for both devices from check 1, evidence
   `Removing listener` lines; `end_undo_step`.

Uncovered even then: nothing material — the two halves are fully exercised
by 1–4. The `parameters` list listener (`add_parameters_listener`) is
untouched and untested; it is out of scope.

## Downstream

**Pin bump only.** Seshat sends no `/live/device/start_listen|stop_listen`
address from `lib/` (verified 2026-08-27 against `/Users/patrick/seshat`),
so no decoding or unsubscribe change is needed. The hobbled-behaviour
warning its integration relies on lives in the vendored `priv/AbletonOSC/API.md`
and is replaced by the new contract in the same pin bump.
`vendored_addresses_test.exs`'s `/live/device/{start,stop}_listen/<property>`
doc patterns remain valid — no address added or removed. If Seshat later
wants a device-name mirror, the per-device push now supports it; that is
Seshat roadmap material, not part of this change.

## Out of scope

- The device `parameters` list listener (`add_parameters_listener`) and the
  other observable Device members the dump surfaced (`is_active`,
  `latency_in_ms`, `latency_in_samples`, `is_using_compare_preset_b`) — new
  address surface; belongs with the device-read buckets (roadmap B-2 /
  device work), not a defect fix.
- Richer `DeviceParameter` listeners (`display_value`, `state`,
  `automation_state`, `name`) — roadmap **B-2 · DeviceParameter rich reply**.
- Return/master device listeners (none exist there) — roadmap **A-3 ·
  Return / master `Track` parity**.
- Deregistering `start_listen/type|class_name` or aliasing them to anything
  — kept registered with an honest structured error, as decided in Context.
- `handler.py` — no changes; its lifecycle semantics are already correct and
  pinned by `test_handler_lifecycle.py`.

## Open questions

None. The one genuine unknown the roadmap entry contained — whether `type`
and `class_name` are observable at all — was measured closed on 2026-08-27
(Live 12.4.3, `dump_lom`: they are not). The Seshat-consumer question was
closed by reading the Seshat checkout directly. Remaining risk is confined
to what only Live can confirm, and the Live verification section names the
exact evidence for each check.

---

## Live verification — RESULT, 2026-08-27 (post-install)

Supersedes the "SKIPPED BY ENVIRONMENT" banner above. Live 12.4 (PID 85482),
this checkout installed and Live restarted. Operator loaded on tracks 0 and 1
via `/live/browser/load_item` — the plan-time set had no device on any track,
which is why these checks could not run then.

- **Check 1 — per-device name subscribe: PASS.**
  `/live/device/start_listen/name 0 0` → immediate push
  `/live/device/get/name (0, 0, 'Operator')`;
  `/live/device/start_listen/name 1 0` → `(1, 0, 'Operator')`. Two devices
  subscribed independently, each push carrying its own `(track_id, device_id)`.
  Before this change the registration was per-property and process-wide, and the
  push carried a bare value with no identity at all.
- **Check 2 — push carries identity on rename: NOT RUN.** Renaming a device
  requires the Live UI: there is no `/live/device/set/name` address (only
  `get/name`), so this cannot be driven over OSC. The identity-carrying shape is
  nonetheless established by check 1's immediate pushes, which are emitted by the
  same code path. Outstanding: a UI rename to observe a change-triggered push.
- **Check 3 — type/class_name error: PASS, and the roadmap premise is disproved
  in production.** `/live/device/start_listen/class_name 0 0` →
  `/live/error ('request','/live/device/start_listen/class_name',"'Device' object has no attribute 'add_class_name_listener'",2,0,0)`;
  `start_listen/type` → the same with `add_type_listener`. Live itself confirms
  what the plan-phase `dump_lom` measurement found: these two properties are not
  observable and `start_listen` on them never worked and cannot work. The error
  envelope matches API.md exactly.
- **Check 4 — float parameter identity: PASS.** This is the item's High-priority
  defect. `start_listen/parameter/value` sent with **floats** `[0.0, 0.0, 1.0]`
  answered with **ints**: `/live/device/get/parameter/value (0, 0, 1, 0.0)` plus
  `.../value_string (0, 0, 1, 'Alg. 1')`. `stop_listen/parameter/value` then sent
  with **ints** `[0, 0, 1]` matched the key and unsubscribed silently — no error,
  no "not listening" warning. A float-sending client can now unsubscribe from
  what it subscribed to; before, the mixed-type key mismatch leaked the listener.
- **Check 5 — cleanup: PASS.** After `stop_listen/name` for both devices, no
  further device pushes were emitted.
