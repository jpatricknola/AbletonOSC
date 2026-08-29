# Plan: `Song` remainder (C-1)

Roadmap item: **#1 · C-1 · `Song` remainder** — from `CLOSING_THE_GAPS.md`
row C-1, closing 25 `Live.Song.Song` rows of the generated inventory in
`FORK_GAPS.md` (the C-1 row lists 24 items; `get_beats_loop_start/length`
count as two members). No § Curated entry in FORK_GAPS cites these members —
the row and the inventory are the whole source — though a § Dispositions row
and an § "Already in the fork" row mention some of them and are updated by
Part 3.3. Planned 2026-08-29.

## Context

`abletonosc/song.py` exposes most of the `Song` class — transport, tempo,
loop, quantization, undo, the fork's `appointed_device` trio — but the
2026-08-27 audit confirmed that none of the 25 members in the C-1 bucket is
registered: not in the generic `properties_rw` / `properties_r` lists, not
in the methods list, not hand-written. The bucket is the long tail of
scalar `Song` state a client currently cannot see or set at all:

- **Recording/automation state** — `session_automation_record` (rw),
  `re_enable_automation_enabled` (ro), `overdub` (rw, the legacy Live 8
  hook), `can_capture_midi` (ro), `count_in_duration` (ro),
  `is_counting_in` (ro). Today a client that wants to know "is Live
  counting in right now" or "is the automation-override arrow lit" has
  no address for either.
- **Scale and Link** — `scale_mode` (rw), `scale_intervals` (ro),
  `is_ableton_link_start_stop_sync_enabled` (rw). The neighbouring
  members `root_note`, `scale_name`, `is_ableton_link_enabled` and
  `clip_trigger_quantization` already exist (`song.py`, upstream lists)
  and are **not** part of this item — the roadmap entry pins that
  boundary explicitly.
- **Set identity and time** — `file_path` (ro), `start_time` (rw),
  `last_event_time` (ro), plus the two `BeatTime`-returning loop queries
  (`get_beats_loop_start`, `get_beats_loop_length`) and the SMPTE clock
  (`get_current_smpte_song_time`).
- **Preferences the mixer behaviour depends on** — `exclusive_arm` (ro),
  `exclusive_solo` (ro), `select_on_launch` (ro).
- **Track visibility** — `visible_tracks` (ro, observable): the set of
  regular tracks not hidden inside a collapsed group. `num_tracks` /
  `track_names` iterate `song.tracks` and cannot answer "which of these
  is on screen".
- **Methods** — `play_selection`, `scrub_by`, `sync_parameter_changes`
  (argument-less/scalar-argument, fire-and-forget) and the two
  device-position methods `move_device` / `find_device_position`, which
  take a Device and a target LomObject and are the only two members in
  the bucket that need the A-4 object resolvers rather than the generic
  loops.

Why now: it is the top roadmap item, billed as a cheap generic-loop batch,
and everything it needs has already shipped — the generic loops, the
structured `/live/error` envelope, and (for the two device-position
methods) `track_identity.py`'s `resolve_track` / `resolve_device`.

Three constraints research surfaced, which shape the plan:

1. **Not everything in the bucket fits the generic loop.**
   `scale_intervals` is a vector of ints (unencodable as a single OSC
   argument — the same reason `Application.unavailable_features` got a
   hand-written flattening read in C-3), `visible_tracks` is an object
   list (FORK_GAPS' own curated note: objects and collections never
   enter the generic property loop), the three `get_*` methods return
   Boost structs (`BeatTime`, `SmpteTime`) that `_call_method` would
   discard, and `move_device` / `find_device_position` take LOM objects
   as arguments. Eleven of the 25 members therefore get fork-owned
   registrations outside the two upstream property loops (the four
   get-only members of constraint 2 among them); the other fourteen ride
   the loops — six rw, five observable ro, three fire-and-forget methods.
