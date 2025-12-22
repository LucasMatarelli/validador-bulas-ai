import streamlit as st
import google.generativeai as genai
from PIL import Image
import fitz  # PyMuPDF
import docx  # Para ler DOCX
import io
import json
import re
import time

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

# ----------------- 2. SEUS MODELOS (MANUALMENTE SELECIONADOS) -----------------
MODELOS_POSSIVEIS = [
    "models/gemini-flash-latest", 
    "models/gemini-2.5-flash",        # Solicitado (Experimental)
    "models/gemini-1.5-flash-latest", # Fallback seguro
    "models/gemini-1.5-pro-latest"    # Fallback potente
]

# ----------------- 3. CONFIGURAÇÃO DE SEGURANÇA (TOTALMENTE ABERTA) -----------------
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
    Tenta consertar JSONs cortados ou mal formatados.
    """
    if not texto_json: return {"secoes": [], "erro_parse": True}

    # 1. Tenta carregar direto
    try:
        return json.loads(texto_json, strict=False)
    except:
        pass

    # 2. Limpeza cirúrgica
    texto_limpo = texto_json.strip()
    
    # Se não termina com chave/colchete fechando, tenta fechar na força bruta
    if not (texto_limpo.endswith("}") or texto_limpo.endswith("]")):
        # Verifica aspas abertas
        conta_aspas = texto_limpo.count('"') - texto_limpo.count('\\"')
        if conta_aspas % 2 != 0: texto_limpo += '"'
        
        # Tenta fechar estruturas comuns
        tentativas = ["}", "]}", "] }", "}]}", "\"}]}"]
        for t in tentativas:
            try:
                return json.loads(texto_limpo + t, strict=False)
            except: continue
    
    # 3. Se falhar tudo, tenta achar o último objeto válido dentro da lista "secoes"
    # Isso salva o que a IA escreveu antes de cortar
    try:
        match = re.search(r'"secoes"\s*:\s*\[(.*)', texto_limpo, re.DOTALL)
        if match:
            conteudo_lista = match.group(1)
            # Tenta pegar objetos completos { ... }
            objetos = re.findall(r'\{[^{}]+\}', conteudo_lista)
            if objetos:
                json_reconstruido = '{"secoes": [' + ','.join(objetos) + ']}'
                return json.loads(json_reconstruido, strict=False)
    except:
        pass

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
        status_box = st.empty()
        status_box.info("Lendo arquivos e iniciando IA...")

        f1.seek(0)
        f2.seek(0)
        
        conteudo1 = process_file_content(f1)
        conteudo2 = process_file_content(f2)
        
        prompt_base = """
        ATUE COMO UM VALIDADOR DE BULAS FARMACÊUTICAS.
        TAREFA: Extrair texto e comparar ARTE (Referência) vs GRÁFICA (Prova).
        
        REGRAS RÍGIDAS:
        1. Transcreva o texto COMPLETO de cada seção encontrada.
        2. Se houver negrito visual, use tags <b>...</b>.
        3. Ignore linhas pontilhadas ("...."), substitua por " ".
        4. Marque divergências na GRÁFICA com <span class='highlight-yellow'>...</span>.
        
        SAÍDA OBRIGATÓRIA (JSON PURO):
        {
            "data_anvisa_ref": "dd/mm/aaaa",
            "data_anvisa_grafica": "dd/mm/aaaa",
            "secoes": [
                {
                    "titulo": "NOME DA SEÇÃO",
                    "texto_arte": "Texto da arte...",
                    "texto_grafica": "Texto da gráfica...",
                    "status": "CONFORME"
                }
            ]
        }
        """
        
        payload = [prompt_base, "=== ARTE ==="] + conteudo1 + ["=== GRÁFICA ==="] + conteudo2
        
        response = None
        sucesso = False
        modelo_usado = ""
        erros_acumulados = []

        # LOOP DE TENTATIVA (RETRY)
        for api_key in keys_validas:
            genai.configure(api_key=api_key)
            
            for model_name in MODELOS_POSSIVEIS:
                try:
                    status_box.text(f"Processando com: {model_name}...")
                    
                    model = genai.GenerativeModel(
                        model_name, 
                        safety_settings=SAFETY_SETTINGS,
                        generation_config={
                            "response_mime_type": "application/json", 
                            "temperature": 0.0,
                            "max_output_tokens": 8192 
                        }
                    )
                    
                    temp_response = model.generate_content(payload)
                    
                    # Validação de resposta vazia
                    if not temp_response.candidates or not temp_response.candidates[0].content.parts:
                        erros_acumulados.append(f"{model_name}: Bloqueio de segurança (conteúdo vazio).")
                        continue 
                    
                    response = temp_response
                    modelo_usado = model_name
                    sucesso = True
                    break 

                except Exception as e:
                    erros_acumulados.append(f"{model_name}: Erro {str(e)}")
                    continue
            
            if sucesso: break

        status_box.empty()

        if sucesso and response:
            try:
                # Limpeza do texto para JSON
                texto_raw = response.text.replace("```json", "").replace("```", "")
                match = re.search(r'\{.*\}', texto_raw, re.DOTALL)
                if match: texto_raw = match.group(0)

                resultado = reparar_json_quebrado(texto_raw)
                
                # --- AQUI ESTA O PULO DO GATO ---
                # Verifica se realmente tem conteúdo
                secoes = resultado.get("secoes", [])
                
                if not secoes:
                    st.error(f"❌ O modelo {modelo_usado} retornou uma resposta vazia ou inválida.")
                    with st.expander("🛠️ Ver Resposta Bruta da IA (Debug)"):
                        st.code(response.text)
                    st.stop() # Para aqui para não mostrar "Tudo Conforme" falso

                data_ref = resultado.get("data_anvisa_ref", "---")
                data_graf = resultado.get("data_anvisa_grafica", "---")

                st.markdown(f"### 📊 Resultado (Modelo: `{modelo_usado}`)")
                
                k1, k2, k3 = st.columns(3)
                k1.metric("Data Ref", data_ref)
                k2.metric("Data Gráfica", data_graf)
                k3.metric("Seções", len(secoes))

                div_count = sum(1 for s in secoes if s.get('status') != 'CONFORME')
                
                if div_count == 0:
                    st.success("✅ **Tudo Conforme!**")
                else:
                    st.warning(f"⚠️ **{div_count} Divergências Encontradas**")
                
                if resultado.get("erro_parse"):
                    st.warning("⚠️ Nota: O texto foi cortado no final (limite da IA), mas recuperamos o início.")

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
                st.error("❌ Erro fatal ao processar o JSON.")
                st.write(e)
                with st.expander("Ver texto bruto"):
                    st.code(response.text)
        else:
             st.error("❌ Falha em todos os modelos. O conteúdo foi bloqueado ou a conexão falhou.")
             with st.expander("Ver detalhes dos erros"):
                 for erro in erros_acumulados:
                     st.write(erro)

    else:
        st.warning("Adicione os arquivos.")
