# This fork

`jpatricknola/AbletonOSC` is a fork of [ideoforms/AbletonOSC](https://github.com/ideoforms/AbletonOSC),
maintained as the bridge for [Seshat](https://github.com/jpatricknola/seshat) —
an AI assistant for Ableton Live. Seshat consumes this repository as a git
submodule at `priv/AbletonOSC`; `mix abletonosc.install` copies the tree
wholesale into the user's Remote Scripts directory.

This file lists **every divergence from upstream**, and is the thing to keep
current when a commit lands here. Its complement is [FORK_GAPS.md](FORK_GAPS.md):
what the Live Object Model exposes that this fork does *not* yet — the
inventory a handler is drawn from, kept here because the fork is where the
gap closes. Before the fork, Seshat's additions lived as
four files patched into the user's install at install time, which made the delta
self-describing by construction. A fork loses that property unless someone
writes it down. This is that.

## Why the fork exists

Two things could no longer be done by patching upstream's install:

1. **A second override.** Seshat's extensions ride on `add_handler` being a
   dict assignment — register an address again and the later registration wins.
   That works for handlers. Upstream PR #213 fixes a one-line logger bug in
   `clip_slot.py` that raises a `RemoteScriptError` on *every* clip operation;
   there is no handler seam to override, only the file itself.
2. **Editing upstream's own files.** Upstream PR #208's resilience fixes live in
   the handler base class and in the OSC server's `process()` tick. No
   `add_handler` seam exists there at all.

Upstream is dormant (last merge 2025-11-16, 33 PRs open, some since 2023), so
waiting for these fixes to arrive by upgrade was not a strategy, and the fork's
ongoing cost — merging upstream releases — is close to zero.

## Divergences from upstream

### Fixes to upstream's own code

- **`handler.py` — base invariants exist before `init_api()`.** Upstream's
  `AbletonOSCHandler.__init__` called `self.init_api()` — the overridable
  route-registration hook — *before* creating `listener_functions`,
  `listener_objects` and `class_identifier`, so every subclass registered its
  routes against a half-built object. Touching either listener dict during
  registration raised `AttributeError`, and `class_identifier` did not exist
  yet; worse, the base's trailing `self.class_identifier = None` ran *after*
  `init_api()`, so anything a subclass set early was clobbered back to `None`.
  The bug was latent — no `init_api()` body in this fork reads those
  attributes at registration time, only later from callbacks — which is
  exactly what makes it dangerous: `/live/<class_identifier>/get/<prop>`, the
  address every listener push goes out on, was correct by accident of timing.
  `BrowserHandler` already carried a `hasattr` workaround comment for it.

  The constructor is now ordered `Component.__init__` → `logger` / `manager` /
  `osc_server` → `listener_functions` / `listener_objects` /
  `listener_lom_properties` → `init_state()` → `init_api()`, and the lifecycle
  is declarative rather than positional (`listener_lom_properties` is the
  fork's third listener dict — see the aliasing bullet below):

  - **`class_identifier` is a class attribute.** Base declares
    `Optional[str] = None`; each subclass declares its own in the class
    statement (`class_identifier = "track"`, …). Identity is therefore set
    before the instance exists, and all eleven now-empty subclass `__init__`
    overrides are gone. `ApplicationHandler`, which never declared one at all,
    gains `"application"` (it registers no listeners and uses no generic
    property path, so this changes nothing on the wire — only a hypothetical
    future log line that would have read `None`).
    `SongStructureHandler` keeps its deliberate `"song"`, sharing
    `SongHandler`'s namespace because its pushes go out on `/live/song/…`.
  - **`init_state()` is a new overridable no-op** — the one documented home
    for subclass instance state, guaranteed to run after every base invariant
    and strictly before any route is registered. `ClipHandler`'s
    `_clip_notes_cache`, `BrowserHandler`'s `_index_cache` (whose `hasattr`
    guard and workaround comment are gone), `MidiMapHandler`'s
    `midi_map_handle` and `SongHandler`'s `last_song_time` moved there.
  - **`manager.py` reloads `abletonosc.osc_server` and `abletonosc.handler`
    first.** They previously reloaded *after* `application`, `clip`,
    `clip_slot` and `device`, so a single `/live/api/reload` would construct
    those four handlers on the stale base: `init_state()` never called
    (`AttributeError` on the first `/live/clip/get/notes`) and the old base's
    trailing `class_identifier = None` shadowing the new class attribute, so
    their listener pushes would go out on `/live/None/get/<prop>` — silently.
    Same ordering rule the list already documents for `track_callback` before
    `track`. General reload robustness is a separate, still-open item.

  No address, request shape or reply shape changes. `tests_unit/
  test_handler_lifecycle.py` constructs the *real* `AbletonOSCHandler` outside
  Live for the first time (conftest's `load_handler_module()` stubs the one
  trivial `ableton.v2` base class it needs) and pins the order, the hook, and
  the listener bookkeeping. The subclass *declarations* — each handler's
  `class_identifier` value, and the absence of a subclass `__init__` or any
  `self.class_identifier` assignment — are pinned separately and without
  imports by `tests_unit/test_handler_subclass_contract.py`, which reaches
  all twelve production subclasses by parsing them.

- **`handler.py` — `_stop_listen` unbinds from the stored object.** Upstream
  unbinds the listener from the target it is *handed*. Listeners are keyed by
  track/return index but bound to a LOM object, and indices renumber when
  something is deleted or reordered: delete track 0 of `[A, B, C]` and index 0
  now means B, so a re-subscribe hands the base class B while the stored
  callback belongs to A. `B.remove_name_listener` raises, the base swallows it
  as "likely benign", and the dict entry is dropped anyway — leaving A's
  listener alive forever, still pushing under index 0. `_start_listen` already
  records the true object in `listener_objects`; `_stop_listen` now reads it.

- **`handler.py` — `_start_listen` can subscribe to one LOM property and push
  under another name.** Upstream derives three things from the single `prop`
  argument: the bookkeeping key `(prop, params)`, the push address
  `/live/<class_identifier>/get/<prop>`, and the `add_%s_listener` /
  `remove_%s_listener` accessor names. That forces one OSC listener address per
  observable property, which `Song.View` breaks: it has exactly one observable
  selection property, `selected_track`, and this fork needs two OSC listeners
  over it — `start_listen/selected_track` pushing a regular-track index (or
  `-1`), and `start_listen/selected_track_identity` pushing the
  `(category, index)` pair (see the `view.py` additions below).

  `_start_listen` therefore takes an optional `lom_property`, which splits the
  accessor name off from the key and the address; `None` — every upstream call
  site, and every other one in this fork — means "same as `prop`" and is
  behaviour-identical to upstream. The mapping is *stored*, in a third dict
  `listener_lom_properties`, rather than merely passed: `_clear_listeners`
  reconstructs `(prop, params)` from the key alone and has no way to know an
  alias was ever used, so `_stop_listen` has to recover the LOM name itself or
  `/live/api/reload` would leave the identity listener bound forever, still
  pushing after the handler that owns it is gone. `_stop_listen` reads it with
  a `.get(listener_key, prop)` fallback, so an unaliased or stale key behaves
  exactly as it did before aliasing existed.
  `tests_unit/test_listener_alias.py` covers all of it against the real base
  class.

- **`track.py` — a wildcard track getter answers for every track.**
  Upstream's `create_track_callback` accepts `"*"` in the track-index slot and
  loops over `song.tracks`, but the loop body ends in
  `return (track_index, *rv)` as soon as a callback produces a value — so
  every `/live/track/get/<prop> *` answered for track 0 and stopped.
  Setters, methods and listener registrations were unaffected only because
  their workers return `None` and the loop therefore ran to completion; the
  bug was getters-only, and silent (one plausible-looking reply, no error).
  The wildcard branch now collects `(track_index, *rv)` for every track and
  returns the **list**, which `_dispatch` sends as one datagram per track on
  the concrete request address — the same reply grammar the `*` *listener*
  pushes have always used, so one address never carries two shapes. Ascending
  index order, all-or-nothing on failure (see below). The full contract is in
  `API.md` § Track API; upstream never stated one.

  Two structural consequences, both fork-only:

  - **New module `abletonosc/track_callback.py`.** The factory was a closure
    over `self` inside `TrackHandler.init_api`, and `track.py` imports
    `ableton.v2` through `handler.py`, so nothing about the fan-out could be
    tested outside Live. Lifted out and parameterised on a `get_tracks`
    callable (`TrackHandler` passes `lambda: self.song.tracks`, preserving
    per-dispatch resolution of `self.song`), it is imported by `track.py` and
    covered directly by `tests_unit/test_track_callback.py` — the first
    tests_unit coverage of shipped handler-side code rather than a
    shape-replica. `track.py` keeps a small local helper of the original
    name so every registration line is unchanged.
  - **`manager.py` reloads `abletonosc.track_callback` before
    `abletonosc.track`.** Without it, `/live/api/reload` re-executes track.py's
    `from .track_callback import ...` against a stale module and wrapper edits
    appear not to take.

  **All-or-nothing on error, deliberately.** Within one endpoint the fan-out
  members are homogeneous — the same property read off every track, every
  index valid by construction — so a mid-loop failure means something
  systemic, not that this track is inapplicable. A failure at track `i`
  therefore aborts collection before anything is sent: zero replies and one
  `/live/error ["request", <address>, "wildcard fan-out failed at track i: …", 1, "*"]`.
  No partial fan-out, and no invented multi-error scheme. This differs on
  purpose from the *address* fan-out above, whose members are heterogeneous
  and where one bad match must never silence the rest.

  **The re-raise preserves the exception class** (`_raise_with_track_context`),
  mutating `args` rather than wrapping. `_is_wildcard_skip` classifies by
  exception class, so a composed `/live/track/get/* *` must still see a
  per-track `ValueError` as a `ValueError` to skip an arg-mismatch endpoint
  like `get/send` silently; a `RuntimeError` wrapper would turn every
  documented skip into a per-endpoint error datagram. The same class-based
  test is blind to *when* in the fan-out the exception arrived: a matched
  getter that fails on track 1 after already succeeding on track 0 is
  classified identically to the immediate arg-mismatch case, so it answers
  with nothing at all under composition — not even the replies already
  collected. Pinned by
  `test_composed_wildcard_mid_fan_out_skip_class_failure_is_silent`.

  **Downstream: pin bump only.** No address added, renamed or removed; the
  single-index reply shape, setter silence and listener pushes are all
  byte-identical. See the client guidance under the wildcard note below.

- **`track.py` — mixer listeners join the same bookkeeping.**
  `_start_mixer_listen` never populated `listener_objects`, so `_clear_listeners`
  (which iterates *all* of `listener_functions`) raised `KeyError` on script
  reload whenever a volume or panning listener was active. And
  `_stop_mixer_listen` re-resolved the `DeviceParameter` from the passed track,
  reproducing the wrong-object unbind above. Both now key as
  `("value", (*params, prop))` with the `DeviceParameter` stored, and stopping
  delegates to the fixed base `_stop_listen`.

- **`device.py` — parameter listeners join the same bookkeeping.** The same two
  bugs as `track.py`'s mixer listeners, in the third place upstream listens to a
  `DeviceParameter`: the key was `('device_parameter_value', …)` and
  `listener_objects` was never populated, so `_clear_listeners` raised on reload
  whenever a parameter listener was active — and since `Manager.clear_api`
  iterates its handler list unguarded, every handler after `DeviceHandler`
  (Seshat's three among them) then kept listeners bound to the dead song object.
  Now keyed `("value", (track, device, parameter))` with the `DeviceParameter`
  stored, stopping delegates to the base `_stop_listen`. Also removes a
  `NameError` in the no-listener warning path, which referenced an unbound
  `prop`.

- **`device.py` — listener identity is a tuple of ints, normalised at the
  callback boundary.** Two changes to `create_device_callback` and the
  callbacks behind it, one rule:

  *Parameter listeners.* Upstream's `include_ids` branch passed the raw OSC
  arguments through, so `start_listen/parameter/value` indexed
  `device.parameters[params[2]]` with whatever arrived. A float-sending
  client (TouchOSC, upstream issue #33 — the reason every *other* device
  callback int-casts) raised `TypeError` and could not subscribe at all, and
  any client that did get a subscription had its raw argument types echoed
  back in the push. (An earlier version of this entry said a float start
  keyed a different bookkeeping entry from an int stop, so the stop missed
  and the listener leaked. That is **wrong** and was corrected 2026-08-27 by
  measurement: CPython tuple keys compare numerically, so `("value", (0.0,))`
  and `("value", (0,))` are one dict entry — and pre-fix a float subscribe
  never registered anything at all, because the `TypeError` above aborted it
  first. The pre-fix float defects were the failed subscribe and the raw
  echo, not a key mismatch.) The wrapper now hands the callee the indices
  already cast and truncated to the identity's arity, and the parameter
  listener pair casts the third itself: exactly three ints, used for the
  `DeviceParameter` lookup, the `("value", (track, device, parameter))` key
  and the echo in both pushes.

  *Property listeners.* Upstream registered
  `/live/device/{start,stop}_listen/{name,type,class_name}` **without**
  `include_ids`, so the wrapper stripped both indices before `_start_listen`
  saw them. The push carried the bare value with no track or device echo, and
  the key collapsed to `(prop, ())` — one subscription per property for the
  whole process, where subscribing a second device silently stopped the
  first. Both are now registered `include_ids=True`: `name` subscribes per
  device and pushes `(track_id, device_id, name)` on `/live/device/get/name`,
  the same shape as the query reply. `get/` and `set/` stay without ids —
  their indices come from the wrapper's `(track_index, device_index, *rv)`
  reply envelope, and adding ids there would echo them twice.

  `type` and `class_name` are not observable in Live at all (measured
  2026-08-27 against 12.4.3 via `dump_lom`: `Live.Device.Device` has no
  `add_type_listener` / `add_class_name_listener`), so subscribing to those
  two answers a structured `/live/error` and always did. They stay registered
  for an explicit refusal rather than an unknown-address silence; the
  measurement is recorded in `API.md` § Device API so it is not re-derived.

  **Downstream: pin bump only.** No address added, renamed or removed. Seshat
  sends no `/live/device/{start,stop}_listen` address from `lib/`; the only
  thing it consumed here was `API.md`'s warning against these listeners,
  which is replaced by the real contract in the same pin. Pinned by
  `tests_unit/test_device_listeners.py`.

- **`scene.py`, `clip.py`, `clip_slot.py` and the `device.py` property pair —
  the same identity rule, applied everywhere it was still missing.** The
  device fix above established the rule; these four call sites did not follow
  it. Upstream's `create_scene_callback` (`include_ids`),
  `create_clip_callback` and `create_clip_slot_callback` (`pass_clip_index`)
  each int-cast their indices for the *LOM lookup* and then handed the callee
  `params[0:]` — the raw OSC arguments — while `create_device_callback`'s
  `include_ids` branch normalised its two indices but appended `*params[2:]`
  untruncated. Measured Live-free against master on 2026-08-27, that produced
  three defects:

  1. **The push echoed the client's number types.** `start_listen/name 0.0`
     pushed `/live/scene/get/name (0.0, 'A')` — a float32-tagged scene id
     where the query reply for the same property echoes an int, and the
     asymmetry persisted for the life of the subscription.
  2. **A non-integral float subscribed one object and keyed another.**
     `start_listen/name 0.7` subscribed scene **0** (the lookup truncates)
     but keyed `("name", (0.7,))` and pushed `0.7`: a push attributed to a
     scene that does not exist, and a listener `stop_listen/name 0` could
     never find — leaked until reload.
  3. **A trailing extra argument poisoned the key.** `start_listen/name 1 99`
     keyed `("name", (1, 99))`, pushed a bogus third field a decoder reads as
     data, and leaked against the well-formed `stop_listen/name 1`.

  All four wrappers now build the identity themselves — `(scene_index,)`,
  `(track_index, clip_index)`, and for `device.py` a new `id_count` keyword on
  `create_device_callback` (default 2, the parameter pair registers 3) — and
  pass exactly that to the callee. Truncation is uniform: arguments past a
  subscription's identity are ignored everywhere, and too *few* arguments
  remain a structured `/live/error`, unchanged. The parameter pair's wire
  behaviour is untouched by the refactor; `tests_unit/test_device_listeners.py`
  passes unmodified, which is the proof. `handler.py` needed no change — it
  was always correct given a canonical key. Downstream: **pin bump only**;
  Seshat sends none of these listen addresses (its listens are
  song/track/return_track/master) and every index it sends is an integer, so
  no well-formed client sees any difference at all.

- **`track_callback.py` — the same identity rule, for the last wrapper that
  still predated it.** `create_track_callback`'s `include_track_id` branch got
  the index half right — `track_index` is `int(params[0])` on the concrete
  path and a generated `range()` int on the wildcard path, so there was never
  a float defect here — but it then appended the raw OSC tail after it:
  `func(track, *args, tuple([track_index] + params[1:]))`. Nothing bounded
  that tail, and because `handler.py` pushes `(*params, *value)`, every
  argument past the index entered the bookkeeping key *and* every subsequent
  push. Measured Live-free against the production `TrackHandler` on
  2026-08-27:

  1. **A trailing extra poisoned the key and leaked the listener.**
     `start_listen/name 0 99` keyed `("name", (0, 99))` and pushed
     `/live/track/get/name (0, 99, 'drums')` — a bogus third field a decoder
     reads as data. The well-formed `stop_listen/name 0` missed the key ("No
     listener function found"), leaking the subscription until reload.
  2. **The mixer pair leaked the same way, silently.**
     `start_listen/volume 0 7` keyed `("value", (0, 7, 'volume'))`;
     `stop_listen/volume 0` missed it with **no** warning at all, because
     `_stop_mixer_listen` is deliberately silent when nothing matches (that
     silence is what makes re-listening idempotent).
  3. **The wildcard amplified it set-wide.** `start_listen/name * 42` put the
     stray argument into *every* track's key, so a well-formed
     `stop_listen/name *` leaked one listener per track.
  4. **Non-numeric extras were accepted and echoed.**
     `start_listen/volume 1 junk` subscribed without error and pushed the
     string `'junk'` as a field on `/live/track/get/volume` — the tail is
     never cast, so garbage in the key and garbage on the wire, no
     `/live/error`.

  The branch now hands the callee exactly `(track_index,)`. That one edit
  fixes both `include_track_id` pairs — the plain property pair and the mixer
  pair — because all four call sites are listener registrations whose callees
  treat `params` purely as identity plus push prefix; `handler.py`,
  `track.py` and `manager.py` needed no change. The non-listener branch still
  passes `tuple(params[1:])` untouched, which `get/send` reads its send index
  out of. Pushes therefore always carry `track_index, value` in the
  query-reply shape, and `stop` ends a subscription however the `start` was
  spelled. `return_track.py` was audited at the same time and is clean: every
  per-property pair there keys on the *parsed* index and the master triple on
  a `"master"` sentinel, so no extra argument is ever read. Downstream:
  **pin bump only** — Seshat sends `/live/track/start_listen/<prop>` with
  exactly one integer index and no track `stop_listen` at all. Pinned by
  `tests_unit/test_track_callback.py` and
  `tests_unit/test_track_listener_identity.py`.

- **`clip_slot.py` — logger format args.** Cherry-picked from upstream PR #213.
  `self.logger.info(track_index, clip_index, rv)` passes an `int` where a format
  string belongs, raising inside every clip-slot callback and flooding Live's
  `Log.txt`.

- **`handler.py` / `osc_server.py` — per-message resilience.** The behaviour is
  upstream PR #208's — one failing message no longer aborts the rest of that
  tick's queue, which matters because Seshat sends ordered multi-message
  sequences — but the mechanism has moved since it was first hand-applied.
  `process()` keeps its try/except inside the recvfrom loop, per #208. The
  handler-local catches are gone: `_call_method` and `_set_property` now let
  exceptions propagate, because every callback invocation is caught
  per-message by `OSCServer._dispatch`, which turns the failure into the
  structured `/live/error ("request", …)` envelope described below instead of
  an uncorrelatable log line. Later messages in the same bundle and later
  queued datagrams still execute; `tests_unit/test_handler_envelope.py` pins
  both properties without Live.

  **Not taken from #208:** its reply-to-sender-port routing. Listener pushes go
  to the fixed response port regardless, so that change buys nothing here and
  touches reply correlation.

### Deliberate changes to upstream's behaviour

Not bug fixes and not extensions: places where upstream works as intended and
this fork intends something different. All of these are **security** changes,
so treat any merge that reverts one as a regression, not a preference.

- **`osc_server.py` — the OSC socket binds loopback only.** Upstream's
  `OSCServer.__init__` defaults `local_addr` to `('0.0.0.0', OSC_LISTEN_PORT)`,
  i.e. every local IPv4 interface. That is a reasonable default for upstream,
  whose users drive Live from phones, tablets and other machines on the LAN. It
  is the wrong default here: every OSC address can control Live, there is no
  authentication anywhere on the wire, and Seshat's only client is on the same
  machine. The default is now `('127.0.0.1', OSC_LISTEN_PORT)`. `Manager`
  constructs `OSCServer()` with no arguments and logs `_local_addr`, so the new
  bind is used and visible in `Log.txt` with no other change.

- **`osc_server.py` — the default reply address is never retargeted.** Upstream's
  `process()` reassigned `self._remote_addr` to the source of the most recent
  datagram, so listener pushes, `/live/startup`, `/live/error` and `/live/test`
  followed whichever client spoke last. (Upstream's own comment concedes this
  prevents listeners from more than one IP.) That assignment is gone; the default
  remote stays `('127.0.0.1', OSC_RESPONSE_PORT)` as constructed. The
  per-callback reply path in `process_message()` is untouched — it still answers
  the originating hostname on the response port, which after the bind change can
  only be loopback.

  **Merge hazard.** Either change is easy to lose: nothing fails, and locally
  everything keeps working, because loopback traffic is unaffected by both. The
  regression is silent remote exposure. Seshat's `vendored_addresses_test` greps
  this file's `osc_server.py` for the loopback default and for the absence of the
  `_remote_addr` assignment, and for this section of `SESHAT.md`. If a networked
  controller (TouchOSC and friends) is ever wanted, it gets an **explicit opt-in
  bind constant plus a security design** — do not restore the wildcard default.

- **The test harness — `tests/` is opt-in and inert, `tests_unit/` is the
  gate.** Upstream ships one test tree, `tests/`, whose `__init__.py`
  constructs an `AbletonOSCClient` and sends `/live/api/reload` **at module
  scope**. Collecting tests from the repository root — which is what
  `CONTRIBUTING.md` told contributors to do, `pytest` with no arguments —
  therefore bound the reply port and reloaded the bridge under whatever
  session the user had open, before a single test ran. The tests themselves
  assumed upstream's blank default template (exactly 4 tracks, 8 scenes, no
  clips, no devices on track 0), left mutated state behind whenever an
  assertion failed, and made every clip test depend on successfully recording
  live audio.

  In this fork:

  - `tests/__init__.py` is inert. It re-exports `TICK_DURATION` and
    `wait_one_tick()` and nothing else touches the network. It also puts the
    repository root on `sys.path` from `__file__` rather than upstream's
    cwd-dependent `sys.path.append(".")`, and imports the client absolutely
    (`from client import …`) rather than upstream's `from ..client import …`,
    which pytest cannot resolve when the checkout directory name is not a
    Python identifier — this working copy is `ableton-osc`.
  - New `tests/conftest.py` owns the only `AbletonOSCClient` in the tree, in a
    session-scoped fixture gated on **`ABLETONOSC_LIVE_TESTS=1`**. It skips —
    never errors — when the variable is unset, when reply port 11001 is busy
    (Seshat's `beam.smp` holds it whenever Seshat is running), and when Live
    does not answer `/live/test`. The reload happens there, once per opted-in
    session. It also holds the set-discovery fixtures (`num_tracks`,
    `num_scenes`, `num_return_tracks`, `midi_track`, `audio_track`,
    `empty_midi_slot`, `midi_clip`, `audio_clip`) and the
    `restored_*_property` context managers that put the set back in `finally`.
  - Every `tests/test_*.py` was rewritten to discover the set instead of
    assuming it, to stop its listeners and delete its clips in `finally`, and
    to `skip` when the open set cannot meet a precondition.
  - New `pytest.ini` sets `testpaths = tests_unit`, so bare `pytest` collects
    only the Live-free gate. New `requirements-dev.txt` (pytest only) and
    `.github/workflows/test.yml` (Python 3.11/3.12) make that gate CI.
  - `client/client.py` binds its reply socket to `127.0.0.1` instead of
    `0.0.0.0`, so the loopback-only policy above holds for the bundled client
    too. A busy port now raises `OSError` out of `__init__`, which the fixture
    turns into a skip.
  - `CONTRIBUTING.md`'s Tests section documents both suites and their real
    preconditions, and its Live-reloading section says `/live/api/reload`
    rather than the non-existent `/live/reload`.
  - `tests_unit/conftest.py`'s `Component` stub carries a **`song`**
    attribute, and the module offers **`bind_song(handler_class, song)`**.
    Live supplies a handler's song through
    `ControlSurface.component_guard()`, which `manager.py` constructs every
    handler inside — `Component.song` is a read-only property over the
    `song=` constructor argument — so `self.song` is populated from the first
    line of `init_state()`/`init_api()`. `SongHandler` and `ViewHandler` rely
    on that: they bind `self.song` and `self.song.view` into `partial()`s
    while the constructor is still registering addresses, which no
    post-construction `handler.song = ...` fixture could satisfy.
    `bind_song()` returns a per-test subclass whose `song` is a class
    attribute, which is the Live-free image of that guarantee; the stub keeps
    `song` a plain attribute rather than a property so the suite's existing
    post-construction assignments still work. Any future handler that reads
    `self.song` at registration time is testable the same way.

  The port collision with Seshat is deliberately *not* worked around: it is the
  interlock that stops this suite from firing `stop_listen` at properties
  Seshat is subscribed to. When Seshat is up, the suite skips itself.

  **Merge hazard.** See the merge-hazards section: `tests/__init__.py` is an
  upstream file, and a merge that takes upstream's version silently restores
  the import-time reload.

### Additions to upstream's code

- **`introspection.py` + `application.py` — `/live/application/dump_lom
  [path]`.** Upstream's `introspection.py` was an unused log-only helper;
  it is now the walker behind FORK_GAPS.md. The handler writes every class
  reachable from `Live` (members classified as property ro/rw, method,
  listener), Max for Live's `_MxDCore.LomTypes` exposure tables, and this
  server's registered addresses to one JSON file (default
  `logs/lom_dump.json`). `tools/lom_gaps.py` diffs the two sides into the
  generated inventory in `FORK_GAPS.md`. `manager.reload_imports` reloads
  `introspection` so the walker is hot-reloadable like the handlers.

- **`clip.py` — `quantize` in the generic methods list.** From upstream PR #198
  (that PR's warp-marker and extended-note work is not taken). Gives
  `/live/clip/quantize track_id, clip_id, grid, amount` via the existing
  `_call_method` path. `grid` is Live's `GridQuantization` enum — **not**
  `RecordingQuantization`, and **not** what this file said until 2026-07-31.
  The enum was measured against a running Live on that date (one clip per
  value, probe notes chosen so every candidate grid lands distinguishably,
  `amount` 1.0, read back with `/live/clip/get/notes`, identical in 4/4 and
  6/8):

  | Value | Grid | | Value | Grid |
  |---|---|---|---|---|
  | 0 | no grid | | 5 | **1/16** |
  | 1 | 1/4 | | 6 | 1/16 triplet |
  | 2 | 1/8 | | 7 | 1/16 triplet |
  | 3 | 1/8 triplet | | 8 | 1/32 |
  | 4 | 1/8 triplet | | ≥9 | invalid — nothing moves |

  So sixteenths is **5**, not `8`. The previous claim here (`g_8_bars=1 …
  g_half=5, g_quarter=6, g_eighth=7, g_sixteenth=8, g_thirtysecond=9`) was
  wrong in every row, as was the matching claim that there are no triplet
  grids — 1/8T and 1/16T are reachable, and only this way. There is no 1/2
  grid and no bar-length grid. Whether the song's `swing_amount` colours the
  result is **unverified** — the property is now settable (see the `song.py`
  entry below), so this is finally testable, but it has not been tested.

  Seshat's `quantize_clip` never puts these integers in front of the model: it
  takes a string grid (`"1/16"`, `"1/8T"`, …) and maps it in one private
  function, `Seshat.Tools.Handlers.grid_quantization/1`, so a future
  correction is a one-line change. The address **never replies**, so a wrong
  integer is silent everywhere except in Live.

- **`song.py` — `swing_amount` in `properties_rw`.** One line in the existing
  list, which the generation loop turns into `/live/song/get/swing_amount`,
  `/live/song/set/swing_amount`, and the matching `start_listen`/`stop_listen`.
  Upstream lists `groove_amount` but not `swing_amount`, and the two are not
  interchangeable: `Song.groove_amount` (LOM, 0.0–1.3 in practice — Ableton's
  own Move script clamps it to `GROOVE_AMOUNT_MAX = 1.3125` and renders it as
  `round(min(x, 1.3) * 100)`%) only *scales* grooves already assigned to clips
  from the Groove Pool, and nothing in this bridge can assign one
  (`Clip.groove` is an unserializable LOM object — see the `clip.py` TODO). So
  on a set with no grooves assigned, upstream's knob does nothing at all.
  `Song.swing_amount` (LOM: float, get/set/observe, 0.0–1.0, "affects MIDI
  Recording Quantization and all direct calls to `Clip.quantize`") is the
  property that makes plain MIDI swing, and it is what Seshat's
  `set_swing_amount` and its session mirror need. The property is present in
  Live 12 Suite's own LOM table (`_MxDCore/LomTypes.pyc`) and both read and
  written by Ableton's Push code (`pushbase/quantization_component.pyc`, which
  also holds a `@listens('swing_amount')` slot — so the generated listener is
  sound), where the user-facing encoder clamps it into 0.0–0.5.

  Because these addresses are generated by a loop rather than written as
  literals, Seshat's `vendored_addresses_test` cannot see them the usual way;
  it greps this file's `song.py` for `swing_amount` instead. An upstream merge
  that drops the line is otherwise invisible — every other song address still
  answers, and swing sets fail the silent way all OSC fails.

- **`song.py` — `begin_undo_step` and `end_undo_step` in the generic methods
  list.** Two lines in the existing list, which the loop turns into
  `/live/song/begin_undo_step` and `/live/song/end_undo_step` (no arguments, no
  reply, exactly like `undo`). `Song.begin_undo_step()` / `Song.end_undo_step()`
  demarcate one undo step explicitly: everything a control-surface script
  changes between the two calls collapses into a single entry in Live's undo
  history. It is the same mechanism Ableton's own Push script uses
  (`pushbase/undo_step_handler.pyc` in Live's shipped Remote Scripts).

  Without them, Live groups script-driven mutations into undo steps by its own
  rules, and those rules are activity-sensitive: measured on Live 12.4.3
  (2026-08-01), `create_track` then `write_midi_notes` collapsed into **one**
  undo step — a single undo deleted the whole track, notes and all — while the
  same pair with an intervening timed-out call landed as two. Seshat wraps every
  tool dispatch in a `begin`/`end` pair (`Seshat.Tools.Handlers.call/2`) so one
  tool call is exactly one undo step.

  Behaviour measured on Live 12.4.3 (2026-08-01) and relied upon by the Elixir
  side: an empty `begin`/`end` pair leaves the undo history untouched (so
  read-only tools can be wrapped too, and no mutating-tool list has to be kept
  in sync); an unmatched `end` is logged as an ordinary method call with no
  exception and no history effect; and `begin` does **not** refcount — with two
  outstanding, the first `end` closes the step. A leaked `begin` therefore
  self-heals at the next wrapped call's `end`.

  Because these addresses are generated by the loop rather than written as
  literals, Seshat's `vendored_addresses_test` cannot see them the usual way; it
  greps this file's `song.py` for both names instead, the same way it does for
  `swing_amount`. An upstream merge that drops either line is otherwise
  invisible — the sends still go out, nothing answers them anyway, and undo
  silently goes back to reverting whole conversations.

- **`view.py` — `/live/view/show_view`, `/live/view/hide_view`,
  `/live/view/get/is_view_visible`, `/live/view/set/detail_clip` and the
  selected-track identity trio.** The first Seshat addresses to live in an
  upstream file rather than in a handler of our own: they belong to the View
  API by every other measure, and splitting them into a fourth module would
  put two `ViewHandler`s in `manager.py`. Upstream can
  *select* a track, scene, clip or device but cannot bring the pane those live in
  into view, put a pane away, or report which panes are open —
  `Application.View.show_view`, `.hide_view`, `.is_view_visible` and
  `song.view.detail_clip` have no OSC address at all. Seshat's view steering
  (every mutating tool ends by showing what it changed) needs the first:
  selecting a clip nobody can see is not confirmation that anything happened.

  The three setters are **silent**, like upstream's setters — an unknown view
  name or an empty clip slot is logged to `Log.txt` and nothing goes on the wire,
  because a steering send must never fail or delay the tool it follows.
  `get/is_view_visible` is the exception and follows the fork's getter rule
  instead: it **always replies**, `[view_name, "ok", 1|0]` or
  `[view_name, "error", message]`, echoing the name it was asked about, because
  a caller waits on it and silence must mean only "this extension isn't
  installed". Live raises on an unrecognised name there — unlike `show_view`,
  which ignores one — so the error arm is reachable and costs a fast reply
  rather than a guard timeout.

  `hide_view` passes its name through verbatim like the others, but only
  `Browser` and `Detail` truly hide (measured against Live 12 Suite,
  2026-07-31): hiding `Session` shows Arranger and vice versa, and hiding
  `Detail/Clip` or `Detail/DeviceChain` flips the detail panel to its other tab
  rather than closing it. Seshat's `hide_view` tool therefore offers a narrower
  enum than this file accepts.

  **The identity trio — `/live/view/get/selected_track_identity` and its
  `start_listen` / `stop_listen` pair — plus a behavioural change to three
  upstream getters in the same file.** `song.view.selected_track` accepts a
  regular track, a return track or the master, and this fork can put any of the
  three there (`/live/view/set/selected_track`, `/live/return_track/select`,
  `/live/master/select`). Upstream's getters resolve it through `song.tracks`
  alone — `list(self.song.tracks).index(...)` — so the fork could *put*
  selection on a return or the master but not *report* it: `get/selected_track`,
  `get/selected_clip` and `get/selected_device` all raised `ValueError` instead
  of replying, and `start_listen/selected_track`'s push raised **inside Live's
  listener callback**, which is outside `OSCServer._dispatch`'s per-message
  catch, so no push and no `/live/error` went out at all — just a traceback in
  `Log.txt`. `get/selected_device` raised the same way whenever a regular track
  was selected but no top-level device was.

  The identity getter answers `(category, index)`, where `category` is the
  address-family prefix that reaches that track (`"track"`, `"return_track"`,
  `"master"`; the master is always index 0). The three legacy getters keep their
  shapes and answer `-1` outside their index space — `-1`, `(-1, scene)`,
  `(-1, -1)`, and `(i, -1)` for a regular track with no top-level device (none
  selected, or one nested inside a rack chain). Full contract in `API.md`
  § Selected-track identity. This is a **behavioural divergence inside an
  upstream file**: upstream raises where the fork now answers, so a merge that
  takes upstream's three getter closures reverts it silently — every address
  still exists, and a client only sees errors return the moment a return or the
  master is selected.

  Two structural consequences:

  - **New module `abletonosc/track_identity.py`** holds the whole resolution
    (`identify_track`, `selected_track_identity`, `selected_track_index`,
    `selected_device_indices`), importing nothing Live-side, on the
    `track_callback.py` model: `view.py` imports `Live` at module scope, so
    logic left as a closure inside `ViewHandler.init_api` could never be reached
    by `tests_unit/`. `tests_unit/test_track_identity.py` drives the shipped
    module directly. It is also the module the inverse resolvers landed in —
    `resolve_track` / `resolve_device`, added by A-4's object-valued reads
    (see that entry below), and what A-3 (return/master `Track` parity) will
    build on.
  - **`manager.py` reloads `abletonosc.track_identity` before
    `abletonosc.view`**, for the same reason it reloads `track_callback` before
    `track`: `view.py` does a `from` import of the resolvers, so reloading it
    afterwards is what rebinds them.

  The listen pair observes the same single LOM property as the legacy
  `selected_track` listener and pushes under its own name, via the base class's
  `lom_property` alias (see the `handler.py` aliasing bullet above). The two
  coexist: distinct bookkeeping keys, one LOM property, two callbacks, and
  stopping one does not touch the other.

  `/live/view/set/selected_device`'s reply — the one view setter that echoes —
  is **kept, deliberately, settled 2026-08-27**. It is upstream's own behaviour;
  silencing it would be a permanent behavioural divergence in an upstream file
  with breakage risk for non-Seshat clients, to remove one datagram. Seshat's
  `FollowCam` ignores it.

- **`osc_server.py` + `manager.py` — `/live/error` carries the request that
  failed.** Upstream catches a raising callback nowhere near the callback: the
  exception unwinds out of `process_message()` into `process()`'s per-datagram
  `except`, which is the only place it is logged, and by then `message.address`
  and `message.params` are long out of scope. The log record is relayed onto
  `/live/error` by `manager.py`'s `LiveOSCErrorLogHandler`, so what reaches a
  client is one formatted string — `"Error handling OSC message: Index out of
  range"` — with nothing in it to say *which* request died. A client that just
  sent a query cannot tell whether that error is its own, so it can only wait
  out its timeout. For Seshat, whose whole query pipeline is serialized behind
  one in-flight request, a vanished track index therefore stalled every OSC read
  in the process for a full five seconds.

  Both dispatch branches now funnel through one private helper,
  `OSCServer._dispatch`, which invokes the callback with both halves of the
  request still in hand and sends a two-shape contract on the same address:

  | Payload | Meaning |
  |---|---|
  | `["request", address (s), message (s), arg_count (i), *request_args]` | The request `address` + `request_args` failed in its handler callback; `message` is the exception text. `address` is always the address **the client actually sent** — for a wildcard request that is the pattern, the only address the client can correlate a pending request against, and the concrete callback address rides in `message` as `"in <callback_address>: <detail>"`. Sent **instead of** a reply — the request gets no other answer. |
  | `["log", message (s)]` | An AbletonOSC error with no originating request (parse failures, socket errors, reload failures, a handler's own internal error logs). Never correlatable. |

  The correlated contract covers exactly: uncaught exceptions from ordinary
  callbacks (both direct and wildcard dispatch), exceptions from the generic
  `_call_method` path, exceptions from the generic `_set_property` path, and
  invalid handler return values (anything that is not a tuple, a list of
  tuples, or `None`). It does **not** cover
  every semantic rejection in the fork — see the scope note below.

  `arg_count` makes the variable tail explicit and keeps a zero-argument request
  from needing a special case. `request_args` are `message.params` echoed back
  through `OscMessageBuilder`, so each keeps its wire type — note that an OSC
  `f` is 32-bit, so a client comparing the echo against what it sent must
  round-trip its own value through 32 bits first.

  The structured send goes out **directly via `self.send`**, not through the log
  relay, because the relay has no request context; the record is marked
  `extra={"osc_request_error": True}` and `LiveOSCErrorLogHandler.emit` skips
  marked records, so one failure produces exactly one datagram. (Measured on
  Live 12.4.3, 2026-08-03: the embedded `logging` does deliver `extra` through
  to a sibling handler's `record`.) The file log keeps its error-level line
  either way, now with the offending address in it. `str(e) or
  type(e).__name__` guards the empty-message case: a bare `Exception()`
  stringifies to `""`, which would render as a blank rejection in a client.

  **Wildcard matching is escaped and anchored.** Upstream compiled the raw
  request address as a regex (`address.replace("*", "[^/]+")`, matched with
  `re.match`), so `/live/*/get/tempo` also reached
  `/live/scene/get/tempo_enabled`, `/live/track/get/*` reached
  `/live/track/get/clips/name`, and any regex metacharacter in a pattern was
  interpreted as regex. Patterns now compile as
  `"[^/]+".join(re.escape(part) for part in address.split("*"))` and are
  matched with `fullmatch`. The contract this encodes: **`*` is the only
  supported metacharacter** (OSC's `?`, `[]`, `{}` and every regex character
  are literal — a documented non-goal, not an accident); `*` matches **one or
  more** non-`/` characters within a single address segment (`[^/]+` is kept
  deliberately — switching to OSC-1.0's zero-or-more would silently widen what
  existing Seshat patterns match); and patterns match **complete registered
  addresses only**. Replies from wildcard fan-out still go out on the concrete
  callback address, as before.

  **Wildcard fan-out failures are isolated.** Upstream ran matches in one
  try-free loop, so a matched callback raising anything outside
  `ValueError`/`AttributeError` aborted the remaining matches. Each match now
  dispatches independently through `_dispatch` and a failure never terminates
  the loop. The legacy skip set — endpoints that simply don't apply to the
  pattern request — is preserved **narrowly**: `ValueError`, `AttributeError`,
  and (new, the confirmed abort case) `IndexError`, when a matched endpoint
  reads a positional argument the pattern request omitted. Skips are logged at
  debug naming the concrete callback and send nothing. `TypeError` and
  `KeyError` are deliberately **not** in the set — both commonly indicate a
  real handler defect, and no broad exception class proves an argument-shape
  mismatch — so they, and every other exception, become the structured
  `("request", <pattern>, "in <callback>: <detail>", …)` error above while the
  remaining matches still run. Widening the skip set waits on per-route
  argument schemas (`issues.md`, endpoint contract inventory). The former "legacy uncorrelated error" outcome
  for wildcard failures is gone entirely.

  **`IndexError` is qualified by argument count** (`_is_wildcard_skip`), because
  the class alone carries both meanings. Live's LOM raises
  `IndexError("Index out of range")` from an out-of-range collection subscript
  — verified in `logs/abletonosc.log`, traceback through `track.py`'s
  `self.song.tracks[track_index]` — and that is the single most common way a
  request is legitimately refused. An unqualified skip would answer
  `/live/track/get/* 99` with **nothing at all**: no reply, no error,
  indistinguishable from a pattern that matched no endpoint, on the fork's most
  frequent rejection. The reproduced abort case is the opposite shape — a
  pattern carrying *no* index reaching an endpoint that reads `params[0]` — so
  `IndexError` is skipped only when `message.params` is empty, and a bad index
  (which always arrives as the argument that produced it) always reports. The
  residual imprecision is deliberately one-sided: a multi-argument pattern
  reaching an endpoint that wants one argument more than it sent (e.g.
  `/live/device/get/* 0 0` and an endpoint reading `params[2]`) reports instead
  of skipping — a correlated error naming that endpoint, with every other match
  still replying. The endpoint-contract-inventory item's per-route schemas are what remove the guess.

  **Wildcards are a fan-out, not a query — do not reach for them as a batching
  shortcut.** A pattern produces one reply per matched endpoint, each on its own
  concrete address, plus possibly an error on the pattern address. Seshat's
  `Transport.query/3` awaits a single reply, and its `/live/error` clause is
  ordered first and cancels the timer, so a wildcard sent through it resolves on
  whichever datagram lands first and discards the rest — and one failing match
  fails the whole query even while the other endpoints reply successfully.
  Correlating the error on the pattern is still right (the concrete address has
  no pending request to match, which is exactly the uncorrelated error this
  change removed); the mismatch is cardinality, so a fully successful wildcard
  is just as wrong through `query/3`, only silently. `query_batch/2` over the
  concrete addresses is the answer. Nothing in Seshat sends a wildcard today.

  **The same applies to the track-index argument wildcard.**
  `/live/track/get/<prop> *` is also a fan-out — one reply per regular track,
  all on the *same* concrete address, `track_index` leading each payload — so
  it must not go through `Transport.query/3` either, and for the identical
  cardinality reason: the query resolves on whichever track's datagram lands
  first and drops every other track. Correlating on the address cannot
  disambiguate them, only the leading `track_index` can. `query_batch/2` over
  concrete track indices remains the answer, and it is what Seshat already
  does. Nothing in Seshat sends `*` in a track index today. If a
  one-round-trip multi-track read is ever wanted, `Transport` needs a
  fan-out-aware receive path (collect N replies keyed by `track_index`, with
  its own completion rule) — a consumer decision, not something this repo can
  supply.

  **Reply validation replaced the `assert`.** Upstream checked handler return
  values with `assert isinstance(rv, tuple)` — stripped under `python -O`, and
  an uncorrelated crash otherwise. An invalid return now raises an
  explicit `TypeError` inside the same boundary, so it comes back as the
  structured error naming the request and the offending handler, identically
  for direct and wildcard dispatch. The error deliberately names only the
  return's *type*, never its repr — an invalid return may be large, sensitive,
  or capable of pushing the error datagram past UDP limits. A `None` return
  still sends nothing; `()` still sends an empty reply.

  **A list of tuples is a multi-reply.** Fork-only, added with the track
  argument-wildcard repair below. A callback may return a `list` whose every
  element is a tuple, and `_dispatch` then sends **one datagram per element**,
  in list order, all on the same reply address (the concrete callback address
  under a wildcard pattern). An empty list sends nothing, exactly as `None`
  does. Validation covers the whole list *before* the first send, so a list
  containing a non-tuple yields the structured `TypeError` error and zero
  replies — never a partial fan-out. This is the mechanism, and the only
  mechanism, by which a single request produces several replies on one
  address; handlers never call `osc_server.send` for replies themselves,
  which would bypass `_dispatch`'s reply addressing.

  Bundles are covered for free, since `process_bundle` funnels every message
  through `process_message`. `process()`'s outer `try`/`except` stays, guarding
  parse errors; callback failures no longer reach it.

  **Scope: what still doesn't use the correlated envelope.** Audited 2026-08-04
  across every `logger.error` request path. Custom browser and
  return/master handlers deliberately reply with endpoint-specific tuples
  containing `"error"` (and their paired `logger.error` lines still relay a
  duplicate legacy `("log", …)` datagram for the same failure — known, left
  for the endpoint-contract-inventory item in `issues.md` as an explicit behaviour change rather than smuggled in
  here); view-steering setters deliberately log and stay silent;
  `song/get/track_data` can log and return partial output. Only the
  dispatcher boundary sets the `osc_request_error` marker — it means "a
  structured `/live/error` was already sent", and nothing else may claim it.

  **Fire-and-forget caveat.** Seshat sends generic setters and methods with
  `Transport.send_message/2`, which returns once UDP transmission succeeds. A
  structured error arriving later is broadcast for observability but cannot
  retroactively fail that completed tool step; only an address-and-argument
  match against an active `Transport.query/3` fails fast. Honest mutation
  acknowledgement/read-back is separate work. The gain from this change is
  context — which request died, with its arguments — not delivery semantics.

  **Companion Seshat update (required before this commit is consumed, not yet
  done as of 2026-08-04).** Seshat's `vendored_addresses_test.exs` greps this
  file's `osc_server.py` for the exact fragment
  `("request", message.address, detail, …)`, which the `_dispatch` refactor
  renamed (the send now reads `("request", error_address, detail, …)`), so the
  guard will fail against this commit until it is updated to assert the
  refactored send semantically. The same companion change must update
  `API.md` where wildcard failures are documented as
  uncorrelated `"log"` messages, record there that wildcards must not be sent
  through `Transport.query/3` (see the fan-out note above — `query_batch/2` is
  the answer), re-run the Transport and vendored-address tests, and bump the
  AbletonOSC submodule pointer / install verification.
  Record the compatibility result here when that lands.

  `LiveOSCErrorLogHandler.emit` also loses upstream's
  `message[message.index(":") + 2:]`, which raises `ValueError` on any error
  message with no colon in it — swallowed by `logging`, so the relay silently
  dropped that error rather than sending it. A `partition(": ")` strip keeps the
  whole message when there is no prefix.

  **Merge hazard.** Losing either half in a merge is completely invisible: every
  address still answers, every error still shows up in `Log.txt`, and clients
  just quietly go back to paying a full timeout per rejection. Seshat's
  `vendored_addresses_test` greps `osc_server.py` for the structured payload
  (historically the fragment `("request", message.address, …)`; after the
  `_dispatch` refactor its target must be the `("request", error_address, …)`
  send — see the companion-update note above), `manager.py` for the
  `("log", …)` tag and the `osc_request_error` check, and this file for this
  section. `tests_unit/test_osc_server.py` and
  `tests_unit/test_handler_envelope.py` pin the behaviour itself without Live.

- **`track.py`, `clip_slot.py`, `song.py`, `view.py` + `track_identity.py` —
  the nine object-valued reads (roadmap A-4, 2026-08-27).** Every LOM member
  whose value is another LOM object was unreadable over the wire: the generic
  property loops hand the OSC builder an unencodable value, which becomes an
  error or a `None`. Nine new addresses, all in this fork, none upstream:

  | Address | Reply |
  |---|---|
  | `/live/track/get/group_track` | `track_index, group_track_index` (`-1` ungrouped) |
  | `/live/clip_slot/get/clip` | `track_index, clip_index, clip_index_or_-1` |
  | `/live/song/get/appointed_device` | `category, track_index, device_index` |
  | `/live/song/set/appointed_device` | (silent) |
  | `/live/song/{start,stop}_listen/appointed_device` | pushes the getter's triple |
  | `/live/view/get/selected_chain` | `category, track_index, device_index, chain_index` |
  | `/live/view/get/selected_parameter` | `category, track_index, device_index, parameter_index` |
  | `/live/view/get/mod_mapping_device` | `category, track_index, device_index` |
  | `/live/view/get/mod_mapping_parameter` | `category, track_index, device_index, parameter_index` |

  The reply pattern — indices into the collections the existing address
  families already accept, prefixed by the `(category, index)` track identity,
  `-1` for "none or not representable at top level", the **reply-only**
  category `"none"` when the member itself is `None` — is documented in
  `API.md` § "Object-valued reads" and is what the later object-family items
  (groove, racks/chains, cue points) are specified against. Nothing existing
  changes shape: every address is new, so downstream needs a pin bump and
  nothing else.

  Four of the five files are **upstream files gaining fork-owned addresses**,
  the `begin/end_undo_step` precedent. The `appointed_device` trio is
  deliberately hand-written and kept *out* of `song.py`'s generic
  `properties_r` / `properties_rw` lists (a merge that absorbed it into one
  would change the address's shape, and those lists are already a merge
  hazard of their own). `clip_slot.py`'s `get/clip` is registered with
  `pass_clip_index=True` — without it the callee receives `params[2:]`, empty
  for a two-argument get, and would have no index to answer with; that flag's
  comment no longer says "the listen pair only".

  All the resolution lives in **`track_identity.py`** (`group_track_index`,
  `owning_track_identity`, `device_identity`, `parameter_identity`,
  `chain_identity`, plus the inverse resolvers `resolve_track` /
  `resolve_device`), so it can be covered exhaustively as plain functions
  parameterised on `song`, with no handler or OSC server in the way.
  `owning_track_identity`
  climbs `canonical_parent` with a 16-level cap: the cap is what keeps a
  cyclic parent chain from hanging Live's UI thread, and exhausting it is a
  loud `ValueError` → `/live/error` rather than a sentinel. ⚠️ The ascent and
  cross-class `==` are **not yet measured against a running Live** (tier-2
  only: Live 12.4.3's own `Push2/track_selection` climbs `canonical_parent`
  off a `Live.Chain` to reach a track); see the plan's Live verification
  checks 3, 6 and 7.

  `set/appointed_device` is the only setter, and it *validates* rather than
  indexes: `"none"`, an unknown category, a negative or out-of-range index and
  a master index other than `0` are each a `ValueError`. That is a deliberate
  divergence from the legacy `/live/view/set/selected_track`, which inherits
  Python's negative indexing and silently selects the last track on a `-1`.
  New addresses have no upstream-compatibility reason to repeat that.

  `manager.py`'s `reload_imports` moves `abletonosc.track_identity` up, ahead
  of `song` and `track` as well as `view` — all three now `from`-import it.
  See § Merge hazards.

  The Live-free tripwires are `tests_unit/test_track_identity.py` (the
  resolvers), `tests_unit/test_object_reads.py` (the two wrapper-borne
  addresses, `/live/track/get/group_track` and `/live/clip_slot/get/clip`,
  dispatched through the real handlers) and — added afterwards, once the
  `Component` stub gained a `song` — `tests_unit/test_song_object_reads.py`
  and `tests_unit/test_view_object_reads.py`, which dispatch the other seven
  addresses through the real `SongHandler` / `ViewHandler`: the registrations,
  the reply shapes, the `getter=` push address, `stop_listen` bookkeeping
  across `clear_api()`, and every `set/appointed_device` rejection arriving as
  a structured `/live/error`. What none of them can prove is the behaviour
  against real LOM objects — the ⚠️ ascent and `==` questions above stay open
  until someone runs A-4's Live verification checks.

### Seshat's own handlers

Three modules that upstream has no equivalent of. Each carries its own header
comment explaining what it adds and why. They are registered at the end of
`manager.py`'s handler list; position is not load-bearing.

- **`abletonosc/browser.py`** — `/live/browser/*`. Upstream exposes no browser
  API at all. Indexing, search, load-onto-track, bulk export to JSON, and
  preview. `load_item`'s ok reply carries the loaded device's **index** as well
  as its name — `[track_index, uri, "ok", name, device_index]`, where
  `device_index` is the position in `track.devices` that
  `/live/view/set/selected_device` and the `/live/device/*` addresses take, and
  `-1` when the device isn't on the chain yet (asynchronously instantiating
  VST/AU plugins). `load_item` does not always append at the end (an
  instrument lands *before* existing audio effects), and a same-named device
  can already be on the chain, so `_loaded_device` disambiguates by diffing
  the post-load chain against a snapshot taken immediately before the load —
  the device that's new — falling back to a name match, then the last device,
  when diffing doesn't resolve it. Without the index, steering the view onto a
  freshly loaded device would cost a second round trip to re-read the whole
  chain.

  `/live/browser/load_item_on_return [return_index, uri]` and
  `/live/browser/load_item_on_master [uri]` are the same load aimed at the two
  chains upstream can't reach — `browser.load_item` loads onto
  `song.view.selected_track`, which accepts a return or the master perfectly
  well, so all three endpoints share one implementation and differ only in
  target resolution and reply shape. They are separate addresses rather than a
  widened `load_item` so the shipped address keeps its exact shape and the reply
  arity says which index space was targeted:
  `[return_index, uri, "ok", return_name, device_name, device_index]` and
  `[uri, "ok", device_name, device_index]`. The return's name is read back
  **after** the load, because Live renames an empty return the moment its first
  device lands (`A-Return` → `A-Reverb`, measured 2026-07-31).

  Both carry a guard `load_item` doesn't need. Measured 2026-07-31 on both a
  return and the master: loading a *non-effect* item with one of them selected
  does not fail — Live silently creates a new MIDI track and loads the
  instrument there, leaving the target chain untouched. So a return/master load
  is verified twice, by the set's track count being unchanged and by the
  target's chain having gained a device; either check failing is an error reply
  naming what actually happened. The stray track is deliberately **not** deleted
  — reporting it and letting the caller offer to remove it is the lesson of
  Seshat's removed `create_project`.

  `/live/browser/export` takes **no arguments** and chooses its own destination:
  it creates a uniquely named file with `tempfile.mkstemp` inside
  `~/.seshat/browser-exports` (owner-only, created on demand) and returns the
  absolute path it wrote — `[export_path, "ok", total_items]`, or
  `["", "error", message]`, which never names a partial file. It used to take a
  `dest_path` and open it with Live's privileges; that request form is now
  rejected with an error reply and an error-level log line, and nothing is
  written. Since only this handler knows an export's name, it is also the only
  thing that can sweep up an export whose reply never reached the caller: a
  startup-and-pre-export sweep deletes matching **regular** direct children of
  the export root (`os.lstat`, so a symlink is skipped rather than followed) that
  are at least ten minutes old. The age gate keeps an overlapping caller's
  finished export alive — the caller reads the file only after its reply
  arrives, outside any transport ordering, so a later export's pre-sweep can
  run mid-read — while
  bounding how long an orphaned multi-megabyte file survives. The export root is
  derived with `expanduser` + `abspath`, **not** `realpath`, because the Elixir
  consumer derives the same string with `Path.expand/1` and validates the reply
  path against it.
- **`abletonosc/return_track.py`** — `/live/return_track/*` and `/live/master/*`.
  Upstream's track addresses resolve through `song.tracks` only, so return
  tracks and the master are unreachable. `/live/return_track/select` is the same
  gap one level up: `/live/view/set/selected_track` indexes `song.tracks` too, so
  no upstream address can select a return. `song.view.selected_track` itself
  accepts any track — the master included — so that handler is the lookup and
  nothing more, and it is silent, for the same reason as the two view addresses
  above.

  The file covers the whole mixer (name, volume, panning, mute and solo per
  return; volume, panning and cue volume on the master) and the whole **device
  chain**, because every `/live/device/*` address, `/live/track/delete_device`
  and `/live/view/set/selected_device` resolves through `song.tracks` as well:
  `get/devices`, `device/get/name`, `device/get/parameters`,
  `device/get|set/parameter/value`, `device/get/parameter/value_string`,
  `delete_device` and `select_device`, each in a return-indexed and a master
  form. Two departures from upstream's spelling are deliberate. The list getters
  **combine** what upstream splits — one `get/devices` reply carries
  `count, (name, type, class_name)×N` where upstream needs three round trips,
  and one `device/get/parameters` reply carries
  `device_name, count, (name, value, min, max)×N` where upstream needs five —
  because the caller wants all of them together and assembling parallel lists
  from separate replies risks describing two different devices. And
  `delete_device` **replies** (`[…, "ok", remaining]`) where upstream's is
  silent: it is a method with a real failure path, and the alternative is
  sandwiching it between two count reads.

  The master deliberately offers no `mute`, `solo` or `arm`: reading one raises
  `RuntimeError("Main track has no 'mute' property!")` rather than returning
  something falsy (measured 2026-07-31), so `hasattr` feature-detection is
  unsafe on a LOM object and the addresses simply do not exist. Returns have no
  `arm` either.

  The mixer listeners are keyed `(index, "volume")` / `(index, "panning")` /
  `("master", "cue_volume")` and so on, **not** by the bare index. The base
  class's `_stop_listen` derives `remove_value_listener` from the *prop* half of
  the key, which forces every DeviceParameter listener to register under
  `"value"` — so the discriminator has to live in the params half, or
  subscribing a return's pan would silently evict its volume listener.
- **`abletonosc/song_structure.py`** — `/live/song/{start,stop}_listen/tracks`
  and `.../return_tracks`. Upstream can only listen to *scalar* song properties,
  so nothing fires when tracks are added, deleted or reordered by hand.

`browser.py`'s `preview_item` / `stop_preview` use the Live API calls proven by
upstream PRs #204 and #192, with Seshat's own URI resolution and reply envelope.

## Merge hazards

Read this before merging anything from upstream.

Remotes are local config, so a fresh checkout of this repo (including the
submodule checkout `git submodule update --init` creates in Seshat) has only
`origin`. Merging or cherry-picking from upstream needs, once per clone:

    git remote add upstream https://github.com/ideoforms/AbletonOSC.git

- **PRs #182 / #185 rename `/live/clip_slot/duplicate_clip_to` to
  `duplicate_to`, with no alias.** Seshat's `duplicate_clip` tool depends on the
  old name. Merging either PR silently breaks it — silently, because OSC is
  fire-and-forget UDP and an unknown address just does nothing. If you take
  those PRs, either keep an alias registration or update Seshat in the same
  change. Seshat's `audit-osc` workflow is the verifier: it checks every
  `/live/` address in Seshat's `lib/` against the API docs.

- **Anything touching `OSCServer.__init__`'s defaults or `process()`.** The
  loopback bind and the removed reply retargeting are both one-liners against
  upstream, and reverting either is invisible from the machine Live runs on —
  loopback keeps working exactly as before. See the deliberate-changes section
  above.

- **`client/client.py`'s reply socket bind.** Also a one-liner against
  upstream (`127.0.0.1` in place of `0.0.0.0`), and also invisible on the
  machine Live runs on: loopback traffic to this fork's own server is
  unaffected either way. A merge that takes upstream's `client.py` unchanged
  silently re-exposes the reply port on every interface — the same regression
  as the `osc_server.py` bullet above, just on the client side.
  `tests_unit/test_live_suite_inert.py::test_client_reply_socket_binds_loopback_only`
  greps this file for `0.0.0.0` for exactly this reason — run
  `python3 -m pytest tests_unit/` on every merge. See the deliberate-changes
  section above.

- **Anything touching `process_message()`, `_dispatch`, or
  `LiveOSCErrorLogHandler.emit`.** The structured `/live/error` payload lives
  in `OSCServer._dispatch` and `manager.py`'s relay and nowhere else. A merge
  that takes upstream's `process_message` drops `_dispatch` wholesale — the
  `("request", …)` send, the escaped/anchored wildcard matching, the fan-out
  isolation, and the reply-type validation — including the multi-reply
  list-of-tuples contract that the track argument wildcard depends on, whose
  loss would turn every `/live/track/get/<prop> *` reply into a structured
  `TypeError` error — and it reintroduces the handler
  exceptions that `handler.py` no longer catches locally (turning every
  generic method/setter failure back into an aborted tick queue). One that
  takes upstream's `emit` drops the `("log", …)` tag and the
  `osc_request_error` skip, which leaves the structured send *and* a duplicate
  legacy line going out for the same failure. Neither is loud: errors still
  reach `Log.txt` and `/live/error`, and clients just go back to timing out.
  `tests_unit/` fails loudly on most of this — run it on every merge. See the
  additions section above.

- **`device.py`'s `create_device_callback` and its property registration
  loop.** Upstream registers the three `{start,stop}_listen/<prop>` pairs
  without `include_ids` and passes raw OSC arguments through the `include_ids`
  branch, with no `id_count` concept at all. A merge that takes upstream's
  `init_api` reverts every layer of the listener-identity fix **silently**:
  the `name` push goes back to carrying a bare value with no device to
  attribute it to, every device collapses onto one process-wide subscription
  per property, float-indexed parameter subscriptions start failing and
  leaking again, and — the layer `id_count` added — a trailing extra argument
  on the property pair once again keys a bogus subscription that a
  well-formed two-argument stop can never reach. Nothing errors, nothing
  logs, and a client only notices that its mirror is wrong.
  `tests_unit/test_device_listeners.py` is the tripwire — run
  `python3 -m pytest tests_unit/` on every merge. See the deliberate-changes
  section above.

- **`scene.py`'s `create_scene_callback`, `clip.py`'s `create_clip_callback`
  and `clip_slot.py`'s `create_clip_slot_callback`.** Upstream's versions of
  all three pass the *raw* OSC arguments into `_start_listen`/`_stop_listen`
  (`params[0:]` / `tuple(params[0:])`) rather than the normalised, truncated
  identity this fork builds. A merge that takes upstream's file reverts the
  identity fix **silently**: pushes go back to echoing float ids where the
  query reply echoes ints, a non-integral index subscribes one object while
  keying and pushing another, and a stray trailing argument keys a
  subscription no well-formed stop can end. Nothing errors and nothing logs —
  a client only notices that its mirror drifts. The three edits are one line
  each and easy to lose in a conflict resolution.
  `tests_unit/test_listener_identity.py` is the tripwire.

- **Anything touching `track.py`'s `create_track_callback`, or
  `manager.py`'s `reload_imports` list.** In this fork `create_track_callback`
  is a small local helper delegating to `abletonosc/track_callback.py`; a
  merge that takes upstream's nested closure restores the early `return` and
  every `/live/track/get/<prop> *` silently goes back to answering for track 0
  only — one plausible-looking reply, no error, nothing in a log to notice.
  Losing `track_callback.py` itself fails loudly (the import breaks), but
  losing the *delegation* does not. `tests_unit/test_track_callback.py` fails
  on that hazard — run it on every merge.

  A merge that restores upstream's nested closure now reverts **two** fork
  behaviours, not one: the wildcard collection above, and the listener
  identity truncation. The truncation lives in `track_callback.py`'s
  `include_track_id` branch, which hands the callee `(track_index,)` where
  upstream's closure appends the raw params tail — so losing it silently
  reopens the key-poisoning leaks described under § Fixes, for the plain and
  mixer listen pairs alike, and for every track at once through `*`. It is a
  one-line difference inside a branch that otherwise reads identically, which
  is exactly the kind of thing a conflict resolution takes from upstream
  without noticing. `tests_unit/test_track_callback.py` and
  `tests_unit/test_track_listener_identity.py` are the tripwires.

  `reload_imports` is a separate hazard on the same list, and no Live-free
  test catches it: nothing outside Live calls `reload_imports`, so it is
  covered only by this file and the in-code comments. The list is one
  upstream also edits, and dropping its `abletonosc.track_callback` line is
  invisible until someone edits the wrapper and `/live/api/reload` appears
  not to take. The same list carries a second fork-owned line,
  `abletonosc.track_identity`, which must stay *before* `abletonosc.song`,
  `abletonosc.track` **and** `abletonosc.view` — all three `from`-import its
  resolvers (the selection resolvers in view.py, the object-valued read
  resolvers in song.py and track.py since A-4). A `from` import binds function
  objects at import time, so any of the three reloaded first keeps calling the
  *previous* edit's resolvers while `/live/api/reload` reports success — same
  silent failure mode, and the same missing test coverage.

- **Anything touching `song.py`'s generic methods list or `properties_rw`.**
  Three entries there are ours — `begin_undo_step`, `end_undo_step` and
  `swing_amount` — and each is a single quoted string inside a list upstream
  also edits, so a merge that takes upstream's version of the list drops them
  without a conflict. Losing the two undo entries doesn't break anything
  loudly: the sends still go out over UDP and nothing answers them either way,
  and undo quietly reverts whole conversations again. Seshat's
  `vendored_addresses_test` greps for all three names for exactly this reason.

- **Anything touching `AbletonOSCHandler.__init__`, a subclass's class-level
  `class_identifier`, or `init_state()`.** Upstream's constructor calls
  `init_api()` before the base invariants exist and assigns
  `class_identifier = None` after it; this fork inverts that (see the fixes
  section above). A merge that takes upstream's `__init__` back, or that
  restores a subclass `__init__` that assigns `self.class_identifier`, is
  **invisible**: nothing registered today reads those attributes at
  registration time, so every address still answers and every push still
  carries the right identifier. It stays invisible until the next handler
  that actually relies on the guarantee — which then fails as a bare
  `AttributeError`, or pushes to `/live/None/get/<prop>` and is never noticed
  at all. `tests_unit/test_handler_lifecycle.py` fails on the base-class half
  of this — `test_invariants_are_set_before_init_api` and
  `test_identifier_is_not_clobbered_after_construction` drive the real
  `AbletonOSCHandler.__init__` through a local `Probe` subclass, so a revert
  of the base constructor fails loudly. The subclass half is caught
  statically by `tests_unit/test_handler_subclass_contract.py`: the
  behavioural layer constructs seven of the twelve production handlers today
  (device, scene, clip_slot, track, clip, song, view) but not
  `application.py`, `browser.py`, `midimap.py`, `return_track.py` or
  `song_structure.py`, which have no conftest loader — so that file parses
  `abletonosc/*.py` with `ast` instead, covering all twelve declarations
  regardless, and fails on a restored subclass
  `__init__`, on a dropped or typo'd class attribute, and on any
  `self.class_identifier` assignment anywhere in a subclass — including one
  pasted into `init_state()`, which shadows identity just as silently.
  Between the two, `python3 -m pytest tests_unit/` on every merge covers both
  halves. The
  `reload_imports` ordering above (osc_server and handler first) is part of
  the same fix and is likewise silent when lost.

- **Anything touching `tests/__init__.py`, or adding module-scope code to
  anything in `tests/`.** Upstream's `tests/__init__.py` constructs an
  `AbletonOSCClient` and sends `/live/api/reload` at import time, so a merge
  that takes upstream's version turns `pytest --collect-only` back into a
  command that binds the reply port and reloads the bridge under a live
  session. This one is **not** silent, by construction:
  `tests_unit/test_live_suite_inert.py` parses every file in `tests/` with
  `ast` and fails if any of them constructs a client or calls
  `send_message` / `send_bundle` / `query` / `await_message` at module scope,
  and also fails if `tests/conftest.py` stops consulting
  `ABLETONOSC_LIVE_TESTS`. It is part of the Live-free gate, so it fires on
  the merge itself — run `python3 -m pytest tests_unit/` on every merge. The
  same merge would also revert the set-discovery and restore-in-`finally`
  rewrites of `tests/test_*.py`, which *are* silent: those tests would simply
  go back to assuming a blank default set and stranding state on failure. See
  the deliberate-changes section above.

- **Anything touching `_stop_listen`, `_start_listen`, `listener_objects` or
  `listener_lom_properties`.** Two fork changes live in these few lines. The
  wrong-object unbind fix above is small and easy to lose in a merge, and its
  symptom is invisible — every address still answers, and the mirror just
  quietly reports one track's name under another's index. The `lom_property`
  alias and its `listener_lom_properties` dict are equally small: a merge that
  takes upstream's `_start_listen` signature breaks
  `/live/view/start_listen/selected_track_identity` loudly (it goes looking for
  `add_selected_track_identity_listener`, which `Song.View` does not have), but
  a merge that keeps the parameter and drops only the *stored* mapping fails
  silently on the reload path instead, leaving identity listeners bound after
  `/live/api/reload`. `tests_unit/test_listener_alias.py` is the tripwire for
  both halves — run `python3 -m pytest tests_unit/` on every merge.

## Contributing back

The base-class listener fix and the mixer-listener bookkeeping are general bugs,
not Seshat-specific, and would be worth filing upstream if it revives. Doing so
is a courtesy, never a dependency.
