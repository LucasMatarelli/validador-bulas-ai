import streamlit as st
import google.generativeai as genai
from PIL import Image
import fitz  # PyMuPDF
import docx  # Para ler DOCX
import io
import json

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

    .highlight-yellow { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; }
    .highlight-red { background-color: #f8d7da; color: #721c24; padding: 2px 4px; border-radius: 4px; border: 1px solid #f5c6cb; font-weight: bold; }
    .highlight-blue { background-color: #d1ecf1; color: #0c5460; padding: 2px 4px; border-radius: 4px; border: 1px solid #bee5eb; font-weight: bold; }

    .border-ok { border-left: 6px solid #28a745 !important; }
    .border-warn { border-left: 6px solid #ffc107 !important; }
    .border-info { border-left: 6px solid #17a2b8 !important; }

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

# ----------------- 3. PROCESSAMENTO INTELIGENTE (COLUNAS + NEGRITO) -----------------
def process_file_content(uploaded_file):
    try:
        filename = uploaded_file.name.lower()

        if filename.endswith(".pdf"):
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            full_text = ""
            has_content = False
            
            for page in doc:
                # Extrai blocos de texto com informações de posição (ajuda a separar colunas)
                blocks = page.get_text("blocks")
                # Ordena primeiro pela posição X (coluna) e depois pela posição Y (linha)
                # Isso garante que ele leia a coluna da esquerda inteira antes de ir para a direita
                blocks.sort(key=lambda b: (b[0], b[1])) 
                
                page_text = ""
                for b in blocks:
                    block_text = b[4] # Conteúdo do texto
                    if len(block_text.strip()) > 2:
                        has_content = True
                        page_text += block_text + "\n"
                full_text += page_text + "\n--- FIM DA PÁGINA ---\n"
            
            if has_content:
                return [full_text]
            else:
                # Caso seja SCAN, mantém a lógica de imagem
                images = []
                for page in doc:
                    pix = page.get_pixmap(matrix=fitz.Matrix(3.0, 3.0)) 
                    images.append(Image.open(io.BytesIO(pix.tobytes("jpeg"))))
                return images
        
        elif filename.endswith((".jpg", ".png", ".jpeg")):
            return [Image.open(uploaded_file)]

        elif filename.endswith(".docx"):
            doc_obj = docx.Document(uploaded_file)
            full_text = []
            for para in doc_obj.paragraphs:
                # Tenta preservar negritos básicos no docx se houver
                text = ""
                for run in para.runs:
                    if run.bold:
                        text += f"**{run.text}**"
                    else:
                        text += run.text
                full_text.append(text)
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
        with st.spinner("Analisando colunas e extraindo texto original..."):
            f1.seek(0); f2.seek(0)
            conteudo1 = process_file_content(f1)
            conteudo2 = process_file_content(f2)
            
            prompt = f"""
            Você é um REVISOR FARMACÊUTICO RIGOROSO.
            Sua tarefa é extrair o texto das seções: {SECOES_COMPLETAS}
            
            ⚠️ REGRAS CRÍTICAS:
            1. RESPEITE AS COLUNAS: O texto foi extraído seguindo a ordem vertical das colunas. Mantenha a sequência lógica.
            2. FIDELIDADE 100%: Transcreva exatamente como está, mantendo NEGRITOS (use markdown **texto**) e pontuação.
            3. NÃO CORRIJA: Se houver um erro de digitação no original, mantenha o erro.
            4. COMPARAÇÃO: Identifique diferenças reais entre ARTE e GRÁFICA.
            
            SAÍDA JSON:
            {{
                "data_anvisa_ref": "data",
                "data_anvisa_grafica": "data",
                "secoes": [
                    {{
                        "titulo": "NOME DA SEÇÃO",
                        "texto_arte": "Texto 100% original",
                        "texto_grafica": "Texto 100% original (com <span class='highlight-yellow'>erro</span> apenas onde divergir)",
                        "status": "CONFORME" ou "DIVERGENTE"
                    }}
                ]
            }}
            """
            
            payload = [prompt, "--- ARTE (REFERÊNCIA) ---"] + conteudo1 + ["--- GRÁFICA (VALIDAÇÃO) ---"] + conteudo2
            
            response = None
            for i, api_key in enumerate(keys_validas):
                try:
                    genai.configure(api_key=api_key)
                    model = genai.GenerativeModel(MODELO_FIXO, generation_config={"response_mime_type": "application/json", "temperature": 0.0})
                    response = model.generate_content(payload)
                    break 
                except Exception as e:
                    if i == len(keys_validas) - 1: st.error(f"Erro: {e}"); st.stop()

            if response:
                try:
                    texto_limpo = response.text.replace("```json", "").replace("```", "").strip()
                    resultado = json.loads(texto_limpo, strict=False)
                    
                    secoes = resultado.get("secoes", [])
                    st.markdown("### 📊 Resultado da Validação")

                    for item in secoes:
                        status = item.get('status', 'CONFORME')
                        titulo = item.get('titulo', 'Seção')
                        css = "border-ok" if status == "CONFORME" else "border-warn"
                        icon = "✅" if status == "CONFORME" else "⚠️"

                        with st.expander(f"{icon} {titulo}", expanded=(status != "CONFORME")):
                            col_esq, col_dir = st.columns(2)
                            with col_esq:
                                st.caption("Arte Original")
                                st.markdown(f'<div class="texto-box {css}">{item.get("texto_arte", "")}</div>', unsafe_allow_html=True)
                            with col_dir:
                                st.caption("Gráfica / Prova")
                                st.markdown(f'<div class="texto-box {css}">{item.get("texto_grafica", "")}</div>', unsafe_allow_html=True)
                except Exception as e:
                    st.error(f"Erro no processamento: {e}")
    else:
        st.warning("Adicione os arquivos.")
