from functools import partial
from typing import Optional, Tuple, Any

import Live

from .handler import AbletonOSCHandler

#--------------------------------------------------------------------------------
# Four addresses in this file are Seshat extensions, added in this fork:
#
#   /live/view/show_view          [view_name]                 (no reply)
#   /live/view/hide_view          [view_name]                 (no reply)
#   /live/view/set/detail_clip    [track_index, scene_index]  (no reply)
#   /live/view/get/is_view_visible [view_name]                -> [view_name, "ok", 1|0]
#                                                             or [view_name, "error", message]
#
# Upstream can select a track, scene, clip or device, but it cannot bring the
# pane those live in into view, put one away, or say which panes are open at
# all: `Application.View.show_view`, `.hide_view`, `.is_view_visible` and
# `song.view.detail_clip` have no OSC address whatsoever. Seshat's view steering
# needs the first — selecting a clip that nobody can see is not confirmation
# that anything happened — and its view *tools* need the rest, so the model can
# answer "what am I looking at?" and act on the answer.
#
# The three setters are silent, like upstream's setters. Nothing waits on a
# steering send, and steering must never fail the tool it follows, so the
# ok/error envelope the fork's *getters* use deliberately does not apply there:
# a bad view name or an empty clip slot is logged to Live's Log.txt and nothing
# goes on the wire.
#
# `get/is_view_visible` is the exception, and follows the fork's getter rule
# instead: it *always* replies, in the ok/error envelope, echoing the view name
# it was asked about. A caller waits on this one, so silence must mean exactly
# one thing — this extension isn't installed — rather than doubling as "bad view
# name". Live raises on an unrecognised name here (unlike show_view, which
# ignores it), so the error arm is reachable and costs a fast reply instead of a
# guard timeout. The boolean goes on the wire as 1/0, matching the convention
# every other AbletonOSC boolean uses.
#--------------------------------------------------------------------------------

#--------------------------------------------------------------------------------
# Live's own names for the panes `Application.View.show_view` accepts, which is
# also the full set `is_view_visible` reads. `hide_view` accepts them all too,
# but only `Browser` and `Detail` genuinely hide anything (measured 2026-07-31);
# the rest merely swap to a sibling view, which is why the *tool* enum is
# narrower than this tuple. Kept here as documentation and for the error
# messages — the name is passed through verbatim, so a name Live gains later
# works without a change here.
#--------------------------------------------------------------------------------
VIEW_NAMES = ("Browser", "Arranger", "Session", "Detail", "Detail/Clip", "Detail/DeviceChain")


class ViewHandler(AbletonOSCHandler):
    def __init__(self, manager):
        super().__init__(manager)
        self.class_identifier = "view"

    def init_api(self):
        def get_selected_scene(params: Optional[Tuple] = ()):
            return (list(self.song.scenes).index(self.song.view.selected_scene),)

        def get_selected_track(params: Optional[Tuple] = ()):
            return (list(self.song.tracks).index(self.song.view.selected_track),)

        def get_selected_clip(params: Optional[Tuple] = ()):
            return (get_selected_track()[0], get_selected_scene()[0])
        
        def get_selected_device(params: Optional[Tuple] = ()):
            return (get_selected_track()[0], list(self.song.view.selected_track.devices).index(self.song.view.selected_track.view.selected_device))

        def set_selected_scene(params: Optional[Tuple] = ()):
            self.song.view.selected_scene = self.song.scenes[params[0]]

        def set_selected_track(params: Optional[Tuple] = ()):
            self.song.view.selected_track = self.song.tracks[params[0]]

        def set_selected_clip(params: Optional[Tuple] = ()):
            set_selected_track((params[0],))
            set_selected_scene((params[1],))

        def set_selected_device(params: Optional[Tuple] = ()):
            device = self.song.tracks[params[0]].devices[params[1]]
            self.song.view.select_device(device)
            return params[0], params[1]

        def show_view(params: Optional[Tuple] = ()):
            view_name = str(params[0]) if len(params) > 0 else ""
            try:
                Live.Application.get_application().view.show_view(view_name)
            except Exception as e:
                self.logger.error("View: could not show view '%s' (%s). Valid names: %s"
                                  % (view_name, e, ", ".join(VIEW_NAMES)))

        def get_is_view_visible(params: Optional[Tuple] = ()):
            view_name = str(params[0]) if len(params) > 0 else ""
            try:
                visible = Live.Application.get_application().view.is_view_visible(view_name)
                return (view_name, "ok", 1 if visible else 0)
            except Exception as e:
                return (view_name, "error",
                        "could not read visibility of '%s': %s" % (view_name, e))

        def hide_view(params: Optional[Tuple] = ()):
            view_name = str(params[0]) if len(params) > 0 else ""
            try:
                Live.Application.get_application().view.hide_view(view_name)
            except Exception as e:
                self.logger.error("View: could not hide view '%s' (%s). Valid names: %s"
                                  % (view_name, e, ", ".join(VIEW_NAMES)))

        def set_detail_clip(params: Optional[Tuple] = ()):
            try:
                clip = self.song.tracks[params[0]].clip_slots[params[1]].clip
            except Exception as e:
                self.logger.error("View: could not read clip slot %s: %s" % (str(params), e))
                return

            if clip is None:
                #--------------------------------------------------------------------------------
                # Not an error worth raising: a delete steers at the slot it just
                # emptied, and the empty slot is the evidence.
                #--------------------------------------------------------------------------------
                self.logger.info("View: clip slot %s is empty, leaving detail_clip alone"
                                 % str(params))
                return

            try:
                self.song.view.detail_clip = clip
            except Exception as e:
                self.logger.error("View: could not set detail_clip to %s: %s" % (str(params), e))

        self.osc_server.add_handler("/live/view/get/selected_scene", get_selected_scene)
        self.osc_server.add_handler("/live/view/get/selected_track", get_selected_track)
        self.osc_server.add_handler("/live/view/get/selected_clip", get_selected_clip)
        self.osc_server.add_handler("/live/view/get/selected_device", get_selected_device)
        self.osc_server.add_handler("/live/view/set/selected_scene", set_selected_scene)
        self.osc_server.add_handler("/live/view/set/selected_track", set_selected_track)
        self.osc_server.add_handler("/live/view/set/selected_clip", set_selected_clip)
        self.osc_server.add_handler("/live/view/set/selected_device", set_selected_device)
        self.osc_server.add_handler("/live/view/show_view", show_view)
        self.osc_server.add_handler("/live/view/get/is_view_visible", get_is_view_visible)
        self.osc_server.add_handler("/live/view/hide_view", hide_view)
        self.osc_server.add_handler("/live/view/set/detail_clip", set_detail_clip)

        self.osc_server.add_handler('/live/view/start_listen/selected_scene', partial(self._start_listen, self.song.view, "selected_scene", getter=get_selected_scene))
        self.osc_server.add_handler('/live/view/start_listen/selected_track', partial(self._start_listen, self.song.view, "selected_track", getter=get_selected_track))
        self.osc_server.add_handler('/live/view/stop_listen/selected_scene', partial(self._stop_listen, self.song.view, "selected_scene"))
        self.osc_server.add_handler('/live/view/stop_listen/selected_track', partial(self._stop_listen, self.song.view, "selected_track"))
