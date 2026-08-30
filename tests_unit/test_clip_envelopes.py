"""
/live/clip/get/has_envelopes and its listen pair, dispatched end to end
through the production ClipHandler on the production OSCServer.

`has_envelopes` is a plain entry in clip.py's `properties_r`, so there is no
handler of its own to test — what is under test is that the entry actually
produces the three addresses, that the reply carries the clip identity the
query named, and that the listen pair subscribes to the LOM member of that
exact name and pushes on the *get* address. A property added to the wrong list
(`properties_rw`) or misspelled fails here rather than in Live.

The wire *value* is pinned too. Live's `Clip.has_envelopes` is a Python bool
and the vendored builder tags a bool `T`/`F` rather than as an int, so a client
decodes `True`/`False` — which compare equal to the `1`/`0` API.md documents,
but are not the same tag. Pinned so a later change to the builder's bool
handling shows up as a failing test and not as a client-side surprise.

Live-free: the clip is a fake, and only the flag and the listener hooks on it
matter.
"""

import pytest

from .conftest import dispatch, load_clip_module, load_handler_module


class FakeManager:
    """`osc_server` is the only attribute AbletonOSCHandler reads off it."""

    def __init__(self, osc_server):
        self.osc_server = osc_server


class FakeClip:
    """
    A clip carrying the flag and the LOM's listener hooks for it. The hooks are
    named `add_has_envelopes_listener` / `remove_has_envelopes_listener`
    because that is the name `_start_listen` derives from the property; a
    property registered under any other spelling raises AttributeError here.
    """

    def __init__(self, has_envelopes=False):
        self.has_envelopes = has_envelopes
        self.listeners = []

    def add_has_envelopes_listener(self, callback):
        self.listeners.append(callback)

    def remove_has_envelopes_listener(self, callback):
        self.listeners.remove(callback)

    def fire(self, value):
        """Live gaining the clip's first envelope: flag flips, then it notifies."""
        self.has_envelopes = value
        for callback in list(self.listeners):
            callback()


class FakeClipSlot:
    def __init__(self, clip):
        self.clip = clip
        self.has_clip = clip is not None


class FakeTrack:
    def __init__(self, clip_slots):
        self.clip_slots = list(clip_slots)


class FakeSong:
    def __init__(self, tracks):
        self.tracks = list(tracks)


def replies(messages, address):
    return [params for addr, params in messages if addr == address]


@pytest.fixture
def clip():
    return FakeClip(has_envelopes=False)


@pytest.fixture
def handler(server, clip):
    """
    Track 0 holds the clip under test at slot 0 and a second, envelope-free
    clip at slot 1, so a handler that ignored the clip index would still have
    to answer the wrong value to pass.
    """
    load_handler_module()
    clip_module = load_clip_module()
    h = clip_module.ClipHandler(FakeManager(server))
    h.song = FakeSong([FakeTrack([FakeClipSlot(clip),
                                  FakeClipSlot(FakeClip(has_envelopes=False))])])
    return h


#--------------------------------------------------------------------------------
# The getter
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("flag", [False, True])
def test_get_has_envelopes_replies_with_the_clip_identity_and_the_flag(
        handler, server, receiver, clip, flag):
    clip.has_envelopes = flag
    dispatch(server, "/live/clip/get/has_envelopes", 0, 0)
    assert replies(receiver.drain(), "/live/clip/get/has_envelopes") == [(0, 0, flag)]


def test_get_has_envelopes_answers_the_clip_the_query_named(handler, server, receiver, clip):
    """Slot 1 is a different clip; its answer must not be slot 0's."""
    clip.has_envelopes = True
    dispatch(server, "/live/clip/get/has_envelopes", 0, 1)
    assert replies(receiver.drain(), "/live/clip/get/has_envelopes") == [(0, 1, False)]


def test_has_envelopes_is_read_only(handler, server, receiver, clip):
    """
    It belongs in `properties_r`, not `properties_rw`: Live's member is
    read-only, so no /live/clip/set/has_envelopes may exist. An address that was
    never registered is logged and dropped — nothing at all on the wire, not
    even /live/error — so the flag is unchanged and the caller sees silence.
    """
    dispatch(server, "/live/clip/set/has_envelopes", 0, 0, 1)
    assert receiver.drain() == []
    assert clip.has_envelopes is False


#--------------------------------------------------------------------------------
# The listen pair
#--------------------------------------------------------------------------------

def test_start_listen_subscribes_and_sends_the_current_value(handler, server, receiver, clip):
    dispatch(server, "/live/clip/start_listen/has_envelopes", 0, 0)
    #--------------------------------------------------------------------------------
    # _start_listen sends the current value immediately, so a client that
    # subscribes never has to also issue a get to learn where it started.
    #--------------------------------------------------------------------------------
    assert replies(receiver.drain(), "/live/clip/get/has_envelopes") == [(0, 0, False)]
    assert len(clip.listeners) == 1


def test_push_arrives_on_the_get_address_when_the_first_envelope_lands(
        handler, server, receiver, clip):
    dispatch(server, "/live/clip/start_listen/has_envelopes", 0, 0)
    receiver.drain()
    clip.fire(True)
    assert replies(receiver.drain(), "/live/clip/get/has_envelopes") == [(0, 0, True)]


def test_stop_listen_unsubscribes(handler, server, receiver, clip):
    dispatch(server, "/live/clip/start_listen/has_envelopes", 0, 0)
    dispatch(server, "/live/clip/stop_listen/has_envelopes", 0, 0)
    receiver.drain()
    assert clip.listeners == []
    clip.fire(True)
    assert replies(receiver.drain(), "/live/clip/get/has_envelopes") == []
