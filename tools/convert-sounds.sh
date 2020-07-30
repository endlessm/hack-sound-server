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

if ! check_ffmpeg_codecs; then
    exit 1
fi

sounds_path=$tools_path/../data/sounds

find "$sounds_path" -type f -iregex ".+\\.wav" | while read -r input; do
    output=${input%.wav}.webm
    ffmpeg \
        -y -i "${input}" -c:a libopus -compression_level:a 10 -b:a 128k -vn "$output" \
        < /dev/null # Avoid ffmpeg take the input that while loop have to read
    rm -v "$input"
done
