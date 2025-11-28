import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
from PIL import Image
import io

# --- CONFIGURAÇÃO DA PÁGINA (WIDE) ---
st.set_page_config(page_title="Validador Belfar", page_icon="💊", layout="wide")

# Estilo para ficar mais parecido com sistemas corporativos
st.markdown("""
<style>
    .report-view {
        background-color: #f8f9fa; 
        padding: 20px; 
        border-radius: 10px; 
        border: 1px solid #ddd;
        font-family: 'Arial', sans-serif;
    }
    .main-title {
        color: #0d6efd; 
        font-weight: bold;
        text-align: center;
    }
    .stButton>button {
        width: 100%;
        background-color: #0d6efd;
        color: white;
    }
</style>
""", unsafe_allow_html=True)

# --- FUNÇÕES DE BACKEND (MANTER IGUAL) ---
def pdf_to_images(uploaded_file):
    if not uploaded_file: return []
    try:
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        images = []
        for page in doc:
            mat = fitz.Matrix(2, 2)
            pix = page.get_pixmap(matrix=mat)
            img_data = pix.tobytes("jpeg")
            images.append(Image.open(io.BytesIO(img_data)))
        return images
    except: return []

def call_gemini(api_key, system_prompt, user_prompt, images):
    if not api_key:
        st.error("⚠️ API Key não configurada no menu lateral.")
        return None
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        content = [user_prompt] + images
        with st.spinner("⏳ Processando inteligência artificial..."):
            response = model.generate_content(content)
            return response.text
    except Exception as e:
        st.error(f"Erro na IA: {e}")
        return None

# --- BARRA LATERAL (INTERFACE CLÁSSICA) ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=50)
    st.title("Validador Belfar")
    
    # 1. Configuração da Chave
    st.markdown("### 🔑 Acesso")
    api_key = st.text_input("Google API Key", type="password")

    st.markdown("---")
    
    # 2. Seleção do Modo (Menu)
    modo = st.selectbox(
        "Selecione o Cenário:",
        [
            "1_Med._Referencia_x_BELFAR",
            "2_Conferencia_MKT",
            "3_Grafica_x_Arte"
        ]
    )

    st.markdown("---")
    
    # 3. Inputs Dinâmicos (Mudam conforme a escolha acima)
    inputs_ok = False # Controle para liberar o botão
    
    if modo == "1_Med._Referencia_x_BELFAR":
        st.info("Comparação de Texto Técnico")
        file1 = st.file_uploader("📂 Bula Referência (PDF)", type="pdf")
        file2 = st.file_uploader("📂 Bula Belfar (PDF)", type="pdf")
        if file1 and file2: inputs_ok = True

    elif modo == "2_Conferencia_MKT":
        st.info("Checklist de Itens Obrigatórios")
        file1 = st.file_uploader("📂 Bula para Análise (PDF)", type="pdf")
        checklist_txt = st.text_area("Itens para validar:", value="VENDA SOB PRESCRIÇÃO\nLogo Belfar\nFarmacêutico Resp.\nSAC", height=100)
        if file1: inputs_ok = True

    elif modo == "3_Grafica_x_Arte":
        st.info("Comparação Visual (Pixel a Pixel)")
        file1 = st.file_uploader("📂 Arte Original (PDF)", type="pdf")
        file2 = st.file_uploader("📂 Prova Gráfica (Scan)", type="pdf")
        if file1 and file2: inputs_ok = True

    st.markdown("---")
    
    # Botão de Ação na Barra Lateral
    btn_processar = st.button("🚀 INICIAR VALIDAÇÃO", disabled=not inputs_ok)

# --- ÁREA PRINCIPAL (RESULTADOS) ---

st.markdown(f'<h1 class="main-title">{modo.replace("_", " ")}</h1>', unsafe_allow_html=True)

if not btn_processar:
    # Tela Inicial (Placeholder)
    st.markdown("""
    <div style="text-align: center; color: #666; margin-top: 50px;">
        <h3>Aguardando arquivos...</h3>
        <p>Utilize o menu lateral (esquerda) para configurar e fazer upload.</p>
    </div>
    """, unsafe_allow_html=True)

else:
    # Lógica de Processamento (Só roda quando clica no botão)
    
    # CENÁRIO 1
    if modo == "1_Med._Referencia_x_BELFAR":
        imgs1 = pdf_to_images(file1)
        imgs2 = pdf_to_images(file2)
        
        prompt = """
        Você é um Especialista Regulatório. 
        Compare o CONTEÚDO TÉCNICO das duas bulas (Imagens 1 vs Imagens 2).
        Ignore formatação. Foque em: Posologia, Concentração e Contraindicações.
        Diga se estão CONFORMES ou descreva as DIVERGÊNCIAS.
        """
        res = call_gemini(api_key, "Especialista Farma", prompt, imgs1 + imgs2)
        if res: st.markdown(res)

    # CENÁRIO 2
    elif modo == "2_Conferencia_MKT":
        imgs1 = pdf_to_images(file1)
        prompt = f"""
        Verifique visualmente se estes itens existem na bula:
        {checklist_txt}
        Responda com [OK] ou [AUSENTE] para cada um.
        """
        res = call_gemini(api_key, "Auditor MKT", prompt, imgs1)
        if res: st.markdown(res)

    # CENÁRIO 3
    elif modo == "3_Grafica_x_Arte":
        imgs1 = pdf_to_images(file1)
        imgs2 = pdf_to_images(file2)
        prompt = """
        Compare visualmente a Arte (Grupo 1) com a Prova Gráfica (Grupo 2).
        Procure: Textos cortados, Manchas, Cores erradas ou Deslocamentos.
        Se estiver perfeito, aprove.
        """
        res = call_gemini(api_key, "Especialista Gráfico", prompt, imgs1 + imgs2)
        if res: st.markdown(res)
