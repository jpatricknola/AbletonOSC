import re
from functools import partial
from typing import Tuple, Callable, Any, Optional
from .handler import AbletonOSCHandler
from .groove import clip_groove_index, resolve_groove, NO_INDEX
import Live

def note_name_to_midi(name):
    """ Maps a MIDI note name (D3, C#6) to a value.
    Assumes that middle C is C4. """
    note_names = [["C"],
                  ["C#", "Db"],
                  ["D"],
                  ["D#", "Eb"],
                  ["E"],
                  ["F"],
                  ["F#", "Gb"],
                  ["G"],
                  ["G#", "Ab"],
                  ["A"],
                  ["A#", "Bb"],
                  ["B"]]

    for index, names in enumerate(note_names):
        if name in names:
            return index
    return None

#--------------------------------------------------------------------------------
# Extended notes — the canonical field order, shared by every address in the
# "Clip: Extended notes" block below (a Seshat extension; see SESHAT.md).
#
# The first five fields are exactly the order the old five-field addresses
# (/live/clip/get/notes, /live/clip/add/notes) have always used, so a client
# upgrades by widening its stride rather than by re-reading the fields. The
# note id is not in this tuple because it is not settable and not part of an
# *add*: it is appended last on every reply, which makes the add form the same
# group truncated to eight.
#
# Nothing here may be reordered without changing the wire contract documented
# in API.md § "Extended notes (note ids)".
#--------------------------------------------------------------------------------
EXTENDED_NOTE_FIELDS = ("pitch", "start_time", "duration", "velocity", "mute",
                        "probability", "velocity_deviation", "release_velocity")

#--------------------------------------------------------------------------------
# Per-field coercion, positionally matched to EXTENDED_NOTE_FIELDS. Clients such
# as TouchOSC send every numeric argument as a float, so a pitch arrives as
# 60.0 and a mute flag as 0.0; Live wants an int pitch and a real bool. The
# same table types the deprecated tuple forms (first five entries), so those
# cannot drift from the extended ones.
#--------------------------------------------------------------------------------
def _to_bool(value):
    return bool(int(value))

EXTENDED_NOTE_COERCIONS = (int, float, float, float, _to_bool,
                           float, float, float)


def coerce_note_fields(group: Tuple[Any]) -> dict:
    """
    Map a wire group of note field values onto {field_name: coerced_value},
    in canonical order. Accepts a group shorter than the full eight (the
    deprecated five-field forms use the first five).
    """
    return dict((field, coerce(value))
                for field, coerce, value in zip(EXTENDED_NOTE_FIELDS,
                                                EXTENDED_NOTE_COERCIONS,
                                                group))


def make_note_specification(group: Tuple[Any]):
    """
    Build a Live.Clip.MidiNoteSpecification from an 8-field wire group.

    Isolated in one function deliberately: whether the constructor accepts
    `probability`, `velocity_deviation` and `release_velocity` as keyword
    arguments is unmeasured (API.md marks it as such). If a future measurement
    says it does not, setting them as attributes on the constructed spec is a
    change to this function alone.
    """
    return Live.Clip.MidiNoteSpecification(**coerce_note_fields(group))


def flatten_notes_extended(notes) -> list:
    """
    Nine fields per note — the canonical order, then the note id.

    Coerced through EXTENDED_NOTE_COERCIONS (plus int() on the id) on the way
    out, not just the way in: `probability`, `velocity_deviation`,
    `release_velocity` and `note_id` are not proven by upstream the way the
    first five fields are, and pythonosc's builder infers an OSC type from the
    Python type — a value it can't type drops the whole reply, silently, with
    only a log line (osc_server.send). Coercing here matches the int()
    already applied to duplicate_notes_by_id's returned ids.
    """
    flat = []
    for note in notes:
        flat += [coerce(getattr(note, field))
                for field, coerce in zip(EXTENDED_NOTE_FIELDS, EXTENDED_NOTE_COERCIONS)]
        flat.append(int(note.note_id))
    return flat


def flatten_notes_basic(notes) -> list:
    """
    Five fields per note: the shape /live/clip/get/notes has always replied,
    applied here to the selected-notes vector so that the deprecated
    Clip.get_selected_notes member never has to be called.
    """
    flat = []
    for note in notes:
        flat += [getattr(note, field) for field in EXTENDED_NOTE_FIELDS[:5]]
    return flat


