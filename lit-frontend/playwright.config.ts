import { defineConfig, devices } from '@playwright/test'

/**
 * End-to-end tests run the real app against the real backend in deterministic mode (no LLM, so no network and no cost),
 * with the real precedent library and outcome model. Ports differ from the dev servers so both can run at once.
 */
export default defineConfig({
  testDir: 'e2e',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: { baseURL: 'http://localhost:3010', trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  projects: [{ name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } }],
  webServer: [
    {
      command: 'cd ../lit-backend && OMP_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false KMP_DUPLICATE_LIB_OK=TRUE PRECEDENT_ARTIFACT_DIR=data/precedent_artifacts/v1 LLM_PROVIDER=none ALLOWED_ORIGINS="*" .venv311/bin/python -m uvicorn main:app --port 8010 --log-level warning',
      url: 'http://localhost:8010/health', reuseExistingServer: true, timeout: 120_000,
    },
    {
      command: 'VITE_API_BASE_URL=http://localhost:8010/api/v1 npx vite --port 3010 --strictPort',
      url: 'http://localhost:3010', reuseExistingServer: true, timeout: 60_000,
    },
  ],
})
