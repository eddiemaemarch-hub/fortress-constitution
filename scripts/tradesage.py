"""TradeSage — Browser Automation for Rudy v2.0
Uses Playwright with Chrome Profile 1 (has TradeSage extension installed).
Interacts with TradeSage AI on TradingView for strategy & backtesting.
"""
import os
import sys
import json
import asyncio
from datetime import datetime

LOG_DIR = os.path.expanduser("~/rudy/logs")
SCREENSHOT_DIR = os.path.expanduser("~/rudy/logs/screenshots")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

CHROME_PROFILE = os.path.expanduser("~/Library/Application Support/Google/Chrome")
TRADINGVIEW_CHART = "https://www.tradingview.com/chart/FxGExYjH/"
TRADESAGE_EXT_ID = "lfemcakbnoemhihafdpigghkjjejgjfj"


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[TradeSage {ts}] {msg}")
    with open(f"{LOG_DIR}/tradesage.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")


async def _launch_browser():
    """Launch Chrome with Profile 1 (TradeSage installed)."""
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()

    # Launch with user's Chrome profile so TradeSage extension is available
    browser = await pw.chromium.launch_persistent_context(
        user_data_dir=os.path.join(CHROME_PROFILE, "Profile 1"),
        headless=False,  # Must be visible for extension to load
        channel="chrome",  # Use installed Chrome, not Playwright's Chromium
        args=[
            f"--disable-extensions-except={CHROME_PROFILE}/Profile 1/Extensions/{TRADESAGE_EXT_ID}/0.4.3_0",
            f"--load-extension={CHROME_PROFILE}/Profile 1/Extensions/{TRADESAGE_EXT_ID}/0.4.3_0",
        ],
        viewport={"width": 1920, "height": 1080},
    )

    return pw, browser


