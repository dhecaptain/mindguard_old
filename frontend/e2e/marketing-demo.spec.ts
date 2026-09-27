import { test, expect } from '@playwright/test'
import { API_BASE, ADMIN, blockExternalRequests, expectNoAxeViolations, loginViaApi } from './helpers'

const DEMO_EMAIL = 'e2e-demo-request@example.com'

test.beforeEach(async ({ page }) => {
  await blockExternalRequests(page)
})

test.describe('Marketing demo request (Delivery Brief §5.5)', () => {
  test('submits the request form and persists it for the admin queue', async ({
    page,
    request,
  }) => {
    await page.goto('/demo')
    await expectNoAxeViolations(page, 'demo request form')

    await page.getByPlaceholder('Jordan Blake').fill('E2E Test Person')
    await page.getByPlaceholder('jordan@yourschool.edu').fill(DEMO_EMAIL)
    await page.getByPlaceholder('Riverside High').fill('E2E Test Academy')
    await page.getByPlaceholder('Head of Pastoral Care').fill('School Counsellor')
    await page.getByPlaceholder('UK').fill('Kenya')
    await page.getByLabel('Student population *').selectOption('Under 500')
    await page.getByLabel(/I agree to be contacted by MindGuard/).check()
    await page.getByRole('button', { name: 'Request demo' }).click()

    await page.waitForURL('**/thank-you')
    await expect(page.getByRole('heading', { name: 'Thank you — request received' })).toBeVisible()

    const token = await loginViaApi(request, ADMIN.email, ADMIN.password)
    const res = await request.get(`${API_BASE}/api/v1/admin/demo-requests`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(res.ok()).toBeTruthy()
    const body = await res.json()
    const rows = Array.isArray(body?.demo_requests) ? body.demo_requests : []
    const submitted = rows.find(
      (r: { work_email: string }) => r.work_email === DEMO_EMAIL,
    ) as
      | { full_name: string; organisation: string; consent_to_contact: boolean | number }
      | undefined
    expect(submitted).toBeTruthy()
    expect(submitted.full_name).toBe('E2E Test Person')
    expect(submitted.organisation).toBe('E2E Test Academy')
    expect(submitted.consent_to_contact).toBeTruthy()
  })
})
