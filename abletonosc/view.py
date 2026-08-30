from functools import partial
from typing import Optional, Tuple, Any

import Live

from .handler import AbletonOSCHandler
from .track_identity import (selected_track_identity, selected_track_index,
                             selected_device_indices, chain_identity,
                             device_identity, parameter_identity,
                             clip_slot_indices, resolve_track, CATEGORY_TRACK)

#--------------------------------------------------------------------------------
# Seventeen addresses in this file are Seshat extensions, added in this fork:
#
#   /live/view/show_view          [view_name]                 (no reply)
#   /live/view/hide_view          [view_name]                 (no reply)
#   /live/view/focus_view         [view_name]                 (no reply)
#   /live/view/set/detail_clip    [track_index, scene_index]  (no reply)
#   /live/view/get/is_view_visible [view_name]                -> [view_name, "ok", 1|0]
#                                                             or [view_name, "error", message]
#   /live/view/get/selected_track_identity          ()        -> [category, index]
#   /live/view/start_listen/selected_track_identity ()        (pushes on the get address)
#   /live/view/stop_listen/selected_track_identity  ()        (no reply)
#   /live/view/get/selected_chain      ()  -> [category, track, device, chain]
#   /live/view/get/selected_parameter  ()  -> [category, track, device, parameter]
#   /live/view/get/mod_mapping_device  ()  -> [category, track, device]
#   /live/view/get/mod_mapping_parameter () -> [category, track, device, parameter]
#   /live/view/get/focused_document_view          () -> ["ok", name]
#                                                    or ["error", message]
#   /live/view/start_listen/focused_document_view ()  (pushes on the get address)
#   /live/view/stop_listen/focused_document_view  ()  (no reply)
#   /live/view/get/highlighted_clip_slot ()                       -> [track, scene]
#   /live/view/set/highlighted_clip_slot [track_index, scene_index] (no reply)
#
# Upstream can select a track, scene, clip or device, but it cannot bring the
# pane those live in into view, put one away, or say which panes are open at
# all: `Application.View.show_view`, `.hide_view`, `.is_view_visible` and
# `song.view.detail_clip` have no OSC address whatsoever. Seshat's view steering
# needs the first — selecting a clip that nobody can see is not confirmation
# that anything happened — and its view *tools* need the rest, so the model can
# answer "what am I looking at?" and act on the answer.
#
# The four setters are silent, like upstream's setters. Nothing waits on a
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
# The next three are the selected-track identity trio, and three *upstream*
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
#
# The last four are A-4's object-valued reads of Song.View: `selected_chain`,
# `selected_parameter`, `mod_mapping_device` and `mod_mapping_parameter` are
# all LOM *objects*, which the generic property loop can only turn into an
# error or a None, so each is answered as indices into the address families
# that already reach those objects — the device triple and the parameter/chain
# quad defined in track_identity.py, with "none" and -1 for a member that is
# None. See API.md § "Object-valued reads". Get-only in this item: all four are
# observable and two are LOM-writable, but no consumer has named a setter or a
# listener yet (C-2 / D-1).
#
# `get/focused_document_view` closes the High-priority `Application.View`
# member in FORK_GAPS: it is the exact Session-vs-Arranger read the rest of
# `/live/view` cannot give. It follows the fork's getter rule, not the silent
# setter rule — it always replies, in the ok/error envelope, because a caller
# waits on it. `focus_view` is fire-and-forget, so without this read a client
# that steers focus has no way to learn whether the steer landed, and a Live
# menu command that quietly refuses several steps later gets misattributed to
# the clip rather than to focus.
#
# ⚠️ It is a *partial* verification, and API.md says so on the row. Live
# answers only "Session" or "Arranger" — the two document views — so it cannot
# report that the Browser or a Detail pane holds focus, and answers "Session"
# regardless. Measured 2026-08-30: focus_view("Browser") disabled the Convert
# commands while focused_document_view was unchanged. A caller can therefore
# use it to prove focus is on the *wrong document view*, but never to prove
# focus is where it needs to be.
#
# Its listen pair is the one pair in this file whose subject is
# `Application.View` rather than `Song.View`. `_start_listen` takes the target
# as a parameter and is subject-agnostic, so nothing bends to accommodate it —
# but the target must be resolved *lazily*, inside the handler, rather than
# bound into a `partial()` at registration time the way every `self.song.view`
# pair above is. `Live.Application` is an empty stub under the Live-free suite
# (see tests_unit/conftest.py), and this file's contract with that suite is
# that its Live dereferences all happen at call time. Hence the two small
# wrappers instead of two partials.
#
# `highlighted_clip_slot` is an object-valued read in the A-4 sense — the LOM
# member is a `ClipSlot` — answered as the ordinary (track, scene) coordinate
# via `clip_slot_indices`, with (-1, -1) for "none". Live documents the member
# as None for the Main and Send tracks, which is that none-pair and not an
# error. It is a *second, independent* confirmation that a selection landed:
# `get/selected_clip` reports the ring, and if the ring and the highlighted
# slot can ever disagree, a menu press acts on something other than what the
# caller believes is selected.
#
# The setter is expected to be redundant — Live's docstring says the slot is
# "defined via the selected track and scene", which is what
# `set/selected_clip` already writes — and is carried as insurance and for
# symmetry, not as a fix. It is *not* one of the silent setters: a rejection
# comes back as a structured "request" error, because a selection write is not
# a steer. It *validates* its two indices rather than subscripting with them,
# which is the A-4 setter rule (`set/appointed_device`, `set/groove`) and not
# upstream's `set/selected_*` idiom: `-1, -1` is what this address's own getter
# answers for "nothing highlighted", and Python's negative indexing would turn
# a client's own snapshot, sent back, into the last scene of the last track
# with nothing on the wire to say so. `-1` is an answer, never an argument.
#
# No listen pair: the member is not observable (the inventory's obs column is
# empty for it), which makes it the *second* object-valued read that could not
# have one even if a consumer asked — `Track.group_track` is no longer alone.
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

        def get_selected_chain(params: Optional[Tuple] = ()):
            identity = chain_identity(self.song, self.song.view.selected_chain)
            self.logger.info("Getting property for %s: selected_chain = %s"
                             % (self.class_identifier, str(identity)))
            return identity

        def get_selected_parameter(params: Optional[Tuple] = ()):
            identity = parameter_identity(self.song, self.song.view.selected_parameter)
            self.logger.info("Getting property for %s: selected_parameter = %s"
                             % (self.class_identifier, str(identity)))
            return identity

        def get_mod_mapping_device(params: Optional[Tuple] = ()):
            identity = device_identity(self.song, self.song.view.mod_mapping_device)
            self.logger.info("Getting property for %s: mod_mapping_device = %s"
                             % (self.class_identifier, str(identity)))
            return identity

        def get_mod_mapping_parameter(params: Optional[Tuple] = ()):
            identity = parameter_identity(self.song, self.song.view.mod_mapping_parameter)
            self.logger.info("Getting property for %s: mod_mapping_parameter = %s"
                             % (self.class_identifier, str(identity)))
            return identity

        def get_highlighted_clip_slot(params: Optional[Tuple] = ()):
            indices = clip_slot_indices(self.song, self.song.view.highlighted_clip_slot)
            self.logger.info("Getting property for %s: highlighted_clip_slot = %s"
                             % (self.class_identifier, str(indices)))
            return indices

        def set_selected_scene(params: Optional[Tuple] = ()):
            self.song.view.selected_scene = self.song.scenes[params[0]]

        def set_selected_track(params: Optional[Tuple] = ()):
            self.song.view.selected_track = self.song.tracks[params[0]]

        def set_selected_clip(params: Optional[Tuple] = ()):
            set_selected_track((params[0],))
            set_selected_scene((params[1],))

        def set_highlighted_clip_slot(params: Optional[Tuple] = ()):
            #--------------------------------------------------------------------------------
            # Validated, not indexed — the A-4 setter rule (set/appointed_device,
            # set/groove), deliberately *not* upstream's set/selected_* idiom
            # directly above. Python's silent negative indexing would make
            # (-1, -1) mean "the last scene of the last track", and -1 is
            # exactly what this address's own getter answers for "nothing
            # highlighted": a client round-tripping its own snapshot would
            # steer the highlight somewhere real and wrong, with nothing on
            # the wire to say so. `-1` is an answer, never an argument.
            #
            # Not one of this file's silent setters either: a rejection is a
            # ValueError arriving as a structured "request" error, because a
            # selection write is not a steer.
            #--------------------------------------------------------------------------------
            track = resolve_track(self.song, CATEGORY_TRACK, params[0])
            scene_index = params[1]
            if not 0 <= scene_index < len(track.clip_slots):
                raise ValueError("Clip slot index out of range for track %s: %s "
                                 "(this track has %d)"
                                 % (params[0], scene_index, len(track.clip_slots)))
            self.song.view.highlighted_clip_slot = track.clip_slots[scene_index]

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

        def focus_view(params: Optional[Tuple] = ()):
            #--------------------------------------------------------------------------------
            # Seshat extension. Distinct from show_view: show_view makes a pane
            # visible, focus_view gives it keyboard focus. Live's menu-command
            # validation reads focus, not visibility — measured 2026-08-30, when
            # Create > Convert Melody to New MIDI Track stayed disabled after
            # show_view("Session") plus an OSC clip selection, and enabled only
            # once the Session grid was clicked. FORK_GAPS previously dismissed
            # this member as "overlaps show_view"; it does not.
            #--------------------------------------------------------------------------------
            view_name = str(params[0]) if len(params) > 0 else ""
            try:
                Live.Application.get_application().view.focus_view(view_name)
            except Exception as e:
                self.logger.error("View: could not focus view '%s' (%s). Valid names: %s"
                                  % (view_name, e, ", ".join(VIEW_NAMES)))

        def get_focused_document_view(params: Optional[Tuple] = ()):
            #--------------------------------------------------------------------------------
            # Getter rule, not the silent-setter rule: a caller waits on this,
            # so it always replies. Live answers "Session" or "Arranger" only —
            # see the ⚠️ in the header and on the API.md row for what that
            # cannot tell you.
            #--------------------------------------------------------------------------------
            try:
                view_name = Live.Application.get_application().view.focused_document_view
                return ("ok", str(view_name))
            except Exception as e:
                return ("error", "could not read focused_document_view: %s" % e)

        def start_listen_focused_document_view(params: Optional[Tuple] = ()):
            #--------------------------------------------------------------------------------
            # The subject is Application.View, not Song.View, so the target is
            # resolved here at call time rather than bound into a partial() at
            # registration time — see the header. _start_listen itself is
            # unchanged and unaware of the difference.
            #--------------------------------------------------------------------------------
            self._start_listen(Live.Application.get_application().view,
                               "focused_document_view",
                               getter=get_focused_document_view)

        def stop_listen_focused_document_view(params: Optional[Tuple] = ()):
            #--------------------------------------------------------------------------------
            # The target passed here is not load-bearing: _stop_listen unbinds
            # from the object stored at subscribe time, falling back to this
            # one only when the key is unknown (in which case there is nothing
            # to unbind). It is resolved lazily all the same, for the same
            # empty-stub reason as start_listen above.
            #--------------------------------------------------------------------------------
            self._stop_listen(Live.Application.get_application().view,
                              "focused_document_view")

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
        self.osc_server.add_handler("/live/view/get/selected_chain", get_selected_chain)
        self.osc_server.add_handler("/live/view/get/selected_parameter", get_selected_parameter)
        self.osc_server.add_handler("/live/view/get/mod_mapping_device", get_mod_mapping_device)
        self.osc_server.add_handler("/live/view/get/mod_mapping_parameter", get_mod_mapping_parameter)
        self.osc_server.add_handler("/live/view/get/highlighted_clip_slot", get_highlighted_clip_slot)
        self.osc_server.add_handler("/live/view/set/selected_scene", set_selected_scene)
        self.osc_server.add_handler("/live/view/set/selected_track", set_selected_track)
        self.osc_server.add_handler("/live/view/set/selected_clip", set_selected_clip)
        self.osc_server.add_handler("/live/view/set/selected_device", set_selected_device)
        self.osc_server.add_handler("/live/view/set/highlighted_clip_slot", set_highlighted_clip_slot)
        self.osc_server.add_handler("/live/view/show_view", show_view)
        self.osc_server.add_handler("/live/view/focus_view", focus_view)
        self.osc_server.add_handler("/live/view/get/is_view_visible", get_is_view_visible)
        self.osc_server.add_handler("/live/view/hide_view", hide_view)
        self.osc_server.add_handler("/live/view/set/detail_clip", set_detail_clip)
        self.osc_server.add_handler("/live/view/get/focused_document_view", get_focused_document_view)
        self.osc_server.add_handler("/live/view/start_listen/focused_document_view", start_listen_focused_document_view)
        self.osc_server.add_handler("/live/view/stop_listen/focused_document_view", stop_listen_focused_document_view)

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
