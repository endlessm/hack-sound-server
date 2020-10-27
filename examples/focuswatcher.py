from gi.repository import GLib

from hack_sound_server.v2.dbus.watcher import FocusWatcher
from hack_sound_server.v2.dbus.watcher import DesktopWatcher
from hack_sound_server.v2.dbus.watcher import BusNameWatcher
from hack_sound_server.v2.dbus.hackableapp import HackableAppsManager
from hack_sound_server.v2.dbus.system import Desktop


if __name__ == "__main__":
    loop = GLib.MainLoop.new(None, False)

    HackableAppsManager.get_proxy_async()
    Desktop.get_shell_proxy_async()
    Desktop.get_dbus_proxy_async()

    toolbox_watcher = BusNameWatcher()
    toolbox_watcher.watch("com.endlessm.HackToolbox")
    desktop_watcher = DesktopWatcher()
    focus_watcher = FocusWatcher(desktop_watcher, toolbox_watcher)

    def focused_app_info_cb(watcher, *args):

        if watcher.focused_app_info is None:
            print("No app is focused")
        else:
            print("focused app id: ",
                  watcher.focused_app_info.focused_app_id)
            print("unique name: ",
                  watcher.focused_app_info.target_unique_name)
            print("well-known name: ",
                  watcher.focused_app_info.target_well_known_name)
        print("-" * 80)

    focus_watcher.connect("notify::focused-app-info", focused_app_info_cb)
    loop.run()
