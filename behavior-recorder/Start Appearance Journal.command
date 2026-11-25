#!/bin/zsh
set -eu
cd -- "$(dirname -- "$0")"
print '탈피 관찰 기록을 시작합니다. 카메라·모델·FFmpeg는 필요하지 않습니다. 종료: Ctrl+C'
exec python3 -m behavior_recorder.vision_lab --appearance-only --port 8768 --storage data/appearance-journal-local --open-browser "$@"
