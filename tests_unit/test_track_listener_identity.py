"""
Listener identity for the Track API, without Ableton Live.

`track_callback.py`'s `include_track_id` branch was the last generic listener
wrapper in this fork that predated the shared rule: a listener's identity is a
tuple of ints, normalised at the callback boundary, truncated to exactly the
arguments that are part of that identity, and used identically for the LOM
lookup, the bookkeeping key and the echo in the push. It cast the index (so,
unlike the scene/clip/clip_slot wrappers, there was never a float defect here)
but then appended the raw params tail after it:

    func(track, *args, tuple([track_index] + params[1:]))

Measured against that code (2026-08-27, `5d75fab`), driving this same
production `TrackHandler`, the tail produced four defects — one per case
below:

* `start_listen/name 0 99` keyed `("name", (0, 99))` and pushed
  `/live/track/get/name (0, 99, 'drums')` — a bogus third field a decoder
  reads as data. The well-formed `stop_listen/name 0` missed the key ("No
  listener function found"), leaking the listener until the script reloaded,
  every later push still carrying the stray `99`.
* `start_listen/volume 0 7` leaked the same way through the mixer pair, but
  **silently**: `_stop_mixer_listen` is deliberately quiet when nothing
  matches, so a missed stop said nothing at all, in the log or on the wire.
* `start_listen/name * 42` put the stray argument into *every* track's key,
  so a well-formed `stop_listen/name *` leaked one listener per track.
* `start_listen/volume 1 junk` subscribed without error and pushed the string
  `'junk'` as a field on `/live/track/get/volume` — the tail is never cast,
  so garbage keys and garbage pushes, and no `/live/error`.

Everything below the fakes is production code: the OSCServer, the dispatcher,
the real `create_track_callback`, and the real `TrackHandler`, constructed
through conftest's synthetic-root loader (track.py imports nothing from Live,
so the Component stub is the only thing standing in). The fakes are only the
LOM objects the callbacks reach through `self.song`.
"""

import pytest

from .conftest import dispatch, load_handler_module, load_track_module


class FakeManager:
    """`osc_server` is the only attribute AbletonOSCHandler reads off it."""

    def __init__(self, osc_server):
        self.osc_server = osc_server


class FakeDeviceParameter:
    """
    Stands in for a mixer DeviceParameter — what `track.mixer_device.volume`,
    `.panning` and each element of `.sends` is in the LOM. A mixer listener
    binds to this object, not to the track.
    """

    def __init__(self, value):
        self.value = value
        self.listeners = []

    def add_value_listener(self, function):
        self.listeners.append(function)

    def remove_value_listener(self, function):
        self.listeners.remove(function)


class FakeMixerDevice:
    def __init__(self, volume, panning, sends):
        self.volume = FakeDeviceParameter(volume)
        self.panning = FakeDeviceParameter(panning)
        self.sends = [FakeDeviceParameter(send) for send in sends]


class FakeTrack:
    def __init__(self, name, volume=0.75, panning=0.0, sends=(0.25,)):
        self.name = name
        self.listeners = []
        self.mixer_device = FakeMixerDevice(volume, panning, sends)

    def add_name_listener(self, function):
        self.listeners.append(function)

    def remove_name_listener(self, function):
        self.listeners.remove(function)


class FakeSong:
    def __init__(self, tracks):
        self.tracks = list(tracks)


@pytest.fixture
def handler(server):
    """
    The production TrackHandler, registered against a production OSCServer.

    `self.song` is read at dispatch time, not at registration time, so
    assigning it after construction is enough — and is the only way to get a
    song in here at all without Live.
    """
    load_handler_module()
    handler = load_track_module().TrackHandler(FakeManager(server))
    handler.song = FakeSong([FakeTrack("drums", volume=0.75),
                             FakeTrack("bass", volume=0.5),
                             FakeTrack("keys", volume=0.25)])
    return handler


def errors(messages):
    return [params for address, params in messages if address == "/live/error"]


def pushes(messages, address):
    return [params for addr, params in messages if addr == address]


#--------------------------------------------------------------------------------
# The plain property pair
#--------------------------------------------------------------------------------

def test_plain_start_with_trailing_extra_keys_on_the_index_alone(handler, server,
                                                                 receiver):
    dispatch(server, "/live/track/start_listen/name", 0, 99)
    messages = receiver.drain()

    assert list(handler.listener_functions.keys()) == [("name", (0,))]
    assert list(handler.listener_objects.keys()) == [("name", (0,))]
    # The immediate push carries the query-reply shape, with no third field.
    assert pushes(messages, "/live/track/get/name") == [(0, "drums")]
    assert type(pushes(messages, "/live/track/get/name")[0][0]) is int
    assert errors(messages) == []


def test_well_formed_stop_ends_a_start_sent_with_extras(handler, server, receiver):
    dispatch(server, "/live/track/start_listen/name", 0, 99)
    receiver.drain()
    track = handler.song.tracks[0]
    assert len(track.listeners) == 1

    dispatch(server, "/live/track/stop_listen/name", 0)

    assert handler.listener_functions == {}
    assert handler.listener_objects == {}
    assert track.listeners == []


def test_stop_with_extras_ends_a_well_formed_start(handler, server, receiver):
    dispatch(server, "/live/track/start_listen/name", 0)
    receiver.drain()
    track = handler.song.tracks[0]

    dispatch(server, "/live/track/stop_listen/name", 0, 99)

    assert handler.listener_functions == {}
    assert track.listeners == []


