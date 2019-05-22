import asyncio
from enum import auto
from enum import Enum

import dbussy as dbus
import glibcoro
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import GObject

from hack_sound_server.dbus.system import Desktop
from hack_sound_server.dbus.hackableapp import HackableApp
from hack_sound_server.dbus.hackableapp import HackableAppsManager
from hack_sound_server.utils.misc import get_app_id
from hack_sound_server.utils.loggable import logger


def get_toolbox_window_app_id(target_app_id):
    app_name = target_app_id.replace("com.endlessm.", "")
    return f"com.endlessm.HackToolbox.{app_name}"


class HackableAppOwnerWatcher(GObject.Object):

    __gsignals__ = {
        "owner-changed": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
        "owner-vanished": (GObject.SignalFlags.RUN_FIRST, None, (str, )),
    }

    def __init__(self):
        super().__init__()

    def _manager_proxy_ready_cb(self, *unused_args):
        self._watch_toolbox_connections()

    def _watch_toolbox_connections(self):
        for app_id in self.manager.whitelisted_app_ids:
            app_ids = [app_id, get_toolbox_window_app_id(app_id)]
            for bus_name in app_ids:
                Gio.bus_watch_name(Gio.BusType.SESSION,
                                   app_id,
                                   Gio.DBusProxyFlags.NONE,
                                   self._bus_name_connected_cb,
                                   self._bus_name_disconnect_cb)

    def _bus_name_connected_cb(self, unused_connection, name, owner):
        self.emit("owner-changed", name, owner)
        
    def _bus_name_disconnect_cb(self, unused_connection, name):
        self.emit("owner-vanished", name)


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
        PENDING = auto()
        CANCELED = auto()
        COMPLETE = auto()

    def __init__(self, focused_app):
        super().__init__()

        self._state = FocusedAppPendingInfo.State.PENDING
        self._hackable_app = None
        self._target_well_known_name = None
        self._target_unique_name = None

        self._timeout_countdown_id = None
        self.state = FocusedAppPendingInfo.State.PENDING

        self._focused_app_id = focused_app[:-8] # Remove .desktop

        HackableAppsManager.connect("notify::currently-hackable-apps",
                                    self._currently_hackable_apps_changed_cb)

        self._hackable_app_changed_id = \
            self.connect("notify::hackable-app", self._hackable_app_changed_cb)
        self._target_well_known_name_id = \
            self.connect("notify::target-well-known-name",
                         self._target_well_known_name_changed_cb)
        self._state_changed_id = self.connect("notify::state",
                                              self._state_changed_cb)
        self._hackable_state_changed_id = None

        self._try_set_hackable_app()
        self._try_set_target_well_known_name()

    def _restart_timeout_countdown(self, default_timeout_ms=30):
        def cancel():
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

    def _try_set_hackable_app(self):
        if HackableAppsManager.proxy is None:
            return

        self.hackable_app = \
            HackableAppsManager.get_by_app_id(self._focused_app_id)

    def _currently_hackable_apps_changed_cb(self, *unused_args):
        self._try_set_hackable_app()

    def _hackable_app_changed_cb(self, *unused_args):
        self._try_set_target_well_known_name()

    def _try_set_target_well_known_name(self):
        if self.hackable_app is not None:
            if self.hackable_app.state == HackableApp.State.TOOLBOX:
                self.target_well_known_name = \
                    get_toolbox_window_app_id(self.hackable_app.app_id)
            else:
                self.target_well_known_name = self._hackable_app.app_id
        elif HackableAppsManager.proxy is not None:
            whitelisted_app_ids = HackableAppsManager.whitelisted_app_ids
            if self._focused_app_id not in whitelisted_app_ids:
                self.target_well_known_name = self._focused_app_id

    def _target_well_known_name_changed_cb(self, *unused_args):
        Desktop.get_name_owner(self.target_well_known_name,
                               self._get_name_owner_cb)

    def _get_name_owner_cb(self, name_owner):
        if name_owner is not None:
            self.target_unique_name = name_owner
            self.state = FocusedAppPendingInfo.State.COMPLETE
        else:
            self.state = FocusedAppPendingInfo.State.CANCELED

    def _state_changed_cb(self, *unused_args):
        if self.state == FocusedAppPendingInfo.State.PENDING:
            self._restart_timeout_countdown()
        elif self.state == FocusedAppPendingInfo.State.CANCELED:
            self._cancel_timeout_countdown()
        elif self.state == FocusedAppPendingInfo.State.COMPLETE:
            self._cancel_timeout_countdown()

    def _hackable_state_changed_cb(self, hackable_app, *unused_args):
        self.state = FocusedAppPendingInfo.State.PENDING
        self._try_set_target_well_known_name()

    def _disconnect_callbacks(self):
        self.disconnect(self._hackable_app_changed_id)
        self.disconnect(self._target_well_known_name_id)
        self.disconnect(self._state_changed_id)
        self._try_disconnect_hackable_app()

    def _try_disconnect_hackable_app(self):
        if (isinstance(self.hackable_app, HackableApp) and
                self._hackable_state_changed_id is not None):
            self.hackable_app.disconnect(self._hackable_state_changed_id)
            self._hackable_state_changed_id = None

    # Emit "notify::property" only if the property actually changed.

    def _set_state(self, value):
        if self._state != value:
            self._state = value
            self.notify("state")

    def _get_state(self):
        return self._state

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

    def _get_hackable_app(self):
        return self._hackable_app

    def _set_target_well_known_name(self, value):
        if self._target_well_known_name != value:
            self.state = FocusedAppPendingInfo.State.PENDING
            self._target_well_known_name = value
            self.notify("target-well-known-name")

    def _get_target_well_known_name(self):
        return self._target_well_known_name

    def _set_target_unique_name(self, value):
        if self._target_unique_name != value:
            self._target_unique_name = value
            self.notify("target-unique-name")

    def _get_target_unique_name(self):
        return self._target_unique_name

    state = \
        GObject.Property(type=object,
                         setter=_set_state,
                         getter=_get_state,
                         flags=(GObject.ParamFlags.READWRITE |
                                GObject.ParamFlags.EXPLICIT_NOTIFY))
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
        self.target_well_known_name = pending_info.target_well_known_name
        self.target_unique_name = pending_info.target_unique_name

    def __eq__(self, other):
        if not isinstance(other, FocusedAppCachedInfo):
            return False
        return (self.target_well_known_name == other.target_well_known_name and
                self.target_unique_name == other.target_unique_name)

    def __ne__(self, other):
        return not self == other
        

class FocusWatcher(GObject.Object):
    def __init__(self, desktop_watcher):
        super().__init__()

        self._desktop_watcher = desktop_watcher
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
        else:
            self._cached_info = None

        if old_cached_info != self._cached_info:
            self.notify("focused-app-info")

    def _update_pending_info(self, focused_app):
        if (isinstance(self._pending_info, FocusedAppPendingInfo) and 
                self._pending_info_state_changed_id is not None):
            self._pending_info._disconnect_callbacks()
            self._pending_info.disconnect(self._pending_info_state_changed_id)

        if self._desktop_watcher.focused_app is None:
            self._pending_info = None
            return
        self._pending_info = FocusedAppPendingInfo(focused_app)
        self._pending_info_state_changed_id = \
            self._pending_info.connect("notify::state",
                                       self._pending_info_state_changed_cb)

    def _start_info_update(self):
        self._update_pending_info(self._desktop_watcher.focused_app)
        if self._pending_info is None:
            self._update_cached_info(None)

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

    def _focused_app_changed_cb(self, *unused_args):
        self._start_info_update()

    def _overview_active_changed_cb(self, *unused_args):
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
