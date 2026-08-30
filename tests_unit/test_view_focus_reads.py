"""
The two reads added for focus verification, dispatched end to end through the
real `ViewHandler`:

  /live/view/get/focused_document_view      + its start_/stop_listen pair
  /live/view/get/highlighted_clip_slot
  /live/view/set/highlighted_clip_slot

`focused_document_view` is the one member in view.py whose subject is
`Application.View` rather than `Song.View`, and the empty `Live` stub is what
makes that interesting here. view.py's contract with this suite is that every
`Live.Application` dereference happens at *call* time, never at registration
time — `test_constructing_the_handler_never_touches_live` is that contract
asserted directly, and the rest of the focused_document_view tests supply the
application object the way test_clip_notes.py supplies `Live.Clip`:
monkeypatching the attribute onto the stub for the duration of one test.

`highlighted_clip_slot` is an object-valued read in the A-4 sense, so what is
pinned here is only the glue — the addresses as registered, the reply arity,
the int-ness of the coordinate, the none-pair, and the *absence* of a listen
pair. The resolver matrix underneath is test_track_identity.py's.
"""

import sys

import pytest

from .conftest import bind_song, dispatch, load_view_module

FOCUSED_DOCUMENT_VIEW = "/live/view/get/focused_document_view"
START_LISTEN_FOCUSED = "/live/view/start_listen/focused_document_view"
STOP_LISTEN_FOCUSED = "/live/view/stop_listen/focused_document_view"
GET_HIGHLIGHTED = "/live/view/get/highlighted_clip_slot"
SET_HIGHLIGHTED = "/live/view/set/highlighted_clip_slot"


class FakeManager:
    """`osc_server` is the only attribute AbletonOSCHandler reads off it."""

    def __init__(self, osc_server):
        self.osc_server = osc_server


class FakeClipSlot:
    def __init__(self, canonical_parent=None):
        self.canonical_parent = canonical_parent


class FakeTrackView:
    def __init__(self):
        self.selected_device = None


class FakeTrack:
    def __init__(self, name, scene_count=0):
        self.name = name
        self.devices = []
        self.view = FakeTrackView()
        self.clip_slots = [FakeClipSlot(canonical_parent=self)
                           for _ in range(scene_count)]


class FakeSongView:
    """
    Carries `highlighted_clip_slot` plus the two upstream listen pairs
    ViewHandler registers against `song.view` during construction.
    """

    def __init__(self):
        self.selected_track = None
        self.selected_scene = None
        self.selected_chain = None
        self.selected_parameter = None
        self.mod_mapping_device = None
        self.mod_mapping_parameter = None
        self.highlighted_clip_slot = None
        self.listeners = {"selected_track": [], "selected_scene": []}

    def add_selected_track_listener(self, callback):
        self.listeners["selected_track"].append(callback)

    def remove_selected_track_listener(self, callback):
        self.listeners["selected_track"].remove(callback)

    def add_selected_scene_listener(self, callback):
        self.listeners["selected_scene"].append(callback)

    def remove_selected_scene_listener(self, callback):
        self.listeners["selected_scene"].remove(callback)


class FakeSong:
    def __init__(self, tracks, return_tracks, master_track, scenes=()):
        self.tracks = list(tracks)
        self.return_tracks = list(return_tracks)
        self.master_track = master_track
        self.scenes = list(scenes)
        self.view = FakeSongView()


class FakeApplicationView:
    """
    The `Application.View` half. `focused_document_view` is read-only in the
    LOM; `set_document_view` here is a test affordance, not a fork address.
    """

    def __init__(self, focused_document_view="Session"):
        self.focused_document_view = focused_document_view
        self.listeners = []

    def add_focused_document_view_listener(self, callback):
        self.listeners.append(callback)

    def remove_focused_document_view_listener(self, callback):
        self.listeners.remove(callback)

    def set_document_view(self, name):
        self.focused_document_view = name
        for callback in list(self.listeners):
            callback()


def install_application(monkeypatch, application_view):
    """
    Supply `Live.Application.get_application()` on the empty stub for the
    duration of one test, the way test_clip_notes.py supplies `Live.Clip`.
    monkeypatch removes the attribute at teardown, so the stub is empty again
    for every other test in the suite.
    """
    import types

    application = types.SimpleNamespace(view=application_view)
    namespace = types.SimpleNamespace(get_application=lambda: application)
    monkeypatch.setattr(sys.modules["Live"], "Application", namespace, raising=False)
    return application_view


