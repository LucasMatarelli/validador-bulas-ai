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
    page_title="Gráfica x Arte",
    page_icon="🎨",
    layout="wide"
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
    .stButton>button { width: 100%; background-color: #55a68e; color: white; font-weight: bold; border-radius: 10px; height: 55px; border: none; font-size: 16px; }
    .stButton>button:hover { background-color: #448c75; }
    
    mark.diff { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; }
    mark.ort { background-color: #f8d7da; color: #721c24; padding: 2px 4px; border-radius: 4px; border-bottom: 2px solid #dc3545; }
    mark.anvisa { background-color: #cff4fc; color: #055160; padding: 2px 4px; border-radius: 4px; border: 1px solid #b6effb; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# ----------------- CONFIGURAÇÃO API -----------------
def get_api_key():
    try:
        return st.secrets["GEMINI_API_KEY"]
    except:
        return os.environ.get("GEMINI_API_KEY")

api_key = get_api_key()
if api_key:
    genai.configure(api_key=api_key)

# ----------------- CONSTANTES -----------------
# Lista padrão para validação visual/textual de bulas
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

SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# ----------------- FUNÇÕES DE BACKEND -----------------

def process_uploaded_file(uploaded_file):
    if not uploaded_file: return None
    try:
        file_bytes = uploaded_file.read()
        filename = uploaded_file.name.lower()
        
        keywords_curva = ["curva", "traço", "outline", "convertido", "vetor"]
        is_curva = any(k in filename for k in keywords_curva)
        
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            return {"type": "text", "data": text, "is_image": False}
            
        elif filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            
            full_text = ""
            if not is_curva:
                for page in doc:
                    full_text += page.get_text() + "\n"
            
            if len(full_text.strip()) > 100 and not is_curva:
                doc.close()
                return {"type": "text", "data": full_text, "is_image": False}
            
            # MODO IMAGEM (ALTA RESOLUÇÃO) - Essencial para "Gráfica x Arte"
            images = []
            limit_pages = min(8, len(doc)) 
            
            for i in range(limit_pages):
                page = doc[i]
                # Zoom 3.0 para ler colunas pequenas em artes gráficas
                pix = page.get_pixmap(matrix=fitz.Matrix(3.0, 3.0))
                try:
                    img_byte_arr = io.BytesIO(pix.tobytes("jpeg", jpg_quality=90))
                except:
                    img_byte_arr = io.BytesIO(pix.tobytes("png"))
                images.append(Image.open(img_byte_arr))
            
            doc.close()
            gc.collect()
            
            if is_curva:
                st.toast(f"👁️ '{filename}': Modo Visual (Curvas) Ativado.", icon="📂")
                
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
    cleaned = clean_json_response(text)
    try:
        return json.loads(cleaned)
    except:
        try:
            start = cleaned.find('{')
            end = cleaned.rfind('}') + 1
            if start != -1 and end != -1:
                json_str = cleaned[start:end]
                json_str = re.sub(r'(?<=: ")(.*?)(?=")', lambda m: m.group(1).replace('\n', ' '), json_str, flags=re.DOTALL)
                return json.loads(json_str)
        except:
            return None
    return None

def normalize_sections(data_json, allowed_titles):
    if not data_json or "SECOES" not in data_json:
        return data_json
    
    clean_sections = []
    allowed_set = {t.strip().upper() for t in allowed_titles}
    
    for sec in data_json["SECOES"]:
        titulo_ia = sec.get("titulo", "").strip().upper()
        if titulo_ia in allowed_set:
            clean_sections.append(sec)
            
    data_json["SECOES"] = clean_sections
    return data_json

# ----------------- UI LATERAL (SIMPLIFICADA PARA PAG 3) -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=80)
    st.title("Validador de Bulas")
    st.info("Módulo: 🎨 Gráfica x Arte")
    
    if api_key:
        st.success("✅ API Conectada")
    else:
        st.error("❌ Sem Chave API")
    st.divider()

# ----------------- CORPO DA PÁGINA -----------------
st.markdown("## 🎨 Gráfica x Arte")
st.caption("Comparação Visual e Textual de Arquivos em Curvas/Imagem")

label1, label2 = "Arte Vigente (Ref)", "Gráfica/Curvas (Cand)"

c1, c2 = st.columns(2)
f1 = c1.file_uploader(label1, type=["pdf", "docx"], key="f1")
f2 = c2.file_uploader(label2, type=["pdf", "docx"], key="f2")
    
if st.button("🚀 INICIAR AUDITORIA"):
    if f1 and f2 and api_key:
        with st.spinner("Analisando colunas, fluxo e layout..."):
            try:
                d1 = process_uploaded_file(f1)
                d2 = process_uploaded_file(f2)
                gc.collect()

                if d1 and d2:
                    risco_copyright = d1['is_image'] or d2['is_image']
                    
                    payload = ["CONTEXTO: Auditoria Farmacêutica (Layout Complexo em Colunas)."]
                    
                    if d1['type'] == 'text': payload.append(f"--- DOC 1 (TEXTO) ---\n{d1['data']}")
                    else: payload.append("--- DOC 1 (IMAGENS) ---"); payload.extend(d1['data'])
                    
                    if d2['type'] == 'text': payload.append(f"--- DOC 2 (TEXTO) ---\n{d2['data']}")
                    else: payload.append("--- DOC 2 (IMAGENS) ---"); payload.extend(d2['data'])

                    secoes_str = "\n".join([f"- {s}" for s in SECOES_PADRAO])
                    
                    # PROMPT DO SEU CÓDIGO ORIGINAL
                    prompt = f"""
                    Você é um Auditor de Qualidade. Sua tarefa é extrair e comparar o texto de bulas.
                    
                    SEÇÕES PERMITIDAS (Ignorar qualquer outra):
                    {secoes_str}
                    
                    ⚠️ INSTRUÇÕES CRÍTICAS DE LEITURA:
                    1. **COLUNAS:** O texto está em colunas. Se uma frase termina abruptamente no fim de uma coluna (ex: "ou", "para"), ela continua no topo da próxima. Não quebre o parágrafo.
                    
                    2. **ATENÇÃO / LACTOSE:** Blocos de aviso ("Atenção: Contém lactose", "Atenção: Contém açúcar") que aparecem soltos no meio ou fim da coluna PERTENCEM à seção de texto imediatamente acima deles. Junte-os.
                    
                    3. **SEM ALUCINAÇÃO:** - NÃO crie títulos novos. Use apenas os da lista.
                        - NÃO repita o título dentro do conteúdo.

                    SAÍDA JSON (Estrita): 
                    {{ 
                        "METADADOS": {{ "score": 0, "datas": [] }}, 
                        "SECOES": [ 
                            {{ 
                                "titulo": "EXATAMENTE UM TÍTULO DA LISTA", 
                                "ref": "Texto completo...", 
                                "bel": "Texto completo...", 
                                "status": "OK" 
                            }} 
                        ] 
                    }}
                    """

                    # ==============================================================
                    # SELEÇÃO DE MODELOS (DO SEU CÓDIGO: TENTA TODOS ATÉ CONSEGUIR)
                    # ==============================================================
                    response = None
                    sucesso = False
                    error_log = []
                    
                    try:
                        all_models = genai.list_models()
                        available_models = [m.name for m in all_models if 'generateContent' in m.supported_generation_methods]
                        
                        def sort_priority(name):
                            # Lógica para priorizar modelos estáveis vs experimentais
                            if "robotics" in name or "experimental" in name or "preview" in name: 
                                return 100 
                            if "gemini-1.5-pro" in name and "002" in name: return 0
                            if "gemini-1.5-pro" in name: return 1
                            if "gemini-3" in name: return 2
                            if "gemini-1.5-flash" in name: return 3
                            return 50
                        
                        available_models.sort(key=sort_priority)
                        # Remove duplicatas mantendo ordem
                        seen = set()
                        available_models = [x for x in available_models if not (x in seen or seen.add(x))]
                        
                        if not available_models: available_models = ["models/gemini-1.5-flash"]
                    except:
                        available_models = ["models/gemini-1.5-flash"]

                    st.caption(f"🔄 Tentando modelos de IA disponíveis...")

                    for model_name in available_models:
                        # Pula modelos instáveis se houver outras opções
                        if ("robotics" in model_name or "preview" in model_name) and len(available_models) > 1 and not sucesso:
                            if available_models.index(model_name) < len(available_models) - 1:
                                continue
                                
                        try:
                            model_run = genai.GenerativeModel(model_name)
                            response = model_run.generate_content(
                                [prompt] + payload,
                                generation_config={"response_mime_type": "application/json"},
                                safety_settings=SAFETY_SETTINGS
                            )
                            sucesso = True
                            st.success(f"✅ Concluído via: {model_name}")
                            break 
                        except Exception as e:
                            error_log.append(f"{model_name}: {str(e)}")
                            continue

                    # --- RENDERIZAÇÃO ---
                    if sucesso and response:
                        if hasattr(response.candidates[0], 'finish_reason') and response.candidates[0].finish_reason == 4:
                            st.error("⚠️ Bloqueio de Segurança")
                        else:
                            raw_data = extract_json(response.text)
                            if raw_data:
                                data = normalize_sections(raw_data, SECOES_PADRAO)
                                
                                meta = data.get("METADADOS", {})
                                cM1, cM2, cM3 = st.columns(3)
                                cM1.metric("Score", f"{meta.get('score',0)}%")
                                cM2.metric("Seções", len(data.get("SECOES", [])))
                                cM3.metric("Datas", str(meta.get("datas", [])))
                                st.divider()
                                
                                if len(data.get("SECOES", [])) == 0:
                                    st.warning("Nenhuma seção válida identificada. Tente melhorar a qualidade do PDF.")
                                
                                for sec in data.get("SECOES", []):
                                    status = sec.get('status', 'N/A')
                                    icon = "✅"
                                    if "DIVERGENTE" in status: icon = "❌"
                                    elif "FALTANTE" in status: icon = "🚨"
                                    elif "DIVERGRIFO" in status: icon = "❓"
                                    
                                    with st.expander(f"{icon} {sec['titulo']} - {status}"):
                                        cA, cB = st.columns(2)
                                        cA.markdown(f"**Referência**\n<div style='background:#f9f9f9;padding:10px;font-size:0.9em'>{sec.get('ref','')}</div>", unsafe_allow_html=True)
                                        cB.markdown(f"**Candidato**\n<div style='background:#f0fff4;padding:10px;font-size:0.9em'>{sec.get('bel','')}</div>", unsafe_allow_html=True)
                            else:
                                st.error("Erro ao estruturar dados. O modelo retornou formato inválido.")
                                with st.expander("Ver Resposta Bruta (Debug)"): st.code(response.text)
                    else:
                        st.error("❌ Todos os modelos falharam.")
                        with st.expander("Logs de Erro"): st.write(error_log)
                    
            except Exception as e:
                st.error(f"Erro geral: {e}")
