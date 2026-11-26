# Pi 원격 업데이트와 LiveScene 화면 확인

**2026-10-07 Pi 운영 릴리스는 `0.4.14-5a9bc13f4f2f`, GPU 운영 소스도 0.4.14다.**
Pi의 건강 상태 `ok`, MQTT 연결과 설치 파일·모의실험 소스의 해시 일치를 확인했다.
GPU는 서비스 PID 4040·`active`, RTX 4060의 CUDA 준비 상태와 관련 소스 9개 해시를
확인했다. Pi 설정·인증정보와 GPU 설정·인증정보·환경 모델은 보존했다.
[Pi 설치 확인](../../var/reports/commissioning/software-r15-20261007-pi-014.json),
[GPU 적용 확인](../../var/reports/commissioning/software-r15-20261007-gpu-014.json).

## 0.4.14 요청/RUN 계약과 통합 모의실험

이번 버전은 GPU가 선택한 **REQ 유지시간**과 그 요청으로 예상되는 **펌프 RUN 시간**을
구분한다. `schema_version=2`, `timing_mode=r15_request_fixture`,
`timing_profile=r15_esp20_pico_window1ms_phase0_v1`을 양쪽에 적용했다.
REQ 후보를 시간 fixture로 순방향 계산한 RUN 계획으로 기존 환경 모델을 평가한다.
원본 Pico의 RUN 상한 3초는 유지한다. ESP 요청 계약의 상한 5초는 펌프 RUN 5초를
뜻하지 않는다. UI의 ON 초도 요청시간이며, 요청 접수·GPIO 요청·ACK를 실제 분사로
표시하지 않는다. [시간 계약](../protocols/r15-bridge.md).

실제 Pi가 실제 GPU에 요청한 통합 모의실험의 결과는 다음과 같다.

| 항목 | 2026-10-07 확인 결과 |
|---|---|
| 가상 사육장·제어 기간 | 3개 사육장, 120분 가상 진행 |
| 실제 CUDA 예측 응답 | schema 2 응답 360회, 5·10·30·60분 예측 |
| 계획 검사 | 응답 360개의 60분 REQ/예상 RUN 계획 검증 |
| 실제 경과 시간 | 97.068661초 |
| HTTPS 왕복 중앙값 / 최대 | 0.068625초 / 1.925126초 |
| 가상 펌프 실행 | 75회, 종료 시 펌프 OFF·열린 밸브 없음·`idle` |
| Linux 선택 회귀검사 | 208개·하위 검사 141개 통과, 실패 0개, 33.46초 |
| 환경 API 관련 검사 | 동일 구현 3개·하위 검사 38개 통과, 실패 0개, 2.99초 |

[통합 결과와 원본 기록 해시](../../var/reports/commissioning/software-r15-20261007-integration.json),
[검사 명령·범위](../../var/reports/commissioning/software-r15-20261007-checks.json),
[실행 로그](../../var/reports/commissioning/software-r15-20261007-checks.log)를 보존한다.
선택 검사에는 요청/RUN 시간, 잘못된 계약 거절, 만료·중복·재시작·센서 오류와 실제
격리 Mosquitto의 2초·5초 요청 전달을 포함한다. GPU 환경 API 검사도 Pi에서 실행한
API/worker 응답 fixture 검사이며 실제 CUDA 360회와 구분한다. 환경 API 검사 뒤 버전
메타데이터만 바뀌었고 검사한 구현은 동일하다. 이번 횟수를 전체 회귀검사 결과로 확대하지 않는다.

센서값·환경 반응·펌프·밸브는 가상이다. 실행한 가상 RUN 구간만 다음 입력 이력에 쓰며,
REQ 유지시간이나 예상 RUN을 실측 이력으로 바꾸지 않는다. 물 토출량은 측정하지 않았다.
선택한 미래 계획은 보존하지만 이후 재계획으로 동작이 달라지므로 이번 운전의 예측 정확도는
채점하지 않았다. 모델은 `SYNTHETIC_ONLY`, `field_validated=false`,
`hardware_execution_allowed=false`다. 운영 DB 쓰기·MQTT 출력·SaaS 데이터 전송 없이
별도 모의실험을 수행했다. 통신·제어 흐름의 검증이며 실제 사육장 성능·3D 복원 품질의
합격 결과가 아니다.

신판 ESP32 스케치도 Pi에서 센서형·N1 중앙형 두 역할 모두 대상 빌드를 통과했다.
CLI 1.5.1·ESP32 core 3.3.12와 고정 라이브러리를 사용했고, 두 역할 모두
`HABITAT_R15_REQUEST_OUTPUTS=0`으로 빌드했다. 업로드는 하지 않았으며 임시 toolchain은
삭제했다. [대상 빌드 결과](../../var/reports/commissioning/esp32-target-build-20261007.json).
대상 빌드와 격리 MQTT 검사를 실제 ESP/Pico GPIO·무선·펌프 시험으로 해석하지 않는다.
실물 시험은 0건이며 운영 출력 잠금을 유지한다.

현재 릴리스와 직전 복구용 릴리스만 보존한다. 이번 관측에서는 `current`가
`0.4.14-5a9bc13f4f2f`, `previous`가 `0.4.13-a1337300e296`이고 관리 릴리스도 이 두 개다.
현재·직전 릴리스의 wheels는 다음 offline 설치와 복구를 위해 유지한다.
새 매장 등록용 `connect.sh`를 다시 실행하거나 운영 DB·설정·모델을 초기화하지 않는다.

**SaaS 하트비트는 정상이고 이벤트 동기화는 아직 완료되지 않았다.** 실제 `/v1/cloud`
확인 시각은 `2026-10-07T05:42:47Z`, 최근 하트비트 ACK는
`2026-10-07T05:42:44.867608Z`이며 하트비트 오류는 없다. 기존 sequence 1 이벤트의
UUID·본문 해시를 보존했고 대기 이벤트는 1개다. 이벤트 성공 시각은 `null`, ACK 최고
순번은 0, 서버 최고 순번은 미확인이다. 연속성 상태는 `blocked`·
`cloud_continuity_unverified`다. [실제 SaaS 연결 상태](../../var/reports/commissioning/software-r15-20261007-cloud.json).
하트비트나 GPU 모의실험 성공을 이벤트 전달로 해석하지 않는다. 서버 확인 또는 원래 DB
확보가 필요하다. [복구 조건](../saas-integration.md)을 따르며 순번을 임의로 바꾸지 않는다.

## 0.4.13 UI 요청시간 표시와 Pi 확인 (과거)

2026-10-06에는 `0.4.13-a1337300e296`의 건강 상태 `ok`, MQTT 연결과 오류 없는
하트비트 ACK, 관련 검사 15개·하위 검사 21개 통과를 확인했다. 당시 GPU는 오프라인이었고
사용자 요청으로 확인을 미뤘다. 아래 기록은 당시 상태이며 위 0.4.14 검증과 구분한다.
[당시 Pi 배포](../../var/reports/commissioning/software-r15-20261006-request-semantics-deployment.json),
[당시 연결 상태](../../var/reports/commissioning/software-r15-20261006-request-semantics-connectivity.json).

아래 2026-10-05의 양쪽 0.4.12 확인과 전체 검사 결과도 당시의 이력이다.

**2026-10-05 Pi 운영 릴리스 `0.4.12-76a2b5356b9c`의 설치와 서비스 건강 상태 `ok`, MQTT 연결을 확인했다. GPU의 실제 API 서비스 소스도 0.4.12이다.** Pi 확인 시각은 `2026-10-05T13:13:25.834393+00:00`, GPU는 `2026-10-05T13:13:12.302080+00:00`이다. GPU의 Splatfacto 복원 상태는 `ok`, CUDA와 복원 실행 환경은 준비 상태다. 수동 업데이트나 새 매장 등록용 `connect.sh`를 다시 실행하지 않는다. [Pi 0.4.12 배포 확인](../../var/reports/commissioning/software-r15-20261005-active-reservation-deployment.json), [GPU 0.4.12 서비스 확인](../../var/reports/commissioning/software-r15-20261005-active-reservation-gpu.json)에 실제 상태를 보존한다.

`hardware_outputs_enabled=false`와 R15 출력 잠금을 유지한다. 센서·ESP32·Pico·펌프·밸브를 조립해 실제 기동한 상태가 아니다. Pi 설치와 GPU 통신 검증을 실물 제어 완료로 해석하지 않는다.

**SaaS의 기존 `sequence=1` 충돌은 미해결이며 대기 이벤트 1개를 보존 중이다.** 0.4.12에서 같은 Pi 서비스의 실제 하트비트 ACK `2026-10-05T13:13:24.986376+00:00`와 하트비트 오류 없음을 확인했다. 이벤트의 순번·UUID·본문 해시는 배포 전후 동일하다. 이벤트는 `cloud_continuity_unverified`로 차단되며 `last_event_success_at=null`이다. `last_heartbeat_success_at`은 연결 확인이며 이벤트 완료를 뜻하지 않는다. 실제 서버 최고 순번 또는 원래 DB가 필요하다. [복구 조건](../saas-integration.md)을 따르며, 현재 순번을 임의로 바꾸지 않는다.

## 0.4.12 R15 자기 예약으로 인한 취소 수정 (과거)

정상 ON 요청이 만든 공용 예약을 주기적인 안전 검사에서 새로운 요청의 진입 제한과
혼동해 곧바로 OFF를 발행하는 버그를 재현했다. 0.4.11 코드에 적용한 회귀검사에서
`hello_pending`·`hello_active` 두 경우 모두 기대한 `['on']` 대신 `['on','off']`가 나와
**2개 실패·0.13초**였다. [수정 전 재현](../../var/reports/commissioning/software-r15-20261005-active-reservation-baseline.log).

0.4.12는 추가 ON의 busy/공용 예약 진입 검사와 진행 중 요청의 안전 검사를 분리한다.
정상 자기 예약은 250ms `step()` → `tick()`에서 취소 사유가 아니며, 센서 stale/invalid,
상태 핀 LOW, 세션·lease 상실, 연결 끊김과 STOP은 기존 정지 조건을 유지한다.
OFF의 `requested`도 물리 OFF 확인이 아니며 `actual_state=null`을 유지한다.
[R15 계약](../protocols/r15-bridge.md).

수정 후 관련 검사 **46개 통과·1.29초**, 전체 검사 **396개 통과·7개 건너뜀·subtest
231개 통과·108.99초**를 확인했다. [관련 검사 로그](../../var/reports/commissioning/software-r15-20261005-active-reservation-tests.log),
[전체 결과·실제 Pi 설치 확인](../../var/reports/commissioning/software-r15-20261005-active-reservation-deployment.json).
설치된 `gateway.py`·`transport.py`의 해시가 개발 소스와 일치하며, Pi의 비공개 설정·
인증 파일은 바이트 그대로 보존했다. 실물 출력과 R15 브리지는 비활성이고 센서 관측은 없다.
카메라 3개의 정확한 예상 모델명과 USB 연결 대기 상태도 유지한다.

