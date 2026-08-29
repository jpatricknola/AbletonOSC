"""
Lifecycle contract of AbletonOSCHandler, the base class every OSC handler
in this fork inherits from.

Upstream's constructor called init_api() *before* creating
listener_functions, listener_objects and class_identifier, so route
registration ran against a half-built object: the invariant that every
listener push address depends on ("/live/<class_identifier>/get/<prop>")
held only by the accident that no init_api() body happened to read it at
registration time. These tests pin the corrected order so a merge or a
refactor that reverts it fails here rather than silently, in Live, months
later.

This is the first file to construct the *real* AbletonOSCHandler outside
Live. It is possible because handler.py's only Live-side dependency is a
trivial base class, stubbed by conftest.load_handler_module(); the OSCServer
and the dispatcher underneath these tests are the production ones. Nine of
the twelve production subclasses are loaded and driven end to end elsewhere
in the suite (device, scene, clip_slot, track, return_track, clip, song,
view, application — see test_device_listeners.py, test_listener_identity.py,
test_object_reads.py, test_return_track.py, test_song_object_reads.py,
test_view_object_reads.py and test_application.py); browser.py, midimap.py
and song_structure.py have no conftest loader yet, so the probes below stand
in for them.

What the probes cannot reach — the *declarations* of all twelve production
subclasses: each one's class_identifier value, and the absence of a subclass
__init__ or any self.class_identifier assignment — is pinned statically,
without imports, by test_handler_subclass_contract.py.
"""

import pytest

from .conftest import dispatch, load_handler_module


@pytest.fixture
def handler_module():
    return load_handler_module()


class FakeManager:
    """`osc_server` is the only attribute AbletonOSCHandler reads off it."""

    def __init__(self, osc_server):
        self.osc_server = osc_server


class FakeTarget:
    """
    A LOM-object stand-in for the listener paths: the add_/remove_ naming
    convention _start_listen/_stop_listen build their getattr calls from.
    """

    def __init__(self, x=1):
        self.x = x
        self.listeners = []

    def add_x_listener(self, function):
        self.listeners.append(function)

    def remove_x_listener(self, function):
        self.listeners.remove(function)


#--------------------------------------------------------------------------------
# 1. Base invariants exist before init_api() runs
#--------------------------------------------------------------------------------

MISSING = "MISSING"


def test_invariants_are_set_before_init_api(handler_module, server):
    seen = {}

    class Probe(handler_module.AbletonOSCHandler):
        class_identifier = "probe"

        def init_api(self):
            for name in ("listener_functions", "listener_objects",
                         "class_identifier", "osc_server", "manager", "logger"):
                seen[name] = getattr(self, name, MISSING)

    manager = FakeManager(server)
    Probe(manager)

    assert seen["listener_functions"] == {}
    assert seen["listener_objects"] == {}
    #--------------------------------------------------------------------------------
    # The subclass's own identifier, not None: upstream's base assigned
    # class_identifier = None *after* init_api(), so registration saw either
    # no attribute at all or, later, the clobbered None.
    #--------------------------------------------------------------------------------
    assert seen["class_identifier"] == "probe"
    assert seen["osc_server"] is server
    assert seen["manager"] is manager
    assert seen["logger"] is not MISSING and seen["logger"] is not None


def test_identifier_is_not_clobbered_after_construction(handler_module, server):
    class Probe(handler_module.AbletonOSCHandler):
        class_identifier = "probe"

    handler = Probe(FakeManager(server))
    assert handler.class_identifier == "probe"
    assert "class_identifier" not in handler.__dict__


def test_base_identifier_defaults_to_none(handler_module, server):
    handler = handler_module.AbletonOSCHandler(FakeManager(server))
    assert handler.class_identifier is None
    assert handler.listener_functions == {}
    assert handler.listener_objects == {}


#--------------------------------------------------------------------------------
# 2. init_state() runs after the invariants and strictly before init_api()
#--------------------------------------------------------------------------------

def test_init_state_runs_between_invariants_and_init_api(handler_module, server):
    events = []

    class Probe(handler_module.AbletonOSCHandler):
        class_identifier = "probe"

        def init_state(self):
            events.append(("init_state",
                           hasattr(self, "listener_functions"),
                           hasattr(self, "listener_objects"),
                           hasattr(self, "osc_server"),
                           self.class_identifier))
            self.token = "from init_state"

        def init_api(self):
            events.append(("init_api", getattr(self, "token", MISSING)))

    Probe(FakeManager(server))

    assert events == [
        ("init_state", True, True, True, "probe"),
        ("init_api", "from init_state"),
    ]


