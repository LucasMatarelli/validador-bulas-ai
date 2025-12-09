import streamlit as st
import requests
import fitz  # PyMuPDF
import docx
import io
import json
import re
import os
import gc
import base64
from PIL import Image

# ----------------- CONFIGURAÇÃO DA PÁGINA -----------------
st.set_page_config(
    page_title="Validador de Bulas",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- ESTILOS CSS -----------------
st.markdown("""
<style>
    header[data-testid="stHeader"] { display: none !important; }
    .main .block-container { padding-top: 20px !important; }
    .main { background-color: #f4f6f8; }
    h1, h2, h3 { color: #2c3e50; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
    .stCard { background-color: white; padding: 25px; border-radius: 15px; box-shadow: 0 10px 20px rgba(0,0,0,0.05); margin-bottom: 25px; border: 1px solid #e1e4e8; }
    .card-title { color: #55a68e; font-size: 1.2rem; font-weight: bold; margin-bottom: 15px; border-bottom: 2px solid #f0f2f5; padding-bottom: 10px; }
    .stButton>button { width: 100%; background-color: #55a68e; color: white; font-weight: bold; border-radius: 10px; height: 55px; border: none; font-size: 16px; }
    mark.diff { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 4px; }
    mark.ort { background-color: #f8d7da; color: #721c24; padding: 2px 4px; border-radius: 4px; }
    mark.anvisa { background-color: #cff4fc; color: #055160; padding: 2px 4px; border-radius: 4px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# ----------------- FUNÇÕES DE CONEXÃO INTELIGENTE (REST API) -----------------

def get_best_available_model(api_key):
    """
    Pergunta à API quais modelos estão disponíveis para esta chave
    e retorna o melhor nome para usar, evitando erro 404.
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        response = requests.get(url)
        if response.status_code != 200:
            return None, f"Erro ao listar modelos: {response.text}"
        
        data = response.json()
        modelos = data.get('models', [])
        
        # Filtra apenas modelos que geram conteúdo
        modelos_uteis = [m['name'] for m in modelos if 'generateContent' in m.get('supportedGenerationMethods', [])]
        
        # Ordem de preferência
        if not modelos_uteis: return None, "Nenhum modelo disponível para esta chave."

        # Tenta achar o Flash
        for m in modelos_uteis:
            if 'flash' in m and '1.5' in m: return m, None
        
        # Tenta achar o Pro 1.5
        for m in modelos_uteis:
            if 'pro' in m and '1.5' in m: return m, None
            
        # Tenta achar o Pro 1.0 (Gemini Pro clássico)
        for m in modelos_uteis:
            if 'gemini-pro' in m: return m, None
            
        # Se não achar preferidos, pega o primeiro da lista
        return modelos_uteis[0], None
        
    except Exception as e:
        return None, str(e)

def call_gemini_api_direct(prompt, parts_payload):
    # 1. Pega a Chave
    api_key = None
    try: api_key = st.secrets["GEMINI_API_KEY"]
    except: pass
    if not api_key: api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key: return {"error": "Chave API não encontrada"}

    # 2. DESCOBRE O MODELO CERTO (Auto-Discovery)
    model_name, error = get_best_available_model(api_key)
    
    if not model_name:
        # Fallback de emergência se a listagem falhar
        model_name = "models/gemini-pro"
    
    # Remove o prefixo 'models/' se já vier com ele, pra garantir formato da URL
    model_name_clean = model_name.replace("models/", "")
    
    # URL Dinâmica
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name_clean}:generateContent?key={api_key}"
    
    headers = {"Content-Type": "application/json"}
    
    # Payload
    final_payload = {
        "contents": [{
            "parts": [{"text": prompt}] + parts_payload
        }],
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
        ],
        "generationConfig": {
            "response_mime_type": "application/json"
        }
    }

    try:
        response = requests.post(url, headers=headers, data=json.dumps(final_payload), timeout=60)
        if response.status_code != 200:
            return {"error": f"Erro HTTP {response.status_code} no modelo {model_name_clean}: {response.text}"}
        return response.json()
    except Exception as e:
        return {"error": str(e)}

# ----------------- PROCESSAMENTO DE ARQUIVOS -----------------
def process_uploaded_file(uploaded_file):
    if not uploaded_file: return None
    try:
        file_bytes = uploaded_file.read()
        filename = uploaded_file.name.lower()
        
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            return [{"text": f"--- CONTEÚDO DOCX ---\n{text}"}]
            
        elif filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            
            # Tenta texto primeiro
            full_text = ""
            for page in doc: full_text += page.get_text() + "\n"
            
            if len(full_text.strip()) > 50:
                 doc.close()
                 return [{"text": f"--- CONTEÚDO PDF (TEXTO) ---\n{full_text}"}]

            # Fallback Imagem
            parts = []
            parts.append({"text": "--- IMAGENS DO PDF ---"})
            limit_pages = min(12, len(doc))
            
            for i in range(limit_pages):
                page = doc[i]
                pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
                img_bytes = pix.tobytes("jpeg", jpg_quality=85)
                b64_string = base64.b64encode(img_bytes).decode('utf-8')
                parts.append({
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": b64_string
                    }
                })
            doc.close(); gc.collect()
            return parts
            
    except Exception as e:
        st.error(f"Erro processamento: {e}")
        return None
    return None

