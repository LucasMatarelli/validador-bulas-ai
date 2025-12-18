import streamlit as st
import google.generativeai as genai
from google.api_core import exceptions
from PIL import Image
import fitz  # PyMuPDF
import io
import time
import re

# ----------------- CONFIGURAÇÃO DA PÁGINA -----------------
st.set_page_config(page_title="Validador (Flash Latest)", layout="wide")

st.markdown("""
<style>
    .highlight-yellow { background-color: #fff9c4; color: #000000; padding: 2px 5px; border-radius: 3px; border: 1px solid #fbc02d; }
    .highlight-red { background-color: #ffcdd2; color: #b71c1c; padding: 2px 5px; border-radius: 3px; border: 1px solid #b71c1c; font-weight: bold; }
    .highlight-blue { background-color: #bbdefb; color: #0d47a1; padding: 2px 5px; border-radius: 3px; border: 1px solid #1976d2; }
    .section-box { border: 1px solid #ddd; padding: 15px; border-radius: 5px; margin-bottom: 20px; background-color: #f9f9f9; }
    .status-ok { background-color: #e8f5e9; color: #2e7d32; padding: 10px; border-radius: 5px; border: 1px solid #c8e6c9; font-weight: bold; text-align: center; }
</style>
""", unsafe_allow_html=True)

# ----------------- DEFINIÇÃO DO MODELO (EXATO) -----------------
# Usando exatamente a string solicitada
MODELO_FIXO = "models/gemini-flash-latest"

def setup_model():
    keys = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2")]
    valid_keys = [k for k in keys if k]

    if not valid_keys:
        return None, "Sem chaves configuradas."

    for api_key in valid_keys:
        try:
            genai.configure(api_key=api_key)
            # Teste de conexão com o nome exato
            model = genai.GenerativeModel(MODELO_FIXO)
            return api_key, None
        except Exception as e:
            # Se der erro no nome do modelo, tenta continuar para a próxima chave
            continue
    
    return None, f"Erro: O modelo '{MODELO_FIXO}' não foi reconhecido ou a chave falhou."

# ----------------- FUNÇÃO DE RETRY (ANTI-429) -----------------
def generate_with_retry(model, payload, max_retries=3):
    """
    Tenta executar a chamada. Se der erro de cota (429), espera e tenta de novo.
    """
    for attempt in range(max_retries):
        try:
            return model.generate_content(payload)
        
        except exceptions.ResourceExhausted as e:
            error_msg = str(e)
            wait_time = 30 # Tempo base
            
            # Tenta ler o tempo que o Google pediu
            match = re.search(r"retry.*in\s+([\d\.]+)", error_msg)
            if match:
                wait_time = float(match.group(1)) + 5
            
            st.warning(f"⚠️ Cota atingida. Aguardando {int(wait_time)}s para retomar...")
            
            # Barra de progresso para o usuário ver que não travou
            my_bar = st.progress(0, text="Aguardando liberação...")
            step = 100
            for i in range(step):
                time.sleep(wait_time / step)
                my_bar.progress(i + 1)
            my_bar.empty()
            
        except Exception as e:
            st.error(f"Erro técnico: {e}")
            return None
            
    st.error("❌ Falha na conexão após várias tentativas.")
    return None

# ----------------- SIDEBAR -----------------
with st.sidebar:
    st.header("⚙️ Configuração")
    
    key, err = setup_model()
    
    if key:
        genai.configure(api_key=key)
        # Temperatura baixa para evitar alucinações no OCR
        model = genai.GenerativeModel(MODELO_FIXO, generation_config={"temperature": 0.1})
        st.markdown(f'<div class="status-ok">Conectado:<br>{MODELO_FIXO}</div>', unsafe_allow_html=True)
    else:
        st.error(f"{err}")
        st.stop()

# ----------------- PROCESSAMENTO DE IMAGENS -----------------
def pdf_to_images(uploaded_file):
    try:
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        images = []
        for page in doc:
            # Zoom 2.0 melhora a leitura de letras pequenas
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

# ----------------- UI PRINCIPAL -----------------
st.title("💊 Validador (Modelo Latest)")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("Arte (Original)", type=["pdf", "jpg", "png"], key="f1")
f2 = c2.file_uploader("Gráfica (Prova)", type=["pdf", "jpg", "png"], key="f2")

if st.button("🚀 Iniciar Comparação"):
    if f1 and f2:
        with st.spinner(f"Enviando para {MODELO_FIXO}..."):
            imgs1 = pdf_to_images(f1) if f1.name.endswith(".pdf") else [Image.open(f1)]
            imgs2 = pdf_to_images(f2) if f2.name.endswith(".pdf") else [Image.open(f2)]
            
            prompt = f"""
            Você é um auditor de qualidade na farmacêutica Belfar.
            Compare visualmente o CONJUNTO A (Arte) com o CONJUNTO B (Gráfica).
            
            ATENÇÃO:
            1. Use OCR para extrair todo o texto, mesmo que esteja em curvas/vetores.
            2. Não alucine texto que não existe.
            3. Verifique todas as seções.
            
            Gere o relatório em HTML, separado por estas seções exatas:
            {SECOES_PACIENTE}
            
            REGRAS DE FORMATAÇÃO (HTML):
            - Divergências de texto (texto a mais ou a menos): <span class="highlight-yellow">TEXTO AQUI</span>
            - Erros de português/digitação: <span class="highlight-red">TEXTO AQUI</span>
            - Na seção 'DIZERES LEGAIS', valide a data da Anvisa: <span class="highlight-blue">Esta bula foi atualizada... (DATA)</span>
            
            Para cada seção, use este bloco:
            <div class="section-box">
                <b>NOME DA SEÇÃO</b><br>
                <p>Texto comparado...</p>
            </div>
            """
            
            payload = [prompt, "--- CONJUNTO A ---"] + imgs1 + ["--- CONJUNTO B ---"] + imgs2
            
            response = generate_with_retry(model, payload)
            
            if response:
                st.markdown(response.text, unsafe_allow_html=True)
                st.success("Processamento concluído.")
    else:
        st.warning("Por favor, faça upload dos dois arquivos.")
