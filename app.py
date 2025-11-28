import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
from PIL import Image
import io

# --- CONFIGURAÇÃO VISUAL ---
st.set_page_config(page_title="Belfar AI Validator", page_icon="💊", layout="wide")

st.markdown("""
<style>
    .main-header {font-size: 30px; font-weight: bold; color: #1E88E5; margin-bottom: 10px;}
    .sub-header {font-size: 18px; color: #555;}
    .report-container {background-color: #f8f9fa; padding: 20px; border-radius: 10px; border-left: 5px solid #1E88E5; box-shadow: 2px 2px 10px rgba(0,0,0,0.05);}
    .stButton>button {width: 100%;}
</style>
""", unsafe_allow_html=True)

# --- SIDEBAR & CONFIGURAÇÃO DA API ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=80)
    st.title("Configuração")
    st.markdown("---")
    
    api_key = st.text_input("🔑 Cole sua Google API Key", type="password", help="Pegue sua chave gratuita no Google AI Studio")
    
    st.info("""
    **Como funciona:**
    Este sistema usa o **Gemini 1.5 Flash**. 
    Ele 'enxerga' as páginas do PDF como imagens, 
    eliminando erros de formatação ou texto embaralhado.
    """)
    st.markdown("---")
    st.caption("Desenvolvido para Belfar Lab.")

# --- FUNÇÕES DE PROCESSAMENTO ---

def pdf_to_images(uploaded_file):
    """Converte PDF em lista de imagens de alta resolução"""
    if not uploaded_file:
        return []
    
    # Lê o arquivo da memória
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    images = []
    
    for page_num, page in enumerate(doc):
        # Zoom de 2x (matrix) para garantir que a IA leia letras miúdas (bula)
        mat = fitz.Matrix(2, 2)
        pix = page.get_pixmap(matrix=mat)
        img_data = pix.tobytes("jpeg")
        images.append(Image.open(io.BytesIO(img_data)))
        
    return images

def call_gemini(system_prompt, user_prompt, images):
    """Função segura para chamar a IA"""
    if not api_key:
        st.error("⚠️ ERRO: API Key não detectada. Insira a chave na barra lateral.")
        return None

    try:
        genai.configure(api_key=api_key)
        # Configurações de segurança para evitar bloqueios indevidos em textos médicos
        safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ]
        
        model = genai.GenerativeModel(
            model_name='gemini-1.5-flash',
            safety_settings=safety_settings,
            system_instruction=system_prompt
        )
        
        # Monta o payload (Texto + Imagens)
        content = [user_prompt] + images
        
        with st.spinner("🧠 A IA está analisando os documentos... Aguarde."):
            response = model.generate_content(content)
            return response.text
            
    except Exception as e:
        st.error(f"Ocorreu um erro na conexão com a IA: {str(e)}")
        return None

# --- INTERFACE PRINCIPAL ---

st.markdown('<div class="main-header">💊 Validador de Bulas Inteligente (V3.0)</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Validação visual e semântica powered by Google Gemini</div>', unsafe_allow_html=True)
st.write("")

# Abas de Navegação
tab1, tab2, tab3 = st.tabs(["📄 1. Ref x BELFAR (Texto)", "✅ 2. Conferência MKT", "🎨 3. Gráfica x Arte"])

