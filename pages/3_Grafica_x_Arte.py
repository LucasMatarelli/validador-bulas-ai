import streamlit as st
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from PIL import Image
import fitz  # PyMuPDF
import docx
import io
import json
import time

# ----------------- 1. CONFIGURAÇÃO VISUAL -----------------
st.set_page_config(page_title="Validador Farmacêutico (Gemini OCR)", page_icon="🛡️", layout="wide")

st.markdown("""
<style>
    [data-testid="stHeader"] { visibility: hidden; }
    
    .texto-box { 
        font-family: 'Courier New', monospace;
        font-size: 0.85rem;
        line-height: 1.4;
        color: #212529;
        background-color: #f8f9fa;
        padding: 15px;
        border-radius: 5px;
        border: 1px solid #ced4da;
        white-space: pre-wrap;
        max-height: 400px;
        overflow-y: auto;
    }

    .border-ok { border-left: 6px solid #28a745 !important; }
    .border-warn { border-left: 6px solid #dc3545 !important; }
    
    div[data-testid="stMetric"] {
        background-color: #ffffff;
        border: 1px solid #e9ecef;
        padding: 10px;
        border-radius: 5px;
        text-align: center;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
</style>
""", unsafe_allow_html=True)

# ----------------- 2. LISTA DE MODELOS (FAILOVER) -----------------
MODELOS_PARA_TENTAR = [
    "models/gemini-1.5-flash",          # Rápido e Gratuito (Recomendado)
    "models/gemini-1.5-flash-latest",   # Versão mais recente
    "models/gemini-1.5-pro",            # Backup potente
    "models/gemini-2.0-flash-exp"       # Experimental
]

# ----------------- 3. PROCESSAMENTO INTELIGENTE (OCR) -----------------
def process_file_content(uploaded_file):
    """
    Prepara o arquivo para o Gemini.
    Se for PDF, converte para imagem de ALTA RESOLUÇÃO para garantir OCR perfeito.
    """
    if not uploaded_file:
        return []

    try:
        filename = uploaded_file.name.lower()
        
        # --- PROCESSAMENTO DE PDF (OCR VIA VISÃO) ---
        if filename.endswith(".pdf"):
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            conteudo = []
            
            # Verifica se tem texto digital
            tem_texto = False
            full_text = ""
            for page in doc:
                full_text += page.get_text()
            
            # Se tiver pouco texto (provável escaneamento) ou se quisermos forçar OCR visual
            # Convertemos para imagens de Alta Resolução (Matrix 4.0 = ~300 DPI)
            if len(full_text.strip()) < 500: # Força imagem se tiver pouco texto
                for page in doc:
                    pix = page.get_pixmap(matrix=fitz.Matrix(4.0, 4.0)) 
                    img_data = pix.tobytes("jpeg")
                    conteudo.append(Image.open(io.BytesIO(img_data)))
                return conteudo
            else:
                # Se for PDF digital nativo, manda o texto (mais rápido)
                return [full_text]

        # --- IMAGENS (JPG/PNG) ---
        elif filename.endswith((".jpg", ".png", ".jpeg", ".webp")):
            return [Image.open(uploaded_file)]

        # --- WORD (DOCX) ---
        elif filename.endswith(".docx"):
            doc = docx.Document(uploaded_file)
            full_text = "\n".join([p.text for p in doc.paragraphs])
            return [full_text]
            
    except Exception as e:
        st.error(f"Erro ao processar arquivo: {e}")
        return []
    
    return []

def repair_json(json_str):
    """Tenta consertar JSON cortado violentamente pelo modelo"""
    json_str = json_str.strip()
    if "```json" in json_str: json_str = json_str.split("```json")[1]
    if "```" in json_str: json_str = json_str.split("```")[0]
    
    json_str = json_str.strip()
    
    # Se não termina com chaves/colchetes, tenta fechar
    if not json_str.endswith("}") and not json_str.endswith("]"):
        if json_str.count('"') % 2 != 0: json_str += '"'
        if "secoes" in json_str and not json_str.endswith("]}"):
            if json_str.endswith("}"): json_str += "]}"
            elif json_str.endswith("]"): json_str += "}"
            else: json_str += "}]}"
    
    return json_str

