import streamlit as st
import google.generativeai as genai
import fitz
import docx
import json
import difflib
import re
import unicodedata

st.set_page_config(page_title="Conferência MKT", page_icon="💊", layout="wide")

st.markdown("""
<style>
    [data-testid="stHeader"] { visibility: hidden; }
    .texto-box { 
        font-family: 'Consolas', monospace; font-size: 0.95rem; line-height: 1.6; color: #212529;
        background-color: #ffffff; padding: 15px; border-radius: 8px; border: 1px solid #ced4da;
        white-space: pre-wrap; text-align: left;
    }
    .highlight-red { background-color: #ffcdd2; color: #b71c1c; padding: 2px; border-radius: 3px; font-weight: bold; }
    .highlight-blue { background-color: #e3f2fd; color: #0d47a1; padding: 2px 6px; border-radius: 12px; font-weight: bold; }
    .border-ok { border-left: 5px solid #4caf50 !important; }
    .border-warn { border-left: 5px solid #f44336 !important; }
    .border-info { border-left: 5px solid #2196f3 !important; }
    div[data-testid="stMetric"] { background-color: #f8f9fa; border: 1px solid #dee2e6; padding: 10px; border-radius: 5px; }
</style>
""", unsafe_allow_html=True)

MODELO_FIXO = "models/gemini-flash-latest"
def limpar(txt):
    if not txt: return ""
    txt = unicodedata.normalize('NFKD', txt)
    txt = txt.replace('\u00a0', ' ').replace('\r', '')
    txt = re.sub(r'(?m)^\s*[\._-]{3,}\s*$', '', txt)
    txt = re.sub(r'\.{4,}', ' ', txt)
    txt = re.sub(r'[ \t]+', ' ', txt)
    return txt.strip()

def datas_azuis(html):
    return re.sub(r'(?<!\d)(\d{2}/\d{2}/\d{4})(?!\d)', r'<span class="highlight-blue">\1</span>', html)

def diff_html(r, n):
    if not r: r = ""; 
    if not n: n = ""
    TOK = "🔨"
    rt = limpar(r).replace('\n', f' {TOK} ')
    nt = limpar(n).replace('\n', f' {TOK} ')
    matcher = difflib.SequenceMatcher(None, rt.split(), nt.split(), autojunk=False)
    out = []
    diff = False
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        trecho = " ".join(nt.split()[j1:j2]).replace(TOK, "\n")
        if tag == 'equal': out.append(trecho)
        elif tag in ['replace', 'insert']:
            if trecho.strip():
                out.append(f'<span class="highlight-red">{trecho}</span>')
                diff = True
            else: out.append(trecho)
        elif tag == 'delete': diff = True
    return " ".join(out).replace(" \n ", "\n").replace("\n ", "\n"), diff

def extrair(up):
    try:
        txt = ""
        if up.name.lower().endswith('.pdf'):
            doc = fitz.open(stream=up.read(), filetype="pdf")
            for p in doc:
                blocks = p.get_text("dict", flags=11, sort=True)["blocks"]
                for b in blocks:
                    for l in b.get("lines", []):
                        ln = ""
                        for s in l.get("spans", []):
                            c = s["text"]
                            if (s["flags"] & 16) or "bold" in s["font"].lower(): ln += f"<b>{c}</b>"
                            else: ln += c
                        txt += ln + " "
                    txt += "\n"
        elif up.name.lower().endswith('.docx'):
            doc = docx.Document(up)
            for p in doc.paragraphs:
                ln = ""
                for r in p.runs:
                    if r.bold: ln+=f"<b>{r.text}</b>"
                    else: ln+=r.text
                txt += ln + "\n\n"
        return limpar(txt)
    except: return ""

def reparar_json(t):
    t = t.replace("```json", "").replace("```", "").strip()
    try: return json.loads(t)
    except:
        try: return json.loads(t + '"]}]}')
        except: return None

st.title("💊 Conferência MKT")
c1, c2 = st.columns(2)
f1 = c1.file_uploader("Ref", type=["pdf", "docx"], key="f1")
f2 = c2.file_uploader("MKT", type=["pdf", "docx"], key="f2")

if st.button("🚀 Processar"):
    keys = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2")]
    valid = [k for k in keys if k]
    if not valid: st.stop()
    
    if f1 and f2:
        with st.spinner("Processando..."):
            f1.seek(0); f2.seek(0)
            tr = extrair(f1)
            tm = extrair(f2)
            
            p = f"""
            ATUE COMO EXTRATOR LITERAL.
            IN1: {tr[:500000]}
            IN2: {tm[:500000]}
            TAREFA:
            1. Extraia o texto COMPLETO E EXATO.
            2. Não invente palavras. Não corrija.
            SECOES: ["APRESENTAÇÕES", "COMPOSIÇÃO", "PARA QUE ESTE MEDICAMENTO É INDICADO", "COMO ESTE MEDICAMENTO FUNCIONA?", "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?", "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?", "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?", "COMO DEVO USAR ESTE MEDICAMENTO?", "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?", "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?", "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?", "DIZERES LEGAIS"]
            JSON: {{"data_anvisa_ref": "...", "data_anvisa_mkt": "...", "secoes": [{{"titulo": "...", "texto_anvisa": "...", "texto_mkt": "..."}}]}}
            """
            
            res = None
            cfg = {"response_mime_type": "application/json", "temperature": 0.0}
            
            for k in valid:
                try:
                    genai.configure(api_key=k)
                    mod = genai.GenerativeModel(MODELO_FIXO, generation_config=cfg)
                    resp = mod.generate_content(p)
                    res = reparar_json(resp.text)
                    if res: break
                except: continue
                
            if res:
                final = []
                err = 0
                isentas = ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]
                
                for s in res.get("secoes", []):
                    t = s["titulo"]
                    tr = s["texto_anvisa"]
                    tm = s["texto_mkt"]
                    
                    if any(x in t.upper() for x in isentas):
                        stt = "CONFORME"
                        hr = datas_azuis(tr) if "DIZERES" in t.upper() else tr
                        hm = datas_azuis(tm) if "DIZERES" in t.upper() else tm
                    else:
                        hm, df = diff_html(tr, tm)
                        hr = datas_azuis(tr)
                        stt = "DIVERGENTE" if df else "CONFORME"
                        if df: err += 1
                    final.append({"t":t, "tr":hr, "tm":hm, "s":stt})
                
                st.markdown("### Resumo")
                cx, cy, cz = st.columns(3)
                cx.metric("Ref", res.get("data_anvisa_ref"))
                cy.metric("MKT", res.get("data_anvisa_mkt"))
                cz.metric("Divergências", err)
                
                for i in final:
                    if "DIZERES" in i['t'].upper(): css="border-info"; ic="⚖️"; ex=False
                    elif any(x in i['t'].upper() for x in ["APRESENTAÇÕES", "COMPOSIÇÃO"]): css="border-info"; ic="📋"; ex=False
                    elif i['s'] == "DIVERGENTE": css="border-warn"; ic="⚠️"; ex=True
                    else: css="border-ok"; ic="✅"; ex=False
                    with st.expander(f"{ic} {i['t']}", expanded=ex):
                        ca, cb = st.columns(2)
                        ca.markdown(f'<div class="texto-box {css}">{i["tr"].replace(chr(10), "<br>")}</div>', unsafe_allow_html=True)
                        cb.markdown(f'<div class="texto-box {css}">{i["tm"].replace(chr(10), "<br>")}</div>', unsafe_allow_html=True)
            else: st.error("Falha na API.")
