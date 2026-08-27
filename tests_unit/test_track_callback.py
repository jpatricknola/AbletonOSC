"""
The track-index argument wildcard, end to end through the real dispatcher.

These exercise the **production** factory — `abletonosc.track_callback`'s
`create_track_callback`, the same object `TrackHandler.init_api` registers —
loaded through conftest's synthetic-package loader and registered on a real
`OSCServer`. Nothing here replicates the wrapper's shape; the tracks and the
per-track workers are the only fakes, because a real one is a Live object.

The defect these pin: the wildcard branch used to `return` on the first
track that produced a value, so every `/live/track/get/<prop> *` answered for
track 0 alone.
"""

import pytest

from .conftest import dispatch, load_module


@pytest.fixture
def create_track_callback():
    return load_module("abletonosc.track_callback").create_track_callback


class FakeTrack:
    def __init__(self, name):
        self.name = name


@pytest.fixture
def tracks():
    return [FakeTrack("drums"), FakeTrack("bass"), FakeTrack("keys")]


def get_name(track, params=()):
    """A scalar getter, in the shape TrackHandler._get_property replies with."""
    return track.name,


def errors(messages):
    return [params for address, params in messages if address == "/live/error"]


def replies(messages):
    return [m for m in messages if m[0] != "/live/error"]


#--------------------------------------------------------------------------------
# Single-index dispatch — unchanged, and pinned so the repair cannot move it
#--------------------------------------------------------------------------------

def test_single_index_getter_replies_once(server, receiver, tracks,
                                          create_track_callback):
    server.add_handler("/live/track/get/name",
                       create_track_callback(lambda: tracks, get_name))
    dispatch(server, "/live/track/get/name", 1)
    assert receiver.drain() == [("/live/track/get/name", (1, "bass"))]


def test_single_index_out_of_range_is_the_existing_envelope(server, receiver, tracks,
                                                            create_track_callback):
    server.add_handler("/live/track/get/name",
                       create_track_callback(lambda: tracks, get_name))
    dispatch(server, "/live/track/get/name", 99)
    messages = receiver.drain()
    assert replies(messages) == []
    assert len(errors(messages)) == 1
    error = errors(messages)[0]
    assert error[0] == "request"
    assert error[1] == "/live/track/get/name"
    assert "range" in error[2]
    # A single-index failure is not a fan-out failure and must not claim to be.
    assert "wildcard fan-out failed" not in error[2]
    assert error[3] == 1
    assert error[4:] == (99,)


#--------------------------------------------------------------------------------
# Wildcard fan-out
#--------------------------------------------------------------------------------

def test_wildcard_getter_replies_once_per_track_ascending(server, receiver, tracks,
                                                          create_track_callback):
    server.add_handler("/live/track/get/name",
                       create_track_callback(lambda: tracks, get_name))
    dispatch(server, "/live/track/get/name", "*")
    assert receiver.drain() == [("/live/track/get/name", (0, "drums")),
                                ("/live/track/get/name", (1, "bass")),
                                ("/live/track/get/name", (2, "keys"))]


def test_wildcard_getter_visits_every_track_exactly_once(server, receiver, tracks,
                                                         create_track_callback):
    visited = []

    def record(track, params=()):
        visited.append(track.name)
        return track.name,

    server.add_handler("/live/track/get/name",
                       create_track_callback(lambda: tracks, record))
    dispatch(server, "/live/track/get/name", "*")
    receiver.drain()
    assert visited == ["drums", "bass", "keys"]


def test_wildcard_getter_passes_trailing_arguments_through(server, receiver, tracks,
                                                           create_track_callback):
    # send-style: the getter reads a positional argument the request carries
    # after the wildcard.
    def get_send(track, params=()):
        send_id, = params
        return send_id, "%s:%d" % (track.name, send_id)

    server.add_handler("/live/track/get/send",
                       create_track_callback(lambda: tracks, get_send))
    dispatch(server, "/live/track/get/send", "*", 0)
    assert receiver.drain() == [("/live/track/get/send", (0, 0, "drums:0")),
                                ("/live/track/get/send", (1, 0, "bass:0")),
                                ("/live/track/get/send", (2, 0, "keys:0"))]


