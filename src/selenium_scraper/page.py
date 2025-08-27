import re, time
from typing import Dict, List
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

VIDEO_XPATH = (
    "//a["
    "contains(translate(normalize-space(text()), 'VIDEO', 'video'), 'video')"
    " or contains(@href,'youtube')"
    " or (contains(@href,'autodesk') and contains(@href,'video'))"
    "]"
)

def _txt(el):
    try:
        return el.text.strip()
    except Exception:
        return ""

def extract_page(driver, url: str, wait_secs: int = 10, save_html: bool = False) -> Dict:
    driver.get(url)
    WebDriverWait(driver, wait_secs).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "h1, article, main"))
    )
    time.sleep(0.2)

    # Title
    title = ""
    for sel in ["article h1", "main h1", "h1"]:
        els = driver.find_elements(By.CSS_SELECTOR, sel)
        if els:
            title = _txt(els[0])
            break

    # Breadcrumb / path
    path: List[str] = []
    for sel in ['nav.breadcrumb a', 'nav[aria-label*="breadcrumb"] a', 'ul.breadcrumb a']:
        b = driver.find_elements(By.CSS_SELECTOR, sel)
        if b:
            path = [_txt(x) for x in b]
            break

    # HTML + optional save
    html = driver.page_source
    if save_html:
        from pathlib import Path
        Path("data/raw").mkdir(parents=True, exist_ok=True)
        safe = re.sub(r'[^a-zA-Z0-9_-]+', '_', title)[:100] or "page"
        Path(f"data/raw/{safe}.html").write_text(html, encoding='utf-8')

    soup = BeautifulSoup(html, "html.parser")

    # Metadata (table/dl near the top)
    meta: Dict[str, str] = {}
    info_block = soup.select_one("article table, main table, article dl, main dl")
    if info_block:
        if info_block.name == "table":
            for row in info_block.select("tr"):
                cols = [c.get_text(strip=True) for c in row.select("th,td")]
                if len(cols) >= 2:
                    meta[cols[0].rstrip(':')] = cols[1]
        elif info_block.name == "dl":
            dts = info_block.select("dt")
            dds = info_block.select("dd")
            for dt, dd in zip(dts, dds):
                meta[dt.get_text(strip=True).rstrip(':')] = dd.get_text(strip=True)

    # Body text for RAG
    body_text = ""
    for sel in ["article", "main"]:
        art = soup.select_one(sel)
        if art:
            for bad in art.select("nav,aside,script,style"):
                bad.decompose()
            body_text = "\n\n".join(p.get_text(" ", strip=True) for p in art.select("p"))
            break

    # Video links (collect from DOM via XPath)
    video_links: List[str] = []
    anchors = driver.find_elements(By.XPATH, VIDEO_XPATH)
    for a in anchors:
        try:
            href = a.get_attribute("href")
            txt = a.text.strip()
            if href and (txt or "video" in (href or "").lower()):
                video_links.append(href)
        except Exception:
            pass

    # ===== CHANGED: dedupe by GUID (not by full URL) =====
    def _guid(u: str):
        m = re.search(r'guid=([A-Za-z0-9-]+)', u or '')
        return m.group(1) if m else None

    unique_by_guid: Dict[str, str] = {}
    for href in video_links:
        g = _guid(href)
        if g and g not in unique_by_guid:
            unique_by_guid[g] = href

    # If we found GUIDs, use those; otherwise fall back to plain URL-dedupe
    if unique_by_guid:
        vids = list(unique_by_guid.values())
    else:
        seen, vids = set(), []
        for v in video_links:
            if v not in seen:
                seen.add(v)
                vids.append(v)
    # ===== END CHANGE =====

    return {
        "title": title,
        "url": url,
        "path": path,
        "meta": meta,
        "text": body_text,
        "video_links": vids,
    }
