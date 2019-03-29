import os
from abc import ABC
from abc import abstractmethod
from gi.repository import Gio

from hack_sound_server.utils.loggable import Logger
from hack_sound_server.v2.utils.misc import dbus_method_to_signal
from hack_sound_server.v2.utils.misc import snakecase


class DBusManager(ABC):
    _SKELETON_CLASS = None
    _managers = {}

    def __init__(self, server, target_object, formatter=None):
        self.target_object = target_object
        self.server = server
        self.skeleton = None

        if formatter is not None:
            self.logger = Logger(formatter, self)
        else:
            self.logger = Logger(obj=self)

    @property
    @abstractmethod
    def interface_name(self):
        pass

    @property
    @abstractmethod
    def object_path(self):
        pass

    @property
    def manager_object_path(self):
        return os.path.abspath(os.path.join(self.object_path, os.pardir))

    @property
    def manager(self):
        manager = self._managers.get(self.manager_object_path)
        if manager is None:
            manager = Gio.DBusObjectManagerServer(
                object_path=self.manager_object_path)
            self._managers[self.manager_object_path] = manager
        return manager

    def register_object(self, connection=None):
        if self._SKELETON_CLASS is None:
            return

        if self.skeleton and self.skeleton.get_connection() is not None:
            self.logger.debug("Object at path '%s' already registered.",
                              self.object_path)
            return

        if connection is None:
            connection = self.server.get_dbus_connection()
        self.manager.set_connection(connection)

        self.skeleton = self._SKELETON_CLASS()
        object_skeleton = Gio.DBusObjectSkeleton()
        object_skeleton.set_object_path(self.object_path)
        object_skeleton.add_interface(self.skeleton)
        self.manager.export(object_skeleton)

        self._connect_signals()

    def unregister_object(self):
        if self.skeleton.get_connection() is None:
            return
        self.skeleton.unexport()

    def _connect_signals(self):
        obj = self.skeleton.get_object()
        iface = obj.get_interface(self.interface_name)
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
            self.skeleton.connect(signal_name, _callback, callback)
