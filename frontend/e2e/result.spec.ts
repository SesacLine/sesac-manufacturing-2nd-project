/** 화면3 분석 결과 — 중복 고지 통합·원인군 렌더·인용 표기·근거 모달.
 *
 *  이 화면이 가장 회귀가 잦다: 상태 5종 × 원인군 유무 × 확신 2종 조합이 전부 다른 렌더로
 *  갈리는데, 어느 조합도 타입 검사로는 안 잡힌다.
 */

import { expect, test } from "@playwright/test";
import { ANALYSIS_REVIEWED, mockApi } from "./fixtures";

const REVIEWED = "/analyses/grp_center_20260208_01";
const NOVEL = "/analyses/grp_unknown_20260208_01";

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test("서머리 카드가 'AI 분석결과' 라벨 뒤 줄바꿈으로 서술을 보여준다", async ({ page }) => {
  await page.goto(REVIEWED);
  const box = page.locator(".headline-box");
  await expect(box.locator(".headline-label")).toHaveText("AI 분석결과");
  await expect(box).toContainText(ANALYSIS_REVIEWED.description!);
  // 라벨과 서술이 다른 줄에 있어야 한다(줄바꿈 요구)
  const labelTop = await box.locator(".headline-label").evaluate((e) => e.getBoundingClientRect().bottom);
  const boxBottom = await box.evaluate((e) => e.getBoundingClientRect().bottom);
  expect(boxBottom).toBeGreaterThan(labelTop);
});

test("불확실성 고지는 화면에 한 번만 나온다", async ({ page }) => {
  await page.goto(REVIEWED);
  // 배너는 conf-warn/conf-note 둘 중 하나만 — 둘 다 뜨면 중복이다.
  const banners = page.locator(".conf-warn, .conf-note");
  await expect(banners).toHaveCount(1);
  await expect(banners).toContainText("확정된 원인이 아닙니다");

  // 예전에 중복으로 있던 표현들이 되살아나면 실패
  const body = page.locator("body");
  await expect(body).not.toContainText("확신:");
  await expect(body).not.toContainText("하나로 좁혀지지 않음");
});

test("같은 증거를 공유하는 후보만 묶이고, 단독 후보는 껍데기 없이 렌더된다", async ({ page }) => {
  await page.goto(REVIEWED);
  // 픽스처: cluster_id 같은 채택 2건(묶음 1개) + cluster_id null 채택 1건(단독)
  const groups = page.locator(".tie-group");
  await expect(groups).toHaveCount(1);
  await expect(groups).toContainText("아래 2건은 설비 데이터상 구분되지 않습니다");
  await expect(groups.locator(".hcard")).toHaveCount(2);

  // 단독 채택 후보는 tie-group 밖에 있어야 한다
  await expect(page.locator(".tie-group .hcard")).toHaveCount(2);
});

test("판정별 3건까지만 보여주고 나머지는 '더 보기'로 펼친다", async ({ page }) => {
  await page.goto(REVIEWED);
  const rejected = ANALYSIS_REVIEWED.hypotheses.filter((h) => h.verdict === "rejected");
  expect(rejected.length).toBeGreaterThan(3); // 픽스처 전제

  const more = page.getByRole("button", { name: `더 보기 (+${rejected.length - 3}건)` });
  await expect(more).toBeVisible();

  const before = await page.locator(".hcard").count();
  await more.click();
  await expect(page.locator(".hcard")).toHaveCount(before + (rejected.length - 3));
  await expect(page.getByRole("button", { name: /접기/ })).toBeVisible();
});

test("인용이 파일 id가 아니라 문헌 이름으로 표시된다", async ({ page }) => {
  await page.goto(REVIEWED);
  const foot = page.locator(".hcard .h-foot").first();
  await expect(foot).toContainText("문헌 근거");
  await expect(foot).toContainText("Liao 외(2026)");
  // 예전 표기: "[1] paper_liao_rag"
  await expect(foot).not.toContainText("paper_liao_rag");
  await expect(foot).not.toContainText("[1]");
});

test("검증등급이 대괄호 코드가 아니라 확인 방법으로 표시된다", async ({ page }) => {
  await page.goto(REVIEWED);
  await expect(page.locator(".hcard .h-stage").first()).toContainText("센서값 자동 검증");
  await expect(page.locator("body")).not.toContainText("[자동]");
});

test("판단불가 카드는 상황과 다음 행동을 말한다", async ({ page }) => {
  await page.goto(NOVEL);
  const box = page.locator(".unable-box");
  await expect(box).toBeVisible();
  await expect(box.locator(".title")).toContainText("처음 보는 결함 형태");
  await expect(box.locator(".title")).not.toContainText("OSR");
  // hypotheses:[] 경로에서도 권장 조치는 나와야 한다(§2.5 필드 존재 계약)
  await expect(page.locator(".action-item")).toHaveCount(1);
});

