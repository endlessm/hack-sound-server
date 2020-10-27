from enum import Enum
from enum import auto

from gi.repository import Gio
from gi.repository import GLib
from gi.repository import GObject

from hack_sound_server.utils.loggable import logger

from hack_sound_server.v2.dbus.system import Desktop
from hack_sound_server.v2.dbus.hackableapp import HackableApp
from hack_sound_server.v2.dbus.hackableapp import HackableAppsManager


class BusNameWatcher(GObject.Object):

    class Unwatched(Exception):
        pass

    class _BusNameData:
        def __init__(self):
            self.watcher_id = None
            self.cached_owner = None

    __gsignals__ = {
        "owner-changed": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
        "owner-vanished": (GObject.SignalFlags.RUN_FIRST, None, (str, )),
    }

    def __init__(self):
        super().__init__()
        self._data_by_bus_name = {}

    def watch(self, bus_name):
        if bus_name in self._data_by_bus_name:
            return

        if not Gio.dbus_is_name(bus_name):
            logger.error(f"Cannot watch '{bus_name}' because not a bus name.")
            return

        logger.debug(f"Start to watch '{bus_name}'.")
        data = BusNameWatcher._BusNameData()
        data.watcher_id = Gio.bus_watch_name(Gio.BusType.SESSION,
                                             bus_name,
                                             Gio.DBusProxyFlags.NONE,
                                             self._bus_name_connected_cb,
                                             self._bus_name_disconnect_cb)
        self._data_by_bus_name[bus_name] = data

    def unwatch(self, bus_name):
        self._ensure_bus_name_watched(bus_name)
        logger.debug(f"Unwatch '{bus_name}'.")
        Gio.bus_unwatch_name(self._data_by_bus_name[bus_name].watcher_id)
        del self._data_by_bus_name[bus_name]

    def unwatch_all(self):
        for bus_name in list(self._data_by_bus_name):
            self.unwatch(bus_name)

    def get_owner(self, bus_name):
        self._ensure_bus_name_watched(bus_name)
        return self._data_by_bus_name[bus_name].cached_owner

    def _bus_name_connected_cb(self, unused_connection, name, owner):
        try:
            self._ensure_bus_name_watched(name)
        except BusNameWatcher.Unwatched as ex:
            logger.warning(ex)
        else:
            self._data_by_bus_name[name].cached_owner = owner
            self.emit("owner-changed", name, owner)

    def _bus_name_disconnect_cb(self, unused_connection, name):
        try:
            self._ensure_bus_name_watched(name)
        except BusNameWatcher.Unwatched as ex:
            logger.warning(ex)
        else:
            self._data_by_bus_name[name].cached_owner = None
            self.emit("owner-vanished", name)

    def _ensure_bus_name_watched(self, bus_name):
        if bus_name not in self._data_by_bus_name:
            raise BusNameWatcher.Unwatched(f"Bus name '{bus_name}' was is not "
                                           "watched.")


class DesktopWatcher(GObject.Object):

    def __init__(self):
        super().__init__()
        Desktop.get_shell_proxy_async(self._shell_proxy_ready_cb)

    def _shell_proxy_ready_cb(self, *unused_args):
        Desktop.shell_proxy.connect("g-properties-changed",
                                    self._shell_properties_changed_cb)
        self.notify("focused-app")
        self.notify("overview-active")

    def _shell_properties_changed_cb(self, unused_proxy, changed_properties,
                                     *unused_args):
        changed_properties_dict = changed_properties.unpack()
        if "FocusedApp" in changed_properties_dict:
            logger.info(f"Focused app is '{self.focused_app}'")
            self.notify("focused-app")
        if "OverviewActive" in changed_properties_dict:
            self.notify("overview-active")

    def _get_focused_app(self):
        if Desktop.shell_proxy is None:
            return None
        return Desktop.get_foreground_app()

    def _get_overview_active(self):
        if Desktop.shell_proxy is None:
            return None
        return Desktop.get_overview_active()

    focused_app = \
        GObject.Property(getter=_get_focused_app, type=str, default=None,
                         flags=(GObject.ParamFlags.READABLE |
                                GObject.ParamFlags.EXPLICIT_NOTIFY))
    overview_active = \
        GObject.Property(getter=_get_overview_active, type=bool, default=False,
                         flags=(GObject.ParamFlags.READABLE |
                                GObject.ParamFlags.EXPLICIT_NOTIFY))


