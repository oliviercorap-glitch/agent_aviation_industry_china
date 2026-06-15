"""
Agent de veille sectorielle — Aviation & Aéroports (Chine)
==========================================================
Sources :
 - CAAC (Administration de l'aviation civile chinoise)
 - Aéroports principaux (PEK, PVG, CAN)
 - Compagnies (Air China, China Eastern, China Southern)
 - OACI, IATA, FlightGlobal, Reuters Aviation, CAPA, Simple Flying

Fréquence : quotidienne (lundi-vendredi, 8h Shanghai)
Variables : DEEPSEEK_API_KEY
"""

import os, json, logging, hashlib
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
import anthropic
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

LOG_FILE  = Path("logs/agent_aviation.log")
SEEN_FILE = Path("seen_aviation_articles.json")

Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(LOG_FILE, encoding="utf-8")],
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mots-clés sectoriels
# ---------------------------------------------------------------------------
KEYWORDS_AVIATION = [
    # Général
    "aviation", "airport", "airline", "CAAC", "IATA", "ICAO", "traffic", "passenger",
    "cargo", "freight", "fleet", "route", "slot", "terminal", "runway", "ATC",
    # Chine
    "China", "Beijing", "Shanghai", "Guangzhou", "Shenzhen", "Chengdu", "Hong Kong",
    "Air China", "China Eastern", "China Southern", "Hainan Airlines", "Spring Airlines",
    "PEK", "PVG", "CAN", "PKX", "SHA", "CTU", "CGO",
    # Réglementation & sécurité
    "safety", "certification", "approval", "regulation", "policy", "restriction", "C919",
    "COMAC", "Boeing", "Airbus", "MAX", "grounding", "accident", "incident",
    # Économie & trafic
    "recovery", "growth", "capacity", "load factor", "yield", "RASK", "CASK",
    "subsidy", "infrastructure", "investment", "concession", "retail",
]

# ---------------------------------------------------------------------------
# Sources RSS (internationales et quelques chinoises)
# ---------------------------------------------------------------------------
RSS_SOURCES = [
    {
        "nom": "CAAC News (en)",
        "url": "http://www.caac.gov.cn/en/SSYD/XCXW/index.html",  # pas de RSS, scraping
        "type": "scrape"
    },
    {
        "nom": "IATA Press Releases",
        "url": "https://www.iata.org/en/pressroom/pr/feed/",
        "type": "rss"
    },
    {
        "nom": "ICAO News",
        "url": "https://www.icao.int/Pages/rss.aspx",
        "type": "rss"
    },
    {
        "nom": "FlightGlobal",
        "url": "https://www.flightglobal.com/feeds/rss/",
        "type": "rss"
    },
    {
        "nom": "Reuters Aviation",
        "url": "https://www.reuters.com/business/aerospace-defense/rss",
        "type": "rss"
    },
    {
        "nom": "CAPA - Centre for Aviation",
        "url": "https://centreforaviation.com/rss/news",
        "type": "rss"
    },
    {
        "nom": "Simple Flying",
        "url": "https://simpleflying.com/feed/",
        "type": "rss"
    },
    {
        "nom": "Airport World News",
        "url": "https://www.airport-world.com/feed/",
        "type": "rss"
    },
    {
        "nom": "Aviation Week China",
        "url": "https://aviationweek.com/taxonomy/term/101/feed",
        "type": "rss"
    }
]

# Sources à scraper (sites chinois sans RSS)
SCRAPE_SOURCES = [
    {
        "nom": "CAAC — Actualités (en)",
        "url": "http://www.caac.gov.cn/en/SSYD/XCXW/index.html",
        "selector": "div.NewsList ul li a",
        "base_url": "http://www.caac.gov.cn"
    },
    {
        "nom": "Beijing Capital Airport (PEK) - News",
        "url": "http://en.bcia.com.cn/news/news.shtml",
        "selector": "div.list ul li a",
        "base_url": "http://en.bcia.com.cn"
    },
    {
        "nom": "Shanghai Airport Authority (PVG/SHA)",
        "url": "https://www.shanghai-airport.com/en/news.jsp",
        "selector": "div.newslist a",
        "base_url": "https://www.shanghai-airport.com"
    },
    {
        "nom": "Guangzhou Baiyun Airport (CAN) - News",
        "url": "http://www.baiyunairport.com/en/media",
        "selector": "div.news-list a",
        "base_url": "http://www.baiyunairport.com"
    },
    {
        "nom": "Air China - Latest News",
        "url": "https://www.airchina.com.cn/en/info/news_list.shtml",
        "selector": "div.newslist a",
        "base_url": "https://www.airchina.com.cn"
    },
    {
        "nom": "China Eastern Airlines - News",
        "url": "https://ceairgroup.ceair.com/ceairgroup/English/News/index.html",
        "selector": "div.news-list a",
        "base_url": "https://ceairgroup.ceair.com"
    },
    {
        "nom": "China Southern Airlines - Media",
        "url": "https://www.csair.com/cn/about/news/",
        "selector": "div.news_list a",
        "base_url": "https://www.csair.com"
    },
    {
        "nom": "COMAC (C919) - Press",
        "url": "http://english.comac.cc/news/",
        "selector": "div.newslist a",
        "base_url": "http://english.comac.cc"
    }
]

