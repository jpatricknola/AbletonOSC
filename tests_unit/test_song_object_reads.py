"""
The `Song.appointed_device` trio — /live/song/get/appointed_device,
/live/song/set/appointed_device and its start/stop_listen pair — dispatched
end to end through the real `SongHandler`.

song.py binds `self.song` into a partial() for every address it registers, so
the handler cannot be built by assigning `handler.song` after construction the
way the other behavioural tests do; conftest's `bind_song()` supplies the song
as a class attribute instead, which is the Live-free image of the
`component_guard()` block manager.py constructs every handler inside. With
that in place the production module loads over conftest's empty `Live` stub
(song.py dereferences `Live` only inside get/track_data, at call time) and
what is under test is the whole glue: the addresses as registered, the
partial() wiring, the setter's coercion and validation, the `getter=` listener
push, and what OSCServer._dispatch turns a resolver ValueError into.

Only the LOM objects are fakes. The resolvers themselves are
test_track_identity.py's subject, and whether real Boost.Python wrappers
behave like these fakes — the canonical_parent ascent and cross-class `==` —
is what API.md § "Object-valued reads" still flags with ⚠️; a green run here
proves the glue, not the LOM.
"""

import pytest

from .conftest import bind_song, dispatch, load_song_module

GET = "/live/song/get/appointed_device"
SET = "/live/song/set/appointed_device"
START = "/live/song/start_listen/appointed_device"
STOP = "/live/song/stop_listen/appointed_device"


class FakeManager:
    """`osc_server` is the only attribute AbletonOSCHandler reads off it."""

    def __init__(self, osc_server):
        self.osc_server = osc_server


class FakeDevice:
    def __init__(self, name, canonical_parent=None, chains=()):
        self.name = name
        self.canonical_parent = canonical_parent
        self.chains = list(chains)


class FakeChain:
    def __init__(self, name, canonical_parent=None, devices=()):
        self.name = name
        self.canonical_parent = canonical_parent
        self.devices = list(devices)


class FakeTrack:
    def __init__(self, name):
        self.name = name
        self.devices = []

    def add_device(self, device):
        device.canonical_parent = self
        self.devices.append(device)
        return device


class FakeSong:
    """
    Thin on purpose. `SongHandler.init_api` reads exactly one attribute off
    the song at *registration* time — `self.song` itself, which every
    partial() closes over; `tracks`, `scenes`, `cue_points` and the rest are
    only ever dereferenced inside a callback, so a fake that never dispatches
    those addresses does not need them.

    `remove_current_song_time_listener` is deliberately absent: clear_api()
    calls it inside a bare `try`, so its AttributeError is swallowed exactly
    as a benign removal failure would be in Live, and the appointed-device
    listener still has to come off.
    """

    def __init__(self, tracks, return_tracks, master_track):
        self.tracks = list(tracks)
        self.return_tracks = list(return_tracks)
        self.master_track = master_track
        self.appointed_device = None
        self.appointed_device_listeners = []

    def add_appointed_device_listener(self, callback):
        self.appointed_device_listeners.append(callback)

    def remove_appointed_device_listener(self, callback):
        self.appointed_device_listeners.remove(callback)

    def notify_appointed_device(self):
        for callback in list(self.appointed_device_listeners):
            callback()


def errors(messages):
    return [params for address, params in messages if address == "/live/error"]


def replies(messages, address):
    return [params for addr, params in messages if addr == address]


def build_song():
    """
    Two regular tracks, one return, one master.

    Track 1 ("bass") carries a top-level device at index 0 and a rack at
    index 1 whose single chain holds a nested device — the device that has an
    owning track but no index in `track.devices`.
    """
    drums = FakeTrack("drums")
    bass = FakeTrack("bass")
    bass.add_device(FakeDevice("filter"))
    rack = bass.add_device(FakeDevice("rack"))
    chain = FakeChain("chain 1", canonical_parent=rack)
    rack.chains = [chain]
    nested = FakeDevice("nested reverb", canonical_parent=chain)
    chain.devices = [nested]

    returns = FakeTrack("A Reverb")
    returns.add_device(FakeDevice("return reverb"))

    master = FakeTrack("master")
    master.add_device(FakeDevice("master limiter"))

    song = FakeSong([drums, bass], [returns], master)
    song.nested_device = nested
    return song


@pytest.fixture
def song():
    return build_song()


