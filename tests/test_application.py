import threading

from . import client, wait_one_tick, TICK_DURATION

#--------------------------------------------------------------------------------
# Test generic application features
#--------------------------------------------------------------------------------

def capture_after_send(client, address, send, timeout=TICK_DURATION):
    """
    Install a capture handler for `address` *before* calling `send`, so a
    reply that arrives faster than a subsequent await_message() could
    subscribe is not lost. Local to the live-integration tests; a shared
    harness home is issue #6's call.
    """
    rv = None
    _event = threading.Event()

    def received_response(address, params):
        nonlocal rv
        rv = params
        _event.set()

    client.set_handler(address, received_response)
    try:
        send()
        if not _event.wait(timeout):
            raise RuntimeError("No response received on: %s" % address)
    finally:
        client.remove_handler(address)
    return rv

def test_application_test(client):
    assert client.query("/live/test")

def test_application_get_version(client):
    rv = client.query("/live/application/get/version")
    assert len(rv) == 2 and rv[0] in (11, 12)

def test_application_error(client):
    response = capture_after_send(
        client, "/live/error",
        lambda: client.send_message("/live/clip/get/color", (0, 10)))
    assert response[0] == "request"
    assert response[1] == "/live/clip/get/color"
    # The human-readable detail: assert presence, not exact wording, so the
    # test does not re-stale when messages improve.
    assert isinstance(response[2], str) and len(response[2]) > 0
    assert response[3] == 2
    assert response[4:] == (0, 10)
