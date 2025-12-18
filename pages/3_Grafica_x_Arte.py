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
        white-space: pre-wrap; /* Mantém parágrafos */
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
                # Temperatura 0.0 é crucial para precisão
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

        with st.spinner("Realizando comparação cirúrgica (palavra por palavra)..."):
            imgs1 = pdf_to_images(f1) if f1.name.endswith(".pdf") else [Image.open(f1)]
            imgs2 = pdf_to_images(f2) if f2.name.endswith(".pdf") else [Image.open(f2)]
            
            # PROMPT DE ALTA PRECISÃO
            prompt = f"""
            Você é um auditor farmacêutico de precisão.
            Analise as imagens e extraia o texto das seções: {SECOES_COMPLETAS}

            ⚠️ INSTRUÇÕES DE COMPARAÇÃO (IMPORTANTE):
            1. Compare o TEXTO DA ARTE com o TEXTO DA GRÁFICA.
            2. Seja CIRÚRGICO nos destaques.
            3. Se houver uma palavra a mais (ex: "não"), marque APENAS a palavra "não". NÃO marque a frase inteira.
            4. Se houver erro de digitação (ex: "vocÊ" vs "você"), marque APENAS a palavra errada.

            REGRAS POR GRUPO:
            - GRUPO 1 ("APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"):
                * Não marque erros. Status sempre "CONFORME".
                * "DIZERES LEGAIS": Extraia a data da Anvisa separadamente para o JSON. No texto, se achar a data, marque de azul. Se não achar, não escreva nada.
            
            - GRUPO 2 (Outras Seções):
                * Marque divergências (palavras extras/faltantes) com <span class="highlight-yellow">PALAVRA</span>.
                * Marque erros gramaticais com <span class="highlight-red">PALAVRA</span>.
                * Capture avisos de "Atenção".

            SAÍDA JSON:
            {{
                "data_anvisa_ref": "dd/mm/aaaa" (ou "Não encontrada"),
                "data_anvisa_grafica": "dd/mm/aaaa" (ou "Não encontrada"),
                "secoes": [
                    {{
                        "titulo": "NOME DA SEÇÃO",
                        "texto_arte": "Texto da arte",
                        "texto_grafica": "Texto da gráfica com highlights precisos",
                        "status": "CONFORME" ou "DIVERGENTE"
                    }}
                ]
            }}
            """
            
            try:
                payload = [prompt, "--- ARTE ---"] + imgs1 + ["--- GRAFICA ---"] + imgs2
                response = model.generate_content(payload)
                resultado = json.loads(response.text)
                
                # Dados globais
                data_ref = resultado.get("data_anvisa_ref", "Não encontrada")
                data_graf = resultado.get("data_anvisa_grafica", "Não encontrada")
                secoes = resultado.get("secoes", [])

                # --- 1. RESUMO NO TOPO (Igual foto) ---
                st.markdown("### 📊 Resumo da Conferência")
                
                # Linha de métricas
                k1, k2, k3 = st.columns(3)
                k1.metric("Data Anvisa (Ref)", data_ref)
                
                # Cor dinâmica para a data
                cor_delta = "normal" if data_ref == data_graf and data_ref != "Não encontrada" else "inverse"
                msg_delta = "Vigência" if data_ref == data_graf else "Diferente"
                if data_graf == "Não encontrada": msg_delta = ""
                
                k2.metric("Data Anvisa (Gráfica)", data_graf, delta=msg_delta, delta_color=cor_delta)
                k3.metric("Seções Analisadas", len(secoes))

                # Barras de status
                div_count = sum(1 for s in secoes if s['status'] != 'CONFORME')
                ok_count = len(secoes) - div_count
                
                b1, b2 = st.columns(2)
                b1.success(f"✅ **Conformes: {ok_count}**")
                if div_count > 0:
                    b2.warning(f"⚠️ **Divergentes: {div_count}**")
                else:
                    b2.success("✨ **Divergentes: 0**")
                
                st.divider()

                # --- 2. LISTA DE SEÇÕES LADO A LADO ---
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
                st.warning("Tente novamente. O modelo pode ter oscilado.")

    else:
        st.warning("Adicione os arquivos.")
