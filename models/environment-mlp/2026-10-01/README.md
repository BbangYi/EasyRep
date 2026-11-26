# 사육장 환경 예측 MLP

최근 환경 기록과 가상의 분무 계획을 바탕으로, 앞으로 60분 동안의 온도와 습도 변화를 예측하는 모델입니다. 이 폴더에는 온도 센서 구성별 학습 가중치와 학습 기록이 들어 있습니다.

> [!IMPORTANT]
> 이 모델은 **합성 데이터로만 학습**했으며 실제 사육장 환경에서 검증되지 않았습니다. 예측 결과는 시뮬레이션·관찰 용도로만 사용하고, 실제 장치의 제어 명령이나 안전 판단에 사용하지 마세요.

## 빠르게 확인하기

현재 모델은 별도 브랜치에 있습니다. Linux 또는 Windows의 WSL에서 아래 명령으로 파일을 받아 무결성을 확인할 수 있습니다.

```bash
git clone --branch codex/environment-mlp-weights-20261001 https://github.com/BbangYi/EasyRep.git
cd EasyRep/models/environment-mlp/2026-10-01
sha256sum --check SHA256SUMS
```

네 파일 모두 `OK`로 표시되면 저장된 파일이 기록된 SHA-256과 일치합니다. 이 확인은 **파일이 기록된 해시와 일치하는지 확인하는 과정**이며, 추론이 정상 동작하거나 실제 환경에서 정확하다는 뜻은 아닙니다.

> 이 브랜치는 모델 파일 보관용입니다. 학습·추론 코드는 현재 [Gateway·펌웨어 브랜치](https://github.com/BbangYi/EasyRep/tree/jaysj0226/gateway-firmware-models)에 별도로 있습니다.

## 들어 있는 파일

| 파일 | 용도 |
| --- | --- |
| [model_1sensors.npz](model_1sensors.npz) | 온도 센서 1개 구성의 가중치 |
| [model_2sensors.npz](model_2sensors.npz) | 온도 센서 2개 구성의 가중치 |
| [model_3sensors.npz](model_3sensors.npz) | 온도 센서 3개 구성의 가중치. 현재 Gateway 브랜치의 CUDA 추론 코드가 사용 |
| [training_report.json](training_report.json) | 학습 시점, 데이터 분할, 검증 손실, 소스와 가중치 해시 |
| [SHA256SUMS](SHA256SUMS) | 가중치 3개와 학습 보고서의 무결성 확인값 |

각 가중치는 약 271 KiB입니다. 학습 데이터 원본과 중간 체크포인트는 포함하지 않습니다.

## 모델은 무엇을 예측하나요?

```text
최근 30분의 환경·분무 기록 + 앞으로 60분의 가상 분무 계획
                              ↓
                        환경 예측 MLP
                              ↓
      앞으로 60분의 공기 온도·습도·따뜻한 면 온도·차가운 면 온도
```

입력 기록은 1분 간격이며, 미래 입력에는 **후보 분무 동작만** 사용합니다. 미래의 센서 측정값이나 날씨를 미리 안다고 가정하지 않습니다. 출력은 미래 **예측값**으로, 현재 센서의 실측값과 구분해야 합니다.

모델 구조는 `210 → 128 → 128 → 240`이며 은닉층에 `tanh` 활성화 함수를 사용합니다. 210개 입력은 30분 이력 150개와 후보 동작 60개로, 240개 출력은 60분 × 4개 예측 채널로 구성됩니다.

## 학습과 검증 기록

2026년 10월 1일에 합성 데이터로 학습했습니다. 각 모델은 학습 구간 15,680개와 검증 구간 2,352개를 사용했으며, **검증 손실이 가장 낮은 시점**의 가중치를 선택했습니다.

| 온도 센서 구성 | 선택된 학습 epoch | 검증 손실: 스케일된 MSE |
| --- | ---: | ---: |
| 1개 | 109 | 0.007908 |
| 2개 | 120 | 0.003853 |
| 3개 | 105 | 0.003773 |

위 값은 스케일된 검증 손실로, 섭씨 온도 오차나 습도 오차를 직접 나타내지 않습니다. 실측 데이터 성능은 아직 확인되지 않았습니다. 자세한 데이터 분할과 원래 수치는 [학습 보고서](training_report.json)를 참고하세요.

## Gateway·GPU 연동 상태

- 가중치와 학습 보고서의 해시는 GPU 데스크탑 원본 및 GitHub에 저장된 파일과 각각 대조했습니다.
- 확인한 Gateway 브랜치의 학습·추론 코드와 설정은 **학습 보고서에 기록된 당시 파일과 해시가 다릅니다**. 해시가 다르다는 사실만으로 호환 불가라고 단정할 수는 없으며, 모델 로딩과 추론을 별도로 검증해야 합니다.
- Gateway 코드는 `HABITAT_ENV_MODEL_DIR` 환경 변수로 모델 디렉터리를 지정합니다. 운영·평가 파일은 저장소 밖의 실행 디렉터리에서 관리하고, Pi·GPU·SaaS의 설정은 각 환경에 맞게 구성하세요.
- 두 브랜치를 통합할 때 Gateway 쪽 모델 명세와 README의 **원본 확인 대기** 상태를 갱신해야 합니다.


### 추론 코드와 함께 검증하기

두 브랜치를 통합하거나 Gateway 코드가 준비된 환경에서, 가중치 세 개와 학습 보고서를 저장소 밖의 같은 실행용 모델 폴더에 준비하세요. 다음은 GPU 데스크탑의 기존 모델 경로를 사용하는 예시입니다. 다른 환경에서는 경로를 변경하고 Python과 NumPy를 준비해야 합니다.

```bash
export HABITAT_ENV_MODEL_DIR="$HOME/.local/share/habitat-gpu/models/environment"
cd gateway
python3 experiments/environment_sim/predictive_misting.py --evaluate --check
```

이 명령은 합성 데이터로 평가·검사를 실행하고 `prediction_results.json`과 `prediction_checks.json`을 모델 폴더에 기록합니다. **이번 업로드에서는 이 명령을 실행하지 않았으므로**, Gateway 코드와 가중치의 호환성이나 실행 성공을 확인한 것은 아닙니다.

<details>
<summary>학습 당시 파일과 Gateway 브랜치의 SHA-256 비교</summary>

비교한 Gateway 커밋: [`58d7a7b`](https://github.com/BbangYi/EasyRep/commit/58d7a7bcff44226ad0c437948f8e4232f63ce885)

| 파일 | 학습 당시 보고서 | Gateway 브랜치 |
| --- | --- | --- |
| `predictive_misting.py` | `547efea658c3ae3870cee9b5eca4d4defe1921777a545feab64e37956f9c629c` | `9c97f1a7f36c361d8ec38aec04518be81f6ab289e195eb768a0949bac1773074` |
| `simulation_config.json` | `2d2f282603cc921c4e1e40ef060696a8861ada1b7cdb783d4639be1dc826c178` | `1d8666c0589904f960350fa37a03d400c7386b4738bae43169b65f68e62041be` |

</details>
