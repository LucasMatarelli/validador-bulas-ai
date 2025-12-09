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

# ... (MANTENHA O CSS IGUAL AO ANTERIOR) ...
st.markdown("""
<style>
    header[data-testid="stHeader"] { display: none !important; }
    .main .block-container { padding-top: 20px !important; }
    .main { background-color: #f4f6f8; }
    h1, h2, h3 { color: #2c3e50; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
    .stRadio > div[role="radiogroup"] > label { background-color: white; border: 1px solid #e1e4e8; padding: 12px 15px; border-radius: 8px; margin-bottom: 8px; transition: all 0.2s; box-shadow: 0 2px 4px rgba(0,0,0,0.02); }
    .stRadio > div[role="radiogroup"] > label:hover { background-color: #f0fbf7; border-color: #55a68e; color: #55a68e; cursor: pointer; }
    .stCard { background-color: white; padding: 25px; border-radius: 15px; box-shadow: 0 10px 20px rgba(0,0,0,0.05); margin-bottom: 25px; border: 1px solid #e1e4e8; transition: transform 0.2s; height: 100%; }
    .stCard:hover { transform: translateY(-5px); box-shadow: 0 15px 30px rgba(0,0,0,0.1); border-color: #55a68e; }
    .card-title { color: #55a68e; font-size: 1.2rem; font-weight: bold; margin-bottom: 15px; border-bottom: 2px solid #f0f2f5; padding-bottom: 10px; }
    .card-text { font-size: 0.95rem; color: #555; line-height: 1.6; }
    .highlight-yellow { background-color: #fff3cd; color: #856404; padding: 0 4px; border-radius: 4px; font-weight: 500; }
    .highlight-pink { background-color: #f8d7da; color: #721c24; padding: 0 4px; border-radius: 4px; font-weight: 500; }
    .highlight-blue { background-color: #cff4fc; color: #055160; padding: 0 4px; border-radius: 4px; font-weight: 500; }
    .stButton>button { width: 100%; background-color: #55a68e; color: white; font-weight: bold; border-radius: 10px; height: 55px; border: none; font-size: 16px; box-shadow: 0 4px 6px rgba(85, 166, 142, 0.2); }
    .stButton>button:hover { background-color: #448c75; box-shadow: 0 6px 8px rgba(85, 166, 142, 0.3); }
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

# ----------------- FUNÇÕES DE BACKEND (IA) -----------------

def get_gemini_model():
    # 1. TENTA LER A CHAVE
    api_key = None
    try: api_key = st.secrets["GEMINI_API_KEY"]
    except: pass
    if not api_key: api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key: return None, "Chave API ausente"

    genai.configure(api_key=api_key)
    
    # 2. LISTA DE MODELOS (DO MAIS NOVO PARA O MAIS ANTIGO)
    # Se a lib estiver velha, 'gemini-1.5-flash' dá erro 404.
    # O código vai tentar o próximo da lista automaticamente.
    modelos_para_testar = [
        'gemini-1.5-flash',       # O ideal
        'gemini-1.5-flash-latest', # Variação de nome
        'gemini-1.5-pro',         # Backup potente
        'gemini-pro',             # O clássico 1.0 (funciona em libs antigas)
    ]
    
    safety_config = {
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    }
    
    # Tenta instanciar um por um
    for model_name in modelos_para_testar:
        try:
            model = genai.GenerativeModel(model_name=model_name, safety_settings=safety_config)
            # Teste rápido de "vida" (opcional, mas bom pra garantir que o nome existe)
            # Vamos apenas retornar o objeto se não der erro na instanciação
            return model, model_name
        except Exception:
            continue
    
    # Se nada funcionar, tenta o genérico sem especificar versão (pode pegar o 1.0)
    return genai.GenerativeModel('gemini-pro', safety_settings=safety_config), "gemini-pro (Fallback Final)"

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
            
            # Prioriza Texto (Mais rápido e barato)
            if len(full_text.strip()) > 50:
                 doc.close()
                 return {"type": "text", "data": full_text}

            # Fallback Imagem (OCR)
            images = []
            limit_pages = min(12, len(doc))
            for i in range(limit_pages):
                page = doc[i]
                pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
                try: img_byte_arr = io.BytesIO(pix.tobytes("jpeg", jpg_quality=90))
                except: img_byte_arr = io.BytesIO(pix.tobytes("png"))
                images.append(Image.open(img_byte_arr))
            doc.close()
            gc.collect()
            return {"type": "images", "data": images}
    except Exception as e:
        st.error(f"Erro arquivo: {e}")
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

# ----------------- BARRA LATERAL -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=80)
    st.title("Validador de Bulas")
    
    model_instance, model_name_used = get_gemini_model()
    
    if model_instance:
        st.success(f"✅ Conectado: {model_name_used.replace('models/', '')}")
    else:
        st.error("❌ Erro de Conexão")
        st.caption("Verifique a chave API.")
    
    st.divider()
    pagina = st.radio("Navegação:", ["🏠 Início", "💊 Ref x BELFAR", "📋 Conferência MKT", "🎨 Gráfica x Arte"])
    st.divider()

# ----------------- PÁGINA INICIAL -----------------
if pagina == "🏠 Início":
    st.markdown("""
    <div style="text-align: center; padding: 30px 20px;">
        <h1 style="color: #55a68e; font-size: 3rem;">Validador Inteligente</h1>
        <p style="font-size: 20px; color: #7f8c8d;">Central de auditoria de bulas com IA.</p>
    </div>
    """, unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1: st.info("💊 Medicamento Referência x BELFAR")
    with c2: st.info("📋 Conferência MKT")
    with c3: st.info("🎨 Gráfica x Arte Vigente")

# ----------------- FERRAMENTA -----------------
else:
    st.markdown(f"## {pagina}")
    lista_secoes = SECOES_PACIENTE
    nome_tipo = "Paciente"
    label_box1 = "Arquivo 1"
    label_box2 = "Arquivo 2"
    
    if pagina == "💊 Ref x BELFAR":
        label_box1 = "📄 Documento de Referência"
        label_box2 = "📄 Documento BELFAR"
        col_tipo, _ = st.columns([1, 2])
        with col_tipo:
            if st.radio("Tipo:", ["Paciente", "Profissional"], horizontal=True) == "Profissional":
                lista_secoes = SECOES_PROFISSIONAL; nome_tipo = "Profissional"

    elif pagina == "📋 Conferência MKT": label_box1 = "📄 ANVISA"; label_box2 = "📄 MKT"
    elif pagina == "🎨 Gráfica x Arte": label_box1 = "📄 Arte Vigente"; label_box2 = "📄 PDF Gráfica"
    
    st.divider()
    c1, c2 = st.columns(2)
    with c1: st.markdown(f"##### {label_box1}"); f1 = st.file_uploader("", type=["pdf", "docx"], key="f1")
    with c2: st.markdown(f"##### {label_box2}"); f2 = st.file_uploader("", type=["pdf", "docx"], key="f2")
    
    st.write("") 
    if st.button("🚀 INICIAR AUDITORIA COMPLETA"):
        if not f1 or not f2: st.warning("⚠️ Faça upload dos dois arquivos.")
        else:
            with st.spinner(f"🤖 Analisando com {model_name_used}..."):
                try:
                    d1 = process_uploaded_file(f1)
                    d2 = process_uploaded_file(f2)
                    gc.collect()

                    if not d1 or not d2: st.error("Erro leitura arquivos."); st.stop()

                    payload = ["CONTEXTO: Documentos Regulatórios Públicos da ANVISA. Não é literário."]
                    n1 = label_box1.replace("📄 ", "").upper()
                    n2 = label_box2.replace("📄 ", "").upper()

                    if d1['type']=='text': payload.append(f"--- {n1} ---\n{d1['data']}")
                    else: payload.append(f"--- {n1} ---"); payload.extend(d1['data'])
                    
                    if d2['type']=='text': payload.append(f"--- {n2} ---\n{d2['data']}")
                    else: payload.append(f"--- {n2} ---"); payload.extend(d2['data'])

                    secoes_str = "\n".join([f"- {s}" for s in lista_secoes])
                    
                    prompt = f"""
                    Atue como Auditor Farmacêutico RÍGIDO (ANVISA).
                    DOCUMENTOS: 1. {n1} (Ref) | 2. {n2} (Alvo)
                    SEÇÕES ({nome_tipo}):
                    {secoes_str}

                    === REGRA: TEXTO LIMPO ===
                    1. Copie APENAS o parágrafo.
                    2. REMOVA títulos das seções.
                    3. DELETE repetições de cabeçalho.

                    === REGRA: COMPARAÇÃO ===
                    - Divergências de sentido: <mark class='diff'>
                    - Erros português: <mark class='ort'>
                    - Dizeres Legais/Composição: Apenas transcreva.

                    === DATA ANVISA ===
                    - Em DIZERES LEGAIS, procure "Aprovado em dd/mm/aaaa". Use <mark class='anvisa'>data</mark>.

                    JSON: {{ "METADADOS": {{ "score": 0-100, "datas": [] }}, "SECOES": [ {{ "titulo": "...", "ref": "...", "bel": "...", "status": "CONFORME|DIVERGENTE|FALTANTE" }} ] }}
                    """

                    # Safety settings locais para garantir
                    response = model_instance.generate_content(
                        [prompt] + payload,
                        generation_config={"response_mime_type": "application/json"},
                         safety_settings={
                            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                        }
                    )
                    
                    if hasattr(response.candidates[0], 'finish_reason') and response.candidates[0].finish_reason == 4:
                        st.error("⚠️ Bloqueio de Copyright. Tente enviar apenas texto.")
                    else:
                        data = extract_json(response.text)
                        if not data: st.error("Erro no JSON da IA.")
                        else:
                            meta = data.get("METADADOS", {})
                            m1, m2, m3 = st.columns(3)
                            m1.metric("Score", f"{meta.get('score', 0)}%")
                            m2.metric("Seções", len(data.get("SECOES", [])))
                            m3.metric("Datas", ", ".join(meta.get("datas", [])) or "--")
                            st.divider()
                            
                            for sec in data.get("SECOES", []):
                                stt = sec.get('status', 'N/A')
                                tit = sec.get('titulo', '').upper()
                                icon = "✅"
                                if "DIVERGENTE" in stt: icon = "❌"
                                elif "FALTANTE" in stt: icon = "🚨"
                                if any(x in tit for x in SECOES_SEM_DIVERGENCIA): icon = "👁️"
                                
                                with st.expander(f"{icon} {tit} — {stt}"):
                                    ca, cb = st.columns(2)
                                    ca.markdown(f"**{n1}**"); ca.markdown(f"<div style='background:#f9f9f9;padding:10px;'>{sec.get('ref','')}</div>", unsafe_allow_html=True)
                                    cb.markdown(f"**{n2}**"); cb.markdown(f"<div style='background:#f0fff4;padding:10px;'>{sec.get('bel','')}</div>", unsafe_allow_html=True)

                except Exception as e: st.error(f"Erro: {e}")
