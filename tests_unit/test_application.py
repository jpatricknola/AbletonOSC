"""
The application-level address table — dialog state, the exact version
identity, `has_option`, the two flattened list reads and the two `show_*`
message methods — dispatched end to end through the real
`ApplicationHandler`.

`ApplicationHandler.init_api` resolves the Live application object *at
registration time*, to bind it into the partial()s of its generic property
loop, so the handler is built after monkeypatching conftest's
`load_application_module()` seam — `abletonosc.application.get_application`
— with the `FakeApplication` below. That seam is the application-object
image of `bind_song()`, and it is what keeps the suite's `Live` stub empty
(see conftest's module docstring).

What this pins is the glue: every address as registered, the reply arity and
shape of each read, the flattening rules for `unavailable_features` and
`control_surfaces` (including the empty-slot and empty-list cases), the
`has_option` echo, listener bookkeeping across `clear_api()` for the two
observable members, and the structured `/live/error` envelope for a missing
argument.

Two of these are regression tests for decisions rather than for code paths:

* **`test_construction_sends_only_startup`** — upstream's `init_api` ended
  with an unsolicited, argument-less
  `/live/application/get/average_process_usage` datagram, which reached
  clients looking like a malformed getter reply. It is removed; an upstream
  merge that restores it fails here.
* **`test_show_message_passes_exactly_one_argument`** — both `show_*`
  methods are called with the text and nothing else, so Live's `buttons`
  default (`OK_BUTTON`) stands. That is the OK-only guarantee, and it is
  load-bearing: `press_current_dialog_button` is deliberately not on the
  wire, so the bridge must never raise a dialog offering choices the remote
  cannot make. Widening the call fails here, which is the point.

What no test here can reach is the real LOM: whether Live's
`unavailable_features` elements stringify usefully, whether `show_message`
blocks the tick thread, what `has_option` actually matches. Those are Live
verification, and `API.md` still marks them ⚠️.
"""

import pytest

from .conftest import dispatch, load_application_module

STARTUP = "/live/startup"
ERROR = "/live/error"


class FakeManager:
    """`osc_server` is the only attribute AbletonOSCHandler reads off it."""

    def __init__(self, osc_server):
        self.osc_server = osc_server


class FakeApplication:
    """
    Stands in for Live.Application.Application, with only the members the
    handler touches.

    The two observable members carry hand-rolled listener registries rather
    than a generic one, so a `start_listen` on a member Live does *not*
    observe (`current_dialog_message`, `current_dialog_button_count`) would
    fail here with the same AttributeError it would raise in Live.
    """

    def __init__(self,
                 open_dialog_count=0,
                 current_dialog_message="",
                 current_dialog_button_count=0,
                 peak_process_usage=0.25,
                 number_of_push_apps_running=0,
                 unavailable_features=(),
                 control_surfaces=(),
                 options=(),
                 show_message_result=0):
        self.open_dialog_count = open_dialog_count
        self.current_dialog_message = current_dialog_message
        self.current_dialog_button_count = current_dialog_button_count
        self.peak_process_usage = peak_process_usage
        self.number_of_push_apps_running = number_of_push_apps_running
        self.unavailable_features = list(unavailable_features)
        self.control_surfaces = list(control_surfaces)
        self._options = set(options)
        self._show_message_result = show_message_result

        self.open_dialog_count_listeners = []
        self.peak_process_usage_listeners = []
        self.has_option_calls = []
        self.show_message_calls = []
        self.show_on_the_fly_message_calls = []

    #--------------------------------------------------------------------------------
    # Version identity
    #--------------------------------------------------------------------------------
    def get_major_version(self):
        return 12

    def get_minor_version(self):
        return 4

    def get_bugfix_version(self):
        return 3

    def get_build_id(self):
        return "2026-01-01_abcdef0"

    def get_variant(self):
        return "Suite"

    def get_version_string(self):
        return "12.4.3"

    #--------------------------------------------------------------------------------
    # Methods
    #--------------------------------------------------------------------------------
    def has_option(self, option):
        self.has_option_calls.append(option)
        return option in self._options

    def show_message(self, *args, **kwargs):
        self.show_message_calls.append((args, kwargs))
        return self._show_message_result

    def show_on_the_fly_message(self, *args, **kwargs):
        self.show_on_the_fly_message_calls.append((args, kwargs))
        return self._show_message_result

    #--------------------------------------------------------------------------------
    # Listeners, for the two observable members only
    #--------------------------------------------------------------------------------
    def add_open_dialog_count_listener(self, fn):
        self.open_dialog_count_listeners.append(fn)

    def remove_open_dialog_count_listener(self, fn):
        self.open_dialog_count_listeners.remove(fn)

    def add_peak_process_usage_listener(self, fn):
        self.peak_process_usage_listeners.append(fn)

    def remove_peak_process_usage_listener(self, fn):
        self.peak_process_usage_listeners.remove(fn)

    def set_open_dialog_count(self, value):
        """Change the value the way Live would: assign, then notify."""
        self.open_dialog_count = value
        for fn in list(self.open_dialog_count_listeners):
            fn()


