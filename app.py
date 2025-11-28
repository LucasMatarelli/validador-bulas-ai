# -*- coding: utf-8 -*-
import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
from PIL import Image
import io
import json
import re
import docx  # python-docx

# ----------------- CHAVE DA API (ESTÁTICA) -----------------
FIXED_API_KEY = "AIzaSyB3ctao9sOsQmAylMoYni_1QvgZFxJ02tw"

# ----------------- CONFIGURAÇÃO E CSS -----------------
st.set_page_config(layout="wide", page_title="Validador Belfar", page_icon="🔬")

GLOBAL_CSS = """
<style>
/* Ajustes Gerais */
.main .block-container { 
    padding-top: 2rem !important; 
    padding-bottom: 3rem !important; 
    max-width: 95% !important; 
}
[data-testid="stHeader"] { display: none !important; }
footer { display: none !important; }

/* --- ESTILOS DA HOME PAGE --- */
.home-title {
    font-size: 36px;
    font-weight: 700;
    color: #111827;
    display: flex;
    align-items: center;
    gap: 15px;
    margin-bottom: 10px;
}
.home-subtitle {
    font-size: 20px;
    color: #374151;
    margin-bottom: 30px;
}
.info-box {
    background-color: #eff6ff;
    border-left: 5px solid #3b82f6;
    padding: 15px;
    border-radius: 4px;
    color: #1e40af;
    font-size: 16px;
    margin-bottom: 30px;
}
.feature-card {
    background-color: white;
    padding: 20px;
    border-radius: 8px;
    border: 1px solid #e5e7eb;
    margin-bottom: 15px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.05);
}
.feature-title {
    font-weight: 700;
    color: #111827;
    font-size: 16px;
    margin-bottom: 5px;
}
.feature-desc {
    color: #4b5563;
    font-size: 14px;
    line-height: 1.5;
}

/* --- ESTILOS DAS FERRAMENTAS --- */
.tool-header {
    font-size: 26px;
    font-weight: 700;
    color: #1f2937;
    margin-bottom: 5px;
    display: flex;
    align-items: center;
    gap: 10px;
}
.bula-box {
  height: 450px;
  overflow-y: auto;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 20px;
  background: #ffffff;
  font-family: "Georgia", "Times New Roman", serif;
  font-size: 15px;
  line-height: 1.6;
  color: #111;
  white-space: pre-wrap;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
}
.upload-header {
    font-size: 16px;
    font-weight: 600;
    color: #374151;
    margin-bottom: 8px;
}
.ref-title { color: #0369a1; font-weight: bold; margin-bottom: 5px; }
.bel-title { color: #15803d; font-weight: bold; margin-bottom: 5px; }

mark.diff { background-color: #fef08a; padding: 2px 4px; color: black; border-radius: 4px; border: 1px solid #fde047; }
mark.ort { background-color: #fecaca; padding: 2px 4px; color: black; border-bottom: 2px solid #ef4444; }
mark.anvisa { background-color: #dbeafe; padding: 2px 4px; color: #1e40af; border: 1px solid #93c5fd; font-weight: 600; }

.stButton>button { 
    width: 100%; 
    background-color: #ef4444; 
    color: white; 
    font-weight: bold; 
    font-size: 16px; 
    height: 50px; 
    border-radius: 8px; 
    border: none;
    margin-top: 20px;
}
.stButton>button:hover { background-color: #dc2626; }
</style>
"""
st.markdown(GLOBAL_CSS, unsafe_allow_html=True)

# ----------------- CONSTANTES -----------------
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
SECOES_PROFISSIONAL = [
    "APRESENTAÇÕES", "COMPOSIÇÃO", "INDICAÇÕES", "RESULTADOS DE EFICÁCIA", 
    "CARACTERÍSTICAS FARMACOLÓGICAS", "CONTRAINDICAÇÕES", "ADVERTÊNCIAS E PRECAUÇÕES", 
    "INTERAÇÕES MEDICAMENTOSAS", "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO", 
    "POSOLOGIA E MODO DE USAR", "REAÇÕES ADVERSAS", "SUPERDOSE", "DIZERES LEGAIS"
]
SECOES_NAO_COMPARAR = ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]

