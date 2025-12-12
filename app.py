import streamlit as st
import google.generativeai as genai
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
    
    .stCard {
        background-color: white; padding: 25px; border-radius: 15px;
        box-shadow: 0 10px 20px rgba(0,0,0,0.05); margin-bottom: 25px;
        border: 1px solid #e1e4e8; transition: transform 0.2s; height: 100%;
    }
    .stCard:hover { transform: translateY(-5px); border-color: #55a68e; }
    .card-title { color: #55a68e; font-size: 1.2rem; font-weight: bold; margin-bottom: 15px; border-bottom: 2px solid #f0f2f5; padding-bottom: 10px; }
    .stButton>button { width: 100%; background-color: #55a68e; color: white; font-weight: bold; border-radius: 10px; height: 55px; border: none; font-size: 16px; }
    .stButton>button:hover { background-color: #448c75; }
    
    mark.diff { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; }
    mark.ort { background-color: #f8d7da; color: #721c24; padding: 2px 4px; border-radius: 4px; border-bottom: 2px solid #dc3545; }
    mark.anvisa { background-color: #cff4fc; color: #055160; padding: 2px 4px; border-radius: 4px; border: 1px solid #b6effb; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# ----------------- CONSTANTES -----------------
SECOES_PACIENTE = [
    "APRESENTAÇÕES", "COMPOSIÇÃO", 
    "PARA QUE ESTE MEDICAMENTO É INDICADO", "COMO ESTE MEDICAMENTO FUNCIONA?", 
    "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?", "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?", 
    "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?", "COMO DEVO USAR ESTE MEDICAMENTO?", 
    "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?", 
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

SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# ----------------- FUNÇÕES DE BACKEND -----------------

def get_gemini_model():
    """Configura o modelo principal (Gemini 3)."""
    api_key = None
    try:
        api_key = st.secrets["GEMINI_API_KEY"]
    except:
        api_key = os.environ.get("GEMINI_API_KEY")
    
    if not api_key: return None, "Sem Chave API"

    genai.configure(api_key=api_key)
    
    # Mantém o 3.0 como padrão visual
    return genai.GenerativeModel("gemini-3-pro-preview"), "Modelo Ativo: gemini-3-pro-preview"

def process_uploaded_file(uploaded_file):
    if not uploaded_file: return None
    try:
        file_bytes = uploaded_file.read()
        filename = uploaded_file.name.lower()
        
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            return {"type": "text", "data": text, "is_image": False}
            
        elif filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            full_text = ""
            for page in doc:
                full_text += page.get_text() + "\n"
            
            if len(full_text.strip()) > 50:
                doc.close()
                return {"type": "text", "data": full_text, "is_image": False}
            
            images = []
            limit_pages = min(6, len(doc)) 
            for i in range(limit_pages):
                page = doc[i]
                pix = page.get_pixmap(matrix=fitz.Matrix(1.0, 1.0))
                try:
                    img_byte_arr = io.BytesIO(pix.tobytes("jpeg", jpg_quality=80))
                except:
                    img_byte_arr = io.BytesIO(pix.tobytes("png"))
                images.append(Image.open(img_byte_arr))
            
            doc.close()
            gc.collect()
            return {"type": "images", "data": images, "is_image": True}
            
    except Exception as e:
        st.error(f"Erro no arquivo: {e}")
        return None
    return None

def clean_json_response(text):
    text = text.replace("```json", "").replace("```", "").strip()
    text = re.sub(r'//.*', '', text)
    if text.startswith("json"): text = text[4:]
    return text

def extract_json(text):
    try:
        clean = clean_json_response(text)
        start = clean.find('{')
        end = clean.rfind('}') + 1
        if start != -1 and end != -1: return json.loads(clean[start:end])
        return json.loads(clean)
    except: return None

# ----------------- UI LATERAL -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=80)
    st.title("Validador de Bulas")
    
    model_instance, model_name = get_gemini_model()
    
    if model_instance:
        st.success(f"✅ {model_name}")
    else:
        st.error("❌ Verifique a Chave API")
    
    st.divider()
    pagina = st.radio("Navegação:", ["🏠 Início", "💊 Ref x BELFAR", "📋 Conferência MKT", "🎨 Gráfica x Arte"])
    st.divider()

# ----------------- PÁGINAS -----------------
if pagina == "🏠 Início":
    st.markdown("<h1 style='color:#55a68e;text-align:center;'>Validador Inteligente</h1>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    c1.info("💊 Ref x BELFAR: Comparação de textos.")
    c2.info("📋 Conf. MKT: Validação de artes.")
    c3.info("🎨 Gráfica: Verificação de PDF.")

else:
    st.markdown(f"## {pagina}")
    
    lista_secoes = SECOES_PACIENTE
    label1, label2 = "Referência", "Candidato"
    
    if pagina == "💊 Ref x BELFAR":
        c_opt, _ = st.columns([1,2])
        if c_opt.radio("Tipo:", ["Paciente", "Profissional"], horizontal=True) == "Profissional":
            lista_secoes = SECOES_PROFISSIONAL
            
    elif pagina == "📋 Conferência MKT": label1, label2 = "ANVISA", "MKT"
    elif pagina == "🎨 Gráfica x Arte": label1, label2 = "Arte Vigente", "Gráfica"
    
    c1, c2 = st.columns(2)
    f1 = c1.file_uploader(label1, type=["pdf", "docx"], key="f1")
    f2 = c2.file_uploader(label2, type=["pdf", "docx"], key="f2")
        
    if st.button("🚀 INICIAR AUDITORIA"):
        if f1 and f2 and model_instance:
            with st.spinner("Analisando documentos..."):
                try:
                    d1 = process_uploaded_file(f1)
                    d2 = process_uploaded_file(f2)
                    gc.collect()

                    if d1 and d2:
                        risco_copyright = d1['is_image'] or d2['is_image']
                        
                        payload = ["CONTEXTO: Comparação de textos técnicos."]
                        
                        if d1['type'] == 'text': payload.append(f"--- DOC 1 ---\n{d1['data']}")
                        else: payload.append("--- DOC 1 ---"); payload.extend(d1['data'])
                        
                        if d2['type'] == 'text': payload.append(f"--- DOC 2 ---\n{d2['data']}")
                        else: payload.append("--- DOC 2 ---"); payload.extend(d2['data'])

                        secoes_str = "\n".join([f"- {s}" for s in lista_secoes])
                        
                        prompt = f"""
                        Atue como Auditor. Compare DOC 1 e DOC 2.
                        SEÇÕES: {secoes_str}
                        REGRAS:
                        1. Extraia o texto. Sem títulos.
                        2. Marque diferenças com <mark class='diff'> e erros com <mark class='ort'>.
                        3. Data: <mark class='anvisa'>dd/mm/aaaa</mark>.
                        SAÍDA JSON: {{ "METADADOS": {{ "score": 0, "datas": [] }}, "SECOES": [ {{ "titulo": "...", "ref": "...", "bel": "...", "status": "..." }} ] }}
                        """

                        # ==============================================================
                        # CASCATA DE SOBREVIVÊNCIA 3.0 (DYNAMIC DISCOVERY)
                        # ==============================================================
                        response = None
                        sucesso = False
                        error_log = []
                        
                        # --- TENTATIVA 1: GEMINI 3 ---
                        try:
                            response = model_instance.generate_content(
                                [prompt] + payload,
                                generation_config={"response_mime_type": "application/json"},
                                safety_settings=SAFETY_SETTINGS
                            )
                            sucesso = True
                        except Exception as e:
                            error_msg = str(e)
                            error_log.append(f"Gemini 3: {error_msg}")
                            if "429" in error_msg or "Quota" in error_msg:
                                st.warning("⚠️ Cota do Gemini 3 esgotada. Buscando alternativa...")
                                time.sleep(1)
                            else:
                                st.warning(f"Erro no Gemini 3. Buscando alternativa...")

                        # --- TENTATIVA 2 & 3: VARREDURA TOTAL ---
                        # Se o principal falhou, listamos TUDO que sua chave API consegue ver
                        # e tentamos um por um, priorizando os modelos 'Flash'
                        if not sucesso:
                            st.caption("🛡️ Escaneando modelos disponíveis na API...")
                            try:
                                # 1. Busca modelos disponíveis
                                all_models = genai.list_models()
                                available_models = []
                                for m in all_models:
                                    if 'generateContent' in m.supported_generation_methods:
                                        available_models.append(m.name)
                                
                                # 2. Ordena: Flash primeiro, depois 1.5, depois Pro 1.0 (legado)
                                # Isso garante que usamos o mais rápido/barato disponível
                                def sort_priority(name):
                                    if "flash" in name and "1.5" in name: return 0
                                    if "flash" in name: return 1
                                    if "pro" in name and "1.5" in name: return 2
                                    if "gemini-pro" in name: return 3 # O antigo 1.0 é o último recurso
                                    return 4
                                
                                available_models.sort(key=sort_priority)
                                
                                # 3. Adiciona fallback forçado caso a lista venha vazia por erro
                                if not available_models:
                                    available_models = ["models/gemini-1.5-flash", "models/gemini-pro"]

                                # 4. Tenta conectar em loop
                                for model_name in available_models:
                                    # Pula o Gemini 3 que já falhou
                                    if "gemini-3" in model_name: continue
                                    
                                    try:
                                        # st.caption(f"Tentando: {model_name}...") # Debug
                                        fallback_model = genai.GenerativeModel(model_name)
                                        response = fallback_model.generate_content(
                                            [prompt] + payload,
                                            generation_config={"response_mime_type": "application/json"},
                                            safety_settings=SAFETY_SETTINGS
                                        )
                                        sucesso = True
                                        st.success(f"✅ Conectado via: {model_name}")
                                        break # Sai do loop ao sucesso
                                    except Exception as inner_e:
                                        # Se for cota (429), continua tentando o próximo. 
                                        # Se for 404, continua.
                                        error_log.append(f"{model_name}: {str(inner_e)}")
                                        continue

                            except Exception as e:
                                error_log.append(f"Erro na varredura: {str(e)}")

                        # --- RESULTADO FINAL ---
                        if not sucesso:
                            st.error("❌ FALHA CRÍTICA: Todas as cotas esgotadas ou erro de conexão.")
                            with st.expander("Ver Logs Técnicos (Debug)"):
                                st.write(error_log)
                                st.info("Sua chave API excedeu os limites gratuitos (Free Tier) de TODOS os modelos hoje.")

                        # ==============================================================
                        # RENDERIZAÇÃO
                        # ==============================================================
                        if sucesso and response:
                            if hasattr(response.candidates[0], 'finish_reason') and response.candidates[0].finish_reason == 4:
                                st.error("⚠️ Bloqueio de Segurança (Copyright)")
                                if risco_copyright: st.warning("Arquivo protegido. Use DOCX.")
                            else:
                                data = extract_json(response.text)
                                if data:
                                    meta = data.get("METADADOS", {})
                                    cM1, cM2, cM3 = st.columns(3)
                                    cM1.metric("Score", f"{meta.get('score',0)}%")
                                    cM2.metric("Seções", len(data.get("SECOES", [])))
                                    cM3.metric("Datas", str(meta.get("datas", [])))
                                    st.divider()
                                    
                                    for sec in data.get("SECOES", []):
                                        status = sec.get('status', 'N/A')
                                        icon = "✅"
                                        if "DIVERGENTE" in status: icon = "❌"
                                        elif "FALTANTE" in status: icon = "🚨"
                                        
                                        with st.expander(f"{icon} {sec['titulo']} - {status}"):
                                            cA, cB = st.columns(2)
                                            cA.markdown(f"**Referência**\n<div style='background:#f9f9f9;padding:10px;'>{sec.get('ref','')}</div>", unsafe_allow_html=True)
                                            cB.markdown(f"**Belfar**\n<div style='background:#f0fff4;padding:10px;'>{sec.get('bel','')}</div>", unsafe_allow_html=True)
                                else:
                                    st.error("Erro ao ler resposta da IA (JSON Inválido). Tente novamente.")
                        
                except Exception as e:
                    st.error(f"Erro geral: {e}")
