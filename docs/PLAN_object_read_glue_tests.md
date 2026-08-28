# Plan: Test coverage for the object-read `song.py` / `view.py` glue

Roadmap item: **Test coverage for the object-read `song.py` / `view.py`
glue** (source: the pr-review finding on `object-valued-read-helpers`,
2026-08-27, recorded in the roadmap entry itself — there is no separate
write-up file). No dependencies. Planned 2026-08-28.

## Context

A-4 shipped nine object-valued read addresses. Two of them —
`/live/track/get/group_track` and `/live/clip_slot/get/clip` — are driven end
to end by `tests_unit/test_object_reads.py` through the real `TrackHandler`
and `ClipSlotHandler`. The other seven live in `song.py` (the
`appointed_device` get / set / listen trio) and `view.py` (`selected_chain`,
`selected_parameter`, `mod_mapping_device`, `mod_mapping_parameter`) and are
pinned by nothing: the resolvers underneath them are covered by
`test_track_identity.py`, but the dispatch glue — the address as registered,
the `partial(...)` wiring, the `getter=` listener push, the setter's argument
coercion, what `_dispatch` turns a resolver `ValueError` into — is not.
Every archived plan and doc comment says the same thing about why:
"`song.py` and `view.py` import `Live` at module scope and are unreachable
from `tests_unit/`".

Research shows that reason is stale. What the pr-review finding established,
and this plan confirmed by reading the code:

- **`import Live` is not the blocker.** Both modules dereference `Live.`
  only inside callbacks at call time — `song.py` in `song_get_track_data`
  (`isinstance(value, Live.Track.Track)`), `view.py` in `show_view`,
  `get_is_view_visible` and `hide_view` (`Live.Application.get_application()`).
  That is exactly the shape `conftest.load_clip_module()` already handles for
  `clip.py` with an *empty* `Live` stub: the import resolves, and any test that
  dispatched one of those addresses would fail loudly on the missing
  attribute rather than quietly exercising a fake Live. `song.py`'s other
  module-scope imports (`os`, `sys`, `tempfile`, `json`) are stdlib.
- **The real blocker is `self.song` at registration time.** Every handler
  the suite drives today (`device`, `scene`, `clip_slot`, `clip`, `track`)
  reads `self.song` only inside callbacks, so the fixtures assign
  `handler.song = FakeSong(...)` *after* construction. `SongHandler.init_api`
  instead binds `self.song` into some sixty `partial(...)`s while the
  constructor is still running (`partial(self._get_property, self.song, prop)`
  for every property, `partial(self._call_method, self.song, method)`, and the
  `appointed_device` listen pair), and `ViewHandler.init_api` binds
  `self.song.view` into its four listen registrations the same way. With the
  current `Component` stub the attribute does not exist, so construction
  raises `AttributeError` before a single address is registered.
- **What `song` is in Live.** Decompiling the constant table of Live 12.4.3's
  shipped `ableton/v2/control_surface/component.pyc`: `Component.__init__`
  takes `(name, parent, register_component, song, layer, is_enabled, ...)`
  and stores `song` as `self._song`; `Component.song` is a property
  returning `self._song`. `AbletonOSCHandler.__init__` calls
  `super().__init__()` with no arguments, so in Live the value is supplied by
  the `ControlSurface.component_guard()` block that `manager.py:113-131`
  constructs every handler inside — the song is available from the first
  line of `init_api()`. The stub therefore needs the same guarantee: a `song`
  that is *already set when `init_api` runs*, not one assigned afterwards.
- **`_callbacks` is a plain dict** (`osc_server.py:62`, `add_handler` assigns
  by address), so "address X is registered" and "address X is not
  registered" are both directly assertable, the way
  `test_object_reads.py::test_group_track_has_no_listen_pair` already does.

