import streamlit as st
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import fitz  # PyMuPDF
import docx
import io
import json
import os
import re
import time
from PIL import Image
from datetime import datetime

# --- CONFIGURAÇÕES DE USO ---
ARQUIVO_CONTADOR = "contador_diario.json"
LIMITE_POR_KEY = 20
LIMITE_TOTAL = 40  # 2 chaves

# --- MODELOS ---
MODELOS_PARA_TENTAR = [
    "models/gemini-1.5-flash",
    "models/gemini-1.5-flash-latest",
    "models/gemini-1.5-pro"
]

# ----------------- 1. GERENCIAMENTO DE CHAVES E COTA -----------------
def gerenciar_uso_diario(incrementar=False):
    hoje = datetime.now().strftime("%Y-%m-%d")
    
    if not os.path.exists(ARQUIVO_CONTADOR):
        dados = {"data": hoje, "contagem": 0}
        with open(ARQUIVO_CONTADOR, "w") as f: json.dump(dados, f)
    else:
        with open(ARQUIVO_CONTADOR, "r") as f:
            try: dados = json.load(f)
            except: dados = {"data": hoje, "contagem": 0}

    if dados.get("data") != hoje:
        dados = {"data": hoje, "contagem": 0}
        with open(ARQUIVO_CONTADOR, "w") as f: json.dump(dados, f)
        
    if incrementar and dados["contagem"] < LIMITE_TOTAL:
        dados["contagem"] += 1
        with open(ARQUIVO_CONTADOR, "w") as f: json.dump(dados, f)
        
    return dados["contagem"]

def mostrar_sidebar_contador():
    uso_atual = gerenciar_uso_diario(incrementar=False)
    restantes = LIMITE_TOTAL - uso_atual
    
    st.sidebar.divider()
    st.sidebar.markdown("### 🤖 Status do Sistema")
    
    if restantes > 0:
        st.sidebar.success(f"ONLINE")
        st.sidebar.progress(uso_atual / LIMITE_TOTAL)
        st.sidebar.caption(f"Uso Hoje: {uso_atual}/{LIMITE_TOTAL}")
    else:
        st.sidebar.error("⛔ Cota Diária Atingida")

def get_gemini_client():
    """Retorna o cliente configurado com a chave correta baseada no uso."""
    uso = gerenciar_uso_diario(incrementar=False)
    if uso >= LIMITE_TOTAL:
        st.error("Cota diária excedida. Volte amanhã.")
        st.stop()
        
    # Seleção de Chave
    if uso < LIMITE_POR_KEY:
        api_key = st.secrets.get("GEMINI_API_KEY")
    else:
        api_key = st.secrets.get("GEMINI_API_KEY2")
        
    if not api_key:
        # Fallback para tentar pegar qualquer uma que exista
        api_key = st.secrets.get("GEMINI_API_KEY") or st.secrets.get("GEMINI_API_KEY2")

    if not api_key:
        st.error("Nenhuma API KEY configurada no secrets.toml")
        st.stop()
        
    return api_key

def chamar_gemini(prompt, conteudo_anexos=[]):
    """Função robusta que tenta vários modelos e trata erros."""
    api_key = get_gemini_client()
    genai.configure(api_key=api_key)
    
    safety = {
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    }

    payload = [prompt] + conteudo_anexos

    for modelo in MODELOS_PARA_TENTAR:
        try:
            model = genai.GenerativeModel(
                modelo,
                generation_config={"response_mime_type": "application/json", "temperature": 0.0},
                safety_settings=safety
            )
            response = model.generate_content(payload)
            
            # Incrementa contador apenas se deu sucesso
            gerenciar_uso_diario(incrementar=True)
            return response.text
        except Exception as e:
            print(f"Erro no modelo {modelo}: {e}")
            continue
            
    st.error("Todos os modelos falharam. Verifique sua conexão ou API Key.")
    st.stop()

# ----------------- 2. PROCESSAMENTO DE ARQUIVOS -----------------
def processar_arquivo(uploaded_file, forcar_ocr=False):
    """
    Lê PDF (Texto ou Imagem) ou DOCX e retorna formato para o Gemini.
    forcar_ocr=True converte PDF para imagem (útil para Gráfica em curva).
    """
    if not uploaded_file: return []
    filename = uploaded_file.name.lower()

    try:
        if filename.endswith(".pdf"):
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            
            # Se forçar OCR ou se não tiver texto digital extraível
            texto_digital = "".join([page.get_text() for page in doc])
            
            if forcar_ocr or len(texto_digital.strip()) < 100:
                imagens = []
                for page in doc:
                    # Alta resolução (300 DPI aprox)
                    pix = page.get_pixmap(matrix=fitz.Matrix(3.0, 3.0))
                    img_byte = pix.tobytes("jpeg")
                    imagens.append(Image.open(io.BytesIO(img_byte)))
                return imagens
            else:
                return [texto_digital] # Retorna texto puro se for PDF digital

        elif filename.endswith(".docx"):
            doc = docx.Document(uploaded_file)
            return ["\n".join([p.text for p in doc.paragraphs])]
        
        elif filename.endswith((".jpg", ".png", ".jpeg")):
            return [Image.open(uploaded_file)]
            
    except Exception as e:
        st.error(f"Erro ao ler arquivo {filename}: {e}")
        return []

def repair_json(json_str):
    """Limpa JSON retornado pela IA."""
    json_str = json_str.strip()
    if "```json" in json_str: json_str = json_str.split("```json")[1]
    if "```" in json_str: json_str = json_str.split("```")[0]
    return json_str.strip()

# ----------------- 3. CONSTANTES COMPARTILHADAS -----------------
SECOES_PADRAO = [
    "APRESENTAÇÕES", "COMPOSIÇÃO", 
    "PARA QUE ESTE MEDICAMENTO É INDICADO", "COMO ESTE MEDICAMENTO FUNCIONA?", 
    "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?", "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?", 
    "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?", "COMO DEVO USAR ESTE MEDICAMENTO?", 
    "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?", 
    "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?", 
    "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?", 
    "DIZERES LEGAIS"
]