def extract_json_from_response(api_response):
    try:
        if 'candidates' in api_response and api_response['candidates']:
            content = api_response['candidates'][0]['content']['parts'][0]['text']
            clean = content.replace("```json", "").replace("```", "").strip()
            start = clean.find('{'); end = clean.rfind('}') + 1
            if start != -1 and end != -1: return json.loads(clean[start:end])
            return json.loads(clean)
        else:
            return None
    except: return None

# ----------------- INTERFACE -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=80)
    st.title("Validador de Bulas")
    
    # Mostra qual modelo foi detectado (se possível) ou status
    st.caption("Modo: Auto-Discovery (REST)")
    st.divider()
    pagina = st.radio("Navegação:", ["🏠 Início", "💊 Ref x BELFAR", "📋 MKT", "🎨 Gráfica"])

if pagina == "🏠 Início":
    st.markdown("<h1 style='text-align: center; color: #55a68e;'>Validador Inteligente</h1>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1: st.info("💊 Ref x BELFAR")
    with c2: st.info("📋 MKT")
    with c3: st.info("🎨 Gráfica")

else:
    st.markdown(f"## {pagina}")
    label_box1 = "Ref"; label_box2 = "BELFAR"
    if pagina == "📋 MKT": label_box1 = "ANVISA"; label_box2 = "MKT"
    elif pagina == "🎨 Gráfica": label_box1 = "Arte"; label_box2 = "Gráfica"
    
    st.divider()
    c1, c2 = st.columns(2)
    with c1: st.markdown(f"##### {label_box1}"); f1 = st.file_uploader("", type=["pdf", "docx"], key="f1")
    with c2: st.markdown(f"##### {label_box2}"); f2 = st.file_uploader("", type=["pdf", "docx"], key="f2")
    
    if st.button("🚀 INICIAR AUDITORIA"):
        if not f1 or not f2: st.warning("Upload obrigatório dos dois arquivos.")
        else:
            with st.spinner("Detectando melhor modelo e analisando..."):
                p1 = process_uploaded_file(f1); p2 = process_uploaded_file(f2)
                gc.collect()

                if not p1 or not p2: st.stop()

                payload_parts = [{"text": "CONTEXTO: Auditoria ANVISA."}]
                payload_parts.append({"text": f"=== DOC 1 ({label_box1}) ==="}); payload_parts.extend(p1)
                payload_parts.append({"text": f"=== DOC 2 ({label_box2}) ==="}); payload_parts.extend(p2)

                prompt = f"""
                Atue como Auditor Farmacêutico.
                Compare DOC 1 e DOC 2.
                Seções: APRESENTAÇÕES, COMPOSIÇÃO, INDICAÇÕES, POSOLOGIA.
                
                Saída JSON:
                {{ "METADADOS": {{ "score": 0-100, "datas": [] }}, "SECOES": [ {{ "titulo": "...", "ref": "...", "bel": "...", "status": "CONFORME|DIVERGENTE|FALTANTE" }} ] }}
                """

                res = call_gemini_api_direct(prompt, payload_parts)
                
                if "error" in res:
                    st.error(f"Falha na API: {res['error']}")
                    if "404" in str(res['error']):
                        st.info("Dica: Verifique se sua Chave API está ativa no Google AI Studio.")
                else:
                    data = extract_json_from_response(res)
                    if not data: st.error("Erro no JSON da resposta.")
                    else:
                        meta = data.get("METADADOS", {})
                        m1, m2, m3 = st.columns(3)
                        m1.metric("Score", f"{meta.get('score', 0)}%")
                        m2.metric("Seções", len(data.get("SECOES", [])))
                        m3.metric("Datas", ", ".join(meta.get("datas", [])) or "--")
                        st.divider()
                        for sec in data.get("SECOES", []):
                            icon = "✅" if "CONFORME" in sec.get('status','') else "❌"
                            with st.expander(f"{icon} {sec.get('titulo')} — {sec.get('status')}"):
                                ca, cb = st.columns(2)
                                ca.markdown(f"**{label_box1}**"); ca.markdown(f"<div style='background:#f9f9f9;padding:10px;'>{sec.get('ref','')}</div>", unsafe_allow_html=True)
                                cb.markdown(f"**{label_box2}**"); cb.markdown(f"<div style='background:#f0fff4;padding:10px;'>{sec.get('bel','')}</div>", unsafe_allow_html=True)
