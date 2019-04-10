import gi
import random
import uuid
gi.require_version('GLib', '2.0')  # noqa
gi.require_version('Gst', '1.0')   # noqa
gi.require_version('GstController', '1.0')  # noqa
from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gst
from gi.repository import GstController
from hack_sound_server.utils.loggable import Logger
from hack_sound_server.utils.loggable import SoundFormatter
from hack_sound_server.utils.misc import Factory


class ServerSoundFactory(Factory):
    def __init__(self, server):
        self.server = server

    def new(self, *args, **kwargs):
        return Sound(self.server, *args, **kwargs)


class Sound(GObject.Object):
    _DEFAULT_VOLUME = 1.0
    _DEFAULT_PITCH = 1.0
    _DEFAULT_RATE = 1.0
    _DEFAULT_FADE_IN_MS = 1000
    _DEFAULT_FADE_OUT_MS = 1000

    __gsignals__ = {
        'released': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'error': (GObject.SignalFlags.RUN_FIRST, None, (GLib.Error, str))
    }

    def __init__(self, server, bus_name, sound_event_id, metadata_extras=None):
        super().__init__()
        self.server = server
        self.logger = Logger(SoundFormatter, self)
        # The following attributes (bus_name, sound_event_id and uuid) are
        # used internally by the logger to format the log messages.
        self.bus_name = bus_name
        self.sound_event_id = sound_event_id
        self.uuid = str(uuid.uuid4())

        assert sound_event_id in server.metadata
        self.metadata = server.metadata[sound_event_id]
        self.metadata_extras = metadata_extras or {}

        self._stop_loop = False
        self._n_loop = 0
        self._is_initial_seek = False
        self._pending_state_change = None
        self._releasing = False

        self.pipeline = self._build_pipeline()
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.__bus_message_cb)

        self.connect("released", self.server.sound_released_cb)
        self.connect("error", self.server.sound_error_cb)

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

    def play(self):
        self._play()

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
                self._add_fade_out()
            except (ValueError, AssertionError):
                self.logger.warning("Fade out effect could not be applied. "
                                    "Pausing.")
                self.pipeline.set_state(Gst.State.PAUSED)
                self._pending_state_change = None

    def _play(self):
        self.logger.info("Playing.")
        if self._releasing:
            self.logger.info("Cannot play because being released.")
            return
        self._stop_loop = False
        self.pipeline.set_state(Gst.State.PLAYING)
        self._add_fade_in()
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

        # Stop at the end of the current loop
        self._stop_loop = True
        try:
            self._add_fade_out()
        except (ValueError, AssertionError) as ex:
            self.logger.error(ex)
            self.logger.warning("Fade out effect could not be applied. Stop.")
            self.release()

    def reset(self):
        self.seek(0.0)
        # Reset keyframes.
        self._fade_control.unset_all()
        self._rate_control.unset_all()
        self._add_fade_in()

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

    def _add_fade_in(self):
        if not self.loop or self.loop and self.fade_in == 0:
            return
        self.logger.debug("Fading in.")
        try:
            current_time = self.get_current_position()
        except ValueError:
            # This is the first call to play the sound and it should fade in
            # from the time 0.
            self.logger.info("Cannot get the current position. "
                             "Current state is '%s'. "
                             "Assume first PlaySound call. Current time=0.",
                             Gst.Element.state_get_name(self.get_state()))
            current_time = 0
        current_volume = self.pipeline.get_by_name("volume").props.volume
        end_time = current_time + self.fade_in * Gst.MSECOND
        consider_delay = current_time == 0
        self._add_keyframe_pair(self._fade_control,
                                current_time, current_volume,
                                end_time, self.volume, False, consider_delay)

    def _add_fade_out(self):
        # This method may raise a ValueError usually if the pipeline is in
        # NULL or READY state which is likely to happen when a StopSound call
        # arrives very quick "just after" a PlaySound call has arrived, because
        # the pipeline may have not reached the PAUSED state yet.
        # Remember that there may be intermediate states:
        # https://gstreamer.freedesktop.org/documentation/design/states.html
        # and that the position query will usually fail if the pipeline is not
        # PAUSED or PLAYING.
        if not self.loop or self.loop and self.fade_out == 0:
            return
        self.logger.debug("Fading out.")
        current_time = self.get_current_position()
        if self.delay and current_time < self.delay * Gst.MSECOND:
            self.logger.warning("Cannot fade out while in an in-progress "
                                "delay.")
            raise AssertionError
        current_volume = self.pipeline.get_by_name("volume").props.volume
        end_time = current_time + self.fade_out * Gst.MSECOND
        self._add_keyframe_pair(self._fade_control,
                                current_time, current_volume,
                                end_time, 0,
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
        assert volume_elem is not None
        # Set the initial volume to 0 for looping sounds that fade in.
        if self.loop and self.fade_in > 0:
            volume_elem.props.volume = 0
        volume_elem.connect("notify::volume", self.__volume_cb)
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
