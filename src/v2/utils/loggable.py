from hack_sound_server.utils.loggable import apply_style
from hack_sound_server.utils.loggable import ObjectFormatter
from hack_sound_server.utils.loggable import ServerFormatter
from hack_sound_server.utils.loggable import SoundFormatter
from hack_sound_server.utils.loggable import YELLOW, GREEN, VIOLET


class PlayerFormatter(ObjectFormatter):
    _DEFAULT_BUS_NAME = YELLOW
    _DEFAULT_OBJECT_PATH_COLOR = GREEN
    _DEFAULT_EVENT_ID_COLOR = VIOLET

    def format(self, record):
        base_template = "{}: "
        args = []

        color = self.beautify and self._DEFAULT_BUS_NAME
        args.append(apply_style(self.bus_name, color))

        color = self.beautify and self._DEFAULT_OBJECT_PATH_COLOR
        args.append(apply_style(self.object_path, color))

        sound_event_id = record.__dict__.get("sound_event_id")
        if sound_event_id is not None:
            color = self.beautify and self._DEFAULT_EVENT_ID_COLOR
            args.append(apply_style(sound_event_id, color))

        template = base_template * len(args)
        prefix = template.format(*args)
        record.msg = "{}{}".format(prefix, record.msg)
        return super().format(record)

    @property
    def object_path(self):
        return self.obj.object_path

    @property
    def bus_name(self):
        return self.obj.bus_name


class PlayerManagerFormatter(PlayerFormatter):
    @property
    def object_path(self):
        return self.obj.obj.object_path

    @property
    def bus_name(self):
        return self.obj.obj.bus_name


class SoundManagerFormatter(SoundFormatter):
    @property
    def bus_name(self):
        return self.obj.obj.bus_name

    @property
    def uuid(self):
        return self.obj.obj.uuid

    @property
    def sound_event_id(self):
        return self.obj.obj.sound_event_id


ServerManagerFormatter = ServerFormatter
