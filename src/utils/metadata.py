import json
import logging
import os
from hack_sound_server.utils.misc import get_metadata_path
from hack_sound_server.utils.misc import get_sounds_dir


_logger = logging.getLogger(__name__)


def _read_in_metadata(metadata, user_type):
    for sound_event_id in metadata:
        metadata[sound_event_id]["sound-file"] =\
            os.path.join(get_sounds_dir(user_type),
                         metadata[sound_event_id]["sound-file"])


def load_metadata(user_type):
    metadata_path = get_metadata_path(user_type)
    ret = None

    if os.path.exists(metadata_path):
        with open(metadata_path, "r") as metadata_file:
            # TODO
            # Check valid JSON schema.
            try:
                metadata = json.load(metadata_file)
                _read_in_metadata(metadata, user_type)
                ret = metadata
            except json.decoder.JSONDecodeError as e:
                _logger.error(
                    "Not possible to decode metadata file at '%s'.\n"
                    "%s" % (metadata_path, e))
    else:
        msg = "The metadata file at '%s' does not exist." % metadata_path
        if user_type == "system":
            _logger.error(msg)
        elif user_type == "user":
            _logger.warning(msg)
    return ret


def read_and_parse_metadata():
    system_metadata = load_metadata("system")
    user_metadata = load_metadata("user")

    if system_metadata is None:
        return user_metadata
    if user_metadata is None:
        return system_metadata
    metadata = system_metadata
    metadata.update(user_metadata)
    return metadata
