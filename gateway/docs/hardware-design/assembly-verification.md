# 센서·카메라 실물 검증과 조립 검토 이력

## 현재 상태 — 2026-10-20 BB6 실물 사육장

사용자가 온습도 측정과 USB RGB 카메라를 갖춘 사육장 1개의 조립 완료를 확인했다.
실제 `habitat-pi`에서도 CAGE-001/ESP32-001의 `data_source=sensor`, TLS MQTT
수신과 신규 SQLite 저장 3건(T1·RH1·T2·T3 모두 valid)을 직접 검증했다.
USB 카메라는 실제 사진 1장과 5초 영상(1280×720, 37프레임, 4.965초)을
촬영하고 전체 디코딩했다. 소등된 환경이라 피사체·초점 판정은 남아 있다.

현재 구성은 **실물 센서·카메라 운영**이다. heartbeat 전용이나 가상 센서 구성이
아니며, 추가 물품을 사용하는 펌프·밸브·SAFE R15 확장은 별도 미완료 단계다.
출력 기능은 계속 잠겨 있다. 현재 배선은 SDA21/SCL22, T2 GPIO18, T3 GPIO19다.
아래 과거 R8/DevKitC 배선도의 GPIO13/14 및 커넥터 위치를 BB6에 적용하지 않는다.
R15 ARMED GPIO27은 향후 하네스·코드 동시 변경안이며 이번에는 적용하지 않았다.