def parse_note_groups(params: Tuple[Any], stride: int, address: str) -> list:
    """
    Split flat wire params into fixed-stride note groups, or raise.

    A zero-length request is an error rather than a no-op: every address that
    parses groups mutates the clip, and a client that sent no notes at all has
    a bug worth hearing about. (/live/clip/add/notes, upstream's, silently
    does nothing in that case; it is left alone.)
    """
    if len(params) == 0 or len(params) % stride != 0:
        raise ValueError("Invalid number of arguments for %s. Expected a non-zero "
                         "multiple of %d note fields, got %d." % (address, stride, len(params)))
    return [tuple(params[offset:offset + stride])
            for offset in range(0, len(params), stride)]


def parse_note_ids(params: Tuple[Any], address: str) -> Tuple[int]:
    """
    Cast wire note ids to a tuple of ints, or raise if none were given.
    """
    if len(params) == 0:
        raise ValueError("Invalid number of arguments for %s. At least one note id "
                         "must be passed." % address)
    return tuple(int(note_id) for note_id in params)


def parse_deprecated_note_tuple(params: Tuple[Any], address: str) -> Tuple[Tuple]:
    """
    Group flat wire params into the ((pitch, start_time, duration, velocity,
    mute), ...) tuple that Live's deprecated set_notes / replace_selected_notes
    members take, with the canonical per-field coercions applied.
    """
    groups = parse_note_groups(params, 5, address)
    return tuple(tuple(coerce(value)
                       for coerce, value in zip(EXTENDED_NOTE_COERCIONS, group))
                 for group in groups)


