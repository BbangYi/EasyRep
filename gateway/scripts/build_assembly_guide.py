"""Build the phase-one assembly guide from the reviewed wiring sources.

Standard library only. No device, network, archive, or deployment operations.
Run from any directory; --check compares the two delivered files without writing.
"""
import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "hardware-design"
COLORS = {"3V3": "#c84b37", "GND": "#405169", "DQ13": "#8266b0",
          "DQ14": "#aa6928", "SDA": "#177f79", "SCL": "#426bb0"}


def load_sources():
    wiring = json.loads((DOC / "pin_connections_R8.json").read_text(encoding="utf-8-sig"))
    manifest = json.loads((DOC / "phase1_manifest.json").read_text(encoding="utf-8-sig"))
    with (DOC / "phase1_connections.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    nodes = {node: [r for r in rows if r["Node"] == node] for node in "ABC"}
    if len(rows) != 72 or {r["Node"] for r in rows} != set("ABC") or any(len(r) != 24 for r in nodes.values()):
        raise ValueError("Expected exactly 24 wiring operations for each of A/B/C")
    expected = {r["id"]: r for r in wiring["wires"]}
    occupied = {}
    for bus in wiring["buses"]:
        for pad in bus["pads"]:
            if pad in occupied:
                raise ValueError("Different buses share a pad: " + pad)
            occupied[pad] = bus["net"]
    for node, operations in nodes.items():
        if [int(r["Step"]) for r in operations] != list(range(1, 25)):
            raise ValueError("Out-of-order operation in node " + node)
        if {r["ID"] for r in operations} != set(expected) | {"R1", "R2"} | {"BUS" + str(n) for n in range(1, 7)}:
            raise ValueError("Missing or duplicate wiring operation in node " + node)
        for r in operations:
            if r["ID"].startswith("BUS"):
                b = wiring["buses"][int(r["ID"][3:]) - 1]
                assert (r["From"], r["To"], r["Net"]) == (b["start"], b["end"], b["net"])
            elif r["ID"] in ("R1", "R2"):
                resistor = wiring["resistors"][int(r["ID"][1:]) - 1]
                assert [r["From"], r["To"]] == resistor["pads"]
                assert [occupied[p] for p in resistor["pads"]] == resistor["nets"]
            else:
                ref = expected[r["ID"]]
                assert (r["To"], r["Net"]) == (ref["pad"], ref["net"])
                assert occupied[r["To"]] == r["Net"]
                if r["ID"].startswith("T"):
                    assert r["From"].startswith("DS-" + node)
                else:
                    assert r["From"] == ref["jx_position"] + " " + ref["pin_name"]
    return wiring, manifest, nodes


def card(code, title, parts, actions, check, stop, count=0, kind="準備"):
    return dict(code=code, title=title, parts=parts, actions=actions, check=check,
                stop=stop, count=count, kind=kind)


def make_steps(wiring, nodes):
    steps = [
        card("00", "범위와 현재 상태 확인", "최초 HWP 12품목 + 보유 Pi 5",
             ["이 안내서는 센서 노드 3대와 USB 카메라의 작업대 검증을 위한 검토본입니다.",
              "실물 사진·홀 배열·헤더 방향·전원 측정은 아직 확인되지 않았습니다. 각 확인 단계의 조건이 맞을 때만 다음 조립을 진행합니다.",
              "기존 R8의 Waveshare 카메라·SAFE R15·구형 설치 스크립트를 이 안내서와 섞지 않습니다. 이 안내서는 장치에 명령을 보내지 않습니다."],
             "최초 HWP 확보품과 이번 작업 범위를 대조하고, 사육 동물이 없는 작업대를 준비합니다.",
             "다른 모델 또는 다른 핀 배열이면 대응 그림을 확정할 때까지 해당 부품을 연결하지 않습니다."),
        card("01", "A·B·C 부품을 분리하고 라벨 붙이기",
             "노드당 ESP32 1, SEN0331 1, DS18B20 2, 분기기판 1",
             ["A = ESP32-001 / CAGE-001 / RGB-001, B = 002, C = 003으로 구분합니다. 실제 매장 설정과 다르면 설정에 맞춰 대응표부터 수정합니다.",
              "첫 프로브는 DS-A1/B1/C1, 두 번째는 DS-A2/B2/C2입니다. GPIO13 프로브는 화면 T2, GPIO14 프로브는 화면 T3입니다.",
              "SEN0331이 화면 T1(온도)·RH1(습도)을 제공합니다. 물리 배선명 T1D를 화면 T1로 읽지 않습니다.",
              "Pico H는 확보품으로 보관합니다. 이번 센서 노드 조립에는 연결하지 않습니다."],
             "세 부품 묶음에 중복 ID가 없고 각 프로브 양끝에 같은 ID를 붙였는지 확인합니다.",
             "입고품 수량과 실제 모델이 HWP와 다르면 먼저 기록합니다."),
        card("02", "공구·전원·커넥터 확인",
             "테스터와 배터리, 인두·받침, 탈피기·니퍼, 절연재, 4.7kΩ 저항 2개/노드",
             ["납·테스터를 구매했다는 사실만으로 인두·배터리·헤더·USB 데이터 케이블까지 있다고 간주하지 않습니다.",
              "4.7kΩ 저항 동봉 여부와 실물 허용오차를 확인합니다. F/F 소켓은 확인된 수핀에만 체결합니다.",
              "Pi 5 전원, ESP32 Micro-USB 전원, UH505 어댑터를 각각 라벨로 확인합니다. ESP32에는 USB와 5V/3V3 핀 전원을 중복 공급하지 않습니다.",
              "ESP32와 센서 사이에는 공통 GND가 필요합니다. Wi-Fi로 통신하는 Pi와 ESP32 사이에는 이 설계상 별도 GPIO·접지선을 추가하지 않습니다."],
             "필수 공구와 실제 맞물리는 커넥터, 정격이 확인된 전원을 준비합니다.",
             "커넥터 성별·전압·극성이 확인되지 않으면 전원을 연결하지 않습니다."),
        card("03", "실물 앞뒷면과 핀 이름 확인", "ESP32·SEN0331 앞뒷면",
             ["ESP32 모듈면: 안테나 위, USB 아래를 유지하면 J2가 왼쪽, J3가 오른쪽입니다. 뒷면은 좌우가 바뀝니다.",
              "SEN0331 센서면에서 헤더 열을 아래에 두면 VCC·GND·SCL·SDA·INT·RST 순서입니다. 실제 실크와 제조사 사진을 대조합니다.",
              "GPIO21은 21번째 핀이 아닙니다. GPIO21=J3.6, GPIO22=J3.3, GPIO13=J2.15, GPIO14=J2.12입니다.",
              "긴 수핀의 장착면, 미납땜 헤더, 프로브의 3선/4선과 선 역할을 실물로 확인합니다. 다른 색 체계는 추측하지 않습니다."],
             "확인한 앞뒷면 사진과 핀 이름을 작업 기록에 남깁니다.",
             "그림은 연결 관계를 설명하는 작업도입니다. 실물 장착면·치수·커넥터가 맞지 않으면 작업을 멈춥니다."),
        card("04", "ESP32 단독 소프트웨어 준비", "센서를 연결하지 않은 ESP32 1대",
             ["현재 프로젝트 firmware/cage_node의 센서 전용 펌웨어와 해당 노드의 비공개 config.h를 사용합니다.",
              "보드·포트를 확인하고 컴파일/업로드 결과를 기록합니다. 이 안내서를 만들면서 실제 ESP32에 업로드한 것은 아닙니다.",
              "Wi-Fi·MQTT 인증정보는 화면 캡처나 이 문서에 복사하지 않습니다. Pi의 실제 TLS 설정과 노드별 ID를 대조합니다.",
              "115200 시리얼의 기동 메시지와 Pi에서 노드 연결 여부를 확인한 뒤 전원을 분리합니다. 이 단계만으로 센서 정상 판정을 하지 않습니다."],
             "노드 ID가 맞고 업로드·기동·인증 결과가 기록되어 있어야 합니다.",
             "컴파일·업로드 또는 인증이 실패하면 하드웨어를 더 연결하지 않고 원인부터 해결합니다."),
        card("05", "기판에 작업 좌표 표시", "분기기판·자·지워지지 않는 방향 표식",
             ["독립 도금홀인지, 공통 패드가 있는지 무전원으로 확인합니다. 자동으로 연결되는 브레드보드가 아닙니다.",
              "R8의 조건은 70×90 방향, 2.54mm 피치, 26×31 독립홀 영역입니다. 실제 기판이 이 조건과 일치하는지 먼저 측정합니다.",
              "조건이 맞을 때 부품면 왼쪽 8번째·위 10번째 홀을 작업 A1로 표시하고 A~K, 1~12의 작업 영역을 정합니다. 이는 제조사 인쇄 좌표가 아닙니다.",
              "기판을 좌우로 뒤집으면 뒷면의 A가 오른쪽입니다. 위쪽 표식과 행 번호는 유지합니다. 실제 외곽에서 A1까지 거리를 기록합니다."],
             "앞뒷면에서 같은 구멍을 가리키는지 확인하고 A1 위치·홀 배열을 기록합니다.",
             "홀 수·피치·공통 패드·부품 간격이 다르면 이 좌표를 강제로 적용하지 않습니다."),
        card("06", "전선 임시 배치와 가공 길이 확인", "노드별 연결표·실제 점퍼선·라벨",
             ["전원을 모두 분리한 상태에서 실제 장착 위치에 부품을 임시 배치합니다.",
              "각 선의 커넥터 출구부터 연결점까지 경로·굽힘 여유·납땜 꼬리를 같은 기준으로 재고 기록한 후 가공합니다. 그림 길이를 자로 재서 절단하지 않습니다.",
              "F/F 점퍼의 기판 쪽을 가공하는 경우 남길 소켓과 선 ID를 먼저 표시합니다. 센서 헤더가 미납땜이면 핀 순서와 장착면 확인 후 납땜합니다.",
              "모든 버스는 납땜면, 저항 몸체는 부품면에 배치합니다. 전선과 저항 리드가 다른 버스에 닿지 않도록 절연·간격을 확인합니다."],
             "가공 전 길이 기록과 완성 하네스의 단선·잘못된 결선 여부를 확인합니다.",
             "10cm 표기나 기존 PDF의 85mm·73.40mm를 실제 절단 길이로 사용하지 않습니다.")
    ]
    checkpoints = {
        "BUS6": ("G1", "버스만 있는 기판 검사",
                 "각 버스 안의 연결을 확인하고, 서로 다른 6개 버스의 15개 조합 사이에 의도하지 않은 연결이 없는지 확인합니다.",
                 "이 검사는 저항·전자부품을 연결하기 전입니다. 이후에는 정상 저항 경로가 생기므로 같은 개방 판정을 재사용하지 않습니다."),
        "R2": ("G2", "두 풀업 저항 검사",
               "3V3↔DQ13, 3V3↔DQ14의 저항을 측정합니다. 실물 4.7kΩ 저항의 허용오차와 계측기 오차로 판정합니다.",
               "두 DQ 사이는 두 저항을 거치는 경로가 생깁니다. 단순 도통음 하나만으로 단락이라고 단정하지 않습니다. 이 단계까지 ESP32·센서는 미연결입니다."),
        "E6": ("G3", "ESP32와 기판만 첫 통전",
               "무전원 상태에서 검정 리드는 COM, 빨강 리드는 테스터 설명서의 전압 측정용 V 단자에 꽂고 DC 전압 모드로 설정합니다. 별도 대전류 단자는 사용하지 않습니다. GND와 3V3 측정점에 탐침을 안정적으로 고정한 뒤 ESP32에 USB 전원 하나만 공급하고 극성·전압을 기록합니다.",
               "실측 전압과 극성이 보드·센서의 제조사 허용 규격에 맞는지 확인되지 않으면 센서를 연결하지 않습니다. 센서가 없으므로 측정값은 invalid/null이어야 합니다. 전원을 다시 분리한 뒤 SEN0331 단계로 이동합니다."),
        "H4": ("G4", "SEN0331 단독 응답 확인",
               "무전원 검사를 마친 뒤 통전하고 Pi의 실제 센서 기록에서 T1·RH1 값과 최신 시각을 확인합니다. 두 DS 프로브 채널은 아직 invalid/null입니다.",
               "숫자가 나온다는 사실만으로 정확도 합격을 주지 않습니다. 비교 기준·위치·시각을 기록하고, 전원을 분리한 뒤 첫 프로브로 이동합니다."),
        "T1D": ("G5", "첫 프로브와 T2 대응 확인",
                "통전 후 첫 프로브만 온도가 변하도록 하여 화면 T2가 대응하는지 확인합니다. 시리얼의 probe channel=T2 gpio=13 rom=... 진단을 기록합니다.",
                "ROM 출력은 이 저장소에서 수정된 펌웨어의 기능입니다. 기존 설치본에서 보장되지 않습니다. 전원을 분리한 뒤 두 번째 프로브를 연결합니다."),
        "T2D": ("G6", "두 번째 프로브와 T3 대응 확인",
                "통전 후 두 번째 프로브의 변화가 화면 T3에 대응하는지 확인합니다. T1·RH1·T2·T3 모두 실제 센서값이며 시각이 갱신되는지 확인합니다.",
                "전체 센서 부하 상태에서도 G3와 같은 DC 전압 절차로 레일 전압을 확인합니다. 탐침 이동·재고정 전에는 전원을 분리합니다. T2/T3의 실제 위치를 기록하며 정상 수치처럼 보이는 고정값은 합격 근거가 아닙니다.")
    }
    for index, r in enumerate(nodes["A"], 1):
        rid = r["ID"]
        if rid.startswith("BUS"):
            title = r["Net"] + " 버스 연결"
            parts = "확인된 기판·절연 전선 또는 적합한 버스 재료"
            actions = [r["From"] + "에서 " + r["To"] + "까지 같은 행의 지정 홀을 납땜면에서 연결합니다.",
                       "구멍을 납으로 막아 후속 선·저항이 들어가지 못하게 하지 않습니다. 선 ID와 목적지를 확인하고 작업합니다."]
            check = "지정 버스의 시작·끝 및 각 지정 패드가 연결되었는지 무전원으로 확인합니다."
        elif rid in ("R1", "R2"):
            title = rid + " 4.7kΩ 풀업 저항"
            parts = "실물 저항값과 허용오차를 확인한 4.7kΩ 저항 1개"
            actions = ["저항 양끝을 " + r["From"] + "와 " + r["To"] + "에 연결합니다. 극성은 없습니다.",
                       "저항 몸체는 부품면, 버스는 납땜면입니다. 교차해 보이는 다른 버스와 전기적으로 연결하지 않습니다."]
            check = "해당 데이터 버스와 3V3 사이에만 저항이 들어가는지 확인합니다."
        else:
            title = rid + " 연결"
            parts = "해당 부품·선 라벨 " + rid
            actions = ["연결표의 출발 단자와 기판 목적지 한 쌍만 연결합니다. 다른 선을 동시에 옮기지 않습니다.",
                       "소켓은 확인한 수핀에, 가공한 기판 쪽 선은 지정 홀에 연결합니다. 프로브는 확인한 리드 역할로 식별합니다."]
            check = "양끝의 핀 이름·선 ID·기판 좌표를 읽으며 연결표와 대조합니다. 서로 다른 버스에 닿은 리드가 없는지 확인합니다."
            if rid in ("H1", "H2", "H3", "H4"):
                actions.append("SEN0331 INT와 RST에는 외부 선을 연결하지 않습니다. 이 설계의 VCC는 ESP32의 3V3입니다.")
            if rid.startswith("T"):
                actions.append("Adafruit 381 식별: 3선형은 빨강=VDD, 파랑/검정=GND, 노랑/흰색=DQ. 4선형은 빨강=VDD, 검정=GND, 흰색=DQ이며 맨구리 실드는 별도로 절연합니다. 실물 제품·색이 다르면 연결을 멈춥니다.")
        step = card("W" + str(index).zfill(2), title, parts, actions, check,
                    "연결·납땜·저항/도통 측정 전에는 모든 전원을 분리합니다. 실물 핀/홀 조건이 다르면 중단합니다.",
                    count=index, kind="배선")
        step["wire_id"] = rid
        steps.append(step)
        if rid in checkpoints:
            code, title, check, condition = checkpoints[rid]
            steps.append(card(code, title, "테스터·노드별 실제 기록",
                              [check, condition], "측정값·관찰 결과·검사 날짜를 기록합니다.",
                              "이 페이지 이동이나 체크는 합격 판정이 아닙니다. 이상이 있으면 전원을 분리하고 직전 연결부터 점검합니다.",
                              count=index, kind="검사"))
    steps.extend([
        card("07", "센서 분리·재연결·재부팅 검사", "완성한 센서 노드 1대",
             ["전원을 분리하고 센서 하나를 분리한 뒤 재기동하여 해당 채널이 invalid/null로 표시되는지 확인합니다. 0으로 바뀌는 것은 정상 처리로 간주하지 않습니다.",
              "전원을 다시 분리하고 센서를 복구한 뒤 최신 측정값으로 돌아오는지 확인합니다. 다른 채널의 ID가 바뀌지 않아야 합니다.",
              "Wi-Fi 단절·복구와 재부팅 후 사육장 ID·측정 시각·센서 위치 대응을 확인합니다.",
              "ROM 진단은 부팅 세션 안의 확인 기능이며 영구적인 프로브 고정·배치 변경 검증을 대신하지 않습니다."],
             "실제 측정 로그와 오류/복구 결과를 남기고 A 노드의 조립 검토를 마칩니다.",
             "분리한 센서가 계속 정상값으로 표시되면 추가 조립보다 원인 해결을 먼저 합니다.", 24, "검사"),
        card("08", "B·C 노드에 검증된 작업 반복", "나머지 센서 부품 묶음 2개",
             ["상단 노드 선택에서 B 또는 C를 선택하면 해당 연결표와 라벨을 볼 수 있습니다.",
              "A에서 확인한 부품 형상이 B/C에도 같은지 먼저 확인하고, 동일 검사 단계를 생략하지 않습니다.",
              "ESP32-002/003 각각의 비공개 설정을 사용합니다. 인증정보·TOPIC_BASE를 A에서 그대로 복사하지 않습니다."],
             "3개 노드의 ID와 실측값을 동시에 비교하고, 한 노드의 센서 변화가 다른 사육장에 표시되지 않는지 확인합니다.",
             "노드별 ID가 중복되거나 연결이 끊기면 세 노드 조립 합격으로 표시하지 않습니다.", 24, "확장"),
        card("09", "Pi 5와 USB 카메라 한 대 확인", "보유 SMG-A USB-OV5628-A · UH505",
             ["카메라가 판매 품번 15668138의 확보품인지 확인합니다. Waveshare SKU24710의 홀더·시야각·케이블 사양을 대신 적용하지 않습니다.",
              "UH505 외부 전원과 실제 데이터 케이블을 확인하고 Pi 5에 연결합니다. 카메라는 4개 데이터 포트 중 하나에 연결합니다. Power Only 포트에는 연결하지 않습니다.",
              "Pi에서 habitat cameras로 실물 장치를 찾고, v4l2-ctl --list-formats-ext -d /dev/videoN에서 지원 형식을 확인합니다. N은 실물 검색 결과입니다.",
              "habitat bind-camera RGB-001 <실제 /dev/v4l/by-path/...-video-index0 경로>로 대응시킵니다. 꺾쇠 부분을 그대로 실행하지 않습니다."],
             "실제 영상·지원 형식·사육장 대응·재연결 후 식별 결과를 기록합니다.",
             "장치 경로, FPS, 초점 잠금 지원은 실물에서 확인합니다. CSI 리본 카메라처럼 연결하지 않습니다.", 24, "카메라"),
        card("10", "USB 카메라 세 대와 저장 상태 확인", "RGB-001/002/003",
             ["한 대씩 추가하며 RGB-002와 RGB-003을 실제 경로에 연결합니다. 세 카메라를 서로 다른 사육장에 매핑합니다.",
              "전원 안정성·USB 대역폭·실제 영상의 선명도·동시 기록 상태를 확인합니다. 지원 해상도가 같아도 동시 동작은 별도 검사입니다.",
              "habitat status의 카메라·사육장 상태를 확인합니다. 기본 640×480/10FPS 설정은 행동 분석 품질을 보장하는 값이 아닙니다.",
              "녹화 용량 한도·남은 공간·기록 중단 상태를 확인합니다. 검증 없이 오래된 영상을 삭제하지 않습니다."],
             "세 영상의 ID·시각·실제 클립 재생과 저장공간 상태를 기록합니다.",
             "영상 누락·전압 문제·다른 사육장 영상이 나타나면 해당 조건을 해결한 뒤 재시험합니다.", 24, "카메라"),
        card("11", "추가 물품으로 확장하기 전", "이번 HWP에 없는 추가 부품",
             ["Pi Zero 2 W는 미구매·조건부 영상 송신기 후보이며 최종 선정품이 아닙니다. 검증 기록의 USB·전원·수신 계약과 실제 카메라 호환을 확인한 뒤 1세트 시험 여부를 결정합니다. 현재 Pi는 로컬 V4L2만 지원하며 원격 영상 수신은 아직 구현 전입니다.",
              "두 번째 SEN0331은 현재 펌웨어와 환경 모델의 입력 구성이 지원하지 않습니다. 주소/버스·RH2 채널·모델 입력을 함께 구현한 뒤 연결합니다.",
              "중앙 분무 ESP32·펌프·밸브·독립 차단부는 실제 모델·압력·기동 전류·회로가 확정된 별도 조립 단계입니다. 센서용 GPIO에 펌프 전원을 연결하지 않습니다.",
              "기존 Pico/SAFE R15 도면에서 이름만 바꿔 새 분무 회로로 사용하지 않습니다. 물통·배관·보호함의 길이와 천공 위치도 실측 대상입니다."],
             "추가 부품 목록·회로·지원 펌웨어·개별 시험 결과가 맞을 때 확장 조립도를 확정합니다.",
             "이 안내서에는 미확정 24V 단자별 연결이나 자동 분무 활성화 절차가 없습니다.", 24, "추가 단계"),
        card("12", "1차 조립 결과 기록", "실측 사진·노드별 검사 기록",
             ["검증 기록 Markdown의 판정 항목에 실제 결과를 남깁니다. 화면을 끝까지 넘겼다는 사실은 조립 완료가 아닙니다.",
              "문서 연결 대조, 호스트 코드 검사, ESP32 실물 시험, Pi 통합 시험을 각각 구분합니다.",
              "GPU의 합성 데이터 예측 응답과 실제 환경 예측 정확도는 별도 결과입니다. habitat gpu-test는 합성 요청이며 실측 성능 증명이 아닙니다.",
              "1차 센서·카메라 합격은 실제 자동 분무·행동 인식·완전한 3D 복원 합격을 의미하지 않습니다."],
             "부품·노드·배치 버전, 검사자, 날짜, 측정값, 오류 및 수정 내역이 추적 가능해야 합니다.",
             "아직 확인하지 않은 항목은 미확인으로 남깁니다. 생물 사육용 자동 출력은 빈 사육장 검증 이전에 켜지 않습니다.", 24, "기록")
    ])
    for s in steps:
        if s["kind"] == "準備":
            s["kind"] = "준비"
    assert len({s["code"] for s in steps}) == len(steps)
    assert [s["count"] for s in steps if s["kind"] == "배선"] == list(range(1, 25))
    return steps


HTML = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>HabitatOS · 1차 조립 안내</title>
<style>
:root{--ink:#20352f;--muted:#62706b;--line:#dce4de;--green:#215e47;--paper:#f6f7f3}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.65 "Malgun Gothic","Apple SD Gothic Neo",sans-serif}
button,select{font:inherit}button,select,a{touch-action:manipulation}button{cursor:pointer;border:1px solid var(--line);border-radius:8px;background:white;color:var(--ink);padding:9px 16px}
button:hover{background:#e9f0e9}button:focus-visible,select:focus-visible,a:focus-visible{outline:3px solid #417b60;outline-offset:3px}button:disabled{opacity:.4;cursor:default}
header{background:#fff;border-bottom:1px solid var(--line);padding:23px max(24px,calc((100vw - 1220px)/2))}
.brand{font-size:13px;font-weight:700;letter-spacing:.14em;color:var(--green)}h1{font-size:29px;margin:3px 0 7px;letter-spacing:-1px}
header p{color:var(--muted);margin:0;max-width:960px}.notice{background:#fff5dc;border:1px solid #ead59e;border-radius:10px;padding:12px 17px;margin:22px 0;color:#674e16;font-size:14px}
main{max-width:1268px;margin:auto;padding:0 24px 32px}.toolbar{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin:17px 0}
select{border:1px solid var(--line);border-radius:8px;background:white;padding:10px;min-width:120px}#jump{flex:1;min-width:270px;max-width:640px}
.layout{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(330px,1fr);gap:22px}.panel{background:white;border:1px solid var(--line);border-radius:15px;overflow:hidden}
.diagramHead{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;padding:14px 18px;border-bottom:1px solid var(--line);gap:10px;font-size:14px}
.diagramHead div{display:flex;gap:7px}dialog{width:min(96vw,1280px);max-height:95vh;border:1px solid var(--line);border-radius:14px;padding:18px;background:#fff;color:var(--ink)}dialog::backdrop{background:#122d22aa}.zoomHead{display:flex;justify-content:space-between;align-items:center;gap:15px;margin-bottom:12px}.zoomHead p{margin:0;font-size:14px}.zoomBody{min-width:760px}#zoom{overflow:auto}
.diagram{padding:5px 6px}svg{display:block;width:100%;height:auto}.legend{display:flex;flex-wrap:wrap;gap:9px 14px;padding:0 20px 10px;font-size:12px;color:var(--muted)}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px}.caption{margin:0;padding:8px 20px 19px;font-size:12px;color:var(--muted)}
.content{padding:23px 25px}.eyebrow{color:var(--green);font-size:13px;font-weight:700}h2{font-size:23px;line-height:1.45;letter-spacing:-.6px;margin:6px 0 18px}
.part{background:#f0f4ef;border-radius:8px;padding:12px 15px;margin-bottom:18px;font-size:14px}.part strong{display:block;color:var(--muted);font-size:12px;margin-bottom:3px}
.connection{border:2px solid #477c60;border-radius:10px;padding:12px 15px;margin:15px 0;background:#f5faf5;overflow-wrap:anywhere}.connection b{font-size:18px}
ol{padding-left:23px;margin:15px 0}li{padding-left:4px;margin:10px 0}.check,.stop{padding:13px 15px;border-radius:8px;margin:16px 0 0;font-size:14px}
.check{background:#edf5ee}.stop{background:#fff5e7;color:#6e4c1a}.check strong,.stop strong{display:block;margin-bottom:4px}
.bottom{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-top:19px}.bottom button{flex-shrink:0;white-space:nowrap}.bottom span{font-size:14px;color:var(--muted)}.primary{background:var(--green);color:white;border-color:var(--green)}.primary:hover{background:#184733}
details{margin-top:22px;background:#fff;border:1px solid var(--line);border-radius:10px;padding:14px 20px}summary{cursor:pointer;font-weight:700}
table{border-collapse:collapse;width:100%;font-size:13px;margin:14px 0}th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;overflow-wrap:anywhere}th{background:#f0f4ef}
.tablewrap{overflow:auto}a{color:var(--green)}footer{font-size:13px;color:var(--muted);margin-top:22px}.printPages{display:none}
@media(max-width:980px){.layout{grid-template-columns:1fr}.diagram{max-width:820px;margin:auto}.content{padding:20px}.toolbar{gap:8px}h1{font-size:25px}main{padding:0 14px 24px}header{padding:20px}}
@media print{@page{size:A4 portrait;margin:12mm}body{background:white;font-size:10pt}body>header,main,dialog{display:none}.printPages{display:block}.printPage{page-break-after:always;break-after:page;padding:0}.printPage:last-child{page-break-after:auto}.printPage h2{font-size:17pt;margin:5px 0}.printPage svg{width:100%;max-height:108mm}.printPage .content{padding:0}.printPage .part{margin:6px 0;padding:7px}.printPage li{margin:4px 0}.printPage .check,.printPage .stop{margin-top:6px;padding:6px;font-size:9pt}.printPage .connection{margin:5px 0;padding:5px}.printPage .caption{padding:0;font-size:8pt}.printPage footer{margin-top:5px;font-size:8pt}.printPage .eyebrow{font-size:9pt}}
</style></head><body>
<header><div class="brand">HABITATOS / ASSEMBLY</div><h1>1차 물품 조립 안내</h1><p>최초 HWP 확보품 · Raspberry Pi 5 · 센서 노드 3대 · USB 카메라 3대</p></header>
<main><div class="notice"><strong>실물 확인 전 검토본 · 2026-10-04</strong> — 현재 물품은 미조립입니다. 그림은 전기 연결과 작업 좌표를 설명하며 실물 크기·장착 형태를 보증하지 않습니다. 각 단계의 확인 조건을 먼저 충족하세요.</div>
<div class="toolbar"><label for="node">사육장</label><select id="node" aria-label="사육장 선택"><option value="A">A · 001</option><option value="B">B · 002</option><option value="C">C · 003</option></select><select id="jump" aria-label="조립 단계 선택"></select><button id="print">인쇄</button></div>
<div class="layout"><section class="panel" aria-label="연결 그림"><div class="diagramHead"><span id="drawingTitle"></span><div><button id="flip">기판 납땜면 보기</button><button id="zoomOpen">확대</button></div></div><div id="diagram" class="diagram"></div><div id="legend" class="legend"></div><p class="caption">실선/점선은 현재 보는 면과 반대 면을 구분합니다. 회색은 앞 단계의 연결, 색 선은 이번 작업입니다. 버스 위 지정 홀은 모두 연결하며, 다른 선끼리의 교차는 접속점이 아닙니다. ESP32·센서 그림은 부품면 기준 기능도입니다. 작은 핀 표기는 ‘확대’로 확인하세요.</p></section><section id="content" class="panel content" aria-live="polite"></section></div>
<nav class="bottom" aria-label="단계 이동"><button id="prev">이전</button><span id="progress"></span><button id="next" class="primary">다음 단계</button></nav>
<details><summary>현재 노드 전체 연결표와 측정 채널</summary><div class="tablewrap" id="wireTable"></div><p>T1·RH1 = SEN0331, T2 = 첫 프로브(GPIO13), T3 = 둘째 프로브(GPIO14). GPIO 번호와 헤더 순번은 서로 다릅니다.</p></details>
<details><summary>확보품과 출처</summary><div id="inventory"></div><ul id="sources"></ul></details>
<footer>문서·코드 검사와 실물 검사는 별도입니다. 페이지 이동은 검사 합격을 저장하지 않습니다. <a href="assembly-verification.md">검증 기록 Markdown</a> · <a href="assembly-guide.md">전체 안내 Markdown</a>. 이 파일은 네트워크·장치를 제어하지 않습니다.</footer></main>
<div class="printPages" id="printPages"></div>
<dialog id="zoom" aria-label="연결 그림 확대"><div class="zoomHead"><p>실물 크기 비례가 아닌 연결 작업도 · 핀 이름과 양끝을 확인하세요.</p><button id="zoomClose">닫기</button></div><div class="zoomBody" id="zoomDrawing"></div></dialog>
<script id="guide-data" type="application/json">__DATA__</script>
<script>
'use strict';
const d=JSON.parse(document.getElementById('guide-data').textContent);
let current=0,node='A',back=false;
const initial=location.hash.slice(1).split('-');
const initialIndex=d.steps.findIndex(s=>s.code===initial[0]);
if(initialIndex>=0)current=initialIndex;
if(['A','B','C'].includes(initial[1]))node=initial[1];
back=initial[2]==='back';
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const $=id=>document.getElementById(id);
function pad(p){let x=350+(p.charCodeAt(0)-65)*30;return [back?1000-x:x,160+(Number(p.slice(1))-1)*29];}
function line(a,b,color,width=3,dash=''){return '<line x1="'+a[0]+'" y1="'+a[1]+'" x2="'+b[0]+'" y2="'+b[1]+'" stroke="'+color+'" stroke-width="'+width+'" '+(dash?'stroke-dasharray="'+dash+'"':'')+'/>';}
function txt(x,y,t,size=14,fill='#33483e',anchor='start'){return '<text x="'+x+'" y="'+y+'" fill="'+fill+'" font-size="'+size+'" text-anchor="'+anchor+'">'+esc(t)+'</text>';}
function rect(x,y,w,h,fill,stroke='#cad6ce'){return '<rect x="'+x+'" y="'+y+'" width="'+w+'" height="'+h+'" rx="9" fill="'+fill+'" stroke="'+stroke+'"/>';}
function drawing(count,rid){
 let z='<svg viewBox="0 0 1100 680" role="img" aria-label="노드 '+node+' '+(back?'기판 납땜면':'기판 부품면')+' 누적 연결도" xmlns="http://www.w3.org/2000/svg">';
 z+=rect(317,113,368,432,'#f4ecda','#d1c6ad')+txt(500,100,'기판 '+(back?'납땜면 · 좌우 반전':'부품면'),18,'#675736','middle');
 z+=txt(500,575,'A1은 직접 붙이는 작업 좌표',14,'#6e6b5e','middle')+txt(500,598,'홀 배열·피치·실물 위치 확인 후 사용',13,'#6e6b5e','middle');
 for(let c=0;c<11;c++)z+=txt(pad(String.fromCharCode(65+c)+'1')[0],143,String.fromCharCode(65+c),12,'#756b55','middle');
 for(let r=1;r<=12;r++){z+=txt(back?672:330,164+(r-1)*29,r,12,'#756b55','middle');for(let c=0;c<11;c++){const p=pad(String.fromCharCode(65+c)+r);z+='<circle cx="'+p[0]+'" cy="'+p[1]+'" r="4.2" fill="#fff" stroke="#b7ad95"/>';}}
 const marks=[['J2.1 · 3V3',1,'left'],['J2.12 · IO14',12,'left'],['J2.14 · GND',14,'left'],['J2.15 · IO13',15,'left'],['J3.3 · IO22',3,'right'],['J3.6 · IO21',6,'right']];
 z+=rect(17,113,270,432,'#eaf0eb')+txt(152,92,'ESP32 · 부품면',17,'#244b37','middle');
 z+=rect(98,124,110,46,'#d8e0d8')+txt(153,153,'안테나 ↑',14,'#496348','middle')+rect(124,509,58,26,'#c9d5d0')+txt(153,528,'USB ↓',12,'#3d564b','middle');
 for(let j=1;j<=19;j++){const y=178+(j-1)*17;z+='<circle cx="41" cy="'+y+'" r="3.3" fill="#96aa9c"/><circle cx="263" cy="'+y+'" r="3.3" fill="#96aa9c"/>';}
 for(const m of marks){const y=178+(m[1]-1)*17;z+=txt(m[2]==='left'?52:252,y-5,m[0],11,'#244b37',m[2]==='left'?'start':'end');}
 z+=txt(153,467,'실물 헤더 방향 확인',11,'#68786c','middle');
 z+=rect(771,116,312,174,'#e9f3f1')+txt(927,145,'SEN0331 · 센서면',17,'#2a6057','middle')+txt(927,178,'헤더 열을 아래에 둔 방향',12,'#5c776f','middle');
 const hp=['VCC','GND','SCL','SDA','INT','RST'];hp.forEach((p,i)=>{z+=txt(796+i*50,218,p,12,'#2d6057','middle');z+='<circle cx="'+(796+i*50)+'" cy="243" r="4.5" fill="#86aaa0"/>';});
 z+=txt(927,196,'INT / RST 외부 연결 없음',12,'#617c74','middle');
 for(let j=1;j<=2;j++){const y=340+(j-1)*151;z+=rect(802,y,255,117,'#f0eff6')+txt(818,y+29,'DS-'+node+j+' → 화면 T'+(j+1),17,'#514c71');['VDD','GND','DQ'].forEach((p,i)=>{z+=txt(825+i*85,y+62,p,13,'#615879','middle');z+='<circle cx="'+(825+i*85)+'" cy="'+(y+80)+'" r="4.5" fill="#9b91b0"/>';});}
 const ep={'E1':[41,178],'E2':[41,399],'E3':[41,416],'E4':[41,365],'E5':[263,263],'E6':[263,212],
 'H1':[796,243],'H2':[846,243],'H3':[896,243],'H4':[946,243],
 'T1+':[825,420],'T1-':[910,420],'T1D':[995,420],'T2+':[825,571],'T2-':[910,571],'T2D':[995,571]};
 const ops=d.nodes[node].slice(0,count);
 for(const r of ops){const active=r.ID===rid,color=active?(d.colors[r.Net]||'#9b4b40'):'#91a19a',width=active?4:2;
 if(r.ID.startsWith('BUS')){z+=line(pad(r.From),pad(r.To),color,width,back?'':'5 4');}
 else if(r.ID==='R1'||r.ID==='R2'){const a=pad(r.From),b=pad(r.To),mid=(a[1]+b[1])/2;z+=line(a,b,color,width,back?'4 3':'');z+=rect(a[0]-8,mid-21,16,42,active?'#f0ce80':'#dfd7c2',color);z+=txt(a[0]+13,mid,r.ID+' 4.7k',11,color);}
 else{
 const a=ep[r.ID],b=pad(r.To),wireIndex=Object.keys(ep).indexOf(r.ID),bend=r.ID.startsWith('E')?292+wireIndex*4:703+(wireIndex-6)*6;
 let route='M '+a[0]+' '+a[1];
 if(r.ID.startsWith('E')&&a[0]===41){route+=' H '+(5+wireIndex*5)+' V '+(555+wireIndex*18)+' H '+bend;}
 else if(r.ID.startsWith('E')){route+=' H '+bend;}
 else{const exitY=r.ID.startsWith('H')?301+(wireIndex-6)*7:r.ID.startsWith('T1')?468+(wireIndex-10)*7:618+(wireIndex-13)*7;route+=' V '+exitY+' H '+bend;}
 route+=' V '+(b[1]-9)+' H '+b[0]+' V '+b[1];
 z+='<path d="'+route+'" fill="none" stroke="'+color+'" stroke-width="'+width+'" stroke-opacity="'+(active?1:.4)+'"/>';
 }
 if(active){const p=pad(r.To);z+='<circle cx="'+p[0]+'" cy="'+p[1]+'" r="8" fill="white" stroke="'+color+'" stroke-width="3"/>';z+=txt(p[0]+11,p[1]-8,r.To,14,color);}}
 z+=txt(24,663,'모든 단계: 실물 조건 확인 · 배선 중 전원 OFF · 도면은 크기 비례가 아님',14,'#705b35');
 return z+'</svg>';
}
function content(s){
 let h='<div class="eyebrow">'+esc(s.kind)+' / '+esc(s.code)+' · 노드 '+node+'</div><h2>'+esc(s.title)+'</h2><div class="part"><strong>준비 부품</strong>'+esc(s.parts)+'</div>';
 if(s.wire_id){const r=d.nodes[node].find(r=>r.ID===s.wire_id);h+='<div class="connection"><div>선 / 부품 ID '+esc(r.ID)+' · '+esc(r.Net)+'</div><b>'+esc(r.From)+' → '+esc(r.To)+'</b></div>';}
 h+='<ol>'+s.actions.map(a=>'<li>'+esc(a)+'</li>').join('')+'</ol><div class="check"><strong>확인할 결과</strong>'+esc(s.check)+'</div><div class="stop"><strong>진행 조건</strong>'+esc(s.stop)+'</div>';
 return h;
}
function table(){const rows=d.nodes[node];$('wireTable').innerHTML='<table><thead><tr><th>순서</th><th>ID</th><th>출발</th><th>기판 목적지</th><th>연결</th></tr></thead><tbody>'+rows.map(r=>'<tr>'+['Step','ID','From','To','Net'].map(k=>'<td>'+esc(r[k])+'</td>').join('')+'</tr>').join('')+'</tbody></table>';}
function render(){const s=d.steps[current];$('node').value=node;$('jump').value=current;$('content').innerHTML=content(s);$('diagram').innerHTML=drawing(s.count,s.wire_id);$('drawingTitle').textContent='배선 '+s.count+' / 24 · 사육장 '+node;$('flip').textContent=back?'기판 부품면 보기':'기판 납땜면 보기';$('progress').textContent=(current+1)+' / '+d.steps.length+' 페이지 · 검사 합격 표시 아님';$('prev').disabled=current===0;$('next').disabled=current===d.steps.length-1;history.replaceState(null,'','#'+s.code+'-'+node+(back?'-back':''));table();}
$('jump').innerHTML=d.steps.map((s,i)=>'<option value="'+i+'">'+esc(s.code+' · '+s.title)+'</option>').join('');
$('legend').innerHTML=Object.entries(d.colors).map(([n,c])=>'<span><i class="dot" style="background:'+c+'"></i>'+esc(n)+'</span>').join('');
$('inventory').innerHTML='<table><thead><tr><th>확보품</th><th>수량</th></tr></thead><tbody>'+d.parts.map(p=>'<tr><td>'+esc(p.name)+(p.seller_model?'<br>'+esc(p.seller_model):'')+'</td><td>'+p.quantity+'</td></tr>').join('')+'</tbody></table>';
$('sources').innerHTML=d.sources.map(s=>'<li><a href="'+esc(s[1])+'" target="_blank" rel="noopener">'+esc(s[0])+'</a></li>').join('');
$('jump').onchange=e=>{current=Number(e.target.value);render();};$('node').onchange=e=>{node=e.target.value;render();};$('flip').onclick=()=>{back=!back;render();};
$('prev').onclick=()=>{if(current>0){current--;render();}};$('next').onclick=()=>{if(current<d.steps.length-1){current++;render();}};
$('zoomOpen').onclick=()=>{$('zoomDrawing').innerHTML=drawing(d.steps[current].count,d.steps[current].wire_id);$('zoom').showModal();};$('zoomClose').onclick=()=>$('zoom').close();
document.addEventListener('keydown',e=>{if(['INPUT','TEXTAREA','SELECT','BUTTON'].includes(document.activeElement.tagName))return;if(e.key==='ArrowRight')$('next').click();if(e.key==='ArrowLeft')$('prev').click();});
function printReady(){const old=back;back=false;$('printPages').innerHTML=d.steps.map((s,i)=>'<section class="printPage"><div class="brand">HABITATOS · 실물 확인 전 검토본</div><div class="content">'+content(s)+'</div>'+drawing(s.count,s.wire_id)+'<p class="caption">연결 관계 작업도. 실물 규격·장착 형상 미확인. 기판 점선은 반대 면의 버스입니다.</p><footer>노드 '+node+' · '+(i+1)+' / '+d.steps.length+' · 2026-10-04</footer></section>').join('');back=old;}
window.addEventListener('hashchange',()=>{const p=location.hash.slice(1).split('-'),i=d.steps.findIndex(s=>s.code===p[0]);if(i>=0)current=i;if(['A','B','C'].includes(p[1]))node=p[1];back=p[2]==='back';render();});
window.addEventListener('beforeprint',printReady);window.addEventListener('afterprint',()=>{$('printPages').innerHTML='';});$('print').onclick=()=>window.print();render();
</script></body></html>
"""


def render_markdown(data):
    out = [
        "# HabitatOS 1차 물품 조립 안내",
        "",
        "**실물 확인 전 검토본 · 2026-10-04.** 최초 HWP 12품목과 보유 Raspberry Pi 5가 기준입니다.",
        "현재 물품은 미조립입니다. 연결 관계 대조는 실물 조립·통전 합격을 의미하지 않습니다.",
        "",
        "[한 단계씩 보는 그림 안내](assembly-guide.html) · [검증 결과와 남은 항목](assembly-verification.md)",
        "",
        "이 파일은 scripts/build_assembly_guide.py에서 연결표·핀맵을 대조하여 생성합니다.",
        "그림·단계 이동은 장치를 제어하지 않습니다. 실제 조립 완료 여부를 자동 판정하지 않습니다.",
        "",
        "## 확보품",
        "",
        "| 품목 | 수량 |",
        "|---|---:|",
    ]
    out += [f"| {p['name']} {p.get('seller_model', '')} | {p['quantity']} |" for p in data["parts"]]
    out += ["", "별도 보유: Raspberry Pi 5. 전원·헤더·케이블·공구·동봉 저항은 실물 확인 대상입니다.", ""]
    for step in data["steps"]:
        out += [f"## {step['code']} · {step['title']}", "", f"준비: {step['parts']}", ""]
        if step.get("wire_id"):
            out += ["| 노드 | 선/부품 ID | 출발 | 기판 목적지 | 연결 |", "|---|---|---|---|---|"]
            for node in "ABC":
                r = next(r for r in data["nodes"][node] if r["ID"] == step["wire_id"])
                out += [f"| {node} | {r['ID']} | {r['From']} | {r['To']} | {r['Net']} |"]
            out.append("")
        out += [f"{i}. {action}" for i, action in enumerate(step["actions"], 1)]
        out += ["", f"**확인할 결과:** {step['check']}", "", f"**진행 조건:** {step['stop']}", ""]
    out += ["## 검사 기록 양식", "", "아래 빈칸은 실제 확인자가 기록합니다. 예시 측정값을 채워 넣지 않습니다.", "",
            "| 날짜·검사자 | 노드·단계 | 부품/전원/배치 식별 | 측정값·관찰 | 판정·다음 조치 |", "|---|---|---|---|---|",
            "| 미기록 | 미기록 | 미기록 | 미측정 | 미판정 |", "",
            "## 제조사 근거", ""]
    out += [f"- [{name}]({url})" for name, url in data["sources"]]
    return "\n".join(out) + "\n"


def build(check=False):
    wiring, manifest, nodes = load_sources()
    data = dict(steps=make_steps(wiring, nodes), nodes=nodes, parts=manifest["parts"],
                colors=COLORS, sources=[
                    ("ESP32-DevKitC V4 핀맵·전원·헤더", "https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32/esp32-devkitc/user_guide.html"),
                    ("DFRobot SEN0331 핀맵·사진·회로도", "https://wiki.dfrobot.com/sen0331/"),
                    ("Adafruit 381 프로브 배선·4.7kΩ", "https://www.adafruit.com/product/381"),
                    ("UH505 데이터/전원 포트", "https://www.iptime.com/products/691?pd=3"),
                    ("Raspberry Pi 전원 조건", "https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#power-supply"),
                ])
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    outputs = {
        DOC / "assembly-guide.md": render_markdown(data),
        DOC / "assembly-guide.html": HTML.replace("__DATA__", body),
    }
    for path, content in outputs.items():
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                raise SystemExit("Guide is stale: " + str(path))
        else:
            path.write_text(content, encoding="utf-8")
    print(json.dumps({"status": "source_and_output_checks_passed", "steps": len(data["steps"]),
                      "nodes": 3, "connections_per_node": 24, "physical_tests": 0,
                      "outputs": [p.name for p in outputs]}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate sources and generated outputs without writing")
    build(parser.parse_args().check)
