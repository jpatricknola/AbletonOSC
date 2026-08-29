"""
The three addresses that name a file to read, dispatched end to end through
the real handlers:

    /live/clip_slot/create_audio_clip
    /live/track/create_audio_clip
    /live/device/replace_sample

Each is registered by the production ClipSlotHandler / TrackHandler /
DeviceHandler constructed on a real OSCServer through conftest's
synthetic-package loader, so what is under test is the whole path: the address
as registered, the wrapper's index normalisation and fan-out, the import rule,
the worker and the reply that reaches the socket. Only the LOM objects are
fakes, and `abletonosc.path_safety.IMPORT_ROOT` is pointed at a tmp directory
holding one real file — the rule itself is exercised directly, and much more
thoroughly, in tests_unit/test_path_safety.py.

**What none of this proves.** Nothing here executes a real
`ClipSlot.create_audio_clip`, so whether Live accepts the path, what it raises
for a non-audio file or a MIDI track's slot, whether the returned Clip is
readable synchronously, and what `position` means in Arrangement time are all
unmeasured — API.md marks each ⚠️ and the plan's Live verification checks are
what settle them. What is proved here is the wire contract and, most of all,
that a refused name reaches no Live method at all.
"""

import os

import pytest

from .conftest import (dispatch, load_clip_slot_module, load_device_module,
                       load_module, load_track_module)


class FakeManager:
    """`osc_server` is the only attribute AbletonOSCHandler reads off it."""

    def __init__(self, osc_server):
        self.osc_server = osc_server


class FakeClip:
    def __init__(self, length=4.0):
        self.length = length


class FakeClipSlot:
    """
    Records every create_audio_clip call, so a test can assert that a refused
    name reached Live not at all — the property the whole rule exists for.
    """

    def __init__(self, has_clip=False, raises=None, length=4.0):
        self.has_clip = has_clip
        self.clip = FakeClip(length) if has_clip else None
        self.calls = []
        self._raises = raises
        self._length = length

    def create_audio_clip(self, path):
        self.calls.append(path)
        if self._raises is not None:
            raise self._raises
        self.clip = FakeClip(self._length)
        self.has_clip = True
        return self.clip


class FakeTrack:
    def __init__(self, name="audio", clip_slots=(), devices=(), raises=None,
                 length=4.0):
        self.name = name
        self.clip_slots = list(clip_slots)
        self.devices = list(devices)
        self.calls = []
        self._raises = raises
        self._length = length

    def create_audio_clip(self, path, position):
        self.calls.append((path, position))
        if self._raises is not None:
            raise self._raises
        return FakeClip(self._length)


class FakeSample:
    def __init__(self, file_path):
        self.file_path = file_path


class FakeSimpler:
    """A device that has `replace_sample`; anything else does not."""

    def __init__(self, file_path="/old/sample.wav", raises=None):
        self.sample = FakeSample(file_path)
        self.calls = []
        self._raises = raises

    def replace_sample(self, path):
        self.calls.append(path)
        if self._raises is not None:
            raise self._raises
        self.sample = FakeSample(path)


class FakeDevice:
    """A non-Simpler: it has no `replace_sample` attribute at all."""

    def __init__(self, name="EQ Eight"):
        self.name = name


class FakeSong:
    def __init__(self, tracks):
        self.tracks = list(tracks)
        self.return_tracks = []
        self.master_track = FakeTrack("master")


def errors(messages):
    return [params for address, params in messages if address == "/live/error"]


def replies(messages, address):
    return [params for addr, params in messages if addr == address]


@pytest.fixture
def import_root(tmp_path, monkeypatch):
    """
    A real import root holding one real file, bound into the shipped rule by
    monkeypatching the module constant — `resolve_import_path` reads it at call
    time, which is exactly what makes this possible without touching internals.
    """
    root = tmp_path / "generated"
    root.mkdir()
    (root / "kick.wav").write_bytes(b"RIFF")
    (tmp_path / "escape.wav").write_bytes(b"RIFF")
    path_safety = load_module("abletonosc.path_safety")
    monkeypatch.setattr(path_safety, "IMPORT_ROOT", str(root))
    return root


