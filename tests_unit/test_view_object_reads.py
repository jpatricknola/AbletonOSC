"""
The four object-valued `Song.View` getters — /live/view/get/selected_chain,
get/selected_parameter, get/mod_mapping_device and get/mod_mapping_parameter
— dispatched end to end through the real `ViewHandler`.

`ViewHandler.init_api` binds `self.song.view` into its four listen
registrations while the constructor is still running, so the handler is built
through conftest's `bind_song()` (see test_song_object_reads.py for why), over
the empty `Live` stub that satisfies view.py's module-scope `import Live` —
the only dereferences are Live.Application.get_application(), inside
show_view / get_is_view_visible / hide_view, and no test here dispatches
those.

What this pins is the glue: the addresses as registered, the *absence* of the
listen pairs (all four are get-only in this fork), the reply arity and the
int-ness of every index, and that a resolution failure arrives as a structured
/live/error rather than a malformed reply. The resolver matrix underneath is
test_track_identity.py's; only the LOM objects here are fakes, and the
canonical_parent shapes they assume are the ones API.md § "Object-valued
reads" still marks ⚠️.
"""

import pytest

from .conftest import bind_song, dispatch, load_view_module

SELECTED_CHAIN = "/live/view/get/selected_chain"
SELECTED_PARAMETER = "/live/view/get/selected_parameter"
MOD_MAPPING_DEVICE = "/live/view/get/mod_mapping_device"
MOD_MAPPING_PARAMETER = "/live/view/get/mod_mapping_parameter"


class FakeManager:
    """`osc_server` is the only attribute AbletonOSCHandler reads off it."""

    def __init__(self, osc_server):
        self.osc_server = osc_server


class FakeParameter:
    def __init__(self, name, canonical_parent=None):
        self.name = name
        self.canonical_parent = canonical_parent


class FakeDevice:
    def __init__(self, name, canonical_parent=None, parameters=(), chains=()):
        self.name = name
        self.canonical_parent = canonical_parent
        self.parameters = list(parameters)
        self.chains = list(chains)
        for parameter in self.parameters:
            parameter.canonical_parent = self


class FakeChain:
    def __init__(self, name, canonical_parent=None, devices=()):
        self.name = name
        self.canonical_parent = canonical_parent
        self.devices = list(devices)


class FakeMixerDevice:
    """
    Track.mixer_device: the owner of `volume`, `panning` and the sends.

    It is *not* a member of `track.devices`, which is exactly the case
    parameter_identity answers with (category, track_index, -1, -1) — but its
    own `canonical_parent` is the track, so the ascent from the parameter
    still finds one. Without that link the mixer case would raise instead of
    answering.
    """

    def __init__(self, track):
        self.canonical_parent = track
        self.volume = FakeParameter("Volume", canonical_parent=self)


class FakeTrackView:
    def __init__(self, selected_device=None):
        self.selected_device = selected_device


class FakeTrack:
    def __init__(self, name):
        self.name = name
        self.devices = []
        self.view = FakeTrackView()
        self.mixer_device = FakeMixerDevice(self)

    def add_device(self, device):
        device.canonical_parent = self
        self.devices.append(device)
        return device


class FakeSongView:
    """
    Carries the members ViewHandler reads plus the two upstream listen pairs
    it registers — `selected_track` and `selected_scene` — so the four
    registrations bind against something real should a later test dispatch
    them. None here does; the four addresses under test have no listen pair
    at all, which is itself asserted below.
    """

    def __init__(self):
        self.selected_track = None
        self.selected_scene = None
        self.selected_chain = None
        self.selected_parameter = None
        self.mod_mapping_device = None
        self.mod_mapping_parameter = None
        self.listeners = {"selected_track": [], "selected_scene": []}

    def add_selected_track_listener(self, callback):
        self.listeners["selected_track"].append(callback)

    def remove_selected_track_listener(self, callback):
        self.listeners["selected_track"].remove(callback)

    def add_selected_scene_listener(self, callback):
        self.listeners["selected_scene"].append(callback)

    def remove_selected_scene_listener(self, callback):
        self.listeners["selected_scene"].remove(callback)


class FakeSong:
    def __init__(self, tracks, return_tracks, master_track, scenes=()):
        self.tracks = list(tracks)
        self.return_tracks = list(return_tracks)
        self.master_track = master_track
        self.scenes = list(scenes)
        self.view = FakeSongView()


def errors(messages):
    return [params for address, params in messages if address == "/live/error"]


def replies(messages, address):
    return [params for addr, params in messages if addr == address]


