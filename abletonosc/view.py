from functools import partial
from typing import Optional, Tuple, Any

import Live

from .handler import AbletonOSCHandler
from .track_identity import (selected_track_identity, selected_track_index,
                             selected_device_indices)

#--------------------------------------------------------------------------------
# Seven addresses in this file are Seshat extensions, added in this fork:
#
#   /live/view/show_view          [view_name]                 (no reply)
#   /live/view/hide_view          [view_name]                 (no reply)
#   /live/view/set/detail_clip    [track_index, scene_index]  (no reply)
#   /live/view/get/is_view_visible [view_name]                -> [view_name, "ok", 1|0]
#                                                             or [view_name, "error", message]
#   /live/view/get/selected_track_identity          ()        -> [category, index]
#   /live/view/start_listen/selected_track_identity ()        (pushes on the get address)
#   /live/view/stop_listen/selected_track_identity  ()        (no reply)
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
#
# The last three are the selected-track identity trio, and three *upstream*
# getters in this file change with them. This fork can select a return track or
# the master (/live/return_track/select, /live/master/select), which the LOM
# accepts on song.view.selected_track — but upstream's getters resolve the
# selection through song.tracks alone, so after either of those selects
# get/selected_track, get/selected_clip and get/selected_device all raised
# ValueError instead of replying, and start_listen/selected_track's push died
# *inside Live's listener callback*, outside OSCServer._dispatch's per-message
# catch, so no push went out at all.
#
# So: /live/view/get/selected_track_identity answers (category, index), where
# category is the address-family prefix that reaches that track — "track",
# "return_track" or "master" — and the resolution itself lives in the Live-free
# track_identity.py. The three legacy getters keep their shapes and report -1
# outside their index space:
#
#   get/selected_track   -> -1            a return or the master is selected
#   get/selected_clip    -> (-1, scene)   likewise
#   get/selected_device  -> (i, -1)       regular track, but no top-level device
#                                         to report: none selected, or the
#                                         selected one is nested in a rack chain
#                        -> (-1, -1)      a return or the master is selected
#
# start_listen/selected_track_identity observes the same one observable LOM
# property as start_listen/selected_track (Song.View.selected_track) and pushes
# under its own name, via the base class's `lom_property` alias. The two coexist:
# distinct bookkeeping keys, one LOM property, two callbacks.
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
    class_identifier = "view"

    def init_api(self):
        def get_selected_scene(params: Optional[Tuple] = ()):
            return (list(self.song.scenes).index(self.song.view.selected_scene),)

        def get_selected_track_identity(params: Optional[Tuple] = ()):
            identity = selected_track_identity(self.song)
            self.logger.info("Getting property for %s: selected_track_identity = %s"
                             % (self.class_identifier, str(identity)))
            return identity

        def get_selected_track(params: Optional[Tuple] = ()):
            index = selected_track_index(self.song)
            self.logger.info("Getting property for %s: selected_track = %s"
                             % (self.class_identifier, index))
            return (index,)

        def get_selected_clip(params: Optional[Tuple] = ()):
            #--------------------------------------------------------------------------------
            # Composed, as upstream: the track half now carries the -1 sentinel
            # for a return/master selection rather than aborting the reply.
            #--------------------------------------------------------------------------------
            clip = (get_selected_track()[0], get_selected_scene()[0])
            self.logger.info("Getting property for %s: selected_clip = %s"
                             % (self.class_identifier, str(clip)))
            return clip

        def get_selected_device(params: Optional[Tuple] = ()):
            indices = selected_device_indices(self.song)
            self.logger.info("Getting property for %s: selected_device = %s"
                             % (self.class_identifier, str(indices)))
            return indices

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
        self.osc_server.add_handler("/live/view/get/selected_track_identity", get_selected_track_identity)
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
        #--------------------------------------------------------------------------------
        # The identity listener observes Song.View.selected_track — the same
        # single observable property as the line above — but keys, and pushes
        # under, its own name. `lom_property` is what splits the
        # add_/remove_%s_listener accessor off from the bookkeeping key and the
        # push address; see AbletonOSCHandler._start_listen.
        #--------------------------------------------------------------------------------
        self.osc_server.add_handler('/live/view/start_listen/selected_track_identity', partial(self._start_listen, self.song.view, "selected_track_identity", getter=get_selected_track_identity, lom_property="selected_track"))
        self.osc_server.add_handler('/live/view/stop_listen/selected_track_identity', partial(self._stop_listen, self.song.view, "selected_track_identity"))
