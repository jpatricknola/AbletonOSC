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

One narrow exception to "no Live stubs": load_handler_module() installs a
minimal ableton.v2.control_surface.component before importing the real
handler.py. handler.py's only Live-side dependency is that trivial base
class — it imports no Live module, calls Component with no arguments and
uses none of its behaviour — so a stub whose Component.__init__ accepts and
ignores everything makes the real base class testable without pretending to
be Live. Nothing else stubs anything: osc_server.py and track_callback.py
are imported exactly as they ship, and the stub is only installed when a
test actually calls load_handler_module(). Most production *subclasses*
(track.py, song.py, ...) import Live itself at module scope and stay out of
reach until that is addressed separately — but device.py does not (it
imports only typing and .handler), so load_device_module() can construct
the real DeviceHandler on top of the same Component stub and drive it end
to end; test_device_listeners.py does exactly that.

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
            with no arguments and uses nothing it provides.
            """

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
    — only `typing` and `.handler` — so once load_handler_module() has put
    the Component stub in place, the production DeviceHandler can be
    constructed and dispatched against outside Live. Local fakes stand in
    for the LOM objects its callbacks reach through `self.song`.
    """
    load_handler_module()
    return load_module("abletonosc.device")


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
