from functools import partial
from typing import Any, Tuple

from .handler import AbletonOSCHandler

#--------------------------------------------------------------------------------
# Return Track & Master API — a Seshat extension, added in this fork.
#
# Upstream AbletonOSC reaches regular tracks only: every /live/track/* handler
# resolves its index through `song.tracks`, which holds audio and MIDI tracks
# and nothing else. Return tracks live in `song.return_tracks` and the master in
# `song.master_track`, so upstream can create and delete a return track but can
# neither name one nor touch its level — and the master fader is unreachable
# entirely.
#
# Seshat needs the names in particular: sends are addressed by index (send 0 =
# send A = return track 0), and the only way to turn "the reverb send" into an
# index is to read the return tracks' names in order.
#
#   /live/return_track/get/count    []                -> [count]
#   /live/return_track/get/name     [index]           -> [index, "ok", name]
#                                                     -> [index, "error", message]
#   /live/return_track/set/name     [index, name]     -> (no reply)
#   /live/return_track/get/volume   [index]           -> [index, "ok", volume]
#                                                     -> [index, "error", message]
#   /live/return_track/set/volume   [index, value]    -> (no reply)
#   /live/return_track/get/panning  [index]           -> [index, "ok", pan]
#                                                     -> [index, "error", message]
#   /live/return_track/set/panning  [index, pan]      -> (no reply)
#   /live/return_track/get/mute     [index]           -> [index, "ok", 0|1]
#                                                     -> [index, "error", message]
#   /live/return_track/set/mute     [index, 0|1]      -> (no reply)
#   /live/return_track/get/solo     [index]           -> [index, "ok", 0|1]
#                                                     -> [index, "error", message]
#   /live/return_track/set/solo     [index, 0|1]      -> (no reply)
#   /live/return_track/select       [index]           -> (no reply)
#   /live/master/get/volume         []                -> [volume]
#   /live/master/set/volume         [value]           -> (no reply)
#   /live/master/get/panning        []                -> [pan]
#   /live/master/set/panning        [pan]             -> (no reply)
#   /live/master/get/cue_volume     []                -> [value]
#   /live/master/set/cue_volume     [value]           -> (no reply)
#   /live/master/select             []                -> (no reply)
#
# The master track has no mute, solo or arm at all — reading one raises
# RuntimeError("Main track has no 'mute' property!") rather than returning
# something falsy, so feature-detecting with hasattr is unsafe on a LOM object
# and those addresses are simply not offered. Returns have no `arm` either.
# (Live 12 calls the master track "Main" in its UI and in those error strings.)
#
# `select` is the same gap one level up: upstream's
# /live/view/set/selected_track resolves through `song.tracks`, so it can never
# reach a return. `song.view.selected_track` itself accepts any track, returns
# and the master included, so this only needs the lookup upstream lacks.
#
# Device chains on returns and the master are unreachable upstream for the same
# reason: every /live/device/* address and /live/track/delete_device resolves its
# track through `song.tracks`, and /live/view/set/selected_device with it. So the
# whole device surface is repeated here against `song.return_tracks` and
# `song.master_track`:
#
#   /live/return_track/get/devices                [index]
#       -> [index, "ok", count, name0, type0, class0, ...]
#       -> [index, "error", message]
#   /live/master/get/devices                      []
#       -> [count, name0, type0, class0, ...]
#   /live/return_track/device/get/name            [index, device]
#       -> [index, device, "ok", name] / [index, device, "error", message]
#   /live/master/device/get/name                  [device]
#       -> [device, "ok", name] / [device, "error", message]
#   /live/return_track/device/get/parameters      [index, device]
#       -> [index, device, "ok", device_name, count, (pname, value, min, max)*N]
#   /live/master/device/get/parameters            [device]
#       -> [device, "ok", device_name, count, (pname, value, min, max)*N]
#   /live/return_track/device/get/parameter/value         [index, device, param]
#       -> [index, device, param, "ok", value]
#   /live/master/device/get/parameter/value               [device, param]
#       -> [device, param, "ok", value]
#   /live/return_track/device/get/parameter/value_string  [index, device, param]
#       -> [index, device, param, "ok", string]
#   /live/master/device/get/parameter/value_string        [device, param]
#       -> [device, param, "ok", string]
#   /live/return_track/device/set/parameter/value [index, device, param, value]
#       -> (no reply)
#   /live/master/device/set/parameter/value       [device, param, value]
#       -> (no reply)
#   /live/return_track/delete_device              [index, device]
#       -> [index, device, "ok", remaining] / [index, device, "error", message]
#   /live/master/delete_device                    [device]
#       -> [device, "ok", remaining] / [device, "error", message]
#   /live/return_track/select_device              [index, device] -> (no reply)
#   /live/master/select_device                    [device]        -> (no reply)
#
# The list getters deliberately combine what upstream splits across several
# addresses — three for a device chain, five for a parameter dump. Each of those
# is a separate round trip on a protocol with no request ids, and the caller
# needs all of them together or none of them; one reply also removes the risk of
# assembling parallel lists from replies that describe different devices. Count
# comes first in the flat tail so the reply stays parseable, and a tail that is
# not a whole number of triples (or quadruples) is a shape error the caller
# rejects rather than truncating.
#
# `delete_device` **replies**, unlike upstream's silent /live/track/delete_device.
# It is a method with a real failure path (a bad index), and the caller would
# otherwise have to sandwich it between two count reads to learn anything at all.
# The reply carries the device count remaining after the delete, re-read from
# Live rather than computed.
#
# Listeners, so a return fader, pan, mute or solo — or the master fader, pan or
# cue level — moved in Live's UI reaches Seshat without waiting for the next
# refresh:
#
#   /live/return_track/start_listen/name    [index]   -> pushes [index, name]
#   /live/return_track/stop_listen/name     [index]
#   /live/return_track/start_listen/volume  [index]   -> pushes [index, value]
#   /live/return_track/stop_listen/volume   [index]
#   /live/return_track/start_listen/panning [index]   -> pushes [index, pan]
#   /live/return_track/stop_listen/panning  [index]
#   /live/return_track/start_listen/mute    [index]   -> pushes [index, 0|1]
#   /live/return_track/stop_listen/mute     [index]
#   /live/return_track/start_listen/solo    [index]   -> pushes [index, 0|1]
#   /live/return_track/stop_listen/solo     [index]
#   /live/master/start_listen/volume        []        -> pushes [value]
#   /live/master/stop_listen/volume         []
#   /live/master/start_listen/panning       []        -> pushes [pan]
#   /live/master/stop_listen/panning        []
#   /live/master/start_listen/cue_volume    []        -> pushes [value]
#   /live/master/stop_listen/cue_volume     []
#
# There are no device listeners here: mirroring device chains is not something
# Seshat does yet, and a parameter listener per parameter would flood the wire.
#
# Each pushes on the matching get/ address. The push shape is deliberately the
# bare pair rather than the ok/error envelope a query reply carries, so the two
# stay distinguishable by arity on the Elixir side; a push has no failure path to
# report anyway.
#
# start_listen/stop_listen are silent on a bad index, like the setters: nothing
# waits on one, and the caller has already read `get/count` to know what exists.
#
# Getters follow browser.py's rule: always reply on the address they were called
# on, including on every error path. Upstream's convention — raise inside the
# callback and send nothing — is the wrong one for an optional extension. A
# silent bad index is indistinguishable from "the user never ran
# `mix abletonosc.install`", and it costs the caller a full guard timeout to
# learn nothing. Replying makes the two cases immediately separable: an error
# envelope is a bad index, and silence means the extension isn't loaded.
#
# `get/count` and `/live/master/get/volume` take no index and so have no failure
# path to report; they reply with the bare value.
#
# Setters stay silent. Each one is guarded by its matching getter immediately
# before it on the Elixir side, so the bad-index case is already reported by the
# time a setter is sent, and nothing ever waits on a setter's reply. `select` is
# silent for a stronger reason: it is view steering that follows a tool which has
# already succeeded, and steering must never fail — or delay — the thing it
# follows.
#
# Volume is 0.0-1.0 on Live's fader scale, read and written through
# `mixer_device.volume.value` — the same reason upstream's TrackHandler
# special-cases volume and panning. Panning is -1.0 to 1.0 through
# `mixer_device.panning.value` (Live displays it as 50L / C / 50R), and the
# master's cue level is `mixer_device.cue_volume.value`, 0.0-1.0 on the *same* dB
# curve as track volume — its parameter is named "Preview Volume" in Live.
#
# Track parity (roadmap item A-3)
# -------------------------------
#
# A return track and the master are Live.Track.Track objects, the same class as
# every regular track, so most of what /live/track/* answers applies to them —
# it was only ever the `song.tracks` lookup that stood in the way. The surface
# below closes that difference for the scalar properties, output routing, the
# returns' own sends and `insert_device`:
#
#   /live/return_track/get/color            [index]   -> [index, "ok", color]
#   /live/return_track/set/color            [index, color]
#   /live/return_track/{start,stop}_listen/color       [index]
#   ... and the same four for color_index
#   /live/return_track/get/has_audio_input  [index]   -> [index, "ok", 0|1]
#   ... and has_audio_output, has_midi_input, has_midi_output
#   /live/return_track/get/output_meter_level         [index] -> [index, "ok", level]
#   /live/return_track/{start,stop}_listen/output_meter_level [index]
#   ... and output_meter_left, output_meter_right
#   /live/return_track/get/available_output_routing_types     [index]
#       -> [index, "ok", count, name0, name1, ...]
#   /live/return_track/get/available_output_routing_channels  [index]
#   /live/return_track/get/output_routing_type        [index] -> [index, "ok", name]
#   /live/return_track/set/output_routing_type        [index, name]
#   /live/return_track/get/output_routing_channel     [index] -> [index, "ok", name]
#   /live/return_track/set/output_routing_channel     [index, name]
#   /live/return_track/get/send             [index, send_id]
#       -> [index, send_id, "ok", value] / [index, send_id, "error", message]
#   /live/return_track/set/send             [index, send_id, value]
#   /live/return_track/insert_device        [index, name[, position]]
#       -> [index, "ok", device_index, count] / [index, "error", message]
#
# with the index-less master form of every one of them except the sends (the
# master has none) — /live/master/get/color, /live/master/insert_device and so
# on.
#
# Three decisions shape that list, and each is a deliberate departure:
#
# 1. Every *new* master getter carries the ok/error envelope, even though the
#    shipped master getters (volume, panning, cue_volume, devices) reply with
#    the bare value. The Main track refuses some members its class declares —
#    reading `mute` raises RuntimeError, measured 2026-07-31 — and whether it
#    refuses `color` is unmeasured. The envelope makes the address
#    self-describing whichever way Live answers, where a bare reply would have
#    to choose between a lie and silence.
# 2. `has_audio_input` / `has_audio_output` / `has_midi_input` /
#    `has_midi_output` get **no listen pair**. On a return and on the master
#    they are constants (always audio in, audio out, never MIDI), so a listener
#    would subscribe to a value that cannot change. Regular tracks have those
#    pairs only because upstream's generic loop registers pairs blindly.
# 3. **No input routing.** Returns and the master have no input section in
#    Live's UI, so those addresses are not offered; the output half is, because
#    both do have an output chooser (a return routes to the master or
#    elsewhere, the master to a hardware out).
#
# The scalar and routing surfaces are table-driven: one row per property,
# walked twice — once index-keyed for returns, once index-less for the master —
# through shared generic callbacks. Sixty new hand-written methods would say
# the same thing sixty times and drift the moment one of them was edited.
#
# Getters wrap the read in try/except and answer the error envelope with the
# exception text, so a member a LOM object refuses is reported rather than
# silently answered as None. Setters keep the shipped split: an argument or
# bounds error is logged and silent, but the assignment itself is unguarded, so
# a LOM write that raises escapes to OSCServer._dispatch and arrives as a
# structured /live/error.
#
# `insert_device` replies, for the same reason `delete_device` does: it is a
# method with a real failure path, and the caller's very next act is addressing
# the device it just created. Its `device_index` is *re-read* from the chain
# (`list(track.devices).index(...)`) rather than assumed, because Live does not
# always append at the end, and is -1 when the returned object is not on the
# chain yet (asynchronously instantiating plugins) — the same convention
# browser.py's `load_item` uses.
#--------------------------------------------------------------------------------


