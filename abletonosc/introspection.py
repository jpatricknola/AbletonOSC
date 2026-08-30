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