# ---------------------------------------------------------------------------
# Fonctions communes
# ---------------------------------------------------------------------------
def charger_vus():
    if SEEN_FILE.exists():
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    return set()

def sauvegarder_vus(vus):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(vus), f)


def fetch_rss(source):
    """Récupère les articles d'un flux RSS (XML)."""
    articles = []
    try:
        resp = requests.get(source["url"], timeout=15,
                            headers={"User-Agent": "CFO-AviationAgent/1.0"})
        resp.raise_for_status()
        # Utilisation de lxml si disponible, sinon fallback
        try:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(resp.content)
        except:
            # fallback avec BeautifulSoup si XML mal formé
            soup = BeautifulSoup(resp.content, "xml")
            root = soup
        items = root.findall(".//item") or root.findall(".//entry")
        for item in items[:20]:
            titre = item.findtext("title") or item.findtext("{http://www.w3.org/2005/Atom}title") or ""
            lien = item.findtext("link") or item.findtext("{http://www.w3.org/2005/Atom}link") or ""
            if lien and not lien.startswith("http"):
                # parfois link est un attribut href
                if hasattr(item.find("link"), "attrib"):
                    lien = item.find("link").attrib.get("href", "")
            desc = item.findtext("description") or item.findtext("summary") or ""
            date = item.findtext("pubDate") or item.findtext("published") or ""
            if titre:
                articles.append({
                    "source": source["nom"],
                    "titre": titre.strip(),
                    "lien": lien.strip(),
                    "desc": desc[:600],
                    "date": date,
                    "id": hashlib.md5((titre + lien).encode()).hexdigest(),
                })
    except Exception as e:
        log.warning(f"Erreur RSS {source['nom']} : {e}")
    return articles


