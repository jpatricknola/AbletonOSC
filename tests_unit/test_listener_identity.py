"""
Listener identity for the Scene, Clip and Clip Slot APIs, without Ableton Live.

The rule these three handlers now share with device.py: a listener's identity
is a tuple of ints, normalised at the callback boundary, truncated to exactly
the arguments that are part of that identity, and used identically for the LOM
lookup, the bookkeeping key and the echo in the push.

Before this, each of the three wrappers cast its indices for the *lookup* but
handed the callee the raw OSC arguments. Measured against master (2026-08-27,
`64a5058`) that produced three distinct defects, one per test below:

* `start_listen/name 0.0` subscribed scene 0 correctly but pushed
  `/live/scene/get/name (0.0, 'Scene A')` — a float32-tagged id, where the
  query reply for the same property echoes an int. Same value, different wire
  type, for the life of the subscription.
* `start_listen/name 0.7` subscribed scene **0** (the lookup truncates) but
  keyed `("name", (0.7,))` and pushed `0.7` — a push attributed to a scene
  that does not exist, and a listener `stop_listen/name 0` could never find.
* `start_listen/name 1 99` keyed `("name", (1, 99))` and pushed a bogus third
  field, and the well-formed `stop_listen/name 1` missed the key entirely,
  leaking the listener until the script reloaded.

Note what is *not* a defect, because the roadmap entry that produced this work
claimed it was: an integral-float start is **not** orphaned by an int stop.
CPython tuple keys compare numerically, so `("name", (0.0,))` and
`("name", (0,))` are one dict entry. That is exactly why the assertions here
check `type(...) is int` on the echoed ids rather than equality — a
value-equality assertion passes against the old, broken behaviour.

Everything below the fakes is production code: the OSCServer, the dispatcher,
and the three real handler subclasses, constructed through conftest's
synthetic-root loaders. scene.py and clip_slot.py need no stub beyond the
Component one; clip.py additionally needs the empty `Live` import shim
described in conftest's docstring.
"""

import pytest

from .conftest import (dispatch, load_clip_module, load_clip_slot_module,
                       load_handler_module, load_scene_module)


class FakeManager:
    """`osc_server` is the only attribute AbletonOSCHandler reads off it."""

    def __init__(self, osc_server):
        self.osc_server = osc_server


class FakeScene:
    def __init__(self, name):
        self.name = name
        self.listeners = []

    def add_name_listener(self, function):
        self.listeners.append(function)

    def remove_name_listener(self, function):
        self.listeners.remove(function)


class FakeClip:
    def __init__(self, name):
        self.name = name
        self.listeners = []

    def add_name_listener(self, function):
        self.listeners.append(function)

    def remove_name_listener(self, function):
        self.listeners.remove(function)


class FakeClipSlot:
    def __init__(self, clip):
        self.clip = clip
        self.has_clip = clip is not None
        self.listeners = []

    def add_has_clip_listener(self, function):
        self.listeners.append(function)

    def remove_has_clip_listener(self, function):
        self.listeners.remove(function)


class FakeTrack:
    def __init__(self, clip_slots):
        self.clip_slots = list(clip_slots)


class FakeSong:
    def __init__(self, scenes, tracks):
        self.scenes = list(scenes)
        self.tracks = list(tracks)


def make_song():
    return FakeSong(scenes=[FakeScene("Scene A"), FakeScene("Scene B")],
                    tracks=[FakeTrack([FakeClipSlot(FakeClip("Clip A")),
                                       FakeClipSlot(FakeClip("Clip B"))]),
                            FakeTrack([FakeClipSlot(FakeClip("Clip C"))])])


#--------------------------------------------------------------------------------
# One table row per handler. `ids` is the well-formed identity every case
# converges on; `floats` and `nonintegral` are the malformed spellings of the
# same subscription that used to diverge from it.
#--------------------------------------------------------------------------------
SPECS = {
    "scene": {
        "prefix": "/live/scene",
        "prop": "name",
        "ids": (0,),
        "floats": (0.0,),
        "nonintegral": (0.7,),
        "too_few": (),
        "value": "Scene A",
        "new_value": "Renamed",
        "other_ids": (1,),
    },
    "clip": {
        "prefix": "/live/clip",
        "prop": "name",
        "ids": (0, 0),
        "floats": (0.0, 0.0),
        "nonintegral": (0.7, 0.2),
        "too_few": (0,),
        "value": "Clip A",
        "new_value": "Renamed",
        "other_ids": (0, 1),
    },
    "clip_slot": {
        "prefix": "/live/clip_slot",
        "prop": "has_clip",
        "ids": (0, 0),
        "floats": (0.0, 0.0),
        "nonintegral": (0.7, 0.2),
        "too_few": (0,),
        "value": True,
        "new_value": False,
        "other_ids": (0, 1),
    },
}

HANDLER_KEYS = list(SPECS.keys())


