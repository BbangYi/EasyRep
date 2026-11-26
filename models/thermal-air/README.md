# 공간 온도 추정과 열부하 계산

정본 코드는 `gateway/`에 있습니다. 이 폴더의 [manifest.json](manifest.json)은 계산 방식과 적용 범위를 기록하며 실행 코드나 학습 가중치를 복제하지 않습니다.

| 기능 | 정본 | 현재 범위 |
|---|---|---|
| Pi 공간 온도 추정 | [model.py](../../gateway/habitat/digital_twin/air/model.py) | T1·T2·T3의 온도와 시각으로 3차원 온도장 추정 |
| 모델 설정 | [air-viewer.json](../../gateway/configs/examples/air-viewer.json) | 사육장·센서 좌표·유효 범위·신선도 예제 |
| 수식·구현 설명 | [기술보고서](../../gateway/docs/air-temperature-technical-report.md) | 이류·확산·벽면 열교환·센서 잔차 보정 |
| 열부하·전력 계산 | [thermal-sizing.py](../../gateway/docs/hardware-design/thermal-sizing.py) | 벽체·환기·잠열·이슬점·전력의 가정 기반 민감도 계산 |

현재 공간 모델은 **20×20×30 cm**만 지원합니다. 2 cm 격자에서 계산하고 1 cm 표시 격자로 보간합니다. 첫 입력과 긴 수신 공백 뒤에는 역거리제곱 보간으로 시작하며, 연속 입력 사이에는 가정한 이류·확산과 벽면 열교환을 계산한 뒤 새 센서값의 잔차로 보정합니다. 풍속·경계 조건·기본 센서 위치는 실측된 유동장이나 공간 정확도 검증을 대신하지 않습니다. 습도장·미래 온도·동물 체온을 산출하는 모델도 아닙니다.

두 계산에는 학습 가중치 파일이 없습니다. 저장소 루트에서 열부하 계산만 실행하려면:

```sh
python3 gateway/docs/hardware-design/thermal-sizing.py
```

이는 출력 수치를 계산할 뿐 장치를 제어하지 않습니다. Pi 실시간 표시의 설치·설정은 기존 `gateway/apps/air/`와 배포 안내를 사용합니다. 공간 모델을 다른 사육장 크기로 확장할 때는 코드의 치수 가정과 검증을 함께 변경해야 합니다.
