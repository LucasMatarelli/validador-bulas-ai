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

# ----------------- 2. CONFIGURAÇÃO MODELO E SCHEMA -----------------
# Fixar no 1.5 Flash para garantir suporte ao Schema
MODELO_FIXO = "models/gemini-1.5-flash"

# Definição estrita do JSON para evitar "Unterminated String"
RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "data_anvisa_ref": {"type": "STRING"},
        "data_anvisa_grafica": {"type": "STRING"},
        "secoes": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "titulo": {"type": "STRING"},
                    "texto_arte": {"type": "STRING"},
                    "texto_grafica": {"type": "STRING"},
                    "status": {"type": "STRING"}
                },
                "required": ["titulo", "texto_arte", "texto_grafica", "status"]
            }
        }
    },
    "required": ["data_anvisa_ref", "data_anvisa_grafica", "secoes"]
}

# ----------------- 3. PROCESSAMENTO INTELIGENTE -----------------
def process_file_content(uploaded_file):
    try:
        filename = uploaded_file.name.lower()

        # --- PROCESSAMENTO DE PDF ---
        if filename.endswith(".pdf"):
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            
            full_text = ""
            has_digital_text = False
            
            for page in doc:
                text = page.get_text("text")
                if len(text.strip()) > 50: 
                    has_digital_text = True
                full_text += text + "\n"
            
            if has_digital_text:
                return [full_text]
            else:
                images = []
                for page in doc:
                    pix = page.get_pixmap(matrix=fitz.Matrix(3.0, 3.0)) 
                    images.append(Image.open(io.BytesIO(pix.tobytes("jpeg"))))
                return images
        
        # --- PROCESSAMENTO DE IMAGENS DIRETAS ---
        elif filename.endswith((".jpg", ".png", ".jpeg")):
            return [Image.open(uploaded_file)]

        # --- PROCESSAMENTO DE DOCX ---
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
    
    keys_disponiveis = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2")]
    keys_validas = [k for k in keys_disponiveis if k]

    if not keys_validas:
        st.error("Nenhuma chave API encontrada.")
        st.stop()

    if f1 and f2:
        with st.spinner("Analisando documentos e validando textos..."):
            f1.seek(0)
            f2.seek(0)
            
            conteudo1 = process_file_content(f1)
            conteudo2 = process_file_content(f2)
            
            prompt = f"""
            Você é um EXTRATOR FORENSE DE TEXTO.
            
            INPUT: Documentos farmacêuticos (Texto Digital ou Imagens).
            TAREFA: Extrair e comparar as seções: {SECOES_COMPLETAS}

            ⚠️ PROTOCOLO ANT-ALUCINAÇÃO:
            1. COPIE O TEXTO EXATAMENTE COMO ESTÁ (IPSIS LITTERIS).
            2. NÃO corrija erros de português encontrados na imagem.
            3. Em "DIZERES LEGAIS", envolva a data da bula em <span class="highlight-blue">DATA</span> se encontrar.

            REGRAS DE COMPARAÇÃO:
            - Seções BLINDADAS (Status OBRIGATÓRIO "CONFORME"): "APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS".
            - Demais seções: Compare palavra por palavra.
            - Divergência Real: Marque com <span class="highlight-yellow">TEXTO ERRADO</span>.
            - Quebras de linha ou formatação não são divergências.

            IMPORTANTE: Retorne APENAS o JSON preenchido conforme o schema solicitado. Sem markdown, sem ```json.
            """
            
            payload = [prompt, "--- ARTE (REFERÊNCIA) ---"] + conteudo1 + ["--- GRÁFICA (VALIDAÇÃO) ---"] + conteudo2
            
            response = None
            ultimo_erro = ""

            for i, api_key in enumerate(keys_validas):
                try:
                    genai.configure(api_key=api_key)
                    # Configuração com SCHEMA para garantir JSON válido
                    model = genai.GenerativeModel(
                        MODELO_FIXO, 
                        generation_config={
                            "response_mime_type": "application/json", 
                            "response_schema": RESPONSE_SCHEMA, # AQUI ESTÁ A CORREÇÃO
                            "temperature": 0.0
                        }
                    )
                    
                    response = model.generate_content(payload)
                    break 

                except Exception as e:
                    ultimo_erro = str(e)
                    if i < len(keys_validas) - 1:
                        continue
                    else:
                        st.error(f"❌ Erro na API: {ultimo_erro}")
                        st.stop()
            
            if response:
                try:
                    # O response.text com schema já vem limpo, mas garantimos:
                    texto_limpo = response.text.strip()
                    # Remove possíveis sobras de markdown se o modelo ignorar (raro com schema)
                    if texto_limpo.startswith("```json"):
                        texto_limpo = texto_limpo[7:-3]
                    
                    resultado = json.loads(texto_limpo)
                    
                    data_ref = resultado.get("data_anvisa_ref", "Não encontrada")
                    data_graf = resultado.get("data_anvisa_grafica", "Não encontrada")
                    secoes = resultado.get("secoes", [])

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

                except json.JSONDecodeError as e:
                    st.error(f"Erro ao interpretar o JSON retornado: {e}")
                    # Mostra o texto cru para debug se der erro
                    with st.expander("Ver JSON cru (Debug)"):
                        st.code(response.text)
                except Exception as e:
                    st.error(f"Erro no processamento dos dados: {e}")

    else:
        st.warning("Adicione os arquivos.")
