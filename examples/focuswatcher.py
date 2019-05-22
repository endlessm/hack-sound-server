from gi.repository import Gio
from gi.repository import GLib

from hack_sound_server.dbus.watcher import FocusWatcher
from hack_sound_server.dbus.watcher import DesktopWatcher
from hack_sound_server.dbus.hackableapp import HackableAppsManager
from hack_sound_server.dbus.system import Desktop


if __name__ == "__main__":
    loop = GLib.MainLoop.new(None, False)

    HackableAppsManager.get_proxy_async()
    Desktop.get_shell_proxy_async()
    Desktop.get_dbus_proxy_async()

    desktop_watcher = DesktopWatcher()
    focus_watcher = FocusWatcher(desktop_watcher)

    def focused_app_info_cb(watcher, *args):

        if watcher.focused_app_info is None:
            print("No app is focused")
        else:
            print("unique name: ",
                  watcher.focused_app_info.target_well_known_name)
            print("well-known name: ",
                  watcher.focused_app_info.target_unique_name)
        print("-" * 80)

    focus_watcher.connect("notify::focused-app-info", focused_app_info_cb)
    loop.run()
