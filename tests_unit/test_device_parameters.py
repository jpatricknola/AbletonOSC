"""
The DeviceParameter description addresses, without Ableton Live.

`/live/device/get/parameters/{name,value,min,max,is_quantized}` describe a
parameter as a number in a range. The seventeen addresses exercised here
describe what it *means*: the GUI string, the enum labels a quantized
parameter cycles through, whether Live greyed it out or handed it to
automation, its reset value, its pre-rename name, and the gesture pair that
groups a run of writes into one undo step.

Everything under test is production code: conftest.load_device_module()
builds the real DeviceHandler on the real OSCServer, and every case goes in
as a datagram through `dispatch`. Only the LOM objects are fakes.

The fakes model three things the real Live objects do that the wire form
depends on:

1. `ParameterState` / `AutomationState` are Boost.Python enums, which are
   `int` subclasses carrying a `name`. FakeEnum is that shape, so these
   tests would still pass if device.py dropped its `int()` cast — and would
   fail if a future Live returned something that is not an int, which is
   exactly the case the cast is insurance against. What the codes *mean* in
   a real Live is unmeasured (API.md marks the table ⚠️).
2. `value_items` / `short_value_items` raise on a non-quantized parameter
   ("Raises an error if 'is_quantized' is False", Live's own docstring). The
   fake raises RuntimeError; the handler catches broadly because the real
   class is unmeasured.
3. `default_value` is not guaranteed to exist for every parameter, so one
   fake raises on the read.

`FakeParameter` in test_device_listeners.py is deliberately left alone —
that file's docstring documents its fakes as the measured `Device` shape,
and this file owns the richer parameter fake instead.

What this cannot prove: any of it against a real `Live.DeviceParameter`.
The enum codes, what actually raises, and what `display_value =` accepts
need the Live verification checks in the plan.
"""

import pytest

from .conftest import dispatch, load_device_module, load_handler_module


class FakeManager:
    """`osc_server` is the only attribute AbletonOSCHandler reads off it."""

    def __init__(self, osc_server):
        self.osc_server = osc_server


class FakeEnum(int):
    """
    A Boost.Python enum's shape for the purposes of this bridge: an int
    subclass with a `name`. `int()` of one is the integer code, which is what
    goes on the wire.
    """

    def __new__(cls, value, name):
        instance = int.__new__(cls, value)
        instance.name = name
        return instance

    def __repr__(self):
        return "FakeEnum(%d, %r)" % (int(self), self.name)


STATE_ENABLED = FakeEnum(0, "enabled")
STATE_DISABLED = FakeEnum(1, "disabled")
STATE_IRRELEVANT = FakeEnum(2, "irrelevant")

AUTOMATION_NONE = FakeEnum(0, "none")
AUTOMATION_PLAYING = FakeEnum(1, "playing")
AUTOMATION_OVERRIDDEN = FakeEnum(2, "overridden")


class FakeParameter:
    """
    A DeviceParameter stand-in covering every member the description
    addresses read, plus the two failure modes the handler answers
    gracefully.
    """

    def __init__(self, name, value=0.0, minimum=0.0, maximum=1.0,
                 is_quantized=False, value_items=(), short_value_items=(),
                 display_value="", state=STATE_ENABLED, is_enabled=True,
                 automation_state=AUTOMATION_NONE, default_value=0.0,
                 original_name=None, default_value_raises=False,
                 display_value_raises=False):
        self.name = name
        self.value = value
        self.min = minimum
        self.max = maximum
        self.is_quantized = is_quantized
        self._value_items = tuple(value_items)
        self._short_value_items = tuple(short_value_items)
        self._display_value = display_value
        self.state = state
        self.is_enabled = is_enabled
        self.automation_state = automation_state
        self._default_value = default_value
        self.original_name = name if original_name is None else original_name
        self.default_value_raises = default_value_raises
        self.display_value_raises = display_value_raises
        self.display_value_writes = []
        self.gestures = []

    #--------------------------------------------------------------------------------
    # Live: "Raises an error if 'is_quantized' is False."
    #--------------------------------------------------------------------------------
    @property
    def value_items(self):
        if not self.is_quantized:
            raise RuntimeError("value_items is not available for this parameter")
        return self._value_items

    @property
    def short_value_items(self):
        if not self.is_quantized:
            raise RuntimeError("short_value_items is not available for this parameter")
        return self._short_value_items

    @property
    def default_value(self):
        if self.default_value_raises:
            raise RuntimeError("this parameter has no default value")
        return self._default_value

    @property
    def display_value(self):
        return self._display_value

    @display_value.setter
    def display_value(self, value):
        if self.display_value_raises:
            raise RuntimeError("cannot parse %r as a value" % (value,))
        self._display_value = value
        self.display_value_writes.append(value)

    def begin_gesture(self):
        self.gestures.append("begin")

    def end_gesture(self):
        self.gestures.append("end")


