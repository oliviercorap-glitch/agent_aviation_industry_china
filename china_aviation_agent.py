import os
import json
import logging
import hashlib
import requests
import time
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from openai import OpenAI
import markdown

# --- Configuration -----------------------------------------------------------
load_dotenv()
LOG_FILE = Path("logs/agent_gse.log")
SEEN_FILE = Path("seen_gse_articles.json")
Path("logs").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(LOG_FILE, encoding="utf-8")],
)
log = logging.getLogger(__name__)

# =============================================================================
#  EXPANDED KEYWORDS : GSE + AIRPORTS + AIRLINES + COMPETITORS
# =============================================================================
KEYWORDS_GSE = [
    "ground support", "gse", "tug", "tractor", "loader", "de-icer", "gpu",
    "towbar", "baggage", "passenger boarding bridge", "air start unit",
    "belt loader", "conveyor belt", "staircase", "dolly", "catering truck",
    "lavatory truck", "water truck", "apron", "ramp", "electric ground support",
    "hybrid gse", "lithium battery gse", "autonomous gse", "maintenance gse",
    "mro ground",
    "地勤设备", "地面支持设备", "行李拖车", "客梯车", "电源车", "气源车",
    "除冰车", "装载机", "传送带车", "飞机牵引车", "新能源地勤", "电动地勤",
    "airport opening", "new runway", "terminal expansion", "airport expansion",
    "passenger record", "traffic record", "cargo volume", "load factor",
    "inauguration", "infrastructure investment",
    "机场", "航空", "航站楼", "停机坪", "扩建", "招标", "采购", "项目", "投运",
    "吞吐量", "旅客", "货邮", "航班", "机位", "远机位", "新机场", "新航站楼",
    "旅客吞吐量创新高", "航班量",
    "airline order", "fleet delivery", "fleet expansion", "airline profit",
    "airline loss", "bankruptcy", "revenue", "EBIT",
    "Air China", "China Eastern", "China Southern", "Hainan Airlines",
    "中国国航", "国航", "中国东方航空", "东方航空", "东航",
    "中国南方航空", "南方航空", "南航", "海南航空", "海航",
    "厦门航空", "厦航", "深圳航空", "深航", "春秋航空", "春秋",
    "吉祥航空", "吉祥", "四川航空", "川航", "山东航空", "山航",
    "订购", "交付", "机队", "盈利", "亏损", "营收", "净利润",
    "复航", "停飞", "航线", "新开航线", "恢复", "破产", "重组",
    "emission regulation", "electric ramp", "diesel ban",
    "steel price", "aluminium", "lithium", "battery cost",
    "semiconductor", "chip shortage", "supply chain disruption",
    "碳中和机场", "电动化", "柴油车禁行", "carbon peak",
    "Belt and Road", "BRI", "tariff", "trade war", "EU tariffs",
    "一带一路", "关税",
    "TLD Group", "TLD", "Alvest", "JBT Corporation", "JBT",
    "Oshkosh AeroTech", "Oshkosh", "Textron GSE", "Textron",
    "Tug Technologies", "Tronair", "ITW GSE", "Fast Global Solutions",
    "Fast Global", "WASP GSE", "Mallaghan", "Mallaghan Engineering",
    "Goldhofer", "MULAG", "HYDRO", "Guinault", "Cavotec",
    "AERO Specialties", "Aero Specialties", "Global Ground Support",
    "DOLL", "Nepean", "Gate GSE", "Clyde Machines", "Douglas Equipment",
    "FgFlightline", "AMSS GSE", "Avia Equipment", "Teleflex Lionel-Dupont",
    "CargoTec", "Bharat Earth Movers", "Bliss-Fox GSE",
    "Imai Aero-Equipment", "Toyota Industries", "JCB", "Jungheinrich",
    "Komatsu", "Cobus", "Rheinmetall", "Vestergaard", "Trepel",
    "AGSE", "Aviapartner", "Havas Ground Handling",
    "Alliance Ground International", "Watkins Aircraft Support",
    "Handiquip GSE", "MAK Controls", "Unitron", "Enersys", "RASAKTI",
    "ATEC Inc", "Joloda Hydraroll", "Wollard International",
    "BEUMER Group", "Powervamp", "Acsoon", "Velocity Airport Solutions",
    "Red Box International", "Power Systems International", "PSI",
    "GB Barberi", "Jetall GPU", "Aeromax GSE", "Current Power",
    "MRCCS", "Bertoli Power Units",
    "Weihai Guangtai", "Guangtai", "威海广泰",
    "CIMC Tianda", "中集天达",
    "Jiangsu Tianyi", "Tianyi", "江苏天一",
    "Shenzhen TECHKING", "TECHKING", "深圳达航",
    "Hangfu", "航福",
    "Shanghai Jiajie", "上海嘉捷",
    "Guangzhou Jinhaoyang", "广州金浩阳",
    "Shenyang Tianhua", "沈阳天华",
    "Shandong Tianhe", "山东天河",
    "Zhejiang Goodsense", "浙江中力",
    "Alha GSE", "Shanghai Ifly", "Ifly GSE",
    "TCR Group", "TCR", "Mercury GSE", "Lufthansa Technik",
    "GE Aviation", "AFI KLM E&M", "ST Aerospace", "MTU Maintenance"
]