def test_init_state_is_an_optional_no_op(handler_module, server):
    """A subclass that needs no state overrides nothing and still builds."""

    class Probe(handler_module.AbletonOSCHandler):
        class_identifier = "probe"

        def init_api(self):
            self.registered = True

    assert Probe(FakeManager(server)).registered is True


#--------------------------------------------------------------------------------
# 3. Registration performed in init_api() reaches the real dispatcher
#--------------------------------------------------------------------------------

def test_route_registered_in_init_api_dispatches(handler_module, server, receiver):
    class Probe(handler_module.AbletonOSCHandler):
        class_identifier = "probe"

        def init_state(self):
            self.greeting = "hello"

        def init_api(self):
            #--------------------------------------------------------------------------------
            # Both halves of the contract in one line: the address is built from
            # the class identifier, and the callback closes over state created
            # in init_state(). Neither was available here before this change.
            #--------------------------------------------------------------------------------
            address = "/live/%s/get/greeting" % self.class_identifier
            self.osc_server.add_handler(address, lambda params: (self.greeting,))

    Probe(FakeManager(server))

    dispatch(server, "/live/probe/get/greeting")
    assert receiver.drain() == [("/live/probe/get/greeting", ("hello",))]


#--------------------------------------------------------------------------------
# 4. Listener bookkeeping against the dicts the constructor now guarantees
#--------------------------------------------------------------------------------

def make_handler(handler_module, server, identifier="probe"):
    class Probe(handler_module.AbletonOSCHandler):
        class_identifier = identifier

    return Probe(FakeManager(server))


def test_start_listen_binds_records_and_pushes(handler_module, server, receiver):
    handler = make_handler(handler_module, server)
    target = FakeTarget(x=7)

    handler._start_listen(target, "x", (0,))

    assert len(target.listeners) == 1
    assert handler.listener_functions[("x", (0,))] is target.listeners[0]
    assert handler.listener_objects[("x", (0,))] is target
    #--------------------------------------------------------------------------------
    # The immediate push carries the params ahead of the value, on the address
    # built from class_identifier.
    #--------------------------------------------------------------------------------
    assert receiver.drain() == [("/live/probe/get/x", (0, 7))]


def test_listener_pushes_on_change(handler_module, server, receiver):
    handler = make_handler(handler_module, server)
    target = FakeTarget(x=1)

    handler._start_listen(target, "x", (0,))
    receiver.drain()

    target.x = 2
    target.listeners[0]()
    assert receiver.drain() == [("/live/probe/get/x", (0, 2))]


def test_stop_listen_unbinds_and_clears(handler_module, server, receiver):
    handler = make_handler(handler_module, server)
    target = FakeTarget()

    handler._start_listen(target, "x", (0,))
    receiver.drain()
    handler._stop_listen(target, "x", (0,))

    assert target.listeners == []
    assert handler.listener_functions == {}
    assert handler.listener_objects == {}


def test_stop_listen_unbinds_from_the_recorded_object(handler_module, server, receiver):
    """
    The fork's _stop_listen fix: indices renumber, so the object handed in on
    unsubscribe need not be the one the callback was bound to. Unbind from the
    object recorded in listener_objects.
    """
    handler = make_handler(handler_module, server)
    bound, handed = FakeTarget(), FakeTarget()

    handler._start_listen(bound, "x", (0,))
    receiver.drain()
    handler._stop_listen(handed, "x", (0,))

    assert bound.listeners == []
    assert handed.listeners == []
    assert handler.listener_functions == {}


def test_clear_listeners_empties_everything(handler_module, server, receiver):
    handler = make_handler(handler_module, server)
    first, second = FakeTarget(), FakeTarget()

    handler._start_listen(first, "x", (0,))
    handler._start_listen(second, "x", (1,))
    receiver.drain()

    handler.clear_api()

    assert first.listeners == []
    assert second.listeners == []
    assert handler.listener_functions == {}
    assert handler.listener_objects == {}


def test_restarting_a_listener_replaces_the_old_binding(handler_module, server, receiver):
    handler = make_handler(handler_module, server)
    target = FakeTarget()

    handler._start_listen(target, "x", (0,))
    handler._start_listen(target, "x", (0,))
    receiver.drain()

    assert len(target.listeners) == 1
    assert handler.listener_functions[("x", (0,))] is target.listeners[0]