class FakeDevice:
    def __init__(self, name, parameters=()):
        self.name = name
        self.parameters = list(parameters)


class FakeTrack:
    def __init__(self, devices):
        self.devices = list(devices)


class FakeSong:
    def __init__(self, tracks):
        self.tracks = list(tracks)


def make_parameters():
    """
    Three parameters chosen so every branch of the new handlers is reachable
    from one device: a quantized switch with labels, a continuous parameter
    whose item reads raise, and a macro-renamed parameter with no default.
    """
    return [
        FakeParameter("Device On", value=1.0, minimum=0.0, maximum=1.0,
                      is_quantized=True,
                      value_items=("Off", "On"),
                      short_value_items=("Off", "On"),
                      display_value="On",
                      state=STATE_ENABLED, is_enabled=True,
                      automation_state=AUTOMATION_NONE,
                      default_value=1.0),
        FakeParameter("Frequency", value=440.0, minimum=20.0, maximum=20000.0,
                      display_value="440 Hz",
                      state=STATE_DISABLED, is_enabled=False,
                      automation_state=AUTOMATION_PLAYING,
                      default_value=440.0),
        FakeParameter("Macro 1", value=0.25, minimum=0.0, maximum=127.0,
                      display_value="32",
                      state=STATE_IRRELEVANT, is_enabled=True,
                      automation_state=AUTOMATION_OVERRIDDEN,
                      original_name="Attack",
                      default_value_raises=True),
    ]


@pytest.fixture
def handler(server):
    """
    The production DeviceHandler on the production OSCServer. Track 0 holds
    a three-parameter device and a device with no parameters at all; track 1
    holds one more so a wrong track index is a different device, not a
    missing one.
    """
    load_handler_module()
    device_module = load_device_module()
    h = device_module.DeviceHandler(FakeManager(server))
    h.song = FakeSong([FakeTrack([FakeDevice("Operator", make_parameters()),
                                  FakeDevice("Utility", [])]),
                       FakeTrack([FakeDevice("EQ Eight", make_parameters())])])
    return h


def parameters_of(handler, track_index=0, device_index=0):
    return handler.song.tracks[track_index].devices[device_index].parameters


def one_message(receiver):
    messages = receiver.drain()
    assert len(messages) == 1, messages
    return messages[0]


#--------------------------------------------------------------------------------
# 1. The six bulk addresses answer one value per parameter, in device order
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("field, expected", [
    ("display_value", ("On", "440 Hz", "32")),
    ("state", (0, 1, 2)),
    ("is_enabled", (True, False, True)),
    ("automation_state", (0, 1, 2)),
    ("original_name", ("Device On", "Frequency", "Attack")),
])
def test_bulk_reads_answer_in_parameter_order(handler, server, receiver,
                                              field, expected):
    address = "/live/device/get/parameters/%s" % field
    dispatch(server, address, 0, 0)

    reply_address, params = one_message(receiver)
    assert reply_address == address
    assert params == (0, 0, *expected)


def test_bulk_reads_carry_the_right_osc_types(handler, server, receiver):
    #--------------------------------------------------------------------------------
    # The enums are int subclasses, so an unconverted reply would still decode
    # as an int here. What this pins is the *tag*: a str where the GUI string
    # goes, T/F where the flag goes, and an int — never a string — where the
    # enum code goes.
    #--------------------------------------------------------------------------------
    dispatch(server, "/live/device/get/parameters/display_value", 0, 0)
    assert [type(param) for param in one_message(receiver)[1][2:]] == [str, str, str]

    dispatch(server, "/live/device/get/parameters/state", 0, 0)
    assert [type(param) for param in one_message(receiver)[1][2:]] == [int, int, int]

    dispatch(server, "/live/device/get/parameters/is_enabled", 0, 0)
    assert [type(param) for param in one_message(receiver)[1][2:]] == [bool, bool, bool]


def test_bulk_default_value_is_float_where_live_answers(handler, server, receiver):
    dispatch(server, "/live/device/get/parameters/default_value", 0, 0)

    reply_address, params = one_message(receiver)
    assert reply_address == "/live/device/get/parameters/default_value"
    assert params[:2] == (0, 0)
    assert params[2] == pytest.approx(1.0)
    assert params[3] == pytest.approx(440.0)


#--------------------------------------------------------------------------------
# 2. A device with no parameters answers the two indices and nothing else
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("field", ["display_value", "state", "is_enabled",
                                   "automation_state", "default_value",
                                   "original_name"])
def test_device_without_parameters_answers_only_the_indices(handler, server,
                                                            receiver, field):
    address = "/live/device/get/parameters/%s" % field
    dispatch(server, address, 0, 1)

    assert one_message(receiver) == (address, (0, 1))


