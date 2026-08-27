"""
The two object-valued reads that go through a wrapper — /live/track/get/group_track
and /live/clip_slot/get/clip — dispatched end to end through the real handlers.

Both are registered by the production `TrackHandler` / `ClipSlotHandler`
constructed on a real `OSCServer` through conftest's synthetic-package loader,
so what is under test is the whole path: the address as registered, the
wrapper's index normalisation and wildcard fan-out, the worker, and the reply
that reaches the socket. Only the LOM objects are fakes.

The other seven addresses in this item (song.py's appointed_device trio and
view.py's four Song.View getters) cannot be reached from here: both modules
`import Live` at module scope. Their resolution logic is
tests_unit/test_track_identity.py's subject, and their registration and push
behaviour are the plan's Live verification checks.
"""

import pytest

from .conftest import dispatch, load_clip_slot_module, load_track_module


class FakeManager:
    """`osc_server` is the only attribute AbletonOSCHandler reads off it."""

    def __init__(self, osc_server):
        self.osc_server = osc_server


class FakeClip:
    def __init__(self, name):
        self.name = name


class FakeClipSlot:
    def __init__(self, clip=None):
        self.clip = clip


class FakeTrack:
    def __init__(self, name, group_track=None, clip_slots=()):
        self.name = name
        self.group_track = group_track
        self.clip_slots = list(clip_slots)
        self.devices = []


class FakeSong:
    def __init__(self, tracks):
        self.tracks = list(tracks)
        self.return_tracks = []
        self.master_track = FakeTrack("master")


def errors(messages):
    return [params for address, params in messages if address == "/live/error"]


def replies(messages, address):
    return [params for addr, params in messages if addr == address]


#--------------------------------------------------------------------------------
# /live/track/get/group_track
#--------------------------------------------------------------------------------

@pytest.fixture
def track_handler(server):
    """
    A production TrackHandler over three tracks, of which track 2 is grouped
    under the group track at index 0.
    """
    handler = load_track_module().TrackHandler(FakeManager(server))
    group = FakeTrack("group")
    song = FakeSong([group, FakeTrack("bass"), FakeTrack("keys")])
    song.tracks[2].group_track = group
    handler.song = song
    return handler


def test_group_track_reports_the_group_index(track_handler, server, receiver):
    dispatch(server, "/live/track/get/group_track", 2)
    assert receiver.drain() == [("/live/track/get/group_track", (2, 0))]


def test_ungrouped_track_reports_minus_one(track_handler, server, receiver):
    dispatch(server, "/live/track/get/group_track", 1)
    assert receiver.drain() == [("/live/track/get/group_track", (1, -1))]


def test_group_track_fans_out_over_the_wildcard(track_handler, server, receiver):
    dispatch(server, "/live/track/get/group_track", "*")
    assert receiver.drain() == [("/live/track/get/group_track", (0, -1)),
                                ("/live/track/get/group_track", (1, -1)),
                                ("/live/track/get/group_track", (2, 0))]


def test_group_track_normalises_a_float_index(track_handler, server, receiver):
    """TouchOSC-style clients send floats; the echoed index is still an int."""
    dispatch(server, "/live/track/get/group_track", 2.0)
    messages = receiver.drain()
    assert messages == [("/live/track/get/group_track", (2, 0))]
    assert type(messages[0][1][0]) is int


def test_group_track_out_of_range_is_an_error(track_handler, server, receiver):
    dispatch(server, "/live/track/get/group_track", 99)
    messages = receiver.drain()
    assert replies(messages, "/live/track/get/group_track") == []
    assert len(errors(messages)) == 1
    error = errors(messages)[0]
    assert error[0] == "request"
    assert error[1] == "/live/track/get/group_track"


def test_group_track_has_no_listen_pair(track_handler, server, receiver):
    """
    Track.group_track is not observable, so neither half may be registered —
    a start_listen that existed would bind a nonexistent
    add_group_track_listener at dispatch time.
    """
    for address in ("/live/track/start_listen/group_track",
                    "/live/track/stop_listen/group_track"):
        assert address not in server._callbacks


#--------------------------------------------------------------------------------
# /live/clip_slot/get/clip
#--------------------------------------------------------------------------------

@pytest.fixture
def clip_slot_handler(server):
    """
    One track whose slot 1 holds a clip and whose slots 0 and 2 are empty.
    """
    handler = load_clip_slot_module().ClipSlotHandler(FakeManager(server))
    track = FakeTrack("drums", clip_slots=[FakeClipSlot(),
                                           FakeClipSlot(FakeClip("loop")),
                                           FakeClipSlot()])
    handler.song = FakeSong([track])
    return handler


def test_clip_present_reports_its_own_index(clip_slot_handler, server, receiver):
    dispatch(server, "/live/clip_slot/get/clip", 0, 1)
    assert receiver.drain() == [("/live/clip_slot/get/clip", (0, 1, 1))]


def test_empty_slot_reports_minus_one(clip_slot_handler, server, receiver):
    dispatch(server, "/live/clip_slot/get/clip", 0, 2)
    assert receiver.drain() == [("/live/clip_slot/get/clip", (0, 2, -1))]


def test_clip_index_is_normalised_in_every_field(clip_slot_handler, server, receiver):
    """
    The third field is the *normalised* index, not the raw argument: a float
    clip_index must not ride through into the reply.
    """
    dispatch(server, "/live/clip_slot/get/clip", 0.0, 1.0)
    messages = receiver.drain()
    assert messages == [("/live/clip_slot/get/clip", (0, 1, 1))]
    assert [type(field) for field in messages[0][1]] == [int, int, int]


def test_clip_out_of_range_is_an_error(clip_slot_handler, server, receiver):
    dispatch(server, "/live/clip_slot/get/clip", 0, 99)
    messages = receiver.drain()
    assert replies(messages, "/live/clip_slot/get/clip") == []
    assert len(errors(messages)) == 1
    assert errors(messages)[0][1] == "/live/clip_slot/get/clip"


def test_clip_has_no_listen_pair(clip_slot_handler, server, receiver):
    for address in ("/live/clip_slot/start_listen/clip",
                    "/live/clip_slot/stop_listen/clip"):
        assert address not in server._callbacks
