#
# Copyright © 2020 Endless OS Foundation LLC.
#
# This file is part of hack-sound-server
# (see https://github.com/endlessm/hack-sound-server).
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
import logging
import os


DEFAULT_LOG_LEVEL = logging.WARNING

_COLOR_TMPL = "\033[3{}m"
(RED,
 GREEN,
 YELLOW,
 BLUE,
 VIOLET,
 CYAN) = map(lambda x: _COLOR_TMPL.format(x), range(1, 7))

BOLD = "\033[1m"
ESC = "\033[0m"


def apply_style(text, color=None, bold=False):
    bold = BOLD if bold else ""
    color = color or ""
    return "{}{}{}{}".format(bold, color, text, ESC)


def get_log_level():
    level = os.environ.get('HACK_SOUND_SERVER_LOGLEVEL')
    if not level:
        return DEFAULT_LOG_LEVEL
    try:
        level = int(level)
    except ValueError:
        level = logging.__dict__.get(level)
    if isinstance(level, int):
        return level
    return DEFAULT_LOG_LEVEL


class DefaultFormatter(logging.Formatter):
    _DEFAULT_FORMAT = ("%(levelname)s : %(asctime)s %(funcName)s"
                       " - %(message)s (%(filename)s:%(lineno)d)")
    _DEFAULT_COLORS = {
        "CRITICAL": VIOLET,
        "ERROR": RED,
        "WARNING": YELLOW,
        "INFO": CYAN,
        "DEBUG": BLUE
    }

    def __init__(self, obj, beautify=True):
        super().__init__(self._DEFAULT_FORMAT)
        self.obj = obj
        self.beautify = beautify

    def format(self, record):
        if self.beautify:
            color = self._DEFAULT_COLORS[record.levelname]
            record.levelname = apply_style(record.levelname, color, bold=True)
            record.levelname = record.levelname.ljust(21)
        else:
            record.levelname = record.levelname.ljust(8)
        return super().format(record)


class ObjectFormatter(DefaultFormatter):
    _DEFAULT_FORMAT = ("%(levelname)s : %(asctime)s %(name)s.%(funcName)s"
                       " - %(message)s (%(filename)s:%(lineno)d)")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def format(self, record, show_object_id=True):
        if show_object_id:
            record.name = "<{} at {}>".format(self.obj.__class__.__name__,
                                              id(self.obj))
        else:
            record.name = "<{}>".format(self.obj.__class__.__name__)
        return super().format(record)


class SoundFormatter(ObjectFormatter):
    _DEFAULT_BUS_NAME = YELLOW
    _DEFAULT_EVENT_ID_COLOR = VIOLET
    _DEFAULT_UUID_COLOR = CYAN

    def __init__(self, obj, beautify=True):
        super().__init__(obj, beautify)

    def format(self, record):
        tmpl = "{}: {}: {}: {}"
        bus_name = apply_style(self.obj.bus_name,
                               self.beautify and self._DEFAULT_BUS_NAME)
        event_id = apply_style(self.obj.sound_event_id,
                               self.beautify and self._DEFAULT_EVENT_ID_COLOR)
        uuid = apply_style(self.obj.uuid,
                           self.beautify and self._DEFAULT_UUID_COLOR)

        record.msg = tmpl.format(bus_name, event_id, uuid, str(record.msg))
        msg = super().format(record)
        return msg


class ServerFormatter(ObjectFormatter):
    """
    Structures a message prefixing the bus name, event id and uuid if existing.

    Users can do the following:
        logger.info("A %s message.", "structured",
                    bus_name=":2:23", sound_event_id="foo/bar", uuid="8a34vv2")

    output: :2:23: foo/bar: 8a34vv2: A structured message.

    Note: bus_name, sound_event_id and uuid are optional.
    """

    _DEFAULT_BUS_NAME = YELLOW
    _DEFAULT_EVENT_ID_COLOR = VIOLET
    _DEFAULT_UUID_COLOR = CYAN

    def __init__(self, obj, beautify=True):
        super().__init__(obj, beautify)

    def format(self, record):
        base_template = "{}: "

        bus_name = record.__dict__.get("bus_name")
        sound_event_id = record.__dict__.get("sound_event_id")
        uuid = record.__dict__.get("uuid")

        prefix = ""
        if bus_name is not None:
            color = self.beautify and self._DEFAULT_BUS_NAME
            prefix += base_template.format(apply_style(bus_name, color))
        if sound_event_id is not None:
            color = self.beautify and self._DEFAULT_EVENT_ID_COLOR
            prefix += base_template.format(apply_style(sound_event_id, color))
        if uuid is not None:
            color = self.beautify and self._DEFAULT_UUID_COLOR
            prefix += base_template.format(apply_style(uuid, color))
        record.msg = "{}{}".format(prefix, record.msg)
        return super().format(record, show_object_id=False)


class Logger(logging.Logger):
    DEFAULT_FORMATTER = DefaultFormatter

    def __init__(self, formatter=DEFAULT_FORMATTER, obj=None):
        super().__init__(id(obj))
        ch = logging.StreamHandler()
        if formatter == self.DEFAULT_FORMATTER:
            formatter = DefaultFormatter(obj)
        else:
            formatter = formatter(obj)
        ch.setFormatter(formatter)
        self.addHandler(ch)
        self.setLevel(get_log_level())

    def _log(self, level, msg, args, exc_info=None, extra=None,
             stack_info=False, **kwargs):
        """
        Passes kwargs as the extra argument so it's accessible from the record.

        Users can do the following:
            logger.info("%d-%s-%s", 3, "pigs", "fly", trump=None)
        """
        extra = extra or {}
        extra.update(kwargs)
        super()._log(level, msg, args, exc_info, extra, stack_info)


logger = Logger()
