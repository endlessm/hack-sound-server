#!/bin/bash -e
tools_path=$(dirname "$0")

usage() {
    echo "Usage: $0 [FILE]" 1>&2;
    echo "Gets the duration in seconds" 1>&2;
    echo "    -c    Check ffprobe." 1>&2;
    exit 1;
}

check_ffmpeg=false
while getopts ":cser:" opt; do
    case "${opt}" in
    c)
        check_ffprobe=true
        ;;
    *)
        usage
        ;;
    esac
done;
shift $((OPTIND-1))

if $check_ffprobe; then
    $tools_path/check-ffmpeg.sh --ffprobe
fi

ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$1"