class FakeControlSurface:
    """
    Only its *class name* ever reaches the wire, so the concrete type is the
    whole fixture. Named subclasses stand in for the two slots below.
    """


class AbletonOSC(FakeControlSurface):
    pass


class Push2(FakeControlSurface):
    pass


def build_handler(server, monkeypatch, application):
    """
    Construct the production ApplicationHandler with `application` in place of
    Live's, by substituting the module seam before __init__ runs — init_api
    calls get_application() during construction, so an instance assignment
    afterwards would always be too late.
    """
    module = load_application_module()
    monkeypatch.setattr(module, "get_application", lambda: application)
    return module.ApplicationHandler(FakeManager(server))


@pytest.fixture
def application():
    return FakeApplication()


@pytest.fixture
def handler(server, monkeypatch, application):
    return build_handler(server, monkeypatch, application)


#--------------------------------------------------------------------------------
# Construction
#--------------------------------------------------------------------------------

def test_construction_sends_only_startup(server, receiver, monkeypatch, application):
    """
    The folded-in bug: upstream's init_api ended with an unsolicited
    argument-less /live/application/get/average_process_usage datagram. Only
    /live/startup may go out at construction now.
    """
    build_handler(server, monkeypatch, application)
    assert receiver.drain() == [(STARTUP, ())]


def test_class_identifier_is_application(handler):
    #--------------------------------------------------------------------------------
    # Not cosmetic: it is the second segment of every listener push address
    # this handler sends.
    #--------------------------------------------------------------------------------
    assert handler.class_identifier == "application"


#--------------------------------------------------------------------------------
# Generic-loop scalar reads
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("prop, value", [
    ("open_dialog_count", 2),
    ("current_dialog_message", "Save changes to your set?"),
    ("current_dialog_button_count", 3),
    ("peak_process_usage", 0.5),
    ("number_of_push_apps_running", 1),
])
def test_generic_get_replies_with_the_value_alone(server, receiver, monkeypatch,
                                                  prop, value):
    application = FakeApplication(**{prop: value})
    build_handler(server, monkeypatch, application)
    receiver.drain()

    address = "/live/application/get/%s" % prop
    dispatch(server, address)
    assert receiver.drain() == [(address, (value,))]


#--------------------------------------------------------------------------------
# Version identity
#--------------------------------------------------------------------------------

#--------------------------------------------------------------------------------
# /live/application/get/version is deliberately absent from this table.
# Upstream's get_version callback is kept byte-identical, and it reaches Live
# directly (`Live.Application.get_application()` inside the callback) rather
# than through the fork's seam — so under the empty Live stub it answers with
# a structured /live/error, not (12, 4). Routing it through the seam would
# make it testable at the cost of editing upstream code for no behavioural
# gain; the fork's own four version reads below are what this item adds, and
# they are covered.
#--------------------------------------------------------------------------------
@pytest.mark.parametrize("address, expected", [
    ("/live/application/get/bugfix_version", (3,)),
    ("/live/application/get/build_id", ("2026-01-01_abcdef0",)),
    ("/live/application/get/variant", ("Suite",)),
    ("/live/application/get/version_string", ("12.4.3",)),
])
def test_version_reads(server, receiver, handler, address, expected):
    receiver.drain()
    dispatch(server, address)
    assert receiver.drain() == [(address, expected)]


