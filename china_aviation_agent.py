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
    # ---------- GSE & EQUIPMENT ----------
    "ground support", "gse", "tug", "tractor", "loader", "de-icer", "gpu",
    "towbar", "baggage", "passenger boarding bridge", "air start unit",
    "belt loader", "conveyor belt", "staircase", "dolly", "catering truck",
    "lavatory truck", "water truck", "apron", "ramp", "electric ground support",
    "hybrid gse", "lithium battery gse", "autonomous gse", "maintenance gse",
    "mro ground",
    "地勤设备", "地面支持设备", "行李拖车", "客梯车", "电源车", "气源车",
    "除冰车", "装载机", "传送带车", "飞机牵引车", "新能源地勤", "电动地勤",

    # ---------- AIRPORTS & INFRASTRUCTURE ----------
    "airport opening", "new runway", "terminal expansion", "airport expansion",
    "passenger record", "traffic record", "cargo volume", "load factor",
    "inauguration", "infrastructure investment",
    "机场", "航空", "航站楼", "停机坪", "扩建", "招标", "采购", "项目", "投运",
    "吞吐量", "旅客", "货邮", "航班", "机位", "远机位", "新机场", "新航站楼",
    "旅客吞吐量创新高", "航班量",

    # ---------- AIRLINES (CLIENTS) ----------
    "airline order", "fleet delivery", "fleet expansion", "airline profit",
    "airline loss", "bankruptcy", "revenue", "EBIT",
    "Air China", "China Eastern", "China Southern", "Hainan Airlines",
    "中国国航", "国航", "中国东方航空", "东方航空", "东航",
    "中国南方航空", "南方航空", "南航", "海南航空", "海航",
    "厦门航空", "厦航", "深圳航空", "深航", "春秋航空", "春秋",
    "吉祥航空", "吉祥", "四川航空", "川航", "山东航空", "山航",
    "订购", "交付", "机队", "盈利", "亏损", "营收", "净利润",
    "复航", "停飞", "航线", "新开航线", "恢复", "破产", "重组",

    # ---------- REGULATIONS & SUPPLY CHAIN ----------
    "emission regulation", "electric ramp", "diesel ban",
    "steel price", "aluminium", "lithium", "battery cost",
    "semiconductor", "chip shortage", "supply chain disruption",
    "碳中和机场", "电动化", "柴油车禁行", "carbon peak",

    # ---------- GEOPOLITICS ----------
    "Belt and Road", "BRI", "tariff", "trade war", "EU tariffs",
    "一带一路", "关税",

    # ---------- COMPETITORS (TOP 20 GLOBAL) ----------
    "TLD Group", "TLD", "Alvest",
    "JBT Corporation", "JBT", "Oshkosh AeroTech", "Oshkosh",
    "Textron GSE", "Textron", "Tug Technologies", "Tronair", "ITW GSE",
    "Fast Global Solutions", "Fast Global", "WASP GSE",
    "Mallaghan", "Mallaghan Engineering", "Goldhofer", "MULAG",
    "HYDRO", "Guinault", "Cavotec", "AERO Specialties", "Aero Specialties",
    "Global Ground Support", "DOLL", "Nepean", "Gate GSE",
    "Clyde Machines", "Douglas Equipment",

    # ---------- COMPETITORS (EUROPEAN & AMERICAN) ----------
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

    # ---------- CHINESE COMPETITORS ----------
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

    # ---------- LOCATION & SERVICES ----------
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

# --- DEEPSEEK PROMPTS (ENGLISH) ----------------------------------------------
SYSTEM_PROMPT_GSE = """You are an expert in the Ground Support Equipment (GSE) market in Asia-Pacific, specializing in industrial strategy and supply chain. You advise the CEO of a GSE manufacturer/lessor (TLD Group).

**IMPORTANT** : Do not limit yourself to articles that only mention equipment.
- Airport openings, traffic records, fleet orders, and airline financial results are **LEADING INDICATORS**.
- Announcements from competitors (JBT, Textron, Guangtai, etc.) must be analyzed as threats or opportunities.
- Translate these signals into potential equipment volumes (e.g., +5% traffic = +10 tractors).

Pay special attention to:
1. Raw material costs (steel, aluminium, lithium, semiconductors)
2. M&A among handlers (Swissport, Menzies, Dnata)
3. Trade policies (tariffs, Belt and Road)
4. Environmental regulations in China

For each major news item, evaluate the concrete impact on:
1. Equipment demand (tractors, loaders, boarding bridges, GPUs)
2. Input costs (impact on margins)
3. Tenders and handling contracts
4. Competitive positioning against challengers

Your analysis is in English, focused on commercial and industrial decisions.
Impact level: CRITICAL / IMPORTANT / WATCH / INFO
"""

