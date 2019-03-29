import itertools
import re


class IdentifierFactory:
    def __init__(self):
        self._id_generator = itertools.count(1)

    def get_next_id(self):
        return next(self._id_generator)


def snakecase(string):
    # Source: https://stackoverflow.com/a/1176023
    s = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', string)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s).lower()


def dbus_method_to_signal(method_name):
    s = re.sub("(.)([A-Z][a-z]+)", r"\1-\2", method_name)
    return "handle-%s" % re.sub("([a-z0-9])([A-Z])", r"\1-\2", s).lower()