class FocusedAppPendingInfo(GObject.Object):

    class State(Enum):
        # Going from PENDING to COMPLETE and from COMPLETE to PENDING is
        # possible, but going from CANCELED to another state is not possible.
        PENDING = auto()
        CANCELED = auto()
        COMPLETE = auto()
        VANISHED = auto()

    def __init__(self, focused_app_id, toolbox_bus_name_watcher,
                 desktop_watcher):
        super().__init__()

        self._state = FocusedAppPendingInfo.State.PENDING
        self._focused_app_id = focused_app_id
        # Asynchronously set properties.
        self._hackable_app = None
        # The target well known name of the focused application. In the case of
        # a hackable app, it can be "com.endlessm.Fizzics" if in the frontside
        # or "com.endlessm.Toolbox" if in the backside.
        self._target_well_known_name = None
        self._target_unique_name = None

        self._timeout_countdown_id = None
        self._restart_timeout_countdown()

        # Setup watchers.
        self._toolbox_bus_name_watcher = toolbox_bus_name_watcher
        self._focused_app_bus_name_watcher = BusNameWatcher()
        self._focused_app_bus_name_watcher.watch(self._focused_app_id)
        self._focused_app_bus_name_watcher.connect("owner-changed",
                                                   self._owner_changed_cb)
        self._focused_app_bus_name_watcher.connect("owner-vanished",
                                                   self._owner_vanished_cb)

        # We start in PENDING state until the target unique name has been set,
        # where the state is set to COMPLETE. Setting the unique name depends
        # on having another properties already set, but these another
        # properties are not set immediately, but they wait for the
        # HackableAppsManager and HackableApp proxies and the bus name watcher
        # to be ready.
        self._currently_hackable_apps_changed_id = HackableAppsManager.connect(
            "notify::currently-hackable-apps",
            self._currently_hackable_apps_changed_cb)

        self._hackable_app_changed_id = self.connect(
            "notify::hackable-app", self._hackable_app_changed_cb)
        self._target_well_known_name_id = self.connect(
            "notify::target-well-known-name",
            self._target_well_known_name_changed_cb)
        self._state_changed_id = self.connect(
            "notify::state", self._state_changed_cb)

        self._hackable_state_changed_id = None

        # Try to set the property values in the case dbus proxies or
        # bus name watchers are ready.
        self._try_set_hackable_app()
        self._try_set_target_well_known_name()

    def cancel(self):
        self.state = FocusedAppPendingInfo.State.CANCELED

    def _owner_changed_cb(self, watcher, bus_name, owner):
        self._try_set_target_unique_name()

    def _owner_vanished_cb(self, *unused_args):
        self.state = FocusedAppPendingInfo.State.VANISHED

    def _currently_hackable_apps_changed_cb(self, *unused_args):
        self._try_set_hackable_app()

    def _hackable_app_changed_cb(self, *unused_args):
        self._try_set_target_well_known_name()

    def _target_well_known_name_changed_cb(self, *unused_args):
        self._try_set_target_unique_name()

    def _state_changed_cb(self, *unused_args):
        if self.state == FocusedAppPendingInfo.State.PENDING:
            self._restart_timeout_countdown()
        elif self.state != FocusedAppPendingInfo.State.VANISHED:
            self._cancel_timeout_countdown()
        if self.state in (FocusedAppPendingInfo.State.CANCELED,
                          FocusedAppPendingInfo.State.VANISHED):
            self._disconnect_callbacks()

    def _try_set_hackable_app(self):
        if HackableAppsManager.proxy is None:
            return

        self.hackable_app = \
            HackableAppsManager.get_by_app_id(self._focused_app_id)

    def _try_set_target_well_known_name(self):
        if self.hackable_app is not None:
            if self.hackable_app.state == HackableApp.State.TOOLBOX:
                self.target_well_known_name = "com.endlessm.HackToolbox"
            else:
                self.target_well_known_name = self._hackable_app.app_id
        elif HackableAppsManager.proxy is not None:
            whitelisted_app_ids = HackableAppsManager.whitelisted_app_ids or ()
            # If not a hackable app, then the focused app is the target
            # well-known name.
            if self._focused_app_id not in whitelisted_app_ids:
                self.target_well_known_name = self._focused_app_id

    def _try_set_target_unique_name(self):
        if self.target_well_known_name == "com.endlessm.HackToolbox":
            watcher = self._toolbox_bus_name_watcher
        else:
            watcher = self._focused_app_bus_name_watcher
        owner = watcher.get_owner(self.target_well_known_name)

        if owner is not None:
            self.target_unique_name = owner
            self.state = FocusedAppPendingInfo.State.COMPLETE

    def _restart_timeout_countdown(self, default_timeout_ms=30):
        def cancel():
            logger.debug("Timeout reached trying to get focused app info.")
            self.state = FocusedAppPendingInfo.State.CANCELED
            self._timeout_countdown_id = None
            return GLib.SOURCE_REMOVE

        self._cancel_timeout_countdown()
        self._timeout_countdown_id = GLib.timeout_add(
            default_timeout_ms, cancel, priority=GLib.PRIORITY_LOW)

    def _cancel_timeout_countdown(self):
        if self._timeout_countdown_id is not None:
            GLib.Source.remove(self._timeout_countdown_id)
            self._timeout_countdown_id = None

    def _hackable_state_changed_cb(self, hackable_app, *unused_args):
        self.state = FocusedAppPendingInfo.State.PENDING
        self._try_set_target_well_known_name()

    def _disconnect_callbacks(self):
        self.disconnect(self._hackable_app_changed_id)
        self.disconnect(self._target_well_known_name_id)
        self.disconnect(self._state_changed_id)
        HackableAppsManager.disconnect(
            self._currently_hackable_apps_changed_id)
        self._focused_app_bus_name_watcher.unwatch_all()
        self._try_disconnect_hackable_app()

    def _try_disconnect_hackable_app(self):
        if (isinstance(self.hackable_app, HackableApp) and
                self._hackable_state_changed_id is not None):
            self.hackable_app.disconnect(self._hackable_state_changed_id)
            self._hackable_state_changed_id = None

    # By default pygobject does emit "notify::property" even when the property
    # is set to a value equal to the old value. Change this behavior to emit
    # "notify::property" only if the property actually changed.
    def _set_state(self, value):
        if self._state != value:
            self._state = value
            self.notify("state")

    def _set_hackable_app(self, value):
        if self._hackable_app != value:
            self.state = FocusedAppPendingInfo.State.PENDING
        self._try_disconnect_hackable_app()
        self._hackable_app = value
        if isinstance(self._hackable_app, HackableApp):
            self._hackable_state_changed_id = \
                self._hackable_app.connect("notify::state",
                                           self._hackable_state_changed_cb)
        self.notify("hackable-app")

    def _set_target_well_known_name(self, value):
        if self._target_well_known_name != value:
            self.state = FocusedAppPendingInfo.State.PENDING
        self._target_well_known_name = value
        self.notify("target-well-known-name")

    def _set_target_unique_name(self, value):
        if self._target_unique_name != value:
            self._target_unique_name = value
            self.notify("target-unique-name")

    def _get_state(self):
        return self._state

    def _get_hackable_app(self):
        return self._hackable_app

    def _get_target_well_known_name(self):
        return self._target_well_known_name

    def _get_target_unique_name(self):
        return self._target_unique_name

    def _get_focused_app_id(self):
        return self._focused_app_id

    state = \
        GObject.Property(type=object,
                         setter=_set_state,
                         getter=_get_state,
                         flags=(GObject.ParamFlags.READWRITE |
                                GObject.ParamFlags.EXPLICIT_NOTIFY))
    focused_app_id = \
        GObject.Property(type=object,
                         getter=_get_focused_app_id,
                         flags=GObject.ParamFlags.READABLE)
    hackable_app = \
        GObject.Property(type=object,
                         setter=_set_hackable_app,
                         getter=_get_hackable_app,
                         flags=(GObject.ParamFlags.READWRITE |
                                GObject.ParamFlags.EXPLICIT_NOTIFY))
    target_well_known_name = \
        GObject.Property(type=str,
                         setter=_set_target_well_known_name,
                         getter=_get_target_well_known_name,
                         flags=(GObject.ParamFlags.READWRITE |
                                GObject.ParamFlags.EXPLICIT_NOTIFY))
    target_unique_name = \
        GObject.Property(type=str,
                         setter=_set_target_unique_name,
                         getter=_get_target_unique_name,
                         flags=(GObject.ParamFlags.READWRITE |
                                GObject.ParamFlags.EXPLICIT_NOTIFY))


