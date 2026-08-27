"""
The selected-track identity resolver, `abletonosc/track_identity.py`.

This drives the *real* shipped module, imported through conftest's synthetic
root package — it imports nothing Live-side, exactly so it can be. It is the
whole of the logic behind /live/view/get/selected_track_identity and the
reworked /live/view/get/selected_track, get/selected_clip and
get/selected_device: view.py itself imports `Live` at module scope and stays
out of reach, so its registrations and closures are covered by the plan's
Live verification checks, not here.

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
