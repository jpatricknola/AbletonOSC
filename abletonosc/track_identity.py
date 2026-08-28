#--------------------------------------------------------------------------------
# Resolving a LOM track object back to the address family that reaches it.
#
# It lives in its own module, importing nothing but `typing`, for the same
# reason track_callback.py does: kept out of the handler closures, it is
# testable as plain functions. Parameterised on `song` instead of closed over
# `self`, it is the real shipped code under test in
# tests_unit/test_track_identity.py, exhaustively and without a handler in the
# way; the handler glue that calls it is driven separately by
# tests_unit/test_view_object_reads.py and
# tests_unit/test_song_object_reads.py.
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
# to use next. A-3 (return/master Track parity) is specified against this
# representation, and A-4 (object-valued read helpers) is built on it: the
# second half of this module resolves every object-valued LOM member the fork
# reads to indices under one of those categories, and carries the inverse
# resolvers ((category, index) -> track, and (category, track_index,
# device_index) -> device) that A-4's one setter needs.
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


#--------------------------------------------------------------------------------
# A-4 (object-valued read helpers) below this line.
#
# An object-valued LOM member — Song.appointed_device, Track.group_track,
# ClipSlot.clip, Song.View.selected_chain / selected_parameter /
# mod_mapping_device / mod_mapping_parameter — cannot go on the wire as
# itself, so each is answered as *indices into the collections the existing
# address families already accept*, prefixed by the (category, index) track
# identity above when the owning track can be any of the three kinds. See
# API.md § "Object-valued reads" for the full pattern.
#
# The resolution lives here rather than in song.py / view.py for the same
# reason identify_track does: as plain functions parameterised on `song` it
# can be covered exhaustively, with no handler, no OSC server and no fixture
# in the way. The registrations and closures in song.py / view.py that call it
# are covered in turn by tests_unit/test_song_object_reads.py and
# tests_unit/test_view_object_reads.py.
#--------------------------------------------------------------------------------

#--------------------------------------------------------------------------------
# The category a reply carries when the member itself is None: nothing is
# appointed, nothing is selected, no mapping gesture is in flight. Reply-only
# — no setter accepts it, and resolve_track/resolve_device reject it
# explicitly, because "none" is an answer and never an argument (the same
# half of the convention that makes NO_INDEX reply-only).
#--------------------------------------------------------------------------------
CATEGORY_NONE = "none"

#--------------------------------------------------------------------------------
# How far owning_track_identity will climb canonical_parent before giving up.
# A device nested in a rack chain inside a rack chain is three links from its
# track; sixteen is far past any real nesting depth, and the cap exists only
# so a cyclic or self-parenting object fails loudly instead of hanging Live's
# message loop — this code runs on the UI thread.
#--------------------------------------------------------------------------------
MAX_PARENT_ASCENT = 16


def _index_of(collection: Any, obj: Any) -> int:
    """
    Index of `obj` in `collection` by `==` scan, or NO_INDEX when absent.

    Absence is an answer here, not a failure: a device inside a rack chain is
    genuinely not a member of `track.devices`, and the -1 says so.
    """
    for index, candidate in enumerate(collection):
        if obj == candidate:
            return index
    return NO_INDEX


def group_track_index(song: Any, track: Any) -> int:
    """
    The index in `song.tracks` of the group track `track` belongs to, or
    NO_INDEX when it is not grouped.

    Same resolution semantics as `song_export_structure`'s inline
    `list(song.tracks).index(track.group_track)` — deliberately not a
    refactor of that upstream function, which may be deleted outright.

    Raises:
        ValueError: `track.group_track` is a track that is not in
                    `song.tracks`. Live has no such state; if it ever
                    appears, it is a loud /live/error rather than a -1 that
                    would read as "ungrouped".
    """
    group_track = track.group_track
    if group_track is None:
        return NO_INDEX

    index = _index_of(song.tracks, group_track)
    if index == NO_INDEX:
        raise ValueError("Group track is not in song.tracks: %s" % _describe(group_track))
    return index


def owning_track_identity(song: Any, obj: Any) -> Tuple[str, int]:
    """
    The (category, index) identity of the track that owns `obj`, found by
    climbing `canonical_parent` until a track is reached.

    Live's own scripts use this ascent (Push2/track_selection climbs
    canonical_parent off a Live.Chain to reach a track), so the chain
    Chain -> rack Device -> Track and DeviceParameter -> Device -> Track are
    the assumed shapes; the climb is written to not care how many links there
    are.

    Raises:
        ValueError: the ascent reached the top (canonical_parent None or
                    missing) or exhausted MAX_PARENT_ASCENT without finding a
                    track. Loud and attributable — /live/error naming the
                    object — rather than a sentinel that would be
                    indistinguishable from "nothing selected".
    """
    node = obj
    for _ in range(MAX_PARENT_ASCENT):
        if node is None:
            break
        try:
            return identify_track(song, node)
        except ValueError:
            pass
        node = getattr(node, "canonical_parent", None)

    raise ValueError("Cannot resolve the owning track of %s (canonical_parent "
                     "ascent found no track within %d levels)"
                     % (_describe(obj), MAX_PARENT_ASCENT))