# =============================================================================
#  SOURCES (FUNCTIONAL)
# =============================================================================
SOURCES = [
    {
        "nom": "Bidcenter (China - Tenders)",
        "url": "https://www.bidcenter.com.cn",
        "type": "scrape_bidcenter",
        "base_url": "https://www.bidcenter.com.cn",
        "encoding": "utf-8"
    },
    {
        "nom": "China Airport News",
        "url": "http://fuwu.caacnews.com.cn/1/5/index.html",
        "type": "scrape_generic",
        "selector": "div.newsList ul li a, .list li a, a",
        "base_url": "http://fuwu.caacnews.com.cn",
        "encoding": "utf-8"
    },
    {
        "nom": "CARNOC.com (China)",
        "url": "https://www.carnoc.com/",
        "type": "scrape_generic",
        "selector": "div.news_list a, .article_list a, a",
        "base_url": "https://www.carnoc.com",
        "encoding": "utf-8"
    },
    {
        "nom": "CAAC News (China)",
        "url": "http://www.caac.gov.cn/PHONE/ZTZL/",
        "type": "scrape_caac",
        "base_url": "http://www.caac.gov.cn"
    },
    {
        "nom": "Ground Handling International",
        "url": "https://www.groundhandling.com/",
        "type": "scrape_generic",
        "selector": "article h3 a, .post-title a, a",
        "base_url": "https://www.groundhandling.com",
    },
    {
        "nom": "CGTN - Aviation",
        "url": "https://www.cgtn.com/",
        "type": "scrape_generic",
        "selector": "div.newsList a, a",
        "base_url": "https://www.cgtn.com",
        "encoding": "utf-8"
    }
]

# --- UTILITY FUNCTIONS --------------------------------------------------------
def normaliser_url(url, base=None):
    if not url:
        return None
    if base:
        url = urljoin(base, url)
    parsed = urlparse(url)
    url_propre = parsed._replace(query="", fragment="").geturl()
    if url_propre.endswith('/'):
        url_propre = url_propre[:-1]
    return url_propre

def charger_vus():
    if SEEN_FILE.exists():
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            try:
                return set(json.load(f))
            except:
                return set()
    return set()

def sauvegarder_vus(vus):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(vus), f, ensure_ascii=False, indent=2)

def requeter_avec_retry(url, retries=3, **kwargs):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3"
    }
    if "headers" in kwargs:
        headers.update(kwargs.pop("headers"))
    for i in range(retries):
        try:
            resp = requests.get(url, timeout=30, headers=headers, **kwargs)
            resp.raise_for_status()
            return resp
        except Exception as e:
            log.warning(f"Attempt {i+1}/{retries} failed for {url} : {e}")
            time.sleep(2 ** i)
    return None

def scrape_caac(source):
    articles = []
    resp = requeter_avec_retry(source["url"])
    if not resp:
        return articles
    try:
        soup = BeautifulSoup(resp.content, "html.parser", from_encoding='utf-8')
        links = soup.find_all('a', href=True)
        for link in links[:15]:
            titre = link.get_text(strip=True)
            if not titre or len(titre) < 10:
                continue
            href = link.get('href')
            if href:
                href = normaliser_url(href, source["base_url"])
            if titre and href:
                articles.append({
                    "source": source["nom"],
                    "titre": titre[:150],
                    "lien": href,
                    "desc": "",
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "id": hashlib.md5((titre + href).encode()).hexdigest(),
                })
        log.info(f"  Scraped {source['nom']}: {len(articles)} articles")
    except Exception as e:
        log.warning(f"Error parsing {source['nom']} : {e}")
    return articles

