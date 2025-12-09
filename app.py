import streamlit as st
import google.generativeai as genai
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
    page_title="Validador de Bulas",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- ESTILOS CSS -----------------
st.markdown("""
<style>
    header[data-testid="stHeader"] { display: none !important; }
    .main .block-container { padding-top: 20px !important; }
    .main { background-color: #f4f6f8; }
    h1, h2, h3 { color: #2c3e50; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
    
    .stCard {
        background-color: white; padding: 25px; border-radius: 15px;
        box-shadow: 0 10px 20px rgba(0,0,0,0.05); margin-bottom: 25px;
        border: 1px solid #e1e4e8; height: 100%;
    }
    .card-title { color: #55a68e; font-size: 1.2rem; font-weight: bold; margin-bottom: 15px; border-bottom: 2px solid #f0f2f5; padding-bottom: 10px; }
    .card-text { font-size: 0.95rem; color: #555; line-height: 1.6; }
    
    mark.diff { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; }
    mark.ort { background-color: #f8d7da; color: #721c24; padding: 2px 4px; border-radius: 4px; border-bottom: 2px solid #dc3545; }
    mark.anvisa { background-color: #cff4fc; color: #055160; padding: 2px 4px; border-radius: 4px; border: 1px solid #b6effb; font-weight: bold; }
    
    .stButton>button { width: 100%; background-color: #55a68e; color: white; font-weight: bold; border-radius: 10px; height: 55px; border: none; font-size: 16px; }
    .stButton>button:hover { background-color: #448c75; }
</style>
""", unsafe_allow_html=True)

# ----------------- CONSTANTES -----------------
SECOES_PACIENTE = [
    "APRESENTAÇÕES", "COMPOSIÇÃO", 
    "PARA QUE ESTE MEDICAMENTO É INDICADO", "COMO ESTE MEDICAMENTO FUNCIONA?", 
    "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?", "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?", 
    "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?", "COMO DEVO USAR ESTE MEDICAMENTO?", 
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
SECOES_SEM_DIVERGENCIA = ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]

# Configurações de segurança no mínimo para evitar bloqueios falsos
SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# ----------------- FUNÇÕES AUXILIARES -----------------
def get_api_key():
    try:
        return st.secrets["GEMINI_API_KEY"]
    except:
        return os.environ.get("GEMINI_API_KEY")

def process_uploaded_file(uploaded_file):
    if not uploaded_file: return None
    try:
        file_bytes = uploaded_file.read()
        filename = uploaded_file.name.lower()
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            return {"type": "text", "data": text}
        elif filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            images = []
            limit_pages = min(12, len(doc))
            for i in range(limit_pages):
                page = doc[i]
                pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
                try: img_byte_arr = io.BytesIO(pix.tobytes("jpeg", jpg_quality=90))
                except: img_byte_arr = io.BytesIO(pix.tobytes("png"))
                images.append(Image.open(img_byte_arr))
            doc.close(); gc.collect()
            return {"type": "images", "data": images}
    except Exception as e:
        st.error(f"Erro arquivo: {e}")
        return None

def extract_json(text):
    try:
        text = text.replace("```json", "").replace("```", "").strip()
        text = re.sub(r'//.*', '', text) # Remove comentários
        if text.startswith("json"): text = text[4:]
        start = text.find('{'); end = text.rfind('}') + 1
        if start != -1 and end != -1: return json.loads(text[start:end])
        return json.loads(text)
    except: return None

