import streamlit as st
import google.generativeai as genai
from mistralai import Mistral
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import fitz  # PyMuPDF
import docx
import io
import json
import re
import os
import gc
import time
from PIL import Image

# ----------------- CONFIGURAÇÃO DA PÁGINA -----------------
st.set_page_config(
    page_title="Validador Híbrido Pro",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- ESTILOS CSS (TABELA E HIGHLIGHT) -----------------
st.markdown("""
<style>
    header[data-testid="stHeader"] { display: none !important; }
    .main .block-container { padding-top: 20px !important; }
    
    .stButton>button { 
        width: 100%; 
        background-color: #55a68e; 
        color: white; 
        font-weight: bold; 
        border-radius: 10px; 
        height: 55px; 
        font-size: 16px; 
        border: none;
        transition: all 0.3s;
    }
    .stButton>button:hover { background-color: #3d8070; transform: scale(1.01); }
    
    .ia-badge { 
        padding: 6px 12px; 
        border-radius: 6px; 
        font-weight: bold; 
        font-size: 0.85em; 
        margin-bottom: 15px; 
        display: inline-block; 
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .mistral-badge { background-color: #e3f2fd; color: #1565c0; border: 2px solid #90caf9; }
    .gemini-badge { background-color: #fff3e0; color: #e65100; border: 2px solid #ffb74d; }
    
    /* ESTILO DAS CAIXAS DE TEXTO */
    .box-content { 
        background-color: #ffffff; 
        padding: 15px; 
        border-radius: 8px; 
        font-family: 'Segoe UI', sans-serif;
        font-size: 0.95em; 
        white-space: pre-wrap; 
        line-height: 1.6; 
        border: 1px solid #e0e0e0;
        min-height: 60px;
        color: #2c3e50;
    }
    .box-bel { background-color: #f1f8e9; border-left: 5px solid #7cb342; }
    .box-ref { background-color: #f5f5f5; border-left: 5px solid #757575; }
    
    /* MARCADORES OBRIGATÓRIOS */
    mark.diff { 
        background-color: #ffeb3b !important; 
        color: #000 !important;
        padding: 2px 5px; 
        border-radius: 4px; 
        font-weight: 800; 
        border: 1px solid #f9a825;
        text-decoration: none;
    }
    mark.ort { 
        background-color: #ff1744 !important; 
        color: #fff !important; 
        padding: 2px 5px; 
        border-radius: 4px; 
        font-weight: 800; 
        border: 1px solid #b71c1c;
        text-decoration: underline wavy #fff;
    }
    mark.anvisa { 
        background-color: #00e5ff !important; 
        color: #000 !important; 
        padding: 2px 5px; 
        border-radius: 4px; 
        font-weight: bold; 
        border: 1px solid #006064; 
    }
</style>
""", unsafe_allow_html=True)

# ----------------- LISTAS OBRIGATÓRIAS -----------------
SECOES_PACIENTE = [
    "APRESENTAÇÕES", "COMPOSIÇÃO", "PARA QUE ESTE MEDICAMENTO É INDICADO", 
    "COMO ESTE MEDICAMENTO FUNCIONA?", "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?", 
    "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?", 
    "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?", 
    "COMO DEVO USAR ESTE MEDICAMENTO?", 
    "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?", 
    "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?", 
    "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?", 
    "DIZERES LEGAIS"
]

SECOES_PROFISSIONAL = [
    "APRESENTAÇÕES", "COMPOSIÇÃO", "INDICAÇÕES", "RESULTADOS DE EFICÁCIA", 
    "CARACTERÍSTICAS FARMACOLÓGICAS", "CONTRAINDICAÇÕES", "ADVERTÊNCIAS E PRECAUÇÕES", 
    "INTERAÇÕES MEDICAMENTOSAS", "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO", 
    "POSOLOGIA E MODO DE USAR", "REAÇÕES ADVERSAS", "SUPERDOSE", "DIZERES LEGAIS"
]

SECOES_IGNORAR_DIFF = ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]

