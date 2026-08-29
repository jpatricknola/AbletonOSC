# Fork gaps — what the installed Live API can do that this fork cannot

_Living list. A **fork gap** is a capability present in the installed Live
Object Model but with no OSC address in this repository. It is neither a
Live limit nor a Seshat tool-layer gap, and it must never be planned as UI
scripting — closing one is a handler here (one commit in this repo, one
submodule pin bump in Seshat, `mix abletonosc.install`, Live restart),
documented in `API.md` and tripwired by
Seshat's `vendored_addresses_test`._

## Three layers, and how to classify a "can't"

Seshat has three capability layers that are easy to collapse into one:

1. **Live's installed Live Object Model** — what Live permits a Remote
   Script to read or call.
2. **This fork** — which LOM members have OSC addresses.
3. **Seshat's tool layer** — which addresses the model can actually use.

"Seshat cannot do X" may mean a tool is missing, a handler is missing, or
Live exposes no API at all. Only the last justifies UI scripting. When a
capability looks out of reach, classify it in this order:

1. Check the [generated inventory](#generated-inventory) — is the member
   on the class at all? (If not there and not in the apiref, it is a Live
   limit.)
2. Check the fork's Python registrations, not only the API markdown — the
   inventory's address list is taken from the running server.
3. Check whether Seshat already has a handler/tool for the address
   ([false gaps](#already-in-the-fork-false-gaps) below lists the usual ones).
4. Only then record it here as a fork gap, or in Seshat as a tool gap.

## Three kinds of gap

A member diff alone does not describe the fork's reach. Gaps come in three
shapes, and each has its own section below:

1. **Member gaps** — a LOM property or method with no address at all.
   *Complete* list: the [generated inventory](#generated-inventory) at the
   bottom, produced mechanically from the running Live. Curated write-ups
   for the ones a plan has looked at are under [Curated entries](#curated-entries).
2. **Addressing gaps** — the member has an address, but the address can
   only reach *some* of the objects that carry it (e.g. `Clip` members work
   for Session clips only). The generated inventory counts these as
   covered; the [Addressing gaps](#addressing-gaps) section is the record.
3. **Shape gaps** — the member has an address, but the reply or argument
   flattens away part of what Live offers (e.g. note IDs). Also counted as
   covered by the inventory; see [Shape gaps](#shape-gaps).

## How to use this file

- **Regenerate the inventory** after every Live upgrade and after every
  handler lands: in Live with this fork installed send
  `/live/application/dump_lom` (writes `logs/lom_dump.json`), then
  `python3 tools/lom_gaps.py <dump> --write`. It rewrites only the block
  between the `lom-gaps` markers. Never edit that block by hand.
- **Add a curated entry** whenever research, a plan, or a review picks a
  gap up — Seshat's `/evaluate` skill (§2.3) produces these. Say what would
  consume it and what shape the address should take, so a plan can find
  the prerequisite. Verify the member in the generated inventory (owner
  class, rw/ro, observable) before writing prose about it.
- **Add an addressing or shape entry** when you find one; the tool cannot.
  Both sections are hand-maintained.
- **Remove an entry** when the fork gains the address, in the same commit.
  Don't leave it marked done — the address docs are the record of what
  exists. The inventory drops it on the next regeneration.
- **Nothing here is prioritised.** A gap enters Seshat's `docs/ROADMAP.md`
  only when a feature needs it; until then it is inventory.
  Sequencing into PR-sized buckets lives in
  [CLOSING_THE_GAPS.md](CLOSING_THE_GAPS.md); what is scheduled, and in
  what order, is [ROADMAP.md](ROADMAP.md).
- **Object-valued members** (`Song.cue_points`, `slices`, `Device.view`)
  are the usual reason a member was skipped: the generic `properties_r/rw`
  machinery serialises scalars only. Closing such a gap means a
  hand-written handler that takes or returns an index, a name, or a
  flattened tuple — say which in the entry. `Clip.groove` is the worked
  example: see the Groove Pool entry under [Closed](#closed).
- **History.** Seshat's former `docs/evaluating/lom-to-fork-gap-audit.md`
  (2026-07-31, deleted 2026-08-27 once folded in here; hand-written from `strings` on `LomTypes.pyc` and the
  apiref) was the first pass and has been folded into this file: its
  dispositions and false-gap table are the two sections below the curated
  entries, its membership claims are superseded by the generated inventory
  (which read ~200 members it did not name and reflects addresses added
  since). Entries that say "July audit" mean that document.

## Evidence tiers

State which one each entry rests on; only the last means "works."

1. **Name present** — read from the running Live's class objects (the
   generated inventory) or matched by `strings` on `LomTypes.pyc`. The
   inventory gives owner class, kind and setter/listener presence; a bare
   `strings` match gives only the name (`export_to_clip_slot` matched that
   way and belonged to Looper).
2. **Documented** — apiref page or Ableton release notes name the owner,
   access mode and version.
3. **Called from a Remote Script** — this fork's own code, Live's shipped
   Python, or a probe handler run through the rig in
   [API.md](API.md) ("Measuring the Live API without building the feature
   first"), with the answer read out of `Log.txt`.

Every curated entry below as of 2026-08-27 is tier 1 or 2; the generated
inventory is tier 1 by construction. **None has been run.** A member being
present does not mean the generic setter accepts it (`Clip.groove` is listed
rw and still fails through the generic setter with "Infered arg_value type is
not supported" — it took a hand-written handler to reach, see the Groove Pool
entry under [Closed](#closed)) or that a `†` Remote-Script-only member does
what its name suggests.

## Curated entries

### `Song.cue_points` — the remaining locator members

- **LOM:** `Song.cue_points` (list, observable), `CuePoint.name` (rw,
  observable), `.time` (ro, observable), `.jump()`; `Song.set_or_delete_cue`,
  `jump_to_next_cue`, `jump_to_prev_cue`, `can_jump_to_next_cue`/`_prev_cue`
  (observable), `is_cue_point_selected`. Tier 1 (inventory, 2026-08-27).
- **Fork today:** `/live/song/get/cue_points` → flattened `(name, time)*`;
  `/live/song/cue_point/jump <index|name>`; `/live/song/cue_point/add_or_delete`;
  `/live/song/jump_to_next_cue`, `jump_to_prev_cue`. (An earlier version of
  this entry said "nothing" — it was wrong; the inventory is what to check.)
- **Still missing:** `start_listen/cue_points` (the list is observable, so
  a locator added in the UI could push), `can_jump_to_next_cue`/`_prev_cue`,
  `is_cue_point_selected`, `CuePoint.name` set, and per-cue `name`/`time`
  listeners — see also [Shape gaps](#song-cue_points--index-keyed-no-timename-listen).
- **Consumers:** live-improv section scheduling
  (`docs/evaluating/generative features/live-improv-exploration.md` §9 said
  "not in the fork" and used scene names instead — also stale);
  arrangement-aware anything.
- **Also in:** [Dispositions](#dispositions-from-the-july-2026-audit), count-in row.

### `DrumChain.in_note` and rack chain insertion — read the Drum Rack pad map

- **LOM:** `DrumChain.in_note` get/set/observe (12.3; -1 = All Notes),
  `DrumChain.out_note`, `RackDevice.insert_chain(index)` (12.3),
  `Track.insert_device` / `Chain.insert_device` (12.3),
  `SimplerDevice.replace_sample(path)` (12.2). Tier 2 (Live 12.2/12.3
  release notes); names verified 2026-08-27.
- **Fork today:** device addresses stop at top-level regular-track
  devices; no chain or drum-pad traversal at all.
- **Shape to build:** `/live/device/get/drum_pads <track> <device>` →
  `(chain_index, in_note, name)*`; `insert_chain` and `in_note` setters
  for building a kit programmatically.
- **Consumers:** one-Drum-Rack output for generated drums
  (`docs/evaluating/generative features/midi-generation-options.md` § Open
  work listed the pad map as unreadable — it is not); per-lane pitch
  normalisation.

### `SimplerDevice` slicing — slice a loaded sample from the bridge

- **LOM:** `SimplerDevice.playback_mode` (2 = Slicing),
  `slicing_playback_mode`, `slices` (list of times), `insert_slice`,
  `remove_slice`, `clear_slices`, `reset_slices`, `move_slice`,
  `selected_slice`, `sample`, `replace_sample`. **Tier 1 for the slice
  members** — present in 12.4.3 `LomTypes.pyc`; the apiref page lists only
  `playback_mode`, `slicing_playback_mode` and `sample`. Verify each
  member's owner and signature in Live's shipped Python before building.
- **Fork today:** no Simpler-specific addresses.
- **Shape to build:** `replace_sample`, `playback_mode` setter, `slices`
  getter; Seshat would write the trigger clip itself from the slice times
  via `write_midi_notes`, standing in for Live's UI-only *Slice to New MIDI
  Track*.
- **Consumers:** "generate audio, keep it editable" output shape
  (`docs/evaluating/generative features/live-native-options.md` §2.4).

## Dispositions (from the July 2026 audit)

_Impact and architectural fit, carried over from Seshat's
`lom-to-fork-gap-audit.md` (2026-07-31) so that file can go. Not a roadmap;
a gap enters `docs/ROADMAP.md` only when a feature needs it. Rows whose
fork side has since landed are marked._

| Priority | Missing bridge surface | Why it matters | Disposition |
|---|---|---|---|
| High | `Application.open_dialog_count`, `current_dialog_message`, `current_dialog_button_count` | Detect and describe a blocking Live dialog without AX or pixels | **Landed** — see [Closed](#application-dialogs-and-versions--closed-2026-08-29). `press_current_dialog_button` stays out, as this row required: still no address for it unless a separately reviewed, non-file use case proves safe — a current dialog may guard unsaved work |
| High | Return/master mixer and device addressing | An empty return cannot become a usable reverb/delay path without human device loading | **Landed** (`/live/return_track/*`, `/live/master/*`) for top-level devices, and widened to `Track` parity by A-3 — colour, meters, output routing, return sends and `insert_device`; see [Closed](#returnmaster-track-parity--closed-2026-08-29). What remains is devices *inside* racks, under [Addressing gaps](#addressing-gaps) |
| High | `Application.View.is_view_visible`, `hide_view` | Closes `show_view`'s blind loop; makes view smoke tests self-verifying | **Landed.** `focused_document_view` (Session vs Arranger, exact) still open and belongs in the same handler |
| Medium–high | `DeviceParameter.value_items`, `is_enabled`, `automation_state`, `default_value`, `original_name` | Tools expose raw min/max but cannot name enum choices, tell whether a parameter is disabled, or warn that automation owns it | **Landed** as one unit, ahead of any device-specific API — see [Closed](#device-parameters--numeric-only--closed-2026-08-29) |
| Medium–high | Extended note identity and modification (`note_id`, `apply_note_modifications`, selection/by-ID methods) | Safe single-note edits; keeps probability, deviation, release velocity the flattened reply discards | **Landed** as one unit — see [Closed](#notes--flattened-to-five-fields--closed-2026-08-29). `/live/clip/get/notes_extended` carries `note_id`, probability, deviation and release velocity, and `apply_note_modifications` edits a note in place keeping its id, so Seshat's `edit_notes` no longer has to compose remove + add |
| Medium | Count-in and automation state (`count_in_duration`, `is_counting_in`, `session_automation_record`, `re_enable_automation_enabled`) | Recording readiness and automation ownership are musically meaningful, exact, and invisible today | **Landed** — see [Closed](#song-remainder--closed-2026-08-29). All four are addresses now, with listen pairs; the `re_enable_automation` action was already bridged. ⚠️ `count_in_duration`'s index→bars mapping is still unmeasured |
| Medium | `Song.View.draw_mode`, `follow_song` | Readable absolute state instead of focus-routed toggle shortcuts | Fold into a concrete view/automation workflow; no value as isolated knobs |
| Medium–low | Groove Pool enumeration and clip assignment | Makes `set_groove_amount` useful without a groove assigned by hand | **Landed** as one unit — see [Closed](#groove-pool--closed-2026-08-29). `/live/song/get/groove_pool` enumerates, `/live/groove/*` reads and writes each groove's amounts, and `/live/clip/set/groove` assigns by pool index or clears with `-1`. ⚠️ Whether an `.agr` file can be loaded into the pool through the browser is still unmeasured, and is the one part of the curated entry that did not close |
| Conditional | Arrangement clips and take lanes | LOM support is substantial; Seshat is deliberately Session-first | Declined until an Arrangement/comping workflow is chosen |
| Conditional | Rack chains, Drum Pads, macros, variations | Deep sound design, but needs recursive addressing and a much larger tool contract | Declined until a named workflow needs inside-the-Rack control; the pad-map read is a curated entry above |
| Conditional | Device-specific APIs (Simpler, Wavetable, Looper, Drift, Roar, …) | Large surface, uneven value; generic parameters already cover much | Only from a concrete feature, never as blanket parity work |

Cautions the audit attached to individual members, kept because the
inventory's one-line docstrings do not carry them:

- `ClipSlot.create_audio_clip`, `Track.create_audio_clip`,
  `SimplerDevice.replace_sample` take absolute file paths. Any handler
  must follow the fork's path-safety rule: the model must not hand
  arbitrary paths to code running with Live's privileges.
- `Application.View.focus_view` overlaps `show_view`; `toggle_browse` is
  inferior to absolute show/hide; `scroll_view`/`zoom_view` need a user
  story before they earn tool surface.
- `Song.appointed_device`, `groove_pool`, `tuning_system`, `tracks`,
  `scenes`, `cue_points` are objects or collections — never put them in
  the generic property loop.
- `Application.control_surfaces` is an object list with little value to
  Seshat today.

## Already in the fork (false gaps)

_Common sources of wrong "fork gap" claims. The missing layer is Seshat's,
not Python's._

| Capability | Existing fork surface | Actual missing layer |
|---|---|---|
| Read/set regular-track audio input | `/live/track/get|set/input_routing_type`, `input_routing_channel`, and the `available_*` lists | Tool layer |
| Read/set regular-track output | Matching `output_routing_*` addresses | Tool layer |
| Set monitoring mode | `/live/track/get|set/current_monitoring_state` | Tool layer |
| Track colour | `/live/track/get|set/color`, `color_index` | Tool layer |
| Read Arrangement clip summary | `/live/track/get/arrangement_clips/{name,length,start_time}` | A full Arrangement workflow, not the three reads |
| Scene tempo / time signature | `/live/scene/get|set/*` | Tool layer |
| Link enable | `is_ableton_link_enabled` get/set/listen | Tool/docs layer |
| Scale root / name | `root_note`, `scale_name` get/set/listen, and since C-1 `scale_mode` get/set/listen and `scale_intervals` get/listen — see [Closed](#song-remainder--closed-2026-08-29) | Tool choices; only `tuning_system` remains a true fork gap (D-5) |
| Cue points | `/live/song/get/cue_points`, `cue_point/jump`, `cue_point/add_or_delete`, `jump_to_next/prev_cue` | Tool layer, plus the listen/guard members in the curated entry |
| Dialog detection needs AX | `/live/application/get/open_dialog_count`, `current_dialog_message`, `current_dialog_button_count` (+ listen on the count) | False, and no longer a fork gap either: the addresses exist — see [Closed](#application-dialogs-and-versions--closed-2026-08-29) |
| Drum Rack pad map unreadable | — | False: `DrumChain.in_note` is a fork gap (curated entry) |

The audit also found eight registered addresses missing from Seshat's
`API.md`; all eight are documented there now. The
rule stands: before implementing any gap, reconcile the address rows with
the Python source in the same change, and never infer an address name from
AbletonOSC naming patterns.

## Addressing gaps

_Members the inventory counts as exposed, but whose address resolves only
one location of the object. Hand-maintained; verified against the
registered address table 2026-08-27._

### `Clip` — Session clips only

`/live/clip/*` resolves `song.tracks[t].clip_slots[s].clip`. The same
`Clip` class is every Arrangement clip (`track.arrangement_clips[n]`) and
every take-lane clip (`take_lane.arrangement_clips[n]`). None of the 86
`Clip` members — notes, loop, warp, name, colour — are reachable there.
The fork's only Arrangement reads are
`/live/track/get/arrangement_clips/{name,length,start_time}`. Closing this
means a second clip resolver keyed `(track, arrangement_index)`, not new
members. `Clip.is_arrangement_clip`/`is_session_clip` exist to tell them
apart.

### `Device` / `DeviceParameter` — top-level devices only

`/live/device/*` resolves `song.tracks[t].devices[d]`.
`/live/return_track/device/*` and `/live/master/device/*` add the same
five reads plus `set/parameter/value` for return and master top-level
devices — a subset (no `class_name`, `type`, `parameters/min|max|is_quantized`,
no listeners). Nothing reaches devices inside a Rack (`RackDevice.chains[c].devices[d]`),
Drum Rack pads (`drum_pads[p].chains[c].devices[d]`), rack return chains,
or Max-device `DeviceIO`. Needs a recursive path form; the whole
`RackDevice`/`Chain`/`DrumPad`/`DrumChain` family in the inventory is
unreachable until it exists.

### `Track` — regular tracks get 109 addresses, return 60, master 49

`/live/track/*` is `song.tracks` only. `Track` is also every return track and
the master, reached instead through `/live/return_track/*` and
`/live/master/*`. Since **A-3** those two prefixes carry the mixer surface
(`name`, `volume`, `panning`, `mute`, `solo`, `cue_volume`), the device subset
(`devices`, `device/*`, `delete_device`, `insert_device`, `select_device`),
`select`, colour (`color`, `color_index`), the four `has_*_input/output`
reads, the three `output_meter_*` reads, output routing (both `available_*`
lists and both get/set pairs), the returns' own `mixer_device.sends`, and a
`start_listen`/`stop_listen` pair for every mutable scalar among them.

Counts measured from the registered address tables on 2026-08-29: **109 / 60 /
49**, against 108 / 30 / 21 before A-3 landed (the "107 / 20 / 15" this
heading carried for months predated the fork's return/master work entirely).

Still missing on returns/master, and deliberately so unless a feature asks:
the clip family (`clip_slots`, `arrangement_clips`, `stop_all_clips`,
`delete_clip`, `fired_slot_index`, `playing_slot_index` — returns have no
clips), input routing (neither has an input section in Live's UI), listen
pairs for the four `has_*` reads (constants there), `arm` and the master's
`mute`/`solo` (absent on those objects, measured 2026-07-31), and the
regular-track-shaped members `is_visible`, `is_grouped`, `is_foldable`,
`fold_state`, `can_be_armed`, `current_monitoring_state`, `group_track` and
the split `devices/*` getters.

### `MixerDevice` — four of eleven members, and only via `Track`

`volume`, `panning`, `sends` reach `track.mixer_device` on a regular track,
and since **A-3** `sends` reaches a *return* track's mixer too
(`/live/return_track/get|set/send`) — Live 12's return-to-return send
section. `cue_volume` reaches the master's. `Chain.mixer_device`
(`ChainMixerDevice`: volume, panning, sends, chain_activator) still has no
path, which is what makes rack chains silent even once devices are reachable;
so do `crossfade_assign`, `panning_mode`, `track_activator`, `crossfader`,
`song_tempo` and the split-stereo members.

### `Song.View` / `Application.View` — `/live/view` is a fixed set

`/live/view/*` exposes selected track/scene/clip/device, `detail_clip`
set, `show_view`, `hide_view`, `is_view_visible`, and — since A-4 — the four
object-valued `Song.View` reads `selected_chain`, `selected_parameter`,
`mod_mapping_device` and `mod_mapping_parameter`. `Track.View`,
`Clip.View`, `Device.View`, `RackDevice.View` and `Eq8Device.View` members
are not addressable because there is no per-object view resolver.

## Shape gaps

_Members the inventory counts as exposed, but whose wire form loses part
of what Live provides. Hand-maintained._

### Routing — names, not objects

`/live/track/get/available_input_routing_types` etc. return names;
`Track.input_routing_type` on the LOM is an object with `display_name`,
`category` and `attached_object`. The fork resolves by display name when
setting, so a routing whose display name is not unique (two identically
named external instruments, two tracks called "Drums") is ambiguous. A
stable identifier would need the object or its index.

### `Song.cue_points` — index-keyed, no time/name listen

`/live/song/get/cue_points` and `cue_point/jump`, `cue_point/add_or_delete`
exist (see curated entry). `CuePoint.name`/`time` are observable in Live;
the fork cannot listen to a cue moving or being renamed, and the index
shifts when one is deleted. An ID or name-keyed form is the shape fix.

## Closed

Move entries here only in the same commit that lands the address, then
delete them at the next tidy — the address docs are the permanent record.

### Groove Pool — closed 2026-08-29

Was a shape gap and an addressing gap at once: `Clip.groove` holds a
`Live.Groove.Groove`, so the generic property loop could not put it on the wire
(upstream commented it out in place with the failure it observed, "Infered arg
value type is not supported"), and there was no address for the pool it indexes
into either. `Song.groove_amount` was therefore a dial with nothing to scale on
any set where a human had not dragged a groove onto a clip by hand.

Closed by roadmap item **D-2**, which adds a new `abletonosc/groove.py`
(`GrooveHandler`, `/live/groove/*`), the hand-written
`/live/song/get/groove_pool` dump and its listen pair in `song.py`, and the
hand-written `/live/clip/get|set/groove` pair and its listen pair in `clip.py`.
A groove is named by its **index into `song.groove_pool.grooves`**, the A-4
object-read pattern applied to a single flat collection; `-1` means "no groove
assigned", and `/live/clip/set/groove -1` is the one sanctioned place in this
fork where `-1` is an argument rather than an answer (it clears the
assignment). `API.md` § "Groove API" is the permanent record, with
§ "Object-valued reads" carrying the reasoning for that exception.

Members this closed: `Song.groove_pool`, `GroovePool.grooves`, `Clip.groove`,
and all six of `Live.Groove.Groove` — `name`, `base`, `quantization_amount`,
`timing_amount`, `random_amount`, `velocity_amount`.

Deliberately still open, each recorded in `API.md` rather than shipped as dead
wire surface: **a listen pair for `Groove.base`** (Live offers no
`add_base_listener` — it is the one non-observable member of the class), and
`base` in the **pool dump** (its wire type is unverified and the OSC builder
drops an entire reply it cannot encode, so it is reachable through its own
address instead, where an encoding surprise costs one address rather than the
whole pool read).

**Carried forward as still open:** whether an `.agr` groove file can be loaded
*into the pool* through `browser.load_item` — the measurement the curated entry
named. The LOM has no `Browser.grooves` root and `packs` is not one of
`browser.py`'s exposed categories, so `.agr` files may not be reachable through
this bridge at all today; that decides whether the ~3,000 grooves shipped with
Live can be used without a human dragging one in. The measurement is in the
archived plan's Live verification section, and a "no" is a candidate roadmap
item (exposing `packs`), not a widening of this one.

⚠️ Nothing in this family has been exercised against a running Live. Whether
`clip.groove = None` clears, what `Groove.base` encodes to and how it maps to
the 1/4…1/32 grids, the four amount ranges (especially `velocity_amount`'s
sign), and whether the `GroovePool.grooves` observer fires on membership
changes only are all unmeasured; `API.md` marks each with a ⚠️.

The generated inventory below still lists the closed members as gaps: it is
regenerated only from a `/live/application/dump_lom` taken against a Live
running the *installed* copy, and no dump has been taken since this landed.

### Return/master `Track` parity — closed 2026-08-29

Was an addressing gap: a return track and the master are `Live.Track.Track`
objects, but the fork reached them through a hand-written address family built
for the mixer-and-devices workflow, so a return could be renamed and faded but
not coloured, metered, or re-routed, and had no reachable sends of its own.

Closed by roadmap item **A-3**, which adds fifty-eight addresses to
`abletonosc/return_track.py` — colour and colour index, the four
`has_*_input/output` reads, the three `output_meter_*` reads, output routing
(both `available_*` lists and both get/set pairs), `mixer_device.sends` on
returns, and `insert_device`, each in a return-indexed and a master form except
the sends — plus one string in `abletonosc/track.py`'s generic methods list for
`/live/track/insert_device`. Address counts went 108 / 30 / 21 → **109 / 60 /
49** for regular / return / master. `API.md` § "Return Track & Master: `Track`
parity" is the permanent record, including the ⚠️ markers on everything still
unmeasured against a running Live (whether the Main track has `color`,
`insert_device` name semantics, return-send behaviour).

Members this closed, on returns and the master: `color`, `color_index`,
`has_audio_input`, `has_audio_output`, `has_midi_input`, `has_midi_output`,
`output_meter_level`, `output_meter_left`, `output_meter_right`,
`output_routing_type`, `output_routing_channel`,
`available_output_routing_types`, `available_output_routing_channels`,
`insert_device` (also on regular tracks), and `MixerDevice.sends` on a return.

Deliberately still open, each recorded in `API.md` rather than shipped as dead
wire surface: **listen pairs for the four `has_*` reads** (constants on a
return and on the master, so a subscription could only deliver its one
immediate push), **input routing** (neither object has an input section in
Live's UI), **send listen pairs** (`Track.sends` is not observable — the same
reason `/live/track/start_listen/send` does not exist), and the master's
`mute`/`solo`/`arm` and a return's `arm` (absent on those objects, measured
2026-07-31). The clip-family members do not apply to a return at all and stay
in the Track section's residual list.

The generated inventory below still lists the closed members as gaps: it is
regenerated only from a `/live/application/dump_lom` taken against a Live
running the *installed* copy, and no dump has been taken since this landed.

### Object-valued reads returned as `None` — closed 2026-08-27

Was a shape gap: the generic getter turns any value the OSC builder cannot
encode into an error or `None`, so no member whose type is another LOM object
could be read at all. Closed by roadmap item A-4, which gives each one a
hand-written, index-returning handler and establishes the pattern every later
object-family item reuses — `API.md` § "Object-valued reads" is the permanent
record, `abletonosc/track_identity.py` the shared resolution.

Members this closed: `Song.appointed_device` (get/set/listen),
`Track.group_track`, `ClipSlot.clip`, and `Song.View`'s `selected_chain`,
`selected_parameter`, `mod_mapping_device` and `mod_mapping_parameter`.
`Song.master_track` was never a gap row — it is reached under `/live/master/*`.

Still object-valued and still unreached, now as an ordinary addressing gap
rather than a shape gap: `Device.view`. `Clip.groove` was the other one, and
became this pattern's first consumer outside `track_identity.py` — see the
Groove Pool entry below. The generated
inventory below still lists the closed members as gaps: it is regenerated only
from a `/live/application/dump_lom` taken against a Live running the *installed*
copy, and no dump has been taken since this landed.

### Notes — flattened to five fields — closed 2026-08-29

Was a shape gap: `/live/clip/get/notes` called `get_notes_extended` and emitted
only `(pitch, start_time, duration, velocity, mute)` per note, discarding
`note_id`, `probability`, `velocity_deviation` and `release_velocity`, and
`/live/clip/add/notes` took the same five, so the three extended fields could
not be written at all. Without a `note_id` on the wire the id-keyed half of
Live's note API was unreachable from a client even where an address existed —
`/live/clip/remove_notes_by_id` was registered and `API.md` had to warn that
nothing in this API yielded an id to pass it.

Closed by roadmap item B-1, which adds twelve addresses to `abletonosc/clip.py`
without touching the old ones: `get/notes_extended`, `add/notes_extended`,
`get/selected_notes_extended`, `get/selected_notes`, `get_notes_by_id`,
`apply_note_modifications`, `duplicate_notes_by_id`, `select_notes_by_id`,
`select_all_notes`, `deselect_all_notes`, and the deprecated
`replace_selected_notes` / `set_notes` pass-throughs. `API.md` § "Extended
notes (note ids)" is the permanent record — the canonical nine-field group
order, the negative-`destination_time` sentinel, the int32/int64 note-id edge,
and the ⚠️ markers on everything still unmeasured against a running Live.

The old five-field addresses are byte-identical: their handler functions were
not edited, and `tests_unit/test_clip_notes.py` pins the five-field reply
against notes that carry the extended fields.

Members this closed: `apply_note_modifications`, `get_notes_by_id`,
`duplicate_notes_by_id`, `select_notes_by_id`, `get_selected_notes`,
`get_selected_notes_extended`, `select_all_notes`, `deselect_all_notes`,
`replace_selected_notes`, `set_notes` — ten inventory rows on
`Live.Clip.Clip`.

Still open on notes, as ordinary member gaps rather than a shape gap: the
`notes` **listener** (`add_notes_listener`), and note editing on Arrangement
clips and take lanes, which needs the clip resolver under
[Addressing gaps](#addressing-gaps). The generated inventory below still lists
the closed members as gaps: it is regenerated only from a
`/live/application/dump_lom` taken against a Live running the *installed* copy,
and no dump has been taken since this landed.

### Device parameters — numeric only — closed 2026-08-29

Was a shape gap: `/live/device/get/parameters/{name,value,min,max,is_quantized}`
and the singular `parameter/{value,value_string,name}` gave a parameter's range
but not its meaning, so a quantized parameter could not be described to a user
at all — no enum labels, no GUI string, no way to tell a greyed-out or
automation-owned knob from a live one. Closed by roadmap item B-2, which adds
seventeen addresses to `abletonosc/device.py`: six bulk lists
(`get/parameters/{display_value,state,is_enabled,automation_state,default_value,original_name}`,
one element per parameter in `device.parameters` order), the matching six
per-parameter getters, `set/parameter/display_value`,
`get/parameter/{value_items,short_value_items}` and the
`parameter/{begin_gesture,end_gesture}` pair. `API.md` § "Parameter
description" is the permanent record — including the two graceful-empty rules
(empty item list for a non-quantized parameter, OSC nil for a missing
`default_value`) and the ⚠️ markers on everything still unmeasured against a
running Live.

Members this closed: `display_value` (get and set), `state`, `is_enabled`,
`automation_state`, `default_value`, `original_name`, `value_items`,
`short_value_items`, `begin_gesture`, `end_gesture` — ten of the twelve the
inventory row counts. `str_for_value` was never a gap in practice: it is
shipped as `/live/device/get/parameter/value_string`.

Still open on this class, now as ordinary member gaps rather than a shape gap:
`re_enable_automation` (a mutation that belongs with an automation-shaped
item), and **listeners** on the three observable members `state`,
`automation_state` and `display_value` — Live offers `add_<name>_listener` for
each, and the pattern to follow is `device_get_parameter_value_listener`. The
generated inventory below still lists the closed members as gaps: it is
regenerated only from a `/live/application/dump_lom` taken against a Live
running the *installed* copy, and no dump has been taken since this landed.

### Application dialogs and versions — closed 2026-08-29

Was a member gap on `Live.Application.Application`, which upstream exposed
three addresses out of twenty-one members. Two things were missing. First,
**dialog state**: a blocking Live dialog was invisible to a client, and the
July 2026 audit had recorded "dialog detection needs AX" as a limitation of
Live — it was a limitation of this bridge. Second, **version identity**:
`get/version` answers `(12, 4)`, which does not say which bugfix release,
which build, or which *edition* is running, and the edition decides which
LOM members exist at all.

Closed by roadmap item C-3, which adds eighteen addresses to
`abletonosc/application.py`: the three dialog reads with a listen pair on
`open_dialog_count` (the only observable one of the three), the four exact
version reads, `get/has_option`, `get/peak_process_usage` (+ listen pair),
`get/number_of_push_apps_running`, the flattened
`get/unavailable_features` and `get/control_surfaces`, and the two
`show_*` message methods. `API.md` § "Application API" and its "Detecting
dialogs" note are the permanent record — including the ⚠️ markers on
everything still unmeasured against a running Live.

The same commit removed an unrelated defect in the same file: the
unsolicited, argument-less `/live/application/get/average_process_usage`
datagram upstream sent at every initialisation (see SESHAT.md § "Fixes to
upstream's own code").

Members this closed: `open_dialog_count`, `current_dialog_message`,
`current_dialog_button_count`, `get_bugfix_version`, `get_build_id`,
`get_variant`, `get_version_string`, `has_option`, `peak_process_usage`,
`unavailable_features`, `number_of_push_apps_running`, `show_message`,
`show_on_the_fly_message`, `control_surfaces` — fourteen of the sixteen the
inventory row counts.

Deliberately still open on this class:

- **`press_current_dialog_button`** — kept off the wire unless a separately
  reviewed, non-file use case proves it safe: a dialog on screen may be
  guarding unsaved work, and pressing its buttons blind is not recoverable.
  This is why the two `show_*` addresses raise **OK-only** dialogs, passing
  Live the text and nothing else so `buttons` keeps its default. The two
  are one decision.
- **`get_document`** — needs no address; `self.song` *is* the document, and
  `view` and `browser` are already in the "Reached under another address"
  list above.
- **Listen pairs for `unavailable_features` and `control_surfaces`** —
  both are observable, but session-static in practice (edition and
  preferences), and a push would need a custom flattening getter. Get-only
  until a consumer appears; a five-line follow-up when one does.

`Live.Application.Application.View` members (`focused_document_view`,
`available_main_views`, …) were never part of this gap — they are their own
row, and their own roadmap item.

The generated inventory below still lists the closed members as gaps: it is
regenerated only from a `/live/application/dump_lom` taken against a Live
running the *installed* copy, and no dump has been taken since this landed.

### `Song` remainder — closed 2026-08-29

Was a plain addressing gap, and the largest single one left on a core class:
`abletonosc/song.py` exposed transport, tempo, loop, quantization and undo, but
25 scalar `Live.Song.Song` members had no address at all — a client could not
ask whether Live was counting in, whether the Automation Arm button was lit,
which tracks were visible, what scale intervals were in force, or where the Set
lived on disk.

Closed by roadmap item **C-1**, which adds fifty-eight addresses to
`abletonosc/song.py`: six read/write and five read-only scalars appended to the
generic property lists as contiguous fork-owned blocks, four get-only
registrations for the members Live offers no listener for, hand-written reads
for `scale_intervals` and `visible_tracks` (plus the derived
`num_visible_tracks`), a second fork-owned methods loop, and five hand-written
method queries — two of which, `move_device` and `find_device_position`, take
their Device and target through A-4's `resolve_device` / `resolve_track`
validators and reach **track-level targets only**. `API.md` § "Song Getters",
§ "Song Setters" and § "Song: method queries" are the permanent record,
including the ⚠️ markers on everything still unmeasured against a running Live.

Members this closed: `can_capture_midi`, `count_in_duration`, `exclusive_arm`,
`exclusive_solo`, `file_path`, `find_device_position`, `get_beats_loop_length`,
`get_beats_loop_start`, `get_current_smpte_song_time`,
`is_ableton_link_start_stop_sync_enabled`, `is_counting_in`, `last_event_time`,
`move_device`, `overdub`, `play_selection`, `re_enable_automation_enabled`,
`scale_intervals`, `scale_mode`, `scrub_by`, `select_on_launch`,
`session_automation_record`, `start_time`, `sync_parameter_changes`,
`tempo_follower_enabled`, `visible_tracks`.

Deliberately still open on this class, each for a reason recorded elsewhere:
`get_data` / `set_data` and `tuning_system` (D-5), `can_jump_to_next_cue` /
`can_jump_to_prev_cue` / `is_cue_point_selected` (B-3, and the curated
cue-point entry), and the `Song.View` members (C-2). `groove_pool` was on this
list too and has since closed — see the Groove Pool entry below. Chain and rack *targets* for the two device-position
methods stay declined with A-1/D-1. `sync_parameter_changes` is registered but
its behaviour is unknown — Remote-Script-only, absent from Max for Live's
table, and Live's docstring is the signature alone.

The generated inventory below still lists the closed members as gaps: it is
regenerated only from a `/live/application/dump_lom` taken against a Live
running the *installed* copy, and no dump has been taken since this landed.

## Generated inventory

<!-- lom-gaps:begin -->
_Generated by `tools/lom_gaps.py` from a `/live/application/dump_lom` taken against Live 12.4.3. Do not edit by hand; rerun the tool. 134 Live classes walked, 568 fork addresses registered._

**Totals:** 205 members exposed, 494 gaps across 44 classes.

Legend: **rw**/**ro** property, **method**; **obs** = Live offers an `add_<name>_listener` (a `start_listen` address is possible); **M4L** = also in Max for Live's `LomTypes` exposure table (members absent there are Remote-Script-only and undocumented in the apiref). Every row is tier 1 evidence (name and kind read from the running Live); nothing here has been called.

## Core classes

### `Live.Song.Song` — 96 members, 63 exposed, 33 gaps

_Reached under another address:_ `get_current_beats_song_time` → /live/song/get/current_song_time; `master_track` → /live/master/*; `view` → /live/view/*

| member | kind | obs | M4L | Live docstring |
|---|---|---|---|---|
| `appointed_device` | rw | yes | yes | Read, write, and listen access to the appointed Device |
| `can_capture_midi` | ro | yes | yes | Get whether there currently is material to be captured on any tracks. |
| `can_jump_to_next_cue` | ro | yes | yes | Returns true when there is a cue marker right to the playing pos that |
| `can_jump_to_prev_cue` | ro | yes | yes | Returns true when there is a cue marker left to the playing pos that |
| `count_in_duration` | ro | yes | yes | Get the count in duration. Returns an index, mapped as follows:  |
| `exclusive_arm` | ro | yes | yes | Get if Tracks should be armed exclusively by default. |
| `exclusive_solo` | ro |  | yes | Get if Tracks should be soloed exclusively by default. |
| `file_path` | ro |  | yes | Get the current Live Set's path on disk. |
| `find_device_position` | method |  | yes | find_device_position( (Song)arg1, (Device)device, (LomObject)target, (int)target_position) -> int : |
| `get_beats_loop_length` | method |  | yes | get_beats_loop_length( (Song)arg1) -> BeatTime : |
| `get_beats_loop_start` | method |  | yes | get_beats_loop_start( (Song)arg1) -> BeatTime : |
| `get_current_smpte_song_time` | method |  | yes | get_current_smpte_song_time( (Song)arg1, (int)arg2) -> SmptTime : |
| `get_data` | method |  |  | get_data( (Song)arg1, (object)key, (object)default_value) -> object : |
| `groove_pool` | ro |  | yes | Get the groove pool. |
| `is_ableton_link_start_stop_sync_enabled` | rw | yes | yes | Enable/disable Ableton Link Start Stop Sync. |
| `is_counting_in` | ro | yes | yes | Get whether currently counting in. |
| `is_cue_point_selected` | method |  | yes | is_cue_point_selected( (Song)arg1) -> bool : |
| `last_event_time` | ro |  | yes | Return the time of the last set event in the song. In contrary to |
| `move_device` | method |  | yes | move_device( (Song)arg1, (Device)device, (LomObject)target, (int)target_position) -> int : |
| `overdub` | rw | yes | yes | Legacy hook for Live 8 overdub state. Now hooks to |
| `play_selection` | method |  | yes | play_selection( (Song)arg1) -> None : |
| `re_enable_automation_enabled` | ro | yes | yes | Returns true if some automated parameter has been overriden |
| `scale_intervals` | ro | yes | yes | Reports the current scale's intervals as a list of integers, starting with the root and representing the number of halfsteps (e.g. Major -> 0, 2, 4, 5, 7, 9, 11) |
| `scale_mode` | rw | yes | yes | Access to the Scale Mode setting in Live. When on, key tracks that belong to the currently selected scale are highlighted in Live's MIDI Note Editor, and pitch-based parameters in MIDI Tools and Devices can be edited in scale degrees rather than semitones. |
| `scrub_by` | method |  | yes | scrub_by( (Song)arg1, (float)arg2) -> None : |
| `select_on_launch` | ro |  | yes | Get if Scenes and Clips should be selected when fired. |
| `session_automation_record` | rw | yes | yes | Returns true if automation recording is enabled. |
| `set_data` | method |  |  | set_data( (Song)arg1, (object)key, (object)value) -> None : |
| `start_time` | rw | yes | yes | Get/Set access to the songs current start time in beats. The set time |
| `sync_parameter_changes` | method |  |  | sync_parameter_changes( (Song)arg1) -> None : |
| `tempo_follower_enabled` | rw | yes | yes | Get/Set whether the Tempo Follower is controlling the tempo. The Tempo Follower Toggle must be made visible in the preferences for this property to be effective. |
| `tuning_system` | ro | yes | yes | Access the currently active tuning system. |
| `visible_tracks` | ro | yes | yes | Const access to a list of all visible Player Tracks in the Live Song, excluding |

### `Live.Song.Song.View` — 11 members, 3 exposed, 8 gaps

| member | kind | obs | M4L | Live docstring |
|---|---|---|---|---|
| `draw_mode` | rw | yes | yes | Get/Set if the Envelope/Note draw mode is enabled. |
| `follow_song` | rw | yes | yes | Get/Set if the Arrangerview should scroll to show the playmarker. |
| `highlighted_clip_slot` | rw |  | yes | Get/Set the clip slot, defined via the selected track and scene in the Session.Will be None for Main- and Sendtracks. |
| `mod_mapping_device` | rw | yes | yes | The device that is waiting for a parameter (via mod_mapping_parameter) to modulate, or None if no device is waiting. |
| `mod_mapping_parameter` | ro | yes | yes | Get the device parameter that's current selected to be mapped. |
| `select_device` | method |  | yes | select_device( (View)arg1, (Device)arg2 [, (bool)ShouldAppointDevice=True]) -> None : |
| `selected_chain` | rw | yes | yes | Get the highlighted chain if available. |
| `selected_parameter` | ro | yes | yes | Get the currently selected device parameter. |

### `Live.Song.CuePoint` — 3 members, 0 exposed, 3 gaps

_Whole class unexposed._ 
- **rw:** `name*`
- **ro:** `time*`
- **method:** `jump`

_`*` observable, `†` not in M4L table._

### `Live.Application.Application` — 21 members, 5 exposed, 16 gaps

_Reached under another address:_ `browser` → /live/browser/*; `get_major_version` → /live/application/get/version; `get_minor_version` → /live/application/get/version; `view` → /live/view/*

| member | kind | obs | M4L | Live docstring |
|---|---|---|---|---|
| `control_surfaces` | ro | yes | yes | Const access to a list of the control surfaces selected in preferences, in the same order. |
| `current_dialog_button_count` | ro |  | yes | Number of buttons on the current dialog. |
| `current_dialog_message` | ro |  | yes | Text of the last dialog that appeared; Empty if all dialogs just disappeared. |
| `get_bugfix_version` | method |  | yes | get_bugfix_version( (Application)arg1) -> int : |
| `get_build_id` | method |  |  | get_build_id( (Application)arg1) -> str : |
| `get_document` | method |  | yes | get_document( (Application)arg1) -> Song : |
| `get_variant` | method |  |  | get_variant( (Application)arg1) -> str : |
| `get_version_string` | method |  | yes | get_version_string( (Application)arg1) -> str : |
| `has_option` | method |  |  | has_option( (Application)arg1, (object)arg2) -> bool : |
| `number_of_push_apps_running` | ro |  |  | Returns the number of connected Push apps. |
| `open_dialog_count` | ro | yes | yes | The number of open dialogs in Live. 0 if not dialog is open. |
| `peak_process_usage` | ro | yes | yes | Reports Live's peak CPU load. |
| `press_current_dialog_button` | method |  | yes | press_current_dialog_button( (Application)arg1, (int)arg2) -> None : |
| `show_message` | method |  |  | show_message( (Application)arg1, (Text)text [, (int)buttons=Application.MessageButtons.OK_BUTTON [, (bool)enable_markup=False [, (bool)show_success_icon=False]]]) -> int : |
| `show_on_the_fly_message` | method |  |  | show_on_the_fly_message( (Application)arg1, (str)message [, (int)buttons=Application.MessageButtons.OK_BUTTON [, (bool)enable_markup=False [, (bool)show_success_icon=False [, (int)push_dialog_type=Application.PushDialogType.MESSAGE_BOX]]]]) -> int : |
| `unavailable_features` | ro | yes |  | List of features that are unavailable due to limitations of the current Live edition. |

### `Live.Application.Application.View` — 10 members, 3 exposed, 7 gaps

| member | kind | obs | M4L | Live docstring |
|---|---|---|---|---|
| `available_main_views` | method |  | yes | available_main_views( (View)arg1) -> StringVector : |
| `browse_mode` | ro | yes | yes | Return true if HotSwap mode is active for any target. |
| `focus_view` | method |  | yes | focus_view( (View)arg1, (object)arg2) -> None : |
| `focused_document_view` | ro | yes | yes | Return the name of the document view ('Session' or 'Arranger') |
| `scroll_view` | method |  | yes | scroll_view( (View)arg1, (int)arg2, (object)arg3, (bool)arg4) -> None : |
| `toggle_browse` | method |  | yes | toggle_browse( (View)arg1) -> None : |
| `zoom_view` | method |  | yes | zoom_view( (View)arg1, (int)arg2, (object)arg3, (bool)arg4) -> None : |

### `Live.Track.Track` — 69 members, 41 exposed, 28 gaps

_Reached under another address:_ `clip_slots` → /live/clip_slot/*; `input_routings` → /live/track/get/available_input_routing_types (legacy string API superseded); `input_sub_routings` → /live/track/get/available_input_routing_channels; `mixer_device` → /live/track/get/volume, panning, send; `output_routings` → /live/track/get/available_output_routing_types; `output_sub_routings` → /live/track/get/available_output_routing_channels; `view` → /live/view/*

| member | kind | obs | M4L | Live docstring |
|---|---|---|---|---|
| `back_to_arranger` | rw | yes | yes | Indicates if it's possible to go back to playing back the clips in the Arranger.Setting a value 0 will go back to the Arranger playback. Setting on grouptracks will go back to the Arranger on all grouped tracks. |
| `can_be_frozen` | ro |  | yes | return True, if this Track can be frozen. |
| `can_show_chains` | ro |  | yes | return True, if this Track contains a rack instrument device that is capable of showing its chains in session view. |
| `create_audio_clip` | method |  | yes | create_audio_clip( (Track)arg1, (object)arg2, (float)arg3) -> Clip : |
| `create_midi_clip` | method |  | yes | create_midi_clip( (Track)arg1, (float)arg2, (float)arg3) -> Clip : |
| `create_take_lane` | method |  | yes | create_take_lane( (Track)arg1) -> LomObject : |
| `current_input_routing` | rw | yes | yes | Get/Set the name of the current active input routing. |
| `current_input_sub_routing` | rw | yes | yes | Get/Set the current active input sub routing. |
| `current_output_routing` | rw | yes | yes | Get/Set the current active output routing. |
| `current_output_sub_routing` | rw | yes | yes | Get/Set the current active output sub routing. |
| `duplicate_clip_slot` | method |  | yes | duplicate_clip_slot( (Track)arg1, (int)arg2) -> int : |
| `duplicate_clip_to_arrangement` | method |  | yes | duplicate_clip_to_arrangement( (Track)self, (Clip)clip, (float)destination_time) -> Clip : |
| `duplicate_device` | method |  |  | duplicate_device( (Track)arg1, (int)arg2) -> None : |
| `get_data` | method |  |  | get_data( (Track)arg1, (object)key, (object)default_value) -> object : |
| `group_track` | ro |  | yes | return the group track if is_grouped. |
| `implicit_arm` | rw | yes | yes | Arm the track for recording. When The track is implicitly armed, it showsin a weaker color in the live GUI and is not saved in the set. |
| `input_meter_left` | ro | yes | yes | Momentary value of left input channel meter, 0.0 to 1.0. For Audio Tracks only. |
| `input_meter_level` | ro | yes | yes | Return the MIDI or Audio meter value of the Tracks input, depending on the |
| `input_meter_right` | ro | yes | yes | Momentary value of right input channel meter, 0.0 to 1.0. For Audio Tracks only. |
| `insert_device` | method |  | yes | insert_device( (Track)arg1, (str)DeviceName [, (int)DeviceIndex=-1]) -> LomObject : |
| `is_frozen` | ro | yes | yes | return True if this Track is currently frozen. No changes should be applied to the track's devices or clips while it is frozen. |
| `is_part_of_selection` | ro |  | yes | return False if the track is not selected. |
| `is_showing_chains` | rw | yes | yes | Get/Set whether a track with a rack device is showing its chains in session view. |
| `jump_in_running_session_clip` | method |  | yes | jump_in_running_session_clip( (Track)arg1, (float)arg2) -> None : |
| `muted_via_solo` | ro | yes | yes | Returns true if the track is muted because another track is soloed. |
| `performance_impact` | ro | yes | yes | Reports the performance impact of this track. |
| `set_data` | method |  |  | set_data( (Track)arg1, (object)key, (object)value) -> None : |
| `take_lanes` | ro | yes | yes | returns the take lanes. |

### `Live.Track.Track.View` — 4 members, 1 exposed, 3 gaps

| member | kind | obs | M4L | Live docstring |
|---|---|---|---|---|
| `device_insert_mode` | rw | yes | yes | Get/Listen the device insertion mode of the track.  By default, it will insert devices at the end, but it can be changed to make it relative to current selection. |
| `is_collapsed` | rw | yes | yes | Get/Set/Listen if the track is shown collapsed in the arranger view. |
| `select_instrument` | method |  | yes | select_instrument( (View)arg1) -> bool : |

### `Live.MixerDevice.MixerDevice` — 11 members, 4 exposed, 7 gaps

_Reached under another address:_ `sends` → /live/track/get/send

| member | kind | obs | M4L | Live docstring |
|---|---|---|---|---|
| `crossfade_assign` | rw | yes | yes | Player- and ReturnTracks only: Access to the Track's Crossfade Assign State. |
| `crossfader` | ro |  | yes | MainTrack only: Const access to the Crossfader. |
| `left_split_stereo` | ro |  | yes | Const access to the Track's Left Split Stereo Panning Device Parameter. |
| `panning_mode` | rw | yes | yes | Access to the Track's Panning Mode. |
| `right_split_stereo` | ro |  | yes | Const access to the Track's Right Split Stereo Panning Device Parameter. |
| `song_tempo` | ro |  | yes | MainTrack only: Const access to the Song's Tempo. |
| `track_activator` | ro |  | yes | Const access to the Tracks Activator Device Parameter. |

### `Live.Clip.Clip` — 86 members, 46 exposed, 40 gaps

_Reached under another address:_ `add_new_notes` → /live/clip/add/notes; `get_all_notes_extended` → /live/clip/get/notes (no args); `get_notes` → /live/clip/get/notes (this is the deprecated tuple form); `get_notes_extended` → /live/clip/get/notes; `remove_notes` → /live/clip/remove/notes (deprecated form); `remove_notes_extended` → /live/clip/remove/notes

| member | kind | obs | M4L | Live docstring |
|---|---|---|---|---|
| `add_warp_marker` | method |  | yes | add_warp_marker( (Clip)self, (object)warp_marker) -> None : |
| `apply_note_modifications` | method |  | yes | apply_note_modifications( (Clip)arg1, (MidiNoteVector)arg2) -> None : |
| `automation_envelope` | method |  |  | automation_envelope( (Clip)arg1, (DeviceParameter)arg2) -> Envelope : |
| `automation_envelopes` | ro |  |  | Const access to a list of all automation envelopes for this clip. |
| `available_warp_modes` | ro |  | yes | Available for AudioClips only. |
| `beat_to_sample_time` | method |  |  | beat_to_sample_time( (Clip)self, (float)beat_time) -> float : |
| `clear_all_envelopes` | method |  | yes | clear_all_envelopes( (Clip)arg1) -> None : |
| `clear_envelope` | method |  | yes | clear_envelope( (Clip)arg1, (DeviceParameter)arg2) -> None : |
| `create_automation_envelope` | method |  |  | create_automation_envelope( (Clip)arg1, (DeviceParameter)arg2) -> Envelope : |
| `crop` | method |  | yes | crop( (Clip)arg1) -> None : |
| `deselect_all_notes` | method |  | yes | deselect_all_notes( (Clip)arg1) -> None : |
| `duplicate_notes_by_id` | method |  | yes | duplicate_notes_by_id( (Clip)self, (object)note_ids [, (object)destination_time=None [, (int)transposition_amount=0]]) -> IntU64Vector : |
| `duplicate_region` | method |  | yes | duplicate_region( (Clip)self, (float)region_start, (float)region_length, (float)destination_time [, (int)pitch=-1 [, (int)transposition_amount=0]]) -> None : |
| `get_notes_by_id` | method |  | yes | get_notes_by_id( (Clip)arg1, (object)note_ids) -> MidiNoteVector : |
| `get_selected_notes` | method |  | yes | get_selected_notes( (Clip)arg1) -> tuple : |
| `get_selected_notes_extended` | method |  | yes | get_selected_notes_extended( (Clip)arg1) -> MidiNoteVector : |
| `groove` | rw | yes | yes | Get the groove associated with this clip. |
| `has_envelopes` | ro | yes | yes | Will notify if the clip gets his first envelope or the last envelope is removed. |
| `is_arrangement_clip` | ro |  | yes | return true if this Clip is an Arrangement Clip. |
| `is_session_clip` | ro |  |  | return true if this Clip is a Session Clip. |
| `is_take_lane_clip` | ro |  |  | return true if this Clip is a Take Lane Clip. |
| `move_playing_pos` | method |  | yes | move_playing_pos( (Clip)arg1, (float)arg2) -> None : |
| `move_warp_marker` | method |  | yes | move_warp_marker( (Clip)self, (float)marker_beat_time, (float)beat_time_distance) -> None : |
| `note_number_to_name` | method |  |  | note_number_to_name( (Clip)self, (int)midi_pitch) -> str : |
| `quantize_pitch` | method |  | yes | quantize_pitch( (Clip)arg1, (int)arg2, (int)arg3, (float)arg4) -> None : |
| `remove_warp_marker` | method |  | yes | remove_warp_marker( (Clip)self, (float)beat_time) -> None : |
| `replace_selected_notes` | method |  | yes | replace_selected_notes( (Clip)arg1, (tuple)arg2) -> None : |
| `sample_rate` | ro |  | yes | Available for AudioClips only. |
| `sample_to_beat_time` | method |  |  | sample_to_beat_time( (Clip)self, (float)sample_time) -> float : |
| `scrub` | method |  | yes | scrub( (Clip)self, (float)scrub_position) -> None : |
| `seconds_to_sample_time` | method |  |  | seconds_to_sample_time( (Clip)self, (float)seconds) -> float : |
| `select_all_notes` | method |  | yes | select_all_notes( (Clip)arg1) -> None : |
| `select_notes_by_id` | method |  | yes | select_notes_by_id( (Clip)arg1, (object)arg2) -> None : |
| `set_fire_button_state` | method |  | yes | set_fire_button_state( (Clip)arg1, (bool)arg2) -> None : |
| `set_notes` | method |  | yes | set_notes( (Clip)arg1, (tuple)arg2) -> None : |
| `signature_denominator` | rw | yes | yes | Get/Set access to the global signature denominator of the Clip. |
| `signature_numerator` | rw | yes | yes | Get/Set access to the global signature numerator of the Clip. |
| `stop_scrub` | method |  | yes | stop_scrub( (Clip)arg1) -> None : |
| `view` | ro |  | yes | Get the view of the Clip. |
| `warp_markers` | ro | yes | yes | Available for AudioClips only. |

### `Live.Clip.Clip.View` — 6 members, 0 exposed, 6 gaps

_Whole class unexposed._ 
- **rw:** `grid_is_triplet`, `grid_quantization`
- **method:** `hide_envelope`, `select_envelope_parameter`, `show_envelope`, `show_loop`

_`*` observable, `†` not in M4L table._

### `Live.ClipSlot.ClipSlot` — 19 members, 14 exposed, 5 gaps

_Reached under another address:_ `clip` → /live/clip/*

| member | kind | obs | M4L | Live docstring |
|---|---|---|---|---|
| `color` | ro | yes | yes | Returns the canonical color for the clip slot or None if it does not exist. |
| `color_index` | ro | yes | yes | Returns the canonical color index for the clip slot or None if it does not exist. |
| `create_audio_clip` | method |  | yes | create_audio_clip( (ClipSlot)arg1, (object)arg2) -> Clip : |
| `is_recording` | ro |  | yes | Returns whether the clip associated with the slot is recording. |
| `set_fire_button_state` | method |  | yes | set_fire_button_state( (ClipSlot)arg1, (bool)arg2) -> None : |

### `Live.Scene.Scene` — 14 members, 13 exposed, 1 gaps

_Reached under another address:_ `clip_slots` → /live/clip_slot/*

| member | kind | obs | M4L | Live docstring |
|---|---|---|---|---|
| `set_fire_button_state` | method |  | yes | set_fire_button_state( (Scene)arg1, (bool)arg2) -> None : |

### `Live.Device.Device` — 15 members, 4 exposed, 11 gaps

| member | kind | obs | M4L | Live docstring |
|---|---|---|---|---|
| `can_compare_ab` | ro |  | yes | Returns true if the Device has the capability to AB compare. |
| `can_have_chains` | ro |  | yes | Returns true if the device is a rack. |
| `can_have_drum_pads` | ro |  | yes | Returns true if the device is a drum rack. |
| `class_display_name` | ro |  | yes | Return const access to the name of the device's class name as displayed in Live's browser and device chain |
| `is_active` | ro | yes | yes | Return const access to whether this device is active. This will be false bothwhen the device is off and when it's inside a rack device which is off. |
| `is_using_compare_preset_b` | rw | yes | yes | Returns whether the Device has loaded the preset in compare slot B. Only relevant if can_compare_ab, otherwise errors. |
| `latency_in_ms` | ro | yes | yes | Returns the latency of the device in ms. |
| `latency_in_samples` | ro | yes | yes | Returns the latency of the device in samples. |
| `save_preset_to_compare_ab_slot` | method |  | yes | save_preset_to_compare_ab_slot( (Device)arg1) -> None : |
| `store_chosen_bank` | method |  | yes | store_chosen_bank( (Device)arg1, (int)arg2, (int)arg3) -> None : |
| `view` | ro |  | yes | Representing the view aspects of a device. |

### `Live.DeviceParameter.DeviceParameter` — 17 members, 5 exposed, 12 gaps

| member | kind | obs | M4L | Live docstring |
|---|---|---|---|---|
| `automation_state` | ro | yes | yes | Returns state of type AutomationState. |
| `begin_gesture` | method |  |  | begin_gesture( (DeviceParameter)arg1) -> None : |
| `default_value` | ro |  | yes | Return the default value for this parameter.  A Default value is only |
| `display_value` | rw | yes | yes | Get/Set the current value (as visible in the GUI) this parameter. |
| `end_gesture` | method |  |  | end_gesture( (DeviceParameter)arg1) -> None : |
| `is_enabled` | ro |  | yes | Returns false if the parameter has been macro mapped or disabled by Max. |
| `original_name` | ro |  | yes | Returns const access the original name of this parameter, unaffected of |
| `re_enable_automation` | method |  | yes | re_enable_automation( (DeviceParameter)arg1) -> None : |
| `short_value_items` | ro |  |  | Return the list of possible values for this parameter. Like value_items, but prefers short value names if available. Raises an error if 'is_quantized' is False. |
| `state` | ro | yes | yes | Returns the state of the parameter: |
| `str_for_value` | method |  | yes | str_for_value( (DeviceParameter)arg1, (float)arg2) -> str : |
| `value_items` | ro |  | yes | Return the list of possible values for this parameter. Raises an error if 'is_quantized' is False. |

### `Live.DeviceIO.DeviceIO` — 5 members, 0 exposed, 5 gaps

_Whole class unexposed._ 
- **rw:** `default_external_routing_channel_is_none`, `routing_channel*`, `routing_type*`
- **ro:** `available_routing_channels*`, `available_routing_types*`

_`*` observable, `†` not in M4L table._

### `Live.RackDevice.RackDevice` — 37 members, 0 exposed, 37 gaps

_Whole class unexposed._ 
- **rw:** `is_showing_chains*`, `is_using_compare_preset_b*`, `name*`, `selected_variation_index`
- **ro:** `can_compare_ab`, `can_have_chains`, `can_have_drum_pads`, `can_show_chains`, `chain_selector`, `chains*`, `class_display_name`, `class_name`, `drum_pads*`, `has_drum_pads*`, `has_macro_mappings*`, `is_active*`, `latency_in_ms*`, `latency_in_samples*`, `macros_mapped*†`, `parameters*`, `return_chains*`, `type`, `variation_count*`, `view`, `visible_drum_pads*`, `visible_macro_count*`
- **method:** `add_macro`, `copy_pad`, `delete_selected_variation`, `insert_chain`, `randomize_macros`, `recall_last_used_variation`, `recall_selected_variation`, `remove_macro`, `save_preset_to_compare_ab_slot`, `store_chosen_bank`, `store_variation`

_`*` observable, `†` not in M4L table._

### `Live.RackDevice.RackDevice.View` — 5 members, 0 exposed, 5 gaps

_Whole class unexposed._ 
- **rw:** `drum_pads_scroll_position*`, `is_collapsed*`, `is_showing_chain_devices*`, `selected_chain*`, `selected_drum_pad*`

_`*` observable, `†` not in M4L table._

### `Live.Chain.Chain` — 16 members, 0 exposed, 16 gaps

_Whole class unexposed._ 
- **rw:** `color*`, `color_index*`, `is_auto_colored*`, `mute*`, `name*`, `solo*`
- **ro:** `devices*`, `has_audio_input`, `has_audio_output`, `has_midi_input`, `has_midi_output`, `mixer_device`, `muted_via_solo*`
- **method:** `delete_device`, `duplicate_device†`, `insert_device`

_`*` observable, `†` not in M4L table._

### `Live.ChainMixerDevice.ChainMixerDevice` — 4 members, 0 exposed, 4 gaps

_Whole class unexposed._ 
- **ro:** `chain_activator`, `panning`, `sends*`, `volume`

_`*` observable, `†` not in M4L table._

### `Live.DrumPad.DrumPad` — 6 members, 0 exposed, 6 gaps

_Whole class unexposed._ 
- **rw:** `mute*`, `solo*`
- **ro:** `chains*`, `name*`, `note`
- **method:** `delete_all_chains`

_`*` observable, `†` not in M4L table._

### `Live.DrumChain.DrumChain` — 19 members, 0 exposed, 19 gaps

_Whole class unexposed._ 
- **rw:** `choke_group*`, `color*`, `color_index*`, `in_note*`, `is_auto_colored*`, `mute*`, `name*`, `out_note*`, `solo*`
- **ro:** `devices*`, `has_audio_input`, `has_audio_output`, `has_midi_input`, `has_midi_output`, `mixer_device`, `muted_via_solo*`
- **method:** `delete_device`, `duplicate_device†`, `insert_device`

_`*` observable, `†` not in M4L table._

### `Live.Browser.Browser` — 21 members, 3 exposed, 18 gaps

| member | kind | obs | M4L | Live docstring |
|---|---|---|---|---|
| `audio_effects` | ro |  |  | Returns a browser item with access to all the Audio Effects content. |
| `clips` | ro |  |  | Returns a browser item with access to all the Clips content. |
| `colors` | ro |  |  | Returns a list of browser items containing the configured colors. |
| `current_project` | ro |  |  | Returns a browser item with access to all the Current Project content. |
| `drums` | ro |  |  | Returns a browser item with access to all the Drums content. |
| `filter_type` | rw | yes |  | Bang triggered when the hotswap target has changed. |
| `hotswap_target` | rw | yes |  | Bang triggered when the hotswap target has changed. |
| `instruments` | ro |  |  | Returns a browser item with access to all the Instruments content. |
| `legacy_libraries` | ro |  |  | Returns a list of browser items containing the installed legacy libraries. The list is always empty as legacy library handling has been removed. |
| `max_for_live` | ro |  |  | Returns a browser item with access to all the Max For Live content. |
| `midi_effects` | ro |  |  | Returns a browser item with access to all the Midi Effects content. |
| `packs` | ro |  |  | Returns a browser item with access to all the Packs content. |
| `plugins` | ro |  |  | Returns a browser item with access to all the Plugins content. |
| `relation_to_hotswap_target` | method |  |  | relation_to_hotswap_target( (Browser)arg1, (BrowserItem)arg2) -> Relation : |
| `samples` | ro |  |  | Returns a browser item with access to all the Samples content. |
| `sounds` | ro |  |  | Returns a browser item with access to all the Sounds content. |
| `user_folders` | ro |  |  | Returns a list of browser items containing all the user folders. |
| `user_library` | ro |  |  | Returns a browser item with access to all the User Library content. |

### `Live.Browser.BrowserItem` — 9 members, 0 exposed, 9 gaps

_Whole class unexposed._ 
- **ro:** `children†`, `is_device†`, `is_folder†`, `is_loadable†`, `is_selected†`, `iter_children†`, `name†`, `source†`, `uri†`

_`*` observable, `†` not in M4L table._

### `Live.Groove.Groove` — 6 members, 0 exposed, 6 gaps

_Whole class unexposed._ 
- **rw:** `base`, `name*`, `quantization_amount*`, `random_amount*`, `timing_amount*`, `velocity_amount*`

_`*` observable, `†` not in M4L table._

### `Live.GroovePool.GroovePool` — 1 members, 0 exposed, 1 gaps

_Whole class unexposed._ 
- **ro:** `grooves*`

_`*` observable, `†` not in M4L table._

### `Live.Sample.Sample` — 30 members, 0 exposed, 30 gaps

_Whole class unexposed._ 
- **rw:** `beats_granulation_resolution*`, `beats_transient_envelope*`, `beats_transient_loop_mode*`, `complex_pro_envelope*`, `complex_pro_formants*`, `end_marker*`, `gain*`, `slicing_beat_division*`, `slicing_region_count*`, `slicing_sensitivity*`, `slicing_style*`, `start_marker*`, `texture_flux*`, `texture_grain_size*`, `tones_grain_size*`, `warp_mode*`, `warping*`
- **ro:** `file_path*`, `length`, `sample_rate`, `slices*`, `warp_markers*`
- **method:** `beat_to_sample_time†`, `clear_slices`, `gain_display_string`, `insert_slice`, `move_slice`, `remove_slice`, `reset_slices`, `sample_to_beat_time†`

_`*` observable, `†` not in M4L table._

### `Live.TakeLane.TakeLane` — 4 members, 0 exposed, 4 gaps

_Whole class unexposed._ 
- **rw:** `name*`
- **ro:** `arrangement_clips*`
- **method:** `create_audio_clip`, `create_midi_clip`

_`*` observable, `†` not in M4L table._

### `Live.TuningSystem.TuningSystem` — 7 members, 0 exposed, 7 gaps

_Whole class unexposed._ 
- **rw:** `highest_note*`, `lowest_note*`, `name*`, `note_tunings*`, `reference_pitch*`
- **ro:** `number_of_notes_in_pseudo_octave†`, `pseudo_octave_in_cents`

_`*` observable, `†` not in M4L table._

## Device subclasses and remaining M4L classes

_Reachable only through `Live.Device.Device` today; the fork has no per-device-type addresses at all, so these are listed compactly._

### `Live.CompressorDevice.CompressorDevice` — 4 members, 0 exposed, 4 gaps (+15 inherited from `Device`, see above)

_Whole class unexposed._ 
- **rw:** `input_routing_channel*`, `input_routing_type*`
- **ro:** `available_input_routing_channels*`, `available_input_routing_types*`

_`*` observable, `†` not in M4L table._

### `Live.DriftDevice.DriftDevice` — 29 members, 0 exposed, 29 gaps (+15 inherited from `Device`, see above)

_Whole class unexposed._ 
- **rw:** `mod_matrix_filter_source_1_index*`, `mod_matrix_filter_source_2_index*`, `mod_matrix_lfo_source_index*`, `mod_matrix_pitch_source_1_index*`, `mod_matrix_pitch_source_2_index*`, `mod_matrix_shape_source_index*`, `mod_matrix_source_1_index*`, `mod_matrix_source_2_index*`, `mod_matrix_source_3_index*`, `mod_matrix_target_1_index*`, `mod_matrix_target_2_index*`, `mod_matrix_target_3_index*`, `pitch_bend_range*`, `voice_count_index*`, `voice_mode_index*`
- **ro:** `mod_matrix_filter_source_1_list`, `mod_matrix_filter_source_2_list`, `mod_matrix_lfo_source_list`, `mod_matrix_pitch_source_1_list`, `mod_matrix_pitch_source_2_list`, `mod_matrix_shape_source_list`, `mod_matrix_source_1_list`, `mod_matrix_source_2_list`, `mod_matrix_source_3_list`, `mod_matrix_target_1_list`, `mod_matrix_target_2_list`, `mod_matrix_target_3_list`, `voice_count_list`, `voice_mode_list`

_`*` observable, `†` not in M4L table._

### `Live.DrumCellDevice.DrumCellDevice` — 1 members, 0 exposed, 1 gaps (+15 inherited from `Device`, see above)

_Whole class unexposed._ 
- **rw:** `gain*`

_`*` observable, `†` not in M4L table._

### `Live.Eq8Device.Eq8Device` — 3 members, 0 exposed, 3 gaps (+15 inherited from `Device`, see above)

_Whole class unexposed._ 
- **rw:** `edit_mode*`, `global_mode*`, `oversample*`

_`*` observable, `†` not in M4L table._

### `Live.Eq8Device.Eq8Device.View` — 2 members, 0 exposed, 2 gaps

_Whole class unexposed._ 
- **rw:** `is_collapsed*`, `selected_band*`

_`*` observable, `†` not in M4L table._

### `Live.HybridReverbDevice.HybridReverbDevice` — 8 members, 0 exposed, 8 gaps (+15 inherited from `Device`, see above)

_Whole class unexposed._ 
- **rw:** `ir_attack_time*`, `ir_category_index*`, `ir_decay_time*`, `ir_file_index*`, `ir_size_factor*`, `ir_time_shaping_on*`
- **ro:** `ir_category_list`, `ir_file_list*`

_`*` observable, `†` not in M4L table._

### `Live.LooperDevice.LooperDevice` — 16 members, 0 exposed, 16 gaps (+15 inherited from `Device`, see above)

_Whole class unexposed._ 
- **rw:** `overdub_after_record*`, `record_length_index*`
- **ro:** `loop_length*`, `record_length_list`, `tempo*`
- **method:** `clear`, `double_length`, `double_speed`, `export_to_clip_slot`, `half_length`, `half_speed`, `overdub`, `play`, `record`, `stop`, `undo`

_`*` observable, `†` not in M4L table._

### `Live.MaxDevice.MaxDevice` — 8 members, 0 exposed, 8 gaps (+15 inherited from `Device`, see above)

_Whole class unexposed._ 
- **ro:** `audio_inputs*`, `audio_outputs*`, `midi_inputs*`, `midi_outputs*`
- **method:** `get_bank_count`, `get_bank_name`, `get_bank_parameters`, `get_value_item_icons†`

_`*` observable, `†` not in M4L table._

### `Live.MeldDevice.MeldDevice` — 4 members, 0 exposed, 4 gaps (+15 inherited from `Device`, see above)

_Whole class unexposed._ 
- **rw:** `mono_poly*`, `poly_voices*`, `selected_engine*`, `unison_voices*`

_`*` observable, `†` not in M4L table._

### `Live.PluginDevice.PluginDevice` — 4 members, 0 exposed, 4 gaps (+15 inherited from `Device`, see above)

_Whole class unexposed._ 
- **rw:** `is_editor_open*`, `selected_preset_index*`
- **ro:** `presets*`
- **method:** `get_parameter_names†`

_`*` observable, `†` not in M4L table._

### `Live.RoarDevice.RoarDevice` — 3 members, 0 exposed, 3 gaps (+15 inherited from `Device`, see above)

_Whole class unexposed._ 
- **rw:** `env_listen*`, `routing_mode_index*`
- **ro:** `routing_mode_list`

_`*` observable, `†` not in M4L table._

### `Live.ShifterDevice.ShifterDevice` — 3 members, 0 exposed, 3 gaps (+15 inherited from `Device`, see above)

_Whole class unexposed._ 
- **rw:** `pitch_bend_range*`, `pitch_mode_index*`
- **ro:** `pitch_mode_list†`

_`*` observable, `†` not in M4L table._

### `Live.SimplerDevice.SimplerDevice` — 21 members, 0 exposed, 21 gaps (+15 inherited from `Device`, see above)

_Whole class unexposed._ 
- **rw:** `note_pitch_bend_range*†`, `pad_slicing*`, `pitch_bend_range*†`, `playback_mode*`, `retrigger*`, `slicing_playback_mode*`, `voices*`
- **ro:** `can_warp_as*`, `can_warp_double*`, `can_warp_half*`, `multi_sample_mode*`, `playing_position*`, `playing_position_enabled*`, `sample*`
- **method:** `crop`, `guess_playback_length`, `replace_sample`, `reverse`, `warp_as`, `warp_double`, `warp_half`

_`*` observable, `†` not in M4L table._

### `Live.SimplerDevice.SimplerDevice.View` — 9 members, 0 exposed, 9 gaps

_Whole class unexposed._ 
- **rw:** `is_collapsed*`, `selected_slice*`
- **ro:** `sample_end*†`, `sample_env_fade_in*†`, `sample_env_fade_out*†`, `sample_loop_end*†`, `sample_loop_fade*†`, `sample_loop_start*†`, `sample_start*†`

_`*` observable, `†` not in M4L table._

### `Live.SpectralResonatorDevice.SpectralResonatorDevice` — 12 members, 0 exposed, 12 gaps (+15 inherited from `Device`, see above)

_Whole class unexposed._ 
- **rw:** `frequency_dial_mode*`, `midi_gate*`, `mod_mode*`, `mono_poly*`, `pitch_bend_range*`, `pitch_mode*`, `polyphony*`
- **ro:** `frequency_dial_mode_list*†`, `midi_gate_list*†`, `mod_mode_list*†`, `mono_poly_list*†`, `pitch_mode_list*†`

_`*` observable, `†` not in M4L table._

### `Live.WavetableDevice.WavetableDevice` — 20 members, 0 exposed, 20 gaps (+15 inherited from `Device`, see above)

_Whole class unexposed._ 
- **rw:** `filter_routing*`, `mono_poly*`, `oscillator_1_effect_mode*`, `oscillator_1_wavetable_category*`, `oscillator_1_wavetable_index*`, `oscillator_2_effect_mode*`, `oscillator_2_wavetable_category*`, `oscillator_2_wavetable_index*`, `poly_voices*`, `unison_mode*`, `unison_voice_count*`
- **ro:** `oscillator_1_wavetables*`, `oscillator_2_wavetables*`, `oscillator_wavetable_categories`, `visible_modulation_target_names*`
- **method:** `add_parameter_to_modulation_matrix`, `get_modulation_target_parameter_name`, `get_modulation_value`, `is_parameter_modulatable`, `set_modulation_value`

_`*` observable, `†` not in M4L table._

<!-- lom-gaps:end -->
