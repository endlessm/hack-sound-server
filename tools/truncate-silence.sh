#!/bin/bash
##
## Copyright © 2020 Endless OS Foundation LLC.
##
## This file is part of hack-sound-server
## (see https://github.com/endlessm/hack-sound-server).
##
## This program is free software; you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation; either version 2 of the License, or
## (at your option) any later version.
##
## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.
##
## You should have received a copy of the GNU General Public License along
## with this program; if not, write to the Free Software Foundation, Inc.,
## 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
##
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
