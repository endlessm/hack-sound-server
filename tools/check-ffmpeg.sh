#!/bin/bash

check_ffmpeg() {
    if command -v ffmpeg > /dev/null; then
        return 0
    fi
    echo "ffmpeg is not installed in PATH."

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
        echo "Please install a build of ffmpeg with the 'webm muxer' and 'libopus encoder'"
        echo "Check the documentation for your distribution or visit https://ffbinaries.com/downloads"
        return 1
    fi
    return 0
}
