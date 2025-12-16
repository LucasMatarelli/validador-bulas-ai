import streamlit as st
import google.generativeai as genai
from groq import Groq
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import fitz  # PyMuPDF
import docx
import io
import json
import re
import os
import gc
from PIL import Image
from difflib import SequenceMatcher

# ----------------- CONFIGURAÇÃO DA PÁGINA -----------------
st.set_page_config(
    page_title="Validador Híbrido (Gemini + Groq)",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- CSS -----------------
st.markdown("""
<style>
    header[data-testid="stHeader"] { display: none !important; }
    .stButton>button { width: 100%; font-weight: bold; border-radius: 8px; height: 60px; font-size: 18px; }
    
    /* Cores das IAs */
    .gemini-tag { background-color: #e1f5fe; color: #0277bd; padding: 2px 6px; border-radius: 4px; border: 1px solid #4fc3f7; font-size: 0.8em; font-weight: bold; }
    .groq-tag { background-color: #fbe9e7; color: #d84315; padding: 2px 6px; border-radius: 4px; border: 1px solid #ffab91; font-size: 0.8em; font-weight: bold; }

    mark.diff { background-color: #fff9c4; color: #f57f17; padding: 2px 6px; border-radius: 4px; border: 1px solid #fbc02d; font-weight: bold; }
    mark.ort { background-color: #ffcdd2; color: #c62828; padding: 2px 6px; border-radius: 4px; border-bottom: 2px solid #b71c1c; font-weight: bold; }
    
    .box-content { background-color: #f8f9fa; padding: 15px; border-radius: 8px; border-left: 5px solid #ccc; font-size: 0.9rem; line-height: 1.6; white-space: pre-wrap; }
    .box-bel { border-left-color: #2e7d32; background-color: #e8f5e9; }
</style>
""", unsafe_allow_html=True)

# ----------------- CONSTANTES -----------------
SECOES_PACIENTE = [
    "APRESENTAÇÕES", "COMPOSIÇÃO", "PARA QUE ESTE MEDICAMENTO É INDICADO", 
    "COMO ESTE MEDICAMENTO FUNCIONA?", "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?", 
    "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?", 
    "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?", 
    "COMO DEVO USAR ESTE MEDICAMENTO?", "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?", 
    "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?", 
    "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?", 
    "DIZERES LEGAIS"
]

SECOES_PROFISSIONAL = [
    "APRESENTAÇÕES", "COMPOSIÇÃO", "INDICAÇÕES", "RESULTADOS DE EFICÁCIA", 
    "CARACTERÍSTICAS FARMACOLÓGICAS", "CONTRAINDICAÇÕES", "ADVERTÊNCIAS E PRECAUÇÕES", 
    "INTERAÇÕES MEDICAMENTOSAS", "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO", 
    "POSOLOGIA E MODO DE USAR", "REAÇÕES ADVERSAS", "SUPERDOSE", "DIZERES LEGAIS"
]

# ----------------- API MANAGERS -----------------

def get_api_keys():
    """Tenta pegar as chaves do secrets ou environment"""
    gemini_key = st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    groq_key = st.secrets.get("GROQ_API_KEY") or os.environ.get("GROQ_API_KEY")
    return gemini_key, groq_key

def setup_gemini(api_key):
    if not api_key: return None
    genai.configure(api_key=api_key)
    # Tenta achar o modelo Flash correto
    try:
        for m in genai.list_models():
            if 'gemini-1.5-flash' in m.name and 'generateContent' in m.supported_generation_methods:
                return m.name
        return "models/gemini-1.5-flash"
    except: return None

def get_groq_client(api_key):
    if not api_key: return None
    return Groq(api_key=api_key)

# ----------------- PROCESSAMENTO ARQUIVO -----------------
def process_file(uploaded_file):
    if not uploaded_file: return None
    try:
        file_bytes = uploaded_file.read()
        filename = uploaded_file.name.lower()
        
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            return {"type": "text", "data": text}
            
        elif filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            full_text = ""
            for page in doc: full_text += page.get_text() + "\n"
            
            # Se tem texto suficiente, é TEXTO (Vai pra Groq)
            if len(full_text.strip()) > 500:
                doc.close()
                return {"type": "text", "data": full_text}
            
            # Se for imagem, é IMAGEM (Vai pro Gemini)
            images = []
            limit = min(10, len(doc))
            for i in range(limit):
                pix = doc[i].get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
                try: img_byte_arr = io.BytesIO(pix.tobytes("jpeg", jpg_quality=90))
                except: img_byte_arr = io.BytesIO(pix.tobytes("png"))
                images.append(Image.open(img_byte_arr))
            doc.close()
            gc.collect()
            return {"type": "images", "data": images}
    except: return None

def extract_json(text):
    text = re.sub(r'//.*', '', text.replace("```json", "").replace("```", "").strip())
    try: return json.loads(text, strict=False)
    except: 
        try:
            start = text.find('{')
            end = text.rfind('}') + 1
            return json.loads(text[start:end], strict=False)
        except: return None

def normalize_sections(data, allowed_titles):
    if not data or "SECOES" not in data: return data
    clean = []
    def norm(t): return re.sub(r'[^A-ZÃÕÁÉÍÓÚÇ]', '', t.upper())
    allowed_map = {norm(t): t for t in allowed_titles}
    
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

# ----------------- PROMPT PADRÃO -----------------
def get_prompt(lista_secoes):
    secoes_txt = "\n".join([f"- {s}" for s in lista_secoes])
    return f"""
    Você é um Auditor Farmacêutico da ANVISA.
    Sua tarefa é comparar dois textos (REFERÊNCIA vs CANDIDATO).
    
    LISTA DE SEÇÕES PARA EXTRAIR:
    {secoes_txt}

    REGRAS DE OURO:
    1. Extraia o conteúdo COMPLETO. Não resuma.
    2. No campo 'bel' (Candidato), marque as diferenças com HTML:
       - <mark class='diff'>palavra_diferente</mark>
       - <mark class='ort'>erro_ortografico</mark>
    3. Retorne APENAS JSON válido.

    FORMATO JSON:
    {{
        "METADADOS": {{ "datas": ["DD/MM/AAAA"] }},
        "SECOES": [
            {{
                "titulo": "TÍTULO EXATO DA LISTA",
                "ref": "Texto referência...",
                "bel": "Texto candidato com marcas...",
                "status": "OK" | "DIVERGENTE" | "FALTANTE"
            }}
        ]
    }}
    """

# ----------------- UI -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=70)
    st.title("Validador Híbrido")
    
    k_gem, k_groq = get_api_keys()
    
    # Status Gemini
    if k_gem:
        gem_model = setup_gemini(k_gem)
        if gem_model: st.success(f"💎 Gemini Ativo ({gem_model})")
        else: st.error("💎 Gemini: Erro Modelo")
    else: st.error("💎 Gemini: Sem Chave")
    
    # Status Groq
    if k_groq:
        groq_client = get_groq_client(k_groq)
        if groq_client: st.success("⚡ Groq Ativo (Llama 3)")
    else: st.warning("⚡ Groq: Sem Chave (Usará Gemini)")

    st.divider()
    st.info("Estratégia:\n⚡ Groq para Texto (Rápido/Grátis)\n💎 Gemini para Imagens")

st.markdown("<h2 style='color:#2e7d32;text-align:center'>Validador Farmacêutico (Híbrido)</h2>", unsafe_allow_html=True)

tipo = st.radio("Modelo:", ["Paciente", "Profissional"], horizontal=True)
lista_alvo = SECOES_PROFISSIONAL if tipo == "Profissional" else SECOES_PACIENTE

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📂 Referência", type=["pdf", "docx"])
f2 = c2.file_uploader("📂 Candidato", type=["pdf", "docx"])

if st.button("🚀 INICIAR AUDITORIA"):
    if f1 and f2:
        with st.spinner("⏳ Processando arquivos..."):
            d1 = process_file(f1)
            d2 = process_file(f2)
            gc.collect()
        
        if d1 and d2:
            prompt_base = get_prompt(lista_alvo)
            response_text = None
            used_ai = ""

            # LÓGICA DE ROTEAMENTO (O CÉREBRO DO SISTEMA)
            # Se tiver imagens, OBRIGATÓRIO usar Gemini
            if d1['type'] == 'images' or d2['type'] == 'images':
                if not k_gem:
                    st.error("⚠️ Arquivos são imagens, mas Gemini não está configurado.")
                    st.stop()
                
                used_ai = "💎 Gemini Vision (Necessário para Imagens)"
                model = genai.GenerativeModel(gem_model)
                
                payload = ["CONTEXTO: Comparação Visual de Bulas."]
                if d1['type']=='text': payload.append(f"REF (TXT):\n{d1['data']}")
                else: payload.extend(["REF (IMG):"] + d1['data'])
                if d2['type']=='text': payload.append(f"CAND (TXT):\n{d2['data']}")
                else: payload.extend(["CAND (IMG):"] + d2['data'])
                
                with st.spinner(f"Processando com {used_ai}..."):
                    try:
                        res = model.generate_content(
                            [prompt_base] + payload,
                            generation_config={"response_mime_type": "application/json", "max_output_tokens": 15000},
                            request_options={"timeout": 600}
                        )
                        response_text = res.text
                    except Exception as e:
                        st.error(f"Erro Gemini: {e}")

            # Se for SÓ TEXTO, preferência para GROQ (Economiza Gemini)
            else:
                if k_groq:
                    used_ai = "⚡ Groq (Llama 3.3 - Rápido & Grátis)"
                    full_prompt = f"{prompt_base}\n\n--- REF ---\n{d1['data']}\n\n--- CAND ---\n{d2['data']}"
                    
                    with st.spinner(f"Processando com {used_ai}..."):
                        try:
                            chat_completion = groq_client.chat.completions.create(
                                messages=[{"role": "user", "content": full_prompt}],
                                model="llama-3.3-70b-versatile", # Modelo excelente e grátis
                                temperature=0.0,
                                response_format={"type": "json_object"} # Garante JSON
                            )
                            response_text = chat_completion.choices[0].message.content
                        except Exception as e:
                            st.warning(f"Groq falhou ({e}). Tentando Gemini...")
                            # Fallback para Gemini se Groq falhar
                            used_ai = "💎 Gemini (Fallback)"
                            model = genai.GenerativeModel(gem_model)
                            res = model.generate_content([prompt_base, f"REF:\n{d1['data']}", f"CAND:\n{d2['data']}"])
                            response_text = res.text
                else:
                    used_ai = "💎 Gemini (Groq não configurada)"
                    model = genai.GenerativeModel(gem_model)
                    res = model.generate_content([prompt_base, f"REF:\n{d1['data']}", f"CAND:\n{d2['data']}"])
                    response_text = res.text

            # --- RESULTADOS ---
            if response_text:
                data = extract_json(response_text)
                if data:
                    norm = normalize_sections(data, lista_alvo)
                    secs = norm.get("SECOES", [])
                    
                    st.success(f"✅ Análise Concluída via {used_ai}")
                    st.divider()
                    
                    cA, cB = st.columns(2)
                    errs = sum(1 for s in secs if s['status'] != "OK")
                    score = 100 - int((errs/max(1, len(secs)))*100)
                    cA.metric("Aprovação", f"{score}%")
                    cB.metric("Seções", f"{len(secs)}/{len(lista_alvo)}")
                    
                    dates = norm.get("METADADOS", {}).get("datas", [])
                    if dates: st.markdown(f"**Data Anvisa:** <mark class='anvisa'>{dates[0]}</mark>", unsafe_allow_html=True)
                    
                    st.markdown("---")
                    
                    for s in secs:
                        icon = "✅"
                        if "DIVERGENTE" in s['status']: icon = "❌"
                        elif "FALTANTE" in s['status']: icon = "🚨"
                        
                        with st.expander(f"{icon} {s['titulo']} - {s['status']}"):
                            cRef, cBel = st.columns(2)
                            cRef.markdown(f"**Referência**<div class='box-content'>{s.get('ref','')}</div>", unsafe_allow_html=True)
                            cBel.markdown(f"**Candidato**<div class='box-content box-bel'>{s.get('bel','')}</div>", unsafe_allow_html=True)
                else:
                    st.error("Erro na leitura da IA (JSON inválido).")
                    st.expander("Debug").code(response_text)
            else:
                st.error("Nenhuma resposta da IA.")
    else:
        st.warning("Envie os arquivos.")
