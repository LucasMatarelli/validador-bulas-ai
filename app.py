# -*- coding: utf-8 -*-
import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
from PIL import Image
import io
import re

# ----------------- CONFIGURAÇÃO E CSS (Visual v107 + v105) -----------------
st.set_page_config(layout="wide", page_title="Auditoria de Bulas AI", page_icon="🔬")

GLOBAL_CSS = """
<style>
/* Ajustes Gerais */
.main .block-container {
    padding-top: 2rem !important;
    padding-bottom: 2rem !important;
    max-width: 95% !important;
}
[data-testid="stHeader"] { display: none !important; }
footer { display: none !important; }

/* Caixa de Bula (Estilo Papel) */
.bula-box {
  height: 450px;
  overflow-y: auto;
  border: 1px solid #dcdcdc;
  border-radius: 6px;
  padding: 20px;
  background: #ffffff;
  font-family: "Georgia", "Times New Roman", serif;
  font-size: 15px;
  line-height: 1.6;
  color: #111;
  box-shadow: 0 2px 5px rgba(0,0,0,0.05);
}

/* Títulos das Seções */
.section-title {
  font-size: 16px;
  font-weight: 700;
  color: #222;
  margin: 15px 0 10px;
  border-bottom: 2px solid #eee;
  padding-bottom: 5px;
}

/* Cores de Destaque */
.ref-title { color: #0b5686; } /* Azul Referência */
.bel-title { color: #0b8a3e; } /* Verde Belfar */

/* Status Box para mensagens da IA */
.status-box {padding: 15px; border-radius: 8px; margin-bottom: 15px; font-size: 15px;}
.success {background-color: #d4edda; color: #155724; border: 1px solid #c3e6cb;}
.error {background-color: #f8d7da; color: #721c24; border: 1px solid #f5c6cb;}

/* Botão Principal */
.stButton>button {
    width: 100%; 
    background-color: #0068c9; 
    color: white; 
    font-weight: bold; 
    height: 50px;
    border-radius: 8px;
    border: none;
}
.stButton>button:hover { background-color: #0053a0; }
</style>
"""
st.markdown(GLOBAL_CSS, unsafe_allow_html=True)

# ----------------- FUNÇÕES BACKEND (IA) -----------------

def get_best_model(api_key):
    """Seleciona o modelo Gemini mais capaz disponível na conta."""
    if not api_key: return None, "Chave vazia"
    try:
        genai.configure(api_key=api_key)
        available = [m.name for m in genai.list_models()]
        
        # Prioridade: 2.5 -> 2.0 -> 1.5
        preferencias = [
            'models/gemini-2.5-flash',
            'models/gemini-2.0-flash-001',
            'models/gemini-2.0-flash',
            'models/gemini-1.5-pro',
            'models/gemini-1.5-flash'
        ]
        for pref in preferencias:
            if pref in available: return pref, None
            
        # Fallback genérico
        for model in available:
            if 'gemini' in model and 'vision' not in model: return model, None
            
        return None, "Nenhum modelo Gemini compatível."
    except Exception as e:
        return None, str(e)

def pdf_to_images(uploaded_file):
    """Renderiza PDF para imagens (Visão Computacional)."""
    if not uploaded_file: return []
    try:
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        images = []
        for page in doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2)) # Zoom 2x para nitidez
            images.append(Image.open(io.BytesIO(pix.tobytes("jpeg"))))
        return images
    except: return []

# ----------------- BARRA LATERAL -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=60)
    st.title("Configuração")
    
    api_key = st.text_input("Chave API Google:", type="password")
    
    selected_model = None
    if api_key:
        mod, err = get_best_model(api_key)
        if mod:
            st.success(f"Conectado: {mod.replace('models/', '')}")
            selected_model = mod
        else:
            st.error(f"Erro: {err}")
    
    st.divider()
    tipo_auditoria = st.radio(
        "Cenário de Análise:",
        (
            "1. Comparação Texto (Ref x Bel)", 
            "2. Conferência MKT (Checklist)", 
            "3. Gráfica x Arte (Visual)"
        )
    )
    st.info("Visual v107/v105 + Motor Gemini AI")

# ----------------- ÁREA PRINCIPAL -----------------

st.markdown("<h2 style='text-align: center; color: #333;'>🔬 Auditoria de Bulas Inteligente</h2>", unsafe_allow_html=True)

# Variáveis de Upload
f1, f2 = None, None
checklist_txt = ""
inputs_ok = False

# --- CENÁRIO 1: TEXTO (Layout Clássico) ---
if "Comparação" in tipo_auditoria:
    st.markdown("Comparação semântica de texto técnico (Posologia, Contraindicações, etc).")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("<div class='section-title ref-title'>📄 Documento Referência</div>", unsafe_allow_html=True)
        f1 = st.file_uploader("Upload PDF Ref", type=["pdf"], key="ref1")
    with c2:
        st.markdown("<div class='section-title bel-title'>📄 Documento BELFAR</div>", unsafe_allow_html=True)
        f2 = st.file_uploader("Upload PDF Belfar", type=["pdf"], key="bel1")
    if f1 and f2: inputs_ok = True

# --- CENÁRIO 2: MKT (Layout v107) ---
elif "MKT" in tipo_auditoria:
    st.markdown("Validação de itens obrigatórios de Marketing.")
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("📄 Arquivo ANVISA (Ref)") # Mantendo estilo v107
        f1 = st.file_uploader("Opcional (para contexto)", type=["pdf"], key="ref2")
    with c2:
        st.subheader("📄 Arquivo MKT (Alvo)")   # Mantendo estilo v107
        f2 = st.file_uploader("Arquivo para Validar", type=["pdf"], key="bel2")
    
    checklist_txt = st.text_area("Itens Obrigatórios (Checklist):", 
        "VENDA SOB PRESCRIÇÃO MÉDICA\nLogo da Belfar\nFarmacêutico Responsável\nSAC 0800\nIndústria Brasileira", height=100)
    
    if f2: inputs_ok = True # Só o arquivo MKT é obrigatório aqui