@pytest.fixture
def song_handler(server, song):
    handler_class = bind_song(load_song_module().SongHandler, song)
    return handler_class(FakeManager(server))


#--------------------------------------------------------------------------------
# Registration
#--------------------------------------------------------------------------------

def test_all_four_appointed_device_addresses_are_registered(song_handler, server):
    """
    Also the pin on the Component stub's `song`: without it the constructor
    raises AttributeError before registering a single address, which is what
    kept this whole file out of reach until now.
    """
    for address in (GET, SET, START, STOP):
        assert address in server._callbacks


#--------------------------------------------------------------------------------
# get
#--------------------------------------------------------------------------------

def test_get_reports_none_when_nothing_is_appointed(song_handler, server, receiver):
    dispatch(server, GET)
    assert receiver.drain() == [(GET, ("none", -1, -1))]


def test_get_reports_a_top_level_device_on_a_regular_track(song_handler, song, server, receiver):
    song.appointed_device = song.tracks[1].devices[0]
    dispatch(server, GET)
    assert receiver.drain() == [(GET, ("track", 1, 0))]


def test_get_reports_a_device_on_a_return_track(song_handler, song, server, receiver):
    song.appointed_device = song.return_tracks[0].devices[0]
    dispatch(server, GET)
    assert receiver.drain() == [(GET, ("return_track", 0, 0))]


def test_get_reports_a_device_on_the_master(song_handler, song, server, receiver):
    song.appointed_device = song.master_track.devices[0]
    dispatch(server, GET)
    assert receiver.drain() == [(GET, ("master", 0, 0))]


def test_get_reports_a_nested_device_with_a_minus_one_device_index(song_handler, song,
                                                                  server, receiver):
    """
    A device inside a rack chain has an owning track but no index in
    `track.devices`, and no address reaches it until A-1 ships a path
    resolver — so the track half is answered and the device half is -1.
    """
    song.appointed_device = song.nested_device
    dispatch(server, GET)
    assert receiver.drain() == [(GET, ("track", 1, -1))]


def test_get_reply_is_a_triple_of_str_int_int(song_handler, song, server, receiver):
    song.appointed_device = song.tracks[1].devices[0]
    dispatch(server, GET)
    params = replies(receiver.drain(), GET)[0]
    assert len(params) == 3
    assert type(params[0]) is str
    assert type(params[1]) is int
    assert type(params[2]) is int


def test_get_of_an_unparented_device_is_a_structured_error(song_handler, song,
                                                           server, receiver):
    """
    A genuine resolution failure — the canonical_parent ascent finds no track
    — raises inside the callback and arrives as /live/error on the request
    path, with nothing on the getter's address.
    """
    song.appointed_device = FakeDevice("orphan", canonical_parent=None)
    dispatch(server, GET)
    messages = receiver.drain()
    assert replies(messages, GET) == []
    assert len(errors(messages)) == 1
    assert errors(messages)[0][0] == "request"
    assert errors(messages)[0][1] == GET


#--------------------------------------------------------------------------------
# set
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("args, expected", [
    (("track", 1, 0), ("tracks", 1, 0)),
    (("return_track", 0, 0), ("return_tracks", 0, 0)),
])
def test_set_appoints_the_named_device(song_handler, song, server, receiver, args, expected):
    collection, track_index, device_index = expected
    dispatch(server, SET, *args)
    assert song.appointed_device is getattr(song, collection)[track_index].devices[device_index]
    assert receiver.drain() == []


def test_set_appoints_a_master_device(song_handler, song, server, receiver):
    dispatch(server, SET, "master", 0, 0)
    assert song.appointed_device is song.master_track.devices[0]
    assert receiver.drain() == []


def test_set_coerces_float_indices(song_handler, song, server, receiver):
    """TouchOSC-style clients send floats; int() coercion happens in the setter."""
    dispatch(server, SET, "track", 1.0, 0.0)
    assert song.appointed_device is song.tracks[1].devices[0]
    assert receiver.drain() == []


