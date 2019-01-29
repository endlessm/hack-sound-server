import gi
import logging
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


_logger = logging.getLogger(__name__)


class HackSoundPlayer(GObject.Object):
    _DEFAULT_VOLUME = 1.0
    _DEFAULT_PITCH = 1.0
    _DEFAULT_RATE = 1.0
    _DEFAULT_FADE_IN_MS = 1000
    _DEFAULT_FADE_OUT_MS = 1000

    __gsignals__ = {
        'eos': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'error': (GObject.SignalFlags.RUN_FIRST, None, (GLib.Error, str))
    }

    def __init__(self, uuid_, metadata, sender, metadata_extras=None):
        GObject.Object.__init__(self)
        self.uuid = uuid_
        self.metadata = metadata
        self.metadata_extras = metadata_extras or {}
        self.sender = sender
        self.pipeline = self._build_pipeline()
        self._stop_loop = False
        self._n_loop = 0
        self._is_initial_seek = False
        self._current_state_change = None
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.__bus_message_cb)

    def release(self):
        self.pipeline.get_bus().remove_signal_watch()
        self.pipeline = None

    def get_state(self):
        return self.pipeline.get_state(timeout=0).state

    def play(self):
        if self.delay is None:
            self._play()
        else:
            GLib.timeout_add(self.delay, self._play)

    def _play(self):
        self.pipeline.set_state(Gst.State.PLAYING)
        self._add_fade_in(self.fade_in, self.volume)
        return GLib.SOURCE_REMOVE

    def stop(self):
        if not self.loop:
            # Just stop immediately
            self.pipeline.send_event(Gst.Event.new_eos())
            return

        if self.fade_out == 0:
            self._stop_loop = True
            self.pipeline.send_event(Gst.Event.new_eos())
            return

        volume_elem = self.pipeline.get_by_name('volume')
        # Stop at the end of the current loop
        self._stop_loop = True
        try:
            self._add_fade_out(volume_elem, self.fade_out)
        except ValueError as ex:
            _logger.error(ex)
            _logger.warning("{}: Fade out effect could not be applied. "
                            "Stop.".format(self.uuid))

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
                                time_end, prop_value, consider_duration=False)

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
    def apply_state_on(self):
        return self.metadata.get("apply-state-on")

    def apply_state(self, state):
        """
        Applies the states supported by the 'apply-state-on' metadata property.

        Supported states are 'pause' and 'silence'.
        """
        volume_elem = self.pipeline.get_by_name("volume")
        self._current_state_change = state

        if state == "pause":
            if volume_elem.props.volume == 0:
                self.pipeline.set_state(Gst.State.PAUSED)
            else:
                self._add_fade_out(volume_elem, self.fade_out)
        elif state == "silence":
            self._add_fade_out(volume_elem, self.fade_out)

    def _add_keyframe_pair(self, control, time_start_ns, value_start,
                           time_end_ns, value_end, consider_duration=True):
        control.unset_all()
        if not self._add_keyframe(control, time_start_ns, value_start):
            raise ValueError('bad start time')
        # Rather than deal with the case where we have to split the keyframes
        # over the sound's loop; if the end keyframe is greater than the sound
        # file duration, we just apply the end keyframe to the end.
        if consider_duration:
            duration = self.get_duration()
            time_end_ns = min(time_end_ns, duration * (self._n_loop + 1))
        if not self._add_keyframe(control, time_end_ns, value_end):
            raise ValueError('bad end time')

    def _add_keyframe(self, control, time_ns, value):
        return control.set(time_ns, value)

    def _add_fade_in(self, time_ms_end, volume_end):
        self._add_keyframe_pair(self._fade_control, 0, 0,
                                time_ms_end * Gst.MSECOND, volume_end, False)

    def _add_fade_out(self, element, time_ms):
        current_volume = element.props.volume
        current_time = self.get_current_position()
        self._add_keyframe_pair(self._fade_control,
                                current_time, current_volume,
                                current_time + time_ms * Gst.MSECOND, 0)

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
            "decodebin",
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

        if self.volume != 0:
            self._add_fade_in(self.fade_in, self.volume)

        return pipeline

    def __volume_cb(self, volume_element, unused_volume):
        # In case of fade-out effects, send EOS as soon volume reaches 0.
        if volume_element.props.volume == 0:
            if self._current_state_change == "pause":
                self.pipeline.set_state(Gst.State.PAUSED)
            self._current_state_change = None
            if self._stop_loop:
                self.pipeline.send_event(Gst.Event.new_eos())

    def __bus_message_cb(self, unused_bus, message):
        if message.type == Gst.MessageType.EOS:
            self.pipeline.set_state(Gst.State.NULL)
            self.emit("eos")
        elif message.type == Gst.MessageType.SEGMENT_DONE:
            if message.src != self.pipeline:
                return
            if self.loop and not self._stop_loop:
                self._n_loop += 1
                self.seek(0.0, flags=Gst.SeekFlags.SEGMENT)
            else:
                # Cancel the SEGMENT seek.
                self.seek()
                self.pipeline.send_event(Gst.Event.new_eos())
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
            _logger.warning("Error from %s: %s (%s)", message.src, error,
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
                self.pipeline.send_event(Gst.Event.new_eos())


DBusWatcher = namedtuple("DBusWatcher", ["watcher_id", "uuids"])


class HackSoundServer(Gio.Application):
    _TIMEOUT_S = 10
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
        self._dbus_id = None
        self.metadata = metadata
        self._countdown_id = None
        self.players = {}
        # COunts the references of a sound by UUID and by bus name.
        self._refcount = {}
        self._watcher_by_bus_name = {}
        # Only useful for sounds tagged with "overlap-behavior":
        self._uuid_by_event_id = {}

    def refcount(self, uuid_, bus_name=None):
        if bus_name is None:
            refcount = 0
            for bus_name in self._refcount[uuid_]:
                refcount += self._refcount[uuid_][bus_name]
            return refcount
        return self._refcount[uuid_][bus_name]

    def ref(self, uuid_, bus_name):
        self._refcount[uuid_][bus_name] += 1

    def unref(self, uuid_, bus_name, count=1):
        if uuid_ not in self._refcount:
            _logger.warning("{}: This uuid is not registered in the refcount "
                            "registry.".format(uuid_))
            return
        if bus_name not in self._refcount[uuid_]:
            _logger.warning("{}: Bus name '{}' is not registered in the "
                            "refcount registry.".format(uuid_, bus_name))
            return
        if self._refcount[uuid_][bus_name] == 0:
            _logger.warning("{}: Cannot decrease refcount for bus name '{}'"
                            "because it's already 0.".format(uuid_, bus_name))
            return
        self._refcount[uuid_][bus_name] -= count
        if self.refcount(uuid_) == 0:
            # Only stop the sound if the last bus name (application) referring
            # to it has been disconnected (closed). The stop method will,
            # indirectly, take care for deleting self._refcount[uuid_].
            self.players[uuid_].stop()

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
            _logger.info('Timeout cancelled')

    def _ensure_release_countdown(self):
        self._cancel_countdown()
        self.hold()
        _logger.info('All sounds done; starting timeout of {} seconds'.format(
            self._TIMEOUT_S))
        self._countdown_id = GLib.timeout_add_seconds(
            self._TIMEOUT_S, self.release, priority=GLib.PRIORITY_LOW)

    def play_sound(self, sound_event_id, connection, sender, path, iface,
                   invocation, options=None):
        if sound_event_id not in self.metadata:
            invocation.return_dbus_error(
                self._DBUS_UNKNOWN_SOUND_EVENT_ID,
                "sound event with id %s does not exist" % sound_event_id)
            return

        overlap_behavior = \
            self.metadata[sound_event_id].get("overlap-behavior", "overlap")
        if overlap_behavior not in self._OVERLAP_BEHAVIOR_CHOICES:
            return invocation.return_dbus_error(
                self._DBUS_UNKNOWN_OVERLAP_BEHAVIOR,
                "'%s' is not a valid option." % overlap_behavior)
        if not self._uuid_by_event_id.get(sound_event_id):
            self._uuid_by_event_id[sound_event_id] = set()

        uuid_ = self._do_overlap_behaviour(sound_event_id, overlap_behavior)
        if uuid_ is not None:
            self._watch_bus_name(sender, uuid_)

        if uuid_ is None:
            self._cancel_countdown()
            self.hold()

            uuid_ = str(uuid.uuid4())
            metadata = self.metadata[sound_event_id]
            self.players[uuid_] = HackSoundPlayer(uuid_, metadata, sender,
                                                  options)
            self._watch_bus_name(sender, uuid_)
            # Insert the uuid in the dictionary organized by sound event id.
            self._uuid_by_event_id[sound_event_id].add(uuid_)

            self.players[uuid_].connect("eos", self.__player_eos_cb,
                                        sound_event_id, uuid_)
            self.players[uuid_].connect("error", self.__player_error_cb,
                                        sound_event_id, uuid_,
                                        connection, path, iface)
            self.players[uuid_].play()
            self.apply_states(self.players[uuid_])

        return invocation.return_value(GLib.Variant('(s)', (uuid_, )))

    def apply_states(self, player_to_exclude):
        """
        Applies the states indicated "apply-state-on" to the stated event ids.

        The metadata for a given sound event may describe something like:
            ```
            "sound-a": {
                "soud-location": "foo.wav",
                "apply-state-on": [
                    "pause": ["sound1", "sound2"],
                    "silence": ["sound3", "sound4"]
                ]
            }
            ```
        By calling this method, the states "pause" would be applied to "sound1"
        and "sound2", and the state "silence" to "sound3" and "sound4".

        Args:
            player_to_exclude (Player): The player which will not be affected
                                        by the state change.
        """
        for player, state in self._players_to_apply_state(player_to_exclude):
            player.apply_state(state)

    def resume_states(self, player_to_exclude):
        for player, _ in self._players_to_apply_state(player_to_exclude):
            player.play()

    def _players_to_apply_state(self, player):
        if player.apply_state_on is None:
            return []
        for state, sound_envent_ids in player.apply_state_on.items():
            for sound_event_id in sound_envent_ids:
                uuids = self._uuid_by_event_id[sound_event_id]
                for uuid in uuids:
                    yield self.players[uuid], state

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
            self.players[uuid_].reset()
            return uuid_
        elif overlap_behavior == "ignore":
            # If a sound is already playing, then ignore the new one.
            return uuid_
        return None

    def stop_sound(self, uuid_, connection, sender, path, iface, invocation):
        assert not (uuid_ in self.players and uuid_ in self._uuid_by_event_id)
        # xor: With the exception that the case of both cases being True will
        # never happen because we never define an UUID in the metadata file.
        if not ((uuid_ not in self.players) ^
                (uuid_ not in self._uuid_by_event_id)):
            _logger.info('Sound {} was supposed to be stopped, '
                         'but did not exist'.format(uuid_))
        elif (uuid_ in self.players and (uuid_ not in self._refcount or
                                         sender not in self._refcount[uuid_])):
            _logger.info('Sound {} was supposed to be refcounted by the bus, '
                         'name \'{}\' but it wasn\'t.'.format(uuid_, sender))
        else:
            if uuid_ in self.players:
                self.unref(uuid_, sender)
            elif uuid_ in self._uuid_by_event_id:
                sound_event_id = uuid_
                for uuid_ in self._uuid_by_event_id[sound_event_id]:
                    self.unref(uuid_, sender)
            invocation.return_value(None)

    def update_properties(self, uuid_, transition_time_ms, options, connection,
                          sender, path, iface, invocation):
        if uuid_ not in self.players:
            _logger.info('Properties of sound {} was supposed to be updated, '
                         'but did not exist'.format(uuid_))
        else:
            self.players[uuid_].update_properties(transition_time_ms, options)
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
            self.stop_sound(params[0], connection, sender, path, iface,
                            invocation)
        elif method == "UpdateProperties":
            self.update_properties(params[0], params[1], params[2], connection,
                                   sender, path, iface, invocation)
        else:
            invocation.return_error_literal(
                Gio.dbus_error_quark(), Gio.DBusError.UNKNOWN_METHOD,
                "Method '%s' not available" % method)

    def __player_eos_cb(self, unused_player, sound_event_id, uuid_):
        # This method is only called when a sound naturally reaches
        # end-of-stream or when an application ordered to stop the sound. In
        # both cases this means to delete the references to that sound UUID.
        self.players[uuid_].release()
        self.resume_states(self.players[uuid_])
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
            del self.players[uuid_]
            self.players[uuid_].release()
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
