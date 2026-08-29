"""
The Groove Pool family (D-2), without Ableton Live.

Three handlers' worth of surface, all driven end to end through the real
OSCServer as datagrams:

  - `/live/groove/*` — the new `GrooveHandler`: get/set for `name`, `base` and
    the four amounts, and the listen pair for the five observable ones;
  - `/live/song/get/groove_pool` and its listen pair — the flattened pool dump
    in `SongHandler`, whose listener rides the `lom_property` alias to
    subscribe `grooves` on the pool object while pushing under its own name;
  - `/live/clip/get|set/groove` and its listen pair — the assignment in
    `ClipHandler`, answered as an index into the pool with `-1` for "none",
    and the one address in this fork that accepts `-1` as an *argument*
    (exactly `-1` clears; `-2` and below are a `ValueError`).

The module-level resolvers (`resolve_groove`, `groove_index`,
`groove_pool_dump`) are also driven directly as plain functions, the
`track_identity.py` pattern: parameterised on `song`, they are the real
shipped code with no handler in the way.

What a green run does **not** prove: anything about real LOM objects. Whether
`clip.groove = None` actually clears the assignment, what `Groove.base`
encodes to on the wire, what the amount ranges are, and whether the
`GroovePool.grooves` observer fires on membership changes only are all
unmeasured — they need the Live verification checks in the plan, and API.md
marks each with a ⚠️ until those run.
"""

import pytest

from .conftest import (bind_song, dispatch, load_clip_module,
                       load_groove_module, load_handler_module,
                       load_song_module)

POOL_GET = "/live/song/get/groove_pool"
POOL_START = "/live/song/start_listen/groove_pool"
POOL_STOP = "/live/song/stop_listen/groove_pool"

CLIP_GET = "/live/clip/get/groove"
CLIP_SET = "/live/clip/set/groove"
CLIP_START = "/live/clip/start_listen/groove"
CLIP_STOP = "/live/clip/stop_listen/groove"

#--------------------------------------------------------------------------------
# The five observable members, in GROOVE_FIELDS order. `base` is deliberately
# absent: it is rw but not observable, so it has get/set and no listen pair.
#--------------------------------------------------------------------------------
OBSERVABLE_PROPERTIES = ("name", "quantization_amount", "timing_amount",
                         "random_amount", "velocity_amount")


class FakeManager:
    """`osc_server` is the only attribute AbletonOSCHandler reads off it."""

    def __init__(self, osc_server):
        self.osc_server = osc_server


class FakeGroove:
    """
    A `Live.Groove.Groove` stand-in carrying all six members and recording
    every listener subscription per property, so a start/stop pair can be
    checked for having bound and unbound the same callable on the same object.
    """

    def __init__(self, name, quantization_amount=0.0, timing_amount=0.0,
                 random_amount=0.0, velocity_amount=0.0, base=2):
        self.name = name
        self.quantization_amount = quantization_amount
        self.timing_amount = timing_amount
        self.random_amount = random_amount
        self.velocity_amount = velocity_amount
        self.base = base
        self.listeners = {}

    def _add(self, prop, callback):
        self.listeners.setdefault(prop, []).append(callback)

    def _remove(self, prop, callback):
        self.listeners[prop].remove(callback)

    def notify(self, prop):
        for callback in list(self.listeners.get(prop, [])):
            callback()

    def __getattr__(self, name):
        #--------------------------------------------------------------------------------
        # add_<prop>_listener / remove_<prop>_listener for the five observable
        # members only — a real Groove has no add_base_listener, and neither
        # does this, so a listen pair wrongly registered for `base` fails here
        # exactly as it would in Live.
        #--------------------------------------------------------------------------------
        for verb, method in (("add_", self._add), ("remove_", self._remove)):
            if name.startswith(verb) and name.endswith("_listener"):
                prop = name[len(verb):-len("_listener")]
                if prop in OBSERVABLE_PROPERTIES:
                    return lambda callback: method(prop, callback)
        raise AttributeError(name)


