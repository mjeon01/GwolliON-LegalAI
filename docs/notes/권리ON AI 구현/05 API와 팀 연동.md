---
tags: [권리ON, API, 팀협업]
status: 검토용 제안
---

# API와 팀 연동

[[00 권리ON 전문기 구현 가이드|시작 노트]] · 이전: [[04 모델 학습과 기술 선택]] · 다음: [[06 평가와 완료 기준]]

## 1. 담당자별 전달물

| 담당자 | 전문기가 받는 것 | 전문기가 제공하는 것 | 처음 합의할 항목 |
| --- | --- | --- | --- |
| 맥슈웰 데이브 | 문서 ID, OCR 블록·좌표·품질 정보, 사용자 상황 | 분석 상태, 조건·쟁점·근거·추가 질문 JSON | OCR 스키마, 사용자 인증, 오류·작업 상태 |
| 김유나 | 마스킹된 텍스트, 원문 위치 매핑, 데이터 처리 정책 | 필요한 입력 목록, 외부 전송 필드, 로그·삭제 대상 | 마스킹 범위, 접근권한, 보관·삭제, 제공사 조건 |
| 정가은 | 스페인어 용어집·검수 결과 | 한국어 설명, 보존할 값·근거 ID, 번역 결과 | 용어 키, 번역 단위, 평가 항목 |
| 오지영 | 중국어 용어집·검수 결과 | 한국어 설명, 보존할 값·근거 ID, 번역 결과 | 문자 체계, 용어 키, 평가 항목 |
| 지도교수·전문가 | 라벨·모델·근거 검토 피드백 | 오류 유형, 모델 비교표, 시나리오 실행 결과 | 미확인 판단과 라벨의 검토 범위 |

## 2. OCR에서 AI로 넘기는 입력

아래 예시는 **백엔드가 AI 모듈에 전달하는 내부 요청**이다. 앱이 사용자 ID나 원본 파일 경로를 임의로 지정하도록 하지 않는다. 백엔드에서 소유권을 확인한 뒤 전달한다.

```json
{
  "schema_version": "1.0",
  "document_id": "doc-demo-001",
  "text_version": "masked-normalized-v1",
  "contract_type_hint": "employment",
  "analysis_as_of": "2026-10-09",
  "event_date": null,
  "blocks": [
    {
      "block_id": "B001",
      "page": 1,
      "text": "월급은 250만원으로 한다.",
      "bbox": [0.10, 0.20, 0.85, 0.25],
      "ocr_confidence": null
    }
  ],
  "user_context": {
    "weekly_work_hours": null,
    "workplace_size_category": "unknown"
  },
  "requested_languages": ["ko"]
}
```

### 입력 규칙

- `bbox`는 페이지 너비·높이로 나눈 `[x0, y0, x1, y1]` 좌표다. 원점은 좌측 상단으로 통일한다.
- 블록의 읽는 순서와 표 관계는 OCR 담당자와 합의한다. 표는 `table_id`, 행·열 정보를 선택 필드로 추가할 수 있다.
- `ocr_confidence`가 제공되지 않으면 `null`이다. OCR 엔진별 점수는 비교 가능한 공통 확률로 취급하지 않는다.
- 계약 유형 힌트와 모델 분류가 다르면 확인 상태로 처리한다.
- `analysis_as_of`는 분석 기준일, `event_date`는 사용자가 확인한 사건일이다. 법령 적용 시점은 쟁점별로 결정한다.
- 원문 위치는 `text_version`과 함께 관리한다. 비식별화·정규화 뒤 문자열 위치가 바뀌면 기존 offset을 재사용하지 않는다.
- 입력 크기·페이지 수·지원 유형의 한도는 모델·장비 샘플 테스트 뒤 확정한다.

## 3. 분석 결과 JSON

아래는 가상의 한 블록만 읽은 **부분 분석 결과 예시**다. 실제 지급일 누락 여부를 확정하는 법률 판단이 아니다.

```json
{
  "schema_version": "1.0",
  "analysis_id": "analysis-demo-001",
  "document_id": "doc-demo-001",
  "analysis_revision": 1,
  "text_version": "masked-normalized-v1",
  "status": "awaiting_input",
  "contract_type": "employment",
  "terms": [
    {
      "key": "wage",
      "value_text": "250만원",
      "normalized_value": {"amount": 2500000, "currency": "KRW", "period": "month"},
      "status": "found",
      "evidence": [{"block_id": "B001", "page": 1, "start": 0, "end": 15, "quote": "월급은 250만원으로 한다."}]
    }
  ],
  "issues": [
    {
      "issue_id": "I001",
      "issue_type": "payment_date_information",
      "status": "not_found",
      "severity": "unassessed",
      "explanation_ko": "현재 읽은 범위에서 지급일을 찾지 못했습니다. 누락된 페이지가 있는지 확인해주세요.",
      "evidence": [],
      "source_ids": [],
      "validation": {"source_checked": false, "context_complete": false}
    }
  ],
  "questions": [
    {"question_id": "Q001", "context_key": "document_complete", "text_ko": "계약서의 모든 페이지를 올렸나요?", "answer_type": "boolean"}
  ],
  "sources": [],
  "coverage": {"pages_read": [1], "document_complete": "unknown", "checked_issue_types": ["payment_date_information"]},
  "versions": {"model": "record-actual-model-id", "prompt": "extract-v1", "rules": "rules-v1", "knowledge": "kb-snapshot-id"}
}
```

법률 설명이 포함되는 실제 결과의 `sources`에는 검색된 근거의 `source_id`, `snapshot_id`, 제목, 공식 URL, 본문, 시행일·검증일을 넣는다. 위 예시는 문서 항목 확인 단계여서 근거 목록이 비어 있다.

