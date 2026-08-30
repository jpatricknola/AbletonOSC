# Fork gaps — what the installed Live API can do that this fork cannot

_Living list. A **fork gap** is a capability present in the installed Live
Object Model but with no OSC address in this repository. It is neither a
Live limit nor a Seshat tool-layer gap, and it must never be planned as UI
scripting — closing one is a handler here (one commit in this repo, one
submodule pin bump in Seshat, `mix abletonosc.install`, Live restart),
documented in `API.md` and tripwired by
Seshat's `vendored_addresses_test`._

**The goal of this repository is full Live Object Model coverage** — the
aim upstream's README states, carried on here. Every row in this file is
work to be done, and the only surface deliberately left unaddressed is what
a **safety** argument keeps out (rule 5 in
[CLOSING_THE_GAPS.md](CLOSING_THE_GAPS.md)). The path-safety rule for
handlers naming a file to read is **no longer** on that list: it was settled
and shipped with the three `create_audio_clip` / `replace_sample` addresses —
see `API.md` § "Handlers that name a file to read" and
`abletonosc/path_safety.py`. It is a rule handlers follow, not an exclusion.
No gap is out of scope for want of a
consumer asking for it; a gap not yet worth doing is a gap ranked low, and
it says so here.

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
3. Check whether Seshat already has a handler/tool for the address. Most
   "the fork can't do X" claims die here: the address exists and the missing
   layer is Seshat's. `API.md` is the address list to check against, never a
   guess from AbletonOSC naming patterns.
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
  gap up — Seshat's `/evaluate` skill (§2.3) produces these. Say what shape
  the address should take and what a caller would do with it, so a plan can
  find the prerequisite; a curated entry is a design note, not a
  justification, and a gap needs no named consumer to be worth writing up.
  Verify the member in the generated inventory (owner class, rw/ro,
  observable) before writing prose about it.
- **Add an addressing or shape entry** when you find one; the tool cannot.
  Both sections are hand-maintained.
- **Before implementing any gap**, reconcile its address rows with the Python
  source in the same change, and never infer an address name from AbletonOSC
  naming patterns — the fork's names diverge from upstream's in places.
- **Remove an entry** when the fork gains the address, in the same commit.
  Don't leave it marked done — the address docs are the record of what
  exists. The inventory drops it on the next regeneration.
- **Nothing here is prioritised.** This file is the inventory: every gap
  in it is in scope, and none of it carries an order. Sequencing into
  PR-sized buckets lives in
  [CLOSING_THE_GAPS.md](CLOSING_THE_GAPS.md); what is scheduled, and in
  what order, is [ROADMAP.md](ROADMAP.md). A gap enters `ROADMAP.md` when
  its bucket comes up the queue, ranked by impact-per-effort — not when a
  downstream feature asks for it.
- **Object-valued members** (`Song.cue_points`, `slices`, `Device.view`)
  are the usual reason a member was skipped: the generic `properties_r/rw`
  machinery serialises scalars only. Closing such a gap means a
  hand-written handler that takes or returns an index, a name, or a
  flattened tuple — say which in the entry. `Clip.groove` is the worked
  example: `/live/clip/get|set/groove` names a groove by its pool index
  (`API.md` § "Groove API").
- **History.** Seshat's former `docs/evaluating/lom-to-fork-gap-audit.md`
  (2026-07-31, deleted 2026-08-27 once folded in here; hand-written from `strings` on `LomTypes.pyc` and the
  apiref) was the first pass and has been folded into this file: what
  survives of it is the dispositions section below, its membership claims
  superseded by the generated inventory (which read ~200 members it did not
  name). Entries that say "July audit" mean that document.

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
not supported" — it took a hand-written handler to reach) or that a `†`
Remote-Script-only member does what its name suggests.

## Curated entries

### `Song.cue_points` — the remaining locator members