#--------------------------------------------------------------------------------
# /live/clip_slot/create_audio_clip
#--------------------------------------------------------------------------------

@pytest.fixture
def clip_slot_handler(server, import_root):
    handler = load_clip_slot_module().ClipSlotHandler(FakeManager(server))
    track = FakeTrack(clip_slots=[FakeClipSlot(), FakeClipSlot(has_clip=True)])
    handler.song = FakeSong([track])
    return handler


def slots(handler):
    return handler.song.tracks[0].clip_slots


def test_clip_slot_import_replies_ok_with_the_length(clip_slot_handler, server,
                                                     receiver, import_root):
    dispatch(server, "/live/clip_slot/create_audio_clip", 0, 0, "kick.wav")
    assert receiver.drain() == [("/live/clip_slot/create_audio_clip",
                                 (0, 0, "ok", 4.0))]


def test_clip_slot_import_hands_live_the_absolute_path(clip_slot_handler, server,
                                                       receiver, import_root):
    """
    The wire carried a bare name; Live is handed the absolute, resolved path
    this fork built. That substitution is the whole point of the rule.
    """
    dispatch(server, "/live/clip_slot/create_audio_clip", 0, 0, "kick.wav")
    receiver.drain()
    assert slots(clip_slot_handler)[0].calls == \
        [os.path.realpath(str(import_root / "kick.wav"))]


@pytest.mark.parametrize("name", ["../escape.wav", "/etc/passwd", "nope.wav", ""])
def test_clip_slot_refused_name_replies_error_and_calls_nothing(
        clip_slot_handler, server, receiver, import_root, name):
    dispatch(server, "/live/clip_slot/create_audio_clip", 0, 0, name)
    messages = receiver.drain()
    reply, = replies(messages, "/live/clip_slot/create_audio_clip")
    assert reply[:3] == (0, 0, "error")
    assert errors(messages) == []
    #--------------------------------------------------------------------------------
    # The assertion the rule exists for: nothing was opened, because Live was
    # never asked.
    #--------------------------------------------------------------------------------
    assert slots(clip_slot_handler)[0].calls == []


def test_clip_slot_missing_name_replies_error(clip_slot_handler, server, receiver,
                                              import_root):
    """
    A malformed request is an "error" reply, not an IndexError escaping as a
    structured error the caller could not tell from a bad index.
    """
    dispatch(server, "/live/clip_slot/create_audio_clip", 0, 0)
    messages = receiver.drain()
    reply, = replies(messages, "/live/clip_slot/create_audio_clip")
    assert reply[:3] == (0, 0, "error")
    assert errors(messages) == []


def test_clip_slot_occupied_slot_replies_error_and_calls_nothing(
        clip_slot_handler, server, receiver, import_root):
    dispatch(server, "/live/clip_slot/create_audio_clip", 0, 1, "kick.wav")
    messages = receiver.drain()
    reply, = replies(messages, "/live/clip_slot/create_audio_clip")
    assert reply[:3] == (0, 1, "error")
    assert slots(clip_slot_handler)[1].calls == []


def test_clip_slot_unreadable_has_clip_replies_error_and_calls_nothing(
        server, receiver, import_root):
    """
    The occupancy check reads a LOM member, and a LOM member can raise rather
    than return falsy. That must stay on this address's "error" channel: an
    escaping exception would answer /live/error instead, the one shape the
    always-reply guarantee does not allow. Nothing has been created yet, so
    refusing is the accurate answer either way.
    """

    class RaisingClipSlot(FakeClipSlot):
        @property
        def has_clip(self):
            raise RuntimeError("slot detached")

        @has_clip.setter
        def has_clip(self, value):
            pass

    slot = RaisingClipSlot()
    handler = load_clip_slot_module().ClipSlotHandler(FakeManager(server))
    handler.song = FakeSong([FakeTrack(clip_slots=[slot])])

    dispatch(server, "/live/clip_slot/create_audio_clip", 0, 0, "kick.wav")
    messages = receiver.drain()
    reply, = replies(messages, "/live/clip_slot/create_audio_clip")
    assert reply[:3] == (0, 0, "error")
    assert "slot detached" in reply[3]
    assert errors(messages) == []
    assert slot.calls == []


