"""
The C-1 `Song` remainder — the fifty-eight addresses that close the long tail
of scalar `Song` state — dispatched end to end through the real `SongHandler`.

Covered here: the six read/write scalars appended to `properties_rw`, the five
observable read-only ones appended to `properties_r`, the four members Live
offers no listener for (get only, *no* listen pair registered), the two
hand-written vector reads (`scale_intervals`, `visible_tracks` +
`num_visible_tracks`), the three fire-and-forget methods, the three
struct-returning method queries, and the two device-position methods with
their resolver validation.

As in `test_song_object_reads.py`, the handler is built through conftest's
`bind_song()`: `song.py` binds `self.song` into a partial() for every address
it registers, so assigning `handler.song` after construction would be too
late.

Only the LOM objects are fakes, and that is the boundary of what a green run
proves. Whether Live's `scale_intervals` really is an iterable of ints,
whether a real `BeatTime` carries `ticks`, what `Live.Song.TimeFormat` ints
mean, what `move_device` returns, and whether `overdub` merely mirrors
`session_record` are questions only a running Live can answer — they are the
plan's Live-verification section's job, and `tests/` (which mutates a running
Live on import) is not part of this gate.
"""

from functools import partial

import pytest

from .conftest import bind_song, dispatch, load_song_module


#--------------------------------------------------------------------------------
# The wire contract, as data. Each row is (property, value, osc_type).
#--------------------------------------------------------------------------------
PROPERTIES_RW = [
    ("is_ableton_link_start_stop_sync_enabled", True, bool),
    ("overdub", False, bool),
    ("scale_mode", True, bool),
    ("session_automation_record", False, bool),
    ("start_time", 8.0, float),
    ("tempo_follower_enabled", True, bool),
]

PROPERTIES_R = [
    ("can_capture_midi", True, bool),
    ("count_in_duration", 2, int),
    ("exclusive_arm", False, bool),
    ("is_counting_in", True, bool),
    ("re_enable_automation_enabled", False, bool),
]

PROPERTIES_R_NO_LISTEN = [
    ("exclusive_solo", True, bool),
    ("file_path", "/Users/somebody/Sets/scratch.als", str),
    ("last_event_time", 128.0, float),
    ("select_on_launch", False, bool),
]

OBSERVABLE = [name for name, _, _ in PROPERTIES_RW + PROPERTIES_R] + [
    "scale_intervals",
    "visible_tracks",
]

METHODS = ["play_selection", "scrub_by", "sync_parameter_changes"]


class FakeManager:
    """`osc_server` is the only attribute AbletonOSCHandler reads off it."""

    def __init__(self, osc_server):
        self.osc_server = osc_server


class FakeDevice:
    def __init__(self, name, canonical_parent=None):
        self.name = name
        self.canonical_parent = canonical_parent


class FakeTrack:
    def __init__(self, name):
        self.name = name
        self.devices = []

    def add_device(self, device):
        device.canonical_parent = self
        self.devices.append(device)
        return device


class FakeBeatTime:
    def __init__(self, bars, beats, sub_division, ticks):
        self.bars = bars
        self.beats = beats
        self.sub_division = sub_division
        self.ticks = ticks


class FakeSmpteTime:
    def __init__(self, hours, minutes, seconds, frames):
        self.hours = hours
        self.minutes = minutes
        self.seconds = seconds
        self.frames = frames


