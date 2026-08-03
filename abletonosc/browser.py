import json
import os
import stat
import tempfile
import time
from typing import Any, Optional, Tuple

import Live

from .handler import AbletonOSCHandler

#--------------------------------------------------------------------------------
# Browser API — a Seshat extension, added in this fork.
#
# Upstream AbletonOSC exposes no browser API at all, so this handler adds the
# endpoints Seshat needs in order to find and load instruments and effects:
#
#   /live/browser/get/items   [category, filter, max_results]
#     -> [category, filter, "ok", returned, total, name, path, uri, ...]
#     -> [category, filter, "error", message]
#
#   /live/browser/load_item   [track_index, uri]
#     -> [track_index, uri, "ok", loaded_device_name, loaded_device_index]
#     -> [track_index, uri, "error", message]
#
# `loaded_device_index` is the device's position in `track.devices` — the index
# /live/view/set/selected_device and the /live/device/* addresses take — so the
# caller can steer Live's view onto what it just loaded without a second query.
# It is -1 when the device is not on the chain yet, which some VST/AU plugins do
# by instantiating asynchronously.
#
#   /live/browser/load_item_on_return   [return_index, uri]
#     -> [return_index, uri, "ok", return_name, device_name, device_index]
#     -> [return_index, uri, "error", message]
#
#   /live/browser/load_item_on_master   [uri]
#     -> [uri, "ok", device_name, device_index]
#     -> [uri, "error", message]
#
# Separate addresses rather than a widened load_item, so the shipped address
# keeps its exact shape and the reply arity itself says which index space was
# targeted. `browser.load_item` loads onto whatever `song.view.selected_track`
# is, and that accepts a return track or the master perfectly well — so all
# three share one implementation and differ only in how the target is resolved
# and how the reply is spelled.
#
# `load_item_on_return` reports the return's name **read back after the load**:
# Live renames an empty return the moment its first device lands (`A-Return`
# became `A-Reverb`, measured 2026-07-31), so a name echoed from before the load
# would be wrong in exactly the case the caller most wants to report.
#
# Both new endpoints carry a guard the regular-track load doesn't need.
# Measured 2026-07-31 on both a return and the master: loading a *non-effect*
# item (an instrument) with one of them selected does not fail — Live silently
# **creates a new MIDI track** and loads the instrument there, leaving the
# target chain untouched. So the load is checked twice: the set's track count
# must be unchanged, and the target's device chain must have gained something.
# Either check failing is an error reply naming what actually happened. The
# stray track is deliberately **not** deleted here — reporting it and letting
# the caller offer to remove it is the lesson of Seshat's removed create_project.
#
#   /live/browser/export      []
#     -> [export_path, "ok", total_items]
#     -> ["", "error", message]
#
# export takes **no arguments**: this handler chooses the destination itself,
# inside EXPORT_ROOT below, and returns the absolute path it actually wrote. A
# caller-supplied path would be opened with Live's privileges, and the one client
# never needed to name the file. A request that still carries the obsolete
# [dest_path] argument is rejected without writing anything.
#
#   /live/browser/preview_item  [uri]
#     -> [uri, "ok", name]
#     -> [uri, "error", message]
#
#   /live/browser/stop_preview  []
#     -> ["ok"]
#     -> ["error", message]
#
# All endpoints always reply on the address they were called on, including on
# every error path — OSC is fire-and-forget UDP, so a client waiting for a
# matching reply would otherwise hang until its timeout. stop_preview takes no
# argument and so has no failure to report, but it still replies "ok" rather
# than staying silent the way an index-less getter's bare value would: nothing
# else confirms that the preview stopped.
#
# Preview audibility depends on Live's cue routing — the preview bus is the cue
# output, so a set with cue routed nowhere previews silently. That is a property
# of the user's set, not an error this handler can detect, so a preview of a
# preset with no audible result still replies "ok".
#--------------------------------------------------------------------------------

CATEGORIES = (
    "instruments",
    "sounds",
    "drums",
    "audio_effects",
    "midi_effects",
    "plugins",
    "samples",
    "user_library",
)

#--------------------------------------------------------------------------------
# `samples` is excluded from the bulk export: it is by far the largest category
# and raw samples are rarely what a tag-aware search is for. They remain
# reachable through /live/browser/get/items.
#--------------------------------------------------------------------------------
EXPORT_CATEGORIES = tuple(c for c in CATEGORIES if c != "samples")