class FakeGroovePool:
    """`Live.GroovePool.GroovePool`: one observable member, `grooves`."""

    def __init__(self, grooves=()):
        self.grooves = list(grooves)
        self.grooves_listeners = []

    def add_grooves_listener(self, callback):
        self.grooves_listeners.append(callback)

    def remove_grooves_listener(self, callback):
        self.grooves_listeners.remove(callback)

    def notify_grooves(self):
        for callback in list(self.grooves_listeners):
            callback()


class FakeClip:
    def __init__(self, groove=None):
        self.groove = groove
        self.groove_listeners = []

    def add_groove_listener(self, callback):
        self.groove_listeners.append(callback)

    def remove_groove_listener(self, callback):
        self.groove_listeners.remove(callback)

    def notify_groove(self):
        for callback in list(self.groove_listeners):
            callback()


class FakeClipSlot:
    def __init__(self, clip):
        self.clip = clip
        self.has_clip = clip is not None


class FakeTrack:
    def __init__(self, clip_slots):
        self.clip_slots = list(clip_slots)


class FakeSong:
    """
    Only what the three handlers' groove addresses reach: the pool, and (for
    the clip half) one track holding one clip.

    `SongHandler` binds `self.song` into a partial() for every address it
    registers, so the song-side fixtures build it through conftest's
    `bind_song()`; the groove and clip handlers touch `self.song` only from
    callbacks and take it after construction.
    """

    def __init__(self, grooves=(), clips=()):
        self.groove_pool = FakeGroovePool(grooves)
        self.tracks = [FakeTrack([FakeClipSlot(clip) for clip in clips])]
        #--------------------------------------------------------------------------------
        # SongHandler's generic loops bind these at registration time.
        #--------------------------------------------------------------------------------
        self.return_tracks = []
        self.master_track = None


def make_grooves():
    """
    Two grooves whose every field is distinct, so a handler that dropped or
    reordered one cannot pass by accident. Velocity amounts are of opposite
    sign because Live's UI shows that column as -100..100%.

    Every amount is exactly representable in binary32: OSC carries a float as
    32 bits, so a value like 0.1 comes back off the wire as 0.10000000149...
    and an equality assertion on it would be testing IEEE rounding rather than
    the handler.
    """
    return [FakeGroove("Swing 16 A", quantization_amount=0.25,
                       timing_amount=0.5, random_amount=0.125,
                       velocity_amount=-0.75, base=2),
            FakeGroove("MPC 8 Straight", quantization_amount=0.75,
                       timing_amount=0.375, random_amount=0.875,
                       velocity_amount=0.25, base=3)]


def errors(messages):
    return [params for address, params in messages if address == "/live/error"]


def replies(messages, address):
    return [params for addr, params in messages if addr == address]


def one_message(receiver):
    messages = receiver.drain()
    assert len(messages) == 1, messages
    return messages[0]


def assert_structured_error(receiver, address):
    """
    The /live/error envelope OSCServer._dispatch sends for a callback that
    raised, with nothing on the request's own address. Returns the detail
    string so a caller can assert on what it names.
    """
    error_address, params = one_message(receiver)
    assert error_address == "/live/error"
    assert params[0] == "request"
    assert params[1] == address
    return params[2]


@pytest.fixture
def grooves():
    return make_grooves()


@pytest.fixture
def song(grooves):
    return FakeSong(grooves=grooves, clips=[FakeClip(), None])


@pytest.fixture
def groove_module():
    return load_groove_module()


@pytest.fixture
def groove_handler(server, song, groove_module):
    handler = groove_module.GrooveHandler(FakeManager(server))
    handler.song = song
    return handler


@pytest.fixture
def song_handler(server, song):
    handler_class = bind_song(load_song_module().SongHandler, song)
    return handler_class(FakeManager(server))


@pytest.fixture
def clip_handler(server, song):
    load_handler_module()
    handler = load_clip_module().ClipHandler(FakeManager(server))
    handler.song = song
    return handler


