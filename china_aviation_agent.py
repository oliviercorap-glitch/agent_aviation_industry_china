import os
import json
import logging
import hashlib
import requests
import re
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import anthropic
import time

# --- Configuration -----------------------------------------------------------
load_dotenv()
LOG_FILE = Path("logs/agent_aviation.log")
SEEN_FILE = Path("seen_aviation_articles.json")
Path("logs").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(LOG_FILE, encoding="utf-8")],
)
log = logging.getLogger(__name__)

# --- Mots-clés élargis (inclut des termes en chinois) -----------------------
KEYWORDS_AVIATION = [
    # English keywords
    "aviation", "airport", "airline", "CAAC", "IATA", "ICAO", "passenger", "cargo",
    "freight", "fleet", "route", "terminal", "runway", "ATC", "safety", "certification",
    "C919", "COMAC", "Boeing", "Airbus", "MAX", "grounding", "traffic", "growth",
    "capacity", "investment", "infrastructure", "expansion", "renovation",
    # Chinese keywords
    "机场", "民航", "航班", "旅客", "吞吐量", "航线", "航站楼", "跑道", "扩建", "投资", "C919",
    "中国商飞", "波音", "空客", "监管"
]

# --- Liste exhaustive des sources --------------------------------------------
SOURCES = [
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
        "nom": "China Daily - Aviation",
        "url": "https://www.chinadaily.com.cn/",
        "type": "scrape_generic",
        "selector": "div.newsList a, .news-item a",
        "base_url": "https://www.chinadaily.com.cn",
        "encoding": "utf-8"
    },
    {
        "nom": "International Airport Review",
        "url": "https://www.internationalairportreview.com/news/",
        "type": "scrape_generic",
        "selector": "article h3 a, .news-item a",
        "base_url": "https://www.internationalairportreview.com",
    },
    {
        "nom": "Airport Technology",
        "url": "https://www.airport-technology.com/news",
        "type": "scrape_generic",
        "selector": "article h3 a, .card-title a, a",
        "base_url": "https://www.airport-technology.com",
    },
    {
        "nom": "CGTN - Aviation",
        "url": "https://news.cgtn.com/",
        "type": "scrape_generic",
        "selector": "div.newsList a, a",
        "base_url": "https://news.cgtn.com",
        "encoding": "utf-8"
    },
    {
        "nom": "ACI Asia-Pacific News",
        "url": "https://www.aci-asiapac.aero/news",
        "type": "scrape_generic",
        "selector": "div.news-item a, a",
        "base_url": "https://www.aci-asiapac.aero",
        "encoding": "utf-8"
    }
]

# --- Fonctions de scraping ---------------------------------------------------
def charger_vus():
    if SEEN_FILE.exists():
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            try:
                return set(json.load(f))
            except json.JSONDecodeError:
                log.warning("Fichier seen_aviation_articles.json corrompu, réinitialisation.")
                return set()
    return set()

def sauvegarder_vus(vus):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(vus), f, ensure_ascii=False, indent=2)