async def _open_tradingview(browser):
    """Navigate to TradingView chart."""
    page = browser.pages[0] if browser.pages else await browser.new_page()
    await page.goto(TRADINGVIEW_CHART, wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(5000)  # Wait for TradeSage to load
    log(f"TradingView chart loaded: {TRADINGVIEW_CHART}")
    return page


async def _find_tradesage_input(page):
    """Find TradeSage's chat/input element on the page."""
    # TradeSage injects a panel into TradingView — look for its elements
    selectors = [
        '[class*="tradesage" i] textarea',
        '[class*="tradesage" i] input',
        '[id*="tradesage" i] textarea',
        '[id*="tradesage" i] input',
        '[class*="sage" i] textarea',
        '[data-extension*="tradesage" i] textarea',
        # TradeSage typically adds a floating panel
        '[class*="ts-chat" i] textarea',
        '[class*="ts-input" i]',
        '[class*="extension"] textarea',
        'iframe[src*="tradesage"]',
    ]

    for sel in selectors:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                log(f"Found TradeSage input: {sel}")
                return el
        except:
            continue

    # Check iframes — extensions often inject via iframe
    frames = page.frames
    for frame in frames:
        try:
            for sel in ['textarea', 'input[type="text"]', '[contenteditable="true"]']:
                el = await frame.query_selector(sel)
                if el and await el.is_visible():
                    log(f"Found input in iframe: {sel}")
                    return el
        except:
            continue

    return None


async def _send_to_tradesage(page, prompt):
    """Send a prompt to TradeSage and capture the response."""
    log(f"Sending to TradeSage: {prompt[:80]}...")

    input_el = await _find_tradesage_input(page)

    if not input_el:
        # Take screenshot for debugging
        ss_path = f"{SCREENSHOT_DIR}/tradesage_{datetime.now().strftime('%H%M%S')}.png"
        await page.screenshot(path=ss_path, full_page=False)
        log(f"Could not find TradeSage input. Screenshot: {ss_path}")
        return f"Could not find TradeSage input panel. Screenshot saved to {ss_path}. Make sure TradeSage extension is open on TradingView."

    await input_el.fill(prompt)
    await page.wait_for_timeout(500)
    await input_el.press("Enter")

    # Wait for response
    log("Waiting for TradeSage response...")
    await page.wait_for_timeout(10000)  # Initial wait

    # Poll for loading to complete
    for _ in range(30):  # Max 60 seconds
        loading = await page.query_selector('[class*="loading" i], [class*="spinner" i], [class*="generating" i]')
        if not loading:
            break
        await page.wait_for_timeout(2000)

    await page.wait_for_timeout(3000)

    # Extract response
    response_selectors = [
        '[class*="tradesage" i] [class*="response" i]',
        '[class*="tradesage" i] [class*="message" i]:last-child',
        '[class*="tradesage" i] [class*="answer" i]',
        '[class*="tradesage" i] [class*="output" i]',
        '[class*="tradesage" i] .prose',
        '[class*="sage" i] [class*="response" i]',
    ]

    response_text = ""
    for sel in response_selectors:
        try:
            elements = await page.query_selector_all(sel)
            if elements:
                last = elements[-1]
                text = await last.inner_text()
                if text and len(text) > 10:
                    response_text = text
                    log(f"Got response ({len(text)} chars)")
                    break
        except:
            continue

    if not response_text:
        # Try iframes
        for frame in page.frames:
            try:
                for sel in ['[class*="response"]', '[class*="message"]:last-child', '.prose', '[class*="output"]']:
                    elements = await frame.query_selector_all(sel)
                    if elements:
                        last = elements[-1]
                        text = await last.inner_text()
                        if text and len(text) > 10:
                            response_text = text
                            log(f"Got response from iframe ({len(text)} chars)")
                            break
                if response_text:
                    break
            except:
                continue

    # Take screenshot of result
    ss_path = f"{SCREENSHOT_DIR}/tradesage_result_{datetime.now().strftime('%H%M%S')}.png"
    await page.screenshot(path=ss_path, full_page=False)
    log(f"Screenshot saved: {ss_path}")

    return response_text or f"Response captured as screenshot: {ss_path}"


async def _run_query(prompt, keep_open=False):
    """Full flow: launch Chrome, open TradingView, query TradeSage."""
    pw, browser = await _launch_browser()
    try:
        page = await _open_tradingview(browser)
        result = await _send_to_tradesage(page, prompt)

        if keep_open:
            log("Browser left open for manual interaction")
            input("Press Enter to close browser...")

        return result
    finally:
        if not keep_open:
            await browser.close()
            await pw.stop()


def query(prompt):
    """Send a prompt to TradeSage. Synchronous wrapper."""
    log(f"Query: {prompt[:100]}")
    result = asyncio.run(_run_query(prompt))
    log(f"Result: {len(result)} chars")
    return result


def generate_strategy(description):
    """Ask TradeSage to generate a Pine Script strategy."""
    prompt = (
        f"Generate a Pine Script v5 strategy for the following: {description}. "
        f"Include entry and exit conditions, backtesting parameters, and proper risk management."
    )
    return query(prompt)


def optimize_strategy(strategy_name):
    """Ask TradeSage to optimize an existing strategy."""
    prompt = (
        f"Optimize the current strategy '{strategy_name}' on this chart. "
        f"Find the most profitable input parameters and show the backtest results."
    )
    return query(prompt)


def backtest(description):
    """Ask TradeSage to run a backtest."""
    prompt = (
        f"Backtest the following strategy on this chart: {description}. "
        f"Show win rate, profit factor, max drawdown, and total return."
    )
    return query(prompt)


def analyze_chart():
    """Ask TradeSage to analyze the current chart."""
    prompt = (
        "Analyze the current chart. What's the trend? Key support/resistance levels? "
        "Any notable patterns? Give me your trade thesis."
    )
    return query(prompt)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
        print(query(prompt))
    else:
        print("Usage: python3 tradesage.py 'your prompt here'")
        print("Functions: generate_strategy(), optimize_strategy(), backtest(), analyze_chart()")
