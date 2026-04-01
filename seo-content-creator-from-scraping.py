import streamlit as st
import requests
from bs4 import BeautifulSoup
from openai import OpenAI
from docx import Document
from io import BytesIO


# ======================
# SESSION STATE
# ======================

if "article" not in st.session_state:
    st.session_state.article = ""

if "title_tag" not in st.session_state:
    st.session_state.title_tag = ""

if "meta_description" not in st.session_state:
    st.session_state.meta_description = ""


# ======================
# SERPER ORGANIC RESULTS
# ======================

def get_competitors(keyword: str, num_results: int, serper_key: str, hl: str, gl: str):
    url = "https://google.serper.dev/search"

    headers = {
        "X-API-KEY": serper_key,
        "Content-Type": "application/json"
    }

    competitors = []
    seen_urls = set()
    start = 0

    blocked_domains = [
        "youtube.com",
        "youtu.be",
        "tiktok.com",
        "instagram.com",
        "facebook.com",
        "pinterest.com"
    ]

    while len(competitors) < num_results and start <= 90:
        payload = {
            "q": keyword,
            "gl": gl,
            "hl": hl,
            "num": 10,
            "start": start
        }

        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()

        organic = data.get("organic", [])
        if not organic:
            break

        for item in organic:
            link = item.get("link")

            if not link:
                continue

            normalized_link = link.strip().rstrip("/")

            if any(domain in normalized_link for domain in blocked_domains):
                continue

            if normalized_link in seen_urls:
                continue

            seen_urls.add(normalized_link)

            competitors.append({
                "title": item.get("title", ""),
                "link": normalized_link
            })

            if len(competitors) >= num_results:
                break

        start += 10

    return competitors[:num_results]


# ======================
# PEOPLE ALSO ASK
# ======================

def get_people_also_ask(keyword: str, serpapi_key: str, hl: str, gl: str):
    url = "https://serpapi.com/search.json"

    params = {
        "engine": "google",
        "q": keyword,
        "hl": hl,
        "gl": gl,
        "api_key": serpapi_key
    }

    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    questions = []
    seen = set()

    for item in data.get("related_questions", []):
        q = item.get("question")
        if not q:
            continue

        clean_q = q.strip()
        if clean_q in seen:
            continue

        seen.add(clean_q)
        questions.append(clean_q)

    return questions[:10]


# ======================
# SCRAPING PAGINA
# ======================

def fetch_page(url: str):
    try:
        resp = requests.get(
            url,
            timeout=15,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            }
        )
        resp.raise_for_status()

        html = resp.text
        soup = BeautifulSoup(html, "html.parser")

        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        text = " ".join(soup.get_text().split())

        return html, text[:18000]

    except Exception:
        return "", ""


def extract_metadata(html: str):
    soup = BeautifulSoup(html, "html.parser")

    title = soup.title.string.strip() if soup.title and soup.title.string else ""

    h1_tag = soup.find("h1")
    h1 = h1_tag.get_text(strip=True) if h1_tag else ""

    meta_desc = ""
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and "content" in meta.attrs:
        meta_desc = meta["content"].strip()

    return title, h1, meta_desc


# ======================
# GENERAZIONE ARTICOLO
# ======================

def parse_generated_content(content: str):
    title = ""
    meta = ""
    article = content

    if "TITLE TAG:" in content and "META DESCRIPTION:" in content and "ARTICLE HTML:" in content:
        after_title = content.split("TITLE TAG:", 1)[1]
        title = after_title.split("META DESCRIPTION:", 1)[0].strip()

        after_meta = after_title.split("META DESCRIPTION:", 1)[1]
        meta = after_meta.split("ARTICLE HTML:", 1)[0].strip()

        article = after_meta.split("ARTICLE HTML:", 1)[1].strip()

    return title, meta, article


def generate_article(keyword: str, competitors: list, paa: list, openai_key: str, language: str):
    client = OpenAI(api_key=openai_key)

    merged = ""

    for comp in competitors:
        merged += f"""
URL: {comp['link']}

TITLE: {comp['html_title']}
H1: {comp['h1']}
META: {comp['meta_desc']}

CONTENUTO:
{comp['text']}

-------------------------
"""

    paa_block = "\n".join([f"- {q}" for q in paa]) if paa else "Nessuna PAA disponibile."

    prompt = f"""
Sei un content writer SEO esperto.

Scrivi un contenuto SEO completo per la keyword:

{keyword}

Language code della ricerca: {language}

Il risultato deve contenere:

TITLE TAG (max 60 caratteri)
META DESCRIPTION (max 155 caratteri, naturale e con soft CTA)
ARTICOLO HTML (800-1500 parole)

L'articolo deve essere scritto in HTML pronto per CMS.

Regole HTML:
- usa <h2> e <h3>
- usa <p>
- usa <ul> <ol>
- usa <strong>
- usa <table> se utile
- NON includere <html> <body>

Le PAA NON devono comparire come Q&A.

# Requisiti editoriali

- Usa gli heading (H1, H2, H3) per formulare quesiti espliciti basati su keyword con volume di ricerca.
- Inserisci sempre la maiuscola a inizio frase.
- Utilizza elenchi puntati o numerati quando utile.
- Le tabelle devono essere ottimizzate per viewport mobile (leggibili da smartphone).
- Evidenzia con **strong** le entità chiave.
- Evita testo di riempimento: ogni paragrafo deve aggiungere valore informativo.
- Evita paragrafi schematici: il testo deve essere discorsivo e ricco. No paragrafi composti solo da punti elenco.
- Al termine dell'articolo suggerisci almeno 4 FAQ relative al contentenuto in formato Q&A

PAA INSIGHTS:
{paa_block}

COMPETITOR DATA:
{merged}

Formato output:

TITLE TAG:
...

META DESCRIPTION:
...

ARTICLE HTML:
...
"""

    response = client.chat.completions.create(
        model="gpt-5.4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )

    content = response.choices[0].message.content or ""
    return parse_generated_content(content)


# ======================
# WORD EXPORT
# ======================

def create_word_file(title_tag: str, meta_description: str, article: str):
    doc = Document()

    doc.add_heading("Title Tag", level=2)
    doc.add_paragraph(title_tag)

    doc.add_heading("Meta Description", level=2)
    doc.add_paragraph(meta_description)

    doc.add_heading("HTML Article", level=2)
    doc.add_paragraph(article)

    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)

    return buffer


