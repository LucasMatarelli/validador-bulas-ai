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
    /* --- ESCONDER MENU SUPERIOR --- */
    [data-testid="stHeader"] { visibility: hidden; }

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
        white-space: pre-wrap; 
        text-align: justify;
    }

    /* Status das Bordas */
    .border-ok { border-left: 6px solid #28a745 !important; }
    .border-warn { border-left: 6px solid #ffc107 !important; }
    .border-info { border-left: 6px solid #17a2b8 !important; }
    
    /* Highlight de Erros */
    .highlight-yellow { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; }
    
    /* Negrito */
    b { font-weight: bold; color: #000; }

    div[data-testid="stMetric"] {
        background-color: #f8f9fa; border: 1px solid #dee2e6; padding: 10px; border-radius: 5px; text-align: center;
    }
</style>
""", unsafe_allow_html=True)

# ----------------- 2. CONFIGURAÇÃO MODELOS (EXATAMENTE COMO PEDIDO) -----------------
MODELOS_POSSIVEIS = [
    "models/gemini-flash-latest", 
    "models/gemini-2.5-flash"
]

# ----------------- 3. CONFIGURAÇÃO DE SEGURANÇA -----------------
SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]

# ----------------- 4. FUNÇÕES AUXILIARES -----------------
def process_file_content(uploaded_file):
    try:
        filename = uploaded_file.name.lower()
        if filename.endswith(".pdf"):
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            full_text = ""
            has_digital_text = False
            for page in doc:
                text = page.get_text("text")
                if len(text.strip()) > 50: has_digital_text = True
                full_text += text + "\n"
            if has_digital_text: return [full_text]
            else:
                images = []
                for page in doc:
                    pix = page.get_pixmap(matrix=fitz.Matrix(3.0, 3.0)) 
                    images.append(Image.open(io.BytesIO(pix.tobytes("jpeg"))))
                return images
        elif filename.endswith((".jpg", ".png", ".jpeg")):
            return [Image.open(uploaded_file)]
        elif filename.endswith(".docx"):
            doc = docx.Document(uploaded_file)
            return ["\n".join([para.text for para in doc.paragraphs])]
    except: return []

def reparar_json_quebrado(texto_json):
    """
    Tenta consertar JSONs cortados pela metade fechando aspas e chaves.
    """
    try:
        return json.loads(texto_json, strict=False)
    except:
        texto_limpo = texto_json.strip()
        
        # Se não termina com chave fechando json, tenta fechar
        if not texto_limpo.endswith("}"):
            # Verifica se parou no meio de uma string (aspas abertas)
            conta_aspas = texto_limpo.count('"') - texto_limpo.count('\\"')
            if conta_aspas % 2 != 0:
                texto_limpo += '"' # Fecha a string
            
            # Tenta fechar as estruturas (bruta força inteligente)
            tentativas = ["}", "]}", "] }", "}]}", "\"}]}"]
            
            for t in tentativas:
                try:
                    return json.loads(texto_limpo + t, strict=False)
                except:
                    continue
        
        return {"secoes": [], "erro_parse": True}

# ----------------- 5. UI PRINCIPAL -----------------
st.title("💊 Gráfica x Arte")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📂 Arte (Original)", type=["pdf", "jpg", "png", "docx"])
f2 = c2.file_uploader("📂 Gráfica (Prova)", type=["pdf", "jpg", "png", "docx"])

if st.button("🚀 Validar"):
    
    keys_disponiveis = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2")]
    keys_validas = [k for k in keys_disponiveis if k]

    if not keys_validas:
        st.error("Nenhuma chave API encontrada.")
        st.stop()

    if f1 and f2:
        with st.spinner("Processando com seus modelos preferidos..."):
            f1.seek(0)
            f2.seek(0)
            
            conteudo1 = process_file_content(f1)
            conteudo2 = process_file_content(f2)
            
            prompt_base = """
            ATUE COMO UM VALIDADOR DE BULAS FARMACÊUTICAS.
            
            TAREFA: Compare os textos da ARTE (Referência) com a GRÁFICA (Prova).
            
            REGRAS CRÍTICAS:
            1. Transcreva o texto COMPLETO de cada seção.
            2. Se houver negrito visual, use tags <b>...</b>.
            3. Ignore linhas pontilhadas longas (ex: "......."), substitua por " ".
            4. Compare palavra por palavra. Se houver erro na GRÁFICA, envolva o erro em <span class='highlight-yellow'>...</span>.
            
            FORMATO DE SAÍDA JSON:
            {
                "data_anvisa_ref": "dd/mm/aaaa",
                "data_anvisa_grafica": "dd/mm/aaaa",
                "secoes": [
                    {
                        "titulo": "TITULO DA SEÇÃO",
                        "texto_arte": "Texto da arte...",
                        "texto_grafica": "Texto da gráfica...",
                        "status": "CONFORME"
                    }
                ]
            }
            """
            
            payload = [prompt_base, "=== ARTE ==="] + conteudo1 + ["=== GRÁFICA ==="] + conteudo2
            
            response = None
            ultimo_erro = ""

            for api_key in keys_validas:
                genai.configure(api_key=api_key)
                for model_name in MODELOS_POSSIVEIS:
                    try:
                        # AQUI ESTÁ A CHAVE PARA FUNCIONAR: max_output_tokens ALTO
                        model = genai.GenerativeModel(
                            model_name, 
                            safety_settings=SAFETY_SETTINGS,
                            generation_config={
                                "response_mime_type": "application/json", 
                                "temperature": 0.0,
                                "max_output_tokens": 8192 
                            }
                        )
                        response = model.generate_content(payload)
                        break 
                    except Exception as e:
                        ultimo_erro = str(e)
                        # Se der erro no modelo 1, ele tenta o modelo 2 automaticamente
                        continue 
                if response: break

            if response:
                try:
                    # Limpeza Básica
                    texto_raw = response.text.replace("```json", "").replace("```", "")
                    
                    # Regex para tentar pegar o bloco JSON principal
                    match = re.search(r'\{.*\}', texto_raw, re.DOTALL)
                    if match:
                        texto_raw = match.group(0)

                    # --- USO DA FUNÇÃO DE REPARO ---
                    resultado = reparar_json_quebrado(texto_raw)
                    
                    if resultado.get("erro_parse"):
                        st.warning("⚠️ O texto gerado foi cortado no final (limite da IA), mas recuperamos o conteúdo.")

                    data_ref = resultado.get("data_anvisa_ref", "---")
                    data_graf = resultado.get("data_anvisa_grafica", "---")
                    secoes = resultado.get("secoes", [])

                    st.markdown("### 📊 Resultado")
                    
                    k1, k2, k3 = st.columns(3)
                    k1.metric("Data Ref", data_ref)
                    k2.metric("Data Gráfica", data_graf)
                    k3.metric("Seções", len(secoes))

                    div_count = sum(1 for s in secoes if s.get('status') != 'CONFORME')
                    
                    if div_count == 0:
                        st.success("✅ **Tudo Conforme!**")
                    else:
                        st.warning(f"⚠️ **{div_count} Divergências Encontradas**")
                    
                    st.divider()

                    for item in secoes:
                        status = item.get('status', 'CONFORME')
                        css = "border-ok" if status == "CONFORME" else "border-warn"
                        icon = "✅" if status == "CONFORME" else "⚠️"
                        
                        aberto = status != "CONFORME"

                        with st.expander(f"{icon} {item.get('titulo', 'Seção')}", expanded=aberto):
                            cA, cB = st.columns(2)
                            with cA:
                                st.caption("Arte")
                                st.markdown(f'<div class="texto-box {css}">{item.get("texto_arte", "")}</div>', unsafe_allow_html=True)
                            with cB:
                                st.caption("Gráfica")
                                st.markdown(f'<div class="texto-box {css}">{item.get("texto_grafica", "")}</div>', unsafe_allow_html=True)

                except Exception as e:
                    st.error("❌ Erro ao processar resposta da IA.")
                    st.code(response.text)
            else:
                 st.error(f"Erro de Conexão com os modelos {MODELOS_POSSIVEIS}: {ultimo_erro}")

    else:
        st.warning("Adicione os arquivos.")