#--------------------------------------------------------------------------------
# The browser walk runs on Live's UI thread, which blocks the UI while it runs.
# These caps bound the worst case on very large samples/packs trees.
#--------------------------------------------------------------------------------
MAX_SCAN_NODES = 20000
MAX_DEPTH = 6

DEFAULT_MAX_RESULTS = 25
MAX_RESULTS_LIMIT = 100

#--------------------------------------------------------------------------------
# Where exports go. Deliberately `expanduser` + `abspath` and **not** `realpath`:
# Seshat derives the same root in Elixir with Path.expand/1, which does not
# resolve symlinks, so a symlinked ~/.seshat would put this path under the link
# target and fail the consumer's root check on every reindex. realpath would buy
# no safety here either — a symlinked export directory is written through by
# both spellings. What guards the final component is mkstemp's exclusive create
# on this side and File.lstat/1 on Elixir's.
#--------------------------------------------------------------------------------
EXPORT_ROOT = os.path.abspath(os.path.expanduser("~/.seshat/browser-exports"))
EXPORT_PREFIX = "seshat-browser-export-"
EXPORT_SUFFIX = ".json"

#--------------------------------------------------------------------------------
# Only Python knows an export's name now, so only Python can sweep up one whose
# reply never reached the caller (a query timeout, a lost datagram, a path the
# consumer refused) — nothing else would ever delete a multi-megabyte orphan.
# The age gate is load-bearing: Transport serializes queries, but the caller
# reads the file only after its export query resolves. A second export and its
# sweep can therefore run while the first caller is still reading. Ten minutes
# is well past the 120-second query timeout plus any plausible read, while still
# bounding how long an orphan survives.
#--------------------------------------------------------------------------------
EXPORT_STALE_SECONDS = 10 * 60


