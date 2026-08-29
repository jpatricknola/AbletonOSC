from typing import Tuple, Any, Callable, Optional
from .handler import AbletonOSCHandler
from .track_callback import create_track_callback as _create_track_callback
from .track_identity import group_track_index
from .path_safety import ImportPathError, resolve_import_path


class TrackHandler(AbletonOSCHandler):
    class_identifier = "track"

    def init_api(self):
        #--------------------------------------------------------------------------------
        # The wrapper itself lives in track_callback.py, which imports nothing
        # from Live and is therefore covered by tests_unit/. All this local
        # helper does is bind the track source, so every registration below
        # reads exactly as it did when the factory was nested here.
        #
        # `lambda: self.song.tracks` rather than the vector itself: the
        # original resolved `self.song` on every dispatch, and a Live set can
        # be closed and reopened under a live control surface.
        #--------------------------------------------------------------------------------
        def create_track_callback(func: Callable,
                                  *args,
                                  include_track_id: bool = False):
            return _create_track_callback(lambda: self.song.tracks,
                                          func,
                                          *args,
                                          include_track_id=include_track_id)

        methods = [
            "delete_device",
            #--------------------------------------------------------------------------------
            # Seshat extension (A-3): the regular-track counterpart of
            # /live/return_track/insert_device and /live/master/insert_device,
            # so `Track.insert_device` is reachable on all three categories
            # rather than on two of them. One string in the generic loop, so it
            # behaves like every other /live/track/<method>: silent on success,
            # failures arrive as a structured /live/error, and `*` fans out per
            # the track-index wildcard contract. Live 12.3+ member; on an older
            # Live the call raises and is reported that way.
            #--------------------------------------------------------------------------------
            "insert_device",
            "stop_all_clips"
        ]
        properties_r = [
            "can_be_armed",
            "fired_slot_index",
            "has_audio_input",
            "has_audio_output",
            "has_midi_input",
            "has_midi_output",
            "is_foldable",
            "is_grouped",
            "is_visible",
            "output_meter_level",
            "output_meter_left",
            "output_meter_right",
            "playing_slot_index",
        ]
        properties_rw = [
            "arm",
            "color",
            "color_index",
            "current_monitoring_state",
            "fold_state",
            "mute",
            "solo",
            "name"
        ]

        for method in methods:
            self.osc_server.add_handler("/live/track/%s" % method,
                                        create_track_callback(self._call_method, method))

        for prop in properties_r + properties_rw:
            self.osc_server.add_handler("/live/track/get/%s" % prop,
                                        create_track_callback(self._get_property, prop))
            self.osc_server.add_handler("/live/track/start_listen/%s" % prop,
                                        create_track_callback(self._start_listen, prop, include_track_id=True))
            self.osc_server.add_handler("/live/track/stop_listen/%s" % prop,
                                        create_track_callback(self._stop_listen, prop, include_track_id=True))
        for prop in properties_rw:
            self.osc_server.add_handler("/live/track/set/%s" % prop,
                                        create_track_callback(self._set_property, prop))

        #--------------------------------------------------------------------------------
        # Volume, panning and send are properties of the track's mixer_device so
        # can't be formulated as normal callbacks that reference properties of track.
        #--------------------------------------------------------------------------------
        mixer_properties_rw = ["volume", "panning"]
        for prop in mixer_properties_rw:
            self.osc_server.add_handler("/live/track/get/%s" % prop,
                                        create_track_callback(self._get_mixer_property, prop))
            self.osc_server.add_handler("/live/track/set/%s" % prop,
                                        create_track_callback(self._set_mixer_property, prop))
            self.osc_server.add_handler("/live/track/start_listen/%s" % prop,
                                        create_track_callback(self._start_mixer_listen, prop, include_track_id=True))
            self.osc_server.add_handler("/live/track/stop_listen/%s" % prop,
                                        create_track_callback(self._stop_mixer_listen, prop, include_track_id=True))

        # Still need to fix these
        # Might want to find a better approach that unifies volume and sends
        def track_get_send(track, params: Tuple[Any] = ()):
            send_id, = params
            return send_id, track.mixer_device.sends[send_id].value

        def track_set_send(track, params: Tuple[Any] = ()):
            send_id, value = params
            track.mixer_device.sends[send_id].value = value

        self.osc_server.add_handler("/live/track/get/send", create_track_callback(track_get_send))
        self.osc_server.add_handler("/live/track/set/send", create_track_callback(track_set_send))

        def track_delete_clip(track, params: Tuple[Any]):
            clip_index, = params
            track.clip_slots[clip_index].delete_clip()

        self.osc_server.add_handler("/live/track/delete_clip", create_track_callback(track_delete_clip))

        #--------------------------------------------------------------------------------
        # Seshat extension: import an audio file onto this track's Arrangement.
        #
        #   /live/track/create_audio_clip [track_id, name, position]
        #     -> [track_index, "ok", position, length]
        #     -> [track_index, "error", message]
        #
        # `name` is a path *relative to* path_safety.IMPORT_ROOT, never an
        # absolute path — see path_safety.py and API.md § "Handlers that name a
        # file to read". Nothing is opened and no Live method is called on a
        # refused name.
        #
        # Always replies, including on every refusal, for the reasons spelled out
        # on /live/clip_slot/create_audio_clip. The "ok"/"error" discriminator is
        # at a fixed index (1) on both paths; the two replies are deliberately
        # *not* the same length (success 4, refusal 3) and the refusal must not
        # be padded to match — the invariant is the discriminator's index.
        #
        # The created Clip is not addressable by any /live/clip/* address (that
        # needs the Arrangement and take-lane resolver, which is unranked), so
        # the reply carries back the position it was asked for plus the clip's
        # length, and /live/track/get/arrangement_clips/start_time is how a
        # caller finds it again.
        #
        # Under `*` this fans out, creating one clip per regular track and
        # replying once per track. The effects are not all-or-nothing: clips
        # created on earlier tracks stay created. A refused name is not a raise,
        # so a bad name under `*` produces N "error" replies and creates nothing.
        #--------------------------------------------------------------------------------
        def track_create_audio_clip(track, params: Tuple[Any] = ()):
            #--------------------------------------------------------------------------------
            # A missing or non-numeric position is a refusal, not an IndexError or
            # a ValueError: either would be a silent wildcard skip on a
            # /live/track/* pattern request, so a malformed request could
            # masquerade as "this endpoint does not apply".
            #--------------------------------------------------------------------------------
            if len(params) < 2:
                message = "expected [name, position], got %d argument(s)" % len(params)
                self.logger.error("track create_audio_clip refused: %s" % message)
                return ("error", message)
            try:
                position = float(params[1])
            except (TypeError, ValueError):
                message = "position must be a number, got %r" % (params[1],)
                self.logger.error("track create_audio_clip refused: %s" % message)
                return ("error", message)

            try:
                path = resolve_import_path(params[0])
            except ImportPathError as e:
                self.logger.error("track create_audio_clip refused: %s" % e)
                return ("error", str(e))

            try:
                clip = track.create_audio_clip(path, position)
            except Exception as e:
                self.logger.error("track create_audio_clip failed: %s" % e)
                return ("error", str(e))

            #--------------------------------------------------------------------------------
            # -1.0 rather than a shorter reply if the length cannot be read: the
            # arity is part of the contract on the success path.
            #--------------------------------------------------------------------------------
            try:
                length = float(clip.length)
            except Exception:
                length = -1.0

            return ("ok", position, length)

        self.osc_server.add_handler("/live/track/create_audio_clip",
                                    create_track_callback(track_create_audio_clip))

        def track_get_clip_names(track, _):
            return tuple(clip_slot.clip.name if clip_slot.clip else None for clip_slot in track.clip_slots)

        def track_get_clip_lengths(track, _):
            return tuple(clip_slot.clip.length if clip_slot.clip else None for clip_slot in track.clip_slots)

        def track_get_clip_colors(track, _):
            return tuple(clip_slot.clip.color if clip_slot.clip else None for clip_slot in track.clip_slots)

        def track_get_arrangement_clip_names(track, _):
            return tuple(clip.name for clip in track.arrangement_clips)

        def track_get_arrangement_clip_lengths(track, _):
            return tuple(clip.length for clip in track.arrangement_clips)

        def track_get_arrangement_clip_start_times(track, _):
            return tuple(clip.start_time for clip in track.arrangement_clips)

        """
        Returns a list of clip properties, or Nil if clip is empty
        """
        self.osc_server.add_handler("/live/track/get/clips/name", create_track_callback(track_get_clip_names))
        self.osc_server.add_handler("/live/track/get/clips/length", create_track_callback(track_get_clip_lengths))
        self.osc_server.add_handler("/live/track/get/clips/color", create_track_callback(track_get_clip_colors))
        self.osc_server.add_handler("/live/track/get/arrangement_clips/name", create_track_callback(track_get_arrangement_clip_names))
        self.osc_server.add_handler("/live/track/get/arrangement_clips/length", create_track_callback(track_get_arrangement_clip_lengths))
        self.osc_server.add_handler("/live/track/get/arrangement_clips/start_time", create_track_callback(track_get_arrangement_clip_start_times))

        def track_get_num_devices(track, _):
            return len(track.devices),

        def track_get_device_names(track, _):
            return tuple(device.name for device in track.devices)

        def track_get_device_types(track, _):
            return tuple(device.type for device in track.devices)

        def track_get_device_class_names(track, _):
            return tuple(device.class_name for device in track.devices)

        def track_get_device_can_have_chains(track, _):
            return tuple(device.can_have_chains for device in track.devices)

        """
         - name: the device's human-readable name
         - type: 1 = instrument, 2 = audio_effect, 4 = midi_effect.
           Measured against Live 12.4.3 on 2026-07-31: an Operator reports 1, a
           Reverb and an EQ Eight report 2. This comment used to say
           0 = audio_effect, 1 = instrument, 2 = midi_effect — any source still
           claiming that is repeating the old guess.
         - class_name: e.g. Operator, Reverb, AuPluginDevice, PluginDevice, InstrumentGroupDevice
        """
        self.osc_server.add_handler("/live/track/get/num_devices", create_track_callback(track_get_num_devices))
        self.osc_server.add_handler("/live/track/get/devices/name", create_track_callback(track_get_device_names))
        self.osc_server.add_handler("/live/track/get/devices/type", create_track_callback(track_get_device_types))
        self.osc_server.add_handler("/live/track/get/devices/class_name", create_track_callback(track_get_device_class_names))
        self.osc_server.add_handler("/live/track/get/devices/can_have_chains", create_track_callback(track_get_device_can_have_chains))

        #--------------------------------------------------------------------------------
        # Track: the group track this track belongs to.
        #
        # Seshat extension (A-4, object-valued reads). `Track.group_track` is a
        # Track object, so the generic property loop could only ever answer it
        # as an unencodable value; this answers the group's index in
        # song.tracks — the coordinate every other /live/track/* address takes
        # — and -1 when the track is not grouped. Resolution lives in the
        # Live-free track_identity.py; see API.md § "Object-valued reads".
        #
        # No listen pair: group_track is not an observable property (measured
        # against Live 12.4.3 in the FORK_GAPS inventory), so there is no
        # add_group_track_listener to bind.
        #--------------------------------------------------------------------------------
        def track_get_group_track(track, params: Tuple[Any] = ()):
            index = group_track_index(self.song, track)
            self.logger.info("Getting property for track: group_track = %s" % index)
            return (index,)

        self.osc_server.add_handler("/live/track/get/group_track",
                                    create_track_callback(track_get_group_track))

        #--------------------------------------------------------------------------------
        # Track: Output routing.
        # An output route has a type (e.g. "Ext. Out") and a channel (e.g. "1/2").
        # Since Live 10, both of these need to be set by reference to the appropriate
        # item in the available_output_routing_types vector.
        #--------------------------------------------------------------------------------
        def track_get_available_output_routing_types(track, _):
            return tuple([routing_type.display_name for routing_type in track.available_output_routing_types])
        def track_get_available_output_routing_channels(track, _):
            return tuple([routing_channel.display_name for routing_channel in track.available_output_routing_channels])
        def track_get_output_routing_type(track, _):
            return track.output_routing_type.display_name,
        def track_set_output_routing_type(track, params):
            type_name = str(params[0])
            for routing_type in track.available_output_routing_types:
                if routing_type.display_name == type_name:
                    track.output_routing_type = routing_type
                    return
            self.logger.warning("Couldn't find output routing type: %s" % type_name)
        def track_get_output_routing_channel(track, _):
            return track.output_routing_channel.display_name,
        def track_set_output_routing_channel(track, params):
            channel_name = str(params[0])
            for channel in track.available_output_routing_channels:
                if channel.display_name == channel_name:
                    track.output_routing_channel = channel
                    return
            self.logger.warning("Couldn't find output routing channel: %s" % channel_name)

        self.osc_server.add_handler("/live/track/get/available_output_routing_types", create_track_callback(track_get_available_output_routing_types))
        self.osc_server.add_handler("/live/track/get/available_output_routing_channels", create_track_callback(track_get_available_output_routing_channels))
        self.osc_server.add_handler("/live/track/get/output_routing_type", create_track_callback(track_get_output_routing_type))
        self.osc_server.add_handler("/live/track/set/output_routing_type", create_track_callback(track_set_output_routing_type))
        self.osc_server.add_handler("/live/track/get/output_routing_channel", create_track_callback(track_get_output_routing_channel))
        self.osc_server.add_handler("/live/track/set/output_routing_channel", create_track_callback(track_set_output_routing_channel))

        #--------------------------------------------------------------------------------
        # Track: Input routing.
        #--------------------------------------------------------------------------------
        def track_get_available_input_routing_types(track, _):
            return tuple([routing_type.display_name for routing_type in track.available_input_routing_types])
        def track_get_available_input_routing_channels(track, _):
            return tuple([routing_channel.display_name for routing_channel in track.available_input_routing_channels])
        def track_get_input_routing_type(track, _):
            return track.input_routing_type.display_name,
        def track_set_input_routing_type(track, params):
            type_name = str(params[0])
            for routing_type in track.available_input_routing_types:
                if routing_type.display_name == type_name:
                    track.input_routing_type = routing_type
                    return
            self.logger.warning("Couldn't find input routing type: %s" % type_name)
        def track_get_input_routing_channel(track, _):
            return track.input_routing_channel.display_name,
        def track_set_input_routing_channel(track, params):
            channel_name = str(params[0])
            for channel in track.available_input_routing_channels:
                if channel.display_name == channel_name:
                    track.input_routing_channel = channel
                    return
            self.logger.warning("Couldn't find input routing channel: %s" % channel_name)

        self.osc_server.add_handler("/live/track/get/available_input_routing_types", create_track_callback(track_get_available_input_routing_types))
        self.osc_server.add_handler("/live/track/get/available_input_routing_channels", create_track_callback(track_get_available_input_routing_channels))
        self.osc_server.add_handler("/live/track/get/input_routing_type", create_track_callback(track_get_input_routing_type))
        self.osc_server.add_handler("/live/track/set/input_routing_type", create_track_callback(track_set_input_routing_type))
        self.osc_server.add_handler("/live/track/get/input_routing_channel", create_track_callback(track_get_input_routing_channel))
        self.osc_server.add_handler("/live/track/set/input_routing_channel", create_track_callback(track_set_input_routing_channel))

    def _set_mixer_property(self, target, prop, params: Tuple) -> None:
        parameter_object = getattr(target.mixer_device, prop)
        self.logger.info("Setting property for %s: %s (new value %s)" % (self.class_identifier, prop, params[0]))
        parameter_object.value = params[0]

    def _get_mixer_property(self, target, prop, params: Optional[Tuple] = ()) -> Tuple[Any]:
        parameter_object = getattr(target.mixer_device, prop)
        self.logger.info("Getting property for %s: %s = %s" % (self.class_identifier, prop, parameter_object.value))
        return parameter_object.value,

    #--------------------------------------------------------------------------------
    # A mixer listener is not bound to the track: it is bound to a DeviceParameter
    # (`mixer_device.volume` and friends), whose change notification is
    # add_value_listener. So it is registered under the base class's bookkeeping as
    # the property "value", with the track index and the mixer property name
    # together forming the params half of the key — ("value", (track_id, "volume")).
    #
    # That shape is what lets _stop_mixer_listen delegate to the base _stop_listen:
    # the base derives its removal method from the key's prop, and "value" yields
    # remove_value_listener, which is the correct one for a DeviceParameter. It also
    # means _clear_listeners handles mixer keys with no special case.
    #--------------------------------------------------------------------------------
    def _mixer_listener_params(self, prop, params: Optional[Tuple] = ()) -> Tuple[Any]:
        return (*tuple(params), prop)

    def _start_mixer_listen(self, target, prop, params: Optional[Tuple] = ()) -> None:
        parameter_object = getattr(target.mixer_device, prop)
        def property_changed_callback():
            value = parameter_object.value
            self.logger.info("Property %s changed of %s %s: %s" % (prop, self.class_identifier, str(params), value))
            osc_address = "/live/%s/get/%s" % (self.class_identifier, prop)
            self.osc_server.send(osc_address, (*params, value,))

        #--------------------------------------------------------------------------------
        # Hand-rolled rather than delegated to _start_listen, only because the reply
        # address and payload differ: the base class would derive
        # /live/track/get/value and send the property name on the wire. All the
        # bookkeeping below is the base class's own, and must stay that way.
        #--------------------------------------------------------------------------------
        listener_key = ("value", self._mixer_listener_params(prop, params))
        self._stop_mixer_listen(target, prop, params)

        self.logger.info("Adding listener for %s %s, property: %s" % (self.class_identifier, str(params), prop))

        parameter_object.add_value_listener(property_changed_callback)
        self.listener_functions[listener_key] = property_changed_callback
        self.listener_objects[listener_key] = parameter_object
        #--------------------------------------------------------------------------------
        # Immediately send the current value
        #--------------------------------------------------------------------------------
        property_changed_callback()

    def _stop_mixer_listen(self, target, prop, params: Optional[Tuple[Any]] = ()) -> None:
        #--------------------------------------------------------------------------------
        # Silent when nothing is registered — unlike the base class, which warns.
        # _start_mixer_listen calls through here unconditionally to make re-listening
        # idempotent, and a first subscribe is not a missing-listener error.
        #--------------------------------------------------------------------------------
        # No target: the base class resolves the DeviceParameter out of
        # listener_objects, and re-deriving it from the track we were handed would
        # touch the very object the fix exists to stop trusting — after a renumber
        # that track may not be the one the callback was registered on, and if it
        # has been deleted the attribute access raises before _stop_listen runs.
        listener_params = self._mixer_listener_params(prop, params)
        if ("value", listener_params) in self.listener_functions:
            self._stop_listen(None, "value", listener_params)
