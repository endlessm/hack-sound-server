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
import json
import os
from hack_sound_server.utils.misc import get_metadata_path
from hack_sound_server.utils.misc import get_sounds_dir
from hack_sound_server.utils.loggable import logger


def _read_in_metadata(metadata, user_type):
    sounds_dir = get_sounds_dir(user_type)
    for sound_event_id in metadata:
        sound_files = metadata[sound_event_id].get("sound-files", [])
        # If both "sound-file" and "sound-files" are specified, we consider all
        # the available sounds.
        if "sound-file" in metadata[sound_event_id]:
            sound_files.append(metadata[sound_event_id]["sound-file"])

        metadata[sound_event_id]["sound-files"] =\
            [os.path.join(sounds_dir, path) for path in set(sound_files)]


def load_metadata(user_type):
    metadata_path = get_metadata_path(user_type)
    ret = {}

    if os.path.exists(metadata_path):
        with open(metadata_path, "r") as metadata_file:
            # TODO
            # Check valid JSON schema.
            try:
                metadata = json.load(metadata_file)
                _read_in_metadata(metadata, user_type)
                ret = metadata
            except Exception as e:
                logger.error(
                    "Not possible to decode metadata file at '%s'.\n"
                    "%s" % (metadata_path, e))
    else:
        msg = "The metadata file at '%s' does not exist." % metadata_path
        if user_type == "system":
            logger.error(msg)
        elif user_type == "user":
            logger.info(msg)
    return ret


def read_and_parse_metadata():
    system_metadata = load_metadata("system")
    user_metadata = load_metadata("user")
    system_metadata.update(user_metadata)
    return system_metadata