def device_identity(song: Any, device: Any) -> Tuple[str, int, int]:
    """
    (category, track_index, device_index) for a device-valued member.

    - `device is None` -> (CATEGORY_NONE, -1, -1);
    - a top-level device -> its index in the owning track's `devices`, under
      the category that reaches that track (/live/track/device/*,
      /live/return_track/device/*, /live/master/device/*);
    - a device nested inside a rack chain -> (category, track_index, -1): it
      has no index in `track.devices`, and no address reaches it until A-1
      ships a path resolver.
    """
    if device is None:
        return (CATEGORY_NONE, NO_INDEX, NO_INDEX)

    category, track_index = owning_track_identity(song, device)
    track = resolve_track(song, category, track_index)
    return (category, track_index, _index_of(track.devices, device))


def parameter_identity(song: Any, parameter: Any) -> Tuple[str, int, int, int]:
    """
    (category, track_index, device_index, parameter_index) for a
    parameter-valued member.

    - `parameter is None` -> the none-quad;
    - a parameter of a top-level device -> the full quad, addressable through
      that category's device/parameter addresses;
    - a mixer or send parameter, or a parameter of a device nested in a rack
      chain -> (category, track_index, -1, -1): the owning track is known,
      but the parameter's parent is not a member of `track.devices`, so there
      is no device index to report it under;
    - a parameter of a top-level device that is not itself in that device's
      `parameters` -> (category, track_index, device_index, -1). Live has no
      such state; this is a can't-happen defended by `_index_of` rather than
      an assumption baked into the return shape.
    """
    if parameter is None:
        return (CATEGORY_NONE, NO_INDEX, NO_INDEX, NO_INDEX)

    category, track_index = owning_track_identity(song, parameter)
    track = resolve_track(song, category, track_index)

    parent = getattr(parameter, "canonical_parent", None)
    device_index = _index_of(track.devices, parent) if parent is not None else NO_INDEX
    if device_index == NO_INDEX:
        return (category, track_index, NO_INDEX, NO_INDEX)

    return (category, track_index, device_index, _index_of(parent.parameters, parameter))


def chain_identity(song: Any, chain: Any) -> Tuple[str, int, int, int]:
    """
    (category, track_index, device_index, chain_index) for a chain-valued
    member.

    - `chain is None` -> the none-quad;
    - a chain of a top-level rack -> the full quad;
    - a chain of a rack that is itself nested in another rack's chain ->
      device_index -1, chain_index still resolved against the owning rack's
      `chains`;
    - a chain absent from its parent's `chains` (a drum rack's DrumChain may
      only appear under `drum_pads[*].chains` — unmeasured, see the API.md
      row) -> chain_index -1;
    - a chain with no `canonical_parent` rack -> (category, track_index, -1,
      -1). Live has no such state for a non-`None` chain; this is a
      can't-happen defended by the same shape as the none-quad, not an
      assumption baked into the return shape.
    """
    if chain is None:
        return (CATEGORY_NONE, NO_INDEX, NO_INDEX, NO_INDEX)

    category, track_index = owning_track_identity(song, chain)
    track = resolve_track(song, category, track_index)

    rack = getattr(chain, "canonical_parent", None)
    if rack is None:
        return (category, track_index, NO_INDEX, NO_INDEX)

    return (category, track_index,
            _index_of(track.devices, rack),
            _index_of(getattr(rack, "chains", ()), chain))


def resolve_track(song: Any, category: str, index: int) -> Any:
    """
    The inverse of identify_track: (category, index) -> the track object.

    Every argument is validated rather than trusted, because this is where
    "-1 is an answer, never an argument" stops being documentation. Python's
    silent negative indexing would make `-1` mean "the last track", which is
    the documented hazard on the legacy /live/view/set/selected_track and has
    no reason to be inherited by a new address.

    Raises:
        ValueError: unknown category (CATEGORY_NONE included — it is
                    reply-only), a master index other than 0, or an index
                    outside its collection.
    """
    if category == CATEGORY_MASTER:
        if index != 0:
            raise ValueError("Master track index must be 0, got %s" % index)
        master_track = getattr(song, "master_track", None)
        if master_track is None:
            raise ValueError("This song has no master track")
        return master_track

    if category == CATEGORY_TRACK:
        collection = song.tracks
    elif category == CATEGORY_RETURN:
        collection = song.return_tracks
    else:
        raise ValueError("Unknown track category: %r (expected %r, %r or %r; "
                         "%r is reply-only)"
                         % (category, CATEGORY_TRACK, CATEGORY_RETURN,
                            CATEGORY_MASTER, CATEGORY_NONE))

    if not 0 <= index < len(collection):
        raise ValueError("Track index out of range for category %r: %s "
                         "(this song has %d)" % (category, index, len(collection)))
    return collection[index]


def resolve_device(song: Any, category: str, track_index: int, device_index: int) -> Any:
    """
    (category, track_index, device_index) -> the device object, with the same
    argument discipline as resolve_track: a negative or out-of-range
    device_index is a ValueError, never a wrap-around.

    Top-level devices only. A device nested in a rack chain is not reachable
    by any index this fork accepts today (A-1).
    """
    track = resolve_track(song, category, track_index)
    devices = track.devices
    if not 0 <= device_index < len(devices):
        raise ValueError("Device index out of range for %s track %d: %s "
                         "(this track has %d device(s))"
                         % (category, track_index, device_index, len(devices)))
    return devices[device_index]