#--------------------------------------------------------------------------------
# Scalar Track properties shared by returns and the master, one row each:
#
#   prop      the LOM member name, which is also the address's last segment and
#             the listener bookkeeping key's prop half
#   parse     the coercion applied to a setter's argument, or None for
#             read-only (no set/ address is registered)
#   listen    whether to register the start_listen/stop_listen pair
#   boolean   whether the getter reports 0/1 rather than the raw value, the
#             `mute`/`solo` precedent for every boolean on this handler
#
# The four has_* rows are read-only *and* unlistenable on purpose — see the
# header above.
#--------------------------------------------------------------------------------
SCALAR_PROPERTIES = (
    ("color", int, True, False),
    ("color_index", int, True, False),
    ("has_audio_input", None, False, True),
    ("has_audio_output", None, False, True),
    ("has_midi_input", None, False, True),
    ("has_midi_output", None, False, True),
    ("output_meter_level", None, True, False),
    ("output_meter_left", None, True, False),
    ("output_meter_right", None, True, False),
)

#--------------------------------------------------------------------------------
# Output routing, which cannot ride the scalar table: the value is a routing
# *object*, read as `.display_name` and written by resolving a display name
# against the matching available_* list. Each row is
# (property, available_list_property).
#
# Same name-based scheme as /live/track/*, and it inherits that scheme's known
# shape limitation with it (FORK_GAPS "Routing — names, not objects"): two
# routings with the same display name are indistinguishable on the wire.
#--------------------------------------------------------------------------------
ROUTING_PROPERTIES = (
    ("output_routing_type", "available_output_routing_types"),
    ("output_routing_channel", "available_output_routing_channels"),
)


