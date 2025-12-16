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

# ----------------- ESTILOS CSS (UI MODERNA) -----------------
st.markdown("""
<style>
    /* Remove cabeçalho padrão do Streamlit */
    header[data-testid="stHeader"] { display: none !important; }
    .main .block-container { padding-top: 20px !important; }
    .main { background-color: #f8f9fa; }
    
    /* Fontes e Títulos */
    h1, h2, h3 { color: #2c3e50; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
    
    /* Estilo dos Cards de Resultado */
    .stCard {
        background-color: white; padding: 25px; border-radius: 12px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.05); margin-bottom: 20px;
        border: 1px solid #e9ecef; transition: transform 0.2s;
    }
    .stCard:hover { transform: translateY(-2px); border-color: #55a68e; }
    
    /* Botão Principal */
    .stButton>button { 
        width: 100%; background: linear-gradient(135deg, #55a68e 0%, #3e8e75 100%); 
        color: white; font-weight: bold; border-radius: 8px; height: 50px; 
        border: none; font-size: 16px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        transition: all 0.3s ease;
    }
    .stButton>button:hover { background: linear-gradient(135deg, #448c75 0%, #2d6b56 100%); box-shadow: 0 6px 8px rgba(0,0,0,0.15); }

    /* --- ESTILO DA SIDEBAR (MENU DE NAVEGAÇÃO) --- */
    section[data-testid="stSidebar"] {
        background-color: #ffffff;
        border-right: 1px solid #eaeaea;
    }
    
    /* Estiliza o Radio Button para parecer botões de menu */
    .stRadio > div[role="radiogroup"] > label {
        background-color: #f8f9fa;
        padding: 12px 15px;
        border-radius: 8px;
        margin-bottom: 8px;
        border: 1px solid transparent;
        transition: all 0.2s;
        cursor: pointer;
    }
    .stRadio > div[role="radiogroup"] > label:hover {
        background-color: #e9ecef;
        border-color: #ced4da;
        transform: translateX(3px);
    }
    /* Quando selecionado (truque visual) */
    .stRadio > div[role="radiogroup"] > label[data-checked="true"] {
        background-color: #e6fffa;
        border-color: #55a68e;
        color: #2c7a65;
        font-weight: bold;
    }

    /* Caixa de Status do Modelo */
    .model-status {
        background-color: #d1fae5;
        color: #065f46;
        padding: 10px;
        border-radius: 8px;
        font-size: 0.85rem;
        text-align: center;
        border: 1px solid #a7f3d0;
        margin-bottom: 20px;
        font-weight: 500;
    }
    .model-error {
        background-color: #fee2e2;
        color: #991b1b;
        padding: 10px;
        border-radius: 8px;
        font-size: 0.85rem;
        text-align: center;
        border: 1px solid #fecaca;
    }

    /* Marcadores de Texto */
    mark.diff { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; }
    mark.ort { background-color: #f8d7da; color: #721c24; padding: 2px 4px; border-radius: 4px; border-bottom: 2px solid #dc3545; }
    mark.anvisa { background-color: #cff4fc; color: #055160; padding: 2px 4px; border-radius: 4px; border: 1px solid #b6effb; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# ----------------- CONSTANTES (LISTAS OFICIAIS) -----------------
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

SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# ----------------- FUNÇÕES DE BACKEND -----------------

def get_gemini_model():
    """Configura o modelo principal."""
    api_key = None
    try:
        api_key = st.secrets["GEMINI_API_KEY"]
    except:
        api_key = os.environ.get("GEMINI_API_KEY")
    
    if not api_key: return None, "Sem Chave API"

    genai.configure(api_key=api_key)
    return genai.GenerativeModel("gemini-1.5-pro"), "gemini-1.5-pro"

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
            
            # MODO IMAGEM (ALTA RESOLUÇÃO)
            images = []
            limit_pages = min(8, len(doc)) 
            
            for i in range(limit_pages):
                page = doc[i]
                # Zoom 3.0 para ler colunas
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
        else:
            pass
            
    data_json["SECOES"] = clean_sections
    return data_json

# ----------------- UI LATERAL (MENU BONITO) -----------------
with st.sidebar:
    # Logo Centralizada e Título
    st.markdown("""
        <div style="text-align: center; padding-bottom: 10px;">
            <img src="https://cdn-icons-png.flaticon.com/512/3004/3004458.png" width="80" style="margin-bottom: 10px;">
            <h2 style="color: #2c3e50; margin: 0; font-size: 1.5rem;">Validador</h2>
            <p style="color: #7f8c8d; font-size: 0.8rem;">Auditoria Inteligente</p>
        </div>
    """, unsafe_allow_html=True)
    
    st.divider()

    # Status do Modelo (Estilo Pill/Card)
    model_instance, model_name = get_gemini_model()
    
    if model_instance:
        st.markdown(f"""
            <div class="model-status">
                <span style="font-size: 1.2em;">⚡</span> Conectado<br>
                <span style="font-size: 0.8em; opacity: 0.8;">{model_name}</span>
            </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
            <div class="model-error">
                ❌ Sem Chave API
            </div>
        """, unsafe_allow_html=True)
    
    # Menu de Navegação
    st.markdown("**Navegação**")
    pagina = st.radio(
        "Ir para:", 
        ["🏠 Início", "💊 Ref x BELFAR", "📋 Conferência MKT", "🎨 Gráfica x Arte"],
        label_visibility="collapsed" # Esconde o label padrão feio
    )
    
    st.divider()
    st.caption("v2.5 Stable • Temp 0.0")

# ----------------- PÁGINAS -----------------
if pagina == "🏠 Início":
    st.markdown("<div style='text-align:center; padding: 40px 0;'><h1 style='color:#55a68e; font-size: 3rem;'>Bem-vindo ao Validador</h1><p style='color:#666; font-size:1.2rem;'>Selecione um módulo no menu lateral para começar.</p></div>", unsafe_allow_html=True)
    
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("""<div class="stCard" style="text-align:center;"><h3>💊 Ref x BELFAR</h3><p>Comparação estrita de textos.</p></div>""", unsafe_allow_html=True)
    with c2:
        st.markdown("""<div class="stCard" style="text-align:center;"><h3>📋 Conf. MKT</h3><p>Validação de artes e layouts.</p></div>""", unsafe_allow_html=True)
    with c3:
        st.markdown("""<div class="stCard" style="text-align:center;"><h3>🎨 Gráfica</h3><p>Verificação de curvas e impressão.</p></div>""", unsafe_allow_html=True)

else:
    st.markdown(f"## {pagina}")
    
    lista_secoes = SECOES_PACIENTE
    label1, label2 = "Referência", "Candidato"
    
    if pagina == "💊 Ref x BELFAR":
        c_opt, _ = st.columns([1,2])
        if c_opt.radio("Tipo:", ["Paciente", "Profissional"], horizontal=True) == "Profissional":
            lista_secoes = SECOES_PROFISSIONAL
            
    elif pagina == "📋 Conferência MKT": label1, label2 = "ANVISA", "MKT"
    elif pagina == "🎨 Gráfica x Arte": label1, label2 = "Arte Vigente", "Gráfica (Curvas)"
    
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"**📂 {label1}**")
        f1 = st.file_uploader("", type=["pdf", "docx"], key="f1")
    with c2:
        st.markdown(f"**📂 {label2}**")
        f2 = st.file_uploader("", type=["pdf", "docx"], key="f2")
        
    st.markdown("<br>", unsafe_allow_html=True)

    if st.button("🚀 INICIAR AUDITORIA"):
        if f1 and f2 and model_instance:
            with st.spinner("🔍 Analisando documentos com precisão máxima..."):
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

                        secoes_str = "\n".join([f"- {s}" for s in lista_secoes])
                        
                        # ==========================================================
                        # PROMPT BLINDADO
                        # ==========================================================
                        prompt = f"""
                        Você é um Auditor de Qualidade. Sua tarefa é extrair e comparar o texto de bulas.
                        
                        SEÇÕES PERMITIDAS (Ignorar qualquer outra):
                        {secoes_str}
                        
                        ⚠️ INSTRUÇÕES CRÍTICAS DE LEITURA:
                        1. **COLUNAS:** O texto está em colunas. Se uma frase termina abruptamente no fim de uma coluna (ex: "ou", "para"), ela continua no topo da próxima. Não quebre o parágrafo.
                        
                        2. **ATENÇÃO / LACTOSE:** Blocos de aviso ("Atenção: Contém lactose", "Atenção: Contém açúcar") que aparecem soltos no meio ou fim da coluna PERTENCEM à seção de texto imediatamente acima deles. Junte-os.
                        
                        3. **SEM ALUCINAÇÃO / OCR LITERAL:** - NÃO INVENTE PALAVRAS. O texto extraído deve ser IDÊNTICO ao da imagem.
                           - NÃO CORRIJA O PORTUGUÊS.
                           - NÃO USE SINÔNIMOS (ex: não troque "médico" por "doutor").
                           - NÃO crie títulos novos (ex: "Composição Adulto"). Use apenas os da lista.
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
                        # SELEÇÃO DE MODELOS (BLOQUEIO DE EXPERIMENTAL)
                        # ==============================================================
                        response = None
                        sucesso = False
                        error_log = []
                        
                        try:
                            all_models = genai.list_models()
                            available_models = [m.name for m in all_models if 'generateContent' in m.supported_generation_methods]
                            
                            def sort_priority(name):
                                if "robotics" in name or "experimental" in name or "preview" in name: return 100 
                                if "gemini-1.5-pro" in name and "002" in name: return 0
                                if "gemini-1.5-pro" in name: return 1
                                if "gemini-3" in name: return 2
                                if "gemini-1.5-flash" in name and not "lite" in name and not "8b" in name: return 3
                                return 50
                            
                            available_models.sort(key=sort_priority)
                            seen = set()
                            available_models = [x for x in available_models if not (x in seen or seen.add(x))]
                            
                            if not available_models: available_models = ["models/gemini-1.5-flash"]
                        except:
                            available_models = ["models/gemini-1.5-flash"]

                        st.caption(f"Processando com modelo estável...")

                        for model_name in available_models:
                            if ("robotics" in model_name or "preview" in model_name) and len(available_models) > 1 and not sucesso:
                                if available_models.index(model_name) < len(available_models) - 1:
                                    continue
                                    
                            try:
                                model_run = genai.GenerativeModel(model_name)
                                # ------------------------------------------------------------------
                                # TEMPERATURE 0.0 + TOKENS 8192
                                # ------------------------------------------------------------------
                                response = model_run.generate_content(
                                    [prompt] + payload,
                                    generation_config={
                                        "response_mime_type": "application/json",
                                        "temperature": 0.0,
                                        "max_output_tokens": 8192 
                                    },
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
                                    data = normalize_sections(raw_data, lista_secoes)
                                    
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
                                            cA.markdown(f"**Referência**\n<div style='background:#f9f9f9;padding:10px;font-size:0.9em;border-radius:5px;'>{sec.get('ref','')}</div>", unsafe_allow_html=True)
                                            cB.markdown(f"**Candidato**\n<div style='background:#f0fff4;padding:10px;font-size:0.9em;border-radius:5px;'>{sec.get('bel','')}</div>", unsafe_allow_html=True)
                                else:
                                    st.error("Erro ao estruturar dados. O modelo retornou formato inválido.")
                                    with st.expander("Ver Resposta Bruta (Debug)"): st.code(response.text)
                        else:
                            st.error("❌ Todos os modelos falharam.")
                            with st.expander("Logs"): st.write(error_log)
                        
                except Exception as e:
                    st.error(f"Erro geral: {e}")