#--------------------------------------------------------------------------------
# has_option
#--------------------------------------------------------------------------------

def test_has_option_echoes_the_option_it_was_asked_about(server, receiver, monkeypatch):
    #--------------------------------------------------------------------------------
    # The echo is the only discriminator on this address: a client firing a
    # burst of has_option requests has nothing else to correlate replies
    # against.
    #--------------------------------------------------------------------------------
    application = FakeApplication(options=("-_EnableFoo",))
    build_handler(server, monkeypatch, application)
    receiver.drain()

    dispatch(server, "/live/application/get/has_option", "-_EnableFoo")
    assert receiver.drain() == [("/live/application/get/has_option",
                                 ("-_EnableFoo", True))]

    dispatch(server, "/live/application/get/has_option", "-_NoSuchOption")
    assert receiver.drain() == [("/live/application/get/has_option",
                                 ("-_NoSuchOption", False))]


def test_has_option_passes_the_string_to_live_unmodified(server, receiver,
                                                         monkeypatch):
    application = FakeApplication()
    build_handler(server, monkeypatch, application)
    receiver.drain()

    dispatch(server, "/live/application/get/has_option", "-_SomeOption")
    assert application.has_option_calls == ["-_SomeOption"]


def test_has_option_with_no_argument_is_a_structured_error(server, receiver, handler):
    """
    params[0] raises IndexError, which OSCServer._dispatch turns into the
    documented ("request", address, detail, argc, *args) envelope rather than
    a malformed reply or silence.
    """
    receiver.drain()
    dispatch(server, "/live/application/get/has_option")

    messages = receiver.drain()
    assert len(messages) == 1
    address, params = messages[0]
    assert address == ERROR
    assert params[0] == "request"
    assert params[1] == "/live/application/get/has_option"
    assert isinstance(params[2], str) and len(params[2]) > 0
    assert params[3] == 0


#--------------------------------------------------------------------------------
# The two flattened list reads
#--------------------------------------------------------------------------------

def test_unavailable_features_is_flat_and_stringified(server, receiver, monkeypatch):
    #--------------------------------------------------------------------------------
    # str() runs unconditionally, so the reply is well-formed whether Live
    # hands back strings or enum-like objects. The second element here is not
    # a string, and must still arrive as one.
    #--------------------------------------------------------------------------------
    class Feature:
        def __str__(self):
            return "MaxForLive"

    application = FakeApplication(unavailable_features=("Sampler", Feature()))
    build_handler(server, monkeypatch, application)
    receiver.drain()

    dispatch(server, "/live/application/get/unavailable_features")
    assert receiver.drain() == [("/live/application/get/unavailable_features",
                                 ("Sampler", "MaxForLive"))]


def test_unavailable_features_empty_replies_with_no_arguments(server, receiver, handler):
    #--------------------------------------------------------------------------------
    # An empty tuple is still a reply: the datagram goes out with zero
    # arguments, so a waiting client is answered rather than left to time out.
    #--------------------------------------------------------------------------------
    receiver.drain()
    dispatch(server, "/live/application/get/unavailable_features")
    assert receiver.drain() == [("/live/application/get/unavailable_features", ())]


def test_control_surfaces_reply_is_class_names(server, receiver, monkeypatch):
    application = FakeApplication(control_surfaces=(AbletonOSC(), Push2()))
    build_handler(server, monkeypatch, application)
    receiver.drain()

    dispatch(server, "/live/application/get/control_surfaces")
    assert receiver.drain() == [("/live/application/get/control_surfaces",
                                 ("AbletonOSC", "Push2"))]