SAFETY = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# ----------------- FUNÇÕES DO SISTEMA -----------------

def configure_apis():
    gem_key = st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if gem_key: genai.configure(api_key=gem_key)
    mis_key = st.secrets.get("MISTRAL_API_KEY") or os.environ.get("MISTRAL_API_KEY")
    mistral_client = Mistral(api_key=mis_key) if mis_key else None
    return (gem_key is not None), mistral_client

def enhance_titles(text, allowed_list):
    """
    TRUQUE DE ENGENHARIA: Adiciona marcadores '###' antes de frases que parecem títulos da lista.
    Isso ajuda a IA a 'achar' as seções mesmo que o layout esteja ruim.
    """
    lines = text.split('\n')
    enhanced_lines = []
    
    # Normaliza lista para comparação
    clean_list = [re.sub(r'[^A-Z]', '', t).upper() for t in allowed_list]
    
    for line in lines:
        clean_line = re.sub(r'[^A-Z]', '', line).upper()
        # Se a linha parece muito com um título da lista, destaca ela
        is_title = False
        for ref_title in clean_list:
            if ref_title in clean_line and len(clean_line) < len(ref_title) + 10:
                enhanced_lines.append(f"\n### {line.strip()} ###\n") # Força destaque
                is_title = True
                break
        if not is_title:
            enhanced_lines.append(line)
            
    return "\n".join(enhanced_lines)

def ocr_with_gemini_flash(images):
    """OCR Rápido"""
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = "Transcreva TODO o texto desta bula médica. Mantenha a ordem de leitura das colunas. Não pule nada."
        response = model.generate_content([prompt, *images], safety_settings=SAFETY)
        return response.text if response.text else ""
    except:
        return ""

def extract_content(uploaded_file, section_list=None):
    if not uploaded_file: return None
    try:
        file_bytes = uploaded_file.read()
        filename = uploaded_file.name.lower()
        text = ""
        method = ""

        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            method = "DOCX"

        elif filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            full_text = ""
            for page in doc:
                full_text += page.get_text() + "\n"
            
            avg_chars = len(full_text) / max(1, len(doc))
            
            if avg_chars > 200:
                text = full_text
                method = "PDF Texto"
                doc.close()
            else:
                st.toast(f"👁️ OCR IA Ativado para '{filename}'...", icon="⚡")
                images = []
                limit = min(12, len(doc))
                for i in range(limit):
                    pix = doc[i].get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
                    images.append(Image.open(io.BytesIO(pix.tobytes("png"))))
                doc.close()
                text = ocr_with_gemini_flash(images)
                method = "OCR IA"

        # APLICA O TRUQUE DO MESTRE: MELHORAR TÍTULOS
        if section_list:
            text = enhance_titles(text, section_list)

        return {"data": text, "method": method, "len": len(text)}

    except Exception as e:
        st.error(f"Erro leitura: {e}")
        return None

def clean_json_response(text):
    if not text: return None
    clean = text.replace("```json", "").replace("```", "").strip()
    try:
        start = clean.find('{')
        end = clean.rfind('}') + 1
        return json.loads(clean[start:end])
    except:
        return None

def normalize_sections(data, allowed_titles):
    if not data or "SECOES" not in data: return data
    normalized = []
    
    def clean(s): return re.sub(r'[^A-Z0-9]', '', s.upper())
    mapa = {clean(t): t for t in allowed_titles}
    
    for sec in data["SECOES"]:
        tit = clean(sec.get("titulo", "").upper())
        match = mapa.get(tit)
        
        # Busca Fuzzy (Aproximada)
        if not match:
            for k, v in mapa.items():
                if k in tit or tit in k:
                    match = v
                    break
        
        if match:
            sec["titulo"] = match
            normalized.append(sec)
            
    # Ordenação pela lista oficial
    normalized.sort(key=lambda x: allowed_titles.index(x["titulo"]) if x["titulo"] in allowed_titles else 999)
    data["SECOES"] = normalized
    return data

