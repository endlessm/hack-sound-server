import json

from gi.repository import Gio
from gi.repository import GLib
from gi.repository import HackSound
from gi.repository import Json

from hack_sound_server.server import Server as _Server
from hack_sound_server.v2.dbus.manager import Manager
from hack_sound_server.v2.dbus.skeleton import Skeleton
from hack_sound_server.v2.player import Player
from hack_sound_server.v2.player import PlayerManager
from hack_sound_server.v2.utils.loggable import ServerSkeletonFormatter


class ServerSkeleton(Skeleton):
    _SKELETON_IFACE_CLASS = HackSound.Server2Skeleton
    _LOGGER_FORMATTER = ServerSkeletonFormatter
    _INTERFACE_NAME = "com.endlessm.HackSoundServer2"

    def __init__(self, server):
        super().__init__(server, server)
        metadata_str = json.dumps(self.target_object.metadata)
        metadata = Json.gvariant_deserialize_data(metadata_str, -1, None)
        self.skeleton_iface.props.metadata = metadata

    @property
    def object_path(self):
        return "/com/endlessm/HackSoundServer2"

    def get_player(self, invocation, app_id, options):
        options = options.unpack()
        player = self.target_object.registry.get_player(app_id, options)
        if not player:
            player = Player(self.target_object, app_id, options)
            self.target_object.registry.add_player(player)
        invocation.return_value(GLib.Variant("(o)", (player.object_path, )))


class ServerManager(Manager):
    _OBJECT_PATH = "/com/endlessm"

    def __init__(self, server):
        super().__init__(server, self._OBJECT_PATH)
        self.player_manager = PlayerManager(server)
        self._owner_id = None

        server.connect("notify::is-registered", self._server_is_registered_cb)

    def _server_is_registered_cb(self, unused_server, unused_pspec):
        self.manager.set_connection()
        self.player_manager.set_connection()

    def export(self, skeleton):
        self._owner_id = Gio.bus_own_name(Gio.BusType.SESSION,
                                          self.server.skeleton._INTERFACE_NAME,
                                          Gio.BusNameOwnerFlags.NONE,
                                          self._acquire_cb, None, None)

    def _acquire_cb(self, connection, bus_name):
        super().export(self.server.skeleton)

    def unexport(self):
        if self._owner_id is None:
            return
        Gio.bus_unown_name(self._owner_id)
        self._owner_id = None


class Server(_Server):
    def __init__(self, metadata):
        super().__init__(metadata)
        self.manager = ServerManager(self)
        self.skeleton = ServerSkeleton(self)
        self.registry.connect("player-removed", self._player_removed_cb)

        # Export all objects managed by the manager.
        self.connect("notify::is-registered", self._server_is_registered_cb)

    def _server_is_registered_cb(self, unused_server, unused_pspec):
        self.manager.set_connection()
        self.manager.player_manager.set_connection()

    def _player_removed_cb(self, unused_registry, player):

        self.manager.player_manager.unexport(player.skeleton)
        player.skeleton.sound_manager.unset_connection()

    def do_dbus_register(self, connection, path):
        super().do_dbus_register(connection, path)
        self.manager.export(self.skeleton)
        return True

    def do_dbus_unregister(self, connection, path):
        super().do_dbus_unregister(connection, path)
        self.manager.unexport()

    def _bus_name_disconnect_cb(self, unused_connection, bus_name):
        super()._bus_name_disconnect_cb(unused_connection, bus_name)
        self.registry.remove_players(bus_name)

    def _get_connection(self):
        return self.get_dbus_connection()

    @property
    def connection(self):
        if not self.props.is_registered:
            return None
        return self.get_dbus_connection()
