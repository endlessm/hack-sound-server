from abc import ABC
from abc import abstractmethod

from gi.repository import Gio

from hack_sound_server.v2.utils.misc import dbus_method_to_signal
from hack_sound_server.v2.utils.misc import snakecase


class Skeleton(ABC):
    _SKELETON_IFACE_CLASS = None
    _LOGGER_FORMATTER = None
    _INTERFACE_NAME = None

    def __init__(self, server, target_object):
        self.server = server
        self.target_object = target_object

        self.skeleton_iface = self._SKELETON_IFACE_CLASS()
        self.logger = self._LOGGER_FORMATTER(obj=self)

        self.skeleton = Gio.DBusObjectSkeleton()
        self.skeleton.set_object_path(self.object_path)
        self.skeleton.add_interface(self.skeleton_iface)

        self._connect_signals()

    @property
    @abstractmethod
    def object_path(self):
        pass

    def _connect_signals(self):
        obj = self.skeleton_iface.get_object()
        iface = obj.get_interface(self._INTERFACE_NAME)
        iface_info = iface.get_info()

        for method in iface_info.methods:
            callback = None
            callback_name = snakecase(method.name)

            if hasattr(self, callback_name):
                callback = getattr(self, callback_name)
            if not callable(callback):
                continue

            def _callback(skeleton, *args):
                callback = args[-1]
                callback(*args[:-1])

            signal_name = dbus_method_to_signal(method.name)
            self.skeleton_iface.connect(signal_name, _callback, callback)
