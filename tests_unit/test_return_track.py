"""
The Return Track & Master API, without Ableton Live.

`return_track.py` had no conftest loader and no unit test at all until this
file: the whole `/live/return_track/*` and `/live/master/*` surface was
covered only by the live suite, which needs Live running and is not part of
the gate. It is loadable for the same reason device.py is — it imports
nothing from Live, only `functools`, `typing` and `.handler` — so
conftest.load_return_track_module() gets the production ReturnTrackHandler
on top of the Component stub, registering its entire address table on the
production OSCServer. Everything under test here is shipped code; only the
LOM objects are fakes.

Two things this file pins that nothing else can:

1. **The envelope.** Every indexed getter on these prefixes replies on its
   own address with `[index, "ok", value]` or `[index, "error", message]`,
   because the extension is optional and silence has to keep meaning "not
   installed". The A-3 parity surface (colour, `has_*`, meters, output
   routing, sends, `insert_device`) extends that convention rather than
   forking it, and every *new* master getter carries the envelope too — the
   Main track refuses some members its class declares, and an envelope is
   the only reply shape that can say so.

2. **Listener key shapes.** Four kinds of listener now coexist on one
   handler: a return's plain Track property `(prop, (index,))`, a return's
   mixer DeviceParameter `("value", (index, "volume"))`, the master's plain
   Track property `(prop, ("master",))`, and the master's mixer parameter
   `("value", ("master", "cue_volume"))`. They must not evict one another,
   and `_clear_listeners` must unbind all of them.
"""

from functools import partial

import pytest

from .conftest import (dispatch, load_handler_module, load_return_track_module,
                       load_track_module)


class FakeManager:
    """`osc_server` is the only attribute AbletonOSCHandler reads off it."""

    def __init__(self, osc_server):
        self.osc_server = osc_server


class FakeParameter:
    """A DeviceParameter stand-in: a value and the add_/remove_ pair."""

    def __init__(self, name, value):
        self.name = name
        self.value = value
        self.listeners = []

    def str_for_value(self, value):
        return "%.1f dB" % value

    def add_value_listener(self, function):
        self.listeners.append(function)

    def remove_value_listener(self, function):
        self.listeners.remove(function)


class FakeRouting:
    """A routing type/channel: the LOM object has `display_name`."""

    def __init__(self, display_name):
        self.display_name = display_name


class FakeDevice:
    def __init__(self, name):
        self.name = name
        self.type = 2
        self.class_name = "Reverb"
        self.parameters = []


class FakeMixerDevice:
    def __init__(self, sends=()):
        self.volume = FakeParameter("Volume", 0.85)
        self.panning = FakeParameter("Pan", 0.0)
        self.cue_volume = FakeParameter("Preview Volume", 0.7)
        self.sends = list(sends)


class FakeTrack:
    """
    A Live.Track.Track stand-in with the members the A-3 surface reads.

    `add_<prop>_listener` / `remove_<prop>_listener` are synthesised for the
    observable properties rather than written out eight times; anything else
    raises AttributeError, exactly as the LOM would.
    """

    LISTENABLE = ("name", "mute", "solo", "color", "color_index",
                  "output_meter_level", "output_meter_left", "output_meter_right")

    def __init__(self, name, color=0x2196F3, sends=(), devices=()):
        self.name = name
        self.mute = False
        self.solo = False
        self.color = color
        self.color_index = 3
        self.has_audio_input = True
        self.has_audio_output = True
        self.has_midi_input = False
        self.has_midi_output = False
        self.output_meter_level = 0.25
        self.output_meter_left = 0.2
        self.output_meter_right = 0.3
        self.mixer_device = FakeMixerDevice(sends=sends)
        self.devices = list(devices)
        self.available_output_routing_types = [FakeRouting("Main"),
                                               FakeRouting("Ext. Out")]
        self.available_output_routing_channels = [FakeRouting("1/2"),
                                                  FakeRouting("3/4")]
        self.output_routing_type = self.available_output_routing_types[0]
        self.output_routing_channel = self.available_output_routing_channels[0]
        self.listeners = {}
        self.inserted = []
        self.insert_result = None
        self.insert_raises = None

    def _listener_op(self, op, prop, function):
        bucket = self.listeners.setdefault(prop, [])
        if op == "add":
            bucket.append(function)
        else:
            bucket.remove(function)

    def __getattr__(self, name):
        for prefix, op in (("add_", "add"), ("remove_", "remove")):
            if name.startswith(prefix) and name.endswith("_listener"):
                prop = name[len(prefix):-len("_listener")]
                if prop in self.LISTENABLE:
                    return partial(self._listener_op, op, prop)
        raise AttributeError(name)

    def all_listeners(self):
        return [function for bucket in self.listeners.values() for function in bucket]

    def insert_device(self, name, position=-1):
        if self.insert_raises is not None:
            raise self.insert_raises
        self.inserted.append((name, position))
        device = self.insert_result if self.insert_result is not None else FakeDevice(name)
        insert_at = len(self.devices) if position < 0 else position
        self.devices.insert(insert_at, device)
        return device

    def delete_device(self, index):
        del self.devices[index]


