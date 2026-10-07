import { chromium, expect, test, type TestInfo } from '@playwright/test';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import fs from 'node:fs';
import { createServer } from 'node:http';
import path from 'node:path';
import type { AddressInfo } from 'node:net';
import { fileURLToPath } from 'node:url';
import { build as viteBuild } from 'vite';
import type { MarketStructureContext } from '../src/types/analysis';

test.use({ locale: 'en-US' });

const currentDir = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(currentDir, '..');
const sourceRoot = path.join(webRoot, 'src');

const context: MarketStructureContext = {
  schemaVersion: 'market-structure-v1',
  status: 'partial',
  market: 'us',
  tradeDate: '2026-07-04',
  marketThemeContext: {
    schemaVersion: 'market-theme-v1',
    status: 'partial',
    market: 'us',
    activeThemes: [
      { name: 'Robotics', changePct: 4.2, rank: 1, source: 'concept', phase: 'accelerating' },
      { name: 'AI Compute', changePct: 3.6, rank: 2, source: 'concept', phase: 'warming' },
    ],
    leadingConcepts: [
      { name: 'Robotics', changePct: 4.2, rank: 1, source: 'concept' },
      { name: 'AI Compute', changePct: 3.6, rank: 2, source: 'concept' },
    ],
    leadingIndustries: [
      { name: 'Industrial Machinery', changePct: 2.1, rank: 2, source: 'industry' },
      { name: 'Software', changePct: 1.8, rank: 4, source: 'industry' },
    ],
    laggingThemes: [],
    themeBreadth: {
      activeCount: 2,
      leadingConceptCount: 2,
      leadingIndustryCount: 2,
      laggingCount: 0,
    },
    dataQuality: {
      status: 'partial',
      missingFields: ['industry_rankings'],
      sources: [],
      errors: [],
    },
  },
  stockMarketPosition: {
    schemaVersion: 'stock-market-position-v1',
    status: 'partial',
    stockCode: 'ISRG',
    stockName: 'Intuitive Surgical',
    market: 'us',
    primaryTheme: {
      name: 'Robotics',
      source: 'concept',
      phase: 'accelerating',
      rank: 1,
      changePct: 4.2,
    },
    relatedBoards: [
      { name: 'Robotics', type: 'Concept', source: 'concept', rank: 1, changePct: 4.2 },
      { name: 'Industrial Machinery', type: 'Industry', source: 'industry', rank: 2, changePct: 2.1 },
    ],
    stockRole: 'follower',
    themePhase: 'accelerating',
    riskTags: [
      { code: 'theme_data_partial', message: 'Market theme data is incomplete' },
      { code: 'stock_theme_evidence_partial', message: 'Stock board did not match theme rankings' },
    ],
    missingFields: ['hotspot_constituents', 'leader_stocks'],
  },
};

function toImportPath(fromDir: string, targetPath: string): string {
  const relativePath = path.relative(fromDir, targetPath).split(path.sep).join('/');
  return relativePath.startsWith('.') ? relativePath : `./${relativePath}`;
}

function writeFile(filePath: string, content: string): void {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, content);
}

async function buildRealComponentFixture(): Promise<{
  distIndexPath: string;
  entryPath: string;
}> {
  const fixtureDir = path.join(webRoot, 'test-results', 'market-structure-card-visual');
  const distDir = path.join(fixtureDir, 'dist');
  const entryPath = path.join(fixtureDir, 'MarketStructureVisualApp.tsx');
  const htmlPath = path.join(fixtureDir, 'index.html');
  const componentImport = toImportPath(
    fixtureDir,
    path.join(sourceRoot, 'components/report/MarketStructureCard.tsx'),
  );
  const cssImport = toImportPath(fixtureDir, path.join(sourceRoot, 'index.css'));
  const typeImport = toImportPath(fixtureDir, path.join(sourceRoot, 'types/analysis.ts'));

  writeFile(
    entryPath,
    `
      import React from 'react';
      import { createRoot } from 'react-dom/client';
      import '${cssImport}';
      import { MarketStructureCard } from '${componentImport}';
      import type { MarketStructureContext } from '${typeImport}';

      const context: MarketStructureContext = ${JSON.stringify(context, null, 8)};

      createRoot(document.getElementById('root')!).render(
        <React.StrictMode>
          <main className="min-h-screen bg-background p-8 text-foreground">
            <div className="mx-auto max-w-5xl" data-testid="market-structure-visual-card">
              <MarketStructureCard context={context} language="en" />
            </div>
          </main>
        </React.StrictMode>,
      );
    `,
  );
  writeFile(
    htmlPath,
    `
      <!doctype html>
      <html lang="en">
        <head>
          <meta charset="UTF-8" />
          <meta name="viewport" content="width=device-width, initial-scale=1.0" />
          <title>MarketStructureCard Real Component Visual Evidence</title>
        </head>
        <body>
          <div id="root"></div>
          <script type="module" src="/MarketStructureVisualApp.tsx"></script>
        </body>
      </html>
    `,
  );

  await viteBuild({
    root: fixtureDir,
    base: './',
    configFile: false,
    publicDir: false,
    logLevel: 'warn',
    plugins: [tailwindcss(), react()],
    define: {
      __APP_PACKAGE_VERSION__: JSON.stringify('visual-evidence'),
      __APP_BUILD_TIME__: JSON.stringify('2026-07-05T00:00:00.000Z'),
    },
    build: {
      outDir: distDir,
      emptyOutDir: true,
      sourcemap: false,
    },
  });

  return {
    distIndexPath: path.join(distDir, 'index.html'),
    entryPath,
  };
}

