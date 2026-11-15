import { expect, test } from "@playwright/test";

const agent = "http://127.0.0.1:8023";

test("no contract: the agent records stated facts, drafts the request and asks back", async ({ page }) => {
  await page.goto(agent + "/upload/");
  await page.getByRole("link", { name: "계약서 없이 상담하기" }).first().click();
  await expect(page).toHaveURL(/\/interview\/$/);
  await page.getByRole("button", { name: "상담 시작" }).click();
  await expect(page).toHaveURL(/session=/);

  const input = page.getByLabel("직접 질문하기", { exact: true });
  await input.fill("계약서를 못 받았고 시급 9000원이에요");
  await page.getByRole("button", { name: "질문 보내기" }).click();
  await expect(page.locator(".chat-turn")).toHaveCount(1);
  await expect(page.getByText("확인한 과정 2단계")).toBeVisible();
  await expect(page.getByRole("heading", { name: "근로계약서 서면 교부 요청서" })).toBeVisible();
  await expect(page.locator(".agent-document pre")).toContainText("근로기준법 제17조");
  const facts = page.locator(".fact-list");
  await expect(facts).toContainText("9000원");
  await expect(input).toHaveValue("");

  // Answering the agent's question is one click.
  await page.locator(".agent-ask").getByRole("button", { name: "예" }).click();
  await expect(page.locator(".chat-turn")).toHaveCount(2);

  // The conversation is kept on the server; a wrong fact can be removed.
  await page.reload();
  await expect(page.locator(".chat-turn")).toHaveCount(2);
  await facts.getByRole("button", { name: "시급 지우기" }).click();
  await expect(page.getByText("아직 기록한 사실이 없습니다.")).toBeVisible();

  // Another browser has no owner token and cannot open the session.
  const stranger = await page.context().browser().newPage();
  const response = await stranger.request.get(agent + "/api/agent/sessions/" + new URL(page.url()).searchParams.get("session"));
  expect(response.status()).toBe(404);
  await stranger.close();
});
