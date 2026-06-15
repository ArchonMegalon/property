from playwright.sync_api import sync_playwright
RUN_ID = '2aebe12c113a4062b8366e6020b77f17'
BASE = 'http://172.17.0.1:8097'
HEADERS = {
    'Authorization': 'Bearer propertyquarry-local-api-token',
    'X-EA-Principal-ID': 'ooda-vienna-investment-fix',
}
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={'width': 1440, 'height': 1400}, extra_http_headers=HEADERS)
    page = context.new_page()
    page.goto(f'{BASE}/app/properties?run_id={RUN_ID}', wait_until='networkidle', timeout=120000)
    page.locator('[data-workbench-row]').nth(0).click()
    page.wait_for_timeout(1500)
    page.screenshot(path='/tmp/vienna_selected_desktop.png', full_page=True)
    mobile = browser.new_context(
        viewport={'width': 430, 'height': 1400},
        is_mobile=True,
        device_scale_factor=2,
        extra_http_headers=HEADERS,
    )
    mpage = mobile.new_page()
    mpage.goto(f'{BASE}/app/properties?run_id={RUN_ID}', wait_until='networkidle', timeout=120000)
    mpage.locator('[data-workbench-row]').nth(0).click()
    mpage.wait_for_timeout(1500)
    mpage.screenshot(path='/tmp/vienna_selected_mobile.png', full_page=True)
    mobile.close()
    context.close()
    browser.close()
