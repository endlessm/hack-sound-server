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

ffmpeg_missing_msg()
{
    echo "Please install a build of ffmpeg with the 'webm muxer' and 'libopus encoder'"
    echo "Check the documentation for your distribution or visit https://ffbinaries.com/downloads"
}

check_ffmpeg() {
    if command -v ffmpeg > /dev/null; then
        return 0
    fi
    echo "ffmpeg is not installed in PATH."
    echo
    ffmpeg_missing_msg

    return 1
}

check_ffmpeg_codecs() {
    if ! check_ffmpeg; then
        return 1
    fi

    local webm_available=$(ffmpeg -hide_banner -muxers | tr -s " " | cut -f2,3 -d" " | grep -e "^E webm$")
    local libopus_available=$(ffmpeg -hide_banner -encoders | tr -s " " | cut -f2,3 -d" " | grep -e "^A..... libopus$")

    if [[ -z "$webm_available" || -z "$libopus_available" ]]; then
        echo "Your ffmpeg build doesn't have the proper codecs"
        echo
        ffmpeg_missing_msg
        return 1
    fi
    return 0
}