class RefusingTrack(FakeTrack):
    """
    A Main track that declares a member and refuses it.

    Reading `master_track.mute` raises RuntimeError("Main track has no 'mute'
    property!") rather than returning something falsy (measured 2026-07-31,
    Live 12.4.3). Whether `color` behaves the same way is unmeasured — this
    fake stands in for the "it does" branch, and pins that a read is an error
    envelope naming the refusal rather than silence or a bare None, and that a
    *write* escapes to /live/error rather than being swallowed.

    `refusing` is switched on after construction, so the fake can still be
    built through FakeTrack's own initialisation.
    """

    refusing = False

    @property
    def color(self):
        if self.refusing:
            raise RuntimeError("Main track has no 'color' property!")
        return self._color

    @color.setter
    def color(self, value):
        if self.refusing:
            raise RuntimeError("Main track has no 'color' property!")
        self._color = value


class FakeSong:
    def __init__(self, return_tracks, master_track, tracks=()):
        self.return_tracks = list(return_tracks)
        self.master_track = master_track
        self.tracks = list(tracks)
        self.view = FakeView()


class FakeView:
    def __init__(self):
        self.selected_track = None
        self.selected_device = None

    def select_device(self, device):
        self.selected_device = device


def make_song(master=None):
    returns = [FakeTrack("A-Reverb", color=0x111111,
                         sends=[FakeParameter("Send A", 0.0),
                                FakeParameter("Send B", 0.25)],
                         devices=[FakeDevice("Reverb")]),
               FakeTrack("B-Delay", color=0x222222,
                         sends=[FakeParameter("Send A", 0.5),
                                FakeParameter("Send B", 0.0)])]
    return FakeSong(returns, master if master is not None else FakeTrack("Main"))


@pytest.fixture
def handler(server):
    """
    The production ReturnTrackHandler on the production OSCServer, with two
    return tracks and a master underneath.

    `self.song` is read only from callbacks, so assigning it after
    construction is enough — no bind_song() needed.
    """
    load_handler_module()
    module = load_return_track_module()
    h = module.ReturnTrackHandler(FakeManager(server))
    h.song = make_song()
    return h


def reply(receiver, server, address, *args):
    """Dispatch one request and return the single reply's params."""
    dispatch(server, address, *args)
    messages = receiver.drain()
    assert len(messages) == 1, "expected one reply, got %s" % (messages,)
    assert messages[0][0] == address
    return messages[0][1]


def silent(receiver, server, address, *args):
    dispatch(server, address, *args)
    assert receiver.drain() == []


#--------------------------------------------------------------------------------
# The shipped contract, pinned before it grows (Part 1).
#--------------------------------------------------------------------------------
def test_get_count(handler, server, receiver):
    assert reply(receiver, server, "/live/return_track/get/count") == (2,)


def test_get_name_ok_envelope(handler, server, receiver):
    assert reply(receiver, server, "/live/return_track/get/name", 1) == (1, "ok", "B-Delay")


def test_get_name_out_of_range_echoes_the_index_verbatim(handler, server, receiver):
    index, status, message = reply(receiver, server, "/live/return_track/get/name", 7)
    assert (index, status) == (7, "error")
    assert "7" in message and "2 return track" in message


def test_non_numeric_index_echoes_minus_one(handler, server, receiver):
    index, status, _message = reply(receiver, server, "/live/return_track/get/name", "nope")
    assert (index, status) == (-1, "error")


def test_setter_is_silent(handler, server, receiver):
    silent(receiver, server, "/live/return_track/set/name", 0, "Verb")
    assert handler.song.return_tracks[0].name == "Verb"


