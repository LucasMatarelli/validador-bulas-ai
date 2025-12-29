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

    /* Destaques */
    .highlight-yellow { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; }
    .highlight-red { background-color: #f8d7da; color: #721c24; padding: 2px 4px; border-radius: 4px; border: 1px solid #f5c6cb; font-weight: bold; }
    .highlight-blue { background-color: #d1ecf1; color: #0c5460; padding: 2px 4px; border-radius: 4px; border: 1px solid #bee5eb; font-weight: bold; }

    /* Bordas de Status */
    .border-ok { border-left: 6px solid #28a745 !important; }
    .border-warn { border-left: 6px solid #ffc107 !important; }
    .border-info { border-left: 6px solid #17a2b8 !important; }

    /* Métricas */
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
# Usando a versão 1.5 Flash que é mais estável com limites de token
MODELO_FIXO = "models/gemini-1.5-flash"

# ----------------- 3. PROCESSAMENTO INTELIGENTE -----------------
def process_file_content(uploaded_file):
    try:
        filename = uploaded_file.name.lower()
        
        if filename.endswith(".pdf"):
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            full_text = ""
            has_digital_text = False
            for page in doc:
                text = page.get_text("text", sort=True)
                if len(text.strip()) > 50: has_digital_text = True
                full_text += text + "\n"
            
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
            full_text = [para.text for para in doc.paragraphs]
            return ["\n".join(full_text)]
            
    except: return []

def repair_json(json_str):
    """Tenta fechar JSON cortado abruptamente para evitar crash"""
    try:
        json_str = json_str.strip()
        # Se cortou no meio de uma string (número ímpar de aspas)
        if json_str.count('"') % 2 != 0:
            json_str += '"'
        
        # Fecha estruturas abertas
        open_braces = json_str.count('{') - json_str.count('}')
        open_brackets = json_str.count('[') - json_str.count(']')
        
        json_str += '}' * max(0, open_braces)
        json_str += ']' * max(0, open_brackets)
        
        # Tenta fechar o objeto raiz se necessário
        if not json_str.endswith("}"):
            json_str += "}"
            
        return json_str
    except:
        return json_str

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
f1 = c1.file_uploader("📂 Arte Vigente", type=["pdf", "jpg", "png", "docx"])
f2 = c2.file_uploader("📂 Arquivo Gráfica", type=["pdf", "jpg", "png", "docx"])

if st.button("🚀 Validar"):
    keys_disponiveis = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2"), st.secrets.get("GEMINI_API_KEY3")]
    keys_validas = [k for k in keys_disponiveis if k]

    if not keys_validas:
        st.error("Nenhuma chave API encontrada.")
        st.stop()

    if f1 and f2:
        with st.spinner("Processando..."):
            f1.seek(0); f2.seek(0)
            conteudo1 = process_file_content(f1)
            conteudo2 = process_file_content(f2)
            
            prompt = f"""
            Você é um EXTRATOR FORENSE DE TEXTO.
            INPUT: Documentos farmacêuticos (Bulas).
            TAREFA: Extrair e comparar as seções: {SECOES_COMPLETAS}

            ⚠️ PROTOCOLO DE LEITURA E OTIMIZAÇÃO:
            1. **FLUXO VERTICAL:** Leia coluna por coluna.
            2. **VERBATIM INTELIGENTE:** Copie o texto exato, MAS para economizar tokens:
               - **IMPORTANTE:** Se houver linhas longas de pontilhados (ex: "nitrato ......... 5mg"), SUBSTITUA os pontos por "[...]" (ex: "nitrato [...] 5mg").
               - Mantenha todo o resto da pontuação e texto inalterado.
            3. **SEM ALUCINAÇÃO:** Não corrija gramática.
            4. **CONTINUIDADE:** Una texto que quebra entre colunas.

            🚨 REGRAS DE STATUS:
            >>> GRUPO BLINDADO (CONFORME OBRIGATÓRIO): [ "APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS" ]
            >>> GRUPO PADRÃO: Compare palavra por palavra. Diferenças reais = <span class="highlight-yellow">TEXTO ERRADO</span>.

            SAÍDA JSON (Não use Markdown, apenas JSON puro):
            {{
                "data_anvisa_ref": "dd/mm/aaaa",
                "data_anvisa_grafica": "dd/mm/aaaa",
                "secoes": [
                    {{ "titulo": "X", "texto_arte": "...", "texto_grafica": "...", "status": "CONFORME/DIVERGENTE" }}
                ]
            }}
            """
            
            payload = [prompt, "--- ARTE ---"] + conteudo1 + ["--- GRÁFICA ---"] + conteudo2
            response = None
            
            for i, api_key in enumerate(keys_validas):
                try:
                    genai.configure(api_key=api_key)
                    model = genai.GenerativeModel(
                        MODELO_FIXO, 
                        generation_config={ "response_mime_type": "application/json", "temperature": 0.0 }
                    )
                    response = model.generate_content(payload)
                    break 
                except Exception as e:
                    if i == len(keys_validas) - 1: st.error(f"Erro fatal: {e}"); st.stop()
            
            if response:
                try:
                    texto_limpo = response.text.replace("```json", "").replace("```", "").strip()
                    
                    try:
                        resultado = json.loads(texto_limpo, strict=False)
                    except json.JSONDecodeError:
                        # Tenta reparar JSON cortado
                        st.warning("⚠️ A resposta foi muito longa e precisou ser recuperada. O final pode estar incompleto.")
                        texto_reparado = repair_json(texto_limpo)
                        resultado = json.loads(texto_reparado, strict=False)
                    
                    secoes = resultado.get("secoes", [])
                    data_ref = resultado.get("data_anvisa_ref", "N/A")
                    data_graf = resultado.get("data_anvisa_grafica", "N/A")

                    st.markdown("### 📊 Resumo da Conferência")
                    k1, k2, k3 = st.columns(3)
                    k1.metric("Ref", data_ref)
                    k2.metric("Gráfica", data_graf, delta="Ok" if data_ref == data_graf else "Diferente")
                    k3.metric("Seções", len(secoes))

                    divs = sum(1 for s in secoes if s['status'] != 'CONFORME')
                    st.success(f"Conformes: {len(secoes)-divs}") if divs == 0 else st.warning(f"Divergentes: {divs}")
                    
                    st.divider()

                    for item in secoes:
                        status = item.get('status', 'CONFORME')
                        css = "border-ok" if status == "CONFORME" else "border-warn"
                        icon = "✅" if status == "CONFORME" else "⚠️"
                        if "DIZERES" in item.get('titulo', ''): css, icon = "border-info", "📅"

                        with st.expander(f"{icon} {item.get('titulo')}", expanded=(status!="CONFORME")):
                            c_esq, c_dir = st.columns(2)
                            c_esq.markdown(f'<div class="texto-box {css}">{item.get("texto_arte")}</div>', unsafe_allow_html=True)
                            c_dir.markdown(f'<div class="texto-box {css}">{item.get("texto_grafica")}</div>', unsafe_allow_html=True)

                except Exception as e:
                    st.error(f"Erro JSON Irrecuperável: {e}")
                    st.code(response.text)
    else:
        st.warning("Adicione os arquivos.")