#--------------------------------------------------------------------------------
# The module constants and the Live-free resolvers
#--------------------------------------------------------------------------------

def test_groove_fields_are_the_documented_order(groove_module):
    """
    The canonical order the pool dump and API.md § "Groove API" both state.
    `base` is not in it: its wire type is unverified and pythonosc drops a
    whole reply it cannot encode, so it gets its own address instead.
    """
    assert groove_module.GROOVE_FIELDS == ("name", "quantization_amount",
                                           "timing_amount", "random_amount",
                                           "velocity_amount")
    assert "base" not in groove_module.GROOVE_FIELDS
    assert len(groove_module.GROOVE_FIELD_COERCIONS) == len(groove_module.GROOVE_FIELDS)


def test_resolve_groove_returns_the_pool_member(groove_module, song):
    assert groove_module.resolve_groove(song, 1) is song.groove_pool.grooves[1]


@pytest.mark.parametrize("index", [-1, -2, -100, 2, 7])
def test_resolve_groove_validates_rather_than_indexing(groove_module, song, index):
    """
    The whole point of the resolver: Python would happily read
    `grooves[-1]` as the last groove, which is the value the getters answer
    for "nothing assigned".
    """
    with pytest.raises(ValueError) as excinfo:
        groove_module.resolve_groove(song, index)
    assert "2 groove(s)" in str(excinfo.value)


def test_resolve_groove_on_an_empty_pool_names_zero(groove_module):
    with pytest.raises(ValueError) as excinfo:
        groove_module.resolve_groove(FakeSong(), 0)
    assert "0 groove(s)" in str(excinfo.value)


def test_groove_index_finds_a_pool_member(groove_module, song):
    assert groove_module.groove_index(song, song.groove_pool.grooves[1]) == 1


def test_groove_index_of_none_is_minus_one(groove_module, song):
    assert groove_module.groove_index(song, None) == groove_module.NO_INDEX


def test_groove_index_of_an_object_outside_the_pool_is_minus_one(groove_module, song):
    """Absence is an answer here, not a resolution failure."""
    assert groove_module.groove_index(song, FakeGroove("elsewhere")) == -1


def test_groove_pool_dump_is_stride_five_in_field_order(groove_module, song):
    assert groove_module.groove_pool_dump(song) == (
        "Swing 16 A", 0.25, 0.5, 0.125, -0.75,
        "MPC 8 Straight", 0.75, 0.375, 0.875, 0.25)


def test_groove_pool_dump_of_an_empty_pool_is_empty(groove_module):
    assert groove_module.groove_pool_dump(FakeSong()) == ()


def test_groove_pool_dump_coerces_every_field(groove_module):
    """
    Coercion on the way out, not only in: pythonosc infers an OSC type from
    the Python type and silently drops a whole reply it cannot type.
    """
    class Weird:
        def __init__(self, value):
            self.value = value

        def __float__(self):
            return float(self.value)

        def __str__(self):
            return "weird-%s" % self.value

    groove = FakeGroove(Weird(1), quantization_amount=Weird(2),
                        timing_amount=Weird(3), random_amount=Weird(4),
                        velocity_amount=Weird(5))
    dump = groove_module.groove_pool_dump(FakeSong(grooves=[groove]))
    assert dump == ("weird-1", 2.0, 3.0, 4.0, 5.0)
    assert type(dump[0]) is str
    assert all(type(value) is float for value in dump[1:])


#--------------------------------------------------------------------------------
# /live/groove/* — registration
#--------------------------------------------------------------------------------

def test_every_groove_address_is_registered(groove_handler, server):
    for prop in OBSERVABLE_PROPERTIES + ("base",):
        assert "/live/groove/get/%s" % prop in server._callbacks
        assert "/live/groove/set/%s" % prop in server._callbacks
    for prop in OBSERVABLE_PROPERTIES:
        assert "/live/groove/start_listen/%s" % prop in server._callbacks
        assert "/live/groove/stop_listen/%s" % prop in server._callbacks


