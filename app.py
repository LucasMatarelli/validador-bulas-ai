# -*- coding: utf-8 -*-
import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
from PIL import Image
import io
import json
import re

# ----------------- CHAVE DA API (ESTÁTICA) -----------------
# A chave ficará fixa aqui. Não precisa mais digitar na tela.
FIXED_API_KEY = "AIzaSyB3ctao9sOsQmAylMoYni_1QvgZFxJ02tw"

# ----------------- CONFIGURAÇÃO E CSS -----------------
st.set_page_config(layout="wide", page_title="Auditoria de Bulas AI", page_icon="🔬")

GLOBAL_CSS = """
<style>
.main .block-container { padding-top: 2rem !important; padding-bottom: 2rem !important; max-width: 95% !important; }
[data-testid="stHeader"] { display: none !important; }
footer { display: none !important; }

/* Caixa de Texto da Bula */
.bula-box {
  height: 450px;
  overflow-y: auto;
  border: 1px solid #dcdcdc;
  border-radius: 6px;
  padding: 18px;
  background: #ffffff;
  font-family: "Georgia", "Times New Roman", serif;
  font-size: 14px;
  line-height: 1.6;
  color: #111;
  white-space: pre-wrap;
}

/* Títulos */
.ref-title { color: #0b5686; font-weight: bold; margin-bottom: 5px; font-size: 1.1em; }
.bel-title { color: #0b8a3e; font-weight: bold; margin-bottom: 5px; font-size: 1.1em; }

/* Marcações (Highlight) */
mark.diff { background-color: #ffff99; padding: 0 2px; color: black; border-radius: 2px; }
mark.ort { background-color: #ffdfd9; padding: 0 2px; color: black; border-bottom: 1px dashed red; }
mark.anvisa { background-color: #DDEEFF; padding: 0 2px; color: black; border: 1px solid #0000FF; font-weight: bold; }

/* Botão */
.stButton>button { width: 100%; background-color: #0068c9; color: white; font-weight: bold; height: 50px; border-radius: 8px; }
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
    # Tenta conectar silenciosamente
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

# ----------------- BARRA LATERAL -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=60)
    st.title("Configuração")
    
    # Conexão Automática
    selected_model = get_best_model(FIXED_API_KEY)
    
    if selected_model:
        st.success(f"✅ Sistema Conectado\nMotor: {selected_model.replace('models/', '')}")
    else:
        st.error("❌ Erro na Chave API Fixa")

    st.divider()
    tipo_auditoria = st.selectbox(
        "Cenário de Análise:",
        ["1. Referência x BELFAR", "2. Conferência MKT", "3. Gráfica x Arte"]
    )
    
    # Lógica de Seleção
    lista_secoes_ativa = SECOES_PACIENTE
    nome_tipo_bula = "Paciente"

    if tipo_auditoria == "1. Referência x BELFAR":
        escolha = st.radio("Tipo de Bula:", ["Paciente", "Profissional"])
        if escolha == "Profissional":
            lista_secoes_ativa = SECOES_PROFISSIONAL
            nome_tipo_bula = "Profissional"
    else:
        lista_secoes_ativa = SECOES_PACIENTE
        nome_tipo_bula = "Paciente"

# ----------------- ÁREA PRINCIPAL -----------------
st.title(f"🔬 Auditoria: {tipo_auditoria}")

f1, f2 = None, None
inputs_ok = False

if tipo_auditoria == "1. Referência x BELFAR":
    c1, c2 = st.columns(2)
    with c1: f1 = st.file_uploader("📂 PDF Referência (Padrão)", type=["pdf"], key="f1")
    with c2: f2 = st.file_uploader("📂 PDF Belfar (Candidata)", type=["pdf"], key="f2")
    if f1 and f2: inputs_ok = True

elif tipo_auditoria == "2. Conferência MKT":
    c1, c2 = st.columns(2)
    with c1: f1 = st.file_uploader("📂 PDF Referência (Opcional)", type=["pdf"], key="f1_mkt")
    with c2: f2 = st.file_uploader("📂 PDF MKT (Obrigatório)", type=["pdf"], key="f2_mkt")
    if f2: inputs_ok = True

elif tipo_auditoria == "3. Gráfica x Arte":
    c1, c2 = st.columns(2)
    with c1: f1 = st.file_uploader("📂 Arte Final", type=["pdf"], key="f1_art")
    with c2: f2 = st.file_uploader("📂 Prova Gráfica", type=["pdf"], key="f2_graf")
    if f1 and f2: inputs_ok = True

st.divider()

if st.button("🚀 INICIAR AUDITORIA COMPLETA"):
    if not inputs_ok:
        st.warning("⚠️ Faça o upload dos arquivos necessários.")
    else:
        with st.spinner("🤖 A IA está lendo, extraindo texto e comparando seções..."):
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
                
                # Formata lista
                secoes_str = "\n".join([f"- {s}" for s in lista_secoes_ativa])
                nao_comparar_str = ", ".join(SECOES_NAO_COMPARAR)
                
                # Prompt JSON Estruturado
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
                
                # --- RENDERIZAÇÃO ---
                meta = json_data.get("METADADOS", {})
                score = meta.get("score_global", 0)
                datas = meta.get("datas_anvisa", [])
                
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Conformidade", f"{score}%")
                m2.metric("Seções", len(lista_secoes_ativa))
                m3.metric("Datas Detectadas", ", ".join(datas) if datas else "-")
                m4.metric("Status", "Processado")
                
                st.divider()
                st.subheader("📝 Comparação Seção a Seção")
                
                for secao in lista_secoes_ativa:
                    dados_sec = json_data.get(secao)
                    if not dados_sec: # Busca aproximada
                        for k, v in json_data.items():
                            if secao.lower() in k.lower():
                                dados_sec = v; break
                    
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
                st.error(f"Erro Crítico: {e}")

st.divider()
st.caption("Sistema de Auditoria v109 | Powered by Google Gemini AI")
