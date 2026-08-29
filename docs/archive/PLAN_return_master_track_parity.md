**Archived 2026-08-29 — shipped.** This is the plan as written *before*
implementation; the code as merged may differ. The change lives in
`abletonosc/return_track.py` (the module-scope `SCALAR_PROPERTIES` and
`ROUTING_PROPERTIES` tables, `_listen_to_track_property`, `_return_send`/
`_send_of`, `_insert_device_into` — fifty-eight new addresses) and one entry
added to `abletonosc/track.py`'s generic `methods` list for
`/live/track/insert_device`; `API.md` § "Return Track & Master: `Track`
parity" is the permanent record. Live verification's eight checks did not
run — the installed Remote Scripts copy was not this checkout (see the
dated Result under Live verification below) — so every ⚠️ marker in `API.md`
stands and all six Open questions below stay open for whoever verifies
against a running Live next. What remains of the return/master gap —
devices inside racks, input routing, listen pairs for the `has_*`
constants, send listen pairs, and the regular-track-shaped members that
don't apply — stays open in `FORK_GAPS.md`'s `Track` and `MixerDevice`
addressing-gap sections; no new roadmap item was needed since those
sections already carry it.

# Plan: Return / master `Track` parity (A-3)

**Status:** draft for review — no code written.
**Roadmap item:** "A-3 · Return / master `Track` parity" (current #1).
**Source:** `CLOSING_THE_GAPS.md` row A-3; FORK_GAPS "Track" and "MixerDevice"
addressing-gap sections.
**Branch:** `feat/return-master-track-parity`, cut from `feat/notes-extended`
(`cb75be37d6a5d90bc8eadee1e87b3e59a1d53123`) — this item stacks on the
unmerged PRs #18 and #19.

## Context

A return track and the master are `Live.Track.Track` objects, the same class
as every regular track, but the fork reaches them through a separate,
hand-written address family (`/live/return_track/*`, `/live/master/*` in
`abletonosc/return_track.py`) that was built for the mixer-and-devices
workflow and stopped there. Recounted from the code on 2026-08-29 (the
FORK_GAPS heading's "107 / 20 / 15" predates the fork's return/master work
and is stale): **regular tracks answer 108 addresses, returns 30, the master
21.** Missing on returns and master: colour, output routing, meters,
`has_*_input/output`, `insert_device`, sends on returns, and every listen
pair beyond `name`/`volume`/`panning`/`mute`/`solo` (returns) and
`volume`/`panning`/`cue_volume` (master). Every return/master feature
downstream trips over the difference — a return can be renamed and faded but
not coloured, metered, or re-routed.

Two constraints shape the whole design, both settled by shipped code:

1. **The `/live/return_track/*` and `/live/master/*` wire convention is the
   ok/error envelope, not upstream's raise-and-say-nothing.** Every indexed
   getter on these prefixes replies on its own address with
   `[index, "ok", value]` or `[index, "error", message]`, because the
   extension is optional and silence must keep meaning "not installed"
   (`API.md` § Return Track & Master API). New addresses on these prefixes
   must keep that envelope; registering them through `track.py`'s generic
   loops (which raise into `/live/error` and reply bare) would fork the
   contract *within* a prefix.
2. **The roadmap's "shared track resolver" is realised inside
   `return_track.py`, not as a cross-handler dispatch refactor.** The handler
   already owns the resolvers (`_return_track`, `_device_of`, …). What must
   not happen is sixty new hand-written methods — the new scalar surface is
   table-driven: one list of `(property, kind)` rows drives both the
   return-indexed and the master registrations through a small set of shared
   generic callbacks. Unifying with `/live/track/*` itself is the A-1-class
   dispatch refactor the roadmap's "Deliberately not planned" section
   declines.

Research that changed the obvious approach:

- **`insert_device` exists on the LOM with a known signature** —
  `insert_device((Track)arg1, (str)DeviceName [, (int)DeviceIndex=-1]) -> LomObject`
  (tier-1, FORK_GAPS generated inventory, Live 12.4.3; Live 12.3+ member).
  Regular tracks don't have an address for it either, so "parity" here means
  all three categories gain it together — see Part 5.
- **`has_*_input/output` are constants on returns and the master** (always
  audio-in/audio-out, never MIDI), so their listen pairs would subscribe to
  values that cannot change. Regular tracks only have those pairs because the
  generic loop registers pairs blindly. The plan ships the four getters but
  no listen pairs — "every `start_listen`" is delivered as *every scalar
  property whose value can change in Live*.
- **Returns and the master have no input section in Live's UI**, so input
  routing addresses are deliberately not offered (see Out of scope). Output
  routing is offered on both — a return routes to the master or elsewhere,
  the master to a hardware out.
- **The master may refuse members the class declares.** Reading
  `master_track.mute` raises `RuntimeError("Main track has no 'mute'
  property!")` (measured 2026-07-31) rather than returning falsy. Whether
  `color`/`color_index` behave the same on the master is unmeasured (⚠️ Open
  question 1), so every *new* master getter carries the ok/error envelope —
  a deliberate departure from the bare-value replies of
  `/live/master/get/volume` (which genuinely has no failure path). The
  envelope makes the address self-describing whichever way Live answers.
- **No measurement could be run in the planning session.** Live was running,
  but the session's permission layer blocked both the probe-handler write to
  the installed copy and even fire-and-forget UDP to port 11000. Every LOM
  behaviour question below is therefore ⚠️-flagged with a recommendation and
  a concrete Live-verification check, instead of measured and closed.

## Wire contract

All addresses below are **new**. No existing address, reply shape, or
listener push changes anywhere in this item. Existing addresses relied on:
`/live/return_track/get/count` (the caller's index guard),
`/live/return_track/delete_device` (the undo path for `insert_device`
verification), and the whole existing envelope convention.

Conventions carried over from the shipped return/master surface, restated
once so every table row below inherits them:

- Indexed getters reply `[echoed indices…, "ok", payload…]` or
  `[echoed indices…, "error", message]` on their own address; out-of-range
  indices are echoed verbatim, non-numeric ones echo as `-1`
  (`_echo_index` rule).
- Master getters (no index) reply `["ok", payload…]` / `["error", message]`
  — **new-address convention**; the shipped bare-value master getters
  (`volume`, `panning`, `cue_volume`, `devices`) are unchanged.
- Setters are silent on success and on argument/bounds errors (logged in
  Live — the `_set_name`/`_set_mute` precedent). An exception raised by the
  LOM write itself is **not** caught in the handler: it escapes to
  `OSCServer._dispatch` and arrives as a structured `/live/error`, exactly
  as the shipped setters behave (`track.name = …` is unguarded). New
  table-driven setters follow that split — guard the parse, let the
  assignment raise — so e.g. `set/color` on a master that refuses the
  member answers `/live/error`, not silence. Listen pairs are
  silent on a bad index; a push carries the bare value tuple (no envelope),
  distinguishable from a query reply by arity; each `start_listen` pushes
  once immediately; re-subscribing is idempotent; `stop_listen` of a
  never-started listener is silent.
- Boolean payloads are `0`/`1` (the `mute`/`solo` precedent). Flat lists
  carry `count` first.
- New getters log their value on the ok path (`logger.info`), like the base
  class's `_get_property` — this is what makes the no-probe Live
  verification below possible, since custom-handler ok paths currently log
  nothing.

### Return-track scalar surface (Part 2)

| Address | Request | Reply / behaviour |
|---|---|---|
| `/live/return_track/get/color` | `index` | `index, "ok", color` (int RGB, as `/live/track/get/color`) / error env |
| `/live/return_track/set/color` | `index, color` | silent |
| `/live/return_track/start_listen/color` | `index` | push `/live/return_track/get/color [index, color]` |
| `/live/return_track/stop_listen/color` | `index` | silent |
| `/live/return_track/get/color_index` | `index` | `index, "ok", color_index` / error env |
| `/live/return_track/set/color_index` | `index, color_index` | silent |
| `/live/return_track/start_listen/color_index` | `index` | push `[index, color_index]` |
| `/live/return_track/stop_listen/color_index` | `index` | silent |
| `/live/return_track/get/has_audio_input` | `index` | `index, "ok", 0\|1` / error env (no set, no listen — constant) |
| `/live/return_track/get/has_audio_output` | `index` | same |
| `/live/return_track/get/has_midi_input` | `index` | same |
| `/live/return_track/get/has_midi_output` | `index` | same |
| `/live/return_track/get/output_meter_level` | `index` | `index, "ok", level` (0.0–1.0) / error env |
| `/live/return_track/start_listen/output_meter_level` | `index` | push `[index, level]` |
| `/live/return_track/stop_listen/output_meter_level` | `index` | silent |
| `/live/return_track/get/output_meter_left` | `index` | as `output_meter_level` |
| `/live/return_track/start_listen/output_meter_left` | `index` | |
| `/live/return_track/stop_listen/output_meter_left` | `index` | |
| `/live/return_track/get/output_meter_right` | `index` | as `output_meter_level` |
| `/live/return_track/start_listen/output_meter_right` | `index` | |
| `/live/return_track/stop_listen/output_meter_right` | `index` | |

If reading a member raises (`RuntimeError` on a LOM object that refuses it),
the getter replies the error envelope with the exception text — never
silence, never a bare `None`.

### Master scalar surface (Part 2)

| Address | Request | Reply / behaviour |
|---|---|---|
| `/live/master/get/color` | | `"ok", color` / `"error", message` |
| `/live/master/set/color` | `color` | silent |
| `/live/master/start_listen/color` | | push `/live/master/get/color [color]` |
| `/live/master/stop_listen/color` | | silent |
| `/live/master/get/color_index` | | `"ok", color_index` / error env |
| `/live/master/set/color_index` | `color_index` | silent |
| `/live/master/start_listen/color_index` | | push `[color_index]` |
| `/live/master/stop_listen/color_index` | | silent |
| `/live/master/get/has_audio_input` | | `"ok", 0\|1` / error env |
| `/live/master/get/has_audio_output` | | same |
| `/live/master/get/has_midi_input` | | same |
| `/live/master/get/has_midi_output` | | same |
| `/live/master/get/output_meter_level` | | `"ok", level` / error env |
| `/live/master/start_listen/output_meter_level` | | push `[level]` |
| `/live/master/stop_listen/output_meter_level` | | silent |
| `/live/master/get/output_meter_left` (+ listen pair) | | as above |
| `/live/master/get/output_meter_right` (+ listen pair) | | as above |

### Output routing (Part 3)

Same name-based scheme as `/live/track/*` routing (see FORK_GAPS "Routing —
names, not objects" for the known shape limitation, which this item inherits
deliberately and does not fix). No listen pairs — parity: regular tracks
have none.

| Address | Request | Reply / behaviour |
|---|---|---|
| `/live/return_track/get/available_output_routing_types` | `index` | `index, "ok", count, name×count` / error env |
| `/live/return_track/get/available_output_routing_channels` | `index` | `index, "ok", count, name×count` / error env |
| `/live/return_track/get/output_routing_type` | `index` | `index, "ok", display_name` / error env |
| `/live/return_track/set/output_routing_type` | `index, name` | silent; unmatched name logged (track.py precedent) |
| `/live/return_track/get/output_routing_channel` | `index` | `index, "ok", display_name` / error env |
| `/live/return_track/set/output_routing_channel` | `index, name` | silent; unmatched name logged |
| `/live/master/get/available_output_routing_types` | | `"ok", count, name×count` / error env |
| `/live/master/get/available_output_routing_channels` | | `"ok", count, name×count` / error env |
| `/live/master/get/output_routing_type` | | `"ok", display_name` / error env |
| `/live/master/set/output_routing_type` | `name` | silent |
| `/live/master/get/output_routing_channel` | | `"ok", display_name` / error env |
| `/live/master/set/output_routing_channel` | `name` | silent |

### Sends on returns (Part 4)

Live 12 gives return tracks their own send section (return-to-return,
disabled by default per Live's feedback guard). `mixer_device.sends` on a
return is the LOM path, same as a regular track's.

| Address | Request | Reply / behaviour |
|---|---|---|
| `/live/return_track/get/send` | `index, send_id` | `index, send_id, "ok", value` / `index, send_id, "error", message` — `send_id` echoed by the `_echo_index` rule when the return lookup already failed; out-of-range `send_id` is an error envelope naming the real count |
| `/live/return_track/set/send` | `index, send_id, value` | silent |

No send listen pairs (parity — regular tracks have none, `API.md` documents
why) and no master form (the master has no sends; goal scopes sends to
returns).

### `insert_device` (Part 5)

| Address | Request | Reply / behaviour |
|---|---|---|
| `/live/return_track/insert_device` | `index, device_name[, position=-1]` | `index, "ok", device_index, count` / `index, "error", message` — `device_index` is the inserted device's position **re-read** from Live (`list(track.devices).index(returned)`), `count` the new chain length; a name Live rejects, or a pre-12.3 Live without the member, answers the error envelope |
| `/live/master/insert_device` | `device_name[, position=-1]` | `"ok", device_index, count` / `"error", message` |
| `/live/track/insert_device` | `track_id, device_name[, position]` | **regular-track counterpart**, one string added to `track.py`'s generic `methods` list: silent on success like every `/live/track/<method>`, failures arrive on `/live/error`, `*` fans out per the track-index wildcard contract. Deliberate small scope addition so the `Track.insert_device` inventory row closes for all three categories at once rather than leaving regular tracks the only ones unable to insert. **Ruled in scope at plan review (2026-08-29):** one string in a shipped, tested loop; silent-success matches every `/live/track/<method>`; the wildcard fan-out is the same mutating-wildcard class as `/live/track/delete_device`; and shipping it here removes `insert_device` from the C-4 bucket (see Part 6) instead of half-closing the member |

`insert_device` replies (rather than staying a silent method) for the same
reason `delete_device` does: it is a method with a real failure path, and
the caller's next act is addressing the device it just created.

## Numbered parts

Each part carries its documentation obligations; the item ships as one PR,
and if the implementer commits parts separately, every commit must leave
code and docs agreeing (the FORK_GAPS closure in Part 6 rides the same
commit as the last code part or a squash).

### Part 1 — test scaffolding for `return_track.py`

`return_track.py` has **no conftest loader and zero unit tests today**
(`tests_unit/conftest.py` docstring: "no loader yet, because nothing has
needed one"). This item needs one before any new address exists.

- `tests_unit/conftest.py`: add `load_return_track_module()` —
  `load_handler_module()` then `load_module("abletonosc.return_track")`.
  The module imports only `typing` and `.handler`, so the Component stub is
  sufficient; `self.song` is read only from callbacks, so the existing
  post-construction `handler.song = FakeSong(...)` pattern works (no
  `bind_song` needed). Update the module docstring's "eight of the twelve"
  enumeration and the "no loader yet" sentence.
- New `tests_unit/test_return_track.py`: local fakes (a `FakeReturnTrack`
  with scalar attributes, `add_/remove_<prop>_listener` recorders, a
  `mixer_device` carrying volume/panning DeviceParameter fakes and a `sends`
  list; a `FakeSong` with `return_tracks` and `master_track`), plus
  baseline tests pinning the *existing* contract before it grows:
  `get/count`, `get/name` ok and error envelopes, `_echo_index` behaviour,
  volume/panning listener key coexistence (`(index, "volume")` vs
  `(index, "panning")`), stop-silence, `_clear_listeners` leaves the fakes
  listener-free.
- Update the loader enumerations in the comment blocks of
  `tests_unit/test_handler_lifecycle.py` and
  `tests_unit/test_handler_subclass_contract.py` (both currently name
  `return_track.py` among the loaderless four). SESHAT.md **does** enumerate
  them too (verified at review): the § Merge hazards bullet on
  `AbletonOSCHandler.__init__` / `class_identifier` says the behavioural
  layer "constructs eight of the twelve production handlers today … but not
  `browser.py`, `midimap.py`, `return_track.py` or `song_structure.py`,
  which have no conftest loader" — update that sentence in the same commit.
- Docs: the SESHAT.md merge-hazards enumeration above. No API.md rows — no
  wire change in this part.

### Part 2 — table-driven scalar surface (colour, `has_*`, meters)

`abletonosc/return_track.py`:

- One module-level table of scalar rows, e.g.
  `(prop, readable, settable, listenable)`:
  `color` (rw, listen), `color_index` (rw, listen), four `has_*` (ro),
  three `output_meter_*` (ro, listen). One registration loop walks it twice
  — once for `/live/return_track/*` (index-keyed) and once for
  `/live/master/*` (index-less) — through four shared generic callbacks
  (return get/set, master get/set) built on `_return_track` and
  `self.song.master_track`. No per-property methods.
- Return listeners for plain `Track` properties reuse the base
  `_start_listen(track, prop, (index,))` exactly as `name`/`mute`/`solo`
  do (the base derives `/live/return_track/get/<prop>` from
  `class_identifier` and pushes `(index, value)`), stopped via
  `_stop_listen_if_present(prop, (index,))`.
- Master listeners for plain `Track` properties need a new hand-rolled
  helper — the base class would derive `/live/return_track/get/<prop>`, the
  wrong prefix. Add `_listen_to_track_property(track, prop, address,
  reply_prefix, listener_params)` as the plain-property sibling of the
  existing `_listen_to_mixer_param`: registers `add_<prop>_listener`, keys
  `(prop, ("master",))`, stores callback and object in the base bookkeeping
  dicts so the fixed `_stop_listen` and `_clear_listeners` work unchanged
  (no alias needed — the key's prop half *is* the LOM name, unlike the
  mixer params' forced `"value"`).
- Getters wrap the `getattr` in `try`/`except Exception` and answer the
  error envelope with the exception text — this is what turns an
  unmeasured master member (Open question 1) into a self-describing reply
  instead of a silent hole.
- Tests: dispatch every new address through the `dispatch` fixture — ok
  envelopes, error envelopes for bad/missing/non-numeric index, 0/1 boolean
  form, setter writes on the fake, listener key shapes
  (`("color", (0,))` vs `("color", ("master",))` coexist; a return's
  `color` listener does not evict its `volume` listener), immediate first
  push, idempotent re-subscribe, silent stop of a never-started listener,
  master getter error envelope when the fake raises `RuntimeError`.
- Docs in this part: API.md rows for all Part-2 addresses (new subsection
  under Return Track & Master API), the "fifty-one addresses" count
  language updated once for the whole item, and the note explaining the
  master-envelope departure; SESHAT.md additions entry for
  `return_track.py` extended with the new surface and the
  master-envelope/no-`has_*`-listen decisions.

### Part 3 — output routing on returns and master

- Same table-driven mechanism, two more shared callbacks for the
  object-list routing members (they cannot ride the scalar getters:
  the value is `routing.display_name` and the setter resolves a name
  against `available_output_routing_types` — port `track.py`'s resolve-by-
  display-name loop, warn-and-return on no match).
- Tests: name-list replies carry `count` first; set resolves the right
  object onto the fake; unmatched name leaves the fake unchanged (and the
  handler silent); master forms.
- Docs: API.md rows; SESHAT.md entry paragraph; explicitly inherit the
  "Routing — names, not objects" shape gap in FORK_GAPS (no change to that
  section — it already describes the limitation class-wide).

### Part 4 — sends on returns

- `get/send` / `set/send` via `_return_track` plus a bounds-checked send
  lookup mirroring `_parameter_of` (error message names the real send
  count). Values through `mixer_device.sends[send_id].value`.
- Tests: ok/error envelopes, echo rule with a failed return lookup, set
  writes the fake DeviceParameter.
- Docs: API.md rows (and a pointer from the Track API's send section noting
  return sends now exist); SESHAT.md; FORK_GAPS "MixerDevice" addressing-gap
  section edited — `sends` is no longer reachable "only via `Track`".

### Part 5 — `insert_device`

- Return and master forms as specified in the wire contract; implemented
  with `try`/`except` around the LOM call so an unknown device name, or a
  Live without the 12.3 member, answers the error envelope. Inserted index
  re-read from `track.devices`.
- `track.py`: append `"insert_device"` to the generic `methods` list — one
  string; the existing loop and `create_track_callback` provide dispatch,
  wildcard fan-out, and `/live/error` on failure. (Flagged droppable.)
- Tests: return/master forms against fakes whose `insert_device` records
  args and returns a fake device (reply carries the re-read index and
  count); fake raising → error envelope; `/live/track/insert_device`
  dispatches through the methods loop with `(name,)` and `(name, position)`.
- Docs: API.md rows in both the Track Methods table and the return/master
  section, each carrying the ⚠️ that `DeviceName` semantics are unmeasured
  (Open question 4) until the Live verification below replaces the ⚠️ with
  the measured contract; SESHAT.md.

### Part 6 — documentation closure and recount

- FORK_GAPS "Track" addressing-gap section: rewrite the heading and body
  with the recounted figures — **pre-change 108 / 30 / 21** (measured from
  the registered tables, 2026-08-29), post-change **109 / 60 / 49** — and
  shrink the "missing" list to what actually remains (see Out of scope);
  delete the stale-count warning paragraph. "MixerDevice" section updated
  per Part 4. Dispositions row "Return/master mixer and device addressing"
  pointer refreshed.
- FORK_GAPS "Closed" entry dated for this item, listing the members closed
  (`Track.color`, `color_index`, `has_audio_input`, `has_audio_output`,
  `has_midi_input`, `has_midi_output`, `output_meter_level/left/right`,
  `output_routing_*` reachability on returns/master, `insert_device`,
  `MixerDevice.sends` on returns) with the standard note that the generated
  inventory is regenerated only from a `/live/application/dump_lom` taken
  against an installed copy running this code, and no such dump has been
  taken yet (the A-4 precedent).
- `CLOSING_THE_GAPS.md` **C-4** ("`Track` remainder") row: strike
  `insert_device` from its member list in the same commit that ships
  Part 5. `/ship` removes only the A-3 row; leaving `insert_device` listed
  in C-4 would silently re-queue a shipped member for a future planner.
- ROADMAP.md is **not** edited here beyond the existing Plan link —
  `/ship` removes the entry and the `CLOSING_THE_GAPS.md` A-3 row. (The
  FORK_GAPS Track heading rename in this part breaks the A-3 row's anchor
  link, but that row is deleted at ship in the same PR; no other file
  references the anchor — verified at review.)

## Testing

- Everything above runs Live-free through `tests_unit/` and
  `conftest.py`'s `dispatch` fixture: registration, dispatch, envelope
  shapes, error paths, setter writes, listener bookkeeping (key shapes,
  eviction-independence, idempotent re-subscribe, `_clear_listeners`).
  `python3 -m pytest tests_unit/` is the only gate.
- Not covered there, by construction: handler code against real LOM objects
  — whether the master accepts `color`, what `insert_device` does with a
  name, real routing display names, meter values. Those are the Live
  verification's job.
- `tests/` (the live suite) mutates a running Live when opted in and is not
  part of the gate; no changes to it in this item.

## Live verification

Precondition for every check: the installed Remote Scripts copy equals this
checkout byte for byte **and Live has been restarted since it was copied**.
Note the stacking: this branch includes the unmerged PR #18/#19 work, so
installing it verifies those too. Method: fire-and-forget UDP to
`127.0.0.1:11000`, evidence read from the installed
`logs/abletonosc.log` (`API.md` § "The no-probe variant" — reply datagrams
land on Seshat's 11001 and cannot be captured). New getters log their ok
path, so values are readable from the log. Wrap the mutating checks in
`/live/song/begin_undo_step` / `end_undo_step` and restore explicitly —
do not rely on undo (roadmap item on the undo step count).

1. **Registration probe:** `/live/return_track/get/color 99` → log line
   "Return track 99 does not exist — this set has N return track(s)".
2. **Colour on a return:** `get/color 0` → logged int; compare against the
   return's colour in Live's UI. `set/color 0 <other>` then `get/color 0`
   → new value logged and visible in the UI; set the original back.
3. **Colour on the master (decides Open question 1):** `get/color` → either
   a logged value (member exists → replace the ⚠️ in API.md with the
   measured fact) or an error envelope logging the `RuntimeError` text
   (member absent → record it beside the mute/solo paragraph and decide
   whether to withdraw the four master colour addresses before merge, the
   "simply not offered" precedent). Then `set/color <value>`: on a refusing
   master the unguarded write must arrive as a structured `/live/error`
   naming the request, not as silence — added at implementation, since the
   setter half of the same decision is what tells a caller the address is
   unusable rather than merely quiet.
4. **`has_*` on return 0 and master:** four gets each → expect
   `1,1,0,0` (audio in/out yes, MIDI no); record.
5. **Meters:** with the set playing audio through a return,
   `get/output_meter_level 0` → nonzero logged; `start_listen/...` → base
   listener log lines and "Property output_meter_level changed" entries;
   `stop_listen` ends them. Master forms likewise. (Meter pushes are
   high-rate — note in API.md what a subscriber signs up for.)
6. **Routing reads:** `get/available_output_routing_types 0` and the master
   form → logged display names; compare with the output choosers in the UI
   (decides Open question 3). `set/output_routing_type` round-trip on a
   return with a second routing available, restored afterwards.
7. **Sends on returns (decides Open question 5):** `get/send 0 0` → logged
   value; `set/send 0 0 0.3`, re-read, restore. Record whether a disabled
   send accepts and reports the value, and whether `len(sends)` matches the
   return count (bad-index error message names the count).
8. **`insert_device` (decides Open question 4):**
   `/live/return_track/insert_device 0 "Reverb"` inside an undo step →
   ok reply logged with index and count, device visible in the UI; remove
   it with `/live/return_track/delete_device 0 <index>`; try a nonsense
   name → error envelope logged. Repeat once on the master, and once via
   `/live/track/insert_device 0 "Reverb"` (evidence: `_call_method` log
   line, device in UI, then `delete_device`). Record which name forms Live
   accepts in API.md.

### Result, 2026-08-29 (PR review)

**All eight checks above: skipped by environment.** The precondition fails —
the installed Remote Scripts copy is *not* this checkout:

    diff -rq --exclude=__pycache__ abletonosc \
      "$HOME/Music/Ableton/User Library/Remote Scripts/AbletonOSC/abletonosc"

reports `application.py`, `clip.py`, `device.py`, `return_track.py`,
`track.py` and `track_identity.py` as differing. Live is running (pid 78577),
but it is running a build that predates this branch *and* the two branches it
stacks on, so every address under test is absent from it: a query would time
out for the trivial reason, and a log line would prove nothing about this
code. Installing the copy and restarting Live are both out of bounds for the
review, so no check was approximated and no result is recorded for any of
them. Every ⚠️ this item carries into `API.md` therefore stands unmeasured,
and checks 1-8 remain owed against an installed, restarted Live.

Remains uncovered even after these: listener pushes as *datagrams* (11001 is
unobservable from this side — log lines are the evidence), and
`insert_device` against a pre-12.3 Live (no such Live available here).

## Downstream

**Pin bump only.** Every address in this item is new; no existing address,
reply shape, or push changes. Seshat decodes nothing differently until it
chooses to consume the new surface (likely first consumers: return colour in
the mirror, master/return meters, `insert_device` behind a device-loading
tool). `vendored_addresses_test` gains tripwires only when Seshat's `lib/`
actually sends the new addresses — nothing to add on the bump itself. One
caveat for a wildcard consumer specifically: `/live/return_track/get/*` now
matches 24 endpoints (was 7), `/live/master/get/*` 20 (was 4), and
`/live/track/*` also now matches `insert_device`; so any Seshat code that
sends a `get/*` or `track/*` pattern and counts or exhaustively matches
replies will see more datagrams after the bump even though no existing
address's shape changed.

## Out of scope

- **Input routing on returns/master** — no input section exists in Live's
  UI for either; addresses deliberately not offered. Reopens if the Live
  verification's routing checks show the LOM disagrees.
- **`mute`/`solo`/`arm` on the master, `arm` on returns** — measured absent
  (2026-07-31); stays as documented.
- **Listen pairs for `has_*`** — constants on returns/master; decision
  recorded in API.md/SESHAT.md rather than shipped as dead wire surface.
- **Send listen pairs** (returns) — parity with regular tracks, which have
  none; the existing API.md rationale covers it.
- **Other `Track` members regular tracks expose** (`is_visible`,
  `is_grouped`, `is_foldable`, `fold_state`, `can_be_armed`,
  `current_monitoring_state`, `fired_slot_index`, `playing_slot_index`,
  clip addresses, `stop_all_clips`, `devices/can_have_chains` split
  getters) — not in the A-3 goal; clip-family members don't apply to
  returns at all. Stays in the FORK_GAPS Track section's residual list.
- **`MixerDevice` members beyond `sends`** (`crossfade_assign`,
  `panning_mode`, `track_activator`, `crossfader`, `song_tempo`,
  split-stereo) — stays the MixerDevice gap row.
- **Device listeners on return/master devices** — existing recorded
  decision in `return_track.py`'s header; unchanged.
- **Routing-by-object identity** (the "names, not objects" shape gap) —
  inherited deliberately; stays a FORK_GAPS shape gap.
- **The generated-inventory regeneration** — requires a `dump_lom` against
  an installed copy running this code; the Closed entry carries the
  standard deferral note (A-4/B-1 precedent).

## Open questions

1. **Does the master track have `color`/`color_index`?** Unknown — the
   mute/solo precedent shows the Main track refuses some class members with
   `RuntimeError`, and the planning session could not measure (probe write
   and UDP both blocked by the session's permission layer). *Assumed
   meanwhile:* readable; the new-master-getter envelope answers truthfully
   either way, so the addresses ship regardless and Live verification
   check 3 decides whether they stay, with the "simply not offered"
   withdrawal as the alternative if the member is absent.
2. **Are `output_meter_*` and `color` observable on return/master
   instances** (i.e. do `add_<prop>_listener` calls succeed)? Class-level
   evidence says yes (the M4L exposure table and the fork's own regular
   track listen pairs); instance behaviour unmeasured. *Assumed:* they
   bind; a failure surfaces as `/live/error` from `start_listen` (an
   `AttributeError` escapes the handler), which check 5 would catch.
3. **Do `available_output_routing_types/channels` work on returns and the
   master?** The UI has output choosers on both, so almost certainly, but
   unmeasured on these instances. *Assumed:* they work; error envelope
   self-describes if not; check 6 decides.
4. **`insert_device` name semantics** — which `DeviceName` strings resolve
   (Live-native English device names? browser item names?), what a rejected
   name raises, and behaviour of `DeviceIndex` clamping. Signature is
   tier-1; semantics are not. *Assumed:* native device display names
   ("Reverb"), unknown names raise and arrive as the error envelope;
   check 8 measures and API.md records.
5. **Sends on returns:** is `len(mixer_device.sends)` the full return
   count (including the return's own index), and does a *disabled* send
   accept a value write? *Assumed:* full count, value writes accepted but
   inaudible until the user enables the send — check 7 measures; API.md
   documents whatever is found, including the feedback-guard caveat.
6. **`/live/track/insert_device` interaction with the `*` wildcard and
   `_is_wildcard_skip`** — a fan-out that fails mid-way on one track
   suppresses the endpoint's replies (documented composition hazard);
   methods return nothing, so the practical impact is one `/live/error`
   naming the failing track, same as any method. *Assumed:* no special
   handling needed; the unit test asserts the method-loop dispatch only.
