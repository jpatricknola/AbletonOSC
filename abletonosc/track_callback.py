#--------------------------------------------------------------------------------
# The wrapper every /live/track/... address is registered through.
#
# It lives in its own module, importing nothing but `typing`, for one reason:
# track.py imports `ableton.v2` through handler.py and therefore cannot be
# imported outside Live, so the wildcard fan-out logic could never be tested
# by tests_unit/ while it sat inside TrackHandler.init_api as a closure over
# `self`. Lifted out and parameterised on a `get_tracks` callable, it is the
# real shipped code under test in tests_unit/test_track_callback.py.
#
# Seshat divergence — see SESHAT.md. Upstream keeps this as a nested closure
# whose wildcard branch returns after the first track.
#--------------------------------------------------------------------------------

from typing import Any, Callable, List, Optional, Tuple


def _raise_with_track_context(exception: BaseException, track_index: int):
    """
    Re-raise `exception` with its message prefixed by the track it failed on,
    **keeping its class**.

    The class is load-bearing, not cosmetic. `OSCServer._is_wildcard_skip`
    decides "this matched endpoint does not apply to this request" by
    exception class, so a composed request like `/live/track/get/* *` relies
    on a per-track `ValueError` still arriving as a `ValueError` — an
    arg-mismatch endpoint such as `/live/track/get/send` raises one unpacking
    the empty params tail, and must stay a silent skip. Wrapping everything in
    a `RuntimeError` would turn every documented skip into a per-endpoint
    error datagram.
    """
    detail = "wildcard fan-out failed at track %d: %s" % (track_index, exception)
    try:
        exception.args = (detail,)
    except Exception:
        #--------------------------------------------------------------------------------
        # Exotic exception types can refuse the assignment. Rebuild rather
        # than lose the track context; fall back to RuntimeError only if the
        # class cannot be constructed from a single message. Construct
        # before raising: `except TypeError` here must catch a failed
        # *construction*, not a successfully rebuilt exception that happens
        # to be a TypeError itself — this is the one helper whose job is
        # preserving the class, so it must not launder its own output.
        #--------------------------------------------------------------------------------
        try:
            rebuilt = type(exception)(detail)
        except Exception:
            raise RuntimeError(detail) from exception
        raise rebuilt from exception
    raise exception


def create_track_callback(get_tracks: Callable[[], Any],
                          func: Callable,
                          *args,
                          include_track_id: bool = False):
    """
    Build the OSC callback for one /live/track/... address.

    Args:
        get_tracks: Zero-argument callable returning the live regular-track
                    vector (in production, `lambda: self.song.tracks`). Called
                    per dispatch, never cached, so track creation and deletion
                    between requests are seen.
        func: The per-track worker, called as `func(track, *args, params_tail)`.
        args: Bound leading arguments for `func` (typically the property name).
        include_track_id: Prepend the track index to the params tail, as the
                          listener registrations need.

    The returned callback reads the track index from `params[0]`:

    - a concrete index replies `(track_index, *rv)`, or nothing when `func`
      returns `None` (setters, methods, listener registrations);
    - `"*"` fans out over every regular track in ascending index order and
      returns a **list** of those per-track tuples, which `OSCServer._dispatch`
      sends as one datagram per element on the concrete request address. A
      fan-out that collects nothing returns `None` and stays silent, which is
      what keeps `/live/track/set/<prop> *` and the listener registrations
      behaving exactly as before.

    The fan-out is all-or-nothing: every track is read before anything is
    sent, and a failure at any track aborts the collection so the request
    produces no replies and exactly one `/live/error` naming that track.
    """

    def invoke(track_index: int, params) -> Optional[Tuple[Any, ...]]:
        track = get_tracks()[track_index]
        if include_track_id:
            return func(track, *args, tuple([track_index] + params[1:]))
        else:
            return func(track, *args, tuple(params[1:]))

    def track_callback(params: Tuple[Any]):
        if params[0] == "*":
            replies: List[Tuple[Any, ...]] = []
            for track_index in range(len(get_tracks())):
                try:
                    rv = invoke(track_index, params)
                except Exception as e:
                    _raise_with_track_context(e, track_index)
                if rv is not None:
                    replies.append((track_index, *rv))
            #--------------------------------------------------------------------------------
            # None rather than [] when nothing was collected: identical on the
            # wire (both send nothing), but it keeps the silent paths —
            # setters, methods, listener registrations — returning exactly what
            # they returned before this module existed.
            #--------------------------------------------------------------------------------
            return replies if replies else None

        track_index = int(params[0])
        rv = invoke(track_index, params)
        if rv is not None:
            return (track_index, *rv)

    return track_callback
