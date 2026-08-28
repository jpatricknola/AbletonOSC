"""
The selected-track identity resolver, `abletonosc/track_identity.py`.

This drives the *real* shipped module, imported through conftest's synthetic
root package — it imports nothing Live-side, exactly so it can be. It is the
whole of the logic behind /live/view/get/selected_track_identity and the
reworked /live/view/get/selected_track, get/selected_clip and
get/selected_device. Kept parameterised on `song` rather than closed over
`self`, it is testable as plain functions; the ViewHandler glue that calls it
— the registrations, the closures and the replies that reach the socket — is
tests_unit/test_view_object_reads.py's subject, and the SongHandler half is
tests_unit/test_song_object_reads.py's.

The fakes below use plain objects with default identity-based `==`, matching
the LOM's object-identity equality. Whether Live's Boost.Python wrappers
really compare equal across separately obtained references for the master
and for return tracks is the one thing these tests cannot settle — see the
plan's open question 1.
"""

import pytest

from .conftest import load_module


@pytest.fixture
def track_identity():
    return load_module("abletonosc.track_identity")


class FakeDevice:
    def __init__(self, name):
        self.name = name


class FakeTrackView:
    def __init__(self, selected_device=None):
        self.selected_device = selected_device


class FakeTrack:
    def __init__(self, name, devices=(), selected_device=None):
        self.name = name
        self.devices = list(devices)
        self.view = FakeTrackView(selected_device)


class FakeSongView:
    def __init__(self, selected_track=None):
        self.selected_track = selected_track


class FakeSong:
    def __init__(self, tracks=(), return_tracks=(), master_track=None,
                 selected_track=None):
        self.tracks = list(tracks)
        self.return_tracks = list(return_tracks)
        self.master_track = master_track
        self.view = FakeSongView(selected_track)


def build_song(selected=None, n_tracks=3, n_returns=2):
    tracks = [FakeTrack("track %d" % i) for i in range(n_tracks)]
    returns = [FakeTrack("return %d" % i) for i in range(n_returns)]
    master = FakeTrack("master")
    song = FakeSong(tracks, returns, master)
    song.view.selected_track = selected if selected is not None else (tracks[0] if tracks else master)
    return song


#--------------------------------------------------------------------------------
# 1. identify_track — one identity per category
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("index", [0, 1, 2])
def test_regular_track_resolves_to_its_index(track_identity, index):
    song = build_song()
    assert track_identity.identify_track(song, song.tracks[index]) == ("track", index)


@pytest.mark.parametrize("index", [0, 1])
def test_return_track_resolves_in_its_own_index_space(track_identity, index):
    song = build_song(n_returns=2)
    #--------------------------------------------------------------------------------
    # Return indices are 0-based within song.return_tracks, a separate index
    # space from song.tracks — the same contract /live/return_track/* uses.
    #--------------------------------------------------------------------------------
    assert track_identity.identify_track(song, song.return_tracks[index]) == ("return_track", index)


def test_master_always_reports_index_zero(track_identity):
    song = build_song()
    assert track_identity.identify_track(song, song.master_track) == ("master", 0)


def test_master_resolves_with_no_tracks_at_all(track_identity):
    song = FakeSong(tracks=(), return_tracks=(), master_track=FakeTrack("master"))
    assert track_identity.identify_track(song, song.master_track) == ("master", 0)


def test_unknown_object_raises_value_error(track_identity):
    song = build_song()
    with pytest.raises(ValueError):
        track_identity.identify_track(song, FakeTrack("orphan"))


def test_none_raises_value_error(track_identity):
    """
    None is an unknown object like any other: a loud /live/error, never a
    sentinel that would be indistinguishable from an answer.
    """
    song = build_song()
    with pytest.raises(ValueError):
        track_identity.identify_track(song, None)


def test_none_raises_even_when_master_is_none(track_identity):
    """
    The master check must not let `None == None` report ("master", 0).
    """
    song = FakeSong(tracks=(), return_tracks=(), master_track=None)
    with pytest.raises(ValueError):
        track_identity.identify_track(song, None)


def test_value_error_survives_an_unrepresentable_track(track_identity):
    class Unrepresentable:
        def __repr__(self):
            raise RuntimeError("no repr for you")

    song = build_song()
    with pytest.raises(ValueError):
        track_identity.identify_track(song, Unrepresentable())


#--------------------------------------------------------------------------------
# 2. selected_track_identity / selected_track_index
#--------------------------------------------------------------------------------

def test_selected_track_identity_reads_the_song_view(track_identity):
    song = build_song()
    song.view.selected_track = song.return_tracks[1]
    assert track_identity.selected_track_identity(song) == ("return_track", 1)


def test_selected_track_index_for_a_regular_track(track_identity):
    song = build_song()
    song.view.selected_track = song.tracks[2]
    assert track_identity.selected_track_index(song) == 2


