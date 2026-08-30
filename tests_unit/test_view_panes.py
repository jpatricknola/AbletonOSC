"""
The four `Application.View` pane addresses, dispatched end to end through the
real `ViewHandler`:

  /live/view/show_view          /live/view/hide_view
  /live/view/focus_view         /live/view/get/is_view_visible

These shipped untested. Not for want of care: `Live` is an empty stub in this
suite, so an address that dereferences `Live.Application.get_application()` was
simply unreachable here, and both `conftest.load_view_module` and
`test_view_object_reads` said so. `conftest.install_application` is what
changed — it hands one test an application and takes it away again — so the
addresses are testable now, and the docstrings that claimed nothing dispatches
them no longer hold.

Two contracts are worth pinning, and neither is visible from the diff that
added these handlers:

**`show_view` and `focus_view` are different methods.** FORK_GAPS dismissed
`focus_view` for months as overlapping `show_view`; it does not — `show_view`
makes a pane visible, `focus_view` gives it keyboard focus, and Live's
menu-command validation reads the second (measured 2026-08-30). A regression
that wired either address to the other method would be invisible on the wire,
because all three steering addresses are silent. `RecordingApplicationView`
records which method was called, so it is not invisible here.

**The steering three are silent even when Live raises.** A bad view name is
logged to `Log.txt` and *nothing* goes out — in particular not a `/live/error`.
That is deliberate: a steer must never fail the tool it follows. Asserting the
absence of `/live/error` is the point; a future "improvement" that let the
exception reach `_dispatch` would break every Seshat tool that ends by showing
what it changed.

`get/is_view_visible` is the exception and follows the fork's *getter* rule:
it always replies, in the two-channel envelope, echoing the name it was asked
about, so silence keeps meaning only "this extension is not installed".
"""

import logging

import pytest

from .conftest import bind_song, dispatch, install_application, load_view_module

SHOW_VIEW = "/live/view/show_view"
HIDE_VIEW = "/live/view/hide_view"
FOCUS_VIEW = "/live/view/focus_view"
IS_VIEW_VISIBLE = "/live/view/get/is_view_visible"

#--------------------------------------------------------------------------------
# view.py's VIEW_NAMES, duplicated deliberately rather than imported: this is
# the wire contract API.md documents, and a test that imports the tuple it is
# checking would pass just as happily after someone edited it.
#--------------------------------------------------------------------------------
DOCUMENTED_VIEW_NAMES = ("Browser", "Arranger", "Session",
                         "Detail", "Detail/Clip", "Detail/DeviceChain")


class FakeManager:
    def __init__(self, osc_server):
        self.osc_server = osc_server


class FakeTrackView:
    def __init__(self):
        self.selected_device = None


class FakeTrack:
    def __init__(self, name):
        self.name = name
        self.devices = []
        self.clip_slots = []
        self.view = FakeTrackView()


class FakeSongView:
    def __init__(self):
        self.selected_track = None
        self.selected_scene = None
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
    def __init__(self):
        self.tracks = [FakeTrack("drums")]
        self.return_tracks = [FakeTrack("A Reverb")]
        self.master_track = FakeTrack("master")
        self.scenes = []
        self.view = FakeSongView()


class RecordingApplicationView:
    """
    Records `(method_name, argument)` for every call, which is what makes
    "show_view and focus_view are not the same method" an assertable claim.
    """

    def __init__(self, visible=True):
        self.calls = []
        self._visible = visible

    def show_view(self, name):
        self.calls.append(("show_view", name))

    def hide_view(self, name):
        self.calls.append(("hide_view", name))

    def focus_view(self, name):
        self.calls.append(("focus_view", name))

    def is_view_visible(self, name):
        self.calls.append(("is_view_visible", name))
        return self._visible


class RefusingApplicationView:
    """Live's behaviour on a name it does not recognise: it raises."""

    def __init__(self, message="invalid view name"):
        self.message = message

    def _refuse(self, name):
        raise RuntimeError("%s: %r" % (self.message, name))

    show_view = _refuse
    hide_view = _refuse
    focus_view = _refuse
    is_view_visible = _refuse


@pytest.fixture
def view_handler(server):
    handler_class = bind_song(load_view_module().ViewHandler, FakeSong())
    return handler_class(FakeManager(server))


#--------------------------------------------------------------------------------
# Registration
#--------------------------------------------------------------------------------

def test_all_four_addresses_are_registered(view_handler, server):
    for address in (SHOW_VIEW, HIDE_VIEW, FOCUS_VIEW, IS_VIEW_VISIBLE):
        assert address in server._callbacks


#--------------------------------------------------------------------------------
# The three steering addresses: each calls its own method, and stays silent
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("address, method", [(SHOW_VIEW, "show_view"),
                                             (HIDE_VIEW, "hide_view"),
                                             (FOCUS_VIEW, "focus_view")])
def test_each_steering_address_calls_its_own_live_method(view_handler, server, receiver,
                                                         monkeypatch, address, method):
    """
    The regression guard for #27's whole point: `focus_view` is not a synonym
    for `show_view`. Wiring either address to the other method changes nothing
    observable on the wire — all three are silent — so the call record is the
    only place it can be caught.
    """
    application_view = install_application(monkeypatch, RecordingApplicationView())

    dispatch(server, address, "Session")

    assert application_view.calls == [(method, "Session")]
    assert receiver.drain() == []


