# -*- coding: utf-8 -*-
import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
from PIL import Image
import io
import json
import re

# ----------------- CHAVE DA API (ESTÁTICA) -----------------
FIXED_API_KEY = "AIzaSyB3ctao9sOsQmAylMoYni_1QvgZFxJ02tw"

# ----------------- CONFIGURAÇÃO E CSS -----------------
st.set_page_config(layout="wide", page_title="Auditoria de Bulas AI", page_icon="🔬")

GLOBAL_CSS = """
<style>
/* Ajustes de Espaçamento Geral */
.main .block-container { 
    padding-top: 3rem !important; 
    padding-bottom: 3rem !important; 
    max-width: 95% !important; 
}
[data-testid="stHeader"] { display: none !important; }
footer { display: none !important; }

/* Título Principal Estilizado */
.main-header {
    font-size: 28px;
    font-weight: 700;
    color: #1f2937;
    margin-bottom: 10px;
    display: flex;
    align-items: center;
    gap: 10px;
}
.sub-header {
    font-size: 16px;
    color: #6b7280;
    margin-bottom: 30px;
    border-bottom: 1px solid #e5e7eb;
    padding-bottom: 20px;
}

/* Caixa de Texto da Bula (Estilo Papel) */
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

/* Headers das Colunas de Upload */
.upload-header {
    font-size: 18px;
    font-weight: 600;
    color: #374151;
    margin-bottom: 10px;
    display: flex;
    align-items: center;
    gap: 8px;
}

/* Cores e Tags */
.ref-title { color: #0369a1; font-weight: bold; margin-bottom: 5px; }
.bel-title { color: #15803d; font-weight: bold; margin-bottom: 5px; }

mark.diff { background-color: #fef08a; padding: 2px 4px; color: black; border-radius: 4px; border: 1px solid #fde047; }
mark.ort { background-color: #fecaca; padding: 2px 4px; color: black; border-bottom: 2px solid #ef4444; }
mark.anvisa { background-color: #dbeafe; padding: 2px 4px; color: #1e40af; border: 1px solid #93c5fd; font-weight: 600; }

/* Botão Principal Grande */
.stButton>button { 
    width: 100%; 
    background-color: #ef4444; /* Vermelho estilo imagem 2 */
    color: white; 
    font-weight: bold; 
    font-size: 16px;
    height: 55px; 
    border-radius: 8px; 
    border: none;
    margin-top: 20px;
}
.stButton>button:hover { background-color: #dc2626; }

/* Status de Conexão na Sidebar */
.connection-status {
    padding: 10px;
    background-color: #dcfce7;
    color: #166534;
    border-radius: 6px;
    font-size: 14px;
    font-weight: 500;
    text-align: center;
    border: 1px solid #bbf7d0;
}
</style>
"""
st.markdown(GLOBAL_CSS, unsafe_allow_html=True)

# ----------------- LISTAS DE SEÇÕES -----------------