Proven at planning time, not assumed: a throwaway script in the session
scratchpad (nothing added to the repo) put `song = None` on the existing
`Component` stub, installed the empty `Live` stub, imported the real
`abletonosc.song` and `abletonosc.view` through `conftest.load_module`,
constructed both handlers through a `type(name, (cls,), {"song": fake})`
subclass and dispatched: `get/appointed_device` answered `("none", -1, -1)`
then `("track", 1, 0)` after a float-argument `set`, `set ... "track" -1 0`
produced `/live/error ("request", "/live/song/set/appointed_device", "Track
index out of range for category 'track': -1 (this song has 2)", 3, "track",
-1, 0)`, the listen pair bound and unbound one callback on the fake, and the
two `view` getters answered their none-quads. The implementer starts from a
design that already runs.

So the item is what the roadmap says it is: a stub extension, two loaders,
two test modules, and the stale "unreachable" claims corrected wherever they
are written down. **No production code changes**; no address, request shape,
reply shape or push changes.

Live 12.4.3 is running at planning time, but there is nothing in this item
for it to answer: the reply shapes under test are defined by the shipped
Python, which the fakes exercise, and the ⚠️ measurements A-4 left open
(the `canonical_parent` ascent, cross-class `==`, drum-rack chains,
`mod_mapping_*` mid-gesture) are LOM facts that fakes cannot settle and that
this item does not claim to. They stay where A-4's archived plan and
`API.md` § "Object-valued reads" record them.

## Wire contract

**No address is added, changed or removed. No `API.md` rows.** The seven
addresses below are *unchanged-but-relied-on*: each is transcribed here from
`API.md` and the handler source so the tests can be checked against it, and
any test that disagrees with a row here is wrong, not the code.

| Address | Request | Reply / effect | Status |
|---|---|---|---|
| `/live/song/get/appointed_device` | — | `category, track_index, device_index`; `"none", -1, -1` when nothing is appointed; a device nested in a rack chain → `category, track_index, -1` | unchanged, relied on |
| `/live/song/set/appointed_device` | `category, track_index, device_index` | silent. `str()`/`int()`-coerced, then *validated* by `resolve_device`: `"none"`, an unknown category, a negative or out-of-range index, or a master index other than `0` → `ValueError` → `/live/error ["request", address, message, argc, *args]`, and `appointed_device` is left unchanged. Fewer than three arguments → `IndexError` on the same envelope | unchanged, relied on |
| `/live/song/start_listen/appointed_device` | — | subscribes `Song.add_appointed_device_listener`, keyed `("appointed_device", ())`, and pushes the getter's triple on `/live/song/get/appointed_device` immediately and on every change; a repeat start replaces rather than stacks | unchanged, relied on |
| `/live/song/stop_listen/appointed_device` | — | unbinds via `remove_appointed_device_listener` on the recorded object and clears all three bookkeeping dicts; with no listener registered logs a warning and sends nothing | unchanged, relied on |
| `/live/view/get/selected_chain` | — | `category, track_index, device_index, chain_index`; `"none", -1, -1, -1` when nothing is selected; nested rack → `device_index` `-1` | unchanged, relied on |
| `/live/view/get/selected_parameter` | — | `category, track_index, device_index, parameter_index`; none-quad; mixer/send parameter or nested-device parameter → `category, track_index, -1, -1` | unchanged, relied on |
| `/live/view/get/mod_mapping_device` | — | `category, track_index, device_index`; idle → `"none", -1, -1` | unchanged, relied on |
| `/live/view/get/mod_mapping_parameter` | — | `category, track_index, device_index, parameter_index`; idle → `"none", -1, -1, -1` | unchanged, relied on |

Shared, and relied on: every getter reply is fixed-arity with `int` indices;
a genuine resolution failure (an object whose `canonical_parent` ascent
finds no track) raises inside the callback and arrives as a structured
`/live/error` on the **request** path with nothing on the getter's address;
the four `view` getters have **no** `start_listen` / `stop_listen`
registrations (get-only in this fork, per `API.md`); `clear_api()` (what
`/live/api/reload` runs through `Manager.clear_api`) unbinds the
`appointed_device` listener. Listener pushes have no error envelope — a
resolver failure inside the push callback propagates out of the fake's
notifier, which is the Live-free image of "dies inside Live's listener
callback with nothing on the wire" and is asserted as such.

