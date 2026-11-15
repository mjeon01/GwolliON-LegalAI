# 권리ON · GwolliON LegalAI

계약서의 주의 조항을 원문·근거와 함께 확인하고, 질문과 상담 문서 작성으로 이어가는 로컬 플랫폼입니다.

**메인 → 계약서 등록 → 검토 → 질문 → 문서 작성**은 각각 별도 페이지입니다. 화면은 차콜·실버·블루, Space Grotesk·Pretendard와 전체 배경 조각상 애니메이션을 사용합니다.

## 실행

Python 3.10 이상과 Node.js 20.19 이상이 필요합니다.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
./run_app.sh
```

**http://127.0.0.1:8020** 에서 엽니다. 실행 스크립트가 프런트엔드 의존성을 준비하고 빌드한 뒤 FastAPI를 시작합니다. 다른 포트는 `GWOLLION_PORT=8021 ./run_app.sh`로 지정합니다.

현재 화면은 **Qwen2.5 7B(Ollama) + 로컬 데이터 검색 + 규칙 검토**를 사용합니다. 사진은 Tesseract로 읽고, 검토·자유 질문·계약서 및 문서 번역은 로컬 모델로 처리합니다. `GWOLLION_AI_PROVIDER=ollama`가 기본이며, 이 모드에서는 OpenAI 키가 있어도 OpenAI 요청을 차단합니다. 프런트엔드의 `CLOUD_AI_ENABLED=false`와 문서 다국어 기능은 별도로 관리합니다.

금액·날짜·역할을 고정하고 원문 인용을 검사합니다. 계약서·문서의 줄별 번역이 검증되지 않으면 해당 줄은 한국어 원문으로 남고, 챗봇 번역 실패는 재시도로 안내합니다. 질문 원문·한국어 해석·한국어 답변을 보관하며, 사건 경위의 한국어 해석과 문서 번역도 로컬 모델로 제공합니다.

## 현재 기능

| 페이지 | 기능 |
| --- | --- |
| 메인 `/` | 검토 시작, 샘플 진입 |
| 계약서 등록 `/upload/` | 사진 최대 5장 미리보기·회전·순서 변경, 페이지별 원문 확인·수정, TXT·PDF 읽기 |
| 샘플 `/samples/` | 가상 인물의 계약서 5종(근로 4·임대차 1), 3개 언어 소개, PDF·PNG 다운로드 |
| 검토 `/review/` | 실제 문서 위에 불리·불일치·확인 필요 조항을 번호와 색으로 표시, 옆에 이유·상황 예시·수정 문구 설명, 추가 사실 입력 |
| 질문 `/chat/` | 에이전트가 계약서·법령·판례·AI Hub 사례를 직접 조회해 답변, 모르는 사실은 되묻기, 말한 사실 기록. 에이전트를 쓸 수 없으면(로컬 모드) 기존 조항 설명·질문 화면 |
| 계약서 없이 상담 `/interview/` | 계약서를 받지 못했거나 현장 촬영이 어려울 때, 들은 조건을 정리하고 근로계약서 교부 요청서 작성 |
| 문서 작성 `/draft/` | 상담 요청문·계약 수정 요청서·검토 요약·사실확인 요청문, 넣을 조항 선택, 빈칸 안내, 미리보기·직접 수정, PDF 저장 |
| 기록 `/history/` | 검토 기록 검색, 이어서 작업, 삭제 |

분석 관련 페이지는 `?id=…`로 계약서를 이어받습니다. 질문·문서 페이지에 바로 들어가면 먼저 계약서를 선택합니다.

## 에이전트

질문 화면과 계약서 없는 상담은 OpenAI 도구 호출 에이전트(`backend/agent/`)가 처리합니다. `GWOLLION_AI_PROVIDER=openai`와 `OPENAI_API_KEY`가 있어야 켜지며(`/api/health`의 `agent_available`), 답변 한 번에 모델 호출이 2~10회 쓰여 `OPENAI_DAILY_LIMIT`에 그만큼 반영됩니다.

- **도구**: 계약서 조항 읽기, 학습된 조항 분류 모델, 권익구제 경로(절차·기관·기한), 법령 조문 조회(사건일 기준 버전), 판례·해석례·질의응답 검색, AI Hub 근로계약서 149건의 조항 구성 비교와 실제 문구 비교, 최저임금 계산(월 209시간 환산), 사실 기록, 교부 요청서 작성
- **검증**: 인용은 이번 답변에서 실제 조회한 원문과 글자 단위로 대조하고, 조회하지 않은 법령 조문·위법 단정·당사자 의무 뒤바뀜이 있으면 한 번 고쳐 쓰게 합니다. 그래도 남으면 답변을 숨기지 않고 경고와 함께 표시합니다.
- **사실 기록**: 사용자 메시지에 실제로 있는 문구를 인용한 사실만 저장하며, 화면에서 지울 수 있습니다.
- **세션**: 대화는 계약서별로 하나이며 추가 사실 입력으로 검토가 갱신돼도 유지됩니다.

## 조항 분류 모델 학습·평가

AI Hub 계약법률문서의 근로계약서(조항 유형 라벨)로 문장별 조항 유형 분류기를 학습합니다. 분석(AI 엔진)과 에이전트의 `classify_clauses` 도구가 `var/ml/clause/v2` 모델을 사용하며, 모델이 없으면 이 단계 없이 동작합니다(`GWOLLION_CLAUSE_MODEL=off`로 끌 수 있음).

**부스 시연(현재 방식)**: 맥에서 `sh scripts/run_model_server.sh`(MPS, API 키 필수, 키는 `var/model-server.key`)를 실행하고 `ngrok http 7860 --url=<고정 도메인>`으로 연결합니다. 앱 환경변수는 아래 3번과 같고 URL만 ngrok 주소입니다.

배포 앱은 torch와 체크포인트를 싣지 않고 모델 서버(`model_server/`, Hugging Face Space)를 호출합니다. 무료 계정은 공개 Space에서만 CPU basic을 쓸 수 있어, Space에는 코드만 두고 가중치는 비공개 모델 저장소에서 내려받습니다.

1. `python3 scripts/ml/build_space.py` → `var/space`(코드) + `var/space-model`(가중치)
2. 비공개 모델 저장소에 `var/space-model`, 공개 Gradio Space(CPU basic)에 `var/space`를 올리고 Space 설정(`MODEL_REPO`, 비밀값 `HF_TOKEN`·`API_KEY`)을 넣습니다. 자세한 표는 `model_server/README.md`.
3. 앱 환경변수: `GWOLLION_CLAUSE_MODEL_URL=https://<user>-<space>.hf.space`, `GWOLLION_CLAUSE_MODEL_KEY=<Space의 API_KEY와 같은 값>`, 선택 `GWOLLION_CLAUSE_MODEL_TIMEOUT`(기본 20초)

