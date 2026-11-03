import { useEffect, useRef, useState } from "react";
import { api, go, params, roles, useSession } from "../lib.js";
import {
  ButtonLink,
  ErrorNotice,
  Field,
  Icon,
  PageHead,
} from "../components/UI.jsx";

const blank = {
  title: "",
  text: "",
  contract_type: "employment",
  user_role: "worker",
  context: {},
  reading: null,
};
export default function Upload() {
  const [form, setForm] = useSession("upload", blank);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [fileName, setFileName] = useState("");
  const [drag, setDrag] = useState(false);
  const fileInput = useRef();
  const set = (key, value) => setForm((old) => ({ ...old, [key]: value }));
  useEffect(() => {
    const sample = params.get("sample");
    if (!sample) return;
    const controller = new AbortController();
    setBusy("샘플을 불러오는 중입니다.");
    api("/api/samples/" + encodeURIComponent(sample), {
      signal: controller.signal,
    })
      .then((data) => {
        setForm({
          ...blank,
          title: data.title,
          text: data.text,
          contract_type: data.contract_type,
          user_role: roles[data.contract_type][0][0],
          context: data.context || {},
        });
        // A refresh must retain the user's edits, rather than overwrite with the sample.
        history.replaceState(null, "", "/upload/");
      })
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setBusy("");
      });
    return () => controller.abort();
  }, []);
  async function readFile(file) {
    if (!file || busy) return;
    setError("");
    if (!/\.(pdf|txt|png|jpe?g|webp)$/i.test(file.name)) {
      setError("PDF, TXT, JPG, PNG, WEBP 파일을 선택해주세요.");
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      setError("파일은 5MB까지 등록할 수 있습니다.");
      return;
    }
    setBusy("파일에서 계약서 내용을 읽고 있습니다.");
    try {
      const body = new FormData();
      body.append("file", file);
      const data = await api("/api/uploads", { method: "POST", body });
      setForm((old) => ({
        ...old,
        text: data.text,
        title: old.title || file.name.replace(/\.[^.]+$/, ""),
        reading: data.reading,
      }));
      setFileName(file.name);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy("");
      if (fileInput.current) fileInput.current.value = "";
    }
  }
  async function submit(event) {
    event.preventDefault();
    setError("");
    if (form.text.trim().length < 20) {
      setError("검토할 계약서 내용을 20자 이상 입력해주세요.");
      return;
    }
    setBusy("검토를 시작하고 있습니다.");
    try {
      const result = await api("/api/analyses", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...form,
          title: form.title.trim() || "내 계약서",
          engine: "rules",
          evidence_mode: "local",
        }),
      });
      setForm(blank);
      go("review", result.analysis_id);
    } catch (e) {
      setError(e.message);
      setBusy("");
    }
  }
  return (
    <>
      <PageHead
        eyebrow="01 / Contract review"
        title="어떤 계약서를 살펴볼까요?"
        description="계약서를 등록하고, 내용을 확인한 뒤 검토를 시작하세요."
        action={
          <ButtonLink to="/samples/" icon="file">
            샘플 계약서
          </ButtonLink>
        }
      />
      <div className="editor-layout">
        <form
          onSubmit={submit}
          className="panel upload-panel"
          aria-busy={!!busy}
        >
          <fieldset disabled={!!busy}>
            <div className="section-heading">
              <span className="section-number">01</span>
              <h2>계약서 등록</h2>
              <span className="small muted">최대 5MB</span>
            </div>
            <div
              className={`dropzone ${drag ? "dragging" : ""}`}
              onDragOver={(e) => {
                e.preventDefault();
                setDrag(true);
              }}
              onDragLeave={() => setDrag(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDrag(false);
                readFile(e.dataTransfer.files[0]);
              }}
            >
              <Icon name="upload" />
              <h3>{fileName || "계약서 파일을 여기에 놓아주세요"}</h3>
              <p>PDF · TXT · JPG · PNG · WEBP</p>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => fileInput.current.click()}
              >
                파일 선택하기
              </button>
              <input
                ref={fileInput}
                className="visually-hidden"
                tabIndex={-1}
                aria-label="계약서 파일"
                type="file"
                accept=".pdf,.txt,.jpg,.jpeg,.png,.webp"
                onChange={(e) => readFile(e.target.files[0])}
              />
            </div>
            {form.reading?.warnings?.map((message, i) => (
              <div className="notice" key={i}>
                {message}
              </div>
            ))}
            <Field label="계약서 이름">
              <input
                maxLength={120}
                placeholder="예: 2026년 근로계약서"
                value={form.title}
                onChange={(e) => set("title", e.target.value)}
              />
            </Field>
            <div className="form-grid">
              <Field label="계약 종류">
                <select
                  value={form.contract_type}
                  onChange={(e) =>
                    setForm((old) => ({
                      ...old,
                      contract_type: e.target.value,
                      user_role: roles[e.target.value][0][0],
                      context: {},
                    }))
                  }
                >
                  <option value="employment">근로계약</option>
                  <option value="lease">주택 임대차계약</option>
                  <option value="sale">매매계약</option>
                </select>
              </Field>
              <Field label="계약에서 내 입장">
                <select
                  value={form.user_role}
                  onChange={(e) => set("user_role", e.target.value)}
                >
                  {roles[form.contract_type].map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <div className="section-heading second-section">
              <span className="section-number">02</span>
              <h2>읽은 내용 확인</h2>
            </div>
            <Field
              label="계약서 내용"
              hint="파일을 읽은 뒤 금액·날짜·누락된 페이지를 확인하세요. 직접 붙여넣어도 됩니다."
            >
              <textarea
                className="contract-input"
                rows={12}
                required
                minLength={20}
                maxLength={50000}
                value={form.text}
                placeholder="이곳에 계약서 내용을 붙여넣으세요."
                onChange={(e) =>
                  setForm((old) => ({
                    ...old,
                    text: e.target.value,
                    reading: old.reading
                      ? {
                          ...old.reading,
                          methods: [
                            ...new Set([...old.reading.methods, "manual_text"]),
                          ],
                        }
                      : {
                          methods: ["manual_text"],
                          ocr_used: false,
                          warnings: [],
                        },
                  }))
                }
              />
            </Field>
            <div className="input-meta">
              <span>{form.text.length.toLocaleString()} / 50,000자</span>
              <span>원문을 수정하면 수정한 내용으로 검토합니다.</span>
            </div>
            <Field label="전체 페이지와 별첨을 포함했나요?">
              <select
                value={
                  form.context.document_complete == null
                    ? ""
                    : String(form.context.document_complete)
                }
                onChange={(e) =>
                  set("context", {
                    ...form.context,
                    document_complete:
                      e.target.value === "" ? null : e.target.value === "true",
                  })
                }
              >
                <option value="">아직 확인하지 못했어요</option>
                <option value="true">네, 모두 포함했어요</option>
                <option value="false">일부만 포함했어요</option>
              </select>
            </Field>
          </fieldset>
          <ErrorNotice message={error} />
          {busy && (
            <p className="inline-status" role="status">
              <span className="spinner" />
              {busy}
            </p>
          )}
          <div className="form-bottom">
            <span className="small muted">
              결과는 다음 페이지에서 확인합니다.
            </span>
            <button className="btn btn-primary" disabled={!!busy} type="submit">
              검토 시작하기 <Icon />
            </button>
          </div>
        </form>
        <aside className="sidebar-note">
          <p className="eyebrow">Before you begin</p>
          <h2>
            좋은 검토는
            <br />
            정확한 원문에서.
          </h2>
          <ol className="guide-list">
            <li>
              <strong>내 입장을 선택하세요</strong>
              <p>같은 조항도 당사자에 따라 부담이 달라집니다.</p>
            </li>
            <li>
              <strong>빠진 내용을 확인하세요</strong>
              <p>
                스캔 문서는 글자가 잘못 읽힐 수 있습니다. 금액과 특약을 한 번 더
                살펴보세요.
              </p>
            </li>
            <li>
              <strong>검토 후 다음 단계로</strong>
              <p>
                주의할 조항을 확인하고 질문과 상담 문서로 이어갈 수 있습니다.
              </p>
            </li>
          </ol>
          <div className="local-note">
            <Icon name="file" />
            <p>계약서와 검토 기록은 이 컴퓨터의 로컬 서버에 저장됩니다.</p>
          </div>
        </aside>
      </div>
    </>
  );
}