def test_base_has_no_listen_pair(groove_handler, server):
    """
    `Groove.base` is the one non-observable member. A registered listen
    address could only ever answer /live/error on the add_base_listener
    lookup; unregistered, the same send is an unknown address — logged,
    unanswered, honest.
    """
    assert "/live/groove/start_listen/base" not in server._callbacks
    assert "/live/groove/stop_listen/base" not in server._callbacks


def test_the_handler_pushes_under_the_groove_identifier(groove_module):
    assert groove_module.GrooveHandler.class_identifier == "groove"


#--------------------------------------------------------------------------------
# /live/groove/get|set
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("prop, expected", [
    ("name", "MPC 8 Straight"),
    ("quantization_amount", 0.75),
    ("timing_amount", 0.375),
    ("random_amount", 0.875),
    ("velocity_amount", 0.25),
    ("base", 3),
])
def test_get_echoes_the_index_then_the_value(groove_handler, server, receiver,
                                             prop, expected):
    address = "/live/groove/get/%s" % prop
    dispatch(server, address, 1)
    reply_address, params = one_message(receiver)
    assert reply_address == address
    assert params[0] == 1
    assert params[1] == expected


def test_get_normalises_a_float_index(groove_handler, server, receiver):
    """TouchOSC-style clients send every number as a float (upstream #33)."""
    dispatch(server, "/live/groove/get/name", 1.0)
    assert one_message(receiver) == ("/live/groove/get/name", (1, "MPC 8 Straight"))


@pytest.mark.parametrize("prop, value", [
    ("name", "renamed"),
    ("quantization_amount", 0.375),
    ("timing_amount", 0.625),
    ("random_amount", 0.25),
    ("velocity_amount", -0.5),
    ("base", 4),
])
def test_set_writes_the_member_and_replies_nothing(groove_handler, song, server,
                                                   receiver, prop, value):
    dispatch(server, "/live/groove/set/%s" % prop, 0, value)
    assert getattr(song.groove_pool.grooves[0], prop) == value
    assert receiver.drain() == []


def test_set_passes_the_amount_through_unclamped(groove_handler, song, server, receiver):
    """
    Ranges are unmeasured (API.md marks them ⚠️), so the setter does not clamp:
    Live is the authority, and a clamp guessed here would silently disagree
    with it.
    """
    dispatch(server, "/live/groove/set/timing_amount", 0, 4.5)
    assert song.groove_pool.grooves[0].timing_amount == 4.5
    assert receiver.drain() == []


#--------------------------------------------------------------------------------
# /live/groove/* — validation
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("index", [-1, -2, 2, 99])
def test_get_of_an_invalid_index_is_a_structured_error(groove_handler, server,
                                                       receiver, index):
    address = "/live/groove/get/name"
    dispatch(server, address, index)
    detail = assert_structured_error(receiver, address)
    assert "2 groove(s)" in detail


def test_a_rejected_get_never_wraps_around_to_the_last_groove(groove_handler,
                                                              server, receiver):
    """
    The failure this validation exists to prevent: `grooves[-1]` is a perfectly
    good Python expression and would answer the last groove's name as though it
    were index -1's.
    """
    dispatch(server, "/live/groove/get/name", -1)
    messages = receiver.drain()
    assert replies(messages, "/live/groove/get/name") == []
    assert len(errors(messages)) == 1


def test_set_of_an_invalid_index_changes_nothing(groove_handler, song, server, receiver):
    dispatch(server, "/live/groove/set/name", 5, "clobbered")
    assert [groove.name for groove in song.groove_pool.grooves] == \
        ["Swing 16 A", "MPC 8 Straight"]
    assert len(errors(receiver.drain())) == 1


def test_a_non_integral_float_index_truncates_toward_zero(groove_handler, server, receiver):
    dispatch(server, "/live/groove/get/name", 1.9)
    assert one_message(receiver) == ("/live/groove/get/name", (1, "MPC 8 Straight"))


def test_no_index_at_all_is_a_structured_error(groove_handler, server, receiver):
    dispatch(server, "/live/groove/get/name")
    assert_structured_error(receiver, "/live/groove/get/name")


