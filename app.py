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

# ----------------- CONFIGURAÇÃO DA PÁGINA -----------------
st.set_page_config(
    page_title="Validador Rígido",
    page_icon="🚧",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- ESTILOS CSS -----------------
st.markdown("""
<style>
    header[data-testid="stHeader"] { display: none !important; }
    .main .block-container { padding-top: 20px !important; }
    .stButton>button { width: 100%; background-color: #55a68e; color: white; font-weight: bold; border-radius: 10px; height: 55px; font-size: 16px; }
    
    .ia-badge { padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 0.8em; margin-bottom: 10px; display: inline-block; }
    .mistral-badge { background-color: #fff3e0; color: #ef6c00; border: 1px solid #ffe0b2; }
    .gemini-badge { background-color: #e1f5fe; color: #01579b; border: 1px solid #b3e5fc; }
    
    .box-ref { background-color: #f8f9fa; padding: 15px; border-radius: 5px; font-size: 0.9em; white-space: pre-wrap; }
    .box-bel { background-color: #f1f8e9; padding: 15px; border-radius: 5px; font-size: 0.9em; white-space: pre-wrap; }
    
    mark.diff { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 3px; }
    mark.ort { background-color: #ffcccc; color: #cc0000; padding: 2px 4px; border-radius: 3px; font-weight: bold; }
    mark.anvisa { background-color: #cce5ff; color: #004085; padding: 2px 4px; border-radius: 3px; font-weight: bold; }
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
    # Gemini
    gem_key = st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if gem_key: genai.configure(api_key=gem_key)
    
    # Mistral
    mis_key = st.secrets.get("MISTRAL_API_KEY") or os.environ.get("MISTRAL_API_KEY")
    mistral_client = Mistral(api_key=mis_key) if mis_key else None
    
    return (gem_key is not None), mistral_client

def auto_select_best_gemini_model():
    """ SELECIONA 1.5 FLASH (O Mais seguro) """
    return "models/gemini-1.5-flash"

def process_uploaded_file(uploaded_file, force_text=False):
    if not uploaded_file: return None
    try:
        file_bytes = uploaded_file.read()
        filename = uploaded_file.name.lower()
        
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            return {"type": "text", "data": text, "count": len(text)}
            
        elif filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            full_text = ""
            for page in doc: full_text += page.get_text() + "\n"
            
            char_count = len(full_text.strip())
            
            # --- NOVA LÓGICA DE DETECÇÃO ---
            # Se tiver mais de 5 letras, ou se o usuário FORÇAR texto
            if char_count > 5 or force_text: 
                doc.close()
                return {"type": "text", "data": full_text, "count": char_count}
            
            # Se não tem texto, é IMAGEM
            images = []
            limit = min(15, len(doc))
            for i in range(limit):
                pix = doc[i].get_pixmap(matrix=fitz.Matrix(2.5, 2.5))
                try: img_byte_arr = io.BytesIO(pix.tobytes("jpeg", jpg_quality=95))
                except: img_byte_arr = io.BytesIO(pix.tobytes("png"))
                images.append(Image.open(img_byte_arr))
            doc.close(); gc.collect()
            return {"type": "images", "data": images, "count": 0}
            
    except Exception as e:
        st.error(f"Erro arquivo: {e}")
        return None
    return None

def extract_json(text):
    text = re.sub(r'//.*', '', text.replace("```json", "").replace("```", "").strip())
    try: return json.loads(text, strict=False)
    except: pass
    try:
        if '"SECOES":' in text:
            start = text.find('{')
            end = text.rfind('}') + 1
            return json.loads(text[start:end], strict=False)
    except: pass
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
    else: st.warning("⚠️ Mistral: OFF (Verifique MISTRAL_API_KEY)")
    
    if gem_ok: st.success("💎 Gemini: ON")
    else: st.error("❌ Gemini: OFF")
    
    st.divider()
    # NOVA OPÇÃO DE SEGURANÇA
    force_text_mode = st.checkbox("⚠️ Forçar Modo Texto", help="Marque se seu PDF tem texto mas o sistema diz que é imagem.")

st.markdown(f"## {pag}")
tipo = st.radio("Tipo:", ["Paciente", "Profissional"], horizontal=True) if pag == "Ref x BELFAR" else "Paciente"
lista = SECOES_PROFISSIONAL if tipo == "Profissional" else SECOES_PACIENTE

c1, c2 = st.columns(2)
f1 = c1.file_uploader("REF", type=["pdf", "docx"], key="f1")
f2 = c2.file_uploader("Candidato", type=["pdf", "docx"], key="f2")

if st.button("🚀 AUDITAR AGORA"):
    if f1 and f2:
        with st.spinner("📖 Lendo arquivos..."):
            # Passamos a opção de forçar texto
            d1 = process_uploaded_file(f1, force_text_mode)
            d2 = process_uploaded_file(f2, force_text_mode)
            gc.collect()
        
        if d1 and d2:
            # MOSTRA O QUE FOI LIDO PARA VOCÊ ENTENDER O ERRO
            if d1['type'] == 'text': st.caption(f"📄 Ref: Lido como TEXTO ({d1['count']} caracteres)")
            else: st.caption(f"🖼️ Ref: Lido como IMAGEM (0 caracteres selecionáveis)")
            
            if d2['type'] == 'text': st.caption(f"📄 Cand: Lido como TEXTO ({d2['count']} caracteres)")
            else: st.caption(f"🖼️ Cand: Lido como IMAGEM (0 caracteres selecionáveis)")

            final_res = None
            model_used = "N/A"
            success = False
            
            # --- PROMPT PADRÃO ---
            secoes_str = "\n".join([f"- {s}" for s in lista])
            prompt = f"""
            ATUE COMO AUDITOR FARMACÊUTICO.
            SEÇÕES ESPERADAS: {secoes_str}
            
            REGRAS:
            1. Extraia o texto COMPLETO.
            2. Compare letra por letra.
            3. Marque erros no 'bel': <mark class='diff'>diferença</mark>, <mark class='ort'>erro_pt</mark>.
            4. Extraia data em DIZERES LEGAIS: <mark class='anvisa'>DD/MM/AAAA</mark>.
            
            JSON: {{ "METADADOS": {{"datas":[]}}, "SECOES": [ {{"titulo":"", "ref":"", "bel":"", "status":"OK/DIVERGENTE/FALTANTE"}} ] }}
            """

            # ==========================================================
            # 🛑 LÓGICA RÍGIDA DE SEPARAÇÃO (SEM FALLBACK CRUZADO)
            # ==========================================================
            
            if pag == "Ref x BELFAR" or pag == "Conferência MKT":
                # >>>> ZONA EXCLUSIVA MISTRAL <<<<
                if not mis_client:
                    st.error("🛑 ERRO: Você está na área do MISTRAL, mas a chave 'MISTRAL_API_KEY' não foi encontrada.")
                    st.stop()
                
                # Verifica se é imagem
                if d1['type'] == 'images' or d2['type'] == 'images':
                    st.error("🛑 ERRO DE ARQUIVO: O Mistral lê apenas TEXTO. Seu arquivo foi identificado como imagem (0 letras). Marque '⚠️ Forçar Modo Texto' na barra lateral para tentar mesmo assim, ou use a aba 'Gráfica x Arte'.")
                    st.stop()

                try:
                    with st.spinner("🌪️ Processando EXCLUSIVAMENTE com MISTRAL AI..."):
                        chat = mis_client.chat.complete(
                            model="mistral-large-latest",
                            messages=[
                                {"role":"system", "content":"Você retorna APENAS JSON válido."},
                                {"role":"user", "content":f"{prompt}\n\nREF:\n{d1['data']}\n\nCAND:\n{d2['data']}"}
                            ],
                            response_format={"type": "json_object"},
                            temperature=0.0
                        )
                        final_res = chat.choices[0].message.content
                        model_used = "🌪️ Mistral Large"
                        success = True
                except Exception as e:
                    st.error(f"❌ Erro no MISTRAL: {e}")
                    st.stop()

            elif pag == "Gráfica x Arte":
                # >>>> ZONA EXCLUSIVA GEMINI <<<<
                if not gem_ok:
                    st.error("🛑 ERRO: Você está na área GRÁFICA, mas a chave 'GEMINI_API_KEY' não foi encontrada.")
                    st.stop()

                try:
                    best_gem = "models/gemini-1.5-flash"
                    with st.spinner(f"💎 Processando EXCLUSIVAMENTE com GEMINI ({best_gem})..."):
                        model = genai.GenerativeModel(best_gem)
                        payload = ["Auditoria."]
                        
                        if d1['type']=='text': payload.append(f"REF:\n{d1['data']}")
                        else: payload.extend(["REF IMG:"] + d1['data'])
                        
                        if d2['type']=='text': payload.append(f"CAND:\n{d2['data']}")
                        else: payload.extend(["CAND IMG:"] + d2['data'])
                        
                        res = model.generate_content(
                            [prompt] + payload,
                            generation_config={"response_mime_type": "application/json"},
                            safety_settings=SAFETY
                        )
                        final_res = res.text
                        model_used = f"💎 Gemini Flash"
                        success = True
                except Exception as e:
                    st.error(f"❌ Erro no GEMINI: {e}")
                    st.stop()

            # --- RENDERIZAÇÃO ---
            if success and final_res:
                cls = 'mistral-badge' if 'Mistral' in model_used else 'gemini-badge'
                st.markdown(f"<div class='ia-badge {cls}'>Processado por: {model_used}</div>", unsafe_allow_html=True)
                
                data = extract_json(final_res)
                if data:
                    norm = normalize_sections(data, lista)
                    secs = norm.get("SECOES", [])
                    dates = data.get("METADADOS", {}).get("datas", [])
                    
                    st.success("✅ Auditoria Concluída!")
                    st.divider()
                    
                    cM1, cM2, cM3 = st.columns(3)
                    errs = sum(1 for s in secs if "DIVERGENTE" in s['status'] or "ERRO" in s['status'])
                    score = 100 - int((errs/max(1,len(secs)))*100) if secs else 0
                    cM1.metric("Score", f"{score}%")
                    cM2.metric("Seções", f"{len(secs)}/{len(lista)}")
                    cM3.markdown(f"**Data:** <mark class='anvisa'>{dates[0] if dates else 'N/A'}</mark>", unsafe_allow_html=True)
                    
                    st.markdown("---")
                    for s in secs:
                        icon = "✅"
                        if "DIVERGENTE" in s['status']: icon = "❌"
                        elif "FALTANTE" in s['status']: icon = "🚨"
                        
                        with st.expander(f"{icon} {s['titulo']} - {s['status']}"):
                            cR, cB = st.columns(2)
                            cR.markdown(f"<div class='box-ref'>{s.get('ref','')}</div>", unsafe_allow_html=True)
                            cB.markdown(f"<div class='box-bel'>{s.get('bel','')}</div>", unsafe_allow_html=True)
                else:
                    st.error("Erro JSON.")
    else:
        st.warning("Envie os arquivos.")