@pytest.fixture
def handlers(server):
    """
    The three production handlers, all registered against one production
    OSCServer and sharing one fake song.

    For these three, `self.song` is read at dispatch time rather than at
    registration time, so assigning it after construction is enough.
    (Handlers that read it *during* registration — song.py, view.py — need
    conftest's `bind_song()` instead; see test_song_object_reads.py.)
    """
    load_handler_module()
    modules = {
        "scene": load_scene_module().SceneHandler,
        "clip": load_clip_module().ClipHandler,
        "clip_slot": load_clip_slot_module().ClipSlotHandler,
    }
    song = make_song()
    built = {}
    for key, handler_class in modules.items():
        handler = handler_class(FakeManager(server))
        handler.song = song
        built[key] = handler
    return built


def target_of(key, handler, ids):
    """The fake LOM object a subscription with `ids` binds to."""
    if key == "scene":
        return handler.song.scenes[ids[0]]
    clip_slot = handler.song.tracks[ids[0]].clip_slots[ids[1]]
    return clip_slot.clip if key == "clip" else clip_slot


def set_value(key, target, value):
    setattr(target, SPECS[key]["prop"], value)


def start_address(key):
    return "%s/start_listen/%s" % (SPECS[key]["prefix"], SPECS[key]["prop"])


def stop_address(key):
    return "%s/stop_listen/%s" % (SPECS[key]["prefix"], SPECS[key]["prop"])


def get_address(key):
    return "%s/get/%s" % (SPECS[key]["prefix"], SPECS[key]["prop"])


def assert_int_ids(params, count):
    #--------------------------------------------------------------------------------
    # The point of the whole item: not that the echoed ids are *equal* to the
    # ints a client sent, but that they are ints. 0.0 == 0 in Python and the
    # old behaviour passed any equality assertion written here.
    #--------------------------------------------------------------------------------
    assert [type(param) for param in params[:count]] == [int] * count


#--------------------------------------------------------------------------------
# 1. A float-indexed subscribe normalises to ints, in the key and on the wire
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("key", HANDLER_KEYS)
def test_float_start_normalises_identity(handlers, server, receiver, key):
    spec = SPECS[key]
    handler = handlers[key]

    dispatch(server, start_address(key), *spec["floats"])

    assert list(handler.listener_functions.keys()) == [(spec["prop"], spec["ids"])]
    target = target_of(key, handler, spec["ids"])
    assert handler.listener_objects[(spec["prop"], spec["ids"])] is target
    assert len(target.listeners) == 1

    messages = receiver.drain()
    assert messages == [(get_address(key), (*spec["ids"], spec["value"]))]
    assert_int_ids(messages[0][1], len(spec["ids"]))


#--------------------------------------------------------------------------------
# 2. A non-integral float start is stoppable by a well-formed stop
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("key", HANDLER_KEYS)
def test_non_integral_float_start_is_stoppable(handlers, server, receiver, key):
    spec = SPECS[key]
    handler = handlers[key]

    dispatch(server, start_address(key), *spec["nonintegral"])

    #--------------------------------------------------------------------------------
    # The lookup always truncated toward zero, so 0.7 subscribed object 0. The
    # key and the push used to disagree with it, which is what leaked.
    #--------------------------------------------------------------------------------
    target = target_of(key, handler, spec["ids"])
    assert list(handler.listener_functions.keys()) == [(spec["prop"], spec["ids"])]
    assert len(target.listeners) == 1

    messages = receiver.drain()
    assert messages == [(get_address(key), (*spec["ids"], spec["value"]))]
    assert_int_ids(messages[0][1], len(spec["ids"]))

    dispatch(server, stop_address(key), *spec["ids"])

    assert target.listeners == []
    assert handler.listener_functions == {}
    assert handler.listener_objects == {}
    assert receiver.drain() == []


#--------------------------------------------------------------------------------
# 3. Arguments past the identity are ignored, on both halves of the pair
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("key", HANDLER_KEYS)
def test_extra_argument_start_is_truncated(handlers, server, receiver, key):
    spec = SPECS[key]
    handler = handlers[key]

    dispatch(server, start_address(key), *spec["ids"], "bogus")

    assert list(handler.listener_functions.keys()) == [(spec["prop"], spec["ids"])]
    assert receiver.drain() == [(get_address(key), (*spec["ids"], spec["value"]))]

    dispatch(server, stop_address(key), *spec["ids"])

    assert target_of(key, handler, spec["ids"]).listeners == []
    assert handler.listener_functions == {}
    assert handler.listener_objects == {}


@pytest.mark.parametrize("key", HANDLER_KEYS)
def test_extra_argument_stop_ends_a_well_formed_start(handlers, server,
                                                      receiver, key):
    spec = SPECS[key]
    handler = handlers[key]

    dispatch(server, start_address(key), *spec["ids"])
    receiver.drain()

    dispatch(server, stop_address(key), *spec["ids"], "bogus")

    assert target_of(key, handler, spec["ids"]).listeners == []
    assert handler.listener_functions == {}
    assert handler.listener_objects == {}
    assert receiver.drain() == []


