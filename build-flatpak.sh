#!/bin/bash
set -e
set -x
rm -rf files var metadata export build

BRANCH=${BRANCH:-master}
GIT_CLONE_BRANCH=${GIT_CLONE_BRANCH:-HEAD}

sed \
  -e "s|@BRANCH@|${BRANCH}|g" \
  -e "s|@GIT_CLONE_BRANCH@|${GIT_CLONE_BRANCH}|g" \
  com.endlessm.HackSoundServer.json.in \
  > com.endlessm.HackSoundServer.json

flatpak-builder build --force-clean --install com.endlessm.HackSoundServer.json

