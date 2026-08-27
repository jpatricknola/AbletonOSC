from .handler import AbletonOSCHandler
from functools import partial
from typing import Tuple, Any

class SceneHandler(AbletonOSCHandler):
    class_identifier = "scene"

    def init_api(self):
        # TODO: Needs unit tests

        def create_scene_callback(func, *args, include_ids: bool = False):
            def scene_callback(params: Tuple[Any]):
                scene_index = int(params[0])
                scene = self.song.scenes[scene_index]
                if (include_ids):
                    #--------------------------------------------------------------------------------
                    # Hand the callee the *normalised, truncated* identity, not the raw
                    # OSC args. Every include_ids callee is a listener path, and a
                    # listener's identity has to be canonical: it is the bookkeeping key,
                    # the LOM subscript and the echo in the push, and those three must
                    # agree across a start/stop pair sent by different clients. TouchOSC
                    # -style clients send floats by default (upstream issue #33), so
                    # start_listen (0.0,) and stop_listen (0,) name the same subscription
                    # only if the cast happens here, once, before the callee sees
                    # anything. A scene subscription's identity is exactly one int:
                    # anything past it is dropped, so a stray trailing argument cannot
                    # key a second subscription that a well-formed stop can never reach.
                    #--------------------------------------------------------------------------------
                    rv = func(scene, *args, (scene_index,))
                else:
                    rv = func(scene, *args, params[1:])

                if rv is not None:
                    return (scene_index, *rv)

            return scene_callback

        methods = [
            "fire",
            "fire_as_selected",
        ]
        properties_r = [
            "is_empty",
            "is_triggered",
        ]
        properties_rw = [
            "color",
            "color_index",
            "name",
            "tempo",
            "tempo_enabled",
            "time_signature_numerator",
            "time_signature_denominator",
            "time_signature_enabled",
        ]

        for method in methods:
            self.osc_server.add_handler("/live/scene/%s" % method, create_scene_callback(self._call_method, method))

        for prop in properties_r + properties_rw:
            self.osc_server.add_handler("/live/scene/get/%s" % prop,
                                        create_scene_callback(self._get_property, prop))
            self.osc_server.add_handler("/live/scene/start_listen/%s" % prop,
                                        create_scene_callback(self._start_listen, prop, include_ids=True))
            self.osc_server.add_handler("/live/scene/stop_listen/%s" % prop,
                                        create_scene_callback(self._stop_listen, prop, include_ids=True))
        for prop in properties_rw:
            self.osc_server.add_handler("/live/scene/set/%s" % prop,
                                        create_scene_callback(self._set_property, prop))
        
        #------------------------------------------------------------------------------------------------
        # The Live API does not have a `fire_selected` Scene method (or class method accessible from Python).
        # This block adds a `fire_selected` method that calls `fire_as_selected` on the selected scene.
        #------------------------------------------------------------------------------------------------
        def scene_fire_selected(params: Tuple[Any] = ()):
            selected_scene = self.song.view.selected_scene
            if selected_scene:
                selected_scene.fire_as_selected()

        self.osc_server.add_handler("/live/scene/fire_selected", scene_fire_selected)