def scrape_source(source):
    """Extrait des articles depuis une page HTML."""
    articles = []
    try:
        resp = requests.get(source["url"], timeout=15,
                            headers={"User-Agent": "CFO-AviationAgent/1.0"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")
        links = soup.select(source["selector"])
        for link in links[:20]:
            titre = link.get_text(strip=True)
            if not titre or len(titre) < 5:
                continue
            href = link.get("href")
            if not href:
                continue
            if not href.startswith("http"):
                href = urljoin(source["base_url"], href)
            articles.append({
                "source": source["nom"],
                "titre": titre,
                "lien": href,
                "desc": "",
                "date": "",
                "id": hashlib.md5((titre + href).encode()).hexdigest(),
            })
    except Exception as e:
        log.warning(f"Erreur scrape {source['nom']} : {e}")
    return articles


def collecter_tous_articles():
    """Rassemble RSS + scrape."""
    tous = []
    for src in RSS_SOURCES:
        if src.get("type") == "rss" or "rss" in src["url"]:
            art = fetch_rss(src)
        else:
            art = scrape_source(src)
        log.info(f"{src['nom']} : {len(art)} articles")
        tous.extend(art)
    for src in SCRAPE_SOURCES:
        art = scrape_source(src)
        log.info(f"{src['nom']} : {len(art)} articles")
        tous.extend(art)
    return tous


def filtrer_pertinents(articles, vus):
    nouveaux = []
    for a in articles:
        if a["id"] in vus:
            continue
        texte = (a["titre"] + " " + a["desc"]).lower()
        if any(kw.lower() in texte for kw in KEYWORDS_AVIATION):
            nouveaux.append(a)
    return nouveaux


# ---------------------------------------------------------------------------
# Analyse par DeepSeek
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """Tu es un expert en aviation commerciale et en infrastructure aéroportuaire, 
spécialisé sur la Chine et l'Asie-Pacifique, conseillant un CFO d'une entreprise du secteur 
(compagnie aérienne, aéroport, MRO, concession, leasing).

Tu analyses les actualités sectorielles et évalues leur impact financier concret sur :
- Trafic passagers et cargo, capacités, load factors
- Revenus annexes (retail, parking, concessions)
- Coûts opérationnels (carburant, personnel, redevances)
- Investissements en infrastructure, financements, PPP
- Réglementations (droits de trafic, créneaux, environnement, sûreté)
- Flotte, commandes, livraisons, retraits
- Concurrence entre aéroports et compagnies

Ton analyse est en français, professionnelle, orientée décisions financières.
Niveau d'impact : CRITIQUE / IMPORTANT / À SURVEILLER / INFO
"""

def analyser_avec_deepseek(articles):
    if not articles:
        return "Aucune information sectorielle significative aujourd'hui."

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY non définie")

    client = anthropic.Anthropic(
        base_url="https://api.deepseek.com/anthropic",
        api_key=api_key
    )

    date_str = datetime.now().strftime("%d %B %Y")
    articles_txt = ""
    for i, a in enumerate(articles, 1):
        articles_txt += (
            f"\n[{i}] Source : {a['source']}\n"
            f"    Titre : {a['titre']}\n"
            f"    Lien  : {a['lien']}\n"
        )
        if a['desc']:
            articles_txt += f"    Résumé: {a['desc']}\n"

    prompt = (
        f"Veille secteur Aviation & Aéroports - Chine — {date_str}\n"
        f"Nombre d'articles : {len(articles)}\n\n"
        f"{articles_txt}\n\n"
        "Pour chaque information importante :\n"
        "1. IMPACT : CRITIQUE / IMPORTANT / À SURVEILLER / INFO\n"
        "2. RÉSUMÉ (1-2 phrases)\n"
        "3. IMPACT FINANCIER pour un CFO (ex: cash flow, marge, CAPEX, risque change)\n"
        "4. ACTION RECOMMANDÉE (alerter, analyser, opportunité, hedge...)\n\n"
        "Termine par :\n"
        "- SYNTHÈSE EXÉCUTIVE (5 lignes max)\n"
        "- 3 INDICATEURS CLÉS À SURVEILLER cette semaine\n"
        "- RISQUE PRINCIPAL pour le secteur en Chine"
    )

    log.info(f"Envoi de {len(articles)} articles à DeepSeek...")
    msg = client.messages.create(
        model="deepseek-v4-pro",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def generer_rapport(articles, analyse):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lignes = [
        "=" * 62,
        f"  VEILLE AVIATION & AÉROPORTS (Chine) — {now}",
        "  Pour : CFO du secteur aéronautique",
        "  Modèle : DeepSeek V4",
        "=" * 62,
        "",
        f"  {len(articles)} information(s) pertinente(s)",
        "",
        "  SOURCES SURVEILLÉES :",
    ]
    for s in RSS_SOURCES + SCRAPE_SOURCES:
        lignes.append(f"    - {s['nom']}")

    if articles:
        lignes += ["", "-" * 62, "  ARTICULES DU JOUR", "-" * 62]
        for i, a in enumerate(articles, 1):
            lignes.append(f"\n  [{i}] {a['source']}")
            lignes.append(f"      {a['titre']}")
            if a["lien"]:
                lignes.append(f"      {a['lien']}")

    lignes += [
        "", "-" * 62,
        "  ANALYSE & RECOMMANDATIONS",
        "-" * 62,
        analyse,
        "", "=" * 62,
    ]
    return "\n".join(lignes)

def sauvegarder_rapport(rapport):
    dossier = Path("rapports")
    dossier.mkdir(exist_ok=True)
    fichier = dossier / f"aviation_chine_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
    with open(fichier, "w", encoding="utf-8") as f:
        f.write(rapport)
    log.info(f"Rapport : {fichier}")


def executer_agent():
    log.info("Démarrage agent veille aviation Chine")
    try:
        vus = charger_vus()
        tous = collecter_tous_articles()
        pertinents = filtrer_pertinents(tous, vus)
        log.info(f"Articles pertinents nouveaux : {len(pertinents)}")
        analyse = analyser_avec_deepseek(pertinents)
        rapport = generer_rapport(pertinents, analyse)
        print(rapport)
        sauvegarder_rapport(rapport)
        for a in pertinents:
            vus.add(a["id"])
        sauvegarder_vus(vus)
        log.info("Terminé.")
    except Exception as e:
        log.exception(f"Erreur : {e}")

if __name__ == "__main__":
    executer_agent()