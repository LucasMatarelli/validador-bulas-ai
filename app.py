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
from difflib import SequenceMatcher

# ----------------- CONFIGURAÇÃO DA PÁGINA -----------------
st.set_page_config(
    page_title="Validador Híbrido Pro",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- ESTILOS CSS (Reforçado para Highlight) -----------------
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
    .mistral-badge { background-color: #e3f2fd; color: #1565c0; border: 2px solid #90caf9; }
    .gemini-badge { background-color: #fff3e0; color: #e65100; border: 2px solid #ffb74d; }
    
    /* CAIXAS DE TEXTO */
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
        color: #333;
    }
    .box-bel { background-color: #f9fbe7; border-left: 5px solid #827717; }
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
        display: inline-block; /* Garante visibilidade */
    }
    mark.ort { 
        background-color: #ff1744 !important; 
        color: #fff !important; 
        padding: 2px 5px; 
        border-radius: 4px; 
        font-weight: 800; 
        border: 1px solid #b71c1c;
        text-decoration: underline wavy #fff;
        display: inline-block;
    }
    mark.anvisa { 
        background-color: #00e5ff !important; 
        color: #000 !important; 
        padding: 2px 5px; 
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

# ----------------- FUNÇÕES DO SISTEMA -----------------

def configure_apis():
    gem_key = st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if gem_key: genai.configure(api_key=gem_key)
    
    mis_key = st.secrets.get("MISTRAL_API_KEY") or os.environ.get("MISTRAL_API_KEY")
    mistral_client = Mistral(api_key=mis_key) if mis_key else None
    
    return (gem_key is not None), mistral_client

def ocr_with_gemini_flash(images):
    """OCR Rápido usando Gemini Flash (Backup de Leitura)"""
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = "Transcreva TODO o texto desta bula médica EXATAMENTE como está. Mantenha tabelas e estrutura. Não pule nenhuma linha."
        response = model.generate_content([prompt, *images], safety_settings=SAFETY)
        return response.text if response.text else ""
    except Exception as e:
        return ""

def extract_content(uploaded_file):
    """Extração Inteligente: Nativo primeiro, OCR se necessário"""
    if not uploaded_file: return None
    try:
        file_bytes = uploaded_file.read()
        filename = uploaded_file.name.lower()
        
        # --- DOCX ---
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            return {"data": text, "method": "DOCX Nativo", "len": len(text)}

        # --- PDF ---
        elif filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            full_text = ""
            for page in doc:
                full_text += page.get_text() + "\n"
            
            # Análise de densidade para decidir OCR
            avg_chars = len(full_text) / max(1, len(doc))
            
            if avg_chars > 200: # Se tem bastante texto, usa nativo
                doc.close()
                return {"data": full_text, "method": "PDF Nativo", "len": len(full_text)}
            
            # Se tem pouco texto, provavelmente é Curva/Imagem -> OCR
            st.toast(f"👁️ Detectado arquivo em Curvas/Imagem: '{filename}'. Ativando OCR IA...", icon="⚡")
            images = []
            limit_pages = min(15, len(doc))
            for i in range(limit_pages):
                pix = doc[i].get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
                img_data = pix.tobytes("png")
                images.append(Image.open(io.BytesIO(img_data)))
            doc.close()
            
            ocr_text = ocr_with_gemini_flash(images)
            if ocr_text:
                return {"data": ocr_text, "method": "OCR (Gemini Flash)", "len": len(ocr_text)}
            else:
                return {"data": "", "method": "Falha OCR", "len": 0}

    except Exception as e:
        st.error(f"Erro ao ler arquivo: {e}")
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
    """Garante que todas as seções encontradas sejam mapeadas"""
    if not data or "SECOES" not in data: return data
    normalized_sections = []
    
    def clean(s): return re.sub(r'[^A-Z0-9]', '', s.upper())
    mapa_allowed = {clean(t): t for t in allowed_titles}
    
    for sec in data["SECOES"]:
        titulo_ia = sec.get("titulo", "").upper()
        titulo_clean = clean(titulo_ia)
        match = mapa_allowed.get(titulo_clean)
        
        if not match:
            for k, v in mapa_allowed.items():
                if k in titulo_clean or titulo_clean in k:
                    match = v
                    break
        
        if match:
            sec["titulo"] = match
            normalized_sections.append(sec)
    
    # Ordena e coloca seções faltantes visualmente no final (opcional, aqui mantemos a ordem do documento)
    # Apenas ordenamos se estiverem na lista permitida
    normalized_sections.sort(key=lambda x: allowed_titles.index(x["titulo"]) if x["titulo"] in allowed_titles else 999)
    data["SECOES"] = normalized_sections
    return data

def get_audit_prompt(secoes_lista):
    secoes_txt = "\n".join([f"- {s}" for s in secoes_lista])
    secoes_ignorar_txt = ", ".join(SECOES_IGNORAR_DIFF)
    
    # Prompt REFORÇADO para HTML e Exaustividade
    prompt = f"""Você é um Auditor de Qualidade Farmacêutica EXTREMAMENTE PRECISO.
Sua tarefa é comparar o texto da REFERÊNCIA com o texto do CANDIDATO.

LISTA DE SEÇÕES QUE VOCÊ DEVE PROCURAR (OBRIGATÓRIO ACHAR TODAS):
{secoes_txt}

--- REGRAS CRÍTICAS DE AUDITORIA ---
1. **EXAUSTIVIDADE**: Processe o documento inteiro. Não pare no meio. Se uma seção da lista acima existe no texto, ELA TEM QUE APARECER NO JSON.
2. **FIDELIDADE**: Copie o texto EXATAMENTE como está nos arquivos. Não resuma.
3. **HTML OBRIGATÓRIO**: Nas divergências, você DEVE inserir as tags HTML dentro da string do JSON.

--- REGRAS DE COMPARAÇÃO ---

CASO 1: SEÇÕES ESPECIAIS [{secoes_ignorar_txt}]
- Nestas seções: APENAS COPIE O TEXTO.
- NÃO MARQUE DIFERENÇAS.
- NÃO USE TAGS <mark>.
- Defina status: "OK".

CASO 2: TODAS AS OUTRAS SEÇÕES
- Compare palavra por palavra.
- Se o CANDIDATO tiver qualquer diferença (letra, número, acento, palavra trocada), marque ASSIM:
  Texto original: "Tomar 10ml"
  Texto candidato: "Tomar <mark class='diff'>20ml</mark>"
  
- Se for erro de português grave:
  "<mark class='ort'>frequência</mark>" (se estiver escrito errado)

- Se for data da Anvisa:
  "<mark class='anvisa'>10/05/2024</mark>"

FORMATO DE SAÍDA JSON (Não use Markdown no JSON, apenas texto cru com as tags HTML embutidas):
{{
    "METADADOS": {{ "datas": ["dd/mm/aaaa"], "produto": "Nome" }},
    "SECOES": [
        {{
            "titulo": "TÍTULO DA SEÇÃO",
            "ref": "Texto completo da referência...",
            "bel": "Texto do candidato COM AS TAGS <mark class='diff'>...</mark> ONDE HOUVER ERRO",
            "status": "DIVERGENTE" (se tiver mark diff) ou "OK" ou "FALTANTE"
        }}
    ]
}}
"""
    return prompt

# ----------------- UI LATERAL -----------------
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

# ----------------- CORPO PRINCIPAL -----------------
st.markdown(f"## 🚀 Auditoria: {pag}")

if pag == "Ref x BELFAR":
    tipo_bula = st.radio("Tipo:", ["Paciente", "Profissional"], horizontal=True)
    lista_alvo = SECOES_PROFISSIONAL if tipo_bula == "Profissional" else SECOES_PACIENTE
else:
    lista_alvo = SECOES_PACIENTE

st.markdown("---")

col_up1, col_up2 = st.columns(2)
with col_up1:
    f1 = st.file_uploader("📂 Arquivo Referência (Padrão)", type=["pdf", "docx"])
with col_up2:
    f2 = st.file_uploader("📂 Arquivo Candidato (Validar)", type=["pdf", "docx"])

if st.button("🚀 INICIAR AUDITORIA (MODO PRECISÃO)"):
    if not f1 or not f2:
        st.warning("⚠️ Anexe os dois arquivos!")
        st.stop()

    bar = st.progress(0, "Lendo arquivos...")
    
    # 1. Leitura
    d1 = extract_content(f1)
    bar.progress(30, "Referência processada...")
    d2 = extract_content(f2)
    bar.progress(60, "Candidato processado...")
    
    if not d1 or not d2:
        st.error("Erro na leitura. Verifique os arquivos.")
        st.stop()
        
    st.caption(f"Ref: {d1['method']} ({d1['len']} chars) | Cand: {d2['method']} ({d2['len']} chars)")
    
    # 2. IA
    prompt_sistema = get_audit_prompt(lista_alvo)
    prompt_usuario = f"--- TEXTO REF ---\n{d1['data']}\n\n--- TEXTO CANDIDATO ---\n{d2['data']}"
    
    json_str = None
    modelo_usado = ""
    start_t = time.time()
    
    try:
        # ROTEAMENTO ESTRITO
        if pag in ["Ref x BELFAR", "Conferência MKT"]:
            if not mis_client:
                st.error("Erro: API Mistral não configurada.")
                st.stop()
            
            # VOLTAMOS PARA O LARGE (Para garantir que ache as seções e marque o texto)
            bar.progress(70, "🌪️ Mistral Large analisando (Pode levar 1-2 min pela precisão)...")
            modelo_usado = "Mistral Large"
            
            resp = mis_client.chat.complete(
                model="mistral-large-latest", 
                messages=[
                    {"role": "system", "content": prompt_sistema},
                    {"role": "user", "content": prompt_usuario}
                ],
                response_format={"type": "json_object"},
                temperature=0.0
            )
            json_str = resp.choices[0].message.content

        else: # Gráfica x Arte
            if not gem_ok:
                st.error("Erro: API Gemini não configurada.")
                st.stop()
                
            bar.progress(70, "💎 Gemini 1.5 Pro analisando...")
            modelo_usado = "Gemini 1.5 Pro"
            
            model = genai.GenerativeModel("gemini-1.5-pro")
            resp = model.generate_content(
                f"{prompt_sistema}\n\n{prompt_usuario}",
                generation_config={"response_mime_type": "application/json", "temperature": 0.0}
            )
            json_str = resp.text
            
    except Exception as e:
        st.error(f"Erro na IA: {str(e)}")
        st.stop()
        
    bar.progress(100, "Concluído!")
    time.sleep(0.5)
    bar.empty()
    
    # 3. Resultados
    if json_str:
        dados = clean_json_response(json_str)
        if dados:
            dados = normalize_sections(dados, lista_alvo)
            
            tempo = time.time() - start_t
            classe_css = "mistral-badge" if "Mistral" in modelo_usado else "gemini-badge"
            st.markdown(f"<div class='ia-badge {classe_css}'>Processado por: {modelo_usado} em {tempo:.1f}s</div>", unsafe_allow_html=True)
            
            secoes = dados.get("SECOES", [])
            auditadas = [s for s in secoes if s['titulo'] not in SECOES_IGNORAR_DIFF]
            erros = sum(1 for s in auditadas if s.get("status") != "OK")
            
            cM1, cM2, cM3 = st.columns(3)
            cM1.metric("Seções Auditadas", len(auditadas))
            cM2.metric("Divergências", erros)
            
            datas = dados.get("METADADOS", {}).get("datas", [])
            dt = datas[0] if datas else "-"
            cM3.markdown(f"**Data Anvisa:** <mark class='anvisa'>{dt}</mark>", unsafe_allow_html=True)
            
            st.divider()
            
            # Renderização com Segurança HTML
            for sec in secoes:
                tit = sec.get("titulo", "N/A")
                stat = sec.get("status", "OK")
                
                if tit in SECOES_IGNORAR_DIFF:
                    icon, cor_stat = "🔒", "OK (Conteúdo Extraído)"
                else:
                    if "DIVERGENTE" in stat: icon, cor_stat = "❌", "DIVERGENTE"
                    elif "FALTANTE" in stat: icon, cor_stat = "🚨", "FALTANTE"
                    else: icon, cor_stat = "✅", "OK"
                
                # Abre se tiver erro OU se for divergente
                aberto = (cor_stat != "OK" and "Conteúdo Extraído" not in cor_stat)
                
                with st.expander(f"{icon} {tit} - {cor_stat}", expanded=aberto):
                    cR, cB = st.columns(2)
                    cR.markdown("<b>Referência</b>", unsafe_allow_html=True)
                    # allow_html=True é essencial para o highlight funcionar
                    cR.markdown(f"<div class='box-content box-ref'>{sec.get('ref','')}</div>", unsafe_allow_html=True)
                    
                    cB.markdown("<b>Candidato</b>", unsafe_allow_html=True)
                    cB.markdown(f"<div class='box-content box-bel'>{sec.get('bel','')}</div>", unsafe_allow_html=True)
        else:
            st.error("Resposta inválida da IA.")
            st.code(json_str)
