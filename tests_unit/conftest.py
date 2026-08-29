"""
Fixtures for driving OSCServer.process_message without Ableton Live.

Importing the production module is the delicate part. osc_server.py does
`from ..pythonosc...`, so it must be imported as a subpackage of a root
package that also contains pythonosc/. In production that root is the
Remote Script directory itself, but its __init__.py — and
abletonosc/__init__.py — import Live-only modules (ableton.v2, Live), and
the repository directory name "ableton-osc" is not a Python identifier
anyway. So this file builds a synthetic root package whose __path__ is the
repository root, imports pythonosc beneath it normally (its __init__.py is
empty), and inserts a namespace-style abletonosc subpackage whose
__init__.py is never executed. The production module's relative imports
then resolve unchanged, with no rewriting.

There are two narrow exceptions to "no Live stubs", both import-only shims
that pretend to no Live *behaviour* whatsoever:

1. load_handler_module() installs a minimal
   ableton.v2.control_surface.component before importing the real
   handler.py. handler.py's only Live-side dependency is that trivial base
   class — it imports no Live module, calls Component with no arguments and
   uses none of its behaviour — so a stub whose Component.__init__ accepts
   and ignores everything makes the real base class testable without
   pretending to be Live. The stub carries one piece of Live's real shape
   deliberately: a `song` attribute (see the class docstring), because a
   handler may read `self.song` at *registration* time.
2. _install_empty_live_stub() installs an *empty* module as
   sys.modules["Live"] for the four loaders whose module does `import Live`
   at module scope. Three of them dereference it only inside a callback, at
   call time: clip.py (Live.Clip.MidiNoteSpecification in clip_add_notes and
   make_note_specification), song.py (Live.Track.Track in get/track_data)
   and view.py (Live.Application.get_application() in show_view /
   get/is_view_visible / hide_view). An empty module satisfies the import,
   and a test that dispatched one of those addresses without arranging for
   the attribute would fail loudly on the missing name rather than quietly
   exercising a fake Live.

   test_clip_notes.py is the one test module that dispatches such an
   address — the two /live/clip/add/notes{,_extended} forms. It supplies
   the missing name the way test_application.py supplies its application
   object: `monkeypatch.setattr(sys.modules["Live"], "Clip", ns,
   raising=False)` for the duration of a test, carrying a recording
   MidiNoteSpecification. monkeypatch deletes the attribute again at
   teardown, so the stub is empty again for every other test, and the
   fake is visible only to the tests that asked for it. Nothing else in
   the suite dispatches a Live-dereferencing address.

   application.py is the fourth, and the one exception to "only inside a
   callback": it needs the application object at *registration* time, to
   bind into the partial()s of its generic property loop. It reaches it
   through the module-level seam `abletonosc.application.get_application()`,
   which test_application.py monkeypatches with a fake before constructing
   the handler — the application-object image of bind_song() below. So the
   Live stub stays empty here too: the seam is what carries the fake, and
   `Live.Application` is never dereferenced under test. A merge that
   inlined `Live.Application.get_application()` back into init_api would
   fail loudly on the empty stub rather than pass quietly.

Nothing else stubs anything: osc_server.py and track_callback.py are
imported exactly as they ship, and each stub is only installed when a test
actually calls the loader that needs it. device.py, scene.py, clip_slot.py,
track.py, return_track.py and groove.py import only
logging/typing/functools/.handler and the Live-free .track_callback /
.track_identity / .path_safety, so load_device_module(), load_scene_module(),
load_clip_slot_module(), load_track_module(), load_return_track_module() and
load_groove_module() construct the real handlers on top of the
Component stub alone; load_clip_module(), load_song_module(),
load_view_module() and load_application_module() add the empty Live stub.
Ten of the thirteen production handlers are therefore driven end to end
(device, scene, clip_slot, track, return_track, groove, clip, song, view,
application); browser.py, midimap.py and song_structure.py have no loader
yet, because nothing has needed one.

path_safety.py — the read-side import rule that clip_slot.py, track.py and
device.py all `from`-import — needs no loader and no stub at all: it imports
only os and typing, so a bare load_module("abletonosc.path_safety") reaches
it, which is what tests_unit/test_path_safety.py drives it through as a plain
function. Its presence in those three modules' import lists therefore does not
change the "no Live stub needed" conclusion for any of their loaders.

test_import.py smoke-tests the loader so it cannot fail only when the
first real dispatcher test is collected.
"""

