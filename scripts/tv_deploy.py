"""TradingView Pine Script Deployer - Browser Automation
Uses Playwright to deploy Pine Scripts to TradingView automatically.
Opens Chrome with your logged-in profile, pastes code, adds to chart.
"""
import os
import sys
import asyncio
from datetime import datetime

LOG_DIR = os.path.expanduser("~/rudy/logs")
SCREENSHOT_DIR = os.path.expanduser("~/rudy/logs/screenshots")
STRATEGIES_DIR = os.path.expanduser("~/rudy/strategies")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

CHROME_PROFILE = os.path.expanduser("~/Library/Application Support/Google/Chrome")
TRADINGVIEW_CHART = "https://www.tradingview.com/chart/"


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[TV Deploy {ts}] {msg}")
    with open(f"{LOG_DIR}/tv_deploy.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")


# Pine Script files to deploy
SCRIPTS = {
    "energy": {
        "file": "pinescript_energy_momentum.pine",
        "name": "Energy Momentum (Trader3)",
        "symbols": ["CCJ", "XOM", "DVN", "CVX", "OXY", "FANG"],
    },
    "squeeze": {
        "file": "pinescript_squeeze.pine",
        "name": "Short Squeeze (Trader4)",
        "symbols": ["GME", "RIVN", "PLTR", "COIN", "SOFI"],
    },
    "sideways": {
        "file": "pinescript_sideways_condor.pine",
        "name": "Sideways Condor (Trader5)",
        "symbols": ["SPY", "QQQ", "IWM", "MSFT", "AAPL"],
    },
}


async def deploy_pine_script(script_key, symbol=None):
    """Deploy a Pine Script to TradingView via browser automation."""
    from playwright.async_api import async_playwright

    if script_key not in SCRIPTS:
        log(f"Unknown script: {script_key}. Options: {list(SCRIPTS.keys())}")
        return False

    info = SCRIPTS[script_key]
    pine_file = os.path.join(STRATEGIES_DIR, info["file"])

    if not os.path.exists(pine_file):
        log(f"Pine file not found: {pine_file}")
        return False

    with open(pine_file) as f:
        pine_code = f.read()

    target_symbol = symbol or info["symbols"][0]
    log(f"Deploying '{info['name']}' on {target_symbol}...")

    pw = await async_playwright().start()

    try:
        # Launch Chrome with user's profile (logged into TradingView)
        browser = await pw.chromium.launch_persistent_context(
            user_data_dir=os.path.join(CHROME_PROFILE, "Default"),
            headless=False,
            channel="chrome",
            viewport={"width": 1920, "height": 1080},
            args=["--no-first-run"],
        )

        page = browser.pages[0] if browser.pages else await browser.new_page()

        # Navigate to TradingView chart
        chart_url = f"{TRADINGVIEW_CHART}?symbol={target_symbol}"
        log(f"Opening {chart_url}")
        await page.goto(chart_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(5000)

        # Take screenshot of initial state
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        await page.screenshot(path=f"{SCREENSHOT_DIR}/tv_deploy_{script_key}_{ts}_before.png")
        log("Screenshot saved (before)")

        # Open Pine Script editor - try keyboard shortcut first
        # TradingView shortcut: Alt+P or click the Pine Editor tab
        try:
            # Look for Pine Editor tab at bottom
            pine_tab = page.locator('text="Pine Editor"').first
            if await pine_tab.is_visible(timeout=3000):
                await pine_tab.click()
                log("Clicked Pine Editor tab")
            else:
                raise Exception("Tab not visible")
        except:
            # Try the bottom panel tabs
            try:
                await page.keyboard.press("Alt+p")
                await page.wait_for_timeout(1000)
                log("Opened Pine Editor via Alt+P")
            except:
                log("Could not find Pine Editor - trying bottom panel")
                # Click on bottom panel area
                bottom_tabs = page.locator('[class*="bottom"] [class*="tab"]')
                count = await bottom_tabs.count()
                for i in range(count):
                    text = await bottom_tabs.nth(i).text_content()
                    if text and "pine" in text.lower():
                        await bottom_tabs.nth(i).click()
                        log(f"Found Pine tab: {text}")
                        break

        await page.wait_for_timeout(2000)

        # Find the code editor area (CodeMirror or Monaco)
        editor = None
        # TradingView uses a custom editor - try multiple selectors
        selectors = [
            '.pine-editor-container textarea',
            '[class*="editor"] textarea',
            '.view-lines',
            'textarea[class*="input"]',
            '.monaco-editor textarea',
            'div[role="textbox"]',
        ]

        for sel in selectors:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    editor = el
                    log(f"Found editor: {sel}")
                    break
            except:
                continue

        if editor:
            # Select all existing code and replace
            await editor.click()
            await page.keyboard.press("Meta+a")  # Cmd+A on Mac
            await page.wait_for_timeout(300)
            await page.keyboard.press("Backspace")
            await page.wait_for_timeout(300)

            # Type the Pine Script (use clipboard for speed)
            await page.evaluate(f"navigator.clipboard.writeText({repr(pine_code)})")
            await page.keyboard.press("Meta+v")  # Cmd+V paste
            await page.wait_for_timeout(1000)
            log("Pasted Pine Script code")
        else:
            # Fallback: try using the "Open" or "New" button and paste
            log("Could not find editor directly, trying clipboard approach")
            # Copy to system clipboard
            import subprocess
            proc = subprocess.Popen(['pbcopy'], stdin=subprocess.PIPE)
            proc.communicate(pine_code.encode())
            log("Code copied to system clipboard - paste manually with Cmd+V in Pine Editor")

        # Try to click "Add to chart" or "Save" button
        try:
            add_btn = page.locator('button:has-text("Add to chart")').first
            if await add_btn.is_visible(timeout=3000):
                await add_btn.click()
                log("Clicked 'Add to chart'")
                await page.wait_for_timeout(3000)
        except:
            log("'Add to chart' button not found - try clicking it manually")

        # Take screenshot of result
        await page.screenshot(path=f"{SCREENSHOT_DIR}/tv_deploy_{script_key}_{ts}_after.png")
        log(f"Screenshot saved (after): tv_deploy_{script_key}_{ts}_after.png")

        # Keep browser open for user to verify
        log("Browser staying open for verification. Close it when done.")
        await page.wait_for_timeout(60000)  # Keep open 60s

    except Exception as e:
        log(f"Error: {e}")
    finally:
        await pw.stop()

    return True


async def deploy_all():
    """Deploy all Pine Scripts sequentially."""
    for key in SCRIPTS:
        await deploy_pine_script(key)


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: python3 tv_deploy.py <script> [symbol]")
        print(f"Scripts: {', '.join(SCRIPTS.keys())}")
        print(f"  python3 tv_deploy.py energy CCJ")
        print(f"  python3 tv_deploy.py squeeze GME")
        print(f"  python3 tv_deploy.py sideways SPY")
        print(f"  python3 tv_deploy.py all")
        return

    script_key = sys.argv[1].lower()
    symbol = sys.argv[2].upper() if len(sys.argv) > 2 else None

    if script_key == "all":
        asyncio.run(deploy_all())
    else:
        asyncio.run(deploy_pine_script(script_key, symbol))


if __name__ == "__main__":
    main()
