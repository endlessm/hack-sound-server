#!/bin/bash -e
tools_path=$(dirname "$0")
$tools_path/check-ffmpeg.sh --ffmpeg

sounds_path=$tools_path/../data/sounds

find "$sounds_path" -type f -iregex ".+\\.wav" | while read -r input; do
    output=${input%.wav}.webm
    ffmpeg \
        -y -i "${input}" -c:a libopus -compression_level:a 10 -b:a 128k -vn "$output" \
        < /dev/null # Avoid ffmpeg take the input that while loop have to read
    rm -v "$input"
done
