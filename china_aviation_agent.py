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
#  NOUVEAUX MOTS-CLÉS (RACINES GÉNÉRIQUES POUR CAPTURER TOUT SIGNAL)
# =============================================================================
# =============================================================================
#  MOTS-CLÉS ÉLARGIS : GSE + AÉROPORTS + COMPAGNIES AÉRIENNES (CLIENTS)
# =============================================================================
KEYWORDS_GSE = [
    # ---------- ANGLAIS (mots racines) ----------
    "ground support", "gse", "airport", "airline", "aviation", "handling",
    "tug", "tractor", "loader", "de-icer", "gpu", "towbar", "baggage",
    "passenger", "cargo", "freight", "fleet", "order", "delivery",
    "expansion", "new runway", "terminal", "swissport", "menzies", "dnata",
    "battery", "lithium", "steel", "semiconductor", "tariff", "belt and road",
    "profit", "loss", "revenue", "bankruptcy", "load factor", "bankruptcy",

    # ---------- CHINOIS (AÉROPORTS & INFRA) ----------
    "机场", "航空", "航站楼", "停机坪", "扩建", "招标", "采购", "项目", "投运",
    "吞吐量", "旅客", "货邮", "航班", "机位", "远机位",

    # ========== NOUVEAU : COMPAGNIES AÉRIENNES (vos gros clients) ==========
    # Noms des compagnies
    "中国国航", "国航",           # Air China
    "中国东方航空", "东方航空", "东航",  # China Eastern
    "中国南方航空", "南方航空", "南航",  # China Southern
    "海南航空", "海航",           # Hainan Airlines
    "厦门航空", "厦航",           # Xiamen Airlines
    "深圳航空", "深航",           # Shenzhen Airlines
    "春秋航空", "春秋",           # Spring Airlines
    "吉祥航空", "吉祥",           # Juneyao Air
    "四川航空", "川航",           # Sichuan Airlines
    "山东航空", "山航",           # Shandong Airlines

    # Événements flotte & finances (signaux forts)
    "订购",                      # Commande de flotte
    "交付",                      # Livraison d'avions
    "机队",                      # Flotte
    "盈利",                      # Bénéfice
    "亏损",                      # Perte
    "营收",                      # Revenu / Chiffre d'affaires
    "净利润",                    # Bénéfice net
    "复航",                      # Reprise des vols
    "停飞",                      # Grounding / Arrêt des vols
    "航线",                      # Ligne aérienne (route)
    "新开航线",                  # Nouvelle route
    "恢复",                      # Rétablissement
    "破产",                      # Faillite
    "重组"                       # Restructuration
]
# =============================================================================
#  SOURCES CORRIGÉES (URLs qui fonctionnent)
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
    # 3. CARNOC (Fonctionne - 2 articles)
    {
        "nom": "CARNOC.com (China)",
        "url": "https://www.carnoc.com/",
        "type": "scrape_generic",
        "selector": "div.news_list a, .article_list a, a",
        "base_url": "https://www.carnoc.com",
        "encoding": "utf-8"
    },
    # 4. CAAC (URL corrigée vers la page d'actualités)
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

# --- FONCTIONS (inchangées, mais je les inclus pour que le script soit complet) ---
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
        # On vérifie si un des mots-clés (en minuscule) est dans le texte
        if any(kw.lower() in texte for kw in KEYWORDS_GSE):
            nouveaux.append(a)
    log.info(f"Articles pertinents (GSE + signaux macro) : {len(nouveaux)}")
    return nouveaux

# --- PROMPT DEEPSEEK (inchangé, excellent) ------------------------------------
SYSTEM_PROMPT_GSE = """Tu es un expert du marché des équipements de support au sol (GSE) en Asie-Pacifique, 
spécialisé en stratégie industrielle et supply chain. Tu conseilles le CEO d'un fabricant / loueur de GSE.

**IMPORTANT** : Ne te limite pas aux articles parlant uniquement d'équipements. 
Les ouvertures d'aéroports, les records de trafic, les commandes de flotte et les résultats financiers des compagnies/handlers sont des **INDICATEURS AVANCÉS**. Tu dois systématiquement traduire ces informations en opportunités ou risques pour le marché GSE.

Accorde une attention particulière aux signaux sur :
- Les coûts des matières premières (acier, aluminium, lithium, semi-conducteurs)
- Les fusions-acquisitions chez les handlers
- Les politiques commerciales (tarifs douaniers, Belt and Road)
- Les réglementations environnementales en Chine

Pour chaque actualité importante, évalue l'impact concret sur :
1. Demande en équipements (tracteurs, chargeurs, passerelles)
2. Coûts des intrants (impact sur nos marges)
3. Appels d'offres et contrats de handling
4. Positionnement concurrentiel
5. Infrastructure aéroportuaire

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
              "3. IMPACT BUSINESS (ex: hausse des coûts, opportunité, risque)\n"
              "4. ACTION RECOMMANDÉE\n\n"
              "Termine par :\n"
              "- SYNTHÈSE EXÉCUTIVE (5 lignes max)\n"
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

# --- GENERATION RAPPORT (inchangée) ------------------------------------------
def generer_rapport(articles, analyse):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lignes = ["=" * 62,
              f"  VEILLE STRATÉGIQUE GSE & MARCHÉ AVIATION (Chine) — {now}",
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

# --- EXECUTION ---------------------------------------------------------------
def executer_agent():
    log.info("Démarrage agent veille GSE + signaux marché (version racines élargies)")
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
