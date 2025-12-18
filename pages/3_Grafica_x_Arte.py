import streamlit as st
import google.generativeai as genai
from PIL import Image
import fitz  # PyMuPDF
import io
import time
from datetime import datetime

# ----------------- CONFIGURAÇÃO DA PÁGINA -----------------
st.set_page_config(page_title="Validador 2.0 Lite", layout="wide")

# CSS para os marca-textos (Amarelo, Vermelho, Azul)
st.markdown("""
<style>
    .highlight-yellow { background-color: #fff9c4; color: #000000; padding: 2px 5px; border-radius: 3px; border: 1px solid #fbc02d; }
    .highlight-red { background-color: #ffcdd2; color: #b71c1c; padding: 2px 5px; border-radius: 3px; border: 1px solid #b71c1c; font-weight: bold; }
    .highlight-blue { background-color: #bbdefb; color: #0d47a1; padding: 2px 5px; border-radius: 3px; border: 1px solid #1976d2; }
    .section-box { border: 1px solid #ddd; padding: 15px; border-radius: 5px; margin-bottom: 20px; background-color: #f9f9f9; }
    .report-title { color: #2e7d32; font-size: 20px; font-weight: bold; margin-bottom: 10px; }
    /* Estilo para o contador de cota */
    .quota-box { border: 2px solid #ff9800; padding: 10px; border-radius: 10px; background-color: #fff3e0; text-align: center; }
    .quota-number { font-size: 30px; font-weight: bold; color: #e65100; }
    .quota-label { font-size: 14px; color: #666; }
</style>
""", unsafe_allow_html=True)

# ----------------- GERENCIAMENTO DE COTA E ESTADO -----------------
COTA_DIARIA_PADRAO = 1500  # Limite padrão do Free Tier para Flash/Lite

if 'req_count' not in st.session_state:
    st.session_state.req_count = 0
if 'last_req_time' not in st.session_state:
    st.session_state.last_req_time = datetime.min

def update_quota_usage():
    """Atualiza o contador e gerencia delay para evitar erro 429"""
    now = datetime.now()
    time_diff = (now - st.session_state.last_req_time).total_seconds()
    
    # Delay de segurança (4 segundos entre chamadas)
    if time_diff < 4:
        time.sleep(4 - time_diff)
    
    st.session_state.req_count += 1
    st.session_state.last_req_time = datetime.now()

# ----------------- CONFIGURAÇÃO DO MODELO ESPECÍFICO -----------------
MODELO_ALVO = "gemini-2.0-flash-lite-preview-02-05"

def setup_specific_model():
    keys = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2")]
    valid_keys = [k for k in keys if k]

    if not valid_keys:
        return None, "Sem chaves configuradas."

    for api_key in valid_keys:
        try:
            genai.configure(api_key=api_key)
            # Tenta instanciar diretamente o modelo pedido
            model_test = genai.GenerativeModel(MODELO_ALVO)
            return api_key, None # Sucesso
        except Exception:
            continue
            
    return None, f"Não foi possível conectar ao modelo {MODELO_ALVO}."

# ----------------- BARRA LATERAL (CONTADOR) -----------------
with st.sidebar:
    st.header("⚙️ Configuração")
    
    found_key, err = setup_specific_model()
    
    if found_key:
        genai.configure(api_key=found_key)
        model = genai.GenerativeModel(MODELO_ALVO, generation_config={"temperature": 0.1})
        st.success(f"Conectado: `{MODELO_ALVO}`")
    else:
        st.error(f"Erro: {err}")
        st.stop()

    st.divider()
    
    # CÁLCULO DA COTA RESTANTE
    restante = COTA_DIARIA_PADRAO - st.session_state.req_count
    if restante < 0: restante = 0
    
    st.markdown(f"""
    <div class="quota-box">
        <div class="quota-label">COTA RESTANTE (HOJE)</div>
        <div class="quota-number">{restante}</div>
        <div style="font-size:12px; margin-top:5px">de {COTA_DIARIA_PADRAO} requisições</div>
    </div>
    """, unsafe_allow_html=True)
    
    st.info("Nota: Este contador reinicia se você atualizar a página (F5), pois a API não informa o uso histórico.")

# ----------------- UTILITÁRIOS DE IMAGEM -----------------
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

# ----------------- UI PRINCIPAL -----------------
st.title("💊 Validador Flash Lite 2.0")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📂 Arquivo ARTE (Original)", type=["pdf", "jpg", "png"], key="f1")
f2 = c2.file_uploader("📂 Arquivo GRÁFICA (Para Validar)", type=["pdf", "jpg", "png"], key="f2")

if st.button("🚀 Validar Agora"):
    if f1 and f2:
        update_quota_usage() # Desconta 1 da cota e força o refresh visual
        
        with st.spinner(f"Processando com {MODELO_ALVO}..."):
            imgs1 = pdf_to_images(f1) if f1.name.endswith(".pdf") else [Image.open(f1)]
            imgs2 = pdf_to_images(f2) if f2.name.endswith(".pdf") else [Image.open(f2)]
            
            prompt = f"""
            Você é um auditor de qualidade farmacêutica.
            Compare o CONJUNTO A (Imagens Originais) com o CONJUNTO B (Imagens da Gráfica).
            
            IMPORTANTE: Use OCR para ler textos em curvas. NÃO ALUCINE.
            
            Gere um relatório HTML separado por estas seções exatas:
            {SECOES_PACIENTE}
            
            REGRAS DE MARCAÇÃO (HTML):
            1. Divergência de conteúdo (texto extra/faltante): <span class="highlight-yellow">TEXTO DIVERGENTE</span>
            2. Erros de português/digitação: <span class="highlight-red">ERRO</span>
            3. Nos 'DIZERES LEGAIS', valide a data da Anvisa: <span class="highlight-blue">DATA/FRASE ANVISA</span>
            
            Formato de saída para cada seção:
            <div class="section-box">
               <div class="report-title">NOME_DA_SEÇÃO</div>
               <p>Texto comparado...</p>
            </div>
            """
            
            payload = [prompt, "--- CONJUNTO A ---"] + imgs1 + ["--- CONJUNTO B ---"] + imgs2
            
            try:
                resp = model.generate_content(payload)
                st.markdown(resp.text, unsafe_allow_html=True)
                st.success("Validação finalizada!")
            except Exception as e:
                st.error(f"Erro: {e}")
                if "429" in str(e): st.warning("Muitas requisições. Aguarde um pouco.")
    else:
        st.warning("Adicione os arquivos primeiro.")