# ----------------- FUNÇÃO DE GERAÇÃO COM ROTAÇÃO DE MODELOS -----------------
def gerar_json_blindado(prompt_setup, payload_arquivos):
    """
    Tenta gerar o JSON. Se um modelo bloquear, pula para o próximo automaticamente.
    """
    api_key = get_api_key()
    if not api_key: st.error("Chave API não encontrada!"); st.stop()
    genai.configure(api_key=api_key)

    # LISTA DE PRIORIDADE: Tenta o Flash -> Se falhar, tenta o Pro -> Se falhar, tenta o Exp
    modelos = [
        'models/gemini-1.5-flash',       # Mais rápido
        'models/gemini-1.5-pro',         # Mais inteligente (menos chance de erro de copyright)
        'models/gemini-2.0-flash-exp'    # Experimental
    ]
    
    full_prompt = [prompt_setup] + payload_arquivos

    last_error = None

    # BARRA DE PROGRESSO INTERNA
    status_text = st.empty()

    for i, model_name in enumerate(modelos):
        try:
            nome_limpo = model_name.split('/')[-1]
            status_text.markdown(f"🔄 Tentativa {i+1}/3: Usando modelo **{nome_limpo}**...")
            
            model = genai.GenerativeModel(model_name, safety_settings=SAFETY_SETTINGS)
            
            response = model.generate_content(
                full_prompt,
                generation_config={"response_mime_type": "application/json"}
            )
            
            # Verifica se bloqueou por Copyright (finish reason 4) ou veio vazio
            blocked = False
            if hasattr(response.candidates[0], 'finish_reason') and response.candidates[0].finish_reason == 4:
                blocked = True
            if not response.parts:
                blocked = True
                
            if blocked:
                raise ValueError(f"Bloqueio de Copyright no modelo {nome_limpo}")
            
            # SE CHEGOU AQUI, SUCESSO!
            status_text.empty()
            return response.text

        except Exception as e:
            last_error = e
            # Se falhar, continua o loop para o próximo modelo
            print(f"Falha no modelo {model_name}: {e}")
            time.sleep(1) 

    # SE TODOS FALHAREM
    status_text.empty()
    st.error("❌ Todos os modelos falharam devido a restrições de Copyright.")
    
    # Retorna JSON de erro para não quebrar a UI
    return """
    {
        "METADADOS": { "score": 0, "datas": ["FALHA GERAL"] },
        "SECOES": [
            { "titulo": "ERRO DE LEITURA", "ref": "Bloqueio persistente em todos os modelos.", "bel": "Tente enviar menos páginas.", "status": "FALTANTE" }
        ]
    }
    """

# ----------------- UI -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=80)
    st.title("Validador de Bulas")
    
    if get_api_key():
        st.success("✅ API Configurada")
    else:
        st.error("❌ Sem Chave API")
    
    st.divider()
    pagina = st.radio("Navegação:", ["🏠 Início", "💊 Ref x BELFAR", "📋 Conferência MKT", "🎨 Gráfica x Arte"])
    st.divider()

