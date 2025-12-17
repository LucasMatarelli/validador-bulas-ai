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
    page_icon="🎯",
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
        padding: 18px; 
        border-radius: 10px; 
        font-size: 0.95em; 
        white-space: pre-wrap; 
        line-height: 1.6; 
        border: 1px solid #e0e0e0;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        min-height: 80px;
        color: #2c3e50;
    }
    .box-bel { background-color: #f9fbe7; border-left: 5px solid #827717; }
    .box-ref { background-color: #f5f5f5; border-left: 5px solid #757575; }
    
    mark.diff { 
        background-color: #ffeb3b !important; 
        color: #000 !important;
        padding: 2px 6px; 
        border-radius: 4px; 
        font-weight: 800; 
        border: 1px solid #f9a825;
        text-decoration: none;
        display: inline-block;
    }
    mark.ort { 
        background-color: #ff1744 !important; 
        color: #fff !important; 
        padding: 2px 6px; 
        border-radius: 4px; 
        font-weight: 800; 
        border: 1px solid #b71c1c;
        text-decoration: underline wavy #fff;
        display: inline-block;
    }
    mark.anvisa { 
        background-color: #00e5ff !important; 
        color: #000 !important; 
        padding: 2px 6px; 
        border-radius: 4px; 
        font-weight: bold; 
        border: 1px solid #006064; 
    }
    
    h1, h2, h3 { font-family: 'Segoe UI', sans-serif; color: #2c3e50; }
</style>
""", unsafe_allow_html=True)

# ----------------- CONSTANTES -----------------
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

def ocr_with_gemini_flash(images):
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = "Transcreva TODO o texto desta bula médica EXATAMENTE como está. Mantenha tabelas e estrutura."
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
            return {"data": text, "method": "DOCX Nativo", "len": len(text)}

        elif filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            full_text = ""
            for page in doc:
                full_text += page.get_text() + "\n"
            
            avg_chars = len(full_text) / max(1, len(doc))
            
            if avg_chars > 200:
                doc.close()
                return {"data": full_text, "method": "PDF Nativo", "len": len(full_text)}
            
            st.toast(f"👁️ '{filename}': Modo OCR...", icon="⚡")
            images = []
            limit = min(15, len(doc))
            for i in range(limit):
                pix = doc[i].get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
                images.append(Image.open(io.BytesIO(pix.tobytes("png"))))
            doc.close()
            
            ocr_text = ocr_with_gemini_flash(images)
            if ocr_text:
                return {"data": ocr_text, "method": "OCR Gemini Flash", "len": len(ocr_text)}
            else:
                return {"data": "", "method": "Falha OCR", "len": 0}

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
        
        if not match:
            for k, v in mapa.items():
                if k in tit or tit in k:
                    match = v
                    break
        
        if match:
            sec["titulo"] = match
            normalized.append(sec)
            
    normalized.sort(key=lambda x: allowed_titles.index(x["titulo"]) if x["titulo"] in allowed_titles else 999)
    data["SECOES"] = normalized
    return data

def get_audit_prompt(secoes_lista):
    secoes_txt = "\n".join([f"- {s}" for s in secoes_lista])
    secoes_ignorar = ", ".join(SECOES_IGNORAR_DIFF)
    
    prompt = f"""Você é um Auditor de Qualidade Farmacêutica (QA).
TAREFA: Extrair seções e comparar o texto da REFERÊNCIA vs CANDIDATO ("bel").

SEÇÕES OBRIGATÓRIAS (Processe o documento todo):
{secoes_txt}

--- REGRAS DE COMPARAÇÃO ---

[CASO 1: SEÇÕES ESPECIAIS -> {secoes_ignorar}]
- Nestas: APENAS COPIE O TEXTO. NÃO MARQUE DIVERGÊNCIAS. 
- Status sempre "OK".

[CASO 2: OUTRAS SEÇÕES]
- Compare palavra por palavra.
- Se houver diferença no CANDIDATO, marque com HTML:
  <mark class='diff'>texto diferente</mark>
- Se houver erro de português grave:
  <mark class='ort'>erro</mark>
- Se for data da Anvisa:
  <mark class='anvisa'>dd/mm/aaaa</mark>

OUTPUT JSON (Estrito):
{{
    "METADADOS": {{ "datas": ["dd/mm/aaaa"], "produto": "Nome" }},
    "SECOES": [
        {{
            "titulo": "EXATO DA LISTA",
            "ref": "Texto referência...",
            "bel": "Texto candidato com tags <mark> se houver erro...",
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
    tipo = st.radio("Tipo:", ["Paciente", "Profissional"], horizontal=True)
    lista_alvo = SECOES_PROFISSIONAL if tipo == "Profissional" else SECOES_PACIENTE
else:
    lista_alvo = SECOES_PACIENTE

st.markdown("---")

c_up1, c_up2 = st.columns(2)
with c_up1:
    f1 = st.file_uploader("📂 Arquivo Referência (Padrão)", type=["pdf", "docx"])
with c_up2:
    f2 = st.file_uploader("📂 Arquivo Candidato (Validar)", type=["pdf", "docx"])

if st.button("🚀 INICIAR AUDITORIA INTELIGENTE"):
    if not f1 or not f2:
        st.warning("⚠️ Envie os dois arquivos.")
        st.stop()
        
    bar = st.progress(0, "Lendo arquivos...")
    
    # 1. Leitura
    d1 = extract_content(f1)
    bar.progress(30, "Referência ok...")
    d2 = extract_content(f2)
    bar.progress(60, "Candidato ok...")
    
    if not d1 or not d2:
        st.error("Erro leitura.")
        st.stop()
        
    total_len = d1['len'] + d2['len']
    st.caption(f"Ref: {d1['len']} | Cand: {d2['len']} | Total: {total_len} chars")
    
    # 2. Processamento IA
    sys_prompt = get_audit_prompt(lista_alvo)
    user_prompt = f"--- TEXTO REF ---\n{d1['data']}\n\n--- TEXTO CANDIDATO ---\n{d2['data']}"
    
    json_res = ""
    model_name = ""
    start_t = time.time()
    
    try:
        # LÓGICA DE ROTEAMENTO HÍBRIDO
        if pag in ["Ref x BELFAR", "Conferência MKT"]:
            if not mis_client:
                st.error("Erro: API Mistral não configurada.")
                st.stop()
            
            # DECISÃO INTELIGENTE BASEADA NO TAMANHO
            # Limite de segurança: 15.000 caracteres (aprox. 5 páginas cheias)
            if total_len < 15000:
                model_id = "mistral-small-latest"
                model_name = "Mistral Small (Turbo)"
                msg_status = "🌪️ Mistral Small (Rápido) Analisando..."
            else:
                model_id = "mistral-large-latest"
                model_name = "Mistral Large (Preciso)"
                msg_status = "🧠 Mistral Large (Pesado/Streaming) Analisando..."
            
            bar.progress(70, msg_status)
            
            # USO DO STREAMING (Resolve o problema do Timeout)
            stream_response = mis_client.chat.stream(
                model=model_id,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
                timeout_ms=300000 # 5 min timeout de conexão (segurança)
            )
            
            chunks = []
            for chunk in stream_response:
                if chunk.data.choices[0].delta.content:
                    chunks.append(chunk.data.choices[0].delta.content)
            json_res = "".join(chunks)

        else: # Gráfica (Gemini)
            if not gem_ok:
                st.error("Erro: API Gemini não configurada.")
                st.stop()
                
            bar.progress(70, "💎 Gemini Pro Analisando...")
            model_name = "Gemini 1.5 Pro"
            
            model = genai.GenerativeModel("gemini-1.5-pro")
            resp = model.generate_content(
                f"{sys_prompt}\n\n{user_prompt}",
                generation_config={"response_mime_type": "application/json", "temperature": 0.0}
            )
            json_res = resp.text
            
    except Exception as e:
        st.error(f"❌ Erro na IA: {e}")
        st.stop()
        
    bar.progress(100, "Concluído!")
    time.sleep(0.5)
    bar.empty()
    
    # 3. Resultados
    if json_res:
        dados = clean_json_response(json_res)
        if dados:
            dados = normalize_sections(dados, lista_alvo)
            
            duracao = time.time() - start_t
            
            # Define cor do badge
            if "Small" in model_name: cls_css = "mistral-small-badge"
            elif "Large" in model_name: cls_css = "mistral-large-badge"
            else: cls_css = "gemini-badge"
                
            st.markdown(f"<div class='ia-badge {cls_css}'>Processado por: {model_name} em {duracao:.1f}s</div>", unsafe_allow_html=True)
            
            secoes = dados.get("SECOES", [])
            auditaveis = [s for s in secoes if s['titulo'] not in SECOES_IGNORAR_DIFF]
            erros = sum(1 for s in auditaveis if s.get("status") != "OK")
            
            cM1, cM2, cM3 = st.columns(3)
            cM1.metric("Seções", len(auditaveis))
            cM2.metric("Divergências", erros)
            
            dt = dados.get("METADADOS", {}).get("datas", ["-"])[0]
            cM3.markdown(f"**Data Anvisa:** <mark class='anvisa'>{dt}</mark>", unsafe_allow_html=True)
            
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
                    cR.markdown("<b>Referência</b>", unsafe_allow_html=True)
                    cR.markdown(f"<div class='box-content box-ref'>{sec.get('ref','')}</div>", unsafe_allow_html=True)
                    
                    cB.markdown("<b>Candidato</b>", unsafe_allow_html=True)
                    cB.markdown(f"<div class='box-content box-bel'>{sec.get('bel','')}</div>", unsafe_allow_html=True)
        else:
            st.error("Falha ao ler resposta da IA.")
            st.code(json_res)
