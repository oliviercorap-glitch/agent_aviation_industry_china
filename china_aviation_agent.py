import os
import json
import logging
import hashlib
import requests
import time
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
#  MOTS-CLÉS ÉLARGIS : GSE + AÉROPORTS + COMPAGNIES + CONCURRENTS
# =============================================================================
KEYWORDS_GSE = [
    # ---------- GSE & ÉQUIPEMENTS ----------
    "ground support", "gse", "tug", "tractor", "loader", "de-icer", "gpu",
    "towbar", "baggage", "passenger boarding bridge", "air start unit",
    "belt loader", "conveyor belt", "staircase", "dolly", "catering truck",
    "lavatory truck", "water truck", "apron", "ramp", "electric ground support",
    "hybrid gse", "lithium battery gse", "autonomous gse", "maintenance gse",
    "mro ground",
    "地勤设备", "地面支持设备", "行李拖车", "客梯车", "电源车", "气源车",
    "除冰车", "装载机", "传送带车", "飞机牵引车", "新能源地勤", "电动地勤",

    # ---------- AÉROPORTS & INFRASTRUCTURES ----------
    "airport opening", "new runway", "terminal expansion", "airport expansion",
    "passenger record", "traffic record", "cargo volume", "load factor",
    "inauguration", "infrastructure investment",
    "机场", "航空", "航站楼", "停机坪", "扩建", "招标", "采购", "项目", "投运",
    "吞吐量", "旅客", "货邮", "航班", "机位", "远机位", "新机场", "新航站楼",
    "旅客吞吐量创新高", "航班量",

    # ---------- COMPAGNIES AÉRIENNES (CLIENTS) ----------
    "airline order", "fleet delivery", "fleet expansion", "airline profit",
    "airline loss", "bankruptcy", "revenue", "EBIT",
    "Air China", "China Eastern", "China Southern", "Hainan Airlines",
    "中国国航", "国航", "中国东方航空", "东方航空", "东航",
    "中国南方航空", "南方航空", "南航", "海南航空", "海航",
    "厦门航空", "厦航", "深圳航空", "深航", "春秋航空", "春秋",
    "吉祥航空", "吉祥", "四川航空", "川航", "山东航空", "山航",
    "订购", "交付", "机队", "盈利", "亏损", "营收", "净利润",
    "复航", "停飞", "航线", "新开航线", "恢复", "破产", "重组",

    # ---------- RÉGLEMENTATIONS & SUPPLY CHAIN ----------
    "emission regulation", "electric ramp", "diesel ban",
    "steel price", "aluminium", "lithium", "battery cost",
    "semiconductor", "chip shortage", "supply chain disruption",
    "碳中和机场", "电动化", "柴油车禁行", "carbon peak",

    # ---------- GÉOPOLITIQUE ----------
    "Belt and Road", "BRI", "tariff", "trade war", "EU tariffs",
    "一带一路", "关税",

    # ---------- CONCURRENTS (TOP 20 MONDIAUX) ----------
    "TLD Group", "TLD", "Alvest",
    "JBT Corporation", "JBT", "Oshkosh AeroTech", "Oshkosh",
    "Textron GSE", "Textron", "Tug Technologies", "Tronair", "ITW GSE",
    "Fast Global Solutions", "Fast Global", "WASP GSE",
    "Mallaghan", "Mallaghan Engineering", "Goldhofer", "MULAG",
    "HYDRO", "Guinault", "Cavotec", "AERO Specialties", "Aero Specialties",
    "Global Ground Support", "DOLL", "Nepean", "Gate GSE",
    "Clyde Machines", "Douglas Equipment",

    # ---------- CONCURRENTS (EUROPÉENS & AMÉRICAINS) ----------
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

    # ---------- CONCURRENTS CHINOIS ----------
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
#  SOURCES (FONCTIONNELLES)
# =============================================================================
SOURCES = [
    # 1. BIDCENTER (Appels d'offres - VITAL)
    {
        "nom": "Bidcenter (Chine - Appels d'offres)",
        "url": "https://www.bidcenter.com.cn",
        "type": "scrape_bidcenter",
        "base_url": "https://www.bidcenter.com.cn",
        "encoding": "utf-8"
    },
    # 2. CHINA AIRPORT NEWS (Fonctionne - 20 articles)
    {
        "nom": "China Airport News",
        "url": "http://fuwu.caacnews.com.cn/1/5/index.html",
        "type": "scrape_generic",
        "selector": "div.newsList ul li a, .list li a, a",
        "base_url": "http://fuwu.caacnews.com.cn",
        "encoding": "utf-8"
    },
    # 3. CARNOC (Fonctionne)
    {
        "nom": "CARNOC.com (China)",
        "url": "https://www.carnoc.com/",
        "type": "scrape_generic",
        "selector": "div.news_list a, .article_list a, a",
        "base_url": "https://www.carnoc.com",
        "encoding": "utf-8"
    },
    # 4. CAAC (URL corrigée)
    {
        "nom": "CAAC News (China)",
        "url": "http://www.caac.gov.cn/PHONE/ZTZL/",
        "type": "scrape_caac",
        "base_url": "http://www.caac.gov.cn"
    },
    # 5. GROUND HANDLING (URL corrigée)
    {
        "nom": "Ground Handling International",
        "url": "https://www.groundhandling.com/",
        "type": "scrape_generic",
        "selector": "article h3 a, .post-title a, a",
        "base_url": "https://www.groundhandling.com",
    },
    # 6. CGTN (URL corrigée)
    {
        "nom": "CGTN - Aviation",
        "url": "https://www.cgtn.com/",
        "type": "scrape_generic",
        "selector": "div.newsList a, a",
        "base_url": "https://www.cgtn.com",
        "encoding": "utf-8"
    }
]

# --- FONCTIONS UTILITAIRES ---------------------------------------------------
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
            log.warning(f"Tentative {i+1}/{retries} échouée pour {url} : {e}")
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
        log.info(f"  Scraping {source['nom']}: {len(articles)} articles")
    except Exception as e:
        log.warning(f"Erreur parsing {source['nom']} : {e}")
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
        log.info(f"  Scraping {source['nom']}: {len(articles)} articles")
    except Exception as e:
        log.warning(f"Erreur scraping {source['nom']} : {e}")
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
        log.info(f"  Scraping {source['nom']}: {len(articles)} appels d'offres")
    except Exception as e:
        log.warning(f"Erreur scraping {source['nom']} : {e}")
    return articles

def collecter_tous_articles():
    tous_articles = []
    for source in SOURCES:
        log.info(f"Collecte depuis : {source['nom']}")
        if source["type"] == "scrape_caac":
            articles = scrape_caac(source)
        elif source["type"] == "scrape_bidcenter":
            articles = scrape_bidcenter(source)
        else:
            articles = scrape_generic(source)
        tous_articles.extend(articles)
        time.sleep(1.5)
    log.info(f"Total articles bruts collectés: {len(tous_articles)}")
    return tous_articles

def filtrer_pertinents(articles, vus):
    nouveaux = []
    for a in articles:
        if a["id"] in vus:
            continue
        texte = (a["titre"] + " " + a.get("desc", "")).lower()
        if any(kw.lower() in texte for kw in KEYWORDS_GSE):
            nouveaux.append(a)
    log.info(f"Articles pertinents (GSE + signaux macro + concurrents) : {len(nouveaux)}")
    return nouveaux

# --- PROMPT DEEPSEEK (VERSION FINALE) ----------------------------------------
SYSTEM_PROMPT_GSE = """Tu es un expert du marché des équipements de support au sol (GSE) en Asie-Pacifique, 
spécialisé en stratégie industrielle et supply chain. Tu conseilles le CEO d'un fabricant / loueur de GSE (TLD Group).

**IMPORTANT** : Ne te limite pas aux articles parlant uniquement d'équipements. 
- Les ouvertures d'aéroports, les records de trafic, les commandes de flotte et les résultats financiers des compagnies sont des **INDICATEURS AVANCÉS**.
- Les annonces de tes concurrents (JBT, Textron, Guangtai, etc.) sont à analyser comme des menaces ou des opportunités.
- Traduis systématiquement ces informations en volumes d'équipements potentiels (ex: +5% de trafic = +10 tracteurs).

Accorde une attention particulière à :
1. Les coûts des matières premières (acier, aluminium, lithium, semi-conducteurs)
2. Les fusions-acquisitions chez les handlers (Swissport, Menzies, Dnata)
3. Les politiques commerciales (tarifs, Belt and Road)
4. Les réglementations environnementales en Chine

Pour chaque actualité importante, évalue l'impact concret sur :
1. Demande en équipements (tracteurs, chargeurs, passerelles, GPU)
2. Coûts des intrants (impact sur nos marges)
3. Appels d'offres et contrats de handling
4. Positionnement concurrentiel face aux challengers

Ton analyse est en français, orientée décisions commerciales et industrielles.
Niveau d'impact : CRITIQUE / IMPORTANT / À SURVEILLER / INFO
"""

def analyser_avec_deepseek(articles):
    if not articles:
        return "Aucune information sectorielle significative pour la GSE aujourd'hui."

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY non définie")

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com/v1")
    date_str = datetime.now().strftime("%d %B %Y")
    articles_txt = ""
    for i, a in enumerate(articles, 1):
        articles_txt += f"\n[{i}] Source : {a['source']}\n"
        articles_txt += f"    Titre : {a['titre']}\n"
        articles_txt += f"    Lien  : {a['lien']}\n"

    prompt = (f"Veille stratégique GSE - Chine / Asie-Pacifique — {date_str}\n"
              f"Nombre d'articles sélectionnés : {len(articles)}\n\n{articles_txt}\n\n"
              "Pour chaque information importante :\n"
              "1. IMPACT : CRITIQUE / IMPORTANT / À SURVEILLER / INFO\n"
              "2. RÉSUMÉ (1-2 phrases) lié au marché GSE\n"
              "3. IMPACT BUSINESS (ex: hausse des coûts, opportunité de vente, menace concurrentielle)\n"
              "4. ACTION RECOMMANDÉE (contacter fournisseur, prospecter client, adapter catalogue)\n\n"
              "Termine par :\n"
              "- SYNTHÈSE EXÉCUTIVE (5 lignes max) pour le comité de direction\n"
              "- 3 INDICATEURS CLÉS À SURVEILLER cette semaine\n"
              "- RISQUE PRINCIPAL pour le marché GSE en Chine")

    log.info(f"Envoi de {len(articles)} articles à DeepSeek...")
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
        log.error(f"Erreur DeepSeek : {e}")
        return "Erreur API."

# --- GÉNÉRATION RAPPORT ------------------------------------------------------
def generer_rapport(articles, analyse):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lignes = ["=" * 62,
              f"  VEILLE STRATÉGIQUE GSE & CONCURRENCE (Chine) — {now}",
              "  Pour : Direction Industrielle & Commerciale", "=" * 62, "",
              f"  {len(articles)} information(s) pertinente(s)", "",
              "  SOURCES SURVEILLÉES :"]
    for s in SOURCES:
        lignes.append(f"    - {s['nom']}")
    if articles:
        lignes += ["", "-" * 62, "  ARTICLES DU JOUR", "-" * 62]
        for i, a in enumerate(articles, 1):
            lignes.append(f"\n  [{i}] {a['source']}")
            lignes.append(f"      {a['titre']}")
            if a["lien"]:
                lignes.append(f"      {a['lien']}")
    lignes += ["", "-" * 62, "  ANALYSE & RECOMMANDATIONS", "-" * 62, analyse, "", "=" * 62]
    return "\n".join(lignes)

def sauvegarder_rapport(rapport):
    dossier = Path("rapports")
    dossier.mkdir(exist_ok=True, parents=True)
    fichier = dossier / f"gse_veille_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
    with open(fichier, "w", encoding="utf-8") as f:
        f.write(rapport)
    log.info(f"Rapport créé : {fichier.absolute()}")

# --- EXÉCUTION ---------------------------------------------------------------
def executer_agent():
    log.info("Démarrage agent veille GSE + concurrents + signaux marché (version finale)")
    try:
        vus = charger_vus()
        tous_articles = collecter_tous_articles()
        articles_pertinents = filtrer_pertinents(tous_articles, vus)
        analyse = analyser_avec_deepseek(articles_pertinents) if articles_pertinents else "Aucune information pertinente aujourd'hui."
        rapport = generer_rapport(articles_pertinents, analyse)
        print(rapport)
        sauvegarder_rapport(rapport)
        for a in articles_pertinents:
            vus.add(a["id"])
        sauvegarder_vus(vus)
        log.info("Terminé.")
    except Exception as e:
        log.exception(f"Erreur fatale : {e}")

if __name__ == "__main__":
    executer_agent()
