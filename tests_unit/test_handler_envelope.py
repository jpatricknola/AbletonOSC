"""
Regression tests for the dispatch/error-boundary rework: failures in the generic method/property
paths reach the dispatcher boundary and come back as one correlated
/live/error ("request", ...) envelope, without aborting the rest of the
bundle or the tick's queue.

AbletonOSCHandler itself imports ableton.v2 and cannot be constructed
outside Live, so these tests register callbacks with the exact shape the
new _set_property/_call_method have — a bare setattr/method call with no
local try/except — and prove the boundary handles what now propagates.
The per-boundary behavior for arbitrary exceptions is already pinned by
test_osc_server.py; this file pins the setter-style failure end to end
and the PR #208 resilience properties (bundles and queued datagrams
survive a failing generic method).
"""

from .conftest import dispatch, load_module


class RejectingTarget:
    """Stands in for a LOM object that rejects a property assignment."""

    @property
    def tempo(self):
        return 120.0

    @tempo.setter
    def tempo(self, value):
        raise RuntimeError("Value out of range")


def set_property_style_callback(target, prop):
    # The exact shape of AbletonOSCHandler._set_property after the dispatch-boundary rework:
    # log-free here for brevity, no try/except, setattr propagates.
    def callback(params):
        setattr(target, prop, params[0])
    return callback


def test_setter_failure_produces_correlated_envelope(server, receiver):
    server.add_handler("/live/song/set/tempo",
                       set_property_style_callback(RejectingTarget(), "tempo"))
    dispatch(server, "/live/song/set/tempo", 999)
    messages = receiver.drain()
    assert [address for address, _ in messages] == ["/live/error"]
    error = messages[0][1]
    assert error[0] == "request"
    assert error[1] == "/live/song/set/tempo"
    assert "Value out of range" in error[2]
    assert error[3] == 1
    assert error[4:] == (999,)


def build_bundle_dgram(messages):
    builder_module = load_module("pythonosc.osc_message_builder")
    bundle_module = load_module("pythonosc.osc_bundle_builder")
    bundle_builder = bundle_module.OscBundleBuilder(bundle_module.IMMEDIATELY)
    for address, params in messages:
        message_builder = builder_module.OscMessageBuilder(address)
        for param in params:
            message_builder.add_arg(param)
        bundle_builder.add_content(message_builder.build())
    return bundle_builder.build().dgram


def failing_method_callback(params):
    # The shape of _call_method after the dispatch-boundary rework: the method call propagates.
    raise RuntimeError("Invalid track index")


def test_bundle_continues_past_failing_generic_method(server, receiver):
    server.add_handler("/live/song/delete_track", failing_method_callback)
    server.add_handler("/live/song/get/tempo", lambda params: (120.0,))
    dgram = build_bundle_dgram([("/live/song/delete_track", (99,)),
                                ("/live/song/get/tempo", ())])
    server.parse_bundle(dgram, ("127.0.0.1", 0))
    messages = receiver.drain()
    errors = [params for address, params in messages if address == "/live/error"]
    assert len(errors) == 1
    assert errors[0][0] == "request"
    assert errors[0][1] == "/live/song/delete_track"
    # The later message in the same bundle still ran.
    assert ("/live/song/get/tempo", (120.0,)) in messages


def test_queued_datagrams_continue_past_failing_generic_method(server, receiver):
    server.add_handler("/live/song/delete_track", failing_method_callback)
    server.add_handler("/live/song/get/tempo", lambda params: (120.0,))

    builder_module = load_module("pythonosc.osc_message_builder")
    import socket
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        server_addr = server._socket.getsockname()
        failing = builder_module.OscMessageBuilder("/live/song/delete_track")
        failing.add_arg(99)
        sender.sendto(failing.build().dgram, server_addr)
        sender.sendto(builder_module.OscMessageBuilder("/live/song/get/tempo").build().dgram,
                      server_addr)

        # Loopback delivery is effectively immediate, but the server socket
        # is non-blocking: retry process() until both datagrams have been
        # picked up and answered.
        import time
        messages = []
        deadline = time.time() + 1.0
        while time.time() < deadline and len(messages) < 2:
            server.process()
            messages += receiver.drain()
        errors = [params for address, params in messages if address == "/live/error"]
        assert len(errors) == 1
        assert errors[0][1] == "/live/song/delete_track"
        assert ("/live/song/get/tempo", (120.0,)) in messages
    finally:
        sender.close()
