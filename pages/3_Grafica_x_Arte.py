import streamlit as st
import google.generativeai as genai
from PIL import Image
import fitz
import docx
import io
import json
import re

st.set_page_config(page_title="Validador Visual", page_icon="💊", layout="wide")
st.markdown("""
<style>
    [data-testid="stHeader"] { visibility: hidden; }
    .texto-box { 
        font-family: 'Consolas', monospace; font-size: 0.9rem; line-height: 1.5; color: #212529;
        background-color: #ffffff; padding: 15px; border-radius: 8px; border: 1px solid #ced4da;
        white-space: pre-wrap; text-align: justify;
    }
    .border-ok { border-left: 5px solid #4caf50 !important; }
    .border-warn { border-left: 5px solid #f44336 !important; }
    .border-info { border-left: 5px solid #2196f3 !important; }
    .highlight-blue { background-color: #e3f2fd; color: #0d47a1; padding: 2px 6px; border-radius: 12px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

MODELO_FIXO = "models/gemini-flash-latest" 
SECOES = ["APRESENTAÇÕES", "COMPOSIÇÃO", "PARA QUE ESTE MEDICAMENTO É INDICADO", "COMO ESTE MEDICAMENTO FUNCIONA?", "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?", "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?", "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?", "COMO DEVO USAR ESTE MEDICAMENTO?", "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?", "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?", "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?", "DIZERES LEGAIS"]

def process_file(up):
    try:
        if up.name.lower().endswith('.pdf'):
            doc = fitz.open(stream=up.read(), filetype="pdf")
            imgs = []
            for p in doc:
                pix = p.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
                imgs.append(Image.open(io.BytesIO(pix.tobytes("jpeg"))))
            return imgs
        elif up.name.lower().endswith(('.jpg', '.png')): return [Image.open(up)]
        elif up.name.lower().endswith('.docx'):
            doc = docx.Document(up)
            return ["\n".join([p.text for p in doc.paragraphs])]
    except: return []

st.title("💊 Gráfica x Arte")
c1, c2 = st.columns(2)
f1 = c1.file_uploader("Arte", type=["pdf", "jpg", "png", "docx"])
f2 = c2.file_uploader("Gráfica", type=["pdf", "jpg", "png", "docx"])

if st.button("🚀 Validar"):
    keys = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2")]
    valid = [k for k in keys if k]
    if not valid: st.stop()
    
    if f1 and f2:
        with st.spinner("Analisando..."):
            f1.seek(0); f2.seek(0)
            c1_content = process_file(f1)
            c2_content = process_file(f2)
            
            p = f"""
            ATUE COMO OCR.
            LISTA: {json.dumps(SECOES, ensure_ascii=False)}
            REGRAS:
            1. COPIE O TEXTO VISUAL EXATO E COMPLETO.
            2. Se houver listas, uma linha por item.
            3. Ignore pontilhados "....".
            4. Use <b> para negrito.
            JSON: {{"data_anvisa_ref": "...", "data_anvisa_grafica": "...", "secoes": [{{"titulo": "...", "texto_arte": "...", "texto_grafica": "...", "status": "CONFORME"}}]}}
            """
            
            pl = [p, "=== ARTE ==="] + c1_content + ["=== GRAFICA ==="] + c2_content
            
            res = None
            for k in valid:
                try:
                    genai.configure(api_key=k)
                    m = genai.GenerativeModel(MODELO_FIXO, generation_config={"response_mime_type": "application/json", "temperature": 0.0})
                    r = m.generate_content(pl)
                    res = json.loads(r.text.replace("```json", "").replace("```", ""))
                    break
                except: continue
                
            if res:
                st.markdown("### Resultado")
                colA, colB = st.columns(2)
                colA.metric("Ref", res.get("data_anvisa_ref"))
                colB.metric("Gráfica", res.get("data_anvisa_grafica"))
                
                isentas = ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]

                for i in res.get("secoes", []):
                    t = i.get('titulo', '')
                    blindada = any(x in t.upper() for x in isentas)
                    
                    if blindada:
                        status = "CONFORME"
                        css = "border-info"
                        ab = False
                    else:
                        status = i.get("status", "CONFORME")
                        css = "border-warn" if status == "DIVERGENTE" else "border-ok"
                        ab = (status == "DIVERGENTE")
                    
                    if "DIZERES" in t.upper(): icon="⚖️"
                    elif blindada: icon="📋"
                    elif status == "DIVERGENTE": icon="⚠️"
                    else: icon="✅"

                    with st.expander(f"{icon} {t}", expanded=ab):
                        ca, cb = st.columns(2)
                        ta = i.get("texto_arte", "")
                        tb = i.get("texto_grafica", "")

                        if "DIZERES LEGAIS" in t.upper():
                            ta = re.sub(r'(\d{2}/\d{2}/\d{4})', r'<span class="highlight-blue">\1</span>', ta)
                            tb = re.sub(r'(\d{2}/\d{2}/\d{4})', r'<span class="highlight-blue">\1</span>', tb)
                        
                        ca.markdown(f'<div class="texto-box {css}">{ta}</div>', unsafe_allow_html=True)
                        cb.markdown(f'<div class="texto-box {css}">{tb}</div>', unsafe_allow_html=True)