def test_clip_slot_live_side_exception_is_caught_and_replied(
        server, receiver, import_root):
    handler = load_clip_slot_module().ClipSlotHandler(FakeManager(server))
    track = FakeTrack(clip_slots=[FakeClipSlot(raises=RuntimeError("bad file"))])
    handler.song = FakeSong([track])

    dispatch(server, "/live/clip_slot/create_audio_clip", 0, 0, "kick.wav")
    messages = receiver.drain()
    reply, = replies(messages, "/live/clip_slot/create_audio_clip")
    assert reply[:3] == (0, 0, "error")
    assert "bad file" in reply[3]
    assert errors(messages) == []


def test_clip_slot_unreadable_length_still_replies_ok_with_minus_one(
        server, receiver, import_root):
    """
    The fallback: a Clip whose length cannot be read costs one field, not the
    arity and not the discriminator's index.
    """
    class LengthlessClipSlot(FakeClipSlot):
        def create_audio_clip(self, path):
            self.calls.append(path)
            self.has_clip = True
            self.clip = object()
            return self.clip

    handler = load_clip_slot_module().ClipSlotHandler(FakeManager(server))
    handler.song = FakeSong([FakeTrack(clip_slots=[LengthlessClipSlot()])])

    dispatch(server, "/live/clip_slot/create_audio_clip", 0, 0, "kick.wav")
    assert receiver.drain() == [("/live/clip_slot/create_audio_clip",
                                 (0, 0, "ok", -1.0))]


def test_clip_slot_bad_index_is_a_structured_error_not_a_reply(
        clip_slot_handler, server, receiver, import_root):
    """
    The split contract: an index error is the wrapper's and arrives as
    /live/error; everything the worker decides arrives as an "error" reply on
    the request address. A client's error handling depends on the difference.
    """
    dispatch(server, "/live/clip_slot/create_audio_clip", 99, 0, "kick.wav")
    messages = receiver.drain()
    assert replies(messages, "/live/clip_slot/create_audio_clip") == []
    error, = errors(messages)
    assert error[0] == "request"
    assert error[1] == "/live/clip_slot/create_audio_clip"


def test_clip_slot_import_has_no_listen_pair(clip_slot_handler, server):
    """A method, not a property: neither half of a listen pair may exist."""
    for address in ("/live/clip_slot/start_listen/create_audio_clip",
                    "/live/clip_slot/stop_listen/create_audio_clip"):
        assert address not in server._callbacks


#--------------------------------------------------------------------------------
# /live/track/create_audio_clip
#--------------------------------------------------------------------------------

@pytest.fixture
def track_handler(server, import_root):
    handler = load_track_module().TrackHandler(FakeManager(server))
    handler.song = FakeSong([FakeTrack("one"), FakeTrack("two", length=8.0)])
    return handler


def test_track_import_replies_ok_with_position_and_length(track_handler, server,
                                                          receiver, import_root):
    dispatch(server, "/live/track/create_audio_clip", 1, "kick.wav", 8.0)
    assert receiver.drain() == [("/live/track/create_audio_clip",
                                 (1, "ok", 8.0, 8.0))]
    assert track_handler.song.tracks[1].calls == \
        [(os.path.realpath(str(import_root / "kick.wav")), 8.0)]


def test_track_import_fans_out_over_the_wildcard(track_handler, server, receiver,
                                                 import_root):
    dispatch(server, "/live/track/create_audio_clip", "*", "kick.wav", 0.0)
    assert receiver.drain() == [("/live/track/create_audio_clip", (0, "ok", 0.0, 4.0)),
                                ("/live/track/create_audio_clip", (1, "ok", 0.0, 8.0))]
    assert [len(track.calls) for track in track_handler.song.tracks] == [1, 1]


