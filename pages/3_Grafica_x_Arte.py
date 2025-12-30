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
st.set_page_config(page_title="Validador Farmacêutico (OCR + Auto-Repair)", page_icon="🛡️", layout="wide")

st.markdown("""
<style>
    [data-testid="stHeader"] { visibility: hidden; }
    
    .texto-box { 
        font-family: 'Courier New', monospace;
        font-size: 0.9rem;
        line-height: 1.5;
        color: #212529;
        background-color: #f8f9fa;
        padding: 15px;
        border-radius: 5px;
        border: 1px solid #ced4da;
        height: 100%; 
        white-space: pre-wrap;
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
# O sistema tentará o modelo mais estável primeiro
MODELOS_PARA_TENTAR = [
    "models/gemini-1.5-flash-latest",  # Melhor custo-benefício/cota
    "models/gemini-1.5-flash",         # Genérico
    "models/gemini-1.5-pro",           # Mais potente (backup)
    "models/gemini-2.0-flash-exp"      # Se a cota permitir
]

# ----------------- 3. PROCESSAMENTO INTELIGENTE (OCR) -----------------
def process_file_content(uploaded_file):
    """
    Lê o arquivo. Se for PDF escaneado (sem texto digital), converte para imagem
    para obrigar o Gemini a fazer OCR.
    """
    try:
        filename = uploaded_file.name.lower()
        if filename.endswith(".pdf"):
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            full_text = ""
            
            # 1. Tenta extrair texto digital
            for page in doc:
                text = page.get_text("text", sort=True)
                full_text += text + "\n"
            
            # 2. DECISÃO INTELIGENTE:
            # Se tiver menos de 100 caracteres, provavelmente é imagem/escaneado.
            # Então convertemos para imagem para o Gemini ler.
            if len(full_text.strip()) < 100:
                images = []
                for page in doc:
                    # Alta resolução (300 DPI) para leitura correta
                    pix = page.get_pixmap(matrix=fitz.Matrix(3.0, 3.0)) 
                    images.append(Image.open(io.BytesIO(pix.tobytes("jpeg"))))
                return images
            else:
                return [full_text]

        elif filename.endswith((".jpg", ".png", ".jpeg")):
            return [Image.open(uploaded_file)]
        elif filename.endswith(".docx"):
            doc = docx.Document(uploaded_file)
            return ["\n".join([p.text for p in doc.paragraphs])]
    except: return []

def repair_json(json_str):
    """Tenta consertar JSON cortado violentamente pelo modelo"""
    json_str = json_str.strip()
    
    # Se não termina com chaves/colchetes, tenta fechar
    if not json_str.endswith("}") and not json_str.endswith("]"):
        # Tenta fechar aspas se estiverem abertas
        if json_str.count('"') % 2 != 0:
            json_str += '"'
        
        # Fecha estruturas comuns do nosso prompt
        if "secoes" in json_str and not json_str.endswith("]}"):
            if json_str.endswith("}"): 
                json_str += "]}"
            elif json_str.endswith("]"):
                json_str += "}"
            else:
                json_str += "}]}"
    
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
st.title("🛡️ Validador Farmacêutico (OCR Ativado)")
st.caption("Auto-Pilot: Detecta PDFs escaneados e corrige JSONs cortados.")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📂 Arte (Referência)", type=["pdf", "jpg", "png", "docx"])
f2 = c2.file_uploader("📂 Gráfica (Validação)", type=["pdf", "jpg", "png", "docx"])

if st.button("🔍 Validar Texto Integral"):
    
    keys_raw = [
        st.secrets.get("GEMINI_API_KEY"), 
        st.secrets.get("GEMINI_API_KEY2"), 
        st.secrets.get("GEMINI_API_KEY3")
    ]
    keys_validas = [k for k in keys_raw if k and len(k) > 10]

    if not keys_validas:
        st.error("Nenhuma chave API válida encontrada.")
        st.stop()

    if f1 and f2:
        with st.spinner(f"Processando arquivos (OCR + Análise)..."):
            f1.seek(0)
            f2.seek(0)
            conteudo1 = process_file_content(f1)
            conteudo2 = process_file_content(f2)
            
            # PROMPT RIGOROSO
            prompt = f"""
            ATUE COMO UM SOFTWARE DE OCR E COMPARAÇÃO FORENSE.
            
            INPUT:
            - ARTE (Pode ser imagem/PDF escaneado). Leia tudo visualmente.
            - GRÁFICA (Texto digital).
            
            TAREFA:
            1. Transcrever o texto dos dois arquivos.
            2. Comparar Arte vs Gráfica.
            
            LISTA DE TÍTULOS OBRIGATÓRIA: {SECOES_PADRAO}

            ⚠️ INSTRUÇÕES:
            - **NÃO RESUMA.** Transcreva o texto COMPLETO, caractere por caractere.
            - **TÍTULOS:** Se o título no arquivo for diferente do gabarito (ex: "Apresentação" vs "APRESENTAÇÕES"), MARQUE COMO DIVERGENTE.
            - Se um dos arquivos for imagem, FAÇA O OCR COMPLETO antes de comparar.

            SAÍDA JSON:
            {{
                "secoes": [
                    {{
                        "titulo_padrao": "Do gabarito",
                        "titulo_encontrado_arte": "Leitura Arte",
                        "titulo_encontrado_grafica": "Leitura Grafica",
                        "texto_arte": "Texto INTEGRAL...",
                        "texto_grafica": "Texto INTEGRAL...",
                        "status": "CONFORME" ou "DIVERGENTE",
                        "obs": "Divergência"
                    }}
                ]
            }}
            """
            
            safety_settings = {
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }

            response = None
            ultimo_erro = ""
            modelo_conectado = ""
            sucesso = False
            status_placeholder = st.empty()
            
            conteudo_final = [prompt, "--- ARTE (REFERÊNCIA) ---"] + conteudo1 + ["--- GRÁFICA (VALIDAÇÃO) ---"] + conteudo2

            # --- LOOP DE TENTATIVAS ---
            for modelo_atual in MODELOS_PARA_TENTAR:
                if sucesso: break
                
                for idx_k, api_key in enumerate(keys_validas):
                    try:
                        status_placeholder.info(f"⏳ Tentando: **{modelo_atual}** (Chave {idx_k+1})...")
                        
                        genai.configure(api_key=api_key)
                        model = genai.GenerativeModel(
                            modelo_atual, 
                            generation_config={
                                "response_mime_type": "application/json", 
                                "temperature": 0.0,
                                "max_output_tokens": 8192
                            },
                            safety_settings=safety_settings
                        )
                        
                        response = model.generate_content(conteudo_final)
                        
                        sucesso = True
                        modelo_conectado = modelo_atual
                        status_placeholder.success(f"✅ Conectado! Usando: **{modelo_atual}**")
                        time.sleep(1)
                        status_placeholder.empty()
                        break 

                    except Exception as e:
                        err = str(e)
                        if "404" in err or "not found" in err.lower(): break 
                        elif "429" in err or "quota" in err.lower():
                            time.sleep(0.5)
                            continue 
                        else:
                            ultimo_erro = err
                            continue
            
            if not sucesso:
                st.error("❌ Falha Total.")
                st.code(ultimo_erro)
                st.stop()
            
            # --- EXIBIÇÃO ---
            if response:
                try:
                    texto = response.text
                    # Limpeza Markdown
                    if "```json" in texto: texto = texto.split("```json")[1].split("```")[0]
                    elif "```" in texto: texto = texto.split("```")[1].split("```")[0]
                    
                    # --- TENTATIVA DE REPARO AUTOMÁTICO DE JSON ---
                    try:
                        data = json.loads(texto.strip(), strict=False)
                    except json.JSONDecodeError:
                        st.warning("⚠️ JSON cortado detectado. Tentando reparar...")
                        texto_reparado = repair_json(texto)
                        try:
                            data = json.loads(texto_reparado, strict=False)
                        except:
                            st.error("Erro fatal: O JSON foi cortado de forma irrecuperável.")
                            st.code(texto) # Mostra o que veio pra debug
                            st.stop()

                    secoes = data.get("secoes", [])

                    total = len(secoes)
                    divs = sum(1 for s in secoes if s['status'] != 'CONFORME')
                    oks = total - divs

                    st.markdown(f"### 📊 Resultado ({modelo_conectado})")
                    c1, c2 = st.columns(2)
                    c1.metric("Conformes", oks)
                    c2.metric("Divergentes", divs, delta_color="inverse")

                    if divs > 0:
                        st.error(f"❌ {divs} Divergências.")
                    else:
                        st.success("✅ Tudo Conforme.")

                    st.divider()

                    for s in secoes:
                        status = s.get('status', 'CONFORME')
                        titulo_padrao = s.get('titulo_padrao', 'Seção')
                        titulo_arte = s.get('titulo_encontrado_arte', '-')
                        titulo_graf = s.get('titulo_encontrado_grafica', '-')
                        obs = s.get('obs', '')

                        if status == "CONFORME":
                            icon, css, aberto = "✅", "border-ok", False
                        else:
                            icon, css, aberto = "🚨", "border-warn", True

                        with st.expander(f"{icon} {titulo_padrao}", expanded=aberto):
                            if titulo_arte != titulo_padrao or titulo_graf != titulo_padrao:
                                st.markdown(f"""
                                <div style="background-color: #f8d7da; padding: 10px; border-radius: 5px; margin-bottom: 10px; color: #721c24;">
                                    <strong>❌ TÍTULO INCORRETO:</strong><br>
                                    Esperado: <code>{titulo_padrao}</code><br>
                                    Arte: <code>{titulo_arte}</code> | Gráfica: <code>{titulo_graf}</code>
                                </div>
                                """, unsafe_allow_html=True)
                            
                            if obs: st.caption(f"📝 {obs}")

                            ce, cd = st.columns(2)
                            with ce:
                                st.caption("Arte")
                                st.markdown(f'<div class="texto-box {css}">{s.get("texto_arte", "")}</div>', unsafe_allow_html=True)
                            with cd:
                                st.caption("Gráfica")
                                st.markdown(f'<div class="texto-box {css}">{s.get("texto_grafica", "")}</div>', unsafe_allow_html=True)

                except Exception as e:
                    st.error("Erro grave ao processar resposta.")
                    st.code(response.text)
    else:
        st.warning("Adicione os arquivos.")