test("근거 모달이 도구 이름 대신 그 섹션이 답하는 질문을 제목으로 쓴다", async ({ page }) => {
  await page.goto(REVIEWED);
  await page.getByRole("button", { name: "설비 데이터 근거 보기" }).first().click();

  const modal = page.locator(".modal");
  await expect(modal).toBeVisible();
  await expect(modal).toContainText("불량 로트가 공통으로 지난 장비");
  await expect(modal).toContainText("센서값 추이와 정상범위");
  await expect(modal).toContainText("정비·알람 이력");
  for (const leak of ["Commonality", "Telemetry", "용의 장비", "t0("]) {
    await expect(modal).not.toContainText(leak);
  }

  // available:false 섹션은 에러가 아니라 사유 문구로 렌더된다
  await expect(modal).toContainText("해당 기간에 남아 있는 데이터가 없습니다");

  await modal.getByRole("button", { name: /닫기/ }).click();
  await expect(page.locator(".modal")).toHaveCount(0);
});

test("로트를 누르면 판독 웨이퍼맵 영역이 열린다", async ({ page }) => {
  await page.route("**/api/v1/lots/*/wafers", (r) =>
    r.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        lot_id: "lot00042",
        wafer_count: 2,
        defect_count: 1,
        normal_count: 1,
        wafers: [
          { wafer_id: "1", defect_pattern: "Center", die_map_url: "/lots/lot00042/wafers/1/die-map" },
          { wafer_id: "2", defect_pattern: "Normal", die_map_url: "/lots/lot00042/wafers/2/die-map" },
        ],
      }),
    }),
  );
  await page.goto(REVIEWED);
  await page.locator(".lot-chip").first().click();
  await expect(page.locator(".wafer-depth")).toBeVisible();
  await expect(page.locator(".wf-item")).toHaveCount(2);
});

test("분석 참조 로트를 소속 로트와 분리해 보여주고, 눌러도 웨이퍼맵이 열린다", async ({ page }) => {
  // 하루 그룹은 로트가 1~2개뿐이라 ⑤가 공통 장비를 찾을 때 최근 7일 같은 패턴 로트를 참조로
  // 함께 본다(§2.5 cohort_lot_ids). 소속 로트는 처분 대상(Hold·수율영향 기준)이라 참조 로트가
  // 섞이면 중복 소속·수율영향 이중 계산이 되므로, 카드가 분리돼 있고 소속 로트 칩이
  // 오염되지 않았는지까지 확인한다.
  await page.route("**/api/v1/lots/*/wafers", (r) =>
    r.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        lot_id: "lot00031",
        wafer_count: 1,
        defect_count: 1,
        normal_count: 0,
        wafers: [
          { wafer_id: "1", defect_pattern: "Center", die_map_url: "/lots/lot00031/wafers/1/die-map" },
        ],
      }),
    }),
  );
  await page.goto(REVIEWED);

  const cohortBox = page.locator(".box", { hasText: "분석 참조 로트" });
  await expect(cohortBox).toContainText(
    `분석 참조 로트 ${ANALYSIS_REVIEWED.cohort_lot_ids.length}개`,
  );
  await expect(cohortBox).toContainText("처분 대상 아님");

  // 소속 로트 카드는 그룹 로트만 — 코호트 로트가 섞이면 실패
  const ownBox = page.locator(".box", { hasText: `소속 로트 ${ANALYSIS_REVIEWED.lot_count}개` });
  await expect(ownBox.locator(".lot-chip")).toHaveCount(ANALYSIS_REVIEWED.lot_ids.length);

  // 코호트 칩도 같은 웨이퍼맵 동작을 쓴다
  await cohortBox.locator(".lot-chip").first().click();
  await expect(page.locator(".wafer-depth")).toBeVisible();
});

test("참조 로트가 없는 그룹은 '분석 참조 로트' 카드를 아예 그리지 않는다", async ({ page }) => {
  // 후보 0건(novel/unmapped)은 ⑤가 안 돌아 코호트가 빈 배열 — 빈 카드가 남으면 안 된다.
  await page.goto(NOVEL);
  await expect(page.locator("body")).not.toContainText("분석 참조 로트");
});

test("근거 모달이 commonality 로트 수가 소속보다 큰 이유를 설명한다", async ({ page }) => {
  // 표의 total_lots(7)가 카드 소속 로트(2)보다 큰 건 참조 로트를 함께 넣었기 때문이다.
  // 설명이 없으면 "왜 7로트지?"가 되므로 §2.7 commonality 섹션에 캡션이 있어야 한다.
  await page.goto(REVIEWED);
  await page.locator(".hcard").first().getByRole("button", { name: /근거/ }).click();
  await expect(page.locator(".modal")).toContainText("분석 참조로 함께 비교했습니다");
});
