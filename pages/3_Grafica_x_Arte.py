import streamlit as st
from mistralai import Mistral
import google.generativeai as genai
import fitz  # PyMuPDF
import io
import re
from PIL import Image

st.set_page_config(page_title="Ref x BELFAR", layout="wide")

# --- CONFIGURAÇÃO BLINDADA ---
def get_best_gemini():
    candidates = [
        "models/gemini-1.5-flash-latest",
        "models/gemini-1.5-flash",
        "models/gemini-1.5-flash-001",
        "models/gemini-2.0-flash-lite-preview-02-05"
    ]
    for model_name in candidates:
        try: return genai.GenerativeModel(model_name)
        except: continue
    return genai.GenerativeModel("gemini-1.5-flash")

try:
    if st.secrets.get("GEMINI_API_KEY"):
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    client = Mistral(api_key=st.secrets["MISTRAL_API_KEY"])
except:
    st.error("Configure as chaves API no secrets.toml")
    st.stop()

def get_text_from_pdf(file):
    doc = fitz.open(stream=file.read(), filetype="pdf")
    text = ""
    for page in doc: 
        # sort=True ORGANIZA COLUNAS (Vital para bulas)
        text += page.get_text("text", sort=True) + "\n"
    
    # Fallback para OCR se for imagem
    if len(text) < 50:
        file.seek(0)
        images = []
        for page in doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
            img_data = pix.tobytes("jpeg")
            images.append(Image.open(io.BytesIO(img_data)))
        try:
            model = get_best_gemini()
            resp = model.generate_content(["Transcreva TUDO o que está escrito nestas imagens, sem resumir:", *images])
            return resp.text
        except: return ""
    return text

# --- UI ---
st.title("💊 Ref x BELFAR (Texto Completo)")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("Referência (PDF)", type="pdf", key="f1")
f2 = c2.file_uploader("Belfar (PDF)", type="pdf", key="f2")

if st.button("🚀 Iniciar Auditoria Completa"):
    if f1 and f2:
        with st.spinner("Extraindo textos (lendo colunas)..."):
            t1 = get_text_from_pdf(f1)
            t2 = get_text_from_pdf(f2)
        
        with st.spinner("🌪️ Mistral analisando (Modo Detalhado)..."):
            # PROMPT CORRIGIDO PARA EXTRAÇÃO TOTAL
            prompt = f"""
            ATUE COMO UM AUDITOR FARMACÊUTICO RÍGIDO (MODO VERBOSO).
            
            SEÇÕES OBRIGATÓRIAS:
            - APRESENTAÇÕES
            - COMPOSIÇÃO
            - PARA QUE ESTE MEDICAMENTO É INDICADO?
            - COMO ESTE MEDICAMENTO FUNCIONA?
            - QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?
            - O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?
            - ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?
            - COMO DEVO USAR ESTE MEDICAMENTO?
            - O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?
            - QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?
            - O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?
            - DIZERES LEGAIS

            REGRAS CRÍTICAS DE EXTRAÇÃO:
            1. **PROIBIDO RESUMIR**: Copie o texto de cada seção da Referência (ref) e do Candidato (bel) NA ÍNTEGRA. Até o último ponto final.
            2. Se a seção for longa, escreva TUDO. Não pare no meio.
            3. Ignore pontilhados (....).
            
            REGRAS DE COMPARAÇÃO (HTML NO CAMPO 'bel'):
            - Use <mark class='diff'>palavra</mark> para DIFERENÇAS (texto trocado, números).
            - Use <mark class='ort'>palavra</mark> para ERROS DE PORTUGUÊS.
            - Use <mark class='anvisa'>data</mark> para a Data Anvisa.
            - Se o texto for igual, copie ele limpo (sem tags).

            JSON DE SAÍDA:
            {{ "METADADOS": {{"datas":[]}}, "SECOES": [ {{"titulo":"NOME DA SEÇÃO", "ref":"TEXTO COMPLETO REF...", "bel":"TEXTO COMPLETO BEL...", "status":"OK/DIVERGENTE"}} ] }}
            """
            
            try:
                # Usando Large para garantir que ele tenha "paciência" para escrever tudo
                resp = client.chat.complete(
                    model="mistral-large-latest",
                    messages=[
                        {"role":"system", "content":"Você é um extrator de texto fiel. Nunca resuma."},
                        {"role":"user", "content":f"{prompt}\n\n=== REF ===\n{t1}\n\n=== CAND ===\n{t2}"}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.0
                )
                
                content = resp.choices[0].message.content
                
                # Renderização
                import json
                data = json.loads(content)
                
                st.success("✅ Análise Completa")
                
                for s in data.get("SECOES", []):
                    icon = "❌" if "DIVERGENTE" in s['status'] else "✅"
                    with st.expander(f"{icon} {s['titulo']}"):
                        cR, cB = st.columns(2)
                        cR.markdown(f"**Referência**\n<div style='background:#f8f9fa;padding:10px;border-radius:5px;'>{s.get('ref')}</div>", unsafe_allow_html=
