import { test, expect } from '@playwright/test';
import fs from 'fs';
import path from 'path';

test('landing page renders correctly', async ({ page }) => {
  const htmlPath = path.resolve(__dirname, '../src/index.html');
  const html = fs.readFileSync(htmlPath, 'utf-8');
  await page.setContent(html);

  // Title
  await expect(page.locator('h1')).toHaveText('Тестовый проект 2');

  // Description (partial match)
  await expect(page.locator('p.description')).toContainText('Одностраничное приложение');

  // Button
  const btn = page.locator('button#startBtn');
  await expect(btn).toBeVisible();
  await expect(btn).toHaveText('Начать');
});
