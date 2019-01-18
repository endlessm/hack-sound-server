#!/bin/bash

have_ffmpeg=1

if command -v ffmpeg > /dev/null; then
    webm_available=$(ffmpeg -hide_banner -muxers | tr -s " " | cut -f2,3 -d" " | grep -e "^E webm$")
    libopus_available=$(ffmpeg -hide_banner -encoders | tr -s " " | cut -f2,3 -d" " | grep -e "^A..... libopus$")

    if [[ -z "$webm_available" || -z "$libopus_available" ]]; then
        echo "Your ffmpeg build doesn't have the proper codecs"
        have_ffmpeg=0
    fi
else
    echo "ffmpeg is not installed in PATH."
    have_ffmpeg=0
fi

if [ $have_ffmpeg -eq 0 ]; then
    echo
    echo "Please install a build of ffmpeg with the 'webm muxer' and 'libopus encoder'"
    echo "Check the documentation for your distribution or visit https://ffbinaries.com/downloads"
    exit 1
fi

set -e

sounds_path=$(dirname "$0")/../data/sounds

find "$sounds_path" -type f -iregex ".+\\.wav" | while read -r input; do
    output=${input%.wav}.webm
    ffmpeg \
        -y -i "${input}" -c:a libopus -compression_level:a 10 -b:a 128k -vn "$output" \
        < /dev/null # Avoid ffmpeg take the input that while loop have to read
    rm -v "$input"
done