def scrape_generic(source):
    articles = []
    resp = requeter_avec_retry(source["url"])
    if not resp:
        return articles
    try:
        encoding = source.get('encoding', 'utf-8')
        soup = BeautifulSoup(resp.content, "html.parser", from_encoding=encoding)
        links = soup.select(source["selector"])
        unique_links = {}
        for link in links:
            href = link.get('href')
            titre = link.get_text(strip=True)
            if not href or not titre or len(titre) < 10:
                continue
            href = normaliser_url(href, source["base_url"])
            if href:
                unique_links[href] = titre
        for href, titre in list(unique_links.items())[:20]:
            articles.append({
                "source": source["nom"],
                "titre": titre[:150],
                "lien": href,
                "desc": "",
                "date": datetime.now().strftime("%Y-%m-%d"),
                "id": hashlib.md5((titre + href).encode()).hexdigest(),
            })
        log.info(f"  Scraped {source['nom']}: {len(articles)} articles")
    except Exception as e:
        log.warning(f"Error scraping {source['nom']} : {e}")
    return articles

def scrape_bidcenter(source):
    articles = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.bidcenter.com.cn/",
        "Accept-Language": "zh-CN,zh;q=0.9"
    }
    resp = requeter_avec_retry(source["url"], headers=headers)
    if not resp:
        return articles
    try:
        soup = BeautifulSoup(resp.content, "html.parser", from_encoding='utf-8')
        links = soup.select('div.tender_list a, ul.tender-list a, .gg_list a, table a, .list-item a')
        if not links:
            links = soup.find_all('a', href=True)
        unique_links = {}
        for link in links:
            href = link.get('href')
            titre = link.get_text(strip=True)
            if not href or not titre or len(titre) < 8:
                continue
            mots_exclus = ['首页', '上一页', '下一页', '末页', '登录', '注册', '发布', '搜索']
            if any(mot in titre for mot in mots_exclus):
                continue
            href = normaliser_url(href, source["base_url"])
            if href and 'bidcenter.com.cn' in href:
                unique_links[href] = titre
        for href, titre in list(unique_links.items())[:15]:
            articles.append({
                "source": source["nom"],
                "titre": titre[:150],
                "lien": href,
                "desc": "",
                "date": datetime.now().strftime("%Y-%m-%d"),
                "id": hashlib.md5((titre + href).encode()).hexdigest(),
            })
        log.info(f"  Scraped {source['nom']}: {len(articles)} tenders")
    except Exception as e:
        log.warning(f"Error scraping {source['nom']} : {e}")
    return articles

def collecter_tous_articles():
    tous_articles = []
    for source in SOURCES:
        log.info(f"Collecting from : {source['nom']}")
        if source["type"] == "scrape_caac":
            articles = scrape_caac(source)
        elif source["type"] == "scrape_bidcenter":
            articles = scrape_bidcenter(source)
        else:
            articles = scrape_generic(source)
        tous_articles.extend(articles)
        time.sleep(1.5)
    log.info(f"Total raw articles collected: {len(tous_articles)}")
    return tous_articles

def filtrer_pertinents(articles, vus):
    nouveaux = []
    for a in articles:
        if a["id"] in vus:
            continue
        texte = (a["titre"] + " " + a.get("desc", "")).lower()
        if any(kw.lower() in texte for kw in KEYWORDS_GSE):
            nouveaux.append(a)
    log.info(f"Relevant articles (GSE + macro signals + competitors): {len(nouveaux)}")
    return nouveaux


# =============================================================================
#  DEEPSEEK — IMPROVED PROMPTS WITH STRUCTURED DELIMITERS
# =============================================================================

