#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
from collections import OrderedDict


ROOT_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.realpath(__file__)), os.pardir))
TOOLS_DIR = os.path.join(ROOT_DIR, "tools")
DATA_DIR = os.path.join(ROOT_DIR, "data")
SOUNDS_DIR = os.path.join(DATA_DIR, "sounds")

SYSTEM_METADATA_PATH = os.path.join(DATA_DIR, "metadata.json")
METADATA_SCHEMA_PATH = os.path.join(ROOT_DIR, "ci", "metadata.schema.json")


def check_media_file_integrity(filepath):
    stream = ffmpeg.input(filepath).output("pipe:", format="null")
    try:
        stream.run(capture_stdout=True, capture_stderr=True)
    except ffmpeg.Error:
        return False
    return True


def check_sorted(metadata):
    if not sorted(metadata) == list(metadata):
        return False

    for sound in metadata:
        props = list(metadata[sound])
        if not sorted(props[1:]) == props[1:]:
            return False


def check_files(metadata, check_media_integrity=False):
    valid = True
    for sound in metadata:
        location = metadata[sound].get("sound-file")
        if not location:
            locations = metadata[sound].get("sound-files")
        else:
            locations = [location]

        for location in locations:
            full_location = os.path.abspath(os.path.join(SOUNDS_DIR, location))
            file_extension = os.path.splitext(full_location)[1]

            if not os.path.isfile(full_location):
                valid = False

                print(f"File '{full_location}' does not exist.",
                      file=sys.stderr)
            elif (check_media_integrity and
                    not check_media_file_integrity(full_location)):
                valid = False
                print(f"File '{full_location}' is not a valid media file.",
                      file=sys.stderr)
            if file_extension != ".webm":
                print(f"File '{full_location}' is not a 'webm' file. "
                      "Did you forget to convert it? "
                      "Use ./tools/convert-sounds.sh", file=sys.stderr)
    return valid


def check_schema():
    proccess = subprocess.Popen(
        ["jsonschema", "-i", f"{args.path.name}", f"{METADATA_SCHEMA_PATH}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    out, err = proccess.communicate()
    is_valid = proccess.returncode == 0

    if not is_valid:
        print(err.decode("utf-8"), file=sys.stderr)
    return is_valid


def check_json():
    proccess = subprocess.Popen(
        ["python", "-m", "json.tool", f"{args.path.name}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    out, err = proccess.communicate()
    is_valid = proccess.returncode == 0

    if not is_valid:
        print(err.decode("utf-8"), file=sys.stderr)
    return is_valid


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--path",
                        type=argparse.FileType("r+"),
                        help="Path to the metadata json file",
                        default=SYSTEM_METADATA_PATH,
                        required=False)
    parser.add_argument("--check-sorted", action="store_true",
                        help="Checks that the metadata json file is sorted.",
                        required=False)
    parser.add_argument("--check-files", action="store_true",
                        help="Checks the existence of specified audio files.",
                        required=False)
    parser.add_argument("--check-integrity", action="store_true",
                        help="Checks for the integrity of audio files.",
                        required=False)

    args = parser.parse_args()

    if not check_json():
        print("Metadata file is not a valid JSON file.", file=sys.stderr)
        sys.exit(1)

    if not check_schema():
        print("Metadata file does not follow the schema.", file=sys.stderr)
        sys.exit(1)

    # From here, we consider a valid json file following the schema.
    metadata = json.loads(args.path.read(), object_pairs_hook=OrderedDict)
    exit_status = 0

    if args.check_sorted and not check_sorted(metadata):
        exit_status = 1
        print("Metadata is not sorted.", file=sys.stderr)

    check_integrity = False
    if args.check_integrity:
        proccess = subprocess.Popen(
            ["bash", "-c",
             f"source {TOOLS_DIR}/check-ffmpeg.sh && check_ffmpeg_codecs"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        out, err = proccess.communicate()
        check_integrity = proccess.returncode == 0

        if not check_integrity:
            exit_status = 1
            print(out, file=sys.stderr)
        try:
            import ffmpeg
        except ModuleNotFoundError:
            print("Please install ffmpeg-python.", file=sys.stderr)
            check_integrity = False

    if args.check_files and not check_files(metadata, check_integrity):
        exit_status = 1

    sys.exit(exit_status)