GPU는 22:07:56 KST에 시작한 PID 2854로 `active/running`·종료 상태 0이며,
GPU·환경·LiveScene health는 모두 HTTP 200이다. 이번 수정에서 실제 센서·물리 출력 시험,
카메라 FPS 측정, 새 학습·렌더는 수행하지 않았다. GPU 설정·인증정보·원본 모델도 변경하지 않았다.

## 0.4.11 카메라 모델명 적용 (과거)

`CameraConfig.expected_model`은 기본값이 `None`인 선택 메타데이터다. 예상 구매 모델명을
기록하며 USB VID/PID 확인이나 자동 하드웨어 식별 기능이 아니다. 이번 실제 Pi 설정에서는
카메라 3개의 해당 값만 `SMG-A USB-OV5628-A (OV5693, Auto Focus/120deg)`로 맞췄다.
세 카메라 모두 `waiting_usb_port_binding`이며 실물 촬영·FPS 측정은 수행하지 않았다.

관련 카메라/API 선택검사 **11개가 0.74초에 통과**했고 예제 설정 검사도 통과했다.
이는 아래 0.4.10 전체 검사와 별도 결과이며 새 버전 전체 회귀검사를 재실행했다는 뜻이 아니다.
GPU에서는 관련 소스 5개 파일의 해시 일치와 서비스 `active/running`·PID 2723·종료 상태 0을
확인했다. GPU·환경·LiveScene health는 모두 HTTP 200이었다. 이번 변경으로 새 학습이나
렌더를 실행하지 않았고 GPU 설정·인증정보·모델도 변경하지 않았다.
[당시 Pi 적용](../../var/reports/commissioning/software-r15-20261005-camera-model.json),
[당시 GPU 확인](../../var/reports/commissioning/software-r15-20261005-gpu-camera-model.json)을 보존한다.

## 0.4.10 검사와 이전 모의실험 근거 (과거)

| 확인 | 결과와 한계 |
|---|---|
| Pi 0.4.10 최종 회귀 검사 | 386개 통과, 7개 건너뜀, subtest 231개 통과, 110.07초. 건너뛴 항목은 COLMAP 5개·OpenCV 2개다. SaaS 연속성·기록 보존·차단 중 하트비트 검사도 포함한다. |
| 실제 설치 후 확인 | 무인증 API는 401, 실제 분무 ON 요청은 409 `hardware_not_commissioned`였다. 사육장 3개와 3초 상한, R15·하드웨어 출력 잠금, GPU 모델 목록 조회 200·모델 1개를 확인했다. MQTT 연결은 실물 노드 기동이나 센서 수신을 뜻하지 않는다. |
| GPU의 기존 복원 환경 진단 | 해당 두 진단 모듈 13개 통과, 건너뜀 0개. Pi에서 실행하지 못한 7개를 포함한다. CPU 기하 회귀 검사이며 복원 품질 평가는 아니다. |
| Pi → GPU 통합 모의실험 (0.4.8 당시) | 실제 Pi가 GPU에 180회 요청했다. 응답시간 중앙값 66.3ms, 최댓값 2.31초. 가상 분무 41회 후 최종 출력 상태는 OFF였다. 합성 센서·가상 출력 결과이며 실물 분무 횟수가 아니다. |
| GPU 배포 소스 | 실제 GPU API 환경의 버전 `0.4.10`과 개발 PC와의 소스 해시 일치를 확인했다. 분무 RUN 상한은 3초다. |
| RGB 복원 실행 경로 | 출처가 확인되지 않은 RGB 38장으로 COLMAP 재실행 → Splatfacto 50회 학습 → Gaussian PLY 내보내기를 완료했다. 마지막 체크포인트는 step 49다. Backend 실행 120.276초, 전체 검사 127.758초이며 복원 품질이나 최적 학습 횟수를 검증한 결과가 아니다. |
| GPU 렌더 | 등록된 30,000스텝 참조 모델의 요청·렌더 경로를 확인했다. 정적 배경 5,000스텝 모델 또는 실제 사육장 복원 품질을 입증한 결과가 아니다. |

GPU API의 Python 3.12 환경과 기존 복원용 Python 3.10 환경은 분리되어 있다. 새 의존성 설치 없이 각 용도에 맞는 기존 환경에서 확인했다. RGB 원본 해시는 실행 전후 같았으며, 시험 모델·PLY 등 임시 산출물 229,939,070바이트는 정리하고 [복원 실행 요약](../../var/reports/commissioning/software-r15-20261005-reconstruction-smoke.json)만 보존했다. [최종 Pi 검사 로그](../../var/reports/commissioning/software-r15-20261005-final-tests.log), [GPU 진단 로그](../../var/reports/commissioning/software-r15-20261005-gpu-diagnostic-tests.log), [GPU 서비스 운영](gpu-service.md), [프로젝트 관리 기록](project-layout.md)에 근거와 운영 범위를 기록한다.

## 이전 수동 전달 절차 종료

앞서 설치한 `0.4.5-5c831e1bc6e9`에서는 SSH 터널로 40,900바이트 화면의 HTTP 200을 확인했다. 2026-10-04의 `0.4.6-e55b121673e8`에서는 외부 HTTPS 화면과 로컬 사육장 등록을 검증했다. 이들은 이전 설치 기록이며 최신 검증·설치 상태는 이 문서 상단을 따른다.

이전에 Raspberry Pi Connect 원격 셸에서 실행하도록 제공한 `HabitatOS-Pi-0.4.5.pyz`는 소스와 설치 도구만 담은 임시 전달 파일이었다. 모델·촬영 영상·인증키·데이터베이스는 포함하지 않았으며, Pi의 호환 의존성 wheel을 재사용하도록 구성했다.

직접 설치 완료 후 208,661바이트 전달 파일은 해시 확인 뒤 삭제했고, 8766 임시 HTTP 서버도 종료했다. **이전 주소 `http://100.83.10.45:8766/HabitatOS-Pi-0.4.5.pyz`는 더 이상 제공되지 않는다.** 따라서 기존 다운로드·설치 명령은 이 안내에서 제거했다.

이전 파일의 `--inspect`는 패키지 내부 해시 확인, `--check`는 설치 전 환경 확인이었다. 이 결과만으로 설치 성공을 판단하지 않았으며, 0.4.5 직접 설치 후 서비스 검증을 별도로 수행했다. SSH 암호나 API 인증키는 전달 파일에 저장하지 않았다.

## 수동 전달 도구의 동작 기록 (과거)

이전 도구는 패키지 해시·경로와 기존 Pi의 Python·CPU 호환성을 확인하고, 캐시된 wheel로 임시 릴리스를 만든 뒤 기존 설치 도구를 실행하도록 구성했다. 설치 후 건강 상태·매장 식별자를 확인하고 임시 소스·배포 압축파일을 정리하는 방식이었다. 이는 도구의 설계 기록이며 사용자가 수동 설치를 실행했다는 기록은 아니다.

운영 설정은 `/etc/habitat-gateway/gateway.toml`, 인증키는 같은 디렉터리의 `gateway.env`, 실제 데이터는 `/var/lib/habitat-gateway`를 계속 사용한다. 설치기는 현재 릴리스와 직전 복구용 릴리스를 유지한다. 기존 `Desktop/habitat` 개발 소스를 덮어쓰지 않고 운영 릴리스를 갱신한다.

이전 전달 도구는 장치 설치 전 Pi를 대상으로 `hardware_outputs_enabled=false`를 확인하고, 출력이 허용된 설정에서는 중단하도록 구성했다. 직접 설치에서도 출력 잠금을 해제하거나 임의의 장치 매핑을 추가하지 않았다.

## 화면 열기

### 일반 인터넷에서 SSH 개발 접속 — 2026-10-07

사용자 요청에 따라 별도 OpenSSH 서비스 `habitat-ssh-dev.service`를 Pi에 설치했다.
`22222/TCP`에서 `<gateway-user>`의 등록된 공개키만 허용하며, root·비밀번호·키보드 대화식
로그인은 허용하지 않는다. 기존 `ssh.service`의 22번 포트와 HabitatOS 운영 설정은
유지했다. 현재 PC의 기존 Ed25519 공개키를 등록하고 LAN의 22222번 포트에서 키 로그인
`id -un` → `<gateway-user>`를 확인했다. 새 비밀키는 만들거나 Pi에 복사하지 않았다.

공통 설정 원본은 [SSH 설정 예시](../../deploy/ssh-dev.conf.example)와
[별도 서비스](../../deploy/systemd/habitat-ssh-dev.service)다. Pi의 실제 사용자 설정은
`/etc/habitat-gateway/ssh-dev.conf`에 두며, 셸·SFTP·TCP 포워딩을 제공한다.
설치·정책과 외부 접속 확인은 [SSH 검증 기록](../../var/reports/commissioning/external-ssh-20261007.json)을 따른다.

공유기 GAPD-7300의 WAN 주소는 확인 당시 `203.0.113.12`이며 자동 IP 할당이다.
WAN 값과 Pi의 공인 출구 값은 일치했다. 공유기의 UPnP discovery 응답은 받지 못했다.
로그인에는 관리자 암호와 보안코드가 필요하며, 사용자 요청으로 공유기 설정은 직접
진행하도록 안내했다. 사용자가 포트포워딩을 적용한 뒤 휴대폰 핫스팟 등 다른 인터넷에서
접속 성공을 확인했다. 현재 PC에서도 아래 외부 주소로 키 로그인하여 `id -un` → `<gateway-user>`,
Pi 서비스 세 개의 `active`와 건강 상태 `ok`를 확인했다. 같은 외부 경로의 키 없는 로그인은
`Permission denied (publickey)`로 거부됐다. 공유기 설정은 사용자가 수행했으며,
공유기에 다시 로그인하여 규칙 표를 검사한 것은 아니다.

| 공유기 포트포워딩 항목 | 값 |
|---|---|
| 이름 | HabitatOS-SSH |
| 프로토콜 | TCP |
| 외부 포트 시작·끝 | 2222 / 2222 |
| 내부 IP | 192.168.219.103 |
| 내부 포트 시작·끝 | 22222 / 22222 |
| 사용 | 활성화 |

Pi의 유선 주소 `192.168.219.103`은 공유기의 DHCP 예약·고정 할당에 등록해야 한다.
주소 예약은 현재 확인 전이다. 외부 접속에 성공한 명령은 다음과 같다.

```powershell
ssh -i "C:\Users\<user>\.ssh\id_ed25519" -p 2222 <gateway-user>@203.0.113.12
```

현재 PC의 `C:\Users\<user>\.ssh\config`에는 같은 주소·사용자·키의 `Host pi` 별칭을
등록하고 실제 접속을 확인했다. 현재 PC에서는 `ssh pi`로 접속한다. 별칭은 각 PC의
설정이므로 다른 PC에는 자동으로 생기지 않는다.

이 명령은 일반 OpenSSH 접속이며 해당 경로에는 Tailscale 클라이언트가 필요 없다.
공인 주소는 변경될 수 있다. 다른 PC는 그 PC의 공개키를 Pi에 별도로 등록해야 한다.
Pi 프로젝트의 개발 경로는 `/home/<gateway-user>/Desktop/habitat`다. 필요할 때 별도 SSH 접속만
중단하는 명령은 `sudo systemctl disable --now habitat-ssh-dev.service`다.
기존 Pi→GPU 연결과 웹 공개 경로는 이 SSH 설정의 성공 근거가 아니다.

