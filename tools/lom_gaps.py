#!/usr/bin/env python3
"""
Regenerate the generated inventory in FORK_GAPS.md from a LOM dump.

    1. In Live, with this fork installed:  send /live/application/dump_lom
       (writes <install>/logs/lom_dump.json; see abletonosc/introspection.py)
    2. python3 tools/lom_gaps.py <lom_dump.json> [--write]

Without --write the markdown goes to stdout. With --write it replaces the
block between the lom-gaps:begin / lom-gaps:end markers in FORK_GAPS.md.

A member counts as covered when any segment of a fork OSC address under
one of the class's address prefixes equals the member name (num_X counts as
covering X). That is deliberately lenient — it under-reports gaps rather
than listing members that are reachable through a flattened address such
as /live/device/get/parameters/name.
"""
import json
import re
import sys
from collections import OrderedDict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOC = REPO / "FORK_GAPS.md"
BEGIN = "<!-- lom-gaps:begin -->"
END = "<!-- lom-gaps:end -->"

# OSC address prefix (/live/<x>/...) -> LOM classes those addresses reach.
PREFIX_CLASSES = {
    "song": ["Live.Song.Song"],
    "track": ["Live.Track.Track", "Live.MixerDevice.MixerDevice"],
    "return_track": ["Live.Track.Track", "Live.MixerDevice.MixerDevice"],
    "master": ["Live.Track.Track", "Live.MixerDevice.MixerDevice"],
    "clip": ["Live.Clip.Clip"],
    "clips": ["Live.Clip.Clip"],
    "clip_slot": ["Live.ClipSlot.ClipSlot"],
    "scene": ["Live.Scene.Scene"],
    "device": ["Live.Device.Device", "Live.DeviceParameter.DeviceParameter"],
    "view": ["Live.Song.Song.View", "Live.Application.Application.View",
             "Live.Track.Track.View", "Live.Clip.Clip.View"],
    "application": ["Live.Application.Application"],
    "browser": ["Live.Browser.Browser", "Live.Browser.BrowserItem"],
    "groove": ["Live.Groove.Groove"],
}
VERBS = {"get", "set", "start_listen", "stop_listen"}

# Reported in the main table, in this order. Everything else in the M4L
# table (device subclasses) goes to the compact section.
CORE = [
    "Live.Song.Song", "Live.Song.Song.View", "Live.Song.CuePoint",
    "Live.Application.Application", "Live.Application.Application.View",
    "Live.Track.Track", "Live.Track.Track.View", "Live.MixerDevice.MixerDevice",
    "Live.Clip.Clip", "Live.Clip.Clip.View", "Live.ClipSlot.ClipSlot", "Live.Scene.Scene",
    "Live.Device.Device", "Live.DeviceParameter.DeviceParameter", "Live.DeviceIO.DeviceIO",
    "Live.RackDevice.RackDevice", "Live.RackDevice.RackDevice.View", "Live.Chain.Chain",
    "Live.ChainMixerDevice.ChainMixerDevice", "Live.DrumPad.DrumPad", "Live.DrumChain.DrumChain",
    "Live.Browser.Browser", "Live.Browser.BrowserItem",
    "Live.Groove.Groove", "Live.GroovePool.GroovePool", "Live.Sample.Sample",
    "Live.TakeLane.TakeLane", "Live.TuningSystem.TuningSystem",
]
IGNORE = {"canonical_parent", "_live_ptr", "View"}

