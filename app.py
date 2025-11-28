import streamlit as st
import fitz  # PyMuPDF
from groq import Groq
import base64

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Validador Belfar (Groq)", page_icon="💊", layout="wide")

# Estilos CSS
st.markdown("""
<style>
    .main-title {color: #f55036; font-weight: bold; text-align: center;}
    .stButton>button {width: 100%; background-color: #f55036; color: white; border: none;}
    .report-box {background-color: #f8f9fa; padding: 20px; border-radius: 10px; border: 1px solid #ddd;}
</style>
""", unsafe_allow_html=True)

# --- FUNÇÕES ---

def pdf_to_base64(uploaded_file):
    """Converte PDF para imagens em Base64 (formato que a Groq aceita)"""
    if not uploaded_file: return []
    try:
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        images_b64 = []
        for page in doc:
            # Baixa resolução (matrix=1.0) para ser rápido e aceito pela API
            pix = page.get_pixmap(matrix=fitz.Matrix(1.0, 1.0))
            img_bytes = pix.tobytes("jpeg")
            base64_str = base64.b64encode(img_bytes).decode('utf-8')
            images_b64.append(f"data:image/jpeg;base64,{base64_str}")
        return images_b64
    except Exception as e:
        st.error(f"Erro ao ler PDF: {e}")
        return []

def call_groq(api_key, system_msg, user_msg, images):
    if not api_key:
        st.error("⚠️ Configure a API Key na barra lateral.")
        return None
    
    client = Groq(api_key=api_key)
    
    # Monta a mensagem (Texto + Imagens)
    content = [{"type": "text", "text": user_msg}]
    
    # Adiciona as imagens ao prompt
    for img_url in images:
        content.append({
            "type": "image_url",
            "image_url": {"url": img_url}
        })
        
    try:
        with st.spinner("⚡ A Groq (Llama 3.2) está analisando..."):
            completion = client.chat.completions.create(
                model="llama-3.2-11b-vision-preview", # Modelo gratuito com visão
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": content}
                ],
                temperature=0.1,
                max_tokens=2048
            )
            return completion.choices[0].message.content
    except Exception as e:
        st.error(f"Erro na API Groq: {str(e)}")
        return None

# --- BARRA LATERAL (MENU) ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=50)
    st.title("Validador (Groq)")
    
    # Input da Chave
    st.markdown("### 🔑 Configuração")
    api_key = st.text_input("Groq API Key (gsk_...)", type="password")
    st.caption("[Criar chave grátis aqui](https://console.groq.com/keys)")
    
    st.markdown("---")
    
    # Seleção de Modo
    modo = st.selectbox("Selecione o Cenário:", [
        "1_Med._Referencia_x_BELFAR",
        "2_Conferencia_MKT",
        "3_Grafica_x_Arte"
    ])
    
    st.markdown("---")
    
    # Inputs Dinâmicos
    inputs_ok = False
    
    if modo == "1_Med._Referencia_x_BELFAR":
        st.info("Comparação Técnica")
        f1 = st.file_uploader("📂 Bula Referência", type="pdf")
        f2 = st.file_uploader("📂 Bula Belfar", type="pdf")
        if f1 and f2: inputs_ok = True

    elif modo == "2_Conferencia_MKT":
        st.info("Checklist Obrigatório")
        f1 = st.file_uploader("📂 Bula MKT", type="pdf")
        checklist = st.text_area("Itens:", "VENDA SOB PRESCRIÇÃO\nLogo Belfar\nFarm. Resp.\nSAC")
        if f1: inputs_ok = True

    elif modo == "3_Grafica_x_Arte":
        st.info("Comparação Visual")
        f1 = st.file_uploader("📂 Arte Final", type="pdf")
        f2 = st.file_uploader("📂 Prova Gráfica", type="pdf")
        if f1 and f2: inputs_ok = True

    st.markdown("---")
    btn_run = st.button("🚀 INICIAR VALIDAÇÃO", disabled=not inputs_ok)

# --- TELA PRINCIPAL ---

st.markdown(f'<h1 class="main-title">{modo.replace("_", " ")}</h1>', unsafe_allow_html=True)

if btn_run:
    # 1. TEXTO TÉCNICO
    if modo == "1_Med._Referencia_x_BELFAR":
        f1.seek(0); f2.seek(0)
        imgs1 = pdf_to_base64(f1)
        imgs2 = pdf_to_base64(f2)
        
        prompt = """
        Atue como Especialista Regulatório.
        As primeiras imagens são a REFERÊNCIA. As últimas são a BELFAR.
        Compare APENAS o texto técnico (Posologia, Contraindicações, Composição).
        Ignore diferenças de formatação.
        Liste divergências ou confirme a conformidade.
        """
        # Limite de segurança: Groq aceita poucas imagens de uma vez, mandamos as primeiras de cada
        res = call_groq(api_key, "Analista Farma", prompt, imgs1[:2] + imgs2[:2]) 
        if res: st.markdown(f'<div class="report-box">{res}</div>', unsafe_allow_html=True)

    # 2. CHECKLIST MKT
    elif modo == "2_Conferencia_MKT":
        f1.seek(0)
        imgs1 = pdf_to_base64(f1)
        prompt = f"Verifique visualmente se estes itens existem na imagem: {checklist}. Responda apenas [OK] ou [AUSENTE]."
        res = call_groq(api_key, "Auditor MKT", prompt, imgs1[:3])
        if res: st.markdown(f'<div class="report-box">{res}</div>', unsafe_allow_html=True)

    # 3. VISUAL GRÁFICO
    elif modo == "3_Grafica_x_Arte":
        f1.seek(0); f2.seek(0)
        imgs1 = pdf_to_base64(f1)
        imgs2 = pdf_to_base64(f2)
        prompt = "Compare visualmente a Arte (primeiras img) vs Prova (últimas img). Procure defeitos de impressão, cortes ou manchas."
        res = call_groq(api_key, "Inspetor Gráfico", prompt, imgs1[:1] + imgs2[:1])
        if res: st.markdown(f'<div class="report-box">{res}</div>', unsafe_allow_html=True)