서버가 잠들었거나 실패하면 분석은 조항 분류 없이(규칙만으로) 계속됩니다.

```bash
.venv/bin/python scripts/ml/build_clause_dataset.py        # train/dev/test(잠금) 분할
.venv/bin/python scripts/ml/train_clause.py baseline       # 기준선: TF-IDF + 로지스틱 회귀
.venv/bin/python scripts/ml/train_clause.py v1             # 1차: klue/roberta-large
.venv/bin/python scripts/ml/train_clause.py v2             # 2차: 조 제목 문맥·가중치·임계값
.venv/bin/python scripts/ml/evaluate_clause.py             # test 비교 → docs/notes/권리ON AI 구현/11 조항 분류 모델 실험.md
.venv/bin/python scripts/ml/draft_risk_labels.py           # 위험 조항 검수용 var/ml/risk/review.csv
.venv/bin/python scripts/ml/evaluate_risk.py               # 검수 후: 규칙 vs 모델+규칙
.venv/bin/python scripts/ml/eval_agent_scenarios.py        # 시나리오 4종 실제 평가 (--dry-run: 비용 없이 점검)
```

처리 구조는 [`docs/notes/권리ON AI 구현/12 AI 처리 구조.md`](docs/notes/권리ON%20AI%20구현/12%20AI%20처리%20구조.md)에 정리했습니다.