# ----------------- BACKEND -----------------
def get_best_model(api_key):
    try:
        genai.configure(api_key=api_key)
        preferencias = ['models/gemini-2.5-flash', 'models/gemini-2.0-flash', 'models/gemini-1.5-pro']
        available = [m.name for m in genai.list_models()]
        for pref in preferencias:
            if pref in available: return pref
        return 'models/gemini-1.5-flash'
    except: return None

def process_file_content(uploaded_file):
    """
    Processa o arquivo.
    - Se PDF: Retorna lista de Imagens (Visão).
    - Se DOCX: Retorna Texto (Texto).
    """
    if not uploaded_file: return None, None
    
    # Processamento DOCX (Extração de Texto)
    if uploaded_file.name.endswith('.docx'):
        try:
            doc = docx.Document(uploaded_file)
            full_text = "\n".join([para.text for para in doc.paragraphs])
            return "text", full_text
        except Exception as e:
            st.error(f"Erro ao ler DOCX: {e}")
            return None, None

    # Processamento PDF (Conversão para Imagem para IA "ver")
    elif uploaded_file.name.endswith('.pdf'):
        try:
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            images = []
            for page in doc:
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                images.append(Image.open(io.BytesIO(pix.tobytes("jpeg"))))
            return "images", images
        except Exception as e:
            st.error(f"Erro ao processar PDF: {e}")
            return None, None
    
    return None, None

def clean_json_response(text):
    text = text.replace("```json", "").replace("```", "").strip()
    text = re.sub(r'//.*', '', text)
    return text

# ----------------- NAVEGAÇÃO -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=60)
    
    # Menu Principal
    page = st.radio(
        "Navegação", 
        ["🏠 Página Inicial", "1. Referência x BELFAR", "2. Conferência MKT", "3. Gráfica x Arte"],
        label_visibility="collapsed"
    )
    
    st.markdown("---")
    
    # Status
    model_name = get_best_model(FIXED_API_KEY)
    if model_name:
        st.success(f"Conectado: {model_name.replace('models/', '')}")
    else:
        st.error("Erro Conexão API")

# ----------------- PÁGINA INICIAL (HOME) -----------------
if page == "🏠 Página Inicial":
    st.markdown("""
    <div class="home-title">
        🔬 Validador Inteligente de Bulas
    </div>
    <div class="home-subtitle">
        Bem-vindo à ferramenta de análise e comparação de documentos.
    </div>
    
    <div class="info-box">
        👈 <b>Comece agora:</b> Selecione uma das ferramentas de análise na barra lateral esquerda.
    </div>
    
    <h3>Ferramentas Disponíveis:</h3>
    """, unsafe_allow_html=True)
    
    st.markdown("""
    <div class="feature-card">
        <div class="feature-title">1. Medicamento Referência x BELFAR</div>
        <div class="feature-desc">
            Compara a bula de referência (Padrão) com a bula BELFAR. Aponta divergências de texto (dose, posologia), 
            erros ortográficos e valida datas da ANVISA. Suporta PDF e DOCX.
        </div>
    </div>
    
    <div class="feature-card">
        <div class="feature-title">2. Conferência MKT</div>
        <div class="feature-desc">
            Auditoria rápida de itens obrigatórios. Verifica se o arquivo final do Marketing contém todas as frases legais, 
            logos e informações exigidas pela ANVISA.
        </div>
    </div>
    
    <div class="feature-card">
        <div class="feature-title">3. Gráfica x Arte Vigente</div>
        <div class="feature-desc">
            Compara o PDF enviado pela Gráfica (Prova) com a Arte Vigente. O sistema analisa o conteúdo visual e textual 
            para garantir que nada foi alterado na impressão.
        </div>
    </div>
    
    <br>
    <div style="background-color:#f9fafb; padding:15px; border-radius:8px; border:1px solid #e5e7eb;">
        <b>💡 O que é um arquivo 'em curva'?</b><br>
        <span style="color:#6b7280; font-size:14px;">
        Uma bula em curva é um arquivo PDF onde todo o texto foi convertido em vetores (desenhos). 
        A maioria dos validadores comuns falha ao ler isso. <b>Este sistema usa Inteligência Artificial Visual</b>, 
        então ele consegue ler e validar arquivos em curva perfeitamente.
        </span>
    </div>
    """, unsafe_allow_html=True)