def build_song():
    drums = FakeTrack("drums", scene_count=3)
    bass = FakeTrack("bass", scene_count=3)
    returns = FakeTrack("A Reverb", scene_count=3)
    master = FakeTrack("master", scene_count=3)
    return FakeSong([drums, bass], [returns], master)


def errors(messages):
    return [params for address, params in messages if address == "/live/error"]


@pytest.fixture
def song():
    return build_song()


@pytest.fixture
def view_handler(server, song):
    handler_class = bind_song(load_view_module().ViewHandler, song)
    return handler_class(FakeManager(server))


#--------------------------------------------------------------------------------
# Registration, and the Live-free construction contract
#--------------------------------------------------------------------------------

def test_all_five_addresses_are_registered(view_handler, server):
    for address in (FOCUSED_DOCUMENT_VIEW, START_LISTEN_FOCUSED, STOP_LISTEN_FOCUSED,
                    GET_HIGHLIGHTED, SET_HIGHLIGHTED):
        assert address in server._callbacks


def test_constructing_the_handler_never_touches_live(view_handler):
    """
    The regression guard for view.py's contract with this suite: the
    focused_document_view listen pair resolves `Live.Application` inside its
    handler, not in a partial() bound during init_api. If a later change binds
    the application view at registration time instead, `view_handler` raises
    AttributeError on the empty stub and this fails loudly — which is the
    whole point of the stub being empty.

    The fixture having been constructed at all is the assertion; the explicit
    check is that nothing put `Application` on the stub as a side effect.
    """
    assert not hasattr(sys.modules["Live"], "Application")


def test_highlighted_clip_slot_has_no_listen_pair(view_handler, server):
    """
    Not observable — the generated inventory's obs column is empty for it, so
    an add_highlighted_clip_slot_listener would not bind. The absence is the
    contract.
    """
    assert "/live/view/start_listen/highlighted_clip_slot" not in server._callbacks
    assert "/live/view/stop_listen/highlighted_clip_slot" not in server._callbacks


#--------------------------------------------------------------------------------
# get/focused_document_view — the two channels
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["Session", "Arranger"])
def test_answers_ok_and_the_document_view_name(view_handler, server, receiver,
                                               monkeypatch, name):
    """The acceptance case, both values Live can return."""
    install_application(monkeypatch, FakeApplicationView(name))

    dispatch(server, FOCUSED_DOCUMENT_VIEW)
    assert receiver.drain() == [(FOCUSED_DOCUMENT_VIEW, ("ok", name))]


def test_a_read_that_raises_answers_on_the_error_channel(view_handler, server,
                                                         receiver, monkeypatch):
    """
    The getter rule, not the silent-setter rule: a caller waits on this, so a
    failure must arrive as an answer rather than as silence. Silence has to
    keep meaning exactly one thing — this extension is not installed.
    """
    class Exploding:
        @property
        def focused_document_view(self):
            raise RuntimeError("no document open")

    install_application(monkeypatch, Exploding())

    dispatch(server, FOCUSED_DOCUMENT_VIEW)
    replies = receiver.drain()
    assert len(replies) == 1
    address, params = replies[0]
    assert address == FOCUSED_DOCUMENT_VIEW
    assert params[0] == "error"
    assert "no document open" in params[1]
    assert errors(replies) == []


def test_the_name_goes_on_the_wire_as_a_string(view_handler, server, receiver,
                                               monkeypatch):
    install_application(monkeypatch, FakeApplicationView("Arranger"))

    dispatch(server, FOCUSED_DOCUMENT_VIEW)
    (_, params), = receiver.drain()
    assert all(isinstance(value, str) for value in params)


#--------------------------------------------------------------------------------
# The Application.View listen pair
#--------------------------------------------------------------------------------

def test_start_listen_binds_to_application_view_and_pushes_immediately(
        view_handler, server, receiver, monkeypatch):
    application_view = install_application(monkeypatch, FakeApplicationView("Session"))

    dispatch(server, START_LISTEN_FOCUSED)
    assert len(application_view.listeners) == 1
    assert receiver.drain() == [(FOCUSED_DOCUMENT_VIEW, ("ok", "Session"))]


