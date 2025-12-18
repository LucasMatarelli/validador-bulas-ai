import streamlit as st
import google.generativeai as genai
from google.api_core import exceptions
from PIL import Image
import fitz  # PyMuPDF
import io
import time
import re

# ----------------- CONFIGURAÇÃO -----------------
st.set_page_config(page_title="Validador V2 (No-Lite)", layout="wide")

st.markdown("""
<style>
    .highlight-yellow { background-color: #fff9c4; color: #000000; padding: 2px 5px; border-radius: 3px; border: 1px solid #fbc02d; }
    .highlight-red { background-color: #ffcdd2; color: #b71c1c; padding: 2px 5px; border-radius: 3px; border: 1px solid #b71c1c; font-weight: bold; }
    .highlight-blue { background-color: #bbdefb; color: #0d47a1; padding: 2px 5px; border-radius: 3px; border: 1px solid #1976d2; }
    .status-ok { background-color: #e8f5e9; color: #2e7d32; padding: 10px; border-radius: 5px; border: 1px solid #c8e6c9; text-align: center; font-weight: bold;}
    .status-err { background-color: #ffebee; color: #c62828; padding: 10px; border-radius: 5px; border: 1px solid #ef9a9a; text-align: center;}
</style>
""", unsafe_allow_html=True)

# ----------------- CAÇADOR DE MODELOS V2 -----------------
def get_best_v2_model():
    """
    Busca qualquer modelo que tenha '2.0' no nome.
    Ignora 1.0 e 1.5.
    Tenta fugir do 'Lite' se houver outro disponível.
    """
    keys = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2")]
    valid_keys = [k for k in keys if k]

    if not valid_keys:
        return None, None, "Sem chaves API."

    for api_key in valid_keys:
        try:
            genai.configure(api_key=api_key)
            models = list(genai.list_models())
            
            # Filtra apenas modelos 2.0 que geram conteúdo
            candidatos = [
                m.name for m in models 
                if "generateContent" in m.supported_generation_methods 
                and "2.0" in m.name
            ]
            
            if not candidatos:
                continue # Tenta a próxima chave
                
            # ORDENAÇÃO DE PREFERÊNCIA:
            # 1. Tenta o Flash Experimental (Padrão) - Melhor cota que o Lite
            for nome in candidatos:
                if "flash-exp" in nome and "lite" not in nome:
                    return api_key, nome, None
            
            # 2. Tenta o Pro Experimental (Se tiver acesso)
            for nome in candidatos:
                if "pro-exp" in nome:
                    return api_key, nome, None
            
            # 3. Se só tiver o Lite ou outros, pega o primeiro que achar da lista V2
            return api_key, candidatos[0], None

        except Exception as e:
            continue
            
    return None, None, "Nenhum modelo 2.0 encontrado na sua conta."

# ----------------- FUNÇÃO DE RETRY (COM BACKOFF MAIOR) -----------------
def generate_with_retry(model, payload, max_retries=3):
    for attempt in range(max_retries):
        try:
            return model.generate_content(payload)
        
        except exceptions.ResourceExhausted as e:
            error_msg = str(e)
            wait_time = 60 # Padrão
            
            # Tenta ler o tempo sugerido pelo erro
            match = re.search(r"retry.*in\s+([\d\.]+)", error_msg)
            if match:
                # Se o Google pedir X segundos, esperamos X + 5 de segurança
                wait_time = float(match.group(1)) + 5
            
            st.warning(f"⚠️ Limite de tokens atingido (Tentativa {attempt+1}/{max_retries}).")
            
            # Barra de progresso
            my_bar = st.progress(0, text="Resfriando API...")
            step = 100
            for i in range(step):
                time.sleep(wait_time / step)
                my_bar.progress(i + 1, text=f"⏳ Aguardando liberação de cota: {int(wait_time * (1 - i/step))}s...")
            
            my_bar.empty()
            # Tenta novamente
            
        except Exception as e:
            st.error(f"Erro inesperado: {e}")
            return None
            
    st.error("❌ Não foi possível processar. O arquivo pode ser muito pesado para a cota atual deste modelo.")
    return None

# ----------------- UI & SETUP -----------------
with st.sidebar:
    st.header("⚙️ Modelo Selecionado")
    
    key, model_name, err = get_best_v2_model()
    
    if model_name:
        genai.configure(api_key=key)
        model = genai.GenerativeModel(model_name, generation_config={"temperature": 0.1})
        st.markdown(f'<div class="status-ok">✅ Usando:<br>{model_name}</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="status-err">{err}</div>', unsafe_allow_html=True)
        st.stop()

st.title("🛡️ Validador (Família Gemini 2.0)")

# ----------------- UTILITÁRIOS -----------------
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

# ----------------- CORPO PRINCIPAL -----------------
c1, c2 = st.columns(2)
f1 = c1.file_uploader("Arte", type=["pdf", "jpg", "png"], key="f1")
f2 = c2.file_uploader("Gráfica", type=["pdf", "jpg", "png"], key="f2")

if st.button("🚀 Validar (Forçar V2)"):
    if f1 and f2:
        with st.spinner(f"Lendo arquivos com {model_name}..."):
            imgs1 = pdf_to_images(f1) if f1.name.endswith(".pdf") else [Image.open(f1)]
            imgs2 = pdf_to_images(f2) if f2.name.endswith(".pdf") else [Image.open(f2)]
            
            prompt = f"""
            Auditor Farmacêutico (Belfar). Análise Visual + OCR.
            Compare ARTE vs GRÁFICA.
            
            Seções obrigatórias: {SECOES_PACIENTE}
            
            HTML Obrigatório:
            - Divergência: <span class="highlight-yellow">TEXTO</span>
            - Erro PT: <span class="highlight-red">TEXTO</span>
            - Dizeres Legais (Data Anvisa): <span class="highlight-blue">DATA</span>
            """
            
            payload = [prompt, "--- ARTE ---"] + imgs1 + ["--- GRAFICA ---"] + imgs2
            
            response = generate_with_retry(model, payload)
            
            if response:
                st.markdown(response.text, unsafe_allow_html=True)
                st.success("Processo finalizado.")
    else:
        st.warning("Faltam arquivos.")
