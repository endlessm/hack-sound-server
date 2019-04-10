import os
from gi.repository import GLib
from abc import ABC
from abc import abstractmethod
from hack_sound_server.configure import DATADIR
from hack_sound_server.configure import PACKAGE


def get_datadir(user_type):
    if user_type == "user":
        return GLib.get_user_data_dir()
    elif user_type == "system":
        return os.path.join(DATADIR, PACKAGE)


def get_metadata_path(user_type):
    data_dir = get_datadir(user_type)
    return os.path.join(data_dir, "metadata.json")


def get_sounds_dir(user_type):
    data_dir = get_datadir(user_type)
    return os.path.join(data_dir, "sounds")


class Factory(ABC):
    @abstractmethod
    def new(self, *args, **kwargs):
        pass