#--------------------------------------------------------------------------------
# /live/groove/{start,stop}_listen
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("prop, value", [
    ("name", "MPC 8 Straight"),
    ("timing_amount", 0.375),
])
def test_start_listen_pushes_immediately_then_on_change(groove_handler, song,
                                                        server, receiver, prop, value):
    address = "/live/groove/get/%s" % prop
    dispatch(server, "/live/groove/start_listen/%s" % prop, 1)
    assert one_message(receiver) == (address, (1, value))

    groove = song.groove_pool.grooves[1]
    setattr(groove, prop, "changed" if prop == "name" else 0.875)
    groove.notify(prop)
    assert one_message(receiver) == (address, (1, "changed" if prop == "name" else 0.875))


def test_stop_listen_unbinds_from_the_groove(groove_handler, song, server, receiver):
    dispatch(server, "/live/groove/start_listen/timing_amount", 0)
    receiver.drain()
    dispatch(server, "/live/groove/stop_listen/timing_amount", 0)
    assert receiver.drain() == []
    assert song.groove_pool.grooves[0].listeners["timing_amount"] == []

    song.groove_pool.grooves[0].notify("timing_amount")
    assert receiver.drain() == []


def test_a_float_start_and_an_int_stop_name_one_subscription(groove_handler, song,
                                                             server, receiver):
    """
    The identity is normalised once, at the callback boundary, so clients that
    disagree about number types can still start and stop each other's
    subscriptions.
    """
    dispatch(server, "/live/groove/start_listen/timing_amount", 0.0)
    receiver.drain()
    assert len(song.groove_pool.grooves[0].listeners["timing_amount"]) == 1

    dispatch(server, "/live/groove/stop_listen/timing_amount", 0)
    assert song.groove_pool.grooves[0].listeners["timing_amount"] == []


def test_a_trailing_argument_does_not_key_a_second_subscription(groove_handler, song,
                                                                server, receiver):
    dispatch(server, "/live/groove/start_listen/timing_amount", 0, 99)
    receiver.drain()
    dispatch(server, "/live/groove/stop_listen/timing_amount", 0)
    assert song.groove_pool.grooves[0].listeners["timing_amount"] == []


def test_clear_api_unbinds_every_groove_listener(groove_handler, song, server, receiver):
    dispatch(server, "/live/groove/start_listen/name", 0)
    dispatch(server, "/live/groove/start_listen/random_amount", 1)
    receiver.drain()

    groove_handler.clear_api()
    assert song.groove_pool.grooves[0].listeners["name"] == []
    assert song.groove_pool.grooves[1].listeners["random_amount"] == []


#--------------------------------------------------------------------------------
# /live/song/get/groove_pool and its listen pair
#--------------------------------------------------------------------------------

def test_all_three_pool_addresses_are_registered(song_handler, server):
    for address in (POOL_GET, POOL_START, POOL_STOP):
        assert address in server._callbacks


def test_pool_get_replies_the_flattened_dump(song_handler, server, receiver):
    dispatch(server, POOL_GET)
    assert replies(receiver.drain(), POOL_GET) == [
        ("Swing 16 A", 0.25, 0.5, 0.125, -0.75,
         "MPC 8 Straight", 0.75, 0.375, 0.875, 0.25)]


def test_pool_get_on_an_empty_pool_replies_with_no_arguments(server, receiver):
    handler_class = bind_song(load_song_module().SongHandler, FakeSong())
    handler_class(FakeManager(server))
    dispatch(server, POOL_GET)
    assert one_message(receiver) == (POOL_GET, ())


def test_pool_listener_subscribes_grooves_on_the_pool_object(song_handler, song,
                                                             server, receiver):
    """
    The `lom_property` alias: the address is `groove_pool` and the push goes out
    under that name, but what is actually subscribed is `grooves` on
    `song.groove_pool` — the observable that fires on membership changes.
    """
    dispatch(server, POOL_START)
    assert len(song.groove_pool.grooves_listeners) == 1
    assert one_message(receiver) == (
        POOL_GET, ("Swing 16 A", 0.25, 0.5, 0.125, -0.75,
                   "MPC 8 Straight", 0.75, 0.375, 0.875, 0.25))