import importlib
import socket
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ROOT_PACKAGE = "abletonosc_under_test"


def load_module(name: str):
    """
    Import `name` (e.g. "abletonosc.osc_server") beneath the synthetic root
    package, creating the root on first use.
    """
    if ROOT_PACKAGE not in sys.modules:
        root = types.ModuleType(ROOT_PACKAGE)
        root.__path__ = [str(REPO_ROOT)]
        sys.modules[ROOT_PACKAGE] = root

        # pythonosc/ imports normally: its __init__.py is empty.
        importlib.import_module(ROOT_PACKAGE + ".pythonosc")

        # abletonosc/ must not execute its __init__.py (it imports every
        # handler, and the handlers import Live). A bare module with a
        # __path__ makes the directory importable as a package without
        # running any of it.
        abletonosc = types.ModuleType(ROOT_PACKAGE + ".abletonosc")
        abletonosc.__path__ = [str(REPO_ROOT / "abletonosc")]
        sys.modules[ROOT_PACKAGE + ".abletonosc"] = abletonosc
        root.abletonosc = abletonosc

    return importlib.import_module(ROOT_PACKAGE + "." + name)


def load_osc_server_module():
    return load_module("abletonosc.osc_server")


def load_handler_module():
    """
    Import the real `abletonosc.handler` beneath the synthetic root, after
    installing the minimal `ableton.v2.control_surface.component` stub it
    needs (see the module docstring for why that is safe).

    The stub is process-global for the rest of the pytest run, but it shadows
    nothing importable outside Live, and no other module in this suite touches
    the `ableton` namespace.
    """
    if "ableton.v2.control_surface.component" not in sys.modules:
        class Component:
            """
            Stands in for ableton.v2's Component. The real one takes
            (name=None, parent=None, register_component=None, song=None,
            layer=None, is_enabled=True, *a, **k); AbletonOSCHandler calls it
            with no arguments and uses nothing it provides *except* `song`.

            `song` is modelled because handlers read it at registration time.
            In Live 12.4.3's ableton/v2/control_surface/component.py the
            constructor's `song=` argument is stored as `self._song` and
            `Component.song` is a read-only property over it; AbletonOSCHandler
            calls `super().__init__()` with no arguments, so the value is
            supplied instead by the `ControlSurface.component_guard()` block
            that manager.py constructs every handler inside. Either way the
            song is available from the first line of init_state()/init_api(),
            which SongHandler and ViewHandler rely on: they bind `self.song`
            and `self.song.view` into partial()s while the constructor is
            still running.

            The stub keeps `song` a plain class attribute defaulting to None
            rather than a read-only property, deliberately: every existing
            fixture in this suite assigns `handler.song = FakeSong(...)`
            *after* construction, which the real property would forbid. Tests
            that need the Live-accurate "already set when init_api() runs"
            guarantee use bind_song() below. The constructor takes no `song=`
            on purpose: AbletonOSCHandler calls `super().__init__()` bare, so
            such a kwarg could never be reached and would only invite a reader
            to assume it is the tested mechanism.
            """

            song = None

            def __init__(self, *args, **kwargs):
                pass

        component = types.ModuleType("ableton.v2.control_surface.component")
        component.Component = Component

        control_surface = types.ModuleType("ableton.v2.control_surface")
        control_surface.__path__ = []
        control_surface.Component = Component
        control_surface.component = component

        v2 = types.ModuleType("ableton.v2")
        v2.__path__ = []
        v2.control_surface = control_surface

        ableton = types.ModuleType("ableton")
        ableton.__path__ = []
        ableton.v2 = v2

        sys.modules["ableton"] = ableton
        sys.modules["ableton.v2"] = v2
        sys.modules["ableton.v2.control_surface"] = control_surface
        sys.modules["ableton.v2.control_surface.component"] = component

    return load_module("abletonosc.handler")


def load_device_module():
    """
    Import the real `abletonosc.device` beneath the synthetic root.

    Unlike the other handler subclasses, device.py imports nothing from Live
    — only `typing`, `.handler` and the Live-free `.path_safety` (os +
    typing, for /live/device/replace_sample's import rule) — so once
    load_handler_module() has put the Component stub in place, the production
    DeviceHandler can be constructed and dispatched against outside Live.
    Local fakes stand in for the LOM objects its callbacks reach through
    `self.song`.
    """
    load_handler_module()
    return load_module("abletonosc.device")