# LOM members the fork reaches under a different address than the member
# name. Each is treated as covered; the value says by what. Keep this honest:
# an alias means the *capability* is reachable, not merely something similar.
ALIASES = {
    "Live.Song.Song": {
        "master_track": "/live/master/*",
        "view": "/live/view/*",
        "tracks": "/live/track/*, /live/song/get/num_tracks",
        "return_tracks": "/live/return_track/*",
        "get_current_beats_song_time": "/live/song/get/current_song_time",
    },
    "Live.Application.Application": {
        "view": "/live/view/*",
        "browser": "/live/browser/*",
        "get_major_version": "/live/application/get/version",
        "get_minor_version": "/live/application/get/version",
        #--------------------------------------------------------------------------------
        # These four *are* exposed, under an address whose last segment drops
        # the "get_" prefix the Live method carries. Coverage is decided by
        # segment equality, so without an alias the tool would keep counting
        # them as gaps.
        #--------------------------------------------------------------------------------
        "get_bugfix_version": "/live/application/get/bugfix_version",
        "get_build_id": "/live/application/get/build_id",
        "get_variant": "/live/application/get/variant",
        "get_version_string": "/live/application/get/version_string",
    },
    "Live.Track.Track": {
        "clip_slots": "/live/clip_slot/*",
        "mixer_device": "/live/track/get/volume, panning, send",
        "view": "/live/view/*",
        "input_routings": "/live/track/get/available_input_routing_types (legacy string API superseded)",
        "output_routings": "/live/track/get/available_output_routing_types",
        "input_sub_routings": "/live/track/get/available_input_routing_channels",
        "output_sub_routings": "/live/track/get/available_output_routing_channels",
    },
    "Live.MixerDevice.MixerDevice": {"sends": "/live/track/get/send"},
    #--------------------------------------------------------------------------------
    # The pool's one member is reached under the *song* prefix, flattened, and
    # then per groove under /live/groove/* — neither of which is a segment
    # equal to "grooves", so without this alias the tool would keep counting it
    # a gap. (`Song.groove_pool` and `Clip.groove` need no alias: both are
    # segments of their own addresses already.)
    #--------------------------------------------------------------------------------
    "Live.GroovePool.GroovePool": {
        "grooves": "/live/song/get/groove_pool, /live/groove/*",
    },
    "Live.Scene.Scene": {"clip_slots": "/live/clip_slot/*"},
    "Live.ClipSlot.ClipSlot": {"clip": "/live/clip/*"},
    "Live.Clip.Clip": {
        "get_notes_extended": "/live/clip/get/notes, /live/clip/get/notes_extended",
        "get_all_notes_extended": "/live/clip/get/notes, /live/clip/get/notes_extended (no args)",
        "add_new_notes": "/live/clip/add/notes, /live/clip/add/notes_extended",
        "remove_notes_extended": "/live/clip/remove/notes",
        "get_notes": "/live/clip/get/notes (this is the deprecated tuple form)",
        "remove_notes": "/live/clip/remove/notes (deprecated form)",
        #--------------------------------------------------------------------------------
        # The verb-form selection getters: their last segment is
        # "selected_notes"/"selected_notes_extended", which does not equal the
        # member name, so segment equality alone would keep counting them as
        # gaps. The other extended-notes addresses are bare member names
        # (/live/clip/get_notes_by_id, /live/clip/set_notes, …) and need no
        # alias.
        #--------------------------------------------------------------------------------
        "get_selected_notes": "/live/clip/get/selected_notes",
        "get_selected_notes_extended": "/live/clip/get/selected_notes_extended",
    },
    #--------------------------------------------------------------------------------
    # /live/device/replace_sample is registered under the "device" prefix, whose
    # class list is Live.Device.Device and Live.DeviceParameter.DeviceParameter
    # only — it does not include SimplerDevice — so segment equality alone would
    # keep counting this member a gap after it shipped. An honest alias: the
    # capability *is* reachable, under a prefix the class map does not associate
    # with the class.
    #
    # Deliberately not fixed by adding Live.SimplerDevice.SimplerDevice to
    # PREFIX_CLASSES["device"]: that would silently re-mark every other
    # SimplerDevice member whose name happens to collide with a /live/device/*
    # segment as covered.
    #
    # Track.create_audio_clip and ClipSlot.create_audio_clip need no alias —
    # /live/track/create_audio_clip and /live/clip_slot/create_audio_clip are
    # segments of their own addresses under prefixes whose class lists do reach
    # those classes, and neither leaks to Live.TakeLane.TakeLane (which has a
    # create_audio_clip of its own but is in no prefix's class list).
    #--------------------------------------------------------------------------------
    "Live.SimplerDevice.SimplerDevice": {
        "replace_sample": "/live/device/replace_sample",
    },
}


def m4l_class_to_qual(key):
    # "Song.View" -> "Live.Song.Song.View"; "Song.Song" -> "Live.Song.Song"
    mod, cls = key.split(".", 1)
    if cls == "View":
        return "Live.%s.%s.View" % (mod, mod)
    return "Live.%s.%s" % (mod, cls)


def covered_names(addresses):
    cov = {}
    for addr in addresses:
        parts = addr.strip("/").split("/")
        if len(parts) < 3 or parts[0] != "live":
            continue
        prefix, rest = parts[1], parts[2:]
        names = set()
        for seg in rest:
            if seg in VERBS:
                continue
            names.add(seg)
            if seg.startswith("num_"):
                names.add(seg[4:])
            if seg == "parameter":
                names.add("parameters")
        for cls in PREFIX_CLASSES.get(prefix, []):
            cov.setdefault(cls, set()).update(names)
    return cov


def members(cls_entry):
    """{name: (kind, settable, observable, doc)} for the reportable members."""
    ms = cls_entry["members"]
    observable = {v["observes"] for v in ms.values() if v.get("kind") == "listener"}
    out = OrderedDict()
    for name in sorted(ms):
        info = ms[name]
        if name in IGNORE or name.startswith("__"):
            continue
        k = info.get("kind")
        if k == "property":
            out[name] = ("rw" if info.get("settable") else "ro", name in observable, info.get("doc", ""))
        elif k == "method":
            out[name] = ("method", name in observable, info.get("doc", ""))
    return out


