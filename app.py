import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
from PIL import Image
import io

# --- CONFIGURAÇÃO VISUAL ---
st.set_page_config(page_title="Validador Belfar (Final)", page_icon="💊", layout="wide")

st.markdown("""
<style>
    .stButton>button {width: 100%; background-color: #28a745; color: white; font-weight: bold;}
    .status-box {padding: 15px; border-radius: 8px; margin-bottom: 15px; font-size: 15px;}
    .success {background-color: #d4edda; color: #155724; border: 1px solid #c3e6cb;}
    .error {background-color: #f8d7da; color: #721c24; border: 1px solid #f5c6cb;}
    .info {background-color: #cce5ff; color: #004085; border: 1px solid #b8daff;}
</style>
""", unsafe_allow_html=True)

# --- FUNÇÃO INTELIGENTE: SELEÇÃO DE MODELO ---
def get_best_model(api_key):
    """
    Verifica quais modelos sua conta tem acesso e escolhe o melhor disponível.
    Prioriza a série 2.5 e 2.0 que apareceu na sua lista.
    """
    if not api_key: return None, "Chave não informada"
    
    try:
        genai.configure(api_key=api_key)
        
        # 1. Pega a lista real do que você tem acesso
        available_models = [m.name for m in genai.list_models()]
        
        # 2. Lista de preferência baseada no seu print (Do melhor para o backup)
        preferencias = [
            'models/gemini-2.5-flash',       # Mais novo e rápido
            'models/gemini-2.0-flash-001',   # Versão estável
            'models/gemini-2.0-flash',       # Versão padrão
            'models/gemini-2.0-pro-exp',     # Experimental potente
            'models/gemini-1.5-flash'        # Fallback antigo
        ]
        
        # 3. Tenta casar a preferência com o disponível
        for pref in preferencias:
            if pref in available_models:
                return pref, None # Achamos o campeão!
        
        # 4. Se nenhum dos preferidos existir, pega o primeiro "gemini" que aceita conteúdo
        for model in available_models:
            if 'gemini' in model and 'embedding' not in model and 'aqa' not in model:
                return model, None
                
        return None, f"Nenhum modelo de geração de texto encontrado. Sua lista: {available_models}"
        
    except Exception as e:
        return None, f"Erro de conexão: {str(e)}"

# --- PROCESSAMENTO DE PDF ---
def pdf_to_images(uploaded_file):
    if not uploaded_file: return []
    try:
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        images = []
        for page in doc:
            # Zoom de 2x para ler letras pequenas da bula
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            img_data = pix.tobytes("jpeg")
            images.append(Image.open(io.BytesIO(img_data)))
        return images
    except: return []

# --- BARRA LATERAL ---
with st.sidebar:
    st.header("⚙️ Configuração")
    
    # Campo de senha
    api_key = st.text_input("Sua Chave Google (AIza...):", type="password")
    
    # Validação imediata da chave e modelo
    selected_model_name = None
    
    if api_key:
        with st.spinner("Verificando modelos disponíveis..."):
            model_name, error_msg = get_best_model(api_key)
            
        if model_name:
            # Limpa o nome para ficar bonito (tira o 'models/')
            display_name = model_name.replace("models/", "")
            st.markdown(f'<div class="status-box success">✅ <b>Conectado!</b><br>Usando motor: {display_name}</div>', unsafe_allow_html=True)
            selected_model_name = model_name
        else:
            st.markdown(f'<div class="status-box error">❌ <b>Erro:</b><br>{error_msg}</div>', unsafe_allow_html=True)
    else:
        st.info("👆 Cole sua chave acima para conectar.")
            
    st.markdown("---")
    modo = st.selectbox("Cenário de Análise:", [
        "1. Referência x BELFAR", 
        "2. Conferência MKT", 
        "3. Gráfica x Arte"
    ])

# --- TELA PRINCIPAL ---
st.title(f"Validador: {modo}")

# Uploads baseados no modo
inputs_ok = False
f1, f2 = None, None
checklist_text = ""

if modo == "1. Referência x BELFAR":
    st.markdown("Comparação de **Texto Técnico** (Posologia, Concentração, etc).")
    c1, c2 = st.columns(2)
    f1 = c1.file_uploader("📂 Bula Referência", type="pdf")
    f2 = c2.file_uploader("📂 Bula Belfar", type="pdf")
    if f1 and f2: inputs_ok = True

elif modo == "2. Conferência MKT":
    st.markdown("Verificação de **Checklist Obrigatório**.")
    f1 = st.file_uploader("📂 Arquivo para Análise", type="pdf")
    checklist_text = st.text_area("Itens Obrigatórios:", "VENDA SOB PRESCRIÇÃO MÉDICA\nLogo da Belfar\nFarmacêutico Responsável\nSAC 0800")
    if f1: inputs_ok = True

elif modo == "3. Gráfica x Arte":
    st.markdown("Comparação **Visual** (Manchas, cortes, layout).")
    c1, c2 = st.columns(2)
    f1 = c1.file_uploader("📂 Arte Final", type="pdf")
    f2 = c2.file_uploader("📂 Prova Gráfica", type="pdf")
    if f1 and f2: inputs_ok = True

# --- BOTÃO DE AÇÃO ---
if st.button("🚀 INICIAR ANÁLISE AGORA", disabled=not (inputs_ok and selected_model_name)):
    
    with st.spinner(f"🤖 A IA ({selected_model_name}) está lendo as bulas..."):
        try:
            # 1. Configura a IA
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(selected_model_name)
            
            # 2. Prepara as Imagens
            imgs_payload = []
            
            if modo == "2. Conferência MKT":
                f1.seek(0)
                imgs_payload = pdf_to_images(f1)
            else:
                f1.seek(0); f2.seek(0)
                # Manda as imagens sequenciadas
                imgs_payload = pdf_to_images(f1) + pdf_to_images(f2)
            
            # 3. Define o Prompt (Comando)
            prompt = ""
            if modo == "1. Referência x BELFAR":
                prompt = """
                Atue como Especialista Regulatório.
                O primeiro grupo de imagens é a Bula REFERÊNCIA.
                O segundo grupo de imagens é a Bula BELFAR.
                
                TAREFA: Compare o TEXTO TÉCNICO.
                Ignore formatação, fontes e quebras de linha.
                Verifique rigorosamente divergências em: 
                - Posologia
                - Concentração (mg/ml)
                - Contraindicações
                
                Responda: "✅ TUDO CONFORME" ou liste as divergências encontradas.
                """
            elif modo == "2. Conferência MKT":
                prompt = f"""
                Analise visualmente o documento.
                Verifique se estes itens estão presentes:
                {checklist_text}
                
                Responda com uma lista: [OK] ou [AUSENTE] para cada item.
                """
            elif modo == "3. Gráfica x Arte":
                prompt = """
                Atue como Especialista em Pré-Impressão.
                Compare visualmente a ARTE ORIGINAL (primeiras imagens) com a PROVA GRÁFICA (últimas imagens).
                
                Procure por:
                - Textos cortados.
                - Manchas de impressão.
                - Elementos faltando.
                
                Se a prova estiver fiel à arte, aprove.
                """
            
            # 4. Envia para o Google
            response = model.generate_content([prompt] + imgs_payload)
            
            # 5. Mostra o resultado
            st.markdown("### 📋 Resultado da Análise:")
            st.markdown(f'<div class="status-box info">{response.text}</div>', unsafe_allow_html=True)
            
        except Exception as e:
            st.error(f"Ocorreu um erro durante a geração: {str(e)}")
