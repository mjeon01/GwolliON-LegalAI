import { test, expect } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";
const image = (name) =>
  path.resolve("../tests/fixtures/samples/images/" + name);
const labels = { ko: "한국어", zh: "中文", es: "Español" };
async function selectLanguage(page, lang) {
  await page.locator(".language-trigger").click();
  await page.locator(`.language-option[data-language="${lang}"]`).click();
  await expect(page.locator(".language-trigger")).toContainText(labels[lang]);
  await expect(page.locator(".language-trigger")).toHaveAttribute(
    "aria-expanded",
    "false",
  );
}
async function noOverflow(page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
  ).toBe(true);
}

test("local photos → review → question → edited TXT with multilingual UI", async ({
  page,
}, info) => {
  const crashes = [];
  const cloudRequests = [];
  const analysisRequests = [];
  page.on("request", (request) => {
    if (/translations/.test(request.url())) cloudRequests.push(request.url());
    if (
      request.method() === "POST" &&
      request.headers()["content-type"]?.includes("application/json")
    ) {
      const body = request.postDataJSON();
      if (
        !request.url().endsWith("/auto-translation") &&
        body.engine === "openai"
      )
        cloudRequests.push(request.url());
      if (request.url().endsWith("/api/analyses")) analysisRequests.push(body);
    }
  });
  page.on("pageerror", (e) => crashes.push(e.message));
  await page.addInitScript(() => {
    if (sessionStorage.getItem("veritas:upload")) return;
    sessionStorage.setItem(
      "veritas:upload",
      JSON.stringify({
        title: "",
        text: "",
        contract_type: "employment",
        user_role: "worker",
        context: {},
        reading: null,
        engine: "openai",
      }),
    );
  });
  await page.goto("/upload/");
  await page
    .getByLabel("계약서 파일")
    .setInputFiles([image("sale-risk-1.png"), image("sale-basic-1.png")]);
  await expect(page.locator(".photo-card")).toHaveCount(2);
  await page.getByRole("button", { name: "회전", exact: true }).first().click();
  await expect(page.locator(".photo-card img").first()).toHaveClass(
    "rotate-90",
  );
  await page.getByRole("button", { name: "뒤로 이동" }).first().click();
  await expect(page.locator(".photo-card").first()).toContainText(
    "sale-basic-1.png",
  );
  await page.getByRole("button", { name: "삭제", exact: true }).first().click();
  await expect(page.locator(".photo-card")).toHaveCount(1);
  await page.getByRole("button", { name: "이 순서로 사진 읽기" }).click();
  await expect(page.locator(".reading-page")).toHaveCount(1);
  await expect(
    page.getByRole("button", { name: "검토 시작하기" }),
  ).toBeDisabled();
  await page.getByLabel("계약 종류", { exact: true }).selectOption("sale");
  await page
    .getByLabel("한국어 원문 확인·수정")
    .fill(
      (await page.getByLabel("한국어 원문 확인·수정").inputValue()) +
        "\n계약 서류를 서로 확인한다.",
    );
  await page.getByRole("checkbox").check();
  await page
    .getByLabel("전체 페이지와 별첨을 포함했나요?")
    .selectOption("true");
  await noOverflow(page);
  await page.screenshot({
    path: info.outputPath("photo-confirm.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "검토 시작하기" }).click();
  await expect(page).toHaveURL(/\/review\/\?id=/);
  await expect(page.locator(".finding-card")).toHaveCount(2);
  await expect(page.locator(".doc-mark.tone-risk")).toHaveCount(2);
  const id = new URL(page.url()).searchParams.get("id");
  expect(analysisRequests[0].engine).toBe("rules");
  await selectLanguage(page, "zh");
  await expect(page.getByText(/OpenAI|OPENAI_API_KEY/)).toHaveCount(0);
  await expect(page.locator(".evidence").first()).toContainText("잔금");
  await noOverflow(page);
  await page.screenshot({
    path: info.outputPath("review-zh.png"),
    fullPage: true,
  });
  await page.goto("/chat/?id=" + id);
  await expect(page.locator(".language-trigger")).toContainText("中文");
  await page
    .getByLabel("输入问题", { exact: true })
    .fill("我应该如何确认文件的提供日期？");
  await page.getByRole("button", { name: "发送问题" }).click();
  await expect(page.locator(".chat-turn")).toHaveCount(1);
  await expect(page.locator(".streaming-turn")).toHaveCount(0);
  await expect(page.locator(".assistant-message > p")).toContainText(
    "请先书面确认",
  );
  await selectLanguage(page, "es");
  await page
    .getByLabel("Escriba su pregunta", { exact: true })
    .fill("¿Cómo puedo solicitar los documentos?");
  await page.getByRole("button", { name: "Enviar pregunta" }).click();
  await expect(page.locator(".chat-turn")).toHaveCount(2);
  await expect(page.locator(".streaming-turn")).toHaveCount(0);
  await expect(page.locator('.assistant-message > p[lang="es"]')).toHaveCount(
    2,
  );
  await expect(
    page.locator('.assistant-message > p[lang="es"]').last(),
  ).toContainText("Confirme por escrito");
  await noOverflow(page);
  await page.goto("/draft/?id=" + id);
  await page
    .getByLabel("Qué ocurrió realmente")
    .fill("상대방에게 서류 제공일을 요청했지만 아직 답변을 받지 못했습니다.");
  await expect(page.locator(".incident-translation")).toHaveCount(0);
  await page
    .getByRole("button", { name: "Crear borrador", exact: true })
    .click();
  await expect(page.locator(".document-view")).toContainText(
    "변호사 상담 요청문",
  );
  await expect(page.locator(".document-translation")).toHaveCount(0);
  await page.locator(".blank-chips button").first().click();
  await expect(page.locator("#draft-editor")).toBeFocused();
  const edited = await page.locator("#draft-editor").inputValue();
  await page.locator("#draft-editor").fill(edited + "\n확인일: 2026-11-03");
  page.once("dialog", (dialog) => dialog.accept());
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Guardar PDF" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/\.pdf$/);
  const pdf = await fs.readFile(await download.path());
  expect(pdf.subarray(0, 5).toString()).toBe("%PDF-");
  await noOverflow(page);
  await page.screenshot({
    path: info.outputPath("draft-es.png"),
    fullPage: true,
  });
  await page.reload();
  await expect(page.locator("#draft-editor")).toHaveValue(
    edited + "\n확인일: 2026-11-03",
  );
  await expect(page.getByRole("button", { name: "Guardar PDF" })).toBeEnabled();
  expect(crashes).toEqual([]);
  expect(cloudRequests).toEqual([]);
});

test("review marks the actual document and links marks to explanations", async ({
  page,
}) => {
  const crashes = [];
  page.on("pageerror", (e) => crashes.push(e.message));
  await page.goto("/upload/?sample=sale-risk");
  await expect(page.getByLabel("계약서 내용", { exact: true })).toContainText(
    "잔금",
  );
  await page.getByRole("button", { name: "검토 시작하기" }).click();
  await expect(page).toHaveURL(/\/review\/\?id=/);
  await expect(page.locator(".doc-page img")).toBeVisible();
  expect(
    await page
      .locator(".doc-page img")
      .evaluate((img) => img.complete && img.naturalWidth > 0),
  ).toBe(true);
  await expect(page.locator(".doc-page .doc-mark.tone-risk")).toHaveCount(2);
  await expect(page.locator(".doc-note.active")).toContainText("잔금");
  await page.locator(".doc-page .doc-mark").nth(1).click();
  await expect(page.locator(".doc-note.active")).toContainText("하자");
  await expect(page.locator(".doc-page .doc-mark.active")).toHaveCount(1);
  await page.locator(".doc-note-head").first().click();
  await expect(page.locator(".doc-note.active")).toContainText("잔금");
  await page.getByRole("button", { name: "다음 항목" }).click();
  await expect(page.locator(".doc-note.active")).toContainText("하자");
  await page.getByRole("button", { name: "확대", exact: true }).click();
  await expect(page.locator(".doc-zoom-value")).toHaveText("120%");
  const pageWidth = () =>
    page.locator(".doc-page").evaluate((e) => e.getBoundingClientRect().width);
  const zoomed = await pageWidth();
  const shape = () =>
    page.locator(".doc-page img").evaluate((img) => {
      const box = img.getBoundingClientRect();
      return [box.height / box.width, img.naturalHeight / img.naturalWidth];
    });
  const [shown, natural] = await shape();
  expect(Math.abs(shown - natural)).toBeLessThan(0.01);
  const paneWidth = await page
    .locator(".doc-pane")
    .evaluate((e) => e.clientWidth);
  expect(zoomed).toBeGreaterThan(paneWidth * 0.9);
  await page.getByRole("button", { name: "원래 크기로" }).click();
  expect(await pageWidth()).toBeLessThan(zoomed);
  await page.getByRole("button", { name: "읽은 텍스트" }).click();
  await expect(page.locator(".doc-text .doc-mark").first()).toContainText(
    "잔금",
  );
  await noOverflow(page);
  await selectLanguage(page, "es");
  await expect(page.locator(".translation-status")).toContainText(
    "Traducción de referencia",
  );
  await page.getByRole("button", { name: "Traducción", exact: true }).click();
  await expect(page.locator(".doc-translated .doc-line").first()).toBeVisible();
  await noOverflow(page);
  await selectLanguage(page, "ko");
  expect(crashes).toEqual([]);
});

test("language persists, samples translate and errors preserve input", async ({
  page,
}) => {
  await page.goto("/samples/");
  await selectLanguage(page, "es");
  await expect(page.locator(".sample-card")).toHaveCount(10);
  await expect(
    page.getByText("Compraventa básica", { exact: true }),
  ).toBeVisible();
  await noOverflow(page);
  await page.goto("/upload/");
  await expect(page.locator(".language-trigger")).toContainText("Español");
  await expect(page.getByText(/OpenAI|OPENAI_API_KEY/)).toHaveCount(0);
  await page
    .getByLabel("Nombre del contrato", { exact: true })
    .fill("Mi prueba");
  await page
    .getByLabel("Contenido del contrato", { exact: true })
    .fill("매도인은 잔금을 먼저 받은 뒤 소유권 이전 서류를 30일 후 제공한다.");
  await page.route("**/api/analyses", (route) =>
    route.request().method() === "POST"
      ? route.fulfill({
          status: 503,
          contentType: "application/json",
          body: JSON.stringify({
            detail: "네트워크 연결을 확인하고 다시 시도해주세요.",
          }),
        })
      : route.continue(),
  );
  await page.getByRole("button", { name: "Iniciar revisión" }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(
    page.getByLabel("Nombre del contrato", { exact: true }),
  ).toHaveValue("Mi prueba");
  await expect(
    page.getByLabel("Contenido del contrato", { exact: true }),
  ).toContainText("잔금");
  await page.reload();
  await expect(
    page.getByLabel("Nombre del contrato", { exact: true }),
  ).toHaveValue("Mi prueba");
  await page.goto("/");
  await noOverflow(page);
});

test("separate pages retain language and fit the viewport", async ({
  page,
  request,
}, info) => {
  const sample = await (await request.get("/api/samples/sale-basic")).json();
  const started = await (
    await request.post("/api/analyses", {
      data: {
        text: sample.text,
        contract_type: "sale",
        engine: "rules",
        context: sample.context,
      },
    })
  ).json();
  const id = started.analysis_id;
  await expect
    .poll(
      async () =>
        (await (await request.get("/api/analyses/" + id)).json()).status,
    )
    .toMatch(/completed|awaiting_input/);
  for (const lang of ["ko", "zh", "es"]) {
    await page.goto("/");
    await selectLanguage(page, lang);
    for (const route of [
      "",
      "samples/",
      "history/",
      "original/?id=" + id,
      "sources/?id=" + id,
      "confirm/?id=" + id,
    ]) {
      await page.goto("/" + route);
      await expect(page.locator(".language-trigger")).toContainText(
        labels[lang],
      );
      await noOverflow(page);
      await expect(page.locator(".error-notice")).toHaveCount(0);
    }
  }
  await page.goto("/");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.screenshot({
    path: info.outputPath("home-es.png"),
    fullPage: true,
  });
  await page.locator(".language-trigger").focus();
  await page.keyboard.press("ArrowDown");
  await expect(page.locator('[data-language="es"]')).toBeFocused();
  await page.keyboard.press("Home");
  await expect(page.locator('[data-language="ko"]')).toBeFocused();
  await page.screenshot({ path: info.outputPath("language-menu.png") });
  await page.keyboard.press("Escape");
  await expect(page.locator(".language-trigger")).toBeFocused();
  await expect(page.locator(".language-trigger")).toHaveAttribute(
    "aria-expanded",
    "false",
  );
});

test("streaming types progressively, preserves failed questions and recovers saved replies", async ({
  page,
  request,
}, info) => {
  const sample = await (await request.get("/api/samples/sale-risk")).json();
  const started = await (
    await request.post("/api/analyses", {
      data: {
        text: sample.text,
        contract_type: "sale",
        engine: "rules",
        context: sample.context,
      },
    })
  ).json();
  const base = "/api/analyses/" + started.analysis_id;
  await expect
    .poll(async () => (await (await request.get(base)).json()).status)
    .toMatch(/completed|awaiting_input/);
  await page.goto("/chat/?id=" + started.analysis_id);
  const input = page.getByLabel("직접 질문하기", { exact: true });
  const send = page.getByRole("button", { name: "질문 보내기" });
  await input.fill("잔금을 보내기 전에 확인할 서류는 무엇인가요?");
  await send.click();
  await expect(page.locator(".streaming-turn")).toBeVisible();
  await expect(send).toBeDisabled();
  await expect(page.locator(".streaming-text")).toContainText(/./);
  const partial = await page.locator(".streaming-text").innerText();
  await page.locator(".streaming-text").scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath("chat-typing.png") });
  await expect(page.locator(".streaming-turn")).toHaveCount(0);
  const completed = await page.locator(".assistant-message > p").innerText();
  expect(completed.length).toBeGreaterThan(partial.length);
  await expect(input).toHaveValue("");
  await noOverflow(page);

  await page.route(
    "**/chat/stream",
    (route) =>
      route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: 'event: status\ndata: {"phase":"generating"}\n\nevent: error\ndata: {"detail":"답변 수신이 중단되었습니다. 다시 시도해주세요."}\n\n',
      }),
    { times: 1 },
  );
  await input.fill("지급일을 서면으로 확인하려면 어떻게 하나요?");
  await send.click();
  await expect(page.getByRole("alert")).toContainText("중단");
  await expect(input).toHaveValue(
    "지급일을 서면으로 확인하려면 어떻게 하나요?",
  );
  await expect(page.locator(".chat-turn")).toHaveCount(1);
  await page.reload();
  await expect(input).toHaveValue(
    "지급일을 서면으로 확인하려면 어떻게 하나요?",
  );
  await page.emulateMedia({ reducedMotion: "reduce" });
  // Simulate losing the terminal event after a successful server commit.
  await page.route(
    "**/chat/stream",
    async (route) => {
      const upstream = await route.fetch();
      const text = await upstream.text();
      expect(text).toContain("event: done");
      await route.fulfill({
        response: upstream,
        body: text.split("event: done")[0],
      });
    },
    { times: 1 },
  );
  await send.click();
  await expect(page.locator(".streaming-turn")).toHaveCount(0);
  await expect(page.locator(".chat-turn")).toHaveCount(2);
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(input).toHaveValue("");
  await page.reload();
  await expect(page.locator(".chat-turn")).toHaveCount(2);
  expect(
    (await (await request.get(base + "/chat?analysis_revision=1")).json())
      .turns,
  ).toHaveLength(2);
});