### 검증 계층

1. **형식:** Pydantic으로 필수 필드·타입·enum을 검사한다.
2. **참조:** block ID·source ID가 해당 분석 입력과 검색 결과에 속하는지 검사한다.
3. **원문:** `block.text[start:end] == quote`를 검사한다.
4. **값:** 정규화 금액·시간·날짜가 원문과 일치하는지 검사한다.
5. **의미:** 근거의 적용 조건과 설명의 관계를 검토한다.

Pydantic은 구조·타입 검증에 사용한다. 법률 근거와 설명의 의미를 확인하는 검증은 별도다. [Pydantic 모델 문서](https://docs.pydantic.dev/latest/concepts/models/)

## 4. 제안 API

| 내부 endpoint | 목적 | 결과 |
| --- | --- | --- |
| `POST /v1/ai/analyses` | OCR 결과로 분석 작업 생성 | `202`, 분석 ID·상태 |
| `GET /v1/ai/analyses/{id}` | 상태·결과 조회 | 부분 결과 또는 완료 결과 |
| `POST /v1/ai/analyses/{id}/answers` | 질문 답변과 상황 추가 | 새 revision·재평가 상태 |
| `POST /v1/ai/analyses/{id}/drafts` | 확인된 사실로 초안 생성 | 초안·사용한 사실·부족한 필드 |
| `POST /v1/ai/analyses/{id}/translations` | 분석 revision을 기준으로 번역 | 언어별 문구·검증 상태 |
| `DELETE /v1/ai/analyses/{id}` | 분석 결과·파생 데이터 삭제 요청 | 삭제 상태 |

앱에서 호출할 공개 API는 맥슈웰 데이브가 설계한 백엔드에 둔다. 위 AI endpoint를 별도 서버로 나누지 않으면 같은 함수 계약으로 구현한다.

### 작업 상태

```text
queued → running → completed
                 → awaiting_input → running
                 → failed
queued / running / awaiting_input → cancelled
```

- `awaiting_input`에서도 확인된 조건과 부분 결과는 제공한다.
- 답변에는 `question_id`와 기준 `analysis_revision`을 포함한다. 오래된 결과에 대한 답변은 충돌을 알리고 현재 질문을 반환한다.
- 같은 요청을 반복해도 중복 모델 호출이 생기지 않도록 요청 키와 입력 해시를 기록한다.
- 재시도 중인 단계와 시도 횟수를 저장한다.
- 삭제·취소된 분석의 worker가 늦게 끝나도 결과를 다시 저장하지 않도록 최종 상태를 확인한다.
- 원본 문서 삭제는 백엔드 저장소·김유나의 삭제 정책과 함께 처리한다.

## 5. 오류 응답과 대응

| 오류 코드 | 사용자·앱에 전달할 내용 | 구현 처리 |
| --- | --- | --- |
| `OCR_UNREADABLE` | 선명한 사진 또는 누락 페이지 요청 | 문제 블록 표시, 분석 보류 |
| `UNSUPPORTED_CONTRACT` | 지원 유형과 확인 가능한 범위 | 해당 유형의 법률 판단 중단 |
| `MODEL_TIMEOUT` | 재시도 가능 여부와 현재 상태 | 단계별 제한 재시도 |
| `INVALID_MODEL_OUTPUT` | 분석 일부를 완료하지 못함 | 형식 재생성 1회 후 부분 실패 |
| `EVIDENCE_MISMATCH` | 원문 확인이 필요한 항목 | 해당 값의 확정 표시 제거 |
| `SOURCE_UNAVAILABLE` | 근거 확인을 완료하지 못함 | 근거 부족 결과와 검증 시점 |
| `CONTEXT_CONFLICT` | 서로 다른 값의 확인 필요 | 후보·출처를 보존하고 질문 |

오류는 `code`, `retryable`, `stage`, `affected_item_ids`로 전달한다. 원본 개인정보나 외부 API의 민감한 내부 응답을 그대로 노출하지 않는다.

## 6. 초기 실행 방식

1. 앱·OCR가 없어도 고정 JSON 파일로 AI 함수 흐름을 실행한다.
2. 서비스 기준 모델로 추출·검색·설명 결과를 저장한다.
3. 백엔드가 내부 함수 또는 endpoint를 연결한다.
4. 데모에서는 단일 worker로 처리하고 분석 상태를 SQLite에 저장한다.
5. 재시작 시 진행 중 작업을 실패·재시도 가능 상태로 바꾸는 복구 처리를 추가한다.
6. 동시 사용자·긴 로컬 추론 요구가 생기면 별도 worker와 작업 큐를 도입한다.

FastAPI의 `BackgroundTasks`만으로 무거운 계산과 재시작 복구를 해결했다고 가정하지 않는다. 공식 문서는 무거운 계산에 별도의 작업 처리 도구를 고려하도록 설명한다. [FastAPI 공식 문서](https://fastapi.tiangolo.com/tutorial/background-tasks/)

## 7. 팀과 먼저 확인할 체크리스트

- [ ] 계약서의 페이지·블록 ID와 원문 위치 연결 방식.
- [ ] 사용자 인증·소유권 확인과 내부 AI 호출 권한.
- [ ] 비식별화 이후에도 분석에 필요한 상황 정보의 보존 방식.
- [ ] 원문 하이라이트를 문자 범위로 할지 블록 영역으로 할지.
- [ ] 분석 revision과 번역 revision의 일치 규칙.
- [ ] 실제 사용할 중국어·스페인어 용어집 형식.
- [ ] 문서 삭제 시 원본·OCR·결과·번역·초안·캐시의 삭제 범위.
- [ ] 로그에는 단계·시간·버전·오류 코드 중심으로 남길 범위.
