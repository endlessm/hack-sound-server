from gi.repository import GLib
from gi.repository import HackSound

from hack_sound_server.server import TooManySoundsException
from hack_sound_server.server import UnknownSoundEventIDException
from hack_sound_server.utils.loggable import Logger
from hack_sound_server.v2.dbus.manager import Manager
from hack_sound_server.v2.dbus.skeleton import Skeleton
from hack_sound_server.v2.sound import InvalidSound
from hack_sound_server.v2.sound import Sound
from hack_sound_server.v2.sound import SoundManager
from hack_sound_server.v2.utils.loggable import PlayerFormatter
from hack_sound_server.v2.utils.loggable import PlayerSkeletonFormatter
from hack_sound_server.v2.utils.misc import IdentifierFactory


PlayerFactory = IdentifierFactory()


class PlayerSkeleton(Skeleton):
    _SKELETON_IFACE_CLASS = HackSound.Server2PlayerSkeleton
    _LOGGER_FORMATTER = PlayerSkeletonFormatter
    _INTERFACE_NAME = "com.endlessm.HackSoundServer2.Player"

    def __init__(self, player):
        super().__init__(player.server, player)
        self.skeleton_iface.props.app_id = self.target_object.bus_name
        options_variant = GLib.Variant("a{sv}", self.target_object.options)
        self.skeleton_iface.props.options = options_variant
        self.sound_manager = SoundManager(player)

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
            server.ensure_not_too_many_sounds(sound_event_id)
            sound = server.get_sound(sound_event_id=sound_event_id,
                                     bus_name=self.target_object.bus_name)
            if sound is not None:
                server.try_overlap_behaviour(sound)
            else:
                peer_bus_name = invocation.get_sender()
                sound = server.new_sound(Sound, self.target_object,
                                         sound_event_id, peer_bus_name,
                                         metadata_extras=options)
            server._play_sound(sound)
            invocation.return_value(GLib.Variant("(o)", (sound.object_path, )))
        except UnknownSoundEventIDException as ex:
            invocation.return_dbus_error(ex.INTERFACE, ex)
        except TooManySoundsException:
            invalid_path = self.target_object.invalid_sound.object_path
            invocation.return_value(GLib.Variant("(o)", (invalid_path, )))


class PlayerManager(Manager):
    _OBJECT_PATH = "/com/endlessm/HackSoundServer2/players"

    def __init__(self, server):
        super().__init__(server, self._OBJECT_PATH)

    def unexport(self, skeleton):
        invalid_sound = skeleton.target_object.invalid_sound
        sound_manager = skeleton.target_object.skeleton.sound_manager
        sound_manager.unexport(invalid_sound.skeleton)
        super().unexport(skeleton)

    def unset_connection(self):
        super().unset_connection()


class Player:
    def __init__(self, server, app_id, options):
        self.server = server
        self.options = options
        self.manager = self.server.manager.player_manager

        self.id = PlayerFactory.get_next_id()
        self.bus_name = app_id
        self.object_path = f"/com/endlessm/HackSoundServer2/players/{self.id}"

        self.logger = Logger(PlayerFormatter, self)
        self.skeleton = PlayerSkeleton(self)

        self.sound_id_factory = IdentifierFactory()
        self.invalid_sound = InvalidSound(self)

        # Export all objects managed by the manager.
        self.skeleton.sound_manager.export(self.invalid_sound.skeleton)
        self.skeleton.sound_manager.set_connection()
        self.manager.export(self.skeleton)

        # Track player on bus name.
        self.server.watch_bus_name(self.bus_name)