# ======================
# SIDEBAR API
# ======================

st.sidebar.title("API Configuration")

st.sidebar.header("SERP scraping")
SERPER_KEY = st.sidebar.text_input(
    "Serper.dev API Key",
    type="password"
)

st.sidebar.header("People Also Ask")
SERPAPI_KEY = st.sidebar.text_input(
    "SerpAPI Key",
    type="password"
)

st.sidebar.header("AI generation")
OPENAI_KEY = st.sidebar.text_input(
    "OpenAI API Key",
    type="password"
)


# ======================
# UI
# ======================

st.markdown(
    f"""
    <div style="text-align:center; padding-top:10px;">
        <img src="{LOGO_URL}" width="220">
        <h1 style="margin-top:15px; margin-bottom:5px;">Magic Article Generator from Scraping</h1>
        <p style="font-size:18px; color:#6b7280; margin-bottom:25px;">
        Genera contenuti SEO analizzando le PAA e i contenuti dei competitor.
        </p>
        <hr style="margin-top:10px; margin-bottom:25px;">
    </div>
    """,
    unsafe_allow_html=True
)

keyword = st.text_input("Keyword")
num_results = st.slider("Numero competitor organici da analizzare", 1, 20, 5)
country = st.text_input("Country code", "it")
language = st.text_input("Language code", "it")

generate = st.button("Genera contenuto")


# ======================
# GENERAZIONE
# ======================

if generate:
    if not SERPER_KEY or not SERPAPI_KEY or not OPENAI_KEY:
        st.error("Inserisci tutte le API key nella sidebar.")
        st.stop()

    if not keyword.strip():
        st.error("Inserisci una keyword.")
        st.stop()

    st.session_state.article = ""
    st.session_state.title_tag = ""
    st.session_state.meta_description = ""

    st.subheader("SERP Insights")

    paa_placeholder = st.empty()
    url_placeholder = st.empty()
    progress = st.progress(0)

    with st.spinner("Recupero risultati organici e People Also Ask..."):
        competitors = get_competitors(
            keyword=keyword,
            num_results=num_results,
            serper_key=SERPER_KEY,
            hl=language,
            gl=country
        )

        paa = get_people_also_ask(
            keyword=keyword,
            serpapi_key=SERPAPI_KEY,
            hl=language,
            gl=country
        )

    if not competitors:
        st.error("Nessun risultato organico trovato.")
        st.stop()

    with paa_placeholder.container():
        st.markdown("### People Also Ask")
        if paa:
            for q in paa:
                st.write("-", q)
        else:
            st.caption("Nessuna PAA trovata.")

    enriched = []
    scraped = []

    for i, comp in enumerate(competitors, start=1):
        scraped.append(comp["link"])

        with url_placeholder.container():
            st.markdown("### URL scrapate")
            for u in scraped:
                st.write("-", u)

        html, text = fetch_page(comp["link"])
        html_title, h1, meta_desc = extract_metadata(html)

        enriched.append({
            **comp,
            "html_title": html_title,
            "h1": h1,
            "meta_desc": meta_desc,
            "text": text
        })

        progress.progress(i / len(competitors))

    with st.spinner(f"Generazione articolo su {len(enriched)} contenuti organici..."):
        title_tag, meta_description, article = generate_article(
            keyword=keyword,
            competitors=enriched,
            paa=paa,
            openai_key=OPENAI_KEY,
            language=language
        )

    st.session_state.title_tag = title_tag
    st.session_state.meta_description = meta_description
    st.session_state.article = article


# ======================
# OUTPUT
# ======================

if st.session_state.article:
    st.subheader("SEO Metadata")

    st.write("**Title Tag**")
    st.write(st.session_state.title_tag)

    st.write("**Meta Description**")
    st.write(st.session_state.meta_description)

    st.subheader("Articolo HTML")
    st.code(st.session_state.article, language="html")

    word_file = create_word_file(
        st.session_state.title_tag,
        st.session_state.meta_description,
        st.session_state.article
    )

    st.download_button(
        label="Scarica Word",
        data=word_file,
        file_name="articolo_seo.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