SYSTEM_PROMPT_GSE = """You are a senior strategy analyst advising the CEO of TLD Group, a global GSE (Ground Support Equipment) manufacturer and lessor operating primarily in China and Asia-Pacific.

Your role: translate raw news signals into actionable commercial and industrial intelligence.

ANALYSIS SCOPE — do not limit yourself to articles that explicitly mention equipment:
- Airport openings, capacity expansions, traffic records → leading demand indicators (quantify: +5% traffic ≈ +10 aircraft tractors per hub)
- Airline fleet orders, deliveries, profitability → fleet-driven GSE procurement cycles
- Competitor announcements (JBT, Textron, Guangtai, etc.) → competitive threats or market gaps
- Raw material costs (steel, aluminium, lithium, semiconductors) → margin pressure signals
- M&A among ground handlers (Swissport, Menzies, Dnata) → contract consolidation risk
- Trade policy (tariffs, BRI) → supply chain and pricing implications
- Environmental regulations in China → electrification timeline and diesel phase-out pace

IMPACT CLASSIFICATION:
- CRITICAL: Immediate action required within 48h (major competitor move, urgent tender, direct threat/opportunity)
- IMPORTANT: Action required this week (significant market shift, pricing signal, client development)
- WATCH: Monitor closely, no immediate action (emerging trend, early-stage development)
- INFO: Background context, file for reference

OUTPUT FORMAT — You must use EXACTLY this structure. Do not deviate.

For each signal, output:
===SIGNAL_START===
SIGNAL_ID: [number, e.g. 1]
IMPACT: [CRITICAL | IMPORTANT | WATCH | INFO]
HEADLINE: [One sharp sentence summarizing the signal — max 15 words]
READING: [2-3 sentences explaining what happened and why it matters for the GSE market]
BUSINESS_IMPACT: [2-3 sentences on concrete commercial/financial consequences for TLD — volumes, margins, contracts, competition]
ACTION: [1-2 sentences on the recommended action — specific, time-bound, named if possible]
===SIGNAL_END===

After all signals, output the closing section EXACTLY as follows:
===SUMMARY_START===
EXECUTIVE_SUMMARY: [4-5 sentences max. Written for an executive committee presentation. What happened, what it means, what we should do.]
WATCH_1: [Key indicator #1 to monitor this week]
WATCH_2: [Key indicator #2 to monitor this week]
WATCH_3: [Key indicator #3 to monitor this week]
MAIN_RISK: [The single biggest risk for TLD's GSE business in China this week — one sentence]
===SUMMARY_END===

Rules:
- Write in English
- Be specific and quantitative when possible (volumes, %, timelines)
- No bullet points inside field values — use plain prose
- Do not add any text outside the delimited blocks
- If fewer than 3 signals are meaningful, still output the SUMMARY block
"""

def construire_prompt_user(articles):
    date_str = datetime.now().strftime("%d %B %Y")
    articles_txt = ""
    for i, a in enumerate(articles, 1):
        articles_txt += f"\n[{i}] SOURCE: {a['source']}\n"
        articles_txt += f"    TITLE: {a['titre']}\n"
        articles_txt += f"    URL: {a['lien']}\n"
        if a.get('desc'):
            articles_txt += f"    EXCERPT: {a['desc'][:200]}\n"

    return f"""GSE STRATEGIC WATCH — China / Asia-Pacific
Date: {date_str}
Articles to analyze: {len(articles)}

{articles_txt}

Analyze each article that carries a meaningful signal for TLD Group's GSE business. Skip pure noise (irrelevant articles with no connection to the GSE market or its demand drivers). Output ONLY the structured blocks defined in your instructions."""


def analyser_avec_deepseek(articles):
    if not articles:
        return ""

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY not set")

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com/v1")

    log.info(f"Sending {len(articles)} articles to DeepSeek...")
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_GSE},
                {"role": "user", "content": construire_prompt_user(articles)}
            ],
            max_tokens=4096,
            temperature=0.2  # Lower temperature = more consistent formatting
        )
        return response.choices[0].message.content
    except Exception as e:
        log.error(f"DeepSeek error : {e}")
        return ""


# =============================================================================
#  PARSER — Delimiter-based (no fragile regex)
# =============================================================================

