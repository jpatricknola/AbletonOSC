# Plan: Normalize listener argument identity in scene.py, clip.py, clip_slot.py, and the device.py property pair

Roadmap item: **Normalize listener argument identity in scene.py, clip.py,
clip_slot.py, and the device.py property pair** (source: pr-review of the
`device-listener-identity` branch, `5d0ec50`, findings 1 and 7 — both filed
non-blocking and recommended as this follow-up). No dependencies.

## Context

The shipped item "Device listener identity — parameter indices and property
listeners" established one rule for `abletonosc/device.py`'s parameter
listeners: **listener identity is a tuple of ints, normalized at the callback
boundary, truncated to exactly the arguments that are part of the identity,
and used identically for the LOM lookup, the bookkeeping key, and the push
echo.** Two gaps its review found are the whole of this item:

1. `scene.py`, `clip.py` and `clip_slot.py` pass the **raw OSC arguments**
   into `_start_listen`/`_stop_listen`. Each wrapper int-casts its indices
   for the LOM *lookup* but hands the callee `params[0:]` /
   `tuple(params[0:])` unmodified (`scene.py` `create_scene_callback`'s
   `include_ids` branch; `clip.py` `create_clip_callback`'s and `clip_slot.py`
   `create_clip_slot_callback`'s `pass_clip_index` branches — all three used
   **only** by the `start_listen`/`stop_listen` registrations, verified by
   reading every call site).
2. `device.py`'s property listen pair (`name`/`type`/`class_name`)
   normalizes its two indices but does not truncate:
   `create_device_callback`'s `include_ids` branch passes
   `(track_index, device_index, *params[2:])` unconditionally.

### What research changed about the roadmap entry

The entry's headline defect — "a start keyed on floats and a stop keyed on
ints never share a bookkeeping entry" — is **not true for equal-valued
numbers**. Measured 2026-08-27 on current master (`64a5058`), driving the
real `SceneHandler` Live-free through the `tests_unit/` loader with fakes:

- `start_listen/name 0.0` keys `("name", (0.0,))`; `stop_listen/name 0`
  **finds and removes it**. CPython tuple keys compare numerically
  (`(0.0,) == (0,)`, equal hashes), so an integral-float start / int stop
  pair does *not* leak. The same equality is why the shipped device fix's
  mixed-type checks passed against Live.

The real, measured defects are adjacent to the claimed one:

- **The push echoes the raw client-typed identity.** The float start above
  immediately pushed `/live/scene/get/name (0.0, 'A')` — a float32-tagged
  scene id — while the query reply for the same property echoes ints
  (`scene_index = int(params[0])` builds the reply envelope). Same value,
  different wire type, and the asymmetry persists on every subsequent push
  for the life of the subscription.
- **A non-integral float subscribes one object and keys another identity.**
  `start_listen/name 0.7` subscribed scene **0** (the lookup truncates) but
  keyed `("name", (0.7,))` and pushed `(0.7, 'A')` — a push attributed to a
  scene that doesn't exist, and a listener that `stop_listen/name 0` misses
  (`0.7 != 0`), **leaking it until reload**.
- **A trailing extra argument poisons the key.** `start_listen/name 1 99`
  keyed `("name", (1, 99))` and pushed `(1, 99, 'B')` — a bogus third field
  a decoder reads as data — and the well-formed `stop_listen/name 1` missed
  the key ("No listener function found"), **leaking the listener until
  reload**. This is defect 2's shape, present in all four files.

So the item is real and the fix is exactly the roadmap's Goal; only the
mechanism of the leak differs from the entry's description (extras and
non-integral floats leak; equal-valued floats merely echo the wrong type).

### What research confirmed

- **None of the three files has device.py's old collapsed-key defect.** The
  roadmap asked this to be checked: every `start_listen`/`stop_listen`
  registration in `scene.py`, `clip.py`, `clip_slot.py` already passes
  `include_ids=True` / `pass_clip_index=True`, so identity reaches the key
  and the push. Only its *form* is wrong.
