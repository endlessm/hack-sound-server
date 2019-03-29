from gi.repository import GLib
from gi.repository import HackSound

from hack_sound_server.utils.loggable import Logger
from hack_sound_server.server import UnknownSoundEventIDException
from hack_sound_server.server import TooManySoundsException
from hack_sound_server.v2.dbus.manager import DBusManager
from hack_sound_server.v2.sound import PlayerSoundFactory
from hack_sound_server.v2.utils.loggable import PlayerFormatter
from hack_sound_server.v2.utils.loggable import PlayerManagerFormatter
from hack_sound_server.v2.utils.misc import IdentifierFactory


PlayerFactory = IdentifierFactory()


class PlayerManager(DBusManager):
    _SKELETON_CLASS = HackSound.Server2PlayerSkeleton

    def __init__(self, player):
        super().__init__(player.server, player, PlayerManagerFormatter)

    @property
    def interface_name(self):
        return "com.endlessm.HackSoundServer2.Player"

    @property
    def object_path(self):
        return self.target_object.object_path

    def play(self, invocation, sound_event_id):
        self._play(invocation, sound_event_id)

    def play_full(self, invocation, sound_event_id, options):
        self._play(invocation, sound_event_id, options)

    def _play(self, invocation, sound_event_id, options=None):
        server = self.target_object.server
        try:
            sound = server.play_sound_with_factory(
                self.target_object.bus_name,
                sound_event_id,
                self.target_object.sound_factory.new,
                sound_event_id,
                metadata_extras=options
            )
            invocation.return_value(GLib.Variant('(o)', (sound.object_path, )))
        except UnknownSoundEventIDException as ex:
            invocation.return_dbus_error(ex.INTERFACE, str(ex))
        except TooManySoundsException:
            invalid_path = self.obj.invalid_sound.object_path
            invocation.return_value(GLib.Variant("(o)", invalid_path))


class Player:
    def __init__(self, server, app_id):
        self.server = server
        self.id = PlayerFactory.get_next_id()
        self.bus_name = app_id
        self.object_path = f"/com/endlessm/HackSoundServer2/players/{self.id}"

        self.logger = Logger(PlayerFormatter, self)
        self.manager = PlayerManager(self)
        self.manager.register_object()

        self.sound_factory = PlayerSoundFactory(self)
        self.invalid_sound = None

        self.register_invalid_sound()

    def register_invalid_sound(self):
        self.invalid_sound = self.sound_factory.new_invalid()

    def unregister_invalid_sound(self):
        self.invalid_sound.manager.unregister_object()
