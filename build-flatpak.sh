#!/bin/bash
set -e
set -x

rm -rf files var metadata export build

source_dir="$(git rev-parse --show-toplevel)"
GIT_CLONE_BRANCH="HEAD" ./tools/build-local-flatpak.sh --install
