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
        border: 1px solid #e1e4e8; transition: transform 0.2s; height: 100%;
    }
    .stCard:hover { transform: translateY(-5px); border-color: #55a68e; }
    .card-title { color: #55a68e; font-size: 1.2rem; font-weight: bold; margin-bottom: 15px; border-bottom: 2px solid #f0f2f5; padding-bottom: 10px; }
    .stButton>button { width: 100%; background-color: #55a68e; color: white; font-weight: bold; border-radius: 10px; height: 55px; border: none; font-size: 16px; }
    .stButton>button:hover { background-color: #448c75; }
    
    mark.diff { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; }
    mark.ort { background-color: #f8d7da; color: #721c24; padding: 2px 4px; border-radius: 4px; border-bottom: 2px solid #dc3545; }
    mark.anvisa { background-color: #cff4fc; color: #055160; padding: 2px 4px; border-radius: 4px; border: 1px solid #b6effb; font-weight: bold; }
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

# ----------------- FUNÇÕES DE BACKEND -----------------

def get_api_key():
    api_key = None
    try:
        api_key = st.secrets["GEMINI_API_KEY"]
    except Exception:
        pass
    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY")
    return api_key

def process_uploaded_file(uploaded_file):
    if not uploaded_file: return None
    try:
        file_bytes = uploaded_file.read()
        filename = uploaded_file.name.lower()
        
        # 1. DOCX
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            return {"type": "text", "data": text}
            
        # 2. PDF (Texto Preferencialmente)
        elif filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            
            # Tenta extrair texto
            full_text = ""
            for page in doc:
                full_text += page.get_text() + "\n"
            
            if len(full_text.strip()) > 50:
                doc.close()
                return {"type": "text", "data": full_text}
            
            # Se for imagem (scan), extrai imagens
            images = []
            limit_pages = min(12, len(doc))
            for i in range(limit_pages):
                page = doc[i]
                pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
                try:
                    img_byte_arr = io.BytesIO(pix.tobytes("jpeg", jpg_quality=90))
                except:
                    img_byte_arr = io.BytesIO(pix.tobytes("png"))
                images.append(Image.open(img_byte_arr))
            
            doc.close()
            gc.collect()
            return {"type": "images", "data": images}
            
    except Exception as e:
        st.error(f"Erro ao processar arquivo: {e}")
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

# ----------------- BARRA LATERAL -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=80)
    st.title("Validador de Bulas")
    
    api_key = get_api_key()
    if api_key:
        genai.configure(api_key=api_key)
        st.success("✅ Sistema Conectado")
    else:
        st.error("❌ Erro de Chave API")
    
    st.divider()
    pagina = st.radio("Navegação:", ["🏠 Início", "💊 Ref x BELFAR", "📋 Conferência MKT", "🎨 Gráfica x Arte"])
    st.divider()

# ----------------- PÁGINA INICIAL -----------------
if pagina == "🏠 Início":
    st.markdown("""
    <div style="text-align: center; padding: 30px 20px;">
        <h1 style="color: #55a68e; font-size: 3rem;">Validador Inteligente</h1>
        <p style="color: #7f8c8d;">Central de auditoria e conformidade de bulas farmacêuticas.</p>
    </div>
    """, unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    c1.info("💊 Ref x BELFAR: Compara texto da bula padrão com a bula Belfar.")
    c2.info("📋 Conf. MKT: Valida artes de marketing contra regras da Anvisa.")
    c3.info("🎨 Gráfica: Verifica curvas e textos em PDFs de impressão.")

# ----------------- FERRAMENTA -----------------
else:
    st.markdown(f"## {pagina}")
    
    lista_secoes = SECOES_PACIENTE
    nome_tipo = "Paciente"
    label1 = "Arquivo Referência"
    label2 = "Arquivo Candidato"
    
    if pagina == "💊 Ref x BELFAR":
        label1, label2 = "📄 Documento de Referência", "📄 Documento BELFAR"
        c_opt, _ = st.columns([1, 2])
        if c_opt.radio("Tipo:", ["Paciente", "Profissional"], horizontal=True) == "Profissional":
            lista_secoes = SECOES_PROFISSIONAL
            nome_tipo = "Profissional"
    elif pagina == "📋 Conferência MKT": label1, label2 = "📄 Arquivo ANVISA", "📄 Arquivo MKT"
    elif pagina == "🎨 Gráfica x Arte": label1, label2 = "📄 Arte Vigente", "📄 PDF da Gráfica"
    
    st.divider()
    c1, c2 = st.columns(2)
    f1 = c1.file_uploader(label1, type=["pdf", "docx"], key="f1")
    f2 = c2.file_uploader(label2, type=["pdf", "docx"], key="f2")
    
    st.write("") 
    if st.button("🚀 INICIAR AUDITORIA COMPLETA"):
        if not f1 or not f2:
            st.warning("⚠️ Faça upload dos dois arquivos.")
        else:
            status_text = st.empty()
            status_text.info("🤖 Lendo arquivos...")
            
            d1 = process_uploaded_file(f1)
            d2 = process_uploaded_file(f2)
            gc.collect()

            if d1 and d2:
                payload = ["CONTEXTO: Auditoria Interna Confidencial Belfar."]
                
                if d1['type'] == 'text': payload.append(f"--- DOC 1 ---\n{d1['data']}")
                else: payload.append("--- DOC 1 ---"); payload.extend(d1['data'])
                
                if d2['type'] == 'text': payload.append(f"--- DOC 2 ---\n{d2['data']}")
                else: payload.append("--- DOC 2 ---"); payload.extend(d2['data'])

                secoes_str = "\n".join([f"- {s}" for s in lista_secoes])
                
                prompt = f"""
                Atue como Auditor Farmacêutico RÍGIDO.
                Analise DOC 1 (Referência) vs DOC 2 (Candidato/Belfar).
                
                SEÇÕES:
                {secoes_str}

                REGRAS:
                1. Extraia APENAS o texto do conteúdo, sem títulos.
                2. Indique divergências com <mark class='diff'> e erros ortográficos com <mark class='ort'>.
                3. Busque data de aprovação em DIZERES LEGAIS: <mark class='anvisa'>dd/mm/aaaa</mark>.

                SAÍDA JSON:
                {{ "METADADOS": {{ "score": 0-100, "datas": [] }}, "SECOES": [ {{ "titulo": "...", "ref": "...", "bel": "...", "status": "..." }} ] }}
                """

                # SISTEMA DE RETRY INTELIGENTE
                response = None
                model_used = ""
                
                # --- TENTATIVA 1: GEMINI 2.0 FLASH EXP (POWER) ---
                try:
                    status_text.info("⚡ Analisando com Gemini 2.0 Flash Exp (Modo Power)...")
                    model = genai.GenerativeModel('gemini-2.0-flash-exp') # Nome corrigido sem 'models/'
                    response = model.generate_content(
                        [prompt] + payload,
                        generation_config={"response_mime_type": "application/json"}
                    )
                    model_used = "Gemini 2.0 Flash Exp"
                except Exception as e:
                    if "429" in str(e):
                        status_text.warning("⚠️ Alto tráfego no modelo Power. Aguardando 12s...")
                        time.sleep(12)
                        try:
                            response = model.generate_content(
                                [prompt] + payload,
                                generation_config={"response_mime_type": "application/json"}
                            )
                            model_used = "Gemini 2.0 Flash Exp (Retry)"
                        except:
                            pass
                    else:
                        print(f"Erro 2.0: {e}")

                # --- TENTATIVA 2: GEMINI 1.5 FLASH (A GARANTIA) ---
                # Se o 2.0 falhou (por cota ou erro), usamos o 1.5 Flash que é blindado contra erros.
                if not response:
                    try:
                        status_text.info("🚀 Alternando para Gemini 1.5 Flash (Modo Rápido e Seguro)...")
                        model = genai.GenerativeModel('gemini-1.5-flash') # Nome corrigido sem 'models/'
                        response = model.generate_content(
                            [prompt] + payload,
                            generation_config={"response_mime_type": "application/json"}
                        )
                        model_used = "Gemini 1.5 Flash"
                    except Exception as e:
                        st.error(f"Erro fatal em todos os modelos: {e}")

                # PROCESSA O RESULTADO
                if response:
                    status_text.success(f"✅ Análise concluída com {model_used}!")
                    
                    if hasattr(response.candidates[0], 'finish_reason') and response.candidates[0].finish_reason == 4:
                        st.error("⚠️ Erro de Copyright detectado. Use arquivos DOCX ou PDF Texto.")
                    else:
                        data = extract_json(response.text)
                        if data:
                            meta = data.get("METADADOS", {})
                            m1, m2, m3 = st.columns(3)
                            m1.metric("Score", f"{meta.get('score', 0)}%")
                            m2.metric("Seções", len(data.get("SECOES", [])))
                            m3.metric("Datas", ", ".join(meta.get("datas", [])) or "--")
                            st.divider()
                            
                            for sec in data.get("SECOES", []):
                                status = sec.get('status', 'N/A')
                                icon = "✅"
                                if "DIVERGENTE" in status: icon = "❌"
                                elif "FALTANTE" in status: icon = "🚨"
                                
                                with st.expander(f"{icon} {sec['titulo']} — {status}"):
                                    ca, cb = st.columns(2)
                                    ca.markdown(f"**Referência**\n<div style='background:#f9f9f9;padding:10px;'>{sec.get('ref','')}</div>", unsafe_allow_html=True)
                                    cb.markdown(f"**Belfar**\n<div style='background:#f0fff4;padding:10px;'>{sec.get('bel','')}</div>", unsafe_allow_html=True)
                        else:
                            st.error("Erro ao ler resposta da IA. Tente novamente.")
