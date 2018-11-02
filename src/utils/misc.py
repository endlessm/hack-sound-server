import os
from gi.repository import GLib
from hack_sound_server.configure import DATADIR
from hack_sound_server.configure import PACKAGE


def get_datadir(user_type):
    if user_type == "user":
        return os.path.join(GLib.get_user_data_dir(), PACKAGE)
    elif user_type == "system":
        return os.path.join(DATADIR, PACKAGE)


def get_metadata_path(user_type):
    data_dir = get_datadir(user_type)
    return os.path.join(data_dir, "metadata.json")


def get_sounds_dir(user_type):
    data_dir = get_datadir(user_type)
    return os.path.join(data_dir, "sounds")