class FakeSong:
    """
    Carries every member the C-1 block touches, plus the `tracks` /
    `return_tracks` / `master_track` collections the A-4 resolvers walk for
    `move_device` / `find_device_position`.

    The add/remove listener pairs are synthesised for exactly the observable
    members, the way `test_song_object_reads.py`'s fake hand-writes them for
    `appointed_device`: a member with no pair here is one Live has no
    `add_<name>_listener` for, so a `start_listen` that reached it would raise
    — which is precisely what the get-only registration is there to prevent.
    """

    def __init__(self, tracks, return_tracks, master_track):
        self.tracks = list(tracks)
        self.return_tracks = list(return_tracks)
        self.master_track = master_track

        for name, value, _ in PROPERTIES_RW + PROPERTIES_R + PROPERTIES_R_NO_LISTEN:
            setattr(self, name, value)
        self.scale_intervals = [0, 2, 4, 5, 7, 9, 11]
        self.visible_tracks = list(self.tracks)

        self.listeners = {}
        for name in OBSERVABLE:
            self.listeners[name] = []
            setattr(self, "add_%s_listener" % name, partial(self._add_listener, name))
            setattr(self, "remove_%s_listener" % name, partial(self._remove_listener, name))

        self.calls = []
        self.beat_times = {
            "get_beats_loop_start": FakeBeatTime(3, 2, 1, 40),
            "get_beats_loop_length": FakeBeatTime(1, 0, 0, 0),
        }
        self.smpte_time = FakeSmpteTime(0, 1, 23, 12)
        self.device_position_result = 1

    #--------------------------------------------------------------------------------
    # Listener plumbing
    #--------------------------------------------------------------------------------
    def _add_listener(self, name, callback):
        self.listeners[name].append(callback)

    def _remove_listener(self, name, callback):
        self.listeners[name].remove(callback)

    def notify(self, name):
        for callback in list(self.listeners[name]):
            callback()

    #--------------------------------------------------------------------------------
    # Methods
    #--------------------------------------------------------------------------------
    def play_selection(self):
        self.calls.append(("play_selection", ()))

    def scrub_by(self, delta):
        self.calls.append(("scrub_by", (delta,)))

    def sync_parameter_changes(self):
        self.calls.append(("sync_parameter_changes", ()))

    def get_beats_loop_start(self):
        self.calls.append(("get_beats_loop_start", ()))
        return self.beat_times["get_beats_loop_start"]

    def get_beats_loop_length(self):
        self.calls.append(("get_beats_loop_length", ()))
        return self.beat_times["get_beats_loop_length"]

    def get_current_smpte_song_time(self, time_format):
        self.calls.append(("get_current_smpte_song_time", (time_format,)))
        return self.smpte_time

    def move_device(self, device, target, position):
        self.calls.append(("move_device", (device, target, position)))
        return self.device_position_result

    def find_device_position(self, device, target, position):
        self.calls.append(("find_device_position", (device, target, position)))
        return self.device_position_result


def errors(messages):
    return [params for address, params in messages if address == "/live/error"]


def replies(messages, address):
    return [params for addr, params in messages if addr == address]


def build_song():
    """Four regular tracks (track 1 carrying two devices), one return, one master."""
    tracks = [FakeTrack(name) for name in ("drums", "bass", "keys", "vox")]
    tracks[1].add_device(FakeDevice("filter"))
    tracks[1].add_device(FakeDevice("compressor"))

    returns = FakeTrack("A Reverb")
    returns.add_device(FakeDevice("return reverb"))

    master = FakeTrack("master")
    return FakeSong(tracks, [returns], master)


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

@pytest.mark.parametrize("prop, _value, _type", PROPERTIES_RW)
def test_read_write_scalars_register_all_four_addresses(song_handler, server, prop, _value, _type):
    for verb in ("get", "set", "start_listen", "stop_listen"):
        assert "/live/song/%s/%s" % (verb, prop) in server._callbacks


@pytest.mark.parametrize("prop, _value, _type", PROPERTIES_R)
def test_read_only_scalars_register_get_and_a_listen_pair(song_handler, server, prop, _value, _type):
    for verb in ("get", "start_listen", "stop_listen"):
        assert "/live/song/%s/%s" % (verb, prop) in server._callbacks
    assert "/live/song/set/%s" % prop not in server._callbacks


@pytest.mark.parametrize("prop, _value, _type", PROPERTIES_R_NO_LISTEN)
def test_non_observable_members_register_get_only(song_handler, server, prop, _value, _type):
    """
    The whole point of the get-only loop: Live has no `add_<name>_listener`
    for these four, so no listen address is registered at all. A start_listen
    sent here is an *unknown address* — logged and unanswered — rather than a
    registration that can only ever reply /live/error AttributeError.
    """
    assert "/live/song/get/%s" % prop in server._callbacks
    assert "/live/song/set/%s" % prop not in server._callbacks
    assert "/live/song/start_listen/%s" % prop not in server._callbacks
    assert "/live/song/stop_listen/%s" % prop not in server._callbacks


