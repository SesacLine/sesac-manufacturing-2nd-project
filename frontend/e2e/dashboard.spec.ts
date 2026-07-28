/** 화면1 대시보드 — 배치 배지·대기열·차트 범례.
 *
 *  여기서 잡고 싶은 회귀는 "타입은 맞는데 화면이 틀린" 것들이다: 상태 enum이 늘었는데
 *  라벨 맵에 없어 raw 값이 노출되거나, 배지 날짜가 서버가 아닌 벽시계를 따라가거나,
 *  내부 분류 기호(OSR·(a)(b)(c))가 다시 새어 나오는 경우.
 */

import { expect, test } from "@playwright/test";
import { ANALYSES, mockApi, TODAY } from "./fixtures";

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
});

test("배치 배지가 서버 '오늘' 날짜를 그대로 찍는다(벽시계 아님)", async ({ page }) => {
  const badge = page.locator(".batch-day");
  await expect(badge).toContainText("일 1회 배치");
  await expect(badge.locator("b")).toHaveText(TODAY.today);
  // 벽시계 연도가 새어 들어오면(예: new Date()) 이 단언이 깨진다.
  await expect(badge).not.toContainText(String(new Date().getFullYear() + 1));
});

test("이번 클릭의 대상 구간을 실행 전에 알려준다", async ({ page }) => {
  await expect(page.getByText(`대상 구간 ${TODAY.target_from}`)).toBeVisible();
});

test("대기열이 상태 5종을 사람이 읽는 말로 표시한다", async ({ page }) => {
  const rows = page.locator("table tbody tr");
  await expect(rows).toHaveCount(ANALYSES.items.length);

  // 상태 배지는 v9대로 "조치 필요 여부" 2종 + 판독상 정상
  await expect(page.locator(".status-pill.ok").first()).toHaveText("✓ 검토 완료");
  await expect(page.locator(".status-pill.na").first()).toHaveText("⚠ 판단 불가");
  await expect(page.locator(".status-pill.mute")).toHaveText("판독상 정상");

  // raw enum이 화면에 노출되면 실패 — 라벨 맵 누락 회귀 감지
  for (const raw of ["normal_reading", "insufficient", "novel", "reviewed"]) {
    await expect(page.locator("table")).not.toContainText(raw);
  }
});

test("원인 이름이 snake_case 대신 한국어 gloss로 뜨고, 원문은 tooltip에 남는다", async ({
  page,
}) => {
  const cell = page.locator("td[title='center_polishing_too_fast']");
  await expect(cell).toHaveText("중심부 연마 과다(CMP)");
});

test("내부 분류 기호가 화면에 새어 나오지 않는다", async ({ page }) => {
  const body = page.locator("body");
  // 예전 문구: "(a) 매핑 없음" / "(b) 신규 패턴·OSR" / "(c) 근거 부족·NFF"
  for (const leak of ["OSR", "NFF", "(a)", "(b)", "(c)", "Hypothesis", "Critic", "MCP"]) {
    await expect(body).not.toContainText(leak);
  }
  // 대신 상황을 말하는 문구가 있어야 한다
  await expect(body).toContainText("처음 보는 결함 형태");
});

test("추이 차트 범례가 한 줄에 들어간다(줄바꿈으로 세로가 늘지 않게)", async ({ page }) => {
  const legend = page.locator(".chart-legend");
  await expect(legend).toBeVisible();
  // 범례 3항목 + 안내 1개가 모두 같은 y축 라인에 있으면 한 줄이다.
  const boxes = await legend.locator(".lg").evaluateAll((els) =>
    els.map((e) => (e as HTMLElement).getBoundingClientRect().top),
  );
  expect(boxes.length).toBe(3);
  expect(Math.max(...boxes) - Math.min(...boxes)).toBeLessThan(4);
});

test("수율 차트는 접기 토글 없이 항상 펼쳐져 있다", async ({ page }) => {
  await expect(page.locator("details.chart-box")).toHaveCount(0);
  // .chart-box 안에는 추이·도넛·Pareto 3개의 svg가 있다 — 첫 번째(추이)만 보면 충분하다.
  await expect(page.locator(".chart-box .chart-svg").first()).toBeVisible();
});

test("대기열 행을 누르면 그 분석 상세로 간다", async ({ page }) => {
  await page.locator("table tbody tr").first().click();
  await expect(page).toHaveURL(/\/analyses\/grp_/);
});

// ── 대기열 정렬 ────────────────────────────────────────────────────────────────────────
// 예전엔 머리글이 "↓ 날짜순"으로 하드코딩돼 있었는데 실제 정렬은 수율영향순이었고, 그마저도
// 서버가 잘라 보낸 **현재 페이지 안에서만** 일어났다(= 가장 위험한 그룹이 2페이지에 숨음).