def test_mixer_listener_keys_coexist(handler, server, receiver):
    dispatch(server, "/live/return_track/start_listen/volume", 0)
    dispatch(server, "/live/return_track/start_listen/panning", 0)
    receiver.drain()

    assert ("value", (0, "volume")) in handler.listener_functions
    assert ("value", (0, "panning")) in handler.listener_functions
    track = handler.song.return_tracks[0]
    assert len(track.mixer_device.volume.listeners) == 1
    assert len(track.mixer_device.panning.listeners) == 1


def test_stop_listen_of_a_never_started_listener_is_silent(handler, server, receiver):
    silent(receiver, server, "/live/return_track/stop_listen/volume", 1)
    silent(receiver, server, "/live/master/stop_listen/color")


def test_clear_listeners_leaves_the_fakes_listener_free(handler, server, receiver):
    for address, args in (("/live/return_track/start_listen/name", (0,)),
                          ("/live/return_track/start_listen/volume", (0,)),
                          ("/live/return_track/start_listen/color", (0,)),
                          ("/live/master/start_listen/color", ()),
                          ("/live/master/start_listen/cue_volume", ())):
        dispatch(server, address, *args)
    receiver.drain()

    handler.clear_api()

    assert handler.listener_functions == {}
    assert handler.listener_objects == {}
    track = handler.song.return_tracks[0]
    master = handler.song.master_track
    assert track.all_listeners() == []
    assert track.mixer_device.volume.listeners == []
    assert master.all_listeners() == []
    assert master.mixer_device.cue_volume.listeners == []


#--------------------------------------------------------------------------------
# Registration (Parts 2-5): every address the item promises exists, and the
# ones it deliberately withholds do not.
#--------------------------------------------------------------------------------
SCALAR_READ_ONLY = ("has_audio_input", "has_audio_output",
                    "has_midi_input", "has_midi_output")
SCALAR_LISTENABLE = ("color", "color_index", "output_meter_level",
                     "output_meter_left", "output_meter_right")


def registered(server):
    #--------------------------------------------------------------------------------
    # OSCServer keeps its callbacks in a private dict; the address table is
    # what this test is about, so read it directly rather than dispatching
    # a hundred requests to infer it.
    #--------------------------------------------------------------------------------
    return set(server._callbacks.keys())


def test_every_new_address_is_registered(handler, server):
    addresses = registered(server)
    expected = set()
    for prop in ("color", "color_index") + SCALAR_READ_ONLY + (
            "output_meter_level", "output_meter_left", "output_meter_right"):
        expected.add("/live/return_track/get/%s" % prop)
        expected.add("/live/master/get/%s" % prop)
    for prop in ("color", "color_index"):
        expected.add("/live/return_track/set/%s" % prop)
        expected.add("/live/master/set/%s" % prop)
    for prop in SCALAR_LISTENABLE:
        for verb in ("start_listen", "stop_listen"):
            expected.add("/live/return_track/%s/%s" % (verb, prop))
            expected.add("/live/master/%s/%s" % (verb, prop))
    for prop in ("output_routing_type", "output_routing_channel"):
        expected.add("/live/return_track/get/%s" % prop)
        expected.add("/live/return_track/set/%s" % prop)
        expected.add("/live/master/get/%s" % prop)
        expected.add("/live/master/set/%s" % prop)
    for prop in ("available_output_routing_types", "available_output_routing_channels"):
        expected.add("/live/return_track/get/%s" % prop)
        expected.add("/live/master/get/%s" % prop)
    expected |= {"/live/return_track/get/send", "/live/return_track/set/send",
                 "/live/return_track/insert_device", "/live/master/insert_device"}

    assert expected <= addresses
    #--------------------------------------------------------------------------------
    # 30 new return addresses + 28 new master addresses. The item's 59th is
    # /live/track/insert_device, registered by track.py and asserted below.
    #--------------------------------------------------------------------------------
    assert len(expected) == 58