def test_the_hand_written_addresses_are_registered(song_handler, server):
    for address in ("/live/song/get/scale_intervals",
                    "/live/song/start_listen/scale_intervals",
                    "/live/song/stop_listen/scale_intervals",
                    "/live/song/get/visible_tracks",
                    "/live/song/start_listen/visible_tracks",
                    "/live/song/stop_listen/visible_tracks",
                    "/live/song/get/num_visible_tracks",
                    "/live/song/play_selection",
                    "/live/song/scrub_by",
                    "/live/song/sync_parameter_changes",
                    "/live/song/get_beats_loop_start",
                    "/live/song/get_beats_loop_length",
                    "/live/song/get_current_smpte_song_time",
                    "/live/song/move_device",
                    "/live/song/find_device_position"):
        assert address in server._callbacks


def test_num_visible_tracks_has_no_listen_pair(song_handler, server):
    """Listen on `visible_tracks` instead — the count has no member of its own."""
    assert "/live/song/start_listen/num_visible_tracks" not in server._callbacks
    assert "/live/song/stop_listen/num_visible_tracks" not in server._callbacks


def test_the_neighbouring_members_this_item_must_not_touch_still_answer(song_handler, server,
                                                                       receiver, song):
    """
    `root_note`, `scale_name`, `is_ableton_link_enabled` and
    `clip_trigger_quantization` are upstream's and explicitly out of C-1's
    bucket; appending to the lists they live in must not disturb them.
    """
    for prop in ("root_note", "scale_name", "is_ableton_link_enabled",
                 "clip_trigger_quantization"):
        setattr(song, prop, 1)
        assert "/live/song/set/%s" % prop in server._callbacks
        dispatch(server, "/live/song/get/%s" % prop)
        assert receiver.drain() == [("/live/song/get/%s" % prop, (1,))]


#--------------------------------------------------------------------------------
# get
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("prop, value, osc_type",
                         PROPERTIES_RW + PROPERTIES_R + PROPERTIES_R_NO_LISTEN)
def test_get_replies_the_value_with_its_osc_type(song_handler, song, server, receiver,
                                                 prop, value, osc_type):
    """
    Type as well as value: tuple equality does not tell `1` from `1.0` or
    `True`, and a changed OSC type is a silent decode change downstream.
    """
    address = "/live/song/get/%s" % prop
    setattr(song, prop, value)
    dispatch(server, address)
    messages = receiver.drain()
    assert replies(messages, address) == [(value,)]
    assert type(replies(messages, address)[0][0]) is osc_type


#--------------------------------------------------------------------------------
# set
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("prop, value, _type", PROPERTIES_RW)
def test_set_writes_the_attribute_and_replies_nothing(song_handler, song, server, receiver,
                                                      prop, value, _type):
    setattr(song, prop, None)
    dispatch(server, "/live/song/set/%s" % prop, value)
    assert getattr(song, prop) == value
    assert receiver.drain() == []


@pytest.mark.parametrize("prop, _value, _type", PROPERTIES_R + PROPERTIES_R_NO_LISTEN)
def test_read_only_members_have_no_setter_and_a_send_is_unanswered(song_handler, server,
                                                                   receiver, prop, _value, _type):
    dispatch(server, "/live/song/set/%s" % prop, 1)
    assert receiver.drain() == []


#--------------------------------------------------------------------------------
# start_listen / stop_listen
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("prop, value, _type", [
    pytest.param("scale_mode", True, bool, id="read-write-member"),
    pytest.param("is_counting_in", True, bool, id="read-only-member"),
])
def test_listen_subscribes_pushes_and_unsubscribes(song_handler, song, server, receiver,
                                                   prop, value, _type):
    address = "/live/song/get/%s" % prop
    setattr(song, prop, value)

    dispatch(server, "/live/song/start_listen/%s" % prop)
    assert len(song.listeners[prop]) == 1
    assert receiver.drain() == [(address, (value,))]

    setattr(song, prop, not value)
    song.notify(prop)
    assert receiver.drain() == [(address, (not value,))]

    dispatch(server, "/live/song/stop_listen/%s" % prop)
    assert song.listeners[prop] == []
    song.notify(prop)
    assert receiver.drain() == []


def test_clear_api_unbinds_the_new_listeners(song_handler, song, server, receiver):
    dispatch(server, "/live/song/start_listen/scale_mode")
    dispatch(server, "/live/song/start_listen/visible_tracks")
    receiver.drain()
    song_handler.clear_api()
    assert song.listeners["scale_mode"] == []
    assert song.listeners["visible_tracks"] == []
    assert song_handler.listener_functions == {}


