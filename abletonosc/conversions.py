"""
Live.Conversions — audio-to-MIDI and the Simpler/Drum Rack conversions.

A Seshat extension; see SESHAT.md and API.md § "Conversions API".

Live.Conversions is a registered Boost.Python module whose members are
module-level free functions, not methods on a LOM object. It was invisible to
this fork's own gap inventory until the walker was taught to record
module-level members (see BLIND_SPOTS.md), which is why these addresses arrive
long after the rest of the clip surface.

Measured signatures, read from Live 12.4.5's running interpreter:

    audio_to_midi_clip( (Song)song, (Clip)audio_clip, (int)audio_to_midi_type) -> None
    is_convertible_to_midi( (Song)song, (Clip)audio_clip) -> bool
    create_midi_track_with_simpler( (Song)song, (Clip)audio_clip) -> None
    create_drum_rack_from_audio_clip( (Song)song, (Clip)audio_clip) -> None
    sliced_simpler_to_drum_rack( (Song)song, (SimplerDevice)simpler) -> None

Every one of them takes the Song as its first argument, which the binary's
string table did not show and which the issue proposing these addresses did not
assume. Every one of the four exposed here returns None, so a handler that
wants to tell a client where the new track landed has to read it back itself —
see _new_track_index().
"""
from typing import Any, Tuple

import Live

from .handler import AbletonOSCHandler

#--------------------------------------------------------------------------------
# The wire spelling of Live.Conversions.AudioToMidiType.
#
# A *name*, never the raw enum integer. Boost.Python enum values are positional
# and a member added in a future Live would silently reassign them, and the
# declared signature is `(int)`, so Live itself would accept a stale positional
# value without complaint. The short spellings are the ones a client will
# reach for; the full ones are Live's own member names, accepted so that a
# caller reading the LOM can use what it read.
#--------------------------------------------------------------------------------
AUDIO_TO_MIDI_TYPES = ("harmony", "melody", "drums")


def resolve_audio_to_midi_type(name):
    """
    Map a wire name to a Live.Conversions.AudioToMidiType member.

    Raises ValueError naming the accepted spellings, which the callers turn
    into an ("error", ...) envelope rather than letting it reach Live.
    """
    if not isinstance(name, str):
        raise ValueError("audio_to_midi type must be a name, not %r — one of: %s"
                         % (name, ", ".join(AUDIO_TO_MIDI_TYPES)))
    key = name.strip().lower()
    if key.endswith("_to_midi"):
        key = key[:-len("_to_midi")]
    if key not in AUDIO_TO_MIDI_TYPES:
        raise ValueError("unknown audio_to_midi type %r — one of: %s"
                         % (name, ", ".join(AUDIO_TO_MIDI_TYPES)))
    #--------------------------------------------------------------------------------
    # Resolved from Live at call time, not bound at import time: Live.Conversions
    # is absent from older Live versions, and this module must import there
    # rather than taking the whole Remote Script down at startup.
    #--------------------------------------------------------------------------------
    conversions = getattr(Live, "Conversions", None)
    if conversions is None:
        raise ValueError("this Live has no Live.Conversions module")
    return getattr(conversions.AudioToMidiType, key + "_to_midi")