#--------------------------------------------------------------------------------
# 4. Re-subscribing is idempotent across number types
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("key", HANDLER_KEYS)
def test_restart_is_idempotent_across_number_types(handlers, server, receiver, key):
    spec = SPECS[key]
    handler = handlers[key]

    dispatch(server, start_address(key), *spec["floats"])
    dispatch(server, start_address(key), *spec["ids"])
    receiver.drain()

    assert len(target_of(key, handler, spec["ids"]).listeners) == 1
    assert len(handler.listener_functions) == 1
    assert len(handler.listener_objects) == 1


#--------------------------------------------------------------------------------
# 5. A change push carries the int identity, not the client's spelling of it
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("key", HANDLER_KEYS)
def test_change_push_carries_int_identity(handlers, server, receiver, key):
    spec = SPECS[key]
    handler = handlers[key]

    dispatch(server, start_address(key), *spec["floats"])
    receiver.drain()

    target = target_of(key, handler, spec["ids"])
    set_value(key, target, spec["new_value"])
    target.listeners[0]()

    messages = receiver.drain()
    assert messages == [(get_address(key), (*spec["ids"], spec["new_value"]))]
    assert_int_ids(messages[0][1], len(spec["ids"]))


#--------------------------------------------------------------------------------
# 6. Subscriptions are per object, and one stop ends exactly one of them
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("key", HANDLER_KEYS)
def test_subscriptions_are_per_object(handlers, server, receiver, key):
    spec = SPECS[key]
    handler = handlers[key]

    dispatch(server, start_address(key), *spec["floats"])
    dispatch(server, start_address(key), *spec["other_ids"])
    receiver.drain()

    assert set(handler.listener_functions.keys()) == {(spec["prop"], spec["ids"]),
                                                      (spec["prop"], spec["other_ids"])}

    dispatch(server, stop_address(key), *spec["ids"])

    assert target_of(key, handler, spec["ids"]).listeners == []
    assert len(target_of(key, handler, spec["other_ids"]).listeners) == 1
    assert list(handler.listener_functions.keys()) == [(spec["prop"], spec["other_ids"])]


#--------------------------------------------------------------------------------
# 7. clear_api() unbinds a malformed subscription too
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("key", HANDLER_KEYS)
def test_clear_api_unbinds_malformed_subscription(handlers, server, receiver, key):
    spec = SPECS[key]
    handler = handlers[key]

    dispatch(server, start_address(key), *spec["nonintegral"], "bogus")
    receiver.drain()

    handler.clear_api()

    assert target_of(key, handler, spec["ids"]).listeners == []
    assert handler.listener_functions == {}
    assert handler.listener_objects == {}


#--------------------------------------------------------------------------------
# 8. Query replies are untouched by any of the above
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("key", HANDLER_KEYS)
def test_query_reply_is_unchanged(handlers, server, receiver, key):
    spec = SPECS[key]

    #--------------------------------------------------------------------------------
    # get/ is registered through the *other* branch of the same wrapper — the
    # one that passes params[n:] and lets the reply envelope prepend the
    # indices. Truncating the listener branch must not have reached it.
    #--------------------------------------------------------------------------------
    dispatch(server, get_address(key), *spec["ids"])
    assert receiver.drain() == [(get_address(key), (*spec["ids"], spec["value"]))]

    dispatch(server, get_address(key), *spec["floats"])
    messages = receiver.drain()
    assert messages == [(get_address(key), (*spec["ids"], spec["value"]))]
    assert_int_ids(messages[0][1], len(spec["ids"]))


#--------------------------------------------------------------------------------
# 9. Fewer than the identity's arity is a malformed request, not a listener
#    leak — the same shape as device.py's parameter-pair regression in
#    tests_unit/test_device_listeners.py, pinned here for scene/clip/clip_slot
#    now that API.md documents it for all three.
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("key", HANDLER_KEYS)
def test_start_listen_with_too_few_arguments_is_a_structured_error(
        handlers, server, receiver, key):
    spec = SPECS[key]
    handler = handlers[key]
    address = start_address(key)

    dispatch(server, address, *spec["too_few"])

    #--------------------------------------------------------------------------------
    # API.md's "Sending fewer than <n> is a malformed request and answers on
    # /live/error" for the scene/clip/clip_slot listen pairs: the missing
    # index raises IndexError while casting, before any dict is written.
    #--------------------------------------------------------------------------------
    messages = receiver.drain()
    assert len(messages) == 1
    error_address, params = messages[0]
    assert error_address == "/live/error"
    assert params[0] == "request"
    assert params[1] == address

    assert handler.listener_functions == {}
    assert handler.listener_objects == {}