## 접근 제어

분석과 대화 세션은 만든 브라우저만 볼 수 있습니다. 생성 시 받은 토큰을 브라우저 `localStorage`에 보관하고 `X-Gwollion-Token` 헤더(이미지는 `access` 쿼리)로 보냅니다. 서버에는 토큰의 SHA-256만 저장하며, 토큰이 없거나 다르면 404를 반환합니다. 이 기능 이전에 만든 분석은 로컬 SQLite에서만 열리고, 공유 Postgres 배포에서는 열리지 않습니다.

## 폴더 구조

```text
backend/             FastAPI와 검토·대화·문서·저장 모듈
  agent/             에이전트 루프·도구·답변 검증
  config.py          서버 환경설정 읽기
  law_client.py      공식 법령 HTTP·원문 처리 공용 함수
frontend/
  src/App.jsx        페이지 연결과 공통 구조
  src/assets/        화면용 이미지·로고·배치 데이터
  src/components/    공통 UI와 문서 표시·애니메이션
  src/pages/         검토·질문·문서 등 작업 페이지
  src/hooks/         데이터 조회·임시 저장·번역·타이핑 훅
  src/i18n/          언어 상태와 한국어·중국어·스페인어 문구
  src/lib/           API·URL·저장·다운로드·SSE 공통 함수
  src/config/        기능 활성화 설정
  src/styles/        공통 디자인과 작업 화면 스타일
  e2e/               PC·모바일 브라우저 테스트
  scripts/           프런트엔드 개발 검사 도구
resources/
  branding/          로고 원본
  fonts/             PDF용 Pretendard 글꼴과 라이선스
  law-index.json     공개 법령 조문 색인
samples/             화면에 보이는 계약서 5종 TXT·명세·PDF·PNG
scripts/             색인·OCR·샘플·로고 생성과 데이터 점검 CLI
tests/               단위·API 테스트와 브라우저용 모의 서버
  fixtures/samples/  회귀 테스트 전용 합성 계약서 10종
docs/                개발·구조 설명
  notes/             설계와 연구 기록
  private/           계획서 원본 (Git 제외)
data/                원본 데이터 (Git 제외)
var/                 분석 DB·참고자료 색인·OCR 모델·캐시 (Git 제외)
tmp/                 작업 중간 산출물 (Git 제외)
```

현재 화면의 소스는 `frontend/src/` 한 곳이며, 빌드 결과인 `frontend/dist/`는 실행할 때 생성합니다. 서버 실행 코드는 `backend/` 안의 공용 함수를 사용하고, `scripts/`는 명령행 작업의 진입점으로 둡니다.

`./run_app.sh`와 패키지·컨테이너 설정 파일은 실행 도구가 찾는 프로젝트 루트에 둡니다. `.env*`, `.vercel/`, 사용자 DB, 생성된 테스트 보고서는 Git에서 제외합니다.

화면 샘플은 `scripts/create_samples.py`, 회귀 테스트 자료는 `scripts/create_test_fixtures.py`, 화면 로고는 `scripts/create_logo_assets.py`로 다시 생성합니다. 로고 생성기는 `resources/branding/logo.png`를 읽습니다.

## 선택 기능 설정

필요한 설정만 프로젝트 루트의 `.env`에 작성합니다. 서버 프로세스 환경변수가 `.env`보다 우선합니다. 키를 프런트엔드 변수에 넣지 마세요. `.env`는 Git에서 제외됩니다.

```dotenv
GWOLLION_AI_PROVIDER=ollama
OLLAMA_MODEL=qwen2.5:7b
OLLAMA_URL=http://127.0.0.1:11434
```

설정은 요청 시 읽습니다. 유료 OpenAI 기능은 서버의 `GWOLLION_AI_PROVIDER=openai`와 API 키를 명시적으로 설정한 경우에만 사용할 수 있으며, 기본 빌드와 Vercel 배포(`Dockerfile.vercel`이 `GWOLLION_AI_PROVIDER=openai`를 설정)는 OpenAI를 요청하고, `VITE_CLOUD_AI=0`으로 빌드하면 로컬 모델을 요청합니다(브라우저 테스트가 이 방식). `/api/health`의 `openai_configured`는 키 존재 여부이며 인증 성공을 뜻하지 않습니다. 인증 오류·사용량 제한·시간 초과는 입력을 보존하고 재시도를 안내합니다.

