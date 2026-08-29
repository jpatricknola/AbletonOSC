# Closing the gaps — plan of attack for FORK_GAPS.md

_Companion to [FORK_GAPS.md](FORK_GAPS.md). That file is the inventory and
is never prioritised; this file is the sequencing. It groups the 494 member
gaps, the addressing gaps and the shape gaps into PR-sized buckets so a
single PR ships a coherent batch instead of one address at a time._

_The ranked queue of what to do next — mixing these buckets with
[issues.md](issues.md) — is [ROADMAP.md](ROADMAP.md)._

## Why buckets, not one PR per gap

Every PR that closes a gap carries the same fixed overhead: handlers,
`API.md` rows, removing the FORK_GAPS entries in the same commit,
regenerating the inventory, a Seshat submodule pin bump and the
`vendored_addresses_test` tripwire. Batching amortises that. More
importantly, the three gap kinds have very different cost profiles:

- **Scalar member gaps** (Song, Track, Application, Clip flags) ride the
  generic `properties_r/rw` loop. Cheap. Batch by owning class.
- **Addressing gaps** are unlocked by a *resolver*, not by members. One
  device-path resolver opens `RackDevice` (37) + `Chain` (16) +
  `ChainMixerDevice` (4) + `DrumPad` (6) + `DrumChain` (19) + `DeviceIO`
  (5) — 87 gaps — and the Arrangement clip resolver makes all 86 `Clip`
  members reachable at a second location. These must land first and land
  alone.
- **Shape gaps** need hand-written handlers with a designed wire form.
  Each is its own PR so the shape can be reviewed on its own.

Device-specific classes (Drift, Wavetable, Looper, …) are deferred, per
the "Conditional" dispositions in FORK_GAPS.md: they get a PR when a
feature needs them, never as blanket parity work.

## Rules that apply to every PR

1. Read the member's row in the generated inventory before writing a
   handler: owner class, rw/ro, observable, M4L column.