#--------------------------------------------------------------------------------
# 3. One parameter without a default does not poison the bulk reply
#--------------------------------------------------------------------------------

def test_bulk_default_value_sends_nil_for_a_parameter_that_raises(handler,
                                                                  server,
                                                                  receiver):
    assert parameters_of(handler)[2].default_value_raises

    dispatch(server, "/live/device/get/parameters/default_value", 0, 0)

    reply_address, params = one_message(receiver)
    assert reply_address == "/live/device/get/parameters/default_value"
    #--------------------------------------------------------------------------------
    # The nil is in the raising parameter's own slot: the other two are real
    # floats, and the reply still has one element per parameter, so a client
    # zipping it against parameters/name stays aligned.
    #--------------------------------------------------------------------------------
    assert len(params) == 5
    assert params[4] is None


#--------------------------------------------------------------------------------
# 4. Each per-parameter getter echoes its index, and normalises float indices
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("field, parameter_index, expected", [
    ("display_value", 1, "440 Hz"),
    ("state", 1, 1),
    ("is_enabled", 1, False),
    ("automation_state", 1, 1),
    ("default_value", 1, 440.0),
    ("original_name", 2, "Attack"),
])
def test_per_parameter_getters(handler, server, receiver, field,
                               parameter_index, expected):
    address = "/live/device/get/parameter/%s" % field
    dispatch(server, address, 0, 0, parameter_index)

    reply_address, params = one_message(receiver)
    assert reply_address == address
    assert params[:3] == (0, 0, parameter_index)
    if isinstance(expected, float):
        assert params[3] == pytest.approx(expected)
    else:
        assert params[3] == expected


@pytest.mark.parametrize("address", [
    "/live/device/get/parameter/display_value",
    "/live/device/get/parameter/state",
    "/live/device/get/parameter/is_enabled",
    "/live/device/get/parameter/automation_state",
    "/live/device/get/parameter/default_value",
    "/live/device/get/parameter/original_name",
    "/live/device/get/parameter/value_items",
    "/live/device/get/parameter/short_value_items",
])
def test_float_indices_normalise_to_ints_in_the_echo(handler, server, receiver,
                                                     address):
    #--------------------------------------------------------------------------------
    # TouchOSC-style clients send floats by default (upstream issue #33). The
    # lookup has to accept them and the echo has to come back as ints, or a
    # client correlating the reply against its own int-indexed request fails
    # the comparison.
    #--------------------------------------------------------------------------------
    dispatch(server, address, 0.0, 0.0, 0.0)

    reply_address, params = one_message(receiver)
    assert reply_address == address
    assert params[:3] == (0, 0, 0)
    assert [type(param) for param in params[:3]] == [int, int, int]


def test_default_value_that_raises_is_nil_per_parameter_too(handler, server,
                                                            receiver):
    dispatch(server, "/live/device/get/parameter/default_value", 0, 0, 2)

    assert one_message(receiver) == (
        "/live/device/get/parameter/default_value", (0, 0, 2, None))


#--------------------------------------------------------------------------------
# 5. value_items: labels when quantized, gracefully empty when not
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("address", ["/live/device/get/parameter/value_items",
                                     "/live/device/get/parameter/short_value_items"])
def test_value_items_lists_the_labels_of_a_quantized_parameter(handler, server,
                                                               receiver, address):
    dispatch(server, address, 0, 0, 0)

    assert one_message(receiver) == (address, (0, 0, 0, "Off", "On"))


@pytest.mark.parametrize("address", ["/live/device/get/parameter/value_items",
                                     "/live/device/get/parameter/short_value_items"])
def test_value_items_of_a_continuous_parameter_is_empty_not_an_error(handler,
                                                                     server,
                                                                     receiver,
                                                                     address):
    #--------------------------------------------------------------------------------
    # Live raises on this read. Answering with the indices and no items — rather
    # than a /live/error — is what stops a client describing a whole device from
    # collecting one error per continuous parameter on its reply socket.
    #--------------------------------------------------------------------------------
    assert not parameters_of(handler)[1].is_quantized

    dispatch(server, address, 0, 0, 1)

    assert one_message(receiver) == (address, (0, 0, 1))


#--------------------------------------------------------------------------------
# 6. set/parameter/display_value assigns the string and stays silent
#--------------------------------------------------------------------------------

def test_set_display_value_assigns_the_string_and_replies_nothing(handler,
                                                                  server,
                                                                  receiver):
    dispatch(server, "/live/device/set/parameter/display_value", 0, 0, 1, "880 Hz")

    parameter = parameters_of(handler)[1]
    assert parameter.display_value_writes == ["880 Hz"]
    #--------------------------------------------------------------------------------
    # Passed through uncast: Live parses the string, so the handler must not
    # coerce it to a number on the way in.
    #--------------------------------------------------------------------------------
    assert parameter.display_value == "880 Hz"
    assert receiver.drain() == []


