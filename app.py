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

# ----------------- ESTILOS CSS -----------------
st.markdown("""
<style>
    header[data-testid="stHeader"] { display: none !important; }
    .main .block-container { padding-top: 20px !important; }
    .main { background-color: #f4f6f8; }
    h1, h2, h3 { color: #2c3e50; font-family: 'Segoe UI', Tahoma, sans-serif; }
    .stCard {
        background-color: white; padding: 25px; border-radius: 15px;
        box-shadow: 0 10px 20px rgba(0,0,0,0.05); margin-bottom: 25px; border: 1px solid #e1e4e8;
    }
    .highlight-yellow { background-color: #fff3cd; color: #856404; padding: 0 4px; border-radius: 4px; }
    .highlight-pink { background-color: #f8d7da; color: #721c24; padding: 0 4px; border-radius: 4px; }
    .highlight-blue { background-color: #cff4fc; color: #055160; padding: 0 4px; border-radius: 4px; }
    .stButton>button { width: 100%; background-color: #55a68e; color: white; font-weight: bold; height: 55px; border-radius: 10px; border:none; }
    .stButton>button:hover { background-color: #448c75; }
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

# ----------------- FUNÇÕES DE BACKEND -----------------

def get_gemini_model():
    # SÓ busca dos secrets. Não tem mais chave fixa no código.
    api_key = None
    try:
        api_key = st.secrets["GEMINI_API_KEY"]
    except:
        pass # Vai tratar abaixo

    if not api_key:
        return None, "Chave API não configurada nos Secrets"

    genai.configure(api_key=api_key)
    
    # Tenta conectar nos modelos 
    modelos = [
        'models/gemini-1.5-pro',
        'models/gemini-1.5-flash',
        'models/gemini-2.0-flash-exp'
    ]
    
    for m in modelos:
        try:
            return genai.GenerativeModel(m), m
        except: continue
        
    return genai.GenerativeModel('models/gemini-1.5-flash'), "Fallback (Flash)"

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
            images = []
            limit_pages = min(12, len(doc)) 
            
            for i in range(limit_pages):
                page = doc[i]
                pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0)) 
                try:
                    img_byte_arr = io.BytesIO(pix.tobytes("jpeg", jpg_quality=90))
                except:
                    img_byte_arr = io.BytesIO(pix.tobytes("png"))
                images.append(Image.open(img_byte_arr))
            
            doc.close()
            gc.collect()
            return {"type": "images", "data": images}
    except Exception as e:
        st.error(f"Erro ao processar arquivo: {e}")
        return None
    return None

def clean_json_response(text):
    text = text.replace("```json", "").replace("```", "").strip()
    text = re.sub(r'//.*', '', text) 
    return json.loads(text) if text else None

# ----------------- INTERFACE -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=80)
    st.title("Validador de Bulas")
    
    model, model_name = get_gemini_model()
    
    if model: 
        st.success(f"✅ Conectado: {model_name.replace('models/', '')}")
    else:
        st.error("❌ Erro: Chave não encontrada")
        st.caption("Verifique se a chave está nos Secrets do Streamlit.")
        
    st.divider()
    pagina = st.radio("Navegação:", ["🏠 Início", "💊 Ref x BELFAR", "📋 Conferência MKT", "🎨 Gráfica x Arte"])

# ----------------- PÁGINAS -----------------
if pagina == "🏠 Início":
    st.markdown("<h1 style='text-align:center; color:#55a68e'>Validador Inteligente</h1>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    c1.info("**💊 Ref x Belfar**\n\nAnalisa conformidade técnica e datas.")
    c2.info("**📋 Conferência MKT**\n\nValida layout e textos obrigatórios.")
    c3.info("**🎨 Gráfica x Arte**\n\nAuditoria visual (arquivos em curva).")

else:
    st.header(pagina)
    lista_secoes = SECOES_PACIENTE
    label_box1, label_box2 = "Arquivo 1", "Arquivo 2"
    
    if pagina == "💊 Ref x BELFAR":
        label_box1, label_box2 = "Referência (Anvisa)", "BELFAR (Candidato)"
        if st.radio("Tipo:", ["Paciente", "Profissional"], horizontal=True) == "Profissional":
            lista_secoes = SECOES_PROFISSIONAL

    elif pagina == "📋 Conferência MKT":
        label_box1, label_box2 = "Texto Aprovado", "PDF Marketing"

    elif pagina == "🎨 Gráfica x Arte":
        label_box1, label_box2 = "Arte Final", "Prova Gráfica"

    st.divider()
    c1, c2 = st.columns(2)
    f1 = c1.file_uploader(label_box1, type=["pdf", "docx"], key="f1")
    f2 = c2.file_uploader(label_box2, type=["pdf", "docx"], key="f2")

    if st.button("🚀 INICIAR AUDITORIA"):
        if not f1 or not f2:
            st.warning("Carregue os dois arquivos.")
        else:
            with st.spinner("🤖 Auditando documentos..."):
                try:
                    if not model: st.stop()
                    d1 = process_uploaded_file(f1)
                    d2 = process_uploaded_file(f2)
                    if not d1 or not d2: st.stop()

                    prompt = f"""
                    Você é um Auditor de Qualidade da Belfar (Uso Interno e Confidencial).
                    Sua função é verificar a conformidade regulatória entre os documentos anexos.
                    
                    TAREFA: Compare as seções listadas abaixo.
                    LISTA DE SEÇÕES: {lista_secoes}
                    
                    REGRAS CRÍTICAS:
                    1. Em "DIZERES LEGAIS", busque a data de aprovação da ANVISA no rodapé. Se achar, marque com <mark class='anvisa'>dd/mm/aaaa</mark>. Se não achar, não invente.
                    2. Aponte divergências de texto com <mark class='diff'>texto</mark>.
                    3. Aponte erros ortográficos com <mark class='ort'>erro</mark>.
                    4. Nas seções {SECOES_SEM_DIVERGENCIA}, apenas transcreva o texto sem marcar diferenças (somente erros de português).
                    
                    SAÍDA JSON OBRIGATÓRIA:
                    {{
                        "METADADOS": {{ "score": 0-100, "datas": [] }},
                        "SECOES": [ {{ "titulo": "...", "ref": "...", "bel": "...", "status": "CONFORME/DIVERGENTE" }} ]
                    }}
                    """
                    
                    payload = ["CONTEXTO: Auditoria interna de conformidade."]
                    if d1['type'] == 'text': payload.append(f"DOC 1:\n{d1['data']}")
                    else: payload.append("DOC 1 (Imagens):"); payload.extend(d1['data'])
                    
                    if d2['type'] == 'text': payload.append(f"DOC 2:\n{d2['data']}")
                    else: payload.append("DOC 2 (Imagens):"); payload.extend(d2['data'])

                    response = model.generate_content(
                        payload + [prompt],
                        generation_config={"response_mime_type": "application/json"},
                        safety_settings={
                            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                        }
                    )

                    if hasattr(response.candidates[0], 'finish_reason') and response.candidates[0].finish_reason == 4:
                        st.error("⚠️ **Bloqueio de Direitos Autorais**")
                        st.warning("O Google detectou que este texto é protegido e bloqueou a resposta.")
                    else:
                        data = clean_json_response(response.text)
                        if data:
                            meta = data.get("METADADOS", {})
                            k1, k2, k3 = st.columns(3)
                            k1.metric("Score", f"{meta.get('score')}%")
                            k2.metric("Seções", len(data.get("SECOES", [])))
                            k3.metric("Datas", ", ".join(meta.get("datas", [])) or "-")
                            
                            st.divider()
                            for sec in data.get("SECOES", []):
                                icon = "✅" if "CONFORME" in sec['status'] else "❌"
                                if any(s in sec['titulo'] for s in SECOES_SEM_DIVERGENCIA):
                                    icon = "👁️"
                                with st.expander(f"{icon} {sec['titulo']} - {sec['status']}"):
                                    ca, cb = st.columns(2)
                                    ca.markdown(f"**Referência:**<br>{sec.get('ref')}", unsafe_allow_html=True)
                                    cb.markdown(f"**Belfar:**<br>{sec.get('bel')}", unsafe_allow_html=True)
                        else:
                            st.error("Erro ao gerar JSON. Tente novamente.")

                except Exception as e:
                    st.error(f"Erro técnico: {e}")
