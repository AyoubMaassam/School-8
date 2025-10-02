from playwright.sync_api import sync_playwright

def run(playwright):
    browser = playwright.chromium.launch()
    page = browser.new_page()

    # Navigate to student detail page
    page.goto("http://127.0.0.1:8000/school/student/1/")
    page.screenshot(path="jules-scratch/verification/student_detail.png")

    # Navigate to student monthly payment page
    page.goto("http://127.0.0.1:8000/school/student/1/monthly-payment/?group_id=1")
    page.screenshot(path="jules-scratch/verification/student_monthly_payment.png")

    browser.close()

with sync_playwright() as playwright:
    run(playwright)
