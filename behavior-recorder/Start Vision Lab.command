#!/bin/zsh
set -eu
cd -- "$(dirname -- "$0")"
if [[ ! -x .venv-vision/bin/python ]] || ! command -v ffmpeg >/dev/null; then
  print '영상 분석 환경(.venv-vision)과 FFmpeg가 필요합니다. README의 설치와 실행 환경을 확인하세요.'
  exit 1
fi
print '관찰 실험실을 시작합니다. 이 터미널을 닫으면 분석 서버가 종료됩니다. 종료: Ctrl+C'
exec .venv-vision/bin/python -m behavior_recorder.vision_lab --open-browser "$@"
