# -*- coding: utf-8 -*-
import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
from PIL import Image
import io
import json
import re

# ----------------- CONFIGURAÇÃO E CSS (O Visual que você quer) -----------------
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
mark.diff { background-color: #ffff99; padding: 0 2px; color: black; border-radius: 2px; } /* Amarelo: Divergência */
mark.ort { background-color: #ffdfd9; padding: 0 2px; color: black; border-bottom: 1px dashed red; } /* Vermelho: Ortografia */
mark.anvisa { background-color: #DDEEFF; padding: 0 2px; color: black; border: 1px solid #0000FF; font-weight: bold; } /* Azul: Data */

/* Botão */
.stButton>button { width: 100%; background-color: #0068c9; color: white; font-weight: bold; height: 50px; border-radius: 8px; }
</style>
"""
st.markdown(GLOBAL_CSS, unsafe_allow_html=True)

# ----------------- DEFINIÇÃO DAS LISTAS DE SEÇÕES (RIGOROSAS) -----------------

SECOES_PACIENTE = [
    "APRESENTAÇÕES", 
    "COMPOSIÇÃO", 
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
    "APRESENTAÇÕES", 
    "COMPOSIÇÃO", 
    "INDICAÇÕES", 
    "RESULTADOS DE EFICÁCIA", 
    "CARACTERÍSTICAS FARMACOLÓGICAS", 
    "CONTRAINDICAÇÕES", 
    "ADVERTÊNCIAS E PRECAUÇÕES", 
    "INTERAÇÕES MEDICAMENTOSAS", 
    "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO", 
    "POSOLOGIA E MODO DE USAR", 
    "REAÇÕES ADVERSAS", 
    "SUPERDOSE", 
    "DIZERES LEGAIS"
]

# Seções que NÃO devem ser comparadas semanticamente (apenas exibidas)
SECOES_NAO_COMPARAR = ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]

# ----------------- FUNÇÕES BACKEND -----------------

def get_best_model(api_key):
    if not api_key: return None, "Chave vazia"
    try:
        genai.configure(api_key=api_key)
        # Prioriza 2.5 e 2.0 que são ótimos para seguir instruções complexas JSON
        preferencias = ['models/gemini-2.5-flash', 'models/gemini-2.0-flash', 'models/gemini-1.5-pro']
        available = [m.name for m in genai.list_models()]
        for pref in preferencias:
            if pref in available: return pref, None
        return 'models/gemini-1.5-flash', None 
    except Exception as e: return None, str(e)

def pdf_to_images(uploaded_file):
    if not uploaded_file: return []
    try:
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        images = []
        for page in doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2)) # Zoom 2x para leitura boa
            images.append(Image.open(io.BytesIO(pix.tobytes("jpeg"))))
        return images
    except: return []

def clean_json_response(text):
    text = text.replace("```json", "").replace("```", "").strip()
    # Corrige problema comum onde a IA coloca comentários no JSON
    text = re.sub(r'//.*', '', text) 
    return text

# ----------------- BARRA LATERAL -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=60)
    st.title("Configuração")
    api_key = st.text_input("Chave API Google:", type="password")
    
    selected_model = None
    if api_key:
        mod, err = get_best_model(api_key)
        if mod:
            st.success(f"Motor Ativo: {mod.replace('models/', '')}")
            selected_model = mod
    
    st.divider()
    tipo_auditoria = st.selectbox(
        "Cenário de Análise:",
        ["1. Referência x BELFAR", "2. Conferência MKT", "3. Gráfica x Arte"]
    )
    
    # Lógica de Seleção de Lista de Seções
    lista_secoes_ativa = SECOES_PACIENTE # Default
    nome_tipo_bula = "Paciente"

    if tipo_auditoria == "1. Referência x BELFAR":
        escolha = st.radio("Tipo de Bula:", ["Paciente", "Profissional"])
        if escolha == "Profissional":
            lista_secoes_ativa = SECOES_PROFISSIONAL
            nome_tipo_bula = "Profissional"
    else:
        # Cenários 2 e 3 sempre usam a lista de Paciente conforme pedido
        lista_secoes_ativa = SECOES_PACIENTE
        nome_tipo_bula = "Paciente"

# ----------------- ÁREA PRINCIPAL -----------------
st.title(f"🔬 Auditoria: {tipo_auditoria}")

# Uploads
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
    if f2: inputs_ok = True # Só o arquivo MKT é crucial

elif tipo_auditoria == "3. Gráfica x Arte":
    c1, c2 = st.columns(2)
    with c1: f1 = st.file_uploader("📂 Arte Final", type=["pdf"], key="f1_art")
    with c2: f2 = st.file_uploader("📂 Prova Gráfica", type=["pdf"], key="f2_graf")
    if f1 and f2: inputs_ok = True

st.divider()

if st.button("🚀 INICIAR AUDITORIA COMPLETA"):
    if not inputs_ok or not api_key:
        st.warning("Verifique a API Key e se os arquivos foram enviados.")
    else:
        with st.spinner("🤖 A IA está lendo, extraindo texto e comparando seções..."):
            try:
                genai.configure(api_key=api_key)
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
                
                # Lista formatada para o prompt
                secoes_str = "\n".join([f"- {s}" for s in lista_secoes_ativa])
                nao_comparar_str = ", ".join(SECOES_NAO_COMPARAR)
                
                # PROMPT PODEROSO QUE FAZ O "CSS" DENTRO DO JSON
                prompt = f"""
                Atue como um Auditor de Qualidade Farmacêutica rigoroso.
                
                Você recebeu imagens de duas bulas (Referência e Belfar).
                
                TAREFA:
                Para cada seção da lista abaixo, extraia o texto COMPLETO de ambos os documentos.
                
                LISTA DE SEÇÕES ({nome_tipo_bula}):
                {secoes_str}
                
                REGRAS DE MARCAÇÃO HTML (Aplique diretamente no texto extraído):
                1. DIVERGÊNCIAS DE CONTEÚDO: Se houver palavras diferentes (mudança de dose, posologia, sentido), envolva a palavra/frase com <mark class='diff'>texto diferente</mark>.
                   (Exceto nas seções: {nao_comparar_str} -> Nessas, extraia o texto mas NÃO marque divergências semânticas).
                2. ERROS ORTOGRÁFICOS: Se houver erro claro de português na Belfar, envolva com <mark class='ort'>erro</mark>.
                3. DATAS ANVISA: Encontre qualquer data de aprovação (ex: 15/04/2023) e envolva com <mark class='anvisa'>dd/mm/aaaa</mark>.
                
                SAÍDA:
                Retorne APENAS um JSON válido.
                Chave: Nome exato da seção.
                Valor: Objeto com:
                  - "ref_text": Texto da referência com marcações HTML.
                  - "bel_text": Texto da belfar com marcações HTML.
                  - "status": "CONFORME", "DIVERGENTE" ou "FALTANTE".
                  
                Seções "Apresentações", "Composição" e "Dizeres Legais" devem ter status "INFORMATIVO" (não julgar divergência).
                
                Adicione uma chave final "METADADOS" com "score_global" (0-100) e "datas_anvisa" (lista de strings).
                """
                
                response = model.generate_content([prompt] + imgs)
                
                try:
                    json_data = json.loads(clean_json_response(response.text))
                except:
                    st.error("Erro ao processar resposta da IA. Tente novamente.")
                    st.stop()
                
                # --- RENDERIZAÇÃO DO FRONT-END ---
                
                # 1. Métricas
                meta = json_data.get("METADADOS", {})
                score = meta.get("score_global", 0)
                datas = meta.get("datas_anvisa", [])
                datas_str = ", ".join(datas) if datas else "Não detectada"
                
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Conformidade", f"{score}%")
                m2.metric("Seções", len(lista_secoes_ativa))
                m3.metric("Datas ANVISA", datas_str)
                m4.metric("Status", "Processado")
                
                st.divider()
                st.subheader("📝 Comparação Seção a Seção")
                
                # 2. Loop de Exibição
                for secao in lista_secoes_ativa:
                    # Busca flexível no JSON
                    dados_sec = json_data.get(secao)
                    if not dados_sec:
                        # Tenta achar aproximado (case insensitive)
                        for k, v in json_data.items():
                            if secao.lower() in k.lower():
                                dados_sec = v
                                break
                    
                    if not dados_sec:
                        # Seção não encontrada na resposta da IA
                        with st.expander(f"{secao} — 🔴 NÃO ENCONTRADA", expanded=False):
                             st.warning("A IA não conseguiu identificar esta seção nos documentos.")
                        continue
                        
                    # Dados extraídos
                    ref_html = dados_sec.get("ref_text", "")
                    bel_html = dados_sec.get("bel_text", "")
                    status = dados_sec.get("status", "N/A").upper()
                    
                    # Definição de Ícones e Cores
                    icon = "✅"
                    expanded = False
                    
                    if "DIVERGENTE" in status:
                        icon = "❌"
                        expanded = True
                    elif "FALTANTE" in status:
                        icon = "🚨"
                        expanded = True
                    elif "INFORMATIVO" in status:
                        icon = "ℹ️"
                        expanded = False
                    
                    # Renderiza o Expander
                    with st.expander(f"{secao} — {icon} {status}", expanded=expanded):
                        col_ref, col_bel = st.columns(2)
                        
                        with col_ref:
                            st.markdown(f"<div class='ref-title'>REFERÊNCIA (Padrão)</div>", unsafe_allow_html=True)
                            if ref_html:
                                st.markdown(f"<div class='bula-box'>{ref_html}</div>", unsafe_allow_html=True)
                            else:
                                st.info("Conteúdo não presente na Referência.")
                                
                        with col_bel:
                            st.markdown(f"<div class='bel-title'>BELFAR (Candidata)</div>", unsafe_allow_html=True)
                            if bel_html:
                                st.markdown(f"<div class='bula-box'>{bel_html}</div>", unsafe_allow_html=True)
                            else:
                                st.info("Conteúdo não presente na Belfar.")

            except Exception as e:
                st.error(f"Erro Crítico: {e}")

st.divider()
st.caption("Sistema de Auditoria v108 | Powered by Google Gemini AI")