def test_withheld_addresses_are_not_registered(handler, server):
    addresses = registered(server)
    for prop in SCALAR_READ_ONLY:
        #--------------------------------------------------------------------------------
        # has_* are constants on a return and on the master (always audio in
        # and out, never MIDI), so a listen pair would subscribe to a value
        # that cannot change, and a setter would write a read-only member.
        #--------------------------------------------------------------------------------
        for verb in ("set", "start_listen", "stop_listen"):
            assert "/live/return_track/%s/%s" % (verb, prop) not in addresses
            assert "/live/master/%s/%s" % (verb, prop) not in addresses

    # No input routing: returns and the master have no input section in Live.
    for prop in ("input_routing_type", "input_routing_channel",
                 "available_input_routing_types", "available_input_routing_channels"):
        assert "/live/return_track/get/%s" % prop not in addresses
        assert "/live/master/get/%s" % prop not in addresses

    # No master sends, and no send listen pairs (parity: tracks have none).
    assert "/live/master/get/send" not in addresses
    assert "/live/return_track/start_listen/send" not in addresses


#--------------------------------------------------------------------------------
# Part 2 — the scalar surface.
#--------------------------------------------------------------------------------
@pytest.mark.parametrize("prop, expected", [("color", 0x111111),
                                            ("color_index", 3),
                                            ("output_meter_level", 0.25),
                                            ("output_meter_left", 0.2),
                                            ("output_meter_right", 0.3)])
def test_return_scalar_getter_ok_envelope(handler, server, receiver, prop, expected):
    index, status, value = reply(receiver, server, "/live/return_track/get/%s" % prop, 0)
    assert (index, status) == (0, "ok")
    assert value == pytest.approx(expected)


@pytest.mark.parametrize("prop, expected", [("has_audio_input", 1),
                                            ("has_audio_output", 1),
                                            ("has_midi_input", 0),
                                            ("has_midi_output", 0)])
def test_return_has_getters_report_zero_or_one(handler, server, receiver, prop, expected):
    assert reply(receiver, server,
                 "/live/return_track/get/%s" % prop, 0) == (0, "ok", expected)


@pytest.mark.parametrize("prop", ["color", "color_index", "has_audio_input",
                                  "output_meter_level"])
def test_return_scalar_getter_error_envelope_on_a_bad_index(handler, server, receiver, prop):
    index, status, _message = reply(receiver, server,
                                    "/live/return_track/get/%s" % prop, 9)
    assert (index, status) == (9, "error")


def test_return_scalar_setters_write_and_stay_silent(handler, server, receiver):
    silent(receiver, server, "/live/return_track/set/color", 1, 0x00FF00)
    silent(receiver, server, "/live/return_track/set/color_index", 1, 7)
    assert handler.song.return_tracks[1].color == 0x00FF00
    assert handler.song.return_tracks[1].color_index == 7


def test_return_scalar_setter_ignores_a_bad_index_and_a_missing_value(handler, server, receiver):
    silent(receiver, server, "/live/return_track/set/color", 9, 1)
    silent(receiver, server, "/live/return_track/set/color", 0)
    assert handler.song.return_tracks[0].color == 0x111111


@pytest.mark.parametrize("prop, expected", [("color", 0x2196F3),
                                            ("color_index", 3),
                                            ("has_audio_input", 1),
                                            ("has_midi_output", 0),
                                            ("output_meter_level", 0.25)])
def test_master_scalar_getters_carry_the_envelope(handler, server, receiver, prop, expected):
    status, value = reply(receiver, server, "/live/master/get/%s" % prop)
    assert status == "ok"
    assert value == pytest.approx(expected)


def test_master_getter_reports_a_refused_member_as_an_error(server, receiver):
    #--------------------------------------------------------------------------------
    # This is the whole reason the new master getters carry an envelope the
    # shipped ones don't: the Main track refuses some members its class
    # declares, and a bare-value reply could only lie or say nothing.
    #--------------------------------------------------------------------------------
    h = refusing_handler(server)

    status, message = reply(receiver, server, "/live/master/get/color")
    assert status == "error"
    assert "color" in message and "Main track" in message


def refusing_handler(server):
    load_handler_module()
    module = load_return_track_module()
    h = module.ReturnTrackHandler(FakeManager(server))
    master = RefusingTrack("Main")
    h.song = make_song(master=master)
    master.refusing = True
    return h


def test_master_setter_lets_a_refused_write_reach_live_error(server, receiver):
    #--------------------------------------------------------------------------------
    # The setter split this handler keeps: an argument or bounds error is
    # logged and silent, but the assignment itself is unguarded, so a LOM
    # object that refuses the member answers a structured /live/error rather
    # than nothing at all.
    #--------------------------------------------------------------------------------
    refusing_handler(server)

    dispatch(server, "/live/master/set/color", 0x010203)
    messages = receiver.drain()
    assert len(messages) == 1
    address, params = messages[0]
    assert address == "/live/error"
    assert params[0] == "request"
    assert params[1] == "/live/master/set/color"
    assert "color" in params[2]


