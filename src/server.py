import gi
import random
import uuid
gi.require_version('GLib', '2.0')  # noqa
gi.require_version('Gst', '1.0')   # noqa
gi.require_version('GstController', '1.0')  # noqa
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gst
from gi.repository import GstController
from collections import namedtuple
from hack_sound_server.utils.loggable import Logger
from hack_sound_server.utils.loggable import PlayerFormatter
from hack_sound_server.utils.loggable import ServerFormatter


class HackSoundPlayer(GObject.Object):
    _DEFAULT_VOLUME = 1.0
    _DEFAULT_PITCH = 1.0
    _DEFAULT_RATE = 1.0
    _DEFAULT_FADE_IN_MS = 1000
    _DEFAULT_FADE_OUT_MS = 1000

    __gsignals__ = {
        'released': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'error': (GObject.SignalFlags.RUN_FIRST, None, (GLib.Error, str))
    }

    def __init__(self, bus_name, sound_event_id, uuid_, metadata,
                 metadata_extras=None):
        super().__init__()
        self.logger = Logger(PlayerFormatter, self)
        # The following attributes (bus_name, sound_event_id and uuid) are used
        # internally by the logger to format the log messages.
        self.bus_name = bus_name
        self.sound_event_id = sound_event_id
        self.uuid = uuid_

        self.metadata = metadata
        self.metadata_extras = metadata_extras or {}
        self.pipeline = self._build_pipeline()
        self._stop_loop = False
        self._n_loop = 0
        self._is_initial_seek = False
        self._pending_state_change = None
        self._releasing = False
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.__bus_message_cb)

    def release(self):
        # Otherwise, GStreamer complains with a WARNING indicating that
        # g_idle_add should be used.
        self.logger.debug("Releasing.")
        self._releasing = True
        GLib.idle_add(self._release)

    def _release(self):
        if self.pipeline is None:
            return
        self.pipeline.set_state(Gst.State.NULL)
        self.pipeline.get_bus().remove_signal_watch()
        self.pipeline = None
        self.emit("released")

    def get_state(self):
        return self.pipeline.get_state(timeout=0).state

    def play(self, fades_in=True):
        self._play(fades_in)

    def pause_with_fade_out(self):
        self.logger.info("Pausing.")
        if self._releasing:
            self.logger.info("Cannot pause because being released.")
            return
        if self._stop_loop:
            self.logger.info("Cannot pause because being stopped.")
            return

        volume_elem = self.pipeline.get_by_name("volume")
        if volume_elem.props.volume == 0:
            self.pipeline.set_state(Gst.State.PAUSED)
            self._pending_state_change = None
        else:
            self._pending_state_change = Gst.State.PAUSED
            # The element will be set to PAUSED state when volume reaches 0.
            try:
                self._add_fade_out(volume_elem, self.fade_out)
            except (ValueError, AssertionError):
                self.logger.warning("Fade out effect could not be applied. "
                                    "Pausing.")
                self.pipeline.set_state(Gst.State.PAUSED)
                self._pending_state_change = None

    def _play(self, fades_in):
        self.logger.info("Playing.")
        if self._stop_loop:
            self.logger.info("Cannot play because stopping with fade out.")
            return
        if self._releasing:
            self.logger.info("Cannot play because being released.")
            return
        self.pipeline.set_state(Gst.State.PLAYING)
        if fades_in:
            self._add_fade_in(self.fade_in, self.volume)
        return GLib.SOURCE_REMOVE

    def stop(self):
        if not self.loop:
            # Just stop immediately
            self.release()
            return

        if self.fade_out == 0 or self.get_state() == Gst.State.PAUSED:
            self._stop_loop = True
            self.release()
            return

        volume_elem = self.pipeline.get_by_name('volume')
        # Stop at the end of the current loop
        self._stop_loop = True
        try:
            self._add_fade_out(volume_elem, self.fade_out)
        except (ValueError, AssertionError) as ex:
            self.logger.error(ex)
            self.logger.warning("Fade out effect could not be applied. Stop.")

    def reset(self):
        self.seek(0.0)
        # Reset keyframes.
        self._fade_control.unset_all()
        self._rate_control.unset_all()
        self._add_fade_in(self.fade_in, self.volume)

    def update_properties(self, transition_time_ms, options):
        if "volume" in options:
            self._update_property_with_keyframes("volume", self._fade_control,
                                                 transition_time_ms, "volume",
                                                 options["volume"])
        if "rate" in options:
            self._update_property_with_keyframes("pitch", self._rate_control,
                                                 transition_time_ms, "rate",
                                                 options["rate"])

    def _update_property_with_keyframes(self, element_name, control,
                                        transition_time_ms, prop_name,
                                        prop_value):
        element = self.pipeline.get_by_name(element_name)
        if element is None:
            return
        current_value = element.get_property(prop_name)
        current_time = self.get_current_position()
        time_end = current_time + transition_time_ms * Gst.MSECOND
        self._add_keyframe_pair(control, current_time, current_value,
                                time_end, prop_value, consider_duration=False,
                                consider_delay=False)

    def seek(self, position=None, flags=None):
        if flags is None:
            flags = Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT
        if position is None:
            self.pipeline.seek(self._DEFAULT_RATE, Gst.Format.TIME, flags,
                               Gst.SeekType.NONE, -1, Gst.SeekType.NONE, -1)
        else:
            self.pipeline.seek_simple(Gst.Format.TIME, flags, position)

    def get_current_position(self):
        ok, current_time = self.pipeline.query_position(Gst.Format.TIME)
        if not ok:
            raise ValueError('error querying position')
        return current_time

    def get_duration(self):
        ok, duration = self.pipeline.query_duration(Gst.Format.TIME)
        if not ok:
            raise ValueError('error querying duration')
        return duration

    @property
    def loop(self):
        return "loop" in self.metadata and self.metadata["loop"]

    @property
    def volume(self):
        volume = self._get_multipliable_prop("volume")
        if volume is None:
            volume = self._DEFAULT_VOLUME
        return volume

    @property
    def pitch(self):
        """
        Changes pitch while keeping the tempo.
        """
        return self._get_multipliable_prop("pitch")

    @property
    def rate(self):
        """
        Changes tempo and pitch.
        """
        if "rate" in self.metadata:
            return self.metadata["rate"]
        return None

    @property
    def fade_in(self):
        return self.metadata.get("fade-in",
                                 self._DEFAULT_FADE_IN_MS if self.loop else 0)

    @property
    def fade_out(self):
        pipeline_fade_out = 0
        if self.loop:
            pipeline_fade_out = self._DEFAULT_FADE_OUT_MS
        metadata_fade_out = self.metadata.get("fade-out")
        if metadata_fade_out is not None:
            pipeline_fade_out = metadata_fade_out
        return pipeline_fade_out

    @property
    def delay(self):
        if "delay" in self.metadata:
            return self.metadata["delay"]
        return None

    @property
    def sound_location(self):
        return random.choice(self.metadata["sound-files"])

    @property
    def type_(self):
        type_ = self.metadata.get("type", "sfx")
        if type_ not in ("sfx", "bg"):
            return "sfx"
        return type_

    def _add_keyframe_pair(self, control, time_start_ns, value_start,
                           time_end_ns, value_end, consider_duration=True,
                           consider_delay=False):
        control.unset_all()
        if not self._add_keyframe(control, time_start_ns, value_start,
                                  consider_delay):
            raise ValueError('bad start time')
        # Rather than deal with the case where we have to split the keyframes
        # over the sound's loop; if the end keyframe is greater than the sound
        # file duration, we just apply the end keyframe to the end.
        if consider_duration:
            duration = self.get_duration()
            time_end_ns = min(time_end_ns, duration * (self._n_loop + 1))
        if not self._add_keyframe(control, time_end_ns, value_end,
                                  consider_delay):
            raise ValueError('bad end time')

    def _add_keyframe(self, control, time_ns, value, consider_delay=False):
        if consider_delay:
            delay = 0 if not self.delay else self.delay * Gst.MSECOND
            time_ns += delay
        return control.set(time_ns, value)

    def _add_fade_in(self, time_ms_end, volume_end):
        self._add_keyframe_pair(self._fade_control, 0, 0,
                                time_ms_end * Gst.MSECOND, volume_end, False,
                                consider_delay=True)

    def _add_fade_out(self, element, time_ms):
        current_volume = element.props.volume
        current_time = self.get_current_position()
        if self.delay and current_time < self.delay * Gst.MSECOND:
            self.logger.warning("Cannot fade out while in an in-progress "
                                "delay.")
            raise AssertionError
        self._add_keyframe_pair(self._fade_control,
                                current_time, current_volume,
                                current_time + time_ms * Gst.MSECOND, 0,
                                consider_delay=False)

    def _get_multipliable_prop(self, prop_name):
        value = self.metadata.get(prop_name, None)
        if prop_name in self.metadata_extras:
            if value is None:
                value = self.metadata_extras[prop_name]
            else:
                value *= self.metadata_extras[prop_name]
        return value

    def _create_control(self, element, prop):
        fade_control = GstController.InterpolationControlSource(
            mode=GstController.InterpolationMode.LINEAR)
        binding = GstController.DirectControlBinding.new_absolute(
            element, prop, fade_control)
        if not element.add_control_binding(binding):
            raise ValueError('bad control binding')
        return fade_control

    def _build_pipeline(self):
        pitch_args = (self.pitch or self._DEFAULT_PITCH,
                      self.rate or self._DEFAULT_RATE)
        elements = [
            "filesrc name=src location=\"{}\"".format(self.sound_location),
            "decodebin name=decoder",
            "identity single-segment=true",
            "audioconvert",
            "pitch name=pitch pitch={} rate={}".format(*pitch_args),
            "volume name=volume volume={}".format(self.volume),
            "autoaudiosink"
        ]
        spipeline = " ! ".join(elements)
        pipeline = Gst.parse_launch(spipeline)

        volume_elem = pipeline.get_by_name("volume")
        volume_elem.connect("notify::volume", self.__volume_cb)
        assert volume_elem is not None
        self._fade_control = self._create_control(volume_elem, "volume")

        pitch_elem = pipeline.get_by_name("pitch")
        assert pitch_elem is not None
        self._rate_control = self._create_control(pitch_elem, "rate")

        decoder_elem = pipeline.get_by_name("decoder")
        assert decoder_elem is not None
        decoder_elem.connect("pad-added", self.__pad_added_cb)

        return pipeline

    def __pad_added_cb(self, unused_decoder, pad):
        if self.pipeline is None:
            return
        if not self.delay:
            return
        pad.set_offset(self.delay * Gst.MSECOND)

    def __volume_cb(self, volume_element, unused_volume):
        # In case of fade-out effects, release the pipeline as soon volume
        # reaches 0.
        if volume_element.props.volume == 0:
            if self._pending_state_change is not None:
                self.pipeline.set_state(self._pending_state_change)
                self._pending_state_change = None
            if self._stop_loop:
                self.release()

    def __bus_message_cb(self, unused_bus, message):
        if message.type == Gst.MessageType.EOS:
            self.release()
        elif message.type == Gst.MessageType.SEGMENT_DONE:
            if message.src != self.pipeline:
                return
            if self.loop and not self._stop_loop:
                self._n_loop += 1
                self.seek(0.0, flags=Gst.SeekFlags.SEGMENT)
            else:
                self.release()
        elif message.type == Gst.MessageType.ASYNC_DONE:
            if message.src != self.pipeline:
                return
            if self.loop and not self._is_initial_seek:
                flags = Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT |\
                        Gst.SeekFlags.SEGMENT
                self.seek(0.0, flags=flags)
                self._is_initial_seek = True
        elif message.type == Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            self.logger.warning("Error from %s: %s (%s)", message.src, error,
                                debug)
            self.pipeline.set_state(Gst.State.NULL)
            self.emit("error", error, debug)
        elif message.type == Gst.MessageType.STATE_CHANGED:
            if message.src != self.pipeline:
                return
            st = message.get_structure()
            old_state = st.get_value("old-state")
            new_state = st.get_value("new-state")
            if (old_state == Gst.State.READY and new_state == Gst.State.PAUSED
                    and self._stop_loop):
                self.release()


