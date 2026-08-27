from typing import Tuple, Any
from .handler import AbletonOSCHandler

class DeviceHandler(AbletonOSCHandler):
    class_identifier = "device"

    def init_api(self):
        def create_device_callback(func, *args, include_ids: bool = False):
            def device_callback(params: Tuple[Any]):
                track_index, device_index = int(params[0]), int(params[1])
                device = self.song.tracks[track_index].devices[device_index]
                if (include_ids):
                    #--------------------------------------------------------------------------------
                    # Hand the callee the *normalised* identity, not the raw OSC args.
                    # Every include_ids callee is a listener path, and a listener's
                    # identity has to be canonical: it is the bookkeeping key, the LOM
                    # subscript and the echo in the push, and those three must agree
                    # across a start/stop pair sent by different clients. TouchOSC-style
                    # clients send floats by default (upstream issue #33), so
                    # start_listen (0.0, 0.0) and stop_listen (0, 0) name the same
                    # subscription only if the cast happens here, once, before the
                    # callee sees anything.
                    #--------------------------------------------------------------------------------
                    rv = func(device, *args, (track_index, device_index, *params[2:]))
                else:
                    rv = func(device, *args, params[2:])

                if rv is not None:
                    return (track_index, device_index, *rv)

            return device_callback

        methods = [
        ]
        properties_r = [
            "class_name",
            "name",
            "type"
        ]
        properties_rw = [
        ]

        for method in methods:
            self.osc_server.add_handler("/live/device/%s" % method,
                                        create_device_callback(self._call_method, method))

        for prop in properties_r + properties_rw:
            self.osc_server.add_handler("/live/device/get/%s" % prop,
                                        create_device_callback(self._get_property, prop))
            #--------------------------------------------------------------------------------
            # include_ids on the listen pair only. The get/ (and set/) registrations
            # above already carry the indices out through the wrapper's
            # (track_index, device_index, *rv) reply envelope, so adding ids there
            # would echo them twice; the listener pushes are built inside
            # _start_listen from its own params, which without ids is the empty
            # tuple — a push with no identity, and a listener key of (prop, ()) that
            # collapses every device onto one process-wide subscription.
            #--------------------------------------------------------------------------------
            self.osc_server.add_handler("/live/device/start_listen/%s" % prop,
                                        create_device_callback(self._start_listen, prop, include_ids=True))
            self.osc_server.add_handler("/live/device/stop_listen/%s" % prop,
                                        create_device_callback(self._stop_listen, prop, include_ids=True))
        for prop in properties_rw:
            self.osc_server.add_handler("/live/device/set/%s" % prop,
                                        create_device_callback(self._set_property, prop))

        #--------------------------------------------------------------------------------
        # Device: Get/set parameter lists
        #--------------------------------------------------------------------------------
        def device_get_num_parameters(device, params: Tuple[Any] = ()):
            return len(device.parameters),

        def device_get_parameters_name(device, params: Tuple[Any] = ()):
            return tuple(parameter.name for parameter in device.parameters)

        def device_get_parameters_value(device, params: Tuple[Any] = ()):
            return tuple(parameter.value for parameter in device.parameters)

        def device_get_parameters_min(device, params: Tuple[Any] = ()):
            return tuple(parameter.min for parameter in device.parameters)

        def device_get_parameters_max(device, params: Tuple[Any] = ()):
            return tuple(parameter.max for parameter in device.parameters)

        def device_get_parameters_is_quantized(device, params: Tuple[Any] = ()):
            return tuple(parameter.is_quantized for parameter in device.parameters)

        def device_set_parameters_value(device, params: Tuple[Any] = ()):
            for index, value in enumerate(params):
                device.parameters[index].value = value

        self.osc_server.add_handler("/live/device/get/num_parameters", create_device_callback(device_get_num_parameters))
        self.osc_server.add_handler("/live/device/get/parameters/name", create_device_callback(device_get_parameters_name))
        self.osc_server.add_handler("/live/device/get/parameters/value", create_device_callback(device_get_parameters_value))
        self.osc_server.add_handler("/live/device/get/parameters/min", create_device_callback(device_get_parameters_min))
        self.osc_server.add_handler("/live/device/get/parameters/max", create_device_callback(device_get_parameters_max))
        self.osc_server.add_handler("/live/device/get/parameters/is_quantized", create_device_callback(device_get_parameters_is_quantized))
        self.osc_server.add_handler("/live/device/set/parameters/value", create_device_callback(device_set_parameters_value))

        #--------------------------------------------------------------------------------
        # Device: Get/set individual parameters
        #--------------------------------------------------------------------------------
        def device_get_parameter_value(device, params: Tuple[Any] = ()):
            # Cast to ints so that we can tolerate floats from interfaces such as TouchOSC
            # that send floats by default.
            # https://github.com/ideoforms/AbletonOSC/issues/33
            param_index = int(params[0])
            return param_index, device.parameters[param_index].value
        
        # Uses str_for_value method to return the UI-friendly version of a parameter value (ex: "2500 Hz")
        def device_get_parameter_value_string(device, params: Tuple[Any] = ()):
            param_index = int(params[0])
            return param_index, device.parameters[param_index].str_for_value(device.parameters[param_index].value)
        
        #--------------------------------------------------------------------------------
        # A parameter listener is not bound to the device: it is bound to a
        # DeviceParameter, whose change notification is add_value_listener. So it is
        # registered under the base class's bookkeeping as the property "value", with
        # the whole (track, device, parameter) path forming the params half of the key
        # — the same shape track.py's mixer listeners and return_track.py use, and
        # what lets _stop_listen and _clear_listeners handle it with no special case.
        #
        # Upstream keyed it 'device_parameter_value' and never populated
        # listener_objects, so _clear_listeners (which iterates *all* of
        # listener_functions) raised on every reload with a parameter listener active.
        # Manager.clear_api iterates its handlers unguarded, so that also meant every
        # handler after this one — including all three of Seshat's — kept listeners
        # bound to the dead song object.
        #--------------------------------------------------------------------------------
        def device_get_parameter_value_listener(device, params: Tuple[Any] = ()):
            #--------------------------------------------------------------------------------
            # The identity of a parameter listener is exactly three ints. The wrapper
            # has already cast the track and device indices; the parameter index is
            # cast here, and the resulting tuple is then used for all three things
            # that have to agree: the DeviceParameter lookup, the bookkeeping key and
            # the echo in both pushes. Anything past the third argument is not part of
            # the identity and is dropped, so a stray extra argument cannot open a
            # second, unstoppable subscription to the same parameter.
            #--------------------------------------------------------------------------------
            params = (int(params[0]), int(params[1]), int(params[2]))
            parameter_index = params[2]

            def property_changed_callback():
                value = device.parameters[parameter_index].value
                self.logger.info("Property %s changed of %s %s: %s" % ('value', 'device parameter', str(params), value))
                self.osc_server.send("/live/device/get/parameter/value", (*params, value,))

                value_string = device.parameters[parameter_index].str_for_value(device.parameters[parameter_index].value)
                self.logger.info("Property %s changed of %s %s: %s" % ('value_string', 'device parameter', str(params), value_string))
                self.osc_server.send("/live/device/get/parameter/value_string", (*params, value_string,))

            listener_key = ("value", params)
            device_get_parameter_remove_value_listener(device, params)

            self.logger.info("Adding listener for %s %s, property: %s" % ('device parameter', str(params), 'value'))
            parameter_object = device.parameters[parameter_index]
            parameter_object.add_value_listener(property_changed_callback)
            self.listener_functions[listener_key] = property_changed_callback
            self.listener_objects[listener_key] = parameter_object

            property_changed_callback()

        #--------------------------------------------------------------------------------
        # Silent when nothing is registered, like the other DeviceParameter listeners
        # in this fork: the start path calls through here unconditionally to make
        # re-listening idempotent, and a first subscribe is not a missing-listener
        # error. Upstream warned here, but referenced an unbound `prop` to do it.
        #--------------------------------------------------------------------------------
        def device_get_parameter_remove_value_listener(device, params: Tuple[Any] = ()):
            #--------------------------------------------------------------------------------
            # Normalised the same way as the start path, and to the same three ints:
            # a stop sent with float indices has to find the key a start sent with
            # int indices created, or the listener leaks until the script reloads.
            #--------------------------------------------------------------------------------
            params = (int(params[0]), int(params[1]), int(params[2]))
            listener_key = ("value", params)
            if listener_key in self.listener_functions:
                self._stop_listen(self.listener_objects[listener_key], "value", params)

        def device_set_parameter_value(device, params: Tuple[Any] = ()):
            param_index, param_value = params[:2]
            param_index = int(param_index)
            device.parameters[param_index].value = param_value

        def device_get_parameter_name(device, params: Tuple[Any] = ()):
            param_index = int(params[0])
            return param_index, device.parameters[param_index].name

        self.osc_server.add_handler("/live/device/get/parameter/value", create_device_callback(device_get_parameter_value))
        self.osc_server.add_handler("/live/device/get/parameter/value_string", create_device_callback(device_get_parameter_value_string))
        self.osc_server.add_handler("/live/device/set/parameter/value", create_device_callback(device_set_parameter_value))
        self.osc_server.add_handler("/live/device/get/parameter/name", create_device_callback(device_get_parameter_name))
        self.osc_server.add_handler("/live/device/start_listen/parameter/value", create_device_callback(device_get_parameter_value_listener, include_ids = True))
        self.osc_server.add_handler("/live/device/stop_listen/parameter/value", create_device_callback(device_get_parameter_remove_value_listener, include_ids = True))
