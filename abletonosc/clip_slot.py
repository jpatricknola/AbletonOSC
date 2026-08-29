from typing import Tuple, Any
from .handler import AbletonOSCHandler
from .path_safety import ImportPathError, resolve_import_path

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

        #--------------------------------------------------------------------------------
        # Seshat extension: import an audio file into this slot as a clip.
        #
        #   /live/clip_slot/create_audio_clip [track_index, clip_index, name]
        #     -> [track_index, clip_index, "ok", length]
        #     -> [track_index, clip_index, "error", message]
        #
        # `name` is a path *relative to* path_safety.IMPORT_ROOT, never an
        # absolute path — see path_safety.py and API.md § "Handlers that name a
        # file to read". Nothing is opened and no Live method is called on a
        # refused name.
        #
        # This address always replies, including on every refusal — browser.py's
        # convention, not the silent-on-success convention of the generic
        # /live/clip_slot/<method> loop above. A path refusal is caller-fixable
        # and undiagnosable from silence, the consumer needs `length` back, and
        # silence would otherwise be indistinguishable from an install that
        # predates this address.
        #
        # The split between the two failure channels is deliberate and
        # documented: a bad track_index or clip_index raises inside
        # create_clip_slot_callback's lookup *before* this worker runs, so it
        # arrives as the structured /live/error envelope like every other
        # clip-slot address. Everything this worker can decide arrives as an
        # "error" reply on the request address instead. The "ok"/"error"
        # discriminator is at a fixed index (2) on both paths, so a client
        # switches on it positionally.
        #
        # The has_clip refusal is the fork's own, not Live's: what Live does
        # with an occupied slot is unmeasured, and an explicit refusal is what
        # the consumer wants either way.
        #--------------------------------------------------------------------------------
        def clip_slot_create_audio_clip(clip_slot, params: Tuple[Any] = ()):
            #--------------------------------------------------------------------------------
            # params[0] is handed to the rule *unmodified*: a non-string is the
            # rule's own refusal, not something coerced into a plausible name
            # here. A missing argument becomes the empty string, so a malformed
            # request is an "error" reply rather than an IndexError escaping as a
            # structured error the caller cannot tell from a bad index.
            #--------------------------------------------------------------------------------
            try:
                path = resolve_import_path(params[0] if params else "")
            except ImportPathError as e:
                self.logger.error("clip_slot create_audio_clip refused: %s" % e)
                return ("error", str(e))

            if clip_slot.has_clip:
                message = "clip slot already contains a clip"
                self.logger.error("clip_slot create_audio_clip refused: %s" % message)
                return ("error", message)

            try:
                clip = clip_slot.create_audio_clip(path)
            except Exception as e:
                self.logger.error("clip_slot create_audio_clip failed: %s" % e)
                return ("error", str(e))

            #--------------------------------------------------------------------------------
            # Read the length back off the returned Clip, falling back to the
            # slot's own clip. -1.0 rather than a shorter reply if neither can be
            # read: the arity is part of the contract, the discriminator is not
            # allowed to move.
            #--------------------------------------------------------------------------------
            length = -1.0
            for candidate in (clip, getattr(clip_slot, "clip", None)):
                try:
                    length = float(candidate.length)
                except Exception:
                    continue
                break

            return ("ok", length)

        self.osc_server.add_handler("/live/clip_slot/create_audio_clip",
                                    create_clip_slot_callback(clip_slot_create_audio_clip))

        def duplicate_clip_slot(clip_slot, args):
            target_track_index, target_clip_index = tuple(args)
            track = self.song.tracks[target_track_index]
            target_clip_slot = track.clip_slots[target_clip_index]
            clip_slot.duplicate_clip_to(target_clip_slot)

        self.osc_server.add_handler("/live/clip_slot/duplicate_clip_to", create_clip_slot_callback(duplicate_clip_slot))