[백업·서비스·실측 3건·촬영 파일·오류와 재검증 기록](../operations/hardware-arrival.md#bb6-actual-20261020).
이 최신 증거가 센서·카메라의 미조립/실물 시험 0건이라는 과거 표현을 갱신한다.
아래 문서·CAD·모의실험 결과는 당시 범위 그대로 보존하며 실제 분무·보호 시험으로
재분류하지 않는다. 이번 작업에서는 ESP32를 재업로드하지 않았다.

## 이전 검토 기준 (2026-10-04~07 이력)

최초 검토일: 2026-10-04. **현재 소프트웨어 검증은 2026-10-07 Pi·GPU 0.4.14, 신판 ESP32 두 역할 target build와 schema 2 통합 모의실험을 기준으로 한다.** 요청 상한 5초와 예상 RUN 3초의 분리 계약을 같은 소스에서 확인했으며 자세한 범위는 12절을 따른다. 2026-10-05/06의 구판 검사도 과거 이력으로 보존하고 신판 결과와 합산하지 않는다. CAD·MQTT·호스트 native·CUDA 가상 제어와 실물 시험은 별개이며 실제 ESP/Pico 업로드·조립·전기·분사 시험은 미실시다.

[그림으로 한 단계씩 보기](assembly-guide.html) · [전체 조립 안내 Markdown](assembly-guide.md)

사용자가 최초 HWP의 12개 품목을 확보했으며 아직 조립하지 않았다고 확인했다. 이 확인은 보유 범위의 근거이며, 납품품의 모델·핀 방향·치수·전원 상태를 직접 검사한 결과는 아니다. 본 기록은 조립 설명서의 근거와 남은 확인 사항을 관리한다. 실제 장치가 정상 작동한다는 합격 증명서로 사용하지 않는다.

## 1. 적용 범위와 정본

- 구매 기준: `(캡스톤디자인_랩타일시티) 재료 구매 신청서.hwp`의 12개 품목과 보유 Raspberry Pi **5**. 파일명에 `(1)`이 붙은 다른 신청서나 후속 XLSX의 물품을 이번 확보품으로 추가하지 않는다.
- 부품 목록: [phase1_manifest.json](phase1_manifest.json), 원 HWP 상품 링크: [hwp_links.txt](hwp_links.txt).
- 센서 노드 배선 기준: [pin_connections_R8.json](pin_connections_R8.json). 이 JSON의 범위는 A 노드이며 `physical_tests: 0`, `hardware_status: 미검증`이다.
- A/B/C 조립표: [phase1_connections.csv](phase1_connections.csv). 노드별 같은 전기 구조를 사용하되 프로브 이름을 구별한다.
- 운영 연결 범위: [hardware-arrival.md](../operations/hardware-arrival.md). 매장 Pi5, 사육장 ESP32 센서 노드, 별도 GPU PC와 SaaS PC라는 역할을 유지한다.

초기 조립 검토에서는 원본 HWP·XLSX·사용자 ZIP을 변경하지 않았다. 이후 사용자 승인에 따라 아래 구매목록 정리를 적용했다. 구매목록 정리는 실제 발주를 수행한 것이 아니다. 2026-10-05에는 별도로 Pi·GPU의 소프트웨어 검증과 GPU WSL 유지 설정 복구를 수행했으며, 실물 출력 잠금은 유지했다.

### 추가 구매목록 정리 (2026-10-04)

- `Desktop/신청서/신청서/HabitatOS_750000원_나머지_구매목록(1).xlsx`를 같은 파일에 수정했다. `(2).xlsx`, HWP와 사용자 ZIP은 그대로 보존했다.
- 최초 HWP 12품목 및 Pi 5 보유를 반영하여 중복 신규 주문을 0으로 변경했다. 활성 RGB 모델은 SMG-A USB-OV5628-A로 바로잡고, 다른 Waveshare 모델의 가격·규격을 확보품에 적용하지 않도록 구분했다.
- 빈 사육장 1개 시험을 기준으로 SN-04 전원, SN-05 데이터 케이블, M01 빈 사육장, TOOL-05 AAA 2개팩, TOOL-02 탈피도구만 각각 1판매단위의 **미보유 시 조건부 구매**로 남겼다. 기존 Pi 환경과 네트워크를 재사용하며 초기화·직결용 어댑터 구매는 요구하지 않는다.
- 기존 기록 가격 기준 조건부 상품액 **50,020원**, 기본 배송 참고액 **11,700원**, 합계 **61,720원**. 실시간 가격·재고·결제 운임을 새로 확인한 견적이 아니며, 기존 보유품을 재사용하면 줄어든다. 확정 발주액은 0원이다.
- 열화상·맞춤 선반·대량 배선 및 후속 분무품의 현재 발주수량을 0으로 보류했다. 기존 설계수량과 안전부품은 유지했다. 후속 소계 0원은 완성 비용 0원을 뜻하지 않으며, 분무·보호회로·원거리 영상 전송의 최종 비용은 미확정이다.
- 검증: 8개 시트·9개 표·237개 링크 수식, 기존 단가·조회일 및 과거 신청서 수량·금액 보존을 확인했다. 전원 수량 1→0 및 전체 조건부 수량 0 변경으로 상품액·배송 재계산을 시험하고 복원했다. 최종 수량 배분 차이 0건, 저장된 수식 오류 셀 0건. 화면 렌더 검사 완료. Microsoft Excel 앱 자체 실행 검증과 실제 하드웨어 검증은 수행하지 않았다.
- 조건부 수량을 변경할 때는 `수량 대조`의 보유 확인/보류 수량도 근거에 맞게 갱신한다. 배분 차이 0은 조립·전량 확보의 증명이 아니다.

### 후속 계획 금액 표시 개선 (2026-10-05)

- 같은 XLSX의 `나머지 구매분` 상단에 기존 계획 상품 소계 **853,073.4원**, 계산 가능한 운임 **40,800원**, 참고 소계 **893,873.4원**을 표시했다. 단가 미정 **4종**, 운임 미정 **6그룹**은 소계에서 제외되므로 전체 비용은 **미확정**이다. 현재 발주액 0원은 별도 행으로 표시하며 두 금액을 합산하지 않는다. 열화상 계획수량도 기존 0을 유지한다. 이는 기존 후속 구성의 과거 가격 기반 참고액이며 비용 절감 후 확정 구성의 견적이 아니다.
- `나머지 구매분` N열에 기존 계획수량, O열에 계획 상품액을 추가했다. `배송정산` P/Q열은 해당 계획의 상품액/운임을 계산한다. 발주수량 D열과 계획수량 N열을 구분하며, 미정 단가가 있는 배송 그룹의 계획 운임도 미확정으로 표시한다. `신청서 대조`의 후속 계획 소계 설명과 참조도 함께 갱신했다.
- 검증: 전원 계획수량 1→0 시 상품액 4,500원과 운임 2,500원 감소; 미정 PCB 계획수량 1→0 시 미정 품목/운임 건수 각각 1 감소; 모든 계획수량 0 시 계획 소계와 미정 건수 0. 시험 입력 복원 후 위 금액·건수를 확인했다. 8개 시트·9개 표·237개 구매 링크, 기존 값·수식·가격 이력 보존을 대조했고 저장 오류 셀 0건 및 화면 검사를 확인했다. 기존 파일에 저장하고 작업 임시파일을 정리했다.

### R15 제조자료 추가 확인 (2026-10-05)

사용자가 제공한 `C:/Users/<user>/Desktop/신청서/신청서/HabitatOS_R15_중앙보호PCB_제작자료_검증기록.zip`을 원본 그대로 검사했다. ZIP SHA-256은 `51a3a941ab124e46892d4f8f3656567000f2fa67ba0ce6a2ee33a01dd0c8b370`이다. 이전 R8 자료에서 R15 제조파일을 찾지 못했다는 판단은 이 새 자료에는 적용하지 않는다.

| 검사 대상 | 이번 검사 결과 | 범위·제한 |
|---|---|---|
| ZIP 내부 무결성 | 중복 경로 0개, `SHA256SUMS.txt`의 279개 파일 해시 전부 일치 | 해시 목록 자체를 제외한 모든 항목 대조 |
| 릴리스 목록 | `pcb/release_manifest.json`의 88개 파일 크기·해시 일치 | 제공된 릴리스 목록과 실제 ZIP 내부 파일 대조 |
| 제조파일 | 실제 KiCad 프로젝트·회로도·PCB, Gerber 9개, PTH/NPTH 드릴, BOM·실장 좌표 존재 | 압축 전체를 풀거나 제조사에 제출하지 않음 |
| BOM·좌표 | 40개 MPN 그룹·191개 부품과 PCBA 좌표 191행의 참조명이 일치 | 중복·누락 0개. 고객 Pico 소켓 2개를 별도 확인해 전체 좌표 193행과 대조 |
| 동봉 회로·PCB 검사 보고서 | 동봉 ERC 9개 회로도 위반 0, DRC 위반·미연결·회로도 대응 오류 0 기록 | 최초 ZIP 검토 당시 제공된 기록 확인. 이후 실제 재실행 결과는 아래 별도 기록 |
| 실물 시험 | 미실시 | 동봉 인수검사 41개 중 물리시험 31개는 측정값 미기록. 실제 RP2040 업로드·펌프 운전 확인 없음 |

제조 견적 검토에 사용할 자료는 `HabitatOS_R15/pcb/manufacturing/`의 Gerber·드릴, `PCBA_BOM.csv`, `positions_PCBA_191.csv`와 별도 고객 소켓 좌표다. PCB 사양은 160×100mm, 2층, 1.6mm, FR-4 Tg150, 1oz, 녹색 솔더마스크·흰색 실크·무연 HASL이다. PCBA 공급 범위는 191개 부품이고, 고객 Pico 소켓 2개와 외부 Pico H·DFR0457 5개는 구분한다. 실제 업체 DFM, 최소 제작·실장 수량, THT 실장 범위, 고객 소켓 처리, 조달·운임·세금 및 견적 금액은 아직 확인되지 않았다. **현재 상태는 제조 견적 검토 가능·발주 보류이며, PCB 가격은 미확정이다.**

동봉 `circuit/pico/`의 BENCH 펌웨어는 `HYDRAULIC_COMMISSIONED=0`으로 RUN·밸브·CYCLE_TRIG 출력이 잠겨 있다. USB/UART 명령 입력 대신 중앙 ESP의 J112 3.3V 디지털 요청·하트비트를 사용한다. 동봉 `outputs/HabitatOS_R15_PCB_배선_예산_합격기준.pdf` 3쪽의 N1 재사용 핀 배정은 GPIO25/32/23→REQ1/2/3, GPIO26→HB, GPIO19/33←ARMED/LEVEL이며 기존 센서 GPIO13/14/21/22와 충돌하지 않는다. **2026-10-05 구현 완료:** 같은 센서 펌웨어에 선택형 중앙 요청 역할을 추가했고, Pi API→인증된 MQTT→N1 요청 프로토콜의 세션·TTL·중복·취소·재접속 처리를 구현·시험했다. 센서형과 중앙형 ESP32 대상 빌드도 통과했다. 추가 ESP 구매는 문서상 필수가 아니다. 이 소프트웨어 결과와 실제 ESP/Pico 업로드·배선·실행 확인은 별개다. [R15 요청 계약](../protocols/r15-bridge.md)을 기준으로 하며, 원본 Pico 펌웨어와 하드웨어 출력 잠금은 유지했다.

동봉 펌웨어의 소프트웨어 RUN 제한은 3초, 하드웨어 제한창은 약 5초다. 2026-10-05에는 2·4·6초 RUN 후보 불일치를 수정하여 당시 [모의실험 설정](../../experiments/environment_sim/simulation_config.json)을 **1·2·3초 RUN 후보·상한 3초**로 제한했고 GPU 응답 계약도 이를 검사했다. 기존 학습 가중치의 입력 정규화 분모 6은 보존하여 정책 한도를 바꾸면서 모델 입력 의미를 바꾸지 않았다. 범위 초과·불일치·NaN과 오래된 4·6초 RUN 설정의 거절 및 학습 예측으로 후보를 고르는 동작을 [검사](../../tests/unit/test_environment_timing.py)한 당시 기록이다. 이때는 요청 상한 증대나 시간 변환을 적용하지 않았다. 이후 11절에서 요청과 RUN의 차이를 확인했으며, 12절의 개정은 Pico RUN 상한을 유지하고 **우리 ESP의 REQ 상한만 5초**로 바꾸는 설계다. `request_hold_ms`는 ESP 요청 신호 유지시간이며 Pico RUN 시간이나 실제 물의 양과 같다고 보장하지 않는다. J104는 24V 감시 입력이고 모터 전류 경로가 아니며, J106~J110의 가운데 2번 핀은 NC다. SAFE_GND와 POWER_GND를 임의로 합치지 않는다. 이 수정만으로 실물 배선·분무 출력을 승인하지 않는다.

수치 정정: 기존에 개별 요청처럼 적었던 28·38·90초는 실제 기록상 사육장별 8·8·15회 분무의 **누적 실행시간**이다. 개별 분무 후보와 누적 시간을 구분한다.

### 제조사 문서 감사: 도착 전에 확정할 사항 (2026-10-05)

실물이 없다는 이유로 규격·설계 검토를 보류하지 않는다. 아래는 정확한 모델의 제조사 문서, 구매처의 품목 식별 자료, R15 정본을 대조한 결과다. **문서로 확인한 설계 조건**, **문서만으로 발견한 수정 사항**, **실측으로 보정할 값**을 구분한다. 종별 적정 분무량이나 카메라 FPS를 임의로 채우지 않는다.

동봉 제조사 PDF는 16개 파일이며 중복을 제외하면 IC 13종과 Pico의 14종이다. PCBA BOM은 40개 MPN 그룹·191개 부품이다. 여러 저항값은 같은 제품군 데이터시트로 검토할 수 있지만, PDF가 들어 있다는 사실이나 구매 링크가 있다는 사실을 전체 품목의 내용 검토 완료로 세지 않는다. 원본 제조 BOM에는 일부 Murata 제품군 링크가 남아 있다. 아래 출처 정정은 현재 native 회로도와 PDF에 반영했고 원본 BOM은 보존했다. 원본 회로도의 외부 접점은 `REMOTE_NC_CONTACT_TO_BE_SELECTED`, 고객 소켓은 `USER_SUPPLIED_1x20_SOCKET` 표기이므로 그 이름을 제조사 품번으로 취급하지 않는다. 후속 목록의 RSF43Y100RF와 접점 설치 조건은 아래 별도로 대조했다. 2026-10-07 후속 검토에서 기존 구매목록의 PH 하우징·기압착 리드 조합을 제조사 도면으로 확인했으며, Pico 고객 소켓은 아래 조건부 후보와 남은 접합 조건을 기록했다. TI SLVUCT6은 도면 표현 참고 자료이며 R15의 동작 근거 데이터시트가 아니다.

| 대상 | 문서로 확정한 조건과 설계 판단 | 원문 |
|---|---|---|
| ESP32-DEVKITC-32E + SEN0331 | GPIO13/14 독립 온도 버스, SDA21/SCL22 및 3.3V 전원이 정본과 일치. SEN0331에는 SDA/SCL 각 10kΩ 풀업이 있으므로 추가 I²C 저항은 기본 구매하지 않는다. USB·5V핀·3V3핀 급전은 상호 배타적이다. | [Espressif 핀·급전](https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32/esp32-devkitc/user_guide.html), [DFRobot SEN0331](https://wiki.dfrobot.com/sen0331/), [V1 회로](https://dfimg.dfrobot.com/wiki/21163/SEN0331_sht31-digital-temperature-humidity-sensor_schematics_V1.0.pdf) |
| Adafruit 381 DS18B20 ×6 | 3.3V 사용과 DATA 풀업 4.7kΩ 확인. 제품에 저항이 동봉되므로 노드당 2개를 우선 사용한다. 판매명의 waterproof를 영구·고압 침수 보증으로 해석하지 않는다. | [Adafruit 381 배선·동봉품](https://www.adafruit.com/product/381), [ADI DS18B20](https://www.analog.com/media/en/technical-documentation/data-sheets/DS18B20.pdf) |
| SEN0331 설치·절연 | 센서 개구부를 테이프·접착제·코팅으로 덮지 않는다. 세척제·IPA·접착제 오염을 피한다. 배선 접속부 절연과 감지부 노출을 구분한다. 0–100%RH 측정범위가 직접 물 분사·침수 허용을 뜻하지 않는다. | [DFRobot 제공 Sensirion 취급지침](https://dfimg.dfrobot.com/nobody/wiki/ed23ca262d11f01046f949078f45a37c.pdf) 1·3·4쪽 |
| Pi 5 + UH505 | 허브는 데이터 4포트와 전원전용 1포트. 카메라 3대의 데이터 포트 수는 충분하다. Pi 5 USB 총전류는 전원 조건에 따라 1.6A 또는 600mA이므로 허브의 외부 급전 경로를 사용한다. 포트 수만으로 세 카메라의 동시 5MP FPS·전력까지 확정하지 않는다. | [EFM UH505](https://www.iptime.com/products/691?pd=3), [Pi 전원](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#power-supply) |
| 정확한 RGB 카메라 SMG-A USB-OV5628-A | 구매 SKU의 상세 본문에서 OV5693·5MP·자동초점·120°·USB2, 표준 UVC, MJPG/MJPEG·YUY2 및 해상도별 FPS 표를 확인했다. 판매 사양과 납품 장치의 실제 지원 모드는 구분한다. AF120 옵션의 최대 소비전력·VID/PID·UVC 버전·초점/노출 잠금 제어는 아직 미확인이다. 다른 Waveshare 모델이나 OEM의 다른 렌즈 옵션 수치를 적용하지 않는다. | [정확한 구매 상품 15668138](https://www.devicemart.co.kr/goods/view?no=15668138), [같은 SKU 상세 본문·모드표](https://www.devicemart.co.kr/goods/view_contents?no=15668138&setMode=pc&zoom=1) |
| USB RGB → 일반 ESP32 | 구매한 일반 ESP32는 USB OTG/PHY 지원이 없다. DEVKITC의 MicroUSB는 USB–UART 브리지 경로로 이 카메라의 호스트 포트가 아니다. 현재 보드에 USB 카메라를 직접 꽂는 무선 영상 구성은 채택하지 않는다. 카메라는 Pi USB 경로를 사용하며 원거리 무선 영상의 호스트 구성은 별도 선정한다. | [Espressif USB 지원표](https://docs.espressif.com/projects/esp-iot-solution/en/latest/usb/usb_overview/usb_overview.html#esp32-s-p-c-series-usb-peripheral-support) |
| 중앙 ESP와 J112 | 기존 N1 핀 배정을 유지하고 Pi 명령·만료·취소·중복·재접속을 처리하는 선택형 ESP 요청 역할과 Pi 어댑터를 구현했다. J112.1/.2 NC, .3 SAFE_GND, .4/.5/.6 요청, .7 HB, .8/.9 ARMED/LEVEL. 대상 빌드와 소프트웨어/MQTT 검사를 통과했으며 실물 GPIO 타이밍은 별도 검증한다. | 동봉 `outputs/HabitatOS_R15_PCB_배선_예산_합격기준.pdf` 3쪽, [R15 요청 계약](../protocols/r15-bridge.md) |
| 실제 실행 응답 | J112의 ARMED/LEVEL은 RUN·밸브·분사 완료 ACK가 아니다. U124/U125 오픈드레인의 HIGH는 전원 OFF·단선에서도 읽힐 수 있다. 구현한 계약은 `requested`/`execution_unverified`와 `actual_state=null`을 사용하고 일반 ACK·과거 관측값으로 R15 물리 상태를 채우지 않는다. HIGH 단독을 실제 분무 성공으로 승격하지 않는 동작을 시험했다. | `circuit/r15_safety_pin_netlist.json`, [TI 1G07](https://www.ti.com/lit/ds/symlink/sn74lvc1g07.pdf) §7.1/7.4, [R15 요청 계약](../protocols/r15-bridge.md) |
| LTC6993IS6-1#TRMPBF | 상승에지·재트리거 불가형 확인. RSET=118kΩ+1kΩ, DIVCODE7의 N=2,097,152에 공식식을 적용해 명목 4.99122176초를 독립 재계산했다. 저항 ±1%·100ppm/K·0–50°C와 IC ±3%를 적용한 4.78108758–5.20534892초가 동봉 계산과 일치한다. 이는 전기적 WINDOW 계산이며 분무량이 아니다. | [ADI LTC6993](https://www.analog.com/media/en/technical-documentation/data-sheets/ltc6993-6993-1-6993-2-6993-3-6993-4.pdf) 전기특성·표1·표2, [Yageo RC_L](https://yageogroup.com/content/datasheet/asset/file/PYU-RC_GROUP_51_ROHS_L) |
| STWD100NXWY3F / SN74LVC74APWR | 정확한 X옵션 watchdog 71–142ms·출력 LOW 140–280ms 확인. 25ms HB와 실제 에지 간격 상한 50ms는 설계 요구다. FF setup/hold/CLR 해제와 반대에지 ARM 구조를 공식 표의 전압 조건 안에서 대조했다. | [ST watchdog](https://www.st.com/resource/en/datasheet/stwd100.pdf) 12–13·17쪽, [TI LVC74A](https://www.ti.com/lit/ds/symlink/sn74lvc74a.pdf) §5.8 |
| JST PH 커넥터 | 2.0mm 피치, AWG24 조건의 2A·100V 정격. J104는 별도 0.5A 보호된 전압 감지 분기이고 J106–J110은 SIG/NC/GND 신호선이다. 펌프 전류를 PH 신호선으로 통과시키는 설계가 아니다. 하우징·접점·전선과 압착 조합까지 지정해야 하며 범용 CH254 2.54mm 점퍼와 혼용하지 않는다. | [JST PH](https://www.jst-mfg.com/product/pdf/eng/ePH.pdf) |
| 저항·커패시터 근거 보완 | Yageo RC_L 제품군 문서로 0805/1210의 공차·TCR·정격을 확인했다. Murata 품번별 문서에서 `GRM2165C1H131JA01D`는 0805·130pF±5%·C0G·50V, `GRM21BR71E105KA99L`은 0805·1µF±10%·X7R·25V를 확인했다. 10nF·0.1µF 문서도 확보했다. 1µF 품번은 제조사 검색에서 단종 예정으로 표시되어 발주 전 공급 상태 확인이 필요하며 자동 대체하지 않는다. X7R의 실제 동작 바이어스에서 유효 용량은 별도 검토 항목이다. | [Yageo RC_L](https://yageogroup.com/content/datasheet/asset/file/PYU-RC_GROUP_51_ROHS_L), [Murata 작성 130pF 문서 / Mouser 배포](https://www.mouser.lt/datasheet/3/76/2/GRM2165C1H131JA01_01A.pdf), [Murata 1µF](https://search.murata.co.jp/Ceramy/image/img/A01X/G101/ENG/GRM21BR71E105KA99-01.pdf), [Murata 10nF](https://search.murata.co.jp/Ceramy/image/img/A01X/G101/ENG/GRM2195C1H103JA01-01A.pdf), [Murata 0.1µF](https://search.murata.co.jp/Ceramy/image/img/A01X/G101/ENG/GRM21BR71H104KA01-01.pdf), [제조사 품번 조회](https://ds.murata.co.jp/simsurfing/mlcc.html?partnumbers=%5B%22GRM21BR71E105KA99%22%5D) |
| GST90A24-P1M + SFDP2-010-040-21 + KCC KAB21-02-2-DC24V | 24V·3.75A 전원, 펌프 제조사 표 최대 소비전류 2A, 밸브 DC24V±5%·7.5W·상시 닫힘을 대조. 정상 1밸브 순차 운전 산술은 2.3125A/55.5W로 전원 정격 안이다. 2A를 기동전류로 부르지 않는다. 공급 최저 23.28V와 밸브 최저 22.8V 사이 손실 예산은 0.48V이며 그 안에 배선·접점·DFR 손실이 들어가야 한다. | [MEAN WELL](https://www.meanwell.com/Upload/PDF/GST90A/GST90A-SPEC.PDF), [SEAFLO 정확 모델 표](https://www.seaflo.com/index.php?a=index&aid=476&c=View&m=home), [KCC 작성 카탈로그](https://cdn.komachine.com/media/product-catalog/kccpr_62925_wcuuqe.pdf). 현행 XLSX `나머지 구매분` 16–18행 |
| DFR0457 ×5 | 부하 입력 5–36V·제어 3.3–10V로 24V 부하와 R15의 5V 신호 드라이버 구성은 명목 규격 범위다. 모터·솔레노이드에는 부하 옆 플라이백 다이오드가 필요하다. 제조사가 공개하지 않은 입력 전류·접점 등가강하·직렬 두 모듈의 고장협조를 전형 330Ω 시험부하로 대체하지 않는다. | [DFRobot 공식](https://wiki.dfrobot.com/dfr0457). 현행 XLSX 30행 |
| 퓨즈·전원 보호협조 | 현행 구매목록의 8A `0314008.MXP`, 2A `0314002.MXP`, 0.5A `0314.500MXP`는 R15 선정품과 일치한다. GST90A의 110–150% 출력전력 히컵과 8A 퓨즈의 연속 시험전류 차단시간을 비교하면, 3.75A 전원에서 퓨즈가 신속 용단할 것이라는 근거는 없다. 문서 검토상 정상 전류 예산 적합과 고장 보호협조 미입증을 분리한다. | [Littelfuse 314](https://www.littelfuse.com/assetdocs/fuse-314-and-324-datasheet?assetguid=24deec6d-9c03-4f0e-b612-8499127355f3), [MEAN WELL](https://www.meanwell.com/Upload/PDF/GST90A/GST90A-SPEC.PDF). XLSX 37·38·49행 |
| RSF43Y100RF ×2 | 수위 플로트 접점이며 180° 회전으로 NO/NC 동작을 바꾼다. 저수위와 받이 고수위에 각각 정상 시 닫힘이 되도록 설치 방향을 구분한다. 얇은 누수막 즉시 검출기가 아니다. 최대 접점 정격으로 R15 EOL 저전류 접점의 최소 젖음전류 성능까지 보증하지 않는다. | [Sensata 작성 데이터시트 / RS 배포](https://docs.rs-online.com/f52f/0900766b815b60d2.pdf). XLSX 32행 |
| 전력 접속 부품 | `01550100Z` 홀더 3개는 최대20A·32V 이하, `54-00064` 잭은 최대6A·48VDC 및 온도 조건, WAGO `221-413`은 해당 구리 AWG16/24 접속 범위를 확인했다. 홀더는 퓨즈 미포함이며 제공 스프링 중 카트리지에 맞는 것을 사용한다. 논리 JST PH와 전력 잭·홀더·분배선을 구분한다. | [Littelfuse 홀더](https://www.littelfuse.com/assetdocs/littelfuse-fuse-holder-155-100-datasheetpdf?assetguid=feb34c70-4b5c-48a2-88f9-895c15c5efcc), [Tensility 도면](https://tensility.s3.us-west-2.amazonaws.com/uploads/pdffiles/54-00064.pdf), [WAGO](https://www.wago.com/gb/products/electrical-interconnections/splicing-connectors-221). XLSX 39·40·48행 |
| 구매 전선 상세 자료 | `GSH-001661`의 판매 브랜드 자체 목록에서 UL2464·AWG16×2C·10m·검정을 확인했다. `CBAZY 24AWG 6색`을 포함하여 정확한 제조사 도체 저항·재질·가닥 구성·허용전류/온도·인증 파일 자료는 확보하지 못했다. AWG/UL 문자열이나 WAGO 접속 가능 범위가 전선 정격의 증명은 아니다. 발주 전 품번별 자료와 하우징·접점·압착 조합을 확인해야 하며, 타 판매품의 PVC/실리콘 사양을 섞지 않는다. | [거상인 자체 목록](https://gersangin.com/goods/goods_list.php?cateCd=105016), 현행 XLSX 46–47행. 판매품 식별은 확인, 제조사 상세 문서는 공백 |

**고객 소켓·PH 하네스 조달 대조(2026-10-07):** 원본 ZIP의 정본 핀맵, 현재 native PCB·소켓 풋프린트, 기존 `(1).xlsx`의 `나머지 구매분` 15·42–47행을 읽어서 대조했다. 원본 BOM·ZIP·구매 셀은 변경하지 않았다. 표의 수량은 N열의 기존 계획 수량이며, 해당 행의 현재 주문 수량 D열은 모두 0이다. 구매 완료 수량으로 표현하지 않는다.

| 연결 대상 | 기존 목록·정본 대조 | 제조사 근거와 선정 상태 |
|---|---|---|
| J102/J103/J104/J105/J111 | PCB `B2B-PH-K-S(LF)(SN)` 5개 ↔ `PHR-2` 5개 | 같은 PH 2mm 계열의 2극 짝을 확인했다. J104는 전압 감지 분기다. [JST PH](https://www.jst-mfg.com/product/pdf/eng/ePH.pdf) 3쪽 |
| J106–J110 | PCB `B3B-PH-K-S(LF)(SN)` 5개 ↔ `PHR-3` 5개 | 정본의 1=SIG, 2=NC, 3=SAFE_GND를 유지한다. 가운데 빈 위치를 채우거나 CH254 점퍼로 대체하지 않는다. [JST PH](https://www.jst-mfg.com/product/pdf/eng/ePH.pdf) 3쪽 |
| J112 | PCB `B9B-PH-K-S(LF)(SN)` 1개 ↔ `PHR-9` 1개 | 정본의 1/2=NC, 3=GND, 4/5/6=REQ, 7=HB, 8/9=ARMED/LEVEL을 유지한다. [JST PH](https://www.jst-mfg.com/product/pdf/eng/ePH.pdf) 3쪽, [요청 계약](../protocols/r15-bridge.md) |
| PH 리드 E14 | 기존 `ASPHSPH24K305` 14개 | JST 조립 도면 **GAM-060 Rev.1**은 양 끝 `SPH-002T-P0.5S`, 검정 UL1007 AWG24, 내부 길이 304.8±5mm, 대응 PHR-2/3/9를 명시한다. 기존 조합의 정확 품번은 확인됐다. [JST 조립 도면](https://gam-gec.com/wp-content/uploads/2018/10/GAM-060.pdf), [JST GAM 사업부 식별](https://gam-gec.com/) |
| 별도 전선 압착 | `CBAZY` AWG24 신호 연장선 / `GSH-001661` AWG16 전력선 | `SPH-002T-P0.5S`는 AWG30–24·절연 외경 0.8–1.5mm 대상이다. CBAZY의 AWG 표기만으로 절연 외경·압착 적합성을 확정하지 않는다. AWG16은 이 접점의 적용 범위 밖이다. 기존 기압착 리드를 사용하면 PH 끝단의 새 압착은 필요 없으며 연장 접속부는 별도로 확인한다. [JST PH](https://www.jst-mfg.com/product/pdf/eng/ePH.pdf) 2쪽 |

정본에서 사용하는 하네스 접점은 **27개**다: 2극 5개에서 10개, SIG/GND 5쌍에서 10개, J112에서 7개다. 기압착 리드 14개에는 접점 28개가 있으므로 **절단해서 짧은 편단 리드로 쓰는 구성의 접점 수**는 충족한다. 실제 설치 경로·스트립 길이·당김 여유를 측정하기 전에는 14개가 모든 배선 길이를 충족한다고 판정하지 않는다. 중앙 절단을 강제하지 않으며, 짧은 조각으로 도달하지 못하는 경로는 절단 배분·연장 방법을 정해야 한다. 하우징의 1번 위치는 JST 도면의 표시와 PCB 패드 1을 대조하고, 결합면과 전선 삽입면을 뒤집어 읽지 않는다. 삽입 후 각 선의 유지·극성·무전원 도통을 검사한다.

Pico용 두 소켓은 native에서 `(10,15)`와 `(27.78,15)`에 있고, 20극·2.54mm 피치·첫/끝 패드 간 48.26mm·두 줄 간 17.78mm·공칭 드릴 1.00mm이다. [Pico 공식 기구 도면](https://datasheets.raspberrypi.com/pico/pico-product-brief.pdf) 4쪽의 피치·배치와 일치한다. [공식 Pico 계열 설명](https://www.raspberrypi.com/documentation/microcontrollers/pico-series.html)에 따르면 Pico H는 헤더가 실장된 변형이다. 이 자료에서 **납품 Pico H 수핀의 단면·노출 길이까지 확인한 것은 아니다.**

- 기존 SN-10 `CONNFLY Single 1×20 Straight 2.54mm / 상품3587`은 ESP 탈착용이다. [CONNFLY DS1023 공식 도면](https://en.connfly.com/static/upload/file/pdf/DS1023.pdf)은 1×20·2.54mm와 8.5/5mm 높이 옵션을 포함하지만, 구매 SKU3587을 정확한 높이·도금 주문 코드에 대응시키지 못했다. 이 소켓 2개를 Pico용으로 확보했다고 간주하지 않는다.
- **조건부 검토 후보 `Harwin M20-7822042` 2개:** [정확한 제품 페이지](https://www.harwin.com/products/M20-7822042)와 [공식 도면 Rev.11](https://content.harwin.com/asset/53851ba8-b32e-4ac5-a0c5-09d9271c0c0a/DRG-00385-Technical-Drawing-Datasheet-M20-782-pdf.pdf)은 20극·2.54mm·몸체 51.20×2.50mm·기판 위 높이 8.50mm·THT 꼬리 3mm·권장 PCB 홀 Ø1.02±0.05mm·결합 수핀 0.64mm 정사각형을 명시한다. R15의 공칭 1mm 홀은 권장 홀 범위 안이며 피치·극수는 일치한다. 이는 도면상 대조 결과다. 실제 제작 후 홀 공차, 본체·주변 부품·USB 케이블 간섭, Pico H 수핀의 단면·접점 도달 길이를 확인해야 최종 선정할 수 있다. 소켓을 절단해 쓰는 품목이 아니며 구매목록에 자동 추가하지 않았다.

이번 대조로 **PH 하우징·압착 접점·리드 전선의 정확 조합 공백**은 해소했다. 남은 문서 조건은 Pico H 수핀/선정 소켓 접합 조건, SKU3587의 정확 제조사 코드, 개별 전선 상세 규격이다. 남은 조립 조건은 실제 경로 길이, 접점 삽입·극성·연장부·소켓 간섭·완성 홀 확인이다. GPIO·분사·발열 시험 통과로 승격하지 않는다. 내려받아 확인한 원문 SHA-256은 PH `447624f4f2f7d37c58c1eaa7ee314ad757fe7aff48f6186491ef6f69fbc00b96`, GAM-060 `501f7d06730cd26bddb9782355fc650298577bc026ea2af9a8b618e7a97eb80a`, Harwin 도면 `dc63950fd4db62272f85d19d3c48739909c6909ae21502f38542ba9acfd2fcf5`, CONNFLY 도면 `3ae996d1a0eb33f5f05a416054090b1fc6b73aff4ad6e9a652f042df14ee3be1`이다. 원문·확인용 그림의 중복 사본은 임시 검토 뒤 정리한다.

**데이터시트 출처 정정:** 원본 R15 BOM·정본 및 최초 DOC1 native의 `BC857B-7-F` 출처 `ds11108.pdf`는 실제로 NPN BC846A–BC848C 문서다. 정확한 PNP 출처는 [BC856A–BC858C / DS11207](https://www.diodes.com/datasheet/download/BC856A.pdf)이며 해당 주문 MPN을 포함한다. NPN `BC847B-7-F`는 [BC847B / DS11108](https://www.diodes.com/datasheet/download/BC847B.pdf), `BAS116-7-F`는 [BAS116 / DS30233](https://www.diodes.com/datasheet/download/BAS116.pdf), `1N4148W-7-F`는 [1N4148W / DS30086](https://www.diodes.com/datasheet/download/1N4148W.pdf)를 사용한다. **2026-10-05 후속 검사에서 실제 DOC1 native와 PDF의 출처를 정정했다.** Diodes 4종·Murata 3종·Yageo 15종, 합계 22개 MPN에 해당하는 부품 149개의 `Datasheet`만 변경했으며, 원본 ZIP·정본 JSON·제조 BOM은 보존했다. 정확한 MPN·기존 URL·새 URL이 모두 일치하는 정정만 검사기가 허용한다. 다른 메타데이터·핀·연결 변경은 허용하지 않는다. 새 해시와 실제 재검사 결과는 아래 후속 기록을 기준으로 한다.

**정확한 카메라 판매 사양 재확인(2026-10-05):** 상품번호 15668138의 [별도 상세 본문](https://www.devicemart.co.kr/goods/view_contents?no=15668138&setMode=pc&zoom=1)에 아래 모드표가 있다. 형식명은 본문에 `MJPG/YUY2`, 모드표에는 `MJPEG/YUY2`로 적혀 있다. 표준 UVC·USB 2.0·자동초점·120°·38×38×6.6mm·40cm USB 테스트 케이블도 판매 사양으로 확인했다. **아래 값은 해당 SKU의 판매 표기이며, 실물 USB 열거·동시 수집 시험 결과가 아니다.**

| 해상도 | MJPEG 판매 표기 | YUY2 판매 표기 |
|---|---:|---:|
| 640×480 | 30fps | 30fps |
| 1280×720 | 30fps | 10fps |
| 1920×1080 | 30fps | 5fps |
| 2048×1536 | 30fps | 2fps |
| 2592×1944 | 30fps | 2fps |

판매 이미지의 PCB 실크 `HBVCAM-5M2134 V11`을 따라 [HBVCAM 공식 제품군 페이지](https://www.hbvcamera.com/5megapixel-usb-cameras/usb-camera-module-with-auto-focus.html)를 확인했다. 이 페이지는 자동/고정초점과 여러 렌즈 옵션을 함께 소개하지만 상세 표는 **고정초점·74°·높이 25mm** 옵션이다. 구매 SKU의 **자동초점·120°·높이 6.6mm**와 완전히 일치하는 제조사 옵션 문서로 확정하지 않는다. 그 표의 최대 소비전력 **920mW**를 구매 카메라의 최대 전력·기동전류나 3대 USB 전력 예산에 전용하지 않는다.

**카메라·전선 자료의 다음 확인 단위:** RGB의 UVC 지원 표기와 위 모드 조합은 확인했다. 남은 문서 조건은 정확한 OEM AF120 옵션/납품 보드 리비전 대응, VID/PID·UVC 버전, 초점·노출 잠금 제어, 정상·기동 최대 전류, 120° 화각의 기준축이다. 납품 장치의 USB descriptor·실제 모드 목록, 안정 장치 경로, 3대 동시 FPS·대역폭·전압은 연결 후 따로 측정한다. 전선은 위 품번별 저항·도체·절연·인증과 압착 조합 자료가 필요하다. 추가 호스트 발주에 영향을 주는 문서 조건을 실물 도착만의 문제로 보류하지 않으며, 이번에 값을 추정하거나 대체품을 새로 주문하지 않았다.

**공개 판매자료 재추적(2026-10-05):** [카메라 상품 15668138](https://www.devicemart.co.kr/goods/view?no=15668138)과 [CBAZY 상품 12375538](https://www.devicemart.co.kr/goods/view?no=12375538)의 메인 판매 페이지는 관련자료 0개를 표시한다. 이는 첨부 자료 개수이며 **카메라 상세 사양·모드표가 없다는 뜻이 아니다.** 별도 로딩되는 위 상세 본문에서 UVC·포맷·FPS 표를 직접 확인하여 이전의 자료 부재 판단을 정정했다. AF120 옵션에 대응하는 전체 제조사 문서 확보와는 구분한다. CBAZY 12375538은 6색·각6m의 실리콘 연선 판매품이고, [UL1007 60m 상품 12375531](https://www.devicemart.co.kr/goods/view?no=12375531)은 별도 품목이다. 후자의 절연·정격을 전자에 옮겨 적용하지 않는다.

판매사에 전달할 요청 내용은 다음과 같다. 이번 작업에서 문의를 실제 발송하거나 구매하지 않았다.

- 카메라 15668138: 이미 확인한 판매 모드표에 대응하는 OEM AF120 옵션·납품 보드 리비전 문서, VID/PID·UVC 버전, 정상·기동 최대 전류, 초점·노출 잠금 제어와 화각 기준축 정보를 요청한다.
- GSH-001661: 제조사 품번, 도체 재질·가닥 구성·최대 저항, 전압·온도 정격, 설치 조건을 포함한 허용전류, 해당 제품의 UL 인증 파일 번호를 요청한다.
- CBAZY 12375538: 주문 SKU와 OEM 품번의 대응 및 그 품번의 도체·저항·전류·온도·인증 문서를 요청한다.

1차의 나머지 소모품·계측기 문서 수준도 구분했다. [PROKIT MT-1233C 제조사 문서](https://shop.prokits.com.tw/instruments/moreinfo_77458.htm)는 DC전압·저항·도통 및 AAA 2개를 확인하고, [Asahi SCS7 합금 문서](https://asahisolder.com/wp-content/uploads/2023/06/DS_SCS7-Solder-Alloy-E-Ver-8.pdf)는 해당 합금·수동 납땜 용도를 확인한다. 반면 PCB-0709D의 26×31 홀 배열·A1 좌표, CH254 점퍼의 전류 정격·선재, 케이블타이의 하중·내후성, 상품9838 테이프의 방수·내열 등급은 정확한 제조사 자료가 없다. 해당 판매 설명을 넘는 성능을 임의로 부여하지 않으며, 기판은 조건부 좌표도, 점퍼는 센서 신호, 타이는 배선 정리, 테이프는 접속부 절연 보조로 범위를 정한다.

당시 3초 RUN 후보 제한과 Pi/N1 요청·미확인 실행 상태 계약은 소프트웨어 구현·검사를 수행했다. 당시 결과는 요청 시간과 실제 RUN의 일치를 검증한 것이 아니다. 이후 11절의 발견에 따라 분리 계약을 개정했고, 12절에 기록한 2026-10-07 동일 소스 배포·소프트웨어 종단 검증을 완료했다. 이는 지정 가상 timing 조건의 결과이며 실물 요청/RUN 시간 일치의 증거가 아니다. 카메라의 판매 UVC·모드·FPS 표는 확인했으며, 정확한 OEM AF120 옵션의 전원·식별·제어 문서와 실물 영상 시험은 남아 있다. 전선 상세 규격, 실물 센서·GPIO·기동 파형·발열·접점 강하·노즐 토출량·사육장 습도 응답, 신규 R15 상태의 SaaS 운영 수신도 별도 항목이다. 구현·빌드·통신 시험을 실제 분사 검증으로 표현하지 않고, 제조사 자료 공백도 실물 도착만의 문제로 분류하지 않는다.

동봉 전체 시스템 예산은 초기 구매품·이전 사육장 구성을 포함한 과거 자료이므로 현재 추가 구매액으로 가져오지 않았다. 기존 구매목록 `(1).xlsx`에는 4개 시트의 상태 문구 8개만 반영했다. 나머지 셀·서식·네이티브 구조를 원본과 대조해 가격·수량·계산식 1,298개 및 구매 링크 237개 보존, 저장된 오류 셀 0개를 확인했다. 저장본을 다시 열어 계획 상품액 853,073.4원·운임 40,800원·참고 소계 893,873.4원, 미정 단가 4종·미정 운임 6그룹이 유지됨을 확인하고 변경 화면을 검사했다. Microsoft Excel 앱 자체 실행 검사는 하지 않았다. 원본 ZIP·HWP·구매 이력을 보존하며 새 배포 ZIP이나 전체 압축 해제본을 만들지 않았다. 검토용 임시 그림·파일은 정리한다.

### 무선 USB 영상 호스트 구성 명시 (2026-10-07)

원거리 사육장의 구성은 **구매 USB 카메라 → 카메라 곁의 별도 Linux USB 영상 노드 → Wi-Fi → 매장 Pi 5 → GPU PC**로 설계한다. 영상 노드는 USB를 읽고 영상을 전달하며, 매장 등록·사육장 관리·장치 제어·SaaS 동기화는 기존 매장 Pi가 맡는다. 일반 ESP32-DEVKITC-32E는 센서·제어용으로 유지한다. 매장 Pi의 USB 직결 수집 프로그램은 구현·소프트웨어 검사 범위이고, 구매 AF120 카메라의 실제 촬영은 미검증이다. 아래의 무선 영상 구성은 문서 설계안이다.

**하드웨어 상태: Pi Zero 2 W는 미구매·조건부 검토 후보이며 최종 미선정이다.** [Raspberry Pi 공식 제품 brief](https://datasheets.raspberrypi.com/rpizero2/raspberry-pi-zero-2-w-product-brief.pdf)의 3쪽은 USB 2.0 OTG 1개, 1GHz 4코어 Arm Cortex-A53, 512MB LPDDR2, 2.4GHz 802.11b/g/n, microSD와 5V DC·2.5A 입력 전원을 명시한다. [공식 OTG 설명](https://pip-assets.raspberrypi.com/categories/685-app-notes-guides-whitepapers/documents/RP-009276-WP-1-Using%20OTG%20mode%20on%20Raspberry%20Pi%20SBCs)은 Zero 계열의 데이터 포트 `USB`와 전원 포트 `PWR IN`을 구분한다. 카메라를 읽는 역할은 USB host이며, [Raspberry Pi Linux overlay 문서](https://raw.githubusercontent.com/raspberrypi/linux/rpi-6.12.y/arch/arm/boot/dts/overlays/README)의 `dwc2`는 `dr_mode`에 host/peripheral/otg를 지원한다. 납품 카메라 커넥터에 맞는 데이터 케이블·OTG 호스트 변환과 OS 설정은 별도 확인한다.

[공식 전원 표](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#power-supply)는 Zero 2 W의 권장 공급용량 2A, 전형적인 bare-board 활성 전류 350mA를 별도로 제시하며 USB 주변장치 전류는 공급기·보드·커넥터 정격에 의해 제한한다고 설명한다. 제품 brief의 5V·2.5A와 이 표의 전형값을 구매 카메라의 전력 예산으로 변환하지 않는다. **350mA는 최대 보드 전류가 아니며, AF120의 정상·기동 최대 전류가 미확정이므로 공급용량에서 전형값을 뺀 차이를 카메라 허용전류로 사용하지 않는다.** 후보의 실제 급전·USB 전압강하·기동·발열 조건을 통과한 기록은 없다.

Linux의 [UVC 드라이버 문서](https://cdn.kernel.org/doc/html/latest/userspace-api/media/drivers/uvcvideo.html), [형식 열거](https://www.kernel.org/doc/html/latest/userspace-api/media/v4l/vidioc-enum-fmt.html), [프레임 간격 열거](https://www.kernel.org/doc/html/latest/userspace-api/media/v4l/vidioc-enum-frameintervals.html)는 USB 영상 장치의 형식·프레임 간격·제어 정보를 조회하는 근거다. 구매 SKU의 판매 UVC 표기를 바탕으로 이 경로를 검토하며, 정확 AF120 옵션의 실제 모드·VID/PID·보드 리비전·초점/노출 제어 지원은 OEM 자료와 납품 장치 조회로 확인한다. 같은 센서나 다른 렌즈 옵션의 자료로 호환을 확정하지 않는다.

| 단계 | 정한 역할·인터페이스 | 구현·검증 상태 |
|---|---|---|
| 카메라 → 영상 노드 | 단일 리더가 실제 지원 모드를 확인한 뒤 USB UVC 영상을 읽는다. 확인된 MJPEG는 재압축 없이 MKV 분할 영상과 JPEG 미리보기에 사용한다. | 기존 [단일 FFmpeg 수집 코드](../../habitat/vision/cameras.py)는 로컬 USB 경로다. 후보 보드·AF120 조합은 미시험 |
| 영상 노드 → 매장 Pi | 미리보기와 완료된 클립을 인증된 HTTPS push로 전송하는 계약을 설계한다. 매장 Pi가 등록된 영상 노드·사육장·카메라 대응을 검증하고 저장한다. | 원격 송신기·Pi 수신 API는 미구현. 현재 센서 MQTT 경로에 영상 파일을 넣지 않음 |
| 매장 Pi → GPU | 초기 다시점 RGB 스캔은 기존 이미지 업로드·3D 작업 계약을 사용한다. 연속 영상의 행동 분석은 별도 영상 작업 계약으로 구분한다. | 기존 GPU 입력은 JPEG/PNG 다시점 묶음이다. 원격 영상 자동 전달·MKV 행동 작업 API·학습된 행동 모델은 없음 |

**무선 전송 계약의 설계 조건:** 매장 Pi에 등록된 `site_id/gateway_id/cage_id/camera_id/host_id`와 영상 업로드 전용 인증정보를 대응시킨다. 영상 노드에 매장 전체 제어 API 토큰을 공유하지 않는다. 프레임·클립의 ID, 세션 ID, 순번, 바이트 크기·SHA-256, 실제 영상 형식·해상도, 원본 시각의 의미와 상대 PTS, 시계 동기화 상태, Pi 수신 시각을 보존한다. 원본 시각이 프로세스 시작 시각인지 실제 프레임 시각인지 구분하고 센서와의 동기화를 임의로 보증하지 않는다. 원본 시각이 불명확하면 그 상태를 기록한다.

수신 시에는 등록 대응·인증·크기·해시·영상 형식과 저장 한도를 검사하고 임시 수신 파일을 완성 파일로 전환한다. 같은 ID·같은 내용의 재전송은 중복 저장을 만들지 않고, 같은 ID·다른 내용은 충돌로 처리한다. 불완전한 클립은 분석 입력으로 쓰지 않는다. 끊김·저장 한도·GPU 장애는 관측/전달 상태로 표시하고 지난 영상을 현재 영상으로 표시하지 않는다. 저장 ACK는 해당 저장 단계의 완료만 뜻한다. Pi 저장·GPU 전달·분석 완료를 별도 상태로 관리하며, 보존 자료를 임의 삭제하지 않는 저장 정책과 재전송 한도를 정한다. 이 조건은 수신 계약의 설계안이며 실제 API 검사 통과 기록이 아니다.

완료 클립 전송은 실시간 스트리밍과 동일하지 않다. 결과 지연에는 클립 분할 구간·전송·대기·GPU 추론 시간이 포함된다. [FFmpeg V4L2 문서](https://ffmpeg.org/ffmpeg-devices.html#video4linux2_002c-v4l2)에 따라 납품 장치에서 형식·크기·프레임 간격을 확인하고, 사용 모드·압축·보존·전송 조건에서 Wi-Fi 처리량·드롭·지연을 실측한다. 후보의 무선 규격이나 판매 FPS를 이 경로의 보장 FPS·지연으로 쓰지 않는다. 고정 카메라의 반복 영상은 새로운 시점을 만들지 않으므로 초기 3D 복원에는 별도의 다시점 스캔·보정이 필요하다.

**현재 프로그램과의 접점:** [CameraConfig](../../habitat/vision/cameras.py)는 `/dev/v4l/by-id` 또는 `/dev/v4l/by-path`만 허용하고, 수집기는 로컬 장치 존재 검사와 V4L2 입력을 사용한다. 현재 설정 상한은 1920×1080이므로 판매표의 2592×1944 수집을 구현 완료로 표시하지 않는다. [Pi 카메라 API](../../habitat_gateway/api.py)는 상태·미리보기 조회를 제공하며 원격 영상 수신 기능은 없다. [GPU capture 계약](../../habitat/compute/contracts.py)은 다시점 JPEG/PNG 3–500장 입력이다. 후속 원격 수집에서는 USB/영상 노드 입력 구분·등록 대응·수신 상태·전용 업로드 권한과 영상 작업 계약을 연결해야 한다. 이번 문서 보완에서 소스 기능·카메라 설정·실행 서비스는 변경하지 않았다.

**후속 인수 조건:** 정확 AF120의 OEM/납품 리비전·정상/기동 전력·UVC 제어 자료, 영상 노드의 보드·전원·OS·OTG 케이블 식별을 먼저 확인한다. 그다음 한 카메라의 실제 USB 열거·지원 모드·단일 리더·재연결, 기동 및 USB 전압·발열, 네트워크 끊김/재전송·등록 충돌·저장 한도·GPU 장애, 실제 영상 클립/미리보기와 시각·지연을 각각 검증한다. 이 결과 전까지 후보를 최종 선정하거나 원거리 영상·GPU 분석의 실물 작동을 합격 처리하지 않는다. 역할·인터페이스와 후보 근거는 본 절에 명시했으며, 호스트 구매·원격 수신 구현·GPU 영상 과제와 물리 인수는 후속 작업으로 남긴다.

### 전력 보호 제조사 자료 재검토 (2026-10-07)

[SEAFLO 21-series 공식 설치 설명서](https://www.seaflo.com/uploads/soft/20220905/1-220Z5113225331.pdf)는
양극선의 8A 퓨즈를 지정한다. 기존 8A 선정의 근거는 확인했지만, 이 지정이 현행 3.75A
공급기·배선·직렬 DFR 모듈 전체의 고장 차단을 입증하지는 않는다.
[Littelfuse 314](https://www.littelfuse.com/assetdocs/littelfuse_fuse_314_324_datasheet.pdf?assetguid=24deec6d-9c03-4f0e-b612-8499127355f3)의
연속 시험은 135% 전류에서 최대 1시간, 200%에서 최대 15초다. 8A의 해당 시험전류는
10.8/16A, 2A는 2.7/4A, 0.5A는 0.675/1A다. 평균 곡선·명목 melting I²t를 임의 기동전류나
히컵 펄스의 보장 용단 시간으로 변환하지 않는다.

[GST90A 사양서](https://www.meanwell.com/Upload/PDF/GST90A/GST90A-SPEC.PDF)의 출력 전력
110–150% 과부하를 4.125–5.625A로 환산하는 것은 **출력 24V가 유지될 때만** 유효하다.
단락 전류 상한이 아니다. [정확 24V 모델의 제조사 샘플 시험기록](https://www.meanwell.com.cn/upload/pdf/GST90A/GST90A24-rpt.pdf)은
2007년 샘플의 OLP 134.4%/230VAC·128.8%/115VAC, 단락 1시간 무손상·히컵을 기록하지만,
DC 단락 파형·on/off 주기·배선과 모듈의 누적 에너지는 제시하지 않는다. 해당 기록의 온도
시험 모델은 48V형이므로 그 케이스 온도를 24V형 실측으로 옮기지 않는다. 현행 온도 저감
그래프도 적용해야 하며 90W를 모든 주변 온도에서 사용할 수 있는 정격으로 설명하지 않는다.

[DFR0457 공식 V1.0 회로도](https://dfimg.dfrobot.com/wiki/17549/DFR0457_mosfet-power-control-module_schematics_V1.0.pdf)는
광입력과 high-side MOSFET 구조를 확인할 수 있다. Q1/U1의 정확 품번·RDS(on)·SOA·누설·
온도별 전압강하·직렬 고장 특성은 공개 도면으로 확정할 수 없다. 공급 최저 23.28V와 밸브
최저 22.8V 사이 손실 예산 0.48V에는 배선·홀더·접점·DFR·뜨거운 상태·기동 손실을 포함해야
한다. 공급 공차의 측정점은 플러그 단자이므로 공급기 출고 케이블 손실을 중복 차감하지 않는다.

[정확 `01550100Z` 홀더 문서](https://www.littelfuse.com/assetdocs/littelfuse-fuse-holder-155-100-datasheetpdf?assetguid=feb34c70-4b5c-48a2-88f9-895c15c5efcc)의
SKU 각주는 8인치 AWG14 적색 비닐 선 루프·스프링 2개·퓨즈 미포함을 명시한다. 일반 제품
설명의 19인치나 별도 구매 AWG16 전선 사양을 이 SKU와 서로 옮겨 적용하지 않는다.

이번 검토로 정상 정격과 선정 출처는 보완했지만 **퓨즈–히컵–직렬 DFR의 고장 보호협조와
실제 전압강하는 미입증**이다. 기존 ELEC-11~15에서 기동·코일 전압·역기전력·고장 에너지·
외함 열조건을 확인해야 한다. 히컵 중 J104→P24_OK→HEALTH/FAULT→ARM 차단과 자동
복귀 뒤 무승인 재기동 금지도 확인한다. J104의 전원 존재 감지를 22.8V 저전압 차단으로
간주하지 않는다. 원본 BOM·회로·구매 셀과 출력 잠금은 변경하지 않았다.

### KiCad 직접 재검사 (2026-10-05)

사용자 요청에 따라 **동봉 보고서 열람을 넘어 실제 KiCad 9.0.9로 ERC·DRC를 재실행했다.** 원본과 같은 버전의 [공식 KiCad Linux Lite 도구](https://www.kicad.org/download/linux/)를 공식 MIT 미러에서 임시 다운로드하여 기존 Ubuntu 24.04 WSL에서 실행했다. 다운로드한 AppImage SHA-256은 `212181f4a3c105f200c363992ff6437666869a0169a97e9129110d20a0d8312a`이다. Windows·Pi·GPU에 KiCad를 영구 설치하거나 회로 출력을 활성화하지 않았다.

최종 검사를 시작한 시각은 2026-10-05 03:05:54 KST(2026-10-04T18:05:54 UTC)다. ZIP의 native whitelist 31개 파일만 임시 추출해 파일별 크기·해시를 대조하고 로컬 심볼·풋프린트 테이블과 프로젝트 규칙을 함께 사용했다.

| 실제 실행한 검사 | 새 보고서 결과 | 종료코드 |
|---|---|---:|
| 전체 계층 회로도 ERC | 9장 모두 검사, 위반 0 | 0 |
| 원본 PCB DRC | 위반 0, 미연결 0, 회로도 불일치 0 | 0 |
| 구리면 재계산 후 DRC | KiCad `pcbnew.ZONE_FILLER`로 별도 임시 사본의 구리면 6개 재계산 성공. 위반·미연결·회로도 불일치 모두 0 | 0 |

DRC 규칙 57개 범주에 무시 설정 0개, 개별 제외 0개다. 모든 새 보고서의 `source`가 대상 파일명과 일치하며 `included_severities`에 `error`, `warning`, `exclusion`이 포함됨을 확인했다. [KiCad 9 CLI 공식 설명](https://docs.kicad.org/9.0/en/cli/cli.html)에 따라 다음 명령을 실제 실행했다. 출력 경로만 검사 임시 폴더를 사용했다.

```sh
kicad-cli sch erc --format json --severity-all --severity-exclusions --exit-code-violations --output erc.json HabitatOS_SAFE_R15.kicad_sch
kicad-cli pcb drc --format json --severity-all --severity-exclusions --exit-code-violations --all-track-errors --schematic-parity --output drc.json HabitatOS_SAFE_R15.kicad_pcb
```

KiCad 9.0.9 CLI에는 `--refill-zones` 옵션이 없으므로 같은 배포본의 Python 3.11·`pcbnew` 엔진으로 별도 사본의 6개 zone을 채운 뒤 동일 DRC 명령을 추가 실행했다. 재계산 후 보드 SHA-256은 원본과 동일한 `6b31499ce6ba9b81c45ff876d4b93c01adce80ee351c0320fc4d0ede50eaced1`이다. 원본 ZIP과 추출한 native 31개 원본 파일도 검사 전후 동일했다. 새 ERC 보고서 해시는 `7a312e90d250e460afa27de095e31732951b40c723d2178b273106ace97af8e8`, DRC는 `bb5b4792f99dc3ba7aadfeb5c382d1a81d8efc7487e61a067ff835492030ccd3`, 구리면 재계산 후 DRC는 `d2a13dc8722cdd2e8518a24e313740a8e6645d3f63ba75c0604859d9d2b316b4`다.

반복 검사는 [check_safe_r15.py](../../tests/hardware/check_safe_r15.py)에 통합했다. 설치된 같은 버전의 `kicad-cli`와 원본 ZIP을 인자로 사용하며, `--pcb-python`을 주면 구리면 재계산 검사도 수행한다. 검사는 임시 디렉터리를 자동 정리하고, 요약 출력이 원본 ZIP과 같은 파일이면 실행 전에 거부한다. 동일 경로 및 하드링크 출력 거부를 실제 시험하여 원본 보존을 확인했다. 구매목록 `(1).xlsx`의 PCB 검증 근거도 직접 재검사 결과로 갱신했다. 임시 KiCad 도구는 Linux에서 삭제했고, Windows의 다운로드·압축 해제본·새 보고서·일회성 실행 파일도 정리했다. 이 기록과 반복 검사 코드만 남긴다.

**결론: 제공된 R15 회로·PCB는 KiCad 9.0.9의 실제 ERC·DRC 및 구리면 재계산 후 DRC를 통과했다.** 업체 DFM·견적, Pi 제어 계약, 실제 납땜·통전·보호회로·펌프 시험은 이 CAD 검사로 확인되지 않는다. 실물 시험 0회와 발주 보류 상태를 유지한다.

### R15 회로도 재작성 및 최종 검사 (2026-10-05)

**R15-DOC1 도면 작업 완료.** [TI SLVUCT6](https://www.ti.com/lit/pdf/slvuct6)의 4쪽 회로 표현과 기능 구분을 참고하여 기존 부품 격자 도면을 전체 흐름 1쪽과 기능별 14쪽의 A3 도면으로 재작성했다. 저항·커패시터·다이오드·NPN/PNP·슈미트·논리 게이트·플립플롭을 해당 기능의 기호로 표현하고, IC의 여러 게이트와 전원 유닛을 분리했다. 각 부품의 물리 핀 번호·핀 이름·전기 유형 및 연결은 원본과 대조했다.

- 최종 도면: [r15-schematic.pdf](r15-schematic.pdf), **15쪽**. KiCad에서 직접 출력한 벡터 PDF이며 목차의 시트 링크 28개와 부품·시트 책갈피 272개를 포함한다.
- 편집 프로젝트: [HabitatOS_SAFE_R15.kicad_pro](kicad-r15/HabitatOS_SAFE_R15.kicad_pro). 같은 폴더에 회로도·PCB·규칙·로컬 심볼/풋프린트 라이브러리를 함께 둔다. KiCad 9.0.9에서 검증했다.
- 기존 [PCB 앞면](r15-pcb-top.png)과 [뒷면](r15-pcb-bottom-mirrored.png), 원본 ZIP과 제조파일은 보존했다. 새로운 제조 ZIP을 만들거나 업체에 제출하지 않았다.

| 쪽 | 기능 |
|---:|---|
| 1 | 전체 기능 흐름과 연결 가능한 목차 |
| 2 | 5V/3.3V 전원 감시와 리셋 |
| 3 | 수위·누수 접점 및 외부 종단저항 |
| 4 | 하트비트 watchdog과 절연 24V 감시 |
| 5 | 분무 제한창과 수동 버튼 |
| 6 | 오류 극성 및 정상 조건 |
| 7 | 펌프·밸브 허가와 one-hot 논리 |
| 8 | ARM·수동 토큰·timeout 기억 |
| 9 | ARM의 양쪽 에지 처리 |
| 10–12 | 외부 CUT/RUN 및 밸브 1/2/3 드라이버 신호 |
| 13–14 | ESP 입력 정형·커넥터·open-drain 상태 출력 |
| 15 | 외부 Pico H, 물리 소켓과 리셋 |

최초 DOC1 파일을 고정한 뒤 **2026-10-05 14:49:27 KST**에 KiCad 검사를 시작했다. 아래 표와 해시는 이 시점의 과거 검증 기록이다. 이후 출처 정정본의 현재 해시는 다음 절에 별도로 기록한다. 독립 검사기는 원본 정본 JSON·원본 native XML·후보에서 새로 추출한 XML을 비교하며, KiCad의 실제 ERC·DRC와 구리면 재계산을 실행했다.

| 최종 검사 | 결과 |
|---|---|
| 부품·연결·핀 유형·메타데이터 | **198부품·695핀·명시적 NC 47개**, 불일치 0 |
| 부품값·MPN·풋프린트·실장 범위 | 원본과 일치; 외부 부품 5개와 USB 접지 선언 유지 |
| PCB 비교 | 형상·패드·배선·구리 영역·규칙 변경 0 |
| 실장 범위 | 기능 부품 193개 = 업체 PCBA 191개 + 고객 소켓 2개; 장착 홀 4개 포함 총 풋프린트 197개 |
| ERC | 전체 15시트 위반 **0**, 종료코드 0 |
| DRC | 위반·미연결·회로도 대응 오류 **모두 0**, 종료코드 0 |
| 구리 영역 재계산 후 DRC | 영역 6개 재계산 성공, 위반·미연결·대응 오류 **모두 0**, 종료코드 0 |
| 규칙·파일 보존 | DRC 57범주, 무시·개별 제외 0. 원본 ZIP·원본 native·고정한 후보 및 검사 사본 해시 유지 |
| 검사기 자체 검증 | 정상/변조 입력 19개 통과. 핀·메타데이터 변경 및 NC에 구리/패드 추가 등을 거절 |
| 최종 PDF 시각 검토 | Poppler로 15쪽 전체 렌더, 독립 육안 검토 및 의심 부위 200dpi 확대 검토 통과 |

PCB에서 바뀐 항목은 새 계층의 **회로도 UUID 경로 193개와 미사용 핀 자동 이름 8개**다. 게이트 분리로 `U120`의 8번 미사용 핀 표시가 `U120C`가 되는 등의 자동 이름 변경이며, 실제 접속·NC 상태·숫자 net ID는 유지된다. 해당 핀은 `U120.8/.11`, `U121.8`, `U122.6/.8/.9`, `U128.6/.8`이다. 검사기는 원본·후보 XML의 명시적 NC, 단독 패드 1개, 구리·추가 패드 연결 없음 및 정확한 새 이름을 입증한 경우만 허용한다. 다른 PCB 변경은 거절하며 DRC의 회로도 대응 검사를 생략하지 않는다.

시각 검토에서 커넥터 라벨 잘림·제목란 침범·핀 이름/MPN과 배선 겹침·NPN 화살표 방향을 발견하여 수정하고 다시 렌더링했다. 최종 PDF는 2026-10-05 14:48:53 KST 출력본이다. 실제 종이 인쇄와 부품 통전 시험은 포함하지 않는다.

내보내기 메시지: native XML 추출은 종료코드 0이고 위 연결 검사를 통과했지만, 원본에서도 표시되던 `schematic has annotation errors` 경고가 남아 있다. 원본 참조명은 유지했으며 이 경고의 원인 자체는 해소하지 않았다. 따라서 ERC·DRC 위반 0과 모든 도구 메시지 0을 동일하게 취급하지 않는다.

| 보존한 검증 증거 | SHA-256 |
|---|---|
| 최종 PDF | `91742522489167abf7c9f5984aebaea58fdcc4cff43dd5d9f601e489e8df5c23` |
| 최종 root 회로도 | `0473a5c0c2b8b7923d5967f77537a4793dc3cac16e9401bdc5526767dcc3a459` |
| 최종 PCB | `59ab9f8de95f02897f2b41038d95ae9fb5c783a5f6d994787fd2589f95108730` |
| 최종 37파일 해시 목록의 집계 | `41fce95df160d84940ad4ea7ee8cc6f828eb8d229b41f526aa4e1eaa2e1acd54` |
| 재작성 생성기 | `401a4159939636b271fbcad5ba815b5956719062eccf4456977cf06b8bcf9765` |
| 검사기 | `4d90f31ac54f62189efdc0b24b9b152037193280dcc1e024f9af113d072d6c2f` |
| 최종 실행 요약 | `63cde820fa22e44ae8313d2b07287b40923a9dee29b4ca8725edb8c224a2822d` |
| 새 ERC 보고서 | `a0f3585e10d4a935e9036d33f2484d56f4204365d5e24a2d22672ab271a0425c` |
| 새 DRC 보고서 | `addfa82be8a50550299d0ccc81e1991b8986fd127e10ec9e71cfa84629adf35a` |
| 재계산 후 DRC 보고서 | `def7332d9375c2c0ad0d1c8f5f43167e5e7cfa9a135fa675593f77ab542fd128` |

파일 집계 해시는 native 37파일의 상대 경로→개별 SHA-256 사전을 키 순으로 정렬하고, 공백 없이 `,`/`:` 구분자를 사용하는 UTF-8 JSON으로 직렬화한 결과의 SHA-256이다.

재현 도구는 [redraw_safe_r15.py](../../scripts/redraw_safe_r15.py), 반복 검사는 기존 [check_safe_r15.py](../../tests/hardware/check_safe_r15.py)에 통합했다. 원본 ZIP과 위 프로젝트를 지정해 같은 버전의 KiCad로 검사한다. `--pcb-python`에는 같은 KiCad `pcbnew`를 가져올 수 있는 Python을 사용한다.

```text
python -B tests/hardware/check_safe_r15.py "원본 R15 ZIP 경로" --project docs/hardware-design/kicad-r15 --cli kicad-cli --pcb-python python
python -B tests/hardware/check_safe_r15.py --self-test
```

최종 PDF와 37개 native 파일 약 3.02MB를 `Desktop/HabitatOS`에 모았다. 반복 출력·그림·보고서는 이 기록에 결과와 해시를 남기고 임시 도구와 함께 정리했다. 원본 ZIP의 제조자료와 기존 구매목록은 이 도면 재작성 작업에서 변경하지 않았다.

**완료 범위는 회로도 표현 개선과 CAD 동일성·설계 규칙 검증이다.** 물리시험 0회, 업체 DFM·조달 견적·실제 보호 타이밍·납땜·통전·펌프·밸브 시험은 미실시이며, 앞 절의 제조 견적 검토 가능·발주 보류 상태를 유지한다.

### Datasheet 출처 정정본 실제 재검증 (2026-10-05)

현재 [native 프로젝트](kicad-r15/HabitatOS_SAFE_R15.kicad_pro)와 [15쪽 PDF](r15-schematic.pdf)는 제조사 출처 정정이 반영된 파일이다. 기존 37개 native 파일의 재생성 전후를 바이트 비교하여 **13개 하위 회로도의 `Datasheet` 149개 속성 외 변경 0**을 확인했다. root 회로도·기호 라이브러리·PCB·제조 연결·규칙은 직전 DOC1과 동일하다. 원본 ZIP은 그대로 보존했다.

실제 KiCad 9.0.9 검사를 **2026-10-05 17:26:54 KST**에 시작했다. 원본 정본 JSON·기존 XML·새 XML 비교에서 **198부품·695핀·명시적 NC 47개**, 핀·전기 유형·허용하지 않은 메타데이터 불일치 모두 0이다. 출처 정정 149개/22MPN은 별도로 집계하여 native 속성과 새 XML이 같은 정정을 포함함을 확인했다. PCB는 기능 부품 193개(업체 PCBA 191개+고객 소켓 2개), 장착 홀 4개, 총 197개 풋프린트와 기존 형상·연결을 유지한다.

| 실제 재검사 | 결과 |
|---|---|
| 전체 계층 ERC | 15장 위반 0, 종료코드 0 |
| PCB DRC·회로도 대응 | 위반·미연결·대응 오류 모두 0, 종료코드 0 |
| 구리 영역 재계산 후 DRC | 같은 KiCad의 `pcbnew`로 임시 사본의 6개 영역 재계산, 세 항목 모두 0, 종료코드 0 |
| 검사 조건 | error·warning·exclusion 포함, DRC 57범주, 무시·개별 제외 0; 원본 31파일·후보 37파일·원본 ZIP 검사 전후 보존 |
| 검사기 자체 검증 | 정상 및 변조 입력 25개 통과. 임의 URL·다른 MPN의 승인 URL·native/XML 정정 불일치 등을 거절 |
| PDF | 17:29:35 KST KiCad 직접 출력, 15쪽·1,774,575바이트. 149개 부품의 PDF 속성 팝업 링크가 새 native 출처와 일치 |
| 시각 검토 | Poppler 24.02.0으로 15쪽 전체 렌더 후 육안 검토. 기존 PDF와 같은 96dpi 조건의 페이지별 픽셀 해시가 15쪽 모두 같음; 도형·문자·배치 변화 없음 |

재계산 사본의 해시 `f62d043a660bd371e24c63e1143182daa924fc498f1eb7ff57e36fe7a7d183c5`와 기존 PCB의 차이는 Windows CRLF에서 Linux LF로 저장된 줄바꿈뿐이다. 줄바꿈을 정규화한 전체 텍스트가 동일함을 추가 확인했으며 실제 프로젝트 보드는 덮어쓰지 않았다. PDF 책갈피 272개도 유지했다. 회로도 표현과 검증 범위는 그대로이며 실물·토출·보호 타이밍 시험을 수행했다는 의미는 아니다.

| 현재 출처 정정본 검증 증거 | SHA-256 |
|---|---|
| PDF | `f8ee9f9fb8bbd516fecc77ae94bb03d394969de9a82e30ea172a376477c316f6` |
| root 회로도 (직전과 동일) | `0473a5c0c2b8b7923d5967f77537a4793dc3cac16e9401bdc5526767dcc3a459` |
| PCB (직전과 동일) | `59ab9f8de95f02897f2b41038d95ae9fb5c783a5f6d994787fd2589f95108730` |
| native 37파일 해시 목록의 집계 | `545a963d4b630d6957a164ac1479c2f2a59e3a2f39e43e97d224f40c5af0110a` |
| 재작성 생성기 | `b517353cee05fa3ed7d617e2c1a70b9a824ff735a629ed31e4f973c971654c81` |
| 검사기 | `df178699953531338d30a97a710253d17711dc05692f43c6dc62ce7d5686db25` |
| 실행 요약 | `410484fffaebc47685375f56cab676d742e0d85ff7f55712e6a9e5054ade5c55` |
| ERC 보고서 | `29be036b514871984b1a5005231a7edc0134b293944464a2eb5425f52c9386b0` |
| DRC 보고서 | `c0e1c8c547ace954a14643bf13be559c85940684501612fa322b98b24d364967` |
| 재계산 후 DRC 보고서 | `c4fc3084e770f506afc79bc179348701b61e9af1f6c05084797b2a8ac14bf4e9` |

검증에 사용한 KiCad Lite·Poppler 및 렌더·검사 임시파일은 결과 기록 후 정리했다. Poppler는 Ubuntu 패키지를 임시 경로에 추출했으며 시스템 apt 패키지를 설치하지 않았다. 이 CAD 출처 정정·재검사 과정에서는 원본 ZIP·HWP·XLSX·제조 보드를 변경하지 않았고 새 제조 ZIP을 만들지 않았다. 앞서 승인받아 수행한 XLSX 정리 이력과 구분한다.

## 2. 확보 범위와 실물 확인 구분

아래 수량은 최초 HWP를 반영한 정본 목록과 사용자의 확보 확인을 기준으로 한다. 개별 납품품 검수는 남아 있다.

| 최초 HWP 품목 | 수량 | 이번 단계의 용도·확인 사항 |
|---|---:|---|
| SMG-A USB-OV5628-A / OV5693 USB RGB 카메라 | 3 | 판매 UVC·MJPEG/YUY2 모드표 확인; 실물 라벨·커넥터·USB 열거/실제 영상 모드는 연결 후 확인 |
| ipTIME UH505 | 1 | 데이터 포트와 충전 전용 포트 구별, 동봉 전원·케이블 확인 |
| ESP32-DEVKITC-32E | 3 | WROOM-32E·DevKitC V4·핀 표기·헤더 방향 확인 |
| DFRobot SEN0331 | 3 | 센서면·ADDR 패드·6핀 헤더 납땜 방향 확인 |
| Adafruit 381 DS18B20 프로브 | 6 | 제품 식별, 3선/4선 및 실제 색상, 동봉 저항 확인 |
| SMG-A PCB-0709D | 3 | 구멍 수·피치·동박 연결 구조 실측; 정본 좌표는 조건부 |
| Raspberry Pi Pico H | 1 | 재고 확인·보관. 이번 센서 배선에 연결하지 않음 |
| 케이블타이 | 1 구매단위 | 확보된 규격과 고정 경로 확인 |
| CH254 F/F 10cm 40P 점퍼 | 1 구매단위 | 실제 소켓·사용 가능한 선 길이 확인 |
| PROKIT MT-1233C | 1 | 계측기 상태와 리드 연결을 제조사 사용법에 따라 확인 |
| SCS7 스프링 무연납 | 1 구매단위 | 확보 규격 확인 |
| 전기용 절연테이프 | 1 구매단위 | 배선 절연 보조 |

ESP32 USB 데이터 케이블·적합한 전원·인두·탈피 도구 등은 원 HWP 12개 품목과 별도로 사용 가능 여부를 확인해야 한다. 구체적인 보유 모델과 수량을 추정하지 않는다. Pi Zero 2 W, ESP32-S3/P4 영상 보드, 열화상 모듈, 추가 공유기 및 펌프·밸브·보호 PCB의 추가 구매·설치는 보류한다.

## 3. 제조사 자료와 핀 대조 결과

| 대상 | 문서상 확인 결과 | 정본 위치 |
|---|---|---|
| ESP 전원 | `J2.1=3V3`, `J2.14=GND` | CSV A 노드 E1/E2, JSON `wires` |
| 프로브 1 데이터 | `GPIO13=J2.15` → `DQ13` | CSV E3/T1D |
| 프로브 2 데이터 | `GPIO14=J2.12` → `DQ14` | CSV E4/T2D |
| I²C SDA | `GPIO21=J3.6` → SEN0331 `P1.4 SDA` | CSV E5/H4 |
| I²C SCL | `GPIO22=J3.3` → SEN0331 `P1.3 SCL` | CSV E6/H3 |
| SEN0331 전원 | `P1.1 VCC` → 3V3, `P1.2 GND` → GND | CSV H1/H2 |
| DS18B20 풀업 | 각 독립 DQ와 3V3 사이에 4.7kΩ 하나씩 | CSV R1/R2, JSON `resistors` |

[Espressif 공식 DevKitC V4 핀 표](https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32/esp32-devkitc/user_guide.html)의 J2/J3 번호와 모두 일치한다. `GPIO13`을 커넥터의 13번째 핀으로 해석하지 않는다. 제조사 보드 사진도 확인했다. 모듈면을 보고 안테나가 위, MicroUSB가 아래이면 J2는 왼쪽, J3는 오른쪽이다. 같은 위·아래를 유지하며 뒷면으로 뒤집으면 좌우가 반전된다.

[DFRobot 공식 SEN0331 앞·뒷면](https://wiki.dfrobot.com/sen0331/)과 [V1.0 회로도](https://dfimg.dfrobot.com/wiki/21163/SEN0331_sht31-digital-temperature-humidity-sensor_schematics_V1.0.pdf)를 시각 확인했다. 센서면을 보고 헤더 구멍을 아래에 두면 왼쪽부터 `VCC-GND-SCL-SDA-INT-RST`이다. 뒷면에서는 반대 순서다. 회로도의 SDA/SCL에는 VDD 방향 10kΩ 풀업이 있으므로 DS18B20용 4.7kΩ을 I²C에 추가하는 것으로 해석하지 않는다. INT/RST는 정본대로 외부선을 연결하지 않는다.

SEN0331의 주소는 ADDR 상태에 따라 `0x44/0x45`이다. [제조사 주소 설명](https://wiki.dfrobot.com/sen0331/docs/21257)에 따라 실제 검색된 주소를 기록한다. [센서 펌웨어](../../firmware/cage_node/cage_node.ino)는 `Wire.begin(21, 22)`와 두 주소 탐색을 사용한다. 프로브 호스트 검사와 이후 통과한 ESP32 센서형·중앙형 대상 빌드는 아래 9절에 기록했다. 실물 업로드·실제 주소 검색은 미실시다.

[Adafruit 381 공식 배선 안내](https://www.adafruit.com/product/381)와 JSON의 색상 규칙이 일치한다. 3선형은 빨강 VDD, 파랑/검정 GND, 노랑/흰색 DATA이고, 4선형은 빨강 VDD, 검정 GND, 흰색 DATA, 맨구리선은 실드다. 실드는 정본에서 개별 절연하도록 정한 설계 선택이며 EMC 검증 결과가 아니다. 다른 색상·다른 제품이면 이 표를 적용하지 않는다. 밀봉 프로브를 벌거벗은 TO-92 소자의 다리 번호로 설명하지 않는다.

## 4. 전원·만능기판 좌표의 제한

ESP32는 MicroUSB 한 경로로 전원을 공급한다. 제조사는 MicroUSB, 5V/GND, 3V3/GND 급전을 상호 배타적인 방법으로 설명한다. USB 급전 상태에서 외부 전원을 5V/3V3 핀에 추가하지 않는다. 센서는 ESP32의 3V3와 해당 노드의 GND를 사용한다. 독립 무선 노드와 Pi 사이에 GPIO선이나 별도 공통접지선을 추가하지 않는다.

JSON의 `B2`, `K12` 등은 **프로젝트가 정한 만능기판 구멍 좌표**다. 제조사가 인쇄한 고유 단자 번호가 아니다. `board_A1`은 26×31 독립 구멍, 2.54mm 피치, 70×90 방향을 실물에서 확인한다는 조건으로 왼쪽·위에서 8번째·10번째 구멍을 A1으로 정했다. 실제 구멍 배열이나 공통 동박이 다르면 이 좌표도를 적용할 수 없다. 무전원 도통 검사와 실측 후 원점을 실물에 표시해야 한다.

긴 핀이 ESP의 뒷면, SEN0331의 앞면으로 나온다는 JSON의 삽입 방향은 조건부다. 납품 헤더가 다르면 좌우·접속면을 다시 대조해야 한다. 점퍼 길이는 소켓에서 나온 선부터 실제 절단 끝까지 측정하고, 실물 경로와 납땜 여유를 같은 기준으로 비교한다. 제품명상의 10cm만으로 도달 가능 여부를 확정하지 않는다.

## 5. 검토에서 발견한 불일치와 처리 상태

| 항목 | 발견 내용 | 처리·현재 상태 |
|---|---|---|
| CSV B/C 프로브 라벨 | B/C 노드에도 `DS-A1/DS-A2`가 복사되어 있었음 | **수정 완료:** B는 `DS-B1/B2`, C는 `DS-C1/C2`. 핀·구멍·네트는 유지 |
| R8 구매 범위 | 사용자 `HabitatOS_A_R8_전체자료.zip` 안 `HabitatOS_R8/HabitatOS_A_R8_레고식_연결조립_안내서.pdf` 1·4쪽은 14/16품목 기준 | 최초 HWP 12품목의 확보 범위와 혼합하지 않음. 원본 ZIP/PDF 보존 |
| R8 RGB 모델 | 같은 PDF 2·30쪽의 Waveshare OV5693(A), SKU24710은 원 HWP SMG-A USB-OV5628-A와 다름 | 현재 manifest는 SMG-A로 구분됨. R8의 광학·전류·FPS 수치를 구매품에 전용하지 않음 |
| 실물 헤더·기판·색상 | 정본은 실물 미검증 조건을 포함함 | **미확인 유지:** 사진·실측·무전원 검사 필요 |
| 전원·USB 부속 | HWP 확보 확인만으로 해당 부속의 규격·상태가 증명되지 않음 | **미확인 유지:** 실제 라벨·커넥터·공급 경로 확인 |
| 프로브 변환 실패 처리 | 변환 시작에 실패해도 기존 scratchpad를 읽을 수 있던 경로 | 시작·완료 응답 확인과 1회성 결과 처리 추가. 호스트 12개 시나리오 통과; 실물 미시험 |
| 펌웨어·운영 연결 | 호스트 검사와 실물 센서·GPIO 동작을 구분해야 함 | 센서형·N1형 ESP32 대상 빌드 및 실제 Mosquitto/Paho 왕복 통과. 실제 ESP/Pico 업로드·센서 수집·GPIO·무선 끊김 복구는 미시험 |

R8 페이지 근거는 같은 날짜의 독립 PDF 검토에서 확인했다. 원 HWP 모델은 [SMG-A 판매 사양](https://www.devicemart.co.kr/goods/view?no=15668138)의 OV5693·5MP·자동초점·120°·USB2.0이다. [Waveshare SKU24710 제조사 사양](https://www.waveshare.com/product/modules/ov5693-5mp-usb-camera-a.htm)은 별도 제품의 정보다.

## 6. 수정 후 문서 데이터 검사

CSV를 읽고 정본 JSON에서 각 노드의 예상 행을 독립적으로 구성하여 비교했다. 다음 항목이 통과했다.

- CSV 총 72행, A/B/C 각각 24행과 단계 순서가 일치한다.
- 버스·저항·외부선의 ID, 출발점, 도착점, 네트를 모두 비교했다. 프로브 이름만 해당 노드 문자로 치환한다.
- B/C에 A 프로브 라벨을 재사용하지 않는다.
- 모든 외부선의 기판 구멍이 의도한 버스에 속하고, 서로 다른 버스의 구멍 중복이 없다.
- 두 저항의 양 끝이 각각 3V3-DQ13, 3V3-DQ14에 해당한다.

이 검사는 JSON과 CSV의 일관성 검사다. 제조사 핀맵 대조와 별도로 수행했지만, 납땜 상태·물리적 단락·접촉 불량을 측정하지는 않는다. 독립 대조는 메모리에서 실행했다. 동일 데이터의 지속 검사는 [안내 생성기](../../scripts/build_assembly_guide.py)의 `--check`로 다시 실행할 수 있다. 별도 테스트 산출물이나 ZIP을 보관하지 않는다.

## 7. 조립도를 확정하는 데 필요한 실물 사진

| 대상 | 확인할 모습 |
|---|---|
| ESP32 | 앞·뒷면 전체, WROOM 모델 표기, USB 위치, 핀 인쇄, 긴 핀이 나온 면이 보이는 옆면 |
| SEN0331 | 센서면·뒷면 ADDR 패드, 실크 인쇄, 별도/납땜된 헤더와 긴 핀 방향 |
| DS18B20 | 포장 모델과 모든 리드 색상, 3선/4선 구별, 실드, 동봉 저항의 색띠/표기 |
| 만능기판 | 앞·뒷면 전체, 자와 함께 찍은 구멍 배열·피치·외곽, 공통 동박 유무 |
| 점퍼 | 양쪽 커넥터, 자와 함께 찍은 사용 가능 길이, 가공 전 상태 |
| 카메라·허브 | 모델 라벨, 카메라 커넥터, 허브 데이터/충전/업스트림 포트와 전원 라벨 |
| 전원·케이블 | 각 공급기의 출력·모델 라벨, 사용 USB 케이블 양 끝, 실제 급전 경로 |

사진으로 보이지 않는 내부 연결·저항값·전압은 계측으로 확인한다. 사진만으로 전기 시험을 통과 처리하지 않는다.

## 8. 단계별 합격 기준과 현재 결과

수치 판정은 실제 부품의 제조사 규격·부품 공차·측정기 사양에 근거한다. 근거 없이 저항 허용범위, 전압 오차, 대기 시간, FPS 또는 센서 정확도를 정하지 않는다.

| 단계 | 합격 기준 | 현재 결과 |
|---|---|---|
| 부품 식별 | 실물 모델·커넥터·헤더가 정본과 일치하거나 차이가 기록되고 배선도에 반영됨 | 사용자 확보 확인만 있음; 납품 검수 미실시 |
| 원점·경로 확인 | 기판 격자와 동박 구조를 확인하고 A1 표시; 선이 실제 경로와 납땜 지점에 무리 없이 도달 | 미실시 |
| 무전원 배선 검사 | 의도한 네트만 도통; 다른 네트 사이 의도하지 않은 연결 없음; 프로브 DQ가 서로 분리됨; 풀업값이 확인된 부품 규격과 일치 | 미실시 |
| 단독 전원 검사 | 급전 경로·극성 확인; 연결 대상 제조사 허용범위를 벗어나는 전압이 없고 단락·손상 징후 없음 | 미실시 |
| 센서 읽기 | 실제 SHT 주소 확인; 프로브 식별값과 위치 대응 기록; 읽기 오류를 유효값으로 처리하지 않고 측정값·시각을 확인 | 미실시 |
| Pi 수집 | 각 ESP32의 노드·사육장 ID가 실제 장치와 일치하고 해당 센서값이 Pi에 수집됨; 인증 실패를 우회하지 않음 | 실물 센서 연동 미실시 |
| 분리·재연결 | 전원을 제거한 상태에서 센서를 분리해 시험 구성; 이후 누락/오류가 유효 측정으로 표시되지 않고 정상 연결 복구가 확인됨 | 미실시 |
| 카메라 수집 | 실제 USB 지원 모드·안정 경로·사육장 대응을 기록하고 영상 취득 확인; 연결 수를 늘린 뒤 프레임·지연·전원 상태 측정 | 미실시 |
| 전체 조립 승인 | 앞 단계의 실측 결과·검토자·시험 조건을 기록하고 발견된 문제를 해결 | **미완료** |

실제 펌프·밸브·보호회로와 자동 분무는 이 표의 합격 범위에 포함하지 않는다. 모의실험 또는 합성 데이터 모델의 결과로 물리 시험을 대신하거나 분무 출력을 활성화하지 않는다.

## 9. 이번에 구현하고 확인한 내용

### 프로브 펌웨어

[DS18B20 데이터시트](https://www.analog.com/media/en/technical-documentation/data-sheets/DS18B20.pdf)의 외부 급전·변환 완료 확인 절차를 반영했다.

- GPIO별 한 개의 DS18B20만 허용하고 ROM 계열·CRC를 확인한다.
- Read Power Supply 명령으로 외부 VDD 급전을 확인한다. 이 배선의 3선 급전 조건에 맞지 않으면 유효값을 만들지 않는다.
- Convert T 직후 busy 응답과 읽기 시점의 완료 응답을 확인한다. 시작 실패, 아직 변환 중, 리셋 실패, scratchpad CRC 오류는 NAN → invalid/null 경로로 처리한다.
- 결과를 읽은 뒤 시작 상태를 소비하여 같은 변환 결과를 재사용하지 않는다. MQTT 연결 시도가 지연되어도 800ms 대기는 실제 변환 시작 이후를 기준으로 한다.
- 시리얼 115200에서 `probe channel=T2 gpio=13 rom=... event=found` 형태로 처음 발견한 ROM을 알린다. 같은 실행 중 ROM이 바뀌면 `event=changed`를 기록한다. GPIO14는 T3이다.

[check_cage_node.py](../../tests/hardware/check_cage_node.py)는 실제 .ino에서 프로브 함수를 가져와 기존 C++ 컴파일러와 OneWire/Serial 모의 객체로 검사한다. **12개 시나리오 통과**를 재실행해 확인했다. 정상 변환, 중복 읽기, 연결 없음, 리셋 실패, 기생 급전, busy 응답 없음, 미완료, CRC 오류, 범위 검사, ROM 변경·불량·다중 장치 거부를 포함한다. 컴파일 임시 파일은 종료 시 제거한다.

위 12개 검사는 프로브 함수의 소프트웨어 분기 검증이다. 이후 2026-10-05 센서형·중앙형의 ESP32 라이브러리 대상 빌드와 실제 MQTT 루프백 검사를 추가로 통과했다. 전기 신호 타이밍, 전원 순간 끊김, 실제 센서 정확도 및 실물 ESP 무선 수집은 검증하지 않았다. ROM은 재부팅 후 보존·고정되지 않는다. `geometry_revision`과 `placement_revision`도 현재 1로 고정되어 있어 실제 센서 이동·교체를 자동 추적하지 않는다.

### 조립 안내

- [HTML](assembly-guide.html)과 [Markdown](assembly-guide.md)을 같은 정본에서 생성했다. 43단계 안에 배선 24개와 중간 전원·센서 확인 단계를 포함한다. A/B/C 전체는 72개 연결이다.
- 한 단계에서 새로 연결할 선을 강조한다. 이전 선은 회색으로 구분하며, 만능기판 앞면/납땜면 전환·확대·노드 선택·인쇄를 제공한다. 기판 전환은 기판만 좌우 반전하며 ESP와 센서는 표기된 앞면을 유지한다.
- 그림은 전기적 연결과 조건부 작업 좌표다. 실물 비례·소켓 삽입면·가공 길이·완성품 장착 형상을 보장하지 않는다. 선의 교차는 접속이 아니며 접속점과 양 끝의 핀 이름을 확인한다.
- ESP 왼쪽 헤더선은 ESP 아래로, 센서선은 각 단자 아래로 분리해 그려 다른 장치 단자를 관통해 보이는 경로를 제거했다.
- 로컬 Chrome에서 **43단계 × 3노드 × 2기판면 = 258개 상태**의 연결 표시·24행 표를 확인했다. 자바스크립트 오류 0건. 해시 링크 이동과 확대 화면을 확인했다.
- 화면 폭 390px에서 가로 넘침이 없고 이전/다음 버튼이 줄바꿈되지 않는 것을 확인했다. 인쇄 CSS에서 43개 페이지를 검사했으며 186×273mm에 대응하는 703×1032px 영역을 넘는 페이지가 없었다(최대 내용 높이 929px). 실제 프린터 출력 검증은 아니다.
- HTML은 외부 CDN·장치 API 없이 파일을 직접 열어 사용한다. 단계 이동을 실물 검사 합격으로 저장하지 않는다. 별도 압축 파일이나 그림 파일 묶음을 생성하지 않았다.

프로젝트 루트에서 재검사: `python scripts/build_assembly_guide.py --check` 및 `python tests/hardware/check_cage_node.py`(기존 g++ 또는 clang++ 필요).

### 2026-10-05 소프트웨어·실제 Pi↔GPU 재검증

소프트웨어 구현과 시험 결과는 다음과 같다. 최초 HWP 센서 역할과 후속 펌프·밸브 역할은
가상화했으며, 이 표를 전체 구매 부품의 조립·통전·실제 분사 합격표로 사용하지 않는다.

이 절의 2026-10-05 검증 당시 Pi 릴리스는 **`0.4.12-76a2b5356b9c`**이며, `2026-10-05T13:13:25.834393+00:00`
확인에서 health `ok`·MQTT 연결 `true`·worker 오류 없음이었다. 설치된 `gateway.py`와
`transport.py` 해시가 검증한 소스와 일치했고, 설정·인증정보 파일의 바이트와 대기 이벤트
1개의 sequence 1·UUID·본문 해시가 배포 전후 동일했다. `hardware_outputs_enabled=false`,
`r15_bridge.enabled=false`를 유지하고, 3개 사육장의 실제 분무 상태는 `null`이다.
하트비트 ACK는 `2026-10-05T13:13:24.986376+00:00`였지만 이벤트 연속성은
`cloud_continuity_unverified`로 차단 중이며, SaaS 이벤트 복구 완료를 뜻하지 않는다.
[Pi 0.4.12 배포 증거](../../var/reports/commissioning/software-r15-20261005-active-reservation-deployment.json).

수정 전에는 정상 ON이 만든 자기 예약을 안전 오류로 처리해, 회귀시험의 첫 250ms tick에서
불필요한 OFF를 보냈다. 대기 hello·활성 hello 두 경우 모두 기존 코드에서 실패를 재현했다.
0.4.12는 **새 ON의 공용 자원 사용 가능 여부**와 **진행 중 요청의 안전 상태**를 분리한다.
정상 요청은 유지하면서 다른 새 ON은 busy/예약으로 거절하고, 센서 오류·상태 만료·수위 핀
저하·노드 단절 및 STOP 처리는 유지한다. 실제 임시 MQTT 시험에도 `transport.step()` 다음
`gateway.tick()`을 넣어 정상 ON 유지와 센서 오류 후 안전 OFF를 확인했다. 이는 소프트웨어
요청·패킷 검사이며 ESP/Pico GPIO나 실제 분사를 시험한 결과가 아니다. `actual_state=null`과
`execution_status=unverified`를 실제 작동 성공으로 바꾸지 않는다.
[수정 전 2개 실패](../../var/reports/commissioning/software-r15-20261005-active-reservation-baseline.log),
[수정 후 관련 검사 46개 통과·1.29초](../../var/reports/commissioning/software-r15-20261005-active-reservation-tests.log).

GPU도 0.4.12 소스 반영 후 재시작했으며 `2026-10-05T13:13:12.302080+00:00`에
서비스 active/running·PID 2854, GPU·환경·LiveScene health 3개 HTTP 200을 확인했다.
`splatfacto`·CUDA·`reconstruction_ready=true`를 유지하며 새 학습·렌더는 수행하지 않았다.
[GPU 0.4.12 확인](../../var/reports/commissioning/software-r15-20261005-active-reservation-gpu.json).

다음 0.4.10 전체 검사·GPU 최초 활성화와 0.4.11 카메라 수정은 당시 결과다. 카메라 모델명 수정은
실제 Pi 릴리스 **`0.4.11-7967566bb2ea`**에 적용했고, 확인 시각은
`2026-10-05T12:19:43.090228+00:00`이다. 관련 카메라/API 선택검사 **11개가 0.74초에
통과**했고 예제 설정 검사도 통과했다. 이를 0.4.11 전체 회귀검사 결과로 합산하지 않는다.

Pi health `ok`·MQTT 연결 `true`를 확인했고, 카메라 설정 3개 모두
`expected_model="SMG-A USB-OV5628-A (OV5693, Auto Focus/120deg)"`,
`waiting_usb_port_binding` 상태였다. 예상 모델명은 설정 메타데이터이며 USB 실물
자동 식별·실제 촬영 합격이 아니다. 하트비트 ACK는 `2026-10-05T12:19:42.760459+00:00`이며,
보존 중인 이벤트의 sequence 1·UUID·본문 해시는 그대로다. 이벤트 충돌 해결이나 SaaS 화면
반영 완료로 해석하지 않는다. [Pi 카메라 모델명 배포 확인](../../var/reports/commissioning/software-r15-20261005-camera-model.json).

| 실행 대상 | 결과 | 시험 범위 |
|---|---|---|
| Pi 최신 전체 검사 | **0.4.12: 396 passed, 7 skipped, 231 subtests passed, 108.99초** | R15 정상 요청 유지·실제 오류 차단을 포함한 소프트웨어·계약 검사. 생략을 통과로 세지 않음 |
| Pi 이전 전체 검사 | **0.4.10: 386 passed, 7 skipped, 231 subtests passed, 110.07초** | 당시 SaaS 연속성/기록 보존·공유 GPU 잠금 등의 검사 기록. 최신 검사와 합산하지 않음 |
| GPU PC의 geometry 회귀 | **13개 통과** | Pi에서 의존성 부재로 생략한 항목 포함. 기존 복원 환경에서 CPU로 실행; 실제 사육장 품질 시험 아님 |
| ESP32 타깃 빌드 | **센서형·N1 중앙형 2개 통과** | Arduino CLI 1.5.1 / ESP32 core 3.3.12 / 고정 라이브러리, 둘 다 `HABITAT_R15_REQUEST_OUTPUTS=0`; 업로드 없음 |
| 실제 MQTT 왕복 | **0.4.12 재검사 통과** | 임시 Mosquitto·Paho·Gateway·HTTP API로 정상 ON의 다음 tick 유지·센서 오류 OFF·상태·TTL·중복·retained ACK·재접속 검사. ESP/Pico는 프로토콜 fixture이며 실물 GPIO 시험 아님 |
| 실제 Pi→GPU CUDA 예측 | **180요청, 60가상분×3사육장** | 벽시계 45.71263초, 요청 왕복 중앙값 66.2567ms·최대 2306.795ms, 가상 펄스 41회·종료 시 모두 OFF |
| 공개 LiveScene 렌더 | **320×237, GPU 17.518초 / Pi 전체 왕복 24.594초** | `interreal-door-original-30000` 공개 문 장면 1회. 정적 5,000 모델·사용자 사육장 복원·실시간 FPS 아님 |
| 실제 RGB 복원 경로 시험 | **38/38장 정렬 → Splatfacto 50회 → Gaussian PLY, 120.276초** | 출처 미확인 보관 이미지로 새 COLMAP부터 실행. 16,920 Gaussian·4,197,752바이트 PLY; 품질·최적 스텝·사용자 사육장 검증 아님 |
| GPU 작업 API | **0.4.10 최초 활성화, 0.4.12 재시작 후 `backend=splatfacto`, `status=ok`, CUDA·`reconstruction_ready=true`** | 작업 수신 준비 상태. 이번 버전 갱신에서 새 학습·렌더·실제 사육장 품질 시험은 수행하지 않음 |
| SaaS 운영 경로 | **기존 sequence=1의 서버 충돌 미해결, 이벤트 1개 보존·차단** | 연속성 보호 중 하트비트 ACK 유지. 사용자에게 서버 순번·원래 DB가 없어 이벤트 복구는 미완료. 신규 R15 서버 배포·저장·화면 연결도 미확인 |

학습된 합성 MLP를 실제 GPU CUDA에서 호출했고 임계값 mock를 AI 결과로 대신하지 않았다.
다만 센서 입력·분무 후 환경 변화는 합성값이며 41회는 실제 물 분사가 아니다.
응답의 `SYNTHETIC_ONLY`, `field_validated=false`, `hardware_execution_allowed=false`와
Pi/ESP/Pico의 별도 출력 잠금을 유지한다. GPU WSL 종료로 생기던 502는 로그인 예약 작업으로
복구했고, SSH 종료 후에도 Pi에서 환경 health·장면 catalog·Pi 중계 200을 확인했다.
[GPU 로그인·가용성 조건](../operations/gpu-service.md).

[Pi 0.4.12 전체 검사 로그](../../var/reports/commissioning/software-r15-20261005-0.4.12-tests.log),
[Pi 0.4.10 당시 전체 검사 로그](../../var/reports/commissioning/software-r15-20261005-final-tests.log),
[Pi↔GPU 모의실험 결과](../../var/reports/commissioning/software-r15-20261005-simulation/result.json),
[공개 장면 렌더 결과](../../var/reports/commissioning/software-r15-20261005-render.json),
[ESP32 빌드 증거](../../var/reports/commissioning/esp32-target-build-20261005.json),
[GPU geometry/API 환경 검사 로그](../../var/reports/commissioning/software-r15-20261005-gpu-diagnostic-tests.log),
[RGB 복원 경로 시험](../../var/reports/commissioning/software-r15-20261005-reconstruction-smoke.json),
[GPU 0.4.10 활성화](../../var/reports/commissioning/software-r15-20261005-gpu-activation.json)를 보존한다.
GPU 로그의 초기 Python 3.10 API import 실패와 최종 실제 API Python 3.12 검증을 구분한다.
13개 geometry 검사는 전자 복원 환경의 CPU 회귀이며, 실제 API Python 3.12에서는
당시 0.4.8 소스와 3초 응답 한도 import 성공을 따로 확인했다. GPU 최초 활성화는
0.4.10 기록이며, 최신 서비스 상태는 위 0.4.12 재시작 확인을 따른다.

RGB 시험은 50회 제한의 실행 경로 검사이며 저장 체크포인트 이름은 `step-000000049.ckpt`였다.
120.276초는 Backend 파이프라인 시간이고 전체 검사 스크립트는 127.758초였다. 원본 38장과
manifest 해시는 보존했고 임시 모델·PLY 등 약 230MB를 삭제했다. 시험 당시 운영 설정은
`not_configured`로 유지했고, 이후 별도 활성화에서 `backend.name`만 `splatfacto`로 변경했다.
따라서 시험 JSON의 과거 설정과 현재 준비 상태를 혼동하지 않는다. worker와 LiveScene은
같은 파일 잠금을 공유하며, 대기 작업을 미리 실행 상태로 바꾸지 않는지와 성공·실패·취소 후
잠금 해제를 검사했다. 이 준비 상태는 LiveScene의 신규 RGB 학습 기능이나 50회 학습 품질을
인증하지 않는다.

[합성 모델 재평가](../../var/reports/commissioning/software-r15-20261005-model-evaluation.json)는
위 60가상분 CUDA 통신 실험과 별도인 CPU 평가다. 기존 가중치와 학습 보고서 해시가 보존됐고
새 학습은 하지 않았다. 3-sensor 구성(SHT 온·습도와 DS 온도 2개 역할)의 2,352개 합성 조건부 평가창에서 습도 MAE는
5/10/30/60분 각각 **0.2961/0.3538/0.5834/1.0235 퍼센트포인트**였다.
이 수치를 실측 센서 정확도·실제 사육장 예측 성능으로 쓰지 않는다.

가상 360분×6회 평균에서 임계값 제어→예측 제어로 바꾸면 A/B/C의 습도 범위 이탈은
각각 14→3.3333분, 62.5→13.1667분, 156.8333→82분으로 감소했다. 반면 가상 펌프 ON은
52→81.3333초, 163→202.5초, 274→331.5초로 증가했고, 가정 물 사용량도
41.6→65.0667mL, 130.4→162mL, 219.2→265.2mL로 증가했다. 온도 범위 이탈도
13.5→17분, 21.8333→25분, 35.6667→40.5분으로 늘었다. 물 사용량은 미보정 0.8mL/초의
계산값이며 실제 토출 측정이 아니다. 60분 Pi 모의실험의 `water_volume_ml`은 null이다.
습도 유지의 개선과 이 비용·온도 결과를 함께 제시하며, 전 지표 개선이나 절수를 주장하지 않는다.

정확한 구매 카메라의 판매 UVC·해상도/포맷/FPS는 위 모드표로 확인했다. OEM AF120 옵션의
전원·장치 식별·제어 문서와 실물 영상 시험, 구매 전선의 도체/절연/저항/인증 자료,
실제 센서/GPIO·보호·RUN·유량/토출·환경 반응, SaaS 충돌 해결·새 계약 배포는 별도 확인이
필요하다. 제조사 문서 공백과 실물 시험 미실시를 구분하며 임의 사양으로 채우지 않는다.

## 10. 실제 목표까지 남은 작업

1. 7절의 실물 식별·치수·헤더·전원 자료와 8절 계측 결과를 확보한다. 차이가 있으면 정본 JSON·CSV부터 수정하고 안내를 재생성한다. 그 전에는 선 절단 길이나 실물 장착 그림을 확정하지 않는다.
2. 신판 ESP32 센서형·중앙형 대상 빌드는 2026-10-07 통과했다. 한 노드의 실제 업로드·SHT31·두 프로브·Pi 수집·분리 복구를 검증한 다음 B/C로 반복한다. 실제 ESP/Pico에는 업로드하지 않았다. Pi·GPU는 12절의 0.4.14 소프트웨어 검증을 수행했으며 물리 출력은 잠겨 있다.
3. 보유 USB 카메라를 Pi5에 하나씩 연결하여 실제 지원 모드·USB 경로·3대 동시 수집 조건을 확인한다. USB 카메라를 기존 ESP32-DEVKITC-32E에 직접 연결해 무선 영상화하는 기능은 이 구성에 없다. 원격 카메라 노드는 추가 하드웨어 선정과 구현이 필요하다.
4. 현재 센서 노드는 SHT31 1개와 DS18B20 2개다. 후속 SHT31 추가와 펌프 1대·밸브 3개 실물 구동은 따로 검증한다. R15 회로·커넥터와 중앙 요청 역할·Pi 명령 변환은 문서·소프트웨어 검사를 수행했다. 11절의 REQ/RUN 차이는 12절의 순방향 요청 계획으로 반영하고 같은 소스의 Pi·GPU 0.4.14 배포·CUDA 가상 제어를 확인했다. 실제 전원·GPIO·보호·RUN/토출 시험은 남아 있다. 실측 전 배선·운전을 승인하지 않는다.
5. 실제 사육장 센서 위치를 기록하고 데이터를 수집한다. GPU의 5·10·30·60분 모델은 실측 데이터로 별도 평가하며, 합성 실험 성적을 실환경 성능으로 표시하지 않는다. 분무 반응 실측과 보호 시험이 끝나기 전 자동 분무 승인으로 이어지지 않는다.

현재 결론: **문서·소프트웨어 검사를 수행한 조립 검토본**이다. 12절의 신판 target build와 실제 Pi↔GPU schema 2 가상 제어 경로를 확인했다. 실제 센서·GPIO·분사까지의 종단 시험은 미실시다. 실물 시험 0건이며 최종 조립 승인·자동 제어 승인 상태는 아니다.

추가 기록(2026-10-04): 실제 Pi·GPU와 가상 센서·펌프로 60분 통합 모의실험을
재실행했다. GPU 응답 180회·가상 분무 31회와 별도 제어 테스트 41개가 통과했다.
[상세 실행 범위와 결과](../operations/hardware-arrival.md)를 참고한다. 이 추가 결과는
실물 배선·통전·펌프 시험 0건이라는 위 상태를 변경하지 않는다.

## 11. 원본 ESP/Pico 코드 결합 검사 — 2026-10-06

목표 완료 감사에서 패킷 fixture와 원본 Pico 프로그램의 실행 근거를 구분했다.
기존 `tests/hardware/check_cage_node.py`에 선택형 `--r15-archive` 검사를 추가했다.
원본 ZIP의 SHA-256과 `main.c`·`sequencer.c/.h`·`host_bridge.c` 해시를 먼저 확인하고,
실제 ESP `r15_bridge.h`와 원본 Pico sequencer/host interface를 기존 C/C++ 컴파일러로
결합했다. 원본·펌웨어·장치 설정은 변경하지 않는다. 기본 BENCH 출력 잠금을 검증하며,
동작 검사는 원본이 제공하는 호스트 전용 commissioning override에서만 실행한다.

기존 51개 프로토콜·2개 GPIO-task·12개 프로브 검사와 새 결합 시나리오 **16개가 통과**했다.
결합 검사의 컴파일 0.552679초·실행 0.055443초는 Windows 호스트 시간이며 실제 제어 지연이
아니다. 기본 잠금, 중복·재사용 대기, 만료 ON, 실행 중 OFF/STOP, gateway lease 만료,
단절, 누수·수위, WINDOW 미상승/중도하락, HB 고정, REQ 고정 시 native RUN 3000ms 상한을
검사했다. [실행 로그](../../var/reports/commissioning/software-r15-20261006-native-esp-pico.log).

새 검사에서 **REQ 유지 1/2/3초는 같은 길이의 RUN이 아님**을 확인했다. ON 수신 400ms,
ESP 출력 20ms 격자, Pico 1ms tick, qualify 20ms, PREOPEN 1000ms, TRIG 후 1ms에
WINDOW HIGH라는 가상 조건에서 RUN은 각각 **0/959/1959ms**였다. 이는 실물 범위나
분무량 보장이 아니다. 원본 sequencer는 PREOPEN·WINDOW_WAIT·RUN 중 REQ LOW면
DRAIN으로 전환한다. GPU 모의실험의 계획값은 가상 펌프 RUN 초이므로 R15 REQ 초로
그대로 전달해 같은 효과를 기대할 수 없다. 실제 RUN 피드백과 시간 변환 검증은 남아 있으며
보상 시간을 추정해 추가하지 않는다. [정확한 조건과 계약](../protocols/r15-bridge.md).

이 검사는 `main.c`/Pico SDK·MQTT·실제 GPIO·아날로그 보호·유량을 실행하지 않는다.
신선도·세션·MQTT 경로는 기존 별도 검사 근거를 사용하고, 실물 인수 조건은 유지한다.
임시 C 소스·object·실행 파일은 검사 종료 시 제거됐고 원본 ZIP·ESP 헤더 해시는 불변이다.

함께 정정한 관리 manifest는 현행 후속 구매 `(1).xlsx`와 존재하는 R8 핀맵을 참조한다.
사라진 `verification/result.json`은 다른 실험으로 대체하지 않고 미확인으로 표시했다.
조립 안내 생성기의 기존 `--check`는 통과했다. Pi 운영 안내에는 셸마다 정의하는
`habitat` 함수를 명시해, 설치되지 않은 상시 명령이나 SSH PATH를 가정하지 않도록 했다.

### Pi 화면 수정과 진단용 가상 시퀀스

Pi 운영 `0.4.13-a1337300e296`에서 UI를 ‘요청 시간·ON 요청’으로 바꾸고 MQTT 연결과
물리 실행 확인을 구분했다. API·LiveScene·handoff 검사 15개·하위 검사 21개 통과,
제공 HTML 해시 일치, 설정·인증 파일·SaaS 대기 이벤트 보존을 실제 Pi에서 확인했다.
[배포 근거](../../var/reports/commissioning/software-r15-20261006-request-semantics-deployment.json).
당시 GPU PC는 오프라인이었고 사용자가 재확인을 나중으로 미뤘다. 마지막 실제 확인 0.4.12를
현재 0.4.13 동기화 근거로 재사용하지 않는다.

개발 소스에는 기존 `VirtualMistingTransport`에 `r15_request_fixture` 모드를 추가했다.
정상 외부 핀의 가상 조건에서 원본 결합 검사와 같은 REQ·qualify·PREOPEN·WINDOW·RUN
시간표를 재현한다. 0 RUN 요청도 완료 기록에 남기고, 양의 가상 RUN만 실행 이력에 쓴다.
기존 모드는 `desired_run_ideal`로 유지한다. 새 CLI 모의실험은 요청 fixture를 기본으로
선택하고 GPU 목표 RUN과 가상 실행 RUN의 차이를 기록한다. 미래 계획 조건이 다르므로
그 결과를 예측 정확도로 채점하지 않는다. 첫 검사 34개 통과 뒤 독립 검토에서 RUN 경계의
0초 실행 기록과 늦은 고장 시 DRAIN 시각 왜곡을 발견해 수정했다. 회귀 4개를 추가한 Pi의
격리 개발 검사 **38개 통과·1.06초**, 현재 PC/Pi 진단 소스 3개 해시 일치를 확인했다.
[최종 진단 검사](../../var/reports/commissioning/software-r15-20261006-request-fixture-check.json).
이 변경은 운영 0.4.13 설치에 포함되지 않았다. MQTT·실제 ESP task·아날로그 보호·GPIO를
재현하는 전체 에뮬레이터가 아니며 GPU 왕복 재검증도 아직 수행하지 않았다.

위 진단 당시 ESP 브리지에 추가한 요청 상한은 3초이고 PREOPEN이 요청 구간을 사용하므로 원하는 1/2/3초 RUN을
같은 숫자의 REQ로 달성할 수 없었다. 해당 진단에서는 시간을 임의 보상하거나 요청 상한을 늘리지 않았다.
원본 Pico의 `run_max_ms=3000`은 RUN 진입 뒤의 펌프 상한이다. 원본 자료에서 REQ 폭의
3초 상한을 확인한 것은 아니며, 두 상한을 같은 하드웨어 요구로 설명하지 않는다.
실제 실행 피드백과 원본 보호 조건을 지키는 명령 계약 검토가 시간 일치 목표의 남은 조건이다.

## 12. 요청 계획과 예상 RUN 분리 개정 — 2026-10-06 설계, 2026-10-07 소프트웨어 종단 검증

원본 Pico의 `run_max_ms=3000`과 제조 ZIP은 변경하지 않는다. 이번 개정은 우리 ESP
요청 브리지의 `request_hold_ms` 상한만 3000→5000ms로 확장한다. 새 호스트 실행에서
프로토콜 59개·GPIO-task 2개·hello 1개·센서 12개·원본 Pico 결합 123개가 통과했다.
실행 명령은 `python -B tests/hardware/check_cage_node.py --r15-archive <원본 ZIP>`이며
종료 코드 0이다. 원본 ZIP은 보존했고 임시 컴파일 파일은 제거했다. 검사 구현은
[native 검사 소스](../../tests/hardware/check_cage_node.py)를 따른다. 위 16개 결합 검사와
2026-10-05 ESP32 대상 빌드는 구판 3초 REQ 구현의 증거로 구분한다.

20ms ESP 작업 격자의 수신 위상 0..19를 바꾼 원본 sequencer 검사에서, WINDOW 응답이
1ms인 가상 조건의 REQ 2/3/4초는 RUN 959–979/1959–1979/2959–2979ms로 이어졌고
REQ 4.5/5초는 모든 검사 위상에서 RUN 3000ms에 도달했다. 위상 0의 RUN은 각각
959/1959/2959/3000/3000ms다. 이는 원본 소스를 결합한 호스트 검사이며 실물 GPIO·펌프
시간 측정이 아니다. 당시 남아 있던 신판 ESP32 대상 빌드·Pi/GPU 배포·schema 2 소프트웨어
종단 검증은 아래 2026-10-07 기록으로 확인했다. 실물 ESP/Pico 설치·GPIO 검증은 남아 있다.

명령 TTL 최대 5초는 **접수 유효기한**으로, REQ 유지시간이나 RUN 시간과 다르다.
수신 후에는 로컬 요청 타이머와 OFF/STOP·핀 억제·연결 유효기간을 각각 적용한다.
하트비트 신선도 1초와 브리지 재사용 대기 7초는 유지하며, 5초 REQ를 허용하기 위해
이 보호 시간을 늘리지 않는다. 신판 ESP hello는 `max_request_hold_ms=5000`을 알리고,
Pi는 필드가 없는 구판 hello를 3000ms 능력으로 처리한다. Pi는 hello 한도를 넘는 요청을
발행 전에 `r15_request_hold_unsupported_by_node`로 거절한다. Pi를 먼저 배포하더라도
구판 ESP에 5초 요청을 허용하지 않으며, 구판 ESP 자체도 3초 초과를 거절한다. 이 거절을
성공으로 표시하거나 조용히 3초로 자르거나 새 ID로 재시도하지 않는다.

GPU schema 1의 `desired_run_ideal`은 목표 RUN을 가상 펌프에 바로 적용한 과거 모드다.
Schema 2는 `timing_mode=r15_request_fixture`,
`timing_profile=r15_esp20_pico_window1ms_phase0_v1`을 사용한다.

| schema 2 항목 | 의미·검사 조건 |
|---|---|
| `selected_plan.request_hold_ms` | 60분 요청 계획, 길이 60의 정수 배열, 각 값 0..5000ms. 0은 요청 없음 |
| `selected_plan.expected_virtual_run_s` | 같은 계획을 시간 fixture로 순방향 실행한 가상 RUN, 길이 60의 유한 실수 배열, 각 값 0..3초 |
| `misting_proposal.request_hold_ms` | 선택 계획의 첫 요청과 같아야 함 |
| `misting_proposal.expected_virtual_run_s` | 선택 계획의 첫 예상 RUN과 같아야 함 |
| `misting_proposal.pulse_seconds` | schema 2에서는 첫 예상 RUN과 동일한 호환 필드. REQ 시간으로 사용하지 않음 |

양의 요청 후보 `[2000, 3000, 4000, 4500, 5000]`ms를 시간 fixture로 순방향 계산한
RUN 계획이 환경 모델의 미래 행동 입력이다. 목표 RUN에 고정 준비 시간을 더하는 역변환을
사용하지 않는다. 배열 길이·정수 요청·유한값·상한·첫 제안과 계획의 일치뿐 아니라,
예상 RUN이 지정 timing profile의 순방향 결과와 일치하는지도 검사해야 한다.
계획의 모든 RUN은 제안에 선언된 `max_pulse_seconds` 상한도 지켜야 한다.
GPU schema 2와 달리 ASCII `R15/1` 및 MQTT hello/ACK의 schema 1은 유지한다.

과거 이력에는 해당 실행 출처에서 이미 경과한 RUN 구간만 집계하며, 요청 유지초나 미래의
예상 RUN을 실제 실행 이력으로 대신 쓰지 않는다. 가상 RUN 기록은 끝까지 가상 출처로
유지하고 물리 실측 이력으로 승격하지 않는다. `field_validated=false`와
`hardware_execution_allowed=false`는 유지한다. 개발 소스 반영과 종단 검증을 구분하며, 기존
schema 1 Pi/GPU 결과를 schema 2 완료·배포 근거로 사용하지 않는다.

예상 RUN은 Pico 준비 상태, HB, WINDOW 상승·유지와 클럭·작업 간격이 fixture 조건대로
동작할 때의 값이다. 이름에 명시된 profile은 20ms ESP 격자의 요청 위상 0과 WINDOW
응답 1ms를 사용한다. 위상 0..19의 RUN 차이는 별도 native oracle 검사 범위이며 위상 0
예측값을 모든 위상의 실물 보장값으로 확장하지 않는다. REQ가 HIGH인 채 원본 3초 RUN이
먼저 끝날 수 있으므로, RUN 종료·DRAIN과 나중의 REQ LOW를 독립 사건으로 표현해야 한다.
ARMED/LEVEL HIGH는 전원 OFF·단선에서도 읽힐 수 있으므로 이
조건을 실물에서 만족했다는 증거가 아니다. 실측에서 요청/HB/WINDOW/RUN 파형, 중도
고장·STOP 반응, 밸브·펌프 지연, 토출량과 사육장 습도 반응을 별도로 확인해야 한다.
이는 고정 보상초를 더한 물리 분무량 교정이 아니며 실제 실행 피드백도 아니다.
원본 ZIP·Pico BENCH 및 Pi/ESP 출력 잠금은 유지하고, 실물 시험은 여전히 0건이다.

### 2026-10-07 실제 Pi·GPU 소프트웨어 검증

Pi 운영 `0.4.14-5a9bc13f4f2f`와 GPU 소스 0.4.14를 적용했다. 신판 ESP 헤더의 센서형·
중앙형 target build는 모두 통과했고 두 config의 `HABITAT_R15_REQUEST_OUTPUTS=0`을
확인했다. 펌웨어 업로드는 수행하지 않았으며 격리 도구chain·스케치·바이너리는 정리했다.
[대상 빌드의 버전·소스/바이너리 해시](../../var/reports/commissioning/esp32-target-build-20261007.json).

실제 Pi의 관련 프로그램 검사 208개·하위 사례 141개와 환경 API 검사 3개·하위 사례 38개가
통과했다. 임시 실제 Mosquitto broker 검사에는 구판 hello의 2초 요청, 신판 5000ms 능력의
5초 요청, 구판에 대한 5초 요청 발행 전 거부, 중복 ACK·재연결·센서 오류가 포함된다.
이는 테스트 peer를 사용한 MQTT/API 검사이며 native oracle와 합쳐 실물 ESP/Pico GPIO
왕복으로 설명하지 않는다. [검사 명령·범위](../../var/reports/commissioning/software-r15-20261007-checks.json).

합성 센서·가상 펌프만 둔 Pi→GPU CUDA 통합 실행은 가상 120분·360요청·75가상 분무를
완료했다. 360응답의 60분 계획을 순방향 timing profile과 대조했고 모든 가상 RUN은 3초
이내였다. 예상/실행 RUN 불일치 0건, 마지막 펌프 OFF·밸브 없음·idle을 확인했다.
왕복 중앙값 68.6ms·최댓값 1.93초, 실제 경과 97.07초다. 실물 시간·토출량·환경 예측
정확도 검증이 아니며 이번 재계획 궤적을 원래 조건부 예측의 정답으로 채점하지 않았다.
[전체 기록 해시와 요약](../../var/reports/commissioning/software-r15-20261007-integration.json).

Pi 설정·인증정보, GPU 설정·인증정보·기존 모델을 보존했다. Pi의 current/previous 2개
릴리스를 유지했다. SaaS 하트비트 ACK와 이벤트 동기화는 구분하며, 대기 이벤트 1개는
연속성 확인 전까지 보존한다. 실물 출력 잠금과 ARMED/LEVEL의 `execution_unverified`
상태 의미, 원본 ZIP·Pico RUN/WINDOW 조건, 기동·발열·보호협조·실제 토출 인수 조건은
이 소프트웨어 통과 결과로 해제하지 않는다.

### 목표 완료 검토 — 2026-10-07

| 요구사항 | 근거와 현재 판정 |
|---|---|
| 정확한 부품 자료·BOM 출처 | 2절의 제조사 대조와 출처 정정은 반영했다. AF120 옵션·전선 상세 규격·소켓 접합 조건은 미확인이다. 문서 검토 전체 완료로 판정하지 않는다. |
| REQ·RUN·WINDOW 일치 | 11·12절의 원본 Pico/native 대조, 시간 fixture와 360개 CUDA 계획 검증으로 소프트웨어 계약을 확인했다. 실제 파형은 인수 조건이다. |
| Pi→ESP→Pico 명령 계약 | N1 핀 배정, 만료·취소·중복·재접속·센서 오류 검사를 통과했다. 실제 장치 업로드와 GPIO 왕복은 미실시다. |
| 요청과 실제 실행 상태 구분 | `requested`·`execution_unverified`·`actual_state=null` 의미를 유지한다. ARMED/LEVEL HIGH만으로 실제 분무 성공을 표시하지 않는다. |
| Pi·GPU 동일 버전과 통합 모의실험 | 양쪽 0.4.14 소스/설치 해시와 선택 검사, 실제 Pi→GPU CUDA 360응답·75가상 실행 기록을 확인했다. 실측 예측 성능 검증은 아니다. |
| USB 카메라 호스트 구성 | 일반 ESP32 USB 직결을 제외하고 별도 Linux 영상 노드의 역할·전원 조건·전송 계약을 명시했다. 후보는 미선정이며 원격 영상 수신은 미구현이다. |
| 실제 기동·발열·토출량·실행 피드백 | 별도 인수표로 유지한다. 실제 시험 0건이며 소프트웨어 결과로 합격 처리하지 않는다. |
| 출력 잠금·원본 보존·임시파일 정리 | Pi/ESP/Pico 출력 잠금과 구매 원본을 보존한다. 임시파일 삭제는 해당 호스트의 삭제 기록으로 확인한다. |
| SaaS 운영 연속성 | 하트비트 ACK는 정상이나 이벤트 1개가 연속성 확인 대기 중이다. 서버 최고 순번 또는 원래 DB 없이 이관을 완료할 수 없다. |

**현재 목표 전체는 미완료다.** 다음 외부 확인은 정확한 부품 옵션/규격 자료와 SaaS의
서버 순번·원래 등록 DB다. 이 정보 없이 규격을 추정하거나 이벤트 순번을 새로 정하지 않는다.
실물 인수와 촬영·행동 모델의 후속 학습도 위 소프트웨어 결과와 구분한다.
