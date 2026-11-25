# 모델

우리 학습 결과 중 작은 판별기·결합 모델 파일과 대표 평가 요약을 보관합니다.

- [`lizard-hybrid-hinge-v1/`](lizard-hybrid-hinge-v1/): 직접 학습한 `verifier.json`·`joint.json`과 파일 해시
- [대표 결과와 한계](RESULTS.md) · [집계 근거](evaluation-summary.json)
- [학습·추론 코드](../behavior-recorder/)

**완전한 추론 패키지는 아닙니다.** 대형 탐지기·특징 추출기 가중치는 제외했고,
필요한 파일의 해시는 모델 폴더의 `manifest.json`에 기록했습니다.
일치하는 구성요소를 준비한 뒤 기존 `scripts/package_hybrid_model.py`로 묶어야 합니다.
이 과거 구성요소를 최근 결합 파이프라인 전체나 운영 검증 모델로 해석하지 마세요.

전체 실험 후보·중간 체크포인트·로컬 저장공간 정리 로그는 게시하지 않습니다.
