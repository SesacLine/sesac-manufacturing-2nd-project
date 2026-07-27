/** Playwright 설정 — API를 목킹한 UI E2E 전용(실백엔드 불필요).
 *
 *  `vite preview`로 **빌드 산출물**을 띄운다(dev 서버 아님). 이유:
 *   · dev 서버는 HMR·on-demand 변환이라 첫 진입 타이밍이 들쭉날쭉해 flaky를 만든다.
 *   · 실제로 배포되는 형태(번들·minify 후)를 검증하게 된다 — tsc가 잡지 못하는 빌드 단계
 *     회귀(예: 트리셰이킹으로 사라지는 코드)까지 이 층에서 걸린다.
 *  reuseExistingServer로 로컬에서 이미 4173이 떠 있으면 재사용한다.
 */

import { defineConfig, devices } from "@playwright/test";

const PORT = 4173;

export default defineConfig({
  testDir: "./e2e",
  // 목킹이라 네트워크 대기가 없다 — 느리면 그건 사실상 버그이므로 타임아웃을 짧게 준다.
  timeout: 15_000,
  expect: { timeout: 5_000 },
  fullyParallel: true,
  // CI에서 test.only가 섞여 들어가면 나머지가 조용히 안 돌므로 실패로 만든다.
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `npm run build && npx vite preview --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
