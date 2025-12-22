import streamlit as st
import google.generativeai as genai
from PIL import Image
import fitz  # PyMuPDF
import docx  # Para ler DOCX
import io
import json
import re

# ----------------- 1. VISUAL & CSS -----------------
st.set_page_config(page_title="Validador Farmacêutico", page_icon="💊", layout="wide")

st.markdown("""
<style>
    [data-testid="stHeader"] { visibility: hidden; }
    .texto-box { 
        font-family: 'Segoe UI', sans-serif; font-size: 0.95rem; line-height: 1.6; color: #212529;
        background-color: #ffffff; padding: 20px; border-radius: 8px; border: 1px solid #ced4da;
        height: 100%; box-shadow: 0 2px 4px rgba(0,0,0,0.05); white-space: pre-wrap; text-align: justify;
    }
    .highlight-yellow { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; }
    .highlight-red { background-color: #f8d7da; color: #721c24; padding: 2px 4px; border-radius: 4px; border: 1px solid #f5c6cb; font-weight: bold; }
    .highlight-blue { background-color: #d1ecf1; color: #0c5460; padding: 2px 4px; border-radius: 4px; border: 1px solid #bee5eb; font-weight: bold; }
    .border-ok { border-left: 6px solid #28a745 !important; }
    .border-warn { border-left: 6px solid #ffc107 !important; }
    .border-info { border-left: 6px solid #17a2b8 !important; }
    div[data-testid="stMetric"] { background-color: #f8f9fa; border: 1px solid #dee2e6; padding: 10px; border-radius: 5px; text-align: center; }
</style>
""", unsafe_allow_html=True)

MODELO_FIXO = "models/gemini-1.5-flash"

# ----------------- 2. PROCESSAMENTO OTIMIZADO -----------------
def process_file_content(uploaded_file):
    try:
        filename = uploaded_file.name.lower()
        if filename.endswith(".pdf"):
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            
            # Tenta texto primeiro
            full_text = ""
            has_digital_text = False
            for page in doc:
                text = page.get_text("text")
                if len(text.strip()) > 50: has_digital_text = True
                full_text += text + "\n"
            
            if has_digital_text:
                return [full_text]
            else:
                images = []
                for page in doc:
                    # OTIMIZAÇÃO: 1.0 (Normal) em vez de 3.0 (Alta)
                    pix = page.get_pixmap(matrix=fitz.Matrix(1.0, 1.0)) 
                    # Compressão JPEG
                    images.append(Image.open(io.BytesIO(pix.tobytes("jpeg", quality=80))))
                return images
        
        elif filename.endswith((".jpg", ".png", ".jpeg")):
            img = Image.open(uploaded_file)
            img.thumbnail((1024, 1024)) # Redimensiona se for gigante
            return [img]

        elif filename.endswith(".docx"):
            doc = docx.Document(uploaded_file)
            full_text = []
            for para in doc.paragraphs:
                full_text.append(para.text)
            return ["\n".join(full_text)]
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

# ----------------- 3. UI -----------------
st.title("💊 Gráfica x Arte")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📂 Arte (Original)", type=["pdf", "jpg", "png", "docx"])
f2 = c2.file_uploader("📂 Gráfica (Prova)", type=["pdf", "jpg", "png", "docx"])

if st.button("🚀 Validar"):
    # 3 CHAVES API
    keys_disponiveis = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2"), st.secrets.get("GEMINI_API_KEY3")]
    keys_validas = [k for k in keys_disponiveis if k]

    if not keys_validas:
        st.error("Nenhuma chave API encontrada.")
        st.stop()

    if f1 and f2:
        with st.spinner("Otimizando e processando..."):
            f1.seek(0); f2.seek(0)
            conteudo1 = process_file_content(f1)
            conteudo2 = process_file_content(f2)
            
            prompt = f"""
            Você é um EXTRATOR FORENSE.
            TAREFA: Extrair seções: {SECOES_COMPLETAS}
            1. Copie texto EXATO (Verbatim). Mantenha Negrito <b>.
            2. Não corrija nada. Não invente.
            3. Ignore formatação visual (pontilhados, etc).
            
            REGRAS DE STATUS:
            - "APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS" -> Status "CONFORME" (Blindado, texto puro).
            - Outros -> Compare e marque <span class="highlight-yellow">ERRO</span> se houver.
            
            SAÍDA JSON: {{
                "data_anvisa_ref": "...", "data_anvisa_grafica": "...",
                "secoes": [{{ "titulo": "...", "texto_arte": "...", "texto_grafica": "...", "status": "CONFORME" }}]
            }}
            """
            
            payload = [prompt, "--- ARTE ---"] + conteudo1 + ["--- GRAFICA ---"] + conteudo2
            
            response = None
            
            # Loop de Chaves
            for i, api_key in enumerate(keys_validas):
                try:
                    genai.configure(api_key=api_key)
                    model = genai.GenerativeModel(MODELO_FIXO, generation_config={"response_mime_type": "application/json", "temperature": 0.0})
                    response = model.generate_content(payload)
                    break 
                except Exception as e:
                    if i == len(keys_validas) - 1:
                        st.error(f"Todas as chaves falharam: {e}")
                        st.stop()
                    continue
            
            if response:
                try:
                    texto_limpo = response.text.replace("```json", "").replace("```", "").strip()
                    resultado = json.loads(texto_limpo, strict=False)
                    
                    data_ref = resultado.get("data_anvisa_ref", "-")
                    data_graf = resultado.get("data_anvisa_grafica", "-")
                    secoes = resultado.get("secoes", [])

                    st.markdown("### 📊 Resumo")
                    k1, k2, k3 = st.columns(3)
                    k1.metric("Ref", data_ref)
                    k2.metric("Gráfica", data_graf)
                    k3.metric("Seções", len(secoes))
                    
                    st.divider()

                    secoes_isentas = ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]

                    for item in secoes:
                        titulo = item.get('titulo', '')
                        eh_isenta = any(x in titulo.upper() for x in secoes_isentas)
                        
                        if eh_isenta:
                            status = "CONFORME"
                            css = "border-info"
                            aberto = False
                        else:
                            status = item.get('status', 'CONFORME')
                            css = "border-warn" if status == "DIVERGENTE" else "border-ok"
                            aberto = (status == "DIVERGENTE")
                        
                        if "DIZERES LEGAIS" in titulo.upper(): icon="📅"
                        elif status == "CONFORME": icon="✅"
                        else: icon="⚠️"

                        with st.expander(f"{icon} {titulo}", expanded=aberto):
                            c1, c2 = st.columns(2)
                            ta = item.get("texto_arte", "")
                            tg = item.get("texto_grafica", "")
                            
                            # Data azul apenas em Dizeres Legais
                            if "DIZERES LEGAIS" in titulo.upper():
                                ta = ta.replace("/", '<span class="highlight-blue">/</span>')
                                tg = tg.replace("/", '<span class="highlight-blue">/</span>')

                            c1.markdown(f'<div class="texto-box {css}">{ta}</div>', unsafe_allow_html=True)
                            c2.markdown(f'<div class="texto-box {css}">{tg}</div>', unsafe_allow_html=True)

                except Exception as e:
                    st.error(f"Erro JSON: {e}")
    else:
        st.warning("Adicione os arquivos.")
