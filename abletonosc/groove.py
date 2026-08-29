#--------------------------------------------------------------------------------
# The Groove Pool: /live/groove/*, plus the shared resolution the
# /live/song/get/groove_pool dump and the /live/clip/*/groove assignment need.
#
# Seshat extension (D-2) — see SESHAT.md. Upstream has no groove surface at
# all: `Song.groove_amount` is in its generic property loop, but that knob only
# *scales* grooves already assigned to clips, and `Clip.groove` holds a
# `Live.Groove.Groove` object, so it could never ride the generic loops (it is
# commented out in place in clip.py with upstream's observed failure, "Infered
# arg_value type is not supported"). On a set where no human has dragged a
# groove onto a clip, `groove_amount` therefore does nothing at all.
#
# The whole family is index-keyed against one flat collection,
# `song.groove_pool.grooves`, so it needs none of track_identity.py's category
# machinery — only its conventions: validate rather than index, fixed-arity
# replies, "none" as an answer (-1), and info-level logging on every
# resolution, because the installed logs/abletonosc.log is the evidence
# channel when another client holds the reply port. See API.md § "Groove API"
# and § "Object-valued reads".
#
# The module-level helpers below import nothing but logging, typing and
# .handler, so song.py and clip.py can `from .groove import ...` with no
# cycle, and tests_unit/ can drive them as plain functions with no handler and
# no Live in the way.
#--------------------------------------------------------------------------------

import logging
from typing import Any, Tuple

from .handler import AbletonOSCHandler

logger = logging.getLogger("abletonosc")

#--------------------------------------------------------------------------------
# The canonical per-groove field order, shared by /live/song/get/groove_pool's
# flattened dump and by the per-groove addresses. It is Live's own Groove Pool
# column order.
#
# `base` is deliberately NOT in this tuple. Its wire type is unverified, and
# pythonosc drops an entire reply it cannot encode (osc_server.send logs and
# gives up), so an encoding surprise in `base` would take the whole pool dump
# down with it; reachable through its own address instead, it breaks one
# address at worst.
#
# Nothing here may be reordered without changing the wire contract documented
# in API.md § "Groove API".
#--------------------------------------------------------------------------------
GROOVE_FIELDS = ("name", "quantization_amount", "timing_amount",
                 "random_amount", "velocity_amount")

#--------------------------------------------------------------------------------
# Per-field coercion, positionally matched to GROOVE_FIELDS. Coercing on the
# way *out* is the same defence flatten_notes_extended applies: pythonosc infers
# an OSC type from the Python type, and a Boost numeric wrapper it cannot type
# drops the whole reply silently, with only a log line to show for it.
#--------------------------------------------------------------------------------
GROOVE_FIELD_COERCIONS = (str, float, float, float, float)

#--------------------------------------------------------------------------------
# The "no groove assigned" sentinel, the same value and the same meaning as
# track_identity.NO_INDEX. Reply-only everywhere in this fork except
# /live/clip/set/groove, which accepts exactly -1 as "clear the assignment" —
# the one sanctioned exception to "-1 is an answer, never an argument",
# specified by the roadmap goal and documented in API.md § "Object-valued
# reads". -2 and below stay a ValueError.
#--------------------------------------------------------------------------------
NO_INDEX = -1


def resolve_groove(song: Any, index: int) -> Any:
    """
    Pool index -> the Live.Groove.Groove object, validated.

    Every argument is validated rather than trusted, exactly as
    `track_identity.resolve_track` is: Python's silent negative indexing would
    make -1 mean "the last groove in the pool", which is precisely the value
    the getters answer for "no groove assigned". A wrap-around there would
    turn a round-tripped read into an assignment.

    Raises:
        ValueError: `index` is negative or outside the pool, named with the
                    pool's real size so the /live/error line is actionable.
    """
    grooves = song.groove_pool.grooves
    count = len(grooves)
    if not 0 <= index < count:
        raise ValueError("Groove pool index out of range: %s (this pool has "
                         "%d groove(s))" % (index, count))
    logger.info("Resolving groove pool index %d of %d" % (index, count))
    return grooves[index]


def groove_index(song: Any, groove: Any) -> int:
    """
    The index of `groove` in `song.groove_pool.grooves`, or NO_INDEX when it is
    None or not in the pool.

    Absence is an answer, not a failure — a clip with no groove is the normal
    state, and a groove object that is somehow not a pool member has no index
    to report either way.

    Mirrors `track_identity._index_of`'s `==` semantics on purpose, and does
    not import it: that helper is private to that module's contract, and the
    scan is three lines.
    """
    if groove is not None:
        for index, candidate in enumerate(song.groove_pool.grooves):
            if groove == candidate:
                return index
    return NO_INDEX


