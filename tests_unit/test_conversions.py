"""
Live.Conversions addresses, dispatched end to end through the production
ConversionsHandler on the production OSCServer.

Live-free. The Live stub carries a fake `Conversions` namespace for the tests
that need one, recording the arguments it was handed, so the two things no
inspection of Live can prove are pinned here instead:

1. **Every member takes the Song first.** The measured signature is
   `audio_to_midi_clip( (Song)song, (Clip)audio_clip, (int)audio_to_midi_type)`,
   and the issue that proposed these addresses assumed it did not. A handler
   that dropped the song argument would still look right in review and would
   fail only against a real Live.
2. **The reply's track index is read back, not returned by Live.** Every
   exposed member returns None, so a handler that trusted the return value
   would answer `None` forever.

The `-1` reply is the honest answer when no track appeared — the shape a
caller would see if Live performs the conversion asynchronously, which is
still unmeasured. It is not an error.
"""

import sys
import types

import pytest

from .conftest import dispatch, load_conversions_module


class FakeManager:
    def __init__(self, osc_server):
        self.osc_server = osc_server


class FakeClip:
    def __init__(self, is_audio_clip=True):
        self.is_audio_clip = is_audio_clip


class FakeClipSlot:
    def __init__(self, clip):
        self.clip = clip


class FakeTrack:
    #--------------------------------------------------------------------------------
    # `_live_ptr` is what the handler reads to tell tracks apart, because
    # Boost.Python hands out a fresh wrapper on each access and `id()` is not
    # stable across a call. The fakes carry one for the same reason.
    #--------------------------------------------------------------------------------
    def __init__(self, ptr, clip_slots=(), devices=()):
        self._live_ptr = ptr
        self.clip_slots = list(clip_slots)
        self.devices = list(devices)


class FakeSong:
    def __init__(self, tracks):
        self.tracks = list(tracks)


class FakeConversions:
    """
    Records every call, and optionally appends a track to `song.tracks` to
    stand in for Live creating one.
    """

    def __init__(self, creates_track=True, raises=None):
        self.calls = []
        self.creates_track = creates_track
        self.raises = raises
        self.convertible = True

    def _record(self, name, args):
        self.calls.append((name, args))
        if self.raises:
            raise self.raises
        if self.creates_track:
            song = args[0]
            song.tracks.append(FakeTrack(ptr=999))

    def audio_to_midi_clip(self, song, clip, conversion_type):
        self._record("audio_to_midi_clip", (song, clip, conversion_type))

    def create_midi_track_with_simpler(self, song, clip):
        self._record("create_midi_track_with_simpler", (song, clip))

    def create_drum_rack_from_audio_clip(self, song, clip):
        self._record("create_drum_rack_from_audio_clip", (song, clip))

    def sliced_simpler_to_drum_rack(self, song, simpler):
        self._record("sliced_simpler_to_drum_rack", (song, simpler))

    def is_convertible_to_midi(self, song, clip):
        self.calls.append(("is_convertible_to_midi", (song, clip)))
        return self.convertible


class FakeAudioToMidiType:
    harmony_to_midi = 0
    melody_to_midi = 1
    drums_to_midi = 2


def replies(messages, address):
    return [params for addr, params in messages if addr == address]


@pytest.fixture
def conversions_module():
    return load_conversions_module()


@pytest.fixture
def song():
    clip = FakeClip()
    midi_clip = FakeClip(is_audio_clip=False)
    simpler = object()
    return FakeSong([FakeTrack(ptr=1,
                               clip_slots=[FakeClipSlot(clip),
                                           FakeClipSlot(midi_clip),
                                           FakeClipSlot(None)],
                               devices=[simpler])])


@pytest.fixture
def live_conversions(monkeypatch, conversions_module):
    """Install a recording `Conversions` on the Live stub for one test."""
    fake = FakeConversions()
    fake.AudioToMidiType = FakeAudioToMidiType
    monkeypatch.setattr(sys.modules["Live"], "Conversions", fake, raising=False)
    return fake


@pytest.fixture
def handler(server, conversions_module, song):
    h = conversions_module.ConversionsHandler(FakeManager(server))
    h.song = song
    return h


