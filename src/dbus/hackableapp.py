from enum import Enum

from gi.repository import Gio
from gi.repository import GLib
from gi.repository import GObject
from hack_sound_server.utils.loggable import logger


class HackableApp(GObject.Object):

    class State(Enum):
        APP = 0
        TOOLBOX = 1

    class InvalidatedException(Exception):
        pass

    __gsignals__ = {
        "proxy-ready": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "proxy-error": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "proxy-cancelled": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, object_path):
        super().__init__()
        self.object_path = object_path

        self.proxy = None
        self._cancellable = Gio.Cancellable()

        self.connect("proxy-ready", self._proxy_ready_cb)
        self._cancellable.connect(self._cancelled_cb)

    def _proxy_ready_cb(self, *unused_args):
        self.proxy.connect("g-properties-changed",
                           self._g_properties_changed_cb)

    def _g_properties_changed_cb(self, unused_proxy, changed_properties,
                                 *unused_args):
        changed_properties_dict = changed_properties.unpack()
        if "State" in changed_properties_dict:
            self.notify("state")

    def cancel(self):
        self._cancellable.cancel()

    def _cancelled_cb(self, *unused_args):
        self.emit("proxy-cancelled")

    def get_proxy_async(self, callback=None, *callback_args):
        def _on_proxy_ready(proxy, result):
            try:
                self.proxy = proxy.new_finish(result)
                self.emit("proxy-ready")
            except GLib.Error as e:
                logger.warning("Error: Failed to get DBus proxy:", e.message)
                self.emit("proxy-error")
                return

            if callable(callback):
                callback(self.proxy, *callback_args)

        if self.proxy is None:
            Gio.DBusProxy.new_for_bus(Gio.BusType.SESSION,
                                      0,
                                      None,
                                      "org.gnome.Shell",
                                      self.object_path,
                                      "com.endlessm.HackableApp",
                                      self._cancellable,
                                      _on_proxy_ready)
        elif callable(callback):
            callback(self.proxy, *callback_args)

    def _get_app_id(self):
        if self.proxy is None:
            raise AttributeError("Proxy invalidated")
        variant = self.proxy.get_cached_property("AppId")
        return variant.unpack()

    def _get_state(self):
        if self.proxy is None:
            raise AttributeError("Proxy invalidated")
        variant = self.proxy.get_cached_property("State")
        return HackableApp.State(variant.unpack())

    app_id = \
        GObject.Property(getter=_get_app_id, type=str,
                         flags=GObject.ParamFlags.READABLE)
    state = \
        GObject.Property(getter=_get_state,
                         type=object,
                         flags=(GObject.ParamFlags.READABLE |
                                GObject.ParamFlags.EXPLICIT_NOTIFY))


class _HackableAppsManager(GObject.Object):
    def __init__(self):
        super().__init__()

        self.proxy = None
        self._ready_hackable_apps = {}
        self._pending_hackable_apps = {}
        self._currently_hackable_apps = {}

    def update_hackable_apps(self):
        """
        Updates the hackable apps asynchronously.
        """
        currently_hackable_apps = \
            self.proxy.get_cached_property("CurrentlyHackableApps")

        for object_path in list(self._pending_hackable_apps.keys()):
            if object_path not in currently_hackable_apps:
                hackable_app = self._pending_hackable_apps[object_path]
                hackable_app.cancel()
                # TODO: As soon this point is reached,
                # the proxy-cancelled callback _remove_pending_hackable_app
                # should be called. Not sure if this line is necessary.
                self._remove_pending_hackable_app(hackable_app)

        for object_path in list(self._ready_hackable_apps.keys()):
            if object_path not in currently_hackable_apps:
                self._remove_ready_hackable_app(hackable_app)

        for object_path in currently_hackable_apps:
            if object_path in self._pending_hackable_apps:
                continue

            hackable_app = HackableApp(object_path)
            hackable_app.connect("proxy-ready",
                                 self._hackable_app_ready_cb)
            hackable_app.connect("proxy-error",
                                 self._remove_pending_hackable_app)
            hackable_app.connect("proxy-cancelled",
                                 self._remove_pending_hackable_app)

            self._pending_hackable_apps[object_path] = hackable_app
            hackable_app.get_proxy_async()

        if not self._pending_hackable_apps:
            self._set_currently_hackable_apps()

    def _remove_pending_hackable_app(self, hackable_app):
        if hackable_app.object_path not in self._pending_hackable_apps:
            return
        del self._pending_hackable_apps[hackable_app.object_path]

    def _remove_ready_hackable_app(self, hackable_app):
        if hackable_app.object_path not in self._ready_hackable_apps:
            return
        del self._ready_hackable_apps[hackable_app.object_path]

    def _hackable_app_ready_cb(self, hackable_app):
        self._remove_pending_hackable_app(hackable_app)
        self._ready_hackable_apps[hackable_app.object_path] = hackable_app
        if not self._pending_hackable_apps:
            self._set_currently_hackable_apps()

    def _set_currently_hackable_apps(self):
        assert self._pending_hackable_apps == {}

        # All the hackable apps have a ready proxy.
        self._currently_hackable_apps = self._ready_hackable_apps
        self._ready_hackable_apps = {}
        self.notify("currently-hackable-apps")

    def get_by_app_id(self, app_id):
        """
        Gets the hackable app given an app id.
        """
        for hackable_app in self._currently_hackable_apps.values():
            if hackable_app.proxy and hackable_app.app_id == app_id:
                return hackable_app
        return None

    def _hackable_app_invalidated(self, hackable_app, object_path):
        del self._hackable_apps[object_path]

    def _setup_proxy(self, proxy):
        self.update_hackable_apps()
        proxy.connect("g-properties-changed", self._g_properties_changed_cb)

    def _g_properties_changed_cb(self, unused_proxy, changed_properties,
                                 *unused_args):
        changed_properties_dict = changed_properties.unpack()
        if "CurrentlyHackableApps" in changed_properties_dict:
            self.update_hackable_apps()

    def get_proxy_async(self, callback, *callback_args):
        def _on_proxy_ready(proxy, result):
            try:
                self.proxy = proxy.new_finish(result)
                self._setup_proxy(self.proxy)
            except GLib.Error as e:
                logger.warning("Error: Failed to get DBus proxy:", e.message)
                return

            if callable(callback):
                callback(self.proxy, *callback_args)

        if self.proxy is None:
            Gio.DBusProxy.new_for_bus(Gio.BusType.SESSION,
                                      0,
                                      None,
                                      "com.endlessm.HackableAppsManager",
                                      "/com/endlessm/HackableAppsManager",
                                      "com.endlessm.HackableAppsManager",
                                      None,
                                      _on_proxy_ready)
        elif callable(callback):
            callback(self.proxy, *callback_args)

    def _get_currently_hackable_apps(self):
        return self._currently_hackable_apps.keys()

    def _get_whitelisted_app_ids(self):
        if self.proxy is None:
            raise AttributeError("Proxy invalidated")
        return self.proxy.get_cached_property("WhitelistedAppIds")

    currently_hackable_apps = \
        GObject.Property(getter=_get_currently_hackable_apps, type=object,
                         flags=(GObject.ParamFlags.READABLE |
                                GObject.ParamFlags.EXPLICIT_NOTIFY))
    whitelisted_app_ids = \
        GObject.Property(getter=_get_whitelisted_app_ids, type=object,
                         flags=GObject.ParamFlags.READABLE)


HackableAppsManager = _HackableAppsManager()