def parser_analyse(raw_text):
    """Parse the structured DeepSeek output into clean Python dicts."""
    signals = []
    summary = {
        "executive_summary": "",
        "watch": [],
        "main_risk": ""
    }

    if not raw_text:
        return signals, summary

    def extract_field(block, field):
        """Extract a named field value from a delimited block."""
        pattern = rf'^{field}:\s*(.+?)(?=\n[A-Z_]+:|$)'
        match = re.search(pattern, block, re.MULTILINE | re.DOTALL)
        if match:
            return match.group(1).strip()
        return ""

    # --- Parse signals ---
    signal_blocks = re.findall(
        r'===SIGNAL_START===(.*?)===SIGNAL_END===',
        raw_text,
        re.DOTALL
    )
    for block in signal_blocks:
        signal = {
            "id": extract_field(block, "SIGNAL_ID"),
            "impact": extract_field(block, "IMPACT").upper() or "INFO",
            "headline": extract_field(block, "HEADLINE"),
            "reading": extract_field(block, "READING"),
            "business_impact": extract_field(block, "BUSINESS_IMPACT"),
            "action": extract_field(block, "ACTION"),
        }
        # Validate impact level
        if signal["impact"] not in ("CRITICAL", "IMPORTANT", "WATCH", "INFO"):
            signal["impact"] = "INFO"
        signals.append(signal)

    # --- Parse summary ---
    summary_match = re.search(
        r'===SUMMARY_START===(.*?)===SUMMARY_END===',
        raw_text,
        re.DOTALL
    )
    if summary_match:
        block = summary_match.group(1)
        summary["executive_summary"] = extract_field(block, "EXECUTIVE_SUMMARY")
        summary["main_risk"] = extract_field(block, "MAIN_RISK")
        for i in range(1, 4):
            watch = extract_field(block, f"WATCH_{i}")
            if watch:
                summary["watch"].append(watch)

    log.info(f"Parsed: {len(signals)} signals, summary={'yes' if summary['executive_summary'] else 'no'}")
    return signals, summary


# =============================================================================
#  HTML REPORT — Clean professional design
# =============================================================================

IMPACT_CONFIG = {
    "CRITICAL": {"label": "Critical",  "color": "#dc2626", "bg": "#fef2f2", "border": "#fecaca", "text": "#991b1b"},
    "IMPORTANT": {"label": "Important", "color": "#d97706", "bg": "#fffbeb", "border": "#fde68a", "text": "#92400e"},
    "WATCH":     {"label": "Watch",     "color": "#0369a1", "bg": "#f0f9ff", "border": "#bae6fd", "text": "#0c4a6e"},
    "INFO":      {"label": "Info",      "color": "#6b7280", "bg": "#f9fafb", "border": "#e5e7eb", "text": "#374151"},
}

def md(text):
    """Convert markdown to HTML, stripping outer <p> for inline use."""
    if not text:
        return ""
    html = markdown.markdown(text.strip(), extensions=['nl2br'])
    # Remove wrapping <p> tags for short single-paragraph content
    if html.count('<p>') == 1:
        html = re.sub(r'^<p>(.*)</p>$', r'\1', html, flags=re.DOTALL)
    return html

