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
#  KEYWORDS AND SOURCES (same as before - omitted for brevity)
#  (keep your existing KEYWORDS_GSE and SOURCES lists here)
# =============================================================================
# ... (paste your existing KEYWORDS_GSE and SOURCES lists here) ...

# =============================================================================
#  UTILITY FUNCTIONS (same as before - omitted)
# =============================================================================
# ... (paste your existing utility functions here) ...

# =============================================================================
#  DEEPSEEK PROMPTS (same as before)
# =============================================================================
# ... (paste SYSTEM_PROMPT_GSE and analyser_avec_deepseek here) ...

# =============================================================================
#  HTML REPORT GENERATION - ENHANCED WITH TOC AND SPACING
# =============================================================================
def markdown_to_html(text):
    if not text:
        return ""
    return markdown.markdown(text, extensions=['nl2br'])

def generer_rapport(articles, analyse):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # --- Parse analysis into blocks (same logic) ---
    parsed_blocks = []
    executive_summary = ""
    key_indicators = []
    main_risk = ""

    lines = analyse.splitlines()
    current_block_lines = []
    in_summary = False
    summary_lines = []

    for line in lines:
        if line.strip().startswith('- EXECUTIVE SUMMARY'):
            in_summary = True
            if current_block_lines:
                parsed_blocks.append('\n'.join(current_block_lines))
                current_block_lines = []
            continue
        if line.strip().startswith('- 3 KEY INDICATORS'):
            if in_summary:
                summary_lines = current_block_lines
                current_block_lines = []
                in_summary = False
            continue
        if line.strip().startswith('- MAIN RISK'):
            continue

        if in_summary:
            summary_lines.append(line)
        elif line.strip().startswith('[') and re.match(r'^\[\d+\]', line.strip()):
            if current_block_lines:
                parsed_blocks.append('\n'.join(current_block_lines))
                current_block_lines = []
            current_block_lines.append(line)
        else:
            if current_block_lines or line.strip():
                current_block_lines.append(line)

    if current_block_lines and not in_summary:
        if any('EXECUTIVE SUMMARY' in l for l in current_block_lines):
            summary_lines.extend(current_block_lines)
        else:
            parsed_blocks.append('\n'.join(current_block_lines))

    def extract_block_info(block):
        impact = "INFO"
        summary = ""
        biz_impact = ""
        action = ""
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

    summary_text = "\n".join(summary_lines).strip()
    exec_summary_match = re.search(r'- EXECUTIVE SUMMARY\s*(.*?)(?=- 3 KEY INDICATORS|$)', summary_text, re.DOTALL)
    if exec_summary_match:
        executive_summary = exec_summary_match.group(1).strip()
    indicators_match = re.search(r'- 3 KEY INDICATORS TO WATCH this week\s*(.*?)(?=- MAIN RISK|$)', summary_text, re.DOTALL)
    if indicators_match:
        key_indicators = [i.strip() for i in indicators_match.group(1).strip().split('\n') if i.strip()]
    risk_match = re.search(r'- MAIN RISK\s*(.*?)$', summary_text, re.DOTALL)
    if risk_match:
        main_risk = risk_match.group(1).strip()

    if not block_infos and not executive_summary:
        block_infos = [{'impact': 'INFO', 'summary': '', 'business_impact': '', 'recommended_action': '', 'raw': analyse}]
        executive_summary = ""

    # Convert Markdown
    for b in block_infos:
        b['summary'] = markdown_to_html(b.get('summary', ''))
        b['business_impact'] = markdown_to_html(b.get('business_impact', ''))
        b['recommended_action'] = markdown_to_html(b.get('recommended_action', ''))
        if 'raw' in b:
            b['raw'] = markdown_to_html(b['raw'])

    exec_summary_html = markdown_to_html(executive_summary)
    main_risk_html = markdown_to_html(main_risk)
    key_indicators_html = [markdown_to_html(ind) for ind in key_indicators]

    impact_icons = {'CRITICAL': '🚨', 'IMPORTANT': '⚠️', 'WATCH': '👀', 'INFO': 'ℹ️'}
    impact_counts = {}
    for b in block_infos:
        imp = b.get('impact', 'INFO')
        impact_counts[imp] = impact_counts.get(imp, 0) + 1

    # --- Generate HTML with TOC ---
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
            line-height: 1.8;
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
            background: #f1f5f9; border-radius: 16px; padding: 18px 24px; margin-bottom: 30px;
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
            font-size: 20px; font-weight: 600; margin: 48px 0 16px 0;
            padding-bottom: 8px; border-bottom: 2px solid #e2e8f0;
        }}
        .sources-list {{
            display: flex; flex-wrap: wrap; gap: 8px 16px;
            background: #f8fafc; padding: 12px 16px; border-radius: 12px; margin-bottom: 30px;
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

        /* TOC */
        .toc {{
            background: #f1f5f9;
            border-radius: 16px;
            padding: 20px 24px;
            margin: 30px 0 20px 0;
        }}
        .toc h3 {{ font-size: 18px; font-weight: 600; margin-bottom: 12px; color: #0f172a; }}
        .toc ul {{
            list-style: none;
            display: flex;
            flex-wrap: wrap;
            gap: 8px 16px;
            padding: 0;
        }}
        .toc li {{
            font-size: 14px;
        }}
        .toc a {{
            color: #1e40af;
            text-decoration: none;
            font-weight: 500;
            display: inline-flex;
            align-items: center;
            gap: 4px;
        }}
        .toc a:hover {{ text-decoration: underline; }}
        .toc .toc-impact {{
            font-size: 12px;
            padding: 0 6px;
            border-radius: 12px;
            background: #94a3b8;
            color: white;
            font-weight: 600;
        }}
        .toc .toc-impact.critical {{ background: #dc2626; }}
        .toc .toc-impact.important {{ background: #f59e0b; }}
        .toc .toc-impact.watch {{ background: #eab308; color: #0f172a; }}
        .toc .toc-impact.info {{ background: #3b82f6; }}

        /* Analysis cards */
        .analysis-card {{
            border-left: 6px solid #94a3b8;
            background: #fafcff;
            border-radius: 12px;
            padding: 24px 28px;
            margin-bottom: 28px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.06);
            transition: box-shadow 0.2s;
        }}
        .analysis-card:hover {{ box-shadow: 0 6px 16px rgba(0,0,0,0.08); }}
        .analysis-card.impact-critical {{ border-left-color: #dc2626; }}
        .analysis-card.impact-important {{ border-left-color: #f59e0b; }}
        .analysis-card.impact-watch {{ border-left-color: #eab308; }}
        .analysis-card.impact-info {{ border-left-color: #3b82f6; }}

        .card-header {{
            display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 12px;
        }}
        .card-header .impact-badge {{
            font-size: 14px; padding: 4px 16px; border-radius: 30px;
        }}
        .card-body p {{
            margin-top: 0.8em;
            margin-bottom: 0.8em;
        }}
        .card-body p:first-of-type {{ margin-top: 0; }}
        .card-body strong {{
            font-weight: 600; color: #1e293b;
        }}
        .card-body ul, .card-body ol {{
            margin: 0.6em 0 0.6em 1.5em;
        }}
        .card-body li {{
            margin-bottom: 0.3em;
        }}
        .back-link {{
            font-size: 14px;
            color: #64748b;
            text-decoration: none;
            display: inline-block;
            margin-top: 12px;
        }}
        .back-link:hover {{ color: #1e40af; }}

        .exec-summary {{
            background: #dbeafe; border-left: 6px solid #2563eb; border-radius: 12px;
            padding: 20px 24px; margin-bottom: 28px;
        }}
        .exec-summary h3 {{ font-size: 18px; font-weight: 600; margin-bottom: 6px; color: #1e3a8a; }}
        .key-indicators {{
            background: #fef3c7; border-left: 6px solid #d97706; border-radius: 12px;
            padding: 20px 24px; margin-bottom: 28px;
        }}
        .key-indicators h3 {{ font-size: 18px; font-weight: 600; margin-bottom: 6px; color: #92400e; }}
        .key-indicators ul {{ list-style: disc; margin-left: 20px; }}
        .main-risk {{
            background: #fee2e2; border-left: 6px solid #dc2626; border-radius: 12px;
            padding: 20px 24px; margin-bottom: 28px;
        }}
        .main-risk h3 {{ font-size: 18px; font-weight: 600; margin-bottom: 6px; color: #991b1b; }}

        .footer {{
            margin-top: 48px; font-size: 13px; color: #94a3b8; text-align: center;
            border-top: 1px solid #e2e8f0; padding-top: 24px;
        }}
        @media (max-width: 640px) {{
            .container {{ padding: 20px 16px; }}
            .stats {{ flex-direction: column; gap: 8px; }}
            .article-table th, .article-table td {{ padding: 8px 6px; }}
            .article-table .source {{ white-space: normal; }}
            .toc ul {{ flex-direction: column; gap: 4px; }}
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

        <!-- Table of Contents -->
        <div class="toc">
            <h3>📑 Table of Contents</h3>
            <ul>
    """
    # Add TOC entries for executive summary, key indicators, main risk if present
    toc_items = []
    if exec_summary_html:
        toc_items.append(('<a href="#exec-summary">📌 Executive Summary</a>', ''))
    if key_indicators_html:
        toc_items.append(('<a href="#key-indicators">📈 Key Indicators</a>', ''))
    if main_risk_html:
        toc_items.append(('<a href="#main-risk">⚠️ Main Risk</a>', ''))
    # Add each analysis card
    for idx, b in enumerate(block_infos):
        impact = b.get('impact', 'INFO')
        label = f"Analysis #{idx+1}"
        toc_items.append((
            f'<a href="#analysis-{idx}">{label} <span class="toc-impact {impact.lower()}">{impact}</span></a>',
            ''
        ))
    for item, _ in toc_items:
        html += f"<li>{item}</li>"
    html += """
            </ul>
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

        <h2 class="section-title" id="analysis-section">📊 Analysis & Recommendations</h2>
    """

    # Executive Summary
    if exec_summary_html:
        html += f"""
        <div class="exec-summary" id="exec-summary">
            <h3>📌 Executive Summary</h3>
            {exec_summary_html}
            <a href="#" class="back-link">↑ Back to top</a>
        </div>
        """

    # Analysis cards
    for idx, block in enumerate(block_infos):
        impact = block.get('impact', 'INFO')
        summary = block.get('summary', '')
        biz = block.get('business_impact', '')
        action = block.get('recommended_action', '')

        card_id = f"analysis-{idx}"
        html += f"""
        <div class="analysis-card impact-{impact.lower()}" id="{card_id}">
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
        # If no structured fields, show raw
        if not summary and not biz and not action:
            raw = block.get('raw', '')
            html += raw
        html += f"""
            </div>
            <a href="#analysis-section" class="back-link">↑ Back to top</a>
        </div>
        """

    # Key Indicators
    if key_indicators_html:
        html += """
        <div class="key-indicators" id="key-indicators">
            <h3>📈 Key Indicators to Watch This Week</h3>
            <ul>
        """
        for ind in key_indicators_html:
            html += f"<li>{ind}</li>"
        html += """
            </ul>
            <a href="#" class="back-link">↑ Back to top</a>
        </div>
        """

    # Main Risk
    if main_risk_html:
        html += f"""
        <div class="main-risk" id="main-risk">
            <h3>⚠️ Main Risk</h3>
            {main_risk_html}
            <a href="#" class="back-link">↑ Back to top</a>
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

# --- EXECUTION ---------------------------------------------------------------
def executer_agent():
    log.info("Starting GSE + competitors + market signals intelligence agent (HTML/EN + TOC)")
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