2026-11-10 다른 PC의 외부 Wi-Fi 접속 요청으로 다시 읽기 점검했다.
`ssh`, `habitat-ssh-dev`, `tailscaled`는 active였고 유선 주소는 여전히
`192.168.219.103`이었다. Pi에서 공인 주소 `203.0.113.12:2222`로 연결해
SSH 배너를 받았으며 서버 Ed25519 공개키 지문이 로컬 Pi와 일치했다:
`SHA256:<SSH-KEY-FINGERPRINT>`.
이는 Pi에서 공인 주소를 통한 도달성 확인이며, 새 PC의 외부 네트워크 로그인
성공 검증은 아니다. 이후 새 PC의 Ed25519 공개키
`SHA256:<SSH-KEY-FINGERPRINT>`을 전달받아 등록했다.
기존 키 4개를 보존해 총 5개가 됐고 `.ssh` 700·`authorized_keys` 600을 유지했다.
변경 전 백업은 `/home/<gateway-user>/.ssh/authorized_keys.before-habitat-1794303964110761289`다.
공인 주소로 호스트 키를 고정한 공개키 사전 인증 질의에서 서버가 새 키를
승인하는 것도 확인했다. 이후 사용자가 새 PC에서 키 암호를 입력하고
`<gateway-user>@habitat-pi:~ $`에 도달한 터미널 결과를 보내 완전한 로그인을 확인했다.
개인키는 새 PC에만 보관하며 서비스 재시작·공유기 변경은 하지 않았다.

새 Windows PC는 개인키를 그 PC에 보관하고 공개키만 전달한다. 기존 전용 키가
있으면 재사용하며, `.ssh` 폴더가 없으면 먼저 만든다.

```powershell
New-Item -ItemType Directory -Force "$HOME\.ssh" | Out-Null
$key = "$HOME\.ssh\id_ed25519_habitat"
if (!(Test-Path $key)) { ssh-keygen -t ed25519 -f $key }
ssh-keygen -y -f $key
```

등록 후 별칭 없이 접속하는 명령은 다음과 같다.

```powershell
ssh -p 2222 -o IdentitiesOnly=yes -i "$HOME\.ssh\id_ed25519_habitat" <gateway-user>@203.0.113.12
```

`ssh -o HostName=203.0.113.12 pi`를 그대로 쓰려면 해당 PC의 SSH 설정에도
`Host pi`, `User <gateway-user>`, `Port 2222`, 해당 개인키의 `IdentityFile`을 지정한다.
사용자는 새 PC의 명령을 `ssh habitat`으로 줄이기를 요청했다. 해당 Windows PC의
`%USERPROFILE%\.ssh\config` 맨 위에 다음 블록을 추가하고 기존 설정은 보존한다.
이 별칭은 Windows 쪽 설정이며 Pi에서 자동으로 반영되지 않는다.

```sshconfig
Host habitat
    HostName 203.0.113.12
    Port 2222
    User <gateway-user>
    IdentityFile ~/.ssh/id_ed25519_habitat
    IdentitiesOnly yes
```

