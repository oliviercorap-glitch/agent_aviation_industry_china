"""
Agent de veille sectorielle — Aviation & Aéroports (Chine)
Version stable avec correction du mode "thinking" DeepSeek
==========================================================
Sources :
 - Simple Flying
 - Airport World News
 (autres sources ajoutables facilement)

Fréquence : quotidienne (lundi-vendredi, 8h Shanghai)
Variables d'environnement requises : DEEPSEEK_API_KEY
"""

import os
import json
import logging
import hashlib
from datetime import datetime
from pathlib import Path

import requests
import anthropic
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

# Configuration des logs
LOG_FILE = Path("logs/agent_aviation.log")
SEEN_FILE = Path("seen_aviation_articles.json")
Path("logs").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(LOG_FILE, encoding="utf-8")],
)
log = logging.getLogger(__name__)

# Mots-clés sectoriels
KEYWORDS_AVIATION = [
    "aviation", "airport", "airline", "CAAC", "IATA", "ICAO", "traffic", "passenger",
    "cargo", "freight", "fleet", "route", "slot", "terminal", "runway", "ATC",
    "China", "Beijing", "Shanghai", "Guangzhou", "Shenzhen", "Chengdu", "Hong Kong",
    "Air China", "China Eastern", "China Southern", "Hainan Airlines", "Spring Airlines",
    "PEK", "PVG", "CAN", "PKX", "SHA", "CTU", "CGO",
    "safety", "certification", "C919", "COMAC", "Boeing", "Airbus", "MAX", "grounding",
    "recovery", "growth", "capacity", "load factor", "yield", "RASK", "CASK",
]

# Sources RSS fonctionnelles (testées)
RSS_SOURCES = [
    {
        "nom": "Simple Flying",
        "url": "https://simpleflying.com/feed/",
    },
    {
        "nom": "Airport World News",
        "url": "https://www.airport-world.com/feed/",
    },
    # Ajoutez d'autres sources ici si elles sont stables
]

# ---------------------------------------------------------------------------
# Fonctions utilitaires
# ---------------------------------------------------------------------------
def charger_vus():
    if SEEN_FILE.exists():
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def sauvegarder_vus(vus):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(vus), f, ensure_ascii=False, indent=2)

def fetch_rss(source):
    """Récupère les articles depuis un flux RSS."""
    articles = []
    try:
        resp = requests.get(source["url"], timeout=15,
                            headers={"User-Agent": "CFO-AviationAgent/1.0"})
        resp.raise_for_status()
        # Utilisation de BeautifulSoup pour parser le XML
        soup = BeautifulSoup(resp.content, "xml")
        items = soup.find_all("item") or soup.find_all("entry")
        for item in items[:15]:
            titre = item.find("title")
            titre = titre.text.strip() if titre else ""
            lien = item.find("link")
            if lien and lien.name == "link":
                lien = lien.get("href", "") if lien.has_attr("href") else lien.text.strip()
            else:
                lien = ""
            desc = item.find("description") or item.find("summary")
            desc = desc.text.strip()[:600] if desc else ""
            date = item.find("pubDate") or item.find("published")
            date = date.text.strip() if date else ""

            if titre:
                articles.append({
                    "source": source["nom"],
                    "titre": titre,
                    "lien": lien,
                    "desc": desc,
                    "date": date,
                    "id": hashlib.md5((titre + lien).encode()).hexdigest(),
                })
    except Exception as e:
        log.warning(f"Erreur RSS {source['nom']} : {e}")
    return articles

def collecter_tous_articles():
    """Rassemble tous les articles depuis les sources RSS."""
    tous = []
    for src in RSS_SOURCES:
        arts = fetch_rss(src)
        log.info(f"{src['nom']} : {len(arts)} articles")
        tous.extend(arts)
    return tous

def filtrer_pertinents(articles, vus):
    """Filtre les articles nouveaux et contenant des mots-clés."""
    nouveaux = []
    for a in articles:
        if a["id"] in vus:
            continue
        texte = (a["titre"] + " " + a["desc"]).lower()
        if any(kw.lower() in texte for kw in KEYWORDS_AVIATION):
            nouveaux.append(a)
    return nouveaux

# ---------------------------------------------------------------------------
# Analyse par DeepSeek (avec gestion du mode "thinking")
# ---------------------------------------------------------------------------
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

    # Extraction du texte en ignorant les blocs de type "thinking"
    texte_reponse = ""
    for bloc in msg.content:
        if hasattr(bloc, 'type') and bloc.type == "text":
            texte_reponse += bloc.text
        elif hasattr(bloc, 'text'):  # fallback pour d'anciens modèles
            texte_reponse += bloc.text

    if not texte_reponse:
        log.warning("Aucun bloc textuel trouvé dans la réponse DeepSeek.")
        return "L'API n'a pas renvoyé de réponse textuelle exploitable."

    return texte_reponse

# ---------------------------------------------------------------------------
# Génération et sauvegarde du rapport
# ---------------------------------------------------------------------------
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
    for s in RSS_SOURCES:
        lignes.append(f"    - {s['nom']}")

    if articles:
        lignes += ["", "-" * 62, "  ARTICLES DU JOUR", "-" * 62]
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
    dossier.mkdir(exist_ok=True, parents=True)
    fichier = dossier / f"aviation_chine_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
    with open(fichier, "w", encoding="utf-8") as f:
        f.write(rapport)
    log.info(f"Rapport créé : {fichier.absolute()}")

# ---------------------------------------------------------------------------
# Agent principal
# ---------------------------------------------------------------------------
def executer_agent():
    log.info("Démarrage agent veille aviation Chine (version corrigée)")
    try:
        vus = charger_vus()
        tous = collecter_tous_articles()
        pertinents = filtrer_pertinents(tous, vus)
        log.info(f"Articles pertinents nouveaux : {len(pertinents)}")
        if pertinents:
            analyse = analyser_avec_deepseek(pertinents)
        else:
            analyse = "Aucun nouvel article pertinent détecté aujourd'hui."
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