SECOES_PADRAO = [
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

# ----------------- 4. UI PRINCIPAL -----------------
st.title("🛡️ Validador Farmacêutico (OCR Gemini)")
st.caption("Usa Inteligência Artificial para ler imagens (OCR) e validar contra o texto original.")

# Input de API Keys na Sidebar para segurança (ou via secrets)
with st.sidebar:
    st.header("Configurações")
    user_key = st.text_input("Sua API Key (Google AI Studio)", type="password")
    st.info("Se não colocar aqui, o sistema tentará usar os 'st.secrets'.")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📂 Arte (PDF/Img - Referência)", type=["pdf", "jpg", "png"])
f2 = c2.file_uploader("📂 Gráfica (Word/PDF - Texto)", type=["pdf", "docx", "txt"])

if st.button("🔍 Validar Texto Integral", type="primary"):
    
    # Gerenciamento de Chaves
    keys_raw = [user_key, st.secrets.get("GEMINI_API_KEY")]
    keys_validas = [k for k in keys_raw if k and len(k) > 10]

    if not keys_validas:
        st.error("❌ Nenhuma API Key encontrada. Insira na barra lateral ou configure secrets.")
        st.stop()

    if f1 and f2:
        with st.spinner(f"Processando arquivos (Isso pode levar alguns segundos)..."):
            f1.seek(0)
            f2.seek(0)
            
            # Processa para obter imagens ou texto
            conteudo_arte = process_file_content(f1)
            conteudo_grafica = process_file_content(f2)
            
            # PROMPT DE ALTA PRECISÃO
            prompt = f"""
            VOCÊ É UM AUDITOR DE QUALIDADE FARMACÊUTICA ESPECIALIZADO EM OCR.
            
            SUA MISSÃO:
            1. Ler o conteúdo visual da ARTE (Input 1) com precisão absoluta de caractere.
            2. Ler o conteúdo de texto da GRÁFICA (Input 2).
            3. Comparar e validar se os TÍTULOS e TEXTOS estão idênticos.
            
            LISTA RÍGIDA DE TÍTULOS ESPERADOS: {SECOES_PADRAO}

            REGRAS DE OURO (CRÍTICO):
            - **TEXTO EXATO:** O texto extraído deve ser idêntico ao da imagem. Não corrija gramática. Não resuma.
            - **TÍTULOS:** Se o título na imagem for "Apresentação" (singular) e a lista pede "APRESENTAÇÕES" (plural), MARQUE COMO DIVERGENTE. Maiúsculas e minúsculas importam.
            - **ESTRUTURA:** Retorne APENAS JSON válido.
            
            SAÍDA JSON OBRIGATÓRIA:
            {{
                "secoes": [
                    {{
                        "titulo_padrao": "Título da Lista Oficial",
                        "titulo_encontrado_arte": "O que você leu na Arte (OCR)",
                        "titulo_encontrado_grafica": "O que você leu na Gráfica",
                        "texto_arte": "Texto completo extraído da seção...",
                        "texto_grafica": "Texto completo do arquivo de texto...",
                        "status": "CONFORME" (se tudo for idêntico) ou "DIVERGENTE",
                        "obs": "Descreva a diferença exata se houver erro."
                    }}
                ]
            }}
            """
            
            # Monta o payload (Prompt + Imagens/Texto misturados)
            inputs_gemini = [prompt, "--- INÍCIO ARTE (IMAGEM/PDF) ---"]
            inputs_gemini.extend(conteudo_arte)
            inputs_gemini.append("--- FIM ARTE --- INÍCIO GRÁFICA (TEXTO) ---")
            inputs_gemini.extend(conteudo_grafica)
            
            # Configurações de Segurança (Desativar bloqueios para ler textos médicos)
            safety = {
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }

            response = None
            sucesso = False
            status_placeholder = st.empty()
            
            # --- LOOP DE TENTATIVAS (MODELOS E CHAVES) ---
            for modelo_atual in MODELOS_PARA_TENTAR:
                if sucesso: break
                
                for api_key in keys_validas:
                    try:
                        status_placeholder.info(f"🧠 Analisando com **{modelo_atual}**...")
                        
                        genai.configure(api_key=api_key)
                        model = genai.GenerativeModel(
                            modelo_atual, 
                            generation_config={"temperature": 0.0, "response_mime_type": "application/json"},
                            safety_settings=safety
                        )
                        
                        # Chama a API
                        response = model.generate_content(inputs_gemini)
                        
                        sucesso = True
                        status_placeholder.success("✅ Análise Concluída!")
                        time.sleep(1)
                        status_placeholder.empty()
                        break 

                    except Exception as e:
                        print(f"Erro {modelo_atual}: {e}")
                        time.sleep(1)
                        continue
            
            if not sucesso:
                st.error("❌ Não foi possível processar. Tente novamente ou verifique a API Key.")
                st.stop()
            
            # --- PARSING E EXIBIÇÃO ---
            if response:
                try:
                    texto_resposta = response.text
                    texto_reparado = repair_json(texto_resposta)
                    data = json.loads(texto_reparado)

                    secoes = data.get("secoes", [])
                    total = len(secoes)
                    divs = sum(1 for s in secoes if s['status'] != 'CONFORME')
                    oks = total - divs

                    # DASHBOARD
                    st.markdown("### 📊 Resultado da Auditoria")
                    c1, c2 = st.columns(2)
                    c1.metric("✅ Seções Conformes", oks)
                    c2.metric("🚨 Divergências", divs, delta_color="inverse")

                    if divs == 0:
                        st.balloons()
                    
                    st.divider()

                    # LISTAGEM
                    for s in secoes:
                        status = s.get('status', 'CONFORME')
                        t_padrao = s.get('titulo_padrao', 'Seção')
                        t_arte = s.get('titulo_encontrado_arte', '-')
                        t_graf = s.get('titulo_encontrado_grafica', '-')
                        obs = s.get('obs', '')

                        cor_titulo = "green" if status == "CONFORME" else "red"
                        icone = "✅" if status == "CONFORME" else "🚨"
                        expanded = True if status != "CONFORME" else False
                        css_box = "border-ok" if status == "CONFORME" else "border-warn"

                        with st.expander(f"{icone} {t_padrao}", expanded=expanded):
                            # Se houver erro no título, mostra em destaque
                            if t_arte != t_padrao:
                                st.warning(f"⚠️ **ERRO DE TÍTULO NA ARTE:** Leu: '{t_arte}' | Esperado: '{t_padrao}'")
                            
                            if obs:
                                st.info(f"📝 **Nota da IA:** {obs}")

                            col_a, col_b = st.columns(2)
                            with col_a:
                                st.caption("🖼️ Texto Extraído da ARTE (OCR)")
                                st.markdown(f'<div class="texto-box {css_box}">{s.get("texto_arte", "")}</div>', unsafe_allow_html=True)
                            with col_b:
                                st.caption("📄 Texto Original da GRÁFICA")
                                st.markdown(f'<div class="texto-box {css_box}">{s.get("texto_grafica", "")}</div>', unsafe_allow_html=True)

                except Exception as e:
                    st.error("Erro ao ler resposta da IA (JSON Inválido).")
                    with st.expander("Ver JSON Bruto"):
                        st.code(response.text)
    else:
        st.warning("⚠️ Por favor, faça o upload dos dois arquivos para comparar.")
