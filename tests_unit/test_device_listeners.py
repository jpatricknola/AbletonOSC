"""
Listener identity for the Device API, without Ableton Live.

Every device listener — the three property pairs and the parameter/value
pair — is addressed by a tuple of indices that arrives over the wire. Three
separate things are built from that tuple: the LOM subscript that finds the
object to bind to, the bookkeeping key under which the callback is
remembered, and the indices echoed back in the push. They only work if all
three agree, and OSC does not guarantee the client's number type: TouchOSC
and friends send floats by default (upstream issue #33), so a start sent as
floats and a stop sent as ints are the same subscription to a human and two
different dict keys to Python. These tests pin the normalisation that makes
them one, and the per-device identity that stops one device's subscription
from silently replacing another's.

This is the first file to construct a production *handler subclass* outside
Live. It is possible because device.py imports no Live module — only
`typing` and `.handler` — so conftest.load_device_module() gets the real
DeviceHandler on top of the same Component stub test_handler_lifecycle.py
uses. The OSCServer, the dispatcher and the handler underneath are all
production code; only the LOM objects below are fakes.

The fakes deliberately expose `add_name_listener` but **no**
`add_type_listener` / `add_class_name_listener`, mirroring the real
`Live.Device.Device` as measured on 2026-08-27 against Live 12.4.3 (see
API.md § Device API). `type` and `class_name` are plain non-observable
properties there, so subscribing to them can only fail — case 9 pins that
it fails as a structured, correlatable /live/error and leaves no
half-registered bookkeeping behind.
"""

import pytest

from .conftest import dispatch, load_device_module, load_handler_module


class FakeManager:
    """`osc_server` is the only attribute AbletonOSCHandler reads off it."""

    def __init__(self, osc_server):
        self.osc_server = osc_server


class FakeParameter:
    """
    A DeviceParameter stand-in: a value, and the add_/remove_ pair
    device.py binds the parameter listener through.
    """

    def __init__(self, name, value):
        self.name = name
        self.value = value
        self.listeners = []

    def str_for_value(self, value):
        return "%.1f Hz" % value

    def add_value_listener(self, function):
        self.listeners.append(function)

    def remove_value_listener(self, function):
        self.listeners.remove(function)


class FakeDevice:
    """
    A Device stand-in. `name` is observable, exactly as the LOM has it;
    `type` and `class_name` are plain attributes with no listener pair,
    exactly as the LOM has them.
    """

    def __init__(self, name, parameters=()):
        self.name = name
        self.type = 1
        self.class_name = "Operator"
        self.parameters = list(parameters)
        self.listeners = []

    def add_name_listener(self, function):
        self.listeners.append(function)

    def remove_name_listener(self, function):
        self.listeners.remove(function)


class FakeTrack:
    def __init__(self, devices):
        self.devices = list(devices)


class FakeSong:
    def __init__(self, tracks):
        self.tracks = list(tracks)


def make_device(name):
    return FakeDevice(name, parameters=[FakeParameter("Device On", 1.0),
                                        FakeParameter("Frequency", 440.0),
                                        FakeParameter("Resonance", 0.5)])


@pytest.fixture
def handler(server):
    """
    The production DeviceHandler, registered against the production
    OSCServer, with a two-device track and a one-device track underneath.

    `self.song` is read at dispatch time, not at registration time, so
    assigning it after construction is enough — and is the only way to get
    a song in here at all without Live.
    """
    load_handler_module()
    device_module = load_device_module()
    h = device_module.DeviceHandler(FakeManager(server))
    h.song = FakeSong([FakeTrack([make_device("Operator"),
                                  make_device("Reverb")]),
                       FakeTrack([make_device("EQ Eight")])])
    return h


def devices_of(handler, track_index):
    return handler.song.tracks[track_index].devices


#--------------------------------------------------------------------------------
# 1. A float-indexed parameter subscribe works, and normalises to ints
#--------------------------------------------------------------------------------

def test_float_parameter_subscribe_normalises_identity(handler, server, receiver):
    dispatch(server, "/live/device/start_listen/parameter/value", 0.0, 0.0, 1.0)

    #--------------------------------------------------------------------------------
    # Before normalisation this raised TypeError on device.parameters[1.0]
    # and the subscription was simply impossible for a float-sending client.
    #--------------------------------------------------------------------------------
    parameter = devices_of(handler, 0)[0].parameters[1]
    assert len(parameter.listeners) == 1

    assert list(handler.listener_functions.keys()) == [("value", (0, 0, 1))]
    assert list(handler.listener_objects.keys()) == [("value", (0, 0, 1))]
    assert handler.listener_objects[("value", (0, 0, 1))] is parameter

    messages = receiver.drain()
    assert messages == [
        ("/live/device/get/parameter/value", (0, 0, 1, 440.0)),
        ("/live/device/get/parameter/value_string", (0, 0, 1, "440.0 Hz")),
    ]
    #--------------------------------------------------------------------------------
    # Ints on the wire, not floats that happen to be whole: a client
    # correlating the push against its own int-indexed request compares the
    # decoded values, and 0.0 != 0 in most languages' pattern matches.
    #--------------------------------------------------------------------------------
    for _, params in messages:
        assert [type(param) for param in params[:3]] == [int, int, int]