- **The `include_ids`/`pass_clip_index` branches serve the listen pairs
  exclusively.** No getter, setter, or method registration uses them, so
  truncating there cannot change any non-listener reply.
- **`handler.py` needs no changes.** `_start_listen`/`_stop_listen`/
  `_clear_listeners` already do the right thing given a canonical key
  (`listener_key = (prop, tuple(params))` both ends); the fix is entirely in
  what the wrappers hand them.
- **Import surface for tests:** `scene.py` and `clip_slot.py` import only
  `typing`/`functools`/`.handler` — constructible under `tests_unit/`'s
  synthetic root exactly like `device.py`. `clip.py` does `import Live` at
  module scope, but its only use is `Live.Clip.MidiNoteSpecification`
  *inside* `clip_add_notes` at call time — an empty stub module satisfies
  the import (Part 3 decision below).
- **Seshat** (read at `/Users/patrick/seshat`, 2026-08-27): `lib/` sends
  **no** `/live/scene|clip|clip_slot|device/{start,stop}_listen` address at
  all (its listens are song/track/return_track/master only), and every index
  it sends anywhere is an Elixir integer (OSC int32). Nothing downstream
  observes the changed behaviour.

## Wire contract

No address is added, removed, or renamed. All changes are to subscription
identity, push echo type, and malformed-request behaviour. Well-formed
int-sending clients see **zero** difference.

**Changed (behavioural) — `/live/scene/start_listen/<prop>` and
`/live/scene/stop_listen/<prop>`** (request: `scene_id`; no direct reply),
for every property in `SceneHandler`'s lists:

- Identity is normalized to exactly one int at the callback boundary:
  `int(params[0])`, arguments past the first ignored. The same tuple is the
  bookkeeping key `(prop, (scene_id,))` and the push echo.
- Pushes on `/live/scene/get/<prop>` carry `(scene_id:int, value)` — the
  query-reply shape — even when the subscription was made with floats or
  stray extras (was: raw args echoed, float ids pushed as float32, extras
  echoed as bogus fields).
- A start sent with any numeric form of index `n` is stopped by a stop sent
  with any numeric form of `n` — including the extra-arg and non-integral
  cases that leak today. Non-integral floats truncate toward zero
  (`int()` semantics), matching what the lookup already did.
- Errors unchanged: missing index → `IndexError`, non-numeric index →
  `ValueError`/`TypeError`, out-of-range index → the LOM's error — all
  already raised by the wrapper's cast/lookup *before* listener code runs,
  all delivered as structured `/live/error ("request", address, detail,
  argc, *raw_args)` by `_dispatch`.

**Changed (behavioural) — `/live/clip/start_listen/<prop>` /
`stop_listen/<prop>`** and **`/live/clip_slot/start_listen/<prop>` /
`stop_listen/<prop>`** (request: `track_id, clip_id`; no direct reply): same
rule with a two-int identity `(track_id, clip_id)`; pushes on the matching
`get/` address carry `(track_id:int, clip_id:int, value)`; arguments past
the second ignored.

**Changed (behavioural) — `/live/device/start_listen/<prop>` /
`stop_listen/<prop>` for `name`, `type`, `class_name`** (request:
`track_id, device_id`; no direct reply): the two indices were already
int-normalized by the shipped item; they are now also **truncated** —
arguments past the second are no longer part of the key or the push, so
`start_listen/name t d extra` subscribes `(name, (t, d))` and a well-formed
two-argument stop ends it (was: keyed `(name, (t, d, extra))`, pushed the
bogus field, and leaked against a well-formed stop). `type`/`class_name`
remain unobservable (structured `/live/error`, unchanged).

**Unchanged but relied on:**

