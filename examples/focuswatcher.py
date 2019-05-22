from gi.repository import Gio
from gi.repository import GLib

from hack_sound_server.dbus.misc import FocusWatcher


if __name__ == "__main__":
    loop = GLib.MainLoop.new(None, False)
    focus_watcher = FocusWatcher()

    def focused_app_cb(watcher, *args):
        print("focused_app changed: ", watcher.focused_app)

    focus_watcher.connect("notify::focused-app", focused_app_cb)
    loop.run()