class ReturnTrackHandler(AbletonOSCHandler):
    class_identifier = "return_track"

    def init_api(self):
        self.osc_server.add_handler("/live/return_track/get/count", self._get_count)
        self.osc_server.add_handler("/live/return_track/get/name", self._get_name)
        self.osc_server.add_handler("/live/return_track/set/name", self._set_name)
        self.osc_server.add_handler("/live/return_track/get/volume", self._get_volume)
        self.osc_server.add_handler("/live/return_track/set/volume", self._set_volume)
        self.osc_server.add_handler("/live/return_track/select", self._select)
        self.osc_server.add_handler("/live/master/get/volume", self._get_master_volume)
        self.osc_server.add_handler("/live/master/set/volume", self._set_master_volume)
        self.osc_server.add_handler("/live/return_track/start_listen/name",
                                    self._start_listen_name)
        self.osc_server.add_handler("/live/return_track/stop_listen/name",
                                    self._stop_listen_name)
        self.osc_server.add_handler("/live/return_track/start_listen/volume",
                                    self._start_listen_volume)
        self.osc_server.add_handler("/live/return_track/stop_listen/volume",
                                    self._stop_listen_volume)
        self.osc_server.add_handler("/live/master/start_listen/volume",
                                    self._start_listen_master_volume)
        self.osc_server.add_handler("/live/master/stop_listen/volume",
                                    self._stop_listen_master_volume)

        #--------------------------------------------------------------------------------
        # Mixer surface beyond the faders: pan and mute/solo per return, pan and
        # cue level on the master.
        #--------------------------------------------------------------------------------
        self.osc_server.add_handler("/live/return_track/get/panning", self._get_panning)
        self.osc_server.add_handler("/live/return_track/set/panning", self._set_panning)
        self.osc_server.add_handler("/live/return_track/start_listen/panning",
                                    self._start_listen_panning)
        self.osc_server.add_handler("/live/return_track/stop_listen/panning",
                                    self._stop_listen_panning)
        self.osc_server.add_handler("/live/return_track/get/mute", self._get_mute)
        self.osc_server.add_handler("/live/return_track/set/mute", self._set_mute)
        self.osc_server.add_handler("/live/return_track/start_listen/mute",
                                    self._start_listen_mute)
        self.osc_server.add_handler("/live/return_track/stop_listen/mute",
                                    self._stop_listen_mute)
        self.osc_server.add_handler("/live/return_track/get/solo", self._get_solo)
        self.osc_server.add_handler("/live/return_track/set/solo", self._set_solo)
        self.osc_server.add_handler("/live/return_track/start_listen/solo",
                                    self._start_listen_solo)
        self.osc_server.add_handler("/live/return_track/stop_listen/solo",
                                    self._stop_listen_solo)
        self.osc_server.add_handler("/live/master/get/panning", self._get_master_panning)
        self.osc_server.add_handler("/live/master/set/panning", self._set_master_panning)
        self.osc_server.add_handler("/live/master/start_listen/panning",
                                    self._start_listen_master_panning)
        self.osc_server.add_handler("/live/master/stop_listen/panning",
                                    self._stop_listen_master_panning)
        self.osc_server.add_handler("/live/master/get/cue_volume", self._get_cue_volume)
        self.osc_server.add_handler("/live/master/set/cue_volume", self._set_cue_volume)
        self.osc_server.add_handler("/live/master/start_listen/cue_volume",
                                    self._start_listen_cue_volume)
        self.osc_server.add_handler("/live/master/stop_listen/cue_volume",
                                    self._stop_listen_cue_volume)
        self.osc_server.add_handler("/live/master/select", self._select_master)

        #--------------------------------------------------------------------------------
        # Device chains on returns and the master.
        #--------------------------------------------------------------------------------
        self.osc_server.add_handler("/live/return_track/get/devices", self._get_devices)
        self.osc_server.add_handler("/live/master/get/devices", self._get_master_devices)
        self.osc_server.add_handler("/live/return_track/device/get/name",
                                    self._get_device_name)
        self.osc_server.add_handler("/live/master/device/get/name",
                                    self._get_master_device_name)
        self.osc_server.add_handler("/live/return_track/device/get/parameters",
                                    self._get_device_parameters)
        self.osc_server.add_handler("/live/master/device/get/parameters",
                                    self._get_master_device_parameters)
        self.osc_server.add_handler("/live/return_track/device/get/parameter/value",
                                    self._get_device_parameter_value)
        self.osc_server.add_handler("/live/master/device/get/parameter/value",
                                    self._get_master_device_parameter_value)
        self.osc_server.add_handler("/live/return_track/device/get/parameter/value_string",
                                    self._get_device_parameter_value_string)
        self.osc_server.add_handler("/live/master/device/get/parameter/value_string",
                                    self._get_master_device_parameter_value_string)
        self.osc_server.add_handler("/live/return_track/device/set/parameter/value",
                                    self._set_device_parameter_value)
        self.osc_server.add_handler("/live/master/device/set/parameter/value",
                                    self._set_master_device_parameter_value)
        self.osc_server.add_handler("/live/return_track/delete_device", self._delete_device)
        self.osc_server.add_handler("/live/master/delete_device", self._delete_master_device)
        self.osc_server.add_handler("/live/return_track/select_device", self._select_device)
        self.osc_server.add_handler("/live/master/select_device", self._select_master_device)

        #--------------------------------------------------------------------------------
        # Track parity: the scalar properties every regular track answers, walked
        # once for returns and once for the master. No per-property methods — the
        # only thing that differs between two rows is the name in the address and
        # the two flags beside it.
        #--------------------------------------------------------------------------------
        for prop, parse, listen, boolean in SCALAR_PROPERTIES:
            self.osc_server.add_handler(
                "/live/return_track/get/%s" % prop,
                partial(self._get_return_property, prop, boolean))
            self.osc_server.add_handler(
                "/live/master/get/%s" % prop,
                partial(self._get_master_property, prop, boolean))

            if parse is not None:
                self.osc_server.add_handler(
                    "/live/return_track/set/%s" % prop,
                    partial(self._set_return_property, prop, parse))
                self.osc_server.add_handler(
                    "/live/master/set/%s" % prop,
                    partial(self._set_master_property, prop, parse))

            if listen:
                self.osc_server.add_handler(
                    "/live/return_track/start_listen/%s" % prop,
                    partial(self._start_listen_return_property, prop))
                self.osc_server.add_handler(
                    "/live/return_track/stop_listen/%s" % prop,
                    partial(self._stop_listen_return_property, prop))
                self.osc_server.add_handler(
                    "/live/master/start_listen/%s" % prop,
                    partial(self._start_listen_master_property, prop))
                self.osc_server.add_handler(
                    "/live/master/stop_listen/%s" % prop,
                    partial(self._stop_listen_master_property, prop))

        #--------------------------------------------------------------------------------
        # Output routing. No listen pairs: regular tracks have none either, and
        # parity is the goal here.
        #--------------------------------------------------------------------------------
        for prop, available_prop in ROUTING_PROPERTIES:
            self.osc_server.add_handler(
                "/live/return_track/get/%s" % available_prop,
                partial(self._get_return_routing_list, available_prop))
            self.osc_server.add_handler(
                "/live/master/get/%s" % available_prop,
                partial(self._get_master_routing_list, available_prop))
            self.osc_server.add_handler(
                "/live/return_track/get/%s" % prop,
                partial(self._get_return_routing, prop))
            self.osc_server.add_handler(
                "/live/master/get/%s" % prop,
                partial(self._get_master_routing, prop))
            self.osc_server.add_handler(
                "/live/return_track/set/%s" % prop,
                partial(self._set_return_routing, prop, available_prop))
            self.osc_server.add_handler(
                "/live/master/set/%s" % prop,
                partial(self._set_master_routing, prop, available_prop))

        #--------------------------------------------------------------------------------
        # Sends on returns (Live 12 gives return tracks their own send section),
        # and insert_device on both.
        #--------------------------------------------------------------------------------
        self.osc_server.add_handler("/live/return_track/get/send", self._get_send)
        self.osc_server.add_handler("/live/return_track/set/send", self._set_send)
        self.osc_server.add_handler("/live/return_track/insert_device", self._insert_device)
        self.osc_server.add_handler("/live/master/insert_device", self._insert_master_device)

    #--------------------------------------------------------------------------------
    # Return tracks
    #--------------------------------------------------------------------------------
    def _get_count(self, params: Tuple[Any] = ()) -> Tuple:
        return (len(self.song.return_tracks),)

    def _get_name(self, params: Tuple[Any] = ()) -> Tuple:
        index, track, error = self._return_track(params, "get/name")
        if error is not None:
            return (index, "error", error)

        return (index, "ok", track.name)

    def _set_name(self, params: Tuple[Any] = ()) -> None:
        index, track, error = self._return_track(params, "set/name")
        if error is not None:
            return None

        if len(params) < 2:
            self.logger.error("Return track: set/name requires [index, name]")
            return None

        track.name = str(params[1])

    def _get_volume(self, params: Tuple[Any] = ()) -> Tuple:
        index, track, error = self._return_track(params, "get/volume")
        if error is not None:
            return (index, "error", error)

        return (index, "ok", track.mixer_device.volume.value)

    def _set_volume(self, params: Tuple[Any] = ()) -> None:
        index, track, error = self._return_track(params, "set/volume")
        if error is not None:
            return None

        try:
            value = float(params[1])
        except (IndexError, TypeError, ValueError):
            self.logger.error("Return track: set/volume requires [index, value]")
            return None

        track.mixer_device.volume.value = value

    def _get_panning(self, params: Tuple[Any] = ()) -> Tuple:
        index, track, error = self._return_track(params, "get/panning")
        if error is not None:
            return (index, "error", error)

        return (index, "ok", track.mixer_device.panning.value)

    def _set_panning(self, params: Tuple[Any] = ()) -> None:
        index, track, error = self._return_track(params, "set/panning")
        if error is not None:
            return None

        try:
            value = float(params[1])
        except (IndexError, TypeError, ValueError):
            self.logger.error("Return track: set/panning requires [index, value]")
            return None

        track.mixer_device.panning.value = value

    #--------------------------------------------------------------------------------
    # mute and solo are plain listenable Track properties, unlike the mixer
    # faders — so no DeviceParameter dance here, just the attribute. They are
    # reported as 0/1 rather than as Python bools so the reply's arity and types
    # match every other envelope on this handler.
    #--------------------------------------------------------------------------------
    def _get_mute(self, params: Tuple[Any] = ()) -> Tuple:
        index, track, error = self._return_track(params, "get/mute")
        if error is not None:
            return (index, "error", error)

        return (index, "ok", 1 if track.mute else 0)

    def _set_mute(self, params: Tuple[Any] = ()) -> None:
        index, track, error = self._return_track(params, "set/mute")
        if error is not None:
            return None

        try:
            value = int(params[1])
        except (IndexError, TypeError, ValueError):
            self.logger.error("Return track: set/mute requires [index, 0|1]")
            return None

        track.mute = bool(value)

    def _get_solo(self, params: Tuple[Any] = ()) -> Tuple:
        index, track, error = self._return_track(params, "get/solo")
        if error is not None:
            return (index, "error", error)

        return (index, "ok", 1 if track.solo else 0)

    def _set_solo(self, params: Tuple[Any] = ()) -> None:
        index, track, error = self._return_track(params, "set/solo")
        if error is not None:
            return None

        try:
            value = int(params[1])
        except (IndexError, TypeError, ValueError):
            self.logger.error("Return track: set/solo requires [index, 0|1]")
            return None

        track.solo = bool(value)

    def _select(self, params: Tuple[Any] = ()) -> None:
        """
        Select a return track in Live's UI.

        `song.view.selected_track` takes any track object, so the only thing
        upstream is missing is the lookup: its /live/view/set/selected_track
        indexes `song.tracks`, where returns do not appear.
        """
        index, track, error = self._return_track(params, "select")
        if error is not None:
            return None

        try:
            self.song.view.selected_track = track
        except Exception as e:
            self.logger.error("Return track: could not select return %d: %s" % (index, e))

    #--------------------------------------------------------------------------------
    # Return track listeners
    #--------------------------------------------------------------------------------
    def _start_listen_name(self, params: Tuple[Any] = ()) -> None:
        index, track, error = self._return_track(params, "start_listen/name")
        if error is not None:
            return None

        #--------------------------------------------------------------------------------
        # A return track is a LOM Track, so `name` is an ordinary listenable
        # property and the base class derives the right address on its own:
        # /live/return_track/get/name, sent as (index, name). It also re-listens
        # safely, unbinding from the object the callback was registered on rather
        # than from whatever `track` an index now resolves to.
        #--------------------------------------------------------------------------------
        self._start_listen(track, "name", (index,))

    def _stop_listen_name(self, params: Tuple[Any] = ()) -> None:
        index, track, error = self._return_track(params, "stop_listen/name")
        if error is not None:
            return None

        self._stop_listen_if_present("name", (index,))

    def _start_listen_volume(self, params: Tuple[Any] = ()) -> None:
        index, track, error = self._return_track(params, "start_listen/volume")
        if error is not None:
            return None

        self._listen_to_mixer_param(track.mixer_device.volume,
                                    "/live/return_track/get/volume",
                                    reply_prefix=(index,),
                                    listener_params=(index, "volume"))

    def _stop_listen_volume(self, params: Tuple[Any] = ()) -> None:
        index, track, error = self._return_track(params, "stop_listen/volume")
        if error is not None:
            return None

        self._stop_listen_if_present("value", (index, "volume"))

    def _start_listen_panning(self, params: Tuple[Any] = ()) -> None:
        index, track, error = self._return_track(params, "start_listen/panning")
        if error is not None:
            return None

        self._listen_to_mixer_param(track.mixer_device.panning,
                                    "/live/return_track/get/panning",
                                    reply_prefix=(index,),
                                    listener_params=(index, "panning"))

    def _stop_listen_panning(self, params: Tuple[Any] = ()) -> None:
        index, track, error = self._return_track(params, "stop_listen/panning")
        if error is not None:
            return None

        self._stop_listen_if_present("value", (index, "panning"))

    def _start_listen_mute(self, params: Tuple[Any] = ()) -> None:
        index, track, error = self._return_track(params, "start_listen/mute")
        if error is not None:
            return None

        #--------------------------------------------------------------------------------
        # `mute` is an ordinary listenable Track property, so the base class
        # derives /live/return_track/get/mute itself and sends (index, value) —
        # the same deal as `name` above. Live pushes a bool where the getter
        # replies 0/1; both are truthy-checked on the Elixir side.
        #--------------------------------------------------------------------------------
        self._start_listen(track, "mute", (index,))

    def _stop_listen_mute(self, params: Tuple[Any] = ()) -> None:
        index, track, error = self._return_track(params, "stop_listen/mute")
        if error is not None:
            return None

        self._stop_listen_if_present("mute", (index,))

    def _start_listen_solo(self, params: Tuple[Any] = ()) -> None:
        index, track, error = self._return_track(params, "start_listen/solo")
        if error is not None:
            return None

        self._start_listen(track, "solo", (index,))

    def _stop_listen_solo(self, params: Tuple[Any] = ()) -> None:
        index, track, error = self._return_track(params, "stop_listen/solo")
        if error is not None:
            return None

        self._stop_listen_if_present("solo", (index,))

    #--------------------------------------------------------------------------------
    # Master track
    #--------------------------------------------------------------------------------
    def _start_listen_master_volume(self, params: Tuple[Any] = ()) -> None:
        #--------------------------------------------------------------------------------
        # The master needs no index, but its listener still needs a key that can't
        # collide with a return track's — hence the "master" sentinel. It never
        # reaches the wire: the push carries the bare value.
        #--------------------------------------------------------------------------------
        self._listen_to_mixer_param(self.song.master_track.mixer_device.volume,
                                    "/live/master/get/volume",
                                    reply_prefix=(),
                                    listener_params=("master", "volume"))

    def _stop_listen_master_volume(self, params: Tuple[Any] = ()) -> None:
        self._stop_listen_if_present("value", ("master", "volume"))

    def _start_listen_master_panning(self, params: Tuple[Any] = ()) -> None:
        self._listen_to_mixer_param(self.song.master_track.mixer_device.panning,
                                    "/live/master/get/panning",
                                    reply_prefix=(),
                                    listener_params=("master", "panning"))

    def _stop_listen_master_panning(self, params: Tuple[Any] = ()) -> None:
        self._stop_listen_if_present("value", ("master", "panning"))

    def _start_listen_cue_volume(self, params: Tuple[Any] = ()) -> None:
        self._listen_to_mixer_param(self.song.master_track.mixer_device.cue_volume,
                                    "/live/master/get/cue_volume",
                                    reply_prefix=(),
                                    listener_params=("master", "cue_volume"))

    def _stop_listen_cue_volume(self, params: Tuple[Any] = ()) -> None:
        self._stop_listen_if_present("value", ("master", "cue_volume"))

    def _stop_listen_if_present(self, prop, listener_params) -> None:
        """
        Stop a listener, saying nothing if there wasn't one.

        The only thing this adds over the base `_stop_listen` is the silence.
        Nothing waits on a stop_listen, and a stop for an index that was never
        listened to is not an error worth a warning in Live's log — where the
        base class would log one.

        Removing the listener from the object it was actually registered on —
        which used to be this method's real job, since a return track's index is
        not stable — is the base class's own behaviour in this fork.
        """
        listener_key = (prop, tuple(listener_params))
        if listener_key in self.listener_functions:
            self._stop_listen(self.listener_objects[listener_key], prop, listener_params)

    def _listen_to_mixer_param(self, parameter, address, reply_prefix, listener_params) -> None:
        """
        Listen to a mixer DeviceParameter, pushing its value on `address`.

        Hand-rolled rather than delegated to the base `_start_listen`, because the
        listenable object here is not the track: it is `mixer_device.volume` (or
        `panning`, or `cue_volume`), a DeviceParameter whose change notification is
        `add_value_listener`. The base class would name the property "value" and
        derive /live/return_track/get/value — an address nothing serves or expects.

        Everything else the base class does is bookkeeping over
        `listener_functions` / `listener_objects`, keyed by (prop, params). So
        registering under ("value", listener_params) with the DeviceParameter as the
        object keeps `_stop_listen` (remove_value_listener) and `_clear_listeners`
        (cleanup on reload) working unchanged — including its unbind from the
        stored object, which is what makes re-listening safe once the same index
        has come to mean a different return track. `_stop_listen_if_present` keeps
        that re-listen quiet on a first subscribe. The immediate first push
        matches base behaviour too.

        Because the *prop* half of that key is forced to "value" for every mixer
        parameter, the discriminator has to live in `listener_params`: hence
        (index, "volume") / (index, "panning") / ("master", "cue_volume") rather
        than the bare index this used to pass. Without it, subscribing a return's
        pan would evict its volume listener — same key, silently. The tuple never
        reaches the wire; `reply_prefix` is what the push carries.

        This is the same shape TrackHandler's mixer listeners use for the tracks
        this handler doesn't reach.
        """
        def value_changed_callback():
            self.osc_server.send(address, (*reply_prefix, parameter.value))

        listener_key = ("value", tuple(listener_params))
        self._stop_listen_if_present("value", listener_params)

        self.logger.info("Adding mixer listener: %s %s" % (address, str(listener_params)))
        parameter.add_value_listener(value_changed_callback)
        self.listener_functions[listener_key] = value_changed_callback
        self.listener_objects[listener_key] = parameter

        value_changed_callback()

    def _get_master_volume(self, params: Tuple[Any] = ()) -> Tuple:
        return (self.song.master_track.mixer_device.volume.value,)

    def _set_master_volume(self, params: Tuple[Any] = ()) -> None:
        try:
            value = float(params[0])
        except (IndexError, TypeError, ValueError):
            self.logger.error("Master: set/volume requires [value]")
            return None

        self.song.master_track.mixer_device.volume.value = value

    def _get_master_panning(self, params: Tuple[Any] = ()) -> Tuple:
        return (self.song.master_track.mixer_device.panning.value,)

    def _set_master_panning(self, params: Tuple[Any] = ()) -> None:
        try:
            value = float(params[0])
        except (IndexError, TypeError, ValueError):
            self.logger.error("Master: set/panning requires [value]")
            return None

        self.song.master_track.mixer_device.panning.value = value

    def _get_cue_volume(self, params: Tuple[Any] = ()) -> Tuple:
        return (self.song.master_track.mixer_device.cue_volume.value,)

    def _set_cue_volume(self, params: Tuple[Any] = ()) -> None:
        try:
            value = float(params[0])
        except (IndexError, TypeError, ValueError):
            self.logger.error("Master: set/cue_volume requires [value]")
            return None

        self.song.master_track.mixer_device.cue_volume.value = value

    def _select_master(self, params: Tuple[Any] = ()) -> None:
        """
        Select the master track in Live's UI. Silent, like `_select` above.
        """
        try:
            self.song.view.selected_track = self.song.master_track
        except Exception as e:
            self.logger.error("Master: could not select the master track: %s" % e)

    #--------------------------------------------------------------------------------
    # Device chains
    #
    # Everything below mirrors upstream's device.py and track.py against
    # `song.return_tracks` / `song.master_track` instead of `song.tracks`. The
    # parameter access is `device.parameters[i]` exactly as upstream's, and
    # `delete_device` is `Track.delete_device(index)` exactly as upstream's
    # /live/track/delete_device — only the lookup and the reply envelope differ.
    #--------------------------------------------------------------------------------
    def _get_devices(self, params: Tuple[Any] = ()) -> Tuple:
        index, track, error = self._return_track(params, "get/devices")
        if error is not None:
            return (index, "error", error)

        return (index, "ok", *_device_chain(track))

    def _get_master_devices(self, params: Tuple[Any] = ()) -> Tuple:
        return _device_chain(self.song.master_track)

    def _get_device_name(self, params: Tuple[Any] = ()) -> Tuple:
        index, device_index, device, error = self._return_device(params, "device/get/name")
        if error is not None:
            return (index, device_index, "error", error)

        return (index, device_index, "ok", device.name)

    def _get_master_device_name(self, params: Tuple[Any] = ()) -> Tuple:
        device_index, device, error = self._master_device(params, "device/get/name")
        if error is not None:
            return (device_index, "error", error)

        return (device_index, "ok", device.name)

    def _get_device_parameters(self, params: Tuple[Any] = ()) -> Tuple:
        index, device_index, device, error = self._return_device(params, "device/get/parameters")
        if error is not None:
            return (index, device_index, "error", error)

        return (index, device_index, "ok", *_device_parameters(device))

    def _get_master_device_parameters(self, params: Tuple[Any] = ()) -> Tuple:
        device_index, device, error = self._master_device(params, "device/get/parameters")
        if error is not None:
            return (device_index, "error", error)

        return (device_index, "ok", *_device_parameters(device))

    def _get_device_parameter_value(self, params: Tuple[Any] = ()) -> Tuple:
        index, device_index, param_index, parameter, error = self._return_device_parameter(
            params, "device/get/parameter/value")
        if error is not None:
            return (index, device_index, param_index, "error", error)

        return (index, device_index, param_index, "ok", parameter.value)

    def _get_master_device_parameter_value(self, params: Tuple[Any] = ()) -> Tuple:
        device_index, param_index, parameter, error = self._master_device_parameter(
            params, "device/get/parameter/value")
        if error is not None:
            return (device_index, param_index, "error", error)

        return (device_index, param_index, "ok", parameter.value)

    def _get_device_parameter_value_string(self, params: Tuple[Any] = ()) -> Tuple:
        index, device_index, param_index, parameter, error = self._return_device_parameter(
            params, "device/get/parameter/value_string")
        if error is not None:
            return (index, device_index, param_index, "error", error)

        return (index, device_index, param_index, "ok", _value_string(parameter))

    def _get_master_device_parameter_value_string(self, params: Tuple[Any] = ()) -> Tuple:
        device_index, param_index, parameter, error = self._master_device_parameter(
            params, "device/get/parameter/value_string")
        if error is not None:
            return (device_index, param_index, "error", error)

        return (device_index, param_index, "ok", _value_string(parameter))

    def _set_device_parameter_value(self, params: Tuple[Any] = ()) -> None:
        _index, _device_index, _param_index, parameter, error = self._return_device_parameter(
            params, "device/set/parameter/value")
        if error is not None:
            return None

        try:
            value = float(params[3])
        except (IndexError, TypeError, ValueError):
            self.logger.error("Return track: device/set/parameter/value requires "
                              "[index, device, parameter, value]")
            return None

        parameter.value = value

    def _set_master_device_parameter_value(self, params: Tuple[Any] = ()) -> None:
        _device_index, _param_index, parameter, error = self._master_device_parameter(
            params, "device/set/parameter/value")
        if error is not None:
            return None

        try:
            value = float(params[2])
        except (IndexError, TypeError, ValueError):
            self.logger.error("Master: device/set/parameter/value requires "
                              "[device, parameter, value]")
            return None

        parameter.value = value

    def _delete_device(self, params: Tuple[Any] = ()) -> Tuple:
        index, device_index, _device, error = self._return_device(params, "delete_device")
        if error is not None:
            return (index, device_index, "error", error)

        track = self.song.return_tracks[index]
        try:
            track.delete_device(device_index)
        except Exception as e:
            self.logger.error("Return track: could not delete device %d on return %d: %s"
                              % (device_index, index, e))
            return (index, device_index, "error",
                    "Could not delete device %d: %s" % (device_index, e))

        return (index, device_index, "ok", len(track.devices))

    def _delete_master_device(self, params: Tuple[Any] = ()) -> Tuple:
        device_index, _device, error = self._master_device(params, "delete_device")
        if error is not None:
            return (device_index, "error", error)

        track = self.song.master_track
        try:
            track.delete_device(device_index)
        except Exception as e:
            self.logger.error("Master: could not delete device %d: %s" % (device_index, e))
            return (device_index, "error",
                    "Could not delete device %d: %s" % (device_index, e))

        return (device_index, "ok", len(track.devices))

    def _select_device(self, params: Tuple[Any] = ()) -> None:
        """
        Select a device on a return track's chain. Silent, like every `select`
        here: it is view steering behind a tool that has already succeeded.

        `song.view.select_device` also opens the device chain in Live's detail
        panel, which is exactly what the caller wants — measured 2026-07-31.
        """
        _index, _device_index, device, error = self._return_device(params, "select_device")
        if error is not None:
            return None

        try:
            self.song.view.select_device(device)
        except Exception as e:
            self.logger.error("Return track: could not select device: %s" % e)

    def _select_master_device(self, params: Tuple[Any] = ()) -> None:
        _device_index, device, error = self._master_device(params, "select_device")
        if error is not None:
            return None

        try:
            self.song.view.select_device(device)
        except Exception as e:
            self.logger.error("Master: could not select device: %s" % e)

    #--------------------------------------------------------------------------------
    # Track parity: shared generic callbacks
    #
    # Four for the scalar table (return get/set, master get/set), four more for
    # its listen pairs, six for routing, and the sends and insert_device pair
    # below them. Every one is bound to a row of SCALAR_PROPERTIES /
    # ROUTING_PROPERTIES by functools.partial at registration time, so adding a
    # property is adding a row.
    #--------------------------------------------------------------------------------
    def _get_return_property(self, prop, boolean, params: Tuple[Any] = ()) -> Tuple:
        index, track, error = self._return_track(params, "get/%s" % prop)
        if error is not None:
            return (index, "error", error)

        value, error = self._read_property(track, prop, "Return track %d" % index)
        if error is not None:
            return (index, "error", error)

        return (index, "ok", (1 if value else 0) if boolean else value)

    def _set_return_property(self, prop, parse, params: Tuple[Any] = ()) -> None:
        index, track, error = self._return_track(params, "set/%s" % prop)
        if error is not None:
            return None

        try:
            value = parse(params[1])
        except (IndexError, TypeError, ValueError):
            self.logger.error("Return track: set/%s requires [index, value]" % prop)
            return None

        #--------------------------------------------------------------------------------
        # Deliberately unguarded: a LOM object that refuses the member raises,
        # and that exception is worth a structured /live/error rather than the
        # silence an argument error gets. Same split as `track.name = ...` above.
        #--------------------------------------------------------------------------------
        self.logger.info("Setting property for return track %d: %s (new value %s)"
                         % (index, prop, value))
        setattr(track, prop, value)

    def _get_master_property(self, prop, boolean, params: Tuple[Any] = ()) -> Tuple:
        value, error = self._read_property(self.song.master_track, prop, "Master track")
        if error is not None:
            return ("error", error)

        return ("ok", (1 if value else 0) if boolean else value)

    def _set_master_property(self, prop, parse, params: Tuple[Any] = ()) -> None:
        try:
            value = parse(params[0])
        except (IndexError, TypeError, ValueError):
            self.logger.error("Master: set/%s requires [value]" % prop)
            return None

        self.logger.info("Setting property for master track: %s (new value %s)" % (prop, value))
        setattr(self.song.master_track, prop, value)

    def _read_property(self, track, prop, label):
        """
        Read `prop` off a Track, reporting a refusal instead of raising.

        Returns (value, None) or (None, message). The catch is what turns a
        member the Main track declares but refuses — reading `mute` raises
        RuntimeError("Main track has no 'mute' property!") — into a
        self-describing error envelope rather than a silent hole or a bare None
        the caller cannot tell from a real value.
        """
        try:
            value = getattr(track, prop)
        except Exception as e:
            message = "could not read %s: %s" % (prop, e)
            self.logger.error("%s: %s" % (label, message))
            return (None, message)

        #--------------------------------------------------------------------------------
        # Logged on the ok path like the base class's _get_property, so the
        # value is readable from Live's log — the only evidence available when
        # verifying against a running Live, since replies go to a port this
        # side cannot bind.
        #--------------------------------------------------------------------------------
        self.logger.info("%s: getting property %s = %s" % (label, prop, value))
        return (value, None)

    def _start_listen_return_property(self, prop, params: Tuple[Any] = ()) -> None:
        index, track, error = self._return_track(params, "start_listen/%s" % prop)
        if error is not None:
            return None

        #--------------------------------------------------------------------------------
        # Plain listenable Track properties, so the base class derives
        # /live/return_track/get/<prop> on its own and pushes (index, value) —
        # exactly as `name`, `mute` and `solo` above.
        #--------------------------------------------------------------------------------
        self._start_listen(track, prop, (index,))

    def _stop_listen_return_property(self, prop, params: Tuple[Any] = ()) -> None:
        index, track, error = self._return_track(params, "stop_listen/%s" % prop)
        if error is not None:
            return None

        self._stop_listen_if_present(prop, (index,))

    def _start_listen_master_property(self, prop, params: Tuple[Any] = ()) -> None:
        self._listen_to_track_property(self.song.master_track, prop,
                                       "/live/master/get/%s" % prop,
                                       reply_prefix=(),
                                       listener_params=("master",))

    def _stop_listen_master_property(self, prop, params: Tuple[Any] = ()) -> None:
        self._stop_listen_if_present(prop, ("master",))

    def _listen_to_track_property(self, track, prop, address, reply_prefix,
                                  listener_params) -> None:
        """
        Listen to a plain Track property, pushing its value on `address`.

        The plain-property sibling of `_listen_to_mixer_param`, and hand-rolled
        for the mirror-image reason: here the *object* is right (a Track, whose
        notification is add_<prop>_listener, so the base class would bind
        correctly) but the *address* is wrong — the base derives it from
        `class_identifier`, which is "return_track" for this handler, and the
        master's pushes have to go out on /live/master/get/<prop>.

        Everything else is the base class's own bookkeeping, written into the
        same dicts: keyed (prop, listener_params) with the track as the object,
        so `_stop_listen` recovers remove_<prop>_listener from the key's prop
        half (no alias needed — unlike the mixer parameters, whose prop is
        forced to "value") and `_clear_listeners` tears these down on reload
        with no special case. The master's key is (prop, ("master",)), which
        cannot collide with a return's (prop, (index,)) or with any mixer key.
        """
        def property_changed_callback():
            value = getattr(track, prop)
            self.logger.info("Property %s changed of %s %s: %s"
                             % (prop, self.class_identifier, str(listener_params), value))
            self.osc_server.send(address, (*reply_prefix, value))

        listener_key = (prop, tuple(listener_params))
        self._stop_listen_if_present(prop, listener_params)

        self.logger.info("Adding listener: %s %s" % (address, str(listener_params)))
        add_listener_function = getattr(track, "add_%s_listener" % prop)
        add_listener_function(property_changed_callback)
        self.listener_functions[listener_key] = property_changed_callback
        self.listener_objects[listener_key] = track

        property_changed_callback()

    #--------------------------------------------------------------------------------
    # Output routing
    #--------------------------------------------------------------------------------
    def _get_return_routing_list(self, available_prop, params: Tuple[Any] = ()) -> Tuple:
        index, track, error = self._return_track(params, "get/%s" % available_prop)
        if error is not None:
            return (index, "error", error)

        names, error = self._routing_names(track, available_prop, "Return track %d" % index)
        if error is not None:
            return (index, "error", error)

        return (index, "ok", len(names), *names)

    def _get_master_routing_list(self, available_prop, params: Tuple[Any] = ()) -> Tuple:
        names, error = self._routing_names(self.song.master_track, available_prop,
                                           "Master track")
        if error is not None:
            return ("error", error)

        return ("ok", len(names), *names)

    def _routing_names(self, track, available_prop, label):
        """
        (names, None) / (None, message) for one of the available_* lists.

        `count` goes first in the reply the callers build, for the same reason
        `_device_chain` puts it there: the flat tail stays parseable, and a tail
        whose length disagrees with the count is a shape error the caller
        rejects rather than truncating.
        """
        try:
            names = [routing.display_name for routing in getattr(track, available_prop)]
        except Exception as e:
            message = "could not read %s: %s" % (available_prop, e)
            self.logger.error("%s: %s" % (label, message))
            return (None, message)

        self.logger.info("%s: getting property %s = %s" % (label, available_prop, names))
        return (names, None)

    def _get_return_routing(self, prop, params: Tuple[Any] = ()) -> Tuple:
        index, track, error = self._return_track(params, "get/%s" % prop)
        if error is not None:
            return (index, "error", error)

        name, error = self._routing_name(track, prop, "Return track %d" % index)
        if error is not None:
            return (index, "error", error)

        return (index, "ok", name)

    def _get_master_routing(self, prop, params: Tuple[Any] = ()) -> Tuple:
        name, error = self._routing_name(self.song.master_track, prop, "Master track")
        if error is not None:
            return ("error", error)

        return ("ok", name)

    def _routing_name(self, track, prop, label):
        """
        (display_name, None) / (None, message) for a routing property.

        The wire carries the display name, not the routing object — the same
        shape (and the same known ambiguity) as /live/track/get/output_routing_type.
        """
        try:
            name = getattr(track, prop).display_name
        except Exception as e:
            message = "could not read %s: %s" % (prop, e)
            self.logger.error("%s: %s" % (label, message))
            return (None, message)

        self.logger.info("%s: getting property %s = %s" % (label, prop, name))
        return (name, None)

    def _set_return_routing(self, prop, available_prop, params: Tuple[Any] = ()) -> None:
        index, track, error = self._return_track(params, "set/%s" % prop)
        if error is not None:
            return None

        try:
            name = str(params[1])
        except (IndexError, TypeError, ValueError):
            self.logger.error("Return track: set/%s requires [index, name]" % prop)
            return None

        self._apply_routing(track, prop, available_prop, name, "Return track %d" % index)

    def _set_master_routing(self, prop, available_prop, params: Tuple[Any] = ()) -> None:
        try:
            name = str(params[0])
        except (IndexError, TypeError, ValueError):
            self.logger.error("Master: set/%s requires [name]" % prop)
            return None

        self._apply_routing(self.song.master_track, prop, available_prop, name, "Master track")

    def _apply_routing(self, track, prop, available_prop, name, label) -> None:
        """
        Resolve `name` against the available_* list and assign it.

        Ported from track.py's resolve-by-display-name loop, including its
        behaviour on no match: a warning in Live's log and nothing written. The
        setter stays silent on the wire either way, like every setter here.
        """
        for routing in getattr(track, available_prop):
            if routing.display_name == name:
                self.logger.info("%s: setting property %s (new value %s)" % (label, prop, name))
                setattr(track, prop, routing)
                return

        self.logger.warning("%s: couldn't find %s: %s" % (label, prop, name))

    #--------------------------------------------------------------------------------
    # Sends on returns
    #
    # Live 12 gives return tracks their own send section (return-to-return,
    # disabled by default behind Live's feedback guard). `mixer_device.sends` is
    # the same LOM path a regular track's sends take, so this is upstream's
    # /live/track/get|set/send with the return lookup and the reply envelope in
    # front of it. No master form: the master has no sends. No listen pairs:
    # regular tracks have none either.
    #--------------------------------------------------------------------------------
    def _get_send(self, params: Tuple[Any] = ()) -> Tuple:
        index, send_id, send, error = self._return_send(params, "get/send")
        if error is not None:
            return (index, send_id, "error", error)

        self.logger.info("Return track %d: getting send %d = %s" % (index, send_id, send.value))
        return (index, send_id, "ok", send.value)

    def _set_send(self, params: Tuple[Any] = ()) -> None:
        index, send_id, send, error = self._return_send(params, "set/send")
        if error is not None:
            return None

        try:
            value = float(params[2])
        except (IndexError, TypeError, ValueError):
            self.logger.error("Return track: set/send requires [index, send_id, value]")
            return None

        self.logger.info("Return track %d: setting send %d (new value %s)"
                         % (index, send_id, value))
        send.value = value

    #--------------------------------------------------------------------------------
    # insert_device
    #--------------------------------------------------------------------------------
    def _insert_device(self, params: Tuple[Any] = ()) -> Tuple:
        index, track, error = self._return_track(params, "insert_device")
        if error is not None:
            return (index, "error", error)

        device_index, count, error = self._insert_device_into(
            track, params, 1, "Return track %d" % index)
        if error is not None:
            return (index, "error", error)

        return (index, "ok", device_index, count)

    def _insert_master_device(self, params: Tuple[Any] = ()) -> Tuple:
        device_index, count, error = self._insert_device_into(
            self.song.master_track, params, 0, "Master track")
        if error is not None:
            return ("error", error)

        return ("ok", device_index, count)

    def _insert_device_into(self, track, params: Tuple[Any], position: int, label):
        """
        `Track.insert_device(name[, position])`, reported as (device_index,
        count, None) or (None, None, message).

        `device_index` is re-read from the chain rather than assumed, because
        Live does not always append at the end (an instrument lands before
        existing audio effects) — the same reasoning behind browser.py's
        `_loaded_device`, and behind `delete_device`'s re-read `remaining`. It
        is -1 when the returned object is not on the chain yet, which is what an
        asynchronously instantiating plugin looks like.

        Everything the LOM call can fail on — a name Live does not recognise, or
        a Live older than 12.3, where `insert_device` does not exist at all —
        arrives as the error envelope rather than as a raise, because this
        address replies.
        """
        try:
            name = str(params[position])
        except (IndexError, TypeError, ValueError):
            message = "insert_device requires a device name at argument %d" % position
            self.logger.error("%s: %s" % (label, message))
            return (None, None, message)

        call_params = [name]
        if len(params) > position + 1:
            try:
                call_params.append(int(params[position + 1]))
            except (TypeError, ValueError):
                message = "insert_device's position argument must be a number"
                self.logger.error("%s: %s" % (label, message))
                return (None, None, message)

        try:
            device = track.insert_device(*call_params)
        except Exception as e:
            message = "could not insert device '%s': %s" % (name, e)
            self.logger.error("%s: %s" % (label, message))
            return (None, None, message)

        devices = list(track.devices)
        try:
            device_index = devices.index(device)
        except ValueError:
            device_index = -1

        self.logger.info("%s: inserted device '%s' at index %d (chain now holds %d)"
                         % (label, name, device_index, len(devices)))
        return (device_index, len(devices), None)

    #--------------------------------------------------------------------------------
    # Lookup
    #--------------------------------------------------------------------------------
    def _return_track(self, params: Tuple[Any], operation: str):
        """
        Resolve params[0] to a return track, bounds-checked.

        Returns (index, track, None) on success and (index, None, message) on
        failure. The index is echoed back verbatim even when it is out of range,
        so the caller's reply still correlates with the query that asked for it.
        """
        try:
            index = int(params[0])
        except (IndexError, TypeError, ValueError):
            message = "%s requires a return track index as its first argument" % operation
            self.logger.error("Return track: %s" % message)
            return (-1, None, message)

        return_tracks = self.song.return_tracks
        if index < 0 or index >= len(return_tracks):
            message = "Return track %d does not exist — this set has %d return track(s)" % (
                index, len(return_tracks))
            self.logger.error("Return track: %s (%s)" % (message, operation))
            return (index, None, message)

        return (index, return_tracks[index], None)

    def _return_device(self, params: Tuple[Any], operation: str):
        """
        Resolve params[0] to a return track and params[1] to a device on it.

        Returns (index, device_index, device, None) on success and
        (index, device_index, None, message) on failure. Both indices are echoed
        back verbatim even when out of range, for the same correlation reason as
        `_return_track` — including when the return track itself failed to
        resolve, in which case the device index is parsed independently just
        for the echo, so the reply still correlates with the query that asked
        for it. -1 stands in only when that value wasn't a number at all.
        """
        index, track, error = self._return_track(params, operation)
        if error is not None:
            return (index, _echo_index(params, 1), None, error)

        device_index, device, message = self._device_of(track, params, 1, operation)
        if message is not None:
            message = "Return track %d: %s" % (index, message)

        return (index, device_index, device, message)

    def _master_device(self, params: Tuple[Any], operation: str):
        """
        Resolve params[0] to a device on the master track.

        Returns (device_index, device, None) / (device_index, None, message).
        """
        device_index, device, message = self._device_of(
            self.song.master_track, params, 0, operation)
        if message is not None:
            message = "Master track: %s" % message

        return (device_index, device, message)

    def _return_device_parameter(self, params: Tuple[Any], operation: str):
        """
        (index, device_index, param_index, parameter, None) / (..., None, message).

        The parameter index is echoed the same way as `_return_device`'s device
        index: parsed independently for the echo when an outer lookup already
        failed, so a bad return or device index still comes back correlated
        with the query that asked about the parameter.
        """
        index, device_index, device, error = self._return_device(params, operation)
        if error is not None:
            return (index, device_index, _echo_index(params, 2), None, error)

        param_index, parameter, message = self._parameter_of(device, params, 2, operation)
        if message is not None:
            message = "Return track %d, device %d: %s" % (index, device_index, message)

        return (index, device_index, param_index, parameter, message)

    def _master_device_parameter(self, params: Tuple[Any], operation: str):
        """
        (device_index, param_index, parameter, None) / (..., None, message).

        Same echo rule as `_return_device_parameter`: the parameter index is
        parsed independently for the echo when the device lookup already
        failed.
        """
        device_index, device, error = self._master_device(params, operation)
        if error is not None:
            return (device_index, _echo_index(params, 1), None, error)

        param_index, parameter, message = self._parameter_of(device, params, 1, operation)
        if message is not None:
            message = "Master track, device %d: %s" % (device_index, message)

        return (device_index, param_index, parameter, message)

    def _return_send(self, params: Tuple[Any], operation: str):
        """
        Resolve params[0] to a return track and params[1] to one of its sends.

        Returns (index, send_id, send, None) / (index, send_id, None, message).
        Both indices are echoed verbatim on failure for the same correlation
        reason as `_return_device` — including the send id when the return
        lookup itself failed, which is parsed independently just for the echo.
        """
        index, track, error = self._return_track(params, operation)
        if error is not None:
            return (index, _echo_index(params, 1), None, error)

        send_id, send, message = self._send_of(track, params, 1, operation)
        if message is not None:
            message = "Return track %d: %s" % (index, message)

        return (index, send_id, send, message)

    def _send_of(self, track, params: Tuple[Any], position: int, operation: str):
        try:
            send_id = int(params[position])
        except (IndexError, TypeError, ValueError):
            message = "%s requires a send index at argument %d" % (operation, position)
            self.logger.error("Send lookup: %s" % message)
            return (-1, None, message)

        sends = track.mixer_device.sends
        if send_id < 0 or send_id >= len(sends):
            message = "there is no send %d — this track has %d send(s)" % (
                send_id, len(sends))
            self.logger.error("Send lookup: %s (%s)" % (message, operation))
            return (send_id, None, message)

        return (send_id, sends[send_id], None)

    def _device_of(self, track, params: Tuple[Any], position: int, operation: str):
        try:
            device_index = int(params[position])
        except (IndexError, TypeError, ValueError):
            message = "%s requires a device index at argument %d" % (operation, position)
            self.logger.error("Device lookup: %s" % message)
            return (-1, None, message)

        devices = track.devices
        if device_index < 0 or device_index >= len(devices):
            message = "there is no device %d — the chain holds %d device(s)" % (
                device_index, len(devices))
            self.logger.error("Device lookup: %s (%s)" % (message, operation))
            return (device_index, None, message)

        return (device_index, devices[device_index], None)

    def _parameter_of(self, device, params: Tuple[Any], position: int, operation: str):
        try:
            param_index = int(params[position])
        except (IndexError, TypeError, ValueError):
            message = "%s requires a parameter index at argument %d" % (operation, position)
            self.logger.error("Parameter lookup: %s" % message)
            return (-1, None, message)

        parameters = device.parameters
        if param_index < 0 or param_index >= len(parameters):
            message = "there is no parameter %d — '%s' has %d parameter(s)" % (
                param_index, device.name, len(parameters))
            self.logger.error("Parameter lookup: %s (%s)" % (message, operation))
            return (param_index, None, message)

        return (param_index, parameters[param_index], None)


