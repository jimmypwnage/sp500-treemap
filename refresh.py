#!/usr/bin/env python3
"""Refresh the S&P 500 treemap end-to-end:

  1. regenerate data.js   (fetch_data.main)
  2. render sp500.png      (headless Chrome screenshot of index.html)
  3. publish to GitHub Pages (git commit + push, only if data changed)

Run standalone (`python refresh.py`) or import and call refresh().
The bot schedules this daily; the PNG it produces is what /sp500 sends.
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PNG = HERE / "sp500.png"
GIT_NAME = "Teoh, Min Wei"
GIT_EMAIL = "mteoh3@gatech.edu"


def render_png():
    """Screenshot index.html to sp500.png at 2x desktop width."""
    file_url = "file://" + str(HERE / "index.html").replace(" ", "%20")
    subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         "--force-device-scale-factor=2", "--window-size=1600,1000",
         "--virtual-time-budget=6000", f"--screenshot={PNG}", file_url],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if not PNG.exists() or PNG.stat().st_size == 0:
        raise RuntimeError("PNG render failed (empty/missing file)")
    print(f"[png] {PNG.stat().st_size // 1024} KB", file=sys.stderr)


def publish():
    """Commit + push data.js/index.html only when data.js actually changed."""
    subprocess.run(["git", "add", "data.js", "index.html"], cwd=HERE, check=True)
    changed = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=HERE).returncode
    if changed == 0:
        print("[publish] no changes, skipping push", file=sys.stderr)
        return
    subprocess.run(
        ["git", "-c", f"user.name={GIT_NAME}", "-c", f"user.email={GIT_EMAIL}",
         "commit", "-m", "data refresh"], cwd=HERE, check=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=HERE, check=True)
    print("[publish] pushed to GitHub Pages", file=sys.stderr)


def refresh():
    os.chdir(HERE)                      # fetch_data uses relative paths
    import fetch_data
    fetch_data.main()
    render_png()
    publish()


if __name__ == "__main__":
    refresh()