@pytest.mark.parametrize("category", ["return_track", "master"])
def test_selected_track_index_is_minus_one_outside_song_tracks(track_identity, category):
    song = build_song()
    song.view.selected_track = (song.return_tracks[0] if category == "return_track"
                                else song.master_track)
    #--------------------------------------------------------------------------------
    # Upstream raises ValueError here, which is what kills the reply *and*
    # the selected_track listener push.
    #--------------------------------------------------------------------------------
    assert track_identity.selected_track_index(song) == -1


#--------------------------------------------------------------------------------
# 3. selected_device_indices
#--------------------------------------------------------------------------------

def test_selected_device_reports_both_indices(track_identity):
    song = build_song()
    devices = [FakeDevice("a"), FakeDevice("b"), FakeDevice("c")]
    track = song.tracks[1]
    track.devices = devices
    track.view.selected_device = devices[2]
    song.view.selected_track = track
    assert track_identity.selected_device_indices(song) == (1, 2)


def test_no_device_selected_reports_minus_one(track_identity):
    song = build_song()
    track = song.tracks[0]
    track.devices = [FakeDevice("a")]
    track.view.selected_device = None
    song.view.selected_track = track
    assert track_identity.selected_device_indices(song) == (0, -1)


def test_device_absent_from_the_chain_reports_minus_one(track_identity):
    """
    `track.view.selected_device` can be a device nested inside a rack chain,
    which is not a member of `track.devices`. Upstream raises ValueError on
    exactly this; the fork answers "no top-level device to report".
    """
    song = build_song()
    track = song.tracks[2]
    track.devices = [FakeDevice("rack")]
    track.view.selected_device = FakeDevice("nested in the rack's chain")
    song.view.selected_track = track
    assert track_identity.selected_device_indices(song) == (2, -1)


def test_empty_device_chain_reports_minus_one(track_identity):
    song = build_song()
    track = song.tracks[0]
    track.devices = []
    track.view.selected_device = None
    song.view.selected_track = track
    assert track_identity.selected_device_indices(song) == (0, -1)


@pytest.mark.parametrize("category", ["return_track", "master"])
def test_device_indices_are_minus_one_for_return_and_master(track_identity, category):
    song = build_song()
    track = song.return_tracks[0] if category == "return_track" else song.master_track
    device = FakeDevice("reverb")
    track.devices = [device]
    #--------------------------------------------------------------------------------
    # Even with a device genuinely selected: there is no regular-track index
    # to report it under, which is A-3's job, not this item's.
    #--------------------------------------------------------------------------------
    track.view.selected_device = device
    song.view.selected_track = track
    assert track_identity.selected_device_indices(song) == (-1, -1)


def test_device_indices_raise_for_an_unknown_selection(track_identity):
    song = build_song()
    song.view.selected_track = FakeTrack("orphan")
    with pytest.raises(ValueError):
        track_identity.selected_device_indices(song)


#--------------------------------------------------------------------------------
# 4. The category strings are the address-family prefixes
#--------------------------------------------------------------------------------

def test_category_constants_match_the_address_families(track_identity):
    assert track_identity.CATEGORY_TRACK == "track"
    assert track_identity.CATEGORY_RETURN == "return_track"
    assert track_identity.CATEGORY_MASTER == "master"
    assert track_identity.NO_INDEX == -1


#--------------------------------------------------------------------------------
# 5. A-4: the object-valued read resolvers
#
# The fakes below add the LOM attributes those resolvers reach for —
# `canonical_parent`, `devices`, `parameters`, `chains`, `group_track` — to
# the same plain-object style as above. What they cannot settle is whether
# Live's own wrappers really return the parents assumed here (open question 1)
# or compare cross-class with `==` without raising (open question 2); those
# are the plan's Live verification checks 3, 6 and 7.
#--------------------------------------------------------------------------------

class FakeParameter:
    def __init__(self, name, canonical_parent=None):
        self.name = name
        self.canonical_parent = canonical_parent


class FakeParentedDevice:
    """A device that knows its parent — a track, or a rack's chain."""

    def __init__(self, name, canonical_parent=None, parameters=(), chains=()):
        self.name = name
        self.canonical_parent = canonical_parent
        self.parameters = list(parameters)
        self.chains = list(chains)


class FakeChain:
    def __init__(self, name, canonical_parent=None, devices=()):
        self.name = name
        self.canonical_parent = canonical_parent
        self.devices = list(devices)


def track_of(song, category, index=0):
    if category == "track":
        return song.tracks[index]
    if category == "return_track":
        return song.return_tracks[index]
    return song.master_track


#--------------------------------------------------------------------------------
# 5a. group_track_index
#--------------------------------------------------------------------------------

