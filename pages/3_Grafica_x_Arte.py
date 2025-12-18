import streamlit as st
import google.generativeai as genai
from PIL import Image
import fitz  # PyMuPDF
import io
import json

# ----------------- 1. VISUAL & CSS -----------------
st.set_page_config(page_title="Validador Farmacêutico", page_icon="💊", layout="wide")

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
        white-space: pre-wrap; /* Mantém parágrafos originais */
        text-align: justify;
    }

    /* Destaques Precisos */
    .highlight-yellow { 
        background-color: #fff3cd; color: #856404; 
        padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; 
    }
    .highlight-red { 
        background-color: #f8d7da; color: #721c24; 
        padding: 2px 4px; border-radius: 4px; border: 1px solid #f5c6cb; font-weight: bold; 
    }
    .highlight-blue { 
        background-color: #d1ecf1; color: #0c5460; 
        padding: 2px 4px; border-radius: 4px; border: 1px solid #bee5eb; font-weight: bold; 
    }

    /* Status das Bordas */
    .border-ok { border-left: 6px solid #28a745 !important; }   /* Verde */
    .border-warn { border-left: 6px solid #ffc107 !important; } /* Amarelo */
    .border-info { border-left: 6px solid #17a2b8 !important; } /* Azul */

    /* Métricas no Topo */
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
                # CRÍTICO: Temperatura 0.0 elimina a criatividade (invenção)
                generation_config={"response_mime_type": "application/json", "temperature": 0.0}
            )
        except: continue
    return None

# ----------------- 3. PROCESSAMENTO -----------------
def pdf_to_images(uploaded_file):
    try:
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        images = []
        for page in doc:
            # Aumentei o Zoom para 3.0 (300 DPI) para ele ler letras miúdas de bula
            pix = page.get_pixmap(matrix=fitz.Matrix(3.0, 3.0))
            images.append(Image.open(io.BytesIO(pix.tobytes("jpeg"))))
        return images
    except: return []

# LISTA EXATA NA ORDEM DA BULA (IMPORTANTE PARA O ROBÔ SABER ONDE PARAR)
SECOES_COMPLETAS = [
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

# ----------------- 4. UI PRINCIPAL -----------------
st.title("💊 Validador de Bulas (Gráfica x Arte)")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📂 Arte (Original)", type=["pdf", "jpg", "png"])
f2 = c2.file_uploader("📂 Gráfica (Prova)", type=["pdf", "jpg", "png"])

if st.button("🚀 Validar"):
    if f1 and f2:
        model = setup_model()
        if not model:
            st.error("Erro de API Key.")
            st.stop()

        with st.spinner("Realizando leitura integral (OCR Forense)..."):
            imgs1 = pdf_to_images(f1) if f1.name.endswith(".pdf") else [Image.open(f1)]
            imgs2 = pdf_to_images(f2) if f2.name.endswith(".pdf") else [Image.open(f2)]
            
            # PROMPT BLINDADO
            prompt = f"""
            Você é um Scanner OCR Forense. Sua tarefa NÃO é interpretar, é TRANSCREVER.
            
            INPUT: Imagens da bula.
            TAREFA: Extrair texto EXATO das seções abaixo.

            LISTA DE TÍTULOS (ORDEM DE LEITURA): 
            {SECOES_COMPLETAS}

            ⚠️ REGRAS DE EXTRAÇÃO (CRÍTICO):
            1. **ONDE COMEÇA E ONDE TERMINA:**
               - Para extrair a seção X, encontre o título X.
               - Copie TUDO o que vier depois dele (parágrafos, quadros de "Atenção", notas de rodapé).
               - **SÓ PARE** quando encontrar o TÍTULO da próxima seção da lista.
               - Se for "DIZERES LEGAIS", copie até o fim da página.
            
            2. **FIDELIDADE TOTAL:**
               - Não corrija erros. Se está escrito "Inflamasão", copie "Inflamasão".
               - Não invente palavras. Se a imagem está borrada, não adivinhe.

            REGRAS DE COMPARAÇÃO (ARTE vs GRÁFICA):
            - GRUPO 1 ("APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"):
                * Status SEMPRE "CONFORME".
                * Apenas transcreva o texto completo encontrado.
                * "DIZERES LEGAIS": Procure a data da Anvisa (ex: aprovado em dd/mm/aaaa). Se achar, extraia para o campo de data e marque de <span class="highlight-blue">AZUL</span> no texto. Se não achar, não marque nada.
            
            - GRUPO 2 (Todas as outras):
                * Comparação palavra por palavra.
                * Divergência (ex: "não" extra): Marque <span class="highlight-yellow">APENAS A PALAVRA</span>.
                * Erro ortográfico: Marque <span class="highlight-red">APENAS A PALAVRA</span>.

            SAÍDA JSON:
            {{
                "data_anvisa_ref": "dd/mm/aaaa" (ou "Não encontrada"),
                "data_anvisa_grafica": "dd/mm/aaaa" (ou "Não encontrada"),
                "secoes": [
                    {{
                        "titulo": "NOME DA SEÇÃO",
                        "texto_arte": "Texto COMPLETO extraído da arte",
                        "texto_grafica": "Texto COMPLETO da gráfica com highlights",
                        "status": "CONFORME" ou "DIVERGENTE"
                    }}
                ]
            }}
            """
            
            try:
                payload = [prompt, "--- ARTE ---"] + imgs1 + ["--- GRAFICA ---"] + imgs2
                response = model.generate_content(payload)
                resultado = json.loads(response.text)
                
                # Extração de dados
                data_ref = resultado.get("data_anvisa_ref", "Não encontrada")
                data_graf = resultado.get("data_anvisa_grafica", "Não encontrada")
                secoes = resultado.get("secoes", [])

                # --- 1. RESUMO NO TOPO ---
                st.markdown("### 📊 Resumo da Conferência")
                
                k1, k2, k3 = st.columns(3)
                k1.metric("Data Anvisa (Ref)", data_ref)
                
                cor_delta = "normal" if data_ref == data_graf and data_ref != "Não encontrada" else "inverse"
                msg_delta = "Vigência" if data_ref == data_graf else "Diferente"
                if data_graf == "Não encontrada": msg_delta = ""
                
                k2.metric("Data Anvisa (Gráfica)", data_graf, delta=msg_delta, delta_color=cor_delta)
                k3.metric("Seções Analisadas", len(secoes))

                div_count = sum(1 for s in secoes if s['status'] != 'CONFORME')
                ok_count = len(secoes) - div_count
                
                b1, b2 = st.columns(2)
                b1.success(f"✅ **Conformes: {ok_count}**")
                if div_count > 0:
                    b2.warning(f"⚠️ **Divergentes: {div_count}**")
                else:
                    b2.success("✨ **Divergentes: 0**")
                
                st.divider()

                # --- 2. LISTA DE SEÇÕES ---
                for item in secoes:
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
                            st.caption("Referência (Arte)")
                            st.markdown(f'<div class="texto-box {css}">{item.get("texto_arte", "")}</div>', unsafe_allow_html=True)
                        with col_dir:
                            st.caption("Validação (Gráfica)")
                            st.markdown(f'<div class="texto-box {css}">{item.get("texto_grafica", "")}</div>', unsafe_allow_html=True)

            except Exception as e:
                st.error(f"Erro no processamento: {e}")
                st.warning("Dica: Se o erro persistir, o arquivo pode estar muito pesado. Tente cortar as páginas.")

    else:
        st.warning("Adicione os arquivos.")
