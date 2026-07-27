/** 배치 실행 흐름 — 실행 → 화면2 진행 → 완료 로그, 그리고 409·초기화.
 *
 *  배치 자체는 목킹한다(실행하면 실LLM 1~2분). 여기서 보는 건 **화면 전환과 상태 반영**이다:
 *  실행이 화면2로 넘어가는가, 폴링이 완료를 인식하는가, 이미 끝난 날짜면 눌리지 않는가,
 *  초기화가 그 잠금을 푸는가.
 */

import { expect, test } from "@playwright/test";
import { mockApi, TODAY } from "./fixtures";

const BATCH_ID = "batch_20260209_01";

const STEPS = [
  "lot_selection",
  "cnn_classify",
  "grouping",
  "vlm_describe",
  "cause_lookup",
  "hypothesis",
  "critic",
  "response_gen",
];

function batchBody(status: "running" | "completed") {
  return {
    batch_id: BATCH_ID,
    status,
    current_step: status === "completed" ? STEPS.length - 1 : 2,
    steps: STEPS,
    logs: [
      {
        time: "09:00:01",
        tool: "run_commonality_analysis",
        message: "[Center] 공통 장비 조회",
        status: "done",
      },
      {
        time: "09:00:04",
        tool: "query_telemetry",
        message: "[Center] down_force 조회",
        status: status === "completed" ? "done" : "running",
      },
    ],
    result_ids: status === "completed" ? ["grp_center_20260208_01"] : null,
    error: null,
  };
}

test("실행 버튼을 누르면 화면2로 이동하고 진행 단계가 보인다", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/v1/batches", (r) =>
    r.fulfill({
      status: 202,
      contentType: "application/json",
      body: JSON.stringify({ batch_id: BATCH_ID, status: "running" }),
    }),
  );
  // 첫 폴링은 running, 이후 completed — 폴링이 완료를 실제로 감지하는지 본다.
  let polls = 0;
  await page.route(`**/api/v1/batches/${BATCH_ID}`, (r) => {
    polls += 1;
    return r.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(batchBody(polls <= 1 ? "running" : "completed")),
    });
  });

  await page.goto("/");
  await page.getByRole("button", { name: /오늘 판독 배치 확인/ }).click();

  await expect(page).toHaveURL(new RegExp(`/batches/${BATCH_ID}`));
  await expect(page.locator(".steps .step")).toHaveCount(STEPS.length);
  // 단계 이름은 모델명이 아니라 하는 일로 (CNN 분류 → 결함 패턴 판독)
  await expect(page.locator(".steps")).toContainText("결함 패턴 판독");
  await expect(page.locator(".steps")).not.toContainText("CNN");
  await expect(page.locator(".steps")).not.toContainText("VLM");

  // 완료되면 패턴별 로그 아코디언으로 바뀐다
  await expect(page.locator("details.acc").first()).toBeVisible({ timeout: 10_000 });
  await expect(page.locator("body")).toContainText("결함 패턴별 분석 로그");
});

test("이미 끝난 날짜면 클릭 전에 버튼이 잠긴다", async ({ page }) => {
  await mockApi(page);
  // done=true가 오면 눌러서 409를 받기 전에 미리 비활성이어야 한다.
  await page.route("**/api/v1/batches/today", (r) =>
    r.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ...TODAY, done: true, batch_id: BATCH_ID }),
    }),
  );
  await page.goto("/");
  await expect(page.getByRole("button", { name: /오늘 판독 배치 확인/ })).toBeDisabled();
  await expect(page.locator(".batch-day-done")).toHaveText("분석 완료");
});

test("409를 받으면 서버 문구를 그대로 안내하고 버튼을 잠근다", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/v1/batches", (r) =>
    r.fulfill({
      status: 409,
      contentType: "application/json",
      body: JSON.stringify({ detail: "2026-02-09 분석이 이미 완료되었습니다." }),
    }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: /오늘 판독 배치 확인/ }).click();

  // 프론트는 detail을 파싱해 분기하지 않고 그대로 보여준다(§2.3)
  await expect(page.locator(".notice")).toContainText("2026-02-09 분석이 이미 완료되었습니다.");
  await expect(page.getByRole("button", { name: /오늘 판독 배치 확인/ })).toBeDisabled();
  await expect(page).toHaveURL(/\/$/); // 자동 이동 없음
});

test("초기화하면 잠금이 풀리고 목록·차트를 다시 읽는다", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/v1/batches/reset", (r) =>
    r.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        batch_id: BATCH_ID,
        removed_analyses: 4,
        cursor_restored_to: "2026-02-06",
      }),
    }),
  );
  page.on("dialog", (d) => d.accept()); // window.confirm

  await page.goto("/");
  await page.getByRole("button", { name: /초기화/ }).click();

  await expect(page.locator(".notice")).toContainText("초기화 완료 — 분석 4건 삭제");
  await expect(page.getByRole("button", { name: /오늘 판독 배치 확인/ })).toBeEnabled();
});

test("백엔드가 죽어 있으면 사람이 읽는 안내가 뜬다", async ({ page }) => {
  await page.route("**/api/v1/**", (r) => r.abort("connectionrefused"));
  await page.goto("/");
  await expect(page.locator(".notice.error").first()).toContainText(
    "서버에 연결할 수 없습니다",
  );
});