def test_set_display_value_that_live_rejects_is_a_structured_error(handler,
                                                                   server,
                                                                   receiver):
    parameters_of(handler)[1].display_value_raises = True

    address = "/live/device/set/parameter/display_value"
    dispatch(server, address, 0, 0, 1, "not a frequency")

    error_address, params = one_message(receiver)
    assert error_address == "/live/error"
    assert params[0] == "request"
    assert params[1] == address
    assert params[3:] == (4, 0, 0, 1, "not a frequency")


#--------------------------------------------------------------------------------
# 7. The gesture pair calls through and says nothing
#--------------------------------------------------------------------------------

def test_gesture_pair_calls_the_parameter_and_is_silent(handler, server, receiver):
    dispatch(server, "/live/device/parameter/begin_gesture", 0, 0, 1)
    dispatch(server, "/live/device/set/parameter/value", 0, 0, 1, 660.0)
    dispatch(server, "/live/device/parameter/end_gesture", 0, 0, 1)

    parameter = parameters_of(handler)[1]
    assert parameter.gestures == ["begin", "end"]
    assert parameter.value == pytest.approx(660.0)
    assert receiver.drain() == []


def test_gestures_address_one_parameter_only(handler, server, receiver):
    dispatch(server, "/live/device/parameter/begin_gesture", 0, 0, 2)

    assert [p.gestures for p in parameters_of(handler)] == [[], [], ["begin"]]


#--------------------------------------------------------------------------------
# 8. Bad indices are structured errors that echo the request
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("address", [
    "/live/device/get/parameter/display_value",
    "/live/device/get/parameter/state",
    "/live/device/get/parameter/is_enabled",
    "/live/device/get/parameter/automation_state",
    "/live/device/get/parameter/default_value",
    "/live/device/get/parameter/original_name",
    "/live/device/get/parameter/value_items",
    "/live/device/get/parameter/short_value_items",
    "/live/device/set/parameter/display_value",
    "/live/device/parameter/begin_gesture",
    "/live/device/parameter/end_gesture",
])
def test_out_of_range_parameter_index_is_an_error(handler, server, receiver,
                                                  address):
    #--------------------------------------------------------------------------------
    # Including the two item lists: their graceful-empty rule covers the
    # member read, not the lookup, so a nonexistent parameter still fails
    # loudly rather than answering an empty list.
    #--------------------------------------------------------------------------------
    dispatch(server, address, 0, 0, 99)

    error_address, params = one_message(receiver)
    assert error_address == "/live/error"
    assert params[0] == "request"
    assert params[1] == address
    assert params[3:] == (3, 0, 0, 99)


@pytest.mark.parametrize("field", ["display_value", "state", "is_enabled",
                                   "automation_state", "default_value",
                                   "original_name"])
def test_out_of_range_device_index_is_an_error(handler, server, receiver, field):
    address = "/live/device/get/parameters/%s" % field
    dispatch(server, address, 0, 99)

    error_address, params = one_message(receiver)
    assert error_address == "/live/error"
    assert params[0] == "request"
    assert params[1] == address
    assert params[3:] == (2, 0, 99)


#--------------------------------------------------------------------------------
# 9. The numeric addresses these were added beside are untouched
#--------------------------------------------------------------------------------

def test_existing_parameter_addresses_are_unchanged(handler, server, receiver):
    #--------------------------------------------------------------------------------
    # add_handler() overwrites silently, so a new registration that collided
    # with an old address would replace it with no warning anywhere. Dispatching
    # the pre-existing family is the cheap proof that none of the seventeen did.
    # (test_device_listeners.py, unmodified, is the same proof for both listen
    # pairs.)
    #--------------------------------------------------------------------------------
    dispatch(server, "/live/device/get/num_parameters", 0, 0)
    assert one_message(receiver) == ("/live/device/get/num_parameters", (0, 0, 3))

    dispatch(server, "/live/device/get/parameters/name", 0, 0)
    assert one_message(receiver) == ("/live/device/get/parameters/name",
                                     (0, 0, "Device On", "Frequency", "Macro 1"))

    dispatch(server, "/live/device/get/parameters/is_quantized", 0, 0)
    assert one_message(receiver) == ("/live/device/get/parameters/is_quantized",
                                     (0, 0, True, False, False))

    dispatch(server, "/live/device/get/parameter/name", 0, 0, 2)
    assert one_message(receiver) == ("/live/device/get/parameter/name",
                                     (0, 0, 2, "Macro 1"))