def test_ungrouped_track_reports_minus_one(track_identity):
    song = build_song()
    song.tracks[0].group_track = None
    assert track_identity.group_track_index(song, song.tracks[0]) == -1


def test_grouped_track_reports_the_group_index(track_identity):
    song = build_song()
    group = song.tracks[0]
    song.tracks[2].group_track = group
    assert track_identity.group_track_index(song, song.tracks[2]) == 0


def test_group_track_outside_song_tracks_raises(track_identity):
    """
    Live has no such state. A -1 here would read as "ungrouped", so it is a
    loud /live/error instead.
    """
    song = build_song()
    song.tracks[1].group_track = FakeTrack("a group in no song")
    with pytest.raises(ValueError):
        track_identity.group_track_index(song, song.tracks[1])


#--------------------------------------------------------------------------------
# 5b. owning_track_identity — the canonical_parent ascent
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("category", ["track", "return_track", "master"])
def test_ascent_finds_the_owning_track_in_every_category(track_identity, category):
    song = build_song()
    track = track_of(song, category, 1 if category == "track" else 0)
    device = FakeParentedDevice("reverb", canonical_parent=track)
    expected = (category, 1 if category == "track" else 0)
    assert track_identity.owning_track_identity(song, device) == expected


def test_ascent_climbs_chain_then_rack_then_track(track_identity):
    song = build_song()
    track = song.tracks[2]
    rack = FakeParentedDevice("rack", canonical_parent=track)
    chain = FakeChain("chain 1", canonical_parent=rack)
    nested = FakeParentedDevice("nested", canonical_parent=chain)
    assert track_identity.owning_track_identity(song, nested) == ("track", 2)


def test_ascent_from_a_track_itself_is_that_track(track_identity):
    song = build_song()
    assert track_identity.owning_track_identity(song, song.tracks[0]) == ("track", 0)


def test_parentless_object_raises(track_identity):
    song = build_song()
    with pytest.raises(ValueError):
        track_identity.owning_track_identity(song, FakeParentedDevice("orphan"))


def test_ascent_terminates_on_a_cycle(track_identity):
    """
    The cap is what keeps a cyclic parent chain from hanging Live's UI
    thread: this call must return (by raising), not spin.
    """
    song = build_song()
    device = FakeParentedDevice("self-parented")
    device.canonical_parent = device
    with pytest.raises(ValueError):
        track_identity.owning_track_identity(song, device)


#--------------------------------------------------------------------------------
# 5c. device_identity
#--------------------------------------------------------------------------------

def test_device_identity_of_none_is_the_none_triple(track_identity):
    song = build_song()
    assert track_identity.device_identity(song, None) == ("none", -1, -1)


@pytest.mark.parametrize("category", ["track", "return_track", "master"])
def test_device_identity_of_a_top_level_device(track_identity, category):
    song = build_song()
    track = track_of(song, category, 1 if category == "track" else 0)
    device = FakeParentedDevice("operator", canonical_parent=track)
    track.devices = [FakeParentedDevice("eq", canonical_parent=track), device]
    expected = (category, 1 if category == "track" else 0, 1)
    assert track_identity.device_identity(song, device) == expected


def test_nested_device_reports_minus_one_for_the_device_index(track_identity):
    song = build_song()
    track = song.tracks[0]
    rack = FakeParentedDevice("rack", canonical_parent=track)
    track.devices = [rack]
    chain = FakeChain("chain", canonical_parent=rack)
    nested = FakeParentedDevice("nested", canonical_parent=chain)
    assert track_identity.device_identity(song, nested) == ("track", 0, -1)


#--------------------------------------------------------------------------------
# 5d. parameter_identity
#--------------------------------------------------------------------------------

def test_parameter_identity_of_none_is_the_none_quad(track_identity):
    song = build_song()
    assert track_identity.parameter_identity(song, None) == ("none", -1, -1, -1)


def test_parameter_of_a_top_level_device_resolves_fully(track_identity):
    song = build_song()
    track = song.tracks[1]
    device = FakeParentedDevice("operator", canonical_parent=track)
    parameters = [FakeParameter("on", device), FakeParameter("volume", device)]
    device.parameters = parameters
    track.devices = [device]
    assert track_identity.parameter_identity(song, parameters[1]) == ("track", 1, 0, 1)


def test_mixer_parameter_reports_no_device(track_identity):
    """
    `track.mixer_device.volume` is a DeviceParameter whose parent is the
    MixerDevice, which is not a member of `track.devices`.
    """
    song = build_song()
    track = song.tracks[0]
    mixer = FakeParentedDevice("mixer", canonical_parent=track)
    volume = FakeParameter("volume", mixer)
    mixer.parameters = [volume]
    track.devices = [FakeParentedDevice("eq", canonical_parent=track)]
    assert track_identity.parameter_identity(song, volume) == ("track", 0, -1, -1)