def load_scene_module():
    """
    Import the real `abletonosc.scene` beneath the synthetic root. Like
    device.py it imports nothing from Live — only typing, functools and
    .handler — so no stub beyond Component is needed.
    """
    load_handler_module()
    return load_module("abletonosc.scene")


def load_groove_module():
    """
    Import the real `abletonosc.groove` beneath the synthetic root. Like
    scene.py it imports nothing from Live — only logging, typing and .handler
    — so no stub beyond Component is needed.

    The module also carries the Live-free pool resolvers (`resolve_groove`,
    `groove_index`, `groove_pool_dump`, `GROOVE_FIELDS`) that song.py and
    clip.py `from`-import, so this loader is what test_groove.py drives them
    through as plain functions as well as through the handler.
    """
    load_handler_module()
    return load_module("abletonosc.groove")


def load_clip_slot_module():
    """
    Import the real `abletonosc.clip_slot` beneath the synthetic root. Like
    device.py it imports nothing from Live — only typing, .handler and the
    Live-free .path_safety (os + typing, for
    /live/clip_slot/create_audio_clip's import rule).
    """
    load_handler_module()
    return load_module("abletonosc.clip_slot")


def load_track_module():
    """
    Import the real `abletonosc.track` beneath the synthetic root. Like
    device.py it imports nothing from Live — only typing, .handler,
    .track_callback, .track_identity and .path_safety — so no stub beyond
    Component is needed.

    Note that constructing `TrackHandler` registers its entire address table
    (getters, setters, methods and both listen pairs, for every property in
    its loops) on the server it is passed, so a test that builds one gets the
    production dispatch surface, not a hand-picked subset.
    """
    load_handler_module()
    return load_module("abletonosc.track")


def load_return_track_module():
    """
    Import the real `abletonosc.return_track` beneath the synthetic root.
    Like device.py it imports nothing from Live — only typing, functools and
    .handler — so no stub beyond Component is needed.

    `ReturnTrackHandler.init_api` registers its whole address table (the
    return-indexed and master forms of every scalar, routing, send and device
    address) but touches `self.song` only from callbacks, so the
    post-construction `handler.song = FakeSong(...)` pattern is enough here;
    bind_song() is not needed.
    """
    load_handler_module()
    return load_module("abletonosc.return_track")


def _install_empty_live_stub():
    """
    Install an empty module as sys.modules["Live"], for the loaders whose
    production module does `import Live` at module scope but dereferences it
    only inside a callback, at call time (see the module docstring).

    Guarded like the Component stub, and installed only when one of those
    loaders is called. `sys.modules` is process-global for the whole pytest
    session, though, so once installed the stub is visible to every test
    collected afterwards, not just ones that call such a loader —
    test_import.py's test_abletonosc_package_init_never_executed accounts for
    that by tolerating a `Live` module in sys.modules as long as it carries no
    `__file__` (a real Live module, loaded from disk, always would).
    """
    if "Live" not in sys.modules:
        sys.modules["Live"] = types.ModuleType("Live")


def load_clip_module():
    """
    Import the real `abletonosc.clip` beneath the synthetic root, over the
    empty `Live` stub: clip.py's only dereference is
    Live.Clip.MidiNoteSpecification, at call time, inside clip_add_notes and
    the module-level make_note_specification that clip_add_notes_extended
    uses. test_clip_notes.py dispatches both of those addresses, and
    monkeypatches a `Clip` namespace onto the stub for the tests that do
    (see the module docstring); the stub itself stays empty.
    """
    load_handler_module()
    _install_empty_live_stub()
    return load_module("abletonosc.clip")


def load_song_module():
    """
    Import the real `abletonosc.song` beneath the synthetic root, over the
    empty `Live` stub: song.py's only dereference is Live.Track.Track, inside
    song_get_track_data (/live/song/get/track_data) at call time, and no test
    in this suite dispatches that address. Its other module-scope imports —
    os, sys, tempfile, json — are stdlib.

    `SongHandler.init_api` binds `self.song` into a partial() for every
    property, method and listener it registers, so the song must already be
    on the instance when the constructor runs: build the handler through
    bind_song(), not by assigning `handler.song` afterwards.
    """
    load_handler_module()
    _install_empty_live_stub()
    return load_module("abletonosc.song")