현재 공인 주소를 사용하는 새 PC 로그인은 확인됐고, 별칭 저장·접속 결과는
사용자 PC에서 확인할 단계다.
Wi-Fi 변경 자체가 공개키 재등록을 요구하지는 않는다. 키 관리와 PC별 설정은
[Microsoft OpenSSH 안내](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_keymanagement)와
[OpenSSH 설정 명세](https://man.openbsd.org/ssh_config.5)를 따른다.

친구별 공개키 추가(2026-10-07): `ksh62@SungHyun`의 Ed25519 키와
`giminu0930@MacBook-Pro.local`의 RSA 4096 키를 기존 키와 함께 등록했다. 실제 Pi의
`authorized_keys` 지문과 디렉터리 700·파일 600을 확인했으며 기존 관리 접속을 유지했다.
친구 PC의 접속 성공은 아직 확인 전이다. 지문·등록 시각은 위 SSH 검증 기록에 남겼다.
Mac의 이번 공개키 지문은 `SHA256:<SSH-KEY-FINGERPRINT>`로,
사용자가 먼저 전달한 `SHA256:<SSH-KEY-FINGERPRINT>`와 다르다.
실제로 전달한 공개키를 등록했으며 RSA SHA-1 서명 허용으로 서버 정책을 완화하지 않았다.

친구 PC의 OpenSSH `~/.ssh/config`에 개별 `Host` 블록을 기존 포괄 규칙보다 먼저 둔다.
첫 친구의 별칭은 `reptile02`, Mac 친구는 `reptile03`이다. 둘 다 `HostName 203.0.113.12`,
`Port 2222`, `User <gateway-user>`, `IdentitiesOnly yes`를 사용한다. `IdentityFile`은 등록된 공개키와
짝인 그 PC의 비밀키 경로다. Windows 첫 친구는 `~/.ssh/id_ed25519_habitat`를 생성했고,
Mac은 아래 최신 9B2c 값과 비교해 맞는 공개키 파일의 `.pub` 확장자를 뺀 경로를
사용한다. 별칭은 Pi에서 자동 배포되지 않으며 두 이름이 별도 Linux 계정을 만드는 것은 아니다.

사용자가 이어서 전달한 Mac Ed25519 공개키도 추가했고 기존 키를 보존했다. 그 지문
`SHA256:<SSH-KEY-FINGERPRINT>`는 처음 받은 9B2c 값과 일치한다.
`reptile03`의 최신 키 선택 기준은 이 Ed25519 키다. 이전 RSA 키도 별도 공개키로 등록된
이력을 유지하며, 키 추가만으로 Mac 클라이언트의 기존 `IdentityFile`이 자동 변경되는 것은 아니다.

### 기존 Pi 웹 화면

PC나 휴대폰 브라우저에서 다음 주소를 연 뒤 **매장 접속키**를 입력한다. 접속 기기에 Tailscale을 설치하거나 SSH 터널을 열 필요가 없다.

[LiveScene 화면 열기](https://gateway.example.ts.net/livescene)

Pi는 켜져 있어야 하며 인터넷과 기존 Tailscale 연결을 유지해야 한다. 매장 접속키는 Pi API 인증키이며, SaaS 계정이나 SSH 로그인 암호가 아니다.

관리자가 키를 확인해야 할 때만 Pi 터미널에서 다음 명령을 사용한다. 키를 화면 캡처나 공유 로그에 포함하지 않는다.

```bash
sudo sed -n 's/^HABITAT_API_TOKEN=//p' /etc/habitat-gateway/gateway.env
```

연결 후 사육장을 선택해 상태를 확인한다. GPU 기능에는 GPU PC와 WSL 서비스의 실행이 필요하다. 이전 공개 문 장면 렌더는 요청당 약 22~24초였으며 실시간 영상이 아니다. 로그인·WSL 유지와 재기동의 제약은 [GPU 서비스 운영](gpu-service.md)을 따른다.

## 외부 접속 설정 기록 — 2026-10-04

Pi의 Tailscale `1.102.4`에서 Funnel을 백그라운드로 설정했고, `AllowFunnel=true`를 확인했다. 기존 HTTPS·Funnel 권한이 있어 추가 계정 정책 동의는 필요하지 않았다. Pi 게이트웨이는 계속 `127.0.0.1:8000`에서 수신하며 공유기 포트는 열지 않았다. Funnel은 접속 기기에 Tailscale이 없어도 동작한다. [공식 설명](https://tailscale.com/docs/features/tailscale-funnel).

공용 Google DNS에서 `203.0.113.11`, `203.0.113.10`을 확인했다. Windows `curl --resolve`로 공용 주소 `203.0.113.11`에 연결해 Tailscale의 `100.x` 주소를 우회한 HTTPS 화면 응답 200과 TLS 인증서 검증 성공을 확인했다. 이 주소는 검증 당시 DNS 결과이며 고정 설정값으로 사용하지 않는다.

같은 공용 경로에서 인증 없는 사육장 조회는 401이었다. Pi 직접 검사에서도 무인증 조회·잘못된 키·무인증 등록 요청은 모두 401, 정상 키의 사육장 조회는 200이었다. 실제 출력은 계속 잠겨 있다.

공개 접속만 중단할 때 Pi에서 다음 명령을 사용한다. 백그라운드 공유는 중단하기 전까지 재부팅 후에도 유지된다. [Funnel 정지 동작](https://tailscale.com/docs/reference/tailscale-cli/funnel).

```bash
sudo tailscale funnel --bg --https=443 off
```

화면 HTML과 `/health`, `/docs`, `/redoc`, `/openapi.json`은 기존처럼 비인증으로 제공한다. 사육장 조회·제어 API는 매장 접속키로 보호한다. 이 접속 화면은 `habitatos.kro.kr`의 SaaS 계정 로그인과 별개다.

## 공기 온도 3D 화면 외부 접속 — 2026-10-25

사용자가 앱 설치 없이 웹 주소와 로그인으로 접속하는 방식을 선택하여 별도
인증 프록시를 추가했다. [CAGE-001 3D 화면](https://gateway.example.ts.net:8443/?cage_id=CAGE-001)을
휴대폰·PC 브라우저에서 열고 사용자명 `habitat`와 새 화면 전용 비밀번호로 로그인한다.
비밀번호는 Pi의 `/etc/habitat-air-viewer/remote-login.json`에 root 소유 0600으로 보관한다.
SaaS 계정이나 Pi 관리자 암호를 재사용하지 않으며, 비밀번호·인증 헤더는 검증 출력에 포함하지 않았다.

연결 경로는 `공개 HTTPS 8443 → Tailscale Funnel → 127.0.0.1:8766 Caddy 인증 →
127.0.0.1:8765 air viewer`다. 기본 Caddy 서비스 두 개는 설치 전에 mask하고,
배포판 Caddy `2.6.2-12+deb13u1`을 별도 `habitat-air-remote.service`에서 실행한다.
기존 HTTPS 443, gateway, recorder, air viewer를 재설정하거나 재시작하지 않는다.
이 기능은 Pi 화면 직접 조회이며 `/v1/edge/air` SaaS 업로드 활성화와는 별개다.

실제 서비스의 첫 시작에서는 DynamicUser 환경에서 홈 디렉터리를 찾지 못해
설치 검증이 실패했고 외부 공개 전에 중단했다. 서비스 전용 상태 디렉터리를
HOME으로 지정해 수정했다. 실패 시 새 unit을 제거하기 전에 서비스를 중지하도록
복구 순서도 보완했다. 셸 환경을 상속하지 않는 실제 Caddy 통합 검사 13개와 기존
배포 검사 36개가 통과했다. 로그인 정보는 재시도 중에도 보존했다.

공용 DNS의 `203.0.113.10`과 최종 확인의 `203.0.113.11`에 직접 연결해 내부 Tailscale 주소를 우회하고,
호스트명에 대한 TLS 인증서 검증을 유지한 채 화면·JS·사육장 목록·측정 API에서
무인증 401 및 정상 로그인 200을 확인했다. 잘못된 비밀번호의 측정 API 요청도
401이었다. 이 IP는 검증 시점의 DNS 결과이며 운영 설정에 고정하지 않는다.
센서·인증·TLS·화면 설정 및 기존 service unit 등 8개 파일의 SHA-256과
기존 Funnel 설정은 유지됐다. 변경 전 상태는
`/etc/habitat-air-viewer/remote-before-20261025.json`에 보존한다.
최종 프록시 PID는 142129이며 enabled/active, 재시작 0회다. 기존 gateway PID 84959,
recorder PID 21687, viewer PID 130247도 유지되고 모두 enabled/active였다.

확인 중 `held/invalid_sensor_message` 상태도 관찰됐으며, 마지막 확인의 화면은 `source_mode=live`, `status=offline`,
`status_reason=bb6_status_offline`, 수신 측정 0건이었다. 외부 조회 경로 확인을
새 실제 센서값이나 3D 추정장 검증으로 해석하지 않는다. 별도 휴대폰의 LTE/5G
브라우저에서 사용자가 로그인하는 동작은 아직 확인하지 않았다.

3D 화면의 외부 공개만 중단하려면 다음 명령을 사용한다. 기존 443은 유지된다.

```bash
sudo tailscale funnel --bg --https=8443 off
```

설치·재설치·타 매장 적용은 [화면 배포 절차](../deployment.md)를 따른다.
프로그램 기본값을 변경하지 않고 설치 인자로 사용자명과 로컬 포트를 지정할 수 있다.
새 인증 프록시 설치기·service·설정 예제는 `--with-air` 배포 묶음에도 포함한다.

## 2026-11-07: 0.4.20 무선 카메라 설치·실물 시험

공통 Gateway에 HTTP MJPEG 입력, 사육장별 TOP/FRONT 화면, 두 카메라 등록과
사육장 inventory 추가 명령을 넣었다. DFR1172도 같은 프로그램과 별도 비공개
설정을 사용한다. [설치·이행 절차](new-store-setup.md)를 따른다. 기존 MQTT 및
SaaS video v1 계약은 유지하며, 새 센서 노드 계정·ACL과 출력 commissioning은
사육장 inventory 생성과 별개다.

`dist/habitat-gateway-0.4.20-47b0ca40e3f7.tar.gz`를 Python 3.13/aarch64용으로
빌드했다. Gateway와 Air Viewer를 함께 업그레이드할 수 있는 `--with-air`
묶음이며 SHA-256은
`4679df29092cdb9fab1c0c25701eda3db0404c190ec4b54debdcb19ae0c345d5`다.
최종 57개 manifest 파일과 보드에 기록한 공통 프로그램 해시를 대조했다.
같은 설치기·의존성을 사용한 초기 묶음은 임시 root에서 오프라인 설치와 6개
카메라 설정 검증을 통과했다. 실제 서비스는 이 설치 시험에서 시작하지 않았다. 비공개 `config.h`,
카메라 `config.json`, 8 MB 제조사 바이너리는 배포 묶음에 포함하지 않았다.

관련 unit/integration/contract 검사 146개와 subtest 10개가 통과했다.
실제 FFmpeg를 사용하는 로컬 모의 MJPEG 두 입력에서 수신·디코딩, 한쪽 단절과
재연결을 검증했고, Chromium 모의 미디어 시험에서 두 화면과 개별 단절 표시를
확인했다. 이는 실물 카메라 영상 확인이 아니다. 장시간 선행 시험 뒤에도 시각
오류 계약 검사가 유효하도록 테스트 실행 시점에 상대 시각을 계산하도록 고쳤다.

이후 사용자가 두 보드를 Pi USB에 연결했다. 둘 다 ESP32-P4 revision 1.3으로
확인하고 제조사 이미지를 `0x2000`에 기록했다. 두 보드 모두 기록 데이터 해시와
별도 `verify-flash` 대조를 통과했으며 MicroPython, 공통 프로그램, 비공개
Wi-Fi 설정 저장과 파일 해시 검증을 마쳤다. 최초 VFS 준비 뒤 REPL이 정상
동작했다. 부팅 중 DWC2 assert 메시지는 관찰됐으나 두 보드에서 Wi-Fi와 실제
JPEG 수신까지 가능했다. 이 메시지를 실제 영상 장애의 원인으로 확정하지 않는다.

사용자가 실제 TOP/FRONT 설치 위치는 아직 정하지 않았다고 확인했다. 현재
A/B는 장치 식별이며 TOP/FRONT는 설치 예정 역할이다. 물리 위치 검증과 구분한다.

| 임시 식별 | P4 USB 고유번호 | Wi-Fi 주소 | 임시 설정 ID |
| --- | --- | --- | --- |
| A | `30:ED:A0:EA:1C:35` | `192.168.219.107` | `RGB-001` / top |
| B | `30:ED:A0:EA:5F:A5` | `192.168.219.108` | `CAGE-001-FRONT` / front |

두 보드의 실제 JPEG는 800×640이다. 가림을 제거한 뒤 실제 장면을 확인했다.
초기 어두운 B 영상은 수신·HLS 디코딩에 성공했지만, 밝은 장면에서 전송 지연이
커졌다. A는 RSSI -22 dBm, B는 -32 dBm이며 A/B의 Wi-Fi MAC은 서로 달랐다.
Pi의 전압 저하/스로틀 상태는 `0x0`이었다. B의 별도 20장 촬영은 매번
39~41 ms였으므로 촬영 속도와 무선 전송 성능을 구분해 평가했다.

A에서 실제 Wi-Fi 절전 값 1을 확인한 뒤 공통 프로그램에 `PM_NONE`을 적용했다.
A는 HTTP 전용 비교시험에서 약 12.09초에 78프레임, 첫 프레임 0.216초를
기록했다. 당시 기존 설정 B는 약 13.96초에 1프레임, 첫 프레임 5.1초였다.
B에도 같은 프로그램을 넣고 절전 값 0을 확인했지만 이후 HTTP 시험은 약
13.52초에 6프레임으로 더 느렸으며, 3초 I/O 제한의 Gateway 동시 시험에서는
B가 계속 수신하지 못했다. 공통 프로그램의 SHA-256은
`833b98b7d2cf6c2641fc177d725e198a8ffd06f8d6534793c75aa9d2d9b453df`이며,
절전 설정의 순서·예외 처리를 포함한 카메라 노드 시험 25개가 통과했다.

직렬 포트를 열 때 DTR/RTS 변화로 보드가 리셋될 수 있으므로 비교시험 중에는
직렬 포트를 열지 않았다. 이후 두 보드를 Pi USB에서 분리하고 각각 5V USB
전원 어댑터로 옮겼다. Pi에서 P4 USB 장치가 사라진 상태에서 두 보드가 자동으로
실행됐고 기존 Wi-Fi 주소의 identity와 실제 영상을 다시 수신했다. 이때 A는 약
12.05초에 24프레임, B는 약 15.49초에 7프레임이었다. 전원 변경이 지연을 모두
해결했다고 판정하지 않는다.

Gateway의 HTTP I/O 제한을 3초에서 10초로 조정했다. 각 카메라는 별도 비동기
프로세스이므로 다른 카메라를 기다리게 하지 않는다. 이 값은 전체 장애 감지 시간
보장이 아니며 기존 프레임 신선도·재시도 간격·종료 제한은 유지했다. 4초 입력
지연 중 TOP 프로세스 유지와 FRONT 연속 수신, 응답 없는 입력 종료를 포함한
카메라 단위 시험 20개·실제 FFmpeg HTTP 통합 시험 1개가 통과했다.

최종 전원 어댑터 실물 시험은 약 26.42초 동안 두 카메라 모두 `preview_ready`,
JPEG 갱신 3회와 내용 변화, 신선한 HLS 세그먼트 6개 및 HLS 디코딩 성공을
확인했다. 두 실제 영상의 동시 수신을 확인했으나 일정한 고속 FPS, 장기 연속
운전, 물리 TOP/FRONT 장착과 보정은 별도 검증 대상이다.

비공개 재설치 설정과 검증 이력은 소스 밖
`~/.config/habitatos/camera-nodes/RGB-001/` 및
`~/.config/habitatos/camera-nodes/CAGE-001-FRONT/`에 `0600`으로 보관했다.
2026-11-09 02:49 KST 재확인까지 운영 Gateway와 Air Viewer는 이전 버전이었으나,
이후 사용자가 Pi 터미널에서 준비한 적용 스크립트를 실행했다. 이 스크립트는
준비 당시 설정 해시가 같은지 확인한 뒤 기존 설정을
`/var/backups/habitatos-camera-0.4.20/gateway.before.toml`에 보관하고, 기존
설치기로 Air Viewer를 먼저 올린 다음 Gateway와 후보 설정을 적용한다. 설치기는
health/identity 검증에 실패하면 이전 Gateway 설정과 릴리스로 복구한다.
이번 설치는 완료됐으며 두 서비스 모두 `0.4.20-47b0ca40e3f7`로 실행 중이다.
Gateway·Air Viewer·센서 recorder·Mosquitto 모두 `active/running`,
`NRestarts=0`을 확인했다. Gateway health는 `ok`, MQTT 연결 상태도 true였다.
원본 백업 해시와 카메라 외 모든 설정의 일치를 확인한 뒤, 완료된 적용 스크립트·
압축 해제한 임시 릴리스·후보 설정 폴더는 제거했다. `dist/`의 versioned 묶음,
현재·직전 Gateway 릴리스, 운영 백업, 비공개 카메라 설정은 보존했다.

02:55 KST 이후 상시 서비스의 인증된 영상 API에서 두 카메라 모두 `live/fresh`,
실제 HLS 디코딩 성공, 5초 간격 최신 세그먼트 갱신을 확인했다.
최종 세그먼트 나이는 각각 약 2.35초·2.59초였다. 기존 외부 주소
`https://gateway.example.ts.net/camera`도 페이지·인증 200과 두 live 상태를
확인했다. 접속 키는 출력하지 않고 기존 비공개 `camera-viewer.html`에서만
메모리로 읽었다. 사용자는 `~/.config/habitatos/camera-viewer.html`의 저장된
접속 버튼을 사용할 수 있다.

02:58:00~02:58:08 KST Gateway API에서 CAGE-001·002의 새 message ID와
수신 시각 갱신, T1·RH1·T2·T3 모두 valid를 확인했다. 최종 값은 CAGE-001
22.20°C / 44.61% / 21.812°C / 21.937°C, CAGE-002
22.67°C / 43.07% / 22.375°C / 22.500°C였다. CAGE-003은 telemetry가 없었다.
Air API에서도 두 사육장의 live sample 증가와 reject 증가 0을 확인했다.
03:02 KST SaaS 센서 이벤트 ACK의 최근 성공을 확인했으며 기존 과거 충돌 8건은
유지됐다. 이를 자동 삭제하거나 재번호화하지 않았다.

03:19 KST 사용자가 FRONT의 `최신 영상 수신 대기`를 보고해 재확인했다.
Pi API에서도 FRONT만 `waiting_fresh_video`였으며, 03:19:30 새 수신 세션이
자동으로 시작됐다. 서비스 재시작이나 설정 변경은 수행하지 않았다.
03:21:35~03:22:05 두 HLS 목록과 JPEG 갱신을 확인하고,
03:24:20~03:24:41 외부 HTTPS 주소에서 10초 간격으로 세 차례 두 카메라의
`live/fresh`, 서로 다른 최신 세그먼트, 실제 디코딩 성공을 확인했다.
같은 시각 CAGE-001·002 센서의 새 메시지와 네 채널 모두 valid도 재확인했다.
FRONT 중단 원인은 확정되지 않았다. 현재 수신기는 재시도 대기 중 오류 표시를
일반 영상 대기로 덮어쓰고 FFmpeg 오류 출력을 보존하지 않아, 이 문구만으로
Wi-Fi·카메라·수신 프로세스 중 원인을 특정할 수 없다.

매장 설정 후보는 카메라만 3쌍으로 전환하고 센서·제어·매장 설정이 원본과 같음을
검증했다. 기존 TOP ID `RGB-001`~`RGB-003`을 보존하며 FRONT ID를 추가한다.
초기 후보에 실제로 검증한 CAGE-001의 두 URL과 800×640 크기를 반영했다.
CAGE-001의 이번 시험은 영구 녹화를 끄며, 기존 `video_upload.enabled=false`를
유지한다. 따라서 SaaS 영상 게시 완료로 해석하지 않는다. 다른 설정은 원본과
같음을 검증했다. 현재 운영 SaaS의 영상 경로에 Pi 인증정보로 빈 검증 요청을
보내도 HTML403이었으며 실제 영상은 보내지 않았다. 서버 소스·배포 접근은 없고
사용자가 팀원에게 전달해야 한다고 확인했다. 정확한 두 ID와 요청 사항은
[서버 작업 지시서](../api/saas-codex-prompt.md)에 정리했다.

### CAGE-001 IR 전달본 검증 — 운영 미적용

2026-11-09 전달 경로는
`/home/<gateway-user>/habitat-handoff/cage001_camera_ir_20261109`다.
Pi에서 `MANIFEST.sha256`의 43개 파일이 모두 일치함을 확인했다.
원본 전달본을 변경하지 않고 자동 정리되는 `/tmp`에서 Python 33개와
실제 IR 헤더를 사용하는 C++ 모의시험 51개를 다시 실행해 모두 통과했다.
ESP32 대상 빌드 2종 성공은 전달된 증거이며, 이번 Pi 검증에서 다시 수행하지 않았다.

카메라 `main.py`는 현재 공통 소스와 동일하다. BB6 센서 함수와 telemetry
payload도 현재 소스와 동일하며 센서 핀 21/22/18/19를 유지한다.
전달본 예제는 `HABITAT_IR_CONTROL=1`, `HABITAT_IR_OUTPUTS=0`,
`HABITAT_R11_PUMP=0`, `HABITAT_R11_PUMP_OUTPUTS=0`이다.
IR 기본 LOW·출력 잠금·최대 5초 유효 시간·재접속 시 OFF는 코드와 모의시험으로
검증했으며 실제 GPIO·점등·안전 검사 지연은 미검증이다.
IR 소스의 공통 저장소 병합, 실사용 설정 병합, MQTT 계정/ACL 변경,
BB6 백업·업로드는 이번 전달본 검증에서 수행하지 않았다.
운영 릴리스는 계속 `0.4.20-47b0ca40e3f7`이며 기존 `/camera` 수신기를 사용한다.

### CAGE-001 IR 설치 — 0.4.22

사용자가 IR 설치와 배선을 확인한 뒤 실제 설치를 진행했다.
처음 연결된 CP2102N 보드는 백업 내 identity가 CAGE-002였으므로 기록하지 않았다.
사용자가 CAGE-001을 연결한 뒤 CH340 `usb-1a86_USB_Serial-if00-port0`,
ESP32 MAC `8c:94:df:aa:3a:74`와 백업 내 `ESP32-001` identity를 확인했다.
전체 4MB 백업 SHA256은
`534c9cd064738a980b76e35059481652a261f06d282b6bb0f5b88f2e93a5987c`다.
921600 baud 읽기는 손상 오류로 실패했고, 460800 baud 재시도는 성공했다.

기존 장치 폴더의 암호가 실행 중인 펌웨어와 달랐으므로 바로 업로드하지 않았다.
기존 작업 소스의 비공개 설정이 백업 내 Wi-Fi·MQTT 인증정보와 일치함을 확인하고
그 설정으로 빌드했다. 원래 설정과 과거 장치 폴더 설정은 비공개 복구 경로에
보존했다. 실제 설정·플래시 백업·업로드 로그는
`~/.config/habitatos/nodes/ESP32-001/ir-commissioning/`에 있으며 공개 패키지에 없다.

사용자가 준비된 `provision_ir.py --apply`를 sudo로 실행했다.
기존 MQTT 암호 항목 전부와 ACL 행이 보존되고 전용 계정 `CAGE001-IR-CTRL`
하나가 추가된 것을 재검증했다. 복구본은
`/var/backups/habitatos-ir/1794164126529971030-CAGE-001`이다.
비공개 `ir.json`/`ir.env`는 `~/.config/habitatos/ir/CAGE-001/`에 mode 0600이다.
Mosquitto는 reload만 했으며 Gateway·Air·센서 recorder·브로커 PID는 유지됐다.

공통 IR 소스를 0.4.22 릴리스에 포함하고 `install.py --user-ir`로
`~/.local/share/habitatos/ir/current`에 설치했다. 현재 IR 릴리스는
`0.4.22-00d66a5b6ccb`, Gateway·Air는 기존 `0.4.20-47b0ca40e3f7`다.
IR은 독립 CLI로 실행하며 카메라 열람 키에 제어 권한을 추가하지 않았다.
공개 묶음 SHA256은
`acad62fab63985a336347426a5e6e88bcb7f0b2fb190f4b520a2f41d6284a5bc`다.

먼저 잠금 펌웨어를 기록·verify-flash하고 `outputs_locked=true`, OFF 상태,
잠금 상태의 ON 차단, CAGE-001·002 센서 네 채널 valid 갱신을 확인했다.
그 뒤 출력 활성화 펌웨어를 기록했다. 첫 실기 갱신 명령이 `invalid_time`으로
거부되어 OFF로 종료됐으므로, IR에만 최대 1000ms 미래 발행 시각 허용을 추가했다.
이미 만료된 명령과 5000ms 초과 TTL은 거부하며 monotonic lease 상한도 유지한다.
최종 IR native 57개 검사, IR 클라이언트·권한·펌웨어 pytest 49개와 25개 subtest가
통과했다. 별도 설치·기존 배포 회귀 64개도 통과했다.

수정 펌웨어의 app SHA256은
`d5d4ff39c6a373f87fb9b3443a6975152d5ae7a8911654fe14438b148dc98417`이며
실제 기록 후 verify-flash를 통과했다. 펌프 코드·GPIO 초기화는 포함되지 않는다.
04:09 KST 10초 시험에서 ON ACK 10개, lease 만료 OFF와 후속 OFF ACK를 확인했다.
이 시험 중 영상은 어두웠고 이후 사용자가 IR 전원 미연결을 확인했다.
따라서 이 기록은 명령·MCU 요청 상태 검증이며 실제 조명 점등 검증은 아니다.
IR 전원 연결 후 영상 검증은 아래 후속 기록으로 구분한다.

04:18 KST 사용자가 IR 12V 전원과 BB6 5V 전원을 연결한 뒤 10초 시험을
다시 수행했다. 위치를 옮기는 동안 BB6 전원이 끊겨 처음 ON 시도는 hello
시간 초과로 전송되지 않았고, 전원 복구 후 ON ACK 10개와 OFF ACK를 받았다.
`RGB-001` 영상 평균 밝기는 OFF/ON/OFF 0.43/58.96/0.32,
`CAGE-001-FRONT`는 0.03/56.65/0.04였다(0~255, 검증 프레임 기준).
두 ON 프레임에서 사육장 내부가 실제로 보이고 OFF 프레임은 다시 어두워지는
것을 직접 확인했다. 이 결과는 영상으로 관찰한 점등·소등 검증이며 VOUT 전압,
조도 균일성 또는 야간 추적 정확도 측정은 아니다. 시험 종료 상태는 OFF다.
개별 프레임과 명령 기록은 비공개 commissioning 경로의
`ir-powered-on-off-check.json` 및 `ir-powered-*.jpg`에 보관했다.

제어 계약·CLI 사용법은 [IR 제어 문서](../protocols/ir-control.md)에 있다.
중간 배포 ZIP 대신 versioned 릴리스만 유지하며, wheel 빌드 디렉터리와
중간 0.4.21 배포 archive는 정리했다. 설치된 이전 IR 릴리스는 rollback용으로 남겼다.

### 카메라 화면 IR 제어 — 운영 활성화 완료

기존 `/camera` 주소에 사육장별 **IR 켜기 / IR 끄기**와 자동 끄기 시간을
추가했다. 현재 주소는 `https://gateway.example.ts.net/camera` 그대로다.
2026-11-09 KST Gateway·Air Viewer·IR runtime에 `0.4.23-71437a21374f`를 적용했다.
실제 공개 주소의 Chromium 화면에서 보기 전용 권한, 제어 로그인, 10초 ON 요청과
수동 OFF를 검증했다. 두 영상은 최신 프레임 재생이 진행됐으며 전면 영상에서
점등도 관찰했다. 촬영 당시 TOP은 검게 표시되어 두 영상의 밝기가 모두 변했다고
판정하지 않는다. 시험 종료 상태는 보드 응답 기준 OFF다.
CAGE-001/002는 시험 후 8초 간격 조회에서 새 메시지가 확인됐고 네 채널 모두
valid였다(최신 표본 나이 각각 1초·4초). 펌프 및 기존 센서 설정은 변경하지 않았다.

첫 활성화는 systemd의 WorkingDirectory/EnvironmentFile 경로에 잘못 적용한
따옴표 때문에 시작되지 않았고 준비 도구가 원복했다. 경로 형식을 수정한 뒤
실제 systemd 파서의 경고도 실패로 처리하는 회귀시험을 추가·통과했다.
카메라·IR·배포 통합 시험 170개와 모의 브라우저 시험, 수정된 준비 도구 시험
43개 및 별도의 실제 systemd 검사 1개를 확인했다. 운영 적용 백업은
`/var/backups/habitatos-camera-ir/1794167217837571834`에 보존한다.

영상 열람 키는 계속 보기 전용이다. 별도의 제어 키로 연결하면 같은 화면에서
IR 버튼을 사용할 수 있다. 이미 영상 키로 로그인한 경우 **IR 제어 키 → 제어 연결**을
사용한다. 제어 키는 해당 Pi에서 명시적으로 등록한 사육장 범위에만 적용된다.
0.4.23의 기본 요청은 5분이며 10초·1분·5분·15분 자동 끄기를 선택하는 방식이었다.
최대 900초이고, 그전에 **IR 끄기**로 종료할 수 있다. 브라우저를 닫아도 이미
접수된 시간은 유지되며 시간이 끝나면 종료한다. 재접속·새로고침만으로 다시
켜지지 않는다. 실제 점등은 영상 또는 현장에서 확인한다.

이미 IR 설치를 마친 BB6에는 이번 웹 기능을 위해 펌웨어를 다시 올릴 필요가 없다.
펌프 활성화, 카메라 펌웨어 변경, MQTT 계정 재발급도 필요하지 않다.
Gateway의 DynamicUser와 IR 제어 사용자는 구분하며, IR worker는 기존 CLI와 같은
Unix 사용자로 실행해 기존 `~/.local/state/habitat-ir/`의 잠금·순번을 공유한다.
영상 수신기는 기존 Gateway 하나를 유지한다.

1. 검증한 공통 릴리스를 기존 IR 사용자로 `install.py --user-ir` 설치한다.
   예: `python3 deploy/install.py --release /path/to/verified-release --user-ir`.
   사용자 IR 런타임은 `~/.local/share/habitatos/ir/current`를 사용한다.
2. 아래 명령으로 준비 내용을 확인하고 `--apply`를 추가해 worker를 설치한다.
   대상 사육장을 늘릴 때는 기존 대상도 포함해 `--cage`를 반복한다.

   ```bash
   sudo python3 deploy/provision_ir_web.py \
     --user <gateway-user> --cage CAGE-001 \
     --viewer-url https://gateway.example.ts.net/camera
   ```

   `--apply`는 새 키 두 개를 기존 Gateway env에 추가하고 `habitat-ir-web.service`만
   시작·검증한다. 다른 설정과 기존 키는 보존한다. IR 켜기 명령은 보내지 않는다.
   복구본은 `/var/backups/habitatos-ir-web/`, 관리 receipt는
   `/etc/habitat-ir/provisioned.json`이다. 키가 이미 준비돼 있으면 재사용한다.
3. 현재 Gateway 설정에서 다른 항목을 보존한 후보 설정에 아래 블록을 넣는다.
   공개 예제는 비활성 상태이며, 준비된 사육장만 명시적으로 활성화한다.

   ```toml
   [camera_ir]
   enabled = true
   endpoint = "http://127.0.0.1:8093"
   token_env = "HABITAT_IR_BRIDGE_TOKEN"
   cage_ids = ["CAGE-001"]
   ```

   기존 versioned 설치기로 Air를 먼저 업데이트하고 Gateway와 후보 설정을 적용한다.
   Gateway 설정 검증과 설치 후 health/identity 확인에 실패하면 설치기의 복구 절차를
   따른다. worker 준비 명령만으로 운영 `/camera` 코드가 바뀌는 것은 아니다.
4. 제어 권한이 필요한 사용자는 Pi의
   `~/.config/habitatos/ir/camera-control.html`을 이용한다. 파일은 mode 0600이며
   제어 키가 들어 있다. 다른 PC에는 기존 인증된 SSH/SCP 경로로 그 파일만 전달해
   브라우저에서 연다. 기존 `camera-viewer.html`은 계속 보기 전용으로 사용할 수 있다.
   제어 키나 전체 `gateway.env`를 채팅·문서·공개 링크에 붙이지 않는다.
5. `systemctl is-active habitat-ir-web` 및
   `curl --fail http://127.0.0.1:8093/health`로 worker identity와 사육장 목록을 확인한다.
   Gateway 상태, 카메라 2대 최신 영상, 기존 센서 수신도 확인한다. 보기 전용 접속에서는
   제어가 잠겨 있고 제어 접속에서만 버튼이 작동해야 한다. 짧은 ON/OFF 시험에서
   노드 응답과 실제 영상 변화를 구분해 기록한다.

소프트웨어 검증: 웹 준비 도구와 기존 IR 준비 도구의 격리 임시파일 시험
**43개 통과**. 계정/사육장 identity, 기존 env 보존, 키 재사용·비출력,
설정·런타임 변경 시 worker 재시작, 실패 시 파일·서비스 상태 복구를 포함한다.
실제 운영 파일·서비스·GPIO를 조작하지 않은 시험이다. Gateway/worker/API/브라우저의
통합 결과와 실제 웹 활성화 결과는 후속 확인 기록으로 구분한다.
일회성 적용 도구를 `/tmp`에 준비한 경우 설치 결과를 기록한 뒤 제거한다.

구성·권한·API·시간 제한은 [IR 제어 계약](../protocols/ir-control.md#optional-camera-web-controls)에 있다.

### 0.4.24 IR 계속 켜기 — 운영 적용 완료

0.4.24는 같은 `/camera` 화면에서 **계속 켜기**를 기본으로 하고, 필요할 때만
자동 끄기 시간을 선택하도록 변경한다. 이 문단 작성 시점에는 운영 0.4.23의 설치
기록과 구분된다. `0.4.24-16c7de2ceac8`을 IR worker·Gateway·Air Viewer에 적용했고
기존 설정·인증정보가 그대로 보존됐음을 확인했다. 적용 백업은
`/var/backups/habitatos-camera-ir/1794168423744515274`다.

통합 시험 183개와 기존 하위 시험 25개, 모의 브라우저 시험을 통과했다.
실제 공개 주소의 Chromium에서 기본 계속 켜기, `remaining_s: null`,
페이지를 12초 비운 뒤에도 유지되는 보드 ON 응답, 재진입 시 새 ON 명령이
발행되지 않음, 수동 OFF를 확인했다. 이어서 선택한 10초 타이머가 별도 OFF
요청 없이 자동 종료하는 것도 확인했다. 시험은 OFF 응답을 확인하고 종료했다.
이후 별도 상태 조회에서는 새로운 계속 켜기 실행이 활성 상태로 확인됐으며,
그 실행에 종료 명령을 추가로 보내지 않았다.
두 카메라 모두 live였고, CAGE-001/002는 8초 간격 조회에서 새 메시지와
네 채널 valid를 유지했다(표본 나이 1.2초·4.2초). 이번 검증은 보드 응답과
영상 갱신 검증이며 물리 광량을 별도로 측정하지 않았다.

계속 켜기를 선택하고 **IR 켜기**를 누르면 **IR 끄기**를 누를 때까지 Pi가
명령을 갱신한다. 브라우저를 닫거나 로그아웃해도 계속 켜기 요청은 유지된다.
화면은 남은 시간 대신 계속 켜기 상태를 보여준다. 자동 끄기를 선택하면 지정한
시간 뒤에 종료하고 남은 시간을 표시한다. 타이머는 1~900초 범위이며 기존
worker의 `max_on_seconds`가 더 작으면 그 제한을 적용한다.

ESP32의 최대 5초 유효시간과 OFF 안전 처리는 그대로다. Pi가 짧은 명령을 계속
갱신하는 방식이며 무기한 GPIO 명령을 넣지 않는다. worker 재시작, Wi-Fi/MQTT
연결 끊김, 노드 세션 변경이 발생하면 갱신이 종료된다. OFF 명령이 전달되지
못해도 마지막 유효 명령의 lease가 만료되면 소등한다. 연결이 복구되거나 화면을
새로고침해도 자동으로 다시 켜지지 않으며, 다시 **IR 켜기**를 눌러야 한다.

API의 `seconds` 생략 또는 `null`은 계속 켜기이고, 명시적인 1~900 정수는
타이머다. 상태 응답의 `mode`는 `continuous` / `timed` / 비활성 시 `null`이며,
계속 켜기 중 `remaining_s`는 `null`이다. 0.4.23처럼 5분 자동 종료를 원하는
외부 API 호출은 `seconds: 300`을 명시해야 한다. 기존에 시간을 명시한 호출의
동작은 유지한다. 기존 0.4.23 UI도 항상 숫자 시간을 보냈으므로 worker만 먼저
갱신한 구간에는 기존 타이머 동작을 유지한다. 새 인증정보나 설정 필드는 없다.

업데이트에는 새 공통 릴리스의 사용자 IR runtime 설치, 기존
`provision_ir_web.py --apply` 재실행, Gateway 릴리스 적용이 필요하다. worker를
먼저 올리고 Gateway를 갱신한다. 기존 worker receipt의 runtime release가 달라지면
worker가 재시작되므로 진행 중 요청은 종료되며 배포 뒤 자동 복원하지 않는다.
펌웨어·배선·MQTT ACL·인증 키·`[camera_ir]` 설정은 바꾸지 않는다. 같은 사용자와
기존 순번/잠금 파일을 유지하고, 펌프 기능을 활성화하지 않는다.

적용 뒤 계속 켜기, 명시적 OFF, 선택한 타이머 종료를 각각 확인한다. 타이머
선택만으로 ON 명령을 보내지 않아야 한다. worker 재시작이나 통신 복구 뒤 자동
ON이 없는지도 소프트웨어 검증과 실제 관찰을 구분해 기록한다.

## 정상 확인과 현재 한계

```bash
systemctl is-active habitat-gateway
curl --fail http://127.0.0.1:8000/health
sudo /opt/habitat-gateway/current/venv/bin/python \
  /opt/habitat-gateway/current/edge_tools.py status
```

서비스는 `active`, 건강 상태는 `ok`인지 확인한다. GPU나 SaaS 연결 상태는 별도로 확인한다. Pi 설치 성공만으로 다른 두 PC의 연결 성공을 판정하지 않는다. GPU 오류가 발생하면 화면에 나타난 오류 문구와 위 상태 결과를 전달한다. 인증키를 포함한 `gateway.env` 전체를 전달하지 않는다.

분무 패널과 정지 경로는 포함되어 있으나 현재 실제 출력은 잠겨 있다. 실제 카메라·분무 장치와 사육장 객체 매핑, 하드웨어 시운전이 끝나야 물리 제어를 허용한다. 공개 문 샘플을 분무 장치에 연결하지 않는다. R15의 GPIO 요청·`requested`·`execution_unverified`는 펌프 실제 동작이나 유량 확인을 뜻하지 않는다. 3초 제한도 실측 분무량 보장이 아니다. 다른 팀원 PC의 SaaS 화면은 수정하지 않았다.

## 0.4.12 배포 임시 파일 정리

설치·운영 검증 후 개발 PC의 `var/tmp/r15-active-reservation` 파일 3개,
1,263,461바이트를 삭제하고 경로 부재를 확인했다. Pi 전달 `.pyz`와 적용 도구,
GPU 임시 검사 도구는 검증 성공 후 스스로 삭제했다.
[이번 정리 기록](../../var/reports/commissioning/software-r15-20261005-active-reservation-cleanup.json)에
결과를 보존했다. 설정·인증정보·DB·모델·구매 원본은 유지했다.

## 0.4.11 배포 임시 파일 정리

적용·상태 확인 후 개발 PC의 `var/tmp/camera-model-release` 파일 3개,
1,262,065바이트를 삭제하고 경로 부재를 확인했다. Pi의 전달 `.pyz`와 적용용 임시
Python 파일도 삭제 후 부재를 확인했고, GPU의 임시 검사 파일 삭제는 종료코드 0이었다.
이번 정리는 [0.4.11 삭제 기록](../../var/reports/commissioning/software-r15-20261005-camera-cleanup.json)에
따로 남겼다. 구매 원본, 운영 설정·인증정보·DB와 모델은 보존했다.

## 0.4.10까지의 배포 임시 파일 정리 기록

Pi의 0.4.8·0.4.9·0.4.10 전달용 `.pyz`와 이전 타이밍 수정 임시 설정 사본은 배포 확인 후 삭제했다. 최종 문서 동기화 후 개발 PC의 프로젝트 `.tmp`도 삭제하고 경로가 없음을 확인했다. 파일 581개, 20,509,879바이트를 정리했다. [삭제 확인 기록](../../var/reports/commissioning/software-r15-20261005-cleanup.json)에 정확한 경로와 결과를 보존했다. 사용자가 전달 파일을 다시 다운로드할 필요는 없다.

공통 소스, 현재·직전 복구용 설치 릴리스, 운영 DB·설정·인증정보와 작은 검증 보고서는 유지한다. 모델·학습 영상·하드웨어 제조자료의 대용량 원본을 전달 패키지에 복제하지 않으며, 사용자가 제공한 원본 ZIP과 구매 신청서는 보존한다. 위 삭제 기록은 0.4.10까지의 결과이며 0.4.11 임시 파일 정리 완료 증거로 재사용하지 않는다.

## 2026-11-25 — 0.4.25 카메라 장치 ID 기반 주소 복구

전원 재연결 후 FRONT(`CAGE-001-FRONT`)가 기존 `192.168.219.108`이 아닌
`192.168.219.105`에서 `/identity`에 응답하는 것을 확인했다. 기존 Pi는 등록된
옛 주소만 재시도했고, 영상·IR 인증키는 그대로 유효했다. 이 문제를 해결하기 위해
`camera_discovery` 선택 설정과 비동기 장치 ID 확인·주소 저장·재접속을 추가했다.
매장·Gateway·사육장·카메라·역할을 모두 대조하며, 기존 API 경로와 키는 유지한다.

기본 설정은 비활성화다. 이번 매장의 후보 설정만 검색 범위
`192.168.219.0/24`, 포트 5000, 검색 간격 30초, 요청 전체 제한 1초, 동시 요청
최대 16개로 지정했다. 원래 카메라 URL을 포함한 나머지 운영 설정은 동일하다.
주소 확인은 신뢰하는 LAN의 논리 ID 대조이며 장치 인증서 검증은 아니다.

관련 단위·HTTP/FFmpeg 통합·카메라/IR API 계약·설치 검사 **281개 통과**를
확인했다. 재시작 시 저장 주소 재검증, 옛 IP의 다른 장치 재할당, 중복 ID 거부,
실행 중 카메라 보호, 느린 HTTP 응답의 전체 제한시간을 포함한다. 새 모듈의
실제 LAN 조회에서도 FRONT의 `.105`를 확인했다. 이때 TOP(`RGB-001`)은
이미 정상 영상 수신 중이어서 검색에서 제외했고 직접 카메라 스트림을 열지 않았다.

배포 묶음은 `dist/habitat-gateway-0.4.25-c95ff382d48e.tar.gz`이며 SHA-256은
`66db7867e880d61050b4351426dcea4f5c7d88d24ff8a8abaa941e3ed00d6514`다.
63개 manifest 파일 확인과 임시 root의 실제 오프라인 설치, Air Viewer 의존성 및
공통 설정 로딩을 검증했다. 실제 접속 키는 이 배포 묶음에 포함되지 않는다.
임시 설치 디렉터리와 생성된 `build/`, `habitat_gateway.egg-info`는 정리했다.

소유자가 준비된 적용 도구를 `sudo`로 실행해 **운영 적용을 완료했다**.
공유 설정 호환성을 위해 Air Viewer를 먼저 갱신한 뒤 Gateway를 설치했다.
백업은 `/var/backups/habitatos-camera-discovery/1795589105963193804`이며,
적용 전후 환경 설정의 값이 같아 기존 영상·IR 키가 보존됐음을 확인했다.
IR worker와 MQTT는 재시작하지 않았고 IR 명령이나 펌웨어 업로드도 없었다.

2026-11-25 **15:47:10~15:47:18 KST**에 기존 전달 파일의 키로 재확인했다.
Gateway는 `0.4.25-c95ff382d48e`, health `ok`, MQTT 연결 정상이다.
TOP(`RGB-001`)은 `.107`, FRONT(`CAGE-001-FRONT`)는 자동 발견한 `.105`를
실제 FFmpeg 입력으로 사용했다. 두 영상 모두 `live/fresh`, 최신 세그먼트 나이
약 2.6초였고 8초 뒤 타임스탬프가 갱신됐다. 각각 HLS 재생목록도 정상 수신됐다.
기존 IR 제어 키 로그인은 성공했으며 IR은 online/OFF/error=null이었다.
CAGE-002도 새 message_id와 5초 간격 측정 시각, 유효한 온도 3개를 계속 수신했다.
이번 관찰만으로 RH1 습도나 카메라의 모든 전원·Wi-Fi 장애 상황까지 검증한 것은 아니다.
15:48 KST에는 각 카메라의 최신 HLS 영상 조각을 Pi API에서 받아 실제 FFmpeg
디코딩도 성공했다(TOP 259,816바이트, FRONT 264,140바이트, 디코더 오류 없음).
확인 후 `/tmp/habitat-camera-discovery-activate.py`와 후보 설정 디렉터리를 정리했다.
운영 백업·릴리스·기존 비공개 키 파일은 유지하고 개발자 전달 안내에 복구 결과를 반영했다.

## 2026-11-26 — 0.4.26 카메라 H.264 중계 전환 준비

사용자 요청에 따라 `카메라 하드웨어 인코딩 → Pi 재인코딩 없는 HLS 중계
→ 기존 SaaS 재생` 경로를 추가했다. 기존 MJPEG/UVC, 영상·IR 인증과 ID를
유지한다. 현재 USB로 연결한 P4의 기존 비공개 설정에는
`CAGE-001-FRONT`/`front`가 저장돼 있어 그 ID를 보존했다.
TOP(`RGB-001`)은 아직 기존 MicroPython MJPEG 펌웨어다.

연결 보드는 ESP32-P4 revision 1.3, 16MB flash, OV5647이다. 전체 flash와
기존 config/main/microdot를 사용자의 비공개 camera-nodes/backups에 보관한
뒤 pre-v3 전용 네이티브 앱을 기록하고 바이트를 대조했다. 전체 복구 이미지
SHA-256은 `d30b3e2d84757db5949385d26a549cdfe12bddda0391f64cecbe9ae476b71c22`다.
최종 앱 SHA-256은 `562bae16b3dbf54f748899f88177b316d3d025c1ddb9f10fe84f18b86031e04a`다.
카메라 ID와 Wi-Fi를 보존했고 C6·센서보드·IR 펌웨어는 기록하지 않았다.

실물에서 HTTP identity schema 2, RTSP/TCP, H.264 Constrained Baseline
800×800을 확인했다. 초기 12초 수신에는 241프레임이 포함됐고, 최종 Pi 명령으로
받은 HLS 조각 6개가 모두 독립 디코딩·코덱/해상도 검사를 통과했다. 최종 조각은
약 1.62~2.94초, 367~664KB였으며 FFmpeg 오류가 없었다. 광학 해상도와
노이즈 개선을 디코딩 성공만으로 판정하지 않는다.

초기 네이티브 입력은 full-range YUV인데 SPS에 범위가 없어 재생기가 limited로
해석했고 어두운 정보가 잘렸다. 카메라 CSI의 출력 범위를 limited BT.601로
지정하고 실제 협상 결과를 검사하도록 수정했다. identity에도 두 값을 추가했다.
Pi는 SPS의 색상 표기만 일치시키고 VCL 화상 데이터는 보존한다. 최종 실물
HLS의 `color_range=tv`, 색상 표기 `smpte170m`과 독립 디코딩을 확인했다.

장면은 수정 후에도 어둡다. 센서 자동 노출·게인은 켜져 있고 게인이 설정
상한에 도달해 있다. 사용자 요청으로 CAGE-001 IR을 60초 제한 ON 요청했고
보드의 GPIO ON 응답을 확인했으나 광원 자체의 점등이나 충분한 조명은 입증하지
못했다. 시험 후 OFF 요청과 OFF 응답을 확인했다. 이 결과를 IR 광량·야간
화질 검증 완료로 해석하지 않는다.

관련 회귀 시험은 기본 294개와 48개 하위 검사 통과(예상 건너뜀 1개), 색상
계약 변경 후 대상 133개 통과, 배포/USB 준비 검사 80개 통과다. 임시 적용
도구의 격리된 순서·복구·권한 검사 22개도 통과했다. 색상 변경 시험은 실제
RTSP 모의 송출로 HLS/MKV의 전체 VCL 해시 보존과 색상 표기를 검사했다.

배포 묶음은 `dist/habitat-gateway-0.4.26-72dee731fc5c.tar.gz`, SHA-256은
`85a766624fa310ebaa7c47882553e5f4dc364288f2385fe93d62ca40ba556ba3`다.
69개 manifest 파일과 임시 root 오프라인 설치를 검증했다. 기존 Air 공유 설정
호환성도 확인했다. 후보 설정은 FRONT의 source_type/url/height/fps만 바꾸며
width는 기존 800을 유지한다. 다른 카메라·센서·IR·MQTT 설정은 동일하다.

사용자가 sudo 적용 도구를 실행했고, **18:13~18:15 KST에 Gateway와 Air
모두 0.4.26-72dee731fc5c로 적용된 것을 확인했다.** Gateway health는 ok,
MQTT 연결은 정상이다. 기존 영상 키로 Pi 내부와 공개 HTTPS 주소에 접속해
두 HLS의 최신 조각을 읽고 디코딩했다. 8초 간격으로 두 영상 모두 타임스탬프가
갱신됐다. 실제 FFmpeg 입력은 카메라당 하나이며 FRONT는 `-c:v copy`와
SPS 색상 표기를 사용한다. TOP은 아직 기존 MJPEG→Pi H.264 인코딩이다.
적용 복구 백업은 `/var/backups/habitatos-camera-h264/1795684271690885129`다.

이 확인 시점에 CAGE-001 IR은 `offline/no_live_hello`였고 Air도 새 센서값을
받지 못했다. IR worker 자체는 재시작되지 않았다. 카메라 정상 수신과 구분해
센서보드 전원·접속을 점검했다.
18:21 KST의 읽기 전용 DB·브로커 점검에서는 CAGE-001 마지막 수신이
18:11:21.314, ESP32-001 연결 유지 시간 초과가 18:12:17이고 이후 재접속
기록이 없었다. 사용자는 BB6 전원이 켜져 있다고 확인했다. 전원 차단으로
단정하지 않고 보드 재시작 후 복구를 요청했다. CAGE-002는 18:21:34.697까지
약 5초 간격으로 새 메시지를 수신했으며 T1·RH1·T2·T3 모두 valid였다.

사용자가 CAGE-001 BB6 전원을 재연결한 뒤 18:29:22 KST에 MQTT 재접속이
확인됐다. 18:30:05와 18:30:14 DB 점검에서 CAGE-001·002 모두 새 message_id를
수신했다. CAGE-001은 T1 22.44°C, RH1 79.77% valid였으며 T2/T3는 연결이
끊기기 전과 동일하게 null/invalid다. CAGE-002는 네 채널 모두 valid다.
IR 제어 키의 권한을 확인한 뒤 20초 제한 ON 시험에서 `on/gpio_requested_on=true`,
OFF 요청 후 `off/gpio_requested_on=false/error=null`을 확인했다.
ON 동안 기존 TOP 영상은 밝아졌지만 새 FRONT 영상은 여전히 어두웠다.
시험 종료 상태는 OFF다. 두 영상의 최신 프레임 갱신과 독립 디코딩은 계속 정상이다.
실제 SaaS 브라우저에서의 지연과 충분한 조명 하의 화질도 아직 검증 완료로
기록하지 않았다.

## 2026-11-26 — FRONT 재생 안정화 및 SaaS 확인

FRONT의 수신 프로세스가 실행 중인데도, 브라우저에 안내한 영상 조각이
재생목록에서 빠지면 HTTP 404가 되는 현상을 확인했다. 18:39 KST 기록에는
FRONT 영상 조각의 404 응답 76회와 200 응답 6회가 있었고, 재생목록 요청은
200 응답을 유지했다. 당시 8초 관찰에서 FFmpeg PID는 같았으며 CPU 사용량은
한 코어 기준 약 6.2%였다. FFmpeg 오류 출력은 보존되지 않아 과거 수신기
재시작의 상세 원인까지 이 기록으로 확정하지 않는다.

0.4.27에는 이미 안내한 조각의 메타데이터를 제한적으로 보관하는 처리와
네이티브 RTSP 입력의 `-fflags +nobuffer`를 추가했다. 계약 검사 134개,
단위 검사 50개, RTSP 검사 5개가 통과했다. 기존 설치 도구를 사용하는 적용
파일로 Air와 Gateway를 갱신했으며, 설정·키 보존 및 실패 시 복구 조건을
확인했다. 복구 백업은
`/var/backups/habitatos-camera-stream-fix/1795686703826093111`이다.

**19:15 KST 재확인 당시 Gateway는 `0.4.28-2f4a27c6bcf9`, Air는
`0.4.27-60febc1deaf8`이었다.** Gateway의 현재 링크와 서비스 시작 시각은
19:06:54 KST다. 운영 `gateway.toml`의 SHA-256은
`18a1cd87a33086c9c9a29b59435581d69aeb695057eea34f7029901346ec0fbf`로
앞선 FRONT 전환 후와 같았다.

현재 0.4.28의 HLS 재요청 허용 시간은 40초이며, 메타데이터 보관 상한은
48개다. 최신 재생목록은 6개 조각과 기존 15초 최신성 조건을 유지한다.
지난 조각의 재요청도 현재 수신기·장치 확인·유효한 스트림·같은 세션 조건과
실제 파일의 존재·해시 검사를 통과해야 한다. **40초는 허용 상한이며 파일을
40초 동안 반드시 제공한다는 보장은 아니다.**

19:17:28~19:17:53 KST 공개 HTTPS 경로에서 서로 다른 FRONT 영상 조각
7개를 받아 모두 오류 없이 디코딩했다. 최신 조각 나이는 약 2.3~4.65초였다.
같은 관찰 구간에 카메라의 프레임 카운터는 52,854에서 53,361로 증가해
약 20fps였으며, 누적 드롭 카운터는 453으로 변하지 않았다.

이미 재생목록에서 빠진 조각도 나이 17.75초·21.95초·26.21초에 HTTP 200으로
다시 받을 수 있었다. 30.4초 시점에는 파일이 만료되어 HTTP 404였다.
조각의 표시 종료 시각(`PROGRAM-DATE-TIME + duration`)에서 파일 수정 시각을
뺀 값은 이전 관찰의 약 +4.04초에서 이번 관찰의 약 -0.86초로 달라졌다.
이 값은 스트림 시각과 파일 생성 시각의 비교이며, 실물 촬영부터 SaaS 표시까지의
전체 지연을 직접 측정한 값은 아니다.

사용자는 처음에는 **SaaS 화면을 새로고침한 뒤 정상으로 보인다**고 확인했으나,
이후 **SaaS의 FRONT 영상이 다시 멈춘다**고 보고했다. 앞선 짧은 수신·디코딩
검증과 새로고침 후 정상 표시는 장시간 재생 문제의 해결 완료를 뜻하지 않는다.
SaaS 재생 멈춤은 재현과 추가 점검이 필요한 상태다.

추가로 수집한 19:18 KST 이후 FRONT 접근 로그에는 재생목록 HTTP 200이
331회, 영상 조각 HTTP 200이 355회였고, 재생목록 HTTP 503이 6회와 영상
조각 HTTP 503이 2회 있었다. 이후 카메라 `/health`의 한 응답은 HTTP 200,
`ready=true`, `frames=62280`, `dropped=504`, 빈 오류 문자열이었다.
앞서 드롭 수치 453이 일정했던 결과는 짧은 관찰 구간에 한정되며, 이후에도
드롭이 늘지 않았다는 뜻은 아니다. 카메라의 단일 정상 상태 응답으로 SaaS
재생 멈춤의 해결을 판정하지 않는다.

19:17 KST에도 CAGE-001·002는 약 5초 간격으로 새 센서 메시지를 수신했다.
CAGE-001은 T1·RH1이 valid이고 T2·T3는 이전부터 이어진 null/invalid다.
CAGE-002는 네 채널 모두 valid였다. IR은 online/OFF로 확인됐고 IR 작업자는
11월 9일부터 같은 PID로 실행 중이었다.

TOP(`RGB-001`)은 약 19:21 KST에 네이티브 펌웨어 전체 기록과 각 기록 구간
검증, 설정 저장 응답까지 확인했다. 그러나 이후 `/health`는 HTTP 503,
`ready=false`, `frames=46`, `dropped=3`, `error=capture_timeout`을 반환했다.
TOP의 네이티브 동작 검증은 통과하지 못했다.

약 19:26 KST에 기존 16MB 전체 플래시 백업의 TOP 복원 기록과 전체 이미지
검증이 모두 종료 코드 0으로 끝났고, 전체 이미지의 다이제스트 일치를 확인했다.
19:27:18 KST에는 Gateway의 TOP(`RGB-001`)이 기존 `http_mjpeg`,
800×640/10fps 설정으로 `fresh=true`, 최신 조각 나이 1.34초를 보고했다.
최신 조각 시각은 `2026-11-26T10:27:16.949Z`였다. **TOP의 원래 펌웨어 복원과
영상 재수신을 확인했으며, 네이티브 H.264 전환은 미완료 상태다.**

같은 시점 FRONT는 네이티브 입력으로 `fresh=true`, 최신 조각 나이 2.38초,
조각 시각 `2026-11-26T10:27:15.952Z`였다. IR은 online/OFF/error=null이었다.
별도로 보낸 TOP의 기존 `/identity` 요청은 Gateway가 스트림을 받는 동안
ReadTimeout이었다. 이 직접 요청의 시간 초과를 TOP 오프라인으로 판정하지
않으며, 위 Gateway 영상 수신 결과와 함께 기록한다.

TOP 후보 설정은 Pi에 적용하지 않았다. FRONT와 기존 운영 설정도 변경하지
않았다. TOP의 복원 확인은 앞서 보고된 SaaS FRONT 재생 멈춤이 해결됐다는
판정과 구분한다.

## 2026-11-26 — 0.4.29 영상 조각 오류 격리 및 실물 검증

0.4.29 장애 분리 변경의 관련 검사에서 166개가 통과했고 2개는 건너뛰었다.
적용 전 약 3분 동안 기준 상태를 172회 관찰했으며, 이 관찰 구간에는 실패가
확인되지 않았다. 별도로 Pi 재생목록을 90회 요청해 모두 HTTP 200을 받았고,
응답 시간 중앙값은 0.034초, 최댓값은 0.073초였다.

이 수치는 해당 구간의 Pi 상태와 재생목록 응답 결과다. SaaS 브라우저에서
영상 진행이 계속되는지와 재발한 멈춤의 해결 여부는 별도 검증이 필요하다.
Gateway에는 `0.4.29-798e0028f991` 적용이 완료됐다. 기존 운영 설정과 키는
보존됐고 Air는 `0.4.27-60febc1deaf8`을 유지했다. 적용 복구 백업은
`/var/backups/habitatos-camera-segment-isolation/1795692461491565319`다.
배포 파일은 `dist/habitat-gateway-0.4.29-798e0028f991.tar.gz`이며 SHA-256은
`bcacca46159d8fdbd5de851304e6f0b50ddcab1f79980024b57ca1843b13b427`이다.
69개 파일 무결성과 임시 경로의 오프라인 설치, 설정·키 보존 및 설치 실패
복구 검사를 통과했다. 이 수정에서는 카메라 펌웨어를 기록하지 않았다.

20:30:56~20:40:55 KST 원본 HLS 목록과 수신기 상태를 575회 관찰했다.
FRONT에서는 4.001~4.002초인 조각 9개가 확인됐고, 이 조각이 15초 유효
범위 안에 있는 표본은 81개였다. 모든 표본에서 수신기·장치·H.264 확인 상태는
정상이었고, 수정본은 길이 제한을 넘는 조각만 제외해 정상 조각을 계속 반환했다.
빈 결과는 두 카메라 모두 0회였다. 기존 코드라면 이 길이 검증 실패가 목록
전체를 503으로 만들었으므로 실제 스트림에서도 해당 실패 조건이 존재함을
확인했다. 과거 보고된 모든 503의 원인이 같다고 단정하지는 않는다.

20:31:05~20:41:05 KST 공개 Gateway HTTPS API를 600초 동안 확인했다.
각 카메라의 재생목록 300회와 최신 영상 조각 51회, 합계 702회 모두 HTTP
200이었다. 404·503·통신 오류와 수신 세션 변경은 없었다. 카메라별 시작·중간·
종료 조각 총 6개는 모두 독립 디코딩에 성공했다. 재생목록 응답 p95는
FRONT 62.45ms, TOP 45.58ms였다. 이는 SaaS 로그인 화면의 연속 재생 시험이
아니며, 영상 조각의 PDT 나이를 실물 촬영부터 화면까지의 지연으로 해석하지 않는다.

20:30:54~20:31:03 KST의 읽기 전용 DB 확인에서는 CAGE-001·002 모두
message_id가 갱신됐다. CAGE-001은 T1·RH1 valid, T2·T3 invalid였고,
CAGE-002는 네 채널 모두 valid였다. IR 작업자는 PID 463332와 11월 9일
시작 시각을 유지하며 active/running이었다.

20:30:54 KST 공개 영상 API의 인증된 IR 조회 결과는
`online=true`, `status=on`, `gpio_requested_on=true`, `active=true`,
`error=null`이었다. 이는 19:27의 OFF 관찰과 다른 시점의 제어 상태다.
이번 점검은 영상 전용 키로 로그인한 뒤 상태만 읽었으며, IR 명령이나
서비스 재시작은 실행하지 않았다.