class ConversionsHandler(AbletonOSCHandler):
    #--------------------------------------------------------------------------------
    # "clip" because every address but one is clip-keyed. Nothing here is
    # observable — these are functions, not properties — so no listener is ever
    # registered and class_identifier is never used as a push prefix. It is set
    # for consistency with song_structure.py, which likewise registers under
    # another handler's address prefix.
    #--------------------------------------------------------------------------------
    class_identifier = "clip"

    def _clip(self, params: Tuple[Any]):
        #--------------------------------------------------------------------------------
        # Cast to int for clients such as TouchOSC that send all numerics as
        # float, matching create_clip_callback in clip.py.
        #--------------------------------------------------------------------------------
        track_index, clip_index = int(params[0]), int(params[1])
        return self.song.tracks[track_index].clip_slots[clip_index].clip

    def _track_ptrs(self):
        #--------------------------------------------------------------------------------
        # `_live_ptr` is the only stable identity a LOM object carries: Boost.Python
        # hands out a fresh wrapper on each attribute access, so `id()` is not
        # stable and `track in tracks` is not reliable across a call.
        #--------------------------------------------------------------------------------
        return [track._live_ptr for track in self.song.tracks]

    def _new_track_index(self, before):
        """
        Index of the track that appeared since `before`, or -1 if none did.

        -1 is an answer, never an argument (API.md). It is the honest reply
        when the conversion was accepted but no track had appeared by the time
        the handler returned — which is what a caller would see if Live
        performs the conversion asynchronously. It is not an error: the caller
        re-reads /live/song/get/num_tracks rather than concluding failure.
        """
        try:
            seen = set(before)
            for index, ptr in enumerate(self._track_ptrs()):
                if ptr not in seen:
                    return index
        except Exception as e:
            #--------------------------------------------------------------------------------
            # Never let the read-back turn a conversion that already happened
            # into a reported failure. The mutation is done; only the reply is
            # degraded.
            #--------------------------------------------------------------------------------
            self.logger.error("conversions: new-track read-back failed: %s" % e)
        return -1

    def _convert(self, name, params, extra=()):
        """
        Shared body for the three clip-keyed conversions that create a track.

        Returns the ("ok", new_track_index) / ("error", message) envelope used
        by every mutating fork handler (see /live/device/replace_sample).
        """
        conversions = getattr(Live, "Conversions", None)
        if conversions is None:
            return ("error", "this Live has no Live.Conversions module")
        try:
            clip = self._clip(params)
        except Exception as e:
            self.logger.error("conversions %s: could not resolve clip: %s" % (name, e))
            return ("error", str(e))
        if clip is None:
            return ("error", "no clip at that track and clip slot")

        before = self._track_ptrs()
        try:
            getattr(conversions, name)(self.song, clip, *extra)
        except Exception as e:
            self.logger.error("conversions %s failed: %s" % (name, e))
            return ("error", str(e))
        return ("ok", self._new_track_index(before))

    def init_api(self):
        #--------------------------------------------------------------------------------
        # Read. Live's own is_convertible_to_midi raises when handed a MIDI clip
        # rather than answering false, which makes it useless as the predicate a
        # client actually wants: "may I offer this conversion?" is asked *before*
        # mutating, and an exception is not an answer. So a MIDI clip is
        # pre-checked here and answered false, and Live is not called. The
        # divergence from the raw LOM member is documented in API.md.
        #--------------------------------------------------------------------------------
        def clip_is_convertible_to_midi(params: Tuple[Any] = ()) -> Tuple:
            track_index, clip_index = int(params[0]), int(params[1])
            clip = self._clip(params)
            if clip is None:
                return (track_index, clip_index, False)
            if not clip.is_audio_clip:
                return (track_index, clip_index, False)
            conversions = getattr(Live, "Conversions", None)
            if conversions is None:
                return (track_index, clip_index, False)
            return (track_index, clip_index,
                    bool(conversions.is_convertible_to_midi(self.song, clip)))

        self.osc_server.add_handler("/live/clip/get/is_convertible_to_midi",
                                    clip_is_convertible_to_midi)

        #--------------------------------------------------------------------------------
        # Mutations. Each creates a new track and returns None from Live, so the
        # reply carries the index this handler read back. The echoed
        # (track_index, clip_index) prefix matches every other /live/clip/*
        # reply.
        #--------------------------------------------------------------------------------
        def clip_audio_to_midi(params: Tuple[Any] = ()) -> Tuple:
            track_index, clip_index = int(params[0]), int(params[1])
            try:
                conversion_type = resolve_audio_to_midi_type(
                    params[2] if len(params) > 2 else None)
            except ValueError as e:
                self.logger.error("conversions audio_to_midi refused: %s" % e)
                return (track_index, clip_index, "error", str(e))
            return (track_index, clip_index,
                    *self._convert("audio_to_midi_clip", params, (conversion_type,)))

        def clip_create_midi_track_with_simpler(params: Tuple[Any] = ()) -> Tuple:
            track_index, clip_index = int(params[0]), int(params[1])
            return (track_index, clip_index,
                    *self._convert("create_midi_track_with_simpler", params))

        def clip_create_drum_rack(params: Tuple[Any] = ()) -> Tuple:
            track_index, clip_index = int(params[0]), int(params[1])
            return (track_index, clip_index,
                    *self._convert("create_drum_rack_from_audio_clip", params))

        self.osc_server.add_handler("/live/clip/audio_to_midi", clip_audio_to_midi)
        self.osc_server.add_handler("/live/clip/create_midi_track_with_simpler",
                                    clip_create_midi_track_with_simpler)
        self.osc_server.add_handler("/live/clip/create_drum_rack_from_audio_clip",
                                    clip_create_drum_rack)

        #--------------------------------------------------------------------------------
        # Device-keyed. Live's *Slice to New MIDI Track*, which FORK_GAPS.md
        # recorded as UI-only and planned around by having the client rebuild
        # the trigger clip from slice times. It is not UI-only.
        #
        # Top-level devices on a regular track, like every other /live/device/*
        # address; a Simpler inside a rack waits on the device path resolver.
        #--------------------------------------------------------------------------------
        def device_sliced_simpler_to_drum_rack(params: Tuple[Any] = ()) -> Tuple:
            track_index, device_index = int(params[0]), int(params[1])
            conversions = getattr(Live, "Conversions", None)
            if conversions is None:
                return (track_index, device_index, "error",
                        "this Live has no Live.Conversions module")
            try:
                device = self.song.tracks[track_index].devices[device_index]
            except Exception as e:
                self.logger.error("conversions sliced_simpler_to_drum_rack: "
                                  "could not resolve device: %s" % e)
                return (track_index, device_index, "error", str(e))

            before = self._track_ptrs()
            try:
                conversions.sliced_simpler_to_drum_rack(self.song, device)
            except Exception as e:
                self.logger.error("conversions sliced_simpler_to_drum_rack failed: %s" % e)
                return (track_index, device_index, "error", str(e))
            return (track_index, device_index, "ok", self._new_track_index(before))

        self.osc_server.add_handler("/live/device/sliced_simpler_to_drum_rack",
                                    device_sliced_simpler_to_drum_rack)
