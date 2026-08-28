"""
`_start_listen(..., lom_property=...)`: subscribe to one LOM property, push
under another name.

The Seshat extension behind /live/view/start_listen/selected_track_identity.
`Song.View` has one observable property, `selected_track`, but two OSC
addresses need to observe it and push different values —
`start_listen/selected_track` its regular-track index (or -1), and
`start_listen/selected_track_identity` the (category, index) pair. Upstream's
`_start_listen` derives three things from `prop`: the bookkeeping key, the
push address, and the `add_%s_listener` accessor name. Aliasing splits the
third off from the first two.

These drive the real `AbletonOSCHandler` and the real `OSCServer`, using the
same Probe pattern as test_handler_lifecycle.py — the aliasing lives in the
base class, so nothing here needs view.py at all. (view.py *is* loadable and
driven, in test_view_object_reads.py; the Probe is still the right subject
for the alias itself, which no handler-specific fake can make clearer.)
"""

import pytest

from .conftest import load_handler_module


@pytest.fixture
def handler_module():
    return load_handler_module()


class FakeManager:
    def __init__(self, osc_server):
        self.osc_server = osc_server


class FakeSongView:
    """
    A `Song.View` stand-in: one observable property, `selected_track`, and
    the add_/remove_ pair named after it. Deliberately has **no**
    `add_selected_track_identity_listener`, so an implementation that
    forgot the alias fails with AttributeError rather than passing.
    """

    def __init__(self, selected_track=("track", 0)):
        self.selected_track = selected_track
        self.listeners = []

    def add_selected_track_listener(self, function):
        self.listeners.append(function)

    def remove_selected_track_listener(self, function):
        self.listeners.remove(function)


def make_handler(handler_module, server, identifier="view"):
    class Probe(handler_module.AbletonOSCHandler):
        class_identifier = identifier

    return Probe(FakeManager(server))


def identity_getter(target):
    """Stands in for view.py's get_selected_track_identity."""
    return lambda params=(): target.selected_track


def index_getter(target):
    """Stands in for view.py's get_selected_track (the -1 sentinel version)."""
    def getter(params=()):
        category, index = target.selected_track
        return (index if category == "track" else -1,)
    return getter


#--------------------------------------------------------------------------------
# 1. The alias routes the subscription without moving the key or the address
#--------------------------------------------------------------------------------

def test_alias_subscribes_to_the_lom_property_and_pushes_under_the_public_name(
        handler_module, server, receiver):
    handler = make_handler(handler_module, server)
    target = FakeSongView(("return_track", 1))

    handler._start_listen(target, "selected_track_identity",
                          getter=identity_getter(target),
                          lom_property="selected_track")

    #--------------------------------------------------------------------------------
    # Bound to add_selected_track_listener — the only add_ method the fake has.
    #--------------------------------------------------------------------------------
    assert len(target.listeners) == 1

    key = ("selected_track_identity", ())
    assert handler.listener_functions[key] is target.listeners[0]
    assert handler.listener_objects[key] is target
    assert handler.listener_lom_properties[key] == "selected_track"

    #--------------------------------------------------------------------------------
    # The immediate push goes out on the *public* name's address.
    #--------------------------------------------------------------------------------
    assert receiver.drain() == [
        ("/live/view/get/selected_track_identity", ("return_track", 1))
    ]


def test_alias_pushes_on_change(handler_module, server, receiver):
    handler = make_handler(handler_module, server)
    target = FakeSongView(("track", 0))

    handler._start_listen(target, "selected_track_identity",
                          getter=identity_getter(target),
                          lom_property="selected_track")
    receiver.drain()

    target.selected_track = ("master", 0)
    target.listeners[0]()

    assert receiver.drain() == [
        ("/live/view/get/selected_track_identity", ("master", 0))
    ]


def test_alias_restarts_rather_than_stacking(handler_module, server, receiver):
    handler = make_handler(handler_module, server)
    target = FakeSongView()

    handler._start_listen(target, "selected_track_identity",
                          getter=identity_getter(target),
                          lom_property="selected_track")
    handler._start_listen(target, "selected_track_identity",
                          getter=identity_getter(target),
                          lom_property="selected_track")
    receiver.drain()

    #--------------------------------------------------------------------------------
    # The restart path runs _stop_listen, which must resolve the LOM name from
    # the stored mapping or raise looking for remove_selected_track_identity_listener.
    #--------------------------------------------------------------------------------
    assert len(target.listeners) == 1
    key = ("selected_track_identity", ())
    assert handler.listener_functions[key] is target.listeners[0]


