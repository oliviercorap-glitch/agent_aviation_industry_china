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

# --- Mots-clés GSE (Ground Support Equipment) - Bilingue ---------------------
KEYWORDS_GSE = [
    # English - Equipment
    "ground support equipment", "gse", "ground handling", "tug", "tractor",
    "belt loader", "conveyor belt", "staircase", "passenger boarding bridge",
    "de-icer", "deicing truck", "gpu", "ground power unit", "air start unit",
    "air conditioning unit", "towbar", "towbarless", "baggage cart", "dolly",
    "catering truck", "lavatory truck", "water truck", "apron", "ramp",
    "electric ground support", "hybrid gse", "lithium battery gse",
    "fast charge", "wireless charging gse", "autonomous gse",
    # English - Players & Contracts
    "swissport", "menzies", "dnata", "ground handler", "handling contract",
    "fleet renewal", "gse maintenance", "mro ground", "tender handling",
    # English - Regulations & Supply Chain
    "emission regulation airport", "electric ramp", "diesel ban airport",
    "raw material steel", "battery supply chain", "semiconductor shortage",
    "aluminium price", "lithium price", "supply chain disruption",
    # Chinese - 设备 (Equipment)
    "地勤设备", "地面支持设备", "行李拖车", "客梯车", "电源车", "气源车",
    "除冰车", "装载机", "传送带车", "飞机牵引车", "机坪", "停机坪",
    "地面服务", "勤务", "新能源地勤", "电动地勤", "充电桩", "机务",
    "无拖把", "抱轮", "飞机加油车", "空调车",
    # Chinese - 市场 & 法规
    "地勤公司", "机场扩建", "新航站楼", "机位", "远机位", "招标", "采购",
    "电动化", "柴油车禁行", "机场排放", "碳中和机场"
]

# --- Sources (priorité aux sites GSE, puis Bidcenter, puis chinois) ---------
SOURCES = [
    # 0. SOURCE PRIORITAIRE : Appels d'offres Chine
    {
        "nom": "Bidcenter (Chine - Appels d'offres aéroportuaires)",
        "url": "https://www.bidcenter.com.cn",
        "type": "scrape_bidcenter",
        "base_url": "https://www.bidcenter.com.cn",
        "encoding": "utf-8"
    },
    # 1. Sources spécialisées GSE
    {
        "nom": "Ground Handling International (News)",
        "url": "https://www.groundhandling.com/news",
        "type": "scrape_generic",
        "selector": "div.news-item a, article h3 a, .article-link a",
        "base_url": "https://www.groundhandling.com",
    },
    {
        "nom": "Aviation Pros - Ground Handling",
        "url": "https://www.aviationpros.com/ground-handling",
        "type": "scrape_generic",
        "selector": "div.article-listing a, h2.article-title a, .listing-title a",
        "base_url": "https://www.aviationpros.com",
    },
    {
        "nom": "International Airport Review - GSE",
        "url": "https://www.internationalairportreview.com/topics/ground-handling/",
        "type": "scrape_generic",
        "selector": "article h3 a, .topic-article a, .post-title a",
        "base_url": "https://www.internationalairportreview.com",
    },
    {
        "nom": "Airport Technology - Ground Support",
        "url": "https://www.airport-technology.com/sectors/ground-support/",
        "type": "scrape_generic",
        "selector": "article h3 a, .card-title a, .post-title a",
        "base_url": "https://www.airport-technology.com",
    },
    # 2. Sources chinoises (infrastructures, régulations)
    {
        "nom": "CAAC News (China)",
        "url": "https://www.caac.gov.cn/",
        "type": "scrape_caac",
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
        "nom": "CGTN - Aviation",
        "url": "https://news.cgtn.com/",
        "type": "scrape_generic",
        "selector": "div.newsList a, a",
        "base_url": "https://news.cgtn.com",
        "encoding": "utf-8"
    }
]

# --- Fonctions utilitaires ---------------------------------------------------
def normaliser_url(url, base=None):
    """Construit une URL absolue et supprime les paramètres de tracking."""
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
            except json.JSONDecodeError:
                log.warning("Fichier seen_gse_articles.json corrompu, réinitialisation.")
                return set()
    return set()

def sauvegarder_vus(vus):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(vus), f, ensure_ascii=False, indent=2)