@pytest.mark.parametrize("args", [
    pytest.param(("none", 0, 0), id="reply-only-none-category"),
    pytest.param(("bogus", 0, 0), id="unknown-category"),
    pytest.param(("track", -1, 0), id="negative-track-index"),
    pytest.param(("track", 1, -1), id="negative-device-index"),
    pytest.param(("track", 99, 0), id="track-index-past-the-end"),
    pytest.param(("track", 1, 99), id="device-index-past-the-end"),
    pytest.param(("master", 1, 0), id="master-index-other-than-zero"),
    pytest.param(("track", 1), id="too-few-arguments"),
])
def test_set_rejections_arrive_as_structured_errors(song_handler, song, server,
                                                    receiver, args):
    """
    Every rejection resolve_device raises — plus the IndexError a short
    request raises at params[2] — lands on the same /live/error envelope,
    echoing the address, the argument count and the arguments, and leaves
    `appointed_device` untouched. `-1` in particular is an error, never
    "the last device".
    """
    song.appointed_device = song.tracks[1].devices[0]
    dispatch(server, SET, *args)
    messages = receiver.drain()
    assert len(errors(messages)) == 1
    error = errors(messages)[0]
    assert error[0] == "request"
    assert error[1] == SET
    assert error[3] == len(args)
    assert tuple(error[4:]) == args
    assert song.appointed_device is song.tracks[1].devices[0]


#--------------------------------------------------------------------------------
# start_listen / stop_listen
#--------------------------------------------------------------------------------

def test_start_listen_binds_one_callback_and_pushes_immediately(song_handler, song,
                                                                server, receiver):
    song.appointed_device = song.tracks[1].devices[0]
    dispatch(server, START)
    assert len(song.appointed_device_listeners) == 1
    assert receiver.drain() == [(GET, ("track", 1, 0))]


def test_start_listen_records_the_bookkeeping_under_its_own_name(song_handler, song, server):
    dispatch(server, START)
    key = ("appointed_device", ())
    assert key in song_handler.listener_functions
    assert song_handler.listener_objects[key] is song
    #--------------------------------------------------------------------------------
    # `appointed_device` is observable under its own name, so no lom_property
    # alias: the recorded LOM name is the public one.
    #--------------------------------------------------------------------------------
    assert song_handler.listener_lom_properties[key] == "appointed_device"


def test_a_change_pushes_the_new_triple_on_the_getter_address(song_handler, song,
                                                              server, receiver):
    dispatch(server, START)
    receiver.drain()
    song.appointed_device = song.master_track.devices[0]
    song.notify_appointed_device()
    assert receiver.drain() == [(GET, ("master", 0, 0))]


def test_a_repeat_start_listen_replaces_rather_than_stacks(song_handler, song,
                                                           server, receiver):
    dispatch(server, START)
    dispatch(server, START)
    receiver.drain()
    assert len(song.appointed_device_listeners) == 1
    song.notify_appointed_device()
    assert len(receiver.drain()) == 1


def test_stop_listen_unbinds_and_empties_the_bookkeeping(song_handler, song,
                                                         server, receiver):
    dispatch(server, START)
    receiver.drain()
    dispatch(server, STOP)
    assert song.appointed_device_listeners == []
    assert song_handler.listener_functions == {}
    assert song_handler.listener_objects == {}
    assert song_handler.listener_lom_properties == {}
    assert receiver.drain() == []


def test_stop_listen_with_no_listener_sends_nothing(song_handler, server, receiver):
    dispatch(server, STOP)
    assert receiver.drain() == []


def test_clear_api_unbinds_the_appointed_device_listener(song_handler, song,
                                                         server, receiver):
    """
    The /live/api/reload path: Manager.clear_api calls each handler's
    clear_api, and SongHandler's chains super().clear_api() before swallowing
    the beat-listener removal in a bare try — the FakeSong has no
    remove_current_song_time_listener at all, and the appointed-device
    listener must still come off.
    """
    dispatch(server, START)
    receiver.drain()
    song_handler.clear_api()
    assert song.appointed_device_listeners == []
    assert song_handler.listener_functions == {}


def test_a_push_that_cannot_resolve_has_no_error_envelope(song_handler, song,
                                                          server, receiver):
    """
    API.md rule 6, pinned rather than left as prose: /live/error is
    _dispatch's per-message catch, and a listener push does not go through it.
    A resolver failure inside the push callback propagates out of Live's
    notifier — modelled here by the fake's — and nothing reaches the wire.
    """
    song.appointed_device = song.tracks[1].devices[0]
    dispatch(server, START)
    receiver.drain()

    song.appointed_device = FakeDevice("orphan", canonical_parent=None)
    with pytest.raises(ValueError):
        song.notify_appointed_device()
    assert receiver.drain() == []
