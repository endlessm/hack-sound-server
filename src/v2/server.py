from gi.repository import Gio
from gi.repository import GLib
from gi.repository import HackSound

from hack_sound_server.server import Server as _Server
from hack_sound_server.v2.dbus.manager import DBusManager
from hack_sound_server.v2.player import Player
from hack_sound_server.v2.sound import ServerSoundFactory


class ServerManager(DBusManager):
    _SKELETON_CLASS = HackSound.Server2Skeleton

    def __init__(self, server):
        super().__init__(server, server)
        self._owner_id = None

        self.server.registry.connect("player-added", self._player_added_cb)
        self.server.registry.connect("player-removed", self._player_removed_cb)

    @property
    def interface_name(self):
        return "com.endlessm.HackSoundServer2"

    @property
    def object_path(self):
        return "/com/endlessm/HackSoundServer2"

    def get_player(self, invocation, app_id, unused_options):
        player = self.target_object.registry.players_by_bus_name.get(app_id)
        if not player:
            player = Player(self.target_object, app_id)
            self.target_object.registry.add_player(player)
        invocation.return_value(GLib.Variant("(o)", (player.object_path, )))

    def _player_added_cb(self, unused_registry, player):
        self.server.watch_bus_name(player.bus_name)
        self.server.cancel_countdown()
        self.server.hold()

    def _player_removed_cb(self, unused_registry):
        if not self.server.registry.players:
            self.server.ensure_release_countdown()
        self.server.release()

    def register_object(self, unused_connection=None, path=None):
        self._owner_id = Gio.bus_own_name(
             Gio.BusType.SESSION,
             self.interface_name,
             Gio.BusNameOwnerFlags.NONE,
             self._acquire_cb, None, None
        )

    def _acquire_cb(self, connection, bus_name):
        super().register_object(connection)

    def unregister_object(self):
        if self._owner_id is None:
            return
        Gio.bus_unown_name(self._owner_id)


class Server(_Server):
    def __init__(self, metadata):
        super().__init__(metadata)
        self.manager = ServerManager(self)
        self.sound_factory = ServerSoundFactory(self)

    def do_dbus_register(self, connection, path):
        super().do_dbus_register(connection, path)
        # self.manager.register_object(connection, path)
        self.manager.register_object()
        return True

    def do_dbus_unregister(self, connection, path):
        super().do_dbus_unregister(connection, path)
        self.manager.unregister_object()

    def _bus_name_disconnect_cb(self, unused_connection, bus_name):
        super()._bus_name_disconnect_cb(unused_connection, bus_name)
        player = self.registry.get_player(bus_name)
        if player is None:
            return
        self.registry.remove_player(bus_name)