def generer_rapport(articles, signals, summary):
    now_full = datetime.now().strftime("%B %d, %Y")
    now_time = datetime.now().strftime("%H:%M")

    # Count by impact level
    counts = {"CRITICAL": 0, "IMPORTANT": 0, "WATCH": 0, "INFO": 0}
    for s in signals:
        counts[s["impact"]] = counts.get(s["impact"], 0) + 1

    # Map signals to source articles (by index)
    def get_article(idx):
        if idx < len(articles):
            return articles[idx]
        return None

    # --- Build signal cards HTML ---
    signals_html = ""
    if not signals:
        signals_html = '<p style="color:#6b7280; font-style:italic; padding:24px 0;">No significant signals identified today.</p>'
    else:
        for i, sig in enumerate(signals):
            cfg = IMPACT_CONFIG.get(sig["impact"], IMPACT_CONFIG["INFO"])
            article = get_article(i)
            source_block = ""
            if article:
                titre_esc = article['titre'].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                lien = article.get('lien', '#')
                source_nom = article['source']
                source_block = f'''
                <div class="signal-source">
                    <span class="source-label">Source</span>
                    <a href="{lien}" target="_blank" rel="noopener">{titre_esc}</a>
                    <span class="source-name">— {source_nom}</span>
                </div>'''

            signals_html += f'''
            <div class="signal-card" data-impact="{sig['impact'].lower()}">
                <div class="signal-card-header" style="border-left: 4px solid {cfg['color']};">
                    <div class="signal-badge" style="background:{cfg['bg']}; color:{cfg['text']}; border:1px solid {cfg['border']};">
                        {cfg['label']}
                    </div>
                    <h3 class="signal-headline">{md(sig['headline'])}</h3>
                </div>
                <div class="signal-body">
                    <div class="signal-section">
                        <div class="signal-section-label">Reading</div>
                        <div class="signal-section-text">{md(sig['reading'])}</div>
                    </div>
                    <div class="signal-section">
                        <div class="signal-section-label">Business impact</div>
                        <div class="signal-section-text">{md(sig['business_impact'])}</div>
                    </div>
                    <div class="signal-section signal-action">
                        <div class="signal-section-label">Recommended action</div>
                        <div class="signal-section-text">{md(sig['action'])}</div>
                    </div>
                    {source_block}
                </div>
            </div>'''

    # --- Build watch indicators HTML ---
    watch_html = ""
    for w in summary.get("watch", []):
        watch_html += f'<li>{md(w)}</li>'

    # --- Build impact counter pills ---
    counter_html = ""
    for level in ["CRITICAL", "IMPORTANT", "WATCH", "INFO"]:
        c = counts.get(level, 0)
        if c > 0:
            cfg = IMPACT_CONFIG[level]
            counter_html += f'<span class="counter-pill" style="background:{cfg["bg"]}; color:{cfg["text"]}; border:1px solid {cfg["border"]};">{c} {cfg["label"]}</span>'

    # --- Sources list ---
    sources_list = "".join(f'<li>{s["nom"]}</li>' for s in SOURCES)

    exec_summary_html = md(summary.get("executive_summary", ""))
    main_risk_html = md(summary.get("main_risk", ""))

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GSE Intelligence Brief — {now_full}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

  :root {{
    --ink: #0f172a;
    --ink-2: #334155;
    --ink-3: #64748b;
    --ink-4: #94a3b8;
    --surface: #ffffff;
    --surface-1: #f8fafc;
    --surface-2: #f1f5f9;
    --border: #e2e8f0;
    --border-2: #cbd5e1;
    --accent: #0f172a;
    --radius: 8px;
    --radius-lg: 12px;
  }}

  body {{
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    background: #f0f2f5;
    color: var(--ink);
    line-height: 1.6;
    padding: 32px 16px 64px;
  }}

  /* ── LAYOUT ── */
  .wrapper {{
    max-width: 900px;
    margin: 0 auto;
  }}

  /* ── MASTHEAD ── */
  .masthead {{
    background: var(--ink);
    color: white;
    border-radius: var(--radius-lg) var(--radius-lg) 0 0;
    padding: 28px 36px 24px;
  }}
  .masthead-eyebrow {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 10px;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #94a3b8;
    margin-bottom: 8px;
  }}
  .masthead-title {{
    font-size: 22px;
    font-weight: 600;
    letter-spacing: -0.02em;
    color: white;
    margin-bottom: 12px;
  }}
  .masthead-meta {{
    display: flex;
    align-items: center;
    gap: 20px;
    flex-wrap: wrap;
  }}
  .meta-item {{
    font-size: 13px;
    color: #94a3b8;
    display: flex;
    align-items: center;
    gap: 6px;
  }}
  .meta-item strong {{ color: #e2e8f0; font-weight: 500; }}
  .masthead-counters {{
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    margin-top: 16px;
    padding-top: 16px;
    border-top: 1px solid #1e293b;
  }}
  .counter-pill {{
    font-size: 11px;
    font-weight: 500;
    padding: 3px 10px;
    border-radius: 20px;
    letter-spacing: 0.02em;
  }}

  /* ── MAIN CARD BODY ── */
  .card-body {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-top: none;
    border-radius: 0 0 var(--radius-lg) var(--radius-lg);
    padding: 36px;
  }}

  /* ── SECTION HEADER ── */
  .section-header {{
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 20px;
    padding-bottom: 12px;
    border-bottom: 1px solid var(--border);
  }}
  .section-header h2 {{
    font-size: 13px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--ink-3);
  }}
  .section-divider {{
    margin: 36px 0;
    border: none;
    border-top: 1px solid var(--border);
  }}

  /* ── EXECUTIVE SUMMARY ── */
  .exec-panel {{
    background: var(--ink);
    border-radius: var(--radius-lg);
    padding: 24px 28px;
    margin-bottom: 32px;
    color: #e2e8f0;
    font-size: 15px;
    line-height: 1.75;
  }}
  .exec-panel-label {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 10px;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: #64748b;
    margin-bottom: 10px;
  }}

  /* ── SIGNAL CARDS ── */
  .signal-card {{
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    margin-bottom: 16px;
    overflow: hidden;
    transition: box-shadow 0.15s;
  }}
  .signal-card:hover {{ box-shadow: 0 4px 12px rgba(0,0,0,0.06); }}
  .signal-card-header {{
    padding: 16px 20px;
    background: var(--surface-1);
    display: flex;
    align-items: flex-start;
    gap: 12px;
  }}
  .signal-badge {{
    font-size: 11px;
    font-weight: 600;
    padding: 3px 9px;
    border-radius: 20px;
    white-space: nowrap;
    letter-spacing: 0.03em;
    margin-top: 2px;
    flex-shrink: 0;
  }}
  .signal-headline {{
    font-size: 15px;
    font-weight: 600;
    color: var(--ink);
    line-height: 1.4;
  }}
  .signal-headline p {{ margin: 0; }}
  .signal-body {{
    padding: 20px;
    display: grid;
    gap: 16px;
  }}
  .signal-section {{}}
  .signal-section-label {{
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--ink-4);
    margin-bottom: 4px;
  }}
  .signal-section-text {{
    font-size: 14px;
    color: var(--ink-2);
    line-height: 1.65;
  }}
  .signal-section-text p {{ margin: 0; }}
  .signal-action .signal-section-text {{
    color: var(--ink);
    font-weight: 500;
  }}
  .signal-source {{
    padding-top: 12px;
    border-top: 1px dashed var(--border);
    font-size: 12px;
    color: var(--ink-4);
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    align-items: center;
  }}
  .source-label {{
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-size: 10px;
    color: var(--ink-4);
    margin-right: 4px;
  }}
  .signal-source a {{
    color: #2563eb;
    text-decoration: none;
    font-weight: 500;
  }}
  .signal-source a:hover {{ text-decoration: underline; }}
  .source-name {{ color: var(--ink-4); }}

  /* ── WATCH & RISK PANELS ── */
  .watch-panel {{
    background: #fffbeb;
    border: 1px solid #fde68a;
    border-radius: var(--radius-lg);
    padding: 20px 24px;
    margin-bottom: 16px;
  }}
  .watch-panel-label {{
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #92400e;
    margin-bottom: 12px;
  }}
  .watch-panel ol {{
    padding-left: 20px;
    display: grid;
    gap: 6px;
  }}
  .watch-panel li {{
    font-size: 14px;
    color: #78350f;
    line-height: 1.5;
  }}
  .watch-panel li p {{ margin: 0; }}
  .risk-panel {{
    background: #fef2f2;
    border: 1px solid #fecaca;
    border-radius: var(--radius-lg);
    padding: 20px 24px;
  }}
  .risk-panel-label {{
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #991b1b;
    margin-bottom: 8px;
  }}
  .risk-panel-text {{
    font-size: 14px;
    color: #7f1d1d;
    line-height: 1.6;
    font-weight: 500;
  }}
  .risk-panel-text p {{ margin: 0; }}

  /* ── SOURCES FOOTER ── */
  .sources-panel {{
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 16px 20px;
    margin-top: 36px;
  }}
  .sources-panel-label {{
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--ink-4);
    margin-bottom: 10px;
  }}
  .sources-panel ul {{
    list-style: none;
    display: flex;
    flex-wrap: wrap;
    gap: 6px 0;
    column-gap: 24px;
    columns: 2;
  }}
  .sources-panel li {{
    font-size: 12px;
    color: var(--ink-3);
    break-inside: avoid;
  }}
  .sources-panel li::before {{
    content: "·";
    margin-right: 6px;
    color: var(--ink-4);
  }}

  /* ── FOOTER ── */
  .page-footer {{
    text-align: center;
    font-size: 11px;
    color: var(--ink-4);
    margin-top: 24px;
    font-family: 'IBM Plex Mono', monospace;
    letter-spacing: 0.04em;
  }}

  /* ── EMPTY STATE ── */
  .no-news {{
    text-align: center;
    padding: 48px 0;
    color: var(--ink-3);
    font-size: 14px;
  }}

  @media (max-width: 600px) {{
    body {{ padding: 12px 8px 48px; }}
    .masthead, .card-body {{ padding: 20px 16px; }}
    .sources-panel ul {{ columns: 1; }}
  }}
