import streamlit as st
import google.generativeai as genai
from google.api_core import exceptions
from PIL import Image
import fitz  # PyMuPDF
import io
import time
import re

# ----------------- CONFIGURAÇÃO DA PÁGINA -----------------
st.set_page_config(page_title="Validador Multi-Modelos", layout="wide")

st.markdown("""
<style>
    .highlight-yellow { background-color: #fff9c4; color: #000000; padding: 2px 5px; border-radius: 3px; border: 1px solid #fbc02d; }
    .highlight-red { background-color: #ffcdd2; color: #b71c1c; padding: 2px 5px; border-radius: 3px; border: 1px solid #b71c1c; font-weight: bold; }
    .highlight-blue { background-color: #bbdefb; color: #0d47a1; padding: 2px 5px; border-radius: 3px; border: 1px solid #1976d2; }
    .status-ok { background-color: #e8f5e9; color: #2e7d32; padding: 10px; border-radius: 5px; border: 1px solid #c8e6c9; font-weight: bold; }
    .status-warning { background-color: #fff3e0; color: #ef6c00; padding: 10px; border-radius: 5px; border: 1px solid #ffe0b2; }
</style>
""", unsafe_allow_html=True)

# ----------------- GERENCIAMENTO DE CHAVES E MODELOS -----------------
def get_available_models():
    """
    Lista TODOS os modelos disponíveis na chave que suportam geração de conteúdo.
    Não filtra nada, para dar opção total ao usuário.
    """
    keys = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2")]
    valid_keys = [k for k in keys if k]

    if not valid_keys:
        return None, [], "Sem chaves configuradas."

    for api_key in valid_keys:
        try:
            genai.configure(api_key=api_key)
            models = list(genai.list_models())
            
            # Pega tudo que gera conteúdo (texto/imagem)
            model_names = [
                m.name for m in models 
                if "generateContent" in m.supported_generation_methods
            ]
            
            # Ordena para facilitar (coloca os experimentais no topo se houver)
            model_names.sort(key=lambda x: "exp" not in x)
            
            if model_names:
                return api_key, model_names, None
                
        except Exception as e:
            continue
            
    return None, [], "Não foi possível listar modelos com suas chaves."

# ----------------- FUNÇÃO DE RETRY (SEGURANÇA CONTRA ERRO 429) -----------------
def generate_with_retry(model, payload, max_retries=3):
    """
    Se der erro de cota, espera e tenta de novo.
    """
    for attempt in range(max_retries):
        try:
            return model.generate_content(payload)
        
        except exceptions.ResourceExhausted as e:
            error_msg = str(e)
            wait_time = 60 # Tempo padrão se não conseguir ler do erro
            
            # Tenta ler o tempo exato que o Google pediu
            match = re.search(r"retry.*in\s+([\d\.]+)", error_msg)
            if match:
                wait_time = float(match.group(1)) + 5 # +5s de margem
            
            st.warning(f"⚠️ Modelo sobrecarregado (Erro 429). Aguardando {int(wait_time)}s para tentar de novo...")
            
            # Barra de progresso visual
            my_bar = st.progress(0, text="Resfriando API...")
            step = 100
            for i in range(step):
                time.sleep(wait_time / step)
                my_bar.progress(i + 1)
            
            my_bar.empty()
            # Tenta novamente no próximo loop
            
        except Exception as e:
            st.error(f"Erro no modelo: {e}")
            return None
            
    st.error("❌ O modelo continua rejeitando as requisições. Tente trocar de modelo na barra lateral.")
    return None

# ----------------- SIDEBAR: SELETOR MANUAL -----------------
with st.sidebar:
    st.header("🎛️ Painel de Controle")
    
    key, options, err = get_available_models()
    
    if key and options:
        genai.configure(api_key=key)
        
        st.info("Como você excluiu as famílias principais, selecione abaixo qualquer outro disponível na sua conta:")
        
        # O usuário escolhe EXATAMENTE qual quer usar
        selected_model_name = st.selectbox(
            "Escolha o Modelo:", 
            options, 
            index=0
        )
        
        # Configura o modelo escolhido
        model = genai.GenerativeModel(selected_model_name, generation_config={"temperature": 0.1})
        
        st.markdown(f'<div class="status-ok">✅ Conectado:<br>{selected_model_name}</div>', unsafe_allow_html=True)
        st.warning("Dica: Modelos com 'exp' (Experimental) costumam ter cotas menos congestionadas.")
        
    else:
        st.error(f"Erro: {err}")
        st.stop()

# ----------------- LÓGICA DE PROCESSAMENTO -----------------
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
st.title("🛡️ Validador Flexível (Seletor Manual)")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("Arte", type=["pdf", "jpg", "png"], key="f1")
f2 = c2.file_uploader("Gráfica", type=["pdf", "jpg", "png"], key="f2")

if st.button("🚀 Validar com Modelo Selecionado"):
    if f1 and f2:
        with st.spinner(f"Enviando para o modelo {selected_model_name}..."):
            imgs1 = pdf_to_images(f1) if f1.name.endswith(".pdf") else [Image.open(f1)]
            imgs2 = pdf_to_images(f2) if f2.name.endswith(".pdf") else [Image.open(f2)]
            
            prompt = f"""
            Auditor de Bula Farmacêutica.
            Compare visualmente o CONJUNTO A (Arte) com o CONJUNTO B (Gráfica).
            Use OCR para ler tudo.
            
            Separe pelas seções: {SECOES_PACIENTE}
            
            Use HTML estrito para retorno:
            - Divergências de texto: <span class="highlight-yellow">TEXTO</span>
            - Erros de português: <span class="highlight-red">TEXTO</span>
            - Data Anvisa (em Dizeres Legais): <span class="highlight-blue">DATA</span>
            """
            
            payload = [prompt, "--- ARTE ---"] + imgs1 + ["--- GRAFICA ---"] + imgs2
            
            # Chama com Retry
            response = generate_with_retry(model, payload)
            
            if response:
                st.markdown(response.text, unsafe_allow_html=True)
                st.success("Análise completa.")
    else:
        st.warning("Envie os arquivos primeiro.")