def analyser_avec_deepseek(articles):
    if not articles:
        return "No significant sector information for GSE today."

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY not set")

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com/v1")
    date_str = datetime.now().strftime("%d %B %Y")
    articles_txt = ""
    for i, a in enumerate(articles, 1):
        articles_txt += f"\n[{i}] Source : {a['source']}\n"
        articles_txt += f"    Title : {a['titre']}\n"
        articles_txt += f"    Link  : {a['lien']}\n"

    prompt = (f"GSE Strategic Watch - China / Asia-Pacific — {date_str}\n"
              f"Number of selected articles: {len(articles)}\n\n{articles_txt}\n\n"
              "For each important piece of information:\n"
              "1. IMPACT : CRITICAL / IMPORTANT / WATCH / INFO\n"
              "2. SUMMARY (1-2 sentences) linked to the GSE market\n"
              "3. BUSINESS IMPACT (e.g., cost increase, sales opportunity, competitive threat)\n"
              "4. RECOMMENDED ACTION (contact supplier, prospect client, adapt catalogue)\n\n"
              "Conclude with:\n"
              "- EXECUTIVE SUMMARY (max 5 lines) for the executive committee\n"
              "- 3 KEY INDICATORS TO WATCH this week\n"
              "- MAIN RISK for the GSE market in China")

    log.info(f"Sending {len(articles)} articles to DeepSeek...")
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "system", "content": SYSTEM_PROMPT_GSE},
                      {"role": "user", "content": prompt}],
            max_tokens=4096,
            temperature=0.3
        )
        return response.choices[0].message.content
    except Exception as e:
        log.error(f"DeepSeek error : {e}")
        return "API error."

