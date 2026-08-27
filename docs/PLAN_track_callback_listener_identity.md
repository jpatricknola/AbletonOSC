# Plan: Normalize listener argument identity in `track_callback.py`

Roadmap item: **Normalize listener argument identity in `track_callback.py`**
(source: `docs/archive/PLAN_listener_identity_normalization.md`, "Out of
scope", first bullet — the residual that item named as real and deliberately
excluded to keep its diff to the four files its title named). No dependencies.

## Context

Two shipped items established one rule for every index-keyed listener in this
fork: **a subscription's identity is a tuple of ints, normalised at the
callback boundary, truncated to exactly the arguments that are part of it,
and used identically for the LOM lookup, the bookkeeping key, and the echo in
every push.** `device.py` got the rule first ("Device listener identity"),
then `scene.py`, `clip.py`, `clip_slot.py` and the device property pair
("Normalize listener argument identity in scene.py, clip.py, clip_slot.py,
and the device.py property pair"). One generic wrapper still predates it:
`track_callback.py`'s `include_track_id` branch builds

```python
return func(track, *args, tuple([track_index] + params[1:]))
```

(`abletonosc/track_callback.py:89`). The index half is already correct —
`track_index` is `int(params[0])` on the concrete path
(`track_callback.py:111`) and a generated `range()` int on the wildcard path
— but nothing bounds `params[1:]`, so every argument past the index enters
the bookkeeping key and, because `handler.py`'s push sends
`(*params, *value)`, every subsequent push.

`include_track_id=True` has exactly four call sites, all in `track.py`, all
listener registrations: the plain property pair
(`/live/track/{start,stop}_listen/<prop>` for every property in
`properties_r + properties_rw`, `track.py:66-68`) and the mixer pair
(`volume`/`panning`, `_start_mixer_listen`/`_stop_mixer_listen`,
`track.py:84-86`). No getter, setter, or method registration uses the
branch, and no module other than `track.py` consumes the factory
(`track_identity.py` names it only in a comment), so truncating there cannot
change any non-listener reply.

### What research measured (2026-08-27, Live-free)

Measured by driving the **production** `TrackHandler` — constructed through
`tests_unit/conftest.py`'s synthetic-root loader against a real `OSCServer`,
with fake tracks/mixer parameters — on the current checkout
(`normalize-listner` @ `5d75fab`, whose only delta from master `ddd1feb` is
documentation):

1. **A trailing extra argument poisons the key and the push.**
   `start_listen/name 0 99` keyed `("name", (0, 99))` and immediately pushed
   `/live/track/get/name (0, 99, 'drums')` — a bogus third field a decoder
   reads as data. The well-formed `stop_listen/name 0` missed the key
   ("No listener function found" warning, nothing on the wire), **leaking
   the listener until reload**, with every subsequent change push still
   carrying the stray `99`.
2. **The mixer pair leaks the same way, silently.** `start_listen/volume 0 7`
   keyed `("value", (0, 7, 'volume'))` and pushed `(0, 7, 0.85)`;
   `stop_listen/volume 0` missed it with **no warning at all**, because
   `_stop_mixer_listen` is deliberately silent when nothing matches (that
   silence exists so re-listening is idempotent). The leak is otherwise
   identical.
3. **The wildcard amplifies the leak set-wide.** `start_listen/name * 42`
   fanned out and keyed `("name", (0, 42))`, `("name", (1, 42))` — the stray
   argument lands in *every* track's key — and the well-formed
   `stop_listen/name *` missed all of them, leaking one listener per track.
4. **A non-numeric extra is accepted and echoed.**
   `start_listen/volume 1 junk` subscribed without error and pushed the
   string `'junk'` as a field on `/live/track/get/volume`. The identity tail
   is never cast, so garbage keys and garbage pushes, no `/live/error`.

Recovery: `clear_api()` (script reload, `/live/startup`) still removes
poisoned keys and unbinds their objects — the leak lasts until reload, not
forever. And confirming the roadmap entry: there is **no float-index defect
here** — `start_listen/name 0.0` keyed `("name", (0,))` and pushed an int
`0`, because the concrete path already casts before `invoke` runs. The
whole defect is the untruncated tail. (This differs from the sibling item,
where the index itself also needed normalising.)

### What research confirmed

- **The fix belongs in `track_callback.py`, not `handler.py` or `track.py`.**
  `_start_listen`/`_stop_listen` key on `tuple(params)` exactly as handed to
  them (`handler.py:141`, `handler.py:171`), and
  `_start_mixer_listen`/`_stop_mixer_listen` build
  `("value", (*params, prop))` the same way (`track.py:258-301`) — all four
  callees treat `params` purely as identity plus push prefix, so handing
  them `(track_index,)` fixes plain and mixer pairs at once, in the one
  place the tuple is built. This is the same call-site placement the four
  sibling files used.
- **`track.py` needs no edit.** Its local `create_track_callback` is a
  binding shim; the registrations read identically before and after.
- **`manager.py` needs no edit.** `reload_imports` already reloads
  `abletonosc.track_callback` before `abletonosc.track`; no module is added.
- **`track.py` is importable outside Live.** It imports only `typing`,
  `.handler` and `.track_callback` — no module-scope `import Live` — so a
  `load_track_module()` loader in `tests_unit/conftest.py` needs nothing
  beyond the existing Component stub, and the end-to-end tests can drive the
  real `TrackHandler`, mixer pair included (the sibling item's
  `test_listener_identity.py` pattern).
- **Seshat** (read at `/Users/patrick/seshat`, 2026-08-27, `4a68267` —
  which already pins `ddd1feb`): `lib/seshat/session/state.ex:1091` sends
  `/live/track/start_listen/<prop> [index]` with exactly one Elixir integer,
  for `@listened_properties ~w(panning volume mute solo name)`; `lib/` sends
  no `/live/track/stop_listen/*` at all. Today's only known client is
  unaffected either way; the defect is reachable only by a malformed or
  hand-crafted request.

## Wire contract

No address is added, removed, or renamed. All changes are to subscription
identity, push payload, and malformed-request behaviour. Well-formed clients
— one int index, no extras — see **zero** difference.

**Changed (behavioural) — `/live/track/start_listen/<prop>` and
`/live/track/stop_listen/<prop>`** (request: `track_index`; no direct
reply), for every scalar property with a listen pair: the 21 in `track.py`'s
`properties_r + properties_rw` loops **and** the mixer pair `volume` /
`panning`:

- A subscription's identity is exactly `(track_index,)`, truncated at the
  callback boundary. **Arguments past the index are not part of the identity
  and are ignored** — they no longer enter the bookkeeping key
  (`(prop, (track_index,))`; `("value", (track_index, prop))` for the mixer
  pair) and no longer appear in any push.
- Pushes on `/live/track/get/<prop>` therefore always carry
  `track_index, value` — the query-reply shape — even when the subscription
  was made with stray extras (was: extras echoed as bogus fields for the
  life of the subscription, including non-numeric ones).
- A start sent with trailing extras is ended by a well-formed stop, and vice
  versa — closing the leaks measured above, plain, mixer, and wildcard
  (`start_listen/<prop> * <extra>` now keys `(i,)` per track, so
  `stop_listen/<prop> *` unsubscribes everything).
- Errors unchanged: **no** index is a malformed request (`params[0]` raises
  `IndexError`) and a non-numeric index raises in the `int()` cast — both
  already raised before listener code runs, both delivered as the structured
  `/live/error ("request", address, detail, argc, *raw_args)`.

**Unchanged but relied on:**

- Every `/live/track/get|set/<prop>` and method address — the
  non-`include_track_id` branch still passes `tuple(params[1:])` untouched
  (`get/send` reads a send index from that tail; truncation must not reach
  it).
- The wildcard fan-out contract (`API.md` § "The track-index argument
  wildcard"): reply grammar, ascending order, all-or-nothing on error,
  silent listener registrations.
- Subscribing pushes the current value immediately; a stop for a
  never-started plain listener logs a warning (silent on the wire); a
  missed mixer stop stays silent even in the log.

## Parts

All parts land in a single commit. `FORK_GAPS.md` is untouched: defect fix,
no LOM coverage change, no inventory regeneration.

### Part 1 — `abletonosc/track_callback.py` (+ its `API.md` rows)

1. In `invoke`, the `include_track_id` branch hands the callee the truncated
   identity:

   ```python
   if include_track_id:
       return func(track, *args, (track_index,))
   ```

   `track_index` is already the int the wrapper computed (cast on the
   concrete path, generated on the wildcard path). Add a short comment in
   the voice of the sibling wrappers: the tuple is the subscription's
   identity — bookkeeping key and push prefix — and arguments past the
   index are not part of it, so they are dropped here rather than poisoning
   a key no well-formed stop can reach.
2. Update the docstring's `include_track_id` line (currently "Prepend the
   track index to the params tail, as the listener registrations need"): it
   now hands the callee the one-int identity `(track_index,)`, the params
   tail deliberately excluded.
3. `API.md` § Track API, same commit: after the "Listen via …" intro
   paragraph, add an identity note in the style of the Scene/Clip sections'
   "**A subscription's identity is one int**" paragraphs, dated 2026-08-27:
   identity is `(track_index,)` for every listen pair including `volume` /
   `panning`; arguments past the index are ignored (key and push); pushes
   always carry `track_index, value` in the query-reply shape; the rule
   composes with `*` (extras after the wildcard are equally ignored, so a
   well-formed `stop_listen/<prop> *` ends whatever a malformed wildcard
   start began); sending no index remains a malformed request answered on
   `/live/error`.

### Part 2 — tests (`tests_unit/`)

1. **`tests_unit/conftest.py`**: add `load_track_module()` beside the other
   loaders — `load_handler_module()` then
   `load_module("abletonosc.track")`; no stub beyond Component (track.py
   imports no `Live`), and note that constructing `TrackHandler` registers
   its full address table on the passed server.
2. **Extend `tests_unit/test_track_callback.py`** (factory level, matching
   its existing style):
   - a concrete `start_listen`-shaped dispatch with a trailing extra: the
     worker receives `("name", (0,))` — tail truncated;
   - the wildcard form with a trailing extra: workers receive
     `[("name", (0,)), ("name", (1,)), ("name", (2,))]`;
   - the existing `test_wildcard_listener_registration_receives_track_id`
     must pass unmodified.
3. **New `tests_unit/test_track_listener_identity.py`** — the real
   `TrackHandler` end to end through the production `OSCServer`
   (`server`/`receiver` fixtures, `dispatch` helper, per
   `test_listener_identity.py`'s pattern), with local fakes: `FakeTrack`
   (settable `name`, `add_name_listener`/`remove_name_listener`, a
   `mixer_device` whose `volume`/`panning` are fake `DeviceParameter`s with
   `value` and `add_value_listener`/`remove_value_listener`, and whose
   `sends` is a list of the same fake `DeviceParameter`s — `track_get_send`
   reads `track.mixer_device.sends[send_id].value`, so the `get/send`
   regression case below needs it), `FakeSong` (`tracks`), `FakeManager`. Construct the handler, then assign
   `handler.song`. Cases — each the inverse of a measured defect:
   - **Plain-pair truncation.** `start_listen/name 0 99` → key
     `("name", (0,))`, immediate push `(0, "drums")` with no third field and
     `type(id) is int`; `stop_listen/name 0` removes it and unbinds the
     fake.
   - **Stop-side truncation (symmetry).** Well-formed start,
     `stop_listen/name 0 99` ends it.
   - **Mixer-pair truncation.** `start_listen/volume 0 7` → key
     `("value", (0, "volume"))`, push `(0, value)`; `stop_listen/volume 0`
     removes it and unbinds the fake `DeviceParameter`.
   - **Non-numeric extra.** `start_listen/volume 1 junk` subscribes
     `("value", (1, "volume"))` and pushes no `'junk'`; well-formed stop
     ends it.
   - **Wildcard truncation.** `start_listen/name * 42` → keys `(0,)`,
     `(1,)` per track, pushes `(i, name)`; `stop_listen/name *` unsubscribes
     every track, empty dicts, fakes unbound.
   - **Idempotent restart across spellings.** `start_listen/name 0` then
     `start_listen/name 0 99` → one key, one bound callback on the fake.
   - **Change push carries the clean identity.** Mutate the fake, fire its
     stored callback, assert `(0, new_value)` on `/live/track/get/name`.
   - **Too-few arguments.** `start_listen/name` with no args → structured
     `/live/error`, nothing registered.
   - **`clear_api()`** after a malformed start empties the dicts and
     unbinds the fakes.
   - **Query regression.** `get/name 0` and `get/volume 0` still reply
     `(0, value)`, and `get/send 0 0` still reads its send index from the
     tail — guarding the untouched non-id branch.

### Part 3 — `SESHAT.md`

1. § "Fixes to upstream's own code": extend the "`scene.py`, `clip.py`,
   `clip_slot.py` and the `device.py` property pair — the same identity
   rule" bullet (or add a sibling directly after it): the rule now also
   covers `track_callback.py`'s `include_track_id` branch — upstream's
   closure (and the fork's lifted factory until this change) appended the
   raw params tail after the cast index, producing the measured defects
   (extra-arg key poison and leak against a well-formed stop, silent for
   the mixer pair, per-track for a wildcard start, non-numeric extras echoed
   as push fields). Identity is now `(track_index,)`, truncated at the
   wrapper. Downstream verdict: pin bump only; Seshat sends one int index
   and nothing else.
2. § Merge hazards: extend the existing "Anything touching `track.py`'s
   `create_track_callback`, or `manager.py`'s `reload_imports` list" bullet:
   the truncation lives in `track_callback.py`'s `include_track_id` branch,
   upstream's closure passes the raw tail, and a merge restoring upstream's
   nested closure now reverts *two* fork behaviours (the wildcard collection
   and the identity truncation). `tests_unit/test_track_callback.py` and
   `tests_unit/test_track_listener_identity.py` are the tripwires.

## Testing

`python3 -m pytest tests_unit/` is the gate and covers everything above:
dispatch through the production server, the production factory, and the
production `TrackHandler`, key truncation, push payloads, leak regressions,
wildcard composition, error envelopes — all Live-free. Not covered there:
whether real `Track` / `MixerDevice` / `DeviceParameter` LOM objects behave
as the fakes do — but this change does not alter which properties are
subscribed or which LOM calls are made, only the tuple handed to bookkeeping
code that already runs against them, so the residual Live risk is the code
path the current release already exercises. `tests/` mutates a running Live
on import and stays out of the gate.

## Live verification

Precondition for every check: the Remote Scripts copy equals this checkout
byte for byte (`diff -rq --exclude=__pycache__ abletonosc "$HOME/Music/…/
Remote Scripts/AbletonOSC/abletonosc"`) **and** Live has been restarted since
it was copied — files on disk are not code in memory. Method: `API.md` § "The
no-probe variant" — fire-and-forget UDP to 127.0.0.1:11000, evidence read
from the installed `logs/abletonosc.log` (Seshat holds reply port 11001).

These checks start and stop listeners but mutate no document state, so no
undo step is needed. **One Seshat-specific caution:** Seshat subscribes
`name`, `volume`, `panning`, `mute`, `solo` on every track, and a
`stop_listen` on one of those keys ends *Seshat's* subscription too (same
key). Use `color` for the plain-pair checks; for the mixer check either run
with no Seshat session attached or finish with a bare
`start_listen/volume 0` so the subscription (and its immediate push) is
restored. "Restored" means: every listener this run started is stopped, and
any Seshat subscription it stopped is re-started, verified in the log.

1. **Plain-pair truncation.** `start_listen/color 0 99` → log
   `Adding listener for track (0,), property: color` — the tuple **without**
   `99` — and the immediate push logged. Then `stop_listen/color 0`:
   `Removing listener for track (0,)`, and **no** "No listener function
   found" warning.
2. **Mixer-pair truncation.** `start_listen/volume 0 99` → `Adding listener
   for track (0,), property: volume`; `stop_listen/volume 0` → the base
   class's `Removing listener for track (0, 'volume'), property value`
   line. (Re-subscribe for Seshat if attached, per above.)
3. **Wildcard truncation.** `start_listen/color * 99` → one
   `Adding listener for track (i,), property: color` line per track, no
   `99` in any tuple; `stop_listen/color *` → one Removing line per track,
   no warnings.
4. **Well-formed regression.** `start_listen/color 1` then
   `stop_listen/color 1` behaves exactly as before — add, immediate push,
   remove, no warning.

Remains uncovered even then: a change-triggered push (needs a UI edit; the
immediate-push echo exercises the same code path, as it did for the two
sibling items), and the non-numeric-extra case against a real Live (nothing
new reaches the LOM — the extra is dropped before any Live call).

## Downstream

**Pin bump only.** Verified 2026-08-27 against `/Users/patrick/seshat`
(`4a68267`, which already pins this repo's `ddd1feb`):
`lib/seshat/session/state.ex` sends `/live/track/start_listen/<prop>
[index]` with exactly one integer argument and never sends
`/live/track/stop_listen/*`; no address is added, renamed, or removed, so
`vendored_addresses_test.exs` patterns stay valid. The vendored
`priv/AbletonOSC/API.md` picks up the new identity paragraph with the pin.

## Out of scope

- **`return_track.py` / master listeners.** Audited clean 2026-08-27 (the
  roadmap entry records the audit): every per-property pair there keys on
  the *parsed* index, never the params tail, and the master triple keys on
  a `"master"` sentinel — extra arguments are never read, nothing can leak.
  No code change, no roadmap follow-up.
- **`song.py`, `view.py`, `song_structure.py` listeners** — identity is the
  empty tuple (no index arguments); the rule is vacuous there.
- **Which track properties are observable.** Subscribing a property whose
  LOM object lacks `add_<prop>_listener` errors structurally today and
  after this change; auditing the lists is gap-bucket work.
- **The plain-pair "No listener function found" warning being log-only.**
  A missed stop still tells the client nothing; that is upstream behaviour
  across every handler and a protocol question, not an identity one.
- **Ship-time housekeeping notes for `/ship`:** two archived banners point
  at this item by its superseded name "Normalize listener argument identity
  in track.py and return_track.py" — the banner of
  `docs/archive/PLAN_device_listener_identity.md` (its "further follow-up
  … on ROADMAP.md as …" clause) and the banner of
  `docs/archive/PLAN_listener_identity_normalization.md` (plus that plan's
  "Out of scope" first two bullets, which this item resolves). When this
  ships and the roadmap entry is deleted, amend both banners to point at
  this plan's archive, noting that `return_track.py` was audited clean
  rather than fixed.

## Open questions

None. The obvious ones were closed at planning time by measurement or
reading:

- *Is the index half already sound?* Yes — measured: a float or concrete
  int index normalises before `invoke`, and the wildcard generates ints;
  the defect is entirely the untruncated tail.
- *Do both `include_track_id` pairs need the fix, and is the wrapper the
  right place?* Yes — all four call sites are listener registrations whose
  callees treat `params` purely as identity + push prefix, so one wrapper
  edit fixes plain and mixer pairs; no other module consumes the factory.
- *Can the real `TrackHandler` be tested Live-free?* Yes — `track.py` has
  no module-scope Live import; a `load_track_module()` loader needs only
  the existing Component stub.
- *Does Seshat send extras or floats here?* No — one integer index, and no
  track `stop_listen` at all (Downstream).
