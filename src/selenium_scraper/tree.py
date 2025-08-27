# src/selenium_scraper/tree.py
import time
from typing import List, Tuple, Callable, Optional
from selenium.webdriver.common.by import By
from selenium.common.exceptions import (
    StaleElementReferenceException,
    ElementClickInterceptedException,
    ElementNotInteractableException,
)

TOC_SELECTORS = [
    'nav[aria-label*="contents"]',
    'nav#toc',
    'div#toc',
    'div.toc, div[class*="toc"]',
    'nav.sidenav, nav.leftnav',
    'div[class*="sidenav"]',
]

def find_toc_root(driver):
    for sel in TOC_SELECTORS:
        els = driver.find_elements(By.CSS_SELECTOR, sel)
        if els:
            return els[0]
    return None

def _candidate_toggles(toc_root):
    """Return a list of elements that look like expandable toggles."""
    selectors = [
        '[aria-expanded="false"]',
        'button[aria-expanded="false"]',
        'li[aria-expanded="false"] > button',
        'li:not(.expanded) > button',
        'button.toc-toggle',
        '.toc-toggle',
        '.expand, .collapsed, .collapse',
        '[role="button"][aria-expanded="false"]',
    ]
    out = []
    seen = set()
    for sel in selectors:
        for el in toc_root.find_elements(By.CSS_SELECTOR, sel):
            try:
                key = el.id
            except Exception:
                key = None
            if key and key in seen:
                continue
            seen.add(key)
            out.append(el)
    return out

def expand_all(
    driver,
    toc_root,
    wait_secs: int = 10,
    max_passes: int = 40,
    max_clicks: int = 1500,
    log: Optional[Callable[[str], None]] = None,
):
    """
    Robust expand: multiple passes, bounded clicks, and progress logs.
    Breaks if links/toggles stop changing to avoid infinite loops.
    """
    clicks = 0
    last_link_count = -1
    for p in range(1, max_passes + 1):
        anchors = toc_root.find_elements(By.CSS_SELECTOR, 'a[href]')
        link_count = len(anchors)
        toggles = _candidate_toggles(toc_root)
        if log:
            log(f"   [expand pass {p}] links={link_count} collapsed={len(toggles)} clicks={clicks}")

        if not toggles:
            if log: log("   No collapsed toggles left  stopping expand.")
            break

        changed = False
        for btn in toggles:
            try:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                driver.execute_script("arguments[0].click();", btn)  # JS click for reliability
                time.sleep(0.06)
                clicks += 1
                changed = True
                if clicks >= max_clicks:
                    if log: log("   Reached max_clicks  stopping expand.")
                    return
            except (StaleElementReferenceException, ElementClickInterceptedException, ElementNotInteractableException):
                continue
            except Exception:
                continue

        time.sleep(0.25)

        # Recount after interactions
        new_link_count = len(toc_root.find_elements(By.CSS_SELECTOR, 'a[href]'))
        if not changed or new_link_count <= last_link_count:
            if log: log("   No growth detected  stopping expand.")
            break
        last_link_count = new_link_count

def collect_links(driver, toc_root) -> List[Tuple[str, str]]:
    """Return list of (title, href) for every anchor in the TOC, de-duplicated."""
    links: List[Tuple[str, str]] = []
    anchors = toc_root.find_elements(By.CSS_SELECTOR, 'a[href]')
    for a in anchors:
        title = (a.text or "").strip()
        href = a.get_attribute('href')
        if title and href:
            links.append((title, href))

    seen = set()
    deduped: List[Tuple[str, str]] = []
    for title, href in links:
        if href not in seen:
            seen.add(href)
            deduped.append((title, href))
    return deduped