2. Members marked Remote-Script-only (no M4L) are undocumented — probe
   them through the rig in [API.md](API.md) ("Measuring the Live API
   without building the feature first") before committing to a shape.
3. Object-valued members (`groove`, `group_track`, `appointed_device`,
   `cue_points`, `tracks`, `scenes`, `tuning_system`) never enter the
   generic property loop. Hand-written, index- or name-keyed.
4. Handlers that take a filesystem path (`create_audio_clip`,
   `replace_sample`) follow the fork's path-safety rule; they live only in
   the bucket that owns them (D-4) so the rule is reviewed once.
5. `press_current_dialog_button` stays out unless a separately reviewed,
   non-file use case proves safe — a dialog may guard unsaved work.
6. Same commit: add addresses, document them in `API.md`, delete the
   FORK_GAPS entries, regenerate the inventory.
7. Resolver PRs (A-1, A-2) ship no scalar padding. They are the riskiest
   changes in the plan (dispatch refactor) and must be reviewable alone.

## Tier A — foundations (resolvers)

Land first, in order. Everything in Tier D depends on A-1; A-4 has landed.

| PR | Scope | Unlocks |
|---|---|---|
| **A-1** Device path resolver | `/live/device/*` (and `return_track`/`master` device addresses) accept a track kind plus a chain path, e.g. `<track> <device> [chain <c> device <d>]…` or a single path string. Reaches `RackDevice.chains[c].devices[d]`, `drum_pads[p].chains[c].devices[d]`, rack return chains, Max `DeviceIO`. | Whole `RackDevice` / `Chain` / `DrumPad` / `DrumChain` / `ChainMixerDevice` / `DeviceIO` family; device parity on returns and master (`class_name`, `type`, `parameters/min|max|is_quantized`, listeners). Closes the [Device addressing gap](FORK_GAPS.md#device--deviceparameter--top-level-devices-only). |
| **A-2** Arrangement and take-lane clip resolver | Second clip resolver keyed `(track, arrangement_index)` and `(track, take_lane, index)`; `Clip.is_arrangement_clip` / `is_session_clip` / `is_take_lane_clip`; `TakeLane` members; `Track.take_lanes`, `create_take_lane`, `duplicate_clip_to_arrangement`. | All 86 `Clip` members at Arrangement locations. Closes the [Clip addressing gap](FORK_GAPS.md#clip--session-clips-only). Note: FORK_GAPS marks Arrangement as "Conditional / declined until a workflow is chosen"; this PR is still the cheapest place to build the resolver, and it can wait behind A-1 if no consumer exists yet. |
| ~~**A-3** Return / master `Track` parity~~ | ~~Bring `/live/return_track/*` and `/live/master/*` up to the regular-track address set: colour, routing, meters, `has_*_input/output`, every `start_listen`, `insert_device`, `mixer_device.sends` on returns. Prefer a shared track resolver over three copies of the handler table.~~ | Landed 2026-08-29, branch `feat/return-master-track-parity`. Closed [Return/master `Track` parity](FORK_GAPS.md#returnmaster-track-parity--closed-2026-08-29) (now `FORK_GAPS.md` § Closed); address counts 108/30/21 → 109/60/49. Devices inside racks and the remaining master/return omissions stay open under the [Track addressing gap](FORK_GAPS.md#track--regular-tracks-get-109-addresses-return-60-master-49) and the [`MixerDevice` gap](FORK_GAPS.md#mixerdevice--four-of-eleven-members-and-only-via-track). |
| ~~**A-4** Object-valued read helpers~~ | ~~Index-returning handlers for `Song.master_track`, `Song.appointed_device` (get/set/listen), `Track.group_track`, `ClipSlot.clip`, `Song.View.selected_chain`, `selected_parameter`, `mod_mapping_device/parameter`. Establishes the pattern (index or `-1`) used by every later object read.~~ | Landed 2026-08-27, branch `object-valued-read-helpers`. Closed [Object-valued reads returned as `None`](FORK_GAPS.md#object-valued-reads-returned-as-none) (now `FORK_GAPS.md` § Closed). `Song.master_track` shipped out of scope — see `ROADMAP.md` § Deliberately not planned. |

## Tier B — shape fixes

One PR each; the wire form is the review subject.

| PR | Scope |
|---|---|
| ~~**B-1** Notes extended~~ | ~~`/live/clip/get/notes_extended` and `/live/clip/add/notes_extended` carrying `note_id`, `probability`, `velocity_deviation`, `release_velocity`; old five-field addresses unchanged. Then the ID-keyed members: `apply_note_modifications`, `get_notes_by_id`, `duplicate_notes_by_id`, `select_notes_by_id`, plus `get_selected_notes(_extended)`, `select_all_notes`, `deselect_all_notes`, `replace_selected_notes`, `set_notes`.~~ Landed 2026-08-29, branch `feat/notes-extended`. Closed [Notes shape gap](FORK_GAPS.md#notes--flattened-to-five-fields--closed-2026-08-29) and the roadmap "Modify a note in place". |
| ~~**B-2** DeviceParameter rich reply~~ | ~~One richer `parameters` reply plus per-parameter addresses: `value_items`, `short_value_items`, `display_value` (get/set), `state`, `is_enabled`, `automation_state`, `default_value`, `original_name`, `begin_gesture`/`end_gesture`.~~ Landed 2026-08-29, branch `feat/device-parameter-rich-reply`. Closed [Device parameters shape gap](FORK_GAPS.md#device-parameters--numeric-only) (now `FORK_GAPS.md` § Closed). `str_for_value` was already shipped before this PR, as `/live/device/get/parameter/value_string`. |
| **B-3** Cue points keyed and observable | `start_listen/cue_points`, per-cue `name`/`time` listeners, `CuePoint.name` set, `can_jump_to_next_cue`/`_prev_cue` (get + listen), `is_cue_point_selected`. Name- or ID-keyed form so deletion does not shift the key. Closes the [curated entry](FORK_GAPS.md#songcue_points--the-remaining-locator-members) and the [shape gap](FORK_GAPS.md#songcue_points--index-keyed-no-timename-listen). |
| **B-4** Routing as stable identifiers | Expose routing objects by index alongside display names (`display_name`, `category`, `attached_object`); setters accept an index. `Track.current_*_routing` / `sub_routing`. Closes [Routing shape gap](FORK_GAPS.md#routing--names-not-objects). |

## Tier C — scalar batches by owning class

Mostly generic-loop additions. Each PR is one class (or one view family).
C-1 has landed.

| PR | Scope |
|---|---|
| ~~**C-1** `Song` remainder~~ | ~~`count_in_duration`, `is_counting_in`, `session_automation_record`, `re_enable_automation_enabled`, `scale_mode`, `scale_intervals`, `tempo_follower_enabled`, `is_ableton_link_start_stop_sync_enabled`, `start_time`, `last_event_time`, `file_path`, `exclusive_arm`, `exclusive_solo`, `select_on_launch`, `can_capture_midi`, `overdub`, `visible_tracks`, `scrub_by`, `play_selection`, `get_beats_loop_start/length`, `get_current_smpte_song_time`, `move_device`, `find_device_position`, `sync_parameter_changes`.~~ Landed 2026-08-29, branch `feat/song-remainder`. Closed the [`Song` remainder](FORK_GAPS.md#song-remainder--closed-2026-08-29) (now `FORK_GAPS.md` § Closed); fifty-eight addresses across the twenty-five members listed. |
| **C-2** View classes | `Song.View`: `draw_mode`, `follow_song`, `highlighted_clip_slot`, `select_device`. `Application.View`: `focused_document_view`, `available_main_views`, `browse_mode`, `focus_view`, `scroll_view`, `zoom_view`, `toggle_browse` (last four only with a user story — see dispositions). `Track.View`: `is_collapsed`, `device_insert_mode`, `select_instrument`. `Clip.View`, `Device.View`, `RackDevice.View`, `Eq8Device.View` via a per-object view resolver. Closes the [View addressing gap](FORK_GAPS.md#songview--applicationview--liveview-is-a-fixed-set). |
| ~~**C-3** `Application`~~ | ~~Dialog reads only: `open_dialog_count`, `current_dialog_message`, `current_dialog_button_count` (listen where observable). `get_bugfix_version`, `get_build_id`, `get_variant`, `get_version_string`, `has_option`, `peak_process_usage`, `unavailable_features`, `number_of_push_apps_running`, `show_message`, `show_on_the_fly_message`, `control_surfaces` (names only).~~ Landed 2026-08-29, branch `application-dialogs-and-versions`. Closed [Application dialogs and versions](FORK_GAPS.md#application-dialogs-and-versions--closed-2026-08-29) (now `FORK_GAPS.md` § Closed). Also removed `issues.md`'s "Remove the unsolicited average-process-usage startup datagram" entry in the same commit. |
| **C-4** `Track` remainder | `is_frozen`, `can_be_frozen`, `back_to_arranger`, `implicit_arm`, `muted_via_solo`, `performance_impact`, `input_meter_left/right/level`, `is_part_of_selection`, `can_show_chains`, `is_showing_chains`, `create_midi_clip`, `duplicate_clip_slot`, `duplicate_device`, `jump_in_running_session_clip`, `get_data`/`set_data`. (`create_audio_clip` → D-4, path rule.) |
| **C-5** `Clip` / `ClipSlot` / `Scene` remainder | Warp markers (`warp_markers`, `add/move/remove_warp_marker`, `available_warp_modes`, `sample_rate`), envelopes (`automation_envelopes`, `automation_envelope`, `create_automation_envelope`, `clear_envelope`, `clear_all_envelopes`, `has_envelopes`), `crop`, `duplicate_region`, `quantize_pitch`, `signature_numerator/denominator`, `scrub`/`stop_scrub`, `move_playing_pos`, `beat/sample/seconds` time conversions, `note_number_to_name`, `set_fire_button_state` on Clip, ClipSlot and Scene; `ClipSlot.color`, `color_index`, `is_recording`. (`ClipSlot.create_audio_clip` → D-4.) |
| **C-6** `Device` / `MixerDevice` remainder | `Device`: `is_active`, `latency_in_ms/samples`, `class_display_name`, `can_have_chains`, `can_have_drum_pads`, `can_compare_ab`, `is_using_compare_preset_b`, `save_preset_to_compare_ab_slot`, `store_chosen_bank`. `MixerDevice`: `crossfade_assign`, `crossfader`, `panning_mode`, `track_activator`, `left/right_split_stereo`, `song_tempo`. |

## Tier D — object families

Each depends on A-1 (path resolver). A-4 (object-read pattern) has landed and
is available to use directly — see `API.md` § "Object-valued reads".

| PR | Scope |
|---|---|
| **D-1** Racks, chains, drum pads | `RackDevice` (chains, return chains, macros, variations, `insert_chain`), `Chain`, `ChainMixerDevice` (volume, panning, sends, chain_activator), `DrumPad`, `DrumChain` incl. the curated [pad-map read](FORK_GAPS.md#drumchainin_note-and-rack-chain-insertion--read-the-drum-rack-pad-map): `/live/device/get/drum_pads` → `(chain_index, in_note, name)*`, `in_note`/`out_note` setters. `DeviceIO`. |
| **D-2** Groove | `/live/song/get/groove_pool` → indexed names and amounts; `Groove.*` amounts get/set; `/live/clip/get|set/groove` by pool index or `-1`. Measure whether `browser.load_item` can load an `.agr` into the pool. Closes the curated [`Clip.groove`](FORK_GAPS.md#clipgroove--assign-a-groove-pool-groove-to-a-clip) entry. |
| **D-3** Browser tree | `Browser` roots (`instruments`, `sounds`, `drums`, `audio_effects`, `midi_effects`, `max_for_live`, `plugins`, `clips`, `samples`, `packs`, `user_library`, `user_folders`, `current_project`, `legacy_libraries`, `colors`), `BrowserItem` traversal, `filter_type`, `hotswap_target`, `relation_to_hotswap_target`. |
| **D-4** Simpler and Sample (path-taking handlers) | Curated [slicing entry](FORK_GAPS.md#simplerdevice-slicing--slice-a-loaded-sample-from-the-bridge): `playback_mode`, `slicing_playback_mode`, `slices`, `insert/remove/clear/reset/move_slice`, `selected_slice`, `sample`, `Sample.*`, `SimplerDevice.View`. Plus every path-taking handler in one reviewed place: `replace_sample`, `Track.create_audio_clip`, `ClipSlot.create_audio_clip`. |
| **D-5** Small leftovers | `TuningSystem`, `Song.tuning_system`, `Song.get_data`/`set_data`. C-1 shipped without these (confirmed in FORK_GAPS's "Already in the fork" table); stands alone unless a smaller bucket fits. |

## Deferred — device-specific classes

Not scheduled. One PR each, only when a feature names it; D-4 sets the
pattern for a device subclass PR. Roughly 130 gaps:

`DriftDevice` (29), `WavetableDevice` (20), `LooperDevice` (16),
`SpectralResonatorDevice` (12), `HybridReverbDevice` (8), `MaxDevice` (8),
`CompressorDevice` (4), `MeldDevice` (4), `PluginDevice` (4),
`Eq8Device` (3 + View 2), `RoarDevice` (3), `ShifterDevice` (3),
`DrumCellDevice` (1).

## Count

| | PRs | Gaps closed |
|---|---|---|
| Tiers A–D | 19 (floor ~15 with the suggested merges) | ~365 of 494, plus every addressing and shape gap |
| Deferred device classes | ~13 | ~130 |
| **Full parity** | **~30** | 494 |

## Tracking

Update this file when a PR lands: strike the row, note the PR number. When
a tier is empty, delete it. Regenerate the FORK_GAPS inventory in the same
commit so the two files never disagree on what is open.