@pytest.mark.parametrize("address", [SHOW_VIEW, HIDE_VIEW, FOCUS_VIEW])
@pytest.mark.parametrize("view_name", DOCUMENTED_VIEW_NAMES)
def test_every_documented_name_is_passed_through_verbatim(view_handler, server, receiver,
                                                          monkeypatch, address, view_name):
    """
    The handler does not validate or map names — Live does. `VIEW_NAMES` exists
    only to name the candidates in a log line, so a name reaching Live altered
    would be a fork-side bug invisible to a client.
    """
    application_view = install_application(monkeypatch, RecordingApplicationView())

    dispatch(server, address, view_name)

    assert application_view.calls[0][1] == view_name
    assert receiver.drain() == []


@pytest.mark.parametrize("address", [SHOW_VIEW, HIDE_VIEW, FOCUS_VIEW])
def test_a_refused_name_is_logged_and_never_reaches_the_wire(view_handler, server,
                                                             receiver, monkeypatch,
                                                             caplog, address):
    """
    The silent-setter contract, and the reason it is not simply an oversight:
    a steer must never fail the tool it follows. Letting the exception reach
    `_dispatch` would turn every mistyped pane name into a `/live/error` that a
    client correlating its in-flight request would read as *that request*
    failing.
    """
    install_application(monkeypatch, RefusingApplicationView())

    with caplog.at_level(logging.ERROR, logger="abletonosc"):
        dispatch(server, address, "NotAView")

    assert receiver.drain() == []
    assert any("NotAView" in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize("address, method", [(SHOW_VIEW, "show_view"),
                                             (HIDE_VIEW, "hide_view"),
                                             (FOCUS_VIEW, "focus_view")])
def test_a_missing_argument_becomes_the_empty_name(view_handler, server, receiver,
                                                   monkeypatch, address, method):
    """
    `str(params[0]) if len(params) > 0 else ""` — an argument-less steer is
    handed to Live as `""` rather than raising an IndexError, so it fails the
    same silent way a bad name does.
    """
    application_view = install_application(monkeypatch, RecordingApplicationView())

    dispatch(server, address)

    assert application_view.calls == [(method, "")]
    assert receiver.drain() == []


@pytest.mark.parametrize("address, method", [(SHOW_VIEW, "show_view"),
                                             (HIDE_VIEW, "hide_view"),
                                             (FOCUS_VIEW, "focus_view")])
def test_a_non_string_argument_is_coerced(view_handler, server, receiver,
                                          monkeypatch, address, method):
    """
    OSC clients send ints and floats where a string is meant. `str()` keeps
    that a Live-side rejection — logged and silent — rather than a TypeError
    escaping into `/live/error`.
    """
    application_view = install_application(monkeypatch, RecordingApplicationView())

    dispatch(server, address, 3)

    assert application_view.calls == [(method, "3")]
    assert receiver.drain() == []


#--------------------------------------------------------------------------------
# get/is_view_visible — the getter rule
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("visible, expected", [(True, 1), (False, 0)])
def test_visibility_answers_the_echoed_ok_envelope(view_handler, server, receiver,
                                                   monkeypatch, visible, expected):
    """
    The name is echoed so a client can correlate, and the boolean goes out as
    1/0 like every other AbletonOSC boolean — never Python's True/False.
    """
    install_application(monkeypatch, RecordingApplicationView(visible=visible))

    dispatch(server, IS_VIEW_VISIBLE, "Session")
    replies = receiver.drain()

    assert replies == [(IS_VIEW_VISIBLE, ("Session", "ok", expected))]
    assert isinstance(replies[0][1][2], int)
    assert not isinstance(replies[0][1][2], bool)


def test_a_refused_name_answers_on_the_error_channel(view_handler, server, receiver,
                                                     monkeypatch):
    """
    The getter rule, not the silent-setter rule. Live raises on an unrecognised
    name here — unlike `show_view`, which ignores one — so this arm is
    reachable, and it costs a client a fast reply instead of a guard timeout.
    Crucially it is *not* a `/live/error`: the envelope is the answer.
    """
    install_application(monkeypatch, RefusingApplicationView())

    dispatch(server, IS_VIEW_VISIBLE, "NotAView")
    replies = receiver.drain()

    assert len(replies) == 1
    address, params = replies[0]
    assert address == IS_VIEW_VISIBLE
    assert params[0] == "NotAView"
    assert params[1] == "error"
    assert "NotAView" in params[2]


def test_visibility_replies_even_with_no_argument(view_handler, server, receiver,
                                                  monkeypatch):
    """
    Silence must keep meaning exactly one thing — this extension is not
    installed — so even a malformed request gets an answer.
    """
    install_application(monkeypatch, RecordingApplicationView(visible=False))

    dispatch(server, IS_VIEW_VISIBLE)

    assert receiver.drain() == [(IS_VIEW_VISIBLE, ("", "ok", 0))]
