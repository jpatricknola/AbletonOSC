# Plan: Object-valued read helpers (A-4)

Roadmap item: **#1 · A-4 · Object-valued read helpers** — from
`CLOSING_THE_GAPS.md` row A-4, closing FORK_GAPS "Object-valued reads
returned as `None`". Planned 2026-08-27.

## Context

The generic property loop (`properties_r` / `properties_rw`) turns any value
the OSC builder cannot encode into an error or `None`, so every LOM member
whose value is another LOM object — `Song.appointed_device`,
`Track.group_track`, `ClipSlot.clip`, `Song.View.selected_chain`,
`selected_parameter`, `mod_mapping_device`, `mod_mapping_parameter` — is
unreadable over the wire today. Each needs a hand-written handler that
answers with *indices into the collections the existing address families
already accept*, `-1` for "none".

This item is small on purpose: it establishes the **object-read pattern**
that every later object-family PR (groove, racks/chains, cue points) reuses,
and it is the declared dependency of the groove bucket (roadmap "D-2 ·
Groove" depends on this item's pattern).

Key constraints research surfaced:

- **The identity convention is already shipped.** `track_identity.py` defines
  `(category, index)` identity for any track — `"track"` / `"return_track"` /
  `"master"`, category strings being exactly the OSC address-family prefixes —
  and its docstring already reserves this item by name: "A-3 … and A-4
  (object-valued read helpers) are both specified against this
  representation, and the inverse resolver ((category, index) -> track
  object) belongs here when A-3 needs it." A-4's setter needs the inverse
  resolver now, so it lands here.
- **`-1` is an answer, never an argument** (`API.md` § Selected-track
  identity). The new getters answer `-1`; the one new setter *rejects*
  negative indices explicitly (a new address has no upstream-compat reason to
  inherit Python's silent negative indexing, which is the documented hazard
  on `set/selected_track`).
- **Return/master devices are already addressable.** `/live/return_track/device/*`
  and `/live/master/device/*` exist (Seshat extension), so a device identity
  that names a category is *directly actionable* today — no need to collapse
  return/master devices to `(-1, -1)` the way the legacy
  `get/selected_device` shape must.
- **Reload order is a trap.** `manager.reload_imports` reloads
  `abletonosc.song` and `abletonosc.track` *before* `abletonosc.track_identity`.
  Both gain `from .track_identity import …` in this item, so the
  `track_identity` reload line must move up — the same silent stale-binding
  failure mode SESHAT.md § Merge hazards documents for `track_callback` /
  `track` and `track_identity` / `view`, and no Live-free test can catch it.
- **`song_export_structure` is not refactored.** The roadmap note "reuse that
  resolution" is honoured by giving the new `group_track` read the *same
  resolution semantics* (index into `song.tracks` by `==` scan, via
  `track_identity`), not by editing upstream's inline copy in
  `song.py:177-184` — that function is upstream code kept verbatim to avoid
  an unforced divergence, and roadmap item "Remove the process-global and
  shared-file risks from song structure export" may delete it outright.
- **`Song.master_track` gets no address** — see Out of scope.

Evidence tier: member kinds, settability and observability below are tier-1
(read from a running Live 12.4.3 by the FORK_GAPS generated inventory):
`appointed_device` rw+observable, `selected_chain` rw+observable,
`selected_parameter` ro+observable, `mod_mapping_device` rw+observable,
`mod_mapping_parameter` ro+observable, `group_track` ro **not** observable.
`canonical_parent` behaviour and cross-class `==` are *not* measured — Live
was running during planning but the permission layer blocked both
measurement variants (probe write and UDP send), so those are ⚠️ Open
questions with defensive handling specified.

## The object-read pattern

What later PRs cite. All of it lands in `API.md` § "Conventions the address
tables don't show" as a new subsection (Part 6):

1. An object-valued member never enters the generic property loop; it gets a
   hand-written handler.
2. The reply identifies the object by **indices into the collections the
   existing address families accept**, prefixed by the track-identity
   category when the owning track can be any of the three kinds:
   - track-valued, confined to regular tracks → bare `track_index`
     (`group_track`);
   - device-valued → `(category, track_index, device_index)`;
   - parameter-valued → `(category, track_index, device_index, parameter_index)`;
   - chain-valued → `(category, track_index, device_index, chain_index)`.
3. `-1` means "none, or not representable at top level" — a `None` member, an
   ungrouped track, an empty slot, a device nested inside a rack chain
   (absent from `track.devices` until A-1 ships a path resolver).
4. When the member itself is `None`, the category slot carries the
   **reply-only** category `"none"` and every index is `-1`. `"none"` never
   appears anywhere but a reply, and no setter accepts it.
5. Replies are fixed-arity: a given address always answers the same number
   of arguments.
6. Getters never error for a "none" reason — that is an answer. A genuine
   resolution failure (an object in no collection, an exhausted
   `canonical_parent` ascent) raises and arrives as a structured
   `/live/error`, loudly — on the **request** path, where
   `OSCServer._dispatch`'s envelope catches it. A *listener push* has no
   such envelope: the getter runs inside Live's listener callback, so a
   resolution failure there kills that push with nothing on the wire and
   only Live's Log.txt to show for it — the same accepted limit as the
   shipped `selected_track_identity` listener (see view.py's header on the
   pre-fork `selected_track` push dying the same way).
7. Every hand-written object-read handler logs its resolution at info level
   (the `get_selected_track_identity` precedent), because the installed
   log file is the only evidence channel when the reply port is held.

## Wire contract

All addresses **new** (nothing existing changes shape). All are fork
divergences to record in SESHAT.md; none exist upstream.

| Address | Request | Reply | Notes |
|---|---|---|---|
| `/live/track/get/group_track` | `track_index` (int, or `"*"`) | `track_index, group_track_index` | `group_track_index` into `song.tracks`; `-1` when ungrouped. `*` fans out per regular track (free via `create_track_callback`, same rules as every other `/live/track/get/*`). No listen pair — `group_track` is not observable (tier-1). Bad index → `/live/error`. |
| `/live/clip_slot/get/clip` | `track_index, clip_index` | `track_index, clip_index, clip_index_or_neg1` | The object-read form of `has_clip`: third field is the clip's index in `/live/clip/*` coordinates — equal to `clip_index` when a clip exists, `-1` when the slot is empty. Indices normalised to int by `create_clip_slot_callback`. No listen pair (see Open questions #7). Bad index → `/live/error`. |
| `/live/song/get/appointed_device` | — | `category, track_index, device_index` | The appointed ("blue hand") device. `category` ∈ `"track"`, `"return_track"`, `"master"`, or reply-only `"none"` (nothing appointed → `("none", -1, -1)`). Nested (rack-chain) device → `(category, track_index, -1)`. Resolution failure → `/live/error`. |
| `/live/song/set/appointed_device` | `category, track_index, device_index` | (silent) | Resolves through the category's collection (`song.tracks` / `song.return_tracks` / `song.master_track`, master requires `track_index == 0`), then `track.devices[device_index]`. **Rejects** `"none"`, unknown categories, negative or out-of-range indices with `ValueError` → structured `/live/error`. Top-level devices only. No un-appoint (no `None`, no `-1`). |
| `/live/song/start_listen/appointed_device` | — | pushes `category, track_index, device_index` on `/live/song/get/appointed_device` | Standard listener contract: one push immediately on subscribe, then on every change. Uses the base `_start_listen` with a custom `getter` (the `selected_track_identity` precedent). A resolution failure *inside the push callback* is outside `_dispatch`'s error envelope — no push, Log.txt only (pattern rule 6). |
| `/live/song/stop_listen/appointed_device` | — | — | Removes exactly its own subscription. |
| `/live/view/get/selected_chain` | — | `category, track_index, device_index, chain_index` | The highlighted rack chain. `device_index` is the owning rack's index in `track.devices` (`-1` if the rack is itself nested); `chain_index` its index in that rack's `chains`. No chain selected → `("none", -1, -1, -1)`. |
| `/live/view/get/selected_parameter` | — | `category, track_index, device_index, parameter_index` | `parameter_index` into `device.parameters` when the parameter's parent is a top-level device; a mixer/send parameter or a nested device's parameter → `(category, track_index, -1, -1)`. Nothing selected → `("none", -1, -1, -1)`. |
| `/live/view/get/mod_mapping_device` | — | `category, track_index, device_index` | Device triple, same shape and sentinels as `appointed_device`. Idle (nothing waiting for a mapping) → `("none", -1, -1)`. |
| `/live/view/get/mod_mapping_parameter` | — | `category, track_index, device_index, parameter_index` | Parameter quad, same shape and sentinels as `selected_parameter`. Idle → `("none", -1, -1, -1)`. |

Error behaviour, all addresses: exceptions propagate to `OSCServer._dispatch`
and arrive as `/live/error ["request", address, message, argc, *args]` — the
fork's standard envelope. The four view getters and the two song getters take
no arguments, so their only error path is a resolution failure.

Relied-on-unchanged: `/live/view/get/selected_track_identity` (category
strings and their meaning), `/live/return_track/device/*` and
`/live/master/device/*` (what makes the category triple actionable),
`/live/track/get/*` wildcard rules.

## Numbered parts

### Part 1 — `abletonosc/track_identity.py`: the resolvers

The Live-free half, where all resolution logic lives (view.py and song.py
import `Live` at module scope and are unreachable from `tests_unit/`; this
module is the shipped code under test — the established pattern).

Add, alongside the existing `identify_track` / `NO_INDEX`:

- `CATEGORY_NONE = "none"` — reply-only, documented as such in the module
  header.
- `group_track_index(song, track) -> int` — `track.group_track` is `None` →
  `NO_INDEX`; else its index in `song.tracks` by `==` scan (identical
  semantics to `song_export_structure`'s `list(...).index(...)`); a
  non-`None` group track absent from `song.tracks` raises `ValueError`
  (impossible state, loud).
- `owning_track_identity(song, obj) -> (category, index)` — bounded
  `canonical_parent` ascent (cap ~16 levels): at each node try
  `identify_track`, on `ValueError` step to `getattr(node,
  "canonical_parent", None)`; `None` or cap exhausted → `ValueError` naming
  the object (via the existing `_describe`-style guard).
- `device_identity(song, device) -> (category, track_index, device_index)` —
  `None` → `(CATEGORY_NONE, NO_INDEX, NO_INDEX)`; else owner via
  `owning_track_identity`, `device_index` by `==` scan of the owning track's
  `devices`, `NO_INDEX` when absent (nested).
- `parameter_identity(song, parameter) -> (category, track_index, device_index, parameter_index)`
  — `None` → none-quad; else owner via ascent from the parameter;
  `parent = parameter.canonical_parent`; if `parent` is a top-level device of
  the owning track, `(cat, ti, di, index-of-parameter-in-parent.parameters)`;
  else (mixer/send parameter, nested device) `(cat, ti, NO_INDEX, NO_INDEX)`.
- `chain_identity(song, chain) -> (category, track_index, device_index, chain_index)`
  — `None` → none-quad; else `parent = chain.canonical_parent` (the rack),
  owner via ascent, `device_index` by scan of owner's `devices`,
  `chain_index` by scan of `parent.chains`.
- `resolve_track(song, category, index) -> track` — the inverse resolver the
  module docstring reserves: validates the category string, requires
  `index == 0` for `"master"`, bounds-checks (`0 <= index < len`) for the
  other two, `ValueError` otherwise. Rejects `CATEGORY_NONE`.
- `resolve_device(song, category, track_index, device_index) -> device` —
  `resolve_track` plus explicit `0 <= device_index < len(track.devices)`
  check; `ValueError` names the offending argument. This is where "`-1` is
  never an argument" becomes enforcement rather than documentation.

Update the module header: the A-4 sentence changes from prospective to
present tense; document the ascent cap and `CATEGORY_NONE`.

Docs in this part: none (no address registered yet).

### Part 2 — `manager.py`: reload `track_identity` before its importers

Move `importlib.reload(abletonosc.track_identity)` above
`importlib.reload(abletonosc.song)` (e.g. directly after
`abletonosc.introspection`), with a comment naming all three `from`-importers
— song, track, view — in the style of the existing ordering comments. Update
the existing comment above `abletonosc.view`.

Docs in this part: extend the `reload_imports` bullet in SESHAT.md § Merge
hazards — the `abletonosc.track_identity` line must now precede **song and
track as well as view**, same silent failure mode, still no Live-free
coverage.

### Part 3 — `abletonosc/track.py`: `/live/track/get/group_track`

Hand-written worker registered through `create_track_callback`, which buys
the `*` wildcard fan-out and int normalisation for free:

```python
def track_get_group_track(track, params: Tuple[Any] = ()):
    index = group_track_index(self.song, track)
    self.logger.info("Getting property for track: group_track = %s" % index)
    return (index,)
```

(import `group_track_index` from `.track_identity` at module top). Register
under `/live/track/get/group_track`. **No** `start_listen`/`stop_listen`
registration — not observable.

Docs in this part, same commit:
- `API.md` § Track Getters: the row (request/reply/`-1` semantics, wildcard
  applies, *no listen pair* — check the section preamble and the listener
  blanket statements and carve the exception explicitly where one exists).
- `SESHAT.md`: divergence entry (new address in an upstream file — the
  `begin/end_undo_step` precedent) under Additions.

### Part 4 — `abletonosc/clip_slot.py`: `/live/clip_slot/get/clip`

Worker through `create_clip_slot_callback` (int normalisation, `(track_index,
clip_index, *rv)` echo for free):

```python
def clip_slot_get_clip(clip_slot, identity: Tuple[Any] = ()):
    # identity is the wrapper-normalised (track_index, clip_index);
    # the wrapper also echoes it as the reply's first two fields
    clip_index = identity[1] if clip_slot.clip is not None else -1
    ...log...
    return (clip_index,)
```

registered with `pass_clip_index=True`. That flag is what delivers the
slot's own index: a plain registration hands the callee only
`tuple(params[2:])` — empty for a two-argument get — and
`duplicate_clip_slot`'s `args` are *extra* client arguments (the target
slot), not the slot's own identity, so neither route reaches `clip_index`.
`pass_clip_index=True` hands the callee the normalised `(track_index,
clip_index)` tuple instead, which is exactly the canonical identity this
reply needs. Its comment in clip_slot.py currently says the flag is "used by
the listen pair only" — update that wording in the same edit. Do not
re-parse raw `params` in the worker: a float `clip_index` from a
TouchOSC-style client would echo un-normalised in the third field. No
listen pair.

Docs in this part, same commit:
- `API.md` § Clip Slot API: the row, **plus** an exception carved into the
  blanket sentence "Every `get/` property above also has
  `/live/clip_slot/start_listen/...`" — `get/clip` has no listen pair.
- `SESHAT.md`: divergence entry (upstream file).

### Part 5 — `abletonosc/song.py`: `appointed_device` get / set / listen

At module top: `from .track_identity import device_identity, resolve_device`
(Part 2 makes this reload-safe). In `init_api`:

```python
def song_get_appointed_device(params: Optional[Tuple] = ()):
    identity = device_identity(self.song, self.song.appointed_device)
    self.logger.info("Getting property for song: appointed_device = %s" % str(identity))
    return identity

def song_set_appointed_device(params):
    category, track_index, device_index = str(params[0]), int(params[1]), int(params[2])
    self.song.appointed_device = resolve_device(self.song, category, track_index, device_index)
```

Register `get/`, `set/`, and the listen pair via
`partial(self._start_listen, self.song, "appointed_device",
getter=song_get_appointed_device)` / `partial(self._stop_listen, self.song,
"appointed_device")` — the property name matches the LOM accessor
(`add_appointed_device_listener`, tier-1 observable), so no `lom_property`
alias is needed; the push goes out on `/live/song/get/appointed_device`.

Placement: with the other hand-written handlers, *not* in the generic loops
(SESHAT.md merge hazard: the generic lists in song.py carry fork-owned
entries; keep this visibly separate).

Docs in this part, same commit:
- `API.md` § Song Getters + § Song Setters rows; listener behaviour noted
  (push shape = getter reply; immediate push on subscribe). Check the Song
  section's listener blanket statements the same way as Parts 3–4.
- `SESHAT.md`: divergence entry (three new addresses in an upstream file).

### Part 6 — `abletonosc/view.py`: the four Song.View getters + the pattern doc

Four getters in `init_api`, each logging its resolution, registered on
`/live/view/get/selected_chain`, `selected_parameter`, `mod_mapping_device`,
`mod_mapping_parameter`, calling `chain_identity` / `parameter_identity` /
`device_identity` / `parameter_identity` respectively on the corresponding
`self.song.view` member (import the three resolvers alongside the existing
`track_identity` imports). Get-only — no setters, no listeners (Out of
scope). Update view.py's header comment block (it enumerates the fork's
addresses in this file).