def test_the_listener_pushes_the_envelope_on_the_get_address(
        view_handler, server, receiver, monkeypatch):
    application_view = install_application(monkeypatch, FakeApplicationView("Session"))

    dispatch(server, START_LISTEN_FOCUSED)
    receiver.drain()

    application_view.set_document_view("Arranger")
    assert receiver.drain() == [(FOCUSED_DOCUMENT_VIEW, ("ok", "Arranger"))]


def test_stop_listen_unbinds_from_application_view(view_handler, server, receiver,
                                                   monkeypatch):
    application_view = install_application(monkeypatch, FakeApplicationView("Session"))

    dispatch(server, START_LISTEN_FOCUSED)
    receiver.drain()
    dispatch(server, STOP_LISTEN_FOCUSED)

    assert application_view.listeners == []
    application_view.set_document_view("Arranger")
    assert receiver.drain() == []


#--------------------------------------------------------------------------------
# get/highlighted_clip_slot
#--------------------------------------------------------------------------------

def test_none_answers_the_none_pair(view_handler, server, receiver, song):
    """
    Live documents the member as None for the Main and Send tracks. That is
    the none-pair, not an error.
    """
    song.view.highlighted_clip_slot = None

    dispatch(server, GET_HIGHLIGHTED)
    assert receiver.drain() == [(GET_HIGHLIGHTED, (-1, -1))]


def test_a_slot_answers_its_track_and_scene_coordinate(view_handler, server,
                                                       receiver, song):
    song.view.highlighted_clip_slot = song.tracks[1].clip_slots[2]

    dispatch(server, GET_HIGHLIGHTED)
    assert receiver.drain() == [(GET_HIGHLIGHTED, (1, 2))]


def test_the_coordinate_goes_on_the_wire_as_ints(view_handler, server, receiver, song):
    song.view.highlighted_clip_slot = song.tracks[0].clip_slots[1]

    dispatch(server, GET_HIGHLIGHTED)
    (_, params), = receiver.drain()
    assert all(isinstance(value, int) for value in params)


def test_a_return_track_slot_answers_the_none_pair(view_handler, server, receiver, song):
    """
    Not a state Live is expected to produce — the member is documented None
    for Send tracks — but no (track, scene) coordinate reaches a return track
    slot, so rule 3's "not representable" -1 is the honest answer rather than
    an index into the wrong collection.
    """
    song.view.highlighted_clip_slot = song.return_tracks[0].clip_slots[1]

    dispatch(server, GET_HIGHLIGHTED)
    assert receiver.drain() == [(GET_HIGHLIGHTED, (-1, -1))]


def test_an_unresolvable_slot_arrives_as_a_structured_error(view_handler, server,
                                                            receiver, song):
    """
    A slot belonging to no track of this song cannot be named, and the ascent
    raising is the loud failure track_identity.py intends — a /live/error, not
    a malformed reply.
    """
    song.view.highlighted_clip_slot = FakeClipSlot(canonical_parent=None)

    dispatch(server, GET_HIGHLIGHTED)
    replies = receiver.drain()
    assert [address for address, _ in replies] == ["/live/error"]
    assert errors(replies)


#--------------------------------------------------------------------------------
# set/highlighted_clip_slot
#--------------------------------------------------------------------------------

def test_the_setter_writes_the_slot_and_replies_with_nothing(view_handler, server,
                                                             receiver, song):
    dispatch(server, SET_HIGHLIGHTED, 1, 2)

    assert song.view.highlighted_clip_slot is song.tracks[1].clip_slots[2]
    assert receiver.drain() == []


def test_the_setter_round_trips_through_the_getter(view_handler, server, receiver, song):
    dispatch(server, SET_HIGHLIGHTED, 0, 1)
    receiver.drain()

    dispatch(server, GET_HIGHLIGHTED)
    assert receiver.drain() == [(GET_HIGHLIGHTED, (0, 1))]


@pytest.mark.parametrize("track_index, scene_index", [(9, 0), (0, 9)])
def test_a_bad_index_arrives_as_a_structured_error(view_handler, server, receiver,
                                                   song, track_index, scene_index):
    """
    Unguarded on purpose, like upstream's set/selected_* — this is not one of
    view.py's silent setters, so a bad index comes back as a "request" error
    rather than being logged and dropped.
    """
    dispatch(server, SET_HIGHLIGHTED, track_index, scene_index)

    replies = receiver.drain()
    assert [address for address, _ in replies] == ["/live/error"]
    assert song.view.highlighted_clip_slot is None
