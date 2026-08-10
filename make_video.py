"""
make_video.py  —  Convert presentation.html → MerchOps_Agent_Demo.mp4

Requirements (auto-installed on first run):
    pip install playwright opencv-python numpy
    playwright install chromium
"""

import subprocess, sys, os, time, pathlib, io
# Force UTF-8 output on Windows cp1252 consoles
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── 1. Auto-install dependencies ─────────────────────────────────────────────
def ensure(pkg, import_name=None):
    try:
        __import__(import_name or pkg)
    except ImportError:
        print(f"[setup] Installing {pkg} …")
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])

ensure("playwright")
ensure("cv2", "cv2")
ensure("numpy")

from playwright.sync_api import sync_playwright
import cv2, numpy as np

# ── 2. Config ─────────────────────────────────────────────────────────────────
HERE        = pathlib.Path(__file__).parent
HTML_FILE   = HERE / "presentation.html"
OUTPUT_FILE = HERE / "MerchOps_Agent_Demo.mp4"

WIDTH, HEIGHT = 1280, 720
FPS           = 12          # frames per second recorded
SLIDE_DURATIONS = [
    7,   # 1  Intro
    8,   # 2  Login
    9,   # 3  Dashboard
    9,   # 4  AI Inbox
    7,   # 5  Drafts
    7,   # 6  Approved Senders
    6,   # 7  Unregistered Users
    7,   # 8  Email Monitor
    6,   # 9  Email Accounts
    9,   # 10 Inventory Engine
    8,   # 11 Inventory Alerts
    9,   # 12 Outro
]

# ── 3. Install Chromium if missing ────────────────────────────────────────────
print("[setup] Checking Playwright Chromium …")
result = subprocess.run(
    [sys.executable, "-m", "playwright", "install", "chromium"],
    capture_output=True, text=True
)
if result.returncode != 0:
    print("[setup] playwright install:", result.stderr[:200])

# ── 4. Record ─────────────────────────────────────────────────────────────────
def slide_js(idx):
    """JS to jump directly to a slide and stop auto-advance."""
    return f"""
    (function(){{
        // stop auto-timer
        if(window._autoTimer) clearTimeout(window._autoTimer);
        if(window._tickTimer) clearInterval(window._tickTimer);

        var slides = document.querySelectorAll('.slide');
        slides.forEach(function(s){{ s.classList.remove('active','exit'); }});
        slides[{idx}].classList.add('active');

        // freeze progress bar
        var pb = document.getElementById('prog-bar');
        if(pb) pb.style.width = (({idx}/(slides.length-1))*100)+'%';

        var ctr = document.getElementById('slide-counter');
        if(ctr) ctr.textContent = '{idx+1} / '+slides.length;

        // disable auto-play button label
        var btn = document.getElementById('btnPlay');
        if(btn) btn.textContent = '▶ Play';
    }})();
    """

print(f"\n[record] Opening:  {HTML_FILE}")
print(f"[record] Output:   {OUTPUT_FILE}")
print(f"[record] Size:     {WIDTH}×{HEIGHT}  @{FPS}fps")
print(f"[record] Slides:   {len(SLIDE_DURATIONS)}")
total_secs = sum(SLIDE_DURATIONS)
print(f"[record] Duration: {total_secs}s  (~{total_secs//60}m{total_secs%60}s)\n")

fourcc = cv2.VideoWriter_fourcc(*"mp4v")
writer = cv2.VideoWriter(str(OUTPUT_FILE), fourcc, FPS, (WIDTH, HEIGHT))

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
    page.goto(HTML_FILE.as_uri())
    page.wait_for_load_state("networkidle")
    time.sleep(1.5)  # let fonts/animations settle

    for slide_idx, duration in enumerate(SLIDE_DURATIONS):
        print(f"  Slide {slide_idx+1:02d}/{len(SLIDE_DURATIONS)} — {duration}s", end="", flush=True)

        # Jump to this slide
        page.evaluate(slide_js(slide_idx))
        time.sleep(0.5)  # let transition finish

        frames_needed = FPS * duration
        interval      = duration / frames_needed

        for f in range(frames_needed):
            # Animate progress inside slide (timer ring)
            frac = f / frames_needed
            page.evaluate(f"""
            (function(){{
                var c = document.getElementById('timer-circle');
                if(c) c.style.strokeDashoffset = (69.1 * (1-{frac:.4f}));
            }})();
            """)

            png_bytes = page.screenshot(type="png")
            arr = np.frombuffer(png_bytes, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)

            if img is not None:
                # resize in case viewport drifted
                if img.shape[1] != WIDTH or img.shape[0] != HEIGHT:
                    img = cv2.resize(img, (WIDTH, HEIGHT))
                writer.write(img)

            if f % FPS == 0:
                print(".", end="", flush=True)
            time.sleep(interval)

        print(f"  ✓ ({frames_needed} frames)")

    browser.close()

writer.release()
size_mb = OUTPUT_FILE.stat().st_size / 1024 / 1024
print(f"\n✅  Video saved:  {OUTPUT_FILE}")
print(f"   File size:   {size_mb:.1f} MB")
print(f"   Duration:    {total_secs}s")
print(f"   Resolution:  {WIDTH}×{HEIGHT}  @{FPS}fps")
print("\nDone! You can now send MerchOps_Agent_Demo.mp4 to anyone.")