def test_master_scalar_setter_writes_and_stays_silent(handler, server, receiver):
    silent(receiver, server, "/live/master/set/color", 0x123456)
    assert handler.song.master_track.color == 0x123456


def test_master_setter_with_no_argument_is_silent(handler, server, receiver):
    silent(receiver, server, "/live/master/set/color")
    assert handler.song.master_track.color == 0x2196F3


#--------------------------------------------------------------------------------
# Part 2 — listeners.
#--------------------------------------------------------------------------------
def test_return_property_listener_pushes_immediately_on_its_get_address(handler, server, receiver):
    dispatch(server, "/live/return_track/start_listen/color", 0)
    assert receiver.drain() == [("/live/return_track/get/color", (0, 0x111111))]

    assert ("color", (0,)) in handler.listener_functions
    track = handler.song.return_tracks[0]
    assert len(track.listeners["color"]) == 1

    track.color = 0x999999
    track.listeners["color"][0]()
    assert receiver.drain() == [("/live/return_track/get/color", (0, 0x999999))]


def test_resubscribing_a_return_property_is_idempotent(handler, server, receiver):
    dispatch(server, "/live/return_track/start_listen/color", 0)
    dispatch(server, "/live/return_track/start_listen/color", 0)
    receiver.drain()

    assert len(handler.song.return_tracks[0].listeners["color"]) == 1


def test_a_return_property_listener_does_not_evict_its_mixer_listener(handler, server, receiver):
    dispatch(server, "/live/return_track/start_listen/volume", 0)
    dispatch(server, "/live/return_track/start_listen/color", 0)
    dispatch(server, "/live/return_track/start_listen/output_meter_level", 0)
    receiver.drain()

    assert set(handler.listener_functions) >= {("value", (0, "volume")),
                                               ("color", (0,)),
                                               ("output_meter_level", (0,))}
    track = handler.song.return_tracks[0]
    assert len(track.mixer_device.volume.listeners) == 1
    assert len(track.listeners["color"]) == 1
    assert len(track.listeners["output_meter_level"]) == 1


def test_stop_listen_removes_the_return_property_listener(handler, server, receiver):
    dispatch(server, "/live/return_track/start_listen/color", 0)
    receiver.drain()

    silent(receiver, server, "/live/return_track/stop_listen/color", 0)
    assert ("color", (0,)) not in handler.listener_functions
    assert handler.song.return_tracks[0].listeners["color"] == []


def test_start_listen_on_a_bad_index_is_silent(handler, server, receiver):
    silent(receiver, server, "/live/return_track/start_listen/color", 9)
    assert handler.listener_functions == {}


def test_master_property_listener_pushes_the_bare_value(handler, server, receiver):
    dispatch(server, "/live/master/start_listen/color")
    assert receiver.drain() == [("/live/master/get/color", (0x2196F3,))]

    #--------------------------------------------------------------------------------
    # ("color", ("master",)) — the sentinel keeps the master's key clear of
    # both a return's (color, (0,)) and any mixer key ("value", (...)).
    #--------------------------------------------------------------------------------
    assert ("color", ("master",)) in handler.listener_functions
    master = handler.song.master_track
    assert len(master.listeners["color"]) == 1

    master.color = 0x654321
    master.listeners["color"][0]()
    assert receiver.drain() == [("/live/master/get/color", (0x654321,))]


def test_master_and_return_listeners_for_one_property_coexist(handler, server, receiver):
    dispatch(server, "/live/return_track/start_listen/color", 0)
    dispatch(server, "/live/master/start_listen/color")
    dispatch(server, "/live/master/start_listen/cue_volume")
    receiver.drain()

    assert set(handler.listener_functions) == {("color", (0,)),
                                               ("color", ("master",)),
                                               ("value", ("master", "cue_volume"))}
    assert len(handler.song.return_tracks[0].listeners["color"]) == 1
    assert len(handler.song.master_track.listeners["color"]) == 1
    assert len(handler.song.master_track.mixer_device.cue_volume.listeners) == 1


