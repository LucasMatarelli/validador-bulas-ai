import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
import json

# ----------------- 1. CONFIGURAÇÃO VISUAL (DESIGN DA FOTO) -----------------
st.set_page_config(page_title="Conferência MKT", page_icon="📊", layout="wide")

st.markdown("""
<style>
    /* Estilo das Caixas de Texto (Conteúdo) */
    .texto-box { 
        font-family: 'Segoe UI', sans-serif;
        font-size: 0.95rem;
        line-height: 1.6;
        color: #333;
        background-color: #ffffff;
        padding: 18px;
        border-radius: 8px;
        border: 1px solid #e0e0e0;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        white-space: pre-wrap;
        text-align: justify;
    }

    /* Cores dos Highlights */
    .highlight-yellow { background-color: #fff9c4; color: #000; padding: 2px 4px; border-radius: 4px; border: 1px solid #fbc02d; }
    .highlight-red { background-color: #ffcdd2; color: #b71c1c; padding: 2px 4px; border-radius: 4px; border: 1px solid #b71c1c; font-weight: bold; }
    .highlight-blue { background-color: #bbdefb; color: #0d47a1; padding: 2px 4px; border-radius: 4px; border: 1px solid #1976d2; font-weight: bold; }

    /* Bordas Laterais de Status */
    .border-ok { border-left: 6px solid #4caf50 !important; }
    .border-warn { border-left: 6px solid #ff9800 !important; }
    .border-info { border-left: 6px solid #2196f3 !important; }

    /* --- ESTILO DO PAINEL SUPERIOR (MÉTRICAS) --- */
    div[data-testid="stMetric"] {
        background-color: #ffffff;
        border: 1px solid #dee2e6;
        padding: 15px;
        border-radius: 8px;
        text-align: center;
        box-shadow: 0 1px 2px rgba(0,0,0,0.05);
    }
    
    /* Barras de Status (Conformes / Divergentes) */
    .status-bar-ok {
        background-color: #e6f4ea; /* Fundo Verde Claro */
        color: #1e8e3e;
        padding: 12px;
        border-radius: 6px;
        font-weight: bold;
        border: 1px solid #ceead6;
        display: flex; align-items: center;
    }
    .status-bar-warn {
        background-color: #fef7e0; /* Fundo Amarelo Claro */
        color: #f9ab00; /* Texto Laranja Escuro */
        padding: 12px;
        border-radius: 6px;
        font-weight: bold;
        border: 1px solid #feefc3;
        display: flex; align-items: center;
    }
</style>
""", unsafe_allow_html=True)

# ----------------- 2. CONFIGURAÇÃO MODELO -----------------
MODELO_FIXO = "models/gemini-flash-latest"

def setup_model():
    keys = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2")]
    valid_keys = [k for k in keys if k]
    
    for api_key in valid_keys:
        try:
            genai.configure(api_key=api_key)
            # Temperatura 0.0 para não inventar nada
            return genai.GenerativeModel(
                MODELO_FIXO, 
                generation_config={"response_mime_type": "application/json", "temperature": 0.0}
            )
        except: continue
    return None

# ----------------- 3. EXTRAÇÃO DE TEXTO (MKT - SEM OCR) -----------------
def extract_text_from_pdf(uploaded_file):
    try:
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        text = ""
        for page in doc:
            text += page.get_text("text") + "\n"
        return text
    except: return ""

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

# ----------------- 4. INTERFACE PRINCIPAL -----------------
st.title("📊 Resumo da Conferência (MKT)")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Anvisa (Texto)", type=["pdf"], key="f1")
f2 = c2.file_uploader("🎨 Arte MKT (Texto)", type=["pdf"], key="f2")