def _echo_index(params: Tuple[Any], position: int) -> int:
    """
    Best-effort echo of an index argument that an *outer* lookup already
    failed on, so the error reply still correlates with the query that asked
    about it (the caller checks every echoed position against what it sent).
    Returns the value at `position` parsed as an int whenever that's possible
    — including one that is out of range, since out-of-range is exactly what
    a real query sends — and -1 only when the value isn't a number at all
    (missing, non-numeric, or wrong type).
    """
    try:
        return int(params[position])
    except (IndexError, TypeError, ValueError):
        return -1


def _device_chain(track) -> Tuple:
    """
    (count, name0, type0, class0, name1, ...) for a track's device chain.

    Count first so the flat tail stays parseable: the reader takes `count`,
    then expects exactly that many triples, and treats any other length as a
    shape error rather than truncating.
    """
    devices = list(track.devices)

    flat = []
    for device in devices:
        flat.append(device.name)
        flat.append(device.type)
        flat.append(device.class_name)

    return (len(devices), *flat)


def _device_parameters(device) -> Tuple:
    """
    (device_name, count, pname0, value0, min0, max0, pname1, ...).

    One reply where upstream needs five, for the same reason `_device_chain`
    combines three: the caller wants all of them together, and assembling
    parallel lists out of separate replies risks describing two different
    devices.
    """
    parameters = list(device.parameters)

    flat = []
    for parameter in parameters:
        flat.append(parameter.name)
        flat.append(parameter.value)
        flat.append(parameter.min)
        flat.append(parameter.max)

    return (device.name, len(parameters), *flat)


def _value_string(parameter) -> str:
    """
    Live's UI-friendly rendering of a parameter's current value ("2.5 kHz").

    Same call as upstream's /live/device/get/parameter/value_string.
    """
    return parameter.str_for_value(parameter.value)