DBusWatcher = namedtuple("DBusWatcher", ["watcher_id", "uuids"])


class HackSoundServer(Gio.Application):
    _TIMEOUT_S = 10
    _MAX_SIMULTANEOUS_SOUNDS = 5
    _OVERLAP_BEHAVIOR_CHOICES = ("overlap", "restart", "ignore")
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
        <signal name='Error'>
          <arg type='s' name='uuid'/>
          <arg type='s' name='error_message'/>
          <arg type='s' name='error_domain'/>
          <arg type='i' name='error_code'/>
          <arg type='s' name='debug'/>
        </signal>
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
        self.players = {}
        # COunts the references of a sound by UUID and by bus name.
        self._refcount = {}
        self._watcher_by_bus_name = {}
        # Only useful for sounds tagged with "overlap-behavior":
        self._uuid_by_event_id = {}
        self._background_players = []

    def play(self, uuid_, fades_in):
        player = self.players[uuid_]
        if player.type_ == "bg":
            # The following rule applies for 'bg' sounds: whenever a new 'bg'
            # sound starts to play back, if any previous 'bg' sound was already
            # playing, then pause that previous sound and play the new one. If
            # this last sound finishes, then the last sound is resumed.
            overlap_behavior =\
                self.metadata[player.sound_event_id].get("overlap-behavior",
                                                         "overlap")

            # Reorder the list of background players if necessary.
            if len(self._background_players) > 0:
                # Sounds with overlap behavior 'ignore' or 'restart' are unique
                # so just need to move the incoming player to the head/top of
                # the list/stack.
                if (overlap_behavior in ("ignore", "restart") and
                        player in self._background_players):
                    # This does not makes sense to fade in the sound if we are
                    # just ignoring the request.
                    fades_in = (overlap_behavior == "ignore" and
                                self._background_players[-1] != player)
                    if self._background_players[-1] != player:
                        self._background_players[-1].pause_with_fade_out()
                    # Reorder.
                    self._background_players.remove(player)
                    self._background_players.append(player)

            if len(self._background_players) == 0:
                self._background_players.append(player)
            elif self._background_players[-1] != player:
                self._background_players[-1].pause_with_fade_out()
                self._background_players.append(player)
        player.play(fades_in)

    def get_player(self, uuid_):
        try:
            return self.players[uuid_]
        except KeyError:
            self.logger.critical("This uuid is not assigned to any player.",
                                 uuid=uuid_)

    def refcount(self, uuid_, bus_name=None):
        if bus_name is None:
            refcount = 0
            for bus_name in self._refcount[uuid_]:
                refcount += self._refcount[uuid_][bus_name]
            return refcount
        return self._refcount[uuid_][bus_name]

    def ref(self, uuid_, bus_name):
        self._refcount[uuid_][bus_name] += 1
        refcount = self._refcount[uuid_][bus_name]
        self.logger.debug("Reference. Refcount: %d", refcount,
                          bus_name=bus_name,
                          sound_event_id=self.get_player(uuid_).sound_event_id,
                          uuid=uuid_)
        self.play(uuid_, fades_in=refcount == 1)

    def unref(self, uuid_, bus_name, count=1):
        if uuid_ not in self._refcount:
            self.logger.warning("This uuid is not registered in the refcount "
                                "registry.", uuid=uuid_)
            return
        if bus_name not in self._refcount[uuid_]:
            self.logger.warning("Bus name '{}' is not registered in the "
                                "refcount registry.".format(bus_name),
                                bus_name=bus_name)
            return
        if self._refcount[uuid_][bus_name] == 0:
            self.logger.warning("Cannot decrease refcount for bus name '{}'"
                                "because it's already 0.".format(bus_name),
                                uuid=uuid_)
            return
        self._refcount[uuid_][bus_name] -= count
        self.logger.debug("Unreference. Refcount: %d",
                          self._refcount[uuid_][bus_name], bus_name=bus_name,
                          sound_event_id=self.get_player(uuid_).sound_event_id,
                          uuid=uuid_)
        if self.refcount(uuid_) == 0:
            # Only stop the sound if the last bus name (application) referring
            # to it has been disconnected (closed). The stop method will,
            # indirectly, take care for deleting self._refcount[uuid_].
            self.get_player(uuid_).stop()

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

    def _cancel_countdown(self):
        if self._countdown_id:
            self.release()
            GLib.Source.remove(self._countdown_id)
            self._countdown_id = None
            self.logger.info('Timeout cancelled')

    def _ensure_release_countdown(self):
        self._cancel_countdown()
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
        if overlap_behavior not in self._OVERLAP_BEHAVIOR_CHOICES:
            msg = "'%s' is not a valid option for 'overlap-behavior'."
            self.logger.info(msg, overlap_behavior,
                             sound_event_id=sound_event_id)
            return invocation.return_dbus_error(
                self._DBUS_UNKNOWN_OVERLAP_BEHAVIOR,
                msg % overlap_behavior)
        if not self._uuid_by_event_id.get(sound_event_id):
            self._uuid_by_event_id[sound_event_id] = set()

        uuid_ = self._do_overlap_behaviour(sound_event_id, overlap_behavior)
        if uuid_ is not None:
            self._watch_bus_name(sender, uuid_)

        if uuid_ is None:
            self._cancel_countdown()
            self.hold()

            if self._check_too_many_sounds(invocation, sound_event_id,
                                           overlap_behavior):
                return

            uuid_ = str(uuid.uuid4())
            metadata = self.metadata[sound_event_id]
            self.players[uuid_] = HackSoundPlayer(sender, sound_event_id,
                                                  uuid_, metadata, options)
            # Insert the uuid in the dictionary organized by sound event id.
            self._uuid_by_event_id[sound_event_id].add(uuid_)

            self.players[uuid_].connect("released", self.__player_released_cb,
                                        sound_event_id, uuid_)
            self.players[uuid_].connect("error", self.__player_error_cb,
                                        sound_event_id, uuid_,
                                        connection, path, iface)
            # Plays the sound.
            self._watch_bus_name(sender, uuid_)

        return invocation.return_value(GLib.Variant('(s)', (uuid_, )))

    def _check_too_many_sounds(self, invocation, sound_event_id,
                               overlap_behavior):
        n_instances = len(self._uuid_by_event_id[sound_event_id])
        if n_instances <= self._MAX_SIMULTANEOUS_SOUNDS:
            return False
        self.logger.info("Sound is already playing %d times, ignoring.",
                         self._MAX_SIMULTANEOUS_SOUNDS,
                         sound_event_id=sound_event_id)
        invocation.return_value(GLib.Variant("(s)", ("", )))
        return True

    def _watch_bus_name(self, bus_name, uuid_):
        # Tracks a player UUID called by its respective DBus names.
        if bus_name not in self._watcher_by_bus_name:
            watcher_id = Gio.bus_watch_name(Gio.BusType.SESSION,
                                            bus_name,
                                            Gio.DBusProxyFlags.NONE,
                                            None,
                                            self._bus_name_disconnect_cb)
            self._watcher_by_bus_name[bus_name] = DBusWatcher(watcher_id,
                                                              set())
        if uuid_ not in self._refcount:
            self._refcount[uuid_] = {}
        if bus_name not in self._refcount[uuid_]:
            self._refcount[uuid_][bus_name] = 0
        self.ref(uuid_, bus_name)
        self._watcher_by_bus_name[bus_name].uuids.add(uuid_)

    def _bus_name_disconnect_cb(self, unused_connection, bus_name):
        # When a dbus name dissappears (for example, when an application that
        # requested to play a sound is killed/colsed), all the players created
        # due to this application will be stopped.
        if bus_name not in self._watcher_by_bus_name:
            return
        for uuid_ in self._watcher_by_bus_name[bus_name].uuids:
            self.unref(uuid_, bus_name, count=self._refcount[uuid_][bus_name])
        # Remove the watcher.
        Gio.bus_unwatch_name(self._watcher_by_bus_name[bus_name].watcher_id)
        del self._watcher_by_bus_name[bus_name]

    def _do_overlap_behaviour(self, sound_event_id, overlap_behavior):
        if overlap_behavior == "overlap":
            return None
        uuids = self._uuid_by_event_id.get(sound_event_id)
        assert len(uuids) <= 1
        if len(uuids) == 0:
            return None
        uuid_ = next(iter(uuids))

        if overlap_behavior == "restart":
            # This behavior indicates to restart the sound.
            self.get_player(uuid_).reset()
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
        assert not (uuid_ in self.players and uuid_ in self._uuid_by_event_id)
        # xor: With the exception that the case of both cases being True will
        # never happen because we never define an UUID in the metadata file.
        if not ((uuid_ not in self.players) ^
                (uuid_ not in self._uuid_by_event_id)):
            self.logger.info("Sound {} was supposed to be stopped, but did "
                             "not exist".format(uuid_))
        elif (uuid_ in self.players and (uuid_ not in self._refcount or
                                         sender not in self._refcount[uuid_])):
            self.logger.info("Sound {} was supposed to be "
                             "refcounted by the bus, name \'{}\' but "
                             "it wasn\'t.".format(uuid_, sender))
        else:
            if uuid_ in self.players:
                self._unref_on_stop(uuid_, sender, term_sound)
            elif uuid_ in self._uuid_by_event_id:
                sound_event_id = uuid_
                for uuid_ in self._uuid_by_event_id[sound_event_id]:
                    self._unref_on_stop(uuid_, sender, term_sound)
            invocation.return_value(None)

    def _unref_on_stop(self, uuid_, bus_name, term_sound=False):
        n_unref = 1 if not term_sound else self.refcount(uuid_, bus_name)
        self.unref(uuid_, bus_name, n_unref)

    def update_properties(self, uuid_, transition_time_ms, options, connection,
                          sender, path, iface, invocation):
        if uuid_ not in self.players:
            self.logger.info("Properties of sound {} was supposed to be "
                             "updated, but did not exist".format(uuid_))
        else:
            player = self.get_player(uuid_)
            player.update_properties(transition_time_ms, options)
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

    def _resume_last_bg_player(self, uuid_):
        player = self.get_player(uuid_)
        if player not in self._background_players:
            return
        assert player.type_ == "bg"

        try:
            self._background_players.remove(player)
            player.release()
        except ValueError:
            self.logger.warning(
                "Sound %s sound was supposed to be in the list of "
                "background sounds, but this isn't", uuid)

        if len(self._background_players) > 0:
            self._background_players[-1].play()

    def __player_released_cb(self, unused_player, sound_event_id, uuid_):
        # This method is only called when a sound naturally reaches
        # end-of-stream or when an application ordered to stop the sound. In
        # both cases this means to delete the references to that sound UUID.
        self.logger.debug(
            "Freeing structures because end-of-stream was reached.",
            bus_name=self.get_player(uuid_).bus_name,
            sound_event_id=self.get_player(uuid_).sound_event_id,
            uuid=uuid_
        )
        self._resume_last_bg_player(uuid_)
        del self.players[uuid_]
        if sound_event_id in self._uuid_by_event_id:
            self._uuid_by_event_id[sound_event_id].remove(uuid_)
            if len(self._uuid_by_event_id[sound_event_id]) == 0:
                del self._uuid_by_event_id[sound_event_id]
        for bus_name in self._refcount[uuid_]:
            if bus_name in self._watcher_by_bus_name:
                self._watcher_by_bus_name[bus_name].uuids.remove(uuid_)
        del self._refcount[uuid_]
        if not self.players:
            self._ensure_release_countdown()
        self.release()

    def __player_error_cb(self, player, error, debug, sound_event_id,
                          uuid_, connection, path, iface):
        # This method is only called when the player fails or when an
        # application ordered to stop the sound. In both cases this means to
        # delete the references to that sound UUID.
        data = (uuid_, error.message, error.domain, error.code, debug)
        vdata = GLib.Variant("(sssis)", data)
        if uuid_ in self.players:
            self.logger.debug(
                "Freeing structures because there was an error.",
                bus_name=self.get_player(uuid_).bus_name,
                sound_event_id=self.get_player(uuid_).sound_event_id,
                uuid=uuid_
            )
            self._resume_last_bg_player(uuid_)
            del self.players[uuid_]
            if sound_event_id in self._uuid_by_event_id:
                self._uuid_by_event_id[sound_event_id].remove(uuid_)
                if len(self._uuid_by_event_id[sound_event_id]) == 0:
                    del self._uuid_by_event_id[sound_event_id]
            for bus_name in self._refcount[uuid_]:
                if bus_name in self._watcher_by_bus_name:
                    self._watcher_by_bus_name[bus_name].uuids.remove(uuid_)
            del self._refcount[uuid_]
            if not self.players:
                self._ensure_release_countdown()
            self.release()
            connection.emit_signal(None, path, iface, 'Error', vdata)