if st.button("🚀 Processar Conferência"):
    if f1 and f2:
        model = setup_model()
        if not model:
            st.error("Erro de API Key.")
            st.stop()

        with st.spinner("Extraindo textos e gerando painel..."):
            # Extração Texto Puro (Sem OCR, mais rápido e limpo para MKT)
            t_anvisa = extract_text_from_pdf(f1)
            t_mkt = extract_text_from_pdf(f2)

            if len(t_anvisa) < 50 or len(t_mkt) < 50:
                st.error("Erro: Arquivo sem texto selecionável. Para imagens escaneadas, use o outro módulo.")
                st.stop()

            # PROMPT ESPECÍFICO PARA JSON ESTRUTURADO COM DATAS SEPARADAS
            prompt = f"""
            Atue como Auditor Farmacêutico.
            
            INPUT:
            TEXTO 1 (ANVISA): {t_anvisa[:50000]}
            TEXTO 2 (MKT): {t_mkt[:30000]}

            TAREFA:
            1. Identifique a "Data de Aprovação da Anvisa" nos dois textos. Se não achar, retorne "Não encontrada".
            2. Mapeie o TEXTO 2 nas seções da lista: {SECOES_PACIENTE}
            3. Compare o conteúdo.
            4. CORRIJA a formatação (remova quebras de linha erradas).

            REGRAS DE STATUS:
            - "APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS": Status "CONFORME". Apenas transcreva.
            - "DIZERES LEGAIS": Transcreva o texto, MAS NÃO COLOQUE "N/A" se faltar data. A data vai apenas no campo específico do JSON.
            - OUTRAS SEÇÕES: Status "CONFORME" ou "DIVERGENTE".
            - Highlights: <span class="highlight-yellow">TEXTO</span> (Divergência), <span class="highlight-red">TEXTO</span> (Erro PT).

            SAÍDA JSON:
            {{
                "data_anvisa_ref": "dd/mm/aaaa" ou "Não encontrada",
                "data_anvisa_mkt": "dd/mm/aaaa" ou "Não encontrada",
                "secoes": [
                    {{
                        "titulo": "NOME DA SEÇÃO",
                        "texto_anvisa": "Texto limpo",
                        "texto_mkt": "Texto limpo com highlights",
                        "status": "CONFORME" ou "DIVERGENTE"
                    }}
                ]
            }}
            """
            
            try:
                response = model.generate_content(prompt)
                res = json.loads(response.text)
                
                # Dados Principais
                data_ref = res.get("data_anvisa_ref", "Não encontrada")
                data_mkt = res.get("data_anvisa_mkt", "Não encontrada")
                secoes = res.get("secoes", [])

                # --- RENDERIZAÇÃO DO PAINEL (IGUAL À FOTO) ---
                
                # Linha 1: Métricas
                m1, m2, m3 = st.columns(3)
                m1.metric("Data Anvisa (Ref)", data_ref)
                m2.metric("Data Anvisa (MKT)", data_mkt)
                m3.metric("Seções Analisadas", len(secoes))
                
                # Linha 2: Barras de Status
                divergentes = sum(1 for s in secoes if s['status'] != 'CONFORME')
                conformes = len(secoes) - divergentes
                
                b1, b2 = st.columns(2)
                b1.markdown(f"""
                <div class="status-bar-ok">
                    ✅ Conformes: {conformes}
                </div>
                """, unsafe_allow_html=True)
                
                if divergentes > 0:
                     b2.markdown(f"""
                    <div class="status-bar-warn" style="color: #c5221f; background-color: #fce8e6; border-color: #fad2cf;">
                        ⚠️ Divergentes: {divergentes}
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    b2.markdown(f"""
                    <div class="status-bar-warn" style="color: #856404; background-color: #fff3cd;">
                        ✨ Divergentes: 0
                    </div>
                    """, unsafe_allow_html=True)

                st.write("") # Espaço
                
                # --- LISTA DE SEÇÕES ---
                for item in secoes:
                    status = item.get('status', 'CONFORME')
                    titulo = item.get('titulo', 'Seção')
                    
                    if "DIZERES LEGAIS" in titulo.upper():
                        icon, css, open_tab = "⚖️", "border-info", True
                    elif status == "CONFORME":
                        icon, css, open_tab = "✅", "border-ok", False
                    else:
                        icon, css, open_tab = "⚠️", "border-warn", True

                    with st.expander(f"{icon} {titulo}", expanded=open_tab):
                        c_esq, c_dir = st.columns(2)
                        with c_esq:
                            st.caption("Bula Anvisa")
                            st.markdown(f'<div class="texto-box {css}">{item.get("texto_anvisa", "")}</div>', unsafe_allow_html=True)
                        with c_dir:
                            st.caption("Arte MKT")
                            st.markdown(f'<div class="texto-box {css}">{item.get("texto_mkt", "")}</div>', unsafe_allow_html=True)

            except Exception as e:
                st.error(f"Erro ao processar JSON: {e}")
    else:
        st.warning("Adicione os arquivos PDF (Texto).")