def test_control_surfaces_empty_slot_keeps_its_position(server, receiver, monkeypatch):
    #--------------------------------------------------------------------------------
    # The list mirrors the preferences slots in order, so an unassigned slot
    # goes out as "" rather than being dropped — dropping it would silently
    # renumber every slot after it.
    #--------------------------------------------------------------------------------
    application = FakeApplication(control_surfaces=(AbletonOSC(), None, Push2()))
    build_handler(server, monkeypatch, application)
    receiver.drain()

    dispatch(server, "/live/application/get/control_surfaces")
    assert receiver.drain() == [("/live/application/get/control_surfaces",
                                 ("AbletonOSC", "", "Push2"))]


#--------------------------------------------------------------------------------
# The message methods
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("address, attribute", [
    ("/live/application/show_message", "show_message_calls"),
    ("/live/application/show_on_the_fly_message", "show_on_the_fly_message_calls"),
])
def test_show_message_passes_exactly_one_argument(server, receiver, monkeypatch,
                                                  address, attribute):
    """
    The OK-only guarantee. Live's `buttons` parameter defaults to
    OK_BUTTON, and it stays defaulted because the call passes the text and
    nothing else — press_current_dialog_button is deliberately not on the
    wire, so a dialog with choices would be unanswerable from the remote.
    """
    application = FakeApplication(show_message_result=7)
    build_handler(server, monkeypatch, application)
    receiver.drain()

    dispatch(server, address, "hello")

    assert getattr(application, attribute) == [(("hello",), {})]
    assert receiver.drain() == [(address, (7,))]


#--------------------------------------------------------------------------------
# Listen pairs — the two observable members only
#--------------------------------------------------------------------------------

def test_start_listen_pushes_immediately_and_on_change(server, receiver, monkeypatch):
    application = FakeApplication(open_dialog_count=0)
    build_handler(server, monkeypatch, application)
    receiver.drain()

    dispatch(server, "/live/application/start_listen/open_dialog_count")
    assert len(application.open_dialog_count_listeners) == 1
    #--------------------------------------------------------------------------------
    # The initial push is part of the base _start_listen contract: a client
    # learns the current value without a separate get.
    #--------------------------------------------------------------------------------
    assert receiver.drain() == [("/live/application/get/open_dialog_count", (0,))]

    application.set_open_dialog_count(1)
    assert receiver.drain() == [("/live/application/get/open_dialog_count", (1,))]


def test_stop_listen_unbinds_and_silences_pushes(server, receiver, monkeypatch):
    application = FakeApplication(open_dialog_count=0)
    handler = build_handler(server, monkeypatch, application)
    receiver.drain()

    dispatch(server, "/live/application/start_listen/open_dialog_count")
    receiver.drain()

    dispatch(server, "/live/application/stop_listen/open_dialog_count")
    assert application.open_dialog_count_listeners == []
    assert handler.listener_functions == {}

    application.set_open_dialog_count(1)
    assert receiver.drain() == []


def test_clear_api_clears_listener_bookkeeping(server, receiver, monkeypatch):
    application = FakeApplication()
    handler = build_handler(server, monkeypatch, application)
    receiver.drain()

    dispatch(server, "/live/application/start_listen/open_dialog_count")
    dispatch(server, "/live/application/start_listen/peak_process_usage")
    receiver.drain()
    assert len(handler.listener_functions) == 2

    handler.clear_api()
    assert handler.listener_functions == {}
    assert handler.listener_objects == {}
    assert application.open_dialog_count_listeners == []
    assert application.peak_process_usage_listeners == []


@pytest.mark.parametrize("prop", ["current_dialog_message",
                                  "current_dialog_button_count",
                                  "number_of_push_apps_running",
                                  "unavailable_features",
                                  "control_surfaces"])
def test_no_listen_pair_for_unobservable_or_static_members(server, receiver,
                                                           handler, prop):
    """
    Live offers no add_<name>_listener for the two current_dialog_* members
    or for number_of_push_apps_running, and the two list reads are
    session-static, so no listen pair is registered for any of them.

    An unregistered address is *dropped*: OSCServer.process_message's final
    else logs "Unknown OSC address" and returns, with no datagram at all —
    so the assertion is silence, not a /live/error. (A wildcard request would
    behave differently; this is a literal address.)
    """
    receiver.drain()
    dispatch(server, "/live/application/start_listen/%s" % prop)
    assert receiver.drain() == []
