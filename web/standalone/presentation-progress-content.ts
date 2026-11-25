export const progressNarrative = [
  {
    "id": "progress-need-observation",
    "title": "서비스의 필요성",
    "lead": "사육 조건·개체 상태·탈피 경과에서 확인된 관리의 빈틈",
    "content": {
      "evidence": [
        {
          "label": "사육 조건",
          "metric": "45.6% · 57.0%",
          "study": "독일 7개 전문 진료기관의 사육자 응답",
          "title": "권장 기준과 큰 차이를 보인 응답",
          "description": "온도 45.6%(유효 250건) · 습도 57.0%(유효 149건) / 포르투갈 220명 중 186명은 기본 조건 하나 이상 미충족",
          "detail": "",
          "source": "Pees 등 (2014) · Azevedo 등 (2021)"
        },
        {
          "label": "행동·상태 변화",
          "metric": "137건",
          "study": "영국 3개 병원 · 2019–2023 진료기록",
          "title": "건강 문제·사육 조건을 점검할 임상 신호",
          "description": "임상기록 214마리: 원인이 바로 특정되지 않은 증상\n137건 · 식욕 저하·부재 80\n무기력 34 · 체중 감소 34",
          "detail": "",
          "source": "Henley 등 (2026) · Schilliger 등 (2021)"
        },
        {
          "label": "탈피 경과",
          "metric": "47건",
          "study": "영국 3개 병원 · 레오파드 게코 214마리 진료기록",
          "title": "가장 많이 기록된 최종 진단: 탈피 이상",
          "description": "진단 272건 중 탈피 이상 47건 / 별도 반복관찰: 게코 3종 27마리·284일",
          "detail": "",
          "source": "Henley 등 (2026) · Pillai 등 (2023)"
        }
      ],
      "closing": ""
    },
    "caption": "사육 조건 조사 · 레오파드 게코 임상 기록 · 반복 탈피 관찰",
    "speakerNotes": [
      "먼저 사육 조건입니다. 독일의 전문 진료기관 7곳에서 수집한 사육자 응답은 304건입니다. 다만 항목별 무응답이 있어, 온도는 유효 250건 중 45.6%, 습도는 유효 149건 중 57.0%가 논문에서 권장 기준과 큰 차이로 분류됐습니다. 즉 사육자가 답한 조건 가운데 기준과 크게 맞지 않았던 응답의 비율입니다. 실제 센서 측정값이나 전체 사육자의 비율은 아닙니다. 포르투갈 사육자 220명 조사에서도 온도·조명·먹이·은신처 네 조건을 모두 충족한 응답은 34명이고, 186명은 하나 이상이 충족되지 않았습니다.",
      "다음은 행동·상태 변화입니다. 영국 3개 병원의 레오파드 게코 214마리 진료기록에서 원인이 바로 특정되지 않은 증상이 137건 기록됐고, 식욕 저하·부재 80건, 무기력과 체중 감소가 각각 34건이었습니다. 파충류 임상 행동 문헌은 과잉활동·반복 행동·비정상 자세 같은 행동 변화를 건강 문제와 부적절한 사육 조건을 함께 점검해야 하는 임상 신호로 다룹니다. EasyRep의 객체 탐지는 질병을 자동 진단한다고 주장하는 것이 아니라, 활동량·위치 이용·은신처 체류 변화를 정량 기록해 확인이 필요한 장면을 남기는 연구 경로입니다.",
      "탈피 경과도 별도로 확인해야 합니다. 이 임상 기록에서 탈피 이상은 총 272건의 최종 진단 가운데 47건으로 가장 많았습니다. 이는 병원에 내원한 집단의 진단 결과이며, 일반 사육 개체의 발생률은 아닙니다. 별도 반복 관찰 연구는 게코 3종 27마리를 284일 동안 매일 관찰했고, 탈피 간격이 개체와 종마다 다름을 보였습니다. 따라서 공통된 날짜가 아니라 개체별 탈피일·사진·환경 조건을 함께 기록할 필요가 있습니다."
    ],
    "sourceRefs": [
      "keeper-germany-2014",
      "keeper-portugal-2021",
      "keeper-gecko-clinical-2026",
      "clinical-reptile-behavior-2021",
      "gecko-ecdysis-repeat-2023",
    ],
    "relatedSlides": [
      "progress-need-prediction",
      "progress-spatial-method",
      "progress-appearance-input",
      "progress-humidity-method"
    ],
    "role": "necessity"
  },
  {
    "id": "progress-need-evidence",
    "title": "서비스의 필요성 - 공간 온도 모델",
    "lead": "열환경의 공간 배치 연구를 바탕으로, 3DGS 구상에서 센서 실측 기반 모델로 전환했습니다.",
    "content": {
      "stages": [
        ["기존 확인 방식", "사육장 전체의 평균·현재값", "Sears 등(2016): 평균·온도 범위가 같아도 공간 배치에 따라 체온조절 정확도·이동 비용이 달라져 위치별 차이를 놓칠 수 있음"],
        ["초기 구상", "3DGS 기반 사육장 재구성", "사육장 내부를 실제처럼 3차원으로 표현하는 방향"],
        ["현재 모델", "센서 위치 + 동일 시각 실측값", "점은 센서 실측값, 공간 색은 거리 기반 온도 추정값"],
        ["선택 이유", "측정값으로 위치별 열환경 비교", "3DGS만으로 시간별 온도장을 만들 수 없어 실측값을 연결"]
      ],
      "closing": ""
    },
    "caption": "Sears 등(2016) 열환경 연구 · 현재 센서 위치 기반 온도 추정",
    "speakerNotes": [
      "Sears 등의 2016년 열환경 연구는 평균 온도와 온도 범위가 같아도, 적정 온도가 공간 안에 어떻게 배치됐는지에 따라 외온동물의 체온조절 정확도와 이동 비용이 달라질 수 있음을 모의와 야외 도마뱀 실험으로 보였습니다. 따라서 기존처럼 사육장 전체의 평균·현재값만 확인하면 위치별 열환경 차이를 놓칠 수 있습니다.",
      "초기에는 사육장 내부를 3DGS처럼 실제 공간으로 재구성하는 방향을 고려했습니다. 하지만 관리에서 필요한 것은 실제처럼 보이는 화면 자체가 아니라, 같은 시각에 어느 위치가 다른 위치보다 덥거나 차가운지를 비교하는 것입니다.",
      "3DGS는 실제 다각도 촬영과 공간 복원이 필요하지만, 그것만으로 시간별 온도장을 만들 수 없습니다. 그래서 현재는 등록한 사육장 형상과 센서 위치, 같은 시각의 실측 온도를 연결하는 모델을 선택했습니다.",
      "화면의 점은 센서 실측값이고, 점 사이의 색은 가까운 센서값을 바탕으로 계산한 추정값입니다. 따라서 이 화면은 실제 3D 촬영이나 3DGS 결과가 아니라, 위치별 온도를 확인하기 위한 센서 기반 공간 추정입니다."
    ],
    "sourceRefs": [
      "thermal-landscape-2016",
      "spatial"
    ],
    "relatedSlides": [
      "progress-need-observation",
      "progress-need-prediction",
      "progress-spatial-method",
      "progress-appearance-input"
    ],
    "role": "necessity"
  },
  {
    "id": "progress-need-prediction",
    "title": "프로젝트 진행 경과",
    "lead": "",
    "content": {
      "earlier": [
        ["10.06", "예측 분무 시험", "합성 환경의 습도 변화 비교"],
        ["10.22", "센서·영상 기반", "센서 조립·수신과 탐지·추적 개발"],
        ["11.05", "R3 발표", "사육장 공간·영상·제어 방향 정리"]
      ],
      "ticks": ["11.06", "11.08", "11.09", "11.10", "11.16", "11.17"],
      "lanes": [
        {
          "title": "환경·이력",
          "segments": [
            {"date": "11.06", "title": "이력 조회 보완", "description": "동일 시각 2,002건 경계 수정 · 운영 확인", "start": 1, "end": 2, "kind": "verified"}
          ]
        },
        {
          "title": "현장 장치·영상",
          "segments": [
            {"date": "11.08", "title": "카메라 연결", "description": "네트워크 카메라 연결", "start": 2, "end": 3, "kind": "verified"},
            {"date": "11.09", "title": "현장 장치 배선", "description": "카메라·적외선 장치 연결", "start": 3, "end": 4, "kind": "verified"},
            {"date": "11.10", "title": "영상 수신 확인", "description": "천장·전면 영상 수신·재생", "start": 4, "end": 5, "kind": "verified"}
          ]
        },
        {
          "title": "개체 탐지",
          "segments": [
            {"date": "11.07–17", "title": "반복 학습·후보 비교", "description": "후보 생성·검증기 비교 · 일반 사진 305장 재평가", "start": 2, "end": 7, "kind": "research"}
          ]
        },
        {
          "title": "탈피 기록·예측",
          "segments": [
            {"date": "11.07–17", "title": "자료 연결·기준선 평가", "description": "외관·날짜·반복 주기 자료 · 예측 오차 비교", "start": 2, "end": 7, "kind": "research"}
          ]
        },
        {
          "title": "습도 제어",
          "segments": [
            {"date": "11.16", "title": "수중 펌프 조립", "description": "사육장 모델 설치", "start": 5, "end": 6, "kind": "verified"},
            {"date": "다음", "title": "실물 반응 시험", "description": "분무 뒤 습도·회복 시간 기록", "start": 6, "end": 7, "kind": "next"}
          ]
        }
      ],
      "closing": ""
    },
    "caption": "2026.10.06–2026.11.17 · 사용자 제공 현장 영상·배선 기록 · 개발·평가 자료",
    "speakerNotes": [
      "10월에는 합성 환경의 분무 변화를 비교하고, 센서 수신과 영상 탐지·추적 기반을 만들었습니다. 11월 5일 R3 발표에서는 사육장 공간·두 방향 영상·분무 제어 방향을 정리했습니다.",
      "R3 이후 11월 6일에는 같은 시각 기록 2,002건의 페이지 경계 누락을 수정하고 운영 조회를 확인했습니다. 11월 8일 네트워크 카메라를 연결하고, 11월 9일 카메라·적외선 장치 현장 배선을 마쳤습니다. 11월 10일 EasyRep에서 천장·전면 영상 수신과 재생을 확인했습니다.",
      "11월 7일부터 17일까지는 개체 탐지와 탈피 예측을 병렬로 반복했습니다. 탐지는 후보 생성과 검증기를 함께 비교했고, 탈피 연구는 외관·날짜·반복 주기 자료를 연결해 단순 기준선과 예측 오차를 비교했습니다.",
      "11월 16일에는 수중 펌프를 사육장 모델에 조립했습니다. 11월 17일에는 일반 사진 305장의 탐지 결과와 탈피 예측의 기준선 비교를 다시 정리했습니다. 실물 분무 반응은 다음 단계에서 기록합니다."
    ],
    "sourceRefs": [
      "r3",
      "remoteHistory",
      "spatial",
      "historyBoundary029",
      "appearancePipeline029",
      "modelLearningAudit20261117",
      "technicalResearch"
    ],
    "relatedSlides": [
      "progress-after-r3",
      "progress-spatial-method",
      "progress-history-result",
      "progress-history-production",
      "progress-detection-result",
      "progress-appearance-input",
      "progress-appearance-prediction",
      "progress-appearance-result",
      "progress-humidity-method"
    ],
    "role": "timeline"
  },
  {
    "id": "progress-after-r3",
    "title": "R3 이후 검증 결과",
    "lead": "",
    "content": {
      "decisions": [
        {
          "area": "공간 이력",
          "focus": "같은 시각 기록 누락 수정",
          "result": "조회 누락 2건 → 0건",
          "scope": "동일 시각 합성 2,002건 경계 시험",
          "decision": "수정 반영 · 운영 화면 확인"
        },
        {
          "area": "개체 탐지",
          "focus": "일반 사진 탐지 개선",
          "result": "F1 93.31% → 96.74%",
          "scope": "개발평가 305장 · 정답 293개",
          "decision": "야간 4/11 기준 미달 · 추가 검증"
        },
        {
          "area": "탈피 예측",
          "focus": "기록 기반 예측 검토",
          "result": "특징 추가로 오차 감소 미확인",
          "scope": "게코 3종 25개체 · 개체 분리 5-fold",
          "decision": "예측 기능 미채택 · 반복 기록 축적"
        }
      ]
    },
    "caption": "2026.11.06–11.17 · 운영 이력 수정 · 일반 사진 개발평가 · 탈피 날짜 예측 비교",
    "speakerNotes": [
      "R3 이후에는 운영 기록, 개체 탐지, 탈피 예측을 각각 다른 기준으로 다시 검증했습니다. 결과를 하나의 완료 주장으로 묶지 않고, 확인된 것과 미채택 결과를 분리해 제시합니다.",
      "공간 이력은 같은 시각의 합성 기록 2,002건 경계에서 남은 2건이 빠지던 문제를 수정한 뒤, 중복 없이 모두 조회하고 운영 화면에서도 확인했습니다.",
      "개체 탐지는 같은 일반 개발 사진 305장, 정답 293개에서 기존 방식과 최신 결합 파이프라인을 비교했습니다. F1은 93.31%에서 96.74%로 올랐지만, 야간은 정답 11개 중 4개만 검출해 채택하지 않았습니다.",
      "탈피 예측은 게코 3종 25개체를 개체 단위로 분리해 비교했습니다. 기록 특징을 더한 결과가 단순 기준선보다 나아지지 않아 기능으로 채택하지 않았고, 비교 기준과 수치는 뒤에서 설명합니다."
    ],
    "sourceRefs": [
      "r3",
      "postR3Delta029",
      "modelLearningAudit20261117"
    ],
    "role": "new-scope",
    "relatedSlides": [
      "progress-history-result",
      "progress-detection-result",
      "progress-appearance-result"
    ]
  },
  {
    "id": "progress-spatial-method",
    "title": "공간 이력 현황",
    "lead": "",
    "content": {
      "snapshot": {
        "label": "운영 환경 이력",
        "value": "397,697건",
        "title": "2개 사육장 · 2026.10.19–11.18",
        "detail": "온도·습도 센서 출처 · 운영 DB 읽기 전용 집계"
      },
      "status": [
        { "label": "현재 활용", "title": "과거 시점·위치별 온·습도 조회", "detail": "선택한 시각의 센서값을 등록 위치와 함께 확인" },
        { "label": "다음 연구", "title": "환경 변화·회복 시간 예측", "detail": "축적 이력에서 최근값·규칙 기준선과 비교해 평가" }
      ],
      "closing": ""
    },
    "caption": "운영 DB 집계 2026.11.18 14:39 KST · 온도·습도 센서 출처 이력만 포함",
    "speakerNotes": [
      "이 장의 핵심은 현재 쌓인 운영 환경 이력이 어디까지 쓸 수 있는지입니다. 운영 DB를 읽기 전용으로 집계한 결과, 2개 사육장에 2026년 10월 19일부터 11월 18일까지 온도·습도 센서 출처 이벤트가 397,697건 있습니다. 이 수는 이벤트 건수이며 센서 정확도나 사육 효과를 뜻하지 않습니다.",
      "현재는 특정 과거 시점에 어느 센서 위치에서 어떤 온도·습도 값이 기록됐는지를 조회할 수 있습니다. 즉 사육장 전체를 하나의 현재값으로 보지 않고, 시간과 위치를 함께 확인하는 단계입니다.",
      "다음 연구는 충분한 이력에서 온도·습도 변화와 분무 뒤 회복 시간을 짧은 다음 구간으로 예측하는 것입니다. 최근값 유지나 규칙 제어를 같은 미래 구간에서 비교해, 예측이 실제로 더 나은지를 판단합니다. 10월의 예측 분무 결과는 합성 시험이므로 여기의 운영 성능으로 사용하지 않습니다.",
      "동일 시각 2,002건의 페이지 경계 누락은 조회 구현을 고친 별도 합성 시험입니다. 이 장의 본문에서는 빼고, 4번 결과와 상세 자료에서만 다룹니다."
    ],
    "sourceRefs": [
      "spatial",
      "esri-idw",
      "liveHistoryAggregate20261118",
      "prediction"
    ],
    "role": "operational-verification",
    "relatedSlides": [
      "rationale-interpolation",
      "rationale-spatial"
    ]
  },
  {
    "id": "progress-history-result",
    "title": "같은 시각 기록의 누락 수정",
    "lead": "과거 위치별 비교에 필요한 동일 시각 기록의 누락 해소",
    "content": {
      "before": "시각 커서: 2,000 + 0",
      "after": "시각·ID 커서: 2,000 + 2",
      "result": "전체 2,002건 · 중복 0",
      "image": "/presentation/er029-history-boundary-20261106.png",
      "closing": "같은 시각의 남은 기록까지 조회 · 11.06 운영 반영",
      "cursorFlow": [
        "서버의 시각·ID 커서",
        "공간 화면의 다음 페이지"
      ]
    },
    "caption": "2026.11.06 · 동일 시각 합성 2,002건 경계 시험 · 운영 조회 확인은 별도 기록",
    "speakerNotes": [
      "같은 시각의 합성 기록 2,002건으로 페이지 경계를 검사했습니다. 기존 공간 화면은 첫 2,000건 이후 남은 기록을 이어 받지 못했습니다. 서버에 이미 있던 전체 정렬 커서를 다음 요청에 전달하도록 수정해 나머지 2건까지 조회했습니다. 전체 2,002건에서 중복은 0건이었습니다.",
      "고정된 조회 경계와 시각·ID 커서를 함께 전달하는 클라이언트 수정입니다. 화면은 로컬 합성 경계 시험 캡처이며, 날짜가 다른 장기 수집 결과와 구분합니다. 별도의 6,505건 탐색과 운영 조회 확인 기록은 참고 자료에 연결했습니다."
    ],
    "sourceRefs": [
      "historyBoundary029",
      "spatial",
      "postR3Delta029"
    ],
    "role": "new-result",
    "relatedSlides": [
      "spatial-history",
      "progress-history-production"
    ]
  },
  {
    "id": "progress-history-production",
    "title": "운영 화면의 기간·시점 조회",
    "lead": "과거 구간과 시점을 바꿔 위치별 센서값 확인",
    "content": {
      "image": "/presentation/er029-production-history-20261106.jpg",
      "flow": [
        "과거 기록 열기",
        "기간 변경",
        "시점 선택"
      ],
      "closing": "누락 수정 후 기간·시점 조회와 센서값 반영 확인",
      "verifiedResults": [
        [
          "과거 기록",
          "2,000건 → 이전 2,000건"
        ],
        [
          "조회 기간",
          "6시간 → 1시간 · 369건"
        ],
        [
          "시점 선택",
          "선택 시점의 센서값 반영"
        ]
      ]
    },
    "caption": "2026.11.06 운영 캡처 · 화면의 가상 검증 사육장·측정 지연 표시 보존",
    "speakerNotes": [
      "2026년 11월 6일 운영 반영 후 로그인된 브라우저에서 과거 기록 조회, 기간 변경과 시점 선택을 확인했습니다. 캡처에는 가상 검증 사육장 이름과 측정 지연 표시가 포함돼 있습니다. 이 결과의 확인 범위는 운영 화면과 이력 요청의 동작입니다.",
      "6시간 페이지에는 2,000건(09:22:27–14:54:40 KST), 이전 페이지에는 2,000건(04:52:11–09:22:22 KST)이 표시됐습니다. 기간을 1시간으로 바꾼 화면에는 369건(08:22:45–09:22:27 KST)이 표시됐고, 시점 선택에 따라 센서값이 바뀌었습니다.",
      "건수는 해당 시점과 기간의 조회 결과입니다. 센서 정확도·수집률·동물의 상태에 대한 측정은 별도 검증 범위입니다. 확인 시각은 2026년 11월 6일 14:58 KST이며 browser-verification.json에 기록돼 있습니다."
    ],
    "sourceRefs": [
      "historyBoundary029",
      "postR3Delta029"
    ],
    "role": "new-operational-verification",
    "relatedSlides": [
      "outdoor-environment"
    ]
  },
  {
    "id": "progress-detection-method",
    "title": "도마뱀 탐지 학습·결합",
    "lead": "개체 출현 후보 · 검증 경로",
    "content": {
      "summary": "일반 사진 개발 평가 경로",
      "pipeline": [
        {
          "label": "기존 후보",
          "title": "hybrid / SAM+CLAHE",
          "detail": "일반 사진 후보 유지"
        },
        {
          "label": "추가 후보",
          "title": "YOLO-World 503",
          "detail": "1,474장 · 883그룹 · 883 update"
        },
        {
          "label": "후단 검증",
          "title": "고정 DINO 검증기",
          "detail": "후보 수락 기준 유지"
        }
      ],
      "trial": {
        "label": "추가 비교",
        "title": "Grounding 561 → 562",
        "detail": "64장 · 64그룹 · 64 update\n추가 수락 후보 없음 · 결합 결과 505와 동일"
      },
      "decision": "결합 평가 · 기존 후보 · 추가 후보 · 고정 검증기"
    },
    "caption": "2026.11.17 · 일반 사진 개발평가에 사용한 후보 생성·검증 결합 경로",
    "speakerNotes": [
      "현재 일반 사진 수치는 단일 모델을 교체한 성능이 아닙니다. 기존 hybrid/SAM+CLAHE 후보를 보존하고, 빈 결과에 YOLO-World 503이 후보를 추가한 뒤 기존 DINO 검증기와 같은 기준으로 수락 여부를 판정한 결합 결과입니다.",
      "YOLO-World 503은 CNN 본체를 1,474장, 883그룹, 883 update로 실제 학습했습니다. 이 숫자는 사진과 학습 묶음의 규모이며, 독립 현장 성능을 뜻하지 않습니다. 후보를 수락하는 DINO 검증기는 이 최종 비교에서는 고정해 두었습니다.",
      "Grounding 561은 시각·언어·결합·검출부를 64장, 64그룹, 64 update로 실제 학습했습니다. 그러나 562 평가에서 추가로 수락된 후보가 없어 현재 결합 성능은 505와 같습니다. 학습이 실행됐다는 사실과 최종 성능 향상은 구분합니다.",
      "다음 장에서는 이 결합 경로가 일반 개발 사진과 야간에서 각각 어느 정도였는지, 그리고 왜 현장 적용을 보류하는지를 별도로 제시합니다."
    ],
    "sourceRefs": [
      "modelLearningAudit20261117"
    ],
    "role": "model-training-method",
    "relatedSlides": [
      "detection",
      "progress-detection-result"
    ]
  },
  {
    "id": "progress-detection-result",
    "title": "도마뱀 탐지 평가",
    "lead": "일반 사진 개발 평가 · 야간 정답 점검",
    "content": {
      "general": {
        "label": "일반 사진 개발 평가 · 305장",
        "before": "기준 조합",
        "after": "현재 결합 파이프라인",
        "metrics": [
          ["TP", "265", "282"],
          ["FN", "28", "11"],
          ["FP", "10", "8"],
          ["F1", "93.31%", "96.74%"]
        ],
        "summary": "정답 +17 · 누락 −17 · 오탐 −2"
      },
      "issue": {
        "label": "야간 정답",
        "value": "4 / 11",
        "context": "야간 정답 11개 중 탐지",
        "summary": "후보 생성 부족 · 후단 검증 실패"
      },
      "next": {
        "label": "다음 평가",
        "title": "새 사육장 · 실제 야간 연속 영상",
        "description": "정답 구간 · 후보 수 · 검증 결과 · 시간당 오탐"
      },
      "closing": ""
    },
    "caption": "2026.11.17 · 같은 개발 사진 305장 비교 · 야간 정답 11개 별도 확인",
    "speakerNotes": [
      "이 장은 11월 7일의 crop 검증기 비교를 대체합니다. 현재 수치는 일반 사진 개발 305장에서 기준 hybrid/SAM+CLAHE와 YOLO-World 503+505 및 Grounding 561+562 결합 파이프라인을 비교한 결과입니다.",
      "일반 사진에서 TP는 265에서 282, FP는 10에서 8, FN은 28에서 11로 바뀌었습니다. precision은 96.36%에서 97.24%, recall은 90.44%에서 96.25%, F1은 93.31%에서 96.74%입니다. 561 학습은 추가로 채택된 후보가 없어 현재 결합 결과는 505 결과와 같습니다.",
      "야간 정답은 11개 중 4개만 찾았습니다. 감사에서는 새 후보 22개 가운데 정답과 맞는 후보 6개가 고정 임계값보다 낮았고, 나머지 16개는 정답과 맞지 않았습니다. 후보 생성 부족과 후단 검증 실패를 구분해 남긴 결과입니다.",
      "다음에는 처음 보는 사육장과 실제 야간 연속 영상에서 정답 구간, 생성 후보 수, 검증 통과·실패, 시간당 오탐을 분리 기록합니다. 일반 사진의 개발평가 개선을 야간 현장 성능으로 확대 해석하지 않습니다."
    ],
    "sourceRefs": [
      "modelLearningAudit20261117"
    ],
    "role": "new-real-feature-training-result",
    "relatedSlides": [
      "progress-detection-method"
    ]
  },
  {
    "id": "progress-appearance-input",
    "title": "탈피 상태 판별",
    "lead": "외관 상태 분류 · 사용 판단",
    "content": {
      "runs": [
        {
          "label": "실험 206",
          "title": "진행 상태",
          "method": "DINOv2 마지막 block + 분류 head\n200 update",
          "data": "사진 19장 · 연속 영상 8프레임\n소유자 라벨 15건",
          "result": "주요 평가 2장 · TP 0 / FN 1 / TN 1"
        },
        {
          "label": "실험 212",
          "title": "탈피 전 상태",
          "method": "DINOv2 마지막 block + 분류 head\n200 update",
          "data": "사진 9장 · 상관 프레임 8개\n탈피 전 사진 1장",
          "result": "평가 4장 · balanced accuracy 50%\n주요 양성 1건 누락"
        }
      ],
      "decision": {
        "label": "사용 판단",
        "title": "미채택",
        "detail": "핵심 양성 누락 · 정상 상태 학습 없음"
      },
      "next": {
        "label": "다음 자료",
        "title": "3단계 라벨",
        "detail": "정상 · 탈피 전 · 진행 상태 / 개체·날짜 분리 평가"
      }
    },
    "caption": "2026.11.17 · 외관 상태 분류 학습 감사 · 사용 미채택",
    "speakerNotes": [
      "외관 상태 판별은 날짜 예측과 다른 과제입니다. 실험 206은 사진에서 눈에 보이는 박리 진행을, 212는 소유자 보고의 탈피 전 상태와 진행 상태를 구분하려 했습니다. 두 실험 모두 DINOv2의 마지막 block과 분류 head를 실제 역전파로 학습했습니다.",
      "206은 19장 사진과 상관된 영상 8프레임, 15개 소유자 라벨로 200 update를 수행했습니다. 핵심 평가 2장에서는 탈피 진행 양성을 놓쳐 TP 0, FN 1, TN 1이었습니다. 별도 stress 양성 두 장을 맞혔더라도 핵심 양성 실패를 덮지 않습니다.",
      "212는 탈피 전 학습 사진이 한 장뿐이었고, 4장 평가에서 주요 양성을 놓쳤습니다. 75% accuracy만 보면 좋아 보이지만 모두 진행 상태로 답하는 기준선도 75%였고 balanced accuracy는 50%였습니다. 그래서 현재 사용을 승인하지 않습니다.",
      "다음에는 같은 종과 촬영 조건에서 정상·탈피 전·진행 상태를 각각 라벨링하고, 같은 개체의 날짜별 사진이 학습과 평가에 섞이지 않도록 분리합니다."
    ],
    "sourceRefs": [
      "appearancePipeline029",
      "modelLearningAudit20261117"
    ],
    "role": "appearance-model-evaluation",
    "relatedSlides": [
      "rationale-shedding",
      "progress-appearance-prediction"
    ]
  },
  {
    "id": "progress-appearance-prediction",
    "title": "탈피 날짜 예측",
    "lead": "개체 분리 5-fold · 기준선 비교",
    "content": {
      "cohort": "게코 3종 · 25개체 · 개체 분리 5-fold",
      "steps": [
        {
          "label": "평가 분리",
          "value": "평가 5개체",
          "description": "다른 20개체 학습"
        },
        {
          "label": "기준선",
          "value": "집단 중앙값",
          "description": "다음 탈피까지 남은 일수"
        },
        {
          "label": "특징 결합",
          "value": "8개 기록 특징",
          "description": "중첩 검증 · 특징 비중"
        }
      ],
      "comparison": [
        {
          "label": "집단 중앙값",
          "value": "MAE 6.72일"
        },
        {
          "label": "기록 특징 결합",
          "value": "MAE 7.03일"
        },
        {
          "label": "비교 결과",
          "value": "오차 +0.31일"
        }
      ],
      "featureFinding": "특징 비중 0 · 5회 중 4회",
      "pending": "사진·날짜 연결 자료 없음",
      "decision": "예측 기능 미채택 · 반복 주기·사진 자료 축적"
    },
    "caption": "2026.11.17 · 게코 3종 25개체 · 개체 분리 5-fold · 날짜 기록 기반 비교",
    "speakerNotes": [
      "비교 기준은 각 평가 그룹의 개체를 빼고 남은 20개체에서 계산한 ‘다음 탈피까지 남은 일수’의 중앙값입니다. 즉, 평가 개체의 정답을 기준선 계산에 넣지 않았습니다.",
      "기록 특징 결합 값은 8개 측정 특징과 이 중앙값을 중첩 검증으로 섞어 만든 값입니다. 집단 중앙값 MAE가 6.72일, 특징 결합 MAE가 7.03일로 0.31일 커졌습니다. 다섯 평가 중 넷은 특징 비중이 0이었습니다.",
      "따라서 이 결과는 특정 개체의 직전 탈피 간격이 아니라, 자료 안에서 가장 단순한 학습 집단 기준과의 비교입니다. 게코 3종 25개체 자료이며 크레스티드 게코 현장 예측 성능 주장은 아닙니다. 사진과 날짜를 결합한 실험은 같은 개체의 사진·관측 시점·이후 탈피일이 모두 연결된 자료가 부족해 아직 평가하지 않았습니다."
    ],
    "sourceRefs": [
      "appearancePipeline029",
      "modelLearningAudit20261117"
    ],
    "role": "new-model-evaluation",
    "relatedSlides": [
      "progress-appearance-result"
    ]
  },
  {
    "id": "progress-appearance-result",
    "title": "외관 관찰부터 예측·평가까지",
    "lead": "검수 사진을 특징 이력·예측·평가 자료로 연결",
    "content": {
      "stages": [
        "사진·조건 검수",
        "누적 특징 이력",
        "기준 시점의 예측",
        "탈피 관찰과 비교"
      ],
      "outputs": [
        [
          "정상 입력",
          "사진·마스크에서 특징·예측·평가 자료 생성"
        ],
        [
          "자료 부족·시점 충돌",
          "예측 보류와 원인 기록"
        ]
      ],
      "closing": "합성 입력의 실행 경로 확인 · 실개체 반복 주기 평가로 연결"
    },
    "caption": "2026.11.07 · 합성 사진·마스크·시계열로 로컬 검증 · 단발 CLI 실행",
    "speakerNotes": [
      "사진·관찰 검수, 누적 이력 구성, 정해진 시점의 예측 발행과 사건 평가를 연결했습니다. 색·질감 시계열, 검수 입력과 누적 이력 처리를 포함합니다. 정상 입력에서는 결과 자료를 만들고, 입력 부족이나 시점 충돌은 보류 사유를 남깁니다.",
      "예측 발행은 사전 일정과 실행 기록을 확인하는 단발 CLI 실행입니다. 상시 스케줄러, 사용자 알림과 웹 예측 화면은 후속 통합 범위입니다. 입력 검수에는 사람이 확인한 개체·촬영·관찰 정보를 사용합니다.",
      "현재 검증은 합성 사진·마스크·시계열을 이용한 로컬 소프트웨어 검증입니다. 다음 평가에는 같은 개체의 반복 탈피 관찰과 촬영 조건이 확인된 자료가 필요합니다."
    ],
    "sourceRefs": [
      "appearancePipeline029"
    ],
    "role": "new-software-result",
    "relatedSlides": [
      "progress-appearance-input"
    ]
  },
  {
    "id": "progress-humidity-method",
    "title": "현장 영상 연동",
    "lead": "카메라·적외선 장치 · 사이트 영상 수신",
    "content": {
      "status": {
        "label": "수신 확인",
        "title": "천장·전면 영상",
        "detail": "2026.11.10 · 네트워크 카메라 2대 · 수신·재생 상태"
      },
      "steps": [
        ["11.08", "카메라 연결", "네트워크 카메라 연결"],
        ["11.09", "현장 장치 배선", "카메라 · 적외선 장치"],
        ["11.10", "사이트 영상 수신", "천장 · 전면 영상 수신 · 재생"],
        ["다음", "실제 영상 평가", "주 · 야간 연속 영상 · 탐지 평가"]
      ]
    },
    "caption": "2026.11.10 사용자 제공 EasyRep 영상 수신 화면",
    "speakerNotes": [
      "11월 8일 네트워크 카메라를 연결했고, 11월 9일에는 카메라와 적외선 장치의 현장 배선을 연결했습니다. 11월 10일 EasyRep에서 천장과 전면 카메라의 영상 수신·재생을 확인했습니다.",
      "화면은 당시 사이트에서 두 카메라가 영상 수신·재생 상태로 표시된 기록입니다. 탐지 결과나 야간 탐지 성능을 의미하는 화면은 아닙니다.",
      "다음 단계는 이 연결을 실제 주·야간 연속 영상으로 기록하고, 정답 구간·후보 수·검증 결과·시간당 오탐을 분리해 평가하는 것입니다."
    ],
    "sourceRefs": [
      "prediction",
      "technicalResearch",
      "r3",
      "monsoon",
      "ecc"
    ],
    "role": "existing-method-followup",
    "relatedSlides": [
      "rationale-misting",
      "prediction",
      "misting"
    ]
  },
  {
    "id": "progress-conclusion",
    "title": "결과보고서 초안",
    "lead": "9개 장 · 4개 검증 축",
    "content": {
      "summary": "현재 자료 · 다음 검증",
      "columns": [
        "검증 축",
        "현재 자료",
        "다음 검증"
      ],
      "rows": [
        [
          "환경·공간 이력",
          "공간 이력 조회 · 센서 위치 기반 추정",
          "기준 센서 · 실측점 오차"
        ],
        [
          "영상 탐지",
          "일반 사진 개발 평가 · 야간 정답 4/11",
          "새 사육장 · 주/야간 연속 영상 · TP/FN/시간당 FP"
        ],
        [
          "탈피 연구",
          "상태 판별 · 날짜 예측 미채택",
          "사진 · 반복 날짜 · 정상/탈피 전/진행 라벨"
        ],
        [
          "습도 제어",
          "수중 펌프 조립",
          "실물 작동 · 누수 · 습도 회복 시간"
        ]
      ],
      "closing": ""
    },
    "caption": "결과보고서 9개 장 · 현재 자료와 다음 검증",
    "speakerNotes": [
      "결과보고서 초안은 서론, 배경, 유사 기술 비교, 시스템, 구현 화면, R3 이후 결과, 관리 흐름, 산출물, 부록의 9개 장으로 구성했습니다. 구현과 측정 결과를 한 장에 섞지 않고, 각 장에서 현재 확인된 범위와 보완이 필요한 근거를 표시합니다.",
      "공간 이력에는 기준 센서와 비교한 공간 추정 오차가, 영상 탐지에는 개발 사진 밖과 실제 야간의 독립 성능이 남아 있습니다. 탈피 연구에는 같은 개체의 사진·반복 날짜 연결 자료가, 습도 제어에는 실물 작동·누수·습도 회복 시간이 부족합니다.",
      "다음 보고서 보완은 숫자를 추가하는 일이 아니라, 각 부족 항목에 맞는 원시 기록과 비교 평가를 연결하는 일입니다. 실패 사례와 미측정 결과도 함께 남겨야 이후 성능 변화를 같은 기준으로 비교할 수 있습니다."
    ],
    "sourceRefs": [
      "postR3Delta029",
      "historyBoundary029",
      "detectorDevelopment029",
      "appearancePipeline029"
    ],
    "role": "summary",
    "relatedSlides": [
      "progress-history-result",
      "progress-detection-result",
      "progress-appearance-result"
    ]
  }
] as const;