def load_view_module():
    """
    Import the real `abletonosc.view` beneath the synthetic root, over the
    empty `Live` stub: view.py's only dereferences are
    Live.Application.get_application() inside show_view, get_is_view_visible
    and hide_view, all at call time, and no test in this suite dispatches
    those addresses.

    `ViewHandler.init_api` binds `self.song.view` into its four listen
    registrations during construction, so — as for load_song_module() — the
    handler must be built through bind_song().
    """
    load_handler_module()
    _install_empty_live_stub()
    return load_module("abletonosc.view")


def load_application_module():
    """
    Import the real `abletonosc.application` beneath the synthetic root, over
    the empty `Live` stub.

    application.py's module-scope needs are Live, os, functools, typing and
    .handler — all satisfied — but unlike the other empty-stub loaders it
    reaches the Live application object at *registration* time, not only from
    a callback. It does so through the module-level `get_application()` seam,
    so a test substitutes the fake there:

        application = load_application_module()
        monkeypatch.setattr(application, "get_application", lambda: fake)
        handler = application.ApplicationHandler(manager)

    which keeps the Live stub empty (see the module docstring). Constructing
    the handler registers its whole address table on the server the manager
    carries, and — like the production script — sends `/live/startup`.
    """
    load_handler_module()
    _install_empty_live_stub()
    return load_module("abletonosc.application")


def bind_song(handler_class, song):
    """
    Return a subclass of `handler_class` whose `song` is `song` from the
    first line of init_state()/init_api().

    The Live-free image of `ControlSurface.component_guard()`, which is what
    supplies a real Component's song before any handler code runs. A class
    attribute is the mechanism because there is no earlier hook: the
    AbletonOSCHandler constructor registers the whole address table, so an
    instance assignment can only ever happen too late. Each call makes its
    own subclass, so nothing is process-global and two tests cannot see each
    other's song.

    `class_identifier` is inherited unchanged, so listener pushes still go out
    on /live/song/... and /live/view/... . test_handler_subclass_contract.py
    parses abletonosc/*.py only, so a test-side subclass does not trip its
    "no subclass __init__" checks.
    """
    return type(handler_class.__name__ + "BoundToSong", (handler_class,), {"song": song})


class Receiver:
    """
    A plain UDP socket standing in for the OSC client, plus a helper that
    drains and decodes everything the server sent to it.
    """

    #--------------------------------------------------------------------------------
    # process_message is synchronous and send() is a direct sendto over
    # loopback, so replies are normally queued before dispatch() returns.
    # The deadline only bounds how long a test that expects nothing waits
    # before concluding nothing was sent.
    #--------------------------------------------------------------------------------
    FIRST_DEADLINE = 0.25
    DRAIN_DEADLINE = 0.05

    def __init__(self):
        self._osc_message = load_module("pythonosc.osc_message")
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(("127.0.0.1", 0))
        self.port = self.socket.getsockname()[1]

    def drain(self):
        """
        Return [(address, params_tuple), ...] for every datagram received,
        in arrival order, waiting at most FIRST_DEADLINE for the first one.
        """
        messages = []
        deadline = self.FIRST_DEADLINE
        while True:
            self.socket.settimeout(deadline)
            try:
                data, _ = self.socket.recvfrom(65536)
            except socket.timeout:
                return messages
            message = self._osc_message.OscMessage(data)
            messages.append((message.address, tuple(message.params)))
            deadline = self.DRAIN_DEADLINE

    def close(self):
        self.socket.close()


@pytest.fixture
def receiver():
    r = Receiver()
    yield r
    r.close()


@pytest.fixture
def server(receiver):
    osc_server = load_osc_server_module()
    s = osc_server.OSCServer(local_addr=("127.0.0.1", 0),
                             remote_addr=("127.0.0.1", receiver.port))
    yield s
    s.shutdown()


def dispatch(server, address, *args):
    """
    Build an OSC datagram for (address, args) and feed it straight into
    server.process_message, the way parse_bundle would.
    """
    builder_module = load_module("pythonosc.osc_message_builder")
    message_module = load_module("pythonosc.osc_message")
    builder = builder_module.OscMessageBuilder(address)
    for arg in args:
        builder.add_arg(arg)
    message = message_module.OscMessage(builder.build().dgram)
    # Only the hostname half of the sender address is used for replies;
    # the server always answers on its configured response port.
    server.process_message(message, ("127.0.0.1", 0))