def build_song():
    """
    Track 1 ("bass") holds:

      devices[0]  filter   — a plain device with two parameters
      devices[1]  rack     — chains[0] holds a nested device and a nested rack

    so a chain, a parameter and a device are each available in a top-level and
    a nested form. The return track and the master each carry one device with
    one parameter, for the two non-regular categories.
    """
    drums = FakeTrack("drums")

    bass = FakeTrack("bass")
    bass.add_device(FakeDevice("filter", parameters=[FakeParameter("Freq"),
                                                     FakeParameter("Res")]))
    rack = bass.add_device(FakeDevice("rack"))
    chain = FakeChain("chain 1", canonical_parent=rack)
    rack.chains = [chain]

    nested = FakeDevice("nested reverb", canonical_parent=chain,
                        parameters=[FakeParameter("Decay")])
    inner_rack = FakeDevice("inner rack", canonical_parent=chain)
    inner_chain = FakeChain("inner chain", canonical_parent=inner_rack)
    inner_rack.chains = [inner_chain]
    chain.devices = [nested, inner_rack]

    returns = FakeTrack("A Reverb")
    returns.add_device(FakeDevice("return reverb", parameters=[FakeParameter("Dry/Wet")]))

    master = FakeTrack("master")
    master.add_device(FakeDevice("master limiter", parameters=[FakeParameter("Ceiling")]))

    song = FakeSong([drums, bass], [returns], master)
    song.rack = rack
    song.chain = chain
    song.nested_device = nested
    song.inner_chain = inner_chain
    return song


@pytest.fixture
def song():
    return build_song()


@pytest.fixture
def view_handler(server, song):
    handler_class = bind_song(load_view_module().ViewHandler, song)
    return handler_class(FakeManager(server))


#--------------------------------------------------------------------------------
# Registration
#--------------------------------------------------------------------------------

def test_all_four_getters_are_registered(view_handler, server):
    for address in (SELECTED_CHAIN, SELECTED_PARAMETER,
                    MOD_MAPPING_DEVICE, MOD_MAPPING_PARAMETER):
        assert address in server._callbacks


@pytest.mark.parametrize("prop", ["selected_chain", "selected_parameter",
                                  "mod_mapping_device", "mod_mapping_parameter"])
def test_the_four_object_getters_have_no_listen_pair(view_handler, server, prop):
    """
    Get-only in this fork, per API.md: all four members are observable and two
    are LOM-writable, but no consumer has named a listener yet. A start_listen
    that existed would push raw LOM objects unless it carried a getter=, so
    the absence is the contract, asserted the way
    test_object_reads.py::test_group_track_has_no_listen_pair asserts its own.
    """
    for half in ("start_listen", "stop_listen"):
        assert "/live/view/%s/%s" % (half, prop) not in server._callbacks


#--------------------------------------------------------------------------------
# selected_chain
#--------------------------------------------------------------------------------

def test_selected_chain_reports_none_when_nothing_is_selected(view_handler, server, receiver):
    dispatch(server, SELECTED_CHAIN)
    assert receiver.drain() == [(SELECTED_CHAIN, ("none", -1, -1, -1))]


def test_selected_chain_of_a_top_level_rack(view_handler, song, server, receiver):
    song.view.selected_chain = song.chain
    dispatch(server, SELECTED_CHAIN)
    assert receiver.drain() == [(SELECTED_CHAIN, ("track", 1, 1, 0))]


def test_selected_chain_of_a_nested_rack_loses_only_the_device_index(view_handler, song,
                                                                    server, receiver):
    """
    The rack that owns this chain is itself inside another rack's chain, so it
    has no index in `track.devices` — but the chain's index within that rack
    is still resolved.
    """
    song.view.selected_chain = song.inner_chain
    dispatch(server, SELECTED_CHAIN)
    assert receiver.drain() == [(SELECTED_CHAIN, ("track", 1, -1, 0))]


#--------------------------------------------------------------------------------
# selected_parameter
#--------------------------------------------------------------------------------

def test_selected_parameter_reports_none_when_nothing_is_selected(view_handler, server, receiver):
    dispatch(server, SELECTED_PARAMETER)
    assert receiver.drain() == [(SELECTED_PARAMETER, ("none", -1, -1, -1))]


def test_selected_parameter_of_a_top_level_device(view_handler, song, server, receiver):
    song.view.selected_parameter = song.tracks[1].devices[0].parameters[1]
    dispatch(server, SELECTED_PARAMETER)
    assert receiver.drain() == [(SELECTED_PARAMETER, ("track", 1, 0, 1))]


