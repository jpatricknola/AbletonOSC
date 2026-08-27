**Archived 2026-08-27 — shipped.** This is the plan as written *before*
implementation; the code as merged may differ. The change lives in
`abletonosc/track_identity.py` (the new `identify_track` resolver),
`abletonosc/view.py` (the identity getter and its `start_listen`/
`stop_listen` pair, and the three rewired legacy getters) and
`abletonosc/handler.py` (`_start_listen`'s `lom_property` aliasing), documented
in `API.md` § View API and its "Selected-track identity" subsection. No new
follow-up items were opened; the roadmap items that depended on this one
("A-4 · Object-valued read helpers" and "A-3 · Return / master `Track`
parity") had that dependency dropped since it is now satisfied.

# Plan: Define selected-track identity across regular, return, and master tracks

Roadmap item: **Define selected-track identity across regular, return, and
master tracks** (source: `issues.md`, "Define selected-track identity across
regular, return, and master tracks", High — that entry closes at ship time).
No dependencies; roadmap items "A-4 · Object-valued read helpers" and
"A-3 · Return / master `Track` parity" depend on the representation chosen
here.

## Context

The fork's own selection addresses break the view getters they share state
with. `/live/return_track/select` and `/live/master/select` (Seshat
extensions, `abletonosc/return_track.py`) assign `song.view.selected_track`
a return track or `song.master_track` — which the LOM accepts happily. But
`abletonosc/view.py`'s `get_selected_track` resolves the selection only one
way:

```python
def get_selected_track(params=()):
    return (list(self.song.tracks).index(self.song.view.selected_track),)
```

`song.tracks` holds regular (audio/MIDI/group) tracks only, so after a valid
return or master select, `.index()` raises `ValueError`. The request then
produces a structured `/live/error` instead of a reply — and it takes
`get_selected_clip` and `get_selected_device` down with it, since both call
`get_selected_track` first. Worse, `/live/view/start_listen/selected_track`
registers this getter as the listener push's value source: the exception
fires *inside Live's listener callback*, outside `OSCServer._dispatch`'s
per-message catch, so the push for that change simply never goes out and a
traceback lands in Live's log. `get_selected_device` additionally crashes the
same way when a regular track is selected but no device is
(`selected_device` is `None`, which `.index()` cannot find).

There is no representation on the wire today for "the selected track is a
return" or "…the master" — the fork can *put* selection there but cannot
*report* it. A-3 (return/master parity) and A-4 (object-valued reads, e.g.
"which track owns `appointed_device`?") both need exactly that
representation, which is why this item precedes them.

Key constraints research surfaced:

- **Seshat never reads selection.** Its `Session.State` tracks no selection
  at all, and `lib/` sends only the view *setters* (`FollowCam` steering,
  fire-and-forget) plus `get/is_view_visible`. No Seshat code decodes any
  reply this plan changes, and no Seshat code subscribes to
  `start_listen/selected_track`. The roadmap's "assess consumers expecting a
  single regular-track index" resolves to: there are none today.
- **Seshat's `vendored_addresses_test` requires every address registered in
  `view.py` to appear verbatim in the vendored `API.md`** (doc-coverage
  check over `@handler_files`, which includes `view.py`). New addresses ride
  the pin bump automatically *because* their `API.md` rows land in the same
  commit — no Seshat-side edit needed. The `@vendored_view_addresses` exact
  list covers only addresses `lib/` sends, which does not change.
- **The settle question is smaller than `issues.md` implies.**
  `/live/view/set/selected_device` echoes both indices; `issues.md` calls
  that "despite being documented as a silent setter", but `API.md` already
  documents it as "The only view setter that replies". Doc and code agree
  today; what remains is to record the *decision* (keep the echo — it is
  upstream's behaviour, silencing it would be a permanent divergence in an
  upstream file with breakage risk for non-Seshat clients, and Seshat's
  `FollowCam` deliberately ignores the reply) rather than to change code.
- **The fork's own precedents fix the shape of the answer.** Return/master
  already live in separate address families with their own index spaces
  (`API.md`: "Return-track indices are 0-based within `song.return_tracks` —
  a separate index space"), and A-4 is specified as "index or `-1` for
  none". So the identity representation is a **(category, index) pair**, and
  `-1` is the established "none" sentinel for the legacy single-int getters.
- **Testability follows the `track_callback.py` precedent.** `view.py`
  imports `Live` at module scope and stays out of `tests_unit/`'s reach, so
  the resolution logic goes into a new Live-free module the suite drives
  directly — which is also the "shared track resolver" seed the A-3 planner
  notes ask for.

## The representation

One canonical identity for any track: **`(category, index)`**, where

- `category` is one of the strings **`"track"`**, **`"return_track"`**,
  **`"master"`** — exactly the OSC address-family prefix that reaches that
  track (`/live/track/*` & `/live/view/set/selected_track`,
  `/live/return_track/*`, `/live/master/*`), so a reply is directly
  actionable: the category names the address family to use next;
- `index` is 0-based **within that category's collection** (`song.tracks`,
  `song.return_tracks`); the master is a single object and always carries
  index `0`.

Strings rather than numeric codes: self-documenting on the wire, no enum
table to keep in sync, and the fork already ships strings in replies
(`"ok"`/`"error"`, names). Legacy single-int addresses keep their shape and
report `-1` when the answer is outside their index space — the same sentinel
A-4 standardises.

## Wire contract

| Address | Status | Request | Reply |
|---|---|---|---|
| `/live/view/get/selected_track_identity` | **new** | (none) | `category, index` — `("track", i)`, `("return_track", i)`, or `("master", 0)` |
| `/live/view/start_listen/selected_track_identity` | **new** | (none) | (no direct reply; see listener behaviour) |
| `/live/view/stop_listen/selected_track_identity` | **new** | (none) | (no reply) |
| `/live/view/get/selected_track` | **changed** | (none) | `track_index` — index in `song.tracks`, or **`-1`** when the selection is a return or the master (today: no reply, `ValueError` on `/live/error`) |
| `/live/view/get/selected_clip` | **changed** | (none) | `track_index, scene_index` — `track_index` is `-1` when the selection is a return or the master (today: no reply, error) |
| `/live/view/get/selected_device` | **changed** | (none) | `track_index, device_index` — `(i, d)` when a regular track and a top-level device are selected; `(i, -1)` when a regular track is selected but there is no top-level device to report — no device selected, **or** the selected device is nested inside a rack chain and so absent from `track.devices` (both today: error); `(-1, -1)` when the selection is a return or the master (today: error) |
| `/live/view/start_listen/selected_track` | **changed (push value only)** | (none) | pushes on `/live/view/get/selected_track`; after this change the push carries `-1` for a return/master selection instead of dying inside the listener callback with no push at all |
| `/live/view/set/selected_track` | unchanged-but-relied-on | `track_index` | (silent; regular tracks only, by design — returns/master are selected via their own families) |
| `/live/view/set/selected_device` | unchanged — **settled** | `track_index, device_index` | echoes `track_index, device_index`; kept as the one deliberate, documented exception to "view setters are silent" (upstream behaviour) |
| `/live/return_track/select`, `/live/master/select` | unchanged-but-relied-on | `[index]` / (none) | (silent) |
| `/live/view/get/selected_scene`, `set/selected_scene`, `set/selected_clip`, scene listeners | unchanged | | |

Error behaviour:

- The three changed getters and the new identity getter **never error for a
  selection-category or no-device-selected reason** — those are answers, not
  failures, and they are encoded in the reply (`-1` / category). A genuine
  LOM failure (e.g. the resolver meeting a track that is in none of the
  three collections — not expected to be reachable, and including a `None`
  `selected_track`, per Open question 3) still raises and arrives
  as a structured `/live/error` via `OSCServer._dispatch`, unchanged.
- The new getter takes no arguments, so like `/live/master/get/volume` it
  replies bare values with no `"ok"`/`"error"` envelope — the envelope
  exists for index-taking getters with a bad-index failure path.
- Silence on the new addresses still means exactly one thing: this fork
  isn't installed.

Listener behaviour:

- `start_listen/selected_track_identity` subscribes to the **same LOM
  property** as `start_listen/selected_track` (`Song.View.selected_track`,
  observable, already used by upstream) but pushes
  `/live/view/get/selected_track_identity [category, index]` on every
  selection change, and once immediately on subscribe (standard
  `_start_listen` behaviour). The two listeners coexist: distinct
  bookkeeping keys, one LOM property with two callbacks.
- `stop_listen/selected_track_identity` removes exactly that subscription;
  `stop_listen/selected_track` keeps removing only the legacy one.
- Starting an already-started identity listen restarts it (existing
  `_start_listen` semantics); stopping a never-started one logs the
  standard warning and does nothing.

Logging: the reworked getters and the identity getter log their result at
info level (mirroring `_get_property`'s "Getting property for …" lines), so
every Live check below is decidable from `logs/abletonosc.log` under the
no-probe rig — today these hand-written closures log nothing on success.

## Numbered parts

### Part 1 — the resolver module: `abletonosc/track_identity.py`

New file, importing nothing Live-side (stdlib `typing` only), on the
`track_callback.py` model. Contents:

- `CATEGORY_TRACK = "track"`, `CATEGORY_RETURN = "return_track"`,
  `CATEGORY_MASTER = "master"`.
- `identify_track(song, track) -> Tuple[str, int]` — compares `track`
  against `song.master_track` first (single object, cheapest), then scans
  `song.tracks`, then `song.return_tracks`, using `==` per element (the
  same equality `.index()` relies on throughout upstream). Raises
  `ValueError` naming the track when it matches nothing (includes a `None`
  selection, which a loaded set is never expected to produce — see Open
  questions).
- `selected_track_identity(song) -> Tuple[str, int]` —
  `identify_track(song, song.view.selected_track)`.
- `selected_track_index(song) -> int` — the legacy single-int view:
  index in `song.tracks`, `-1` for any non-`"track"` category.
- `selected_device_indices(song) -> Tuple[int, int]` — `(track_index,
  device_index)` per the wire contract above: resolves the track via
  `identify_track`; for a regular track, resolves
  `song.view.selected_track.view.selected_device` within
  `song.view.selected_track.devices` by `==` scan, `-1` when `None` or not
  found; `(-1, -1)` for return/master.

Same commit:

- `tests_unit/test_track_identity.py` (see Testing).
- `manager.py`: `importlib.reload(abletonosc.track_identity)` inserted
  immediately **before** `importlib.reload(abletonosc.view)` (view.py will
  `from`-import it — same before/after reasoning as the existing
  `track_callback`-before-`track` comment, and worth the same one-line
  comment).
- `SESHAT.md`: extend the merge-hazard bullet that covers
  `manager.py`'s `reload_imports` list (the `track.py`/`track_callback.py`
  one) to name `abletonosc.track_identity` as a second fork-owned line that
  a merge taking upstream's list silently drops.

### Part 2 — `handler.py`: listen to one LOM property, push under another name

`_start_listen` derives three things from `prop` today: the bookkeeping key,
the push address, and the `add_%s_listener` accessor name. The identity
listener needs the first two to say `selected_track_identity` while the
third says `selected_track`. So:

- `_start_listen(self, target, prop, params=(), getter=None,
  lom_property=None)` — `lom_prop = lom_property or prop`;
  `add_%s_listener` uses `lom_prop`; the key stays `(prop, tuple(params))`
  and the push address stays `"/live/%s/get/%s" % (class_identifier, prop)`.
- A third bookkeeping dict `self.listener_lom_properties`, initialised in
  `AbletonOSCHandler.__init__` beside `listener_functions` /
  `listener_objects`, records `listener_key -> lom_prop`.
- `_stop_listen` resolves
  `lom_prop = self.listener_lom_properties.get(listener_key, prop)` for the
  `remove_%s_listener` name (the `.get` fallback keeps every existing call
  site and any stale-key path behaving exactly as today) and deletes the
  entry alongside the other two dicts.
- `_clear_listeners` needs no change: it reconstructs `(prop, params)` from
  the key and `_stop_listen` now recovers the LOM property itself — this is
  the reason the mapping must be stored rather than passed.

Default path (`lom_property=None`) is behaviour-identical, byte-for-byte in
its observable effects; the existing `tests_unit` listener tests are the
regression net.

Same commit:

- New Live-free tests driving the real `handler.py` (see Testing).
- `SESHAT.md`: update the "Anything touching `_stop_listen`,
  `_start_listen`, or `listener_objects`" merge-hazard bullet and the
  `AbletonOSCHandler.__init__` bullet to cover `lom_property` and
  `listener_lom_properties` — a merge that takes upstream's `handler.py`
  drops both silently, and the new unit tests are the tripwire to name.

### Part 3 — `view.py` rewiring, the new addresses, and the docs

`abletonosc/view.py`:

- `from .track_identity import selected_track_identity,
  selected_track_index, selected_device_indices` (module-level, so reload
  order from Part 1 applies).
- `get_selected_track` → `(selected_track_index(self.song),)`;
  `get_selected_clip` composes it unchanged; `get_selected_device` →
  `selected_device_indices(self.song)`; new
  `get_selected_track_identity` → `selected_track_identity(self.song)`.
  Each logs its result at info level.
- Register `/live/view/get/selected_track_identity`, plus
  `/live/view/start_listen/selected_track_identity` via
  `partial(self._start_listen, self.song.view, "selected_track_identity",
  getter=get_selected_track_identity, lom_property="selected_track")` and
  the matching `stop_listen` via `partial(self._stop_listen, self.song.view,
  "selected_track_identity")`.
- Extend the file-top Seshat-extensions comment block with the three new
  addresses and the changed-getter semantics (it is the in-file contract
  record, mirroring the existing four).

Same commit, documentation:

- `API.md` § View API: the three new rows (marked ⚠️ Seshat extension, like
  the existing four); amend the `get/selected_track`, `get/selected_clip`,
  `get/selected_device` and `set/selected_device` rows; replace the
  "`/live/view/set/selected_track` resolves its index through `song.tracks`"
  bullet with a short **Selected-track identity** note: the
  `(category, index)` representation, category strings = address-family
  prefixes, the `-1` sentinel on the legacy getters, listener coexistence,
  which select address each category maps to, and the settled
  `set/selected_device` echo (deliberate upstream-compatible exception,
  dated). Update the extension-row **counts** to seven where a count is what
  the text states: API.md's "⚠️ Four rows above do **not** exist in stock
  AbletonOSC" (View extensions subsection) and `view.py`'s file-top "Four
  addresses in this file are Seshat extensions". Do **not** mechanically
  replace every "four": the subsection prose that follows ("Without that
  install all four here are unknown: the three setters silently do nothing,
  and the getter never replies") describes the four view-steering addresses
  specifically — reword rather than renumber, adding the identity trio's own
  uninstalled behaviour (getter queries time out; the listen pair is unknown
  and never pushes).
- `SESHAT.md`: extend the `view.py` additions bullet (currently the four
  view addresses) with the new addresses and the changed reply semantics,
  including that the changed getters are a *behavioural* divergence inside
  an upstream file (upstream raises where the fork now answers `-1`), so a
  merge taking upstream's `view.py` getters reverts it silently.
- `FORK_GAPS.md`: **no entry closes and no regeneration is needed** —
  `Song.View.selected_track` is already counted exposed, the new addresses
  expose no additional LOM member, and no new address segment equals a LOM
  member name, so `tools/lom_gaps.py` coverage is unchanged. The plan
  records this explicitly so `/ship` doesn't go looking.
- `issues.md`: untouched now; the source entry is removed at `/ship` time
  per the roadmap's removal rule.

## Testing (`tests_unit/`, the only gate)

All Live-free, `python3 -m pytest tests_unit/` (94 tests green at base
`96b8c22`; must stay green plus the additions).

- **`tests_unit/test_track_identity.py`** (new) — imports the real module
  via `conftest.load_module("abletonosc.track_identity")`. Fake song built
  from plain objects (default identity-based `==`, matching the LOM's
  object-identity equality): `tracks`, `return_tracks`, `master_track`,
  `view.selected_track`, per-track `devices` and `view.selected_device`.
  Cases: each category resolves with the right index (first/last/middle
  return); master reports index 0; `identify_track` raises `ValueError` on
  an unknown object and on `None`; `selected_track_index` gives `-1` for
  return/master; `selected_device_indices` gives `(i, d)`, `(i, -1)` for
  `selected_device is None` and for a device object not on the chain, and
  `(-1, -1)` for return/master; empty `tracks`/`return_tracks` lists do not
  blow up master resolution.
- **Listener aliasing tests** (new, beside the existing handler-lifecycle /
  device-listener suites; e.g. `tests_unit/test_listener_alias.py`) —
  construct the real `AbletonOSCHandler` via `conftest.load_handler_module`'s
  Probe pattern, with a fake target recording
  `add_selected_track_listener` / `remove_selected_track_listener` calls
  and a stub `osc_server` recording sends. Assert: `lom_property` routes
  add/remove to the LOM name while the key and push address use the public
  name (`/live/<id>/get/selected_track_identity`); the immediate push fires
  with the getter's value; double-start restarts (old callback removed from
  the fake, exactly one live subscription); `stop_listen` with the public
  name removes the right callback and clears all three dicts;
  `_clear_listeners` (i.e. `clear_api`) unbinds an aliased listener without
  raising; and the `lom_property=None` default leaves every existing
  observable behaviour intact (existing tests double as this regression
  net).

Explicitly **not** covered Live-free: `view.py`'s registrations and closures
(it imports `Live` at module scope, like every production handler except
`device.py`, and `conftest.py` deliberately stubs nothing beyond the
Component base), the real LOM's equality semantics, and listener firing on
category changes — that is what Live verification below is for. `tests/`
mutates a running Live when opted in and is not part of the gate.

## Live verification

Precondition for every check: the Remote Scripts copy equals this checkout
byte for byte **and** Live has been restarted since it was copied. Method:
`API.md` § "The no-probe variant" — send fire-and-forget UDP to 11000, read
evidence from the installed `logs/abletonosc.log` (11001 is Seshat's; the
new info-level getter logging added in Part 3 exists exactly so these
checks are log-decidable). Wrap the sequence in
`/live/song/begin_undo_step` / `end_undo_step`; selection is view state and
not undo-covered, so **also** read the identity first and re-select the
original track by category at the end.

1. **Baseline + install probe.** Send `/live/view/get/selected_track_identity`.
   Evidence: a log line with `("track", i)` (or the actual category) matching
   the highlighted track in Live's UI. This is also the "new address is
   registered" check — an uninstalled/stale copy logs `Unknown OSC address`.
2. **Return selection agrees everywhere.** Send `/live/return_track/select 0`,
   then `get/selected_track_identity`, then `get/selected_track`, then
   `get/selected_clip`, then `get/selected_device`. Evidence: log lines
   showing `("return_track", 0)`, `-1`, `(-1, <scene>)`, `(-1, -1)`, and
   **no traceback** — today the last three log a `ValueError`. This is the
   check that decides Open question 1 (LOM equality for returns).
3. **Master selection agrees everywhere.** Send `/live/master/select`, then
   the same four getters. Evidence: `("master", 0)`, `-1`, `(-1, <scene>)`,
   `(-1, -1)`. Decides Open question 1 for the master.
4. **Identity listener pushes across categories.** Send
   `/live/view/start_listen/selected_track_identity` — evidence: the
   immediate "Property selected_track_identity changed" push line. Then
   `/live/view/set/selected_track 0`, `/live/return_track/select 0`,
   `/live/master/select` — evidence: three push lines carrying
   `("track", 0)`, `("return_track", 0)`, `("master", 0)`. Decides Open
   question 2 (listener fires on category moves). Then
   `stop_listen/selected_track_identity` — evidence: "Removing listener"
   line; and one further `master/select`→`set/selected_track` round trip
   produces **no** further identity push lines.
5. **Legacy listener no longer dies.** `start_listen/selected_track`, then
   `/live/return_track/select 0` — evidence: a push line with `-1` and no
   traceback (today: traceback, no push). Then `stop_listen/selected_track`.
   (Seshat holds no `selected_track` subscription — verified against its
   `lib/` — so the stop strands nothing; per the rig rule, first grep the
   log's "Adding listener" lines to confirm.)
6. **Device none-selected sentinel.** With a regular track selected and its
   device chain empty (or after clicking empty space so no device is
   selected — UI step), `get/selected_device` — evidence: `(i, -1)` logged,
   no error. (If the set happens to have a rack, selecting a device nested
   inside it is a second, optional probe of the same `(i, -1)` arm — the
   nested device is absent from `track.devices`; `tests_unit/` covers this
   arm regardless.)
7. **Restore.** Re-select the originally selected track via the address its
   recorded category names; re-read `get/selected_track_identity` and match
   it against the step-1 value. `end_undo_step`.

Remains uncovered even after this: `set/selected_device`'s echo reaching the
wire (the reply port is Seshat's; the echo is upstream-shipped behaviour and
untouched by this change), and `identify_track`'s `ValueError` arm (requires
a selection outside all three collections, which nothing can produce on
purpose — it exists as a guard, exercised only in `tests_unit/`).

## Downstream

**Pin bump only.** Rationale, address by address: Seshat sends none of the
changed getters and holds no view listeners (verified against `lib/` — the
only view addresses in `lib/` are the setters FollowCam fires and forgets,
plus `get/is_view_visible`); the `set/selected_device` echo it already
deliberately ignores is unchanged; the three new addresses enter the
vendored `API.md` in the same commit, which is exactly what
`vendored_addresses_test`'s doc-coverage check requires — they join neither
`@vendored_view_addresses` (that list is only for addresses `lib/` sends)
nor any `Session.State` matcher. No decoding change, no renamed address, no
new tripwire. If Seshat later wants selection mirroring (e.g. a
"what is selected?" tool), `selected_track_identity` is the address to
build it on — new work there, not an obligation of this pin.

## Out of scope

- **An identity *setter*** (`/live/view/set/selected_track_identity
  [category, index]`). Redundant: each category already has a select address
  (`/live/view/set/selected_track`, `/live/return_track/select`,
  `/live/master/select`), and the API.md identity note documents the
  mapping. Reopen only if a consumer wants one datagram instead of a
  two-step.
- **The inverse resolver** (`(category, index) -> track object`) and any
  widening of `/live/return_track/*` / `/live/master/*` handler tables.
  That is A-3's job; `track_identity.py` is deliberately the module it will
  grow in.
- **Device identity on returns/master** (`selected_device` resolution when
  the selection is a return or the master — the chain is readable, only the
  reply shape is missing). Belongs to A-3's device-surface parity;
  `(-1, -1)` says "not answerable in regular-track coordinates" until then.
- **`highlighted_clip_slot`, `selected_chain`, `selected_parameter`,
  `appointed_device`** and the rest of `Song.View` — A-4, which builds on
  this representation.
- **Making `view.py` importable without Live** (moving `import Live` into
  the closures) — would widen `tests_unit/` coverage but is a gratuitous
  diff in an upstream file; the extracted resolver already carries the
  logic worth testing. Reconsider if roadmap item "Verify handler
  `class_identifier` … without Live" (#1 at time of writing) wants more.
- **`scene.py`/`clip.py`/`clip_slot.py` listener-identity normalization** —
  its own roadmap item (created by the device-listener-identity review),
  not this one, even though both touch listener bookkeeping.

## Open questions

1. ⚠️ **Does LOM equality hold for the master and return readback?** —
   i.e. after `song.view.selected_track = song.master_track`, does
   `selected_track == master_track` (and membership of a selected return in
   `list(song.return_tracks)`) evaluate `True` across separately obtained
   references? Could not be measured this run: Live was running, but the
   permission system denied writing the probe handler into the installed
   Remote Scripts copy, so the `API.md` measuring rig was unavailable.
   Confidence is high regardless: upstream's shipped getters already depend
   on cross-reference `==` via `.index()` for tracks, scenes and devices,
   the fork's `load_item_on_return`/`_on_master` measured (2026-07-31) that
   `song.view.selected_track` assignment round-trips through the LOM
   correctly, and Boost.Python LOM wrappers compare by underlying object.
   The plan assumes **yes**; Live verification checks 2–3 decide it, and
   they run before anything ships. If it somehow failed, the resolver is
   the single place to swap in a different comparison.
2. ⚠️ **Does the `selected_track` listener fire when selection crosses
   categories** (regular → return → master)? Same measurement block as
   above. Assumed **yes** — it is one observable LOM property with one
   notifier, and Live's own docs type it as "the selected track", not "the
   selected regular track". Live verification check 4 decides. If it fired
   only for regular tracks, the getters and the new getter are unaffected;
   the identity listener would under-report exactly as the legacy one
   always has, and that finding would go to `API.md` as a measured
   limitation rather than changing this design.
3. **Can `song.view.selected_track` be `None`?** Not measurable on demand
   (no known UI state produces it; Live always highlights some track).
   Decided rather than left open: `identify_track` raises `ValueError` on
   `None` like any unknown object, which `_dispatch` turns into a
   structured `/live/error` — a loud, attributable answer to a state the
   plan believes unreachable. Listed here only because it cannot be proven
   unreachable from outside Live's source.

### Result — 2026-08-27 (pr-review): **skipped by environment**

Checks 1–7 were **all skipped by environment**; none was run, and no result
is recorded for any of them. Nothing about the design, the resolver or the
listener aliasing is confirmed or refuted on real Live objects by this
review, and open questions 1 and 2 remain open.

Precondition state at review time:

- **Live is running** — PID 70216, `Ableton Live 12 Suite`.
- **The installed copy is not this checkout.** `diff -rq
  --exclude=__pycache__ abletonosc "$HOME/Music/Ableton/User Library/Remote
  Scripts/AbletonOSC/abletonosc"` reports 14 differing files —
  `application.py`, `browser.py`, `clip.py`, `clip_slot.py`, `device.py`,
  `handler.py`, `midimap.py`, `osc_server.py`, `return_track.py`,
  `scene.py`, `song.py`, `song_structure.py`, `track.py`, `view.py` — and
  two files present only in the checkout: `track_callback.py` and
  `track_identity.py`. The install predates at least the previous two
  shipped items, so it carries neither the `lom_property` alias nor
  `track_identity.py`, and `/live/view/get/selected_track_identity` would
  answer `Unknown OSC address` for the trivial reason that the code is not
  there.
- **Restart therefore cannot be established either** — moot while the copy
  differs.

Installing this checkout into Remote Scripts and restarting Live are both
outside a review's bounds (as is binding 11001, which Seshat holds), so no
UDP was sent and the installed `logs/abletonosc.log` was not appended to by
this review. Checks 1–7 remain the gate they were written to be, and must
run against an installed, restarted copy of this branch before the
behaviour is claimed anywhere as measured.
