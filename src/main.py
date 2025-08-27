# src/main.py
import os, sys, time, traceback
from pathlib import Path
from tqdm import tqdm
from dotenv import load_dotenv
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from src.config import BASE_URL, HEADLESS, WAIT_SECS, REQUEST_DELAY_SECS, SAVE_HTML
from src.selenium_scraper.driver import make_driver
from src.selenium_scraper.tree import find_toc_root, expand_all, collect_links
from src.selenium_scraper.page import extract_page
from src.utils import write_jsonl, write_csv, sleep_safely

def log(msg: str):
    print(msg, flush=True)

def wait_ready(driver, timeout: int):
    end = time.time() + timeout
    while time.time() < end:
        try:
            state = driver.execute_script("return document.readyState")
            if state == "complete":
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False

def diag_dump(driver, name: str):
    Path("data/debug").mkdir(parents=True, exist_ok=True)
    try:
        driver.save_screenshot(f"data/debug/{name}.png")
    except Exception:
        pass
    try:
        html = driver.page_source
        Path(f"data/debug/{name}.html").write_text(html, encoding="utf-8")
    except Exception:
        pass

def _dismiss_banners(driver):
    # Best-effort cookie/consent close
    xpaths = [
        "//button[contains(.,'Accept')]", "//button[contains(.,'I agree')]",
        "//button[contains(.,'Got it')]", "//button[contains(.,'Agree')]",
        "//button[contains(.,'OK')]", "//button[contains(.,'Continue')]",
    ]
    for xp in xpaths:
        try:
            btns = driver.find_elements(By.XPATH, xp)
            if btns:
                btns[0].click()
                time.sleep(0.2)
        except Exception:
            pass

def _find_toc_root_any_frame(driver):
    # Try default content first
    r = find_toc_root(driver)
    if r:
        return r
    # Try iframes
    frames = driver.find_elements(By.TAG_NAME, "iframe")
    log(f"   TOC not in main DOM. Checking {len(frames)} iframe(s)...")
    for idx, fr in enumerate(frames):
        try:
            driver.switch_to.frame(fr)
            r = find_toc_root(driver)
            driver.switch_to.default_content()
            if r:
                log(f"   TOC found inside iframe #{idx}.")
                # Switch again to return the element context
                driver.switch_to.frame(fr)
                return r
        except Exception:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass
    return None

def run():
    load_dotenv()
    headless_env = os.getenv("HEADLESS")
    headless = HEADLESS if headless_env is None else (headless_env not in ("0","false","False"))

    log("Step 0: Launching Chrome…")
    driver = make_driver(headless=headless)

    try:
        log(f"Step 1: Loading URL → {BASE_URL}")
        driver.get(BASE_URL)

        if not wait_ready(driver, WAIT_SECS):
            log("   Warning: document.readyState did not reach 'complete' in time.")

        # Ensure body is present
        WebDriverWait(driver, WAIT_SECS).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "body"))
        )
        log(f"   Loaded. Title: {driver.title!r}")
        _dismiss_banners(driver)

        log("Step 2: Locating left TOC…")
        toc_root = _find_toc_root_any_frame(driver)
        if not toc_root:
            log("   ERROR: Could not find the left tutorial TOC.")
            diag_dump(driver, "no_toc_found")
            raise RuntimeError("Could not find the left tutorial TOC on the page.")

        log("Step 3: Expanding the TOC…")
        expand_all(driver, toc_root, wait_secs=WAIT_SECS, log=log)

        log("Step 4: Collecting links from TOC…")
        links = collect_links(driver, toc_root)
        log(f"   Found {len(links)} sub-headers to scrape.")
        if not links:
            diag_dump(driver, "toc_but_no_links")
            raise RuntimeError("TOC found but contains no links. Selectors may need updating.")

        log("Step 5: Visiting each page and extracting fields…")
        records = []
        visited = set()
        for i, (title, href) in enumerate(tqdm(links, desc="Scraping", unit="page")):
            if href in visited:
                continue
            visited.add(href)
            try:
                rec = extract_page(driver, href, wait_secs=WAIT_SECS, save_html=SAVE_HTML)
                rec["toc_title"] = title
                records.append(rec)
            except Exception as e:
                records.append({
                    "toc_title": title, "url": href, "error": str(e),
                    "title": "", "path": [], "meta": {}, "text": "", "video_links": []
                })
            # Progress log every 10 pages
            if (i + 1) % 10 == 0:
                log(f"   Progress: {i+1}/{len(links)} pages done.")
            sleep_safely(float(os.getenv("REQUEST_DELAY_SECS", REQUEST_DELAY_SECS)))

        log("Step 6: Saving outputs…")
        write_jsonl(records, "data/processed/tutorials.jsonl")
        write_csv(records, "data/processed/tutorials.csv")
        log("Done ✅  Saved: data/processed/tutorials.jsonl and data/processed/tutorials.csv")

    except Exception as e:
        log(f"\nFATAL: {e}")
        traceback.print_exc()
        diag_dump(driver, "fatal_error")
        sys.exit(1)
    finally:
        try:
            driver.quit()
        except Exception:
            pass

if __name__ == "__main__":
    run()