def test_resubscribing_the_master_property_is_idempotent(handler, server, receiver):
    dispatch(server, "/live/master/start_listen/output_meter_level")
    dispatch(server, "/live/master/start_listen/output_meter_level")
    receiver.drain()

    assert len(handler.song.master_track.listeners["output_meter_level"]) == 1


def test_stop_listen_removes_the_master_property_listener(handler, server, receiver):
    dispatch(server, "/live/master/start_listen/color")
    receiver.drain()

    silent(receiver, server, "/live/master/stop_listen/color")
    assert ("color", ("master",)) not in handler.listener_functions
    assert handler.song.master_track.listeners["color"] == []


#--------------------------------------------------------------------------------
# Part 3 — output routing.
#--------------------------------------------------------------------------------
def test_return_available_routing_lists_carry_count_first(handler, server, receiver):
    assert reply(receiver, server,
                 "/live/return_track/get/available_output_routing_types",
                 0) == (0, "ok", 2, "Main", "Ext. Out")
    assert reply(receiver, server,
                 "/live/return_track/get/available_output_routing_channels",
                 0) == (0, "ok", 2, "1/2", "3/4")


def test_master_available_routing_lists_carry_count_first(handler, server, receiver):
    assert reply(receiver, server,
                 "/live/master/get/available_output_routing_types") == ("ok", 2, "Main",
                                                                        "Ext. Out")


def test_routing_getters_reply_the_display_name(handler, server, receiver):
    assert reply(receiver, server,
                 "/live/return_track/get/output_routing_type", 0) == (0, "ok", "Main")
    assert reply(receiver, server,
                 "/live/master/get/output_routing_channel") == ("ok", "1/2")


def test_routing_getter_error_envelope_on_a_bad_index(handler, server, receiver):
    index, status, _message = reply(receiver, server,
                                    "/live/return_track/get/output_routing_type", 4)
    assert (index, status) == (4, "error")

    index, status, _message = reply(
        receiver, server, "/live/return_track/get/available_output_routing_types", 4)
    assert (index, status) == (4, "error")


def test_routing_setter_resolves_the_object_by_display_name(handler, server, receiver):
    track = handler.song.return_tracks[0]
    silent(receiver, server, "/live/return_track/set/output_routing_type", 0, "Ext. Out")
    assert track.output_routing_type is track.available_output_routing_types[1]

    silent(receiver, server, "/live/return_track/set/output_routing_channel", 0, "3/4")
    assert track.output_routing_channel is track.available_output_routing_channels[1]


def test_master_routing_setter_resolves_the_object(handler, server, receiver):
    master = handler.song.master_track
    silent(receiver, server, "/live/master/set/output_routing_type", "Ext. Out")
    assert master.output_routing_type is master.available_output_routing_types[1]


def test_an_unmatched_routing_name_changes_nothing(handler, server, receiver):
    track = handler.song.return_tracks[0]
    before = track.output_routing_type
    silent(receiver, server, "/live/return_track/set/output_routing_type", 0, "Nowhere")
    assert track.output_routing_type is before

    master = handler.song.master_track
    before = master.output_routing_type
    silent(receiver, server, "/live/master/set/output_routing_type", "Nowhere")
    assert master.output_routing_type is before


def test_routing_setter_on_a_bad_index_is_silent(handler, server, receiver):
    silent(receiver, server, "/live/return_track/set/output_routing_type", 9, "Ext. Out")


#--------------------------------------------------------------------------------
# Part 4 — sends on returns.
#--------------------------------------------------------------------------------
def test_get_send_ok_envelope(handler, server, receiver):
    assert reply(receiver, server, "/live/return_track/get/send", 0, 1) == (0, 1, "ok", 0.25)


def test_get_send_out_of_range_names_the_real_count(handler, server, receiver):
    index, send_id, status, message = reply(receiver, server,
                                            "/live/return_track/get/send", 0, 5)
    assert (index, send_id, status) == (0, 5, "error")
    assert "2 send" in message


def test_get_send_echoes_the_send_id_when_the_return_lookup_failed(handler, server, receiver):
    index, send_id, status, _message = reply(receiver, server,
                                             "/live/return_track/get/send", 9, 1)
    assert (index, send_id, status) == (9, 1, "error")

    index, send_id, status, _message = reply(receiver, server,
                                             "/live/return_track/get/send", 9, "x")
    assert (index, send_id, status) == (9, -1, "error")