def test_restart_across_spellings_leaves_one_subscription(handler, server, receiver):
    dispatch(server, "/live/track/start_listen/name", 0)
    dispatch(server, "/live/track/start_listen/name", 0, 99)
    receiver.drain()

    assert list(handler.listener_functions.keys()) == [("name", (0,))]
    assert len(handler.song.tracks[0].listeners) == 1


def test_change_push_carries_the_clean_identity(handler, server, receiver):
    dispatch(server, "/live/track/start_listen/name", 0, 99)
    receiver.drain()

    track = handler.song.tracks[0]
    track.name = "renamed"
    track.listeners[0]()

    assert receiver.drain() == [("/live/track/get/name", (0, "renamed"))]


#--------------------------------------------------------------------------------
# The mixer pair (volume / panning) — same rule, different bookkeeping shape:
# the key is ("value", (track_index, prop)) and the listener binds to a
# DeviceParameter.
#--------------------------------------------------------------------------------

def test_mixer_start_with_trailing_extra_keys_on_the_index_alone(handler, server,
                                                                 receiver):
    dispatch(server, "/live/track/start_listen/volume", 0, 7)
    messages = receiver.drain()

    assert list(handler.listener_functions.keys()) == [("value", (0, "volume"))]
    assert pushes(messages, "/live/track/get/volume") == [(0, 0.75)]
    assert errors(messages) == []


def test_well_formed_stop_ends_a_mixer_start_sent_with_extras(handler, server,
                                                              receiver):
    dispatch(server, "/live/track/start_listen/volume", 0, 7)
    receiver.drain()
    parameter = handler.song.tracks[0].mixer_device.volume
    assert len(parameter.listeners) == 1

    dispatch(server, "/live/track/stop_listen/volume", 0)

    assert handler.listener_functions == {}
    assert handler.listener_objects == {}
    assert parameter.listeners == []


def test_non_numeric_extra_is_dropped_rather_than_echoed(handler, server, receiver):
    dispatch(server, "/live/track/start_listen/volume", 1, "junk")
    messages = receiver.drain()

    assert list(handler.listener_functions.keys()) == [("value", (1, "volume"))]
    assert pushes(messages, "/live/track/get/volume") == [(1, 0.5)]
    assert errors(messages) == []

    dispatch(server, "/live/track/stop_listen/volume", 1)
    assert handler.listener_functions == {}
    assert handler.song.tracks[1].mixer_device.volume.listeners == []


#--------------------------------------------------------------------------------
# The wildcard, where the stray argument used to land in every track's key
#--------------------------------------------------------------------------------

def test_wildcard_start_with_trailing_extra_keys_per_track(handler, server, receiver):
    dispatch(server, "/live/track/start_listen/name", "*", 42)
    messages = receiver.drain()

    assert list(handler.listener_functions.keys()) == [("name", (0,)),
                                                       ("name", (1,)),
                                                       ("name", (2,))]
    assert pushes(messages, "/live/track/get/name") == [(0, "drums"),
                                                        (1, "bass"),
                                                        (2, "keys")]


def test_well_formed_wildcard_stop_ends_a_malformed_wildcard_start(handler, server,
                                                                   receiver):
    dispatch(server, "/live/track/start_listen/name", "*", 42)
    receiver.drain()
    assert all(len(track.listeners) == 1 for track in handler.song.tracks)

    dispatch(server, "/live/track/stop_listen/name", "*")

    assert handler.listener_functions == {}
    assert handler.listener_objects == {}
    assert all(track.listeners == [] for track in handler.song.tracks)


#--------------------------------------------------------------------------------
# Errors and teardown, unchanged by the truncation
#--------------------------------------------------------------------------------

def test_start_listen_with_no_index_is_a_malformed_request(handler, server, receiver):
    dispatch(server, "/live/track/start_listen/name")
    messages = receiver.drain()

    assert len(errors(messages)) == 1
    error = errors(messages)[0]
    assert error[0] == "request"
    assert error[1] == "/live/track/start_listen/name"
    assert handler.listener_functions == {}
    assert handler.listener_objects == {}


def test_clear_api_recovers_after_a_start_with_extras(handler, server, receiver):
    dispatch(server, "/live/track/start_listen/name", 0, 99)
    dispatch(server, "/live/track/start_listen/volume", 1, "junk")
    receiver.drain()

    handler.clear_api()

    assert handler.listener_functions == {}
    assert handler.listener_objects == {}
    assert handler.song.tracks[0].listeners == []
    assert handler.song.tracks[1].mixer_device.volume.listeners == []


#--------------------------------------------------------------------------------
# The untouched non-listener branch: queries still read the params tail
#--------------------------------------------------------------------------------

def test_queries_are_unaffected_by_the_truncation(handler, server, receiver):
    dispatch(server, "/live/track/get/name", 0)
    assert receiver.drain() == [("/live/track/get/name", (0, "drums"))]

    dispatch(server, "/live/track/get/volume", 0)
    assert receiver.drain() == [("/live/track/get/volume", (0, 0.75))]

    # get/send reads its send index out of the tail the include_track_id=False
    # branch still passes through verbatim.
    dispatch(server, "/live/track/get/send", 0, 0)
    assert receiver.drain() == [("/live/track/get/send", (0, 0, 0.25))]
