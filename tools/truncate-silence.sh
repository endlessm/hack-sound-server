#!/bin/bash -e
tools_path=$(dirname "$0")

usage() {
    echo "Usage: $0 [OPTION] [FILE]" 1>&2;
    echo "Truncates silence from the start or the end of an audio file"
    echo "    -c    Check ffmpeg." 1>&2;
    echo "    -s    Truncate files from the start of the stream." 1>&2;
    echo "    -e    Truncate files from the end of the stream." 1>&2;
    echo "    -r    Amplitud ratio. Samples with lower amplitud than this ratio will be removed." 1>&2;
    exit 1;
}

check_ffmpeg=true
truncate_start=false
truncate_end=false
ratio=0.005

while getopts ":cser:" opt; do
    case "${opt}" in
    c)
        check_ffmpeg=true
        ;;
    s)
        truncate_start=true
        ;;
    e)
        truncate_end=true
        ;;
    r)
        ratio=${OPTARG}
        ;;
    *)
        usage
        ;;
    esac
done;
shift $((OPTIND-1))

if ${check_ffmpeg}; then
    $tools_path/check-ffmpeg.sh --ffmpeg
fi

if ${truncate_start}; then
    ffmpeg -y -i "$1" -af silenceremove=1:0:$ratio "$1"
fi

if ${truncate_end}; then
    ffmpeg -y -i "$1" -af "areverse" "$1"
    ffmpeg -y -i "$1" -af silenceremove=1:0:$ratio "$1"
    ffmpeg -y -i "$1" -af "areverse" "$1"
fi
