import gi
import logging
import uuid
gi.require_version('GLib', '2.0')  # noqa
gi.require_version('Gst', '1.0')   # noqa
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gst


_logger = logging.getLogger(__name__)


class HackSoundPlayer(GObject.Object):
    __gsignals__ = {
        'eos': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'error': (GObject.SignalFlags.RUN_FIRST, None, (GLib.Error, str))
    }

    def __init__(self, metadata, sender):
        GObject.Object.__init__(self)
        self.metadata = metadata
        self.sender = sender
        self.pipeline = self._build_pipeline()
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.__bus_message_cb)

    def play(self):
        self.pipeline.set_state(Gst.State.PLAYING)

    def stop(self):
        self.pipeline.send_event(Gst.Event.new_eos())

    @property
    def sound_location(self):
        return self.metadata["sound-file"]

    def _build_pipeline(self):
        spipeline = ("filesrc location=\"%s\" ! decodebin ! autoaudiosink" %
                     self.sound_location)
        return Gst.parse_launch(spipeline)

    def __bus_message_cb(self, unused_bus, message):
        if message.type == Gst.MessageType.EOS:
            self.pipeline.set_state(Gst.State.NULL)
            self.emit("eos")
        elif message.type == Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            _logger.warning("Error from %s: %s (%s)", message.src, error,
                            debug)
            self.pipeline.set_state(Gst.State.NULL)
            self.emit("error", error, debug)


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
                   invocation):
        if sound_event_id not in self.metadata:
            invocation.return_dbus_error(
                self._DBUS_UNKNOWN_SOUND_EVENT_ID,
                "sound event with id %s does not exist" % sound_event_id)
            return

        self._cancel_countdown()
        self.hold()

        uuid_ = str(uuid.uuid4())
        self.players[uuid_] = HackSoundPlayer(self.metadata[sound_event_id],
                                              sender)
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