def test_selected_parameter_on_the_mixer_has_no_device_index(view_handler, song,
                                                             server, receiver):
    """
    `mixer_device` is not a member of `track.devices`, so there is no device
    index to report the parameter under — but the owning track is known.
    """
    song.view.selected_parameter = song.tracks[1].mixer_device.volume
    dispatch(server, SELECTED_PARAMETER)
    assert receiver.drain() == [(SELECTED_PARAMETER, ("track", 1, -1, -1))]


def test_selected_parameter_of_a_nested_device_has_no_device_index(view_handler, song,
                                                                   server, receiver):
    song.view.selected_parameter = song.nested_device.parameters[0]
    dispatch(server, SELECTED_PARAMETER)
    assert receiver.drain() == [(SELECTED_PARAMETER, ("track", 1, -1, -1))]


def test_selected_parameter_on_a_return_track(view_handler, song, server, receiver):
    song.view.selected_parameter = song.return_tracks[0].devices[0].parameters[0]
    dispatch(server, SELECTED_PARAMETER)
    assert receiver.drain() == [(SELECTED_PARAMETER, ("return_track", 0, 0, 0))]


def test_selected_parameter_on_the_master(view_handler, song, server, receiver):
    song.view.selected_parameter = song.master_track.devices[0].parameters[0]
    dispatch(server, SELECTED_PARAMETER)
    assert receiver.drain() == [(SELECTED_PARAMETER, ("master", 0, 0, 0))]


#--------------------------------------------------------------------------------
# mod_mapping_device / mod_mapping_parameter
#--------------------------------------------------------------------------------

def test_mod_mapping_device_reports_none_when_idle(view_handler, server, receiver):
    dispatch(server, MOD_MAPPING_DEVICE)
    assert receiver.drain() == [(MOD_MAPPING_DEVICE, ("none", -1, -1))]


def test_mod_mapping_device_reports_a_top_level_device(view_handler, song, server, receiver):
    song.view.mod_mapping_device = song.tracks[1].devices[0]
    dispatch(server, MOD_MAPPING_DEVICE)
    assert receiver.drain() == [(MOD_MAPPING_DEVICE, ("track", 1, 0))]


def test_mod_mapping_parameter_reports_none_when_idle(view_handler, server, receiver):
    dispatch(server, MOD_MAPPING_PARAMETER)
    assert receiver.drain() == [(MOD_MAPPING_PARAMETER, ("none", -1, -1, -1))]


def test_mod_mapping_parameter_reports_a_top_level_parameter(view_handler, song,
                                                             server, receiver):
    song.view.mod_mapping_parameter = song.tracks[1].devices[0].parameters[0]
    dispatch(server, MOD_MAPPING_PARAMETER)
    assert receiver.drain() == [(MOD_MAPPING_PARAMETER, ("track", 1, 0, 0))]


#--------------------------------------------------------------------------------
# Shared shape and failure
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("address, prop, arity", [
    (SELECTED_CHAIN, "selected_chain", 4),
    (SELECTED_PARAMETER, "selected_parameter", 4),
    (MOD_MAPPING_DEVICE, "mod_mapping_device", 3),
    (MOD_MAPPING_PARAMETER, "mod_mapping_parameter", 4),
])
def test_every_reply_is_a_category_and_int_indices(view_handler, song, server, receiver,
                                                   address, prop, arity):
    """
    Fixed arity and int indices for all four, in a resolvable state — the
    shape Seshat decodes positionally. Floats reaching the wire here would be
    a silent decode change.
    """
    song.view.selected_chain = song.chain
    song.view.selected_parameter = song.tracks[1].devices[0].parameters[0]
    song.view.mod_mapping_device = song.tracks[1].devices[0]
    song.view.mod_mapping_parameter = song.tracks[1].devices[0].parameters[0]

    dispatch(server, address)
    params = replies(receiver.drain(), address)[0]
    assert len(params) == arity
    assert type(params[0]) is str
    assert [type(field) for field in params[1:]] == [int] * (arity - 1)


def test_an_unresolvable_object_is_a_structured_error(view_handler, song, server, receiver):
    """
    One of the four is enough: all four route through the same
    OSCServer._dispatch catch, and the resolvers they share are
    test_track_identity.py's subject. An object whose canonical_parent ascent
    finds no track raises, and the failure arrives on the request path with
    nothing on the getter's address.
    """
    song.view.selected_parameter = FakeParameter("orphan", canonical_parent=None)
    dispatch(server, SELECTED_PARAMETER)
    messages = receiver.drain()
    assert replies(messages, SELECTED_PARAMETER) == []
    assert len(errors(messages)) == 1
    assert errors(messages)[0][0] == "request"
    assert errors(messages)[0][1] == SELECTED_PARAMETER
