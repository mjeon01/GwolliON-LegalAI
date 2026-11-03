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

현재 화면은 API 키 없이 로컬 규칙 검토·Tesseract 사진 판독·Ollama 자유 질문을 사용합니다. OpenAI 선택·키 안내는 잠시 숨겼습니다. `frontend/src/config/features.js`의 `CLOUD_AI_ENABLED=false`로 제어하며, 서버의 OpenAI 연동과 기존 번역 데이터는 유지합니다. 화면 언어를 중국어·스페인어로 바꾸면 계약서와 검토 설명을 로컬 Ollama로 자동 번역해 원문과 함께 보여줍니다. 금액·날짜·시간·요일·주소는 모델을 거치지 않고, 숫자·당사자 역할 검사를 통과하지 못한 줄은 한국어로 남습니다. 의미 전체를 검증하지는 않는 참고 번역입니다. 챗봇은 선택한 언어로 답하며 기존 대화도 해당 언어로 전환합니다. 질문 원문과 한국어 해석, 한국어 답변은 함께 보관합니다. 사건 경위·문서는 한국어를 사용합니다.

## 현재 기능

| 페이지 | 기능 |
| --- | --- |
| 메인 `/` | 검토 시작, 샘플 진입 |
| 계약서 등록 `/upload/` | 사진 최대 5장 미리보기·회전·순서 변경, 페이지별 원문 확인·수정, TXT·PDF 읽기 |
| 샘플 `/samples/` | 가상 인물의 계약서 5종(근로 4·임대차 1), 3개 언어 소개, PDF·PNG 다운로드 |
| 검토 `/review/` | 실제 문서 위에 불리·불일치·확인 필요 조항을 번호와 색으로 표시, 옆에 이유·상황 예시·수정 문구 설명, 추가 사실 입력 |
| 질문 `/chat/` | 조항별 설명, 한국어·중국어·스페인어 질문과 한국어 해석 보관 |
| 문서 작성 `/draft/` | 상담 요청문·계약 수정 요청서·검토 요약·사실확인 요청문, 넣을 조항 선택, 빈칸 안내, 미리보기·직접 수정, PDF 저장 |
| 기록 `/history/` | 검토 기록 검색, 이어서 작업, 삭제 |

분석 관련 페이지는 `?id=…`로 계약서를 이어받습니다. 질문·문서 페이지에 바로 들어가면 먼저 계약서를 선택합니다.

## 폴더 구조

```text
backend/             FastAPI와 검토·대화·문서·저장 모듈
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
OPENAI_API_KEY=여기에_API_키
OPENAI_MODEL=gpt-5.4-mini
```

설정은 요청 시 읽으므로 키를 수정한 뒤 재시도할 수 있습니다. `/api/health`의 `openai_configured`는 키 존재 여부이며 인증 성공을 뜻하지 않습니다. 인증 오류·사용량 제한·시간 초과는 입력을 보존하고 재시도를 안내합니다.

| 설정 | 용도 |
| --- | --- |
| `OPENAI_API_KEY` | OpenAI 서버 전용 키 |
| `OPENAI_MODEL` | 이미지 입력·구조화 출력을 지원하는 모델. 기본 `gpt-5.4-mini` |
| `OPENAI_DAILY_LIMIT` | 하루(한국 시간) OpenAI 호출 상한. 초과하면 요청을 보내지 않음. 기본 `300` |
| `OLLAMA_URL` | 로컬 Ollama 주소. 기본 `http://127.0.0.1:11434` |
| `OLLAMA_MODEL` | 기본 `qwen2.5:7b` |
| `legal_api_key` | 국가법령정보 공동활용 OC. 공식 근거 조회 API 사용 시 필요 |

```bash
# 자유 질문용 모델 준비
ollama pull qwen2.5:7b
ollama serve

# macOS 한국어 OCR 준비
brew install tesseract
.venv/bin/python scripts/setup_ocr.py
```

현재 화면의 기본 검토는 **기존 규칙 + 검증된 원문·근거**입니다. API에서 `engine`을 생략한 기존 요청은 계속 규칙 검토를 사용합니다. 상태는 [`/api/health`](http://127.0.0.1:8020/api/health), API 명세는 [`/docs`](http://127.0.0.1:8020/docs)에서 확인합니다.

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

계약서 원문·결과·대화와 PDF·사진을 다시 그린 문서 표시용 페이지 이미지(메타데이터 제거, 긴 변 1800px)는 기존 `var/mvp/analyses.sqlite3`에 저장합니다. 업로드 파일 자체는 보관하지 않으며, 페이지 이미지는 검토 기록을 삭제할 때 함께 지워지고 검토에 연결되지 않은 것은 하루 뒤 정리합니다. DB 경로는 기록 보존을 위해 유지하며, `GWOLLION_DB` 환경변수로 변경할 수 있습니다. 입력 중인 내용과 문서 초안은 같은 브라우저 탭의 `sessionStorage`에 임시 보관합니다. 언어 선택은 `localStorage`에 저장합니다. 질문 원문·한국어 해석·답변은 revision별로 저장하고, 번역 캐시는 분석 ID·revision·언어·목적·원문 SHA-256으로 구분합니다. 한국어 편집본이 바뀌면 두 언어 저장 전에 번역 갱신이 필요합니다.

업로드는 파일당 5MB·사진 최대 5장(총 25MB), 문서 20페이지·50,000자입니다. 사진·스캔 판독은 최대 5페이지이며 TXT·텍스트 PDF는 직접 추출합니다. OpenAI 검토는 조항 단위로 전체 문서를 나누고 실패·미완료 범위를 표시합니다. 7,000자 초과 단일 조항은 줄바꿈으로 나눠야 합니다. 기존 Ollama의 6,000자 제한은 유지합니다. 현재 로컬 단일 작업공간이며, 전문가 검수 전의 계약 이해·상담 준비 도구입니다.

OpenAI API를 직접 호출하거나 화면의 클라우드 기능을 다시 활성화하면 이미지·텍스트가 외부 OpenAI API로 전달됩니다. 이미지는 방향 보정·EXIF 제거 후 공개 URL 없이 전송합니다. `store:false`는 응답 저장을 끄는 설정으로, 완전한 무보관을 의미하지 않습니다. [OpenAI 데이터 정책](https://developers.openai.com/api/docs/guides/your-data)을 확인하세요. 서버 로그에는 요청별 모델·토큰 수·처리 시간·오류 종류만 남기며 키·이미지·문서 본문을 기록하지 않습니다.

사진의 판독 불가·실패 페이지는 숨기지 않습니다. 페이지별 원문을 수정하고 모든 페이지를 대조·확인해야 분석할 수 있습니다. 파일 미리보기는 메모리에만 있으므로 새로고침 후 원본 사진을 다시 선택해야 할 수 있습니다.

번역은 숫자·날짜·인용·역할을 고정하고 별도 의미 검사를 수행합니다. 검증 실패 시 번역을 저장하지 않으며 한국어 원문을 유지합니다. 이는 전문가의 법률·번역 검수를 대체하지 않습니다. API 규격은 [이미지 입력](https://developers.openai.com/api/docs/guides/images-vision?api-mode=responses), [구조화 출력](https://developers.openai.com/api/docs/guides/structured-outputs), [GPT-5.4 mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini)를 기준으로 합니다.

- [화면 구조와 페이지 안내](frontend/README.md)
- [백엔드 구조·API·데이터 관리](docs/backend.md)
- [설계·연구 기록](docs/notes/README.md)
