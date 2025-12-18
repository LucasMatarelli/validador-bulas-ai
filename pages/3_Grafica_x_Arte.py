import streamlit as st
import google.generativeai as genai
from PIL import Image
import fitz  # PyMuPDF
import io
import json

# ----------------- 1. VISUAL & CSS (O segredo do Design) -----------------
st.set_page_config(page_title="Validador Visual", page_icon="⚖️", layout="wide")

st.markdown("""
<style>
    /* Estilo das caixas de texto */
    .texto-box { 
        font-family: 'Segoe UI', sans-serif;
        font-size: 0.95rem;
        line-height: 1.6;
        color: #333;
        background-color: #ffffff;
        padding: 15px;
        border-radius: 8px;
        border: 1px solid #e0e0e0;
        height: 100%; /* Para alinhar altura */
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }

    /* CORES DOS MARCA-TEXTOS (Funcionam dentro do HTML) */
    .highlight-yellow { 
        background-color: #fff9c4; color: #000; 
        padding: 2px 4px; border-radius: 4px; border: 1px solid #fbc02d; 
    }
    .highlight-red { 
        background-color: #ffcdd2; color: #b71c1c; 
        padding: 2px 4px; border-radius: 4px; border: 1px solid #b71c1c; font-weight: bold; 
    }
    .highlight-blue { 
        background-color: #bbdefb; color: #0d47a1; 
        padding: 2px 4px; border-radius: 4px; border: 1px solid #1976d2; font-weight: bold; 
    }

    /* Bordas laterais para indicar Status */
    .border-ok { border-left: 5px solid #4caf50 !important; }
    .border-warn { border-left: 5px solid #ff9800 !important; }
    .border-info { border-left: 5px solid #2196f3 !important; }
</style>
""", unsafe_allow_html=True)

# ----------------- 2. MODELO GEMINI -----------------
MODELO_FIXO = "models/gemini-flash-latest"

def setup_model():
    keys = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2")]
    valid_keys = [k for k in keys if k]
    
    for api_key in valid_keys:
        try:
            genai.configure(api_key=api_key)
            # IMPORTANTE: Forçamos a resposta em JSON para montar o layout depois
            return genai.GenerativeModel(
                MODELO_FIXO, 
                generation_config={"response_mime_type": "application/json"}
            )
        except: continue
    return None

# ----------------- 3. PROCESSAMENTO -----------------
def pdf_to_images(uploaded_file):
    try:
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        images = []
        for page in doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
            images.append(Image.open(io.BytesIO(pix.tobytes("jpeg"))))
        return images
    except: return []

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
st.title("⚖️ Comparador Lado a Lado (Seção por Seção)")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📂 Arte (Original)", type=["pdf", "jpg", "png"])
f2 = c2.file_uploader("📂 Gráfica (Prova)", type=["pdf", "jpg", "png"])

if st.button("🚀 Iniciar Comparação"):
    if f1 and f2:
        model = setup_model()
        if not model:
            st.error("Chave API inválida.")
            st.stop()

        with st.spinner("Lendo documentos e separando seções..."):
            imgs1 = pdf_to_images(f1) if f1.name.endswith(".pdf") else [Image.open(f1)]
            imgs2 = pdf_to_images(f2) if f2.name.endswith(".pdf") else [Image.open(f2)]
            
            # PROMPT ESTRUTURADO PARA JSON
            prompt = f"""
            Atue como auditor farmacêutico.
            Compare as imagens da ARTE (Referência) com a GRÁFICA (Prova).
            
            Extraia e compare o texto destas seções: {SECOES_PACIENTE}

            SAÍDA OBRIGATÓRIA (JSON Array):
            [
              {{
                "titulo": "NOME DA SEÇÃO",
                "texto_arte": "Texto puro da Arte",
                "texto_grafica": "Texto da Gráfica com tags HTML de destaque",
                "status": "CONFORME" (se igual) ou "DIVERGENTE" (se diferente)
              }}
            ]

            REGRAS DE DESTAQUE (apenas no campo 'texto_grafica'):
            - Diferenças de texto: <span class="highlight-yellow">TEXTO</span>
            - Erros de português: <span class="highlight-red">TEXTO</span>
            - Data Anvisa (Dizeres Legais): <span class="highlight-blue">DATA</span>
            """
            
            payload = [prompt, "--- ARTE ---"] + imgs1 + ["--- GRAFICA ---"] + imgs2
            
            try:
                # 1. Pega a resposta do Gemini
                response = model.generate_content(payload)
                
                # 2. Converte o texto JSON em objeto Python
                dados = json.loads(response.text)

                # 3. MOSTRA NA TELA (O Layout Lado a Lado Real)
                st.write("")
                k1, k2, k3 = st.columns(3)
                k1.metric("Seções", len(dados))
                divergentes = sum(1 for d in dados if d['status'] != 'CONFORME')
                k3.metric("Divergências", divergentes, delta_color="inverse")
                st.divider()

                for item in dados:
                    status = item.get('status', 'DIVERGENTE')
                    titulo = item.get('titulo', 'Seção')
                    
                    # Define ícone e cor da borda
                    if status == "CONFORME":
                        icon = "✅"
                        css = "border-ok"
                    elif "DIZERES LEGAIS" in titulo.upper():
                        icon = "👁️"
                        css = "border-info"
                    else:
                        icon = "⚠️"
                        css = "border-warn"

                    # CRIA O ACORDEÃO PARA A SEÇÃO
                    with st.expander(f"{icon} {titulo}", expanded=(status != "CONFORME")):
                        
                        # AQUI ESTÁ O SEGREDO: COLUNAS REAIS DO STREAMLIT
                        col_esq, col_dir = st.columns(2)
                        
                        with col_esq:
                            st.caption("📄 Arte (Referência)")
                            st.markdown(f"""
                            <div class="texto-box {css}">
                                {item.get('texto_arte', '')}
                            </div>
                            """, unsafe_allow_html=True)
                            
                        with col_dir:
                            st.caption("📄 Gráfica (Validação)")
                            st.markdown(f"""
                            <div class="texto-box {css}">
                                {item.get('texto_grafica', '')}
                            </div>
                            """, unsafe_allow_html=True)

            except Exception as e:
                st.error(f"Erro ao processar: {e}")
                st.write(response.text) # Debug se falhar o JSON

    else:
        st.warning("Envie os arquivos.")