def groove_pool_dump(song: Any) -> Tuple:
    """
    The whole pool, flattened: GROOVE_FIELDS per groove, in pool order, with no
    count prefix — the shape /live/song/get/groove_pool answers and its
    listener pushes.

    An empty pool is an empty tuple, which OSCServer._dispatch sends as a
    zero-argument reply on the getter's address. That is an answer ("the pool
    is empty"), not an error.
    """
    flat = []
    for groove in song.groove_pool.grooves:
        flat += [coerce(getattr(groove, field))
                 for field, coerce in zip(GROOVE_FIELDS, GROOVE_FIELD_COERCIONS)]
    return tuple(flat)


class GrooveHandler(AbletonOSCHandler):
    #--------------------------------------------------------------------------------
    # Class-body assignment, no __init__ — the AbletonOSCHandler subclass
    # contract (see handler.py's docstring and
    # tests_unit/test_handler_subclass_contract.py). Listener pushes go out on
    # /live/groove/get/<prop>, which is why this family needs a handler class of
    # its own rather than a block inside song.py.
    #--------------------------------------------------------------------------------
    class_identifier = "groove"

    def init_api(self):
        def create_groove_callback(func, *args, include_ids: bool = False):
            """
            Creates a callback expecting (groove_index, *args), which resolves
            the groove through `resolve_groove` and calls `func` with it.

            `include_ids` hands the callee the *normalised, truncated* identity
            rather than the raw OSC args, exactly as `create_scene_callback`
            does: a listener's identity is the bookkeeping key, and it must
            agree across a start/stop pair sent by different clients.
            TouchOSC-style clients send every number as a float (upstream issue
            #33), so `start_listen 0.0` and `stop_listen 0` name the same
            subscription only because the int() happens here, once. A groove
            subscription's identity is exactly one int; anything past it is
            dropped, so a stray trailing argument cannot key a subscription a
            well-formed stop could never reach.
            """
            def groove_callback(params: Tuple[Any]):
                index = int(params[0])
                groove = resolve_groove(self.song, index)
                if include_ids:
                    rv = func(groove, *args, (index,))
                else:
                    rv = func(groove, *args, tuple(params[1:]))

                if rv is not None:
                    return (index, *rv)

            return groove_callback

        #--------------------------------------------------------------------------------
        # Every member of Live.Groove.Groove is rw. Only `base` is not
        # observable, so it is the one property registered without a listen
        # pair: putting it in the loop below would manufacture
        # /live/groove/start_listen/base, which could only ever answer
        # /live/error AttributeError on the add_base_listener lookup. This is
        # song.py's `properties_r_no_listen` split, applied to a rw member.
        #--------------------------------------------------------------------------------
        properties_rw = list(GROOVE_FIELDS)
        properties_rw_no_listen = ["base"]

        for prop in properties_rw + properties_rw_no_listen:
            self.osc_server.add_handler("/live/groove/get/%s" % prop,
                                        create_groove_callback(self._get_property, prop))
            self.osc_server.add_handler("/live/groove/set/%s" % prop,
                                        create_groove_callback(self._set_property, prop))

        #--------------------------------------------------------------------------------
        # stop_listen resolves nothing, on purpose.
        #
        # A subscription's identity is the normalised index, and the object it
        # was bound to is already in `listener_objects` — the base
        # `_stop_listen` unbinds from *that*, deliberately ignoring whatever
        # target it is handed (see handler.py's comment on renumbering). So
        # resolving the current pool member first buys nothing, and costs the
        # one case that matters: removing a groove renumbers the pool, so the
        # index a client subscribed under can be out of range by the time it
        # stops. `resolve_groove` would raise, the client would get
        # /live/error, and the stored listener would survive — still bound to
        # a groove the pool no longer holds, still pushing — until
        # `clear_api`. Keying straight off the index unbinds it instead, which
        # is what API.md § "Groove API" promises.
        #
        # An index that never carried a subscription is not an error here: the
        # base logs "No listener function found" and sends nothing, exactly as
        # every other handler's stop does. Nothing is indexed, so a negative
        # index cannot wrap; it simply names no subscription.
        #--------------------------------------------------------------------------------
        def create_groove_stop_listen_callback(prop):
            def groove_stop_listen_callback(params: Tuple[Any]):
                index = int(params[0])
                listener_key = (prop, (index,))
                target = self.listener_objects.get(listener_key)
                self._stop_listen(target, prop, (index,))

            return groove_stop_listen_callback

        for prop in properties_rw:
            self.osc_server.add_handler("/live/groove/start_listen/%s" % prop,
                                        create_groove_callback(self._start_listen, prop,
                                                               include_ids=True))
            self.osc_server.add_handler("/live/groove/stop_listen/%s" % prop,
                                        create_groove_stop_listen_callback(prop))
