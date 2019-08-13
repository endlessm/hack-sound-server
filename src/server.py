import gi
gi.require_version('GLib', '2.0')  # noqa
from gi.repository import Gio
from gi.repository import GLib
from collections import namedtuple
from hack_sound_server.registry import Registry
from hack_sound_server.sound import Sound
from hack_sound_server.utils.loggable import Logger
from hack_sound_server.utils.loggable import ServerFormatter


DBusWatcher = namedtuple("DBusWatcher", ["watcher_id", "uuids"])


class UnregisteredUUID(Exception):
    pass


class TooManySoundsException(Exception):
    pass


class UnknownSoundEventIDException(Exception):
    INTERFACE = "com.hack_computer.HackSoundServer.UnknownSoundEventID"


class Server(Gio.Application):
    _TIMEOUT_S = 10
    _MAX_SIMULTANEOUS_SOUNDS = 5
    OVERLAP_BEHAVIOR_CHOICES = ("overlap", "restart", "ignore")
    _DBUS_NAME = "com.hack_computer.HackSoundServer"
    _DBUS_XML = """
    <node>
      <interface name='com.hack_computer.HackSoundServer'>
        <method name='PlaySound'>
          <arg type='s' name='sound_event' direction='in'/>
          <arg type='s' name='uuid' direction='out'/>
        </method>
        <method name='PlayFull'>
          <arg type='s' name='sound_event' direction='in'/>
          <arg type='a{sv}' name='options' direction='in'/>
          <arg type='s' name='uuid' direction='out'/>
        </method>
        <method name='UpdateProperties'>
          <arg type='s' name='uuid' direction='in'/>
          <arg type='i' name='transition_time_ms' direction='in'/>
          <arg type='a{sv}' name='options' direction='in'/>
        </method>
        <method name='StopSound'>
          <arg type='s' name='uuid' direction='in'/>
        </method>
        <method name='TerminateSound'>
          <arg type='s' name='uuid' direction='in'/>
        </method>
      </interface>
    </node>
    """

    def __init__(self, metadata):
        super().__init__(application_id=self._DBUS_NAME,
                         flags=Gio.ApplicationFlags.IS_SERVICE)
        self.logger = Logger(ServerFormatter, self)
        self._dbus_id = None
        self.metadata = metadata
        self._countdown_id = None
        self.registry = Registry()

    def get_sound(self, uuid=None, sound_event_id=None, bus_name=None):
        """
        Gets an existing sound given its UUID or event id and bus name.

        Optional Arguments:
            uuid (str): The sound uuid or the sound to look up.
            sound_event_id (str): The sound event id of the sound to look up.
                                  If specified, bus_name argument should be
                                  also specified.
            bus_name (str): The bus name of the sound to look up.

        Returns:
            A sound object if found. Otherwise, None.

        Raises:
            AssertionError: If uuid or sound_event_id and bus_name were not
                            specified.
            UnknownSoundEventIDException: If the input sound_event_id is not
                                          in the registry metadata.
        """

        if uuid is None and sound_event_id is None:
            raise AssertionError(
                "uuid or sound_event_id argument not specified")
        if sound_event_id is not None and bus_name is None:
            raise AssertionError("bus_name argument should be specified")

        if uuid is not None:
            sound = self.registry.sounds.get(uuid)
            if sound is None:
                raise UnregisteredUUID(
                    f"No sound with UUID {uuid} exists in the registry.")
            return sound

        # Try to find if a non-overlapping sound already existed.
        if sound_event_id not in self.metadata:
            self.logger.info("This sound event id does not exist.",
                             sound_event_id=sound_event_id)
            raise UnknownSoundEventIDException("sound event with id %s does "
                                               "not exist" % sound_event_id)

        overlap_behavior = \
            self.metadata[sound_event_id].get("overlap-behavior", "overlap")
        if overlap_behavior == "overlap":
            return None

        uuids = self.registry.sound_events.get_uuids(sound_event_id, bus_name)
        assert len(uuids) <= 1
        if len(uuids) == 0:
            return None
        uuid = next(iter(uuids))

        return self.get_sound(uuid=uuid)

    def refcount(self, sound):
        """
        Gives the number of references for the given `sound`.

        Input sounds are expected to be in the registry.

        Args:
            sound: A sound object.
        Raises:
            AssertionError: The sound is not in the registry.

        Returns:
            int: The number of references for the input `sound`.
        """
        if sound.uuid not in self.registry.refcount:
            raise AssertionError("Cannot get the number of references "
                                 "for a sound that is not in the registry.")
        return self.registry.refcount[sound.uuid]

    def ref(self, sound):
        if sound.uuid not in self.registry.refcount:
            self.registry.refcount[sound.uuid] = 0
        self.registry.refcount[sound.uuid] += 1
        refcount = self.registry.refcount[sound.uuid]
        self.logger.debug("Reference. Refcount: %d", refcount,
                          bus_name=sound.bus_name,
                          sound_event_id=sound.sound_event_id,
                          uuid=sound.uuid)

    def unref(self, sound, clear_all=False):
        try:
            refcount = self.refcount(sound)
        except AssertionError as ex:
            self.logger.error("Cannot unref this sound: %s", ex,
                              bus_name=sound.bus_name,
                              sound_event_id=sound.sound_event_id,
                              uuid=sound.uuid)
            return

        assert sound.uuid in self.registry.refcount
        assert refcount >= 0

        if refcount == 0:
            self.logger.warning("Cannot decrease refcount for this sound "
                                "because it's already 0.",
                                bus_name=sound.bus_name,
                                sound_event_id=sound.sound_event_id,
                                uuid=sound.uuid)
            return

        count = 1 if not clear_all else refcount
        self.registry.refcount[sound.uuid] -= count
        self.logger.debug("Unreference. Refcount: %d",
                          self.registry.refcount[sound.uuid],
                          bus_name=sound.bus_name,
                          sound_event_id=sound.sound_event_id,
                          uuid=sound.uuid)
        if self.registry.refcount[sound.uuid] == 0:
            # Only stop the sound if the last bus name (application) referring
            # to it has been disconnected (closed). The stop method will,
            # indirectly, take care for deleting
            # self.registry.refcount[sound.uuid].
            sound.stop()

    def do_dbus_register(self, connection, path):
        Gio.Application.do_dbus_register(self, connection, path)
        info = Gio.DBusNodeInfo.new_for_xml(self._DBUS_XML)
        self._dbus_id = connection.register_object(path,
                                                   info.interfaces[0],
                                                   self.__method_called_cb)
        return True

    def do_dbus_unregister(self, connection, path):
        Gio.Application.do_dbus_unregister(self, connection, path)
        if not self._dbus_id:
            return
        connection.unregister_object(self._dbus_id)
        self._dbus_id = None

    def cancel_countdown(self):
        if self._countdown_id:
            self.release()
            GLib.Source.remove(self._countdown_id)
            self._countdown_id = None
            self.logger.info('Timeout cancelled')

    def ensure_release_countdown(self):
        def release():
            self._countdown_id = None
            self.release()
            return GLib.SOURCE_REMOVE

        self.cancel_countdown()
        self.hold()
        self.logger.info('All sounds done; starting timeout of {} '
                         'seconds'.format(self._TIMEOUT_S))
        self._countdown_id = GLib.timeout_add_seconds(
            self._TIMEOUT_S, release, priority=GLib.PRIORITY_LOW)

    def new_sound(self, sound_klass, *args, **kwargs):
        self.cancel_countdown()
        self.hold()
        return sound_klass(*args, **kwargs)

    def _play_sound(self, sound):
        sound_to_pause = self.registry.add_sound(sound)
        self.watch_sound_bus_name(sound)
        self.ref(sound)
        if sound_to_pause is not None:
            sound_to_pause.pause_with_fade_out()
        sound.play()
        return sound

    def play_sound(self, sound_event_id, connection, sender, path, iface,
                   invocation, options=None):
        try:
            self.ensure_not_too_many_sounds(sound_event_id)
            sound = self.get_sound(sound_event_id=sound_event_id,
                                   bus_name=sender)
            if sound is not None:
                self.try_overlap_behaviour(sound)
            else:
                sound = self.new_sound(Sound, self, sender, sound_event_id,
                                       metadata_extras=options)
            self._play_sound(sound)
            invocation.return_value(GLib.Variant("(s)", (sound.uuid, )))
        except UnknownSoundEventIDException as ex:
            invocation.return_dbus_error(ex.INTERFACE, str(ex))
        except TooManySoundsException:
            invocation.return_value(GLib.Variant("(s)", ("", )))

    def ensure_not_too_many_sounds(self, sound_event_id):
        # Use before creating a sound.
        if not self.registry.sound_events.has_sound_event_id(sound_event_id):
            n_instances = 0
        else:
            n_instances = \
                len(self.registry.sound_events.get_uuids(sound_event_id))
        if n_instances >= self._MAX_SIMULTANEOUS_SOUNDS:
            self.logger.info("Sound is already playing %d times, ignoring.",
                             self._MAX_SIMULTANEOUS_SOUNDS,
                             sound_event_id=sound_event_id)
            raise TooManySoundsException

    def watch_sound_bus_name(self, sound):
        """
        Watches a sound bus name for the given sound..

        If a watcher already exists no bus name watcher will be created.

        Args:
            sound (Sound): A sound object
        """
        if sound.bus_name not in self.registry.watcher_by_bus_name:
            watcher_id = Gio.bus_watch_name(Gio.BusType.SESSION,
                                            sound.bus_name,
                                            Gio.DBusProxyFlags.NONE,
                                            None,
                                            self._bus_name_disconnect_cb)

            # Tracks a sound UUID called by its respective DBus names.
            uuids = set()
            self.registry.watcher_by_bus_name[sound.bus_name] = \
                DBusWatcher(watcher_id, uuids)
        self.registry.watcher_by_bus_name[sound.bus_name].uuids.add(sound.uuid)

    def _bus_name_disconnect_cb(self, unused_connection, bus_name):
        # When a dbus name dissappears (for example, when an application that
        # requested to play a sound is killed/colsed), all the sounds created
        # due to this application will be stopped.
        if bus_name not in self.registry.watcher_by_bus_name:
            return
        for uuid_ in self.registry.watcher_by_bus_name[bus_name].uuids:
            try:
                sound = self.get_sound(uuid_)
            except UnregisteredUUID as ex:
                self.logger.critical("An error ocurred when trying to release "
                                     "a sound with this uuid: %s. Skipping.",
                                     ex, uuid=uuid_)
                continue
            self.unref(sound, clear_all=True)
        # Remove the watcher.
        watcher_id = self.registry.watcher_by_bus_name[bus_name].watcher_id
        Gio.bus_unwatch_name(watcher_id)
        del self.registry.watcher_by_bus_name[bus_name]

    def try_overlap_behaviour(self, sound):
        overlap_behavior = self.metadata[sound.sound_event_id].get(
            "overlap-behavior", "overlap")
        if overlap_behavior == "restart":
            # This behavior indicates to restart the sound.
            sound.reset()
        elif overlap_behavior == "ignore":
            # If a sound is already playing, then ignore the new one.
            pass

    def terminate_sound_for_sender(self, uuid_or_event_id, connection, sender,
                                   invocation, term_sound=False):
        """
        Decreases the reference count of a sound for the given `sender`.

        Args:
            uuid (str): The sound uuid or the sound event id to stop playing.
            connection (Gio.DBusConnection): The current connection.
            sender (str): The unique bus name of the sender (starts with ':').
            invocation (Gio.DBusMethodInvocation): Used to handle
                                                   error or results.
        Optional keyword arguments:
            term_sound (bool): Defaults to False, which means to decrease the
                               refcount by 1. If set to True, then the refcount
                               is set to 0.
        """
        sounds_to_stop = []
        try:
            sound = self.get_sound(uuid_or_event_id)
            sounds_to_stop = [sound]
        except UnregisteredUUID:
            event_id_in_registry = \
                self.registry.sound_events.has_sound_event_id(uuid_or_event_id)
            if not event_id_in_registry:
                self.logger.info("Sound with UUID or event id '%s' was "
                                 "supposed to be stopped, but did not exist.",
                                 uuid_or_event_id)
            else:
                def uuids_to_sounds(uuids, sound_event_id):
                    for uuid in uuids:
                        try:
                            sound = self.get_sound(uuid)
                        except UnregisteredUUID as ex:
                            self.logger.critical(
                                "Sound with this UUID cannot be stopped. "
                                "Skipping, because of an error: %s", ex,
                                uuid=uuid, sound_event_id=sound_event_id)
                            continue
                        yield sound
                    else:
                        return []

                sound_event_id = uuid_or_event_id
                sound_events = self.registry.sound_events
                bus_name_uuids = sound_events.get_uuids(sound_event_id, sender)
                sounds_to_stop = uuids_to_sounds(bus_name_uuids,
                                                 sound_event_id)

        for sound in sounds_to_stop:
            uuid_in_refcount_registry = sound.uuid in self.registry.refcount
            if not uuid_in_refcount_registry or sender != sound.bus_name:
                self.logger.info("Sound with this UUID cannot be stopped. It "
                                 "was supposed to be refcounted by "
                                 "the bus name %s but it wasn\'t. Skipping.",
                                 sender, uuid=sound.uuid)
                continue
            self.unref_on_stop(sound, term_sound)
        invocation.return_value(None)

    def unref_on_stop(self, sound, term_sound=False):
        self.unref(sound, clear_all=term_sound)

    def update_properties(self, uuid_, transition_time_ms, options, connection,
                          sender, path, iface, invocation):

        try:
            sound = self.get_sound(uuid_)
            sound.update_properties(transition_time_ms, options)
        except UnregisteredUUID:
            self.logger.info("Properties of sound {} was supposed to be "
                             "updated, but did not exist".format(uuid_))
        invocation.return_value(None)

    def __method_called_cb(self, connection, sender, path, iface,
                           method, params, invocation):
        if method == "PlaySound":
            self.play_sound(params[0], connection, sender, path, iface,
                            invocation)
        if method == "PlayFull":
            self.play_sound(params[0], connection, sender, path,
                            iface, invocation, params[1])
        elif method == 'StopSound':
            self.terminate_sound_for_sender(params[0], connection, sender,
                                            invocation)
        elif method == 'TerminateSound':
            self.terminate_sound_for_sender(params[0], connection, sender,
                                            invocation, term_sound=True)
        elif method == "UpdateProperties":
            self.update_properties(params[0], params[1], params[2], connection,
                                   sender, path, iface, invocation)
        else:
            invocation.return_error_literal(
                Gio.dbus_error_quark(), Gio.DBusError.UNKNOWN_METHOD,
                "Method '%s' not available" % method)

    def sound_released_cb(self, sound):
        # This method is only called when a sound naturally reaches
        # end-of-stream or when an application ordered to stop the sound. In
        # both cases this means to delete the references to that sound UUID.
        self.logger.debug(
            "Freeing structures because end-of-stream was reached.",
            bus_name=sound.bus_name,
            sound_event_id=sound.sound_event_id,
            uuid=sound.uuid
        )
        self.__free_registry_with_countdown(sound)

    def sound_error_cb(self, sound, error, debug):
        # This method is only called when the sound fails or when an
        # application ordered to stop the sound. In both cases this means to
        # delete the references to that sound UUID.
        self.logger.error("Freeing structures because of a GStreamer error. "
                          "%s: %s", error.message, debug,
                          sound_event_id=sound.sound_event_id,
                          uuid=sound.uuid)

        if sound.uuid not in self.registry.sounds:
            return
        self.__free_registry_with_countdown(sound)

    def __free_registry(self, sound):
        sound_to_resume = self.registry.remove_sound(sound)
        if sound_to_resume is not None:
            sound_to_resume.play()

    def __free_registry_with_countdown(self, sound):
        self.__free_registry(sound)
        if not self.registry.sounds:
            self.ensure_release_countdown()
        self.release()
