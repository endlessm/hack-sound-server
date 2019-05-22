from enum import auto
from enum import Enum

from gi.repository import GLib
from gi.repository import GObject

from hack_sound_server.dbus.system import Desktop
from hack_sound_server.dbus.hackableapp import HackableApp
from hack_sound_server.dbus.hackableapp import HackableAppsManager
from hack_sound_server.utils.misc import get_app_id
from hack_sound_server.utils.loggable import logger


class FocusWatcher(GObject.Object):

    class Status(Enum):
        WAITING_FOCUSED_APP_ID = auto()
        FOCUSED_APP_ID_SET = auto()
        REAL_APP_ID_SET = auto()
        COMPLETED = auto()

    __gsignals__ = {
        "status-changed": (GObject.SignalFlags.RUN_FIRST, None, ())
    }

    def __init__(self):
        super().__init__()

        HackableAppsManager.get_proxy_async(self._manager_proxy_ready_cb)
        Desktop.get_shell_proxy_async(self._shell_proxy_ready_cb)
        Desktop.get_dbus_proxy_async(self._dbus_proxy_ready_cb)

        # Intermediate helper attributes.
        self._focused_app_id = None
        self._real_app_id = None
        # The unique bus name of the currently Hack application.
        self._focused_app = None

        self._status = FocusWatcher.Status.WAITING_FOCUSED_APP_ID
        self.connect("status-changed", self._status_changed_cb)

    def _status_changed_cb(self, unused_watcher):
        if self._status == FocusWatcher.Status.WAITING_FOCUSED_APP_ID:
            self._set_focused_app_id()
        elif self._status == FocusWatcher.Status.FOCUSED_APP_ID_SET:
            self._set_real_app_id()
        elif self._status == FocusWatcher.Status.REAL_APP_ID_SET:
            try:
                Desktop.get_name_owner(self._real_app_id,
                                       self._get_name_owner_cb)
            except Exception as ex:
                logger(ex)

    def _dbus_proxy_ready_cb(self, *unused_args):
        if self._status != FocusWatcher.Status.REAL_APP_ID_SET:
            return
        assert self._real_app_id is not None
        Desktop.get_name_owner(self._real_app_id, self._get_name_owner_cb)

    def _manager_proxy_ready_cb(self, *unused_args):
        HackableAppsManager.connect("notify::currently-hackable-apps",
                                    self._currently_hackable_apps_changed_cb)
        self._set_real_app_id()

    def _currently_hackable_apps_changed_cb(self, *unused_args):
        self._set_real_app_id()

    def _get_name_owner_cb(self, name_owner):
        self._focused_app = name_owner
        self._status = FocusWatcher.Status.COMPLETED
        self.emit("status-changed")
        self.notify("focused-app")

    def _shell_proxy_ready_cb(self, *unused_args):
        Desktop.shell_proxy.connect("g-properties-changed",
                                    self._shell_properties_changed_cb)
        self._status = FocusWatcher.Status.WAITING_FOCUSED_APP_ID
        self.emit("status-changed")

    def _shell_properties_changed_cb(self, unused_proxy, changed_properties,
                                     *unused_args):
        changed_properties_dict = changed_properties.unpack()
        if "FocusedApp" in changed_properties_dict:
            self._status = FocusWatcher.Status.WAITING_FOCUSED_APP_ID
            self.emit("status-changed")

    def _hackable_app_state_changed_cb(self, hackable_app, *unused_args):
        self._ensure_hackable_app_disconnected(hackable_app)
        print("_hackable_app_state_changed_cb")
        self._status = FocusWatcher.Status.WAITING_FOCUSED_APP_ID
        self.emit("status-changed")

    def _ensure_hackable_app_disconnected(self, hackable_app):
        try:
            hackable_app.disconnect_by_func(
                self._hackable_app_state_changed_cb)
        except:
            pass

    def _set_real_app_id(self):
        if self._status != FocusWatcher.Status.FOCUSED_APP_ID_SET:
            return

        change_status = False
        try:
            hackable_app = \
                HackableAppsManager.get_by_app_id(self._focused_app_id)
        except AttributeError:
            hackable_app = None

        if hackable_app is not None:
            change_status = True

            self._ensure_hackable_app_disconnected(hackable_app)
            hackable_app.connect("notify::state",
                                 self._hackable_app_state_changed_cb)

            if hackable_app.state == HackableApp.State.TOOLBOX:
                app_name = hackable_app.app_id.replace("com.endlessm.", "")
                self._real_app_id = f"com.endlessm.HackToolbox.{app_name}"
            else:
                self._real_app_id = hackable_app.app_id
        else:
            if not HackableAppsManager.proxy:
                return

            whitelisted_app_ids = HackableAppsManager.whitelisted_app_ids
            if self._focused_app_id not in whitelisted_app_ids:
                change_status = True
                self._real_app_id = self._focused_app_id

        if change_status:
            self._status = FocusWatcher.Status.REAL_APP_ID_SET
            self.emit("status-changed")

    def _set_focused_app_id(self):
        assert Desktop.shell_proxy is not None
        self._focused_app_id = Desktop.get_foreground_app()
        if self._focused_app_id is not None:
            self._focused_app_id = get_app_id(self._focused_app_id)
        self._status = FocusWatcher.Status.FOCUSED_APP_ID_SET
        self.emit("status-changed")

    def _get_focused_app(self):
        return self._focused_app

    focused_app = \
        GObject.Property(getter=_get_focused_app, type=str, default=None,
                         flags=(GObject.ParamFlags.READABLE |
                                GObject.ParamFlags.EXPLICIT_NOTIFY))