# ----------------- FERRAMENTAS DE ANÁLISE -----------------
else:
    # Cabeçalho Comum das Ferramentas
    st.markdown(f'<div class="tool-header">🔬 {page}</div>', unsafe_allow_html=True)
    
    # Variáveis de Estado
    f1, f2 = None, None
    inputs_ok = False
    lista_secoes = SECOES_PACIENTE
    nome_tipo = "Paciente"
    
    # --- CENÁRIO 1: REF x BELFAR ---
    if page == "1. Referência x BELFAR":
        # Seletor Interno (Horizontal)
        st.markdown("**Selecione o Tipo de Bula:**")
        tipo_sel = st.radio("Tipo:", ["Paciente", "Profissional"], horizontal=True, label_visibility="collapsed")
        
        if tipo_sel == "Profissional":
            lista_secoes = SECOES_PROFISSIONAL
            nome_tipo = "Profissional"
            
        st.write("") # Espaço
        
        c1, c2 = st.columns(2, gap="large")
        with c1:
            st.markdown('<div class="upload-header">📄 Referência (Padrão)</div>', unsafe_allow_html=True)
            f1 = st.file_uploader("PDF ou DOCX", type=["pdf", "docx"], key="f1")
        with c2:
            st.markdown('<div class="upload-header">📄 Belfar (Candidata)</div>', unsafe_allow_html=True)
            f2 = st.file_uploader("PDF ou DOCX", type=["pdf", "docx"], key="f2")
            
        if f1 and f2: inputs_ok = True

    # --- CENÁRIO 2: MKT ---
    elif page == "2. Conferência MKT":
        c1, c2 = st.columns(2, gap="large")
        with c1:
            st.markdown('<div class="upload-header">📄 Referência (Opcional)</div>', unsafe_allow_html=True)
            f1 = st.file_uploader("PDF ou DOCX", type=["pdf", "docx"], key="f1_mkt")
        with c2:
            st.markdown('<div class="upload-header">📄 Arquivo MKT (Obrigatório)</div>', unsafe_allow_html=True)
            f2 = st.file_uploader("PDF ou DOCX", type=["pdf", "docx"], key="f2_mkt")
        
        if f2: inputs_ok = True

    # --- CENÁRIO 3: GRÁFICA ---
    elif page == "3. Gráfica x Arte":
        c1, c2 = st.columns(2, gap="large")
        with c1:
            st.markdown('<div class="upload-header">🎨 Arte Final</div>', unsafe_allow_html=True)
            f1 = st.file_uploader("PDF ou DOCX", type=["pdf", "docx"], key="f1_art")
        with c2:
            st.markdown('<div class="upload-header">🖨️ Prova Gráfica</div>', unsafe_allow_html=True)
            f2 = st.file_uploader("PDF ou DOCX", type=["pdf", "docx"], key="f2_art")
        
        if f1 and f2: inputs_ok = True

    # --- EXECUÇÃO (LÓGICA HÍBRIDA PDF/DOCX) ---
    if st.button("🚀 INICIAR AUDITORIA COMPLETA"):
        if not inputs_ok:
            st.warning("⚠️ Faça o upload dos arquivos necessários.")
        else:
            with st.spinner("🤖 Processando arquivos (PDF visual ou DOCX texto)..."):
                try:
                    genai.configure(api_key=FIXED_API_KEY)
                    model = genai.GenerativeModel(model_name)
                    
                    # Processa Arquivo 1
                    t1, content1 = process_file_content(f1)
                    # Processa Arquivo 2 (se existir)
                    t2, content2 = process_file_content(f2) if f2 else (None, None)
                    
                    # Monta Payload para IA
                    payload = []
                    
                    # Adiciona conteúdo do Arq 1
                    if t1 == "images": payload.extend(content1)
                    elif t1 == "text": payload.append(f"--- DOCUMENTO REFERÊNCIA (TEXTO EXTRAÍDO) ---\n{content1}\n--- FIM REF ---")
                    
                    # Adiciona conteúdo do Arq 2
                    if t2 == "images": payload.extend(content2)
                    elif t2 == "text": payload.append(f"--- DOCUMENTO BELFAR/ALVO (TEXTO EXTRAÍDO) ---\n{content2}\n--- FIM ALVO ---")
                    
                    # Configura Prompt
                    secoes_str = "\n".join([f"- {s}" for s in lista_secoes])
                    nao_comparar_str = ", ".join(SECOES_NAO_COMPARAR)
                    
                    prompt = f"""
                    Atue como um Auditor de Qualidade Farmacêutica Sênior.
                    
                    Você recebeu dois documentos (Referência e Alvo/Belfar). 
                    Eles podem ser imagens (PDF visual) ou texto bruto (DOCX). Analise o conteúdo disponível.
                    
                    TAREFA: Extraia e compare o texto das seções abaixo.
                    
                    LISTA DE SEÇÕES ({nome_tipo}):
                    {secoes_str}
                    
                    REGRAS:
                    1. DIVERGÊNCIAS: Envolva diferenças de sentido com <mark class='diff'>texto</mark>.
                       (Ignore nas seções: {nao_comparar_str}).
                    2. ORTOGRAFIA: Envolva erros na Belfar com <mark class='ort'>erro</mark>.
                    3. DATAS: Envolva datas (ex: 10/05/2024) com <mark class='anvisa'>data</mark>.
                    
                    SAÍDA JSON:
                    {{
                        "NOME_DA_SECAO": {{
                            "ref_text": "Texto completo...",
                            "bel_text": "Texto completo...",
                            "status": "CONFORME" | "DIVERGENTE" | "FALTANTE" | "INFORMATIVO"
                        }},
                        "METADADOS": {{ "score_global": 90, "datas_anvisa": ["dd/mm/aaaa"] }}
                    }}
                    """
                    
                    # Envia
                    response = model.generate_content([prompt] + payload)
                    json_data = json.loads(clean_json_response(response.text))
                    
                    # Renderiza Resultados
                    st.markdown("<br>", unsafe_allow_html=True)
                    st.subheader("📊 Resultado da Análise")
                    
                    meta = json_data.get("METADADOS", {})
                    score = meta.get("score_global", 0)
                    datas = meta.get("datas_anvisa", [])
                    
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Conformidade", f"{score}%")
                    m2.metric("Seções", len(lista_secoes))
                    m3.metric("Datas ANVISA", ", ".join(datas) if datas else "-")
                    m4.metric("Status", "Concluído", delta="OK")
                    
                    st.markdown("---")
                    
                    for secao in lista_secoes:
                        dados_sec = json_data.get(secao)
                        # Busca flexível
                        if not dados_sec:
                            for k, v in json_data.items():
                                if secao.lower() in k.lower(): dados_sec = v; break
                        
                        if not dados_sec: continue
                            
                        status = dados_sec.get("status", "N/A").upper()
                        ref_html = dados_sec.get("ref_text", "")
                        bel_html = dados_sec.get("bel_text", "")
                        
                        icon = "✅"
                        expanded = False
                        if "DIVERGENTE" in status: icon, expanded = "❌", True
                        elif "FALTANTE" in status: icon, expanded = "🚨", True
                        elif "INFORMATIVO" in status: icon = "ℹ️"
                        
                        with st.expander(f"{secao} — {icon} {status}", expanded=expanded):
                            c_ref, c_bel = st.columns(2)
                            with c_ref:
                                st.markdown(f"<div class='ref-title'>REFERÊNCIA</div><div class='bula-box'>{ref_html}</div>", unsafe_allow_html=True)
                            with c_bel:
                                st.markdown(f"<div class='bel-title'>BELFAR</div><div class='bula-box'>{bel_html}</div>", unsafe_allow_html=True)

                except Exception as e:
                    st.error(f"Erro na Análise: {e}")

st.markdown("<br><br><div style='text-align:center; color:#9ca3af; font-size:12px'>Validador v112 | Belfar Lab</div>", unsafe_allow_html=True)