#--------------------------------------------------------------------------------
# 2. Mixed-type start/stop pairs address the same listener
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("start_args, stop_args", [
    ((0.0, 0.0, 1.0), (0, 0, 1)),
    ((0, 0, 1), (0.0, 0.0, 1.0)),
])
def test_mixed_type_start_stop_does_not_leak(handler, server, receiver,
                                             start_args, stop_args):
    dispatch(server, "/live/device/start_listen/parameter/value", *start_args)
    receiver.drain()

    dispatch(server, "/live/device/stop_listen/parameter/value", *stop_args)

    parameter = devices_of(handler, 0)[0].parameters[1]
    assert parameter.listeners == []
    assert handler.listener_functions == {}
    assert handler.listener_objects == {}
    #--------------------------------------------------------------------------------
    # A stop is silent on the wire either way; what would betray the leak is
    # an error, or a push arriving later from a listener that was never
    # unbound. Neither may appear.
    #--------------------------------------------------------------------------------
    assert receiver.drain() == []


#--------------------------------------------------------------------------------
# 3. Re-subscribing is idempotent across number types
#--------------------------------------------------------------------------------

def test_restart_is_idempotent_across_number_types(handler, server, receiver):
    dispatch(server, "/live/device/start_listen/parameter/value", 0.0, 0.0, 1.0)
    dispatch(server, "/live/device/start_listen/parameter/value", 0, 0, 1)
    receiver.drain()

    parameter = devices_of(handler, 0)[0].parameters[1]
    assert len(parameter.listeners) == 1
    assert len(handler.listener_functions) == 1
    assert len(handler.listener_objects) == 1


#--------------------------------------------------------------------------------
# 4. clear_api() unbinds a float-indexed subscription
#--------------------------------------------------------------------------------

def test_clear_api_unbinds_float_indexed_subscription(handler, server, receiver):
    dispatch(server, "/live/device/start_listen/parameter/value", 0.0, 0.0, 1.0)
    receiver.drain()

    handler.clear_api()

    assert devices_of(handler, 0)[0].parameters[1].listeners == []
    assert handler.listener_functions == {}
    assert handler.listener_objects == {}


#--------------------------------------------------------------------------------
# 5. A parameter change pushes both datagrams with int indices
#--------------------------------------------------------------------------------

def test_parameter_change_pushes_both_datagrams(handler, server, receiver):
    dispatch(server, "/live/device/start_listen/parameter/value", 0.0, 0.0, 1.0)
    receiver.drain()

    parameter = devices_of(handler, 0)[0].parameters[1]
    parameter.value = 880.0
    parameter.listeners[0]()

    assert receiver.drain() == [
        ("/live/device/get/parameter/value", (0, 0, 1, 880.0)),
        ("/live/device/get/parameter/value_string", (0, 0, 1, "880.0 Hz")),
    ]


#--------------------------------------------------------------------------------
# 6. name subscribes per device, not per property
#--------------------------------------------------------------------------------

def test_name_subscribes_per_device(handler, server, receiver):
    dispatch(server, "/live/device/start_listen/name", 0, 0)
    dispatch(server, "/live/device/start_listen/name", 0, 1)

    #--------------------------------------------------------------------------------
    # Registered without include_ids the key was ("name", ()) for every
    # device, so this second subscribe found the first one's key and stopped
    # it — one subscription per property, process-wide, with nothing on the
    # wire to say so.
    #--------------------------------------------------------------------------------
    assert set(handler.listener_functions.keys()) == {("name", (0, 0)),
                                                      ("name", (0, 1))}
    assert len(devices_of(handler, 0)[0].listeners) == 1
    assert len(devices_of(handler, 0)[1].listeners) == 1

    assert receiver.drain() == [
        ("/live/device/get/name", (0, 0, "Operator")),
        ("/live/device/get/name", (0, 1, "Reverb")),
    ]


#--------------------------------------------------------------------------------
# 7. A name change push says which device changed
#--------------------------------------------------------------------------------

def test_name_change_push_carries_identity(handler, server, receiver):
    dispatch(server, "/live/device/start_listen/name", 0, 0)
    dispatch(server, "/live/device/start_listen/name", 0, 1)
    receiver.drain()

    device = devices_of(handler, 0)[1]
    device.name = "Valhalla"
    device.listeners[0]()

    assert receiver.drain() == [("/live/device/get/name", (0, 1, "Valhalla"))]
    assert len(devices_of(handler, 0)[0].listeners) == 1


