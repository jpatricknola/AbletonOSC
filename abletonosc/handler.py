from ableton.v2.control_surface.component import Component
from typing import Optional, Tuple, Any
import logging
from .osc_server import OSCServer

class AbletonOSCHandler(Component):
    """
    Base class for every OSC handler in this fork.

    Constructor contract — the order is the point, and every subclass and
    every future handler relies on it:

      1. ``Component.__init__`` runs.
      2. The base invariants exist: ``logger``, ``manager``, ``osc_server``,
         ``listener_functions``, ``listener_objects``,
         ``listener_lom_properties``. ``class_identifier`` is a *class*
         attribute, so it is already set before the instance exists at all.
      3. ``init_state()`` runs — the one documented place for subclass-owned
         instance state.
      4. ``init_api()`` runs — route registration, which may therefore rely
         on everything above it.

    So ``init_api()`` may read ``self.class_identifier``, touch the listener
    dicts, and use anything ``init_state()`` created. Teardown is
    ``clear_api()``.

    Do not reorder these steps. Nothing fails immediately if you do: no
    ``init_api()`` body in this repository reads the invariants at
    registration time, they are only read later from callbacks. A reverted
    order therefore stays invisible until the first handler that uses the
    guarantee — and then fails as a bare ``AttributeError``, or worse, as
    listener pushes silently addressed to ``/live/None/get/<prop>``.
    """

    #--------------------------------------------------------------------------------
    # The name this handler answers to: it appears in every log line and in the
    # "/live/<class_identifier>/get/<prop>" addresses that listener pushes go
    # out on. Declared at class level rather than assigned in __init__ so that
    # identity is available from the first line of init_state()/init_api(),
    # with no ordering hazard at all. Subclasses override it in their class
    # statement; None here is only the "never declared one" default.
    #--------------------------------------------------------------------------------
    class_identifier: Optional[str] = None

    def __init__(self, manager):
        super().__init__()

        self.logger = logging.getLogger("abletonosc")
        self.manager = manager
        self.osc_server: OSCServer = self.manager.osc_server
        self.listener_functions = {}
        self.listener_objects = {}
        self.listener_lom_properties = {}
        self.init_state()
        self.init_api()

    def init_state(self):
        """
        Create subclass-owned instance state.

        Runs once per instance, after every base invariant exists and strictly
        before ``init_api()``. Subclass instance state belongs here; route
        registration does not — that is ``init_api()``.
        """
        pass

    def init_api(self):
        pass

    def clear_api(self):
        self._clear_listeners()

    #--------------------------------------------------------------------------------
    # Generic callbacks
    #--------------------------------------------------------------------------------
    #--------------------------------------------------------------------------------
    # _call_method and _set_property let exceptions propagate: every callback
    # invocation is caught per-message by OSCServer._dispatch, which sends the
    # structured /live/error ("request", address, detail, argc, *args)
    # envelope with the failing request still in hand, and process() has its
    # own per-datagram catch — so a failure here never aborts the rest of the
    # messages queued on this tick.
    #--------------------------------------------------------------------------------
    def _call_method(self, target, method, params: Optional[Tuple] = ()):
        self.logger.info("Calling method for %s: %s (params %s)" % (self.class_identifier, method, str(params)))
        getattr(target, method)(*params)

    def _set_property(self, target, prop, params: Tuple) -> None:
        self.logger.info("Setting property for %s: %s (new value %s)" % (self.class_identifier, prop, params[0]))
        setattr(target, prop, params[0])

    def _get_property(self, target, prop, params: Optional[Tuple] = ()) -> Tuple[Any]:
        try:
            value = getattr(target, prop)
        except RuntimeError:
            #--------------------------------------------------------------------------------
            # Gracefully handle errors, which may occur when querying parameters that don't apply
            # to a particular object (e.g. track.fold_state for a non-group track)
            #--------------------------------------------------------------------------------
            value = None
        self.logger.info("Getting property for %s: %s = %s" % (self.class_identifier, prop, value))
        return (value, *params)

    def _start_listen(self, target, prop, params: Optional[Tuple] = (), getter = None,
                      lom_property: Optional[str] = None) -> None:
        """
        Start listening for the property named `prop` on the Live object `target`.
        `params` is typically a tuple containing the track/clip index.

        getter can be used for a customer getter when we're accessing native objects
        e.g. in view.py we don't return the selected_scene, but the selected_scene index.

        Args:
            target:
            prop: the *public* name — the bookkeeping key and the second half
                  of the "/live/<class_identifier>/get/<prop>" push address.
            params:
            getter:
            lom_property: the name of the LOM property to actually subscribe
                  to, when it differs from `prop`. Seshat extension: it lets
                  two OSC addresses observe one observable property and push
                  different values under their own names —
                  `start_listen/selected_track` and
                  `start_listen/selected_track_identity` both subscribe to
                  `Song.View.selected_track`. `None` (every upstream call
                  site) means "same as `prop`", which is upstream behaviour
                  exactly.
        """
        def property_changed_callback():
            if getter is None:
                value = getattr(target, prop)
            else:
                value = getter(params)
            if type(value) is not tuple:
                value = (value,)
            self.logger.info("Property %s changed of %s %s: %s" % (prop, self.class_identifier, str(params), value))
            osc_address = "/live/%s/get/%s" % (self.class_identifier, prop)
            self.osc_server.send(osc_address, (*params, *value,))

        lom_prop = lom_property or prop
        listener_key = (prop, tuple(params))
        if listener_key in self.listener_functions:
            self._stop_listen(target, prop, params)

        #--------------------------------------------------------------------------------
        # The alias is named in the log only when there is one, so the
        # unaliased line — every upstream call site — stays byte for byte what
        # it has always been.
        #--------------------------------------------------------------------------------
        if lom_prop == prop:
            self.logger.info("Adding listener for %s %s, property: %s" % (self.class_identifier, str(params), prop))
        else:
            self.logger.info("Adding listener for %s %s, property: %s (LOM property: %s)" % (self.class_identifier, str(params), prop, lom_prop))
        add_listener_function_name = "add_%s_listener" % lom_prop
        add_listener_function = getattr(target, add_listener_function_name)
        add_listener_function(property_changed_callback)
        self.listener_functions[listener_key] = property_changed_callback
        self.listener_objects[listener_key] = target
        #--------------------------------------------------------------------------------
        # The LOM name has to be *stored*, not just passed: _clear_listeners
        # reconstructs (prop, params) from the key alone and has no way to know
        # an alias was ever used, so _stop_listen must be able to recover it.
        #--------------------------------------------------------------------------------
        self.listener_lom_properties[listener_key] = lom_prop
        #--------------------------------------------------------------------------------
        # Immediately send the current value
        #--------------------------------------------------------------------------------
        property_changed_callback()

    def _stop_listen(self, target, prop, params: Optional[Tuple[Any]] = ()) -> None:
        listener_key = (prop, tuple(params))
        if listener_key in self.listener_functions:
            self.logger.info("Removing listener for %s %s, property %s" % (self.class_identifier, str(params), prop))
            #--------------------------------------------------------------------------------
            # Unbind from the object the listener was actually registered on, not the
            # one we were handed. Listeners are keyed by index but bound to a LOM
            # object, and indices renumber: delete track 0 of [A, B, C] and index 0
            # now means B, so a re-subscribe hands us B while the stored callback
            # belongs to A. B.remove_x_listener would then raise, be swallowed below
            # as benign, and the dict entry dropped regardless — leaving A's listener
            # alive forever, still pushing under an index that now means someone else.
            #--------------------------------------------------------------------------------
            target = self.listener_objects.get(listener_key, target)
            listener_function = self.listener_functions[listener_key]
            #--------------------------------------------------------------------------------
            # Unbind from the LOM property the listener was actually registered
            # on, which is `prop` itself for every caller that did not alias.
            # The .get fallback keeps unaliased and stale-key paths behaving
            # exactly as they did before aliasing existed — including
            # device.py's hand-rolled parameter listener, which writes the two
            # other dicts itself and unbinds through here under "value".
            #--------------------------------------------------------------------------------
            lom_prop = self.listener_lom_properties.get(listener_key, prop)
            remove_listener_function_name = "remove_%s_listener" % lom_prop
            remove_listener_function = getattr(target, remove_listener_function_name)
            try:
                remove_listener_function(listener_function)
            except Exception as e:
                #--------------------------------------------------------------------------------
                # This exception may be thrown when an observer is no longer connected --
                # e.g., when trying to stop listening for a clip property of a clip that has been deleted.
                # Ignore as it is benign.
                #--------------------------------------------------------------------------------
                self.logger.info("Exception whilst removing listener (likely benign): %s" % e)

            del self.listener_functions[listener_key]
            del self.listener_objects[listener_key]
            self.listener_lom_properties.pop(listener_key, None)
        else:
            self.logger.warning("No listener function found for property: %s (%s)" % (prop, str(params)))

    def _clear_listeners(self):
        """
        Clears all listener functions, to prevent listeners continuing to report after a reload.
        """
        for listener_key in list(self.listener_functions.keys())[:]:
            target = self.listener_objects[listener_key]
            prop, params = listener_key
            self._stop_listen(target, prop, params)
