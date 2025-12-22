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
        font-family: 'Segoe UI', sans-serif; font-size: 0.95rem; line-height: 1.6; color: #212529;
        background-color: #ffffff; padding: 20px; border-radius: 8px; border: 1px solid #ced4da;
        white-space: pre-wrap; text-align: left;
    }
    .highlight-red { background-color: #ffcdd2; color: #b71c1c; padding: 2px 4px; border-radius: 4px; border: 1px solid #e57373; font-weight: bold; }
    .highlight-blue { background-color: #e3f2fd; color: #0d47a1; padding: 2px 6px; border-radius: 12px; border: 1px solid #2196f3; font-weight: bold; }
    
    .border-ok { border-left: 6px solid #4caf50 !important; }
    .border-warn { border-left: 6px solid #f44336 !important; }
    .border-info { border-left: 6px solid #2196f3 !important; }
    div[data-testid="stMetric"] { background-color: #f8f9fa; border: 1px solid #dee2e6; padding: 10px; border-radius: 5px; text-align: center; }
</style>
""", unsafe_allow_html=True)

MODELO_FIXO = "models/gemini-flash-latest"

def limpar_texto(texto):
    if not texto: return ""
    texto = unicodedata.normalize('NFKD', texto)
    texto = texto.replace('\u00a0', ' ').replace('\r', '')
    texto = re.sub(r'[\._]{3,}', ' ', texto) 
    texto = re.sub(r'[ \t]+', ' ', texto)
    return texto.strip()

def destacar_datas(html):
    return re.sub(r'(?<!\d)(\d{2}/\d{2}/\d{4})(?!\d)', r'<span class="highlight-blue">\1</span>', html)

def gerar_diff_red(ref, novo):
    if not ref: ref = ""; 
    if not novo: novo = ""
    
    TOKEN = " [[BR]] "
    ref_c = limpar_texto(ref).replace('\n', TOKEN)
    nov_c = limpar_texto(novo).replace('\n', TOKEN)
    
    a = ref_c.split()
    b = nov_c.split()
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    out = []
    diff = False
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        trecho = " ".join(b[j1:j2]).replace("[[BR]]", "\n")
        if tag == 'equal': out.append(trecho)
        elif tag in ['replace', 'insert']:
            if trecho.strip():
                out.append(f'<span class="highlight-red">{trecho}</span>')
                diff = True
            else: out.append(trecho)
        elif tag == 'delete': diff = True
            
    final = " ".join(out).replace(" \n ", "\n").replace("\n ", "\n").replace(" \n", "\n")
    return destacar_datas(final), diff

def extract_text(uploaded):
    try:
        txt = ""
        if uploaded.name.lower().endswith('.pdf'):
            doc = fitz.open(stream=uploaded.read(), filetype="pdf")
            for page in doc:
                blocks = page.get_text("dict", flags=11, sort=True)["blocks"]
                for b in blocks:
                    for l in b.get("lines", []):
                        ln = ""
                        for s in l.get("spans", []):
                            c = s["text"]
                            if (s["flags"] & 16) or "bold" in s["font"].lower(): ln += f"<b>{c}</b>"
                            else: ln += c
                        txt += ln + " "
                    txt += "\n"
        elif uploaded.name.lower().endswith('.docx'):
            doc = docx.Document(uploaded)
            for p in doc.paragraphs:
                ln = ""
                for r in p.runs:
                    if r.bold: ln += f"<b>{r.text}</b>"
                    else: ln += r.text
                txt += ln + "\n\n"
        return limpar_texto(txt)
    except: return ""

st.title("💊 Conferência MKT")
c1, c2 = st.columns(2)
f1 = c1.file_uploader("Ref", type=["pdf", "docx"], key="f1")
f2 = c2.file_uploader("MKT", type=["pdf", "docx"], key="f2")

if st.button("🚀 Processar"):
    keys = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2"), st.secrets.get("GEMINI_API_KEY3")]
    valid = [k for k in keys if k]
    if not valid: st.stop()
    
    if f1 and f2:
        with st.spinner("Comparando..."):
            f1.seek(0); f2.seek(0)
            tr = extract_text(f1)
            tm = extract_text(f2)
            
            prompt = f"""
            Você é um Auditor.
            INPUT 1: {tr[:150000]}
            INPUT 2: {tm[:150000]}
            TAREFA: Extraia o texto COMPLETO das seções abaixo. NÃO RESUMA.
            SEÇÕES: ["APRESENTAÇÕES", "COMPOSIÇÃO", "PARA QUE ESTE MEDICAMENTO É INDICADO", "COMO ESTE MEDICAMENTO FUNCIONA?", "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?", "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?", "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?", "COMO DEVO USAR ESTE MEDICAMENTO?", "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?", "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?", "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?", "DIZERES LEGAIS"]
            JSON: {{"data_anvisa_ref": "...", "data_anvisa_mkt": "...", "secoes": [{{"titulo": "...", "texto_anvisa": "...", "texto_mkt": "..."}}]}}
            """
            
            for k in valid:
                try:
                    genai.configure(api_key=k)
                    mod = genai.GenerativeModel(MODELO_FIXO, generation_config={"response_mime_type": "application/json"})
                    res = mod.generate_content(prompt)
                    break
                except: continue
                
            if res:
                try:
                    j = json.loads(res.text)
                    final = []
                    errs = 0
                    for s in j.get("secoes", []):
                        hr, diff = gerar_diff_red(s["texto_anvisa"], s["texto_mkt"])
                        status = "DIVERGENTE" if diff else "CONFORME"
                        if diff: errs += 1
                        final.append({"t": s["titulo"], "tr": destacar_datas(s["texto_anvisa"].replace('\n', '<br>')), "tm": hr.replace('\n', '<br>'), "s": status})
                    
                    st.markdown("### Resumo")
                    c_x, c_y, c_z = st.columns(3)
                    c_x.metric("Ref", j.get("data_anvisa_ref"))
                    c_y.metric("MKT", j.get("data_anvisa_mkt"))
                    c_z.metric("Erros", errs)
                    
                    for i in final:
                        css = "border-warn" if i["s"] == "DIVERGENTE" else "border-ok"
                        with st.expander(f"{'⚠️' if i['s']=='DIVERGENTE' else '✅'} {i['t']}", expanded=(i["s"]=="DIVERGENTE")):
                            ca, cb = st.columns(2)
                            ca.markdown(f'<div class="texto-box {css}">{i["tr"]}</div>', unsafe_allow_html=True)
                            cb.markdown(f'<div class="texto-box {css}">{i["tm"]}</div>', unsafe_allow_html=True)
                except Exception as e: st.error(str(e))
