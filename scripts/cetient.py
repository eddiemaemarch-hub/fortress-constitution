"""Cetient — Automated Legal AI Interface for Rudy v2.0
Browser automation via Playwright. Logs in, sends prompts, retrieves responses.
"""
import os
import sys
import json
import time
import asyncio
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

LOG_DIR = os.path.expanduser("~/rudy/logs")
COOKIE_FILE = os.path.expanduser("~/rudy/data/cetient_cookies.json")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(os.path.dirname(COOKIE_FILE), exist_ok=True)

CETIENT_EMAIL = os.environ.get("CETIENT_EMAIL", "eddiemaemarch@icloud.com")
CETIENT_PASSWORD = os.environ.get("CETIENT_PASSWORD", "")


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[Cetient {ts}] {msg}")
    with open(f"{LOG_DIR}/cetient.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")


async def _create_browser():
    """Create a Playwright browser instance."""
    from playwright.async_api import async_playwright
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    return pw, browser


async def _login(page):
    """Log into Cetient."""
    log("Navigating to Cetient...")
    await page.goto("https://cetient.com", wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(2000)

    # Look for login/sign-in button or link
    login_selectors = [
        'a:has-text("Log in")', 'a:has-text("Login")', 'a:has-text("Sign in")',
        'button:has-text("Log in")', 'button:has-text("Login")', 'button:has-text("Sign in")',
        'a[href*="login"]', 'a[href*="signin"]', 'a[href*="sign-in"]',
    ]

    clicked = False
    for sel in login_selectors:
        try:
            el = await page.query_selector(sel)
            if el:
                await el.click()
                await page.wait_for_timeout(2000)
                clicked = True
                log(f"Clicked login via: {sel}")
                break
        except:
            continue

    if not clicked:
        log("No login button found — may already be logged in or different layout")

    # Fill email
    email_selectors = [
        'input[type="email"]', 'input[name="email"]', 'input[placeholder*="email" i]',
        'input[name="username"]', 'input[id*="email" i]',
    ]
    for sel in email_selectors:
        try:
            el = await page.query_selector(sel)
            if el:
                await el.fill(CETIENT_EMAIL)
                log("Email entered")
                break
        except:
            continue

    # Fill password
    pw_selectors = [
        'input[type="password"]', 'input[name="password"]', 'input[id*="password" i]',
    ]
    for sel in pw_selectors:
        try:
            el = await page.query_selector(sel)
            if el:
                await el.fill(CETIENT_PASSWORD)
                log("Password entered")
                break
        except:
            continue

    # Click submit
    submit_selectors = [
        'button[type="submit"]', 'button:has-text("Log in")', 'button:has-text("Login")',
        'button:has-text("Sign in")', 'input[type="submit"]',
    ]
    for sel in submit_selectors:
        try:
            el = await page.query_selector(sel)
            if el:
                await el.click()
                await page.wait_for_timeout(3000)
                log("Login submitted")
                break
        except:
            continue

    # Save cookies for future sessions
    cookies = await page.context.cookies()
    with open(COOKIE_FILE, "w") as f:
        json.dump(cookies, f)
    log("Cookies saved")


async def _send_prompt(page, prompt):
    """Send a prompt to Cetient and get the response."""
    log(f"Sending prompt: {prompt[:80]}...")

    # Look for chat/input field
    input_selectors = [
        'textarea', 'input[type="text"]',
        '[contenteditable="true"]',
        'textarea[placeholder*="ask" i]', 'textarea[placeholder*="type" i]',
        'textarea[placeholder*="message" i]',
        'input[placeholder*="ask" i]', 'input[placeholder*="search" i]',
    ]

    input_el = None
    for sel in input_selectors:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                input_el = el
                log(f"Found input: {sel}")
                break
        except:
            continue

    if not input_el:
        log("ERROR: Could not find input field")
        # Take screenshot for debugging
        screenshot_path = f"{LOG_DIR}/cetient_debug.png"
        await page.screenshot(path=screenshot_path)
        log(f"Screenshot saved to {screenshot_path}")
        return "Error: Could not find Cetient input field. Check ~/rudy/logs/cetient_debug.png"

    # Type the prompt
    await input_el.fill(prompt)
    await page.wait_for_timeout(500)

    # Submit — try Enter key first, then look for send button
    await input_el.press("Enter")
    await page.wait_for_timeout(1000)

    # Also try clicking send button
    send_selectors = [
        'button:has-text("Send")', 'button:has-text("Submit")',
        'button[type="submit"]', 'button[aria-label*="send" i]',
        'button svg', 'button:has-text("Go")',
    ]
    for sel in send_selectors:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.click()
                log(f"Clicked send: {sel}")
                break
        except:
            continue

    # Wait for response — poll for content changes
    log("Waiting for response...")
    await page.wait_for_timeout(5000)  # Initial wait

    # Try to detect when response is complete (look for loading indicators to disappear)
    for _ in range(30):  # Max 60 seconds
        loading = await page.query_selector('[class*="loading" i], [class*="spinner" i], [class*="typing" i]')
        if not loading:
            break
        await page.wait_for_timeout(2000)

    await page.wait_for_timeout(3000)  # Final buffer

    # Extract response text
    # Look for the last response/message element
    response_selectors = [
        '[class*="response" i]', '[class*="answer" i]', '[class*="message" i]:last-child',
        '[class*="assistant" i]', '[class*="bot" i]', '[class*="reply" i]',
        '[class*="output" i]', '[class*="result" i]',
        'article:last-child', '.prose:last-child',
    ]

    response_text = ""
    for sel in response_selectors:
        try:
            elements = await page.query_selector_all(sel)
            if elements:
                last = elements[-1]
                text = await last.inner_text()
                if text and len(text) > 20:
                    response_text = text
                    log(f"Got response via: {sel} ({len(text)} chars)")
                    break
        except:
            continue

    if not response_text:
        # Fallback: get main content area
        try:
            body_text = await page.inner_text("main")
            if body_text:
                response_text = body_text
                log(f"Fallback: got main content ({len(body_text)} chars)")
        except:
            try:
                body_text = await page.inner_text("body")
                response_text = body_text[-5000:] if len(body_text) > 5000 else body_text
                log(f"Fallback: got body content ({len(response_text)} chars)")
            except:
                response_text = "Error: Could not extract response from Cetient."

    return response_text


async def _query_cetient(prompt):
    """Full flow: launch browser, login, send prompt, get response."""
    pw, browser = await _create_browser()

    try:
        context = await browser.new_context()

        # Load cookies if available
        if os.path.exists(COOKIE_FILE):
            with open(COOKIE_FILE) as f:
                cookies = json.load(f)
            await context.add_cookies(cookies)
            log("Loaded saved cookies")

        page = await context.new_page()

        # Try going directly — cookies might keep us logged in
        await page.goto("https://cetient.com", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)

        # Check if we need to login
        current_url = page.url
        page_text = await page.inner_text("body")

        needs_login = any(term in page_text.lower() for term in ["log in", "sign in", "login", "sign up"])
        if needs_login and CETIENT_PASSWORD:
            await _login(page)
            await page.wait_for_timeout(2000)

        response = await _send_prompt(page, prompt)

        # Save screenshot of result
        screenshot_path = f"{LOG_DIR}/cetient_last_result.png"
        await page.screenshot(path=screenshot_path, full_page=True)

        return response

    finally:
        await browser.close()
        await pw.stop()


def query(prompt):
    """Synchronous wrapper — use this from other modules."""
    if not CETIENT_PASSWORD:
        return ("Cetient password not set. Add CETIENT_PASSWORD to your environment:\n"
                "  export CETIENT_PASSWORD='your_password'\n"
                "Or add it to ~/rudy/start.sh")
    log(f"Query: {prompt[:100]}")
    result = asyncio.run(_query_cetient(prompt))
    log(f"Result: {len(result)} chars")
    return result


def draft_complaint(case_type, jurisdiction, facts):
    """Draft a legal complaint."""
    prompt = (
        f"Draft a civil complaint for {case_type} in {jurisdiction}. "
        f"Facts of the case: {facts}. "
        f"Include all required sections: caption, jurisdiction statement, "
        f"factual allegations, causes of action, prayer for relief. "
        f"Format as a proper legal document ready for filing."
    )
    return query(prompt)


def research_case_law(topic, jurisdiction="federal"):
    """Research case law on a topic."""
    prompt = (
        f"Research case law on: {topic}. "
        f"Jurisdiction: {jurisdiction}. "
        f"Provide relevant cases with citations, holdings, and how they apply. "
        f"Include both landmark cases and recent decisions."
    )
    return query(prompt)


def legal_analysis(question):
    """Get legal analysis on a question."""
    prompt = (
        f"Provide a thorough legal analysis of the following: {question}. "
        f"Cite relevant statutes and case law. "
        f"Discuss majority and minority positions where applicable."
    )
    return query(prompt)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
        print(query(prompt))
    else:
        print("Usage: python3 cetient.py 'your legal question here'")
        print("Set CETIENT_PASSWORD env variable first.")