def test_pool_listener_pushes_the_whole_dump_on_a_membership_change(song_handler, song,
                                                                    server, receiver):
    dispatch(server, POOL_START)
    receiver.drain()

    song.groove_pool.grooves.pop(0)
    song.groove_pool.notify_grooves()
    assert one_message(receiver) == (POOL_GET, ("MPC 8 Straight", 0.75, 0.375, 0.875, 0.25))


def test_pool_stop_listen_unbinds_the_alias(song_handler, song, server, receiver):
    dispatch(server, POOL_START)
    receiver.drain()
    dispatch(server, POOL_STOP)
    assert song.groove_pool.grooves_listeners == []

    song.groove_pool.notify_grooves()
    assert receiver.drain() == []


def test_pool_stop_listen_unbinds_the_original_pool_after_it_is_replaced(
        song_handler, song, server, receiver):
    """
    `song_start_listen_groove_pool` / `song_stop_listen_groove_pool` both
    dereference `self.song.groove_pool` at call time rather than binding it
    into a partial() at registration (song.py's "dereferenced at *call*
    time" comment) — because loading a set can hand back a different pool
    object. Unbinding is claimed to stay correct "either way" because
    `_stop_listen` unbinds from the object stored in `listener_objects`, not
    the one it is handed. Pin that: swap in a fresh pool between start and
    stop, and confirm the *original* pool's listener is the one removed.
    """
    dispatch(server, POOL_START)
    receiver.drain()
    original_pool = song.groove_pool
    assert len(original_pool.grooves_listeners) == 1

    song.groove_pool = FakeGroovePool(make_grooves())

    dispatch(server, POOL_STOP)
    assert original_pool.grooves_listeners == []

    original_pool.notify_grooves()
    assert receiver.drain() == []


def test_clear_api_unbinds_the_pool_listener(song_handler, song, server, receiver):
    dispatch(server, POOL_START)
    receiver.drain()
    song_handler.clear_api()
    assert song.groove_pool.grooves_listeners == []


#--------------------------------------------------------------------------------
# /live/clip/get|set/groove
#--------------------------------------------------------------------------------

def test_all_four_clip_groove_addresses_are_registered(clip_handler, server):
    for address in (CLIP_GET, CLIP_SET, CLIP_START, CLIP_STOP):
        assert address in server._callbacks


def test_clip_get_reports_minus_one_when_no_groove_is_assigned(clip_handler,
                                                               server, receiver):
    dispatch(server, CLIP_GET, 0, 0)
    assert one_message(receiver) == (CLIP_GET, (0, 0, -1))


def test_clip_get_reports_the_pool_index(clip_handler, song, server, receiver):
    song.tracks[0].clip_slots[0].clip.groove = song.groove_pool.grooves[1]
    dispatch(server, CLIP_GET, 0, 0)
    assert one_message(receiver) == (CLIP_GET, (0, 0, 1))


def test_clip_get_reports_minus_one_for_a_groove_outside_the_pool(clip_handler, song,
                                                                  server, receiver):
    """
    Absence is an answer, not an error — the same half of the convention as a
    `None` groove.
    """
    song.tracks[0].clip_slots[0].clip.groove = FakeGroove("orphan")
    dispatch(server, CLIP_GET, 0, 0)
    assert one_message(receiver) == (CLIP_GET, (0, 0, -1))


def test_clip_get_reply_is_three_ints(clip_handler, song, server, receiver):
    song.tracks[0].clip_slots[0].clip.groove = song.groove_pool.grooves[0]
    dispatch(server, CLIP_GET, 0, 0)
    params = replies(receiver.drain(), CLIP_GET)[0]
    assert len(params) == 3
    assert all(type(value) is int for value in params)


