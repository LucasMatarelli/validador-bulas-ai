import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
import json

# ----------------- 1. CONFIGURAÇÃO VISUAL (Estilo Gráfica x Arte) -----------------
st.set_page_config(page_title="Conferência MKT", page_icon="📊", layout="wide")

st.markdown("""
<style>
    /* Caixas de Texto - Estilo "Bonitinho" */
    .texto-box { 
        font-family: 'Segoe UI', sans-serif;
        font-size: 0.95rem;
        line-height: 1.6;
        color: #212529;
        background-color: #ffffff;
        padding: 20px;
        border-radius: 8px;
        border: 1px solid #ced4da;
        height: 100%; 
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        white-space: pre-wrap; /* Mantém parágrafos */
        text-align: justify;
    }

    /* Destaques (Marca-textos) */
    .highlight-yellow { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 3px; border: 1px solid #ffeeba; }
    .highlight-red { background-color: #f8d7da; color: #721c24; padding: 2px 4px; border-radius: 3px; border: 1px solid #f5c6cb; font-weight: bold; }
    .highlight-blue { background-color: #d1ecf1; color: #0c5460; padding: 2px 4px; border-radius: 3px; border: 1px solid #bee5eb; font-weight: bold; }

    /* Status das Bordas */
    .border-ok { border-left: 6px solid #28a745 !important; }   /* Verde */
    .border-warn { border-left: 6px solid #ffc107 !important; } /* Amarelo */
    .border-info { border-left: 6px solid #17a2b8 !important; } /* Azul (Info) */

    /* Estilo das Métricas (Igual da foto) */
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
    valid_keys = [k for k in keys if k]
    
    for api_key in valid_keys:
        try:
            genai.configure(api_key=api_key)
            return genai.GenerativeModel(
                MODELO_FIXO, 
                generation_config={"response_mime_type": "application/json", "temperature": 0.0}
            )
        except: continue
    return None

# ----------------- 3. EXTRAÇÃO DE TEXTO (MKT usa Texto Puro, não Imagem) -----------------
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

# ----------------- 4. UI PRINCIPAL -----------------
st.title("📊 Conferência MKT (Texto vs Texto)")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Anvisa (Referência)", type=["pdf"], key="f1")
f2 = c2.file_uploader("🎨 Arte MKT (Para Validar)", type=["pdf"], key="f2")

if st.button("🚀 Processar Conferência"):
    if f1 and f2:
        model = setup_model()
        if not model:
            st.error("Sem chave API.")
            st.stop()

        with st.spinner("Extraindo textos e gerando painel de conferência..."):
            t_anvisa = extract_text_from_pdf(f1)
            t_mkt = extract_text_from_pdf(f2)

            if len(t_anvisa) < 50 or len(t_mkt) < 50:
                st.error("Erro: Arquivo vazio ou ilegível (Verifique se não é imagem escaneada).")
                st.stop()

            # PROMPT ESPECÍFICO PARA MKT (TEXTO)
            prompt = f"""
            Você é um Revisor Farmacêutico Meticuloso.
            
            TEXTO 1 (ANVISA/REF): {t_anvisa[:50000]}
            TEXTO 2 (MKT/VAL): {t_mkt[:30000]}

            SUA MISSÃO:
            1. Encontre a "Data de Aprovação da Anvisa" nos Dizeres Legais de AMBOS.
            2. Mapeie o conteúdo do TEXTO 2 (MKT) nas seções da lista: {SECOES_PACIENTE}
            3. Compare com o TEXTO 1.
            4. CORRIJA A FORMATAÇÃO: Junte as linhas quebradas erradas dos PDFs para formar parágrafos fluidos.

            REGRAS DE STATUS:
            - "APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS": Status SEMPRE "CONFORME". Apenas transcreva o texto limpo.
            - DIZERES LEGAIS: NÃO adicione "N/A" ou "Data não encontrada" no corpo do texto. Deixe apenas o texto legal. A data deve ir apenas para o campo de dados JSON separado.
            - OUTRAS SEÇÕES: Compare rigorosamente. Use <span class="highlight-yellow">TEXTO</span> para divergências e <span class="highlight-red">TEXTO</span> para erros.

            SAÍDA JSON:
            {{
                "data_anvisa_ref": "dd/mm/aaaa" (ou "Não encontrada"),
                "data_anvisa_mkt": "dd/mm/aaaa" (ou "Não encontrada"),
                "secoes": [
                    {{
                        "titulo": "NOME DA SEÇÃO",
                        "texto_anvisa": "Texto formatado (sem quebras erradas)",
                        "texto_mkt": "Texto formatado (sem quebras erradas) com highlights",
                        "status": "CONFORME" ou "DIVERGENTE"
                    }}
                ]
            }}
            """
            
            try:
                response = model.generate_content(prompt)
                resultado = json.loads(response.text)
                
                # Extrai dados
                data_ref = resultado.get("data_anvisa_ref", "Não encontrada")
                data_mkt = resultado.get("data_anvisa_mkt", "Não encontrada")
                dados_secoes = resultado.get("secoes", [])

                # --- 1. PAINEL DE MÉTRICAS (Igual à foto) ---
                st.markdown("### 📊 Resumo da Conferência")
                
                c_d1, c_d2, c_d3 = st.columns(3)
                c_d1.metric("Data Anvisa (Ref)", data_ref)
                c_d2.metric("Data Anvisa (MKT)", data_mkt)
                
                total = len(dados_secoes)
                divergentes = sum(1 for d in dados_secoes if d['status'] != 'CONFORME')
                c_d3.metric("Seções Analisadas", total)

                # --- 2. BARRA DE STATUS (Igual à foto) ---
                sub1, sub2 = st.columns(2)
                sub1.success(f"✅ Conformes: {total - divergentes}")
                
                if divergentes > 0:
                    sub2.warning(f"⚠️ Divergentes: {divergentes}")
                else:
                    sub2.success("✨ Divergentes: 0")

                st.divider()

                # --- 3. SEÇÕES LADO A LADO ---
                for item in dados_secoes:
                    status = item.get('status', 'CONFORME')
                    titulo = item.get('titulo', 'Seção')
                    
                    # Definição visual
                    if "DIZERES LEGAIS" in titulo.upper():
                        icon = "⚖️"
                        css = "border-info"
                        aberto = True
                    elif status == "CONFORME":
                        icon = "✅"
                        css = "border-ok"
                        aberto = False
                    else:
                        icon = "⚠️"
                        css = "border-warn"
                        aberto = True

                    with st.expander(f"{icon} {titulo}", expanded=aberto):
                        col_esq, col_dir = st.columns(2)
                        
                        with col_esq:
                            st.caption("📜 Bula Anvisa (Referência)")
                            st.markdown(f'<div class="texto-box {css}">{item.get("texto_anvisa", "")}</div>', unsafe_allow_html=True)
                            
                        with col_dir:
                            st.caption("🎨 Arte MKT (Validado)")
                            st.markdown(f'<div class="texto-box {css}">{item.get("texto_mkt", "")}</div>', unsafe_allow_html=True)

            except Exception as e:
                st.error(f"Erro ao processar: {e}")
                st.warning("O modelo pode ter retornado um JSON inválido. Tente novamente.")
    else:
        st.warning("Adicione os arquivos PDF.")