def test_wildcard_getter_carries_bound_property_argument(server, receiver, tracks,
                                                         create_track_callback):
    # The *args form the property loops use: create_track_callback(f, prop).
    def get_property(track, prop, params=()):
        return getattr(track, prop),

    server.add_handler("/live/track/get/name",
                       create_track_callback(lambda: tracks, get_property, "name"))
    dispatch(server, "/live/track/get/name", "*")
    assert receiver.drain() == [("/live/track/get/name", (0, "drums")),
                                ("/live/track/get/name", (1, "bass")),
                                ("/live/track/get/name", (2, "keys"))]


def test_wildcard_setter_iterates_silently(server, receiver, tracks,
                                           create_track_callback):
    def set_name(track, params=()):
        track.name = params[0]

    server.add_handler("/live/track/set/name",
                       create_track_callback(lambda: tracks, set_name))
    dispatch(server, "/live/track/set/name", "*", "renamed")
    assert receiver.drain() == []
    assert [track.name for track in tracks] == ["renamed"] * 3


def test_wildcard_listener_registration_receives_track_id(server, receiver, tracks,
                                                          create_track_callback):
    seen = []

    def start_listen(track, prop, params=()):
        seen.append((prop, params))

    server.add_handler("/live/track/start_listen/name",
                       create_track_callback(lambda: tracks, start_listen, "name",
                                             include_track_id=True))
    dispatch(server, "/live/track/start_listen/name", "*")
    assert receiver.drain() == []
    assert seen == [("name", (0,)), ("name", (1,)), ("name", (2,))]


def test_wildcard_over_zero_tracks_is_silent(server, receiver, create_track_callback):
    server.add_handler("/live/track/get/name",
                       create_track_callback(lambda: [], get_name))
    dispatch(server, "/live/track/get/name", "*")
    assert receiver.drain() == []


def test_wildcard_over_one_track_replies_once(server, receiver, create_track_callback):
    server.add_handler("/live/track/get/name",
                       create_track_callback(lambda: [FakeTrack("only")], get_name))
    dispatch(server, "/live/track/get/name", "*")
    assert receiver.drain() == [("/live/track/get/name", (0, "only"))]


#--------------------------------------------------------------------------------
# All-or-nothing on error
#--------------------------------------------------------------------------------

def test_wildcard_failure_yields_no_replies_and_one_error(server, receiver, tracks,
                                                          create_track_callback):
    def get_name_failing_on_bass(track, params=()):
        if track.name == "bass":
            raise RuntimeError("LOM said no")
        return track.name,

    server.add_handler("/live/track/get/name",
                       create_track_callback(lambda: tracks,
                                             get_name_failing_on_bass))
    dispatch(server, "/live/track/get/name", "*")
    messages = receiver.drain()
    # Track 0 succeeded before track 1 failed, and must not have been sent.
    assert replies(messages) == []
    assert len(errors(messages)) == 1
    error = errors(messages)[0]
    assert error[0] == "request"
    assert error[1] == "/live/track/get/name"
    assert "wildcard fan-out failed at track 1" in error[2]
    assert "LOM said no" in error[2]
    assert error[3] == 1
    assert error[4:] == ("*",)


def test_wildcard_failure_stops_the_fan_out(server, receiver, tracks,
                                            create_track_callback):
    visited = []

    def failing(track, params=()):
        visited.append(track.name)
        raise RuntimeError("boom")

    server.add_handler("/live/track/get/name",
                       create_track_callback(lambda: tracks, failing))
    dispatch(server, "/live/track/get/name", "*")
    receiver.drain()
    assert visited == ["drums"]


