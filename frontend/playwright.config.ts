import { defineConfig } from "@playwright/test";

// Stub config — no critical-flow specs exist yet (docs/TESTING.md: E2E lands
// once there's a real flow, e.g. upload -> evidence -> claim inspection).
export default defineConfig({
  testDir: "./e2e",
  webServer: {
    command: "npm run dev",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
  },
  use: {
    baseURL: "http://localhost:3000",
  },
});
