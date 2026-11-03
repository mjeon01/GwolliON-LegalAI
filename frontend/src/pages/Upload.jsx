import { useEffect, useRef, useState } from "react";
import { api, go, params, roles } from "../lib/index.js";
import useSession from "../hooks/useSession.js";
import useLoad from "../hooks/useLoad.js";
import { language, t } from "../i18n/index.js";
import { CLOUD_AI_ENABLED } from "../config/features.js";
import {
  ButtonLink,
  ErrorNotice,
  Field,
  Icon,
  PageHead,
  PrivacyNote,
  EngineSelect,
} from "../components/UI.jsx";
const blank = {
  title: "",
  text: "",
  contract_type: "employment",
  user_role: "worker",
  context: {},
  reading: null,
  document_id: null,
  engine: CLOUD_AI_ENABLED ? "openai" : "rules",
};
export default function Upload() {
  const [form, setForm] = useSession("upload", blank);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [photos, setPhotos] = useState([]);
  const [previews, setPreviews] = useState([]);
  const [readSignature, setReadSignature] = useState("");
  const photoSignature = JSON.stringify(photos.map((p) => [p.id, p.rotation]));
  const photosChanged = photos.length > 0 && photoSignature !== readSignature;
  const [readingMode, setReadingMode] = useState(
    CLOUD_AI_ENABLED ? "openai" : "local",
  );
  const [drag, setDrag] = useState(false);
  const fileInput = useRef();
  const ownedUrls = useRef(new Set());
  const { data: health } = useLoad("/api/health");
  const set = (key, value) =>
    setForm((old) => ({
      ...old,
      [key]: value,
    }));
  useEffect(
    () => () => ownedUrls.current.forEach((url) => URL.revokeObjectURL(url)),
    [],
  );
  useEffect(() => {
    const sample = params.get("sample");
    if (!sample) return;
    const controller = new AbortController();
    setBusy("샘플을 불러오는 중입니다.");
    const path = "/api/samples/" + encodeURIComponent(sample);
    Promise.all([
      api(path, { signal: controller.signal }),
      api(path + "/document", { method: "POST", signal: controller.signal }),
    ])
      .then(([data, { document_id }]) => {
        setForm({
          ...blank,
          document_id,
          title: data.title,
          text: data.text,
          contract_type: data.contract_type,
          user_role: roles[data.contract_type][0][0],
          context: data.context || {},
        });
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
  function selectFiles(list) {
    if (busy) return;
    const files = Array.from(list);
    if (fileInput.current) fileInput.current.value = "";
    if (!files.length) return;
    setError("");
    if (files.some((f) => /\.hei[cf]$/i.test(f.name)))
      return setError("HEIC 사진은 JPG로 변환한 뒤 등록해주세요.");
    if (files.some((f) => !/\.(pdf|txt|png|jpe?g|webp)$/i.test(f.name)))
      return setError("PDF, TXT, JPG, PNG, WEBP 파일을 선택해주세요.");
    if (files.some((f) => f.size > 5 * 1024 * 1024))
      return setError("파일은 장당 5MB까지 등록할 수 있습니다.");
    const documents = files.filter((f) => /\.(pdf|txt)$/i.test(f.name));
    if (documents.length) {
      if (files.length !== 1) return setError("TXT·PDF는 하나씩 등록해주세요.");
      return readFiles(
        files.map((file) => ({
          file,
          rotation: 0,
        })),
        true,
      );
    }
    if (
      files.length + photos.length > 5 ||
      files.reduce((n, f) => n + f.size, 0) +
        photos.reduce((n, p) => n + p.file.size, 0) >
        25 * 1024 * 1024
    )
      return setError("사진은 최대 5장, 전체 25MB까지 등록할 수 있습니다.");
    setPhotos((old) => [
      ...old,
      ...files.map((file) => {
        const url = URL.createObjectURL(file);
        ownedUrls.current.add(url);
        return {
          file,
          url,
          rotation: 0,
          id: crypto.randomUUID(),
        };
      }),
    ]);
    setPreviews([]);
  }
  function alter(index, action) {
    setPhotos((old) => {
      const list = [...old];
      if (action === "rotate")
        list[index] = {
          ...list[index],
          rotation: (list[index].rotation + 90) % 360,
        };
      else if (action === "delete") {
        URL.revokeObjectURL(list[index].url);
        ownedUrls.current.delete(list[index].url);
        list.splice(index, 1);
      } else {
        const next = index + action;
        if (next >= 0 && next < list.length)
          [list[index], list[next]] = [list[next], list[index]];
      }
      return list;
    });
    setPreviews([]);
  }
  async function readFiles(items = photos, isDocument = false) {
    if (!items.length || busy) return;
    setBusy("파일에서 계약서 내용을 읽고 있습니다.");
    setError("");
    try {
      const body = new FormData();
      items.forEach((p) => body.append("files", p.file));
      body.append("rotations", JSON.stringify(items.map((p) => p.rotation)));
      body.append("reading_mode", readingMode);
      const data = await api("/api/uploads", {
        method: "POST",
        body,
      });
      setForm((old) => ({
        ...old,
        text: data.text,
        title: old.title || items[0].file.name.replace(/\.[^.]+$/, ""),
        reading: data.reading,
        document_id: data.document_id,
      }));
      setPreviews(data.page_previews || []);
      setReadSignature(
        isDocument ? "" : JSON.stringify(items.map((p) => [p.id, p.rotation])),
      );
      if (isDocument) setPhotos([]);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy("");
    }
  }
  function editPage(index, changes) {
    setForm((old) => {
      const pages = old.reading.pages.map((p, i) =>
        i === index
          ? {
              ...p,
              ...changes,
            }
          : p,
      );
      return {
        ...old,
        text: pages.map((p) => p.text).join("\f"),
        reading: {
          ...old.reading,
          pages,
        },
      };
    });
  }
  const pages = form.reading?.pages || [];
  const unconfirmed = pages.some(
    (p) =>
      !p.confirmed ||
      p.status === "failed" ||
      !p.text.trim() ||
      p.text.includes("[판독 불가]"),
  );
  async function submit(e) {
    e.preventDefault();
    setError("");
    if (photosChanged)
      return setError("사진이 변경되었습니다. 현재 순서로 다시 읽어주세요.");
    if (unconfirmed)
      return setError("모든 페이지를 원본과 대조하고 확인 표시를 해주세요.");
    if (form.text.trim().length < 20)
      return setError("검토할 계약서 내용을 20자 이상 입력해주세요.");
    if (form.text.length > 50000)
      return setError("읽은 텍스트는 50,000자까지 지원합니다.");
    setBusy("검토를 시작하고 있습니다.");
    try {
      const result = await api("/api/analyses", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          ...form,
          title: form.title.trim() || "내 계약서",
          engine: CLOUD_AI_ENABLED ? form.engine || "openai" : "rules",
          language: CLOUD_AI_ENABLED ? language() : "ko",
          evidence_mode: "local",
        }),
      });
      // Preserve input for retry if the background review fails.
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
        title={t("어떤 계약서를 살펴볼까요?")}
        description={t(
          "계약서를 등록하고, 내용을 확인한 뒤 검토를 시작하세요.",
        )}
        action={
          <ButtonLink to="/samples/" icon="file">
            {t("샘플 계약서")}
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
              <h2>{t("계약서 등록")}</h2>
              <span className="small muted">{t("사진 5장 · 장당 5MB")}</span>
            </div>
            {CLOUD_AI_ENABLED && (
              <Field label={t("사진·스캔 읽기 방식")}>
                <select
                  value={readingMode}
                  onChange={(e) => setReadingMode(e.target.value)}
                >
                  <option value="openai">{t("OpenAI 사진 판독")}</option>
                  <option value="local">{t("로컬 OCR")}</option>
                </select>
              </Field>
            )}
            {readingMode === "openai" && <PrivacyNote />}
            {CLOUD_AI_ENABLED && health && !health.openai_configured && (
              <div className="notice">
                {t(
                  "OpenAI 키가 아직 없습니다. 서버 .env에 OPENAI_API_KEY를 설정하거나 로컬 방식을 선택해주세요.",
                )}
              </div>
            )}
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
                selectFiles(e.dataTransfer.files);
              }}
            >
              <Icon name="upload" />
              <h3>{t("계약서 파일을 여기에 놓아주세요")}</h3>
              <p>PDF · TXT · JPG · PNG · WEBP</p>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => fileInput.current.click()}
              >
                {t("파일 선택하기")}
              </button>
              <input
                ref={fileInput}
                type="file"
                multiple
                accept=".pdf,.txt,.jpg,.jpeg,.png,.webp,.heic,.heif"
                className="visually-hidden"
                aria-label={t("계약서 파일")}
                onChange={(e) => selectFiles(e.target.files)}
              />
            </div>
            {!!photos.length && (
              <>
                <ol className="photo-list">
                  {photos.map((p, i) => (
                    <li key={p.id} className="photo-card">
                      <div className="photo-frame">
                        <img
                          src={p.url}
                          alt={t("사진 {0}: {1}")
                            .replace("{0}", i + 1)
                            .replace("{1}", p.file.name)}
                          className={`rotate-${p.rotation}`}
                        />
                      </div>
                      <p>
                        {t(i + 1)}. {t(p.file.name)}
                      </p>
                      <div className="photo-actions">
                        <button
                          type="button"
                          onClick={() => alter(i, "rotate")}
                        >
                          {t("회전")}
                        </button>
                        <button
                          type="button"
                          disabled={!i}
                          onClick={() => alter(i, -1)}
                          aria-label={t("앞으로 이동")}
                        >
                          ←
                        </button>
                        <button
                          type="button"
                          disabled={i === photos.length - 1}
                          onClick={() => alter(i, 1)}
                          aria-label={t("뒤로 이동")}
                        >
                          →
                        </button>
                        <button
                          type="button"
                          onClick={() => alter(i, "delete")}
                        >
                          {t("삭제")}
                        </button>
                      </div>
                    </li>
                  ))}
                </ol>
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => readFiles()}
                >
                  {t("이 순서로 사진 읽기")}
                  <Icon />
                </button>
                <p className="small muted">
                  {t(
                    "사진을 변경한 뒤 다시 읽기를 누르면 새 원문으로 바뀝니다.",
                  )}
                </p>
              </>
            )}
            <Field label={t("계약서 이름")}>
              <input
                maxLength={120}
                placeholder={t("예: 2026년 근로계약서")}
                value={form.title}
                onChange={(e) => set("title", e.target.value)}
              />
            </Field>
            <div className="form-grid">
              <Field label={t("계약 종류")}>
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
                  <option value="employment">{t("근로계약")}</option>
                  <option value="lease">{t("주택 임대차계약")}</option>
                  <option value="sale">{t("매매계약")}</option>
                </select>
              </Field>
              <Field label={t("계약에서 내 입장")}>
                <select
                  value={form.user_role}
                  onChange={(e) => set("user_role", e.target.value)}
                >
                  {roles[form.contract_type].map(([v, l]) => (
                    <option key={v} value={v}>
                      {t(l)}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <div className="section-heading second-section">
              <span className="section-number">02</span>
              <h2>{t("읽은 내용 확인")}</h2>
            </div>
            {t(
              form.reading?.warnings?.map((w, i) => (
                <div className="notice" key={i}>
                  {t(w)}
                </div>
              )),
            )}
            {t(
              !!pages.length ? (
                pages.map((p, i) => (
                  <section className="reading-page" key={p.page}>
                    <h3>
                      {t("페이지")}
                      {p.page} ·{" "}
                      {{
                        text: "텍스트 읽기",
                        pdf_text: "PDF 텍스트",
                        ocr: "로컬 OCR",
                        openai_vision: "사진 판독",
                        manual_text: "직접 수정",
                      }[p.method] || p.method}
                    </h3>
                    <div className="page-comparison">
                      {previews.find((v) => v.page === p.page) && (
                        <img
                          src={previews.find((v) => v.page === p.page).url}
                          alt={t("판독에 사용한 사진")}
                        />
                      )}
                      <Field label={t("한국어 원문 확인·수정")}>
                        <textarea
                          rows={10}
                          value={p.text}
                          maxLength={50000}
                          onChange={(e) =>
                            editPage(i, {
                              text: e.target.value,
                              confirmed: false,
                              status: "needs_review",
                            })
                          }
                        />
                      </Field>
                    </div>
                    {p.warnings.map((w, j) => (
                      <p className="notice" key={j}>
                        {t(w)}
                      </p>
                    ))}
                    {p.status === "failed" && (
                      <p role="alert">
                        {t(
                          "이 페이지를 읽지 못했습니다. 다시 읽거나 원문을 직접 입력해주세요.",
                        )}
                      </p>
                    )}
                    <label className="check-label">
                      <input
                        type="checkbox"
                        checked={p.confirmed}
                        disabled={
                          !p.text.trim() ||
                          p.status === "failed" ||
                          p.text.includes("[판독 불가]")
                        }
                        onChange={(e) =>
                          editPage(i, {
                            confirmed: e.target.checked,
                            status: "ok",
                          })
                        }
                      />
                      {t("원본과 대조해 금액·날짜·누락을 확인했습니다.")}
                    </label>
                  </section>
                ))
              ) : (
                <Field
                  label={t("계약서 내용")}
                  hint={t(
                    CLOUD_AI_ENABLED
                      ? "한국어 계약서 원문을 입력하세요. 질문과 사건 경위는 한국어·중국어·스페인어를 지원합니다."
                      : "한국어 계약서 원문을 입력하세요.",
                  )}
                >
                  <textarea
                    className="contract-input"
                    rows={12}
                    required
                    minLength={20}
                    maxLength={50000}
                    value={form.text}
                    placeholder={t("이곳에 계약서 내용을 붙여넣으세요.")}
                    onChange={(e) => set("text", e.target.value)}
                  />
                </Field>
              ),
            )}
            <div className="input-meta">
              <span>{t(form.text.length.toLocaleString())} / 50,000</span>
              <span>{t("원문을 수정하면 수정한 내용으로 검토합니다.")}</span>
            </div>
            <Field label={t("전체 페이지와 별첨을 포함했나요?")}>
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
                <option value="">{t("아직 확인하지 못했어요")}</option>
                <option value="true">{t("네, 모두 포함했어요")}</option>
                <option value="false">{t("일부만 포함했어요")}</option>
              </select>
            </Field>
            <EngineSelect
              value={form.engine || "openai"}
              onChange={(value) => set("engine", value)}
              rules
            />
          </fieldset>
          <ErrorNotice message={error} />
          {busy && (
            <p className="inline-status" role="status">
              <span className="spinner" />
              {t(busy)}
            </p>
          )}
          {(form.engine || "openai") === "openai" && <PrivacyNote />}
          <div className="form-bottom">
            <span className="small muted">
              {t("결과는 다음 페이지에서 확인합니다.")}
            </span>
            <button
              className="btn btn-primary"
              disabled={!!busy || unconfirmed || photosChanged}
              type="submit"
            >
              {t("검토 시작하기")}
              <Icon />
            </button>
          </div>
        </form>
        <aside className="sidebar-note">
          <p className="eyebrow">Before you begin</p>
          <h2>
            {t("좋은 검토는")}
            <br />
            {t("정확한 원문에서.")}
          </h2>
          <ol className="guide-list">
            <li>
              <strong>{t("내 입장을 선택하세요")}</strong>
              <p>{t("같은 조항도 당사자에 따라 부담이 달라집니다.")}</p>
            </li>
            <li>
              <strong>{t("빠진 내용을 확인하세요")}</strong>
              <p>
                {t(
                  "사진의 순서를 정하고, 읽은 내용을 원본과 나란히 확인하세요.",
                )}
              </p>
            </li>
            <li>
              <strong>{t("검토 후 다음 단계로")}</strong>
              <p>
                {t(
                  "주의할 조항을 확인하고 질문과 상담 문서로 이어갈 수 있습니다.",
                )}
              </p>
            </li>
          </ol>
          <div className="local-note">
            <Icon name="file" />
            <p>
              {t(
                "원문·검토·대화와 문서 표시용 페이지 이미지는 이 컴퓨터에 저장되며, 검토 기록을 삭제하면 함께 삭제됩니다.",
              )}
            </p>
          </div>
        </aside>
      </div>
    </>
  );
}