def test_reraise_preserves_the_exception_class(tracks, create_track_callback):
    # The dispatcher's skip/report decision is class-based, so the wrap must
    # not launder a ValueError into a RuntimeError.
    def failing(track, params=()):
        raise ValueError("bad value")

    callback = create_track_callback(lambda: tracks, failing)
    with pytest.raises(ValueError) as excinfo:
        callback(["*"])
    assert "wildcard fan-out failed at track 0" in str(excinfo.value)
    assert "bad value" in str(excinfo.value)


#--------------------------------------------------------------------------------
# Composition with the address wildcard
#--------------------------------------------------------------------------------

def test_address_and_argument_wildcards_compose(server, receiver, tracks,
                                                create_track_callback):
    # /live/track/get/* * — the scalar getter fans out per track; the
    # send-style endpoint, whose worker raises ValueError unpacking the empty
    # params tail, is skipped silently under README § Wildcard queries.
    def get_send(track, params=()):
        send_id, = params
        return send_id, 0.5

    server.add_handler("/live/track/get/name",
                       create_track_callback(lambda: tracks, get_name))
    server.add_handler("/live/track/get/send",
                       create_track_callback(lambda: tracks, get_send))
    dispatch(server, "/live/track/get/*", "*")
    messages = receiver.drain()
    assert errors(messages) == []
    assert sorted(replies(messages)) == [("/live/track/get/name", (0, "drums")),
                                         ("/live/track/get/name", (1, "bass")),
                                         ("/live/track/get/name", (2, "keys"))]


def test_composed_wildcard_reports_a_genuine_failure(server, receiver, tracks,
                                                     create_track_callback):
    def failing(track, params=()):
        raise RuntimeError("boom")

    server.add_handler("/live/track/get/name",
                       create_track_callback(lambda: tracks, get_name))
    server.add_handler("/live/track/get/mute",
                       create_track_callback(lambda: tracks, failing))
    dispatch(server, "/live/track/get/*", "*")
    messages = receiver.drain()
    # The failing endpoint never silences the one that works.
    assert sorted(replies(messages)) == [("/live/track/get/name", (0, "drums")),
                                         ("/live/track/get/name", (1, "bass")),
                                         ("/live/track/get/name", (2, "keys"))]
    assert len(errors(messages)) == 1
    error = errors(messages)[0]
    assert error[1] == "/live/track/get/*"       # the pattern the client sent
    assert "/live/track/get/mute" in error[2]    # the concrete endpoint
    assert "wildcard fan-out failed at track 0" in error[2]


def test_composed_wildcard_mid_fan_out_skip_class_failure_is_silent(server, receiver, tracks,
                                                                    create_track_callback):
    # pr-review nit: under wildcard=True, _is_wildcard_skip decides by
    # exception class alone, with no regard for *where* in the fan-out it was
    # raised. A skip-classified exception (ValueError here) at track 1, after
    # track 0 already succeeded, is indistinguishable from the immediate
    # arg-mismatch case pinned above: OSCServer._dispatch never sees the
    # replies collected for track 0, because they never left track_callback's
    # local `replies` list before the exception propagated. So the matched
    # endpoint answers with nothing at all — no reply, no error — even though
    # it genuinely failed partway through, not merely "did not apply". This
    # is the documented all-or-nothing contract doing its job (API.md § The
    # track-index argument wildcard), just reachable through a path
    # (composition with an address pattern) where it looks identical to a
    # silent skip. See API.md and SESHAT.md for the one-sentence note this
    # test pins.
    def fails_from_track_one(track, params=()):
        if track.name != "drums":
            raise ValueError("not drums")
        return track.name,

    server.add_handler("/live/track/get/name",
                       create_track_callback(lambda: tracks, get_name))
    server.add_handler("/live/track/get/mute",
                       create_track_callback(lambda: tracks, fails_from_track_one))
    dispatch(server, "/live/track/get/*", "*")
    messages = receiver.drain()
    # The working endpoint is unaffected.
    assert sorted(replies(messages)) == [("/live/track/get/name", (0, "drums")),
                                         ("/live/track/get/name", (1, "bass")),
                                         ("/live/track/get/name", (2, "keys"))]
    # The failing endpoint produces nothing at all: not even the track-0
    # reply it already collected before failing at track 1, and no error.
    assert errors(messages) == []


