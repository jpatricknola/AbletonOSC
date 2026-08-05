"""
Smoke tests for conftest's module loader, so a loader regression fails
here by name rather than as collateral damage in the dispatcher tests.
"""

import sys

from .conftest import ROOT_PACKAGE, load_module, load_osc_server_module


def test_osc_server_module_imports():
    module = load_osc_server_module()
    assert hasattr(module, "OSCServer")


def test_relative_imports_resolved_within_synthetic_root():
    load_osc_server_module()
    assert (ROOT_PACKAGE + ".pythonosc.osc_message") in sys.modules
    assert (ROOT_PACKAGE + ".abletonosc.constants") in sys.modules


def test_abletonosc_package_init_never_executed():
    #--------------------------------------------------------------------------------
    # abletonosc/__init__.py imports every handler, and the handlers import
    # Live-only modules. The loader must expose the package without running
    # it: the namespace module carries none of the names the real
    # __init__.py defines.
    #--------------------------------------------------------------------------------
    load_osc_server_module()
    package = sys.modules[ROOT_PACKAGE + ".abletonosc"]
    assert not hasattr(package, "SongHandler")
    assert "ableton" not in sys.modules
    assert "Live" not in sys.modules


def test_server_starts_on_ephemeral_port(server):
    local_hostname, local_port = server._local_addr
    assert local_hostname == "127.0.0.1"
    # Constructed with port 0; the OS picked an ephemeral one. The bound
    # socket, not _local_addr, is what proves no fixed port was taken.
    assert server._socket.getsockname()[1] != 0


def test_dispatch_and_receiver_round_trip(server, receiver):
    from .conftest import dispatch
    server.add_handler("/scaffold/echo", lambda params: tuple(params))
    dispatch(server, "/scaffold/echo", 7, "hello")
    assert receiver.drain() == [("/scaffold/echo", (7, "hello"))]
