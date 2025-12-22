import streamlit as st
import google.generativeai as genai
from PIL import Image
import fitz  # PyMuPDF
import docx  # Para ler DOCX
import io
import json
import re  # Para limpeza de texto

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

    /* Destaques Precisos */
    .highlight-yellow { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; }
    .highlight-blue { background-color: #d1ecf1; color: #0c5460; padding: 2px 4px; border-radius: 4px; border: 1px solid #bee5eb; font-weight: bold; }
    
    /* Negrito preservado */
    b, strong { font-weight: 900; color: #000; }

    /* Status das Bordas */
    .border-ok { border-left: 6px solid #28a745 !important; }
    .border-warn { border-left: 6px solid #ffc107 !important; }
    .border-info { border-left: 6px solid #17a2b8 !important; }

    div[data-testid="stMetric"] {
        background-color: #f8f9fa; border: 1px solid #dee2e6; padding: 10px; border-radius: 5px; text-align: center;
    }
</style>
""", unsafe_allow_html=True)

# ----------------- 2. CONFIGURAÇÃO MODELOS (FAILOVER) -----------------
MODELOS_POSSIVEIS = [
    "models/gemini-1.5-flash",        # Mais atual e robusto
    "models/gemini-flash-latest",     # Alternativa
    "models/gemini-1.5-pro-latest"    # Último recurso
]

# ----------------- 3. CONFIGURAÇÃO DE SEGURANÇA (IMPORTANTE) -----------------
# Desativa filtros para permitir termos médicos/farmacêuticos
SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]

# ----------------- 4. PROCESSAMENTO INTELIGENTE -----------------
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
            full_text = [para.text for para in doc.paragraphs]
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
        with st.spinner("Processando... Lendo documentos complexos..."):
            f1.seek(0)
            f2.seek(0)
            
            conteudo1 = process_file_content(f1)
            conteudo2 = process_file_content(f2)
            
            # --- CONSTRUÇÃO DO PROMPT SEGURA (SEM F-STRING COMPLEXA) ---
            intro_prompt = f"Você é um EXTRATOR FORENSE DE TEXTO FARMACÊUTICO.\nINPUT: Documentos.\nTAREFA: Extrair e comparar as seções: {SECOES_COMPLETAS}\n"
            
            regras_prompt = """
            ⚠️ PROTOCOLO DE EXTRAÇÃO (CRUCIAL):
            1. **INTEGRIDADE TOTAL:** Extraia TODO o texto de cada seção. NÃO RESUMA. NÃO CORTE. Vá até o último ponto final.
            2. **NEGRITO VISUAL:** Se houver texto em **negrito**, envolva-o na tag <b> e </b>.
            3. **LAYOUT PONTILHADO:** Ignore linhas de pontinhos longas (ex: "Cloridrato .......... 5mg"). Transcreva apenas "Cloridrato 5mg".
            4. **NÃO ALUCINE:** Copie exatamente o que vê.

            ⚠️ PROTOCOLO DE JSON E ASPAS:
            - NUNCA use aspas duplas (") dentro do texto sem escapá-las (\").
            - Para tags HTML, use aspas simples: <span class='highlight-yellow'>.

            🚨 COMPARAÇÃO:
            - Compare ARTE vs GRÁFICA.
            - Marque divergências na GRÁFICA com <span class='highlight-yellow'>TEXTO ERRADO</span>.

            SAÍDA JSON OBRIGATÓRIA:
            {
                "data_anvisa_ref": "dd/mm/aaaa",
                "data_anvisa_grafica": "dd/mm/aaaa",
                "secoes": [
                    {
                        "titulo": "NOME DA SEÇÃO",
                        "texto_arte": "Texto COMPLETO da arte",
                        "texto_grafica": "Texto COMPLETO da gráfica",
                        "status": "CONFORME"
                    }
                ]
            }
            """
            
            # Junta as partes do prompt
            final_prompt = intro_prompt + regras_prompt
            
            payload = [final_prompt, "--- ARTE (REFERÊNCIA) ---"] + conteudo1 + ["--- GRÁFICA (VALIDAÇÃO) ---"] + conteudo2
            
            response = None
            ultimo_erro = ""

            # Loop de Chaves
            for api_key in keys_validas:
                genai.configure(api_key=api_key)
                
                # Loop de Modelos
                for model_name in MODELOS_POSSIVEIS:
                    try:
                        # CONFIGURAÇÃO DE SEGURANÇA E TOKENS
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
                        continue 
                
                if response: break

            if response:
                try:
                    if not response.parts:
                        st.error(f"Erro: O modelo bloqueou a resposta. Detalhes: {response.prompt_feedback}")
                        st.stop()

                    texto_limpo = response.text.replace("```json", "").replace("```", "").strip()
                    texto_limpo = re.sub(r'\.{4,}', '...', texto_limpo)

                    resultado = json.loads(texto_limpo, strict=False)
                    
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

                    div_count = sum(1 for s in secoes if s.get('status') != 'CONFORME')
                    ok_count = len(secoes) - div_count
                    
                    b1, b2 = st.columns(2)
                    b1.success(f"✅ **Conformes: {ok_count}**")
                    if div_count > 0: b2.warning(f"⚠️ **Divergentes: {div_count}**")
                    else: b2.success("✨ **Divergentes: 0**")
                    
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
                    st.error("Erro na leitura dos dados (JSON).")
                    st.warning("O documento pode ser muito extenso ou conter caracteres inválidos.")
                except Exception as e:
                    st.error(f"Erro no processamento: {e}")
            else:
                 st.error(f"Não foi possível conectar. Erro: {ultimo_erro}")

    else:
        st.warning("Adicione os arquivos.")