def test_track_refusal_under_the_wildcard_replies_per_track_and_calls_nothing(
        track_handler, server, receiver, import_root):
    """
    A refused name is not a raise, so `*` produces one "error" reply per track
    and creates nothing — the well-behaved case, and the reason the fan-out's
    all-or-nothing abort is not reachable through this address.
    """
    dispatch(server, "/live/track/create_audio_clip", "*", "../escape.wav", 0.0)
    messages = receiver.drain()
    assert [params[:2] for params in
            replies(messages, "/live/track/create_audio_clip")] == \
        [(0, "error"), (1, "error")]
    assert errors(messages) == []
    assert [track.calls for track in track_handler.song.tracks] == [[], []]


def test_track_missing_position_is_an_error_reply_not_an_index_error(
        track_handler, server, receiver, import_root):
    """
    An IndexError here would be a silent wildcard skip on a /live/track/*
    pattern request, so a malformed request could masquerade as "this endpoint
    does not apply".
    """
    dispatch(server, "/live/track/create_audio_clip", 0, "kick.wav")
    messages = receiver.drain()
    reply, = replies(messages, "/live/track/create_audio_clip")
    assert reply[:2] == (0, "error")
    assert errors(messages) == []
    assert track_handler.song.tracks[0].calls == []


def test_track_non_numeric_position_is_an_error_reply(track_handler, server,
                                                      receiver, import_root):
    dispatch(server, "/live/track/create_audio_clip", 0, "kick.wav", "soon")
    messages = receiver.drain()
    reply, = replies(messages, "/live/track/create_audio_clip")
    assert reply[:2] == (0, "error")
    assert track_handler.song.tracks[0].calls == []


def test_track_live_side_exception_is_caught_and_replied(server, receiver,
                                                         import_root):
    handler = load_track_module().TrackHandler(FakeManager(server))
    handler.song = FakeSong([FakeTrack(raises=RuntimeError("no arrangement"))])

    dispatch(server, "/live/track/create_audio_clip", 0, "kick.wav", 0.0)
    messages = receiver.drain()
    reply, = replies(messages, "/live/track/create_audio_clip")
    assert reply[:2] == (0, "error")
    assert "no arrangement" in reply[2]
    assert errors(messages) == []


def test_track_bad_index_is_a_structured_error_not_a_reply(track_handler, server,
                                                           receiver, import_root):
    dispatch(server, "/live/track/create_audio_clip", 99, "kick.wav", 0.0)
    messages = receiver.drain()
    assert replies(messages, "/live/track/create_audio_clip") == []
    error, = errors(messages)
    assert error[0] == "request"
    assert error[1] == "/live/track/create_audio_clip"


#--------------------------------------------------------------------------------
# /live/device/replace_sample
#--------------------------------------------------------------------------------

@pytest.fixture
def device_handler(server, import_root):
    handler = load_device_module().DeviceHandler(FakeManager(server))
    handler.song = FakeSong([FakeTrack(devices=[FakeSimpler(), FakeDevice()])])
    return handler


def devices(handler):
    return handler.song.tracks[0].devices


def test_replace_sample_replies_ok_with_the_new_file_path(device_handler, server,
                                                          receiver, import_root):
    resolved = os.path.realpath(str(import_root / "kick.wav"))
    dispatch(server, "/live/device/replace_sample", 0, 0, "kick.wav")
    assert receiver.drain() == [("/live/device/replace_sample",
                                 (0, 0, "ok", resolved))]
    assert devices(device_handler)[0].calls == [resolved]


def test_replace_sample_refused_name_replies_error_and_calls_nothing(
        device_handler, server, receiver, import_root):
    dispatch(server, "/live/device/replace_sample", 0, 0, "../escape.wav")
    messages = receiver.drain()
    reply, = replies(messages, "/live/device/replace_sample")
    assert reply[:3] == (0, 0, "error")
    assert errors(messages) == []
    assert devices(device_handler)[0].calls == []


def test_replace_sample_live_side_exception_is_caught_and_replied(
        server, receiver, import_root):
    handler = load_device_module().DeviceHandler(FakeManager(server))
    handler.song = FakeSong([FakeTrack(
        devices=[FakeSimpler(raises=RuntimeError("unsupported format"))])])

    dispatch(server, "/live/device/replace_sample", 0, 0, "kick.wav")
    messages = receiver.drain()
    reply, = replies(messages, "/live/device/replace_sample")
    assert reply[:3] == (0, 0, "error")
    assert "unsupported format" in reply[3]
    assert errors(messages) == []