# --- Fonctions de scraping avec retry ----------------------------------------
def requeter_avec_retry(url, retries=3, **kwargs):
    """Effectue une requête HTTP avec 3 tentatives en cas d'échec."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    if "headers" in kwargs:
        headers.update(kwargs.pop("headers"))
    for i in range(retries):
        try:
            resp = requests.get(url, timeout=30, headers=headers, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.exceptions.RequestException as e:
            log.warning(f"Tentative {i+1}/{retries} échouée pour {url} : {e}")
            time.sleep(2 ** i)
    return None

def scrape_caac(source):
    """Scraping spécifique pour le site CAAC."""
    articles = []
    resp = requeter_avec_retry(source["url"])
    if not resp:
        return articles
    try:
        soup = BeautifulSoup(resp.content, "html.parser", from_encoding='utf-8')
        news_block = soup.find('div', class_='newsList') or soup.find('div', class_='list') or soup.find('ul', class_='news')
        if news_block:
            links = news_block.find_all('a')
        else:
            links = soup.find_all('a', href=True)
        for link in links[:20]:
            titre = link.get_text(strip=True)
            if not titre or len(titre) < 15 or ">" in titre:
                continue
            href = link.get('href')
            if href:
                href = normaliser_url(href, "https://www.caac.gov.cn")
            if titre and href:
                articles.append({
                    "source": source["nom"],
                    "titre": titre[:150],
                    "lien": href,
                    "desc": "",
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "id": hashlib.md5((titre + href).encode()).hexdigest(),
                })
        log.info(f"  Scraping CAAC: {len(articles)} articles")
    except Exception as e:
        log.warning(f"Erreur parsing CAAC : {e}")
    return articles

def scrape_generic(source):
    """Scraping générique avec sélecteur CSS."""
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
            if not href or not titre or len(titre) < 12:
                continue
            if titre.lower().startswith(('read more', 'continue', 'click here')):
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
    """Scraping spécifique pour Bidcenter (portail d'appels d'offres chinois)."""
    articles = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.bidcenter.com.cn/",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
    }
    resp = requeter_avec_retry(source["url"], headers=headers)
    if not resp:
        return articles
    try:
        soup = BeautifulSoup(resp.content, "html.parser", from_encoding='utf-8')
        
        # Sélecteurs typiques de Bidcenter (liste des tenders)
        links = soup.select('div.tender_list a, ul.tender-list a, .gg_list a, table a, .list-item a')
        if not links:
            links = soup.find_all('a', href=True)
        
        unique_links = {}
        for link in links:
            href = link.get('href')
            titre = link.get_text(strip=True)
            if not href or not titre or len(titre) < 10:
                continue
            # Nettoyage : on ignore les liens de navigation
            mots_exclus = ['首页', '上一页', '下一页', '末页', '登录', '注册', '发布', '搜索', '招标公告']
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
        log.info(f"  Scraping {source['nom']}: {len(articles)} appels d'offres trouvés")
    except Exception as e:
        log.warning(f"Erreur scraping {source['nom']} : {e}")
    return articles

def collecter_tous_articles():
    """Rassemble tous les articles via les différentes méthodes."""
    tous_articles = []
    for source in SOURCES:
        log.info(f"Collecte depuis : {source['nom']}")
        if source["type"] == "scrape_caac":
            articles = scrape_caac(source)
        elif source["type"] == "scrape_bidcenter":
            articles = scrape_bidcenter(source)
        elif source["type"] == "scrape_generic":
            articles = scrape_generic(source)
        else:
            articles = []
        tous_articles.extend(articles)
        time.sleep(1.5)
    log.info(f"Total articles bruts collectés: {len(tous_articles)}")
    return tous_articles

def filtrer_pertinents(articles, vus):
    """Filtre les articles nouveaux et contenant les mots-clés GSE."""
    nouveaux = []
    for a in articles:
        if a["id"] in vus:
            continue
        texte = (a["titre"] + " " + a.get("desc", "")).lower()
        if any(kw.lower() in texte for kw in KEYWORDS_GSE):
            nouveaux.append(a)
    log.info(f"Articles GSE pertinents et nouveaux : {len(nouveaux)}")
    return nouveaux

# --- Analyse par DeepSeek (via OpenAI client) --------------------------------
SYSTEM_PROMPT_GSE = """Tu es un expert du marché des équipements de support au sol (GSE) en Asie-Pacifique, 
spécialisé en stratégie industrielle et supply chain. Tu conseilles le CEO d'un fabricant / loueur de GSE.

