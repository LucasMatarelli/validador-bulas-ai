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

# ----------------- FUNÇÃO DE CONEXÃO DIRETA (REST API) -----------------
def call_gemini_api_direct(prompt, parts_payload):
    """
    Faz a chamada HTTP direta para o Google, sem usar biblioteca.
    Isso evita erros de versão e 404.
    """
    # 1. Pega a Chave
    api_key = None
    try: api_key = st.secrets["GEMINI_API_KEY"]
    except: pass
    if not api_key: api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key: return {"error": "Chave API não encontrada"}

    # 2. URL Fixa (Modelo 1.5 Flash - Estável e Grátis)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    
    # 3. Cabeçalhos
    headers = {"Content-Type": "application/json"}

    # 4. Configuração de Segurança (Block None)
    safety_settings = [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
    ]

    # 5. Monta o JSON final
    final_payload = {
        "contents": [{
            "parts": [
                {"text": prompt}
            ] + parts_payload # Adiciona imagens ou textos processados
        }],
        "safetySettings": safety_settings,
        "generationConfig": {
            "response_mime_type": "application/json"
        }
    }

    try:
        response = requests.post(url, headers=headers, data=json.dumps(final_payload), timeout=60)
        
        if response.status_code != 200:
            return {"error": f"Erro HTTP {response.status_code}: {response.text}"}
            
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
            # Retorna formato para o Payload do Gemini
            return [{"text": f"--- CONTEÚDO DO ARQUIVO DOCX ---\n{text}"}]
            
        elif filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            
            # Tenta texto primeiro
            full_text = ""
            for page in doc: full_text += page.get_text() + "\n"
            
            if len(full_text.strip()) > 50:
                 doc.close()
                 return [{"text": f"--- CONTEÚDO DO PDF (TEXTO) ---\n{full_text}"}]

            # Se não tiver texto, converte para imagem (Base64) para a API ler
            parts = []
            parts.append({"text": "--- O ARQUIVO A SEGUIR SÃO IMAGENS DO PDF ---"})
            limit_pages = min(12, len(doc))
            
            for i in range(limit_pages):
                page = doc[i]
                pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5)) # Qualidade média
                # Converte para base64
                img_bytes = pix.tobytes("jpeg", jpg_quality=85)
                b64_string = base64.b64encode(img_bytes).decode('utf-8')
                
                parts.append({
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": b64_string
                    }
                })
            
            doc.close()
            gc.collect()
            return parts
            
    except Exception as e:
        st.error(f"Erro ao processar arquivo: {e}")
        return None
    return None

def extract_json_from_response(api_response):
    try:
        # Caminho para extrair texto da resposta REST do Gemini
        text_response = api_response['candidates'][0]['content']['parts'][0]['text']
        
        clean = text_response.replace("```json", "").replace("```", "").strip()
        start = clean.find('{'); end = clean.rfind('}') + 1
        if start != -1 and end != -1: return json.loads(clean[start:end])
        return json.loads(clean)
    except Exception as e:
        st.error(f"Erro ao ler JSON da resposta: {e} | Resposta Crua: {str(api_response)}")
        return None

# ----------------- INTERFACE -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=80)
    st.title("Validador de Bulas")
    st.caption("Modo: Conexão Direta (REST)")
    
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
    label_box1 = "Arquivo 1"; label_box2 = "Arquivo 2"
    if pagina == "💊 Ref x BELFAR": label_box1 = "Ref"; label_box2 = "BELFAR"
    elif pagina == "📋 MKT": label_box1 = "ANVISA"; label_box2 = "MKT"
    elif pagina == "🎨 Gráfica": label_box1 = "Arte"; label_box2 = "Gráfica"
    
    st.divider()
    c1, c2 = st.columns(2)
    with c1: st.markdown(f"##### {label_box1}"); f1 = st.file_uploader("", type=["pdf", "docx"], key="f1")
    with c2: st.markdown(f"##### {label_box2}"); f2 = st.file_uploader("", type=["pdf", "docx"], key="f2")
    
    if st.button("🚀 INICIAR AUDITORIA"):
        if not f1 or not f2: st.warning("Faça upload dos dois arquivos.")
        else:
            with st.spinner(f"Processando e enviando para o Google..."):
                # Processa arquivos
                parts1 = process_uploaded_file(f1)
                parts2 = process_uploaded_file(f2)
                gc.collect()

                if not parts1 or not parts2: st.stop()

                # Monta Prompt
                payload_parts = []
                payload_parts.append({"text": "CONTEXTO: Auditoria Regulatória ANVISA. Documentos públicos de saúde."})
                
                # Adiciona partes do Doc 1
                payload_parts.append({"text": f"=== DOCUMENTO 1 ({label_box1}) ==="})
                payload_parts.extend(parts1)
                
                # Adiciona partes do Doc 2
                payload_parts.append({"text": f"=== DOCUMENTO 2 ({label_box2}) ==="})
                payload_parts.extend(parts2)

                prompt_text = f"""
                Atue como Auditor Farmacêutico (ANVISA).
                Compare o DOC 1 com o DOC 2.
                SEÇÕES PARA ANALISAR: APRESENTAÇÕES, COMPOSIÇÃO, INDICAÇÕES, POSOLOGIA, ADVERTÊNCIAS.
                
                REGRA ZERO: EXTRAÇÃO LIMPA
                1. Ignore títulos, extraia apenas o conteúdo.
                
                REGRA UM: COMPARAÇÃO
                - Divergências de sentido: use <mark class='diff'>
                - Erros ortográficos: use <mark class='ort'>
                - Se encontrar "Aprovado em dd/mm/aaaa" nos Dizeres Legais, use <mark class='anvisa'>.

                SAÍDA JSON OBRIGATÓRIA:
                {{ "METADADOS": {{ "score": 0-100, "datas": [] }}, "SECOES": [ {{ "titulo": "...", "ref": "...", "bel": "...", "status": "CONFORME|DIVERGENTE|FALTANTE" }} ] }}
                """

                # Chama a API Direta
                resultado = call_gemini_api_direct(prompt_text, payload_parts)
                
                if "error" in resultado:
                    if "429" in str(resultado['error']):
                        st.error("Muitas requisições. Espere alguns segundos.")
                    elif "finishReason" in str(resultado) and "SAFETY" in str(resultado):
                         st.error("⚠️ Bloqueio de Conteúdo (Copyright/Segurança).")
                    else:
                        st.error(f"Erro na API: {resultado['error']}")
                else:
                    data = extract_json_from_response(resultado)
                    if not data: st.error("Erro ao interpretar JSON da IA.")
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
