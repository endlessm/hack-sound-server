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
import os
from gi.repository import GLib
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
