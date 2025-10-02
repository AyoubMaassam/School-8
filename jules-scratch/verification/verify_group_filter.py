from playwright.sync_api import sync_playwright

def run(playwright):
    browser = playwright.chromium.launch()
    page = browser.new_page()

    # Navigate to group list page
    page.goto("http://127.0.0.1:8000/groups/")
    page.wait_for_load_state("networkidle")
    page.screenshot(path="jules-scratch/verification/group_list_unfiltered.png")

    # Select the academic level and filter
    page.select_option('select[name="academic_level"]', label="ثانوي - السنة اولى علمي")
    page.click('button:has-text("تطبيق")')
    page.wait_for_load_state("networkidle")
    page.screenshot(path="jules-scratch/verification/group_list_filtered.png")

    browser.close()

with sync_playwright() as playwright:
    run(playwright)