#--------------------------------------------------------------------------------
# The type name mapping
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("harmony", 0), ("melody", 1), ("drums", 2),
    ("harmony_to_midi", 0), ("MELODY", 1), ("  drums  ", 2),
])
def test_type_names_map_to_the_enum(conversions_module, live_conversions, name, expected):
    assert conversions_module.resolve_audio_to_midi_type(name) == expected


@pytest.mark.parametrize("name", ["nonsense", "", None, 0, 1])
def test_unknown_type_names_are_refused(conversions_module, live_conversions, name):
    #--------------------------------------------------------------------------------
    # 0 and 1 are refused as deliberately as "nonsense". Live's own signature
    # declares `(int)`, so a raw positional value would be accepted by Live and
    # silently reassigned by any future enum member. The wire takes names.
    #--------------------------------------------------------------------------------
    with pytest.raises(ValueError):
        conversions_module.resolve_audio_to_midi_type(name)


#--------------------------------------------------------------------------------
# is_convertible_to_midi
#--------------------------------------------------------------------------------

def test_is_convertible_answers_true_for_a_convertible_audio_clip(
        handler, server, receiver, live_conversions):
    dispatch(server, "/live/clip/get/is_convertible_to_midi", 0, 0)
    assert replies(receiver.drain(),
                   "/live/clip/get/is_convertible_to_midi") == [(0, 0, True)]


def test_is_convertible_answers_false_for_a_midi_clip_without_calling_live(
        handler, server, receiver, live_conversions):
    #--------------------------------------------------------------------------------
    # Live's member raises on a MIDI clip rather than answering false, which
    # makes it useless as a "may I offer this?" predicate. The pre-check is the
    # documented divergence from the raw LOM member, and Live is not called.
    #--------------------------------------------------------------------------------
    dispatch(server, "/live/clip/get/is_convertible_to_midi", 0, 1)
    assert replies(receiver.drain(),
                   "/live/clip/get/is_convertible_to_midi") == [(0, 1, False)]
    assert live_conversions.calls == []


def test_is_convertible_answers_false_for_an_empty_slot(
        handler, server, receiver, live_conversions):
    dispatch(server, "/live/clip/get/is_convertible_to_midi", 0, 2)
    assert replies(receiver.drain(),
                   "/live/clip/get/is_convertible_to_midi") == [(0, 2, False)]
    assert live_conversions.calls == []


def test_is_convertible_passes_the_song_and_the_clip_the_query_named(
        handler, server, receiver, live_conversions, song):
    dispatch(server, "/live/clip/get/is_convertible_to_midi", 0, 0)
    name, args = live_conversions.calls[0]
    assert name == "is_convertible_to_midi"
    assert args == (song, song.tracks[0].clip_slots[0].clip)


#--------------------------------------------------------------------------------
# audio_to_midi
#--------------------------------------------------------------------------------

def test_audio_to_midi_passes_song_clip_and_mapped_type(
        handler, server, receiver, live_conversions, song):
    dispatch(server, "/live/clip/audio_to_midi", 0, 0, "melody")
    name, args = live_conversions.calls[0]
    assert name == "audio_to_midi_clip"
    assert args == (song, song.tracks[0].clip_slots[0].clip, 1)


def test_audio_to_midi_replies_with_the_index_of_the_track_that_appeared(
        handler, server, receiver, live_conversions):
    dispatch(server, "/live/clip/audio_to_midi", 0, 0, "melody")
    assert replies(receiver.drain(), "/live/clip/audio_to_midi") == [(0, 0, "ok", 1)]


def test_audio_to_midi_replies_minus_one_when_no_track_appeared(
        handler, server, receiver, live_conversions):
    #--------------------------------------------------------------------------------
    # The shape a caller sees if Live converts asynchronously — still
    # unmeasured. -1 is an answer, never an argument (API.md); it is not an
    # error, and the caller re-reads num_tracks rather than concluding failure.
    #--------------------------------------------------------------------------------
    live_conversions.creates_track = False
    dispatch(server, "/live/clip/audio_to_midi", 0, 0, "drums")
    assert replies(receiver.drain(), "/live/clip/audio_to_midi") == [(0, 0, "ok", -1)]