## Numbered parts

### Part 1 — `tests_unit/conftest.py`: the `song`-bearing `Component` stub and two loaders

Files: `tests_unit/conftest.py`.

1. Extend the `Component` stub in `load_handler_module()` to model the one
   further thing Live's `Component` provides that a handler relies on:
   `__init__(self, *args, song=None, **kwargs)` stores `song` when given,
   and the class carries `song = None` as the default. Keep it a plain
   attribute rather than a property so the existing fixtures'
   post-construction `handler.song = FakeSong(...)` keep working unchanged
   (the real `song` is a read-only property; the stub deliberately stays
   more permissive, and the docstring says so). Update the stub's docstring
   and the module docstring, which currently says `song.py` and friends
   "stay out of reach until that is addressed separately".
2. Add `bind_song(handler_class, song)` — a helper returning a subclass of
   `handler_class` whose class body sets `song = song`. This is the Live-free
   image of `component_guard()`: `self.song` resolves through the class
   attribute from the first line of `init_state()`/`init_api()`, before any
   instance assignment could happen, and nothing is process-global (each
   test's subclass is its own). `class_identifier` is inherited so pushes
   still go out under `song` / `view`. `test_handler_subclass_contract.py`
   parses only `abletonosc/*.py`, so a test-side subclass does not trip it.
3. Add `load_song_module()` and `load_view_module()`, modelled on
   `load_clip_module()`: `load_handler_module()`, install the empty `Live`
   stub if absent (the same guarded `sys.modules["Live"] = ModuleType("Live")`
   — factor the three loaders' stub install into one small
   `_install_empty_live_stub()` rather than pasting it a third time), then
   `load_module("abletonosc.song")` / `("abletonosc.view")`. Each docstring
   names the call-time-only `Live.` dereferences that make the empty stub
   safe (`song.py:196` `Live.Track.Track` in `get/track_data`; `view.py`'s
   `Live.Application.get_application()` in `show_view`, `get/is_view_visible`,
   `hide_view`) and states that no test in the suite dispatches those
   addresses.
4. `test_import.py`'s `test_abletonosc_package_init_never_executed` already
   tolerates a file-less `Live` stub; no change needed there. Add one smoke
   test each to `test_import.py` that the two new loaders import the real
   module (`module.__name__ == ROOT_PACKAGE + ".abletonosc.song"` /
   `.view`) and expose `SongHandler` / `ViewHandler`, matching
   `test_handler_module_imports_over_the_component_stub`.

### Part 2 — `tests_unit/test_song_object_reads.py`: the `appointed_device` trio

Files: new `tests_unit/test_song_object_reads.py`.

Fakes, local to the module in the style of `test_object_reads.py` and
`test_track_identity.py`: `FakeDevice(name, canonical_parent)`,
`FakeChain(rack)` with `canonical_parent`, `FakeTrack(name, devices)` whose
devices carry `canonical_parent = track`, `FakeSongView` (only what
`SongHandler` touches: nothing at registration), and `FakeSong(tracks,
return_tracks, master_track)` with an `appointed_device` attribute and a
real `add_/remove_appointed_device_listener` pair recording into
`listeners` (the `FakeTarget` idiom from `test_handler_lifecycle.py`).
`FakeSong` must also carry every attribute `SongHandler.init_api` *reads at
registration*: none beyond `self.song` itself — every other access is inside
a partial or closure — but the fixture docstring says why the fake can be
this thin.

Fixture `song_handler(server)`: `bind_song(load_song_module().SongHandler,
song)(FakeManager(server))`, over a set with two regular tracks (track 1
holding a top-level `FakeDevice` and a rack whose chain holds a nested
`FakeDevice`), one return track with a device, and a master with a device.

Tests — each one line of the wire contract above:

- **Registration**: all four `appointed_device` addresses are in
  `server._callbacks`; the constructor succeeded at all (this is the test
  that fails on a `Component` stub without `song`).
- **get**: nothing appointed → `("none", -1, -1)`; top-level device on a
  regular track → `("track", 1, 0)`; on the return → `("return_track", 0,
  0)`; on the master → `("master", 0, 0)`; nested device → `("track", 1,
  -1)`. Each reply is exactly three fields and both indices are `int`.
- **get failure**: an appointed device whose `canonical_parent` is `None`
  (no track reachable) → no reply on the getter address, exactly one
  `/live/error` whose first two fields are `"request"` and
  `/live/song/get/appointed_device`.
- **set happy path**: `("track", 1, 0)` → `song.appointed_device is` that
  device and nothing on the wire; `("return_track", 0, 0)` and
  `("master", 0, 0)` likewise; float indices `("track", 1.0, 0.0)` land the
  same device (the `int()` coercion).
- **set rejections**, each: one `/live/error` on the request path echoing
  the address, the arg count and the arguments, and `appointed_device`
  unchanged — category `"none"`; unknown category; negative track index;
  negative device index; track index past the end; device index past the
  end; `("master", 1, 0)`; and a two-argument request (`IndexError`, same
  envelope). `-1` in particular must be an error, never "the last device".
- **listen**: `start_listen` binds exactly one callback on the fake, records
  the `("appointed_device", ())` key in all three dicts with
  `listener_lom_properties` equal to `"appointed_device"` (no alias), and
  pushes the current triple immediately on `/live/song/get/appointed_device`;
  changing `song.appointed_device` and firing the recorded callback pushes
  the new triple; a second `start_listen` leaves one callback bound, not
  two; `stop_listen` unbinds it and empties the dicts; `stop_listen` with
  no listener sends nothing (warning only); `clear_api()` unbinds it (the
  `/live/api/reload` path — `Manager.clear_api` calls each handler's
  `clear_api`, which for `SongHandler` also swallows the beat-listener
  removal in a bare `try`, so the fake may omit
  `remove_current_song_time_listener` entirely, or carry one that raises or
  no-ops; assert the appointed-device listener is gone either way).
- **listen push failure**: with a listener bound and `appointed_device`
  then set to an unparented device, firing the callback raises out of the
  fake's notifier and nothing reaches the receiver — pinning `API.md` rule 6
  ("a listener push has no such envelope") rather than leaving it prose.

### Part 3 — `tests_unit/test_view_object_reads.py`: the four `Song.View` getters

Files: new `tests_unit/test_view_object_reads.py`.

Fakes extend the Part 2 set with parameters: `FakeParameter(name,
canonical_parent)`, devices carrying `parameters`, a rack `FakeDevice`
carrying `chains`, a `FakeMixerDevice(track)` whose `volume` parameter's
parent is the mixer (not in `track.devices`) and whose own `canonical_parent`
is the track — `owning_track_identity` must be able to climb parameter →
mixer → track, or the mixer case raises instead of answering
`(cat, ti, -1, -1)` — and a `FakeSongView` with
`selected_track`, `selected_scene`, `selected_chain`, `selected_parameter`,
`mod_mapping_device`, `mod_mapping_parameter` plus `add_/remove_` pairs for
`selected_track` and `selected_scene` (so the four upstream listen
registrations bind against something real should a later test need them —
none here does). `FakeSong` gains `scenes` and `view`.

Fixture `view_handler(server)` via `bind_song(load_view_module().ViewHandler,
song)`.

Tests:

- **Registration**: the four `get` addresses are in `server._callbacks`;
  none of `/live/view/{start,stop}_listen/{selected_chain,
  selected_parameter, mod_mapping_device, mod_mapping_parameter}` is — the
  get-only claim in `API.md`, pinned the way `test_group_track_has_no_listen_pair`
  pins its absence.
- **`selected_chain`**: `None` → `("none", -1, -1, -1)`; chain of a
  top-level rack on track 1 → `("track", 1, rack_index, chain_index)`; chain
  of a nested rack → `device_index` `-1`, `chain_index` still resolved; four
  fields, ints.
- **`selected_parameter`**: `None` → none-quad; parameter of a top-level
  device → full quad; mixer volume → `(cat, ti, -1, -1)`; parameter of a
  nested device → `(cat, ti, -1, -1)`; on a return-track device →
  `("return_track", 0, d, p)`; on the master → `("master", 0, d, p)`.
- **`mod_mapping_device`** / **`mod_mapping_parameter`**: idle → the
  documented none shapes; a top-level device / its parameter → triple /
  quad. (These share resolvers with the two above; one positive and one
  none case each is the glue-level pin — the resolver matrix is
  `test_track_identity.py`'s.)
- **Failure**: an object whose ascent finds no track → `/live/error`
  `("request", address, ...)` and no reply, for one of the four addresses
  (the other three route through the same `_dispatch` catch; one is
  enough, named as such).
- **Parameterised over the four addresses**: arity and `int`-ness of every
  reply field.

### Part 4 — Correct the stale "unreachable" claims

Files: `tests_unit/test_object_reads.py`, `tests_unit/test_track_identity.py`,
`tests_unit/test_handler_subclass_contract.py`, `tests_unit/test_handler_lifecycle.py`,
`tests_unit/test_listener_alias.py`, `abletonosc/track_identity.py` (comment only),
`SESHAT.md`.

Each of these states that `song.py` / `view.py` cannot be imported by
`tests_unit/`; after Parts 1–3 that is false and a reader will act on it.
Reword each to the truth — the modules load over the empty `Live` stub and
the `song`-bearing `Component` stub, and the glue is covered by the two new
modules — without deleting the *reason the resolvers live in
`track_identity.py`* (they were extracted before the loaders existed; the
separation is still what keeps the logic parameterised on `song` and is not
being undone):

- `test_object_reads.py` module docstring: replace the second paragraph
  ("The other seven addresses … cannot be reached from here … Live
  verification checks") with a pointer to the two new modules.
- `test_track_identity.py` module docstring: "view.py itself imports `Live`
  at module scope and stays out of reach" → covered by
  `test_view_object_reads.py`.
- `test_handler_subclass_contract.py` docstring: "five of the twelve …
  `import Live` at module scope, and only device.py is loaded and driven end
  to end today" — restate which handlers the behavioural layer now drives
  (device, scene, clip, clip_slot, track, song, view) and which still are
  not (application, browser, midimap, return_track, song_structure). The
  file's checks are unchanged.
- `test_handler_lifecycle.py` module docstring (lines 17–19: "Five
  production subclasses (application.py, browser.py, clip.py, song.py,
  view.py) import Live at module scope and are out of reach entirely; the
  rest are simply not loaded here … device.py is the exception"): the same
  stale claim in a fourth test file — restate as in the
  `test_handler_subclass_contract.py` bullet (driven: device, scene, clip,
  clip_slot, track, song, view; not loaded: application, browser, midimap,
  return_track, song_structure). Probes and checks unchanged.
- `test_listener_alias.py` docstring: "(which imports Live and stays out of
  reach)" → no longer the reason; the alias test remains the base-class
  pin.
- `abletonosc/track_identity.py` header comment (`"view.py imports Live at
  module scope and therefore cannot be imported outside Live, so any
  resolution logic written as a closure … could never be reached"`) and the
  A-4 block comment (`"both of those import Live at module scope and are
  unreachable from tests_unit/"`): comment-only edits, no code — reword to
  "kept out of the handler closures so it is testable as plain functions;
  the handler glue is driven separately by `tests_unit/test_song_object_reads.py`
  / `test_view_object_reads.py`". This is the one production file touched
  and the diff must be comments only; `python3 -m pytest tests_unit/` and a
  `git diff --stat` showing no non-comment line are the check.
- `SESHAT.md` A-4 entry (the paragraph beginning "All the resolution lives
  in **`track_identity.py`**" and the closing paragraph "`tests_unit/
  test_track_identity.py` (resolvers) and `tests_unit/test_object_reads.py`
  … the `song.py` / `view.py` registrations can only be checked against a
  running Live"): update the last paragraph to name the two new modules as
  the Live-free tripwires for the seven addresses, and add a bullet to the
  **test harness** entry ("The test harness — `tests/` is opt-in and inert,
  `tests_unit/` is the gate") recording the stub's `song` attribute and
  `bind_song` as the fork's mechanism for handlers that read `self.song` at
  registration, mirroring `component_guard()`. Also the § Merge hazards
  paragraph on the base-constructor order (the sentence "the suite still
  never constructs a production handler (`TrackHandler` and the rest import
  `Live` at module scope, out of reach here)"), which was already false for
  `TrackHandler` and is false for `SongHandler` / `ViewHandler` after this
  item: reword to say the static `ast` check exists because the behavioural
  layer does not construct *every* subclass, and name the five it still does
  not. The selected-track-identity entry's "`view.py` imports `Live` at
  module scope, so logic left as a closure … could never be reached" is
  history explaining why `track_identity.py` was extracted and may stand as
  past tense. This *is* the SESHAT.md
  divergence entry for the item: `tests_unit/` is fork-owned, but the
  paragraph a merger reads about what the suite catches must not undersell
  it.
- `docs/archive/PLAN_object_valued_read_helpers.md` banner cites the
  follow-up by rank ("#2 · Test coverage …"), which is already stale (it is
  #1 now) and ROADMAP.md's own rule says ranks are never cited outside that
  file. Fix it to cite by title, with no rank, in the same commit — `/ship`
  would otherwise leave a dangling pointer to a deleted entry.

No `API.md` rows (no address changes), no `FORK_GAPS.md` deletion or
inventory regeneration (no gap closes), no source write-up to remove (the
roadmap entry cites a pr-review finding, not a file) — `/ship` deletes the
roadmap entry only.

## Testing (`tests_unit/`, the only gate)

`python3 -m pytest tests_unit/` — 269 passing at planning time on CPython
3.12.7 / pytest 7.4.4; this item adds roughly forty. All Live-free, all
driven through `conftest.py`'s `dispatch` / `server` / `receiver` fixtures
against the real `OSCServer`, the real `AbletonOSCHandler`, and the real
`SongHandler` / `ViewHandler`. Only the LOM objects are fakes, and a handler
against *real* LOM objects is **not** covered here — in particular the
fakes' `canonical_parent` shapes and identity-based `==` are the assumptions
`API.md` § "Object-valued reads" already flags ⚠️, and a green run proves
the glue, not the LOM. `tests/` mutates a running Live on import and is not
part of the gate.

What the two new modules pin, by clause of the roadmap Goal:

- **reply shapes** — Parts 2 and 3 getter tests (category, arity, `int`
  indices, the `"none"` and `-1` sentinels, all three track categories);
- **the listener push address** — Part 2: pushes on
  `/live/song/get/appointed_device`, immediate and on change, carrying the
  resolved triple rather than a raw object;
- **`stop_listen` bookkeeping** — Part 2: the three dicts after start /
  restart / stop / `clear_api()`, and the unbind hitting the recorded
  object;
- **setter validation** — Part 2: every `resolve_device` rejection arrives
  as a structured `/live/error` and leaves the member alone;
- **get-only** — Part 3: the four `view` listen pairs are not registered;
- **loader** — Part 1's `test_import.py` smoke tests, so a loader regression
  fails by name.

What is deliberately not asserted: the exact `ValueError` message text
(owned by `track_identity.py` and its tests), the log lines (no test in the
suite asserts logging), and `/live/view/get/selected_track` and friends
(pre-existing view addresses that the loader now makes reachable but which
are outside this item — see Out of scope).

## Live verification

Precondition for every check: the installed Remote Scripts copy equals this
checkout byte for byte **and** Live has been restarted since it was copied.
Method: `API.md` § "The no-probe variant".

**There is nothing for Live to verify in this item.** No production
behaviour changes — the only production-file edit is comment text in
`track_identity.py`, and the `git diff` is the proof of that. The seven addresses' behaviour against real LOM objects
was, and remains, A-4's Live verification list (checks 3–8 in
`docs/archive/PLAN_object_valued_read_helpers.md`, recorded there as skipped
by environment on 2026-08-27, with open questions 1, 2, 4, 5 and 7 still
open). This item does not close them and does not pretend to: a Live-free
test of the glue is precisely the layer that cannot. If a Live run of those
checks ever happens, its findings go into `API.md` beside the existing
measurements, dated and version-stamped, exactly as that plan says.

Uncovered, and why: whether Live's real `Component.song` is populated at the
moment `init_api()` runs is the assumption the `bind_song` helper models.
It is confirmed today by the fact that the installed `song.py` registers at
all — a `SongHandler` whose `self.song` were unset at `init_api` time would
fail at startup and be visible in `Log.txt` — so it needs no new check.

## Downstream

**Pin bump only — and not even needed for behaviour.** No address, request
shape, reply shape, push or error envelope changes; the diff outside
`tests_unit/` is comments and prose. Seshat's `vendored_addresses_test`
gains no tripwire. The bump is worth taking so the submodule's gate matches
the pinned commit, nothing more.

## Out of scope

- **Coverage of the rest of `song.py` and `view.py`** now that they load:
  the generic `properties_r` / `properties_rw` loop, `get/track_data`,
  `get/cue_points`, `cue_point/*`, the beat listener, `export/structure`;
  `view.py`'s `selected_scene` / `selected_track` / `selected_clip` /
  `selected_device` getters and setters, `selected_track_identity` (whose
  resolver and alias are already pinned), `show_view` / `hide_view` /
  `is_view_visible` / `detail_clip`. The Goal names the seven object-read
  addresses; each of those other families belongs to the roadmap item that
  next touches it (the `Song` remainder, song structure export, the C-3
  application work), which now has a loader to build on. Anything shaped
  like "while we are here" grows this PR past its review subject.
- **Any change to `song.py` or `view.py` code.** If a test in Parts 2–3
  fails against the shipped glue, that is a finding to report, not fix here
  — the roadmap entry says "no production code changes expected", and a
  behaviour change would be a wire-contract change needing its own API.md
  row and SESHAT.md entry.
- **Making the stub's `song` a read-only property** to match Live exactly.
  It would break every existing post-construction `handler.song = ...`
  fixture for no coverage gain; recorded in the stub docstring instead.
- **A-4's open ⚠️ measurements** (ascent, cross-class `==`, drum-rack
  chains, `mod_mapping_*` mid-gesture, `ClipSlot` `clip` observability,
  the FORK_GAPS dump). LOM facts; unreachable from a fake; they stay with
  A-4's archived plan and the `API.md` markers.
- **`application.py`, `browser.py`, `midimap.py`, `return_track.py`,
  `song_structure.py` loaders.** Not needed here; whichever item first
  needs one adds it (`return_track.py` for A-3 is the likely first).

## Open questions

None. The one thing that looked open — whether `self.song` can be present
before `init_api()` without Live — was closed by reading Live 12.4.3's
`component.pyc` constant table (`song` is `_song` from the constructor's
`song=` argument, resolved through `component_guard()` in `manager.py`), and
`bind_song` is the Live-free model of that. Everything else in this plan is
a design choice with its reasoning recorded inline. The ⚠️ markers that
remain in `API.md` § "Object-valued reads" belong to A-4 and are unchanged
by this item.
