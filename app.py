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
from PIL import Image

# ----------------- CONFIGURAÇÃO DA PÁGINA -----------------
st.set_page_config(
    page_title="Validador de Bulas",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- ESTILOS CSS (MANTIDOS) -----------------
st.markdown("""
<style>
    header[data-testid="stHeader"] { display: none !important; }
    .main .block-container { padding-top: 20px !important; }
    .main { background-color: #f4f6f8; }
    h1, h2, h3 { color: #2c3e50; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
    .stCard { background-color: white; padding: 25px; border-radius: 15px; box-shadow: 0 10px 20px rgba(0,0,0,0.05); margin-bottom: 25px; border: 1px solid #e1e4e8; }
    .card-title { color: #55a68e; font-size: 1.2rem; font-weight: bold; margin-bottom: 15px; border-bottom: 2px solid #f0f2f5; padding-bottom: 10px; }
    .highlight-yellow { background-color: #fff3cd; color: #856404; padding: 0 4px; border-radius: 4px; }
    .highlight-pink { background-color: #f8d7da; color: #721c24; padding: 0 4px; border-radius: 4px; }
    .highlight-blue { background-color: #cff4fc; color: #055160; padding: 0 4px; border-radius: 4px; }
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
SECOES_SEM_DIVERGENCIA = ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]

# ----------------- FUNÇÕES BACKEND -----------------

def get_gemini_model():
    # 1. Autenticação
    api_key = None
    try: api_key = st.secrets["GEMINI_API_KEY"]
    except: pass
    if not api_key: api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key: return None, "Chave Ausente"

    genai.configure(api_key=api_key)

    # 2. SELEÇÃO DE MODELO À PROVA DE FALHAS (Evita erro 404)
    modelo_escolhido = 'models/gemini-pro' # Fallback padrão antigo
    
    try:
        # Pergunta à API quais modelos existem na sua conta/versão
        modelos_disponiveis = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        
        # Ordem de preferência (Do melhor/mais barato para o antigo)
        preferencias = [
            'models/gemini-1.5-flash',
            'models/gemini-1.5-flash-latest',
            'models/gemini-1.5-pro',
            'models/gemini-1.5-pro-latest',
            'models/gemini-1.0-pro',
            'models/gemini-pro'
        ]
        
        # Seleciona o primeiro da lista de preferência que EXISTE na lista de disponíveis
        for pref in preferencias:
            if pref in modelos_disponiveis:
                modelo_escolhido = pref
                break
                
    except Exception as e:
        # Se falhar ao listar, usa o genérico que costuma funcionar sempre
        print(f"Erro ao listar modelos: {e}")
        modelo_escolhido = 'gemini-pro'

    # 3. Configurações de Segurança (BLOCK_NONE para evitar erro de Copyright falso)
    safety_config = {
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    }

    return genai.GenerativeModel(modelo_escolhido, safety_settings=safety_config), modelo_escolhido

def process_uploaded_file(uploaded_file):
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
            # Prioriza Texto (Rápido e evita erro de imagem)
            if len(full_text.strip()) > 50:
                 doc.close(); return {"type": "text", "data": full_text}
            # Fallback Imagem
            images = []
            limit_pages = min(12, len(doc))
            for i in range(limit_pages):
                page = doc[i]
                pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
                try: img_byte_arr = io.BytesIO(pix.tobytes("jpeg", jpg_quality=90))
                except: img_byte_arr = io.BytesIO(pix.tobytes("png"))
                images.append(Image.open(img_byte_arr))
            doc.close(); gc.collect()
            return {"type": "images", "data": images}
    except Exception as e: st.error(f"Erro arquivo: {e}"); return None
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

# ----------------- BARRA LATERAL -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=80)
    st.title("Validador de Bulas")
    model_instance, model_name_used = get_gemini_model()
    if model_instance: st.success(f"✅ Conectado: {model_name_used.replace('models/', '')}")
    else: st.error("❌ Erro Conexão"); st.caption("Verifique Secrets.")
    st.divider()
    pagina = st.radio("Navegação:", ["🏠 Início", "💊 Ref x BELFAR", "📋 Conferência MKT", "🎨 Gráfica x Arte"])
    st.divider()

# ----------------- PÁGINA INICIAL -----------------
if pagina == "🏠 Início":
    st.markdown("<h1 style='text-align: center; color: #55a68e;'>Validador Inteligente</h1>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1: st.info("💊 Ref x BELFAR")
    with c2: st.info("📋 MKT")
    with c3: st.info("🎨 Gráfica")

# ----------------- FERRAMENTA -----------------
else:
    st.markdown(f"## {pagina}")
    lista_secoes = SECOES_PACIENTE
    nome_tipo = "Paciente"
    label_box1 = "Arquivo 1"; label_box2 = "Arquivo 2"
    
    if pagina == "💊 Ref x BELFAR":
        label_box1 = "Ref"; label_box2 = "BELFAR"
        col_tipo, _ = st.columns([1, 2])
        with col_tipo:
            if st.radio("Tipo:", ["Paciente", "Profissional"], horizontal=True) == "Profissional":
                lista_secoes = SECOES_PROFISSIONAL; nome_tipo = "Profissional"
    elif pagina == "📋 Conferência MKT": label_box1 = "ANVISA"; label_box2 = "MKT"
    elif pagina == "🎨 Gráfica x Arte": label_box1 = "Arte"; label_box2 = "Gráfica"
    
    st.divider()
    c1, c2 = st.columns(2)
    with c1: st.markdown(f"##### {label_box1}"); f1 = st.file_uploader("", type=["pdf", "docx"], key="f1")
    with c2: st.markdown(f"##### {label_box2}"); f2 = st.file_uploader("", type=["pdf", "docx"], key="f2")
    
    if st.button("🚀 INICIAR AUDITORIA"):
        if not f1 or not f2: st.warning("Faça upload dos dois arquivos.")
        else:
            with st.spinner(f"Analisando com {model_name_used}..."):
                d1 = process_uploaded_file(f1)
                d2 = process_uploaded_file(f2)
                gc.collect()
                if not d1 or not d2: st.error("Erro leitura."); st.stop()

                payload = ["CONTEXTO: Auditoria Regulatória ANVISA. Documentos públicos."]
                n1 = label_box1.upper(); n2 = label_box2.upper()
                
                if d1['type']=='text': payload.append(f"--- {n1} ---\n{d1['data']}")
                else: payload.append(f"--- {n1} ---"); payload.extend(d1['data'])
                if d2['type']=='text': payload.append(f"--- {n2} ---\n{d2['data']}")
                else: payload.append(f"--- {n2} ---"); payload.extend(d2['data'])

                prompt = f"""
                Atue como Auditor Farmacêutico (ANVISA).
                DOC 1: {n1} | DOC 2: {n2}
                SEÇÕES ({nome_tipo}): {" | ".join(lista_secoes)}

                REGRA: Extraia o texto EXATO de cada seção para os dois documentos e compare.
                - Use <mark class='diff'> para divergências.
                - Use <mark class='ort'> para erros ortográficos.
                - Ignore formatação, foque no conteúdo.
                - Se achar "Aprovado em dd/mm/aaaa" nos Dizeres Legais, marque com <mark class='anvisa'>.

                JSON: {{ "METADADOS": {{ "score": 0-100, "datas": [] }}, "SECOES": [ {{ "titulo": "...", "ref": "...", "bel": "...", "status": "CONFORME|DIVERGENTE|FALTANTE" }} ] }}
                """

                try:
                    # Tenta gerar
                    response = model_instance.generate_content(
                        [prompt] + payload,
                        generation_config={"response_mime_type": "application/json"}
                    )
                    
                    if hasattr(response.candidates[0], 'finish_reason') and response.candidates[0].finish_reason == 4:
                        st.error("⚠️ Bloqueio de Copyright. Tente enviar arquivo .DOCX ou apenas texto.")
                    else:
                        data = extract_json(response.text)
                        if not data: st.error("Erro processamento IA.")
                        else:
                            meta = data.get("METADADOS", {})
                            m1, m2, m3 = st.columns(3)
                            m1.metric("Score", f"{meta.get('score', 0)}%")
                            m2.metric("Seções", len(data.get("SECOES", [])))
                            m3.metric("Datas", ", ".join(meta.get("datas", [])) or "--")
                            st.divider()
                            for sec in data.get("SECOES", []):
                                stt = sec.get('status', 'N/A')
                                icon = "✅" if "CONFORME" in stt else "❌"
                                if "FALTANTE" in stt: icon = "🚨"
                                with st.expander(f"{icon} {sec['titulo']} — {stt}"):
                                    ca, cb = st.columns(2)
                                    ca.markdown(f"**{n1}**"); ca.markdown(f"<div style='background:#f9f9f9;padding:10px;'>{sec.get('ref','')}</div>", unsafe_allow_html=True)
                                    cb.markdown(f"**{n2}**"); cb.markdown(f"<div style='background:#f0fff4;padding:10px;'>{sec.get('bel','')}</div>", unsafe_allow_html=True)
                except Exception as e: st.error(f"Erro: {e}")