def test_clip_set_assigns_the_pool_object(clip_handler, song, server, receiver):
    dispatch(server, CLIP_SET, 0, 0, 1)
    assert song.tracks[0].clip_slots[0].clip.groove is song.groove_pool.grooves[1]
    assert receiver.drain() == []


def test_clip_set_minus_one_clears_the_assignment(clip_handler, song, server, receiver):
    """
    ⚠️ Live-side behaviour unmeasured: whether Live accepts `clip.groove = None`
    is Live verification check 2. What is pinned here is that the handler makes
    exactly that assignment for exactly -1.
    """
    song.tracks[0].clip_slots[0].clip.groove = song.groove_pool.grooves[0]
    dispatch(server, CLIP_SET, 0, 0, -1)
    assert song.tracks[0].clip_slots[0].clip.groove is None
    assert receiver.drain() == []


def test_clip_set_round_trips_a_read(clip_handler, song, server, receiver):
    """
    The reason -1 is a sanctioned argument here: `get → -1 → set -1` restores
    "no groove", which is what the read said. On the appointed-device setter
    the same value would have been a wrap-around.
    """
    dispatch(server, CLIP_GET, 0, 0)
    index = one_message(receiver)[1][2]
    dispatch(server, CLIP_SET, 0, 0, index)
    assert song.tracks[0].clip_slots[0].clip.groove is None


@pytest.mark.parametrize("index", [-2, -100, 2, 42])
def test_clip_set_rejects_everything_but_minus_one_and_a_real_index(clip_handler, song,
                                                                    server, receiver, index):
    song.tracks[0].clip_slots[0].clip.groove = song.groove_pool.grooves[0]
    dispatch(server, CLIP_SET, 0, 0, index)
    detail = assert_structured_error(receiver, CLIP_SET)
    assert "2 groove(s)" in detail
    #--------------------------------------------------------------------------------
    # -2 must not wrap around to grooves[-2], which is grooves[0] here and
    # would look exactly like a successful no-op.
    #--------------------------------------------------------------------------------
    assert song.tracks[0].clip_slots[0].clip.groove is song.groove_pool.grooves[0]


def test_clip_set_normalises_a_float_index(clip_handler, song, server, receiver):
    dispatch(server, CLIP_SET, 0.0, 0.0, 1.0)
    assert song.tracks[0].clip_slots[0].clip.groove is song.groove_pool.grooves[1]


def test_clip_set_on_an_empty_slot_is_a_structured_error(clip_handler, server, receiver):
    """Slot 1 holds no clip — the same failure every /live/clip/* address has."""
    dispatch(server, CLIP_SET, 0, 1, 0)
    assert_structured_error(receiver, CLIP_SET)


#--------------------------------------------------------------------------------
# /live/clip/{start,stop}_listen/groove
#--------------------------------------------------------------------------------

def test_clip_listener_pushes_the_index_with_the_clip_identity(clip_handler, song,
                                                               server, receiver):
    clip = song.tracks[0].clip_slots[0].clip
    dispatch(server, CLIP_START, 0, 0)
    assert one_message(receiver) == (CLIP_GET, (0, 0, -1))

    clip.groove = song.groove_pool.grooves[0]
    clip.notify_groove()
    assert one_message(receiver) == (CLIP_GET, (0, 0, 0))


def test_clip_listener_identity_is_normalised(clip_handler, song, server, receiver):
    clip = song.tracks[0].clip_slots[0].clip
    dispatch(server, CLIP_START, 0.0, 0.0)
    receiver.drain()
    assert len(clip.groove_listeners) == 1

    dispatch(server, CLIP_STOP, 0, 0)
    assert clip.groove_listeners == []


def test_clip_stop_listen_unbinds(clip_handler, song, server, receiver):
    clip = song.tracks[0].clip_slots[0].clip
    dispatch(server, CLIP_START, 0, 0)
    receiver.drain()
    dispatch(server, CLIP_STOP, 0, 0)
    assert clip.groove_listeners == []

    clip.notify_groove()
    assert receiver.drain() == []
