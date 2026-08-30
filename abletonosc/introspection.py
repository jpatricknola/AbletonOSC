"""
LOM surface dump — the machine side of FORK_GAPS.md.

dump_lom() walks every class reachable from the `Live` module (submodules,
nested classes such as Live.Song.Song.View), and every module that carries
members of its own — Boost.Python free functions such as
Live.Conversions.audio_to_midi_clip, which are recorded under the module's
qualname with "kind": "module" on the entry. It records each member's kind:
property (with whether it has a setter), method (with the Boost.Python
docstring, which carries the signature), listener (add_X_listener, i.e. X is
observable), nested class, or enum value. It also serialises the tables in
_MxDCore.LomTypes, which are the exact member lists Max for Live exposes,
and the OSC server's registered addresses, so a single file holds both
sides of the gap diff. tools/lom_gaps.py turns that file into the table in
FORK_GAPS.md.

Runs inside Live only (imports Live). Triggered by
/live/application/dump_lom [path]; default path is logs/lom_dump.json next
to abletonosc.log.
"""
import inspect
import json
import logging
import os
import re
import time

logger = logging.getLogger("abletonosc")


def _doc(obj):
    doc = getattr(obj, "__doc__", None)
    if not doc:
        return ""
    return doc.strip().splitlines()[0][:300]


def _classify(name, attr):
    if isinstance(attr, property):
        return {
            "kind": "property",
            "settable": attr.fset is not None,
            "doc": _doc(attr),
        }
    if isinstance(attr, type):
        return {"kind": "class"}
    if callable(attr):
        if name.startswith("add_") and name.endswith("_listener"):
            return {"kind": "listener", "observes": name[4:-9]}
        if name.startswith("remove_") and name.endswith("_listener"):
            return {"kind": "listener_remove"}
        if name.endswith("_has_listener"):
            return {"kind": "listener_query"}
        return {"kind": "method", "doc": _doc(attr)}
    return {"kind": "value", "type": type(attr).__name__, "repr": repr(attr)[:100]}


def _visit_class(cls, qualname, classes, seen):
    if id(cls) in seen:
        return
    seen.add(id(cls))
    members = {}
    for name in dir(cls):
        if name.startswith("__"):
            continue
        try:
            attr = getattr(cls, name)
        except Exception as e:
            members[name] = {"kind": "error", "error": str(e)}
            continue
        members[name] = _classify(name, attr)
        if isinstance(attr, type):
            _visit_class(attr, qualname + "." + name, classes, seen)
    classes[qualname] = {"doc": _doc(cls), "members": members}


def _visit_module(mod, qualname, classes, seen):
    #--------------------------------------------------------------------------------
    # Members registered directly on a module — Boost.Python free functions —
    # are recorded under the module's own qualname, with the same _classify()
    # the class walk uses, so a free function lands as {"kind": "method"}
    # carrying its docstring, which is where Boost.Python keeps the signature.
    #
    # They used to be dropped silently: this function handled submodules and
    # classes and had no else branch, so Live.Conversions appeared in the dump
    # as nothing but its AudioToMidiType enum (a class), while
    # audio_to_midi_clip, is_convertible_to_midi and five more members of the
    # same module were invisible. FORK_GAPS.md is generated from this dump, so
    # absence from it was not evidence of absence from Live. See BLIND_SPOTS.md.
    #
    # Module entries carry "kind": "module" so tools/lom_gaps.py can tell them
    # apart from classes in the same dict, and are recorded only when they hold
    # at least one such member — most modules hold none, and empty entries
    # would inflate the walked count for nothing.
    #--------------------------------------------------------------------------------
    if id(mod) in seen:
        return
    seen.add(id(mod))
    members = {}
    for name in dir(mod):
        if name.startswith("__"):
            continue
        try:
            attr = getattr(mod, name)
        except Exception as e:
            members[name] = {"kind": "error", "error": str(e)}
            continue
        if inspect.ismodule(attr):
            _visit_module(attr, qualname + "." + name, classes, seen)
        elif isinstance(attr, type):
            _visit_class(attr, qualname + "." + name, classes, seen)
        else:
            members[name] = _classify(name, attr)
    if members:
        classes[qualname] = {"doc": _doc(mod), "members": members, "kind": "module"}


