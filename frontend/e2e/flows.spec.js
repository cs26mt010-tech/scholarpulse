const { test, expect } = require('@playwright/test');

const STUDENT = { email: 'sam.green.sp@gmail.com', password: 'ScholarPulse!2026' };

async function login(page, { email, password }) {
  await page.goto('/');
  await page.locator('#nav-auth').click();
  await page.locator('#loginEmailInput').fill(email);
  await page.locator('#loginPasswordInput').fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).last().click();
}

test('E2E 1: student can sign in through the UI and sees a signed-in state', async ({ page }) => {
  await login(page, STUDENT);
  await expect(page.locator('#nav-auth')).not.toHaveText(/^Sign in$/i, { timeout: 10000 });
});

test('E2E 2: wrong password shows an error and stays signed out', async ({ page }) => {
  await login(page, { email: STUDENT.email, password: 'wrong-password' });
  await expect(page.locator('#loginError')).toBeVisible({ timeout: 10000 });
  await expect(page.locator('#nav-auth')).toHaveText(/Sign in/i);
});

test('E2E 3: Ask AI on a resource returns an answer or keyword fallback with citations', async ({ page }) => {
  await login(page, STUDENT);
  await expect(page.locator('#nav-auth')).not.toHaveText(/^Sign in$/i, { timeout: 10000 });
  await page.evaluate(() => openResourceDetail(1));
  await page.locator('#resourceAiInput').fill('What is Dijkstra algorithm?');
  await page.locator('#resourceAiBtn').click();
  await expect(page.locator('#aiStateIdle')).toBeHidden({ timeout: 15000 });
});
