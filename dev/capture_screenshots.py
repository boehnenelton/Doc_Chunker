#!/usr/bin/env python3
"""
Name:           capture_screenshots.py
Description:    Playwright automated screenshot capture script for Doc_Chunker Web Interface.
                Spawns Doc_Chunker_Flask on a dedicated port, launches native headless Chromium
                via termux_playwright, and captures high-resolution screenshots of the Document
                Manager, Drawer Navigation, Chunks Overview, Chunk Editor, Categories, Compiler,
                and Tools Hub for documentation and README illustration.
Version:        1.0.0
Date Created:   2026-11-12
Author:         Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
RELATIONAL_ID:  a4e8d891-f923-4561-a834-08246bc92015
"""

import os
import sys
import time
import asyncio
import subprocess
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FLASK_SCRIPT = REPO_ROOT / "Doc_Chunker_Flask.py"
ASSETS_DIR = REPO_ROOT / "docs" / "assets"
TEST_PORT = 5055
BASE_URL = f"http://127.0.0.1:{TEST_PORT}"


def wait_for_server(url: str, timeout_sec: int = 15) -> bool:
    start_time = time.time()
    while time.time() - start_time < timeout_sec:
        try:
            with urllib.request.urlopen(f"{url}/", timeout=2) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


async def capture_screenshots():
    print("=" * 65)
    print("      Doc_Chunker Playwright Automated Screenshot Capture")
    print("=" * 65)

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Start Server on dedicated TEST_PORT
    server_env = os.environ.copy()
    server_env["PORT"] = str(TEST_PORT)
    server_env["HOST"] = "127.0.0.1"
    print(f"[*] Starting Doc_Chunker Flask server on {BASE_URL}...")
    server_process = subprocess.Popen(
        [sys.executable, str(FLASK_SCRIPT)],
        env=server_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    try:
        if not wait_for_server(BASE_URL):
            print("[FAIL] Doc_Chunker Flask server failed to start within timeout.")
            server_process.kill()
            sys.exit(1)
        print("[✓] Doc_Chunker Flask server is online and responding.")

        # 2. Launch Browser via termux_playwright
        from termux_playwright import async_playwright_termux, launch

        async with async_playwright_termux() as playwright_instance:
            print("[*] Launching headless Chromium via termux_playwright...")
            browser = await launch(playwright_instance, headless=True)
            print("[✓] Browser launched successfully.")

            context = await browser.new_context(
                viewport={"width": 1280, "height": 820},
                device_scale_factor=1
            )
            page = await context.new_page()

            # --- SCREENSHOT 1: Document Projects Dashboard ---
            print(f"[*] Navigating to {BASE_URL}/ (Document Projects Dashboard)...")
            await page.goto(f"{BASE_URL}/", timeout=30000, wait_until="domcontentloaded")
            await page.wait_for_timeout(800)
            shot_docs = ASSETS_DIR / "screenshot_doc_manager.png"
            await page.screenshot(path=str(shot_docs), full_page=False)
            print(f"[✓] Captured {shot_docs.name} ({shot_docs.stat().st_size} bytes)")

            # --- SCREENSHOT 2: Drawer Navigation Open ---
            print("[*] Opening drawer navigation menu...")
            try:
                drawer_btn = await page.query_selector("button.header-btn, .header-menu-btn, button[onclick*='openDrawer']")
                if drawer_btn:
                    await drawer_btn.click()
                    await page.wait_for_timeout(500)
                else:
                    await page.evaluate("() => { if (typeof openDrawer === 'function') openDrawer(); }")
                    await page.wait_for_timeout(500)
            except Exception as e:
                print(f"[!] Note on drawer trigger: {e}")

            shot_drawer = ASSETS_DIR / "screenshot_drawer_nav.png"
            await page.screenshot(path=str(shot_drawer), full_page=False)
            print(f"[✓] Captured {shot_drawer.name} ({shot_drawer.stat().st_size} bytes)")

            # Close drawer
            try:
                await page.evaluate("() => { if (typeof closeDrawer === 'function') closeDrawer(); }")
                await page.wait_for_timeout(300)
            except Exception:
                pass

            # --- SCREENSHOT 3: Chunks Overview Panel ---
            print(f"[*] Navigating to {BASE_URL}/chunks (Chunks Overview)...")
            await page.goto(f"{BASE_URL}/chunks", timeout=30000, wait_until="domcontentloaded")
            await page.wait_for_timeout(800)
            shot_chunks = ASSETS_DIR / "screenshot_chunks_overview.png"
            await page.screenshot(path=str(shot_chunks), full_page=False)
            print(f"[✓] Captured {shot_chunks.name} ({shot_chunks.stat().st_size} bytes)")

            # --- SCREENSHOT 4: Chunk Editor View ---
            print(f"[*] Navigating to {BASE_URL}/chunks/edit/e68f0204 (Chunk Editor)...")
            await page.goto(f"{BASE_URL}/chunks/edit/e68f0204", timeout=30000, wait_until="domcontentloaded")
            await page.wait_for_timeout(800)
            shot_editor = ASSETS_DIR / "screenshot_chunk_editor.png"
            await page.screenshot(path=str(shot_editor), full_page=False)
            print(f"[✓] Captured {shot_editor.name} ({shot_editor.stat().st_size} bytes)")

            # --- SCREENSHOT 5: Categories Panel ---
            print(f"[*] Navigating to {BASE_URL}/categories (Categories)...")
            await page.goto(f"{BASE_URL}/categories", timeout=30000, wait_until="domcontentloaded")
            await page.wait_for_timeout(800)
            shot_cats = ASSETS_DIR / "screenshot_categories_panel.png"
            await page.screenshot(path=str(shot_cats), full_page=False)
            print(f"[✓] Captured {shot_cats.name} ({shot_cats.stat().st_size} bytes)")

            # --- SCREENSHOT 6: Markdown Compiler & Export Panel ---
            print(f"[*] Navigating to {BASE_URL}/compile (Compiler & Export)...")
            await page.goto(f"{BASE_URL}/compile", timeout=30000, wait_until="domcontentloaded")
            await page.wait_for_timeout(800)
            shot_compile = ASSETS_DIR / "screenshot_compile_panel.png"
            await page.screenshot(path=str(shot_compile), full_page=False)
            print(f"[✓] Captured {shot_compile.name} ({shot_compile.stat().st_size} bytes)")

            # --- SCREENSHOT 7: Tools Hub Panel ---
            print(f"[*] Navigating to {BASE_URL}/tools (Tools Hub)...")
            await page.goto(f"{BASE_URL}/tools", timeout=30000, wait_until="domcontentloaded")
            await page.wait_for_timeout(800)
            shot_tools = ASSETS_DIR / "screenshot_tools_hub.png"
            await page.screenshot(path=str(shot_tools), full_page=False)
            print(f"[✓] Captured {shot_tools.name} ({shot_tools.stat().st_size} bytes)")

            # Clean teardown
            await page.close()
            await context.close()
            await browser.close()
            print("[✓] Headless Chromium browser closed cleanly.")

    finally:
        print("[*] Terminating Doc_Chunker Flask server process...")
        server_process.terminate()
        try:
            server_process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            server_process.kill()
        print("[✓] Server terminated.")

    print("=" * 65)
    print("ALL SCREENSHOTS CAPTURED SUCCESSFULLY!")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(capture_screenshots())
