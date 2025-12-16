import streamlit as st
import google.generativeai as genai
from mistralai import Mistral
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import fitz  # PyMuPDF
import docx
import io
import json
import re
import os
import gc
import time
from PIL import Image
from difflib import SequenceMatcher

# ----------------- CONFIGURAÇÃO -----------------
st.set_page_config(
    page_title="Validador Híbrido (Blindado)",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- ESTILOS -----------------
st.markdown("""
<style>
    header[data-testid="stHeader"] { display: none !important; }
    .main .block-container { padding-top: 20px !important; }
    .stButton>button { width: 100%; background-color: #55a68e; color: white; font-weight: bold; border-radius: 10px; height: 55px; font-size: 16px; }
    
    .ia-badge { padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 0.8em; margin-bottom: 10px; display: inline-block; }
    .mistral-badge { background-color: #e3f2fd; color: #1565c0; border: 1px solid #90caf9; }
    .gemini-badge { background-color: #e1f5fe; color: #01579b; border: 1px solid #b3e5fc; }
    
    .box-content { background-color: #f8f9fa; padding: 15px; border-radius: 5px; font-size: 0.9em; white-space: pre-wrap; line-height: 1.5; }
    .box-bel { background-color: #f1f8e9; border-left: 4px solid #55a68e; }
    .box-ref { border-left: 4px solid #6c757d; }
    
    mark.diff { background-color: #fff176; color: #000; padding: 2px 4px; border-radius: 3px; font-weight: bold; border: 1px solid #fdd835; }
    mark.ort { background-color: #ffcdd2; color: #b71c1c; padding: 2px 4px; border-radius: 3px; font-weight: bold; border-bottom: 2px solid #b71c1c; }
    mark.anvisa { background-color: #b3e5fc; color: #01579b; padding: 2px 4px; border-radius: 3px; font-weight: bold; border: 1px solid #039be5; }
</style>
""", unsafe_allow_html=True)

# ----------------- CONSTANTES -----------------
SECOES_PACIENTE = [
    "APRESENTAÇÕES", "COMPOSIÇÃO", "PARA QUE ESTE MEDICAMENTO É INDICADO", 
    "COMO ESTE MEDICAMENTO FUNCIONA?", "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?", 
    "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?", "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?", 
    "COMO DEVO USAR ESTE MEDICAMENTO?", "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?", 
    "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?", 
    "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?", "DIZERES LEGAIS"
]

SECOES_PROFISSIONAL = [
    "APRESENTAÇÕES", "COMPOSIÇÃO", "INDICAÇÕES", "RESULTADOS DE EFICÁCIA", 
    "CARACTERÍSTICAS FARMACOLÓGICAS", "CONTRAINDICAÇÕES", "ADVERTÊNCIAS E PRECAUÇÕES", 
    "INTERAÇÕES MEDICAMENTOSAS", "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO", 
    "POSOLOGIA E MODO DE USAR", "REAÇÕES ADVERSAS", "SUPERDOSE", "DIZERES LEGAIS"
]

SAFETY = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# ----------------- FUNÇÕES BACKEND -----------------

def configure_apis():
    gem_key = st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if gem_key: genai.configure(api_key=gem_key)
    
    mis_key = st.secrets.get("MISTRAL_API_KEY") or os.environ.get("MISTRAL_API_KEY")
    mistral_client = Mistral(api_key=mis_key) if mis_key else None
    
    return (gem_key is not None), mistral_client

def ocr_with_gemini(images):
    try:
        model = genai.GenerativeModel("models/gemini-1.5-flash")
        response = model.generate_content(
            ["Transcreva TODO o texto destas imagens fielmente. Não adicione comentários.", *images],
            generation_config={"max_output_tokens": 40000}
        )
        return response.text
    except: return ""

def process_uploaded_file(uploaded_file):
    if not uploaded_file: return None
    try:
        file_bytes = uploaded_file.read()
        filename = uploaded_file.name.lower()
        
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            txt = "\n".join([p.text for p in doc.paragraphs])
            return {"type": "text", "data": txt, "len": len(txt)}
            
        elif filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            full_text = ""
            for page in doc: full_text += page.get_text() + "\n"
            
            if len(full_text.strip()) > 100: 
                doc.close()
                return {"type": "text", "data": full_text, "len": len(full_text)}
            
            st.toast(f"📄 '{uploaded_file.name}': Ativando OCR...", icon="👁️")
            
            images = []
            limit = min(15, len(doc))
            for i in range(limit):
                pix = doc[i].get_pixmap(matrix=fitz.Matrix(1.5, 1.5)) # Otimizado
                try: img_byte_arr = io.BytesIO(pix.tobytes("jpeg", jpg_quality=80))
                except: img_byte_arr = io.BytesIO(pix.tobytes("png"))
                images.append(Image.open(img_byte_arr))
            doc.close()
            gc.collect()
            
            extracted = ocr_with_gemini(images)
            
            if extracted and len(extracted) > 50:
                return {"type": "text", "data": extracted, "len": len(extracted)}
            else:
                return {"type": "images", "data": images, "len": 0}
            
    except Exception as e:
        st.error(f"Erro: {e}")
        return None
    return None

def extract_json(text):
    """
    Função Blindada: Procura o primeiro { e o último } para ignorar lixo antes/depois.
    """
    if not text: return None
    
    # 1. Tenta limpeza básica
    clean_text = text.replace("```json", "").replace("```", "").strip()
    
    # 2. Tenta regex para encontrar o bloco JSON principal
    match = re.search(r'\{.*\}', clean_text, re.DOTALL)
    if match:
        clean_text = match.group(0)
    
    # 3. Tenta parsear
    try: 
        return json.loads(clean_text)
    except: 
        return None

def normalize_sections(data, allowed):
    if not data or "SECOES" not in data: return data
    clean = []
    def norm(t): return re.sub(r'[^A-ZÃÕÁÉÍÓÚÇ]', '', t.upper())
    allowed_map = {norm(t): t for t in allowed}
    for sec in data["SECOES"]:
        t_ia = norm(sec.get("titulo", ""))
        match = allowed_map.get(t_ia)
        if not match:
            for k, v in allowed_map.items():
                if k in t_ia or t_ia in k or SequenceMatcher(None, k, t_ia).ratio() > 0.8:
                    match = v; break
        if match:
            sec["titulo"] = match
            clean.append(sec)
    data["SECOES"] = clean
    return data

# ----------------- UI -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=70)
    st.title("Validador Rígido")
    pag = st.radio("Menu", ["Ref x BELFAR", "Conferência MKT", "Gráfica x Arte"])
    st.divider()
    
    gem_ok, mis_client = configure_apis()
    if mis_client: st.success("🌪️ Mistral: ON")
    else: st.error("⚠️ Mistral: OFF")
    if gem_ok: st.success("💎 Gemini: ON")
    else: st.error("❌ Gemini: OFF")

st.markdown(f"## {pag}")
tipo = st.radio("Tipo:", ["Paciente", "Profissional"], horizontal=True) if pag == "Ref x BELFAR" else "Paciente"
lista = SECOES_PROFISSIONAL if tipo == "Profissional" else SECOES_PACIENTE

c1, c2 = st.columns(2)
f1 = c1.file_uploader("REF", type=["pdf", "docx"], key="f1")
f2 = c2.file_uploader("Candidato", type=["pdf", "docx"], key="f2")

if st.button("🚀 AUDITAR AGORA"):
    if f1 and f2:
        with st.spinner("📖 Preparando arquivos..."):
            d1 = process_uploaded_file(f1)
            d2 = process_uploaded_file(f2)
            gc.collect()
        
        if d1 and d2:
            final_res = None
            model_used = "N/A"
            success = False
            
            secoes_str = "\n".join([f"- {s}" for s in lista])
            
            # --- PROMPT RIGOROSO ---
            prompt = f"""
            ATUE COMO UM AUDITOR FARMACÊUTICO RÍGIDO.
            SEÇÕES: {secoes_str}
            
            INSTRUÇÕES:
            1. Extraia o texto COMPLETO de REF e BEL (Candidato).
            2. O campo 'bel' NÃO PODE SER VAZIO. Copie o texto do candidato.
            3. Marque erros no 'bel' usando HTML:
               - Diferenças (qualquer uma): <mark class='diff'>texto</mark>
               - Erros de PT: <mark class='ort'>texto</mark>
               - Data Anvisa: <mark class='anvisa'>DD/MM/AAAA</mark>
            
            SAÍDA APENAS JSON (SEM COMENTÁRIOS):
            {{ "METADADOS": {{"datas":[]}}, "SECOES": [ {{"titulo":"", "ref":"...", "bel":"...", "status":"OK/DIVERGENTE/FALTANTE"}} ] }}
            """

            # 🛑 MISTRAL
            if pag in ["Ref x BELFAR", "Conferência MKT"]:
                if not mis_client: st.error("MISTRAL OFF"); st.stop()
                if d1['type'] == 'images' or d2['type'] == 'images':
                    st.error("Erro: OCR falhou (Imagem pura)."); st.stop()

                try:
                    with st.spinner("🌪️ Mistral analisando..."):
                        chat = mis_client.chat.complete(
                            model="open-mistral-nemo", # Rápido e Eficiente
                            messages=[
                                {"role":"system", "content":"Você retorna APENAS JSON."},
                                {"role":"user", "content":f"{prompt}\n\n=== REF ===\n{d1['data']}\n\n=== CAND ===\n{d2['data']}"}
                            ],
                            response_format={"type": "json_object"},
                            temperature=0.0
                        )
                        final_res = chat.choices[0].message.content
                        model_used = "🌪️ Mistral Nemo"
                        success = True
                except Exception as e:
                    st.error(f"Erro Mistral: {e}"); st.stop()

            # 🛑 GEMINI
            elif pag == "Gráfica x Arte":
                if not gem_ok: st.error("GEMINI OFF"); st.stop()
                try:
                    with st.spinner("💎 Gemini analisando..."):
                        model = genai.GenerativeModel("models/gemini-1.5-flash")
                        payload = [prompt]
                        payload.append(f"REF:\n{d1['data']}" if d1['type']=='text' else d1['data'])
                        payload.append(f"CAND:\n{d2['data']}" if d2['type']=='text' else d2['data'])
                        
                        res = model.generate_content(payload, generation_config={"response_mime_type": "application/json"})
                        final_res = res.text
                        model_used = "💎 Gemini Flash"
                        success = True
                except Exception as e:
                    st.error(f"Erro Gemini: {e}"); st.stop()

            # RENDERIZAÇÃO
            if success and final_res:
                cls = 'mistral-badge' if 'Mistral' in model_used else 'gemini-badge'
                st.markdown(f"<div class='ia-badge {cls}'>Processado por: {model_used}</div>", unsafe_allow_html=True)
                
                data = extract_json(final_res)
                if data:
                    norm = normalize_sections(data, lista)
                    secs = norm.get("SECOES", [])
                    dates = data.get("METADADOS", {}).get("datas", [])
                    
                    st.success("✅ Concluído!")
                    st.divider()
                    
                    c1, c2, c3 = st.columns(3)
                    errs = sum(1 for s in secs if s['status'] != "OK")
                    score = 100 - int((errs/max(1,len(secs)))*100) if secs else 0
                    c1.metric("Score", f"{score}%")
                    c2.metric("Seções", f"{len(secs)}/{len(lista)}")
                    c3.markdown(f"**Data:** <mark class='anvisa'>{dates[0] if dates else 'N/A'}</mark>", unsafe_allow_html=True)
                    
                    st.markdown("---")
                    for s in secs:
                        icon = "✅"
                        if "DIVERGENTE" in s['status']: icon = "❌"
                        elif "FALTANTE" in s['status']: icon = "🚨"
                        
                        with st.expander(f"{icon} {s['titulo']} - {s['status']}"):
                            cR, cB = st.columns(2)
                            cR.markdown(f"<div class='box-content box-ref'>{s.get('ref','')}</div>", unsafe_allow_html=True)
                            cB.markdown(f"<div class='box-content box-bel'>{s.get('bel','')}</div>", unsafe_allow_html=True)
                else:
                    st.error("❌ ERRO AO LER RESPOSTA DA IA (JSON QUEBRADO)")
                    with st.expander("Ver Resposta Bruta (Para Debug)"):
                        st.code(final_res) # AQUI ESTÁ O SEGREDO DO DEBUG
    else:
        st.warning("Envie os arquivos.")