def get_audit_prompt(secoes_lista):
    secoes_txt = "\n".join([f"- {s}" for s in secoes_lista])
    secoes_ignorar = ", ".join(SECOES_IGNORAR_DIFF)
    
    prompt = f"""Você é um Auditor Farmacêutico Meticuloso.
TAREFA: Mapear seções e comparar REFERÊNCIA vs CANDIDATO ("bel").

LISTA DE SEÇÕES (Você DEVE encontrar estas seções no texto. Procure por títulos similares marcados com ###):
{secoes_txt}

INSTRUÇÕES CRÍTICAS PARA O FORMATO DE SAÍDA:
1. SEÇÕES ESPECIAIS [{secoes_ignorar}]:
   - Copie o texto. Status: "OK". NÃO USE TAGS HTML.

2. TODAS AS OUTRAS SEÇÕES (Auditoria Rigorosa):
   - Você DEVE usar tags HTML EXATAS para marcar diferenças.
   - NÃO USE MARCAÇÃO MARKDOWN (**bold**). USE HTML (<mark>).
   
   EXEMPLO DO QUE EU QUERO:
   Ref: "Tomar 1 comprimido."
   Bel: "Tomar <mark class='diff'>2 comprimidos</mark>."

   TIPOS DE TAG:
   - Diferença de texto/número: <mark class='diff'>texto errado</mark>
   - Erro de português: <mark class='ort'>erro</mark>
   - Data Anvisa: <mark class='anvisa'>10/05/2024</mark>

OUTPUT JSON:
{{
    "METADADOS": {{ "datas": ["dd/mm/aaaa"], "produto": "Nome" }},
    "SECOES": [
        {{
            "titulo": "NOME DA LISTA",
            "ref": "Texto original...",
            "bel": "Texto com <mark class='diff'>tags</mark>...",
            "status": "DIVERGENTE"
        }}
    ]
}}
"""
    return prompt

# ----------------- UI -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=70)
    st.title("Validador Pro")
    st.divider()
    pag = st.radio("Navegação", ["Ref x BELFAR", "Conferência MKT", "Gráfica x Arte"])
    st.divider()
    gem_ok, mis_client = configure_apis()
    c1, c2 = st.columns(2)
    c1.markdown(f"Mistral: {'✅' if mis_client else '❌'}")
    c2.markdown(f"Gemini: {'✅' if gem_ok else '❌'}")

# ----------------- MAIN -----------------
st.markdown(f"## 🚀 Auditoria: {pag}")

if pag == "Ref x BELFAR":
    tipo = st.radio("Tipo de Bula:", ["Paciente", "Profissional"], horizontal=True)
    lista_alvo = SECOES_PROFISSIONAL if tipo == "Profissional" else SECOES_PACIENTE
else:
    lista_alvo = SECOES_PACIENTE

st.markdown("---")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📂 Referência (Word/PDF)", type=["pdf", "docx"])
f2 = c2.file_uploader("📂 Candidato (Word/PDF)", type=["pdf", "docx"])