- **LOM:** `Song.cue_points` (list, observable), `CuePoint.name` (rw,
  observable), `.time` (ro, observable), `.jump()`; `Song.set_or_delete_cue`,
  `jump_to_next_cue`, `jump_to_prev_cue`, `can_jump_to_next_cue`/`_prev_cue`
  (observable), `is_cue_point_selected`. Tier 1 (inventory, 2026-08-27).
- **Fork today:** `/live/song/get/cue_points` → flattened `(name, time)*`;
  `/live/song/cue_point/jump <index|name>`; `/live/song/cue_point/add_or_delete`;
  `/live/song/jump_to_next_cue`, `jump_to_prev_cue`.
- **Still missing:** `start_listen/cue_points` (the list is observable, so
  a locator added in the UI could push), `can_jump_to_next_cue`/`_prev_cue`,
  `is_cue_point_selected`, `CuePoint.name` set, and per-cue `name`/`time`
  listeners — see also [Shape gaps](#songcue_points--index-keyed-no-timename-listen).
- **Consumers:** live-improv section scheduling
  (`docs/evaluating/generative features/live-improv-exploration.md` §9 said
  "not in the fork" and used scene names instead — also stale);
  arrangement-aware anything.
- **Also in:** the cue-points bucket in [CLOSING_THE_GAPS.md](CLOSING_THE_GAPS.md).

### `DrumChain.in_note` and rack chain insertion — read the Drum Rack pad map

- **LOM:** `DrumChain.in_note` get/set/observe (12.3; -1 = All Notes),
  `DrumChain.out_note`, `RackDevice.insert_chain(index)` (12.3),
  `Track.insert_device` / `Chain.insert_device` (12.3),
  `SimplerDevice.replace_sample(path)` (12.2 — now shipped for
  *top-level* Simplers as `/live/device/replace_sample`; a Simpler
  inside a drum pad's chain is still unreachable, which is what this
  entry needs). Tier 2 (Live 12.2/12.3 release notes); names verified
  2026-08-27.
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
  `slicing_playback_mode`, `sample`, `replace_sample`; and on the `Sample`
  the last of those returns, `slices` (list of times), `insert_slice`,
  `remove_slice`, `clear_slices`, `reset_slices`, `move_slice`.
  `selected_slice` is a `SimplerDevice.View` member. **The ownership
  question this entry used to raise is answered by the generated inventory
  below: the slice API belongs to `Sample`, not `SimplerDevice`** — which
  is why they are separate buckets in CLOSING_THE_GAPS.md and why `Sample`
  must ship first. **Tier 1 for the slice members** — present in 12.4.3
  `LomTypes.pyc`; the apiref page lists only `playback_mode`,
  `slicing_playback_mode` and `sample`. Signatures still want checking
  against Live's shipped Python before building.
- **Fork today:** `/live/device/replace_sample` only — shipped with the
  read-side path rule (`API.md` § "Handlers that name a file to read"), for
  a top-level Simpler on a regular track. No other Simpler-specific address.
- **Shape to build:** `playback_mode` setter, `slices` getter; Seshat would
  write the trigger clip itself from the slice times via `write_midi_notes`,
  standing in for Live's UI-only *Slice to New MIDI Track*.
- **Consumers:** "generate audio, keep it editable" output shape
  (`docs/evaluating/generative features/live-native-options.md` §2.4).

## Dispositions (from the July 2026 audit)

_Impact and architectural fit, carried over from Seshat's
`lom-to-fork-gap-audit.md` (2026-07-31) so that file can go. Not a roadmap
and not a gate: these are impact judgements that inform where a bucket
sits in [CLOSING_THE_GAPS.md](CLOSING_THE_GAPS.md), and every row below is
in scope. Rows whose fork side has landed are deleted, not marked — the
address docs are the record._

| Priority | Missing bridge surface | Why it matters | Disposition |
|---|---|---|---|
| Medium | `Song.View.draw_mode`, `follow_song` | Readable absolute state instead of focus-routed toggle shortcuts | Members of the *Object view classes* bucket, which is where they land — the per-object view resolver is the real work and these ride it. Little use as isolated knobs, so don't split them out into a PR of their own |
| Declined | `Application.press_current_dialog_button` | Would let a client dismiss a blocking Live dialog rather than only describe it | Stays out unless a separately reviewed, non-file use case proves it safe: a dialog on screen may be guarding unsaved work, and pressing its buttons blind is not recoverable. The same decision is why the two `show_*` addresses raise **OK-only** dialogs, passing Live the text and nothing else so `buttons` keeps its default |
| High | Rack chains, Drum Pads, macros, variations | Racks are how real sets are built — a Drum Rack is the standard way to hold a kit — and nothing inside one is addressable today. `ChainMixerDevice` is what keeps rack chains silent even once their devices are reachable | The largest surface in the plan (87 gaps) and the one the device path resolver exists to unlock; the resolver lands first and alone. Too large for one PR, so it is three buckets in CLOSING_THE_GAPS.md — *Rack chains and chain mixer*, *Drum racks* and *Rack macros and variations*. The pad-map read is a curated entry above |
| High | Arrangement clips and take lanes | The Arrangement is where a project is finished, and none of the 86 `Clip` members reach a clip there — only three read-only `arrangement_clips/*` fields do | The cheapest high-leverage change here: one resolver keyed `(track, arrangement_index)` reaches every `Clip` member at two further locations. Sequenced behind the device path resolver, which unblocks more |
| Low | Device-specific APIs (Simpler, Wavetable, Looper, Drift, Roar, …) | Large surface, uneven value; generic parameters already cover much | Tail work, after the shared buckets, which close the 15 inherited `Device` members once for all of them. Not one PR per class: the seven classes with four members or fewer batch into one, per the tail table in CLOSING_THE_GAPS.md |

Cautions the audit attached to individual members, kept because the
inventory's one-line docstrings do not carry them:

- `ClipSlot.create_audio_clip`, `Track.create_audio_clip`,
  `SimplerDevice.replace_sample` take absolute file paths, and **all three
  now ship** — `/live/clip_slot/create_audio_clip`,
  `/live/track/create_audio_clip`, `/live/device/replace_sample`. They
  settled the fork's read-side path rule, which is now written down rather
  than pending: the wire carries a name relative to one fixed root
  (`~/.seshat/generated`) and the handler builds the absolute path itself.
  See `API.md` § "Handlers that name a file to read" and
  `abletonosc/path_safety.py`; any further handler naming a file to read
  follows the same rule, and `/live/browser/export` remains the separate
  write-side one. No member of the LOM is left waiting on this caution.
  (The generated rows below still count these three as gaps: the inventory
  has not been regenerated since they shipped — that needs a
  `/live/application/dump_lom` from a Live running the new code.)
- `Application.View.focus_view` was previously dismissed here as overlapping
  `show_view`. That claim is disproved and is what kept the member closed:
  `show_view` makes a pane *visible*, `focus_view` gives it *keyboard focus*,
  and Live's menu-command validation reads focus, not visibility. Measured
  2026-08-30 — Create > Convert Melody to New MIDI Track stayed disabled after
  `show_view("Session")` with a clip selected over OSC, and enabled only once
  the Session grid was clicked. Shipped as `/live/view/focus_view`.
  (Its generated row below still counts it as a gap, for the same reason
  the three above are still counted: the inventory is a `dump_lom`
  artifact and is not hand-edited.)
- `Application.View.toggle_browse` is a relative toggle where absolute
  show/hide already exists. Still coverage; document the overlap on the row so
  a caller reaching for it is pointed at the absolute address instead.
  `scroll_view`/`zoom_view` have no such overlap — measure their arguments
  before writing the handler, since the apiref carries only the signature.
- `Song.appointed_device`, `groove_pool`, `tuning_system`, `tracks`,
  `scenes`, `cue_points` are objects or collections — never put them in
  the generic property loop.
- `Application.control_surfaces` is an object list, so it needs a
  hand-written flattening getter rather than the generic property loop —
  which is the whole cost of the row, since the value is session-static.

## Addressing gaps

_Members the inventory counts as exposed, but whose address resolves only
one location of the object. Hand-maintained; verified against the
registered address table 2026-08-29._

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

`/live/device/*` resolves `song.tracks[t].devices[d]` — regular tracks only.
Return and master devices have their own prefixes
(`/live/return_track/device/*`, `/live/master/device/*`) carrying five
addresses each; everything else the regular prefix answers is missing there:
`class_name`, `type`, `num_parameters`, the rich per-parameter reads
(`value_items`, `short_value_items`, `display_value`, `state`, `is_enabled`,
`automation_state`, `default_value`, `original_name`), the `parameters/*` bulk
reads including `min`/`max`/`is_quantized`, `set/parameter/display_value`,
`set/parameters/value`, the `begin_gesture`/`end_gesture` pair, and all four
listen pairs.

Nothing at all reaches devices inside a Rack (`RackDevice.chains[c].devices[d]`),
Drum Rack pads (`drum_pads[p].chains[c].devices[d]`), rack return chains, or
Max-device `DeviceIO`. Needs a recursive path form; the whole
`RackDevice`/`Chain`/`DrumPad`/`DrumChain` family in the inventory is
unreachable until it exists.

### `Track` — regular tracks get 109 addresses, return 60, master 49

`/live/track/*` is `song.tracks` only. `Track` is also every return track and
the master, reached instead through `/live/return_track/*` and
`/live/master/*` — 109 / 60 / 49 addresses respectively, measured 2026-08-29
against the live server's own registration table.

Still missing on returns/master. Most are not gaps at all — the member is
absent or meaningless on those objects, which is a Live limit to record
rather than surface to add: the clip family (`clip_slots`,
`arrangement_clips`, `stop_all_clips`, `delete_clip`, `fired_slot_index`,
`playing_slot_index` — returns have no clips), input routing (neither has
an input section in Live's UI), listen pairs for the four `has_*` reads
(constants there), and `arm` plus the master's `mute`/`solo` (absent on
those objects, measured 2026-07-31).

The regular-track-shaped remainder — `is_visible`, `is_grouped`,
`is_foldable`, `fold_state`, `can_be_armed`, `current_monitoring_state`,
`group_track` and the split `devices/*` getters — is unmeasured on returns
and master. Probe each before writing a handler: a member that exists there
is a gap to close, one that raises is a Live limit to record here. The
`devices/*` getters ride with the device path resolver, which gives those
two prefixes full device parity anyway.

### `MixerDevice` — four of eleven members, and only via `Track`

`volume`, `panning` and `sends` reach `track.mixer_device` on a regular track
and on a return; `cue_volume` reaches the master's. `Chain.mixer_device`
(`ChainMixerDevice`: volume, panning, sends, chain_activator) still has no
path, which is what makes rack chains silent even once devices are reachable;
so do `crossfade_assign`, `panning_mode`, `track_activator`, `crossfader`,
`song_tempo` and the split-stereo members.

### `Song.View` / `Application.View` — `/live/view` is a fixed set

`/live/view/*` is a fixed set of `Song.View` and `Application.View` addresses
with no per-object view resolver behind it, so `Track.View`, `Clip.View`,
`Device.View`, `RackDevice.View` and `Eq8Device.View` members are not
addressable at all. `Application.View`'s own remainder — `available_main_views`, `browse_mode` —
is a member gap on top of that. `focused_document_view` has shipped, as
`/live/view/get/focused_document_view` plus a listen pair; note what it does
*not* close, because the row in API.md is the only place that says so: Live
answers `Session` or `Arranger` and nothing else, so it cannot report that the
Browser or a Detail pane holds focus. `focus_view("Browser")` disabled the
Convert commands with this read unchanged (measured 2026-08-30). It proves
focus is on the wrong document view; it cannot prove focus is right.

`Song.View.highlighted_clip_slot` has shipped too, get and set, as the
object-valued (track, scene) coordinate — a second, independent confirmation
that a selection landed, alongside the `selected_clip` ring. The setter is
expected to be redundant with `set/selected_clip` and is carried as insurance.

(The generated member tables below still count all three as gaps, and still
carry `focus_view`: the inventory is a `dump_lom` artifact and is not
hand-edited. This prose is the record until the next dump.)

## Shape gaps

_Members the inventory counts as exposed, but whose wire form loses part
of what Live provides. Hand-maintained._

### Routing — names, not objects

`/live/track/get/available_input_routing_types` etc. return names;
`Track.input_routing_type` on the LOM is an object with `display_name`,
`category` and `attached_object`. The fork resolves by display name when
setting, so a routing whose display name is not unique (two identically
named external instruments, two tracks called "Drums") is ambiguous. A
stable identifier would need the object or its index. Resolution failure is also
**silent** on `/live/track/set/{input,output}_routing_{type,channel}`: a name
absent from the available list is logged to Live's Log.txt and nothing goes on
the wire, so a caller cannot distinguish a rejected name from a lost datagram
without reading the value back. Recorded in the API.md rows rather than fixed —
these are conventionally silent setters — but it is a shape gap all the same.

### `Song.cue_points` — index-keyed, no time/name listen

`/live/song/get/cue_points` and `cue_point/jump`, `cue_point/add_or_delete`
exist (see curated entry). `CuePoint.name`/`time` are observable in Live;
the fork cannot listen to a cue moving or being renamed, and the index
shifts when one is deleted. An ID or name-keyed form is the shape fix.

### Groove Pool dump — `base` excluded

`/live/song/get/groove_pool` flattens five fields per groove and leaves `base`
out. The reason was protective — its wire type was unverified, and the OSC
builder drops an entire reply it cannot encode, so a surprise in `base` would
have taken the whole pool read down with it. Measured against Live 12.4.5 on
2026-08-29 the surprise did not materialise: `base` reads as a plain string
(`gb_sixteen` on a stock "Swing 16ths 66") and encodes cleanly. The exclusion
is now conservatism rather than protection, and it stays only because moving a
field into the dump is a wire-contract change. Folding it in is the shape fix.

### `Clip.groove` — the "no groove" read is gated, but the gate is unverified

`/live/clip/get/groove` answers `-1` when `Clip.has_groove` is false, without
consulting `Clip.groove` at all (`clip_groove_index` in
`abletonosc/groove.py`). That replaced an `==` scan over the pool, which could
only ever answer an index — so "no groove" and "pool index `0`" were the same
value on the wire, and replaying a read of an ungrooved clip *assigned* it pool
groove 0. Live never hands back `None` for `Clip.groove`; the companion flag is
the discriminator, which is why the flag exists at all.

⚠️ **Evidence tier: assumed, not measured.** That `has_groove` is false for a
clip Live's UI shows as ungrooved is Live's own documented contract ("Returns
true if a groove is associated with this clip", LOM, since Live 11.0), but this
fork has never seen it answer `False`. The one reading taken (Live 12.4.5,
2026-08-29) was on a freshly created clip, which reported `has_groove = True`
in a pool holding one groove — consistent with the clip genuinely holding pool
groove 0, and equally consistent with the flag being true for every clip.
Separating the two needs a pool holding **two** grooves and a UI-confirmed
ungrooved clip; grooves cannot be added to the pool over this bridge (no
`Browser.grooves` root, and `GroovePool` has no add — see § "Loading an `.agr`
groove file into the pool"), so it needs a human at Live's UI. Until that runs,
the gap stays open: the code is right under either reading, and the *claim* is
not yet evidence. `API.md` § "Groove API" carries the same ⚠️.

**The setter half is not a gap here.** `/live/clip/set/groove` can assign but
never un-assign, because Live's setter refuses `NoneType` (measured) and the
LOM documents no other spelling for "no groove" (searched). That is a layer-1
Live limit, not a fork shape gap; it lives in `API.md` § "Groove API",
"Assignment is one-way", and in `SESHAT.md`. The `-1` argument that once
claimed to clear has been withdrawn.

## Residual member gaps

_Single members left open beside a family that is otherwise complete — each a
deliberate stop, not an oversight. The generated inventory lists them like any
other gap; this section carries the reason so a plan need not re-derive it._

### `Clip.notes` has no listener

`add_notes_listener` exists on `Live.Clip.Clip`; the fork registers no
`/live/clip/start_listen/notes`. A client mirroring a clip's contents has to
re-read after every edit it makes, and cannot see an edit made in Live's UI at
all. The push *shape* is the open question, not the subscription: the
nine-field flattened group of `/live/clip/get/notes_extended` is large, and
resending the whole clip on every note edit is the naive answer.

### `Clip` envelopes — the flag ships, the contents do not

`has_envelopes` has shipped, as `/live/clip/get/has_envelopes` plus a listen
pair. It is the whole of the envelope surface for now. The rest of the family —
`automation_envelope`, `automation_envelopes`, `create_automation_envelope`,
`clear_envelope`, `clear_all_envelopes` — is in the LOM and stays unexposed,
listed in the generated table below like any other gap. They are not blocked,
only unclaimed: each is keyed by a `DeviceParameter`, which the fork can already
name as a `(track, device, parameter)` triple (see `track_identity.py`), so an
address is buildable. What is missing is the measurement — a `DeviceParameter`
addresses *device automation*, and **whether any spelling of these reaches a MIDI
clip's pitch-bend or CC lanes is unmeasured**. Until someone measures it,
importing a file through `/live/browser/load_item` is the only route by which
envelope data is known to reach a clip, and `has_envelopes` is the only way to
see that it did — it answers "something is there" and nothing about what or
where.

(The generated table below still counts `has_envelopes` as a gap: the inventory
is a `dump_lom` artifact and is not hand-edited. This prose is the record until
the next dump.)

### `DeviceParameter` — `re_enable_automation` and three listen pairs

Two things are missing beside an otherwise complete parameter surface: the
**`re_enable_automation` mutation**, held back because it belongs with an
automation-shaped item rather than a description one, and **listen pairs** on
the three observable members `state`, `automation_state` and `display_value` —
Live offers an `add_<name>_listener` for each, and
`device_get_parameter_value_listener` is the pattern to copy.

### `Application` — listen pairs for `unavailable_features` and `control_surfaces`

Both are observable, but session-static in practice (edition and preferences),
and a push needs a custom flattening getter because both replies are flattened
lists. Get-only until a consumer appears; a five-line follow-up when one does.

### `Device.view`

The one object-valued member the object-read pattern did not reach. An ordinary
addressing gap rather than a shape gap: it needs the per-object view resolver
described under
[`Song.View` / `Application.View`](#songview--applicationview--liveview-is-a-fixed-set),
not a new reply shape.

### `Groove.base` has no listen pair

Live offers no `add_base_listener` — `base` is the one non-observable member of
`Live.Groove.Groove` — so this is a Live limit, not a fork gap.
`/live/groove/start_listen/base` is deliberately **not registered**: an address
that could only ever answer `AttributeError` is worse than an unknown one.
Recorded here so the asymmetry is not read as an oversight and "fixed".

### Loading an `.agr` groove file into the pool

Unmeasured, and the one part of the groove work that did not close. The LOM has
no `Browser.grooves` root and `packs` is not one of `browser.py`'s exposed
categories, so `.agr` files may not be reachable through this bridge at all
today. It decides whether the ~3,000 grooves shipped with Live can be used
without a human dragging one in. A "no" makes exposing `packs` the fix — it is
already inside the browser-tree bucket in
[CLOSING_THE_GAPS.md](CLOSING_THE_GAPS.md) — not a widening of the groove
family.

### `Song.sync_parameter_changes` — registered, behaviour unknown

The address exists; what it does is not known. Remote-Script-only, absent from
Max for Live's table, and Live's docstring is the signature alone. Not a gap —
a measurement owed before any consumer relies on it.

## Generated inventory

<!-- lom-gaps:begin -->
_Generated by `tools/lom_gaps.py` from a `/live/application/dump_lom` taken against Live 12.4.5. Do not edit by hand; rerun the tool. 134 Live classes walked, 774 fork addresses registered._

**Totals:** 280 members exposed, 419 gaps across 44 classes.

Legend: **rw**/**ro** property, **method**; **obs** = Live offers an `add_<name>_listener` (a `start_listen` address is possible); **M4L** = also in Max for Live's `LomTypes` exposure table (members absent there are Remote-Script-only and undocumented in the apiref). Every row is tier 1 evidence (name and kind read from the running Live); nothing here has been called.

## Core classes

### `Live.Song.Song` — 96 members, 90 exposed, 6 gaps

_Reached under another address:_ `get_current_beats_song_time` → /live/song/get/current_song_time; `master_track` → /live/master/*; `view` → /live/view/*

| member | kind | obs | M4L | Live docstring |
|---|---|---|---|---|
| `can_jump_to_next_cue` | ro | yes | yes | Returns true when there is a cue marker right to the playing pos that |
| `can_jump_to_prev_cue` | ro | yes | yes | Returns true when there is a cue marker left to the playing pos that |
| `get_data` | method |  |  | get_data( (Song)arg1, (object)key, (object)default_value) -> object : |
| `is_cue_point_selected` | method |  | yes | is_cue_point_selected( (Song)arg1) -> bool : |
| `set_data` | method |  |  | set_data( (Song)arg1, (object)key, (object)value) -> None : |
| `tuning_system` | ro | yes | yes | Access the currently active tuning system. |

### `Live.Song.Song.View` — 11 members, 7 exposed, 4 gaps

| member | kind | obs | M4L | Live docstring |
|---|---|---|---|---|
| `draw_mode` | rw | yes | yes | Get/Set if the Envelope/Note draw mode is enabled. |
| `follow_song` | rw | yes | yes | Get/Set if the Arrangerview should scroll to show the playmarker. |
| `highlighted_clip_slot` | rw |  | yes | Get/Set the clip slot, defined via the selected track and scene in the Session.Will be None for Main- and Sendtracks. |
| `select_device` | method |  | yes | select_device( (View)arg1, (Device)arg2 [, (bool)ShouldAppointDevice=True]) -> None : |

### `Live.Song.CuePoint` — 3 members, 0 exposed, 3 gaps

_Whole class unexposed._ 
- **rw:** `name*`
- **ro:** `time*`
- **method:** `jump`

_`*` observable, `†` not in M4L table._

### `Live.Application.Application` — 21 members, 19 exposed, 2 gaps

_Reached under another address:_ `browser` → /live/browser/*; `get_bugfix_version` → /live/application/get/bugfix_version; `get_build_id` → /live/application/get/build_id; `get_major_version` → /live/application/get/version; `get_minor_version` → /live/application/get/version; `get_variant` → /live/application/get/variant; `get_version_string` → /live/application/get/version_string; `view` → /live/view/*

| member | kind | obs | M4L | Live docstring |
|---|---|---|---|---|
| `get_document` | method |  | yes | get_document( (Application)arg1) -> Song : |
| `press_current_dialog_button` | method |  | yes | press_current_dialog_button( (Application)arg1, (int)arg2) -> None : |

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

### `Live.Track.Track` — 69 members, 43 exposed, 26 gaps

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
| `implicit_arm` | rw | yes | yes | Arm the track for recording. When The track is implicitly armed, it showsin a weaker color in the live GUI and is not saved in the set. |
| `input_meter_left` | ro | yes | yes | Momentary value of left input channel meter, 0.0 to 1.0. For Audio Tracks only. |
| `input_meter_level` | ro | yes | yes | Return the MIDI or Audio meter value of the Tracks input, depending on the |
| `input_meter_right` | ro | yes | yes | Momentary value of right input channel meter, 0.0 to 1.0. For Audio Tracks only. |
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

### `Live.Clip.Clip` — 86 members, 58 exposed, 28 gaps

_Reached under another address:_ `add_new_notes` → /live/clip/add/notes, /live/clip/add/notes_extended; `get_all_notes_extended` → /live/clip/get/notes, /live/clip/get/notes_extended (no args); `get_notes` → /live/clip/get/notes (this is the deprecated tuple form); `get_notes_extended` → /live/clip/get/notes, /live/clip/get/notes_extended; `get_selected_notes` → /live/clip/get/selected_notes; `get_selected_notes_extended` → /live/clip/get/selected_notes_extended; `remove_notes` → /live/clip/remove/notes (deprecated form); `remove_notes_extended` → /live/clip/remove/notes

| member | kind | obs | M4L | Live docstring |
|---|---|---|---|---|
| `add_warp_marker` | method |  | yes | add_warp_marker( (Clip)self, (object)warp_marker) -> None : |
| `automation_envelope` | method |  |  | automation_envelope( (Clip)arg1, (DeviceParameter)arg2) -> Envelope : |
| `automation_envelopes` | ro |  |  | Const access to a list of all automation envelopes for this clip. |
| `available_warp_modes` | ro |  | yes | Available for AudioClips only. |
| `beat_to_sample_time` | method |  |  | beat_to_sample_time( (Clip)self, (float)beat_time) -> float : |
| `clear_all_envelopes` | method |  | yes | clear_all_envelopes( (Clip)arg1) -> None : |
| `clear_envelope` | method |  | yes | clear_envelope( (Clip)arg1, (DeviceParameter)arg2) -> None : |
| `create_automation_envelope` | method |  |  | create_automation_envelope( (Clip)arg1, (DeviceParameter)arg2) -> Envelope : |
| `crop` | method |  | yes | crop( (Clip)arg1) -> None : |
| `duplicate_region` | method |  | yes | duplicate_region( (Clip)self, (float)region_start, (float)region_length, (float)destination_time [, (int)pitch=-1 [, (int)transposition_amount=0]]) -> None : |
| `is_arrangement_clip` | ro |  | yes | return true if this Clip is an Arrangement Clip. |
| `is_session_clip` | ro |  |  | return true if this Clip is a Session Clip. |
| `is_take_lane_clip` | ro |  |  | return true if this Clip is a Take Lane Clip. |
| `move_playing_pos` | method |  | yes | move_playing_pos( (Clip)arg1, (float)arg2) -> None : |
| `move_warp_marker` | method |  | yes | move_warp_marker( (Clip)self, (float)marker_beat_time, (float)beat_time_distance) -> None : |
| `note_number_to_name` | method |  |  | note_number_to_name( (Clip)self, (int)midi_pitch) -> str : |
| `quantize_pitch` | method |  | yes | quantize_pitch( (Clip)arg1, (int)arg2, (int)arg3, (float)arg4) -> None : |
| `remove_warp_marker` | method |  | yes | remove_warp_marker( (Clip)self, (float)beat_time) -> None : |
| `sample_rate` | ro |  | yes | Available for AudioClips only. |
| `sample_to_beat_time` | method |  |  | sample_to_beat_time( (Clip)self, (float)sample_time) -> float : |
| `scrub` | method |  | yes | scrub( (Clip)self, (float)scrub_position) -> None : |
| `seconds_to_sample_time` | method |  |  | seconds_to_sample_time( (Clip)self, (float)seconds) -> float : |
| `set_fire_button_state` | method |  | yes | set_fire_button_state( (Clip)arg1, (bool)arg2) -> None : |
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

### `Live.DeviceParameter.DeviceParameter` — 17 members, 15 exposed, 2 gaps

| member | kind | obs | M4L | Live docstring |
|---|---|---|---|---|
| `re_enable_automation` | method |  | yes | re_enable_automation( (DeviceParameter)arg1) -> None : |
| `str_for_value` | method |  | yes | str_for_value( (DeviceParameter)arg1, (float)arg2) -> str : |

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

### `Live.Groove.Groove` — 6 members, 6 exposed, 0 gaps

_No gaps._

### `Live.GroovePool.GroovePool` — 1 members, 1 exposed, 0 gaps

_Reached under another address:_ `grooves` → /live/song/get/groove_pool, /live/groove/*

_No gaps._

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
