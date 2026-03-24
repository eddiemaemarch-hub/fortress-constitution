"""Rudy Brain — Powered by Claude Code (Anthropic)
No API credits needed — runs on Max plan via claude CLI.
Replaces Gemini as the conversational AI brain for the dashboard.
"""
import os
import sys
import json
import subprocess
import tempfile
from datetime import datetime

LOG_DIR = os.path.expanduser("~/rudy/logs")
DATA_DIR = os.path.expanduser("~/rudy/data")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

SYSTEM_PROMPT = """You are Rudy v2.0, an autonomous trading and research AI assistant built for Lawson Tyrone Robinson (Commander).

PERSONALITY:
- Professional, confident, direct
- You call Lawson "Commander"
- You are loyal, sharp, and always ready
- Keep responses concise — no fluff
- You ARE the system — not a chatbot pretending to be one

YOUR SYSTEMS (Trading Constitution v42.0):

SYSTEM 1 — MSTR Lottery ($100k quarterly): MSTR/IBIT deep OTM calls, 10x Rule
SYSTEM 2 — Conservative Diagonal ($10k): Any stock except MSTR/IBIT, $50-250/trade
SYSTEM 3 — Energy Momentum ($20k): CCJ,UEC,LEU,VST,CEG,XOM,CVX,OXY,DVN,FANG,SMR — calls+puts, 45-60 DTE
SYSTEM 4 — Short Squeeze ($10k): GME,AMC,SOFI,RIVN,LCID — OTM calls, 14-30 DTE
SYSTEM 6 — Metals Momentum ($15k): GLD,GDX,NEM,SLV,MP,REMX — calls+puts, 45-90 DTE
SYSTEM 7 — SpaceX IPO ($10k/$25k): RKLB,ASTS,LUNR,GOOGL,LMT,NOC — calls+puts, 60-90 DTE
SYSTEM 8 — 10X Moonshot ($10k): JOBY,IONQ,QUBT,SMR,OKLO,RKLB,DNA,CRSP,BBAI,SOUN — calls+puts, 60-120 DTE

SCANNERS: Grok (X/Twitter), YouTube, TikTok, Truth Social (Trump), Congress (Pelosi+), DeepSeek (regime), Memory
INFRA: IBKR TWS port 7496 (paper), Telegram bot, webhook port 5555, dashboard localhost:3000
Total allocation: $170k. Paper trading until Sep/Oct 2026.
ALL strategies use OPTIONS ONLY — calls AND puts. All exits automated.

Working directory: ~/rudy/ (scripts/, strategies/, logs/, data/)
Respond helpfully and in character. Be concise."""

# Write system prompt to file for claude CLI
SYSTEM_PROMPT_FILE = os.path.join(DATA_DIR, "rudy_system_prompt.txt")
with open(SYSTEM_PROMPT_FILE, "w") as f:
    f.write(SYSTEM_PROMPT)


def _run_claude(prompt, tools=None, timeout=120):
    """Run claude CLI and return response."""
    env = os.environ.copy()
    env["CLAUDE_CODE"] = ""
    env["CLAUDECODE"] = ""
    # Remove invalid API key so Claude uses Max plan auth instead
    env.pop("ANTHROPIC_API_KEY", None)

    cmd = ["claude", "-p", "--append-system-prompt", SYSTEM_PROMPT]
    if tools:
        cmd.extend(["--tools", tools])

    # Pipe prompt via stdin to avoid shell escaping issues
    result = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=max(timeout, 120),
        cwd=os.path.expanduser("~/rudy"),
        env=env,
    )

    reply = result.stdout.strip()
    if not reply and result.stderr:
        # Filter out warnings
        err = result.stderr.strip()
        if "NotOpenSSLWarning" not in err and err:
            reply = f"Error: {err[:200]}"
    return reply or "No response generated. Try again, Commander."


def think(user_message):
    """Process a message through Claude Code and return Rudy's response."""
    try:
        reply = _run_claude(user_message)

        # Log
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(f"{LOG_DIR}/rudy_brain.log", "a") as f:
            f.write(f"[{ts}] USER: {user_message}\n")
            f.write(f"[{ts}] RUDY: {reply}\n\n")

        return reply
    except subprocess.TimeoutExpired:
        return "Response timed out. Try a simpler question, Commander."
    except Exception as e:
        return f"Brain error: {str(e)}"


def think_with_tools(user_message):
    """Process message with tool access — can read files, grep code, run commands."""
    try:
        reply = _run_claude(user_message, tools="Read,Glob,Grep,Bash", timeout=120)

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(f"{LOG_DIR}/rudy_brain.log", "a") as f:
            f.write(f"[{ts}] USER (tools): {user_message}\n")
            f.write(f"[{ts}] RUDY: {reply}\n\n")

        return reply
    except subprocess.TimeoutExpired:
        return "Tool response timed out — took over 2 minutes."
    except Exception as e:
        return f"Brain error: {str(e)}"


def reset():
    """Reset conversation."""
    pass


if __name__ == "__main__":
    print("Rudy Brain — Claude Code Powered")
    print("Type 'quit' to exit\n")
    while True:
        msg = input("You: ")
        if msg.lower() in ("quit", "exit", "q"):
            break
        print(f"Rudy: {think(msg)}\n")