- `/live/device/start_listen/parameter/value` / `stop_listen/parameter/value`
  — already exactly three ints, truncated (shipped item). The
  implementation moves the truncation point into the wrapper (Part 4) with
  **no wire-visible change**; the too-few-arguments `/live/error` and
  ignore-extras behaviours pinned by `tests_unit/test_device_listeners.py`
  must keep passing verbatim.
- Every `get/` query reply shape in the Scene, Clip, Clip Slot, and Device
  API tables — untouched (the non-listen wrapper branches are not edited).
- Subscribing pushes the current value immediately; stopping a
  never-started listener is a logged warning, silent on the wire.

## Parts

All parts land in a single commit — each code part carries its API.md rows;
Part 5 carries SESHAT.md. `FORK_GAPS.md` is untouched: this is a defect fix,
no LOM coverage changes, no inventory regeneration.

### Part 1 — `abletonosc/scene.py`

1. In `create_scene_callback`, the `include_ids` branch passes the
   normalized, truncated identity instead of the raw args:

   ```python
   if include_ids:
       rv = func(scene, *args, (scene_index,))
   ```

   (`scene_index` is the int the wrapper already computes for the lookup.)
   Add a short comment stating the identity rule, in the voice of
   `device.py`'s `include_ids` comment.
2. `API.md` § Scene API → "Scene Getters", same commit: extend the listen
   intro sentence with the identity contract — index normalized to int at
   the boundary; pushes echo `scene_id` as int in the query-reply shape;
   arguments past the index are not part of the subscription's identity and
   are ignored; float-sending clients (TouchOSC, upstream issue #33) can
   start and stop interchangeably with int-sending ones. Date the note
   2026-08-27.

### Part 2 — `abletonosc/clip_slot.py`

1. Same change in `create_clip_slot_callback`'s `pass_clip_index` branch:

   ```python
   if pass_clip_index:
       rv = func(clip_slot, *args, (track_index, clip_index))
   ```

2. `API.md` § Clip Slot API, same commit: extend the "Every `get/` property
   above also has …" paragraph with the same identity note (two-int
   identity, extras ignored, int echo in pushes).

### Part 3 — `abletonosc/clip.py` (+ `tests_unit/conftest.py` loader)

1. Same change in `create_clip_callback`'s `pass_clip_index` branch:

   ```python
   if pass_clip_index:
       rv = func(clip, *args, (track_index, clip_index))
   ```

   The docstring above it ("pass_clip_index is a bit of an ugly hack…")
   gains a sentence: the branch hands the callee the normalized identity,
   not the raw args, and why.
2. `tests_unit/conftest.py`: add `load_clip_module()` beside
   `load_device_module()`. `clip.py`'s module-scope `import Live` is
   satisfied by an **empty stub module** installed into `sys.modules["Live"]`
   only when this helper runs (guarded, like the Component stub);
   `Live.Clip.MidiNoteSpecification` is only dereferenced inside
   `clip_add_notes` at call time, which no test in this item dispatches.
   Update the conftest module docstring: the "one narrow exception to no
   Live stubs" sentence becomes two exceptions, both import-only shims that
   pretend to no Live behaviour. Also add `load_scene_module()` and
   `load_clip_slot_module()` (no stubs needed — they import only
   typing/functools/.handler).
3. `API.md` § Clip API, same commit: extend the listen intro paragraph
   ("Every `get/` property below also has …") with the identity note.

### Part 4 — `abletonosc/device.py` property-pair truncation

1. `create_device_callback` gains an identity-arity keyword, decided here
   (the roadmap left it open): a parameter on the wrapper, because
   per-callee truncation is impossible for the property pair — its callees
   are the base class's `_start_listen`/`_stop_listen`, which must stay
   generic. Shape:

   ```python
   def create_device_callback(func, *args, include_ids: bool = False,
                              id_count: int = 2):
       ...
       if include_ids:
           rv = func(device, *args, tuple(int(p) for p in params[:id_count]))
   ```

   The property listen pair keeps the default (`id_count=2`); the parameter
   pair registers with `id_count=3`. Extend the existing `include_ids`
   block comment: identity is normalized **and truncated** here, and
   `id_count` is how a callee declares how many leading arguments are its
   identity.