#--------------------------------------------------------------------------------
# Track source resolution
#--------------------------------------------------------------------------------

def test_track_source_is_resolved_per_dispatch(server, receiver, tracks,
                                               create_track_callback):
    # get_tracks is called on every request, never cached at registration, so
    # a track created between two requests is included in the second.
    server.add_handler("/live/track/get/name",
                       create_track_callback(lambda: tracks, get_name))
    dispatch(server, "/live/track/get/name", "*")
    assert len(receiver.drain()) == 3
    tracks.append(FakeTrack("vox"))
    dispatch(server, "/live/track/get/name", "*")
    assert receiver.drain() == [("/live/track/get/name", (0, "drums")),
                                ("/live/track/get/name", (1, "bass")),
                                ("/live/track/get/name", (2, "keys")),
                                ("/live/track/get/name", (3, "vox"))]


#--------------------------------------------------------------------------------
# Listener identity truncation (include_track_id)
#
# The identity a listener registration is handed is exactly (track_index,).
# Arguments past the index are not part of it: before the truncation they
# entered the bookkeeping key and, via handler.py's (*params, *value) push,
# every subsequent push — so a start with a stray extra keyed a subscription
# no well-formed stop could reach.
#--------------------------------------------------------------------------------

def test_listener_registration_truncates_trailing_arguments(server, receiver, tracks,
                                                            create_track_callback):
    seen = []

    def start_listen(track, prop, params=()):
        seen.append((prop, params))

    server.add_handler("/live/track/start_listen/name",
                       create_track_callback(lambda: tracks, start_listen, "name",
                                             include_track_id=True))
    dispatch(server, "/live/track/start_listen/name", 0, 99)
    assert receiver.drain() == []
    assert seen == [("name", (0,))]


def test_wildcard_listener_registration_truncates_trailing_arguments(
        server, receiver, tracks, create_track_callback):
    seen = []

    def start_listen(track, prop, params=()):
        seen.append((prop, params))

    server.add_handler("/live/track/start_listen/name",
                       create_track_callback(lambda: tracks, start_listen, "name",
                                             include_track_id=True))
    dispatch(server, "/live/track/start_listen/name", "*", 42)
    assert receiver.drain() == []
    assert seen == [("name", (0,)), ("name", (1,)), ("name", (2,))]


def test_listener_registration_drops_non_numeric_extras(server, receiver, tracks,
                                                        create_track_callback):
    seen = []

    def start_listen(track, prop, params=()):
        seen.append((prop, params))

    server.add_handler("/live/track/start_listen/name",
                       create_track_callback(lambda: tracks, start_listen, "name",
                                             include_track_id=True))
    dispatch(server, "/live/track/start_listen/name", 1, "junk")
    assert receiver.drain() == []
    assert seen == [("name", (1,))]


def test_non_listener_branch_still_receives_the_params_tail(server, receiver, tracks,
                                                            create_track_callback):
    # The include_track_id=False branch is untouched: get/send reads its send
    # index out of exactly this tail.
    seen = []

    def get_send(track, params=()):
        seen.append(params)
        return params[0], "value"

    server.add_handler("/live/track/get/send",
                       create_track_callback(lambda: tracks, get_send))
    dispatch(server, "/live/track/get/send", 1, 0)
    assert receiver.drain() == [("/live/track/get/send", (1, 0, "value"))]
    assert seen == [(0,)]