class FocusedAppCachedInfo:
    def __init__(self, pending_info):
        self.focused_app_id = pending_info.focused_app_id
        self.target_well_known_name = pending_info.target_well_known_name
        self.target_unique_name = pending_info.target_unique_name

    def __eq__(self, other):
        if not isinstance(other, FocusedAppCachedInfo):
            return False
        return (self.target_well_known_name == other.target_well_known_name and
                self.target_unique_name == other.target_unique_name and
                self.focused_app_id == other.focused_app_id)

    def __ne__(self, other):
        return not self == other


class FocusWatcher(GObject.Object):
    def __init__(self, desktop_watcher, toolbox_bus_name_watcher):
        super().__init__()

        self._desktop_watcher = desktop_watcher
        self._toolbox_bus_name_watcher = toolbox_bus_name_watcher

        self._pending_info = None
        self._cached_info = None

        self._start_info_update()

        self._pending_info_state_changed_id = None
        self._desktop_watcher.connect("notify::focused-app",
                                      self._focused_app_changed_cb)
        self._desktop_watcher.connect("notify::overview-active",
                                      self._overview_active_changed_cb)

    def _update_cached_info(self, pending_info):
        old_cached_info = self._cached_info
        if (pending_info is not None and
                pending_info.state == FocusedAppPendingInfo.State.COMPLETE):
            self._cached_info = FocusedAppCachedInfo(pending_info)
        elif pending_info is None:
            self._cached_info = None

        if old_cached_info != self._cached_info:
            self.notify("focused-app-info")

    def _ensure_disconnected_pending_info(self):
        if (isinstance(self._pending_info, FocusedAppPendingInfo) and
                self._pending_info_state_changed_id is not None):
            self._pending_info.disconnect(self._pending_info_state_changed_id)
            self._pending_info_state_changed_id = None
            self._pending_info.cancel()

    def _update_pending_info(self, focused_app):
        if isinstance(focused_app, str) and focused_app.endswith(".desktop"):
            focused_app_id = focused_app[:-8]
        else:
            focused_app_id = None
        if (isinstance(self._pending_info, FocusedAppPendingInfo) and
                self._pending_info.focused_app_id == focused_app_id):
            return

        self._ensure_disconnected_pending_info()

        if focused_app_id is None:
            self._pending_info = None
        elif (Gio.dbus_is_name(focused_app_id) and
                not Gio.dbus_is_unique_name(focused_app_id)):
            self._pending_info = \
                FocusedAppPendingInfo(focused_app_id,
                                      self._toolbox_bus_name_watcher,
                                      self._desktop_watcher)
            self._pending_info_state_changed_id = self._pending_info.connect(
                "notify::state", self._pending_info_state_changed_cb)
        else:
            self._pending_info = None
            logger.warning(f"Focused app is '{focused_app}'. But applications "
                           "without a focused app name distinct from a "
                           "well-known-name application id are not supported.")

    def _start_info_update(self):
        self._update_pending_info(self._desktop_watcher.focused_app)
        if self._pending_info is None:
            self._update_cached_info(None)
        else:
            self._update_cached_info(self._pending_info)

    def _pending_info_state_changed_cb(self, pending_info, *unused_args):
        if self._pending_info != pending_info:
            logger.warning("Object at <%s> was supposed to be freed",
                           pending_info)
            return

        state = self._pending_info.state
        if state == FocusedAppPendingInfo.State.COMPLETE:
            self._update_cached_info(pending_info)
        elif state == FocusedAppPendingInfo.State.CANCELED:
            self._update_cached_info(None)
        elif state == FocusedAppPendingInfo.State.VANISHED:
            pass

    def _focused_app_changed_cb(self, *unused_args):
        self._start_info_update()

    def _overview_active_changed_cb(self, *unused_args):
        # self._update_pending_info(None)
        if self._desktop_watcher.overview_active:
            self._update_cached_info(None)
        else:
            self._update_cached_info(self._pending_info)

    def _get_focused_app(self):
        return self._cached_info

    focused_app_info = \
        GObject.Property(getter=_get_focused_app, type=object, default=None,
                         flags=(GObject.ParamFlags.READABLE |
                                GObject.ParamFlags.EXPLICIT_NOTIFY))
