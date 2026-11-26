#!/usr/bin/env bash
set -euo pipefail

model_dir="$HOME/.local/share/habitat-gpu/models/environment"
branch="codex/environment-mlp-weights-20261001"
target="models/environment-mlp/2026-10-01"

if command -v gh >/dev/null 2>&1; then
  gh_cmd=gh
elif command -v gh.exe >/dev/null 2>&1; then
  gh_cmd=gh.exe
else
  printf '%s\n' 'GitHub CLI (gh)를 찾을 수 없습니다. 이 메시지를 Codex에 알려주세요.' >&2
  exit 1
fi
login="$("$gh_cmd" api user --jq .login 2>/dev/null | tr -d '\r' || true)"
if [[ "$login" != 'jaysj0226' ]]; then
  printf '%s\n' "GitHub CLI 계정 확인 실패: ${login:-로그인되지 않음}. jaysj0226 계정이 필요합니다." >&2
  exit 1
fi

(cd "$model_dir" && sha256sum --check -) <<'CHECKSUMS'
6e992f3aa59939e57d1d7e249ee4388e5044e0113c1c37fe55a6da0177eb0038  model_1sensors.npz
3d5fa74a6799652c41ac082974152763d0fc3d7b71280a99e80095e5fd6ffc1a  model_2sensors.npz
7d56293563fff144e8887051d9a83220b6b617b79e66a9fd3708b5bdef82fd3f  model_3sensors.npz
7c69c3c0ec68abab1318b5dc8c4e4c37f1ea1bbbf6b71bf7e8b65cfd48bcc548  training_report.json
CHECKSUMS

python3 - "$model_dir" <<'PY'
import pathlib
import sys
import zipfile

root = pathlib.Path(sys.argv[1])
for sensors in (1, 2, 3):
    path = root / f"model_{sensors}sensors.npz"
    with zipfile.ZipFile(path) as archive:
        bad_file = archive.testzip()
        if bad_file or not archive.namelist():
            raise SystemExit(f"Invalid model archive: {path.name}: {bad_file}")
        print(f"{path.name}: archive OK ({len(archive.namelist())} entries)")
PY

tmp_parent="$(cd "${TMPDIR:-/tmp}" && pwd -P)"
work_dir="$(mktemp -d -- "$tmp_parent/easyrep-mlp.XXXXXXXX")"
case "$work_dir" in
  "$tmp_parent"/easyrep-mlp.*) ;;
  *) printf '%s\n' '임시 작업 경로를 확인할 수 없습니다.' >&2; exit 1 ;;
esac
trap 'rm -rf -- "$work_dir"' EXIT

git_auth=(-c credential.helper= -c "credential.helper=!$gh_cmd auth git-credential")
git "${git_auth[@]}" clone --quiet --no-tags --single-branch --branch "$branch" \
  https://github.com/BbangYi/EasyRep.git "$work_dir/repo"
cd "$work_dir/repo"

for sensors in 1 2 3; do
  cp -- "$model_dir/model_${sensors}sensors.npz" "$target/"
done
(cd "$target" && sha256sum --check SHA256SUMS)

git rm -- "$target/upload-from-ubuntu.sh"
git add -f -- "$target/model_1sensors.npz" "$target/model_2sensors.npz" "$target/model_3sensors.npz"
git diff --cached --check
git diff --cached --stat
git -c user.name='jaysj0226' -c user.email='95292789+jaysj0226@users.noreply.github.com' \
  commit -m 'Add trained environment MLP weights'
git "${git_auth[@]}" push origin "HEAD:refs/heads/$branch"
printf '\nPUSHED_COMMIT=%s\n' "$(git rev-parse HEAD)"