SECOES_PACIENTE = [
    "APRESENTAÇÕES", "COMPOSIÇÃO", 
    "PARA QUE ESTE MEDICAMENTO É INDICADO", 
    "COMO ESTE MEDICAMENTO FUNCIONA?", 
    "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?", 
    "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?", 
    "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?", 
    "COMO DEVO USAR ESTE MEDICAMENTO?", 
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

# ----------------- FUNÇÕES BACKEND -----------------

def get_best_model(api_key):
    try:
        genai.configure(api_key=api_key)
        preferencias = ['models/gemini-2.5-flash', 'models/gemini-2.0-flash', 'models/gemini-1.5-pro']
        available = [m.name for m in genai.list_models()]
        for pref in preferencias:
            if pref in available: return pref
        return 'models/gemini-1.5-flash'
    except: return None

def pdf_to_images(uploaded_file):
    if not uploaded_file: return []
    try:
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        images = []
        for page in doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            images.append(Image.open(io.BytesIO(pix.tobytes("jpeg"))))
        return images
    except: return []

def clean_json_response(text):
    text = text.replace("```json", "").replace("```", "").strip()
    text = re.sub(r'//.*', '', text) 
    return text

# ----------------- BARRA LATERAL (SIMPLIFICADA) -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=70)
    st.markdown("### Navegação")
    
    # Menu de Navegação
    tipo_auditoria = st.radio(
        "Selecione o Cenário:",
        ["1. Referência x BELFAR", "2. Conferência MKT", "3. Gráfica x Arte"]
    )
    
    st.markdown("---")
    
    # Status da Conexão (Fixo)
    selected_model = get_best_model(FIXED_API_KEY)
    if selected_model:
        st.markdown(f"""
        <div class="connection-status">
            ✅ Sistema Conectado<br>
            <span style="font-size:11px">{selected_model.replace('models/', '')}</span>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.error("❌ Erro na API Key")

# ----------------- ÁREA PRINCIPAL -----------------

# Título Principal (Estilo v21.9)
st.markdown(f"""
<div class="main-header">
    🔬 Inteligência Artificial para Auditoria de Bulas
</div>
<div class="sub-header">
    Cenário Ativo: <b>{tipo_auditoria}</b>
</div>
""", unsafe_allow_html=True)

# Variáveis Globais de Execução
f1, f2 = None, None
inputs_ok = False
lista_secoes_ativa = SECOES_PACIENTE
nome_tipo_bula = "Paciente"

# --- LÓGICA DE LAYOUT POR CENÁRIO ---

if tipo_auditoria == "1. Referência x BELFAR":
    # Seletor "Bonitinho" na página principal
    st.markdown("**Tipo de Bula:**")
    tipo_bula_radio = st.radio(
        "Selecione o tipo:", 
        ["Paciente", "Profissional"], 
        horizontal=True,
        label_visibility="collapsed"
    )
    
    if tipo_bula_radio == "Profissional":
        lista_secoes_ativa = SECOES_PROFISSIONAL
        nome_tipo_bula = "Profissional"
    
    st.markdown("<br>", unsafe_allow_html=True) # Espaçamento
    
    c1, c2 = st.columns(2, gap="large")
    with c1:
        st.markdown('<div class="upload-header">📄 Documento de Referência</div>', unsafe_allow_html=True)
        f1 = st.file_uploader("PDF Referência (Padrão)", type=["pdf"], key="f1", label_visibility="collapsed")
    with c2:
        st.markdown('<div class="upload-header">📄 Documento BELFAR</div>', unsafe_allow_html=True)
        f2 = st.file_uploader("PDF Belfar (Candidata)", type=["pdf"], key="f2", label_visibility="collapsed")
    
    if f1 and f2: inputs_ok = True

elif tipo_auditoria == "2. Conferência MKT":
    c1, c2 = st.columns(2, gap="large")
    with c1:
        st.markdown('<div class="upload-header">📄 Referência (Opcional)</div>', unsafe_allow_html=True)
        f1 = st.file_uploader("Upload opcional", type=["pdf"], key="f1mkt", label_visibility="collapsed")
    with c2:
        st.markdown('<div class="upload-header">📄 Arquivo MKT (Obrigatório)</div>', unsafe_allow_html=True)
        f2 = st.file_uploader("Upload para validar", type=["pdf"], key="f2mkt", label_visibility="collapsed")
    
    if f2: inputs_ok = True

elif tipo_auditoria == "3. Gráfica x Arte":
    c1, c2 = st.columns(2, gap="large")
    with c1:
        st.markdown('<div class="upload-header">🎨 Arte Final</div>', unsafe_allow_html=True)
        f1 = st.file_uploader("Upload Arte", type=["pdf"], key="f1art", label_visibility="collapsed")
    with c2:
        st.markdown('<div class="upload-header">🖨️ Prova Gráfica</div>', unsafe_allow_html=True)
        f2 = st.file_uploader("Upload Prova", type=["pdf"], key="f2art", label_visibility="collapsed")
    
    if f1 and f2: inputs_ok = True

# --- BOTÃO DE AÇÃO (Vermelho e Largo) ---
if st.button("🚀 INICIAR AUDITORIA COMPLETA"):
    if not inputs_ok:
        st.warning("⚠️ Por favor, faça o upload dos arquivos necessários acima.")
    else:
        with st.spinner("🤖 Lendo documentos, extraindo seções e comparando textos..."):
            try:
                genai.configure(api_key=FIXED_API_KEY)
                model = genai.GenerativeModel(selected_model)
                
                # Prepara imagens
                imgs = []
                if f2:
                    if f1: f1.seek(0)
                    f2.seek(0)
                    imgs = pdf_to_images(f1) + pdf_to_images(f2) if f1 else pdf_to_images(f2)
                else:
                    f1.seek(0)
                    imgs = pdf_to_images(f1)
                
                # Setup do Prompt
                secoes_str = "\n".join([f"- {s}" for s in lista_secoes_ativa])
                nao_comparar_str = ", ".join(SECOES_NAO_COMPARAR)
                
                prompt = f"""
                Atue como um Auditor de Qualidade Farmacêutica rigoroso.
                
                TAREFA: Extraia o TEXTO COMPLETO das seções abaixo para os dois documentos.
                
                LISTA DE SEÇÕES ({nome_tipo_bula}):
                {secoes_str}
                
                REGRAS DE MARCAÇÃO HTML (Aplique dentro do texto extraído):
                1. DIVERGÊNCIAS: Se houver mudança de sentido (dose, posologia), envolva com <mark class='diff'>texto diferente</mark>.
                   (IGNORAR divergências nas seções: {nao_comparar_str}).
                2. ORTOGRAFIA: Se houver erro de português na Belfar, envolva com <mark class='ort'>erro</mark>.
                3. DATAS: Envolva datas de aprovação (ex: 10/10/2024) com <mark class='anvisa'>data</mark>.
                
                SAÍDA: JSON obrigatório.
                Formato:
                {{
                    "NOME_DA_SECAO": {{
                        "ref_text": "Texto completo...",
                        "bel_text": "Texto completo...",
                        "status": "CONFORME" | "DIVERGENTE" | "FALTANTE" | "INFORMATIVO"
                    }},
                    "METADADOS": {{ "score_global": 90, "datas_anvisa": ["dd/mm/aaaa"] }}
                }}
                """
                
                response = model.generate_content([prompt] + imgs)
                json_data = json.loads(clean_json_response(response.text))
                
                # --- RESULTADOS ---
                st.markdown("<br>", unsafe_allow_html=True)
                st.subheader("📊 Resultado da Análise")
                
                meta = json_data.get("METADADOS", {})
                score = meta.get("score_global", 0)
                datas = meta.get("datas_anvisa", [])
                
                # Métricas Bonitas
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Conformidade", f"{score}%")
                m2.metric("Seções Analisadas", len(lista_secoes_ativa))
                m3.metric("Datas ANVISA", ", ".join(datas) if datas else "-")
                m4.metric("Status", "Processado", delta="OK")
                
                st.markdown("---")
                
                # Loop de Seções
                for secao in lista_secoes_ativa:
                    dados_sec = json_data.get(secao)
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
                        col_ref, col_bel = st.columns(2)
                        with col_ref:
                            st.markdown(f"<div class='ref-title'>REFERÊNCIA</div><div class='bula-box'>{ref_html}</div>", unsafe_allow_html=True)
                        with col_bel:
                            st.markdown(f"<div class='bel-title'>BELFAR</div><div class='bula-box'>{bel_html}</div>", unsafe_allow_html=True)

            except Exception as e:
                st.error(f"Erro Crítico: {e}")

st.markdown("<br><br><div style='text-align:center; color:#9ca3af; font-size:12px'>Sistema de Auditoria v110 | Belfar Lab</div>", unsafe_allow_html=True)