</style>
</head>
<body>
<div class="wrapper">

  <!-- MASTHEAD -->
  <div class="masthead">
    <div class="masthead-eyebrow">TLD Group · Market Intelligence</div>
    <div class="masthead-title">GSE Intelligence Brief</div>
    <div class="masthead-meta">
      <div class="meta-item">
        <span>Date</span>
        <strong>{now_full}</strong>
      </div>
      <div class="meta-item">
        <span>Generated</span>
        <strong>{now_time}</strong>
      </div>
      <div class="meta-item">
        <span>Articles analyzed</span>
        <strong>{len(articles)}</strong>
      </div>
      <div class="meta-item">
        <span>Signals identified</span>
        <strong>{len(signals)}</strong>
      </div>
    </div>
    {f'<div class="masthead-counters">{counter_html}</div>' if counter_html else ''}
  </div>

  <!-- MAIN BODY -->
  <div class="card-body">

    <!-- Executive Summary -->
    {f'''
    <div class="exec-panel">
      <div class="exec-panel-label">Executive summary</div>
      {exec_summary_html if exec_summary_html else '<em style="color:#475569;">No summary available.</em>'}
    </div>
    ''' if exec_summary_html else ''}

    <!-- Signals -->
    <div class="section-header">
      <h2>Signals</h2>
    </div>
    {signals_html}

    {f'''
    <hr class="section-divider">

    <!-- To Watch -->
    <div class="section-header">
      <h2>To watch this week</h2>
    </div>
    <div class="watch-panel">
      <div class="watch-panel-label">Key indicators</div>
      <ol>
        {watch_html}
      </ol>
    </div>

    <!-- Main Risk -->
    <div class="risk-panel">
      <div class="risk-panel-label">Main risk</div>
      <div class="risk-panel-text">{main_risk_html}</div>
    </div>
    ''' if watch_html or main_risk_html else ''}

    <!-- Sources -->
    <div class="sources-panel">
      <div class="sources-panel-label">Monitored sources</div>
      <ul>
        {sources_list}
      </ul>
    </div>

  </div><!-- /card-body -->

  <div class="page-footer">
    GSE Intelligence Agent · Powered by DeepSeek · {now_full}
  </div>