# --- CENÁRIO 1: REF x BELFAR ---
with tab1:
    st.markdown("### Comparação de Conteúdo Médico")
    st.write("Verifica se o teor da bula Belfar bate com a Referência, ignorando diferenças de layout.")
    
    col1, col2 = st.columns(2)
    with col1:
        file_ref = st.file_uploader("Upload Bula Referência (PDF)", type="pdf", key="f1")
    with col2:
        file_bel = st.file_uploader("Upload Bula Belfar (PDF)", type="pdf", key="f2")

    if st.button("Analisar Divergências Médicas", type="primary"):
        if file_ref and file_bel:
            imgs_ref = pdf_to_images(file_ref)
            imgs_bel = pdf_to_images(file_bel)
            
            system_instruction = "Você é um Especialista Sênior em Assuntos Regulatórios da ANVISA."
            prompt = """
            Analise visualmente as imagens fornecidas.
            O primeiro grupo de imagens é a BULA REFERÊNCIA (Padrão).
            O segundo grupo é a BULA BELFAR (Candidata).

            TAREFA: Compare o TEXTO TÉCNICO das duas.
            Ignore formatação, quebras de linha ou fontes. Foque no significado.
            
            Verifique rigorosamente:
            1. Posologia (Doses e frequências).
            2. Contraindicações.
            3. Concentração do medicamento.
            4. Cuidados de conservação.

            Gere um relatório em Markdown:
            - Se estiver tudo certo, diga: "✅ Conteúdo Técnico Conforme".
            - Se houver divergência, crie uma tabela mostrando: [Item] | [Texto Referência] | [Texto Belfar].
            """
            
            # Envia tudo junto para a IA entender a separação
            response = call_gemini(system_instruction, prompt, imgs_ref + imgs_bel)
            if response:
                st.markdown('<div class="report-container">', unsafe_allow_html=True)
                st.markdown(response)
                st.markdown('</div>', unsafe_allow_html=True)
        else:
            st.warning("Por favor, faça upload dos dois arquivos.")

# --- CENÁRIO 2: MKT ---
with tab2:
    st.markdown("### Conferência de Marketing & Legal")
    st.write("Verifica automaticamente se itens obrigatórios constam no documento.")
    
    file_mkt = st.file_uploader("Upload Bula para MKT (PDF)", type="pdf", key="f3")
    
    default_checklist = "Frase: 'VENDA SOB PRESCRIÇÃO MÉDICA'\nLogo da Belfar visível\nNome do Farmacêutico Responsável\nNúmero do CRF\nEndereço da Indústria"
    checklist = st.text_area("Itens para verificar (um por linha):", value=default_checklist, height=150)
    
    if st.button("Rodar Checklist MKT", type="primary"):
        if file_mkt:
            imgs_mkt = pdf_to_images(file_mkt)
            
            system_instruction = "Você é um Auditor de Qualidade Farmacêutica."
            prompt = f"""
            Analise as imagens da bula anexa.
            Verifique a presença dos seguintes itens obrigatórios:
            
            {checklist}
            
            Para cada item, responda:
            - [OK] Se encontrou (cite onde está ou o texto exato).
            - [AUSENTE] Se não encontrou.
            
            Se houver erros grosseiros de português, aponte em uma seção "Observações Extras".
            """
            
            response = call_gemini(system_instruction, prompt, imgs_mkt)
            if response:
                st.markdown('<div class="report-container">', unsafe_allow_html=True)
                st.markdown(response)
                st.markdown('</div>', unsafe_allow_html=True)

# --- CENÁRIO 3: GRÁFICA ---
with tab3:
    st.markdown("### Validação Visual (Pré-Impressão)")
    st.write("Compara a Arte Final com a Prova Gráfica para detectar defeitos de impressão.")
    
    c1, c2 = st.columns(2)
    with c1:
        file_arte = st.file_uploader("Upload Arte Final (PDF)", type="pdf", key="f4")
    with c2:
        file_prova = st.file_uploader("Upload Prova Gráfica (Scan/PDF)", type="pdf", key="f5")
        
    if st.button("Comparar Visualmente", type="primary"):
        if file_arte and file_prova:
            imgs_arte = pdf_to_images(file_arte)
            imgs_prova = pdf_to_images(file_prova)
            
            system_instruction = "Você é um Especialista em Pré-Impressão Gráfica."
            prompt = """
            Compare visualmente a ARTE ORIGINAL (primeiras imagens) com a PROVA GRÁFICA (últimas imagens).
            
            Procure por defeitos de impressão:
            1. Textos cortados nas margens.
            2. Manchas, sujeiras ou borrões na prova gráfica.
            3. Cores desbotadas ou ilegíveis.
            4. Elementos gráficos deslocados.
            
            Se a prova estiver perfeita, confirme a aprovação.
            """
            
            response = call_gemini(system_instruction, prompt, imgs_arte + imgs_prova)
            if response:
                st.markdown('<div class="report-container">', unsafe_allow_html=True)
                st.markdown(response)
                st.markdown('</div>', unsafe_allow_html=True)