def esc(s):
    return s.replace("|", "\\|").replace("\n", " ")


def render(dump):
    classes = dump["classes"]
    m4l_raw = dump["mxd"].get("AVAILABLE_TYPE_PROPERTIES", {})
    m4l = {m4l_class_to_qual(k): {row[0] for row in v} for k, v in m4l_raw.items()}
    cov = covered_names(dump["osc_addresses"])

    lines = []
    lines.append("_Generated by `tools/lom_gaps.py` from a `/live/application/dump_lom` "
                 "taken against Live %s. Do not edit by hand; rerun the tool. "
                 "%d Live classes walked, %d fork addresses registered._"
                 % (dump["live_version"], len(classes), len(dump["osc_addresses"])))
    lines.append("")
    lines.append("Legend: **rw**/**ro** property, **method**; **obs** = Live offers "
                 "an `add_<name>_listener` (a `start_listen` address is possible); "
                 "**M4L** = also in Max for Live's `LomTypes` exposure table "
                 "(members absent there are Remote-Script-only and undocumented in the apiref). "
                 "Every row is tier 1 evidence (name and kind read from the running Live); "
                 "nothing here has been called.")
    lines.append("")

    totals = {"covered": 0, "gap": 0}
    ordered = [c for c in CORE if c in classes]
    others = sorted(c for c in m4l if c in classes and c not in CORE)

    device_members = set(members(classes["Live.Device.Device"])) if "Live.Device.Device" in classes else set()

    def class_block(cls, compact):
        ms = members(classes[cls])
        got = cov.get(cls, set()) | set(ALIASES.get(cls, {}))
        inherited = set()
        if compact and cls != "Live.Device.Device":
            inherited = {n for n in ms if n in device_members}
            for n in inherited:
                del ms[n]
        gaps = [(n, *v) for n, v in ms.items() if n not in got]
        done = [n for n in ms if n in got]
        totals["covered"] += len(done)
        totals["gap"] += len(gaps)
        m4l_names = m4l.get(cls, set())
        head = "### `%s` — %d members, %d exposed, %d gaps" % (cls, len(ms), len(done), len(gaps))
        if inherited:
            head += " (+%d inherited from `Device`, see above)" % len(inherited)
        lines.append(head)
        lines.append("")
        aliased = [n for n in ms if n in ALIASES.get(cls, {}) and n not in cov.get(cls, set())]
        if aliased:
            lines.append("_Reached under another address:_ " + "; ".join(
                "`%s` → %s" % (n, ALIASES[cls][n]) for n in aliased))
            lines.append("")
        if not gaps:
            lines.append("_No gaps._")
            lines.append("")
            return
        if compact or not done:
            # whole class unexposed, or a device subclass: one line per kind
            by_kind = {}
            for n, kind, obs, _ in gaps:
                tag = n + ("*" if obs else "") + ("" if n in m4l_names else "†")
                by_kind.setdefault(kind, []).append("`%s`" % tag)
            if not done:
                lines.append("_Whole class unexposed._ ")
            for kind in ("rw", "ro", "method"):
                if kind in by_kind:
                    lines.append("- **%s:** %s" % (kind, ", ".join(by_kind[kind])))
            lines.append("")
            lines.append("_`*` observable, `†` not in M4L table._")
            lines.append("")
            return
        lines.append("| member | kind | obs | M4L | Live docstring |")
        lines.append("|---|---|---|---|---|")
        for n, kind, obs, doc in gaps:
            lines.append("| `%s` | %s | %s | %s | %s |" % (
                n, kind, "yes" if obs else "", "yes" if n in m4l_names else "", esc(doc)))
        lines.append("")

    lines.append("## Core classes")
    lines.append("")
    for cls in ordered:
        class_block(cls, compact=False)
    lines.append("## Device subclasses and remaining M4L classes")
    lines.append("")
    lines.append("_Reachable only through `Live.Device.Device` today; the fork has no "
                 "per-device-type addresses at all, so these are listed compactly._")
    lines.append("")
    for cls in others:
        class_block(cls, compact=True)

    summary = ("**Totals:** %d members exposed, %d gaps across %d classes."
               % (totals["covered"], totals["gap"], len(ordered) + len(others)))
    lines.insert(2, summary)
    lines.insert(3, "")
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    dump = json.load(open(sys.argv[1]))
    md = render(dump)
    if "--write" in sys.argv:
        text = DOC.read_text()
        if BEGIN not in text or END not in text:
            text = text.rstrip() + "\n\n## Generated inventory\n\n" + BEGIN + "\n" + END + "\n"
        pre, rest = text.split(BEGIN, 1)
        _, post = rest.split(END, 1)
        DOC.write_text(pre + BEGIN + "\n" + md + "\n" + END + post)
        print("wrote", DOC)
    else:
        print(md)


if __name__ == "__main__":
    main()
