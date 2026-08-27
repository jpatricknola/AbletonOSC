from typing import Tuple, Any
from .handler import AbletonOSCHandler

class ClipSlotHandler(AbletonOSCHandler):
    class_identifier = "clip_slot"

    def init_api(self):
        def create_clip_slot_callback(func, *args, pass_clip_index=False):
            def clip_slot_callback(params: Tuple[Any]):
                track_index, clip_index = int(params[0]), int(params[1])
                track = self.song.tracks[track_index]
                clip_slot = track.clip_slots[clip_index]

                if pass_clip_index:
                    #--------------------------------------------------------------------------------
                    # Hand the callee the *normalised, truncated* identity, not the raw
                    # OSC args. pass_clip_index is used by the listen pair and by
                    # get/clip, the one getter whose *reply* contains its own slot
                    # index; either way the identity has to be canonical — it is the
                    # bookkeeping key and the LOM subscript, and for the listen pair
                    # also the echo in the push, so it must agree across a start/stop
                    # pair sent by different clients. TouchOSC-style clients send
                    # floats by default (upstream issue #33). A clip slot subscription's
                    # identity is exactly two ints; anything past them is dropped, so a
                    # stray trailing argument cannot key a second subscription that a
                    # well-formed stop can never reach.
                    #--------------------------------------------------------------------------------
                    rv = func(clip_slot, *args, (track_index, clip_index))
                else:
                    rv = func(clip_slot, *args, tuple(params[2:]))

                self.logger.info("clip_slot %s %s -> %s", track_index, clip_index, rv)
                if rv is not None:
                    return (track_index, clip_index, *rv)

            return clip_slot_callback

        methods = [
            "fire",
            "stop",
            "create_clip",
            "delete_clip"
        ]
        properties_r = [
            "has_clip",
            "controls_other_clips",
            "is_group_slot",
            "is_playing",
            "is_triggered",
            "playing_status",
            "will_record_on_start",
        ]
        properties_rw = [
            "has_stop_button"
        ]

        for method in methods:
            self.osc_server.add_handler("/live/clip_slot/%s" % method,
                                        create_clip_slot_callback(self._call_method, method))

        for prop in properties_r + properties_rw:
            self.osc_server.add_handler("/live/clip_slot/get/%s" % prop,
                                        create_clip_slot_callback(self._get_property, prop))
            self.osc_server.add_handler("/live/clip_slot/start_listen/%s" % prop,
                                        create_clip_slot_callback(self._start_listen, prop, pass_clip_index=True))
            self.osc_server.add_handler("/live/clip_slot/stop_listen/%s" % prop,
                                        create_clip_slot_callback(self._stop_listen, prop, pass_clip_index=True))
        for prop in properties_rw:
            self.osc_server.add_handler("/live/clip_slot/set/%s" % prop,
                                        create_clip_slot_callback(self._set_property, prop))

        #--------------------------------------------------------------------------------
        # Seshat extension (A-4, object-valued reads). `ClipSlot.clip` is a Clip
        # object, unencodable by the generic property loop; this answers the
        # clip's index in /live/clip/* coordinates — which is the slot's own
        # clip_index — or -1 when the slot is empty. The object-read form of
        # get/has_clip; see API.md § "Object-valued reads".
        #
        # pass_clip_index=True is load-bearing: without it the callee is handed
        # `params[2:]`, which is empty for a two-argument get, so it would have
        # no clip_index to answer with. Reading params directly instead would
        # echo an un-normalised float from a TouchOSC-style client.
        #--------------------------------------------------------------------------------
        def clip_slot_get_clip(clip_slot, identity: Tuple[Any] = ()):
            clip_index = identity[1] if clip_slot.clip is not None else -1
            self.logger.info("Getting property for clip_slot: clip = %s" % clip_index)
            return (clip_index,)

        self.osc_server.add_handler("/live/clip_slot/get/clip",
                                    create_clip_slot_callback(clip_slot_get_clip,
                                                              pass_clip_index=True))

        def duplicate_clip_slot(clip_slot, args):
            target_track_index, target_clip_index = tuple(args)
            track = self.song.tracks[target_track_index]
            target_clip_slot = track.clip_slots[target_clip_index]
            clip_slot.duplicate_clip_to(target_clip_slot)

        self.osc_server.add_handler("/live/clip_slot/duplicate_clip_to", create_clip_slot_callback(duplicate_clip_slot))
