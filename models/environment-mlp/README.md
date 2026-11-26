# 합성 환경 MLP

**현재 상태: 최종 가중치와 학습 보고서의 원본 확인 대기.** 이 폴더에는 [전달 manifest](manifest.json)가 있으며, 아직 완전한 추론 묶음이 아닙니다. Pi의 기본 모델 폴더와 기존 사용자 모델 경로에서 원본을 찾지 못했습니다. GPU의 파일을 확인하기 전에는 크기·해시·실제 학습 버전을 채우지 않습니다.

정본 [predictive_misting.py](../../gateway/experiments/environment_sim/predictive_misting.py)는 가정한 온습도·표면온도 Plant, 합성 데이터 생성, PyTorch 학습, NumPy 추론과 평가를 포함합니다. MLP는 `210 → 128 → 128 → 240`, 은닉층은 tanh이며 30분 이력과 60분 후보 분무 동작으로 60분의 네 채널을 예측합니다. 1·2·3개 온도센서 입력 변형을 학습하고, 현재 [CUDA worker](../../gateway/experiments/environment_sim/gpu_predict.py)는 3센서 모델을 사용합니다.

입력 스케일의 분무 시간 기준은 기존 가중치 호환을 위해 6초로 유지되지만, 현재 [실험 설정](../../gateway/experiments/environment_sim/simulation_config.json)의 후보 RUN은 최대 3초입니다. 이 차이를 임의로 바꾸지 않습니다. Plant 계수·분무 효과는 실측 보정 전의 가정이고 결과는 `SIMULATION_ONLY` 또는 `SHADOW_ONLY`입니다. 모델의 제안을 실물 동작 승인으로 사용하지 않습니다.

Pi 요청·결과 검증은 [`habitat/compute/environment.py`](../../gateway/habitat/compute/environment.py), GPU API·프로세스 수명은 [`habitat/gpu/environment_api.py`](../../gateway/habitat/gpu/environment_api.py)가 담당합니다. 데이터셋 생성과 예측 평가 코드는 같은 `gateway/habitat/compute/`에 있으며, 이 코드의 존재가 실측 데이터로 재학습한 모델이 있다는 뜻은 아닙니다.

## 원본 확보 후 기록할 항목

최종 파일은 정확히 `model_1sensors.npz`, `model_2sensors.npz`, `model_3sensors.npz`, `training_report.json`입니다. 각 파일의 SHA-256·바이트 수, 모델 버전과 실제 저장 위치를 manifest에 기록합니다. 학습 보고서의 모델별 `weights_sha256`을 원본 파일과 대조하고, 학습 소스·설정 해시, 학습 시각, 데이터 분할, 선택 epoch와 검증 손실을 보존합니다. 현재 소스와 학습 당시 소스가 다르면 그 차이를 명시하며 새 학습으로 덮어쓰지 않습니다. GPU 추론에는 특히 3센서 가중치와 보고서의 일치가 필요합니다.

작은 최종 파일은 검토된 버전 디렉터리에 한정해 Git에 포함하고, 크기상 별도 배포가 필요하면 Release asset의 URI·해시·크기를 기록합니다. 그 결정 전에는 가짜 파일·빈 가중치·추정 해시를 추가하지 않습니다. 원본 학습 데이터와 중간 체크포인트는 이 폴더에 넣지 않습니다.

## 검증된 버전 실행

원본 확인 후 네 파일을 **소스 밖의 모델 실행 디렉터리**에 준비합니다. 아래 `VERIFIED_VERSION`은 실제 검증한 버전으로 바꾸며 현재 존재하는 버전 이름이 아닙니다. 평가 과정은 같은 디렉터리에 결과 JSON을 쓰므로 Git 소스 폴더를 실행 출력 경로로 사용하지 않습니다. NumPy와 기존 모델 실행 환경이 필요합니다.

```sh
cd gateway
export HABITAT_ENV_MODEL_DIR="/absolute/runtime/models/environment-mlp/VERIFIED_VERSION"
python3 experiments/environment_sim/predictive_misting.py --evaluate --check
```

이 명령은 기존 가중치를 평가하며 새 학습이나 장치 제어를 실행하지 않습니다. GPU 서비스는 같은 `HABITAT_ENV_MODEL_DIR`을 자식 worker에 전달하고 CUDA 실행 환경을 별도로 사용합니다. [GPU 서비스 안내](../../gateway/docs/operations/gpu-service.md)의 설치·검증 절차를 따르며, 가중치 전달 완료·합성 평가 통과·실물 환경 검증을 구분합니다.
