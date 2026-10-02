import { expect, test, type Page } from '@playwright/test';

const smokePassword = process.env.DSA_WEB_SMOKE_PASSWORD;

if (!smokePassword) {
  test.skip(true, 'Set DSA_WEB_SMOKE_PASSWORD to run authenticated smoke tests.');
}


async function captureSmokeScreenshot(page: Page, testInfo: { outputPath: (name: string) => string }, name: string, options: { fullPage?: boolean } = {}) {
  const path = testInfo.outputPath(`${name}.png`);
  await page.screenshot({
    path,
    fullPage: options.fullPage ?? true,
  });
  await testInfo.attach(name, {
    path,
    contentType: 'image/png',
  });
}

async function login(page: Page) {
  test.skip(!smokePassword, 'Set DSA_WEB_SMOKE_PASSWORD to run authenticated smoke tests.');

  await page.goto('/login');
  await page.waitForLoadState('domcontentloaded');

  const passwordInput = page.locator('#password');
  const submitButton = page.getByRole('button', { name: /Enter workspace|Finish setup and sign in/ });
  const homeLink = page.getByRole('link', { name: 'Home' });

  const isAlreadyAuthenticated =
    page.url().endsWith('/') ||
    await homeLink.isVisible({ timeout: 2_000 }).catch(() => false);

  if (isAlreadyAuthenticated) {
    await page.waitForLoadState('domcontentloaded');
    return;
  }

  await expect(passwordInput).toBeVisible({ timeout: 10_000 });
  await passwordInput.fill(smokePassword!);
  await expect(submitButton).toBeVisible();

  await Promise.all([
    page.waitForResponse(
      (response) => response.url().includes('/api/v1/auth/login') && response.status() === 200,
      { timeout: 15_000 }
    ),
    submitButton.click(),
  ]);

  await page.waitForURL('/', { timeout: 15_000 });
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(1000);
}

test.describe('web smoke', () => {
  test.use({ locale: 'en-US' });

  test('login page renders password form', async ({ page }, testInfo) => {
    await page.goto('/login');
    await page.waitForLoadState('domcontentloaded');

    // Check for branding
    await expect(page.getByText('DAILY STOCK').first()).toBeVisible();
    await expect(page.getByText('Analysis Engine')).toBeVisible();

    // Check for password input
    await expect(page.locator('#password')).toBeVisible();

    // Check for submit button
    await expect(page.getByRole('button', { name: /Enter workspace|Finish setup and sign in/ })).toBeVisible();

    await captureSmokeScreenshot(page, testInfo, 'smoke-login-page-en');
  });

  test('home page shows analysis entry and history panel after login', async ({ page }, testInfo) => {
    await login(page);

    const stockInput = page.getByPlaceholder('Enter a stock code or name, e.g. AAPL, Apple, HK00700');
    await expect(stockInput).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole('link', { name: 'Home' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Ask' })).toBeVisible();
    await expect(page.getByText('Analysis history')).toBeVisible();

    await stockInput.fill('600519');
    const analyzeButton = page.getByRole('button', { name: 'Analyze', exact: true });
    await expect(analyzeButton).toBeVisible();

    await captureSmokeScreenshot(page, testInfo, 'smoke-home-page-en', { fullPage: true });
  });

  test('chat page allows entering a question and starts a request', async ({ page }) => {
    await login(page);

    // Navigate to chat page by clicking the link
    await page.getByRole('link', { name: 'Ask' }).click();
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(1000);

    await expect(page.getByTestId('chat-workspace')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId('chat-session-list-scroll')).toBeVisible();
    await expect(page.getByTestId('chat-message-scroll')).toBeVisible();

    const input = page.getByPlaceholder(/analyze 600519/);
    await expect(input).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('Strategy', { exact: true })).toBeVisible();

    const prompt = 'Give me a brief analysis of 600519';
    await input.fill(prompt);
    await page.getByRole('button', { name: 'Send' }).click();

    await expect(page.locator('p').filter({ hasText: prompt }).last()).toBeVisible({ timeout: 5000 });
  });

  test('chat page uses accessible labels instead of native title attributes for key actions', async ({ page }) => {
    await login(page);

    await page.getByRole('link', { name: 'Ask' }).click();
    await page.waitForLoadState('domcontentloaded');

    const sendButton = page.getByRole('button', { name: 'Send' });
    const composer = page.getByPlaceholder(/analyze 600519/);

    await expect(page.getByTestId('chat-workspace')).toBeVisible({ timeout: 10_000 });
    await expect(sendButton).toBeVisible({ timeout: 10_000 });
    await expect(composer).toBeVisible({ timeout: 10_000 });

    await expect(sendButton).not.toHaveAttribute('title', /.+/);
    await expect(composer).not.toHaveAttribute('title', /.+/);
  });

  test('mobile shell opens navigation drawer after login', async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await login(page);

    // Try to open navigation menu
    const menuButton = page.getByRole('button', { name: /Open navigation|Navigation/i });
    if (await menuButton.isVisible({ timeout: 2000 }).catch(() => false)) {
      await menuButton.click();
    }

    // Check if navigation is visible
    await expect(page.getByRole('link', { name: 'Backtest' })).toBeVisible({ timeout: 5000 });

    await captureSmokeScreenshot(page, testInfo, 'smoke-mobile-shell-nav');
  });

  test('settings page renders title and save actions after login', async ({ page }, testInfo) => {
    await login(page);

    // Navigate to settings page by clicking the link
    await page.getByRole('link', { name: 'Settings' }).click();
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(1000);

    // Use heading role for more precise selection
    await expect(page.getByRole('heading', { name: 'System settings' })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole('button', { name: 'Reset' })).toBeVisible();
    await expect(page.getByRole('button', { name: /Save configuration/ })).toBeVisible();

    await captureSmokeScreenshot(page, testInfo, 'smoke-settings-page-en');
  });

  test('shell renders English copy without a UI language toggle', async ({ page }, testInfo) => {
    await login(page);

    // The interface is English-only: the former language toggle must not be rendered.
    await expect(page.getByRole('button', { name: 'Switch UI language' })).toHaveCount(0);
    await expect(page.getByRole('link', { name: 'Settings' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Home' })).toBeVisible();
    await captureSmokeScreenshot(page, testInfo, 'smoke-home-page-en');

    await page.reload();
    await page.waitForLoadState('domcontentloaded');

    await expect(page.getByRole('link', { name: 'Settings' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Home' })).toBeVisible();

    await page.getByRole('link', { name: 'Settings' }).click();
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(1000);

    await expect(page.getByRole('heading', { name: 'System settings' })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole('button', { name: 'Send test' })).toBeVisible();
    await expect(page.getByRole('textbox', { name: 'Title' })).toHaveValue('DSA notification test');

    await captureSmokeScreenshot(page, testInfo, 'smoke-settings-page-en');
  });

  test('backtest page renders filter controls after login', async ({ page }, testInfo) => {
    await login(page);

    // Navigate to backtest page by clicking the link
    await page.getByRole('link', { name: 'Backtest' }).click();
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(1000);

    // Check for filter controls
    const filterInput = page.getByPlaceholder('Filter by stock code (leave empty for all)');
    await expect(filterInput).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole('button', { name: 'Filter' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Run backtest' })).toBeVisible();

    await captureSmokeScreenshot(page, testInfo, 'smoke-backtest-page-en', { fullPage: true });
  });
});
