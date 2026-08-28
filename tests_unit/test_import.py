"""
Smoke tests for conftest's module loader, so a loader regression fails
here by name rather than as collateral damage in the dispatcher tests.
"""

import sys

from .conftest import (ROOT_PACKAGE, load_handler_module, load_module,
                       load_osc_server_module, load_song_module,
                       load_view_module)


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
    #--------------------------------------------------------------------------------
    # No *real* Live-side module may be imported by anything in this suite.
    # "ableton" and "Live" can each legitimately be present: load_handler_module()
    # installs a synthetic stub of ableton.v2.control_surface.component so the
    # real handler.py base class can be constructed, and the clip/song/view
    # loaders (used by other tests in the same session) install an empty
    # "Live" stub so those modules' module-scope `import Live` resolves
    # (see conftest._install_empty_live_stub).
    # Real modules are loaded from Live's Remote Scripts directory and carry
    # a __file__; the stubs are bare ModuleType instances and do not.
    #--------------------------------------------------------------------------------
    for name, module in list(sys.modules.items()):
        if name == "ableton" or name.startswith("ableton.") or name == "Live" or name.startswith("Live."):
            assert not hasattr(module, "__file__"), \
                "real Live module imported into tests_unit: %s" % name


def test_handler_module_imports_over_the_component_stub():
    module = load_handler_module()
    assert hasattr(module, "AbletonOSCHandler")
    #--------------------------------------------------------------------------------
    # The real handler.py, not a replica: it still subclasses whatever
    # ableton.v2 supplied, which under the stub is a no-op base.
    #--------------------------------------------------------------------------------
    assert module.__name__ == ROOT_PACKAGE + ".abletonosc.handler"
    assert module.AbletonOSCHandler.class_identifier is None


def test_song_module_imports_over_the_live_stub():
    #--------------------------------------------------------------------------------
    # song.py does `import Live` at module scope but dereferences it only
    # inside get/track_data, at call time, so the empty stub is enough to
    # reach the real module. The behavioural cover is
    # test_song_object_reads.py.
    #--------------------------------------------------------------------------------
    module = load_song_module()
    assert module.__name__ == ROOT_PACKAGE + ".abletonosc.song"
    assert hasattr(module, "SongHandler")


def test_view_module_imports_over_the_live_stub():
    module = load_view_module()
    assert module.__name__ == ROOT_PACKAGE + ".abletonosc.view"
    assert hasattr(module, "ViewHandler")


def test_component_stub_carries_a_song_attribute():
    #--------------------------------------------------------------------------------
    # SongHandler and ViewHandler read self.song while init_api() is still
    # registering addresses, so `song` must exist on the base class before
    # any instance assignment could happen. Live's Component has it as a
    # read-only property fed by component_guard(); the stub keeps it a plain
    # attribute so the suite's post-construction `handler.song = ...`
    # fixtures still work. bind_song() is the accurate path.
    #
    # This reads a process-global: it holds because every fixture sets `song`
    # on an instance or, via bind_song(), on a per-test subclass — never on
    # the base class. A fixture that did `AbletonOSCHandler.song = ...` would
    # make this fail order-dependently; that is the tripwire, not a flake.
    #--------------------------------------------------------------------------------
    module = load_handler_module()
    assert module.AbletonOSCHandler.song is None
    assert "song" not in vars(module.AbletonOSCHandler)


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
