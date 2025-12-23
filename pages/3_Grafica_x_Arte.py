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
    /* --- ESCONDER MENU SUPERIOR (CONFORME SOLICITADO) --- */
    [data-testid="stHeader"] {
        visibility: hidden;
    }

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

# ----------------- 3. PROCESSAMENTO INTELIGENTE -----------------
def process_file_content(uploaded_file):
    """
    Lógica Híbrida aprimorada para Colunas e Formatação.
    """
    try:
        filename = uploaded_file.name.lower()

        # --- PROCESSAMENTO DE PDF ---
        if filename.endswith(".pdf"):
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            full_text = ""
            has_digital_text = False
            
            for page in doc:
                # 'blocks' detecta colunas automaticamente (lê esquerda depois direita)
                blocks = page.get_text("blocks")
                # Ordena blocos: primeiro por coordenada X (coluna), depois Y (linha)
                blocks.sort(key=lambda b: (b[0], b[1])) 
                
                page_text = ""
                for b in blocks:
                    if len(b[4].strip()) > 0:
                        page_text += b[4] + "\n"
                
                if len(page_text.strip()) > 50:
                    has_digital_text = True
                full_text += page_text + "\n"
            
            if has_digital_text:
                return [full_text]
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
        with st.spinner("Processando... Respeitando colunas e layout original..."):
            f1.seek(0)
            f2.seek(0)
            
            conteudo1 = process_file_content(f1)
            conteudo2 = process_file_content(f2)
            
            prompt = f"""
            Você é um EXTRATOR FORENSE DE TEXTO. 
            IMPORTANTE: Os documentos podem ter DUAS COLUNAS. Respeite a ordem de leitura: termine a primeira coluna antes de ir para a segunda.
            
            TAREFA: Extrair e comparar as seções: {SECOES_COMPLETAS}

            ⚠️ PROTOCOLO DE MANUTENÇÃO DE ORIGINALIDADE:
            1. **VERBATIM:** Copie EXATAMENTE como está. Preserve palavras, números e principalmente o NEGRITO (se presente no texto digital).
            2. **COESÃO DE COLUNAS:** Garanta que o final da primeira coluna se conecte corretamente com o topo da segunda coluna ou próxima página.
            3. **ESTRUTURA:** Não resuma. Se o texto original for longo, extraia-o inteiro.

            SAÍDA JSON:
            {{
                "data_anvisa_ref": "dd/mm/aaaa",
                "data_anvisa_grafica": "dd/mm/aaaa",
                "secoes": [
                    {{
                        "titulo": "NOME DA SEÇÃO",
                        "texto_arte": "Texto ORIGINAL",
                        "texto_grafica": "Texto ORIGINAL (com spans de erro se houver)",
                        "status": "CONFORME" ou "DIVERGENTE"
                    }}
                ]
            }}
            """
            
            payload = [prompt, "--- ARTE (REFERÊNCIA) ---"] + conteudo1 + ["--- GRÁFICA (VALIDAÇÃO) ---"] + conteudo2
            
            response = None
            ultimo_erro = ""

            for i, api_key in enumerate(keys_validas):
                try:
                    genai.configure(api_key=api_key)
                    model = genai.GenerativeModel(
                        MODELO_FIXO, 
                        generation_config={"response_mime_type": "application/json", "temperature": 0.0}
                    )
                    response = model.generate_content(payload)
                    break 
                except Exception as e:
                    ultimo_erro = str(e)
                    if i < len(keys_validas) - 1:
                        st.warning(f"⚠️ Chave {i+1} falhou. Trocando...")
                        continue
                    else:
                        st.error(f"❌ Erro fatal: {ultimo_erro}")
                        st.stop()
            
            if response:
                try:
                    texto_bruto = response.text
                    if "```json" in texto_bruto:
                        texto_bruto = texto_bruto.split("```json")[1].split("```")[0]
                    elif "```" in texto_bruto:
                        texto_bruto = texto_bruto.split("```")[1].split("```")[0]
                    
                    resultado = json.loads(texto_bruto.strip(), strict=False)
                    
                    data_ref = resultado.get("data_anvisa_ref", "Não encontrada")
                    data_graf = resultado.get("data_anvisa_grafica", "Não encontrada")
                    secoes = resultado.get("secoes", [])

                    st.markdown("### 📊 Resumo da Conferência")
                    k1, k2, k3 = st.columns(3)
                    k1.metric("Data Anvisa (Ref)", data_ref)
                    k2.metric("Data Anvisa (Gráfica)", data_graf)
                    k3.metric("Seções Analisadas", len(secoes))

                    st.divider()

                    for item in secoes:
                        status = item.get('status', 'CONFORME')
                        titulo = item.get('titulo', 'Seção')
                        css = "border-ok" if status == "CONFORME" else "border-warn"
                        icon = "✅" if status == "CONFORME" else "⚠️"

                        with st.expander(f"{icon} {titulo}", expanded=(status != "CONFORME")):
                            c_art, c_gra = st.columns(2)
                            c_art.markdown(f'<div class="texto-box {css}">{item.get("texto_arte", "")}</div>', unsafe_allow_html=True)
                            c_gra.markdown(f'<div class="texto-box {css}">{item.get("texto_grafica", "")}</div>', unsafe_allow_html=True)

                except Exception as e:
                    st.error(f"Erro no processamento: {e}")
    else:
        st.warning("Adicione os arquivos.")
