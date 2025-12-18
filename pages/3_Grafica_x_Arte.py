import streamlit as st
import google.generativeai as genai
from PIL import Image
import fitz  # PyMuPDF
import io
import json

# ----------------- 1. CONFIGURAÇÃO VISUAL -----------------
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
    }

    /* Destaques */
    .highlight-yellow { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 3px; border: 1px solid #ffeeba; }
    .highlight-red { background-color: #f8d7da; color: #721c24; padding: 2px 4px; border-radius: 3px; border: 1px solid #f5c6cb; font-weight: bold; }
    .highlight-blue { background-color: #d1ecf1; color: #0c5460; padding: 2px 4px; border-radius: 3px; border: 1px solid #bee5eb; font-weight: bold; }

    /* Status das Bordas */
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
            return genai.GenerativeModel(
                MODELO_FIXO, 
                # Temperatura 0.0 para não inventar nada
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
            pix = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5))
            images.append(Image.open(io.BytesIO(pix.tobytes("jpeg"))))
        return images
    except: return []

# LISTA DE TODAS AS SEÇÕES
SECOES_COMPLETAS = [
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
st.title("💊 Validador de Bulas (Regras Específicas)")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📂 Arte (Original)", type=["pdf", "jpg", "png"])
f2 = c2.file_uploader("📂 Gráfica (Prova)", type=["pdf", "jpg", "png"])

if st.button("🚀 Validar"):
    if f1 and f2:
        model = setup_model()
        if not model:
            st.error("Erro de API Key.")
            st.stop()

        with st.spinner("Analisando seções conforme regras de negócio..."):
            imgs1 = pdf_to_images(f1) if f1.name.endswith(".pdf") else [Image.open(f1)]
            imgs2 = pdf_to_images(f2) if f2.name.endswith(".pdf") else [Image.open(f2)]
            
            # PROMPT COM AS NOVAS REGRAS DE NEGÓCIO
            prompt = f"""
            Você é um auditor farmacêutico rigoroso. Analise as imagens.
            
            SEÇÕES PARA ANALISAR: {SECOES_COMPLETAS}

            ⚠️ REGRAS ESPECÍFICAS POR GRUPO DE SEÇÃO:

            GRUPO 1: ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]
            - NESTAS SEÇÕES, NÃO COMPARE O TEXTO EM BUSCA DE ERROS.
            - Status deve ser SEMPRE "CONFORME".
            - Apenas transcreva o texto da Gráfica.
            - REGRA ESPECIAL "DIZERES LEGAIS": 
                Procure a frase "Esta bula foi aprovada pela Anvisa em...". 
                Se encontrar a data, marque com <span class="highlight-blue">DATA</span>.
                Se NÃO encontrar data nenhuma, adicione o texto "N/A" ao final.

            GRUPO 2: [TODAS AS OUTRAS SEÇÕES]
            - Comparação rigorosa ARTE vs GRÁFICA.
            - Marque divergências (texto extra/faltante) com <span class="highlight-yellow">TEXTO</span>.
            - Marque erros de português com <span class="highlight-red">TEXTO</span>.
            - Capture avisos de "Atenção" até o próximo título.

            SAÍDA JSON:
            [
              {{
                "titulo": "NOME DA SEÇÃO",
                "texto_arte": "Texto extraído da arte",
                "texto_grafica": "Texto da gráfica (com highlights se aplicável)",
                "status": "CONFORME" ou "DIVERGENTE"
              }}
            ]
            """
            
            payload = [prompt, "--- ARTE ---"] + imgs1 + ["--- GRAFICA ---"] + imgs2
            
            try:
                response = model.generate_content(payload)
                dados = json.loads(response.text)

                st.write("")
                
                # Métricas
                total = len(dados)
                # Conta divergentes ignorando os falsos positivos das seções 'blindadas'
                divergentes = sum(1 for d in dados if d['status'] != 'CONFORME')
                
                k1, k2, k3 = st.columns(3)
                k1.metric("Total Seções", total)
                k2.metric("Aprovadas", total - divergentes)
                k3.metric("Divergentes", divergentes, delta_color="inverse")
                st.divider()

                for item in dados:
                    status = item.get('status', 'CONFORME')
                    titulo = item.get('titulo', 'Seção')
                    
                    # Lógica Visual dos Ícones e Cores
                    if "DIZERES LEGAIS" in titulo.upper():
                        icon = "📅" # Ícone de calendário para data
                        css = "border-info" # Azul
                        # Força visualização aberta se tiver data ou N/A
                        expandir = True 
                    elif status == "CONFORME":
                        icon = "✅"
                        css = "border-ok" # Verde
                        expandir = False
                    else:
                        icon = "⚠️"
                        css = "border-warn" # Amarelo/Vermelho
                        expandir = True

                    with st.expander(f"{icon} {titulo}", expanded=expandir):
                        col_esq, col_dir = st.columns(2)
                        
                        with col_esq:
                            st.caption("Referência (Arte)")
                            st.markdown(f'<div class="texto-box {css}">{item.get("texto_arte", "")}</div>', unsafe_allow_html=True)
                            
                        with col_dir:
                            st.caption("Validação (Gráfica)")
                            st.markdown(f'<div class="texto-box {css}">{item.get("texto_grafica", "")}</div>', unsafe_allow_html=True)

            except Exception as e:
                st.error(f"Erro no processamento: {e}")

    else:
        st.warning("Adicione os arquivos.")
