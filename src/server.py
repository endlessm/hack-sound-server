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


class Server(Gio.Application):
    _TIMEOUT_S = 10
    _MAX_SIMULTANEOUS_SOUNDS = 5
    OVERLAP_BEHAVIOR_CHOICES = ("overlap", "restart", "ignore")
    _DBUS_NAME = "com.endlessm.HackSoundServer"
    _DBUS_UNKNOWN_SOUND_EVENT_ID = \
        "com.endlessm.HackSoundServer.UnknownSoundEventID"
    _DBUS_UNKNOWN_OVERLAP_BEHAVIOR = \
        "com.endlessm.HackSoundServer.UnknownOverlapBehavior"
    _DBUS_XML = """
    <node>
      <interface name='com.endlessm.HackSoundServer'>
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

    def play(self, uuid_):
        sound = self.registry.sounds[uuid_]
        if sound.type_ == "bg":
            # The following rule applies for 'bg' sounds: whenever a new 'bg'
            # sound starts to play back, if any previous 'bg' sound was already
            # playing, then pause that previous sound and play the new one. If
            # this last sound finishes, then the last sound is resumed.
            overlap_behavior =\
                self.metadata[sound.sound_event_id].get("overlap-behavior",
                                                        "overlap")

            # Reorder the list of background sounds if necessary.
            if len(self.registry.background_sounds) > 0:
                # Sounds with overlap behavior 'ignore' or 'restart' are unique
                # so just need to move the incoming sound to the head/top of
                # the list/stack.
                if (overlap_behavior in ("ignore", "restart") and
                        sound in self.registry.background_sounds):
                    last_sound = self.registry.background_sounds[-1]
                    if last_sound != sound:
                        last_sound.pause_with_fade_out()
                    # Reorder.
                    self.registry.background_sounds.remove(sound)
                    self.registry.background_sounds.append(sound)

            if len(self.registry.background_sounds) == 0:
                self.registry.background_sounds.append(sound)
            elif self.registry.background_sounds[-1] != sound:
                self.registry.background_sounds[-1].pause_with_fade_out()
                self.registry.background_sounds.append(sound)
        sound.play()

    def get_sound(self, uuid_):
        try:
            return self.registry.sounds[uuid_]
        except KeyError:
            self.logger.critical("This uuid is not assigned to any sound.",
                                 uuid=uuid_)

    def refcount(self, sound):
        """
        Gives the number of references for the given `sound`.

        Input sounds are expected to be in the registry.

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
        self.registry.refcount[sound.uuid] += 1
        refcount = self.registry.refcount[sound.uuid]
        self.logger.debug("Reference. Refcount: %d", refcount,
                          bus_name=sound.uuid,
                          sound_event_id=sound.sound_event_id,
                          uuid=sound.uuid)
        self.play(sound.uuid)

    def unref(self, sound, count=1):
        if sound.uuid not in self.registry.refcount:
            self.logger.warning("This uuid is not registered in the refcount "
                                "registry.", uuid=sound.uuid)
            return
        if self.refcount(sound) == 0:
            self.logger.warning("Cannot decrease refcount for this sound "
                                "because it's already 0.",
                                bus_name=sound.bus_name,
                                sound_event_id=sound.sound_event_id,
                                uuid=sound.uuid)
            return
        self.registry.refcount[sound.uuid] -= count
        self.logger.debug("Unreference. Refcount: %d",
                          self.registry.refcount[sound.uuid],
                          bus_name=sound.bus_name,
                          sound_event_id=sound.sound_event_id,
                          uuid=sound.uuid)
        if self.refcount(sound) == 0:
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
        self.cancel_countdown()
        self.hold()
        self.logger.info('All sounds done; starting timeout of {} '
                         'seconds'.format(self._TIMEOUT_S))
        self._countdown_id = GLib.timeout_add_seconds(
            self._TIMEOUT_S, self.release, priority=GLib.PRIORITY_LOW)

    def play_sound(self, sound_event_id, connection, sender, path, iface,
                   invocation, options=None):
        if sound_event_id not in self.metadata:
            self.logger.info("This sound event id does not exist.",
                             sound_event_id=sound_event_id)
            invocation.return_dbus_error(
                self._DBUS_UNKNOWN_SOUND_EVENT_ID,
                "sound event with id %s does not exist" % sound_event_id)
            return

        overlap_behavior = \
            self.metadata[sound_event_id].get("overlap-behavior", "overlap")
        if overlap_behavior not in self.OVERLAP_BEHAVIOR_CHOICES:
            msg = "'%s' is not a valid option for 'overlap-behavior'."
            self.logger.info(msg, overlap_behavior,
                             sound_event_id=sound_event_id)
            return invocation.return_dbus_error(
                self._DBUS_UNKNOWN_OVERLAP_BEHAVIOR,
                msg % overlap_behavior)
        if not self.registry.uuids_by_event_id.get(sound_event_id):
            self.registry.uuids_by_event_id[sound_event_id] = set()

        uuid_ = self.do_overlap_behaviour(sound_event_id, overlap_behavior)
        if uuid_ is not None:
            sound = self.get_sound(uuid_)
            self.watch_bus_name(sound)

        if uuid_ is None:
            if self.check_too_many_sounds(sound_event_id, overlap_behavior):
                invocation.return_value(GLib.Variant("(s)", ("", )))
                return
            self.cancel_countdown()
            self.hold()

            sound = Sound(self, sender, sound_event_id, options)
            uuid_ = sound.uuid
            self.registry.sounds[uuid_] = sound

            # Insert the uuid in the dictionary organized by sound event id.
            self.registry.uuids_by_event_id[sound_event_id].add(uuid_)
            # Plays the sound.
            self.watch_bus_name(sound)

        return invocation.return_value(GLib.Variant('(s)', (uuid_, )))

    def check_too_many_sounds(self, sound_event_id, overlap_behavior):
        n_instances = len(self.registry.uuids_by_event_id[sound_event_id])
        if n_instances <= self._MAX_SIMULTANEOUS_SOUNDS:
            return False
        self.logger.info("Sound is already playing %d times, ignoring.",
                         self._MAX_SIMULTANEOUS_SOUNDS,
                         sound_event_id=sound_event_id)
        return True

    def watch_bus_name(self, sound):
        # Tracks a sound UUID called by its respective DBus names.
        if sound.bus_name not in self.registry.watcher_by_bus_name:
            watcher_id = Gio.bus_watch_name(Gio.BusType.SESSION,
                                            sound.bus_name,
                                            Gio.DBusProxyFlags.NONE,
                                            None,
                                            self._bus_name_disconnect_cb)
            self.registry.watcher_by_bus_name[sound.bus_name] = \
                DBusWatcher(watcher_id, set())
        if sound.uuid not in self.registry.refcount:
            self.registry.refcount[sound.uuid] = 0
        self.ref(sound)
        self.registry.watcher_by_bus_name[sound.bus_name].uuids.add(sound.uuid)

    def _bus_name_disconnect_cb(self, unused_connection, bus_name):
        # When a dbus name dissappears (for example, when an application that
        # requested to play a sound is killed/colsed), all the sounds created
        # due to this application will be stopped.
        if bus_name not in self.registry.watcher_by_bus_name:
            return
        for uuid_ in self.registry.watcher_by_bus_name[bus_name].uuids:
            sound = self.get_sound(uuid_)
            self.unref(sound, count=self.refcount(sound))
        # Remove the watcher.
        watcher_id = self.registry.watcher_by_bus_name[bus_name].watcher_id
        Gio.bus_unwatch_name(watcher_id)
        del self.registry.watcher_by_bus_name[bus_name]

    def do_overlap_behaviour(self, sound_event_id, overlap_behavior):
        if overlap_behavior == "overlap":
            return None
        uuids = self.registry.uuids_by_event_id.get(sound_event_id)
        assert len(uuids) <= 1
        if len(uuids) == 0:
            return None
        uuid_ = next(iter(uuids))

        if overlap_behavior == "restart":
            # This behavior indicates to restart the sound.
            self.get_sound(uuid_).reset()
            return uuid_
        elif overlap_behavior == "ignore":
            # If a sound is already playing, then ignore the new one.
            return uuid_
        return None

    def terminate_sound_for_sender(self, uuid_, connection, sender, invocation,
                                   term_sound=False):
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
        assert not (uuid_ in self.registry.sounds and
                    uuid_ in self.registry.uuids_by_event_id)
        # xor: With the exception that the case of both cases being True will
        # never happen because we never define an UUID in the metadata file.
        if not ((uuid_ not in self.registry.sounds) ^
                (uuid_ not in self.registry.uuids_by_event_id)):
            self.logger.info("Sound {} was supposed to be stopped, but did "
                             "not exist".format(uuid_))
        elif (uuid_ in self.registry.sounds and
              (uuid_ not in self.registry.refcount or
               sender != self.get_sound(uuid_).bus_name)):
            self.logger.info("Sound {} was supposed to be "
                             "refcounted by the bus, name \'{}\' but "
                             "it wasn\'t.".format(uuid_, sender))
        else:
            if uuid_ in self.registry.sounds:
                # Stop by UUID.
                self.unref_on_stop(self.get_sound(uuid_), term_sound)
            elif uuid_ in self.registry.uuids_by_event_id:
                # Stop by sound event id.
                sound_event_id = uuid_
                for uuid_ in self.registry.uuids_by_event_id[sound_event_id]:
                    sound = self.get_sound(uuid_)
                    # Don't unreference sounds instantiated from other apps.
                    if sound.bus_name != sender:
                        continue
                    self.unref_on_stop(self.get_sound(uuid_), term_sound)
        invocation.return_value(None)

    def unref_on_stop(self, sound, term_sound=False):
        n_unref = 1 if not term_sound else self.refcount(sound.uuid)
        self.unref(sound, n_unref)

    def update_properties(self, uuid_, transition_time_ms, options, connection,
                          sender, path, iface, invocation):
        if uuid_ not in self.registry.sounds:
            self.logger.info("Properties of sound {} was supposed to be "
                             "updated, but did not exist".format(uuid_))
        else:
            sound = self.get_sound(uuid_)
            sound.update_properties(transition_time_ms, options)
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

    def _resume_last_bg_sound(self, uuid_):
        sound = self.get_sound(uuid_)
        if sound not in self.registry.background_sounds:
            return
        assert sound.type_ == "bg"

        try:
            self.registry.background_sounds.remove(sound)
            sound.release()
        except ValueError:
            self.logger.warning(
                "Sound %s sound was supposed to be in the list of "
                "background sounds, but this isn't", uuid_)

        if len(self.registry.background_sounds) > 0:
            last_sound = self.registry.background_sounds[-1]
            self.logger.info("Resuming sound.",
                             sound_event_id=last_sound.sound_event_id,
                             uuid=last_sound.uuid)
            if self.refcount(last_sound) == 0:
                self.logger.info("Cannot resume this sound because its "
                                 "owning apps have dissapeared from the bus.",
                                 sound_event_id=last_sound.sound_event_id,
                                 uuid=last_sound.uuid)
                return
            last_sound.play()

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
        self._resume_last_bg_sound(sound.uuid)
        del self.registry.sounds[sound.uuid]
        if sound.sound_event_id in self.registry.uuids_by_event_id:
            self.registry.uuids_by_event_id[sound.sound_event_id].remove(
                sound.uuid)
            if len(self.registry.uuids_by_event_id[sound.sound_event_id]) == 0:
                del self.registry.uuids_by_event_id[sound.sound_event_id]
        if sound.bus_name in self.registry.watcher_by_bus_name:
            uuids = self.registry.watcher_by_bus_name[sound.bus_name].uuids
            if sound.uuid in uuids:
                uuids.remove(sound.uuid)
        del self.registry.refcount[sound.uuid]

    def __free_registry_with_countdown(self, sound):
        self.__free_registry(sound)
        if not self.registry.sounds:
            self.ensure_release_countdown()
        self.release()
