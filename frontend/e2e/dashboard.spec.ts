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
