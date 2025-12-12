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
from PIL import Image

# ----------------- CONFIGURAÇÃO DA PÁGINA -----------------
st.set_page_config(
    page_title="Validador Farmacêutico Pro",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- ESTILOS CSS -----------------
st.markdown("""
<style>
    header[data-testid="stHeader"] { display: none !important; }
    .main .block-container { padding-top: 20px !important; }
    .main { background-color: #f8fafc; }
    h1, h2, h3 { color: #0f172a; font-family: 'Inter', sans-serif; }
    
    .stCard {
        background-color: white; padding: 25px; border-radius: 12px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); margin-bottom: 20px;
        border: 1px solid #e2e8f0;
    }
    .stButton>button { 
        width: 100%; background-color: #3b82f6; color: white; 
        font-weight: 600; border-radius: 8px; height: 50px; border: none; 
        transition: all 0.2s;
    }
    .stButton>button:hover { background-color: #2563eb; transform: translateY(-1px); }
    
    mark.diff { background-color: #fef9c3; color: #854d0e; padding: 2px 6px; border-radius: 4px; font-weight: bold; border: 1px solid #fde047; }
    mark.ort { background-color: #fee2e2; color: #991b1b; padding: 2px 6px; border-radius: 4px; border-bottom: 2px solid #ef4444; }
    mark.anvisa { background-color: #dbeafe; color: #1e40af; padding: 2px 6px; border-radius: 4px; font-weight: bold; }
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

# Configuração de Segurança: LIBERADO (Block None) para evitar falsos positivos
SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# ----------------- FUNÇÕES DE BACKEND -----------------

def get_gemini_model():
    """
    Configura EXCLUSIVAMENTE o modelo PRO.
    """
    api_key = None
    try:
        api_key = st.secrets["GEMINI_API_KEY"]
    except:
        api_key = os.environ.get("GEMINI_API_KEY")
    
    if not api_key:
        return None, "Erro: Sem Chave API"

    genai.configure(api_key=api_key)
    
    # ---------------------------------------------------------
    # DEFINIÇÃO DO MODELO - AQUI ESTÁ A LÓGICA RESTRITIVA
    # ---------------------------------------------------------
    # Usamos 'gemini-1.5-pro' pois é a tag oficial para o modelo Pro mais recente.
    # Se você tiver acesso beta ao 2.5 ou 3.0, mude a string abaixo.
    MODELO_ALVO = "gemini-1.5-pro" 
    
    try:
        model = genai.GenerativeModel(MODELO_ALVO)
        # Teste de conexão (Ping)
        model.generate_content("Ping", request_options={"timeout": 5})
        return model, f"Conectado: {MODELO_ALVO.upper()}"
    except Exception as e:
        return None, f"Erro ao conectar no {MODELO_ALVO}: {e}"

def process_uploaded_file(uploaded_file):
    if not uploaded_file: return None
    try:
        file_bytes = uploaded_file.read()
        filename = uploaded_file.name.lower()
        
        # DOCX (Prioritário - Texto Puro)
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            return {"type": "text", "data": text, "is_image": False}
            
        # PDF (Tenta texto, se falhar vai para imagem de alta resolução)
        elif filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            
            full_text = ""
            for page in doc:
                full_text += page.get_text() + "\n"
            
            # Se o PDF tem texto selecionável, usamos ele (mais rápido e preciso)
            if len(full_text.strip()) > 100:
                doc.close()
                return {"type": "text", "data": full_text, "is_image": False}
            
            # Se for SCAN, renderiza imagens
            images = []
            # Pro Models aguentam mais contexto, podemos processar mais páginas se necessário
            limit_pages = min(15, len(doc)) 
            for i in range(limit_pages):
                page = doc[i]
                pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0)) # Alta resolução para o Pro ler bem
                try:
                    img_byte_arr = io.BytesIO(pix.tobytes("jpeg", jpg_quality=90))
                except:
                    img_byte_arr = io.BytesIO(pix.tobytes("png"))
                images.append(Image.open(img_byte_arr))
            
            doc.close()
            gc.collect()
            return {"type": "images", "data": images, "is_image": True}
            
    except Exception as e:
        st.error(f"Erro no arquivo: {e}")
        return None
    return None

def clean_json_response(text):
    text = text.replace("```json", "").replace("```", "").strip()
    text = re.sub(r'//.*', '', text)
    if text.startswith("json"): text = text[4:]
    return text

def extract_json(text):
    try:
        clean = clean_json_response(text)
        start = clean.find('{')
        end = clean.rfind('}') + 1
        if start != -1 and end != -1: return json.loads(clean[start:end])
        return json.loads(clean)
    except: return None

# ----------------- UI LATERAL -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=70)
    st.markdown("### Validador Pro")
    
    model_instance, status_msg = get_gemini_model()
    
    if model_instance:
        st.success(f"💎 {status_msg}")
    else:
        st.error(f"❌ {status_msg}")
    
    st.divider()
    pagina = st.radio("Ferramentas:", ["🏠 Home", "💊 Comparador de Textos", "📋 Validação de Artes"])
    st.divider()

# ----------------- PÁGINAS -----------------
if pagina == "🏠 Home":
    st.title("Validador Farmacêutico IA")
    st.info("Sistema configurado para utilizar exclusivamente a arquitetura Gemini Pro.")
    
    c1, c2 = st.columns(2)
    c1.markdown("### 💊 Comparador\nVerificação cruzada de documentos (Word/PDF).")
    c2.markdown("### 📋 Artes\nConferência visual e textual de materiais finais.")

else:
    st.markdown(f"## {pagina}")
    
    lista_secoes = SECOES_PACIENTE
    label1, label2 = "Referência (Aprovado)", "Candidato (Em Análise)"
    
    if pagina == "💊 Comparador de Textos":
        if st.radio("Modelo de Bula:", ["Paciente", "Profissional"], horizontal=True) == "Profissional":
            lista_secoes = SECOES_PROFISSIONAL
            
    elif pagina == "📋 Validação de Artes": 
        label1, label2 = "Texto Matriz", "Arte Final (PDF/Imagem)"
    
    c1, c2 = st.columns(2)
    f1 = c1.file_uploader(label1, type=["pdf", "docx"], key="f1")
    f2 = c2.file_uploader(label2, type=["pdf", "docx"], key="f2")
        
    if st.button("🚀 EXECUTAR ANÁLISE PRO"):
        if not model_instance:
            st.error("Erro Crítico: API Key inválida ou Modelo Pro indisponível.")
        elif f1 and f2:
            with st.spinner("Analisando com modelo de alta precisão..."):
                try:
                    d1 = process_uploaded_file(f1)
                    d2 = process_uploaded_file(f2)
                    gc.collect()

                    if d1 and d2:
                        payload = ["CONTEXTO: Auditoria Regulatória Farmacêutica (ANVISA)."]
                        
                        if d1['type'] == 'text': payload.append(f"--- DOC REF ---\n{d1['data']}")
                        else: payload.append("--- DOC REF ---"); payload.extend(d1['data'])
                        
                        if d2['type'] == 'text': payload.append(f"--- DOC CANDIDATO ---\n{d2['data']}")
                        else: payload.append("--- DOC CANDIDATO ---"); payload.extend(d2['data'])

                        secoes_str = "\n".join([f"- {s}" for s in lista_secoes])
                        
                        # Prompt Otimizado para o Modelo Pro (Mais complexo e detalhista)
                        prompt = f"""
                        ATUE COMO: Auditor Sênior da Qualidade.
                        TAREFA: Comparar DOC REF vs DOC CANDIDATO.
                        
                        INSTRUÇÕES RIGOROSAS:
                        1. Identifique qualquer desvio de texto (supressão, adição, alteração).
                        2. Verifique a grafia correta de termos técnicos e posologias.
                        3. Ignore diferenças apenas de formatação (negrito/itálico), foque no conteúdo.
                        
                        SEÇÕES PARA AUDITAR:
                        {secoes_str}

                        SAÍDA JSON OBRIGATÓRIA:
                        Use tags HTML para destacar as falhas no texto 'bel':
                        <mark class='diff'>Diferença</mark>
                        <mark class='ort'>Erro Ortográfico</mark>
                        <mark class='anvisa'>Data</mark>

                        Schema:
                        {{
                            "METADADOS": {{ "score_fidelidade": 0-100, "datas_detectadas": [] }},
                            "SECOES": [
                                {{ 
                                    "titulo": "Nome da Seção", 
                                    "ref": "Trecho da Referência", 
                                    "bel": "Trecho do Candidato com as tags de erro aplicadas", 
                                    "status": "CONFORME" ou "DIVERGENTE" 
                                }}
                            ]
                        }}
                        """

                        try:
                            # Configurações para o modelo PRO (Temperatura baixa para precisão)
                            response = model_instance.generate_content(
                                [prompt] + payload,
                                generation_config={"response_mime_type": "application/json", "temperature": 0.0},
                                safety_settings=SAFETY_SETTINGS,
                                request_options={"timeout": 900} # Timeout maior pois o Pro demora mais
                            )
                            
                            if hasattr(response.candidates[0], 'finish_reason') and response.candidates[0].finish_reason == 4:
                                st.error("⚠️ Bloqueio de Copyright detectado.")
                                st.warning("O documento parece ser um material protegido publicado. Tente usar versão em Word.")
                            else:
                                data = extract_json(response.text)
                                if data:
                                    meta = data.get("METADADOS", {})
                                    col_m1, col_m2, col_m3 = st.columns(3)
                                    
                                    score = meta.get('score_fidelidade', 0)
                                    cor = "green" if score == 100 else ("orange" if score > 90 else "red")
                                    
                                    col_m1.markdown(f"### Score: <span style='color:{cor}'>{score}%</span>", unsafe_allow_html=True)
                                    col_m2.metric("Seções", len(data.get("SECOES", [])))
                                    col_m3.metric("Datas", str(meta.get("datas_detectadas", [])))
                                    st.divider()
                                    
                                    for sec in data.get("SECOES", []):
                                        status = sec.get('status', 'N/A')
                                        icon = "✅" if "CONFORME" in status.upper() else "❌"
                                        
                                        with st.expander(f"{icon} {sec['titulo']}"):
                                            cA, cB = st.columns(2)
                                            cA.caption("Referência")
                                            cA.info(sec.get('ref',''))
                                            cB.caption("Análise")
                                            cB.markdown(f"<div style='background:#fff; border:1px solid #ddd; padding:10px; border-radius:5px'>{sec.get('bel','')}</div>", unsafe_allow_html=True)
                                else:
                                    st.error("Falha ao interpretar a resposta da IA.")
                                    
                        except Exception as e:
                            st.error(f"Erro na execução da IA: {e}")
                            
                except Exception as e:
                    st.error(f"Erro no processamento: {e}")
