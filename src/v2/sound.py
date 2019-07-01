from gi.repository import Gio
from gi.repository import GObject
from gi.repository import HackSound

from hack_sound_server.sound import Sound as _Sound
from hack_sound_server.sound import SoundBase as _SoundBase
from hack_sound_server.v2.dbus.manager import Manager
from hack_sound_server.v2.dbus.skeleton import Skeleton
from hack_sound_server.v2.utils.loggable import SoundSkeletonFormatter


class SoundManager(Manager):
    def __init__(self, player):
        object_path = f"{player.object_path}/sounds"
        super().__init__(player.server, object_path)


class SoundSkeleton(Skeleton):
    _SKELETON_IFACE_CLASS = HackSound.Server2SoundSkeleton
    _LOGGER_FORMATTER = SoundSkeletonFormatter
    _INTERFACE_NAME = "com.endlessm.HackSoundServer2.Sound"

    def __init__(self, sound):
        super().__init__(sound.player.server, sound)

    @property
    def object_path(self):
        return self.target_object.object_path

    def stop(self, invocation):
        self.terminate_sound_for_sender(invocation)

    def terminate(self, invocation):
        self.terminate_sound_for_sender(invocation, term_sound=True)

    def update_properties(self, invocation, transition_time_ms, options):
        server = self.manager.server

        if self.target_object.uuid not in server.registry.sounds:
            self.logger.info("Properties of this sound was supposed to be "
                             "updated, but it is not in the registry.")
        else:
            player = server.get_sound(self.target_object.uuid)
            player.update_properties(transition_time_ms, options)
        invocation.return_value(None)

    def terminate_sound_for_sender(self, invocation, term_sound=False):
        """
        Decreases the reference count of a sound for the given `sender`.

        Optional keyword arguments:
            term_sound (bool): Defaults to False, which means to decrease the
                               refcount by 1. If set to True, then the refcount
                               is set to 0.
        """
        server = self.server
        server.terminate_sound_for_sender(self.target_object.uuid,
                                          invocation.get_connection(),
                                          self.target_object.player.bus_name,
                                          invocation, term_sound)

    def _method_called_cb(self, connection, sender, path, iface,
                          method, params, invocation):
        if self.target_object.is_invalid:
            invocation.return_error_literal(
                Gio.dbus_error_quark(), Gio.DBusError.UNKNOWN_METHOD,
                "Cannot call methods on an invalid sound."
            )
            return

        super()._method_called_cb(connection, sender, path, iface,
                                  method, params, invocation)


class InvalidSound(_SoundBase):
    def __init__(self, player):
        super().__init__()
        self.id = "invalid"
        self.player = player
        self.object_path = f"{self.player.object_path}/sounds/{self.id}"

        self.skeleton = SoundSkeleton(self)
        self.player.skeleton.sound_manager.export(self.skeleton)

    @property
    def uuid(self):
        return self.object_path


class Sound(_Sound):

    __gsignals__ = {
        "stop": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, player, sound_event_id, peer_bus_name,
                 metadata_extras=None):
        super().__init__(player.server, player.bus_name, sound_event_id,
                         metadata_extras=metadata_extras)

        self.id = player.sound_id_factory.get_next_id()
        self.player = player
        self.object_path = f"{self.player.object_path}/sounds/{self.id}"
        self.peer_bus_name = peer_bus_name

        self.skeleton = SoundSkeleton(self)
        self.player.skeleton.sound_manager.export(self.skeleton)

        self.connect("stop", self._stop_cb)
        self.connect("released", self._stop_cb)

    def stop(self):
        self.emit("stop")
        super().stop()

    def _stop_cb(self, unused_sound):
        self.player.skeleton.sound_manager.unexport(self.skeleton)

    @property
    def uuid(self):
        return self.object_path