# --- HTML REPORT GENERATION (enhanced) ----------------------------------------
def generer_rapport(articles, analyse):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # --- Parse analysis into structured blocks ---
    # We'll try to extract per-article blocks and the final summary sections.
    parsed_blocks = []
    executive_summary = ""
    key_indicators = []
    main_risk = ""

    # Split into blocks using pattern like "[1]" etc.
    block_pattern = re.compile(r'^\[\d+\]', re.MULTILINE)
    raw_blocks = block_pattern.split(analyse)
    # The first element is the text before any [n] (usually empty or intro)
    # The rest correspond to blocks, but we lose the marker; we need to capture them.
    # Better: iterate lines and accumulate.
    lines = analyse.splitlines()
    current_block_lines = []
    in_summary = False
    summary_lines = []
    indicators_lines = []
    risk_lines = []
    for line in lines:
        # Check if it's a summary/indicators/risk section
        if line.strip().startswith('- EXECUTIVE SUMMARY'):
            in_summary = True
            # If we were building a block, save it
            if current_block_lines:
                parsed_blocks.append('\n'.join(current_block_lines))
                current_block_lines = []
            continue
        if line.strip().startswith('- 3 KEY INDICATORS'):
            # End summary, start indicators
            if in_summary:
                summary_lines = current_block_lines  # actually we need to capture previous lines
                current_block_lines = []
                in_summary = False
            # We'll just capture lines until next marker
            continue
        if line.strip().startswith('- MAIN RISK'):
            # End indicators, start risk
            if not in_summary:
                # We were in indicators
                pass
            continue

        if in_summary:
            summary_lines.append(line)
        elif line.strip().startswith('[') and re.match(r'^\[\d+\]', line.strip()):
            # New block start
            if current_block_lines:
                parsed_blocks.append('\n'.join(current_block_lines))
                current_block_lines = []
            current_block_lines.append(line)
        else:
            if current_block_lines or line.strip():
                current_block_lines.append(line)
    # After loop, add remaining block if any
    if current_block_lines and not in_summary:
        # check if it's summary leftovers
        if any('EXECUTIVE SUMMARY' in l for l in current_block_lines):
            summary_lines.extend(current_block_lines)
        else:
            parsed_blocks.append('\n'.join(current_block_lines))

    # Now parse each block to extract impact, summary, biz impact, action
    def extract_block_info(block):
        impact = "INFO"
        summary = ""
        biz_impact = ""
        action = ""
        # Use regex with DOTALL
        impact_match = re.search(r'IMPACT\s*:\s*(CRITICAL|IMPORTANT|WATCH|INFO)', block, re.IGNORECASE)
        if impact_match:
            impact = impact_match.group(1).upper()
        summary_match = re.search(r'SUMMARY\s*\([^)]*\)\s*:\s*(.*?)(?=\d\.\s*BUSINESS IMPACT|$)', block, re.DOTALL | re.IGNORECASE)
        if summary_match:
            summary = summary_match.group(1).strip()
        biz_match = re.search(r'BUSINESS IMPACT\s*:\s*(.*?)(?=\d\.\s*RECOMMENDED ACTION|$)', block, re.DOTALL | re.IGNORECASE)
        if biz_match:
            biz_impact = biz_match.group(1).strip()
        action_match = re.search(r'RECOMMENDED ACTION\s*:\s*(.*?)(?=\[\d+\]|$)', block, re.DOTALL | re.IGNORECASE)
        if action_match:
            action = action_match.group(1).strip()
        return {'impact': impact, 'summary': summary, 'business_impact': biz_impact, 'recommended_action': action}

    block_infos = [extract_block_info(b) for b in parsed_blocks if b.strip()]

    # Now extract executive summary, indicators, risk from the remaining lines (summary_lines)
    # We'll parse summary_lines for EXECUTIVE SUMMARY content
    summary_text = "\n".join(summary_lines).strip()
    # Extract executive summary between "- EXECUTIVE SUMMARY" and the next section
    exec_summary_match = re.search(r'- EXECUTIVE SUMMARY\s*(.*?)(?=- 3 KEY INDICATORS|$)', summary_text, re.DOTALL)
    if exec_summary_match:
        executive_summary = exec_summary_match.group(1).strip()
    indicators_match = re.search(r'- 3 KEY INDICATORS TO WATCH this week\s*(.*?)(?=- MAIN RISK|$)', summary_text, re.DOTALL)
    if indicators_match:
        key_indicators = [i.strip() for i in indicators_match.group(1).strip().split('\n') if i.strip()]
    risk_match = re.search(r'- MAIN RISK\s*(.*?)$', summary_text, re.DOTALL)
    if risk_match:
        main_risk = risk_match.group(1).strip()

    # Fallback if parsing failed: treat entire analyse as plain text inside a card
    if not block_infos and not executive_summary:
        # Just use raw analyse
        block_infos = [{'impact': 'INFO', 'summary': '', 'business_impact': '', 'recommended_action': '', 'raw': analyse}]
        executive_summary = ""

    # --- Build HTML ---
    impact_icons = {'CRITICAL': '🚨', 'IMPORTANT': '⚠️', 'WATCH': '👀', 'INFO': 'ℹ️'}
    impact_colors = {'CRITICAL': '#dc2626', 'IMPORTANT': '#f59e0b', 'WATCH': '#eab308', 'INFO': '#3b82f6'}

    # Count impact levels for stats
    impact_counts = {}
    for b in block_infos:
        imp = b.get('impact', 'INFO')
        impact_counts[imp] = impact_counts.get(imp, 0) + 1

    # Escape newlines for display in HTML (must be done outside f-string)
    # Precompute escaped versions
    exec_summary_esc = executive_summary.replace('\n', '<br>') if executive_summary else ""
    key_indicators_esc = [ind.replace('\n', '<br>') for ind in key_indicators]
    main_risk_esc = main_risk.replace('\n', '<br>') if main_risk else ""

    # For each block, pre-escape fields
    block_infos_esc = []
    for b in block_infos:
        esc = {
            'impact': b.get('impact', 'INFO'),
            'summary': b.get('summary', '').replace('\n', '<br>'),
            'business_impact': b.get('business_impact', '').replace('\n', '<br>'),
            'recommended_action': b.get('recommended_action', '').replace('\n', '<br>'),
            'raw': b.get('raw', '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        }
        # Also escape summary etc. for raw if present
        block_infos_esc.append(esc)

    # Start HTML
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GSE Strategic Watch - {now}</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,400;14..32,500;14..32,600;14..32,700&display=swap" rel="stylesheet">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f8fafc;
            color: #0f172a;
            padding: 40px 20px;
            line-height: 1.6;
        }}
        .container {{
            max-width: 1100px;
            margin: 0 auto;
            background: white;
            border-radius: 24px;
            padding: 40px 45px;
            box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05), 0 10px 15px -3px rgba(0,0,0,0.08);
        }}
        h1 {{ font-size: 28px; font-weight: 700; letter-spacing: -0.02em; margin-bottom: 6px; }}
        .subhead {{ font-size: 16px; color: #64748b; margin-bottom: 30px; }}
        .stats {{
            display: flex; flex-wrap: wrap; gap: 20px 40px;
            background: #f1f5f9; border-radius: 16px; padding: 18px 24px; margin-bottom: 20px;
        }}
        .stat-item {{ font-size: 15px; }}
        .stat-item strong {{ font-weight: 600; color: #0f172a; }}
        .impact-badge {{
            display: inline-block; padding: 2px 12px; border-radius: 20px; font-weight: 600; font-size: 13px;
            color: white; background: #94a3b8;
        }}
        .impact-badge.critical {{ background: #dc2626; }}
        .impact-badge.important {{ background: #f59e0b; }}
        .impact-badge.watch {{ background: #eab308; color: #0f172a; }}
        .impact-badge.info {{ background: #3b82f6; }}
        .section-title {{
            font-size: 20px; font-weight: 600; margin: 36px 0 16px 0;
            padding-bottom: 8px; border-bottom: 2px solid #e2e8f0;
        }}
        .sources-list {{
            display: flex; flex-wrap: wrap; gap: 8px 16px;
            background: #f8fafc; padding: 12px 16px; border-radius: 12px; margin-bottom: 20px;
        }}
        .source-tag {{ font-size: 14px; background: #e2e8f0; padding: 2px 12px; border-radius: 20px; color: #1e293b; }}
        .article-table {{
            width: 100%; border-collapse: collapse; font-size: 14px; margin-top: 8px;
        }}
        .article-table th {{ text-align: left; padding: 10px 12px; background: #f1f5f9; font-weight: 600; border-bottom: 2px solid #cbd5e1; }}
        .article-table td {{ padding: 10px 12px; border-bottom: 1px solid #e2e8f0; vertical-align: top; }}
        .article-table tr:last-child td {{ border-bottom: none; }}
        .article-table .source {{ font-weight: 500; color: #1e293b; white-space: nowrap; }}
        .article-table .title a {{ color: #1e40af; text-decoration: none; font-weight: 500; }}
        .article-table .title a:hover {{ text-decoration: underline; }}

        /* Analysis cards */
        .analysis-card {{
            border-left: 6px solid #94a3b8;
            background: #f8fafc;
            border-radius: 12px;
            padding: 16px 20px;
            margin-bottom: 20px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.04);
            transition: box-shadow 0.2s;
        }}
        .analysis-card:hover {{ box-shadow: 0 4px 12px rgba(0,0,0,0.08); }}
        .analysis-card.impact-critical {{ border-left-color: #dc2626; }}
        .analysis-card.impact-important {{ border-left-color: #f59e0b; }}
        .analysis-card.impact-watch {{ border-left-color: #eab308; }}
        .analysis-card.impact-info {{ border-left-color: #3b82f6; }}

        .card-header {{
            display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 8px;
        }}
        .card-header .impact-badge {{
            font-size: 14px; padding: 4px 16px; border-radius: 30px;
        }}
        .card-body p {{
            margin-top: 8px;
        }}
        .card-body strong {{
            font-weight: 600; color: #1e293b;
        }}
        .exec-summary {{
            background: #dbeafe; border-left: 6px solid #2563eb; border-radius: 12px;
            padding: 16px 20px; margin-bottom: 20px;
        }}
        .exec-summary h3 {{ font-size: 18px; font-weight: 600; margin-bottom: 6px; color: #1e3a8a; }}
        .key-indicators {{
            background: #fef3c7; border-left: 6px solid #d97706; border-radius: 12px;
            padding: 16px 20px; margin-bottom: 20px;
        }}
        .key-indicators h3 {{ font-size: 18px; font-weight: 600; margin-bottom: 6px; color: #92400e; }}
        .key-indicators ul {{ list-style: disc; margin-left: 20px; }}
        .main-risk {{
            background: #fee2e2; border-left: 6px solid #dc2626; border-radius: 12px;
            padding: 16px 20px; margin-bottom: 20px;
        }}
        .main-risk h3 {{ font-size: 18px; font-weight: 600; margin-bottom: 6px; color: #991b1b; }}

        .footer {{
            margin-top: 36px; font-size: 13px; color: #94a3b8; text-align: center;
            border-top: 1px solid #e2e8f0; padding-top: 24px;
        }}
        @media (max-width: 640px) {{
            .container {{ padding: 20px 16px; }}
            .stats {{ flex-direction: column; gap: 8px; }}
            .article-table th, .article-table td {{ padding: 8px 6px; }}
            .article-table .source {{ white-space: normal; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🛫 GSE Strategic Watch</h1>
        <div class="subhead">{now} · Asia-Pacific Focus</div>

        <div class="stats">
            <span class="stat-item"><strong>{len(articles)}</strong> relevant article(s)</span>
            <span class="stat-item"><strong>{len(SOURCES)}</strong> sources monitored</span>
            <span class="stat-item">Impact levels: 
                {''.join(f'<span class="impact-badge {k.lower()}">{v}</span> ' for k,v in impact_counts.items())}
            </span>
        </div>

        <div class="sources-list">
            {''.join(f'<span class="source-tag">{s["nom"]}</span>' for s in SOURCES)}
        </div>

        <h2 class="section-title">📰 Articles of the Day</h2>
        <table class="article-table">
            <thead><tr><th>#</th><th>Source</th><th>Title</th></tr></thead>
            <tbody>
    """
    for i, a in enumerate(articles, 1):
        titre_esc = a['titre'].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        lien = a['lien'] or '#'
        html += f"""
                <tr>
                    <td>{i}</td>
                    <td class="source">{a['source']}</td>
                    <td class="title"><a href="{lien}" target="_blank">{titre_esc}</a></td>
                </tr>
        """
    html += """
            </tbody>
        </table>

        <h2 class="section-title">📊 Analysis & Recommendations</h2>
    """

    # Executive summary if available
    if executive_summary:
        html += f"""
        <div class="exec-summary">
            <h3>📌 Executive Summary</h3>
            <p>{exec_summary_esc}</p>
        </div>
        """

    # Analysis cards
    for idx, block in enumerate(block_infos_esc):
        impact = block.get('impact', 'INFO')
        summary = block.get('summary', '')
        biz = block.get('business_impact', '')
        action = block.get('recommended_action', '')
        # If we have raw and no parsed fields, show raw
        if not summary and not biz and not action:
            raw = block.get('raw', '')
            html += f"""
            <div class="analysis-card impact-{impact.lower()}">
                <div class="card-header">
                    <span class="impact-badge {impact.lower()}">{impact_icons.get(impact, '')} {impact}</span>
                    <span style="font-size:14px; color:#64748b;">Analysis #{idx+1}</span>
                </div>
                <div class="card-body">
                    <p style="white-space:pre-wrap;">{raw}</p>
                </div>
            </div>
            """
            continue

        # Build card with structured fields
        html += f"""
        <div class="analysis-card impact-{impact.lower()}">
            <div class="card-header">
                <span class="impact-badge {impact.lower()}">{impact_icons.get(impact, '')} {impact}</span>
                <span style="font-size:14px; color:#64748b;">Analysis #{idx+1}</span>
            </div>
            <div class="card-body">
        """
        if summary:
            html += f"<p><strong>📝 Summary:</strong> {summary}</p>"
        if biz:
            html += f"<p><strong>💼 Business Impact:</strong> {biz}</p>"
        if action:
            html += f"<p><strong>✅ Recommended Action:</strong> {action}</p>"
        html += """
            </div>
        </div>
        """

    # Key indicators and main risk
    if key_indicators:
        html += """
        <div class="key-indicators">
            <h3>📈 Key Indicators to Watch This Week</h3>
            <ul>
        """
        for ind in key_indicators_esc:
            html += f"<li>{ind}</li>"
        html += """
            </ul>
        </div>
        """
    if main_risk:
        html += f"""
        <div class="main-risk">
            <h3>⚠️ Main Risk</h3>
            <p>{main_risk_esc}</p>
        </div>
        """

    html += """
        <div class="footer">
            Generated by GSE Intelligence Agent · Powered by DeepSeek
        </div>
    </div>
</body>
</html>
    """
    return html

def sauvegarder_rapport(rapport_html):
    dossier = Path("rapports")
    dossier.mkdir(exist_ok=True, parents=True)
    fichier = dossier / f"gse_veille_{datetime.now().strftime('%Y%m%d_%H%M')}.html"
    with open(fichier, "w", encoding="utf-8") as f:
        f.write(rapport_html)
    log.info(f"Report saved: {fichier.absolute()}")

# --- EXECUTION ---------------------------------------------------------------
def executer_agent():
    log.info("Starting GSE + competitors + market signals intelligence agent (HTML/EN)")
    try:
        vus = charger_vus()
        tous_articles = collecter_tous_articles()
        articles_pertinents = filtrer_pertinents(tous_articles, vus)
        analyse = analyser_avec_deepseek(articles_pertinents) if articles_pertinents else "No relevant information today."
        rapport_html = generer_rapport(articles_pertinents, analyse)
        sauvegarder_rapport(rapport_html)
        print(f"✅ HTML report generated: rapports/gse_veille_{datetime.now().strftime('%Y%m%d_%H%M')}.html")
        for a in articles_pertinents:
            vus.add(a["id"])
        sauvegarder_vus(vus)
        log.info("Done.")
    except Exception as e:
        log.exception(f"Fatal error : {e}")

if __name__ == "__main__":
    executer_agent()
