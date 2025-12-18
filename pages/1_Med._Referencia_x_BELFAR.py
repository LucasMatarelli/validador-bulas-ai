import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
import json

# ----------------- 1. VISUAL & CSS (Design Padronizado) -----------------
st.set_page_config(page_title="Ref x BELFAR", page_icon="💊", layout="wide")

st.markdown("""
<style>
    /* Caixas de Texto */
    .texto-box { 
        font-family: 'Segoe UI', sans-serif;
        font-size: 0.95rem;
        line-height: 1.6;
        color: #212529;
        background-color: #ffffff;
        padding: 18px;
        border-radius: 8px;
        border: 1px solid #e0e0e0;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        white-space: pre-wrap; /* Mantém parágrafos corretos */
        text-align: justify;
    }

    /* Destaques */
    .highlight-yellow { background-color: #fff9c4; color: #000; padding: 2px 4px; border-radius: 4px; border: 1px solid #fbc02d; }
    .highlight-red { background-color: #ffcdd2; color: #b71c1c; padding: 2px 4px; border-radius: 4px; border: 1px solid #b71c1c; font-weight: bold; }
    .highlight-blue { background-color: #bbdefb; color: #0d47a1; padding: 2px 4px; border-radius: 4px; border: 1px solid #1976d2; font-weight: bold; }

    /* Bordas de Status */
    .border-ok { border-left: 6px solid #4caf50 !important; }   /* Verde */
    .border-warn { border-left: 6px solid #ff9800 !important; } /* Laranja */
    .border-info { border-left: 6px solid #2196f3 !important; } /* Azul */

    /* Card de Métricas */
    div[data-testid="stMetric"] {
        background-color: #f8f9fa;
        border: 1px solid #dee2e6;
        padding: 10px;
        border-radius: 5px;
        text-align: center;
    }
</style>
""", unsafe_allow_html=True)

# ----------------- 2. CONFIGURAÇÃO MODELO -----------------
MODELO_FIXO = "models/gemini-flash-latest"

def setup_model():
    keys = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2")]
    valid_keys = [k for k in keys if k is not None]

    if not valid_keys: return None

    # Tenta conectar com as chaves disponíveis
    for api_key in valid_keys:
        try:
            genai.configure(api_key=api_key)
            return genai.GenerativeModel(
                MODELO_FIXO, 
                generation_config={"response_mime_type": "application/json", "temperature": 0.0}
            )
        except: continue
    return None

# ----------------- 3. EXTRAÇÃO DE TEXTO -----------------
def get_text_from_pdf(file):
    try:
        doc = fitz.open(stream=file.read(), filetype="pdf")
        text = ""
        for page in doc:
            text += page.get_text("text") + "\n"
        return text
    except: return ""

# ----------------- 4. LISTAS DE SEÇÕES -----------------
SECOES_PACIENTE = [
    "APRESENTAÇÕES", "COMPOSIÇÃO", "PARA QUE ESTE MEDICAMENTO É INDICADO", 
    "COMO ESTE MEDICAMENTO FUNCIONA?", "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?", 
    "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?", "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?", 
    "COMO DEVO USAR ESTE MEDICAMENTO?", "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?", 
    "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?", 
    "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?", "DIZERES LEGAIS"
]

SECOES_PROFISSIONAL = [
    "APRESENTAÇÕES", "COMPOSIÇÃO", "INDICAÇÕES", "RESULTADOS DE EFICÁCIA", 
    "CARACTERÍSTICAS FARMACOLÓGICAS", "CONTRAINDICAÇÕES", "ADVERTÊNCIAS E PRECAUÇÕES", 
    "INTERAÇÕES MEDICAMENTOSAS", "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO", 
    "POSOLOGIA E MODO DE USAR", "REAÇÕES ADVERSAS", "SUPERDOSE", "DIZERES LEGAIS"
]

# ----------------- 5. UI PRINCIPAL -----------------
st.title("💊 Ref x BELFAR (Texto Estruturado)")
st.caption(f"Modelo Ativo: {MODELO_FIXO}")

# 1. Upload
c1, c2 = st.columns(2)
f1 = c1.file_uploader("📂 Referência (PDF)", type="pdf", key="f1")
f2 = c2.file_uploader("📂 Belfar (PDF)", type="pdf", key="f2")

# 2. Escolha do Tipo de Bula
tipo_bula = st.radio("Tipo de Bula:", ["Paciente", "Profissional"], horizontal=True)
secoes_alvo = SECOES_PACIENTE if tipo_bula == "Paciente" else SECOES_PROFISSIONAL

