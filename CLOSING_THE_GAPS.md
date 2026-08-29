# Closing the gaps — plan of attack for FORK_GAPS.md

_Companion to [FORK_GAPS.md](FORK_GAPS.md). That file is the inventory and
is never prioritised; this file is the sequencing. It groups the member
gaps, the addressing gaps and the shape gaps into PR-sized buckets so a
single PR ships a coherent batch instead of one address at a time. Against
the 2026-08-29 inventory that is **419 member gaps across 44 classes**, plus
five addressing gaps and four shape gaps._

**The goal is full Live Object Model coverage.** Every bucket below is
scheduled work; the order is impact-per-effort, most valuable first, and
the tail is genuinely last rather than out of scope. The only surface that
stays permanently unaddressed is what a safety argument keeps out, and that
is rule 5 alone. Rule 4 is not an exclusion: the path-taking handlers are
scheduled work — ranked on the roadmap — and the rule constrains the shape
of their handlers, not whether they get written. A bucket is never held
back for want of a downstream consumer requesting it.

Buckets are named, not numbered. FORK_GAPS.md points at four of them by
name — *Cue points keyed and observable*, *Object view classes*, *Browser
tree* and the three rack buckets — so a name here is a cross-reference and
renaming one means editing that file in the same commit. The named
entry points are the [cue-points bucket](FORK_GAPS.md#songcue_points--the-remaining-locator-members),
the [view bucket](FORK_GAPS.md#songview--applicationview--liveview-is-a-fixed-set)
and the [browser-tree bucket](FORK_GAPS.md#loading-an-agr-groove-file-into-the-pool).

## Why buckets, not one PR per gap

Every PR that closes a gap carries the same fixed overhead: handlers,
`API.md` rows, removing the FORK_GAPS entries in the same commit,
regenerating the inventory, a Seshat submodule pin bump and the
`vendored_addresses_test` tripwire. Batching amortises that. The three gap
kinds have very different cost profiles:

- **Member gaps** on scalars ride the generic `properties_r/rw` loop.
  Cheap. Batch by owning class.
- **Addressing gaps** are unlocked by a *resolver*, not by members. One
  device-path resolver opens `RackDevice` (37) + `Chain` (16) +
  `ChainMixerDevice` (4) + `DrumPad` (6) + `DrumChain` (19) + `DeviceIO`
  (5) — 87 gaps — and a second clip resolver makes all 86 `Clip` members
  reachable at Arrangement and take-lane locations. Resolvers land first
  and land alone.
- **Shape gaps** need a hand-written handler with a designed wire form.
  One bucket each, so the shape is the review subject.

Device-specific classes (Drift, Wavetable, Looper, …) are tail work,
ranked after the shared buckets because the device path resolver and the
`Device` remainder close the 15 inherited `Device` members once for all of
them. Ordered last, not excluded.

### How big a bucket may be

**One bucket is one PR.** A bucket that cannot ship as a single reviewable
PR is mis-scoped and must be split before it is planned.

The ceiling is calibrated against what this fork has actually merged: the
*Song remainder* PR (#21) closed **25 members with 58 addresses**, and is
the largest comfortable review this repository has done. So:

- **Up to ~25 members** of generic-loop scalars is one PR.
- **Fewer — 10 to 15 —** when the members are hand-written: object-valued
  replies under rule 3, a designed wire form, or a resolver in the same
  change.
- **A class with more members than that is its own bucket**, and a class
  larger than the ceiling splits by *member family* (`RackDevice` splits
  into chains, drum pads and macros), never by arbitrary halves.

The member counts on each row below are **sizing estimates for splitting,
not inventory figures**. [FORK_GAPS.md](FORK_GAPS.md) is the count of
record; where a row and the regenerated inventory disagree, the inventory
is right and the row is stale.

Two things a bucket must never be:

- **A bucket smaller than a PR.** A one- or zero-member item is a
  ride-along under rule 8, not a bucket. Those are listed under *Not
  buckets* below rather than given a row that implies a PR.
- **A bucket holding members that close for free.** `RackDevice` counts 13
  `Device`-generic members (`name`, `class_name`, `type`, `parameters`,
  `is_active`, the two `latency_*`, the compare-A/B trio, `store_chosen_bank`,
  `view`); a `RackDevice` *is* a `Device`, so those answer the moment the
  device path resolver can address one. They are inventory rows, not work,
  and no bucket below claims them.

## Rules that apply to every bucket

1. Read the member's row in the generated inventory before writing a
   handler: owner class, rw/ro, observable, M4L column.
2. Members marked Remote-Script-only (no M4L) are undocumented — probe
   them through the rig in [API.md](API.md) ("Measuring the Live API
   without building the feature first") before committing to a shape.
3. Object-valued members never enter the generic property loop —
   FORK_GAPS names `Song.cue_points`, `appointed_device`, `groove_pool`,
   `tuning_system`, `tracks`, `scenes`, `slices`, `Device.view`.
   Hand-written, taking or returning an index, a name or a flattened
   tuple; say which in the PR.
4. Handlers taking an absolute filesystem path (`Track.create_audio_clip`,
   `ClipSlot.create_audio_clip`, `SimplerDevice.replace_sample`) follow
   the fork's path-safety rule, which constrains their shape and does not
   keep them out. Note what the rule cannot be here: `/live/browser/export`
   answers the hazard by naming the destination itself, which works only
   because no caller cared what the file was called. These three are the
   opposite — Live's signature takes the path as the *subject* of the call
   (`create_audio_clip((Track), (object)path, (float)position)`), and the
   caller is choosing which file. They are also reads rather than writes,
   so traversal and clobber, the concerns `export` removed, do not apply
   in the same form. The bucket must therefore decide a shape rather than
   copy one: a rooted allowlist (`realpath` the argument, require it under
   a declared root set, reject otherwise with `export`'s error shape) is
   the presumed answer, with a `BrowserItem.uri` form alongside it if
   measurement shows a URI resolves to a filesystem path. Settle the root
   set against a stated consumer use case — there is none on record yet.
   All three ship together so the shape is reviewed once, as their own
   roadmap item rather than inside the `Sample` or `SimplerDevice` bucket.
5. `press_current_dialog_button` is the one exception to the coverage goal
   and it is a **safety** exception, not a scheduling one: a dialog on
   screen may be guarding unsaved work, and pressing its buttons blind is
   not recoverable. Stays out until a separately reviewed, non-file use
   case proves it safe.
6. Same commit: add addresses, document them in `API.md`, delete the
   FORK_GAPS entries, regenerate the inventory.
7. Resolver buckets ship no scalar padding. They are the riskiest changes
   here (a dispatch refactor each) and must be reviewable alone.
8. A member whose only remaining gap is a **listen pair** is not an
   inventory row — its getter already exists. Those ride along with the
   bucket owning the getter, never a PR of their own.

## Resolvers — land first

Both lead the queue. Everything under *Object families* depends on the
first, and the second reaches every `Clip` member at two further locations
for one resolver's work — the best impact-per-effort on this page. They are
also the two riskiest changes here (rule 7), so each ships alone.

| Bucket | Scope | Unlocks |
|---|---|---|
| **Device path resolver** | `/live/device/*` (and the `return_track` / `master` device prefixes) accept a track kind plus a chain path — `<track> <device> [chain <c> device <d>]…`, or one path string. Reaches `RackDevice.chains[c].devices[d]`, `drum_pads[p].chains[c].devices[d]`, rack return chains and Max `DeviceIO`. | The whole rack family (87 gaps, written in *Racks, chains and drum pads*), and device parity on returns and master: `class_name`, `type`, `num_parameters`, the rich per-parameter reads, the `parameters/*` bulk reads with `min`/`max`/`is_quantized`, `set/parameter/display_value`, `set/parameters/value`, the gesture pair and all four listen pairs. Closes the [Device addressing gap](FORK_GAPS.md#device--deviceparameter--top-level-devices-only). |
| **Arrangement and take-lane clip resolver** | A second clip resolver keyed `(track, arrangement_index)` and `(track, take_lane, index)`; `Clip.is_arrangement_clip` / `is_session_clip` / `is_take_lane_clip`; the four `TakeLane` members; `Track.take_lanes`, `create_take_lane`, `duplicate_clip_to_arrangement`. | 10 member gaps directly, and all 86 `Clip` members at a second and third location. Closes the [Clip addressing gap](FORK_GAPS.md#clip--session-clips-only). Cheapest place to build the resolver; sequenced behind the device path resolver only because that one unblocks more. |

## Shape buckets

The wire form is the review subject, so one bucket each.

| Bucket | Scope |
|---|---|
| **Cue points keyed and observable** | `start_listen/cue_points`, per-cue `name`/`time` listeners, `CuePoint.name` set, `CuePoint.jump`, `can_jump_to_next_cue`/`_prev_cue` (get + listen), `is_cue_point_selected`. Name- or ID-keyed so deleting a locator does not shift the key. Six member gaps — the whole `CuePoint` class plus three on `Song`. Closes the [curated entry](FORK_GAPS.md#songcue_points--the-remaining-locator-members) and the [shape gap](FORK_GAPS.md#songcue_points--index-keyed-no-timename-listen). This is the bucket the curated entry names. |
| **Routing as stable identifiers** | Expose routing objects by index alongside their display names (`display_name`, `category`, `attached_object`); setters accept an index. Covers `Track.current_input_routing` / `current_output_routing` and both `sub_routing` members, which the inventory still counts as gaps because the fork answers only the legacy string API — and which are ambiguous today whenever two routings share a display name. Closes the [Routing shape gap](FORK_GAPS.md#routing--names-not-objects). |
| **Groove Pool `base` in the dump** | Fold `base` into `/live/song/get/groove_pool` as a sixth field and register `/live/groove/get/base` against the measured type. The protective reason is gone — measured 2026-08-29, `base` is a plain string (`gb_sixteen`) that encodes cleanly — so what is left is a wire-contract change to a reply Seshat already parses, which is why it stands alone. `/live/groove/start_listen/base` stays unregistered: [that asymmetry is deliberate](FORK_GAPS.md#groovebase-has-no-listen-pair), not an oversight to fix. Closes the [shape gap](FORK_GAPS.md#groove-pool-dump--base-excluded). |
| **Clip automation envelopes** | `automation_envelopes`, `automation_envelope`, `create_automation_envelope`, `clear_envelope`, `clear_all_envelopes`, `has_envelopes`, plus `DeviceParameter.re_enable_automation` and the listen pairs on `state`, `automation_state` and `display_value`. **Split out of the `Clip` remainder, where it was the reason that bucket was oversized.** An `Envelope` is object-valued and keyed by a `DeviceParameter`, so under rule 3 it needs a designed reply — which makes it a shape bucket, not a member one. The parameter-side follow-ups belong here rather than in a bucket of their own: they are automation-shaped and too few to ship alone. Seven members, and the envelope shape is the review subject. Closes the [`DeviceParameter` residual](FORK_GAPS.md#deviceparameter--re_enable_automation-and-three-listen-pairs). |
| **Clip notes listener** | `/live/clip/start_listen/notes` over Live's `add_notes_listener`. The subscription is five lines; **the push shape is the whole PR**. Resending the clip's full nine-field `notes_extended` group on every edit is the naive answer — decide between that and a bare "contents changed" ping the client follows with a read, before writing the handler. Closes the [residual entry](FORK_GAPS.md#clipnotes-has-no-listener). |

Not a bucket: **`Clip.groove`'s `-1`**. The read is now gated on Live's own
`Clip.has_groove` rather than an `==` scan, and the `-1` argument to
`/live/clip/set/groove` has been withdrawn — assignment is one-way, which is a
Live limit and not a shape this fork can close. What is left is a
*verification* gap, not a code one: this fork has never seen `has_groove`
answer `False`, and confirming it needs a two-groove pool and a UI-confirmed
ungrooved clip, i.e. a human at Live's UI rather than a PR. It stays recorded
in [FORK_GAPS](FORK_GAPS.md) for that reason.

## Member buckets by owning class

Mostly generic-loop additions. One class per bucket unless the class is
too small to fill a PR or too large to fit one.

| Bucket | Scope | ~Members |
|---|---|---|
| **Object view classes** | The per-object view resolver is the substance; the members are cheap once it exists. `Song.View`: `draw_mode`, `follow_song`, `highlighted_clip_slot`, `select_device`. `Application.View`: `focused_document_view` (High in the dispositions — the exact Session-vs-Arranger read `/live/view` cannot give), `available_main_views`, `browse_mode`, `focus_view`, `scroll_view`, `zoom_view`, `toggle_browse` — per the cautions, document `focus_view`/`toggle_browse` as overlapping the absolute `show_view`/`hide_view` pair, and measure the two `*_view` argument forms before writing them. `Track.View`: `is_collapsed`, `device_insert_mode`, `select_instrument`. `Clip.View`: `grid_quantization`, `grid_is_triplet`, the envelope show/hide four; plus the `Clip.view` member itself. Closes the [View addressing gap](FORK_GAPS.md#songview--applicationview--liveview-is-a-fixed-set). This is the bucket the dispositions table names. | 21 |
| **`Track` remainder** | `is_frozen`, `can_be_frozen`, `back_to_arranger`, `implicit_arm`, `muted_via_solo`, `performance_impact`, `input_meter_left/right/level`, `is_part_of_selection`, `can_show_chains`, `is_showing_chains`, `create_midi_clip`, `duplicate_clip_slot`, `duplicate_device`, `jump_in_running_session_clip`, `get_data`/`set_data`. (`create_audio_clip` is ranked on the roadmap under rule 4. The take-lane trio → clip resolver. The four `current_*_routing` → *Routing as stable identifiers*.) | 22 |
| **`Clip` warp markers and sample time** | `warp_markers`, `add`/`move`/`remove_warp_marker`, `available_warp_modes`, `sample_rate`, and the three conversions `beat_to_sample_time`, `sample_to_beat_time`, `seconds_to_sample_time`. **Split out of the `Clip` remainder**: a warp marker is object-valued, so the list read and the add/move/remove arguments are a designed shape under rule 3, and reviewing that shape next to a pile of scalars buries it. The audio-clip-only members also want a Live session with a warped audio clip to verify, which the scalar half does not. | 9 |
| **`Clip` / `ClipSlot` / `Scene` scalars and methods** | What is left once envelopes and warp markers leave: `crop`, `duplicate_region`, `quantize_pitch`, `signature_numerator`/`denominator`, `scrub`/`stop_scrub`, `move_playing_pos`, `note_number_to_name`, `set_fire_button_state` on all three classes, and `ClipSlot.color`, `color_index`, `is_recording`. Generic loop and thin methods throughout. (`ClipSlot.create_audio_clip` is ranked on the roadmap; `Clip.view` → *Object view classes*; the three `is_*_clip` flags → clip resolver.) | 15 |
| **`Device` / `MixerDevice` remainder** | `Device`: `is_active`, `latency_in_ms`/`_samples`, `class_display_name`, `can_have_chains`, `can_have_drum_pads`, `can_compare_ab`, `is_using_compare_preset_b`, `save_preset_to_compare_ab_slot`, `store_chosen_bank`. `MixerDevice`: `crossfade_assign` and `panning_mode` are scalars; `crossfader`, `track_activator`, `left`/`right_split_stereo` and `song_tempo` are each a `DeviceParameter`, so they follow the object-read pattern, and `crossfader`/`song_tempo` exist on the Main track only. Closes the [`MixerDevice` addressing gap](FORK_GAPS.md#mixerdevice--four-of-eleven-members-and-only-via-track) for regular tracks; `ChainMixerDevice` stays behind the device resolver. Ship this before the rack buckets: it is what makes `RackDevice`'s 13 `Device`-generic rows close for free. | 17 |
| **Tuning system and set data** | `TuningSystem` (whole class), `Song.tuning_system` (object-valued — index- or name-keyed, never the generic loop), `Song.get_data`/`set_data`. | 10 |

## Object families — each needs the device path resolver first

The rack family was one 87-member bucket and is split here by member
family, which is also how `RackDevice` divides internally.

| Bucket | Scope | ~Members |
|---|---|---|
| **Rack chains and chain mixer** | `Chain` in full (`name`, `color`/`color_index`, `is_auto_colored`, `mute`/`solo`/`muted_via_solo`, `devices`, the four `has_*_input`/`output` flags, `mixer_device`, `insert_device`, `delete_device`, `duplicate_device`), `ChainMixerDevice` (`volume`, `panning`, `sends`, `chain_activator` — the members that keep rack chains silent even once their devices are reachable), and `RackDevice`'s chain-side members: `chains`, `return_chains`, `insert_chain`, `chain_selector`, `can_have_chains`, `can_show_chains`, `is_showing_chains`. | 27 |
| **Drum racks** | `DrumChain` in full (`in_note`/`out_note`, `choke_group`, and the `Chain`-shaped remainder) and `DrumPad` (`note`, `chains`, `name`, `mute`/`solo`, `delete_all_chains`), plus `RackDevice`'s pad-side members: `drum_pads`, `visible_drum_pads`, `has_drum_pads`, `can_have_drum_pads`, `copy_pad`. Carries the curated [pad-map read](FORK_GAPS.md#drumchainin_note-and-rack-chain-insertion--read-the-drum-rack-pad-map): `/live/device/get/drum_pads <track> <device>` → `(chain_index, in_note, name)*`, with `in_note`/`out_note` setters for building a kit programmatically. Ships after *Rack chains*, whose `Chain` shape it reuses. | 30 |
| **Rack macros and variations** | `RackDevice`'s macro and variation half: `selected_variation_index`, `variation_count`, `visible_macro_count`, `has_macro_mappings`, `macros_mapped`, `add_macro`, `remove_macro`, `randomize_macros`, `store_variation`, `recall_selected_variation`, `recall_last_used_variation`, `delete_selected_variation`. Independent of the chain and pad halves — it touches no chain addressing — so it can ship in any order among the three. | 12 |
| **Device view classes** | The view classes that need a device address, split from *Object view classes* for that reason alone: `Device.view`, `RackDevice.View` (`selected_chain`, `selected_drum_pad`, `is_collapsed`, `is_showing_chain_devices`, `drum_pads_scroll_position`), `SimplerDevice.View` (`selected_slice`, `is_collapsed`, and the seven read-only sample markers), `Eq8Device.View`. Closes the [`Device.view` residual](FORK_GAPS.md#deviceview). | 17 |
| **Browser tree** | `Browser` roots (`instruments`, `sounds`, `drums`, `audio_effects`, `midi_effects`, `max_for_live`, `plugins`, `clips`, `samples`, `packs`, `user_library`, `user_folders`, `current_project`, `legacy_libraries`, `colors`), `BrowserItem` traversal (`children`, `iter_children`, `name`, `uri`, `source`, `is_device`, `is_folder`, `is_loadable`, `is_selected`), `filter_type`, `hotswap_target`, `relation_to_hotswap_target`. Also settles [loading an `.agr` into the Groove Pool](FORK_GAPS.md#loading-an-agr-groove-file-into-the-pool) — there is no `Browser.grooves` root, so if `.agr` files are reachable at all it is through `packs`. Measure that first: a "no" is a Live limit worth recording, not a reason to widen the groove family. `BrowserItem.source` is the member to measure for the roadmap's audio-clip item — if it yields a filesystem path, a URI form becomes possible there. Needs no device resolver; listed here because it is an object-tree traversal like the rest. | 27 |
| **`Sample`** | The whole class, and **the owner of the slice API** — the inventory settles the open question the curated entry raised: `slices`, `insert_slice`, `move_slice`, `remove_slice`, `reset_slices` and `clear_slices` are `Sample` members, not `SimplerDevice` ones. Also the warp members (`warping`, `warp_mode`, `warp_markers`), the marker pair, `gain`/`gain_display_string`, `file_path`, `length`, `sample_rate`, the four slicing controls (`slicing_style`, `slicing_beat_division`, `slicing_region_count`, `slicing_sensitivity`), the granulation and texture sets, and the two beat/sample conversions. At the ceiling on its own; do not add to it. | 30 |
| **`SimplerDevice`** | `playback_mode`, `slicing_playback_mode`, `pad_slicing`, `multi_sample_mode`, `voices`, `retrigger`, the two pitch-bend ranges, `playing_position` and `playing_position_enabled`, `sample` (object-valued — returns the `Sample` the bucket above exposes, so ship that one first), the warp trio `warp_as`/`warp_double`/`warp_half` with their three `can_*` reads, `crop`, `reverse`, `guess_playback_length`. `replace_sample` is not here: it is ranked on the roadmap with the two `create_audio_clip` members under rule 4. | 20 |

The former *Simpler and Sample* bucket was 62 members. It is now three
buckets — *`Sample`*, *`SimplerDevice`* and the `SimplerDevice.View` share
of *Device view classes* — plus the three path-taking handlers ranked on
the roadmap. Nothing left it; it was only ever three PRs wearing one name.

## Not buckets — ride-alongs and measurement

Neither of these is a PR, and neither has a row above. They are recorded
here so nobody plans one as though it were a bucket.

| Item | Why it is not a bucket | Where it lands |
|---|---|---|
| **`Application` listen pairs** | `unavailable_features` and `control_surfaces` are observable but session-static in practice, and each push needs a custom flattening getter. Rule 8: their getters already exist, so they are not inventory rows and cannot fill a PR. Closes the [residual entry](FORK_GAPS.md#application--listen-pairs-for-unavailable_features-and-control_surfaces). | The next `Application`-touching change. |
| **Open measurements** | No new addresses at all — these close ⚠️ marks on contracts already shipped. `Song.sync_parameter_changes`, [registered but unmeasured](FORK_GAPS.md#songsync_parameter_changes--registered-behaviour-unknown), Remote-Script-only and absent from Max for Live's table. `move_device` and `find_device_position`, unmeasured because the verification set had no track carrying a device. The `count_in_duration` index and the `TimeFormat` int mappings, accepted and echoed but never decoded. And the values behind the `Application` getters whose OK paths log nothing — those replies go to a port this machine cannot bind, so this one needs a free reply port or a temporary logging patch before it can run at all. | Any PR that already runs a Live session. |
| **`RackDevice`'s `Device`-generic rows** | 13 inventory rows that are `Device` members on a `RackDevice`: `name`, `class_name`, `class_display_name`, `type`, `parameters`, `is_active`, `latency_in_ms`/`_samples`, `can_compare_ab`, `is_using_compare_preset_b`, `save_preset_to_compare_ab_slot`, `store_chosen_bank`, `view`. A `RackDevice` *is* a `Device`, so they answer as soon as the resolver can address one and the `Device` remainder has shipped. Work already counted elsewhere. | Closes with *Device path resolver* + *`Device` / `MixerDevice` remainder*. |

## Tail — device-specific classes

Last in the queue, not outside it, and **not one PR per class** — seven of
the thirteen classes have four members or fewer, which is under a PR, so
they batch. Each class also inherits the 15 `Device` members, which the
device resolver and the `Device` remainder close once for all of them.

| Bucket | Classes | ~Members |
|---|---|---|
| **`DriftDevice`** | The largest device subclass; its own PR. | 29 |
| **`WavetableDevice`** | Its own PR. | 20 |
| **`LooperDevice`** | Its own PR. Transport-shaped members, so it wants a Live session more than the others. | 16 |
| **Spectral Resonator and Hybrid Reverb** | `SpectralResonatorDevice` (12) + `HybridReverbDevice` (8). Neither fills a PR alone; both are plain parameter surfaces. | 20 |
| **Max for Live devices** | `MaxDevice` (8) + `DeviceIO` (5). `DeviceIO` is Max's I/O surface and is meaningless without `MaxDevice`, so it moves here out of the rack family, where it only ever sat because the resolver reaches it. | 13 |
| **Small device classes** | `CompressorDevice` (4), `MeldDevice` (4), `PluginDevice` (4), `Eq8Device` (3, its `View` in *Device view classes*), `RoarDevice` (3), `ShifterDevice` (3), `DrumCellDevice` (1). Seven classes of parameter scalars, one generic loop, one PR. Split only if review shows it running long. | 22 |

## Count

One row per bucket, one bucket per PR.

| Section | PRs | ~Members |
|---|---|---|
| Resolvers | 2 | 10 |
| Shape buckets | 5 | 18 |
| Member buckets | 6 | 94 |
| Object families | 7 | 163 |
| Tail — device classes | 6 | 120 |
| Ranked on the roadmap (rule 4 path handlers) | 1 | 3 |
| **Full coverage** | **27** | **419** |

**27 PRs, down from the ~28 buckets the previous count named — but the
previous figure counted a 62-member bucket and an 87-member bucket as one
PR each.** The bucket count barely moves because splitting the four
oversized buckets is offset by merging the sub-PR items away: the
`Application` listen pairs, the lone `DeviceParameter` follow-up and the
seven tiny device classes no longer hold rows of their own.

The **PR column is exact** — it is this file's own decision. The
**member column is estimates**, and it sums a little above the 417 real
gaps because a few members are described in two rows' prose: the four
`Track.current_*_routing` members are counted in `Track`'s inventory and
discussed under *Routing as stable identifiers*, and `Clip.view` is
counted on `Clip` and discussed under *Object view classes*. Neither is
work done twice. [FORK_GAPS.md](FORK_GAPS.md) remains the count of record.

Everything here is in scope; the split is order, not inclusion. The two
members in no bucket are `Application.get_document` — a false gap,
`self.song` *is* the document — and `press_current_dialog_button`, the one
address held out on safety grounds under rule 5. Full coverage means 417
of 419.

## Tracking

Update this file when a bucket lands: strike the row, note the PR. When a
section is empty, delete it. Regenerate the FORK_GAPS inventory in the
same commit so the two files never disagree on what is open, and check the
three buckets FORK_GAPS names still exist under those names.