if st.button("🚀 INICIAR AUDITORIA COMPLETA"):
    if not f1 or not f2:
        st.warning("⚠️ Faltam arquivos.")
        st.stop()
        
    bar = st.progress(0, "Lendo arquivos...")
    
    # 1. Leitura (Com Boost de Títulos)
    d1 = extract_content(f1, lista_alvo)
    bar.progress(30, "Ref OK...")
    d2 = extract_content(f2, lista_alvo)
    bar.progress(60, "Cand OK...")
    
    if not d1 or not d2:
        st.error("Erro na leitura.")
        st.stop()
        
    tot_len = d1['len'] + d2['len']
    st.caption(f"Ref: {d1['len']} | Cand: {d2['len']} | Total: {tot_len}")
    
    # 2. IA
    sys_prompt = get_audit_prompt(lista_alvo)
    user_prompt = f"--- TEXTO REF ---\n{d1['data']}\n\n--- TEXTO CANDIDATO ---\n{d2['data']}"
    
    json_res = ""
    model_name = ""
    start_t = time.time()
    
    try:
        if pag in ["Ref x BELFAR", "Conferência MKT"]:
            if not mis_client:
                st.error("Mistral API ausente.")
                st.stop()
            
            # --- FORÇANDO MISTRAL LARGE PARA GARANTIR MARCA-TEXTO ---
            # O "Small" é rápido mas erra o HTML. O "Large" com Streaming é a solução.
            model_name = "Mistral Large (Preciso)"
            bar.progress(70, "🧠 Mistral Large Analisando (Streaming)...")
            
            stream = mis_client.chat.stream(
                model="mistral-large-latest",
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
                timeout_ms=300000
            )
            
            chunks = []
            for chunk in stream:
                if chunk.data.choices[0].delta.content:
                    chunks.append(chunk.data.choices[0].delta.content)
            json_res = "".join(chunks)

        else: # Gráfica
            if not gem_ok:
                st.error("Gemini API ausente.")
                st.stop()
            bar.progress(70, "💎 Gemini Analisando...")
            model_name = "Gemini 1.5 Pro"
            resp = genai.GenerativeModel("gemini-1.5-pro").generate_content(
                f"{sys_prompt}\n\n{user_prompt}",
                generation_config={"response_mime_type": "application/json", "temperature": 0.0}
            )
            json_res = resp.text
            
    except Exception as e:
        st.error(f"Erro IA: {e}")
        st.stop()
        
    bar.progress(100, "Concluído!")
    time.sleep(0.5)
    bar.empty()
    
    # 3. Render
    if json_res:
        dados = clean_json_response(json_res)
        if dados:
            dados = normalize_sections(dados, lista_alvo)
            duracao = time.time() - start_t
            
            css = "mistral-badge" if "Mistral" in model_name else "gemini-badge"
            st.markdown(f"<div class='ia-badge {css}'>Motor: {model_name} ({duracao:.1f}s)</div>", unsafe_allow_html=True)
            
            secoes = dados.get("SECOES", [])
            auditaveis = [s for s in secoes if s['titulo'] not in SECOES_IGNORAR_DIFF]
            erros = sum(1 for s in auditaveis if s.get("status") != "OK")
            
            m1, m2, m3 = st.columns(3)
            m1.metric("Seções Encontradas", len(secoes))
            m2.metric("Divergências", erros)
            
            dt = dados.get("METADADOS", {}).get("datas", ["-"])[0]
            m3.markdown(f"**Anvisa:** <mark class='anvisa'>{dt}</mark>", unsafe_allow_html=True)
            
            st.divider()
            
            for sec in secoes:
                tit = sec.get("titulo", "N/A")
                stat = sec.get("status", "OK")
                
                if tit in SECOES_IGNORAR_DIFF:
                    icon, lbl = "🔒", "OK (Conteúdo Extraído)"
                else:
                    if "DIVERGENTE" in stat: icon, lbl = "❌", "DIVERGENTE"
                    elif "FALTANTE" in stat: icon, lbl = "🚨", "FALTANTE"
                    else: icon, lbl = "✅", "OK"
                
                aberto = (lbl != "OK" and "Conteúdo" not in lbl)
                
                with st.expander(f"{icon} {tit} - {lbl}", expanded=aberto):
                    cR, cB = st.columns(2)
                    cR.markdown(f"<div class='box-content box-ref'>{sec.get('ref','')}</div>", unsafe_allow_html=True)
                    cB.markdown(f"<div class='box-content box-bel'>{sec.get('bel','')}</div>", unsafe_allow_html=True)
        else:
            st.error("Falha resposta IA.")
            st.code(json_res)
