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

# ----------------- ESTILOS CSS -----------------
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
        transition: all 0.3s;
        border: none;
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
    .mistral-small-badge { background-color: #e8f5e9; color: #2e7d32; border: 2px solid #a5d6a7; }
    .mistral-large-badge { background-color: #e3f2fd; color: #1565c0; border: 2px solid #90caf9; }
    .gemini-badge { background-color: #fff3e0; color: #e65100; border: 2px solid #ffb74d; }
    
    .box-content { 
        background-color: #ffffff; 
        padding: 15px; 
        border-radius: 8px; 
        font-size: 0.9em; 
        white-space: pre-wrap; 
        line-height: 1.5; 
        border: 1px solid #e0e0e0;
        min-height: 60px;
        color: #2c3e50;
    }
    .box-bel { background-color: #f1f8e9; border-left: 4px solid #7cb342; }
    .box-ref { background-color: #f5f5f5; border-left: 4px solid #757575; }
    
    mark.diff { background-color: #ffeb3b !important; color: #000; padding: 2px 5px; border-radius: 4px; font-weight: 800; }
    mark.ort { background-color: #ff1744 !important; color: #fff; padding: 2px 5px; border-radius: 4px; font-weight: 800; }
    mark.anvisa { background-color: #00e5ff !important; color: #000; padding: 2px 5px; border-radius: 4px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# ----------------- CONSTANTES (SUA LISTA ATUALIZADA) -----------------
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

# ----------------- FUNÇÕES BACKEND -----------------

def configure_apis():
    gem_key = st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if gem_key: genai.configure(api_key=gem_key)
    mis_key = st.secrets.get("MISTRAL_API_KEY") or os.environ.get("MISTRAL_API_KEY")
    mistral_client = Mistral(api_key=mis_key) if mis_key else None
    return (gem_key is not None), mistral_client

def clean_text_layout(text):
    """Limpa ruídos de layout para ajudar a IA a achar títulos"""
    # Remove excesso de quebras de linha que quebram frases no meio
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Remove espaços excessivos
    text = re.sub(r'[ \t]+', ' ', text)
    return text.strip()

def ocr_with_gemini_flash(images):
    """OCR Rápido"""
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = "Transcreva TODO o texto desta bula médica. Mantenha a ordem de leitura das colunas corretamente."
        response = model.generate_content([prompt, *images], safety_settings=SAFETY)
        return response.text if response.text else ""
    except:
        return ""

def extract_content(uploaded_file):
    if not uploaded_file: return None
    try:
        file_bytes = uploaded_file.read()
        filename = uploaded_file.name.lower()
        
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            return {"data": clean_text_layout(text), "method": "DOCX", "len": len(text)}

        elif filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            full_text = ""
            for page in doc:
                full_text += page.get_text() + "\n"
            
            avg_chars = len(full_text) / max(1, len(doc))
            
            # Se tem texto selecionável suficiente
            if avg_chars > 200:
                doc.close()
                return {"data": clean_text_layout(full_text), "method": "PDF Texto", "len": len(full_text)}
            
            # Se for imagem/curvas
            st.toast(f"👁️ '{filename}': OCR (Layout Curvas)...", icon="⚡")
            images = []
            limit = min(12, len(doc)) # Reduzi levemente o limite para ganhar velocidade
            for i in range(limit):
                pix = doc[i].get_pixmap(matrix=fitz.Matrix(1.5, 1.5)) # Matrix 1.5 é mais rápida e suficiente
                images.append(Image.open(io.BytesIO(pix.tobytes("png"))))
            doc.close()
            
            ocr_text = ocr_with_gemini_flash(images)
            return {"data": ocr_text, "method": "OCR AI", "len": len(ocr_text)}

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
        
        # Fuzzy match simples
        if not match:
            for k, v in mapa.items():
                if k in tit or tit in k:
                    match = v
                    break
        
        if match:
            sec["titulo"] = match
            normalized.append(sec)
            
    # Ordenação forçada pela lista oficial
    normalized.sort(key=lambda x: allowed_titles.index(x["titulo"]) if x["titulo"] in allowed_titles else 999)
    data["SECOES"] = normalized
    return data

def get_audit_prompt(secoes_lista):
    secoes_txt = "\n".join([f"- {s}" for s in secoes_lista])
    secoes_ignorar = ", ".join(SECOES_IGNORAR_DIFF)
    
    prompt = f"""Você é um Auditor Farmacêutico.
TAREFA: Localizar as seções listada abaixo no texto da bula e comparar REFERÊNCIA vs CANDIDATO ("bel").

MAPA DE SEÇÕES (OBRIGATÓRIO ENCONTRAR E MAPEAR):
{secoes_txt}

INSTRUÇÃO DE LAYOUT: O texto pode estar em colunas quebradas. Reconstrua as frases logicamente.
INSTRUÇÃO DE TÍTULOS: Se o título no texto for ligeiramente diferente (ex: "Posologia" vs "POSOLOGIA E MODO DE USAR"), considere como encontrado e use o título da lista acima.

--- REGRAS DE COMPARAÇÃO ---

1. SEÇÕES ESPECIAIS [{secoes_ignorar}]:
   - Extraia o texto completo.
   - Status: "OK".
   - NÃO MARQUE DIVERGÊNCIAS (Ignore amarelo).

2. DEMAIS SEÇÕES:
   - Compare palavra por palavra.
   - Diferenças (texto/número/pontuação) -> use <mark class='diff'>texto do candidato</mark>
   - Erros de português -> use <mark class='ort'>erro</mark>
   - Data Anvisa -> use <mark class='anvisa'>dd/mm/aaaa</mark>

SAÍDA JSON (Apenas o JSON):
{{
    "METADADOS": {{ "datas": ["dd/mm/aaaa"], "produto": "Nome" }},
    "SECOES": [
        {{
            "titulo": "TITULO DA LISTA ACIMA",
            "ref": "Texto extraído da referência...",
            "bel": "Texto do candidato com tags <mark>...",
            "status": "OK" | "DIVERGENTE" | "FALTANTE"
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
f1 = c1.file_uploader("📂 Referência", type=["pdf", "docx"])
f2 = c2.file_uploader("📂 Candidato", type=["pdf", "docx"])

if st.button("🚀 INICIAR AUDITORIA RÁPIDA"):
    if not f1 or not f2:
        st.warning("⚠️ Arquivos necessários.")
        st.stop()
        
    bar = st.progress(0, "Lendo arquivos...")
    
    # 1. Leitura
    d1 = extract_content(f1)
    bar.progress(30, "Ref OK...")
    d2 = extract_content(f2)
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
        # LÓGICA DE VELOCIDADE
        if pag in ["Ref x BELFAR", "Conferência MKT"]:
            if not mis_client:
                st.error("Mistral API ausente.")
                st.stop()
            
            # Limite aumentado para 80k para favorecer velocidade (Small é muito mais rápido)
            # O Prompt melhorado garante que ele ache as seções mesmo sendo "Small"
            if tot_len < 80000:
                model_id = "mistral-small-latest"
                model_name = "Mistral Small (Turbo)"
                msg_status = "🌪️ Analisando Rápido (Mistral Turbo)..."
            else:
                model_id = "mistral-large-latest"
                model_name = "Mistral Large (Preciso)"
                msg_status = "🧠 Analisando Detalhado (Mistral Large)..."
            
            bar.progress(70, msg_status)
            
            # Streaming sempre ativo para evitar travamentos
            stream = mis_client.chat.stream(
                model=model_id,
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

        else: # Gráfica (Gemini)
            if not gem_ok:
                st.error("Gemini API ausente.")
                st.stop()
            bar.progress(70, "💎 Analisando (Gemini Pro)...")
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
            
            badges = {"Small": "mistral-small-badge", "Large": "mistral-large-badge", "Gemini": "gemini-badge"}
            css = next((v for k, v in badges.items() if k in model_name), "mistral-small-badge")
            
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