#--------------------------------------------------------------------------------
# scale_intervals
#--------------------------------------------------------------------------------

SCALE_INTERVALS = "/live/song/get/scale_intervals"


def test_scale_intervals_replies_a_flattened_int_tuple(song_handler, song, server, receiver):
    song.scale_intervals = [0, 2, 4, 5, 7, 9, 11]
    dispatch(server, SCALE_INTERVALS)
    messages = receiver.drain()
    assert replies(messages, SCALE_INTERVALS) == [(0, 2, 4, 5, 7, 9, 11)]
    assert all(type(value) is int for value in replies(messages, SCALE_INTERVALS)[0])


def test_scale_intervals_coerces_each_element(song_handler, song, server, receiver):
    """
    Live's vector elements are a Boost numeric type, not necessarily Python
    ints; `int()` per element is what keeps the reply encodable either way.
    """
    song.scale_intervals = [0.0, 2.0, 4.0]
    dispatch(server, SCALE_INTERVALS)
    params = replies(receiver.drain(), SCALE_INTERVALS)[0]
    assert params == (0, 2, 4)
    assert all(type(value) is int for value in params)


def test_scale_intervals_empty_still_replies(song_handler, song, server, receiver):
    song.scale_intervals = []
    dispatch(server, SCALE_INTERVALS)
    assert receiver.drain() == [(SCALE_INTERVALS, ())]


def test_scale_intervals_listen_pushes_the_flattened_tuple(song_handler, song, server, receiver):
    """
    The `getter=` hook is the whole reason this listen pair works: without it
    `_start_listen` would push the raw list, which the OSC builder cannot
    encode.
    """
    dispatch(server, "/live/song/start_listen/scale_intervals")
    assert receiver.drain() == [(SCALE_INTERVALS, (0, 2, 4, 5, 7, 9, 11))]

    song.scale_intervals = [0, 2, 3, 5, 7, 8, 10]
    song.notify("scale_intervals")
    assert receiver.drain() == [(SCALE_INTERVALS, (0, 2, 3, 5, 7, 8, 10))]

    dispatch(server, "/live/song/stop_listen/scale_intervals")
    assert song.listeners["scale_intervals"] == []


#--------------------------------------------------------------------------------
# visible_tracks / num_visible_tracks
#--------------------------------------------------------------------------------

VISIBLE_TRACKS = "/live/song/get/visible_tracks"
NUM_VISIBLE_TRACKS = "/live/song/get/num_visible_tracks"


def test_visible_tracks_replies_indices_into_song_tracks(song_handler, song, server, receiver):
    song.visible_tracks = [song.tracks[0], song.tracks[3]]
    dispatch(server, VISIBLE_TRACKS)
    messages = receiver.drain()
    assert replies(messages, VISIBLE_TRACKS) == [(0, 3)]
    assert all(type(value) is int for value in replies(messages, VISIBLE_TRACKS)[0])


def test_visible_tracks_keeps_track_order(song_handler, song, server, receiver):
    """The answer is a pass over `song.tracks`, so it is in track order even
    when `visible_tracks` is not."""
    song.visible_tracks = [song.tracks[3], song.tracks[1]]
    dispatch(server, VISIBLE_TRACKS)
    assert replies(receiver.drain(), VISIBLE_TRACKS) == [(1, 3)]


def test_visible_tracks_with_everything_hidden_replies_empty(song_handler, song, server, receiver):
    song.visible_tracks = []
    dispatch(server, VISIBLE_TRACKS)
    assert receiver.drain() == [(VISIBLE_TRACKS, ())]


def test_num_visible_tracks_counts_them(song_handler, song, server, receiver):
    song.visible_tracks = [song.tracks[0], song.tracks[3]]
    dispatch(server, NUM_VISIBLE_TRACKS)
    messages = receiver.drain()
    assert replies(messages, NUM_VISIBLE_TRACKS) == [(2,)]
    assert type(replies(messages, NUM_VISIBLE_TRACKS)[0][0]) is int


