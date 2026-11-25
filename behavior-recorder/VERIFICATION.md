# 검증 결과 — 2026-10-08

아래는 수집기 최초 구현의 21개 테스트 기록입니다. 이후 추가한 특징·모델 파이프라인과 전체 40개 테스트 결과는 [AI_VERIFICATION.md](AI_VERIFICATION.md)에 있습니다. `data/verification.json`의 소스 해시는 최초 수집기 검증 시점의 snapshot입니다.

Python 3.12.14, macOS arm64, FFmpeg 9.0.1에서 확인했습니다. 실제 동물·카메라 데이터는 사용하지 않았습니다.

## 결과

- `python3 -m unittest discover -s tests -v`: **21개 통과**, 테스트 보고 시간 2.058초.
- 보관된 시나리오: 160×120 MPEG-4 합성 영상, 5 fps, 2초, **10프레임**.
- 수집 시작/종료, 체크섬 검사, 원본 프레임 PTS, 관측불가 수동 라벨 1건, 합성 센서 1건, 원단위 열화상 배열 1건을 기록했습니다.
- 라벨 JSONL 내보내기 후 다시 가져왔을 때 중복 추가 0건입니다.
- 원본과 모든 확정 기록을 ZIP으로 내보내고 복원한 폴더를 다시 이동했습니다. 이동 후 integrity 검사 통과, headless 재생 종료 코드 0입니다.
- 이동 후 새 라벨 작성·이전 라벨 대체·재내보내기도 자동 테스트에서 통과했습니다.
- H.264 B-frame 및 0이 아닌 시작 PTS의 별도 2초 합성 파일도 10프레임·원본 PTS·상대시간 보존을 확인했습니다.
- `config.pi.json`으로 만든 real 세션의 영상·라벨·센서·열화상은 모두 **0건**입니다. 카메라가 `unconfigured`이면 입력을 거절합니다.

## 실패 경로

다음은 한정된 입력 또는 실패 주입을 사용했습니다. 실제 저장장치를 가득 채우거나 전원을 끄지 않았습니다.

- 입력 중복 재처리와 동일 ID 충돌, 잘못된 설정·출처·revision·경로
- clip sequence 누락, PTS 누락/역행/간격, 불확실한 촬영시각
- 원본 체크섬 손상, 없는 파일, 용량 한도와 디스크 잔여 공간 부족
- 복사 중 쓰기 오류, probe 중단, manifest 확정 실패
- 미확정 entry를 정상 자료에서 제외하고 quarantine으로 보존
- 실제 별도 CLI 프로세스에서 파일 입력 idle/resumed 확인 후 **SIGTERM** 전송: 종료 코드 130, `interrupted` 기록
- 센서 raw payload·별도 수신시각·unit·quality·revision 보존
- RGB/컬러 영상의 수치 열화상 입력 거절, 결측 배열 보존
- 라벨 범위·개체 ID·불확실성·대체 이력, BORIS TSV fixture
- ZIP 경로 이탈과 용량 한도 거절

## 보관된 증거

- [기계 판독 검증 결과](data/verification.json)
- [전체 테스트 로그](data/test-results.txt)
- [이동 후 세션 manifest](data/moved/manifest.json)
- [실데이터 0건 세션 manifest](data/pi-empty/manifest.json)
- [휴대용 ZIP](data/demo.zip): 31,304 bytes
- 세션 ID: `aca8069b-64c4-49ef-b600-01de300194d3`
- clip ID: `d698a7d4-bcd0-4315-ae93-5c0743f79d40`
- 원본 SHA-256: `4a7716c086eb78fe112db3f05e9cdc4cf0202dc62c046c7e4a5cbb9b6f3bc2b3`
- ZIP SHA-256: `2edec86e80ea9cbc856a2b4f815a9f5a479aa632e836ca31ce2155646c16f8ae`

`data/`는 `.gitignore` 대상이며 위 파일은 현재 로컬 작업 결과입니다. 테스트마다 생기는 임시 fixture는 테스트가 정리합니다.

## 남은 검증

Linux/Pi 실행, 실카메라·실센서·수치 열화상 SDK, 장시간 저장·실제 전원 차단, 화면 재생, 실제 BORIS 앱 왕복은 미검증입니다. 하드웨어 동기화와 촬영시각 정확도를 측정하지 않았습니다. 운영 서버 접속·배포·DB 변경·장치 제어·상시 녹화·모델 학습은 수행하지 않았습니다.

카메라가 준비되면 먼저 모델/인터페이스를 확인하고 Pi에서 **10초짜리 원본 구간 한 개**를 만들어 파일 입력 계약에 연결합니다. 이후 PTS·촬영시각·온도/CPU·저장량·단절 복구를 실제 장비에서 확인합니다.
