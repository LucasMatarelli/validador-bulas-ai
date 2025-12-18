import streamlit as st
import google.generativeai as genai
from google.api_core import exceptions
from PIL import Image
import fitz  # PyMuPDF
import io
import time
import re

# ----------------- CONFIGURAÇÃO -----------------
st.set_page_config(page_title="Validador Inteligente", layout="wide")

st.markdown("""
<style>
    .highlight-yellow { background-color: #fff9c4; color: #000000; padding: 2px 5px; border-radius: 3px; border: 1px solid #fbc02d; }
    .highlight-red { background-color: #ffcdd2; color: #b71c1c; padding: 2px 5px; border-radius: 3px; border: 1px solid #b71c1c; font-weight: bold; }
    .highlight-blue { background-color: #bbdefb; color: #0d47a1; padding: 2px 5px; border-radius: 3px; border: 1px solid #1976d2; }
    .section-box { border: 1px solid #ddd; padding: 15px; border-radius: 5px; margin-bottom: 20px; background-color: #f9f9f9; }
    .status-box { padding: 10px; border-radius: 5px; margin-bottom: 10px; font-weight: bold; text-align: center;}
    .status-ok { background-color: #e8f5e9; color: #2e7d32; border: 1px solid #c8e6c9; }
    .status-wait { background-color: #fff3e0; color: #ef6c00; border: 1px solid #ffe0b2; }
</style>
""", unsafe_allow_html=True)

# ----------------- MODELO -----------------
MODELO_ALVO = "gemini-2.0-flash-lite-preview-02-05"

def setup_model():
    keys = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2")]
    valid_keys = [k for k in keys if k]
    if not valid_keys: return None
    
    # Retorna a primeira chave válida
    return valid_keys[0]

# ----------------- FUNÇÃO DE RETRY INTELIGENTE -----------------
def generate_with_retry(model, payload, max_retries=3):
    """
    Tenta gerar conteúdo. Se der erro 429 (Cota), espera o tempo necessário e tenta de novo.
    """
    for attempt in range(max_retries):
        try:
            return model.generate_content(payload)
        
        except exceptions.ResourceExhausted as e:
            # Tenta ler o tempo de espera da mensagem de erro
            error_msg = str(e)
            wait_time = 60 # Padrão 60s se não achar
            
            # Procura por "retry in X s" ou similar
            # O erro da sua imagem: "retry in 50.483399551s"
            match = re.search(r"retry.*in\s+([\d\.]+)", error_msg)
            if match:
                wait_time = float(match.group(1)) + 2 # +2s de gordura
            
            st.warning(f"⚠️ Cota momentânea cheia (Token Limit).")
            
            # Barra de progresso visual para espera
            progress_text = "Aguardando liberação da API..."
            my_bar = st.progress(0, text=progress_text)
            
            for percent_complete in range(100):
                time.sleep(wait_time / 100)
                my_bar.progress(percent_complete + 1, text=f"⏳ Resfriando API: {int(wait_time * (1 - percent_complete/100))}s restantes...")
            
            my_bar.empty()
            st.info("🔄 Tentando novamente agora...")
            # O loop continua e tenta de novo
            
        except Exception as e:
            st.error(f"Erro fatal não relacionado à cota: {e}")
            return None
            
    st.error("❌ Falha após várias tentativas. O arquivo pode ser muito grande para o limite gratuito.")
    return None

# ----------------- UI -----------------
with st.sidebar:
    st.header("⚙️ Status do Sistema")
    api_key = setup_model()
    
    if api_key:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(MODELO_ALVO, generation_config={"temperature": 0.1})
        st.markdown(f'<div class="status-box status-ok">Conectado: {MODELO_ALVO}</div>', unsafe_allow_html=True)
    else:
        st.error("Sem chave API configurada.")
        st.stop()
        
    st.info("""
    **Sobre a Cota:**
    Como a API não informa o saldo, este sistema agora detecta automaticamente quando o Google bloqueia (Erro 429) e cria uma fila de espera inteligente.
    """)

st.title("🛡️ Validador (Com Retry Automático)")

# ----------------- PROCESSAMENTO -----------------
def pdf_to_images(uploaded_file):
    try:
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        images = []
        for page in doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
            images.append(Image.open(io.BytesIO(pix.tobytes("jpeg"))))
        return images
    except: return []

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

c1, c2 = st.columns(2)
f1 = c1.file_uploader("Arte", type=["pdf", "jpg", "png"], key="f1")
f2 = c2.file_uploader("Gráfica", type=["pdf", "jpg", "png"], key="f2")

if st.button("🚀 Validar"):
    if f1 and f2:
        with st.spinner("Processando imagens..."):
            imgs1 = pdf_to_images(f1) if f1.name.endswith(".pdf") else [Image.open(f1)]
            imgs2 = pdf_to_images(f2) if f2.name.endswith(".pdf") else [Image.open(f2)]
            
            prompt = f"""
            Atue como auditor de qualidade farmacêutica (Belfar).
            Compare as imagens ARTE vs GRÁFICA.
            Use OCR para ler tudo.
            
            Seções obrigatórias: {SECOES_PACIENTE}
            
            Use HTML:
            - Divergência: <span class="highlight-yellow">TEXTO</span>
            - Erro PT: <span class="highlight-red">TEXTO</span>
            - Data Anvisa (Dizeres Legais): <span class="highlight-blue">DATA</span>
            """
            
            payload = [prompt, "--- ARTE ---"] + imgs1 + ["--- GRAFICA ---"] + imgs2
            
            # CHAMA A FUNÇÃO DE RETRY
            response = generate_with_retry(model, payload)
            
            if response:
                st.markdown(response.text, unsafe_allow_html=True)
                st.success("Concluído!")
    else:
        st.warning("Anexe os arquivos.")