def test_num_tracks_is_unaffected_by_visibility(song_handler, song, server, receiver):
    song.visible_tracks = [song.tracks[0]]
    dispatch(server, "/live/song/get/num_tracks")
    assert receiver.drain() == [("/live/song/get/num_tracks", (4,))]


def test_visible_tracks_listen_pushes_the_new_index_tuple(song_handler, song, server, receiver):
    """A group track folding is exactly this: the same `song.tracks`, a
    smaller `visible_tracks`."""
    dispatch(server, "/live/song/start_listen/visible_tracks")
    assert receiver.drain() == [(VISIBLE_TRACKS, (0, 1, 2, 3))]

    song.visible_tracks = [song.tracks[0], song.tracks[1]]
    song.notify("visible_tracks")
    assert receiver.drain() == [(VISIBLE_TRACKS, (0, 1))]

    dispatch(server, "/live/song/stop_listen/visible_tracks")
    assert song.listeners["visible_tracks"] == []


#--------------------------------------------------------------------------------
# Fire-and-forget methods
#--------------------------------------------------------------------------------

def test_play_selection_calls_live_and_replies_nothing(song_handler, song, server, receiver):
    dispatch(server, "/live/song/play_selection")
    assert song.calls == [("play_selection", ())]
    assert receiver.drain() == []


def test_sync_parameter_changes_calls_live_and_replies_nothing(song_handler, song,
                                                               server, receiver):
    dispatch(server, "/live/song/sync_parameter_changes")
    assert song.calls == [("sync_parameter_changes", ())]
    assert receiver.drain() == []


def test_scrub_by_passes_the_float_through(song_handler, song, server, receiver):
    dispatch(server, "/live/song/scrub_by", 4.0)
    assert song.calls == [("scrub_by", (4.0,))]
    assert type(song.calls[0][1][0]) is float
    assert receiver.drain() == []


def test_scrub_by_with_no_argument_is_a_structured_error(song_handler, song, server, receiver):
    dispatch(server, "/live/song/scrub_by")
    messages = receiver.drain()
    assert song.calls == []
    assert len(errors(messages)) == 1
    assert errors(messages)[0][0] == "request"
    assert errors(messages)[0][1] == "/live/song/scrub_by"


#--------------------------------------------------------------------------------
# Struct-returning method queries
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("method, expected", [
    ("get_beats_loop_start", (3, 2, 1, 40)),
    ("get_beats_loop_length", (1, 0, 0, 0)),
])
def test_beat_time_queries_decode_the_struct_into_four_ints(song_handler, song, server,
                                                            receiver, method, expected):
    address = "/live/song/%s" % method
    dispatch(server, address)
    messages = receiver.drain()
    assert replies(messages, address) == [expected]
    assert all(type(value) is int for value in replies(messages, address)[0])
    assert song.calls == [(method, ())]


def test_a_missing_beat_time_attribute_is_a_structured_error(song_handler, song,
                                                             server, receiver):
    """
    ⚠️ `ticks` is documented, not measured. If Live's BeatTime spells it
    differently the address fails loudly on /live/error with the attribute
    named — it never answers a wrong number.
    """
    class Truncated:
        bars, beats, sub_division = 1, 0, 0

    song.beat_times["get_beats_loop_start"] = Truncated()
    dispatch(server, "/live/song/get_beats_loop_start")
    messages = errors(receiver.drain())
    assert len(messages) == 1
    assert messages[0][1] == "/live/song/get_beats_loop_start"
    assert "ticks" in messages[0][2]


SMPTE = "/live/song/get_current_smpte_song_time"


def test_smpte_query_echoes_the_format_then_the_four_fields(song_handler, song,
                                                            server, receiver):
    dispatch(server, SMPTE, 1)
    messages = receiver.drain()
    assert replies(messages, SMPTE) == [(1, 0, 1, 23, 12)]
    assert all(type(value) is int for value in replies(messages, SMPTE)[0])
    assert song.calls == [("get_current_smpte_song_time", (1,))]


def test_smpte_query_coerces_a_float_format(song_handler, song, server, receiver):
    dispatch(server, SMPTE, 3.0)
    assert replies(receiver.drain(), SMPTE) == [(3, 0, 1, 23, 12)]
    assert song.calls == [("get_current_smpte_song_time", (3,))]


