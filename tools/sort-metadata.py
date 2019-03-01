#!/usr/bin/python3
import argparse
import json
import os
from collections import OrderedDict


ROOT_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), os.pardir)
DATA_DIR = os.path.join(ROOT_DIR, "data")
SYSTEM_METADATA_PATH = os.path.join(DATA_DIR, "metadata.json")


def beautify_sound_event_id(entry):
    # Always put sound-file and sound-files at the beginning.
    items = []
    if "sound-file" in entry:
        items.append(("sound-file", entry["sound-file"]))
        del entry["sound-file"]
    if "sound-files" in entry:
        items.append(("sound-files", sorted(entry["sound-files"])))
        del entry["sound-files"]
    items.extend(sorted(entry.items()))

    return OrderedDict(items)


def beautify_metadata(metadata):
    return OrderedDict(sorted(metadata.items()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--path",
                        type=argparse.FileType("r+"),
                        help="Path to the metadata json file",
                        default=SYSTEM_METADATA_PATH,
                        required=False)
    parser.add_argument("--inplace", action="store_true",
                        required=False)

    args = parser.parse_args()

    metadata = json.loads(args.path.read())
    metadata = {
        sound: beautify_sound_event_id(metadata[sound]) for sound in metadata
    }
    metadata = beautify_metadata(metadata)
    sorted_metadata = json.dumps(metadata, indent=4)

    print(sorted_metadata)
    if args.inplace:
        args.path.seek(0)
        args.path.truncate(0)
        args.path.write(sorted_metadata)
    args.path.close()
