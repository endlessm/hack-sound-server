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
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.__bus_message_cb)

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

        pipeline_fade_out = self._DEFAULT_FADE_OUT_MS
        if self.fade_out is not None:
            pipeline_fade_out = self.fade_out

        volume_elem = self.pipeline.get_by_name('volume')
        try:
            self._add_fade_out(volume_elem, pipeline_fade_out)
        except ValueError as ex:
            _logger.error(ex)
            _logger.warning("{}: Fade out effect could not be applied. "
                            "Stop.".format(self.uuid))
        # Stop at the end of the current loop
        self._stop_loop = True

    def seek(self, position):
        self.pipeline.seek_simple(Gst.Format.TIME,
                                  Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                                  position)

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

    def _add_fade_in(self, element, time_ms, volume):
        if not self._fade_control.set(0, 0):
            raise ValueError('bad start time')
        if not self._fade_control.set(time_ms * Gst.MSECOND, volume):
            raise ValueError('bad end time')

    def _remove_fade_in(self):
        self._fade_control.unset_all()

    def _add_fade_out(self, element, time_ms):
        current_volume = element.props.volume
        ok, duration = self.pipeline.query_duration(Gst.Format.TIME)
        if not ok:
            raise ValueError('error querying duration')
        ok, current_time = self.pipeline.query_position(Gst.Format.TIME)
        if not ok:
            raise ValueError('error querying position')

        # Rather than deal with the case where we have to split the fade out
        # over the sound's loop; if there is less than the fade out time
        # remaining in the current loop, we just fade out for the rest of this
        # loop instead.
        time_ns = min(time_ms * Gst.MSECOND, duration - current_time)

        if not self._fade_control.set(current_time, current_volume):
            raise ValueError('bad start time')
        if not self._fade_control.set(current_time + time_ns, 0):
            raise ValueError('bad end time')

    def _get_multipliable_prop(self, prop_name):
        value = self.metadata.get(prop_name, None)
        if prop_name in self.metadata_extras:
            if value is None:
                value = self.metadata_extras[prop_name]
            else:
                value *= self.metadata_extras[prop_name]
        return value

    def _build_pipeline(self):
        pipeline_volume = self._DEFAULT_VOLUME
        if self.volume is not None:
            pipeline_volume = self.volume
        pipeline_fade_in = self._DEFAULT_FADE_IN_MS
        if self.fade_in is not None:
            pipeline_fade_in = self.fade_in

        pitch_args = (self.pitch or self._DEFAULT_PITCH,
                      self.rate or self._DEFAULT_RATE)
        elements = [
            "filesrc name=src location=\"{}\"".format(self.sound_location),
            "decodebin",
            "volume name=volume volume={}".format(pipeline_volume),
            "audioconvert",
            "pitch pitch={} rate={}".format(*pitch_args),
            "autoaudiosink"
        ]
        spipeline = " ! ".join(elements)
        pipeline = Gst.parse_launch(spipeline)

        volume_elem = pipeline.get_by_name("volume")
        assert volume_elem is not None
        self._fade_control = GstController.InterpolationControlSource(
            mode=GstController.InterpolationMode.LINEAR)
        binding = GstController.DirectControlBinding.new_absolute(
            volume_elem, "volume", self._fade_control)
        if not volume_elem.add_control_binding(binding):
            raise ValueError('bad control binding')

        if pipeline_fade_in != 0:
            self._add_fade_in(volume_elem, pipeline_fade_in, pipeline_volume)

        return pipeline

    def __bus_message_cb(self, unused_bus, message):
        if message.type == Gst.MessageType.EOS:
            if self.loop and not self._stop_loop:
                self._remove_fade_in()
                self.seek(0.0)
            else:
                self.pipeline.set_state(Gst.State.NULL)
                self.emit("eos")
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
        else:
            invocation.return_error_literal(
                Gio.dbus_error_quark(), Gio.DBusError.UNKNOWN_METHOD,
                "Method '%s' not available" % method)

    def __player_eos_cb(self, unused_player, uuid_):
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
