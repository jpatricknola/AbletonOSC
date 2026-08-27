#--------------------------------------------------------------------------------
# Resolving a LOM track object back to the address family that reaches it.
#
# It lives in its own module, importing nothing but `typing`, for the same
# reason track_callback.py does: view.py imports `Live` at module scope and
# therefore cannot be imported outside Live, so any resolution logic written
# as a closure inside ViewHandler.init_api could never be reached by
# tests_unit/. Parameterised on `song` instead of closed over `self`, it is
# the real shipped code under test in tests_unit/test_track_identity.py.
#
# Seshat divergence — see SESHAT.md. Upstream has no equivalent: its view
# getters resolve the selection through `song.tracks` alone, which raises
# ValueError the moment a return track or the master is selected.
#
# One canonical identity for any track: (category, index), where `category`
# is exactly the OSC address-family prefix that reaches that track --
#
#   "track"        -> /live/track/*, /live/view/set/selected_track
#   "return_track" -> /live/return_track/*  (index within song.return_tracks)
#   "master"       -> /live/master/*        (a single object, always index 0)
#
# -- so a reply is directly actionable: the category names the address family
# to use next. A-3 (return/master Track parity) and A-4 (object-valued read
# helpers) are both specified against this representation, and the inverse
# resolver ((category, index) -> track object) belongs here when A-3 needs it.
#--------------------------------------------------------------------------------

from typing import Any, Tuple

CATEGORY_TRACK = "track"
CATEGORY_RETURN = "return_track"
CATEGORY_MASTER = "master"

#--------------------------------------------------------------------------------
# The "outside this index space" sentinel the legacy single-int getters answer
# with, and the same one roadmap item A-4 standardises on for its
# object-valued reads.
#--------------------------------------------------------------------------------
NO_INDEX = -1


def _describe(track: Any) -> str:
    """
    A repr for the ValueError message that cannot itself raise.

    The only caller is the failure path below, whose whole job is to be
    attributable: a LOM wrapper whose repr throws must not launder a
    ValueError into something else on its way to /live/error.
    """
    try:
        return repr(track)
    except Exception:
        return "<unrepresentable track object>"


def identify_track(song: Any, track: Any) -> Tuple[str, int]:
    """
    Resolve `track` to its (category, index) identity.

    Comparison is `==` per element, the same equality upstream's own getters
    rely on through `list(...).index(...)`; LOM wrappers compare by the
    underlying Live object, so a reference obtained one way matches a
    reference obtained another.

    The master is checked first: it is a single object rather than a scan,
    and it is the one category whose index is a constant.

    Raises:
        ValueError: `track` is in none of the three collections — including
                    when it is None. A loaded set is not expected to produce
                    either state, so this is a loud, attributable
                    /live/error rather than a sentinel: a sentinel would
                    make "no idea what is selected" indistinguishable from
                    an answer.
    """
    if track is not None:
        master_track = getattr(song, "master_track", None)
        if master_track is not None and track == master_track:
            return (CATEGORY_MASTER, 0)

        for index, candidate in enumerate(song.tracks):
            if track == candidate:
                return (CATEGORY_TRACK, index)

        for index, candidate in enumerate(song.return_tracks):
            if track == candidate:
                return (CATEGORY_RETURN, index)

    raise ValueError("Track is not in song.tracks, song.return_tracks or "
                     "song.master_track: %s" % _describe(track))


def selected_track_identity(song: Any) -> Tuple[str, int]:
    """
    The identity of `song.view.selected_track`, served on
    /live/view/get/selected_track_identity and pushed by its listener.
    """
    return identify_track(song, song.view.selected_track)


def selected_track_index(song: Any) -> int:
    """
    The legacy single-int view of the selection: its index in `song.tracks`,
    or NO_INDEX when the selection is a return track or the master.

    Upstream raises ValueError here instead, which is what takes
    /live/view/get/selected_track, /live/view/get/selected_clip and the
    selected_track listener push down after any /live/return_track/select or
    /live/master/select.
    """
    category, index = selected_track_identity(song)
    return index if category == CATEGORY_TRACK else NO_INDEX


def selected_device_indices(song: Any) -> Tuple[int, int]:
    """
    (track_index, device_index) for the selected device, in regular-track
    coordinates:

    - `(i, d)` — a regular track is selected and its selected device is at
      index `d` of `track.devices`;
    - `(i, -1)` — a regular track is selected but there is no top-level
      device to report: nothing is selected (`selected_device is None`), or
      the selected device is nested inside a rack chain and so absent from
      `track.devices`. Upstream raises in both cases;
    - `(-1, -1)` — the selection is a return track or the master. Their
      device chains are readable, but there is no regular-track index to
      report them under; A-3's device-surface parity is where that reply
      shape gets defined.
    """
    track = song.view.selected_track
    category, index = identify_track(song, track)
    if category != CATEGORY_TRACK:
        return (NO_INDEX, NO_INDEX)

    device = track.view.selected_device
    if device is not None:
        for device_index, candidate in enumerate(track.devices):
            if device == candidate:
                return (index, device_index)

    return (index, NO_INDEX)