def walk_live():
    """
    Return {qualified_name: {member_name: info}} for every class reachable
    from the Live module, plus every module that carries members of its own.
    """
    import Live
    classes = {}
    seen = set()
    _visit_module(Live, "Live", classes, seen)
    # Boost.Python submodules can be absent from dir(Live) until imported;
    # LomTypes' table names every class Max for Live sees, so pull those too.
    try:
        from _MxDCore.LomTypes import AVAILABLE_TYPE_PROPERTIES
        for cls in AVAILABLE_TYPE_PROPERTIES:
            if isinstance(cls, type):
                _visit_class(cls, cls.__module__ + "." + cls.__name__, classes, seen)
    except Exception as e:
        logger.warning("LomTypes class sweep failed: %s" % e)
    return classes


def _jsonable(obj, depth=0):
    if depth > 6:
        return repr(obj)
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    if isinstance(obj, dict):
        return {str(_key(k)): _jsonable(v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [_jsonable(v, depth + 1) for v in obj]
    if isinstance(obj, type):
        return getattr(obj, "__module__", "") + "." + obj.__name__
    return repr(obj)


def _key(k):
    if isinstance(k, type):
        return getattr(k, "__module__", "") + "." + k.__name__
    return k


def mxd_tables():
    """
    Serialise every module-level container in _MxDCore.LomTypes. These are
    Max for Live's own exposure lists; the names are stable across versions
    (PROPERTY_TYPES, ENUM_TYPES, ROOT_KEYS, ...) but nothing here depends on
    a particular one existing.
    """
    try:
        from _MxDCore import LomTypes
    except Exception as e:
        return {"error": str(e)}
    out = {}
    for name in dir(LomTypes):
        if name.startswith("_"):
            continue
        value = getattr(LomTypes, name)
        if isinstance(value, (dict, list, tuple, set, frozenset)):
            try:
                out[name] = _jsonable(value)
            except Exception as e:
                out[name] = {"error": str(e)}
    return out


def dump_lom(path, osc_server=None):
    import Live
    app = Live.Application.get_application()
    data = {
        "live_version": "%d.%d.%d" % (app.get_major_version(),
                                      app.get_minor_version(),
                                      app.get_bugfix_version()),
        "classes": walk_live(),
        "mxd": mxd_tables(),
        "osc_addresses": sorted(osc_server._callbacks.keys()) if osc_server else [],
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=1, sort_keys=True)
    logger.info("Wrote LOM dump: %s (%d classes, %d addresses)"
                % (path, len(data["classes"]), len(data["osc_addresses"])))
    return path, len(data["classes"]), len(data["osc_addresses"])


#--------------------------------------------------------------------------------
# The instance walk — tier 2, and the other half of this module.
#
# Everything above records what Live *declares*: names, kinds and docstrings
# read off classes. None of it is ever called, and a declared signature is not
# a contract — Live.Conversions.audio_to_midi_clip declares `-> None` and is
# asynchronous, which decided the entire shape of the handler built on it.
#
# What follows holds real objects and reads them. It answers two questions no
# static walk can (BLIND_SPOTS.md blind spots 4 and 5):
#
#   1. What type is behind a property? Every one of Live's 894 properties has
#      a getter and not one carries a docstring (measured: `Q1 properties=894
#      with_fget=894 fget_doc=0`), so `Song.tracks` documents its element type
#      as prose and nowhere else. Holding a Song and reading type() off what
#      comes back is the only channel there is.
#   2. What surface does a given *kind* of object carry? Live.Device.Device is
#      one walked class whose instances differ by class_name; a Wavetable and
#      an Operator are two different capability surfaces reached through it.
#
# Read-only by construction, and it has to stay that way:
#
#   - no instantiation, and nothing is loaded from the browser
#   - a method is called only when it passes is_read_shaped() below
#   - listener members are recorded and NEVER called. Not a style rule: this
#     machine's Seshat subscribes to song tempo, signature, is_playing,
#     root_note, scale_name, groove/swing, tracks, return_tracks and the master
#     mixer params, and a stray stop_listen would silently unsubscribe a
#     running consumer. The walk cannot do that because it calls no listener
#     member at all.
#   - every read is wrapped individually. hasattr() is not a safe feature test
#     on a LOM object and a failed read is not falsy: master_track.mute raises
#     RuntimeError rather than returning False, and one unguarded read would
#     abandon the rest of the walk.
#
# Output is logs/lom_instances.json, written beside lom_dump.json and
# deliberately NOT merged into it. The two have different provenance and
# different lifetimes: lom_dump.json is per-Live-version and reproducible from
# any session, this file is per-*set* and is only as good as the set it was
# taken against. FORK_GAPS.md is a member-level coverage diff generated from
# the former, and instance shape is not member-level surface, so merging would
# make that report's numbers move with whatever set happened to be open.
# tools/lom_gaps.py therefore does not read this file and is untouched by it.
#--------------------------------------------------------------------------------

READ_METHOD_PREFIXES = ("get_", "is_", "has_", "can_")

#--------------------------------------------------------------------------------
# Policy overrides on top of the syntactic predicate, by *qualified* name — a
# get_session_id elsewhere in Live would be a different method.
#
# Measured 2026-08-30 against Live 12.4.5: of 589 methods, 44 carry one of the
# prefixes above and 18 of those take only the receiver. Three of the 18 are
# these. BLIND_SPOTS.md states the rule they fall under — "Reachable is not
# desirable. Live.Licensing is reachable and stays shut" — and
# get_progress_dialog is additionally dialog-adjacent, next to the
# press_current_dialog_button decline in ROADMAP.md's "Deliberately not
# planned": a dialog on screen may be guarding unsaved work.
#
# A syntactic predicate was always going to need a policy override. This is it,
# and it was found by measuring rather than by argument. Any future entry
# carries its own reason on the line above it.
#--------------------------------------------------------------------------------
READ_METHOD_DENYLIST = frozenset([
    "Live.Licensing.PythonLicensingBridge.get_progress_dialog",
    "Live.Licensing.PythonLicensingBridge.get_session_id",
    "Live.Licensing.PythonLicensingBridge.get_trial_time_left",
])

#--------------------------------------------------------------------------------
# song -> tracks -> track -> devices -> device -> parameters -> parameter is
# depth 6, so 8 leaves headroom for a rack chain without letting a
# canonical_parent back-edge that the id() guard somehow misses run away.
#--------------------------------------------------------------------------------
WALK_MAX_DEPTH = 8

#--------------------------------------------------------------------------------
# A vector's element *type* comes from its first element: a 1,000-note vector's
# elements are all the same type and reading every one is pure cost.
#
# Recursion is capped only for payload vectors. Structural collections must be
# traversed in full: "which DeviceParameters does a Wavetable carry" is
# unanswerable if the Wavetable happens to be on track 65. Note selections and
# warp markers can contain thousands of same-shaped value objects, so those
# named payloads retain a separate recursion budget.
#--------------------------------------------------------------------------------
VECTOR_RECURSE_LIMIT = 64

VECTOR_PAYLOAD_MEMBERS = frozenset([
    "get_all_notes_extended",
    "get_selected_notes",
    "get_selected_notes_extended",
    "notes",
    "warp_markers",
])

REPR_LIMIT = 100
EXAMPLE_PATH_LIMIT = 3


def _docstring_arity(doc):
    """
    Number of arguments in a Boost.Python signature docstring, or None when it
    does not parse.

    Boost.Python keeps the signature in the docstring and exposes nothing to
    inspect.signature(), so this string is the only place an arity can come
    from:

        get_document( (Application)arg1) -> Song :                      -> 1
        get_data( (Song)arg1, (object)key, (object)default_value) -> ...-> 3

    Commas inside the parenthesised type prefixes are not separators, hence the
    depth counter rather than a split(",").
    """
    if not doc:
        return None
    match = re.match(r"\s*[A-Za-z_][A-Za-z_0-9]*\(\s*(.*?)\s*\)\s*->", doc)
    if not match:
        return None
    inner = match.group(1)
    if inner == "":
        return 0
    depth = 0
    count = 1
    for char in inner:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            count += 1
    return count


def is_read_shaped(name, doc, owner=""):
    """
    Whether the sweep may call this method.

    Three rules, all of which must hold: the name carries a read prefix; the
    docstring parses to a signature taking exactly one argument, the receiver;
    and the qualified name is not denylisted.

    Fails closed on purpose. A docstring that does not parse is skipped rather
    than called, because the arity is the only thing standing between a read
    sweep and calling a mutator with no arguments.
    """
    if not name.startswith(READ_METHOD_PREFIXES):
        return False
    if _docstring_arity(doc) != 1:
        return False
    qualified = (owner + "." + name) if owner else name
    return qualified not in READ_METHOD_DENYLIST


def _is_listener_member(name):
    """
    The three listener shapes _classify() already names. Recorded, never
    called — see the module comment above.
    """
    return ((name.startswith("add_") and name.endswith("_listener"))
            or (name.startswith("remove_") and name.endswith("_listener"))
            or name.endswith("_has_listener"))


def _qualname(obj):
    #--------------------------------------------------------------------------------
    # Measured 2026-08-30, Live 12.4.5: Boost.Python sets __module__ to the
    # *leaf* module name, not the dotted path — type(song).__module__ is
    # "Song", not "Live.Song". Left alone, every key here would be "Song.Song"
    # and could not be compared against lom_dump.json's "Live.Song.Song", which
    # is the whole point of taking both dumps.
    #
    # __qualname__ is preferred where Boost.Python provides it, because a
    # nested class is "Song.View" there and the class walk records it as
    # Live.Song.Song.View.
    #--------------------------------------------------------------------------------
    cls = type(obj)
    module = getattr(cls, "__module__", "") or ""
    name = getattr(cls, "__qualname__", None) or cls.__name__
    qualname = (module + "." + name) if module else name
    if not qualname.startswith("Live."):
        qualname = "Live." + qualname
    return qualname


def _is_vector(value):
    """
    Container-shaped: something to iterate for element types rather than an
    object to walk. Strings and bytes have __len__ and are neither.
    """
    if isinstance(value, (str, bytes, bytearray)):
        return False
    return hasattr(type(value), "__len__") and hasattr(type(value), "__iter__")


def _is_live_object(value):
    """
    Whether this value is an object to walk into.

    Measured 2026-08-30, Live 12.4.5: every walkable Live object derives from
    ``LomObject`` and every vector does not —

        song       -> Song.Song, LomObject.LomObject, Boost.Python.instance
        track      -> Track.Track, Track.DeviceContainer, LomObject.LomObject, ...
        song.tracks-> Base.Vector, Boost.Python.instance

    so this one check both identifies a Live object and separates it from a
    container, which is exactly the split the walk needs. Keying off
    ``__module__`` instead does not work: Boost.Python sets it to the leaf name
    ("Song"), so a "Live." prefix test matches nothing at all — the first run
    of this walk recursed into zero objects for precisely that reason.
    """
    if value is None or isinstance(value, (bool, int, float, str, bytes)):
        return False
    try:
        mro = type(value).__mro__
    except Exception:
        return False
    return any(base.__name__ == "LomObject" for base in mro)


def _short_repr(value):
    try:
        return repr(value)[:REPR_LIMIT]
    except Exception as e:
        return "<repr failed: %s>" % type(e).__name__


def _error_key(exc):
    return "%s: %s" % (type(exc).__name__, exc)


def _bump(mapping, key):
    mapping[key] = mapping.get(key, 0) + 1


class _InstanceWalk:
    """
    One traversal. Holds the id() cycle guard and the accumulating record so
    that walk_instances() stays a function over its arguments.
    """

    def __init__(self, max_depth=WALK_MAX_DEPTH):
        self.max_depth = max_depth
        self.types = {}
        self.seen = set()
        self.device_class_names = set()
        self.totals = {"objects": 0, "reads": 0, "errors": 0, "calls": 0}
        self.skipped = {
            "methods_not_read_shaped": 0,
            "methods_denylisted": [],
            "listeners_never_called": 0,
            "depth_truncations": 0,
            "cycle_hits": 0,
            "vector_truncations": 0,
        }

    #--------------------------------------------------------------------------------
    # An object's key is its type qualname plus a discriminator, because
    # Live.Device.Device is one type whose instances are different capability
    # surfaces. class_name is itself a LOM read and gets the same guard as
    # every other one.
    #--------------------------------------------------------------------------------
    def _key(self, obj):
        qualname = _qualname(obj)
        try:
            class_name = getattr(obj, "class_name", None)
        except Exception:
            class_name = None
        if isinstance(class_name, str) and class_name:
            self.device_class_names.add(class_name)
            return qualname + "/" + class_name
        return qualname

    def _entry(self, key):
        if key not in self.types:
            self.types[key] = {"instances": 0, "example_paths": [], "members": {}}
        return self.types[key]

    def _member(self, entry, name, kind):
        members = entry["members"]
        if name not in members:
            members[name] = {"kind": kind, "reads": 0, "types": {}}
        return members[name]

    #--------------------------------------------------------------------------------
    # Identity, and it is NOT id().
    #
    # Measured 2026-08-30, Live 12.4.5: Boost.Python hands back a *fresh Python
    # wrapper* on every property access, so `song.groove_pool.canonical_parent
    # is song` is False and id() differs every time. An id()-keyed guard
    # therefore never fires on the real graph. The first run of this walk did
    # exactly that: it recorded the same Song 11 times, walked
    # song.groove_pool.canonical_parent.groove_pool.canonical_parent... until
    # the depth bound stopped it (94 truncations), and never reached
    # Song.tracks at all — while reporting 0 errors, because a walk that
    # wanders in a circle looks identical to a walk that succeeded.
    #
    # id() is also actively unsafe here: those short-lived wrappers are
    # collected, addresses are reused, and a reused address reads as a cycle
    # hit against an object that was never visited — 54 of them in that run.
    #
    # _live_ptr is Live's own pointer to the underlying C++ object. It is an
    # int, it is stable across wrappers, and every LomObject carries it. Vector
    # elements and anything without it fall back to id(), which is correct for
    # objects that are not LOM objects to begin with.
    #--------------------------------------------------------------------------------
    def _identity(self, obj):
        try:
            pointer = obj._live_ptr
        except Exception:
            pointer = None
        if isinstance(pointer, int):
            return ("live_ptr", pointer)
        return ("id", id(obj))

    def visit(self, obj, path, depth=0):
        if depth > self.max_depth:
            self.skipped["depth_truncations"] += 1
            return
        identity = self._identity(obj)
        if identity in self.seen:
            self.skipped["cycle_hits"] += 1
            return
        self.seen.add(identity)

        entry = self._entry(self._key(obj))
        entry["instances"] += 1
        if len(entry["example_paths"]) < EXAMPLE_PATH_LIMIT:
            entry["example_paths"].append(path)
        self.totals["objects"] += 1

        try:
            names = dir(obj)
        except Exception:
            return

        for name in names:
            if name.startswith("__"):
                continue
            self._visit_member(obj, entry, name, path, depth)

    def _visit_member(self, obj, entry, name, path, depth):
        #--------------------------------------------------------------------------------
        # Classify off the *class*, not the instance: reading the attribute is
        # what we are deciding whether to do, so it cannot also be how we
        # decide. A property read here would call the getter of every member,
        # including the ones this function exists to refuse.
        #--------------------------------------------------------------------------------
        try:
            class_attr = getattr(type(obj), name, None)
        except Exception:
            class_attr = None

        if _is_listener_member(name):
            self._member(entry, name, "listener")
            self.skipped["listeners_never_called"] += 1
            return

        if isinstance(class_attr, property):
            self._read(obj, entry, name, "property", path, depth)
            return

        if callable(class_attr):
            doc = _doc(class_attr)
            if is_read_shaped(name, doc, _qualname(obj)):
                self._read(obj, entry, name, "method", path, depth, call=True)
            else:
                self._member(entry, name, "method")
                self.skipped["methods_not_read_shaped"] += 1
                qualified = _qualname(obj) + "." + name
                if (qualified in READ_METHOD_DENYLIST
                        and qualified not in self.skipped["methods_denylisted"]):
                    self.skipped["methods_denylisted"].append(qualified)
            return

        #--------------------------------------------------------------------------------
        # Not a property and not callable: a constant registered on the class.
        # Recorded from the class attribute already in hand, no instance read.
        #--------------------------------------------------------------------------------
        if class_attr is not None:
            record = self._member(entry, name, "value")
            record["reads"] += 1
            _bump(record["types"], type(class_attr).__name__)
            record.setdefault("repr", _short_repr(class_attr))

    def _read(self, obj, entry, name, kind, path, depth, call=False):
        record = self._member(entry, name, kind)
        try:
            value = getattr(obj, name)
            if call:
                value = value()
                self.totals["calls"] += 1
        except Exception as e:
            #--------------------------------------------------------------------------------
            # The expected case, not the exceptional one. master_track.mute
            # raises RuntimeError on every set there is; a member that is
            # registered but unreadable in this session is exactly the kind of
            # fact the walk exists to record.
            #--------------------------------------------------------------------------------
            errors = record.setdefault("errors", {})
            _bump(errors, _error_key(e))
            self.totals["errors"] += 1
            return

        record["reads"] += 1
        self.totals["reads"] += 1
        _bump(record["types"], type(value).__name__)
        record.setdefault("repr", _short_repr(value))

        if _is_vector(value):
            self._read_vector(record, value, path, name, depth)
        elif _is_live_object(value):
            self.visit(value, "%s.%s" % (path, name), depth + 1)

    def _read_vector(self, record, value, path, name, depth):
        #--------------------------------------------------------------------------------
        # The element type is the answer blind spot 4 could not reach
        # statically: Song.tracks documents its contents as prose and carries
        # no type anywhere in the interpreter. This is the only place in this
        # repository where a property's value type is recorded rather than
        # inferred.
        #--------------------------------------------------------------------------------
        try:
            elements = list(value)
        except Exception as e:
            _bump(record.setdefault("errors", {}), _error_key(e))
            self.totals["errors"] += 1
            return

        record["length"] = len(elements)
        if elements:
            first = elements[0]
            element_type = (_qualname(first) if _is_live_object(first)
                            else type(first).__name__)
            _bump(record.setdefault("element_types", {}), element_type)

        recurse_limit = (VECTOR_RECURSE_LIMIT
                         if name in VECTOR_PAYLOAD_MEMBERS else len(elements))
        if len(elements) > recurse_limit:
            self.skipped["vector_truncations"] += 1
        for index, element in enumerate(elements[:recurse_limit]):
            if _is_live_object(element):
                self.visit(element, "%s.%s[%d]" % (path, name, index), depth + 1)


def walk_instances(roots, max_depth=WALK_MAX_DEPTH):
    """
    Traverse real Live objects from `roots`, a sequence of (path, object)
    pairs, and return (types, totals, skipped, device_class_names).

    Reads only. See the module comment above for the rules this holds to and
    why each one is there.
    """
    walk = _InstanceWalk(max_depth=max_depth)
    for path, obj in roots:
        if obj is not None:
            walk.visit(obj, path, 0)
    return walk.types, walk.totals, walk.skipped, sorted(walk.device_class_names)


def _guarded(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _provenance(song, device_class_names, walk_seconds):
    """
    Which set produced this dump. A walk over a working set measures that set,
    not Live, and a dump that cannot say which set it came from cannot be
    compared against the next one.
    """
    return {
        "song_file_path": _guarded(lambda: song.file_path),
        "track_count": _guarded(lambda: len(song.tracks)),
        "return_track_count": _guarded(lambda: len(song.return_tracks)),
        "scene_count": _guarded(lambda: len(song.scenes)),
        "device_class_names": device_class_names,
        "coverage": "set-scoped",
        "walk_seconds": walk_seconds,
    }


def dump_lom_instances(path, song):
    """
    Walk the live object graph and write logs/lom_instances.json.

    Takes no path from the wire — see the handler in application.py.
    """
    import Live
    app = Live.Application.get_application()

    started = time.time()
    types, totals, skipped, device_class_names = walk_instances([
        ("application", app),
        ("song", song),
    ])
    walk_seconds = round(time.time() - started, 3)

    data = {
        "schema": 1,
        "live_version": "%d.%d.%d" % (app.get_major_version(),
                                      app.get_minor_version(),
                                      app.get_bugfix_version()),
        "provenance": _provenance(song, device_class_names, walk_seconds),
        "types": types,
        "skipped": skipped,
        "totals": dict(totals, types=len(types)),
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=1, sort_keys=True)

    logger.info("Wrote LOM instance dump: %s (%d types, %d objects, %d reads, "
                "%d calls, %d errors, %.3fs)"
                % (path, len(types), totals["objects"], totals["reads"],
                   totals["calls"], totals["errors"], walk_seconds))
    return path, len(types), totals["objects"], totals["errors"]
