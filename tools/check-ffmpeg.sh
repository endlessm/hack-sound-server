#!/bin/bash

usage() {
    echo "Usage: $0" 1>&2;
    echo "Checks if ffmpeg tools are installed" 1>&2;
    echo "    --fprobe    Check ffmpeg with the needed encoders." 1>&2;
    echo "    --ffmpeg    Check ffprobe." 1>&2;
    exit 1;
}

check_ffprobe=false
check_ffmpeg=false

opts=$(getopt \
    --longoptions "ffmpeg,ffprobe" \
    --name "$(basename "$0")" \
    --options "" \
    -- "$@"
)
eval set --$opts

while true; do
  case "$1" in
    --ffprobe)
        check_ffprobe=true
        ;;
    --ffmpeg)
        check_ffmpeg=true
        ;;
    --)
        shift
        break;;
  esac
  shift
done

have_ffmpeg=1
have_ffprobe=1

if $check_ffmpeg; then
    if command -v ffmpeg > /dev/null; then
        webm_available=$(ffmpeg -hide_banner -muxers\
                                | tr -s " " | cut -f2,3 -d" " | grep -e "^E webm$")
        libopus_available=$(ffmpeg -hide_banner -encoders \
                                | tr -s " " | cut -f2,3 -d" " | grep -e "^A..... libopus$")
        if [[ -z "$webm_available" || -z "$libopus_available" ]]; then
            echo "Your ffmpeg build doesn't have the proper codecs"
            have_ffmpeg=0
        fi
    else
        echo "ffmpeg is not installed in PATH."
        have_ffmpeg=0
    fi
fi

if $check_ffprobe; then
    if command -v ffprobe > /dev/null; then
        have_ffprobe=1
    else
        have_ffprobe=0
    fi
fi

if [[ $have_ffmpeg -eq 0 ]] || $check_ffprobe && [[ $have_ffprobe -eq 0 ]]; then
    suggest_download() {
        echo "Check the documentation for your distribution or visit https://ffbinaries.com/downloads"
    }

    echo
    if [ $have_ffmpeg -eq 0 ]; then
        echo "Please install a build of ffmpeg with the 'webm muxer' and 'libopus encoder'"
    fi
    if $check_ffprobe && [[ $have_ffprobe -eq 0 ]]; then
        echo "Please install a build of ffprobe"
    fi
    suggest_download
    exit 1
fi
