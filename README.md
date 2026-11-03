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

샘플 계약서와 기본 검토는 API 키나 로컬 모델 없이 사용할 수 있습니다. 자유 질문에는 Ollama, 스캔·사진 읽기에는 한국어 OCR이 필요합니다.

## 현재 기능

| 페이지 | 기능 |
| --- | --- |
| 메인 `/` | 검토 시작, 샘플 진입 |
| 계약서 등록 `/upload/` | TXT·PDF·이미지 읽기, 원문 수정, 계약 종류와 본인 입장 선택 |
| 샘플 `/samples/` | 가상 계약서 6종과 PDF 다운로드 |
| 검토 `/review/` | 주의 조항·이유·상황 예시, 원문과 근거 확인, 추가 사실 입력 |
| 질문 `/chat/` | 조항별 빠른 설명과 로컬 AI 자유 질문 |
| 문서 작성 `/draft/` | 상담 요청문·검토 요약·사실확인 요청문 작성, 편집, 복사, TXT 저장 |
| 기록 `/history/` | 검토 기록 검색, 이어서 작업, 삭제 |

분석 관련 페이지는 `?id=…`로 계약서를 이어받습니다. 질문·문서 페이지에 바로 들어가면 먼저 계약서를 선택합니다.

## 폴더 구조

```text
backend/             FastAPI와 계약 검토·검색·대화·문서·저장 모듈
frontend/            현재 React + Vite 화면
  src/assets/        조각상 레이어, 아이콘, 배치 데이터
  src/components/    메뉴, 공통 UI, 메인과 애니메이션
  src/pages/         검토·질문·문서 등 작업 페이지
  src/styles/        공통 디자인과 작업 화면 스타일
resources/           공개 법령 조문 색인
samples/             합성 계약서 TXT와 시나리오 명세
  pdf/               다운로드·테스트용 샘플 PDF
scripts/             데이터 점검, 법령·참고자료 색인, OCR 준비, 평가
tests/              단위·API·페이지 연결 검증
docs/                개발·구조 설명
  notes/             설계와 연구 기록
  private/           계획서 원본 (Git 제외)
data/                원본 데이터 (Git 제외)
var/                 분석 DB, 참고자료 색인, OCR 모델, 캐시 (Git 제외)
```

현재 화면의 소스는 `frontend/` 한 곳입니다. 빌드 결과인 `frontend/dist/`는 실행할 때 생성합니다.

## 선택 기능 설정

필요한 설정만 프로젝트 루트의 `.env`에 작성합니다. 기존 `.env`가 있으면 해당 파일을 사용합니다.

| 설정 | 용도 |
| --- | --- |
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

현재 화면의 기본 검토는 **규칙 + 저장된 법령**입니다. 상태는 [`/api/health`](http://127.0.0.1:8020/api/health), API 명세는 [`/docs`](http://127.0.0.1:8020/docs)에서 확인합니다.

## 개발과 검증

```bash
# 프런트엔드 개발: 백엔드가 8020에서 실행 중일 때
npm --prefix frontend run dev

# 배포 형태 빌드와 로컬 자동 검사
npm --prefix frontend run build
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -q
```

Vite 개발 주소는 http://127.0.0.1:5173 이며 `/api`를 8020으로 전달합니다. Python 테스트는 임시 DB와 모의 모델·공식 API 응답을 사용합니다. 실제 Ollama 답변과 공식 API 연결은 별도로 확인합니다.

## 데이터와 범위

계약서 원문·결과·대화는 기존 `var/mvp/analyses.sqlite3`에 저장합니다. DB 경로는 기록 보존을 위해 유지하며, `GWOLLION_DB` 환경변수로 변경할 수 있습니다. 입력 중인 내용과 문서 초안은 같은 브라우저 탭의 `sessionStorage`에 임시 보관합니다.

업로드는 5MB·20페이지·50,000자, OCR은 최대 5페이지, AI 검토·자유 질문은 문서 6,000자 범위입니다. 현재 로컬 단일 작업공간이며, 전문가 검수 전의 계약 이해·상담 준비 도구입니다.

- [화면 구조와 페이지 안내](frontend/README.md)
- [백엔드 구조·API·데이터 관리](docs/backend.md)
- [설계·연구 기록](docs/notes/README.md)