Docs in this part, same commit:
- `API.md` § View API: four rows, ⚠️-marked as Seshat extensions like their
  neighbours; update § "View extensions (Seshat…)" — "Seven rows above"
  becomes eleven, and the not-installed behaviour note covers the four new
  getters (never reply when not installed).
- `API.md` § Conventions: new subsection "Object-valued reads" carrying the
  pattern rules from "The object-read pattern" above, cross-referenced from
  the Selected-track identity `-1` paragraph.
- `SESHAT.md`: extend the view.py entry under "Seshat's own handlers".

### Part 7 — FORK_GAPS

Same commit: delete the curated section **"Object-valued reads returned as
`None`"** (line ~361). The generated inventory is regenerated only from a
real dump and none exists (see Open questions #6): do **not** hand-edit the
generated block; the Live-verification step includes taking the post-install
dump and running `tools/lom_gaps.py <dump> --write`, which clears
`appointed_device`, `group_track` and the four `Song.View` rows. If that
regeneration cannot happen before the PR merges, the PR description says so
and the next dump picks it up.

(`CLOSING_THE_GAPS.md` row A-4 and the ROADMAP entry are removed at `/ship`
time, not here.)

## Testing (`tests_unit/`, the only gate)

`python3 -m pytest tests_unit/` — all Live-free. Handler code against real
LOM objects is *not* covered here, and `tests/` mutates a running Live on
import and is not part of the gate.

- **`test_track_identity.py`** (extend; direct calls, the existing FakeSong /
  FakeTrack style, fakes gaining `canonical_parent`, `devices`,
  `parameters`, `chains`, `mixer_device`, `group_track`):
  - `group_track_index`: ungrouped → `-1`; grouped → index; foreign group
    track → `ValueError`.
  - `owning_track_identity`: object parented under a regular / return /
    master track; ascent through Chain→Rack→Track; parentless object →
    `ValueError`; ascent cap terminates (self-parented fake) → `ValueError`.
  - `device_identity`: `None` → `("none", -1, -1)`; top-level device on each
    category; nested device → `(cat, ti, -1)`.
  - `parameter_identity`: `None` quad; top-level device parameter →
    full quad; mixer-volume fake (parent not in `devices`) →
    `(cat, ti, -1, -1)`; nested-device parameter → `(cat, ti, -1, -1)`.
  - `chain_identity`: `None` quad; chain of a top-level rack → full quad;
    chain of a nested rack → `(cat, ti, -1, chain_index)`.
  - `resolve_track` / `resolve_device`: happy path all three categories;
    rejects `"none"`, unknown category, negative index, out-of-range index,
    master with `index != 0` — each `ValueError`.
- **`test_track_callback.py` or a sibling** (dispatch through
  `load_track_module` + `server`/`receiver` fixtures): `get/group_track`
  single index (grouped and ungrouped fakes), `*` fan-out reply-per-track,
  float index normalisation, out-of-range → `/live/error`; and that
  `start_listen/group_track` is **not** registered.
- **clip_slot dispatch tests** (`load_clip_slot_module`): `get/clip` with
  clip present → `(t, c, c)`; empty → `(t, c, -1)`; float indices; bad index
  → `/live/error`; `start_listen/clip` not registered.
- **song.py / view.py glue is not unit-testable** (module-scope
  `import Live`) — exactly like the existing `selected_track_identity` glue.
  Everything those handlers do beyond one resolver call and one log line is
  registration, which Live verification covers. The `_start_listen`
  `getter=` machinery the appointed-device listener uses is already covered
  by `test_listener_alias.py`.

## Live verification

Precondition for every check: the installed Remote Scripts copy equals this
checkout **byte for byte** and Live has been restarted since it was copied
(files on disk are not code in memory). Note: at plan time the installed
copy is one commit behind (`track_callback.py` differs) — a full reinstall
is needed anyway. Method: `API.md` § "The no-probe variant" — fire-and-forget
UDP to 11000, evidence read from the installed `logs/abletonosc.log` (every
new handler logs its resolution; that is deliberate, Part rules #7). Wrap
every mutating check in `/live/song/begin_undo_step` / `end_undo_step` and
restore what you change.

1. **group_track**: in a set with a grouped track at index `i` inside a group
   at `g`: send `/live/track/get/group_track i` → log
   `group_track = g`; ungrouped track → `-1`; `* ` → one log line per track;
   index past the end → error log naming the address.
2. **clip**: `/live/clip_slot/get/clip t c` against a full and an empty slot
   → `c` and `-1` in the log.
3. **appointed_device get**: click a top-level device in Live's UI, send the
   getter → `("track", i, d)` matching the UI; click a return-track device →
   `("return_track", r, d)`; a master device → `("master", 0, d)`; a device
   *inside a rack* → `(cat, ti, -1)`; fresh set with no devices →
   `("none", -1, -1)`.
4. **appointed_device set**: `set/appointed_device "track" i d` → blue hand
   moves in the UI *and* read-back getter logs the same triple (every setter
   is fire-and-forget; the read-back is the proof). Then
   `set/appointed_device "track" -1 0` → structured error in the log,
   appointment unchanged (read-back again). Restore the original appointment
   by the same setter.
5. **appointed_device listen**: `start_listen/appointed_device` → immediate
   "Property appointed_device changed" push logged with the current triple;
   click a different device → second push; `stop_listen` → clicking produces
   no further pushes.
6. **selected_parameter**: click a device parameter in the UI → full quad in
   the log; click the track volume fader → `(cat, ti, -1, -1)` (this is the
   mixer-parameter ⚠️ check); nothing selected → none-quad.
7. **selected_chain**: select a rack chain → `(cat, ti, di, ci)` matching the
   UI; with a *drum* rack chain → record what `chain_index` resolves to
   (Open question #5); no rack in the set → none-quad.
8. **mod_mapping pair**: idle → none-shapes. If a macro-map gesture can be
   driven from the UI (rack "Map" mode), read both mid-gesture.
9. **Failure attribution**: any resolution failure on a *request* must
   appear as a structured `/live/error` log line naming the request address,
   not a silent no-reply. On a listener *push* the envelope does not apply
   (pattern rule 6): a failure there is a missing push plus a traceback in
   Live's Log.txt — check 5's pushes double as the evidence that the getter
   is not raising.

Remains uncovered after this: nothing in scope, except the drum-rack
`chain_index` semantics if no drum rack is to hand (documented as measured
or left ⚠️ in API.md accordingly).

Also at verification time: send `/live/application/dump_lom`, run
`tools/lom_gaps.py logs/lom_dump.json --write`, commit the regenerated
inventory (Part 7).

## Downstream

**Pin bump only.** Every address is new; no existing address, reply shape,
push, or error changes. Nothing in Seshat consumes these members today (the
generic loop never delivered them). When Seshat wants the new reads it adds
tool plumbing and, per its convention, `vendored_addresses_test` tripwires
for the nine new addresses — its call, on its side, at its pace.

## Out of scope

- **`/live/song/get/master_track`** — named in the roadmap Goal, deliberately
  not registered. The FORK_GAPS inventory already records `master_track` as
  *reached under `/live/master/*`* (it is not a gap row), and under the
  shipped identity convention the reply would be the constant
  `("master", 0)`: a permanent wire address that can only ever answer one
  value, which Seshat would then have to tripwire forever. The Goal's
  substance — the object-read pattern plus the readable members — is
  delivered without it. If a consumer ever needs the constant, it is a
  five-line follow-up.
- **Setters for `selected_chain` and `mod_mapping_device`** (LOM-rw): the
  Goal names get/set/listen only for `appointed_device`. They stay in the
  C-2 / D-1 buckets.
- **Listeners for the four `Song.View` members** (all observable): same
  reasoning; the `getter=` machinery makes them a cheap follow-up once a
  consumer names them.
- **Un-appointing** (`appointed_device = None` / `-1` as input): forbidden by
  the `-1` convention's second half. Not offered.
- **Chain/nested-device addressing** beyond the `-1` sentinel — that is A-1
  (path resolver), declined until a workflow needs it.
- **`ClipSlot.clip` beyond existence** — clip properties are `/live/clip/*`.

## Open questions

1. ⚠️ **`canonical_parent` ascent semantics.** Assumed:
   `Chain.canonical_parent` → owning rack device;
   `DeviceParameter.canonical_parent` → owning `Device` / `MixerDevice`;
   `Device.canonical_parent` → `Chain` or `Track`; ascent from any of the
   seven members terminates at a track within the cap. Could not be measured
   now: Live 12.4.3 was running during planning, but the permission layer
   blocked both the probe rig (writing the temporary handler into the
   installed copy) and even fire-and-forget UDP sends, so no measurement of
   any kind was possible this phase. The code is defensive regardless
   (bounded ascent, loud `ValueError` → `/live/error`); Live verification
   checks 3, 6, 7 decide it. If an implementer with send permission can run
   the probe rig first, fold the measurement into `API.md` beside the others,
   dated and version-stamped.
2. ⚠️ **Cross-class `==` on LOM wrappers.** The ascent compares devices,
   chains and parameters against tracks via `==` (through `identify_track`).
   Track-vs-track `==` is shipped and measured; cross-class is assumed to
   return `False` rather than raise. If it raises, the failure is a
   structured `/live/error` (attributable, not silent) and the fix is an
   `isinstance`-free guard in `owning_track_identity`; verification check 3
   exercises it on every category.
3. ⚠️ **Assigning a nested device to `appointed_device`.** The setter only
   *reaches* top-level devices, so the question does not gate this item; it
   matters only for A-1. Left unmeasured, noted in the API.md row.
4. ⚠️ **`mod_mapping_*` live values.** Docstrings (tier-1) say device is
   `None` when nothing waits for a mapping; the idle none-reply is safe
   regardless. What a mid-gesture read returns is confirmed at verification
   check 8, best-effort.
5. ⚠️ **Drum-rack chains.** Whether a `DrumChain` appears in the owning
   rack's `chains` (so `chain_index` resolves) or only under
   `drum_pads[*].chains` (so it answers `-1`). The reply is well-defined
   either way (`-1` falls out of the scan); which one is true gets measured
   at verification check 7 and written into the API.md row.
6. ⚠️ **FORK_GAPS inventory regeneration needs a post-install dump.** No
   `lom_dump.json` exists in the repo or the installed `logs/`, and a dump
   taken before the new code is installed cannot contain the new addresses —
   while this lifecycle run may not install into Live. Plan: ship the curated
   -section deletion in the code commit; take the dump and regenerate at the
   Live-verification step (post-install), or say so in the PR and let the
   next dump clear the rows. Recommendation: commit the dated dump json
   (e.g. `tools/lom_dump_<date>.json`) when it is finally taken, so future
   regenerations have a reproducible input.
7. ⚠️ **Does `ClipSlot` offer `add_clip_listener`?** Not answerable from the
   inventory (the `clip` row was alias-suppressed before the obs column was
   read). Scope is unaffected — no listen pair is planned — but if it is
   observable, a follow-up listen pair becomes possible and the API.md row
   should not claim impossibility, only absence.

