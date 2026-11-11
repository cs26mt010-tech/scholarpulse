const { test, expect } = require('@playwright/test');

test('ScholarPulse home page loads with project title', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveTitle(/ScholarPulse/i);
  await expect(page.locator('body')).toContainText(/ScholarPulse/i);
});

test('health endpoint is reachable from the browser test environment', async ({ request }) => {
  const response = await request.get('/api/v1/health');
  expect(response.ok()).toBeTruthy();
  const body = await response.json();
  expect(body).toBeTruthy();
});

test('resource catalogue API supports paginated browsing', async ({ request }) => {
  const response = await request.get('/api/v1/resources?page=1&page_size=10');
  expect(response.ok()).toBeTruthy();
  const body = await response.json();
  expect(body).toHaveProperty('items');
  expect(body).toHaveProperty('total');
  expect(body).toHaveProperty('page');
  expect(body).toHaveProperty('page_size');
  expect(body.items.length).toBeLessThanOrEqual(10);
});

test('resource search endpoint accepts the q parameter', async ({ request }) => {
  const response = await request.get('/api/v1/resources?q=Dijkstra&page=1&page_size=10');
  expect(response.ok()).toBeTruthy();
  const body = await response.json();
  expect(body).toHaveProperty('items');
  expect(body).toHaveProperty('total');
  expect(body.page).toBe(1);
});
