import logging


class DefaultFormatter(logging.Formatter):
    _DEFAULT_FORMAT = ("%(levelname)s : %(asctime)s %(funcName)s"
                       " - %(message)s (%(filename)s:%(lineno)d)")

    def __init__(self, obj):
        super().__init__(self._DEFAULT_FORMAT)
        self.obj = obj

    def format(self, record):
        record.levelname = record.levelname.ljust(8)
        return super().format(record)


class ObjectFormatter(DefaultFormatter):
    _DEFAULT_FORMAT = ("%(levelname)s : %(asctime)s %(name)s.%(funcName)s"
                       " - %(message)s (%(filename)s:%(lineno)d)")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def format(self, record):
        record.name = "<{} at {}>".format(self.obj.__class__.__name__,
                                          id(self.obj))
        return super().format(record)


class PlayerFormatter(ObjectFormatter):
    def __init__(self, obj):
        super().__init__(obj)

    def format(self, record):
        tmpl = "{}: {}: {}: {}"
        bus_name = self.obj.bus_name
        event_id = self.obj.sound_event_id
        uuid = self.obj.uuid

        record.msg = tmpl.format(bus_name, event_id, uuid, record.msg)
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

    def __init__(self, obj):
        super().__init__(obj)

    def format(self, record):
        base_template = "{}: "

        bus_name = record.__dict__.get("bus_name")
        sound_event_id = record.__dict__.get("sound_event_id")
        uuid = record.__dict__.get("uuid")

        prefix = ""
        if bus_name is not None:
            prefix += base_template.format(bus_name)
        if sound_event_id is not None:
            prefix += base_template.format(sound_event_id)
        if uuid is not None:
            prefix += base_template.format(uuid)
        record.msg = "{}{}".format(prefix, record.msg)
        return super().format(record)


class BaseLoggable(logging.Logger):
    def __init__(self, formatter=None):
        super().__init__(id(self))
        ch = logging.StreamHandler()
        if formatter is None:
            formatter = DefaultFormatter(self)
        else:
            formatter = formatter(self)
        ch.setFormatter(formatter)
        self.addHandler(ch)

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


class Loggable(BaseLoggable):
    def __init__(self, formatter=None):
        if formatter is None:
            formatter = ObjectFormatter(self)
        super().__init__(formatter=formatter)


logger = BaseLoggable()