def test_nested_device_parameter_reports_no_device(track_identity):
    song = build_song()
    track = song.tracks[2]
    rack = FakeParentedDevice("rack", canonical_parent=track)
    track.devices = [rack]
    chain = FakeChain("chain", canonical_parent=rack)
    nested = FakeParentedDevice("nested", canonical_parent=chain)
    parameter = FakeParameter("cutoff", nested)
    nested.parameters = [parameter]
    assert track_identity.parameter_identity(song, parameter) == ("track", 2, -1, -1)


#--------------------------------------------------------------------------------
# 5e. chain_identity
#--------------------------------------------------------------------------------

def test_chain_identity_of_none_is_the_none_quad(track_identity):
    song = build_song()
    assert track_identity.chain_identity(song, None) == ("none", -1, -1, -1)


def test_chain_of_a_top_level_rack_resolves_fully(track_identity):
    song = build_song()
    track = song.tracks[1]
    rack = FakeParentedDevice("rack", canonical_parent=track)
    chains = [FakeChain("a", rack), FakeChain("b", rack)]
    rack.chains = chains
    track.devices = [FakeParentedDevice("eq", canonical_parent=track), rack]
    assert track_identity.chain_identity(song, chains[1]) == ("track", 1, 1, 1)


def test_chain_of_a_nested_rack_reports_no_device_index(track_identity):
    song = build_song()
    track = song.tracks[0]
    outer = FakeParentedDevice("outer rack", canonical_parent=track)
    track.devices = [outer]
    outer_chain = FakeChain("outer chain", canonical_parent=outer)
    outer.chains = [outer_chain]
    inner = FakeParentedDevice("inner rack", canonical_parent=outer_chain)
    inner_chains = [FakeChain("x", inner), FakeChain("y", inner)]
    inner.chains = inner_chains
    assert track_identity.chain_identity(song, inner_chains[1]) == ("track", 0, -1, 1)


def test_chain_absent_from_its_racks_chains_reports_minus_one(track_identity):
    """
    The drum-rack shape, if a DrumChain turns out to live only under
    `drum_pads[*].chains` (open question 5): the reply is still well formed.
    """
    song = build_song()
    track = song.tracks[0]
    rack = FakeParentedDevice("drum rack", canonical_parent=track)
    rack.chains = []
    track.devices = [rack]
    orphan_chain = FakeChain("drum chain", canonical_parent=rack)
    assert track_identity.chain_identity(song, orphan_chain) == ("track", 0, 0, -1)


#--------------------------------------------------------------------------------
# 5f. resolve_track / resolve_device — where "-1 is never an argument" is
#     enforcement rather than documentation
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("category,index", [("track", 2), ("return_track", 1), ("master", 0)])
def test_resolve_track_happy_path(track_identity, category, index):
    song = build_song()
    assert track_identity.resolve_track(song, category, index) is track_of(song, category, index)


@pytest.mark.parametrize("category,index", [
    ("none", 0),
    ("none", -1),
    ("tracks", 0),
    ("", 0),
    ("track", -1),
    ("track", 3),
    ("return_track", -1),
    ("return_track", 2),
    ("master", 1),
    ("master", -1),
])
def test_resolve_track_rejects(track_identity, category, index):
    song = build_song()
    with pytest.raises(ValueError):
        track_identity.resolve_track(song, category, index)


def test_resolve_track_negative_index_is_not_python_indexing(track_identity):
    """
    `song.tracks[-1]` would be the last track. A new address has no
    upstream-compatibility reason to inherit that.
    """
    song = build_song()
    with pytest.raises(ValueError):
        track_identity.resolve_track(song, "track", -1)


@pytest.mark.parametrize("category", ["track", "return_track", "master"])
def test_resolve_device_happy_path(track_identity, category):
    song = build_song()
    track = track_of(song, category, 0)
    devices = [FakeParentedDevice("a", track), FakeParentedDevice("b", track)]
    track.devices = devices
    assert track_identity.resolve_device(song, category, 0, 1) is devices[1]


@pytest.mark.parametrize("device_index", [-1, 2, 99])
def test_resolve_device_rejects_out_of_range(track_identity, device_index):
    song = build_song()
    track = song.tracks[0]
    track.devices = [FakeParentedDevice("a", track), FakeParentedDevice("b", track)]
    with pytest.raises(ValueError):
        track_identity.resolve_device(song, "track", 0, device_index)


def test_resolve_device_rejects_the_none_category(track_identity):
    song = build_song()
    with pytest.raises(ValueError):
        track_identity.resolve_device(song, "none", -1, -1)


def test_category_none_is_declared(track_identity):
    assert track_identity.CATEGORY_NONE == "none"