test("기본 정렬은 분석일 최신순이고, 머리글 표시가 실제 정렬과 일치한다", async ({ page }) => {
  // 픽스처는 날짜 순서와 수율영향 순서를 일부러 어긋나게 뒀다 — 기본이 날짜순이면
  // 수율영향 열은 정렬돼 보이지 않아야 한다(-1.2 / -2.1 / -3.4 / null).
  // (allInnerTexts는 자동 대기가 없어 렌더 전에 읽으면 빈 배열이다 — 먼저 행 수로 기다린다)
  await expect(page.locator("table tbody tr")).toHaveCount(ANALYSES.items.length);
  expect(await page.locator("table tbody tr td:nth-child(1)").allInnerTexts()).toEqual(
    ["2026-02-08", "2026-02-08", "2026-02-07", "2026-02-05"],
  );
  expect(await page.locator("table tbody tr td:nth-child(3)").allInnerTexts()).toEqual(
    ["-1.2%p", "-2.1%p", "-3.4%p", "—"],
  );

  await expect(page.locator(".box-title", { hasText: "분석 결과" })).toContainText("분석일순");
  await expect(page.locator("th[aria-sort='descending']")).toContainText("분석일");
});

test("수율영향 머리글을 누르면 피해 큰 순으로 바뀌고 null은 맨 뒤로 간다", async ({ page }) => {
  await page.getByRole("button", { name: /수율영향/ }).click();
  await expect(page.locator("th[aria-sort='ascending']")).toContainText("수율영향");
  expect(await page.locator("table tbody tr td:nth-child(3)").allInnerTexts()).toEqual(
    ["-3.4%p", "-2.1%p", "-1.2%p", "—"],
  );

  // 방향을 뒤집어도 null(모르는 값)은 여전히 맨 뒤 — "가장 작은 값"으로 취급하면
  // 구 저장분이 가장 위험한 그룹처럼 맨 위에 올라온다.
  await page.getByRole("button", { name: /수율영향/ }).click();
  expect(await page.locator("table tbody tr td:nth-child(3)").allInnerTexts()).toEqual(
    ["-1.2%p", "-2.1%p", "-3.4%p", "—"],
  );
});

test("소속 로트 열이 참조 로트 수를 슬래시로 함께 보여준다", async ({ page }) => {
  // 참조 로트는 처분 대상이 아니라 공통 장비 탐색에 참조만 한 로트라 합산하지 않는다.
  await expect(page.locator("thead")).toContainText("소속/참조 로트");
  expect(await page.locator("table tbody tr td:nth-child(4)").allInnerTexts()).toEqual(
    ["7개/2개", "2개/0개", "3개/1개", "5개/0개"],
  );
});

test("머리글을 누르면 그 열로 정렬되고, 다시 누르면 방향이 뒤집힌다", async ({ page }) => {
  const header = page.getByRole("button", { name: /소속\/참조 로트/ });

  // 정렬 키는 **소속 로트 수**다 — 참조 수로 줄을 세우면 "이력이 많았던 순"이 된다.
  await header.click(); // 기본 방향 = 내림차순(많은 순)
  await expect(page.locator("th[aria-sort='descending']")).toContainText("소속/참조 로트");
  expect(await page.locator("table tbody tr td:nth-child(4)").allInnerTexts()).toEqual(
    ["7개/2개", "5개/0개", "3개/1개", "2개/0개"],
  );

  await header.click(); // 같은 열 재클릭 → 방향만 반전
  await expect(page.locator("th[aria-sort='ascending']")).toContainText("소속/참조 로트");
  expect(await page.locator("table tbody tr td:nth-child(4)").allInnerTexts()).toEqual(
    ["2개/0개", "3개/1개", "5개/0개", "7개/2개"],
  );
});

test("정렬은 현재 페이지가 아니라 전체 기준이다", async ({ page }) => {
  // 12건(=PAGE_SIZE 초과) 중 **가장 위험한 행을 맨 끝**에 둔다. 페이지를 먼저 자르고
  // 정렬하면 이 행은 2페이지에 남아 1페이지 첫 행이 되지 못한다.
  const items = Array.from({ length: 12 }, (_, i) => ({
    analysis_id: `grp_center_2026020${i % 9}_${i}`,
    batch_id: "batch_20260209_01",
    analyzed_date: "2026-02-09",
    pattern: "Center",
    lot_count: 1,
    top_cause: "center_polishing_too_fast",
    status: "reviewed",
    confidence: "low",
    cohort_count: 0,
    yield_impact: i === 11 ? -9.9 : -(i % 5) - 0.1,
  }));
  await page.route("**/api/v1/analyses?**", (r) =>
    r.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ count: items.length, items }),
    }),
  );
  await page.goto("/");

  await expect(page.locator("table tbody tr")).toHaveCount(10); // PAGE_SIZE
  await page.getByRole("button", { name: /수율영향/ }).click();
  await expect(page.locator("table tbody tr td:nth-child(3)").first()).toHaveText("-9.9%p");
  await expect(page.locator(".pager")).toContainText("1 / 2");
});
