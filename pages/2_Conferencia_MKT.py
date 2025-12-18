import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
import json

# ----------------- 1. VISUAL & CSS (Igual ao Visual Lado a Lado) -----------------
st.set_page_config(page_title="MKT Estruturado", page_icon="📢", layout="wide")

st.markdown("""
<style>
    /* Caixas de Texto */
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
    }

    /* Destaques (Marca-textos) */
    .highlight-yellow { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 3px; border: 1px solid #ffeeba; }
    .highlight-red { background-color: #f8d7da; color: #721c24; padding: 2px 4px; border-radius: 3px; border: 1px solid #f5c6cb; font-weight: bold; }
    .highlight-blue { background-color: #d1ecf1; color: #0c5460; padding: 2px 4px; border-radius: 3px; border: 1px solid #bee5eb; font-weight: bold; }

    /* Bordas de Status */
    .border-ok { border-left: 6px solid #28a745 !important; }   /* Verde */
    .border-warn { border-left: 6px solid #ffc107 !important; } /* Amarelo */
    .border-info { border-left: 6px solid #17a2b8 !important; } /* Azul (Info) */
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
            # Temperatura 0.0 para garantir fidelidade ao texto extraído
            return genai.GenerativeModel(
                MODELO_FIXO, 
                generation_config={"response_mime_type": "application/json", "temperature": 0.0}
            )
        except: continue
    return None

# ----------------- 3. EXTRAÇÃO DE TEXTO (PDF -> STRING) -----------------
def extract_text_from_pdf(uploaded_file):
    try:
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        text = ""
        for page in doc:
            text += page.get_text("text") + "\n"
        return text
    except: return ""

# LISTA OFICIAL DE SEÇÕES
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
st.title("📢 Conferência MKT (Estruturada)")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Anvisa (Referência)", type=["pdf"], key="f1")
f2 = c2.file_uploader("🎨 Arte MKT (Para Validar)", type=["pdf"], key="f2")

if st.button("🚀 Estruturar e Validar"):
    if f1 and f2:
        model = setup_model()
        if not model:
            st.error("Sem chave API.")
            st.stop()

        with st.spinner("Extraindo textos e organizando nas seções..."):
            # 1. Pega o texto cru dos PDFs
            t_anvisa = extract_text_from_pdf(f1)
            t_mkt = extract_text_from_pdf(f2)

            if len(t_anvisa) < 50 or len(t_mkt) < 50:
                st.error("Erro: Um dos arquivos não tem texto selecionável (pode ser imagem).")
                st.stop()
            
            # 2. PROMPT PARA ORGANIZAR E VALIDAR
            prompt = f"""
            Você é um Revisor Farmacêutico. 
            Tenho dois textos brutos extraídos de PDF:
            TEXTO 1 (ANVISA/REF): {t_anvisa[:50000]}
            TEXTO 2 (MKT/VAL): {t_mkt[:30000]}

            SUA TAREFA:
            1. Identifique no TEXTO 2 (MKT) o conteúdo correspondente a cada seção da lista abaixo.
            2. Compare com o TEXTO 1.
            
            LISTA DE SEÇÕES: {SECOES_PACIENTE}

            ⚠️ REGRAS ESPECÍFICAS DE STATUS E VISUALIZAÇÃO:

            GRUPO A (Não Comparar): ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]
            - Defina status sempre como "CONFORME".
            - Apenas transcreva o conteúdo completo encontrado.
            - REGRA ESPECIAL PARA 'DIZERES LEGAIS':
                - Procure a data da Anvisa (ex: "aprovado em dd/mm/aaaa").
                - Se achar, envolva com <span class="highlight-blue">DATA</span>.
                - Se NÃO achar, escreva "N/A" no final do texto.

            GRUPO B (Comparar Rigorosamente): [TODAS AS OUTRAS]
            - Compare o conteúdo. Se o MKT omitiu avisos importantes ou mudou o sentido, status "DIVERGENTE".
            - Use <span class="highlight-yellow">TEXTO</span> para divergências de conteúdo.
            - Use <span class="highlight-red">TEXTO</span> para erros de português.
            - Se a seção não existir no MKT (comum em peças publicitárias), coloque "Não consta na peça" e status "CONFORME" (pois MKT nem sempre tem tudo).

            SAÍDA JSON ARRAY:
            [
                {{
                    "titulo": "NOME DA SEÇÃO",
                    "texto_anvisa": "Conteúdo completo da Anvisa",
                    "texto_mkt": "Conteúdo completo do MKT com highlights",
                    "status": "CONFORME" ou "DIVERGENTE"
                }}
            ]
            """
            
            try:
                response = model.generate_content(prompt)
                dados = json.loads(response.text)

                st.write("")
                
                # Métricas
                total = len(dados)
                divergentes = sum(1 for d in dados if d['status'] != 'CONFORME')
                
                k1, k2, k3 = st.columns(3)
                k1.metric("Seções Mapeadas", total)
                k2.metric("Conformes", total - divergentes)
                k3.metric("Divergências", divergentes, delta_color="inverse")
                st.divider()

                # Renderização Visual
                for item in dados:
                    status = item.get('status', 'CONFORME')
                    titulo = item.get('titulo', 'Seção')
                    
                    # Definição visual (ícone e borda)
                    if "DIZERES LEGAIS" in titulo.upper():
                        icon = "📅"
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
                st.error(f"Erro no processamento: {e}")
    else:
        st.warning("Envie os dois PDFs.")