if pagina == "🏠 Início":
    st.markdown("<h1 style='text-align: center; color: #55a68e;'>Validador Inteligente</h1>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    c1.info("**Ref x BELFAR**: Comparação de Bula Padrão vs Bula Belfar.")
    c2.info("**Conferência MKT**: Validação de materiais de marketing.")
    c3.info("**Gráfica x Arte**: Conferência final de pré-impressão.")

else:
    st.markdown(f"## {pagina}")
    
    lista_secoes = SECOES_PACIENTE
    nome_tipo = "Paciente"
    label_box1, label_box2 = "Arquivo 1", "Arquivo 2"
    
    if pagina == "💊 Ref x BELFAR":
        label_box1, label_box2 = "📄 Referência", "📄 BELFAR"
        col_tipo, _ = st.columns([1, 2])
        if col_tipo.radio("Tipo:", ["Paciente", "Profissional"], horizontal=True) == "Profissional":
            lista_secoes = SECOES_PROFISSIONAL; nome_tipo = "Profissional"

    elif pagina == "📋 Conferência MKT": label_box1, label_box2 = "📄 ANVISA", "📄 MKT"
    elif pagina == "🎨 Gráfica x Arte": label_box1, label_box2 = "📄 Arte Vigente", "📄 PDF Gráfica"
    
    st.divider()
    c1, c2 = st.columns(2)
    f1 = c1.file_uploader(label_box1, type=["pdf", "docx"], key="f1")
    f2 = c2.file_uploader(label_box2, type=["pdf", "docx"], key="f2")
        
    if st.button("🚀 INICIAR AUDITORIA") and f1 and f2:
        with st.spinner("🤖 Lendo arquivos e processando..."):
            d1 = process_uploaded_file(f1)
            d2 = process_uploaded_file(f2)
            
            if d1 and d2:
                payload = ["CONTEXTO: Auditoria Regulatória de Bula (RDC 47/2009). Dados públicos de saúde."]
                
                # Monta payload
                doc1_label = label_box1.replace("📄 ", "").upper()
                doc2_label = label_box2.replace("📄 ", "").upper()
                
                if d1['type'] == 'text': payload.append(f"--- {doc1_label} ---\n{d1['data']}")
                else: payload.append(f"--- {doc1_label} ---"); payload.extend(d1['data'])
                
                if d2['type'] == 'text': payload.append(f"--- {doc2_label} ---\n{d2['data']}")
                else: payload.append(f"--- {doc2_label} ---"); payload.extend(d2['data'])
                
                secoes_str = "\n".join([f"- {s}" for s in lista_secoes])
                
                # PROMPT CORRIGIDO (MARCAÇÃO DUPLA E CONTEXTO LEGAL)
                prompt = f"""
                Atue como Auditor Farmacêutico Especialista.
                OBJETIVO: Comparar textos regulatórios para conformidade sanitária.
                
                SEÇÕES A ANALISAR ({nome_tipo}):
                {secoes_str}
                
                === REGRA 1: MARCAÇÃO BILATERAL ===
                Aplique as tags <mark> EM AMBOS os textos (ref e bel) sempre que encontrar a ocorrência.
                - DIVERGÊNCIAS: Use <mark class='diff'>texto</mark> nos dois lados.
                - ERROS ORTOGRÁFICOS: Use <mark class='ort'>texto</mark> nos dois lados.
                
                === REGRA 2: DATA DA ANVISA ===
                Busque "Aprovado em dd/mm/aaaa" nos DIZERES LEGAIS.
                IMPORTANTE: Se a data existir no texto, aplique <mark class='anvisa'>dd/mm/aaaa</mark> NO TEXTO ONDE ELA APARECE (seja Ref, seja Bel, ou ambos).
                
                SAÍDA JSON:
                {{
                    "METADADOS": {{ "score": 0-100, "datas": ["lista de datas"] }},
                    "SECOES": [
                        {{ "titulo": "NOME", "ref": "texto html...", "bel": "texto html...", "status": "STATUS" }}
                    ]
                }}
                """
                
                # CHAMA A FUNÇÃO QUE TROCA DE MODELO SE DER ERRO
                json_res = gerar_json_blindado(prompt, payload)
                data = extract_json(json_res)
                
                if data:
                    meta = data.get("METADADOS", {})
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Conformidade", f"{meta.get('score', 0)}%")
                    m2.metric("Seções", len(data.get("SECOES", [])))
                    m3.metric("Datas", ", ".join(meta.get("datas", [])) or "--")
                    st.divider()
                    
                    for sec in data.get("SECOES", []):
                        icon = "✅"
                        if "DIVERGENTE" in sec['status']: icon = "❌"
                        elif "FALTANTE" in sec['status']: icon = "🚨"
                        elif any(x in sec['titulo'] for x in SECOES_SEM_DIVERGENCIA): icon = "👁️"
                        
                        with st.expander(f"{icon} {sec['titulo']} — {sec['status']}"):
                            cA, cB = st.columns(2)
                            cA.markdown(f"**{doc1_label}**"); cA.markdown(f"<div style='background:#f9f9f9; padding:10px; border-radius:5px;'>{sec.get('ref', '')}</div>", unsafe_allow_html=True)
                            cB.markdown(f"**{doc2_label}**"); cB.markdown(f"<div style='background:#f0fff4; padding:10px; border-radius:5px;'>{sec.get('bel', '')}</div>", unsafe_allow_html=True)
                else:
                    st.error("Erro ao processar JSON da IA.")