def test_stop_listen_uses_the_public_name_and_clears_all_three_dicts(
        handler_module, server, receiver):
    handler = make_handler(handler_module, server)
    target = FakeSongView()

    handler._start_listen(target, "selected_track_identity",
                          getter=identity_getter(target),
                          lom_property="selected_track")
    receiver.drain()

    #--------------------------------------------------------------------------------
    # The stop_listen registration in view.py is a partial over the public
    # name only — it never learns the LOM name.
    #--------------------------------------------------------------------------------
    handler._stop_listen(target, "selected_track_identity")

    assert target.listeners == []
    assert handler.listener_functions == {}
    assert handler.listener_objects == {}
    assert handler.listener_lom_properties == {}


def test_clear_listeners_unbinds_an_aliased_listener(handler_module, server, receiver):
    """
    The reload path. `_clear_listeners` reconstructs (prop, params) from the
    key alone, so an alias passed only as an argument would be lost here and
    every /live/api/reload would leave the identity listener bound forever,
    still pushing after the handler that owns it is gone.
    """
    handler = make_handler(handler_module, server)
    target = FakeSongView()

    handler._start_listen(target, "selected_track_identity",
                          getter=identity_getter(target),
                          lom_property="selected_track")
    receiver.drain()

    handler.clear_api()

    assert target.listeners == []
    assert handler.listener_functions == {}
    assert handler.listener_objects == {}
    assert handler.listener_lom_properties == {}


#--------------------------------------------------------------------------------
# 2. Coexistence: two OSC listeners over one observable property
#--------------------------------------------------------------------------------

def test_both_listeners_coexist_on_one_lom_property(handler_module, server, receiver):
    handler = make_handler(handler_module, server)
    target = FakeSongView(("track", 2))

    handler._start_listen(target, "selected_track", getter=index_getter(target))
    handler._start_listen(target, "selected_track_identity",
                          getter=identity_getter(target),
                          lom_property="selected_track")
    receiver.drain()

    #--------------------------------------------------------------------------------
    # Two distinct keys, two distinct callbacks, one LOM property.
    #--------------------------------------------------------------------------------
    assert len(target.listeners) == 2
    assert set(handler.listener_functions.keys()) == {
        ("selected_track", ()), ("selected_track_identity", ()),
    }

    target.selected_track = ("return_track", 0)
    for listener in list(target.listeners):
        listener()

    assert receiver.drain() == [
        ("/live/view/get/selected_track", (-1,)),
        ("/live/view/get/selected_track_identity", ("return_track", 0)),
    ]


def test_stopping_one_leaves_the_other_subscribed(handler_module, server, receiver):
    handler = make_handler(handler_module, server)
    target = FakeSongView()

    handler._start_listen(target, "selected_track", getter=index_getter(target))
    handler._start_listen(target, "selected_track_identity",
                          getter=identity_getter(target),
                          lom_property="selected_track")
    receiver.drain()

    handler._stop_listen(target, "selected_track")

    assert list(handler.listener_functions.keys()) == [("selected_track_identity", ())]
    assert handler.listener_lom_properties == {("selected_track_identity", ()): "selected_track"}
    assert len(target.listeners) == 1
    assert target.listeners[0] is handler.listener_functions[("selected_track_identity", ())]


#--------------------------------------------------------------------------------
# 3. The unaliased default is unchanged
#--------------------------------------------------------------------------------

def test_default_records_the_property_as_its_own_lom_name(handler_module, server, receiver):
    handler = make_handler(handler_module, server)
    target = FakeSongView()

    handler._start_listen(target, "selected_track", getter=index_getter(target))
    receiver.drain()

    key = ("selected_track", ())
    assert handler.listener_lom_properties[key] == "selected_track"
    assert len(target.listeners) == 1

    handler._stop_listen(target, "selected_track")
    assert target.listeners == []
    assert handler.listener_lom_properties == {}


def test_stop_listen_falls_back_to_the_property_name_without_a_recorded_alias(
        handler_module, server, receiver):
    """
    A stale key with no entry in listener_lom_properties — the state a
    pre-alias listener dict would be in after a partial reload — must behave
    exactly as it did before aliasing existed: derive the remove_ name from
    `prop`.
    """
    handler = make_handler(handler_module, server)
    target = FakeSongView()

    handler._start_listen(target, "selected_track", getter=index_getter(target))
    receiver.drain()
    del handler.listener_lom_properties[("selected_track", ())]

    handler._stop_listen(target, "selected_track")

    assert target.listeners == []
    assert handler.listener_functions == {}


def test_unknown_property_still_warns_and_does_nothing(handler_module, server, receiver):
    handler = make_handler(handler_module, server)
    target = FakeSongView()

    handler._stop_listen(target, "selected_track_identity")

    assert target.listeners == []
    assert handler.listener_functions == {}
    assert handler.listener_lom_properties == {}