def test_replace_sample_unreadable_sample_still_replies_ok_with_empty_path(
        server, receiver, import_root):
    class SampleLessSimpler(FakeSimpler):
        def replace_sample(self, path):
            self.calls.append(path)
            del self.sample

    handler = load_device_module().DeviceHandler(FakeManager(server))
    handler.song = FakeSong([FakeTrack(devices=[SampleLessSimpler()])])

    dispatch(server, "/live/device/replace_sample", 0, 0, "kick.wav")
    assert receiver.drain() == [("/live/device/replace_sample", (0, 0, "ok", ""))]


def test_replace_sample_on_a_non_simpler_is_a_structured_error(
        device_handler, server, receiver, import_root):
    dispatch(server, "/live/device/replace_sample", 0, 1, "kick.wav")
    messages = receiver.drain()
    assert replies(messages, "/live/device/replace_sample") == []
    error, = errors(messages)
    assert error[0] == "request"
    assert error[1] == "/live/device/replace_sample"


def test_replace_sample_on_a_non_simpler_is_a_silent_skip_under_a_pattern(
        device_handler, server, receiver, import_root):
    """
    `/live/device/*` matches exactly one registered address — `*` spans a
    single segment, and every other device address has two segments after
    /live/device — so this asserts precisely this endpoint's behaviour: the
    AttributeError from binding `replace_sample` is a wildcard skip, and
    nothing at all goes out.

    This is why the method is bound before the path is resolved. Resolving
    first would answer an "error" triple here instead of skipping.
    """
    matched = [address for address in server._callbacks
               if address.startswith("/live/device/")
               and "/" not in address[len("/live/device/"):]]
    assert matched == ["/live/device/replace_sample"]

    dispatch(server, "/live/device/*", 0, 1, "kick.wav")
    assert receiver.drain() == []


def test_replace_sample_bad_index_is_a_structured_error(device_handler, server,
                                                        receiver, import_root):
    dispatch(server, "/live/device/replace_sample", 0, 99, "kick.wav")
    messages = receiver.drain()
    assert replies(messages, "/live/device/replace_sample") == []
    error, = errors(messages)
    assert error[1] == "/live/device/replace_sample"


#--------------------------------------------------------------------------------
# The shared invariant
#--------------------------------------------------------------------------------

def test_the_discriminator_sits_at_a_fixed_index_on_both_paths(
        server, receiver, import_root):
    """
    A client switches on the "ok"/"error" field positionally: index 2 for the
    clip-slot and device addresses, index 1 for the track address. Arity is
    *not* the invariant — the track address replies four fields on success and
    three on a refusal, deliberately, and must not be padded.
    """
    def fresh_song():
        return FakeSong([FakeTrack(clip_slots=[FakeClipSlot()],
                                   devices=[FakeSimpler()])])

    clip_slot_handler = load_clip_slot_module().ClipSlotHandler(FakeManager(server))
    track_handler = load_track_module().TrackHandler(FakeManager(server))
    device_handler = load_device_module().DeviceHandler(FakeManager(server))

    cases = [
        ("/live/clip_slot/create_audio_clip", (0, 0), 2),
        ("/live/track/create_audio_clip", (0,), 1),
        ("/live/device/replace_sample", (0, 0), 2),
    ]

    for address, prefix, index in cases:
        for name, expected in (("kick.wav", "ok"), ("../escape.wav", "error")):
            #--------------------------------------------------------------------------------
            # A fresh song per dispatch: a success leaves state behind (a filled
            # slot, a replaced sample) that would refuse the next one.
            #--------------------------------------------------------------------------------
            song = fresh_song()
            clip_slot_handler.song = song
            track_handler.song = song
            device_handler.song = song

            args = prefix + (name,)
            if address == "/live/track/create_audio_clip":
                args = args + (0.0,)
            dispatch(server, address, *args)
            reply, = replies(receiver.drain(), address)
            assert reply[index] == expected, (address, name, reply)
