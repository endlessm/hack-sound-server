from gi.repository import Gio
from gi.repository import HackSound

from hack_sound_server.sound import Sound as _Sound
from hack_sound_server.sound import SoundBase as _SoundBase
from hack_sound_server.sound import ServerSoundFactory as _ServerSoundFactory
from hack_sound_server.v2.dbus.manager import DBusManager
from hack_sound_server.v2.utils.loggable import SoundManagerFormatter
from hack_sound_server.v2.utils.misc import IdentifierFactory


class PlayerSoundFactory(IdentifierFactory):
    def __init__(self, player):
        super().__init__()
        self.player = player

    def new(self, sound_event_id, metadata_extras=None):
        """
        Creates a new valid `Sound` for the given event id.

        If the sound is a non-overlaping sound, then an existing sound will
        be returned.

        Args:
            sound_event_id (str): The sound event identifier as specified
                                  in the metadata.json file.

            The rest of arguments are the same of Sound.__init__ method.

        Returns:
            A `Sound` object.
        """

        return self.player.server.sound_factory.new2(self.player,
                                                     sound_event_id,
                                                     metadata_extras)

    def new_invalid(self):
        """
        Creates a new invalid `Sound`.

        All DBus methods calls on this sound will emit a DBus error.

        Returns:
            A `Sound` object.
        """

        return self.player.server.sound_factory.new2_invalid(self.player)


class SoundManager(DBusManager):
    _SKELETON_CLASS = HackSound.Server2SoundSkeleton

    def __init__(self, sound):
        super().__init__(sound.player.server, sound, SoundManagerFormatter)

    @property
    def interface_name(self):
        return "com.endlessm.HackSoundServer2.Sound"

    @property
    def object_path(self):
        print("tget obj:", self.target_object.object_path)
        return self.target_object.object_path

    def stop(self, invocation):
        self.terminate_sound_for_sender(invocation)

    def terminate(self, invocation):
        self.terminate_sound_for_sender(invocation, term_sound=True)

    def update_properties(self, invocation, transition_time_ms, options):
        server = self.server

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

        # TODO
        # Maybe the Registry should have a method check_sound_exists
        # and actually check in all the dictionaries for the existence of the
        # sound.
        if self.target_object.uuid not in server.registry.sounds:
            self.logger.info("This sound was supposed to be stopped, but did "
                             "not exist in the registry.")
        elif (self.target_object.uuid in server.registry.sounds and
                self.target_object.uuid not in server.registry.refcount):
            self.logger.info("This sound was supposed to be "
                             "refcounted by its bus name in the registry, "
                             "but it isn't.")
        else:
            target_bus_name = self.target_object.bus_name
            assert (self.target_object.player and
                    target_bus_name == self.target_object.player.bus_name)

            server.unref_on_stop(self.target_object, term_sound)

            if server.refcount(self.target_object) == 0:
                self.unregister_object()
            # TODO
            # Now it is not possible to stop a sound by its sound event id!
            # Should there be a method
            # com.endlessm.HackSoundServer.Player.StopSound?
        invocation.return_value(None)

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

        self.manager = SoundManager(self)
        self.manager.register_object()

    @property
    def uuid(self):
        return self.object_path


class Sound(_Sound):
    def __init__(self, player, sound_event_id, metadata_extras=None):
        super().__init__(player.server, player.bus_name, sound_event_id,
                         metadata_extras)

        self.id = player.sound_factory.get_next_id()
        self.player = player
        self.object_path = f"{self.player.object_path}/sounds/{self.id}"

        self.manager = SoundManager(self)
        self.manager.register_object()

    @property
    def uuid(self):
        return self.object_path


class ServerSoundFactory(_ServerSoundFactory):
    def __init__(self, server):
        super().__init__(server)

    def new2(self, *args, **kwargs):
        return Sound(*args, **kwargs)

    def new2_invalid(self, *args):
        return InvalidSound(*args)
