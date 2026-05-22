import { test, expect } from '@playwright/test'

test('dashboard loads and shows elevators', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByText('Elevator Maintenance')).toBeVisible()
  await expect(page.getByText('Total elevators')).toBeVisible()
  await expect(page.locator('table tbody tr')).toHaveCount(100)
})

test('high-risk elevator detail page loads', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('link', { name: /View →/ }).first().click()
  await expect(page.getByText('Model explanation')).toBeVisible()
  await expect(page.getByText('Prediction drivers')).toBeVisible()
  await expect(page.getByText('Dispatch technician')).toBeVisible()
})

test('post-visit report form submits', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('link', { name: /View →/ }).first().click()
  await page.getByRole('link', { name: 'Submit post-visit report' }).click()
  await expect(page.getByText('Post-visit report')).toBeVisible()
  await page.getByPlaceholder('Full name').fill('Test Technician')
  await page.getByRole('button', { name: 'Submit report' }).click()
  await expect(page.getByText('Report submitted')).toBeVisible()
})