# --- CENÁRIO 3: GRÁFICA (Layout v105) ---
elif "Gráfica" in tipo_auditoria:
    st.markdown("Comparação Visual (Pixel-Perfect) para Pré-Impressão.")
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("📄 Arte Vigente")      # Mantendo estilo v105
        f1 = st.file_uploader("PDF Original", type=["pdf"], key="ref3")
    with c2:
        st.subheader("📄 PDF da Gráfica")    # Mantendo estilo v105
        f2 = st.file_uploader("Prova Digitalizada", type=["pdf"], key="bel3")
    if f1 and f2: inputs_ok = True

st.divider()

# --- EXECUÇÃO ---
if st.button("🔍 Iniciar Auditoria Completa"):
    if not api_key:
        st.error("⚠️ Insira a Chave API na barra lateral.")
    elif not inputs_ok:
        st.warning("⚠️ Faça o upload dos arquivos necessários.")
    else:
        with st.spinner("🤖 A IA está analisando os documentos..."):
            try:
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel(selected_model)
                
                # Prepara imagens
                imgs_payload = []
                if "MKT" in tipo_auditoria:
                    # No MKT o foco é o arquivo f2 (Belfar/MKT)
                    f2.seek(0)
                    imgs_payload = pdf_to_images(f2)
                else:
                    f1.seek(0); f2.seek(0)
                    imgs_payload = pdf_to_images(f1) + pdf_to_images(f2)
                
                # PROMPTS INTELIGENTES (Gerando a saída no estilo antigo)
                prompt = ""
                
                if "Comparação" in tipo_auditoria:
                    prompt = """
                    Atue como Auditor de Qualidade Farmacêutica.
                    Compare as Bulas (Primeiro grupo = Ref, Segundo grupo = Belfar).
                    
                    Gere uma saída HTML LIMPA (sem tags html, head, body) para ser inserida numa div.
                    
                    1. Calcule uma nota estimada de conformidade (0-100%).
                    2. Crie uma TABELA para: POSOLOGIA, COMPOSIÇÃO, CONTRAINDICAÇÕES.
                       Colunas: Item | Ref | Belfar | Status.
                       Se houver divergência, coloque em negrito.
                    
                    Formato de saída obrigatório:
                    SCORE: [Nota]%
                    <hr>
                    (Tabela HTML aqui)
                    """
                    
                elif "MKT" in tipo_auditoria:
                    prompt = f"""
                    Atue como Auditor de Marketing Farmacêutico.
                    Analise o documento visualmente.
                    
                    Checklist para verificar:
                    {checklist_txt}
                    
                    Gere uma saída estilo Relatório:
                    1. Nota de Conformidade (baseada em quantos itens achou).
                    2. Lista detalhada.
                    
                    Formato de saída obrigatório:
                    SCORE: [Nota]%
                    <hr>
                    <h3>Checklist de Itens</h3>
                    <ul>
                    (Liste cada item com ✅ ou ❌ e uma breve observação de onde está)
                    </ul>
                    """
                    
                elif "Gráfica" in tipo_auditoria:
                    prompt = """
                    Atue como Especialista de Pré-Impressão.
                    Compare a ARTE VIGENTE (Primeiras imagens) com o PDF DA GRÁFICA (Últimas imagens).
                    
                    Procure defeitos visuais:
                    - Textos cortados ou faltando.
                    - Manchas de tinta.
                    - Deslocamento de layout.
                    - Cores/Fontes visivelmente erradas.
                    
                    Formato de saída obrigatório:
                    SCORE: [Nota]%
                    <hr>
                    <h3>Relatório Visual</h3>
                    (Se perfeito, diga "Aprovado para Impressão". Se não, liste os erros com bullet points).
                    """

                # Chamada IA
                resp = model.generate_content([prompt] + imgs_payload)
                texto_ia = resp.text
                
                # --- PARSER PARA EXTRAIR NOTA E HTML ---
                # A IA vai mandar "SCORE: 95%". Vamos pegar isso para o st.metric
                score_val = "N/A"
                if "SCORE:" in texto_ia:
                    parts = texto_ia.split("SCORE:")
                    try:
                        score_val = parts[1].split("%")[0].strip() + "%"
                        # O resto do texto é o relatório
                        relatorio_html = parts[1].split("%", 1)[1]
                    except:
                        relatorio_html = texto_ia
                else:
                    relatorio_html = texto_ia

                # --- VISUALIZAÇÃO ESTILO DASHBOARD (IGUAL v107) ---
                
                # 1. Métricas no Topo
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Conformidade", score_val)
                c2.metric("Motor IA", selected_model.split("/")[-1])
                c3.metric("Análise", "Visual + Texto")
                c4.metric("Status", "Concluído", delta="OK")
                
                st.divider()
                
                # 2. Relatório dentro da Bula-Box
                st.subheader("📝 Relatório Detalhado")
                
                # Usamos markdown com HTML allow para renderizar a tabela/lista bonita dentro da caixa
                st.markdown(f"""
                <div class='bula-box'>
                    {relatorio_html}
                </div>
                """, unsafe_allow_html=True)

            except Exception as e:
                st.error(f"Erro na análise: {e}")

st.divider()
st.caption("Sistema de Auditoria v107/v105 (Híbrido) | Powered by Google Gemini")