class ClipHandler(AbletonOSCHandler):
    class_identifier = "clip"

    def init_state(self):
        self._clip_notes_cache = []

    def init_api(self):
        def create_clip_callback(func, *args, pass_clip_index=False):
            """
            Creates a callback that expects the following set of arguments:
              (track_index, clip_index, *args)

            The callback then extracts the relevant `Clip` object from the current Song,
            and calls `func` with this `Clip` object plus any additional *args.

            pass_clip_index is a bit of an ugly hack, although seems like the lesser of
            evils for scenarios where the track/clip index is needed (as a clip is unable
            to query its own index). Other alternatives include _always_ passing track/clip
            index to the callback, but this adds arg clutter to every single callback.

            pass_clip_index hands the callee the *normalised, truncated* identity
            (track_index, clip_index), not the raw OSC args. It is used by the
            start_listen/stop_listen registrations only, and a listener's identity has
            to be canonical: it is the bookkeeping key, the LOM subscript and the echo
            in the push, and those three must agree across a start/stop pair sent by
            different clients. Anything past the second argument is not part of the
            identity and is dropped, so a stray trailing argument cannot key a second
            subscription that a well-formed stop can never reach.
            """

            def clip_callback(params: Tuple[Any]) -> Tuple:
                #--------------------------------------------------------------------------------
                # Cast to int to support clients such as TouchOSC that, by default, pass all
                # numeric arguments as float.
                #--------------------------------------------------------------------------------
                track_index, clip_index = int(params[0]), int(params[1])
                track = self.song.tracks[track_index]
                clip = track.clip_slots[clip_index].clip
                if pass_clip_index:
                    rv = func(clip, *args, (track_index, clip_index))
                else:
                    rv = func(clip, *args, tuple(params[2:]))

                if rv is not None:
                    return (track_index, clip_index, *rv)

            return clip_callback

        methods = [
            "fire",
            "stop",
            "duplicate_loop",
            "remove_notes_by_id",
            #--------------------------------------------------------------------------------
            # Both take no arguments and return nothing, which is exactly what
            # _call_method handles. Part of the extended-notes block below in
            # everything but registration site (SESHAT.md).
            #--------------------------------------------------------------------------------
            "select_all_notes",
            "deselect_all_notes",
            #--------------------------------------------------------------------------------
            # quantize(quantization_grid, amount).
            #
            # The grid is Live's GridQuantization enum, NOT RecordingQuantization.
            # MEASURED against a running Live on 2026-07-31 — one clip per value,
            # probe notes chosen so each candidate grid lands distinguishably:
            #   0 no grid    1 1/4        2 1/8        3 1/8 triplet
            #   4 1/8 triplet             5 1/16       6 1/16 triplet
            #   7 1/16 triplet            8 1/32       >=9 invalid, nothing moves
            # so sixteenths is 5, and there ARE triplet grids. This comment used to
            # say `5 g_half ... 8 g_sixteenth, 9 g_thirtysecond`, and every row of
            # that was wrong; if some document disagrees with the table above, the
            # instrument won. There is no 1/2 grid and no bar-length grid. 3/4 and
            # 6/7 are duplicates (reason unknown; prefer the lower). Whether the
            # song's swing_amount colours the result is UNVERIFIED — the old claim
            # that it is where swing comes from shared a sentence with the false
            # "no triplet grids", and nothing here has tested it.
            #
            # Amount is a float on 0.0-1.0 (Live's UI shows it as a percentage),
            # applied linearly: new = old + amount * (target - old). Only note
            # starts move; a move that lands two same-pitch notes on one point
            # merges them (later velocity wins), and one that creates a same-pitch
            # overlap trims the earlier note.
            #--------------------------------------------------------------------------------
            "quantize"
        ]
        properties_r = [
            "end_time",
            "file_path",
            "gain_display_string",
            #--------------------------------------------------------------------------------
            # `has_envelopes` is a Seshat extension. It is a plain read-only bool
            # and needs no handler of its own, but what it is *for* is not obvious
            # from the name: no address in this fork authors envelope data, so
            # importing a file through /live/browser/load_item is currently the
            # only route by which expression data reaches a clip. This flag is
            # the only way a client can see that it arrived: notes read back through
            # get/notes_extended, but none of those nine fields is expression, so
            # without this the difference between an import that carried pitch bend
            # and one that carried only notes is invisible on the wire.
            #
            # It answers only "does *some* envelope exist" — not which parameter
            # owns it, and not its values. Reading or writing an envelope's contents
            # needs `Clip.automation_envelope` / `create_automation_envelope`, which
            # exist in the LOM (see FORK_GAPS.md) but are unexposed. Both are keyed
            # by a DeviceParameter — device automation — and whether any spelling
            # of them reaches a MIDI clip's pitch-bend or CC lanes is unmeasured.
            # Until that is settled and one is exposed, this flag is the whole of
            # what a client can learn about envelopes.
            #--------------------------------------------------------------------------------
            "has_envelopes",
            "has_groove",
            "is_midi_clip",
            "is_audio_clip",
            "is_overdubbing",
            "is_playing",
            "is_recording",
            "is_triggered",
            "length",
            "playing_position",
            "sample_length",
            "start_time",
            "will_record_on_start"
            ## TODO list:
            ## "groove" is no longer here: it is an object-valued member and is
            ## registered by hand below (Seshat extension D-2), because the
            ## generic loops cannot encode a Live.Groove.Groove — which is what
            ## upstream's "Infered arg_value type is not supported" was.
            ## is_arrangement_clip            
            ##"warp_markers", ## "Infered arg_value type is not supported"
            ##"view", ##"Infered arg_value type is not supported"
        ]
        properties_rw = [
            "color",
            "color_index",
            "end_marker",
            "gain",
            "launch_mode",
            "launch_quantization",
            "legato",
            "loop_end",
            "loop_start",
            "looping",
            "muted",
            "name",
            "pitch_coarse",
            "pitch_fine",
            "position",
            "ram_mode",
            "start_marker",
            "velocity_amount",
            "warp_mode",
            "warping",
        ]

        for method in methods:
            self.osc_server.add_handler("/live/clip/%s" % method,
                                        create_clip_callback(self._call_method, method))

        for prop in properties_r + properties_rw:
            self.osc_server.add_handler("/live/clip/get/%s" % prop,
                                        create_clip_callback(self._get_property, prop))
            self.osc_server.add_handler("/live/clip/start_listen/%s" % prop,
                                        create_clip_callback(self._start_listen, prop, pass_clip_index=True))
            self.osc_server.add_handler("/live/clip/stop_listen/%s" % prop,
                                        create_clip_callback(self._stop_listen, prop, pass_clip_index=True))
        for prop in properties_rw:
            self.osc_server.add_handler("/live/clip/set/%s" % prop,
                                        create_clip_callback(self._set_property, prop))

        def clip_get_notes(clip, params: Tuple[Any] = ()):
            if len(params) == 4:
                pitch_start, pitch_span, time_start, time_span = params
            elif len(params) == 0:
                pitch_start, pitch_span, time_start, time_span = 0, 127, -8192, 16384
            else:
                raise ValueError("Invalid number of arguments for /clip/get/notes. Either 0 or 4 arguments must be passed.")
            notes = clip.get_notes_extended(pitch_start, pitch_span, time_start, time_span)
            all_note_attributes = []
            for note in notes:
                all_note_attributes += [note.pitch, note.start_time, note.duration, note.velocity, note.mute]
            return tuple(all_note_attributes)

        def clip_add_notes(clip, params: Tuple[Any] = ()):
            notes = []
            for offset in range(0, len(params), 5):
                pitch, start_time, duration, velocity, mute = params[offset:offset + 5]
                note = Live.Clip.MidiNoteSpecification(start_time=start_time,
                                                       duration=duration,
                                                       pitch=pitch,
                                                       velocity=velocity,
                                                       mute=mute)
                notes.append(note)
            clip.add_new_notes(tuple(notes))

        def clip_remove_notes(clip, params: Tuple[Any] = ()):
            if len(params) == 4:
                pitch_start, pitch_span, time_start, time_span = params
            elif len(params) == 0:
                pitch_start, pitch_span, time_start, time_span = 0, 127, -8192, 16384
            else:
                raise ValueError("Invalid number of arguments for /clip/remove/notes. Either 0 or 4 arguments must be passed.")
            clip.remove_notes_extended(pitch_start, pitch_span, time_start, time_span)

        self.osc_server.add_handler("/live/clip/get/notes", create_clip_callback(clip_get_notes))
        self.osc_server.add_handler("/live/clip/add/notes", create_clip_callback(clip_add_notes))
        self.osc_server.add_handler("/live/clip/remove/notes", create_clip_callback(clip_remove_notes))

        #--------------------------------------------------------------------------------
        # Clip: Extended notes (note ids) — a Seshat extension, added in this fork.
        #
        # Everything above flattens a note to five fields, which throws away the
        # note_id Live assigns and the probability / velocity_deviation /
        # release_velocity it carries — and without an id on the wire, the whole
        # id-keyed half of Live's note API is unreachable from a client, including
        # the /live/clip/remove_notes_by_id this fork already registers.
        #
        # These addresses expose that half. The old five-field addresses are not
        # touched: their reply shape is pinned by tests_unit/test_clip_notes.py,
        # and a client upgrades by moving to a parallel address, never by having
        # one change under it. Canonical field order lives in
        # EXTENDED_NOTE_FIELDS at module scope; see API.md § "Extended notes".
        #--------------------------------------------------------------------------------
        def clip_get_notes_extended(clip, params: Tuple[Any] = ()):
            if len(params) == 4:
                pitch_start, pitch_span, time_start, time_span = params
            elif len(params) == 0:
                pitch_start, pitch_span, time_start, time_span = 0, 127, -8192, 16384
            else:
                raise ValueError("Invalid number of arguments for /live/clip/get/notes_extended. Either 0 or 4 arguments must be passed.")
            notes = clip.get_notes_extended(pitch_start, pitch_span, time_start, time_span)
            return tuple(flatten_notes_extended(notes))

        def clip_add_notes_extended(clip, params: Tuple[Any] = ()):
            #--------------------------------------------------------------------------------
            # Silent on success, even though Live may well return the new notes:
            # add_new_notes' return value is unmeasured, so the reply would be a
            # guess. Clients read the new ids back with get/notes_extended.
            #--------------------------------------------------------------------------------
            groups = parse_note_groups(params, 8, "/live/clip/add/notes_extended")
            notes = [make_note_specification(group) for group in groups]
            clip.add_new_notes(tuple(notes))

        def clip_get_selected_notes_extended(clip, params: Tuple[Any] = ()):
            return tuple(flatten_notes_extended(clip.get_selected_notes_extended()))

        def clip_get_selected_notes(clip, params: Tuple[Any] = ()):
            #--------------------------------------------------------------------------------
            # Five fields, from the extended call: Live's own get_selected_notes is
            # deprecated, and flattening here gives the same five-field shape
            # without calling it.
            #--------------------------------------------------------------------------------
            return tuple(flatten_notes_basic(clip.get_selected_notes_extended()))

        def clip_get_notes_by_id(clip, params: Tuple[Any] = ()):
            note_ids = parse_note_ids(params, "/live/clip/get_notes_by_id")
            return tuple(flatten_notes_extended(clip.get_notes_by_id(note_ids)))

        def clip_apply_note_modifications(clip, params: Tuple[Any] = ()):
            #--------------------------------------------------------------------------------
            # Live's modify-in-place path, as Push drives it: fetch the notes by id,
            # mutate the objects, hand the same vector back. Every cited id is
            # checked against what Live returned *before* anything is mutated, so an
            # unknown id is a clean /live/error with the clip untouched rather than a
            # half-applied edit.
            #--------------------------------------------------------------------------------
            groups = parse_note_groups(params, 9, "/live/clip/apply_note_modifications")
            note_ids = tuple(int(group[8]) for group in groups)
            notes = clip.get_notes_by_id(note_ids)
            #--------------------------------------------------------------------------------
            # Keyed on int(note.note_id), not the raw attribute: lookups below are
            # int(group[8]), and a MidiNote's own id type is unmeasured (Live calls
            # it IntU64). If the two didn't compare equal, every request would raise
            # the "No note with id" error below for a perfectly valid id.
            #--------------------------------------------------------------------------------
            notes_by_id = dict((int(note.note_id), note) for note in notes)
            for note_id in note_ids:
                if note_id not in notes_by_id:
                    raise ValueError("No note with id %d in this clip "
                                     "(/live/clip/apply_note_modifications)" % note_id)
            for group in groups:
                note = notes_by_id[int(group[8])]
                for field, value in coerce_note_fields(group).items():
                    setattr(note, field, value)
            clip.apply_note_modifications(notes)

        def clip_duplicate_notes_by_id(clip, params: Tuple[Any] = ()):
            if len(params) < 3:
                raise ValueError("Invalid number of arguments for /live/clip/duplicate_notes_by_id. "
                                 "Expected destination_time, transposition_amount and at least one note id.")
            destination_time = float(params[0])
            transposition_amount = int(params[1])
            note_ids = parse_note_ids(params[2:], "/live/clip/duplicate_notes_by_id")
            #--------------------------------------------------------------------------------
            # OSC has no null, so a negative destination time is the sentinel for
            # Live's None default (duplicate in place). -1 is the documented
            # spelling; any negative value means the same, which is why duplicating
            # *to* a negative beat is not reachable through this address.
            #--------------------------------------------------------------------------------
            if destination_time < 0:
                destination_time = None
            new_note_ids = clip.duplicate_notes_by_id(note_ids, destination_time,
                                                      transposition_amount)
            return tuple(int(note_id) for note_id in new_note_ids)

        def clip_select_notes_by_id(clip, params: Tuple[Any] = ()):
            clip.select_notes_by_id(parse_note_ids(params, "/live/clip/select_notes_by_id"))

        #--------------------------------------------------------------------------------
        # The two deprecated tuple members, exposed as pass-throughs for LOM
        # parity. Live's own docstrings carry no description of what they do, and
        # their semantics are unmeasured (API.md marks both). New clients should use
        # add/notes_extended and apply_note_modifications instead.
        #--------------------------------------------------------------------------------
        def clip_replace_selected_notes(clip, params: Tuple[Any] = ()):
            clip.replace_selected_notes(parse_deprecated_note_tuple(params, "/live/clip/replace_selected_notes"))

        def clip_set_notes(clip, params: Tuple[Any] = ()):
            clip.set_notes(parse_deprecated_note_tuple(params, "/live/clip/set_notes"))

        self.osc_server.add_handler("/live/clip/get/notes_extended", create_clip_callback(clip_get_notes_extended))
        self.osc_server.add_handler("/live/clip/add/notes_extended", create_clip_callback(clip_add_notes_extended))
        self.osc_server.add_handler("/live/clip/get/selected_notes_extended", create_clip_callback(clip_get_selected_notes_extended))
        self.osc_server.add_handler("/live/clip/get/selected_notes", create_clip_callback(clip_get_selected_notes))
        self.osc_server.add_handler("/live/clip/get_notes_by_id", create_clip_callback(clip_get_notes_by_id))
        self.osc_server.add_handler("/live/clip/apply_note_modifications", create_clip_callback(clip_apply_note_modifications))
        self.osc_server.add_handler("/live/clip/duplicate_notes_by_id", create_clip_callback(clip_duplicate_notes_by_id))
        self.osc_server.add_handler("/live/clip/select_notes_by_id", create_clip_callback(clip_select_notes_by_id))
        self.osc_server.add_handler("/live/clip/replace_selected_notes", create_clip_callback(clip_replace_selected_notes))
        self.osc_server.add_handler("/live/clip/set_notes", create_clip_callback(clip_set_notes))

        #--------------------------------------------------------------------------------
        # Clip: groove — a Seshat extension (D-2), and the first consumer of the
        # object-valued read pattern outside track_identity.py.
        #
        # `Clip.groove` holds a `Live.Groove.Groove`, so it can never enter the
        # generic property loops above: the OSC builder has no encoding for the
        # object, which is exactly upstream's commented-out "Infered arg_value
        # type is not supported". It is answered instead as an **index into
        # `song.groove_pool.grooves`** — the same index space /live/groove/* and
        # /live/song/get/groove_pool use.
        #
        # **The read is gated on `Clip.has_groove`, not on `clip.groove`'s
        # value.** Live never hands back None for that member — the flag exists
        # precisely because the member always holds an object — so an == scan
        # over the pool cannot express "no groove" and would answer 0,
        # indistinguishable from a clip assigned to pool index 0. Both the
        # getter and the listener push go through `clip_groove_index`, so they
        # can never disagree. ⚠️ That `has_groove` is false for a clip Live's UI
        # shows as ungrooved is Live's documented contract, not something this
        # fork has measured — see clip_groove_index's docstring.
        #
        # **Assignment is one-way.** The setter takes a pool index >= 0. It was
        # once specified to accept exactly -1 as "clear the assignment", the one
        # address in this fork where -1 was an *argument*; that exception is
        # withdrawn. `clip.groove = None` raises Boost.Python.ArgumentError —
        # Live's setter is typed (TPyHandle<AClip>, TPyHandle<AAbstractGroove>)
        # and refuses NoneType (measured against Live 12.4.5 on 2026-08-29) —
        # and no other spelling for "no groove" is documented in the LOM, so -1
        # is now rejected by this fork with a truthful message instead of being
        # forwarded to Live for a Boost ArgumentError. -2 and below, and any
        # index past the end of the pool, keep resolve_groove's out-of-range
        # ValueError → /live/error naming the pool's real size, never a Python
        # negative-index wrap-around.
        #
        # See API.md § "Clip API" for the wire detail, § "Groove API" for the
        # one-way reasoning, and § "Object-valued reads" for the convention
        # this fork no longer makes an exception to.
        #--------------------------------------------------------------------------------
        def clip_get_groove(clip, params: Tuple[Any] = ()):
            index = clip_groove_index(self.song, clip)
            self.logger.info("Getting property for clip: groove = %d" % index)
            return (index,)

        def clip_set_groove(clip, params: Tuple[Any] = ()):
            index = int(params[0])
            if index == NO_INDEX:
                #--------------------------------------------------------------------------------
                # Exactly -1 is rejected here rather than forwarded to Live.
                # Forwarding produced a Boost.Python.ArgumentError naming a C++
                # signature; this raise produces the same /live/error envelope
                # with a detail that names the actual limit. The branch stays
                # keyed on exactly NO_INDEX so -2 and below still fall through
                # to resolve_groove and keep their out-of-range message; the
                # literal "cannot be cleared" is what distinguishes the two on
                # the wire (tests_unit/test_groove.py asserts on it).
                #--------------------------------------------------------------------------------
                raise ValueError(
                    "A clip's groove cannot be cleared over this bridge: Live's "
                    "setter is typed (TPyHandle<AClip>, TPyHandle<AAbstractGroove>) "
                    "and rejects None (measured against Live 12.4.5, 2026-08-29). "
                    "No other spelling for \"no groove\" is documented in the LOM "
                    "(searched, not measured). Send a pool index >= 0 to assign; "
                    "un-assign in Live's Clip Groove chooser. This pool has "
                    "%d groove(s)." % len(self.song.groove_pool.grooves))
            #--------------------------------------------------------------------------------
            # resolve_groove validates before it indexes, so this line is the
            # rejection path for -2 and below, and for an index past the end of
            # the pool. `index` is already an int by here (truncated toward
            # zero above, this fork's documented convention), so a
            # non-integral negative float never reaches this line: -0.5
            # truncates to 0 (assigns pool[0]) and -1.5 truncates to -1 (the
            # NO_INDEX rejection above).
            #--------------------------------------------------------------------------------
            groove = resolve_groove(self.song, index)
            self.logger.info("Setting property for clip: groove = %d" % index)
            clip.groove = groove

        def clip_groove_listener_value(params: Tuple[Any]):
            #--------------------------------------------------------------------------------
            # `getter=` on _start_listen: without it the push would carry the raw
            # Groove object and fail to encode, dropping the datagram silently.
            # The clip is re-resolved from the pushed identity because a Clip
            # cannot report its own indices, and the identity is what the push
            # echoes — the appointed_device / scale_intervals precedent.
            #--------------------------------------------------------------------------------
            track_index, clip_index = params
            clip = self.song.tracks[track_index].clip_slots[clip_index].clip
            return clip_groove_index(self.song, clip)

        self.osc_server.add_handler("/live/clip/get/groove", create_clip_callback(clip_get_groove))
        self.osc_server.add_handler("/live/clip/set/groove", create_clip_callback(clip_set_groove))
        self.osc_server.add_handler("/live/clip/start_listen/groove",
                                    create_clip_callback(partial(self._start_listen,
                                                                 getter=clip_groove_listener_value),
                                                         "groove", pass_clip_index=True))
        self.osc_server.add_handler("/live/clip/stop_listen/groove",
                                    create_clip_callback(self._stop_listen, "groove",
                                                         pass_clip_index=True))

        def clips_filter_handler(params: Tuple):
            # TODO: Pre-cache clip notes
            if len(self._clip_notes_cache) == 0:
                self.logger.warning("Building clip notes cache...")
                self._build_clip_name_cache()
            else:
                self.logger.warning("Found existing clip notes cache (len = %d)" % len(self._clip_notes_cache))
            note_indices = [note_name_to_midi(name) for name in params]

            self.logger.warning("Got note indices: %s" % note_indices)
            for track_index, track in enumerate(self.song.tracks):
                for clip_slot_index, clip_slot in enumerate(track.clip_slots):
                    clip_notes_list = self._clip_notes_cache[track_index][clip_slot_index]
                    if clip_notes_list:
                        clip = clip_slot.clip
                        if all(note in note_indices for note in clip_notes_list):
                            clip.muted = False
                        else:
                            clip.muted = True

        self.osc_server.add_handler("/live/clips/filter", clips_filter_handler)

        def clips_unfilter_handler(params: Tuple):
            track_start = params[0] if len(params) > 0 else 0
            track_end = params[1] if len(params) > 1 else len(self.song.tracks)

            self.logger.info("Unfiltering tracks: %d .. %d" % (track_start, track_end))
            for track in self.song.tracks[track_start:track_end]:
                for clip_slot in track.clip_slots:
                    if clip_slot.has_clip:
                        clip = clip_slot.clip
                        clip.muted = False

        self.osc_server.add_handler("/live/clips/unfilter", clips_unfilter_handler)

    def _build_clip_name_cache(self):
        regex = "([_-])([A-G][A-G#b1-9-]*)$"
        for track_index, track in enumerate(self.song.tracks):
            self._clip_notes_cache.append([])
            for clip_slot_index, clip_slot in enumerate(track.clip_slots):
                self._clip_notes_cache[-1].append([])
                if clip_slot.has_clip:
                    clip = clip_slot.clip
                    clip_name = clip.name
                    match = re.search(regex, clip_name)
                    if match:
                        clip_notes_str = match.group(2)
                        clip_notes_str = re.sub("[1-9]", "", clip_notes_str)
                        clip_notes_list = clip_notes_str.split("-")
                        clip_notes_list = [note_name_to_midi(name) for name in clip_notes_list]
                        self._clip_notes_cache[-1][-1] = clip_notes_list
