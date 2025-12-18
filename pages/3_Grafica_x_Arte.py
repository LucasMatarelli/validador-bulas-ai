import streamlit as st
import google.generativeai as genai
from PIL import Image
import fitz  # PyMuPDF
import io
import json

# ----------------- 1. VISUAL (CSS) -----------------
st.set_page_config(page_title="Validador Fidelidade Total", page_icon="🎯", layout="wide")

st.markdown("""
<style>
    /* Estilo das caixas de texto */
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

    /* Cores dos Destaques */
    .highlight-yellow { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 3px; border: 1px solid #ffeeba; }
    .highlight-red { background-color: #f8d7da; color: #721c24; padding: 2px 4px; border-radius: 3px; border: 1px solid #f5c6cb; font-weight: bold; }
    .highlight-blue { background-color: #d1ecf1; color: #0c5460; padding: 2px 4px; border-radius: 3px; border: 1px solid #bee5eb; font-weight: bold; }

    /* Bordas de Status */
    .border-ok { border-left: 6px solid #28a745 !important; }
    .border-warn { border-left: 6px solid #ffc107 !important; }
    .border-info { border-left: 6px solid #17a2b8 !important; }
</style>
""", unsafe_allow_html=True)

# ----------------- 2. CONFIGURAÇÃO MODELO (MODO ROBÔ) -----------------
MODELO_FIXO = "models/gemini-flash-latest"

def setup_model():
    keys = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2")]
    valid_keys = [k for k in keys if k]
    
    for api_key in valid_keys:
        try:
            genai.configure(api_key=api_key)
            return genai.GenerativeModel(
                MODELO_FIXO, 
                # CRÍTICO: Temperatura 0.0 impede invenção de palavras
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
            # Zoom aumentado (2.5) para ler letras miúdas de 'Atenção'
            pix = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5))
            images.append(Image.open(io.BytesIO(pix.tobytes("jpeg"))))
        return images
    except: return []

# Mapeamento para ajudar o robô a saber onde parar
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

# ----------------- 4. INTERFACE PRINCIPAL -----------------
st.title("🎯 Validador de Precisão (OCR Literal)")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📂 Arte (Original)", type=["pdf", "jpg", "png"])
f2 = c2.file_uploader("📂 Gráfica (Prova)", type=["pdf", "jpg", "png"])

if st.button("🚀 Extrair e Comparar"):
    if f1 and f2:
        model = setup_model()
        if not model:
            st.error("Chave API inválida.")
            st.stop()

        with st.spinner("Lendo cada palavra e quadros de alerta..."):
            imgs1 = pdf_to_images(f1) if f1.name.endswith(".pdf") else [Image.open(f1)]
            imgs2 = pdf_to_images(f2) if f2.name.endswith(".pdf") else [Image.open(f2)]
            
            # PROMPT DE ALTA RIGIDEZ
            prompt = f"""
            Você é um motor de OCR de alta precisão para a indústria farmacêutica.
            Sua missão: Ler as imagens e extrair o texto IPSIS LITTERIS (exatamente como está escrito).

            SEÇÕES A EXTRAIR: {SECOES_PACIENTE}

            ⚠️ REGRAS OBRIGATÓRIAS DE EXTRAÇÃO:
            1. NÃO INVENTE PALAVRAS. Se a imagem diz "Inflamasão", escreva "Inflamasão".
            2. CAPTURA COMPLETA: O conteúdo de uma seção vai do título dela até encontrar o TÍTULO DA PRÓXIMA SEÇÃO.
            3. QUADROS DE ALERTA: Você DEVE incluir todo texto que estiver em caixas de "Atenção", "Importante" ou letras miúdas que aparecem ANTES do próximo título numérico.
            4. Se o texto estiver em curvas/vetores, use sua visão para transcrever.

            Gere um JSON Array exato:
            [
              {{
                "titulo": "NOME DA SEÇÃO",
                "texto_arte": "Texto LITERAL da Arte",
                "texto_grafica": "Texto da Gráfica com marcações HTML",
                "status": "CONFORME" ou "DIVERGENTE"
              }}
            ]

            REGRAS DE HIGHLIGHT (apenas no 'texto_grafica'):
            - Diferenças (texto extra/faltante): <span class="highlight-yellow">TEXTO</span>
            - Erros literais (typos): <span class="highlight-red">TEXTO</span>
            - Data Anvisa: <span class="highlight-blue">DATA</span>
            """
            
            payload = [prompt, "--- ARTE ---"] + imgs1 + ["--- GRAFICA ---"] + imgs2
            
            try:
                response = model.generate_content(payload)
                dados = json.loads(response.text)

                st.write("")
                k1, k2, k3 = st.columns(3)
                k1.metric("Seções", len(dados))
                divs = sum(1 for d in dados if d['status'] != 'CONFORME')
                k3.metric("Divergências", divs, delta_color="inverse")
                st.divider()

                for item in dados:
                    status = item.get('status', 'DIVERGENTE')
                    titulo = item.get('titulo', 'Seção')
                    
                    if status == "CONFORME":
                        icon, css = "✅", "border-ok"
                    elif "DIZERES LEGAIS" in titulo.upper():
                        icon, css = "👁️", "border-info"
                    else:
                        icon, css = "⚠️", "border-warn"

                    with st.expander(f"{icon} {titulo}", expanded=(status != "CONFORME")):
                        col_esq, col_dir = st.columns(2)
                        
                        with col_esq:
                            st.caption("📄 Arte (Original)")
                            st.markdown(f'<div class="texto-box {css}">{item.get("texto_arte", "")}</div>', unsafe_allow_html=True)
                            
                        with col_dir:
                            st.caption("📄 Gráfica (Validação)")
                            st.markdown(f'<div class="texto-box {css}">{item.get("texto_grafica", "")}</div>', unsafe_allow_html=True)

            except Exception as e:
                st.error(f"Erro: {e}")
                st.warning("Se o erro persistir, o arquivo pode estar muito denso. Tente cortar as páginas.")

    else:
        st.warning("Envie os arquivos.")
