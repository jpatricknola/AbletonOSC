# Closing the gaps — plan of attack for FORK_GAPS.md

_Companion to [FORK_GAPS.md](FORK_GAPS.md). That file is the inventory and
is never prioritised; this file is the sequencing. It groups the member
gaps, the addressing gaps and the shape gaps into PR-sized buckets so a
single PR ships a coherent batch instead of one address at a time. Against
the 2026-08-29 inventory that is **419 member gaps across 44 classes**, plus
five addressing gaps and four shape gaps._

Buckets are named, not numbered. FORK_GAPS.md points at three of them by
name — the [cue-points bucket](FORK_GAPS.md#songcue_points--the-remaining-locator-members),
the [view bucket](FORK_GAPS.md#songview--applicationview--liveview-is-a-fixed-set)
and the [browser-tree bucket](FORK_GAPS.md#loading-an-agr-groove-file-into-the-pool)
— so a name here is a cross-reference and changing one breaks that file.

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

Device-specific classes (Drift, Wavetable, Looper, …) are deferred, per
the Conditional dispositions in FORK_GAPS.md: a PR when a feature names
one, never blanket parity work.

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
   the fork's path-safety rule. All three live in one bucket so the rule
   is reviewed once.
5. `press_current_dialog_button` stays out — Declined in the dispositions
   until a separately reviewed, non-file use case proves it safe.
6. Same commit: add addresses, document them in `API.md`, delete the
   FORK_GAPS entries, regenerate the inventory.
7. Resolver buckets ship no scalar padding. They are the riskiest changes
   here (a dispatch refactor each) and must be reviewable alone.
8. A member whose only remaining gap is a **listen pair** is not an
   inventory row — its getter already exists. Those ride along with the
   bucket owning the getter, never a PR of their own.

## Resolvers — land first

Both are declined in FORK_GAPS's dispositions until a workflow needs the
payoff. They are listed first because everything under *Object families*
depends on the first one, not because they are scheduled.

| Bucket | Scope | Unlocks |
|---|---|---|
| **Device path resolver** | `/live/device/*` (and the `return_track` / `master` device prefixes) accept a track kind plus a chain path — `<track> <device> [chain <c> device <d>]…`, or one path string. Reaches `RackDevice.chains[c].devices[d]`, `drum_pads[p].chains[c].devices[d]`, rack return chains and Max `DeviceIO`. | The whole rack family (87 gaps, written in *Racks, chains and drum pads*), and device parity on returns and master: `class_name`, `type`, `num_parameters`, the rich per-parameter reads, the `parameters/*` bulk reads with `min`/`max`/`is_quantized`, `set/parameter/display_value`, `set/parameters/value`, the gesture pair and all four listen pairs. Closes the [Device addressing gap](FORK_GAPS.md#device--deviceparameter--top-level-devices-only). |
| **Arrangement and take-lane clip resolver** | A second clip resolver keyed `(track, arrangement_index)` and `(track, take_lane, index)`; `Clip.is_arrangement_clip` / `is_session_clip` / `is_take_lane_clip`; the four `TakeLane` members; `Track.take_lanes`, `create_take_lane`, `duplicate_clip_to_arrangement`. | 10 member gaps directly, and all 86 `Clip` members at a second and third location. Closes the [Clip addressing gap](FORK_GAPS.md#clip--session-clips-only). Cheapest place to build the resolver even though Arrangement is Conditional/declined; it can wait behind the device resolver if no consumer exists. |

## Shape buckets

The wire form is the review subject, so one bucket each.

| Bucket | Scope |
|---|---|
| **Cue points keyed and observable** | `start_listen/cue_points`, per-cue `name`/`time` listeners, `CuePoint.name` set, `CuePoint.jump`, `can_jump_to_next_cue`/`_prev_cue` (get + listen), `is_cue_point_selected`. Name- or ID-keyed so deleting a locator does not shift the key. Six member gaps — the whole `CuePoint` class plus three on `Song`. Closes the [curated entry](FORK_GAPS.md#songcue_points--the-remaining-locator-members) and the [shape gap](FORK_GAPS.md#songcue_points--index-keyed-no-timename-listen). This is the bucket the curated entry names. |
| **Routing as stable identifiers** | Expose routing objects by index alongside their display names (`display_name`, `category`, `attached_object`); setters accept an index. Covers `Track.current_input_routing` / `current_output_routing` and both `sub_routing` members, which the inventory still counts as gaps because the fork answers only the legacy string API — and which are ambiguous today whenever two routings share a display name. Closes the [Routing shape gap](FORK_GAPS.md#routing--names-not-objects). |
| **Groove Pool `base` in the dump** | Fold `base` into `/live/song/get/groove_pool` as a sixth field and register `/live/groove/get/base` against the measured type. The protective reason is gone — measured 2026-08-29, `base` is a plain string (`gb_sixteen`) that encodes cleanly — so what is left is a wire-contract change to a reply Seshat already parses, which is why it stands alone. `/live/groove/start_listen/base` stays unregistered: [that asymmetry is deliberate](FORK_GAPS.md#groovebase-has-no-listen-pair), not an oversight to fix. Closes the [shape gap](FORK_GAPS.md#groove-pool-dump--base-excluded). |
| **Clip notes listener** | `/live/clip/start_listen/notes` over Live's `add_notes_listener`. The subscription is five lines; **the push shape is the whole PR**. Resending the clip's full nine-field `notes_extended` group on every edit is the naive answer — decide between that and a bare "contents changed" ping the client follows with a read, before writing the handler. Closes the [residual entry](FORK_GAPS.md#clipnotes-has-no-listener). |

Not a bucket: **`Clip.groove`'s unreachable `-1`**. Recorded as a shape gap
but owned by the roadmap defect "The clip↔groove assignment contract is
broken in both directions", which carries the diagnosis and the two
separable fixes. FORK_GAPS says explicitly not to plan against that
paragraph.

## Member buckets by owning class

Mostly generic-loop additions, one bucket per class or view family.

| Bucket | Scope | Gaps |
|---|---|---|
| **View classes** | A per-object view resolver is the substance; the members are cheap once it exists. `Song.View`: `draw_mode`, `follow_song`, `highlighted_clip_slot`, `select_device`. `Application.View`: `focused_document_view` (High in the dispositions — the exact Session-vs-Arranger read `/live/view` cannot give), `available_main_views`, `browse_mode`; `focus_view`, `scroll_view`, `zoom_view` and `toggle_browse` only with a user story, per the cautions. `Track.View`: `is_collapsed`, `device_insert_mode`, `select_instrument`. `Clip.View`: `grid_quantization`, `grid_is_triplet`, the envelope show/hide four. Plus `Device.view`, `RackDevice.View`, `Eq8Device.View`. Closes the [View addressing gap](FORK_GAPS.md#songview--applicationview--liveview-is-a-fixed-set) and the [`Device.view` residual](FORK_GAPS.md#deviceview). This is the bucket the dispositions table names. | 28 |
| **`Track` remainder** | `is_frozen`, `can_be_frozen`, `back_to_arranger`, `implicit_arm`, `muted_via_solo`, `performance_impact`, `input_meter_left/right/level`, `is_part_of_selection`, `can_show_chains`, `is_showing_chains`, `create_midi_clip`, `duplicate_clip_slot`, `duplicate_device`, `jump_in_running_session_clip`, `get_data`/`set_data`. (`create_audio_clip` → *Simpler and Sample*, rule 4. The take-lane trio → clip resolver. The four `current_*_routing` → *Routing as stable identifiers*.) | 22 |
| **`Clip` / `ClipSlot` / `Scene` remainder** | Warp markers (`warp_markers`, `add`/`move`/`remove_warp_marker`, `available_warp_modes`, `sample_rate`), envelopes (`automation_envelopes`, `automation_envelope`, `create_automation_envelope`, `clear_envelope`, `clear_all_envelopes`, `has_envelopes`), `crop`, `duplicate_region`, `quantize_pitch`, `signature_numerator`/`denominator`, `scrub`/`stop_scrub`, `move_playing_pos`, the beat/sample/seconds conversions, `note_number_to_name`, `set_fire_button_state` on all three classes; `ClipSlot.color`, `color_index`, `is_recording`. The envelope members are object-valued — an `Envelope` keyed by a `DeviceParameter` — so they need a designed reply under rule 3, and they are the reason this bucket may want splitting. (`ClipSlot.create_audio_clip` → *Simpler and Sample*; `Clip.view` → *View classes*; the three `is_*_clip` flags → clip resolver.) | 30 |
| **`Device` / `MixerDevice` remainder** | `Device`: `is_active`, `latency_in_ms`/`_samples`, `class_display_name`, `can_have_chains`, `can_have_drum_pads`, `can_compare_ab`, `is_using_compare_preset_b`, `save_preset_to_compare_ab_slot`, `store_chosen_bank`. `MixerDevice`: `crossfade_assign` and `panning_mode` are scalars; `crossfader`, `track_activator`, `left`/`right_split_stereo` and `song_tempo` are each a `DeviceParameter`, so they follow the object-read pattern, and `crossfader`/`song_tempo` exist on the Main track only. Closes the [`MixerDevice` addressing gap](FORK_GAPS.md#mixerdevice--four-of-eleven-members-and-only-via-track) for regular tracks; `ChainMixerDevice` stays behind the device resolver. | 17 |
| **Parameter automation follow-ups** | `DeviceParameter.re_enable_automation`, held back from the parameter-description work because it is a mutation belonging with automation-shaped work, plus listen pairs on the three observable members `state`, `automation_state` and `display_value`, copying `device_get_parameter_value_listener`. Pairs naturally with the clip-envelope members above if the two land together. Closes the [residual entry](FORK_GAPS.md#deviceparameter--re_enable_automation-and-three-listen-pairs). | 1 |
| **`Application` listen pairs** | `unavailable_features` and `control_surfaces` — observable, but session-static in practice, and each push needs a custom flattening getter. Rule 8 applies: this exists only once a consumer asks, or riding along with another `Application`-touching change. Closes the [residual entry](FORK_GAPS.md#application--listen-pairs-for-unavailable_features-and-control_surfaces). | 0 |

## Object families

Each needs the device path resolver first.

| Bucket | Scope | Gaps |
|---|---|---|
| **Racks, chains and drum pads** | The addresses written over the resolver. `RackDevice` (chains, return chains, macros, variations, `insert_chain`), `Chain`, `ChainMixerDevice` (volume, panning, sends, chain_activator — the members that keep rack chains silent even once devices are reachable), `DrumPad`, `DrumChain` including the curated [pad-map read](FORK_GAPS.md#drumchainin_note-and-rack-chain-insertion--read-the-drum-rack-pad-map): `/live/device/get/drum_pads <track> <device>` → `(chain_index, in_note, name)*`, with `in_note`/`out_note` setters for building a kit programmatically. `DeviceIO`. Large enough to split by class if the resolver lands with room to spare. | 87 |
| **Browser tree** | `Browser` roots (`instruments`, `sounds`, `drums`, `audio_effects`, `midi_effects`, `max_for_live`, `plugins`, `clips`, `samples`, `packs`, `user_library`, `user_folders`, `current_project`, `legacy_libraries`, `colors`), `BrowserItem` traversal, `filter_type`, `hotswap_target`, `relation_to_hotswap_target`. Also settles [loading an `.agr` into the Groove Pool](FORK_GAPS.md#loading-an-agr-groove-file-into-the-pool) — there is no `Browser.grooves` root, so if `.agr` files are reachable at all it is through `packs`, which this bucket already exposes. Measure that first: a "no" is a Live limit worth recording, not a reason to widen the groove family. This is the bucket that residual entry names. | 27 |
| **Simpler and Sample** | The curated [slicing entry](FORK_GAPS.md#simplerdevice-slicing--slice-a-loaded-sample-from-the-bridge): `playback_mode`, `slicing_playback_mode`, `slices`, `insert`/`remove`/`clear`/`reset`/`move_slice`, `selected_slice`, `sample`, `Sample.*`, `SimplerDevice.View`. Verify each slice member's owner and signature in Live's shipped Python first — the apiref lists only three of them. Also the home for every path-taking handler under rule 4: `replace_sample`, `Track.create_audio_clip`, `ClipSlot.create_audio_clip`. | 62 |
| **Tuning system and set data** | `TuningSystem` (whole class), `Song.tuning_system` (object-valued — index- or name-keyed, never the generic loop), `Song.get_data`/`set_data`. Small; stands alone unless a bucket it fits inside is already open. | 10 |

## Measurement, not addresses

No new addresses. These close ⚠️ marks on contracts already shipped, and
each is cheap enough to fold into any PR that runs a Live session anyway.
Listed so they are not mistaken for gaps.

| Bucket | Scope |
|---|---|
| **Open measurements** | `Song.sync_parameter_changes` — [registered, behaviour unknown](FORK_GAPS.md#songsync_parameter_changes--registered-behaviour-unknown); Remote-Script-only, absent from Max for Live's table, docstring is the signature alone. `move_device` and `find_device_position`, unmeasured because the verification set had no track carrying a device. The `count_in_duration` index and the `TimeFormat` int mappings, accepted and echoed but never decoded. And the values behind the `Application` getters whose OK paths log nothing — those replies go to a port this machine cannot bind, so this one needs a free reply port or a temporary logging patch before it can run at all. |

## Deferred — device-specific classes

Not scheduled. One PR each, only when a feature names it; *Simpler and
Sample* sets the pattern for a device subclass PR. 117 gaps:

`DriftDevice` (29), `WavetableDevice` (20), `LooperDevice` (16),
`SpectralResonatorDevice` (12), `HybridReverbDevice` (8), `MaxDevice` (8),
`CompressorDevice` (4), `MeldDevice` (4), `PluginDevice` (4),
`Eq8Device` (3, its `View` in *View classes*), `RoarDevice` (3),
`ShifterDevice` (3), `DrumCellDevice` (1). Each also inherits the 15
`Device` members, which the device resolver and the `Device` remainder
bucket cover once for all of them.

## Count

| | Buckets | Gaps closed |
|---|---|---|
| Named buckets above | 15 | 300 of 419, plus every addressing and shape gap |
| Deferred device classes | ~13 | 117 |
| **Full parity** | **~28** | 419 |

The two members in neither row are `Application.get_document` — a false
gap, `self.song` *is* the document — and `press_current_dialog_button`,
declined under rule 5.

## Tracking

Update this file when a bucket lands: strike the row, note the PR. When a
section is empty, delete it. Regenerate the FORK_GAPS inventory in the
same commit so the two files never disagree on what is open, and check the
three buckets FORK_GAPS names still exist under those names.