| 설정 | 용도 |
| --- | --- |
| `GWOLLION_AI_PROVIDER` | 기본 `ollama`. `openai`를 명시해야 유료 호출 허용 |
| `OPENAI_API_KEY` | OpenAI를 명시적으로 켠 경우의 서버 전용 키 |
| `OPENAI_MODEL` | 이미지 입력·구조화 출력을 지원하는 모델. 기본 `gpt-5.4-mini` |
| `OPENAI_DAILY_LIMIT` | 하루(한국 시간) OpenAI 호출 상한. 초과하면 요청을 보내지 않음. 기본 `300` |
| `OLLAMA_URL` | 로컬 Ollama 주소. 기본 `http://127.0.0.1:11434` |
| `OLLAMA_MODEL` | 기본 `qwen2.5:7b` |
| `legal_api_key` | 국가법령정보 공동활용 OC. 공식 근거 조회 API 사용 시 필요 |

```bash
# 검토·자유 질문·번역용 로컬 모델 준비
ollama pull qwen2.5:7b
ollama serve

# macOS 한국어 OCR 준비
brew install tesseract
.venv/bin/python scripts/setup_ocr.py
```

현재 화면의 기본 검토는 **기존 규칙 + Qwen 의미 검토 + 검증된 원문·근거**입니다. API에서 `engine`을 생략한 기존 요청은 계속 규칙 검토를 사용합니다. 상태는 [`/api/health`](http://127.0.0.1:8020/api/health), API 명세는 [`/docs`](http://127.0.0.1:8020/docs)에서 확인합니다.

## 개발과 검증

```bash
# 프런트엔드 개발: 백엔드가 8020에서 실행 중일 때
npm --prefix frontend run dev

# 배포 형태 빌드와 로컬 자동 검사
npm --prefix frontend run build
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -q
npm --prefix frontend run test:i18n
npm --prefix frontend exec playwright install chromium
npm --prefix frontend run test:e2e
```

Vite 개발 주소는 http://127.0.0.1:5173 이며 `/api`를 8020으로 전달합니다. Python 테스트는 임시 DB와 모의 모델·공식 API 응답을 사용합니다. 실제 OpenAI·Ollama 응답과 공식 API 연결은 별도로 확인합니다. 브라우저 테스트는 8021의 임시 DB와 모의 로컬 OCR·모델 응답을 사용하며 클라우드 호출은 차단합니다. 1440px·375px에서 언어 선택, 사진부터 한국어 TXT 저장까지 검사합니다.

## 데이터와 범위

`data/`는 모델을 파인튜닝하는 데 사용한 것이 아니라 **검색 후 참고 원문을 모델에 제공하는 RAG**에 사용합니다. 현재 로컬 색인은 ZIP 38개, 182,424건이며 `var/corpus/manifest.json`에서 다시 확인할 수 있습니다. 재생성은 `.venv/bin/python scripts/build_reference_index.py`로 실행합니다.

- `Training` 자료만 검색하며 `Validation`과 원문 해시가 같은 자료도 제외합니다.
- 계약서의 여러 쟁점을 함께 검색하고, 자유 질문마다 한국어로 해석된 질문과 선택 조항에 맞춰 다시 검색합니다.
- 계약 양식·판결 참고자료·질의응답 등 최대 4건을 종류별로 분산 선택하고, 검색어가 모인 원문의 연속 구간을 제공합니다.
- 법령과 참고 사례의 입력 공간을 구분합니다. 사례를 실제 사용자 사건의 사실이나 법률 판단 정답으로 사용하지 않으며, 답변이 인용한 사례는 출처 제목과 검증된 인용문을 표시합니다.
- SQLite FTS5 trigram 검색 색인을 사용합니다. 기존 DB를 다시 만들지 않고 같은 색인을 사용합니다.

공개 배포에는 모델을 실행할 장비와 참고자료 색인을 별도로 준비해야 합니다. 현재 `Dockerfile.vercel`은 `data/` 및 `var/corpus/`를 포함하지 않으며, 모델도 설치하지 않습니다. 로컬 모델 사용은 유료 모델 API 호출료를 없애지만 장비·전력·호스팅 운영 비용까지 없애는 것은 아닙니다. 현재 코드 변경만으로 공개 사이트가 로컬 컴퓨터의 Qwen이나 데이터에 연결되지는 않습니다.


계약서 원문·결과·대화와 PDF·사진을 다시 그린 문서 표시용 페이지 이미지(메타데이터 제거, 긴 변 1800px)는 기존 `var/mvp/analyses.sqlite3`에 저장합니다. 업로드 파일 자체는 보관하지 않으며, 페이지 이미지는 검토 기록을 삭제할 때 함께 지워지고 검토에 연결되지 않은 것은 하루 뒤 정리합니다. DB 경로는 기록 보존을 위해 유지하며, `GWOLLION_DB` 환경변수로 변경할 수 있습니다. 입력 중인 내용과 문서 초안은 같은 브라우저 탭의 `sessionStorage`에 임시 보관합니다. 언어 선택은 `localStorage`에 저장합니다. 질문 원문·한국어 해석·답변은 revision별로 저장하고, 번역 캐시는 분석 ID·revision·언어·목적·원문 SHA-256으로 구분합니다. 한국어 편집본이 바뀌면 두 언어 저장 전에 번역 갱신이 필요합니다.

업로드는 파일당 5MB·사진 최대 5장(총 25MB), 문서 20페이지·50,000자입니다. 사진·스캔 판독은 최대 5페이지이며 TXT·텍스트 PDF는 직접 추출합니다. OpenAI 검토는 조항 단위로 전체 문서를 나누고 실패·미완료 범위를 표시합니다. 7,000자 초과 단일 조항은 줄바꿈으로 나눠야 합니다. Ollama 검토·항목 추출은 원문 블록 ID를 유지하며 최대 6,000자·35블록씩 나눕니다. 한 블록이 6,000자를 넘으면 원문 줄바꿈을 안내하며, 자유 질문은 6,000자 이내 문서 또는 선택 조항에 한정합니다. 현재 로컬 단일 작업공간이며, 전문가 검수 전의 계약 이해·상담 준비 도구입니다.

서버에서 `GWOLLION_AI_PROVIDER=openai`를 명시하고 OpenAI 기능을 요청하면 이미지·텍스트가 외부 OpenAI API로 전달됩니다. 이미지는 방향 보정·EXIF 제거 후 공개 URL 없이 전송합니다. `store:false`는 응답 저장을 끄는 설정으로, 완전한 무보관을 의미하지 않습니다. [OpenAI 데이터 정책](https://developers.openai.com/api/docs/guides/your-data)을 확인하세요. 서버 로그에는 요청별 모델·토큰 수·처리 시간·오류 종류만 남기며 키·이미지·문서 본문을 기록하지 않습니다.

사진의 판독 불가·실패 페이지는 숨기지 않습니다. 페이지별 원문을 수정하고 모든 페이지를 대조·확인해야 분석할 수 있습니다. 파일 미리보기는 메모리에만 있으므로 새로고침 후 원본 사진을 다시 선택해야 할 수 있습니다.

번역은 숫자·날짜·인용·역할을 고정하고 별도 의미 검사를 수행합니다. 검증 실패 시 번역을 저장하지 않으며 한국어 원문을 유지합니다. 이는 전문가의 법률·번역 검수를 대체하지 않습니다. API 규격은 [이미지 입력](https://developers.openai.com/api/docs/guides/images-vision?api-mode=responses), [구조화 출력](https://developers.openai.com/api/docs/guides/structured-outputs), [GPT-5.4 mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini)를 기준으로 합니다.

- [화면 구조와 페이지 안내](frontend/README.md)
- [백엔드 구조·API·데이터 관리](docs/backend.md)
- [설계·연구 기록](docs/notes/README.md)
