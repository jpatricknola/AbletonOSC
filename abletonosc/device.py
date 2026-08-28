from typing import Tuple, Any
from .handler import AbletonOSCHandler

class DeviceHandler(AbletonOSCHandler):
    class_identifier = "device"

    def init_api(self):
        def create_device_callback(func, *args, include_ids: bool = False,
                                   id_count: int = 2):
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
                    #
                    # The identity is also *truncated* here: id_count is how a callee
                    # declares how many leading arguments are its identity (two for the
                    # property pair, three for the parameter pair, which reaches a
                    # DeviceParameter rather than the Device itself). Anything past that
                    # is dropped, so a stray trailing argument cannot key a second
                    # subscription that a well-formed stop can never reach.
                    #
                    # The first two identity elements are (track_index, device_index)
                    # themselves, reused rather than recomputed from params, so the
                    # lookup index and the identity index can never drift apart.
                    #--------------------------------------------------------------------------------
                    identity = (track_index, device_index) + tuple(
                        int(param) for param in params[2:id_count])
                    rv = func(device, *args, identity)
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
            # include_ids on the listen pair only. The get/ registration just above,
            # and the set/ registration in the loop below, already carry the indices
            # out through the wrapper's (track_index, device_index, *rv) reply
            # envelope, so adding ids there would echo them twice; the listener
            # pushes are built inside _start_listen from its own params, which
            # without ids is the empty tuple — a push with no identity, and a
            # listener key of (prop, ()) that collapses every device onto one
            # process-wide subscription.
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
            # The identity of a parameter listener is exactly three ints, and the
            # tuple is then used for all three things that have to agree: the
            # DeviceParameter lookup, the bookkeeping key and the echo in both pushes.
            # On the dispatch path the wrapper has already cast and truncated it
            # (include_ids with id_count=3), so this normalisation is a no-op there;
            # it stays because the start path calls the remove function below
            # directly, and because a callee that declares its own arity should not
            # depend on its caller having applied it. Note that a request carrying
            # fewer than three arguments still fails here, on int(params[2]) — too
            # few arguments is a malformed request, not a shorter identity.
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
            # Redundant on the dispatch path (the wrapper truncates and casts), but
            # load-bearing for the direct call the start path makes into here.
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

        #--------------------------------------------------------------------------------
        # Device: Describe parameters
        #
        # The numeric block above says where a parameter sits in its range. The
        # addresses below say what it *means*: the string the GUI shows, the enum
        # labels a quantized parameter cycles through, whether Live has greyed it out
        # or handed it to automation, what it resets to, and the name a rack macro or
        # a Max device renamed it from.
        #
        # Shape: one bulk address per field that is a single scalar per parameter,
        # answering in device.parameters order exactly as parameters/name does, plus a
        # per-parameter address for each. There is deliberately no combined record
        # address: API.md "Round trips cost ticks, not datagrams" measured a burst of
        # N different addresses answering inside one tick, identical to a single bulk
        # endpoint, so a record buys no latency — and value_items is variable-length
        # per parameter, so it could not sit in a fixed-arity record anyway.
        #
        # Every registration below is a literal address string, never assembled in a
        # loop. Seshat's vendored_addresses_test scrapes add_handler("...") literals
        # (plus the methods/properties_r/properties_rw lists) to check that every
        # address this fork registers is documented in API.md; an address built from a
        # format string would be invisible to that tripwire.
        #--------------------------------------------------------------------------------
        def _parameter_at(device, params: Tuple[Any]):
            #--------------------------------------------------------------------------------
            # Cast to int so we tolerate floats from interfaces such as TouchOSC that
            # send floats by default (upstream issue #33), exactly as
            # device_get_parameter_value does. The index comes back alongside the
            # parameter because every per-parameter reply echoes it.
            #--------------------------------------------------------------------------------
            param_index = int(params[0])
            return param_index, device.parameters[param_index]

        def _enum_code(value):
            #--------------------------------------------------------------------------------
            # ParameterState and AutomationState are Boost.Python enums. A Boost enum
            # is an int subclass, so the OSC builder would encode one as an int by
            # accident; casting here makes the integer wire form deliberate, and stops
            # a Live version that returns something else from silently changing the
            # reply's OSC type tag. Same convention as /live/device/get/type, which
            # already sends Live's device-type code. The code -> name tables are in
            # API.md, under "Parameter description".
            #--------------------------------------------------------------------------------
            return int(value)

        def _default_value_or_none(parameter):
            #--------------------------------------------------------------------------------
            # Live's docstring for default_value begins "Return the default value for
            # this parameter.  A Default value is only" — i.e. not every parameter has
            # one, and what a parameter without one does is unmeasured. A raise here
            # would cost the whole bulk reply, so one parameter's failure becomes OSC
            # nil in its own slot instead (the vendored builder encodes None as 'N').
            #--------------------------------------------------------------------------------
            try:
                return parameter.default_value
            except Exception:
                return None

        def _value_items_or_empty(parameter, attribute: str):
            #--------------------------------------------------------------------------------
            # Live: "Return the list of possible values for this parameter. Raises an
            # error if 'is_quantized' is False." The exception class is unmeasured —
            # Live 12.4.3's own Push2/model/repr guards the same read with
            # (AttributeError, RuntimeError) — so the catch is broad.
            #
            # Answering with no items rather than a /live/error is deliberate: a client
            # describing a whole device reads this per parameter, and would otherwise
            # collect one error per continuous parameter on its reply socket.
            # parameters/is_quantized already says which parameters can have items at
            # all, so an empty list is not ambiguous.
            #--------------------------------------------------------------------------------
            try:
                return tuple(getattr(parameter, attribute))
            except Exception:
                return ()

        def device_get_parameters_display_value(device, params: Tuple[Any] = ()):
            return tuple(parameter.display_value for parameter in device.parameters)

        def device_get_parameters_state(device, params: Tuple[Any] = ()):
            return tuple(_enum_code(parameter.state) for parameter in device.parameters)

        def device_get_parameters_is_enabled(device, params: Tuple[Any] = ()):
            return tuple(parameter.is_enabled for parameter in device.parameters)

        def device_get_parameters_automation_state(device, params: Tuple[Any] = ()):
            return tuple(_enum_code(parameter.automation_state) for parameter in device.parameters)

        def device_get_parameters_default_value(device, params: Tuple[Any] = ()):
            return tuple(_default_value_or_none(parameter) for parameter in device.parameters)

        def device_get_parameters_original_name(device, params: Tuple[Any] = ()):
            return tuple(parameter.original_name for parameter in device.parameters)

        def device_get_parameter_display_value(device, params: Tuple[Any] = ()):
            param_index, parameter = _parameter_at(device, params)
            return param_index, parameter.display_value

        def device_set_parameter_display_value(device, params: Tuple[Any] = ()):
            #--------------------------------------------------------------------------------
            # The value is passed through uncast: display_value is Live's *string*
            # setter ("100 Hz"), and Live does the parsing. A string Live cannot parse
            # is Live's business — if it raises, _dispatch turns that into a structured
            # /live/error naming this request.
            #--------------------------------------------------------------------------------
            _, parameter = _parameter_at(device, params)
            parameter.display_value = params[1]

        def device_get_parameter_state(device, params: Tuple[Any] = ()):
            param_index, parameter = _parameter_at(device, params)
            return param_index, _enum_code(parameter.state)

        def device_get_parameter_is_enabled(device, params: Tuple[Any] = ()):
            param_index, parameter = _parameter_at(device, params)
            return param_index, parameter.is_enabled

        def device_get_parameter_automation_state(device, params: Tuple[Any] = ()):
            param_index, parameter = _parameter_at(device, params)
            return param_index, _enum_code(parameter.automation_state)

        def device_get_parameter_default_value(device, params: Tuple[Any] = ()):
            param_index, parameter = _parameter_at(device, params)
            return param_index, _default_value_or_none(parameter)

        def device_get_parameter_original_name(device, params: Tuple[Any] = ()):
            param_index, parameter = _parameter_at(device, params)
            return param_index, parameter.original_name

        def device_get_parameter_value_items(device, params: Tuple[Any] = ()):
            param_index, parameter = _parameter_at(device, params)
            return (param_index, *_value_items_or_empty(parameter, "value_items"))

        def device_get_parameter_short_value_items(device, params: Tuple[Any] = ()):
            param_index, parameter = _parameter_at(device, params)
            return (param_index, *_value_items_or_empty(parameter, "short_value_items"))

        #--------------------------------------------------------------------------------
        # The gesture pair takes the /live/song/cue_point/jump form — object segment,
        # then verb — rather than /live/device/<method>, because the generic `methods`
        # loop at the top of this file reaches a Device, and these are methods of one
        # of its parameters. Both are silent, like every other method address here.
        #--------------------------------------------------------------------------------
        def device_parameter_begin_gesture(device, params: Tuple[Any] = ()):
            _, parameter = _parameter_at(device, params)
            parameter.begin_gesture()

        def device_parameter_end_gesture(device, params: Tuple[Any] = ()):
            _, parameter = _parameter_at(device, params)
            parameter.end_gesture()

        self.osc_server.add_handler("/live/device/get/parameters/display_value", create_device_callback(device_get_parameters_display_value))
        self.osc_server.add_handler("/live/device/get/parameters/state", create_device_callback(device_get_parameters_state))
        self.osc_server.add_handler("/live/device/get/parameters/is_enabled", create_device_callback(device_get_parameters_is_enabled))
        self.osc_server.add_handler("/live/device/get/parameters/automation_state", create_device_callback(device_get_parameters_automation_state))
        self.osc_server.add_handler("/live/device/get/parameters/default_value", create_device_callback(device_get_parameters_default_value))
        self.osc_server.add_handler("/live/device/get/parameters/original_name", create_device_callback(device_get_parameters_original_name))
        self.osc_server.add_handler("/live/device/get/parameter/display_value", create_device_callback(device_get_parameter_display_value))
        self.osc_server.add_handler("/live/device/set/parameter/display_value", create_device_callback(device_set_parameter_display_value))
        self.osc_server.add_handler("/live/device/get/parameter/state", create_device_callback(device_get_parameter_state))
        self.osc_server.add_handler("/live/device/get/parameter/is_enabled", create_device_callback(device_get_parameter_is_enabled))
        self.osc_server.add_handler("/live/device/get/parameter/automation_state", create_device_callback(device_get_parameter_automation_state))
        self.osc_server.add_handler("/live/device/get/parameter/default_value", create_device_callback(device_get_parameter_default_value))
        self.osc_server.add_handler("/live/device/get/parameter/original_name", create_device_callback(device_get_parameter_original_name))
        self.osc_server.add_handler("/live/device/get/parameter/value_items", create_device_callback(device_get_parameter_value_items))
        self.osc_server.add_handler("/live/device/get/parameter/short_value_items", create_device_callback(device_get_parameter_short_value_items))
        self.osc_server.add_handler("/live/device/parameter/begin_gesture", create_device_callback(device_parameter_begin_gesture))
        self.osc_server.add_handler("/live/device/parameter/end_gesture", create_device_callback(device_parameter_end_gesture))

        self.osc_server.add_handler("/live/device/get/parameter/value", create_device_callback(device_get_parameter_value))
        self.osc_server.add_handler("/live/device/get/parameter/value_string", create_device_callback(device_get_parameter_value_string))
        self.osc_server.add_handler("/live/device/set/parameter/value", create_device_callback(device_set_parameter_value))
        self.osc_server.add_handler("/live/device/get/parameter/name", create_device_callback(device_get_parameter_name))
        self.osc_server.add_handler("/live/device/start_listen/parameter/value", create_device_callback(device_get_parameter_value_listener, include_ids = True, id_count = 3))
        self.osc_server.add_handler("/live/device/stop_listen/parameter/value", create_device_callback(device_get_parameter_remove_value_listener, include_ids = True, id_count = 3))
