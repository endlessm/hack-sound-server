import gi
import logging
import uuid
gi.require_version('GLib', '2.0')  # noqa
gi.require_version('Gst', '1.0')   # noqa
gi.require_version('GstController', '1.0')  # noqa
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gst
from gi.repository import GstController


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
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.__bus_message_cb)

    def release(self):
        self.pipeline.get_bus().remove_signal_watch()
        self.pipeline = None

    def play(self):
        if self.delay is None:
            self._play()
        else:
            GLib.timeout_add(self.delay, self._play)

    def _play(self):
        self.pipeline.set_state(Gst.State.PLAYING)
        return GLib.SOURCE_REMOVE

    def stop(self):
        if not self.loop:
            # Just stop immediately
            self.pipeline.send_event(Gst.Event.new_eos())
            return

        pipeline_fade_out = 0
        if self.loop:
            pipeline_fade_out = self._DEFAULT_FADE_OUT_MS
        if self.fade_out is not None:
            pipeline_fade_out = self.fade_out

        if pipeline_fade_out == 0:
            self._stop_loop = True
            self.pipeline.send_event(Gst.Event.new_eos())
            return

        volume_elem = self.pipeline.get_by_name('volume')
        try:
            self._add_fade_out(volume_elem, pipeline_fade_out)
        except ValueError as ex:
            _logger.error(ex)
            _logger.warning("{}: Fade out effect could not be applied. "
                            "Stop.".format(self.uuid))
        # Stop at the end of the current loop
        self._stop_loop = True

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
        return self._get_multipliable_prop("volume")

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
        if "fade-in" in self.metadata:
            return self.metadata["fade-in"]
        return None

    @property
    def fade_out(self):
        if "fade-out" in self.metadata:
            return self.metadata["fade-out"]
        return None

    @property
    def delay(self):
        if "delay" in self.metadata:
            return self.metadata["delay"]
        return None

    @property
    def sound_location(self):
        return self.metadata["sound-file"]

    def _add_keyframe_pair(self, control, time_start_ns, value_start,
                           time_end_ns, value_end, consider_duration=True):
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
        pipeline_volume = self._DEFAULT_VOLUME
        if self.volume is not None:
            pipeline_volume = self.volume
        pipeline_fade_in = 0
        if self.loop:
            pipeline_fade_in = self._DEFAULT_FADE_IN_MS
        if self.fade_in is not None:
            pipeline_fade_in = self.fade_in

        pitch_args = (self.pitch or self._DEFAULT_PITCH,
                      self.rate or self._DEFAULT_RATE)
        elements = [
            "filesrc name=src location=\"{}\"".format(self.sound_location),
            "decodebin",
            "identity single-segment=true",
            "audioconvert",
            "pitch name=pitch pitch={} rate={}".format(*pitch_args),
            "volume name=volume volume={}".format(pipeline_volume),
            "autoaudiosink"
        ]
        spipeline = " ! ".join(elements)
        pipeline = Gst.parse_launch(spipeline)

        volume_elem = pipeline.get_by_name("volume")
        assert volume_elem is not None
        self._fade_control = self._create_control(volume_elem, "volume")

        pitch_elem = pipeline.get_by_name("pitch")
        assert pitch_elem is not None
        self._rate_control = self._create_control(pitch_elem, "rate")

        if pipeline_fade_in != 0:
            self._add_fade_in(pipeline_fade_in, pipeline_volume)

        return pipeline

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


class HackSoundServer(Gio.Application):
    _TIMEOUT_S = 10
    _DBUS_NAME = "com.endlessm.HackSoundServer"
    _DBUS_UNKNOWN_SOUND_EVENT_ID = \
        "com.endlessm.HackSoundServer.UnknownSoundEventID"
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
        self._cancel_countdown()
        self.hold()

        uuid_ = str(uuid.uuid4())
        metadata = self.metadata[sound_event_id]
        self.players[uuid_] = HackSoundPlayer(uuid_, metadata, sender, options)
        self.players[uuid_].connect("eos", self.__player_eos_cb, uuid_)
        self.players[uuid_].connect("error", self.__player_error_cb, uuid_,
                                    connection, path, iface)
        self.players[uuid_].play()
        invocation.return_value(GLib.Variant('(s)', (uuid_, )))

    def stop_sound(self, uuid_, connection, sender, path, iface, invocation):
        if uuid_ not in self.players:
            _logger.info('Sound {} was supposed to be stopped, '
                         'but did not exist'.format(uuid_))
        else:
            self.players[uuid_].stop()
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

    def __player_eos_cb(self, unused_player, uuid_):
        self.players[uuid_].release()
        del self.players[uuid_]
        if not self.players:
            self._ensure_release_countdown()
        self.release()

    def __player_error_cb(self, player, error, debug, uuid_, connection,
                          path, iface):
        data = (uuid_, error.message, error.domain, error.code, debug)
        vdata = GLib.Variant("(sssis)", data)
        if uuid_ in self.players:
            del self.players[uuid_]
            if not self.players:
                self._ensure_release_countdown()
            self.release()
            connection.emit_signal(None, path, iface, 'Error', vdata)
