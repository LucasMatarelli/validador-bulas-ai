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
import time
from PIL import Image
from difflib import SequenceMatcher

# ----------------- CONFIGURAÇÃO -----------------
st.set_page_config(
    page_title="Validador Turbo V2",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- ESTILOS (CSS BLINDADO) -----------------
# Removemos a dependência de classes. O estilo será inline, mas mantemos backup aqui.
st.markdown("""
<style>
    header[data-testid="stHeader"] { display: none !important; }
    .main .block-container { padding-top: 20px !important; }
    
    .stButton>button { 
        width: 100%; 
        background-color: #55a68e; 
        color: white; 
        font-weight: bold; 
        height: 60px; 
        border-radius: 12px; 
        font-size: 18px;
        border: none; 
        transition: all 0.3s;
    }
    .stButton>button:hover { background-color: #3d8070; transform: scale(1.02); }
    
    /* Caixas de Texto */
    .box-content { 
        background-color: #ffffff; 
        padding: 20px; 
        border-radius: 8px; 
        border: 1px solid #e0e0e0; 
        line-height: 1.8; 
        color: #212121;
        font-family: 'Segoe UI', sans-serif;
    }
    .box-ref { border-left: 6px solid #9e9e9e; background-color: #f5f5f5; }
    .box-bel { border-left: 6px solid #66bb6a; background-color: #f1f8e9; }
    
    .ia-badge {
        padding: 5px 10px;
        background-color: #e3f2fd;
        color: #1565c0;
        border-radius: 15px;
        font-weight: bold;
        font-size: 0.8em;
        margin-bottom: 10px;
        display: inline-block;
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

# ----------------- INTELIGÊNCIA PYTHON (PRÉ-IA) -----------------

def clean_text_structure(text):
    """Limpa quebras de linha ruins que confundem a IA"""
    # Junta linhas que foram quebradas no meio da frase
    text = re.sub(r'([a-zà-ú,])\n([a-zà-ú])', r'\1 \2', text)
    # Remove múltiplos espaços
    text = re.sub(r'[ \t]+', ' ', text)
    return text

def mark_sections_in_text(text, allowed_list):
    """
    O PYTHON ENCONTRA AS SEÇÕES E INSERE MARCADORES GIGANTES.
    Isso obriga o Mistral Turbo a ver a seção.
    """
    lines = text.split('\n')
    enhanced_text = []
    
    # Normaliza lista para busca
    clean_titles = {re.sub(r'[^A-Z]', '', t).upper(): t for t in allowed_list}
    
    for line in lines:
        line_clean = re.sub(r'[^A-Z]', '', line).upper()
        
        found = None
        # Busca exata ou muito próxima
        if line_clean in clean_titles:
            found = clean_titles[line_clean]
        else:
            # Busca parcial forte (para títulos longos)
            for k, v in clean_titles.items():
                if len(k) > 10 and k in line_clean:
                    found = v
                    break
        
        if found:
            # MARCADOR INEQUÍVOCO PARA A IA
            enhanced_text.append(f"\n\n============== SEÇÃO: {found} ==============\n")
        else:
            enhanced_text.append(line)
            
    return "\n".join(enhanced_text)

# ----------------- EXTRAÇÃO -----------------
def get_ocr_gemini(images):
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        resp = model.generate_content(["Transcreva TUDO. Não pule nada. Mantenha tabelas.", *images])
        return resp.text if resp.text else ""
    except: return ""

def extract_text(file, section_list):
    if not file: return None
    try:
        data = file.read()
        name = file.name.lower()
        text = ""
        
        if name.endswith('.docx'):
            text = "\n".join([p.text for p in docx.Document(io.BytesIO(data)).paragraphs])
        
        elif name.endswith('.pdf'):
            doc = fitz.open(stream=data, filetype="pdf")
            full_txt = ""
            for p in doc: full_txt += p.get_text() + "\n"
            
            # Decide se usa OCR
            if len(full_txt) / max(1, len(doc)) > 200:
                text = full_txt
                doc.close()
            else:
                imgs = []
                # Limita paginas para velocidade, mas garante o suficiente
                for i in range(min(15, len(doc))):
                    pix = doc[i].get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
                    imgs.append(Image.open(io.BytesIO(pix.tobytes("png"))))
                doc.close()
                text = get_ocr_gemini(imgs)

        # 1. Limpeza básica
        text = clean_text_structure(text)
        # 2. Marcação de Títulos via Python
        text = mark_sections_in_text(text, section_list)
        
        return text
    except: return ""

# ----------------- CONFIG APIs -----------------
def get_config():
    k1 = st.secrets.get("MISTRAL_API_KEY") or os.environ.get("MISTRAL_API_KEY")
    k2 = st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if k2: genai.configure(api_key=k2)
    return (Mistral(api_key=k1) if k1 else None), (k2 is not None)

mistral, gemini_ok = get_config()

# ----------------- UI -----------------
st.sidebar.title("Validador Pro")
page = st.sidebar.radio("Navegação", ["Ref x BELFAR", "Conferência MKT", "Gráfica x Arte"])

list_secs = SECOES_PACIENTE
if page == "Ref x BELFAR":
    if st.radio("Tipo", ["Paciente", "Profissional"], horizontal=True) == "Profissional":
        list_secs = SECOES_PROFISSIONAL

st.markdown(f"## 🚀 {page}")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("Referência")
f2 = c2.file_uploader("Candidato")

if st.button("🚀 AUDITAR AGORA (TURBO OTIMIZADO)"):
    if not f1 or not f2:
        st.warning("Arquivos faltando.")
        st.stop()
    
    if page in ["Ref x BELFAR", "Conferência MKT"] and not mistral:
        st.error("Mistral API necessária.")
        st.stop()
        
    bar = st.progress(0, "Lendo arquivos...")
    
    t1 = extract_text(f1, list_secs)
    bar.progress(30, "Ref OK")
    t2 = extract_text(f2, list_secs)
    bar.progress(60, "Cand OK")
    
    # ---------------- PROMPT DE ALTA PRECISÃO ----------------
    # Truque: Usamos CSS inline no prompt para garantir que o highlight funcione
    secoes_ignorar_str = ", ".join(SECOES_IGNORAR_DIFF)
    
    prompt = f"""Você é um Auditor JSON Rigoroso.
    
    SUA TAREFA:
    Localize no texto as seções marcadas como "============== SEÇÃO: TITULO ==============".
    Compare o texto da Referência com o Candidato.
    
    LISTA DE SEÇÕES OBRIGATÓRIAS (Você DEVE incluir TODAS no JSON, mesmo que vazias):
    {json.dumps(list_secs, ensure_ascii=False)}

    REGRAS DE CONTEÚDO:
    1. **NÃO RESUMA**: Traga o texto COMPLETO de cada seção. Se o texto for longo, traga TUDO.
    2. **SEÇÕES ESPECIAIS** [{secoes_ignorar_str}]:
       - Apenas copie o texto. Status: "OK". NÃO MARQUE DIFERENÇAS.
    
    REGRAS DE MARCAÇÃO (CRUCIAL):
    Nas outras seções, se houver diferença no Candidato, USE ESTILOS INLINE (Não use classes):
    - Diferença: <span style='background-color: #ffeb3b; font-weight: bold; color: black;'>TEXTO DIFERENTE</span>
    - Erro PT: <span style='background-color: #ff5252; font-weight: bold; color: white;'>ERRO</span>
    - Data: <span style='background-color: #00e5ff; font-weight: bold; color: black;'>DATA</span>

    SAÍDA JSON APENAS:
    {{
        "METADADOS": {{ "datas": [], "produto": "" }},
        "SECOES": [
            {{
                "titulo": "TITULO EXATO DA LISTA",
                "ref": "Texto completo...",
                "bel": "Texto com <span style...>tags</span>...",
                "status": "OK" ou "DIVERGENTE"
            }}
        ]
    }}
    """
    
    json_res = ""
    model_used = ""
    start_t = time.time()
    
    try:
        # LÓGICA ROTEAMENTO
        if page in ["Ref x BELFAR", "Conferência MKT"]:
            model_used = "Mistral Small (Turbo)"
            bar.progress(75, "🌪️ Mistral Turbo Analisando (Streaming)...")
            
            # Streaming para evitar timeout + Prompt reforçado
            stream = mistral.chat.stream(
                model="mistral-small-latest",
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": f"REFERENCIA:\n{t1}\n\nCANDIDATO:\n{t2}"}
                ],
                response_format={"type": "json_object"},
                temperature=0.0
            )
            
            chunks = []
            for chunk in stream:
                if chunk.data.choices[0].delta.content:
                    chunks.append(chunk.data.choices[0].delta.content)
            json_res = "".join(chunks)
            
        else: # Gemini
            if not gemini_ok: st.error("Gemini Key missing"); st.stop()
            model_used = "Gemini 1.5 Pro"
            bar.progress(75, "💎 Gemini Analisando...")
            resp = genai.GenerativeModel("gemini-1.5-pro").generate_content(
                f"{prompt}\n\nREFERENCIA:\n{t1}\n\nCANDIDATO:\n{t2}",
                generation_config={"response_mime_type": "application/json"}
            )
            json_res = resp.text
            
    except Exception as e:
        st.error(f"Erro IA: {e}")
        st.stop()
        
    bar.progress(100, "Concluído!")
    time.sleep(0.5)
    bar.empty()
    
    # RENDERIZAÇÃO
    if json_res:
        # Limpeza do JSON
        json_res = json_res.replace("```json", "").replace("```", "").strip()
        try:
            data = json.loads(json_res)
        except:
            st.error("Erro ao processar resposta da IA. Tente novamente.")
            st.stop()
            
        # Normalização e Ordenação
        secs = []
        raw_secs = data.get("SECOES", [])
        
        # Mapeamento para garantir ordem e nomes corretos
        for target_title in list_secs:
            found_sec = None
            # Procura a seção na resposta da IA
            for s in raw_secs:
                # Limpa strings para comparação
                t_ia = re.sub(r'[^A-Z]', '', s.get('titulo','').upper())
                t_target = re.sub(r'[^A-Z]', '', target_title.upper())
                
                if t_target in t_ia or t_ia in t_target:
                    found_sec = s
                    break
            
            if found_sec:
                found_sec['titulo'] = target_title # Força o nome correto
                secs.append(found_sec)
            else:
                # Se a IA comeu a seção, cria uma vazia avisando
                secs.append({
                    "titulo": target_title,
                    "ref": "Não encontrado no texto.",
                    "bel": "Não encontrado no texto.",
                    "status": "FALTANTE"
                })

        diverg = sum(1 for s in secs if s['status'] != "OK" and s['titulo'] not in SECOES_IGNORAR_DIFF)
        
        # Header Resultados
        st.markdown(f"<div class='ia-badge'>Motor: {model_used} ({time.time()-start_t:.1f}s)</div>", unsafe_allow_html=True)
        cM1, cM2, cM3 = st.columns(3)
        cM1.metric("Seções", len(secs))
        cM2.metric("Divergências", diverg)
        dt = data.get("METADADOS", {}).get("datas", ["-"])[0]
        cM3.markdown(f"**Anvisa:** {dt}")
        
        st.markdown("---")
        
        for s in secs:
            title = s['titulo']
            status = s['status']
            
            # Ícones e Cores
            icon = "✅"
            if "DIVERGENTE" in status: icon = "❌"
            elif "FALTANTE" in status: icon = "🚨"
            
            if title in SECOES_IGNORAR_DIFF:
                icon = "🔒"
                status = "OK (Conteúdo Extraído)"
            
            # Expander
            aberto = (status != "OK" and "Conteúdo" not in status)
            with st.expander(f"{icon} {title} - {status}", expanded=aberto):
                cR, cB = st.columns(2)
                # O parâmetro unsafe_allow_html=True aqui é OBRIGATÓRIO para o highlight funcionar
                cR.markdown(f"<div class='box-content box-ref'>{s.get('ref','')}</div>", unsafe_allow_html=True)
                cB.markdown(f"<div class='box-content box-bel'>{s.get('bel','')}</div>", unsafe_allow_html=True)