Pour chaque actualité, tu évalues l'impact concret sur :
- Demande en équipements (tracteurs, chargeurs, passerelles, groupes électrogènes, dégivreuses)
- Coûts des intrants (acier, aluminium, batteries lithium, semi-conducteurs)
- Réglementations locales (normes de bruit, émissions CO2, interdictions diesel dans les aéroports chinois/européens)
- Appels d'offres et contrats de handling (Swissport, Menzies, Dnata, sociétés locales)
- Maintenance et MRO au sol (pièces détachées, fiabilité, obsolescence)
- Infrastructure aéroportuaire (nouveaux terminaux, nouvelles aires de stationnement => besoin de GSE supplémentaire)

Ton analyse est en français, orientée décisions commerciales et industrielles.
Niveau d'impact : CRITIQUE / IMPORTANT / À SURVEILLER / INFO
"""

def analyser_avec_deepseek(articles):
    if not articles:
        return "Aucune information sectorielle significative pour la GSE aujourd'hui."

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY non définie dans le fichier .env")

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com/v1")

    date_str = datetime.now().strftime("%d %B %Y")
    articles_txt = ""
    for i, a in enumerate(articles, 1):
        articles_txt += f"\n[{i}] Source : {a['source']}\n"
        articles_txt += f"    Titre : {a['titre']}\n"
        articles_txt += f"    Lien  : {a['lien']}\n"
        if a.get('desc'):
            articles_txt += f"    Résumé: {a['desc']}\n"

    prompt = (f"Veille concurrentielle et réglementaire GSE - Chine / Asie-Pacifique — {date_str}\n"
              f"Nombre d'articles sélectionnés : {len(articles)}\n\n{articles_txt}\n\n"
              "Pour chaque information importante :\n"
              "1. IMPACT : CRITIQUE / IMPORTANT / À SURVEILLER / INFO\n"
              "2. RÉSUMÉ (1-2 phrases) lié au marché GSE\n"
              "3. IMPACT BUSINESS (ex: hausse des coûts de production, opportunité de remplacement de flotte, nouveau marché à saisir, risque d'approvisionnement)\n"
              "4. ACTION RECOMMANDÉE (contacter fournisseur, ajuster stock de sécurité, prospecter tel aéroport, adapter catalogue produit)\n\n"
              "Termine par :\n"
              "- SYNTHÈSE EXÉCUTIVE (5 lignes max) pour le comité de direction\n"
              "- 3 INDICATEURS CLÉS À SURVEILLER cette semaine (ex: prix du lithium, annonces de Swissport, réglementation PEK)\n"
              "- RISQUE PRINCIPAL pour la chaîne d'approvisionnement GSE en Chine")

    log.info(f"Envoi de {len(articles)} articles à DeepSeek...")
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_GSE},
                {"role": "user", "content": prompt}
            ],
            max_tokens=4096,
            temperature=0.3
        )
        return response.choices[0].message.content
    except Exception as e:
        log.error(f"Erreur lors de l'appel à DeepSeek : {e}")
        return "L'API n'a pas pu traiter la demande. Vérifiez votre clé et votre connexion."

# --- Génération du rapport ---------------------------------------------------
def generer_rapport(articles, analyse):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lignes = ["=" * 62,
              f"  VEILLE STRATÉGIQUE GSE (Chine / Asie) — {now}",
              "  Pour : Direction Industrielle & Commerciale",
              "  Modèle : DeepSeek Chat", "=" * 62, "",
              f"  {len(articles)} information(s) GSE pertinente(s)", "",
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
    fichier = dossier / f"gse_chine_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
    with open(fichier, "w", encoding="utf-8") as f:
        f.write(rapport)
    log.info(f"Rapport créé : {fichier.absolute()}")

# --- Exécution principale ----------------------------------------------------
def executer_agent():
    log.info("Démarrage agent veille GSE Chine (version métier + Bidcenter)")
    try:
        vus = charger_vus()
        tous_articles = collecter_tous_articles()
        articles_pertinents = filtrer_pertinents(tous_articles, vus)
        analyse = analyser_avec_deepseek(articles_pertinents) if articles_pertinents else "Aucune information GSE pertinente aujourd'hui."
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