#--------------------------------------------------------------------------------
# 8. stop_listen/name stops one device, and floats find the int key
#--------------------------------------------------------------------------------

def test_stop_listen_name_stops_only_its_own_device(handler, server, receiver):
    dispatch(server, "/live/device/start_listen/name", 0.0, 0.0)
    dispatch(server, "/live/device/start_listen/name", 0, 1)
    receiver.drain()

    dispatch(server, "/live/device/stop_listen/name", 0, 0)

    assert devices_of(handler, 0)[0].listeners == []
    assert len(devices_of(handler, 0)[1].listeners) == 1
    assert list(handler.listener_functions.keys()) == [("name", (0, 1))]
    assert receiver.drain() == []

    dispatch(server, "/live/device/stop_listen/name", 0.0, 1.0)

    assert devices_of(handler, 0)[1].listeners == []
    assert handler.listener_functions == {}
    assert handler.listener_objects == {}


#--------------------------------------------------------------------------------
# 9. type / class_name are not observable in Live: fail loudly and cleanly
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("prop", ["type", "class_name"])
def test_unobservable_property_subscribe_is_a_structured_error(handler, server,
                                                               receiver, prop):
    address = "/live/device/start_listen/%s" % prop
    dispatch(server, address, 0, 0)

    messages = receiver.drain()
    assert len(messages) == 1
    error_address, params = messages[0]
    assert error_address == "/live/error"
    #--------------------------------------------------------------------------------
    # The envelope carries the request back so the client can correlate it:
    # ("request", address, detail, argc, *args).
    #--------------------------------------------------------------------------------
    assert params[0] == "request"
    assert params[1] == address
    assert "add_%s_listener" % prop in params[2]
    assert params[3:] == (2, 0, 0)

    #--------------------------------------------------------------------------------
    # _start_listen resolves add_<prop>_listener *before* it writes either
    # dict, so a failure leaves no half-registered entry that a later
    # _clear_listeners would trip over.
    #--------------------------------------------------------------------------------
    assert handler.listener_functions == {}
    assert handler.listener_objects == {}


#--------------------------------------------------------------------------------
# 10. Query replies are unchanged by any of the above
#--------------------------------------------------------------------------------

def test_query_replies_are_unchanged(handler, server, receiver):
    dispatch(server, "/live/device/get/name", 0, 0)
    assert receiver.drain() == [("/live/device/get/name", (0, 0, "Operator"))]

    dispatch(server, "/live/device/get/parameter/value", 0, 0, 1)
    assert receiver.drain() == [("/live/device/get/parameter/value",
                                 (0, 0, 1, 440.0))]

    #--------------------------------------------------------------------------------
    # get/ is registered without include_ids: the wrapper's reply envelope
    # already prepends the indices, so adding ids there would echo them twice.
    #--------------------------------------------------------------------------------
    dispatch(server, "/live/device/get/type", 0, 1)
    assert receiver.drain() == [("/live/device/get/type", (0, 1, 1))]


#--------------------------------------------------------------------------------
# 11. Arguments past the third are ignored on a parameter subscription
#--------------------------------------------------------------------------------

def test_parameter_subscribe_ignores_arguments_past_the_third(handler, server,
                                                              receiver):
    dispatch(server, "/live/device/start_listen/parameter/value", 0, 0, 1, "bogus")

    #--------------------------------------------------------------------------------
    # API.md, § Device: Listening: "Arguments past the third are not part of
    # a parameter subscription's identity and are ignored." The key and the
    # push both carry exactly three ints, with the fourth argument dropped.
    #--------------------------------------------------------------------------------
    assert list(handler.listener_functions.keys()) == [("value", (0, 0, 1))]
    assert receiver.drain() == [
        ("/live/device/get/parameter/value", (0, 0, 1, 440.0)),
        ("/live/device/get/parameter/value_string", (0, 0, 1, "440.0 Hz")),
    ]


#--------------------------------------------------------------------------------
# 12. Fewer than three arguments is a malformed request, not a listener leak
#--------------------------------------------------------------------------------

def test_parameter_subscribe_with_too_few_arguments_is_a_structured_error(
        handler, server, receiver):
    address = "/live/device/start_listen/parameter/value"
    dispatch(server, address, 0, 0)

    #--------------------------------------------------------------------------------
    # API.md, § Device: Listening: "sending fewer than three is a malformed
    # request and answers on /live/error." params[2] is missing, so the
    # normalisation raises IndexError before any dict is written.
    #--------------------------------------------------------------------------------
    messages = receiver.drain()
    assert len(messages) == 1
    error_address, params = messages[0]
    assert error_address == "/live/error"
    assert params[0] == "request"
    assert params[1] == address

    assert handler.listener_functions == {}
    assert handler.listener_objects == {}