</div><!-- /wrapper -->
</body>
</html>"""

    return html


# --- SAVE REPORT ------------------------------------------------------------
def sauvegarder_rapport(rapport_html):
    dossier = Path("rapports")
    dossier.mkdir(exist_ok=True, parents=True)
    fichier = dossier / f"gse_veille_{datetime.now().strftime('%Y%m%d_%H%M')}.html"
    with open(fichier, "w", encoding="utf-8") as f:
        f.write(rapport_html)
    log.info(f"Report saved: {fichier.absolute()}")
    return fichier


# --- EXECUTION ---------------------------------------------------------------
def executer_agent():
    log.info("Starting GSE intelligence agent")
    try:
        vus = charger_vus()
        tous_articles = collecter_tous_articles()
        articles_pertinents = filtrer_pertinents(tous_articles, vus)

        raw_analyse = analyser_avec_deepseek(articles_pertinents) if articles_pertinents else ""
        signals, summary = parser_analyse(raw_analyse)

        rapport_html = generer_rapport(articles_pertinents, signals, summary)
        fichier = sauvegarder_rapport(rapport_html)
        print(f"✅ Report generated: {fichier}")

        for a in articles_pertinents:
            vus.add(a["id"])
        sauvegarder_vus(vus)
        log.info("Done.")

    except Exception as e:
        log.exception(f"Fatal error : {e}")


if __name__ == "__main__":
    executer_agent()