def test_set_send_writes_the_parameter(handler, server, receiver):
    silent(receiver, server, "/live/return_track/set/send", 1, 0, 0.75)
    assert handler.song.return_tracks[1].mixer_device.sends[0].value == pytest.approx(0.75)


def test_set_send_with_a_bad_send_id_writes_nothing(handler, server, receiver):
    silent(receiver, server, "/live/return_track/set/send", 1, 9, 0.75)
    assert handler.song.return_tracks[1].mixer_device.sends[0].value == pytest.approx(0.5)


#--------------------------------------------------------------------------------
# Part 5 — insert_device.
#--------------------------------------------------------------------------------
def test_return_insert_device_replies_with_the_re_read_index_and_count(handler, server, receiver):
    track = handler.song.return_tracks[0]
    assert reply(receiver, server,
                 "/live/return_track/insert_device", 0, "Delay") == (0, "ok", 1, 2)
    assert track.inserted == [("Delay", -1)]
    assert [device.name for device in track.devices] == ["Reverb", "Delay"]


def test_return_insert_device_passes_the_position_through(handler, server, receiver):
    track = handler.song.return_tracks[0]
    assert reply(receiver, server,
                 "/live/return_track/insert_device", 0, "Delay", 0) == (0, "ok", 0, 2)
    assert track.inserted == [("Delay", 0)]


def test_insert_device_reports_a_rejected_name_as_an_error(handler, server, receiver):
    handler.song.return_tracks[0].insert_raises = RuntimeError("No such device: Nonsense")

    index, status, message = reply(receiver, server,
                                   "/live/return_track/insert_device", 0, "Nonsense")
    assert (index, status) == (0, "error")
    assert "Nonsense" in message


def test_insert_device_on_a_bad_return_index_is_an_error_envelope(handler, server, receiver):
    index, status, _message = reply(receiver, server,
                                    "/live/return_track/insert_device", 9, "Delay")
    assert (index, status) == (9, "error")


def test_insert_device_with_no_name_is_an_error_envelope(handler, server, receiver):
    index, status, _message = reply(receiver, server, "/live/return_track/insert_device", 0)
    assert (index, status) == (0, "error")


def test_insert_device_reports_minus_one_for_a_device_not_on_the_chain(handler, server, receiver):
    #--------------------------------------------------------------------------------
    # What an asynchronously instantiating plugin looks like: the call returns
    # an object that is not (yet) in track.devices.
    #--------------------------------------------------------------------------------
    track = handler.song.return_tracks[0]
    ghost = FakeDevice("Plugin")

    def insert_device(name, position=-1):
        track.inserted.append((name, position))
        return ghost

    track.insert_device = insert_device
    assert reply(receiver, server,
                 "/live/return_track/insert_device", 0, "Plugin") == (0, "ok", -1, 1)


def test_master_insert_device(handler, server, receiver):
    master = handler.song.master_track
    assert reply(receiver, server, "/live/master/insert_device", "Limiter") == ("ok", 0, 1)
    assert master.inserted == [("Limiter", -1)]


def test_master_insert_device_error_envelope(handler, server, receiver):
    handler.song.master_track.insert_raises = RuntimeError("nope")
    status, message = reply(receiver, server, "/live/master/insert_device", "Nonsense")
    assert status == "error"
    assert "Nonsense" in message


#--------------------------------------------------------------------------------
# Part 5 — the regular-track counterpart, one string in track.py's generic
# methods loop: silent on success, and dispatched with the params tail.
#--------------------------------------------------------------------------------
@pytest.fixture
def track_handler(server):
    load_handler_module()
    module = load_track_module()
    h = module.TrackHandler(FakeManager(server))
    h.song = FakeSong([], FakeTrack("Main"),
                      tracks=[FakeTrack("1 Audio"), FakeTrack("2 MIDI")])
    return h


def test_track_insert_device_is_silent_and_calls_the_method(track_handler, server, receiver):
    silent(receiver, server, "/live/track/insert_device", 1, "Reverb")
    assert track_handler.song.tracks[1].inserted == [("Reverb", -1)]


def test_track_insert_device_passes_a_position(track_handler, server, receiver):
    silent(receiver, server, "/live/track/insert_device", 0, "Reverb", 0)
    assert track_handler.song.tracks[0].inserted == [("Reverb", 0)]
