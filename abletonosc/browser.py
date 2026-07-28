import json
import os
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
#   /live/browser/export      [dest_path]
#     -> [dest_path, "ok", total_items]
#     -> [dest_path, "error", message]
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
        self.osc_server.add_handler("/live/browser/export", self._export)
        self.osc_server.add_handler("/live/browser/preview_item", self._preview_item)
        self.osc_server.add_handler("/live/browser/stop_preview", self._stop_preview)

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

        try:
            item = self._find_item(uri)
        except Exception as e:
            self.logger.error("Browser: failed to search for uri %s: %s" % (uri, e))
            return (track_index, uri, "error", "Could not search the browser: %s" % e)

        if item is None:
            return (track_index, uri, "error",
                    "No browser item found with uri '%s' — "
                    "query /live/browser/get/items to get a valid uri" % uri)

        try:
            before = list(track.devices)
        except Exception:
            before = []

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
            return (track_index, uri, "error", "Could not load '%s': %s" % (item.name, e))

        name, index = self._loaded_device(track, item, before)
        return (track_index, uri, "ok", name, index)

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
        dest_path = str(params[0]) if len(params) > 0 else ""
        if not dest_path:
            return ("", "error", "export requires [dest_path]")

        #--------------------------------------------------------------------------------
        # This walks every category in one go on Live's UI thread, so the UI can
        # hitch for several seconds. It is a deliberate trade: one OSC round-trip
        # and a file on disk, instead of hundreds of datagrams bounded by UDP's
        # size limit and get/items' 100-item cap.
        #--------------------------------------------------------------------------------
        self.logger.info("Browser: exporting %d categories to %s — "
                         "Live's UI may be unresponsive while this runs"
                         % (len(EXPORT_CATEGORIES), dest_path))

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

        if not export:
            return (dest_path, "error", "Could not index any browser category")

        try:
            directory = os.path.dirname(dest_path)
            if directory and not os.path.isdir(directory):
                os.makedirs(directory)

            with open(dest_path, "w") as f:
                json.dump(export, f)
        except Exception as e:
            self.logger.error("Browser: failed to write export to %s: %s" % (dest_path, e))
            return (dest_path, "error", "Could not write '%s': %s" % (dest_path, e))

        self.logger.info("Browser: exported %d item(s) to %s" % (total, dest_path))
        return (dest_path, "ok", total)

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
