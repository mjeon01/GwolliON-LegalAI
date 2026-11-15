---
title: GwolliON Clause Model
sdk: gradio
sdk_version: 6.32.0
python_version: "3.12"
app_file: app.py
pinned: false
---

# 권리ON 조항 유형 분류 서버

`scripts/ml/build_space.py`가 만든 폴더입니다. 직접 고치지 말고 저장소의 `model_server/`를 고친 뒤 다시 만드세요.

- `GET /health` — 모델 이름·라벨 수
- `POST /classify` (헤더 `X-Api-Key`) — `{"rows": [{"text": "...", "title": "..."}]}` → `{"model": "v2", "labels": [[...]]}`

Space에는 코드만 있습니다. AI Hub 데이터로 학습한 가중치는 **비공개 모델 저장소**에 두고 시작할 때 내려받습니다.

| Space 설정 | 종류 | 값 |
| --- | --- | --- |
| `MODEL_REPO` | Variable | 비공개 모델 저장소 (예: `Mun2/gwollion-clause-model`) |
| `HF_TOKEN` | Secret | 그 저장소만 읽는 토큰 |
| `API_KEY` | Secret | 앱의 `GWOLLION_CLAUSE_MODEL_KEY`와 같은 임의 문자열 |
| `DEMO_PAGE` | Variable | `1`이면 테스트 화면 (키 없이 쓰이므로 공개 Space에서는 끔) |
