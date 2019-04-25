#!/bin/bash
tools_path=$(dirname "$0")

source "$tools_path/check-ffmpeg.sh"
if ! check_ffmpeg; then
    exit 1
fi

usage() {
    echo "Usage: $0 [OPTION] [ARGS]" 1>&2;
    echo "Truncates silence from the start or the end of an audio file" 1>&2
    echo "    -h | --help       Help." 1>&2
    echo "    -i[:path]         Path of the input file." 1>&2
    echo "    -s                Truncate silence from the start of the stream." 1>&2
    echo "    -e                Truncate silence from the end of the stream." 1>&2
    echo "    -r[:ratio]        Amplitude ratio. Samples with lower amplitude than this ratio will be removed." 1>&2
    exit 1
}

reverse()
{
    local tmp_file=$(dirname "$input_file")/tmp-$(basename "$input_file")
    ffmpeg -y -i "$input_file" -af "areverse" "$tmp_file"
    mv "$tmp_file" "$input_file"
}

silence()
{
    local tmp_file=$(dirname "$input_file")/tmp-$(basename "$input_file")
    ffmpeg -y -i "$input_file" -af silenceremove=1:0:$ratio "$tmp_file"
    mv "$tmp_file" "$input_file"
}

input_file=
truncate_start=false
truncate_end=false
ratio=0.005

opts=$(getopt \
    --longoptions "help" \
    --name "$(basename "$0")" \
    --options "cser:i:h" \
    -- "$@"
)

while true; do
  case "$1" in
    -s)
        truncate_start=true
        ;;
    -e)
        truncate_end=true
        ;;
    -r)
        ratio="$2"
        shift
        ;;
    -i)
        input_file="$2"
        shift
        ;;
    -h | --help)
        usage
        ;;
    *)
        break;;
    esac
    shift
done;

if [ -z "$input_file" ]; then
    echo "An input file is required." 1>&2
    exit 1
fi

if ${truncate_start}; then
    silence
fi

if ${truncate_end}; then
    reverse
    silence
    reverse
fi