def scrape_caac(source):
    """Scraping spécifique pour le site CAAC pour contourner des structures complexes."""
    articles = []
    try:
        resp = requests.get(source["url"], timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser", from_encoding='utf-8')
        # Zone d'actualité ciblée
        news_block = soup.find('div', class_='newsList') or soup.find('div', class_='list') or soup.find('ul', class_='news')
        if news_block:
            links = news_block.find_all('a')
        else:
            links = soup.find_all('a', href=True)
        for link in links[:15]:
            titre = link.get_text(strip=True)
            if not titre or len(titre) < 15 or ">" in titre:
                continue
            href = link.get('href')
            if href and not href.startswith('http'):
                href = 'https://www.caac.gov.cn' + href
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
        log.warning(f"Erreur scraping {source['nom']} : {e}")
    return articles

def scrape_generic(source):
    """Scraping générique amélioré."""
    articles = []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
        resp = requests.get(source["url"], timeout=30, headers=headers)
        resp.raise_for_status()
        encoding = source.get('encoding', 'utf-8')
        soup = BeautifulSoup(resp.content, "html.parser", from_encoding=encoding)
        links = soup.select(source["selector"])
        unique_links = {}
        for link in links:
            href = link.get('href')
            titre = link.get_text(strip=True)
            if href and titre and len(titre) > 15 and not titre.lower().startswith('read more'):
                if href.startswith('/'):
                    href = source["base_url"] + href
                elif not href.startswith('http'):
                    href = source["base_url"] + "/" + href
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
        log.info(f"  Scraping {source['nom']}: {len(articles)} articles")
    except Exception as e:
        log.warning(f"Erreur scraping {source['nom']} : {e}")
    return articles

def collecter_tous_articles():
    """Rassemble tous les articles via les différentes méthodes de scraping."""
    tous_articles = []
    for source in SOURCES:
        log.info(f"Collecte depuis : {source['nom']}")
        if source["type"] == "scrape_caac":
            articles = scrape_caac(source)
        elif source["type"] == "scrape_generic":
            articles = scrape_generic(source)
        else:
            articles = []
        tous_articles.extend(articles)
        time.sleep(1)
    log.info(f"Total articles bruts collectés: {len(tous_articles)}")
    return tous_articles

def filtrer_pertinents(articles, vus):
    """Filtre les articles nouveaux et contenant des mots-clés."""
    nouveaux = []
    for a in articles:
        if a["id"] in vus:
            continue
        texte = (a["titre"] + " " + a.get("desc", "")).lower()
        if any(kw.lower() in texte for kw in KEYWORDS_AVIATION):
            nouveaux.append(a)
    log.info(f"Articles pertinents et nouveaux : {len(nouveaux)}")
    return nouveaux

# --- Analyse par DeepSeek ----------------------------------------------------
SYSTEM_PROMPT = """Tu es un expert en aviation commerciale et en infrastructure aéroportuaire, 
spécialisé sur la Chine et l'Asie-Pacifique, conseillant un CFO d'une entreprise du secteur.

Tu analyses les actualités sectorielles et évalues leur impact financier concret sur :
- Trafic passagers et cargo, capacités, load factors
- Revenus annexes (retail, parking, concessions)
- Coûts opérationnels (carburant, personnel, redevances)
- Investissements en infrastructure, financements, PPP
- Réglementations (droits de trafic, créneaux, environnement, sûreté)
- Flotte, commandes, livraisons, retraits

Ton analyse est en français, professionnelle, orientée décisions financières.
Niveau d'impact : CRITIQUE / IMPORTANT / À SURVEILLER / INFO
"""

def analyser_avec_deepseek(articles):
    if not articles:
        return "Aucune information sectorielle significative aujourd'hui."

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY non définie")

    client = anthropic.Anthropic(base_url="https://api.deepseek.com/anthropic", api_key=api_key)
    date_str = datetime.now().strftime("%d %B %Y")
    articles_txt = ""
    for i, a in enumerate(articles, 1):
        articles_txt += f"\n[{i}] Source : {a['source']}\n"
        articles_txt += f"    Titre : {a['titre']}\n"
        articles_txt += f"    Lien  : {a['lien']}\n"
        if a.get('desc'):
            articles_txt += f"    Résumé: {a['desc']}\n"

    prompt = (f"Veille secteur Aviation & Aéroports - Chine — {date_str}\n"
              f"Nombre d'articles : {len(articles)}\n\n{articles_txt}\n\n"
              "Pour chaque information importante :\n"
              "1. IMPACT : CRITIQUE / IMPORTANT / À SURVEILLER / INFO\n"
              "2. RÉSUMÉ (1-2 phrases)\n"
              "3. IMPACT FINANCIER pour un CFO (ex: cash flow, marge, CAPEX, risque change)\n"
              "4. ACTION RECOMMANDÉE (alerter, analyser, opportunité, hedge...)\n\n"
              "Termine par :\n"
              "- SYNTHÈSE EXÉCUTIVE (5 lignes max)\n"
              "- 3 INDICATEURS CLÉS À SURVEILLER cette semaine\n"
              "- RISQUE PRINCIPAL pour le secteur en Chine")

    log.info(f"Envoi de {len(articles)} articles à DeepSeek...")
    msg = client.messages.create(model="deepseek-v4-pro",
                                 max_tokens=4096,
                                 system=SYSTEM_PROMPT,
                                 messages=[{"role": "user", "content": prompt}])
    # Extraction du texte en ignorant les blocs de type "thinking"
    texte_reponse = ""
    for bloc in msg.content:
        if hasattr(bloc, 'type') and bloc.type == "text":
            texte_reponse += bloc.text
        elif hasattr(bloc, 'text'):
            texte_reponse += bloc.text
    if not texte_reponse:
        log.warning("Aucun bloc textuel trouvé dans la réponse DeepSeek.")
        return "L'API n'a pas renvoyé de réponse textuelle exploitable."
    return texte_reponse

# --- Génération du rapport ---------------------------------------------------
def generer_rapport(articles, analyse):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lignes = ["=" * 62,
              f"  VEILLE AVIATION & AÉROPORTS (Chine) — {now}",
              "  Pour : CFO du secteur aéronautique",
              "  Modèle : DeepSeek V4", "=" * 62, "",
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
    fichier = dossier / f"aviation_chine_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
    with open(fichier, "w", encoding="utf-8") as f:
        f.write(rapport)
    log.info(f"Rapport créé : {fichier.absolute()}")

# --- Exécution principale ----------------------------------------------------
def executer_agent():
    log.info("Démarrage agent veille aviation Chine (version enrichie)")
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
        log.exception(f"Erreur : {e}")

if __name__ == "__main__":
    executer_agent()