class BrowserHandler(AbletonOSCHandler):
    def __init__(self, manager):
        super().__init__(manager)
        self.class_identifier = "browser"

    def init_api(self):
        #--------------------------------------------------------------------------------
        # init_api() is called from AbletonOSCHandler.__init__, so it must not
        # depend on anything assigned in our own __init__ body. The cache is
        # created here and survives clear_api()/init_api() reload cycles only
        # insofar as the handler object does — a fresh handler re-indexes.
        #--------------------------------------------------------------------------------
        if not hasattr(self, "_index_cache"):
            # category name -> list of (name, path, uri, BrowserItem)
            self._index_cache = {}

        self.osc_server.add_handler("/live/browser/get/items", self._get_items)
        self.osc_server.add_handler("/live/browser/load_item", self._load_item)
        self.osc_server.add_handler("/live/browser/load_item_on_return",
                                    self._load_item_on_return)
        self.osc_server.add_handler("/live/browser/load_item_on_master",
                                    self._load_item_on_master)
        self.osc_server.add_handler("/live/browser/export", self._export)
        self.osc_server.add_handler("/live/browser/preview_item", self._preview_item)
        self.osc_server.add_handler("/live/browser/stop_preview", self._stop_preview)

        #--------------------------------------------------------------------------------
        # Sweep once at startup as well as before each export, so orphans left by
        # a crashed or killed consumer don't wait for the next reindex. Never let
        # it break registration: the addresses above matter more than the sweep.
        #--------------------------------------------------------------------------------
        try:
            self._clean_stale_exports()
        except Exception as e:
            self.logger.warning("Browser: stale export sweep failed: %s" % e)

    #--------------------------------------------------------------------------------
    # Endpoints
    #--------------------------------------------------------------------------------
    def _get_items(self, params: Tuple[Any] = ()) -> Tuple:
        category = str(params[0]) if len(params) > 0 else ""
        name_filter = str(params[1]) if len(params) > 1 else ""
        max_results = _clamp_max_results(params[2] if len(params) > 2 else None)

        if category not in CATEGORIES:
            return (category, name_filter, "error",
                    "Unknown category '%s'. Valid categories: %s"
                    % (category, ", ".join(CATEGORIES)))

        try:
            index = self._index(category)
        except Exception as e:
            self.logger.error("Browser: failed to index category %s: %s" % (category, e))
            return (category, name_filter, "error",
                    "Could not index category '%s': %s" % (category, e))

        #--------------------------------------------------------------------------------
        # Match against "folder/path/Name" rather than the name alone, so a
        # filter like "bass" also finds everything filed under a Bass folder.
        #--------------------------------------------------------------------------------
        needle = name_filter.lower()
        matches = [(name, path, uri)
                   for (name, path, uri, _item) in index
                   if needle in ("%s/%s" % (path, name) if path else name).lower()]
        returned = matches[:max_results]

        flat = []
        for name, path, uri in returned:
            flat.append(name)
            flat.append(path)
            flat.append(uri)

        return (category, name_filter, "ok", len(returned), len(matches), *flat)

    def _load_item(self, params: Tuple[Any] = ()) -> Tuple:
        try:
            track_index = int(params[0])
        except (IndexError, TypeError, ValueError):
            return (-1, "", "error", "load_item requires [track_index, uri]")

        uri = str(params[1]) if len(params) > 1 else ""
        if not uri:
            return (track_index, uri, "error", "Missing browser item uri")

        tracks = list(self.song.tracks)
        if track_index < 0 or track_index >= len(tracks):
            return (track_index, uri, "error",
                    "Track index %d out of range — the set has %d track(s)"
                    % (track_index, len(tracks)))
        track = tracks[track_index]

        name, index, error = self._load_onto(track, uri, verify_target=False)
        if error is not None:
            return (track_index, uri, "error", error)

        return (track_index, uri, "ok", name, index)

    def _load_item_on_return(self, params: Tuple[Any] = ()) -> Tuple:
        try:
            return_index = int(params[0])
        except (IndexError, TypeError, ValueError):
            return (-1, "", "error", "load_item_on_return requires [return_index, uri]")

        uri = str(params[1]) if len(params) > 1 else ""
        if not uri:
            return (return_index, uri, "error", "Missing browser item uri")

        return_tracks = list(self.song.return_tracks)
        if return_index < 0 or return_index >= len(return_tracks):
            return (return_index, uri, "error",
                    "Return track index %d out of range — the set has %d return track(s)"
                    % (return_index, len(return_tracks)))
        track = return_tracks[return_index]

        name, index, error = self._load_onto(
            track, uri, verify_target=True, label="return track %d" % return_index)
        if error is not None:
            return (return_index, uri, "error", error)

        #--------------------------------------------------------------------------------
        # The return's name is read *after* the load on purpose — see the header.
        #--------------------------------------------------------------------------------
        return (return_index, uri, "ok", _track_name(track), name, index)

    def _load_item_on_master(self, params: Tuple[Any] = ()) -> Tuple:
        uri = str(params[0]) if len(params) > 0 else ""
        if not uri:
            return ("", "error", "load_item_on_master requires [uri]")

        name, index, error = self._load_onto(
            self.song.master_track, uri, verify_target=True, label="the master track")
        if error is not None:
            return (uri, "error", error)

        return (uri, "ok", name, index)

    def _load_onto(self, track, uri, verify_target: bool, label: str = ""):
        """
        Resolve `uri` and load it onto `track`, reading back what landed.

        Returns (device_name, device_index, None) on success and
        (None, -1, message) on failure. Shared by all three load endpoints —
        they differ only in how the target track is found and how the reply is
        spelled.

        `verify_target` turns on the return/master guard described in the header:
        Live answers a non-effect load on those chains by creating a stray MIDI
        track rather than refusing, so success has to be *checked*, not assumed.
        A regular track needs no such check — every browser item is loadable
        there, and the existing address's behaviour is deliberately unchanged.
        """
        try:
            item = self._find_item(uri)
        except Exception as e:
            self.logger.error("Browser: failed to search for uri %s: %s" % (uri, e))
            return (None, -1, "Could not search the browser: %s" % e)

        if item is None:
            return (None, -1,
                    "No browser item found with uri '%s' — "
                    "query /live/browser/get/items to get a valid uri" % uri)

        try:
            before = list(track.devices)
        except Exception:
            before = []

        tracks_before = list(self.song.tracks) if verify_target else []

        try:
            #--------------------------------------------------------------------------------
            # browser.load_item() always loads onto the selected track, so the
            # selection and the load happen together here rather than being
            # split across two OSC messages (which would race).
            #--------------------------------------------------------------------------------
            self.song.view.selected_track = track
            Live.Application.get_application().browser.load_item(item)
        except Exception as e:
            self.logger.error("Browser: failed to load %s: %s" % (uri, e))
            return (None, -1, "Could not load '%s': %s" % (item.name, e))

        if verify_target:
            error = self._verify_landed(track, item, before, tracks_before, label)
            if error is not None:
                return (None, -1, error)

        name, index = self._loaded_device(track, item, before)
        return (name, index, None)

    def _verify_landed(self, track, item, before, tracks_before, label):
        """
        Confirm a return/master load actually landed there. Message, or None.
        """
        stray = [t for t in self.song.tracks if t not in tracks_before]
        if stray:
            return ("Live would not load '%s' onto %s — it created a new track \"%s\" and put "
                    "it there instead, leaving %s unchanged. Only audio effects can go on a "
                    "return or the master. The new track was left in place rather than "
                    "deleted."
                    % (item.name, label, _track_name(stray[0]), label))

        try:
            landed = [device for device in track.devices if device not in before]
        except Exception as e:
            return ("Loaded '%s', but %s's device chain could not be read back to confirm it "
                    "landed: %s" % (item.name, label, e))

        if not landed:
            return ("Nothing was added to %s — its device chain is unchanged after loading "
                    "'%s'. Only audio effects can go on a return or the master; a plugin that "
                    "instantiates asynchronously can also look like this, so check Live before "
                    "retrying." % (label, item.name))

        return None

    def _preview_item(self, params: Tuple[Any] = ()) -> Tuple:
        uri = str(params[0]) if len(params) > 0 else ""
        if not uri:
            return ("", "error", "preview_item requires [uri]")

        try:
            item = self._find_item(uri)
        except Exception as e:
            self.logger.error("Browser: failed to search for uri %s: %s" % (uri, e))
            return (uri, "error", "Could not search the browser: %s" % e)

        if item is None:
            return (uri, "error",
                    "No browser item found with uri '%s' — "
                    "query /live/browser/get/items to get a valid uri" % uri)

        try:
            #--------------------------------------------------------------------------------
            # Unlike load_item, this touches neither the selected track nor the set:
            # the preview plays on Live's cue bus and leaves the session alone.
            #--------------------------------------------------------------------------------
            Live.Application.get_application().browser.preview_item(item)
        except Exception as e:
            self.logger.error("Browser: failed to preview %s: %s" % (uri, e))
            return (uri, "error", "Could not preview '%s': %s" % (item.name, e))

        return (uri, "ok", item.name)

    def _stop_preview(self, params: Tuple[Any] = ()) -> Tuple:
        try:
            Live.Application.get_application().browser.stop_preview()
        except Exception as e:
            self.logger.error("Browser: failed to stop preview: %s" % e)
            return ("error", "Could not stop the preview: %s" % e)

        return ("ok",)

    def _export(self, params: Tuple[Any] = ()) -> Tuple:
        if len(params) > 0:
            #--------------------------------------------------------------------------------
            # The obsolete [dest_path] form. Its reply goes to the fixed response
            # port rather than back to the sender's socket, so for anything but
            # Seshat's own transport this log line is the only observable outcome.
            #--------------------------------------------------------------------------------
            self.logger.error("Browser: export takes no arguments (got %d) — "
                              "this handler chooses the destination. Nothing was "
                              "written. Re-run mix abletonosc.install and restart Live."
                              % len(params))
            return ("", "error",
                    "export takes no arguments: it writes into %s and returns the path. "
                    "Re-run mix abletonosc.install and restart Live." % EXPORT_ROOT)

        #--------------------------------------------------------------------------------
        # This walks every category in one go on Live's UI thread, so the UI can
        # hitch for several seconds. It is a deliberate trade: one OSC round-trip
        # and a file on disk, instead of hundreds of datagrams bounded by UDP's
        # size limit and get/items' 100-item cap.
        #--------------------------------------------------------------------------------
        self.logger.info("Browser: exporting %d categories to %s — "
                         "Live's UI may be unresponsive while this runs"
                         % (len(EXPORT_CATEGORIES), EXPORT_ROOT))

        #--------------------------------------------------------------------------------
        # An export always re-walks: its whole purpose is to pick up Packs and
        # presets added since the last walk, which update Live's browser without
        # a restart. _load_item tolerates the cleared cache — _find_item lazily
        # re-indexes whatever it needs.
        #--------------------------------------------------------------------------------
        self._index_cache = {}

        export = {}
        total = 0
        for category in EXPORT_CATEGORIES:
            try:
                index = self._index(category)
            except Exception as e:
                self.logger.error("Browser: failed to index category %s: %s" % (category, e))
                continue

            export[category] = [{"name": name, "path": path, "uri": uri}
                                for (name, path, uri, _item) in index]
            total += len(export[category])

        #--------------------------------------------------------------------------------
        # Nothing is created on disk until there is something worth writing.
        #--------------------------------------------------------------------------------
        if not export:
            return ("", "error", "Could not index any browser category")

        try:
            self._clean_stale_exports()
        except Exception as e:
            self.logger.warning("Browser: stale export sweep failed: %s" % e)

        try:
            fd, export_path = _new_export_file()
        except Exception as e:
            self.logger.error("Browser: could not create an export file in %s: %s"
                              % (EXPORT_ROOT, e))
            return ("", "error", "Could not create an export file in '%s': %s"
                    % (EXPORT_ROOT, e))

        try:
            handle = os.fdopen(fd, "w")
        except Exception as e:
            #--------------------------------------------------------------------------------
            # fdopen didn't take ownership of the descriptor, so close it here.
            # Below, the `with` owns it and closes it on every path.
            #--------------------------------------------------------------------------------
            self.logger.error("Browser: could not open %s for writing: %s" % (export_path, e))
            _close_quietly(fd)
            self._remove_quietly(export_path)
            return ("", "error", "Could not open the browser export for writing: %s" % e)

        try:
            with handle as f:
                json.dump(export, f)
        except Exception as e:
            self.logger.error("Browser: failed to write export to %s: %s" % (export_path, e))
            self._remove_quietly(export_path)
            return ("", "error", "Could not write the browser export: %s" % e)

        self.logger.info("Browser: exported %d item(s) to %s" % (total, export_path))
        return (export_path, "ok", total)

    #--------------------------------------------------------------------------------
    # Export housekeeping
    #--------------------------------------------------------------------------------
    def _clean_stale_exports(self) -> None:
        """
        Remove export files old enough that no caller can still be reading them.

        Deliberately narrow: direct children of EXPORT_ROOT only, matching the
        export name shape, regular files by os.lstat (so a symlink is skipped
        rather than followed), and at least EXPORT_STALE_SECONDS old. Everything
        else in that directory — fresh exports, symlinks, subdirectories, files
        nobody here named — is left alone. Failures are logged and skipped: a
        sweep must never be the reason an export fails.
        """
        try:
            names = os.listdir(EXPORT_ROOT)
        except OSError:
            #--------------------------------------------------------------------------------
            # No export directory yet is the normal state before the first export.
            #--------------------------------------------------------------------------------
            return

        cutoff = time.time() - EXPORT_STALE_SECONDS

        for name in names:
            if not (name.startswith(EXPORT_PREFIX) and name.endswith(EXPORT_SUFFIX)):
                continue

            path = os.path.join(EXPORT_ROOT, name)

            try:
                info = os.lstat(path)
            except OSError as e:
                self.logger.warning("Browser: could not inspect %s: %s" % (path, e))
                continue

            if not stat.S_ISREG(info.st_mode):
                continue

            if info.st_mtime > cutoff:
                continue

            try:
                os.remove(path)
                self.logger.info("Browser: removed stale export %s" % path)
            except OSError as e:
                self.logger.warning("Browser: could not remove stale export %s: %s" % (path, e))

    def _remove_quietly(self, path: str) -> None:
        try:
            os.remove(path)
        except OSError as e:
            self.logger.warning("Browser: could not remove partial export %s: %s" % (path, e))

    #--------------------------------------------------------------------------------
    # Indexing
    #--------------------------------------------------------------------------------
    def _index(self, category: str):
        """
        Return a cached list of (name, path, uri, BrowserItem) for every loadable
        item under `category`. `path` is the "/"-joined chain of folder names
        between the category root and the item ("" for a top-level item); it is
        what makes an exported catalog searchable by where a preset lives. The
        BrowserItem is kept so that a later load needs no second walk.
        """
        if category in self._index_cache:
            return self._index_cache[category]

        browser = Live.Application.get_application().browser
        root = getattr(browser, category)

        items = []
        seen_uris = set()
        scanned = 0
        stack = [(child, 1, ()) for child in reversed(_children_of(root))]

        while stack:
            item, depth, parents = stack.pop()

            scanned += 1
            if scanned > MAX_SCAN_NODES:
                self.logger.warning(
                    "Browser: hit scan cap of %d nodes indexing '%s' — "
                    "index may be incomplete" % (MAX_SCAN_NODES, category))
                break

            try:
                if item.is_loadable:
                    uri = item.uri
                    if uri and uri not in seen_uris:
                        seen_uris.add(uri)
                        items.append((item.name, "/".join(parents), uri, item))

                if depth < MAX_DEPTH:
                    child_parents = parents + (item.name,)
                    for child in reversed(_children_of(item)):
                        stack.append((child, depth + 1, child_parents))
            except RuntimeError:
                #--------------------------------------------------------------------------------
                # Live raises RuntimeError when a browser node goes stale
                # mid-walk (e.g. a disconnected drive). Skip it.
                #--------------------------------------------------------------------------------
                continue

        self.logger.info("Browser: indexed %d loadable item(s) in '%s' (%d nodes scanned)"
                         % (len(items), category, scanned))
        self._index_cache[category] = items
        return items

    def _find_item(self, uri: str) -> Optional[Any]:
        #--------------------------------------------------------------------------------
        # Already-indexed categories first: the common path is a load straight
        # after a get/items call on the same category.
        #--------------------------------------------------------------------------------
        for category in list(self._index_cache.keys()):
            for (_name, _path, item_uri, item) in self._index_cache[category]:
                if item_uri == uri:
                    return item

        for category in CATEGORIES:
            if category in self._index_cache:
                continue
            for (_name, _path, item_uri, item) in self._index(category):
                if item_uri == uri:
                    return item

        return None

    def _loaded_device(self, track, item, before=()) -> Tuple[str, int]:
        """
        Read back the track's device list so the reply positively confirms what
        landed, rather than echoing what we asked for.

        `before` is the chain's device list as it stood immediately prior to
        the load, used to disambiguate a track that already carried a
        same-named device — otherwise a name match finds the pre-existing
        device instead of the one just loaded.

        Returns (name, index), where index is the device's position in
        `track.devices` — what the caller needs to select it — or -1 when the
        device isn't on the chain to be indexed.
        """
        try:
            devices = list(track.devices)
        except Exception:
            return (item.name, -1)

        if not devices:
            #--------------------------------------------------------------------------------
            # Some VST/AU plugins instantiate asynchronously and aren't on the
            # track yet. Fall back to the browser item's own name, and -1 for the
            # index: there is nothing to point at.
            #--------------------------------------------------------------------------------
            return (item.name, -1)

        #--------------------------------------------------------------------------------
        # Prefer a device object that wasn't on the chain before the load: that
        # is the one that was just loaded, even when the chain already held a
        # same-named device. Fall back to a name match (covers `before` being
        # unavailable) and finally to the tail, since load_item() does not
        # always append at the end — an instrument lands before any existing
        # audio effects.
        #--------------------------------------------------------------------------------
        for index, device in enumerate(devices):
            if device not in before:
                return (device.name, index)

        for index, device in enumerate(devices):
            if device.name == item.name:
                return (device.name, index)

        return (devices[-1].name, len(devices) - 1)


def _new_export_file() -> Tuple[int, str]:
    """
    Create a fresh, uniquely named export file inside EXPORT_ROOT.

    Returns (open write descriptor, absolute path). mkstemp does the exclusive
    create — no caller-supplied name, no pre-existing file reused, no widening
    of the 0600 mode it opens with — and the directory is created owner-only.
    """
    os.makedirs(EXPORT_ROOT, 0o700, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix=EXPORT_PREFIX, suffix=EXPORT_SUFFIX, dir=EXPORT_ROOT)
    return (fd, os.path.abspath(path))


def _track_name(track) -> str:
    """
    A track's name, or "" if Live won't give it up — a name is only ever used to
    make a reply readable, never to decide anything.
    """
    try:
        return track.name
    except Exception:
        return ""


def _close_quietly(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass


def _children_of(item) -> list:
    try:
        return list(item.children)
    except (AttributeError, RuntimeError):
        return []


def _clamp_max_results(value) -> int:
    try:
        max_results = int(value)
    except (TypeError, ValueError):
        return DEFAULT_MAX_RESULTS

    return max(1, min(MAX_RESULTS_LIMIT, max_results))