2. **Four members are not observable** (`exclusive_solo`, `file_path`,
   `last_event_time`, `select_on_launch` — no `add_<name>_listener` per
   the inventory's `obs` column). Registering them through the existing
   `properties_r` list would manufacture `start_listen` addresses that
   can only ever answer `/live/error AttributeError`. C-3 set the
   precedent (`application.py`'s split `properties_r` /
   `properties_listen`): they get get-only registrations, and API.md
   says so.
3. **The fork-owned entries must stay contiguous.** `song.py`'s lists are
   upstream's, already carrying three single-string fork entries
   (`begin_undo_step`, `end_undo_step`, `swing_amount`) that SESHAT.md's
   merge-hazards section names one by one because a merge drops them
   without a conflict. Interleaving ~15 more strings into upstream's
   lists multiplies that hazard; appending them as clearly-commented
   fork-owned blocks (`properties_rw = properties_rw + [...]` after the
   upstream lists, a second small methods loop after the upstream one)
   keeps the divergence to a few contiguous blocks a conflict resolver
   can see whole — the same reasoning that kept `appointed_device` and
   device.py's B-2 block out of the loops.

**Deliberately excluded, already settled:** `get_data` / `set_data` and
`tuning_system` are D-5's, `groove_pool` is D-2's, `can_jump_to_next_cue` /
`can_jump_to_prev_cue` / `is_cue_point_selected` are B-3's, `Song.View`
members are C-2's, and chain targets for `move_device` are A-1/D-1
territory (declined until a workflow needs racks). None is revisited here.

## Wire contract

Every address below is **new** and lives under `/live/song/`. All are
Seshat fork additions — none exists in stock AbletonOSC — and every
failure arrives as the structured
`/live/error ("request", address, detail, argc, *args)` envelope from
`OSCServer._dispatch`. Setters are silent on success, like every generic
setter in this fork.

### New — generic-loop scalars, read/write (get + set + listen)

Via the existing registration loops, from a fork-owned appended block in
`properties_rw`. For each `<prop>`: `/live/song/get/<prop>` replies
`(<value>,)`; `/live/song/set/<prop> <value>` is silent;
`/live/song/start_listen/<prop>` / `stop_listen/<prop>` push
`(<value>,)` on `/live/song/get/<prop>` (immediate initial push, as
`_start_listen` always does). All six are observable per the inventory.

| Property | Type | Notes |
|---|---|---|
| `is_ableton_link_start_stop_sync_enabled` | bool | Link Start/Stop Sync; distinct from the existing `is_ableton_link_enabled` |
| `overdub` | bool | Legacy Live 8 overdub hook; ⚠️ the apiref docstring is truncated ("Now hooks to…") — assumed to mirror session-record state, unmeasured |
| `scale_mode` | bool | Scale highlighting/editing mode; pairs with existing `root_note` / `scale_name` |
| `session_automation_record` | bool | The Automation Arm button |
| `start_time` | float (beats) | ⚠️ set-quantization semantics truncated in the apiref, unmeasured |
| `tempo_follower_enabled` | bool | No effect unless the Tempo Follower toggle is enabled in Live's preferences (per the docstring) |

### New — generic-loop scalars, read-only + listen (get + listen, no set)

Via a fork-owned appended block in `properties_r`. Same get/listen shapes
as above; no `set` address exists.

| Property | Type | Notes |
|---|---|---|
| `can_capture_midi` | bool | Material available for Capture MIDI on any track |
| `count_in_duration` | int | Index into the count-in preference table. ⚠️ Mapping assumed 0=None, 1=1 Bar, 2=2 Bars, 3=4 Bars (M4L docs; Push2's `transport_state.pyc` indexes a `COUNT_IN_DURATION_IN_BARS` table with it) — unmeasured |
| `exclusive_arm` | bool | The Exclusive Arm preference (note: observable; `exclusive_solo` is not, per the inventory) |
| `is_counting_in` | bool | True while the count-in runs |
| `re_enable_automation_enabled` | bool | True when some automated parameter is overridden (the Re-Enable Automation button is lit) |

### New — get-only reads (no listen pair, no set)

Registered by a separate get-only loop (C-3's `properties_listen`
precedent, inverted): these four have no `add_<name>_listener`, so no
`start_listen`/`stop_listen` address is registered at all — a
`start_listen` send logs `Unknown OSC address` and nothing answers, rather
than manufacturing an AttributeError reply.

| Address | Reply | Notes |
|---|---|---|
| `/live/song/get/exclusive_solo` | `(bool,)` | Exclusive Solo preference |
| `/live/song/get/file_path` | `(string,)` | The set's path on disk. ⚠️ Value for a never-saved set unmeasured (assumed empty string; if reading raises `RuntimeError`, `_get_property` answers `(None,)` by its existing catch) |
| `/live/song/get/last_event_time` | `(float,)` | Beat time of the last event in the song |
| `/live/song/get/select_on_launch` | `(bool,)` | Select-on-launch preference |

### New — hand-written reads

- `/live/song/get/scale_intervals` → variable-arity tuple of ints, the
  current scale's intervals in halfsteps from the root (Major →
  `0 2 4 5 7 9 11`). Flattened with no count prefix, like
  `/live/application/get/unavailable_features`. Observable:
  `/live/song/start_listen/scale_intervals` / `stop_listen` push the same
  tuple on `/live/song/get/scale_intervals` via `_start_listen`'s
  `getter=` hook (the `appointed_device` pattern — the push must carry
  the flattened ints, not the raw vector).
- `/live/song/get/visible_tracks` → variable-arity tuple of ints: the
  indices (into `song.tracks`, the same index space as `num_tracks` /
  `track_names`) of every visible regular track, in track order.
  Observable, same `getter=` listen pattern as `scale_intervals`.
- `/live/song/get/num_visible_tracks` → `(int,)`, the count — the
  `num_tracks` companion. (Covers the member under the lom_gaps
  matcher's `num_X` rule as well; no listen pair, read it or listen on
  `visible_tracks` instead.)

### New — methods, fire-and-forget (no reply)

Via a second, fork-owned methods loop after upstream's. Same contract as
every `/live/song/<method>` row: silent on success, structured
`/live/error` on failure.

| Address | Args | Notes |
|---|---|---|
| `/live/song/play_selection` | | Play the current arrangement selection |
| `/live/song/scrub_by` | `delta` (float, beats) | Scrub the playhead by a beat delta |
| `/live/song/sync_parameter_changes` | | ⚠️ Remote-Script-only, absent from M4L's table, docstring is signature-only — behaviour unknown; registered as-is because the row lists it, flagged in API.md |

### New — method queries (methods with a reply)

Hand-written, because `_call_method` discards return values and these
return Boost structs. Address = the LOM method name verbatim (so the
inventory matcher counts the member covered), placed as a query row with
request and reply:

- `/live/song/get_beats_loop_start` (no args) →
  `(bars, beats, sub_division, ticks)`, four ints decoded off the
  returned `BeatTime`.
- `/live/song/get_beats_loop_length` (no args) → same shape.
- `/live/song/get_current_smpte_song_time <format:int>` →
  `(format, hours, minutes, seconds, frames)` — the format echoed first
  for correlation (the `has_option` precedent), then the four fields off
  the returned `SmpteTime`. `format` is passed to Live unmodified as the
  `Live.Song.TimeFormat` int the Boost signature declares.
  ⚠️ Attribute names on both structs are apiref/M4L-derived, not
  measured: `bars`/`beats`/`sub_division` appear as attribute names in
  Live 12.4.3's shipped `Blackstar_Live_Logic`/`Akai_Force_MPC` scripts,
  `ticks` and the four SMPTE names do not — a wrong name raises
  `AttributeError` and arrives loudly on `/live/error`, never as a wrong
  value. ⚠️ The TimeFormat int mapping is unmeasured; API.md documents
  the argument as pass-through with the M4L member names listed as the
  best available reference.

### New — device-position methods (object-argument, resolver-validated)

Both take a device triple and a track pair, in the A-4 identity
convention (`category` ∈ `"track"`, `"return_track"`, `"master"`), and
both reply. Track-level targets only: a chain target has no address in
this fork until A-1, exactly as `resolve_device` reaches top-level
devices only. Every argument is validated by `resolve_device` /
`resolve_track` — `"none"`, an unknown category, or an out-of-range index
is a `ValueError` on `/live/error`, never a Python negative-index
wrap-around.

- `/live/song/move_device
  <device_category> <device_track_index> <device_index>
  <target_category> <target_track_index> <position:int>`
  → calls `song.move_device(device, target_track, position)` and replies
  `(target_category, target_track_index, result)` where `result` is the
  int Live returns — ⚠️ assumed to be the device's resulting index in the
  target's `devices` list (M4L docs), unmeasured.
- `/live/song/find_device_position` — same six arguments, same reply
  shape; calls `song.find_device_position(...)`. ⚠️ Assumed
  non-mutating ("where would it land"), unmeasured; API.md carries the
  flag until a Live pass confirms.

### Changed

Nothing. No existing address, argument list, or reply shape changes.

### Unchanged but relied on

- `OSCServer._dispatch`'s reply-type validation and structured
  `/live/error` envelope (all new error behaviour above rides it).
- `_get_property` / `_set_property` / `_start_listen` / `_stop_listen`
  including the `getter=` hook (SESHAT.md § merge hazards names them).
- `track_identity.resolve_track` / `resolve_device` and their
  "-1 is an answer, never an argument" validation contract.
- The existing `/live/song/get/root_note`, `scale_name`,
  `is_ableton_link_enabled`, `clip_trigger_quantization` rows —
  neighbours this item must not touch.

## Numbered parts

### Part 1 — `abletonosc/song.py`: the addresses

Files: `abletonosc/song.py`.

1. After upstream's `properties_rw` / `properties_r` list literals and
   before the registration loops, append the fork-owned blocks under a
   Seshat-extension comment that names this plan and the merge hazard
   (contiguous block, do not interleave with upstream's strings):
   `properties_rw = properties_rw + [` the six rw members `]`,
   `properties_r = properties_r + [` the five observable ro members `]`.
2. After the existing property loops, a get-only loop over the four
   non-observable members (`exclusive_solo`, `file_path`,
   `last_event_time`, `select_on_launch`) registering
   `/live/song/get/<prop>` via `partial(self._get_property, ...)` only,
   with a comment stating why there is no listen pair (C-3 precedent).
3. Hand-written `scale_intervals`: getter flattening to
   `tuple(int(i) for i in self.song.scale_intervals)`, registered for
   `get` and, with `getter=`, for `start_listen`/`stop_listen`
   (the `appointed_device` registration shape).
4. Hand-written `visible_tracks` + `num_visible_tracks`: a resolver that
   walks `enumerate(self.song.tracks)` once and collects the indices of
   tracks present in `song.visible_tracks` (identity comparison against
   the visible list, order-preserving single pass — not
   `list.index` per element); `get`, `get` for the count, and the
   `getter=` listen pair on `visible_tracks`.
5. A second methods loop for `play_selection`, `scrub_by`,
   `sync_parameter_changes` (fork-owned block, same
   `partial(self._call_method, ...)` shape as upstream's loop).
6. Hand-written `get_beats_loop_start` / `get_beats_loop_length` /
   `get_current_smpte_song_time` returning the decoded tuples specified
   above; SMPTE takes `int(params[0])` (IndexError on no-args is the
   deliberate error path, as `has_option` documents).
7. Hand-written `move_device` / `find_device_position` using
   `resolve_device` + `resolve_track`, coercing
   `str/int/int/str/int/int` exactly as `song_set_appointed_device`
   coerces its triple, logging the resolution at info level, replying
   the three-field echo+result tuple.
8. Every hand-written handler logs at info level (the log file is the
   only evidence channel when Seshat holds the reply port).

### Part 2 — `tests_unit/test_song_remainder.py`: coverage

Files: `tests_unit/test_song_remainder.py` (new; no `conftest.py` changes
expected — `load_song_module`, `bind_song`, `dispatch`, `receiver`,
`server` already exist and `test_song_object_reads.py` is the template).

Cover, all Live-free through the `dispatch` fixture against a `FakeSong`:

1. Parametrized get/reply for every new scalar (fake attribute in, one
   correctly-typed reply datagram out on the same address).
2. Parametrized set for the six rw members (attribute written, nothing
   sent).
3. Listener bookkeeping for at least one rw member and one ro member:
   `start_listen` subscribes (`add_<name>_listener` called, immediate
   push), `stop_listen` unsubscribes; `FakeSong` grows the
   add/remove listener pairs the way `test_song_object_reads.py`'s fake
   does for `appointed_device`.
4. The four no-listen members: `get` answers; the
   `start_listen`/`stop_listen` addresses are absent from
   `server._callbacks` (no manufactured error path).
5. `scale_intervals`: vector-ish fake (a plain list) → flattened int
   tuple reply; listen push carries the flattened tuple, not the list.
6. `visible_tracks`: fake `tracks` of four with a two-element
   `visible_tracks` subset (shared object identity) → index tuple reply,
   `num_visible_tracks` count; a group-collapse-shaped change (subset
   swap) pushed through the listener getter.
7. The three fire-and-forget methods: method called with coerced args,
   nothing sent; `scrub_by` passes the float through.
8. `get_beats_loop_*`: fake `BeatTime` with the four attributes → four-int
   reply. `get_current_smpte_song_time`: fake method recording its int
   argument, fake `SmpteTime` → five-field echo reply; no-args →
   structured `/live/error`.
9. `move_device` / `find_device_position`: happy path (resolved device
   and track objects handed to the fake method, reply carries the fake's
   return int); validation failures (`"none"` category, out-of-range
   index, master index ≠ 0) each answer `/live/error` and call nothing.
10. Reply-shape discipline: every reply asserted as a tuple datagram on
    the request address (the `_dispatch` contract).

State explicitly in the module docstring: fakes prove the glue, not the
LOM — whether real Boost vectors/structs behave like these fakes is the
Live-verification section's job, and `tests/` (which mutates a running
Live) is not part of the gate.

### Part 3 — documentation, same commit as Parts 1–2

Files: `API.md`, `SESHAT.md`, `FORK_GAPS.md`.

1. **API.md** — in § Song API: the six setter rows, the eleven getter
   rows (marking which have no listen pair and which are Seshat
   extensions — every row here is one), `scale_intervals` /
   `visible_tracks` / `num_visible_tracks` with their variable-arity
   notes, the three fire-and-forget method rows in the Song Methods
   table (with the ⚠️ Seshat-fork marker the `begin_undo_step` rows use),
   and a new query table for the five reply-carrying methods
   (`get_beats_loop_start`, `get_beats_loop_length`,
   `get_current_smpte_song_time`, `move_device`,
   `find_device_position`) with request/reply columns and the ⚠️ flags
   from the wire contract above (struct attribute names, TimeFormat
   mapping, count_in mapping, move/find return semantics) recorded
   beside the rows they qualify.
2. **SESHAT.md** — one new entry under "Additions to upstream's code"
   describing the C-1 block (the appended lists, the get-only loop, the
   hand-written handlers, and why the blocks are contiguous), and an
   update to the merge-hazard bullet "Anything touching `song.py`'s
   generic methods list or `properties_rw`" (currently "Three entries
   there are ours — `begin_undo_step`, `end_undo_step` and
   `swing_amount`") so it also covers `properties_r` and names the
   appended fork blocks and loops — a merge that takes upstream's
   `song.py` lists wholesale now drops the whole batch without a
   conflict, and `tests_unit/test_song_remainder.py` is the tripwire.
3. **FORK_GAPS.md** — three edits. (There is no standalone staleness
   note above the generated inventory; the C-3 staleness paragraph sits
   at the end of its § Closed subsection, and each closed item carries
   its own.)
   - Add a § Closed subsection (`### \`Song\` remainder — closed <date>`)
     after the five existing ones, naming the 25 `Live.Song.Song`
     members this item closes and ending with the standard "the
     generated inventory below still lists the closed members as
     gaps…" paragraph — no fresh `dump_lom` can be taken from this
     environment; the inventory regenerates at the next dump.
   - Mark the § Dispositions row "Count-in and automation state
     (`count_in_duration`, `is_counting_in`,
     `session_automation_record`, `re_enable_automation_enabled`)"
     **Landed** with a pointer to the new Closed subsection, the way
     the landed rows above it are marked.
   - Update the § "Already in the fork (false gaps)" row "Scale root /
     name", whose note currently reads "`scale_mode`, `scale_intervals`,
     `tuning_system` remain true fork gaps" — after this item only
     `tuning_system` remains.
   No § Curated entry cites these members, so nothing else moves.

(The `CLOSING_THE_GAPS.md` C-1 row strike-through and the ROADMAP entry
removal are `/ship`'s, not this PR's.)

## Testing (`tests_unit/`, the only gate)

`python3 -m pytest tests_unit/` — the whole suite, not only the new file;
`test_handler_subclass_contract.py` and `test_import.py` parse/load
`song.py` and will catch a malformed registration. The new file's coverage
is Part 2. What it cannot cover, by design: real LOM behaviour (vector
types, Boost struct attributes, TimeFormat ints, what `move_device`
returns, whether `overdub` mirrors `session_record`) — that is the next
section. `tests/` mutates a running Live on import and stays out of the
gate.

## Live verification

**Precondition for every check:** the Remote Scripts copy equals this
checkout byte for byte (`diff -rq`) *and* Live has been restarted since it
was copied — files on disk are not code in memory.

**Environment note (2026-08-29):** Live 12.4.3 was running during
planning, but this environment's permission policy denies writing probe
handlers into the installed copy and denies UDP sends, so every check
below is **deferred** — the archived-plan precedent
(`docs/archive/PLAN_application_dialogs_and_versions.md` recorded all
nine of its checks as skipped by environment). Method: `API.md` § "The
no-probe variant" — send to 11000, never bind 11001 (Seshat's), read
evidence from the installed `logs/abletonosc.log`, wrap mutations in
`begin_undo_step`/`end_undo_step` and restore everything.

1. **Scalar spot-checks (read-only):** send `get` for each of the eleven
   loop scalars plus `file_path`, `exclusive_solo`, `last_event_time`,
   `select_on_launch`; evidence = the `_get_property` log line naming the
   value, cross-checked against Live's UI (Automation Arm lit ↔
   `session_automation_record`, preferences pane ↔ `exclusive_arm`/
   `exclusive_solo`/`select_on_launch`, title bar path ↔ `file_path`).
2. **`count_in_duration` mapping:** set the count-in preference to each
   of None/1/2/4 bars in the UI, `get` after each; evidence = four log
   lines pinning the index mapping. Fold the result into API.md beside
   the row.
3. **rw setters land:** inside an undo pair, `set/scale_mode 1` then
   `get` (read-back proves it), same for `tempo_follower_enabled`,
   `session_automation_record`,
   `is_ableton_link_start_stop_sync_enabled`, `start_time 8.0`;
   restore originals, `undo` leftovers.
4. **`overdub` aliasing:** toggle `session_record` in the UI, `get/overdub`
   before and after; evidence decides the API.md wording ("legacy alias"
   vs independent flag).
5. **`scale_intervals`:** set scale to Major then Minor via the existing
   `set/scale_name`, `get/scale_intervals` after each; evidence = the
   flattened tuples `0 2 4 5 7 9 11` / `0 2 3 5 7 8 10` in the log, which
   also proves vector flattening against a real Boost vector.
6. **`visible_tracks`:** on a set with a group track, `get` folded and
   unfolded; evidence = the index tuple shrinking/growing while
   `num_tracks` stays constant.
7. **Struct decodes:** `get_beats_loop_start` / `get_beats_loop_length`
   against a known loop brace; `get_current_smpte_song_time 1` (and one
   other format int); evidence = decoded fields in the log matching the
   UI clock — or a structured `/live/error AttributeError` naming the
   wrong attribute, which is the designed loud failure. Record the
   TimeFormat ints exercised.
8. **`move_device`:** on a scratch track with two devices, inside an undo
   pair: move device 0 to position 1 on the same track; evidence = the
   reply int in the log plus `/live/track/get/devices/name` read-back
   showing the new order; then undo. Also one cross-track move, one
   `find_device_position` call before it (evidence that find did not
   mutate: read-back unchanged).
9. **`scrub_by` / `play_selection` / `sync_parameter_changes`:**
   `scrub_by 4.0` with `get/current_song_time` read-back;
   `play_selection` with an arrangement selection and `get/is_playing`
   read-back; `sync_parameter_changes` — log-only, recording that it
   raised or not (its semantics stay ⚠️ even after a clean call).
10. **No-listen contract:** `start_listen/file_path`; evidence = the
    `Unknown OSC address` log line and no error datagram.

**Remains uncovered even after this pass:** `sync_parameter_changes`
semantics (a clean no-op call proves callability, not meaning);
`file_path` on a never-saved set (needs File → New, discarding the open
set); `overdub` behaviour distinct from what check 4 observes;
`tempo_follower_enabled` effect (needs the preference toggle visible and
a tempo-follow source configured).

## Downstream

**Pin bump only.** No existing address, argument list, or reply shape
changes; all 58 new addresses are additive, and Seshat consumes none of
them yet. When Seshat grows tools on these members, its
`vendored_addresses_test` should grep `song.py` for the new names the way
it already does for `swing_amount` / `begin_undo_step` / `end_undo_step`
(the addresses are loop-generated, so the literal-address audit cannot see
them) — but that is that PR's obligation, not this one's.

## Out of scope

- `Song.get_data` / `set_data`, `tuning_system` — D-5 (fold into a later
  batch; the roadmap keeps them).
- `groove_pool` — D-2 (roadmap #2).
- `can_jump_to_next_cue` / `can_jump_to_prev_cue`,
  `is_cue_point_selected`, cue-point listeners — B-3.
- `Song.View` members (`draw_mode`, `follow_song`,
  `highlighted_clip_slot`, …) — C-2.
- Chain/rack targets for `move_device` / `find_device_position` — A-1 /
  D-1 (declined until racks are scheduled); this PR reaches track-level
  targets only and says so in API.md.
- Any change to the four already-registered neighbours (`root_note`,
  `scale_name`, `is_ableton_link_enabled`, `clip_trigger_quantization`).
- Regenerating the FORK_GAPS inventory (requires a `dump_lom` against a
  Live running this code; the staleness note carries the delta until
  then).

## Open questions

Every ⚠️ in the body, gathered. None could be closed at planning time:
the only instrument that can answer them is a probe or no-probe pass
against the running Live, and this environment's permission policy denies
the UDP sends and installed-copy writes those need (Live 12.4.3 *was*
running; the shipped `.pyc` bundle was mined instead, which is how
`bars`/`beats`/`sub_division` and the `COUNT_IN_DURATION_IN_BARS` table
were corroborated).

1. **`count_in_duration` index mapping.** Unknown: the exact index→bars
   table. Why open: apiref docstring truncates mid-sentence; the Push2
   table's values are marshalled in a 3.11 `.pyc` this environment cannot
   unmarshal. Assumed meanwhile: 0=None, 1=1 Bar, 2=2 Bars, 3=4 Bars
   (M4L documentation), flagged in API.md. Live check 2 closes it.
2. **`BeatTime.ticks` and the four `SmpteTime` attribute names.**
   Unknown: whether the struct attributes are exactly
   `bars/beats/sub_division/ticks` and `hours/minutes/seconds/frames`.
   Why open: only the first three BeatTime names appear in shipped
   scripts; the rest are M4L-derived. Assumed meanwhile: the documented
   names, with a wrong name failing loudly as `/live/error
   AttributeError` rather than a wrong value. Live check 7 closes it.
3. **`Live.Song.TimeFormat` int mapping.** Unknown: which int selects
   which SMPTE format. Why open: enum values live only in the running
   Live. Assumed meanwhile: pass-through int, documented as such with the
   M4L member names (`smpte_24`, `smpte_25`, `smpte_29`, `smpte_30`,
   `smpte_30_drop`, `ms_time`) as reference. Live check 7 records the
   exercised ints.
4. **`move_device` / `find_device_position` semantics.** Unknown: what
   the returned int means (assumed: resulting/would-be device index),
   whether `find` is truly non-mutating, and whether Boost accepts a
   `Track` for the `(LomObject)target` parameter at all. Why open:
   Remote-Script method, no shipped-script call site found. Assumed
   meanwhile: M4L semantics; a rejected target raises and arrives as a
   structured error, so the failure mode is loud. Live check 8 closes it.
5. **`overdub`'s relationship to `session_record`.** Unknown: what the
   truncated "Now hooks to…" docstring hooks to. Assumed meanwhile:
   legacy alias of session-record state, documented with the ⚠️. Live
   check 4 closes it.
6. **`file_path` on a never-saved set.** Unknown: empty string vs
   RuntimeError (which `_get_property` turns into `(None,)`). Why open:
   answering requires discarding the open set. Assumed meanwhile: empty
   string, flagged in API.md; stays open past the first Live pass.
7. **`sync_parameter_changes` behaviour.** Unknown: what it does — it is
   Remote-Script-only, absent from M4L's table, docstring is
   signature-only. Assumed meanwhile: registered as a plain
   fire-and-forget method because the C-1 row lists it, flagged ⚠️ in
   API.md as behaviour-unknown. May never fully close; a clean call in
   Live check 9 at least proves it callable.
8. **`start_time` set semantics.** Unknown: the quantization the
   truncated docstring describes for the setter. Assumed meanwhile:
   plain float-beats set, flagged in API.md. Live check 3's read-back
   narrows it.
