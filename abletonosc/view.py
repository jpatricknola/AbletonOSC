from functools import partial
from typing import Optional, Tuple, Any

import Live

from .handler import AbletonOSCHandler

#--------------------------------------------------------------------------------
# Two addresses in this file are Seshat extensions, added in this fork:
#
#   /live/view/show_view       [view_name]              (no reply)
#   /live/view/set/detail_clip [track_index, scene_index]  (no reply)
#
# Upstream can select a track, scene, clip or device, but it cannot bring the
# pane those live in into view: `Application.View.show_view` and
# `song.view.detail_clip` have no OSC address at all. Seshat's view steering
# needs both — selecting a clip that nobody can see is not confirmation that
# anything happened.
#
# Both are silent, like upstream's setters. Nothing waits on a steering send,
# and steering must never fail the tool it follows, so the ok/error envelope the
# fork's *getters* use deliberately does not apply here: a bad view name or an
# empty clip slot is logged to Live's Log.txt and nothing goes on the wire.
#--------------------------------------------------------------------------------

#--------------------------------------------------------------------------------
# Live's own names for the panes `Application.View.show_view` accepts. Kept here
# as documentation and for the error message — the name is passed through
# verbatim, so a name Live gains later works without a change here.
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
        self.osc_server.add_handler("/live/view/set/detail_clip", set_detail_clip)

        self.osc_server.add_handler('/live/view/start_listen/selected_scene', partial(self._start_listen, self.song.view, "selected_scene", getter=get_selected_scene))
        self.osc_server.add_handler('/live/view/start_listen/selected_track', partial(self._start_listen, self.song.view, "selected_track", getter=get_selected_track))
        self.osc_server.add_handler('/live/view/stop_listen/selected_scene', partial(self._stop_listen, self.song.view, "selected_scene"))
        self.osc_server.add_handler('/live/view/stop_listen/selected_track', partial(self._stop_listen, self.song.view, "selected_track"))