function isMissingPlaywrightBrowser(error: unknown): boolean {
  return error instanceof Error && error.message.includes("Executable doesn't exist");
}

function isHttpUrl(value: string): boolean {
  const lower = value.trim().toLowerCase();
  return lower.startsWith('http://') || lower.startsWith('https://');
}

async function startStaticServer(rootDir: string): Promise<{
  url: string;
  close: () => Promise<void>;
}> {
  const server = createServer((request, response) => {
    const requestPath = decodeURIComponent((request.url || '/').split('?', 1)[0]);
    const relativePath = requestPath === '/' ? 'index.html' : requestPath.replace(/^\/+/, '');
    const filePath = path.resolve(rootDir, relativePath);
    const relativeToRoot = path.relative(rootDir, filePath);
    if (relativeToRoot.startsWith('..') || path.isAbsolute(relativeToRoot)) {
      response.writeHead(403).end('Forbidden');
      return;
    }

    fs.readFile(filePath, (error, content) => {
      if (error) {
        response.writeHead(error.code === 'ENOENT' ? 404 : 500).end('Not found');
        return;
      }
      const contentTypes: Record<string, string> = {
        '.css': 'text/css; charset=utf-8',
        '.html': 'text/html; charset=utf-8',
        '.js': 'text/javascript; charset=utf-8',
      };
      response.writeHead(200, {
        'Content-Type': contentTypes[path.extname(filePath)] || 'application/octet-stream',
      });
      response.end(content);
    });
  });

  await new Promise<void>((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const address = server.address() as AddressInfo;
  return {
    url: `http://127.0.0.1:${address.port}/`,
    close: () => new Promise<void>((resolve, reject) => {
      server.close((error) => (error ? reject(error) : resolve()));
    }),
  };
}

async function renderMarketStructureCard(distIndexPath: string, testInfo: TestInfo): Promise<void> {
  let browser: { close: () => Promise<void> } | null = null;
  try {
    browser = await chromium.launch();
  } catch (error) {
    if (!isMissingPlaywrightBrowser(error)) {
      throw error;
    }
    test.skip(
      true,
      'Playwright Chromium is not installed in this environment; skip visual smoke check.',
    );
    return;
  }

  const staticServer = await startStaticServer(path.dirname(distIndexPath));
  try {
    const page = await browser.newPage({
      locale: 'en-US',
      viewport: { width: 1280, height: 900 },
    });
    await page.goto(staticServer.url, { waitUntil: 'networkidle' });
    const card = page.getByTestId('market-structure-visual-card');
    await expect(card).toBeVisible();
    await expect(card.getByRole('region', { name: 'Themes and Stock Position' })).toBeVisible();
    await expect(card.getByText('Market Theme Layer')).toBeVisible();
    await expect(card.getByText('Stock Position Layer')).toBeVisible();
    await expect(card.getByText(/Robotics \+4\.20%/).first()).toBeVisible();

    const screenshotPath = testInfo.outputPath('market-structure-card-visual.png');
    const screenshot = await card.screenshot({ path: screenshotPath });
    expect(screenshot).toBeTruthy();
    expect(screenshot.length).toBeGreaterThan(1024);
    const githubServer = process.env.GITHUB_SERVER_URL || 'https://github.com';
    const githubRepository = process.env.GITHUB_REPOSITORY;
    const githubRunId = process.env.GITHUB_RUN_ID;
    const artifactName = 'market-structure-card-visual';
    const artifactRunHint = githubRepository && githubRunId
      ? `${githubServer}/${githubRepository}/actions/runs/${githubRunId}`
      : 'Unavailable (not running in GitHub Actions)';
    const artifactDownloadHint = githubRunId
      ? `gh run download ${githubRunId} --name ${artifactName} --dir ./.market-structure-card-visual`
      : '';
    const reproductionCommand = 'cd apps/dsa-web && npx playwright test e2e/market-structure-card-visual.spec.ts';
    const artifactHint = `${artifactRunHint}/artifacts`;
    const artifactPageHint = githubRepository && githubRunId
      ? `${githubServer}/${githubRepository}/actions/runs/${githubRunId}/jobs`
      : '';
    const externalEvidenceDir = process.env.DSA_WEB_VISUAL_EVIDENCE
      ? path.resolve(process.env.DSA_WEB_VISUAL_EVIDENCE)
      : '';
    const externalEvidenceUrl = process.env.DSA_WEB_VISUAL_EVIDENCE && isHttpUrl(process.env.DSA_WEB_VISUAL_EVIDENCE)
      ? process.env.DSA_WEB_VISUAL_EVIDENCE
      : '';
    const artifactManifestPath = testInfo.outputPath('market-structure-card-visual-artifact.txt');
    const evidenceNotes = [
      'MarketStructureCard visual evidence attached',
      `Screenshot attachment: market-structure-card-visual.png`,
      `Playwright attachment name (artifact evidence): ${artifactName}`,
      `Repro command: ${reproductionCommand}`,
    ];
    if (artifactDownloadHint) {
      evidenceNotes.push(`If running in GitHub Actions, download artifacts by command: ${artifactDownloadHint}`);
    }
    if (externalEvidenceUrl) {
      evidenceNotes.push(`External visual evidence URL: ${externalEvidenceUrl}`);
    }
    if (externalEvidenceDir && !externalEvidenceUrl) {
      try {
        fs.mkdirSync(externalEvidenceDir, { recursive: true });
        const externalScreenshot = path.join(externalEvidenceDir, 'market-structure-card-visual.png');
        fs.copyFileSync(screenshotPath, externalScreenshot);
        evidenceNotes.push(`Local shareable evidence copy: ${externalScreenshot}`);
      } catch (copyError) {
        testInfo.annotations.push({
          type: 'warning',
          description: `External visual evidence copy failed: ${String(copyError)}`,
        });
      }
    }
    if (githubRepository && githubRunId) {
      evidenceNotes.push(
        `GitHub Actions run: ${artifactRunHint}`,
        `GitHub Actions artifacts page: ${artifactHint}`,
        `GitHub Actions jobs page: ${artifactPageHint}`,
        `Download command: ${artifactDownloadHint}`,
        `Evidence attachment name: ${artifactName} (attach the screenshots directly, or link the run's artifact download, in the PR description or a comment)`,
      );
    } else {
      evidenceNotes.push(
        'Not running in GitHub Actions, so there is no public artifact link; add a reproducible screenshot and the scenario that produced it.',
        'Reproducible evidence path (local): ' + testInfo.outputPath('market-structure-card-visual.png'),
        `Repro command: ${reproductionCommand}`,
      );
    }
    evidenceNotes.push(
      `For externally traceable review, rerun this test in an environment with PR permissions, download the ${artifactName} attachment from the Actions page, and add the download link to the PR.`,
    );
    writeFile(
      artifactManifestPath,
      evidenceNotes.join('\n'),
    );

    testInfo.annotations.push({
      type: 'info',
      description:
        `Market structure card visual evidence attached in Playwright artifacts. `
        + `Attachment: ${artifactName}. `
        + (githubRepository && githubRunId
          ? `Attach the file from ${artifactHint} to the PR description or a comment.`
          : 'Not running in GitHub Actions; add the screenshot attachment or an accessible link to the PR description or a comment.'),
    });
    await testInfo.attach('market-structure-card-visual', {
      path: screenshotPath,
      contentType: 'image/png',
    });
    await testInfo.attach('market-structure-card-visual-evidence', {
      path: artifactManifestPath,
      contentType: 'text/plain',
    });
    await testInfo.attach('market-structure-card-visual-bytes', {
      body: screenshot,
      contentType: 'image/png',
    });
  } finally {
    if (browser) {
      await browser.close();
    }
    await staticServer.close();
  }
}

test.describe('MarketStructureCard visual smoke', () => {
  test('renders MarketStructureCard with expected sections', async ({ baseURL: _baseURL }, testInfo) => {
    void _baseURL;
    const { distIndexPath } = await buildRealComponentFixture();
    expect(fs.existsSync(distIndexPath)).toBe(true);
    await renderMarketStructureCard(distIndexPath, testInfo);
  });
});