2. `device_get_parameter_value_listener` and
   `device_get_parameter_remove_value_listener` keep their internal
   three-int normalization — it is now redundant on the dispatch path but
   remains load-bearing for the direct call the start path makes into the
   remove function, and costs nothing. Their comments stay accurate either
   way; adjust only if wording now overclaims where truncation happens.
3. Behaviour to preserve exactly (pinned by existing tests):
   `start_listen/parameter/value` with two args → structured `/live/error`
   (`params[:3]` of two elements still leaves `int(params[2])` in the
   callee to raise `IndexError`); with four args → fourth ignored.
4. `API.md` § Device API → "Device: Listening", same commit: the paragraph
   "**Indices are normalised to ints** (2026-08-27) — …" currently ends
   "this rule is parameter-only, since the property pair takes exactly two
   arguments; sending **fewer** than three to the parameter pair is a
   malformed request…". Rewrite: truncation is now uniform — arguments past
   a subscription's identity (two for the property pair, three for the
   parameter pair) are ignored everywhere; too few arguments remain a
   structured `/live/error`. Keep the date stamp, adding 2026-08-27 for
   this revision is unnecessary (same date) but update if implementation
   lands later.

### Part 5 — tests and SESHAT.md

1. **New `tests_unit/test_listener_identity.py`** — scene, clip, clip_slot
   driven end to end through the production `OSCServer` (the
   `server`/`receiver` fixtures and `dispatch` helper, per
   `test_device_listeners.py`'s pattern), with local fakes: `FakeScene`
   (settable `name`, `add_name_listener`/`remove_name_listener`),
   `FakeClip` (same), `FakeClipSlot` (`has_clip`,
   `add_has_clip_listener`/`remove_has_clip_listener`, plus a `clip`
   attribute holding the `FakeClip`), `FakeTrack` (`clip_slots`),
   `FakeSong` (`scenes`, `tracks`), `FakeManager`. Construct each handler,
   then assign `handler.song` (callbacks read it at dispatch time). Cases,
   for each of the three handlers:
   - **Float start normalizes.** `start_listen/<prop>` with float ids →
     key is the int tuple; immediate push on `get/<prop>` echoes ints
     (assert `type(...) is int` on each echoed id — the value-equality trap
     is exactly what let the old behaviour look correct).
   - **Non-integral float start is stoppable.** Start with `0.7` (scene) /
     `0.7, 0.2` (clip, clip_slot) → subscribes object 0, key is `(0,)` /
     `(0, 0)`, push echoes `0`; `stop_listen` with int `0`s removes it —
     the leak measured on master.
   - **Extra-arg start is truncated.** Start with one trailing junk arg →
     key excludes it, push excludes it, well-formed stop removes it — the
     other leak measured on master.
   - **Mixed-type restart is idempotent.** Float start then int start →
     one key, one registered callback on the fake.
   - **Change push carries int identity.** Mutate the fake, fire its stored
     callback, assert the push tuple.
   - **`clear_api()`** after a float/extra start empties the dicts and
     unbinds the fake.
   - **Query regression.** One `get/<prop>` per handler still replies
     `(ids..., value)` unchanged — guards the untouched wrapper branches.
2. **Extend `tests_unit/test_device_listeners.py`**:
   - `start_listen/name t d junk` → key `("name", (t, d))`, push
     `(t, d, name)`, and `stop_listen/name t d` removes it.
   - `stop_listen/name t d junk` stops a well-formed start (symmetry).
   - Existing parameter-pair tests (`…ignores_arguments_past_the_third`,
     `…too_few_arguments_is_a_structured_error`, the mixed-type and
     idempotency cases) must pass **unmodified** — they are the tripwire
     that Part 4's refactor is wire-invisible.
3. **`SESHAT.md`**, same commit:
   - § "Fixes to upstream's own code": extend the existing
     "`device.py` — listener identity is a tuple of ints…" bullet (or add a
     sibling) — the rule now covers `scene.py`, `clip.py`, `clip_slot.py`
     and the device property pair's truncation; name the measured defects
     (raw-typed push echo, extra-arg and non-integral-float leaks) and the
     downstream verdict (pin bump only; Seshat sends none of these listens).
     While editing that bullet, also **correct its parameter-listener
     sentence** "a start sent as floats keyed a different bookkeeping entry
     from a stop sent as ints, so the stop missed and the listener leaked
     until reload" — disproved by this item's measurement (Context): CPython
     tuple keys compare numerically, so equal-valued float/int keys are the
     same dict entry, and pre-fix a float subscribe never registered at all
     (the raw-value `TypeError` on `device.parameters[params[2]]` aborted
     it). The pre-fix float defects were the failed subscribe and the raw
     echo, not a key mismatch — this misstatement is what the roadmap entry
     for this item inherited, so it must not survive in SESHAT.md.
   - § Merge hazards: extend the existing `create_device_callback` bullet
     or add one naming `create_scene_callback`, `create_clip_callback`,
     `create_clip_slot_callback` — upstream's versions of these closures
     pass raw args, so a merge that takes upstream's file reverts this
     silently; `tests_unit/test_listener_identity.py` is the tripwire.
   - Do **not** touch the `AbletonOSCHandler.__init__` merge-hazard bullet
     or `tests_unit/test_handler_subclass_contract.py` — they belong to the
     in-flight "Verify handler `class_identifier` and lifecycle invariants"
     branch (`handler-class-identifier-invariants`, PR #9).

## Testing

`python3 -m pytest tests_unit/` is the gate and covers everything above:
dispatch through the production server and production handlers, key
normalization and truncation, push echo types, leak regressions, error
envelopes — all Live-free. Not covered there: whether real
`Scene`/`Clip`/`ClipSlot`/`Device` LOM objects behave as the fakes do
(`add_<prop>_listener` existence and semantics) — but this change does not
alter *which* properties are subscribed, only the tuple handed to code that
already runs against them, so the residual Live risk is the same code path
the current release already exercises. `tests/` mutates a running Live on
import and stays out of the gate.

## Live verification

Precondition for every check: the Remote Scripts copy equals this checkout
byte for byte (`diff -rq --exclude=__pycache__ abletonosc "$HOME/Music/…/
Remote Scripts/AbletonOSC/abletonosc"`) **and** Live has been restarted
since it was copied — files on disk are not code in memory. (At planning
time the installed copy equals *master*; once this branch exists it will
differ until installed.) Method: `API.md` § "The no-probe variant" —
fire-and-forget UDP to 127.0.0.1:11000, evidence read from the installed
`logs/abletonosc.log` (Seshat holds reply port 11001). These checks start
and stop listeners but mutate no document state, so no undo step is
required; "restored" means every started listener is stopped, verified in
the log. None of the scene/clip/clip_slot properties used are in Seshat's
subscribed set (its listens are song/track/return_track/master only), so a
concurrent Seshat session is undisturbed.

1. **Scene float identity.** Send `/live/scene/start_listen/name` with
   float `0.0`. Evidence: log line `Adding listener for scene (0,),
   property: name` — the tuple printed with an **int**, and the immediate
   push logged. Then `stop_listen/name` with int `0`: `Removing listener
   for scene (0,)`, no "No listener function found" warning.
2. **Scene extra-arg truncation.** `start_listen/name 0 99` → `Adding
   listener for scene (0,)` (no `99` in the tuple); `stop_listen/name 0`
   removes it.
3. **Clip two-int identity.** On a track/slot with a clip:
   `start_listen/playing_position 0.0 0.0` → `Adding listener for clip
   (0, 0)`; `stop_listen/playing_position 0 0` removes it.
4. **Clip slot.** `start_listen/has_clip 0.0 0.0` → `Adding listener for
   clip_slot (0, 0)`; stop with ints removes it.
5. **Device property truncation.** Requires a device on a regular track
   (load one first if the set has none, and delete it after — that pair is
   the one mutation, wrapped in `begin_undo_step`/`end_undo_step`).
   `start_listen/name 0 0 99` → `Adding listener for device (0, 0)`;
   `stop_listen/name 0 0` removes it.
6. **Parameter pair regression.** `start_listen/parameter/value 0 0 1 99`
   → `Adding listener for device parameter (0, 0, 1)`;
   `stop_listen/parameter/value 0 0 1` removes it — proving Part 4 did not
   move the parameter pair's behaviour.

Remains uncovered even then: a change-triggered push for scene/clip
properties (needs a UI edit; the immediate-push echo exercises the same
code path, as it did for the device item), and non-integral-float lookup
against a real LOM vector (the truncation happens before the LOM is
touched, so nothing new reaches Live).

## Downstream

**Pin bump only.** Verified 2026-08-27 against `/Users/patrick/seshat`:
`lib/` sends no `/live/scene|clip|clip_slot|device/{start,stop}_listen`
address, and every index Seshat sends is an integer, so even the addresses
it does use see identical behaviour. No address added/renamed/removed —
`vendored_addresses_test.exs` patterns stay valid. The vendored
`priv/AbletonOSC/API.md` picks up the new identity notes with the pin.

## Out of scope

- **`track.py` / `track_callback.py` listeners.** `include_track_id` builds
  `tuple([track_index] + params[1:])` — index already int (and the wildcard
  fan-out generates ints), but trailing args are not truncated, so the
  extra-arg residual exists there too, including the mixer pair. Not named
  by this item's title or Why; if it is worth doing it earns its own
  roadmap entry citing this plan — do not let it creep in here.
- **`return_track.py` / master listeners.** Hand-rolled per-property pairs
  with their own identity handling; fork-only code, same residual question,
  same disposition as track.py.
- **`song.py`, `view.py`, `song_structure.py` listeners** — identity is the
  empty tuple (no index arguments); the rule is vacuous there.
- **Which properties are observable.** Subscribing to a property whose LOM
  object lacks `add_<prop>_listener` errors structurally today and after
  this change; auditing the scene/clip lists against the LOM is gap-bucket
  work, not identity work.
- **`clip_slot.py`'s per-dispatch `self.logger.info("clip_slot %s %s -> %s"…)`
  line** — log noise, upstream-inherited, untouched (bounded-log-retention
  territory, and the "Low-priority issues" opportunistic bucket).
- **Ship-time housekeeping note for `/ship`:** the archived
  `docs/archive/PLAN_device_listener_identity.md` banner says the follow-up
  "went to ROADMAP.md as *Normalize listener argument identity…*" — when
  this item ships and the entry is deleted, amend that banner clause to
  point at this plan's archive instead.

## Open questions

None. The three questions the roadmap entry left were all closed at
planning time:

- *Does int-casting alone close the scene/clip/clip_slot gap?* No —
  measured Live-free on master (Context): truncation is required too
  (extra-arg starts leak against well-formed stops), and the entry's
  equal-valued float/int leak does not actually occur (CPython numeric key
  equality); the leaks are the extra-arg and non-integral-float cases.
- *Do the three files have device.py's collapsed-key property-pair shape?*
  No — all their listen registrations already pass ids (Context).
- *Wrapper arity parameter vs per-callee truncation for `device.py`?*
  Decided: wrapper parameter (`id_count`, default 2), because the property
  pair's callees are the shared base-class methods and cannot truncate
  per-callee (Part 4).
- *Does Seshat send float indices to these addresses?* It sends nothing to
  these addresses at all, and integers everywhere else (Downstream).