def test_audio_to_midi_refuses_an_unknown_type_without_calling_live(
        handler, server, receiver, live_conversions):
    dispatch(server, "/live/clip/audio_to_midi", 0, 0, "nonsense")
    replied = replies(receiver.drain(), "/live/clip/audio_to_midi")
    assert len(replied) == 1
    assert replied[0][:3] == (0, 0, "error")
    assert live_conversions.calls == []


def test_audio_to_midi_refuses_a_missing_type_without_calling_live(
        handler, server, receiver, live_conversions):
    dispatch(server, "/live/clip/audio_to_midi", 0, 0)
    replied = replies(receiver.drain(), "/live/clip/audio_to_midi")
    assert replied[0][:3] == (0, 0, "error")
    assert live_conversions.calls == []


def test_audio_to_midi_reports_a_live_failure_as_an_error_envelope(
        handler, server, receiver, live_conversions):
    live_conversions.raises = RuntimeError("inconvertible clip")
    dispatch(server, "/live/clip/audio_to_midi", 0, 0, "harmony")
    replied = replies(receiver.drain(), "/live/clip/audio_to_midi")
    assert replied[0][:3] == (0, 0, "error")
    assert "inconvertible clip" in replied[0][3]


def test_audio_to_midi_refuses_an_empty_slot(handler, server, receiver, live_conversions):
    dispatch(server, "/live/clip/audio_to_midi", 0, 2, "harmony")
    replied = replies(receiver.drain(), "/live/clip/audio_to_midi")
    assert replied[0][:3] == (0, 2, "error")
    assert live_conversions.calls == []


#--------------------------------------------------------------------------------
# The two other clip-keyed conversions, and the device-keyed one
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("address,member", [
    ("/live/clip/create_midi_track_with_simpler", "create_midi_track_with_simpler"),
    ("/live/clip/create_drum_rack_from_audio_clip", "create_drum_rack_from_audio_clip"),
])
def test_clip_keyed_conversions_pass_song_and_clip_and_report_the_new_track(
        handler, server, receiver, live_conversions, song, address, member):
    dispatch(server, address, 0, 0)
    name, args = live_conversions.calls[0]
    assert name == member
    assert args == (song, song.tracks[0].clip_slots[0].clip)
    assert replies(receiver.drain(), address) == [(0, 0, "ok", 1)]


def test_sliced_simpler_to_drum_rack_passes_song_and_the_device(
        handler, server, receiver, live_conversions, song):
    dispatch(server, "/live/device/sliced_simpler_to_drum_rack", 0, 0)
    name, args = live_conversions.calls[0]
    assert name == "sliced_simpler_to_drum_rack"
    assert args == (song, song.tracks[0].devices[0])
    assert replies(receiver.drain(),
                   "/live/device/sliced_simpler_to_drum_rack") == [(0, 0, "ok", 1)]


def test_sliced_simpler_reports_a_bad_device_index_as_an_error_envelope(
        handler, server, receiver, live_conversions):
    dispatch(server, "/live/device/sliced_simpler_to_drum_rack", 0, 9)
    replied = replies(receiver.drain(), "/live/device/sliced_simpler_to_drum_rack")
    assert replied[0][:3] == (0, 9, "error")
    assert live_conversions.calls == []


#--------------------------------------------------------------------------------
# A Live without the module at all
#--------------------------------------------------------------------------------

def test_a_live_without_conversions_is_reported_not_raised(
        handler, server, receiver, monkeypatch):
    #--------------------------------------------------------------------------------
    # Live.Conversions is absent from older Live versions. The module must
    # import there and the addresses must answer, rather than the Remote Script
    # failing at startup or the address raising.
    #--------------------------------------------------------------------------------
    monkeypatch.delattr(sys.modules["Live"], "Conversions", raising=False)
    dispatch(server, "/live/clip/audio_to_midi", 0, 0, "melody")
    replied = replies(receiver.drain(), "/live/clip/audio_to_midi")
    assert replied[0][:3] == (0, 0, "error")

    dispatch(server, "/live/clip/get/is_convertible_to_midi", 0, 0)
    assert replies(receiver.drain(),
                   "/live/clip/get/is_convertible_to_midi") == [(0, 0, False)]
