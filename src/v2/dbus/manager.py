from gi.repository import Gio


class Manager:
    def __init__(self, server, object_path):
        self.manager = Gio.DBusObjectManagerServer(object_path=object_path)
        self.server = server

        if self.server.connection is not None:
            self.set_connection()
        else:
            self.server.connect("notify::is-registered",
                                self._server_is_registered_cb)

    def export(self, skeleton):
        self.manager.export(skeleton.skeleton)

    def unexport(self, skeleton):
        self.manager.unexport(skeleton.object_path)

    def set_connection(self):
        if self.server.connection is None:
            return
        self.manager.set_connection(self.server.connection)

    def unset_connection(self):
        self.manager.set_connection(None)

    def _server_is_registered_cb(self, connection, unused_arg):
        self.set_connection()
