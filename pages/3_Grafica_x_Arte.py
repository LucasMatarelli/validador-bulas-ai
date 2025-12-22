import streamlit as st
import google.generativeai as genai
from PIL import Image
import fitz
import docx
import io
import json
import re

# ----------------- 1. VISUAL & CSS -----------------
st.set_page_config(page_title="Validador Farmacêutico", page_icon="💊", layout="wide")

st.markdown("""
<style>
    [data-testid="stHeader"] { visibility: hidden; }

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
        white-space: pre-wrap; 
        text-align: justify;
    }

    .border-ok { border-left: 6px solid #28a745 !important; }
    .border-warn { border-left: 6px solid #ffc107 !important; }
    
    .highlight-yellow { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; }
    
    b { font-weight: bold; color: #000; }

    div[data-testid="stMetric"] {
        background-color: #f8f9fa; border: 1px solid #dee2e6; padding: 10px; border-radius: 5px; text-align: center;
    }
</style>
""", unsafe_allow_html=True)

MODELO_FIXO = "models/gemini-flash-latest" 

SECOES_OBRIGATORIAS = [
    "APRESENTAÇÕES", "COMPOSIÇÃO", "PARA QUE ESTE MEDICAMENTO É INDICADO", 
    "COMO ESTE MEDICAMENTO FUNCIONA?", "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?", 
    "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?", 
    "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?", 
    "COMO DEVO USAR ESTE MEDICAMENTO?", 
    "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?", 
    "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?", 
    "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?", 
    "DIZERES LEGAIS"
]

# ----------------- 3. FUNÇÕES -----------------
def process_file_content(uploaded_file):
    try:
        filename = uploaded_file.name.lower()
        if filename.endswith(".pdf"):
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            images = []
            for page in doc:
                pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0)) 
                images.append(Image.open(io.BytesIO(pix.tobytes("jpeg"))))
            return images
        elif filename.endswith((".jpg", ".png", ".jpeg")):
            return [Image.open(uploaded_file)]
        elif filename.endswith(".docx"):
            doc = docx.Document(uploaded_file)
            return ["\n".join([para.text for para in doc.paragraphs])]
    except: return []

def reparar_json_quebrado(texto_json):
    if not texto_json: return {"secoes": [], "erro_parse": True}
    texto_limpo = texto_json.strip().replace("```json", "").replace("```", "")
    try:
        return json.loads(texto_limpo)
    except:
        return {"secoes": [], "erro_parse": True}

# ----------------- 4. UI PRINCIPAL -----------------
st.title("💊 Gráfica x Arte")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📂 Arte (Original)", type=["pdf", "jpg", "png", "docx"])
f2 = c2.file_uploader("📂 Gráfica (Prova)", type=["pdf", "jpg", "png", "docx"])

if st.button("🚀 Validar"):
    keys_disponiveis = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2"), st.secrets.get("GEMINI_API_KEY3")]
    keys_validas = [k for k in keys_disponiveis if k]

    if not keys_validas:
        st.error("Nenhuma chave API encontrada.")
        st.stop()

    if f1 and f2:
        with st.spinner("Analisando visualmente (Ignorando pontilhados)..."):
            f1.seek(0); f2.seek(0)
            conteudo1 = process_file_content(f1)
            conteudo2 = process_file_content(f2)
            
            prompt_base = f"""
            ATUE COMO UM AUDITOR FARMACÊUTICO.
            
            Compare as duas imagens/textos fornecidos (ARTE vs GRÁFICA).
            
            LISTA DE SEÇÕES: {json.dumps(SECOES_OBRIGATORIAS, ensure_ascii=False)}

            REGRAS DE EXTRAÇÃO:
            1. Extraia o texto COMPLETO. Não pare no meio da seção.
            2. Se o texto estiver em colunas, leia na ordem correta.
            3. IGNORE PONTILHADOS (".....") de formatação de tabela. Extraia apenas o texto.
            4. Mantenha bullet points em linhas separadas.
            5. Use <b> para negrito.

            SAÍDA JSON:
            {{
                "data_anvisa_ref": "dd/mm/aaaa",
                "data_anvisa_grafica": "dd/mm/aaaa",
                "secoes": [
                    {{
                        "titulo": "NOME DA SEÇÃO",
                        "texto_arte": "Texto completo limpo",
                        "texto_grafica": "Texto completo limpo",
                        "status": "CONFORME" ou "DIVERGENTE"
                    }}
                ]
            }}
            """
            
            payload = [prompt_base, "=== ARTE (REF) ==="] + conteudo1 + ["=== GRÁFICA (PROVA) ==="] + conteudo2
            
            final_result = None
            for api_key in keys_validas:
                genai.configure(api_key=api_key)
                try:
                    model = genai.GenerativeModel(MODELO_FIXO, generation_config={"response_mime_type": "application/json"})
                    response = model.generate_content(payload)
                    final_result = reparar_json_quebrado(response.text)
                    break
                except Exception as e:
                    continue

            if final_result and "secoes" in final_result:
                secoes = final_result["secoes"]
                
                st.markdown("### 📊 Resultado da Análise Visual")
                k1, k2, k3 = st.columns(3)
                k1.metric("Data Ref", final_result.get("data_anvisa_ref", "-"))
                k2.metric("Data Gráfica", final_result.get("data_anvisa_grafica", "-"))
                k3.metric("Seções", len(secoes))

                st.divider()

                for item in secoes:
                    status = item.get('status', 'CONFORME')
                    if status == "CONFORME":
                        css, icon, aberto = "border-ok", "✅", False
                    else:
                        css, icon, aberto = "border-warn", "⚠️", True

                    with st.expander(f"{icon} {item.get('titulo')}", expanded=aberto):
                        cA, cB = st.columns(2)
                        with cA:
                            st.caption("Arte")
                            st.markdown(f'<div class="texto-box {css}">{item.get("texto_arte", "").replace(chr(10), "<br>")}</div>', unsafe_allow_html=True)
                        with cB:
                            st.caption("Gráfica")
                            st.markdown(f'<div class="texto-box {css}">{item.get("texto_grafica", "").replace(chr(10), "<br>")}</div>', unsafe_allow_html=True)
            else:
                st.error("Falha ao analisar documentos. Tente novamente.")
    else:
        st.warning("Adicione os arquivos.")