def test_smpte_query_with_no_argument_is_a_structured_error(song_handler, song,
                                                            server, receiver):
    """No-args is deliberately an error rather than a default format."""
    dispatch(server, SMPTE)
    messages = receiver.drain()
    assert replies(messages, SMPTE) == []
    assert len(errors(messages)) == 1
    assert errors(messages)[0][1] == SMPTE
    assert song.calls == []


#--------------------------------------------------------------------------------
# move_device / find_device_position
#--------------------------------------------------------------------------------

DEVICE_POSITION_ADDRESSES = ["/live/song/move_device", "/live/song/find_device_position"]


@pytest.mark.parametrize("address", DEVICE_POSITION_ADDRESSES)
def test_device_position_resolves_both_objects_and_echoes_the_target(song_handler, song,
                                                                     server, receiver, address):
    dispatch(server, address, "track", 1, 0, "track", 2, 0)
    messages = receiver.drain()
    assert replies(messages, address) == [("track", 2, 1)]

    method, args = song.calls[0]
    assert method == address.rsplit("/", 1)[1]
    assert args[0] is song.tracks[1].devices[0]
    assert args[1] is song.tracks[2]
    assert args[2] == 0


@pytest.mark.parametrize("address", DEVICE_POSITION_ADDRESSES)
def test_device_position_reply_is_str_int_int(song_handler, song, server, receiver, address):
    dispatch(server, address, "track", 1, 1, "return_track", 0, 0)
    params = replies(receiver.drain(), address)[0]
    assert len(params) == 3
    assert type(params[0]) is str
    assert type(params[1]) is int
    assert type(params[2]) is int


@pytest.mark.parametrize("address", DEVICE_POSITION_ADDRESSES)
def test_device_position_reaches_a_master_target(song_handler, song, server, receiver, address):
    dispatch(server, address, "track", 1, 0, "master", 0, 0)
    assert replies(receiver.drain(), address) == [("master", 0, 1)]
    assert song.calls[0][1][1] is song.master_track


@pytest.mark.parametrize("address", DEVICE_POSITION_ADDRESSES)
def test_device_position_coerces_float_indices(song_handler, song, server, receiver, address):
    """TouchOSC-style clients send floats; the coercion happens in the handler."""
    dispatch(server, address, "track", 1.0, 0.0, "track", 2.0, 1.0)
    assert replies(receiver.drain(), address) == [("track", 2, 1)]
    assert song.calls[0][1][2] == 1


@pytest.mark.parametrize("address", DEVICE_POSITION_ADDRESSES)
@pytest.mark.parametrize("args", [
    pytest.param(("none", 0, 0, "track", 0, 0), id="reply-only-none-device-category"),
    pytest.param(("bogus", 0, 0, "track", 0, 0), id="unknown-device-category"),
    pytest.param(("track", -1, 0, "track", 0, 0), id="negative-device-track-index"),
    pytest.param(("track", 1, -1, "track", 0, 0), id="negative-device-index"),
    pytest.param(("track", 99, 0, "track", 0, 0), id="device-track-past-the-end"),
    pytest.param(("track", 1, 99, "track", 0, 0), id="device-index-past-the-end"),
    pytest.param(("track", 1, 0, "none", 0, 0), id="reply-only-none-target-category"),
    pytest.param(("track", 1, 0, "chain", 0, 0), id="chain-target-declined-until-A-1"),
    pytest.param(("track", 1, 0, "track", 99, 0), id="target-track-past-the-end"),
    pytest.param(("track", 1, 0, "track", -1, 0), id="negative-target-track-index"),
    pytest.param(("track", 1, 0, "master", 1, 0), id="master-index-other-than-zero"),
    pytest.param(("track", 1, 0, "track", 2), id="too-few-arguments"),
])
def test_device_position_rejections_arrive_as_structured_errors(song_handler, song, server,
                                                                receiver, address, args):
    """
    Every resolver ValueError — plus the IndexError a short request raises —
    lands on the same envelope, echoing the address, the argument count and
    the arguments, and Live's method is never called. `-1` is an error, never
    "the last one".
    """
    dispatch(server, address, *args)
    messages = receiver.drain()
    assert song.calls == []
    assert replies(messages, address) == []
    assert len(errors(messages)) == 1
    error = errors(messages)[0]
    assert error[0] == "request"
    assert error[1] == address
    assert error[3] == len(args)
    assert tuple(error[4:]) == args
