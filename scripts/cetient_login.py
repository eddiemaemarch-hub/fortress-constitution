"""Cetient — Manual Login Script
Opens a visible browser window for you to log in.
Saves cookies so Rudy can use Cetient automatically after.
"""
import json
import os
from playwright.sync_api import sync_playwright

COOKIE_FILE = os.path.expanduser("/Users/eddiemae/rudy/data/cetient_cookies.json")
os.makedirs(os.path.dirname(COOKIE_FILE), exist_ok=True)

print("Opening Cetient in a browser window...")
print("Log in with your account, then come back here and press Enter.")
print()

pw = sync_playwright().start()
browser = pw.chromium.launch(headless=False)
context = browser.new_context()
page = context.new_page()
page.goto("https://cetient.com")

input(">>> Log in on the browser, then press Enter here to save session... ")

cookies = context.cookies()
with open(COOKIE_FILE, "w") as f:
    json.dump(cookies, f, indent=2)

print(f"\nSession saved! {len(cookies)} cookies stored.")
print("Rudy can now use Cetient automatically.")

browser.close()
pw.stop()