if st.button("🚀 Iniciar Auditoria"):
    if f1 and f2:
        model = setup_model()
        if not model:
            st.error("Erro: Sem chaves API configuradas.")
            st.stop()

        with st.spinner("Extraindo textos e analisando..."):
            t_ref = get_text_from_pdf(f1)
            t_bel = get_text_from_pdf(f2)
        
        if len(t_ref) < 50 or len(t_bel) < 50:
            st.error("⚠️ Texto insuficiente. Verifique se os arquivos são PDFs de texto (não imagem).")
        else:
            # PROMPT PADRONIZADO
            prompt = f"""
            Você é um Auditor Farmacêutico. 
            
            INPUT:
            === TEXTO REFERÊNCIA ===
            {t_ref[:50000]}
            
            === TEXTO BELFAR ===
            {t_bel[:50000]}

            SUA MISSÃO:
            1. Mapeie o texto da BELFAR nas seções abaixo.
            2. Compare com o texto da REFERÊNCIA.
            3. Corrija a formatação (remova quebras de linha erradas).

            LISTA DE SEÇÕES: {secoes_alvo}

            REGRAS DE COMPARAÇÃO:
            - GRUPO 1 ("APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS", "RESULTADOS DE EFICÁCIA", "CARACTERÍSTICAS FARMACOLÓGICAS"):
                * Status SEMPRE "CONFORME". Apenas transcreva o texto da BELFAR.
                * DIZERES LEGAIS: Procure a Data da Anvisa (dd/mm/aaaa). Se achar, envolva com <span class="highlight-blue">DATA</span>. Se não achar, não escreva nada. Extraia a data também separadamente.
            
            - GRUPO 2 (Outras Seções):
                * Compare o conteúdo.
                * Divergências de sentido/texto: <span class="highlight-yellow">TEXTO</span>.
                * Erros de PT: <span class="highlight-red">TEXTO</span>.

            SAÍDA JSON:
            {{
                "data_anvisa_ref": "dd/mm/aaaa" (ou "Não encontrada"),
                "data_anvisa_bel": "dd/mm/aaaa" (ou "Não encontrada"),
                "secoes": [
                    {{
                        "titulo": "NOME DA SEÇÃO",
                        "texto_ref": "Texto da Referência formatado",
                        "texto_bel": "Texto Belfar formatado com highlights",
                        "status": "CONFORME" ou "DIVERGENTE"
                    }}
                ]
            }}
            """
            
            try:
                response = model.generate_content(prompt)
                data = json.loads(response.text)
                
                # Extração
                d_ref = data.get("data_anvisa_ref", "-")
                d_bel = data.get("data_anvisa_bel", "-")
                lista_secoes = data.get("secoes", [])

                # --- RESUMO (TOPO) ---
                st.markdown("### 📊 Relatório de Auditoria")
                
                k1, k2, k3 = st.columns(3)
                k1.metric("Data Anvisa (Ref)", d_ref)
                
                cor_delta = "normal" if d_ref == d_bel and d_ref != "Não encontrada" else "inverse"
                msg_delta = "Vigência" if d_ref == d_bel else "Diferente"
                if d_bel == "Não encontrada": msg_delta = ""
                
                k2.metric("Data Anvisa (Belfar)", d_bel, delta=msg_delta, delta_color=cor_delta)
                k3.metric("Seções Analisadas", len(lista_secoes))

                div_count = sum(1 for s in lista_secoes if s['status'] != 'CONFORME')
                ok_count = len(lista_secoes) - div_count

                b1, b2 = st.columns(2)
                b1.success(f"✅ **Conformes: {ok_count}**")
                if div_count > 0:
                    b2.warning(f"⚠️ **Divergentes: {div_count}**")
                else:
                    b2.success("✨ **Divergentes: 0**")
                
                st.divider()

                # --- LISTA DE SEÇÕES (LADO A LADO) ---
                for item in lista_secoes:
                    status = item.get('status', 'CONFORME')
                    titulo = item.get('titulo', 'Seção')
                    
                    if "DIZERES LEGAIS" in titulo.upper():
                        icon, css, aberto = "📅", "border-info", True
                    elif status == "CONFORME":
                        icon, css, aberto = "✅", "border-ok", False
                    else:
                        icon, css, aberto = "⚠️", "border-warn", True

                    with st.expander(f"{icon} {titulo}", expanded=aberto):
                        col_esq, col_dir = st.columns(2)
                        
                        with col_esq:
                            st.caption("Referência")
                            st.markdown(f'<div class="texto-box {css}">{item.get("texto_ref", "")}</div>', unsafe_allow_html=True)
                        
                        with col_dir:
                            st.caption("Belfar (Validado)")
                            st.markdown(f'<div class="texto-box {css}">{item.get("texto_bel", "")}</div>', unsafe_allow_html=True)

            except Exception as e:
                st.error(f"Erro na análise: {e}")

    else:
        st.warning("Envie os dois arquivos PDF.")
