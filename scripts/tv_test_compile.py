"""Test Pine Scripts compile on TradingView via browser automation."""
import os
import sys
import asyncio
from datetime import datetime

STRATEGIES_DIR = os.path.expanduser("~/rudy/strategies")
SCREENSHOT_DIR = os.path.expanduser("~/rudy/logs/screenshots")
CHROME_PROFILE = os.path.expanduser("~/Library/Application Support/Google/Chrome")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

SCRIPTS = [
    ("pinescript_energy_momentum.pine", "Energy Momentum", "CCJ"),
    ("pinescript_squeeze.pine", "Short Squeeze", "GME"),
    ("pinescript_sideways_condor.pine", "Sideways Condor", "SPY"),
]


async def test_all():
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()

    try:
        browser = await pw.chromium.launch_persistent_context(
            user_data_dir=os.path.join(CHROME_PROFILE, "Default"),
            headless=False,
            channel="chrome",
            viewport={"width": 1920, "height": 1080},
            args=["--no-first-run"],
        )

        page = browser.pages[0] if browser.pages else await browser.new_page()

        for filename, name, symbol in SCRIPTS:
            pine_path = os.path.join(STRATEGIES_DIR, filename)
            with open(pine_path) as f:
                code = f.read()

            print(f"\n=== Testing: {name} on {symbol} ===")

            # Navigate to chart
            await page.goto(
                f"https://www.tradingview.com/chart/?symbol={symbol}",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            await page.wait_for_timeout(5000)

            # Open Pine Editor
            try:
                pine_tab = page.locator('[data-name="pine-editor"]').first
                if await pine_tab.is_visible(timeout=3000):
                    await pine_tab.click()
                else:
                    raise Exception("not found")
            except:
                try:
                    # Try text-based search
                    tabs = page.locator('[class*="tab"]')
                    count = await tabs.count()
                    for i in range(count):
                        text = await tabs.nth(i).text_content()
                        if text and "pine" in text.lower():
                            await tabs.nth(i).click()
                            print(f"  Found Pine tab: {text}")
                            break
                except:
                    # Keyboard shortcut
                    await page.keyboard.press("Alt+p")

            await page.wait_for_timeout(2000)

            # Copy code to clipboard and try to paste
            await page.evaluate(f"navigator.clipboard.writeText({repr(code)})")

            # Try to find and interact with the code editor
            editor_found = False
            for sel in [
                'textarea.inputarea',
                '.view-lines',
                '[class*="editor"] textarea',
                'div[role="textbox"]',
                '.monaco-editor textarea',
            ]:
                try:
                    el = page.locator(sel).first
                    if await el.is_visible(timeout=1500):
                        await el.click()
                        await page.keyboard.press("Meta+a")
                        await page.wait_for_timeout(200)
                        await page.keyboard.press("Meta+v")
                        await page.wait_for_timeout(1000)
                        editor_found = True
                        print(f"  Pasted code via {sel}")
                        break
                except:
                    continue

            if not editor_found:
                print(f"  Could not paste automatically - code is on clipboard")

            # Try to click "Add to chart"
            await page.wait_for_timeout(1000)
            try:
                add_btn = page.locator('button:has-text("Add to chart")').first
                if await add_btn.is_visible(timeout=2000):
                    await add_btn.click()
                    print(f"  Clicked 'Add to chart'")
                    await page.wait_for_timeout(3000)
            except:
                pass

            # Check for errors in the Pine Editor output
            try:
                error_el = page.locator('[class*="error"], [class*="Error"]').first
                if await error_el.is_visible(timeout=2000):
                    error_text = await error_el.text_content()
                    print(f"  ERROR: {error_text[:200]}")
                else:
                    print(f"  No errors detected")
            except:
                print(f"  Could not check for errors")

            # Screenshot
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            ss_path = f"{SCREENSHOT_DIR}/tv_test_{filename}_{ts}.png"
            await page.screenshot(path=ss_path)
            print(f"  Screenshot: {ss_path}")

        # Keep browser open for manual inspection
        print("\nBrowser staying open for 120s - inspect results...")
        await page.wait_for_timeout(120000)

    except Exception as e:
        print(f"Error: {e}")
    finally:
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(test_all())
