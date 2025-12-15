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
    
    /* CARTÕES PRINCIPAIS */
    .stCard {
        background-color: white; padding: 25px; border-radius: 15px;
        box-shadow: 0 10px 20px rgba(0,0,0,0.05); margin-bottom: 25px;
        border: 1px solid #e1e4e8; transition: transform 0.2s; height: 100%;
    }
    .stCard:hover { transform: translateY(-5px); border-color: #55a68e; }
    .card-title { color: #55a68e; font-size: 1.2rem; font-weight: bold; margin-bottom: 15px; border-bottom: 2px solid #f0f2f5; padding-bottom: 10px; }
    
    /* BOTÃO DE AÇÃO */
    .stButton>button { width: 100%; background-color: #55a68e; color: white; font-weight: bold; border-radius: 10px; height: 55px; border: none; font-size: 16px; }
    .stButton>button:hover { background-color: #448c75; }
    
    /* MARCADORES DE TEXTO (Isso será usado pela IA) */
    mark.diff { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; text-decoration: none; }
    mark.ort { background-color: #ffc9c9; color: #9c0000; padding: 2px 4px; border-radius: 4px; border-bottom: 2px solid #dc3545; font-weight: bold; }
    mark.anvisa { background-color: #cff4fc; color: #055160; padding: 2px 4px; border-radius: 4px; border: 1px solid #b6effb; font-weight: bold; }

    /* --- MENU LATERAL (SIDEBAR) --- */
    section[data-testid="stSidebar"] {
        background-color: #ffffff;
        border-right: 1px solid #eee;
    }
    section[data-testid="stSidebar"] .stRadio > div[role="radiogroup"] {
        gap: 10px;
    }
    section[data-testid="stSidebar"] .stRadio label {
        background-color: #f8f9fa !important;
        padding: 15px 20px !important;
        border-radius: 10px !important;
        border: 1px solid #e9ecef !important;
        cursor: pointer;
        margin: 0 !important;
        color: #495057 !important;
        transition: all 0.2s ease;
        display: flex;
        align-items: center;
    }
    section[data-testid="stSidebar"] .stRadio label:hover {
        background-color: #e8f5e9 !important;
        border-color: #55a68e !important;
        color: #55a68e !important;
    }
    section[data-testid="stSidebar"] .stRadio div[aria-checked="true"] label {
        background-color: #55a68e !important;
        color: white !important;
        border-color: #448c75 !important;
        box-shadow: 0 4px 6px rgba(85, 166, 142, 0.3);
    }
    section[data-testid="stSidebar"] .stRadio label p {
        color: inherit !important;
        font-weight: 600 !important;
        font-size: 16px !important;
    }
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
    return genai.GenerativeModel("gemini-3-pro-preview"), "Modelo Ativo: gemini-3-pro-preview"

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
    # Limpeza bruta de markdown
    text = text.replace("```json", "").replace("```", "").strip()
    text = re.sub(r'//.*', '', text) # Remove comentários
    if text.startswith("json"): text = text[4:]
    return text

def extract_json(text):
    """
    Parser robusto com recuperação de dados truncados.
    """
    cleaned = clean_json_response(text)
    
    try:
        return json.loads(cleaned, strict=False)
    except:
        pass

    # Salva-vidas para corte abrupto (tenta fechar o JSON na marra)
    try:
        if '"SECOES":' in cleaned:
            last_valid_comma = cleaned.rfind("},")
            if last_valid_comma != -1:
                fixed_json_str = cleaned[:last_valid_comma+1] + "]}"
                return json.loads(fixed_json_str, strict=False)
    except:
        pass

    try:
        start = cleaned.find('{')
        end = cleaned.rfind('}') + 1
        if start != -1 and end != -1:
            json_str = cleaned[start:end]
            return json.loads(json_str, strict=False)
    except:
        pass
        
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

# ----------------- UI LATERAL -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=80)
    st.markdown("<h2 style='text-align: center; color: #55a68e; margin-bottom: 20px;'>Validador de Bulas</h2>", unsafe_allow_html=True)
    
    pagina = st.radio(
        "Navegação:", 
        ["🏠 Início", "💊 Ref x BELFAR", "📋 Conferência MKT", "🎨 Gráfica x Arte"],
        label_visibility="collapsed"
    )
    
    st.divider()
    
    model_instance, model_name = get_gemini_model()
    
    if model_instance:
        st.markdown(f"<div style='text-align:center; padding: 10px; background-color: #e8f5e9; border-radius: 8px; font-size: 0.8em; color: #2e7d32;'>✅ {model_name}</div>", unsafe_allow_html=True)
    else:
        st.error("❌ Verifique a Chave API")

# ----------------- PÁGINAS -----------------
if pagina == "🏠 Início":
    st.markdown("<h1 style='color:#55a68e;text-align:center;'>Validador Inteligente</h1>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    c1.info("💊 Ref x BELFAR: Comparação de textos.")
    c2.info("📋 Conf. MKT: Validação de artes.")
    c3.info("🎨 Gráfica: Verificação de PDF.")

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
    f1 = c1.file_uploader(label1, type=["pdf", "docx"], key="f1")
    f2 = c2.file_uploader(label2, type=["pdf", "docx"], key="f2")
        
    if st.button("🚀 INICIAR AUDITORIA"):
        if f1 and f2 and model_instance:
            with st.spinner("Analisando colunas, fluxo e layout..."):
                try:
                    d1 = process_uploaded_file(f1)
                    d2 = process_uploaded_file(f2)
                    gc.collect()

                    if d1 and d2:
                        risco_copyright = d1['is_image'] or d2['is_image']
                        
                        payload = ["CONTEXTO: Auditoria Farmacêutica (Layout Complexo em Colunas)."]
                        
                        if d1['type'] == 'text': payload.append(f"--- DOC 1 (REFERÊNCIA) ---\n{d1['data']}")
                        else: payload.append("--- DOC 1 (REFERÊNCIA/IMAGEM) ---"); payload.extend(d1['data'])
                        
                        if d2['type'] == 'text': payload.append(f"--- DOC 2 (CANDIDATO/BELFAR) ---\n{d2['data']}")
                        else: payload.append("--- DOC 2 (CANDIDATO/IMAGEM) ---"); payload.extend(d2['data'])

                        secoes_str = "\n".join([f"- {s}" for s in lista_secoes])
                        
                        # ==========================================================
                        # PROMPT BLINDADO E COM DESTAQUES (AMARELO/VERMELHO)
                        # ==========================================================
                        prompt = f"""
                        Você é um Auditor de Qualidade Farmacêutica Sênior. Sua tarefa é extrair e comparar minuciosamente as bulas.
                        
                        OBJETIVOS:
                        1. Extrair TODO o conteúdo de TODAS as seções listadas abaixo. NÃO PARE NO MEIO.
                        2. Comparar o texto do Doc 1 (Ref) com o Doc 2 (Candidato).
                        3. Extrair a Data de Aprovação da Anvisa (geralmente no rodapé).
                        
                        SEÇÕES OBRIGATÓRIAS (Extrair todas):
                        {secoes_str}
                        
                        REGRAS DE COMPARAÇÃO E DESTAQUE:
                        - Ignore apenas diferenças de espaçamento (quebras de linha, espaços duplos).
                        - Se houver qualquer palavra diferente, palavra a mais ou palavra faltando no Candidato:
                          > STATUS: "DIVERGENTE"
                          > AÇÃO: No texto do 'bel' (Candidato), envolva a parte divergente ou extra com a tag HTML: <mark class='diff'>TEXTO DIVERGENTE AQUI</mark>.
                        - Se houver erro de português (ortografia) no Candidato:
                          > STATUS: "DIVERGENTE"
                          > AÇÃO: Envolva o erro com a tag: <mark class='ort'>ERRO AQUI</mark>.
                        
                        DATA DA ANVISA:
                        - Procure por "Aprovado em", "Data da aprovação", ou datas no rodapé (Ex: 31/07/2025). Coloque no campo 'datas'.

                        SAÍDA JSON OBRIGATÓRIA (Use aspas duplas escapadas dentro do texto): 
                        {{ 
                            "METADADOS": {{ "score": 100, "datas": ["dd/mm/aaaa"] }}, 
                            "SECOES": [ 
                                {{ 
                                    "titulo": "TÍTULO DA SEÇÃO", 
                                    "ref": "Texto original completo...", 
                                    "bel": "Texto candidato com <mark class='diff'>divergências em amarelo</mark> e <mark class='ort'>erros em vermelho</mark>...", 
                                    "status": "OK" ou "DIVERGENTE" 
                                }} 
                            ] 
                        }}
                        
                        IMPORTANTE:
                        - Processe o documento ATÉ O FINAL (Dizeres Legais).
                        - Não abrevie textos longos.
                        """

                        # ==============================================================
                        # SELEÇÃO DE MODELOS (SEM LITE PARA NÃO CORTAR)
                        # ==============================================================
                        response = None
                        sucesso = False
                        error_log = []
                        
                        try:
                            all_models = genai.list_models()
                            available_models = [m.name for m in all_models if 'generateContent' in m.supported_generation_methods]
                            
                            def sort_priority(name):
                                # BANIMENTO DE LITE E EXPERIMENTAL (Causadores de corte e alucinação)
                                if "lite" in name: return 999 
                                if "robotics" in name or "experimental" in name or "preview" in name: return 100 

                                # Prioriza modelos Robustos (Pro > Flash padrão)
                                if "gemini-1.5-pro" in name and "002" in name: return 0
                                if "gemini-1.5-pro" in name: return 1
                                if "gemini-3" in name: return 2
                                if "gemini-1.5-flash" in name and not "8b" in name: return 3
                                return 50
                            
                            available_models.sort(key=sort_priority)
                            # Remove duplicatas e purga os Lites da lista se possível
                            seen = set()
                            available_models = [x for x in available_models if not (x in seen or seen.add(x))]
                            # Filtro final para remover Lite se tiver outras opções
                            filtered = [x for x in available_models if "lite" not in x]
                            if filtered: available_models = filtered
                            
                            if not available_models: available_models = ["models/gemini-1.5-flash"]
                        except:
                            available_models = ["models/gemini-1.5-flash"]

                        st.caption(f"Processando auditoria completa (pode levar alguns segundos)...")

                        for model_name in available_models:
                            if ("lite" in model_name or "experimental" in model_name) and len(available_models) > 1 and not sucesso:
                                continue
                                    
                            try:
                                model_run = genai.GenerativeModel(model_name)
                                # Token máximo 8192 para garantir que leia até os DIZERES LEGAIS
                                response = model_run.generate_content(
                                    [prompt] + payload,
                                    generation_config={
                                        "response_mime_type": "application/json",
                                        "max_output_tokens": 8192 
                                    },
                                    safety_settings=SAFETY_SETTINGS
                                )
                                sucesso = True
                                st.success(f"✅ Análise concluída via: {model_name}")
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
                                    # Data da Anvisa
                                    datas_anvisa = meta.get("datas", [])
                                    display_date = datas_anvisa[0] if datas_anvisa else "Não encontrada"
                                    cM3.metric("Data Anvisa", str(display_date))
                                    st.divider()
                                    
                                    if len(data.get("SECOES", [])) == 0:
                                        st.warning("Nenhuma seção válida identificada. O PDF pode estar como imagem de baixa qualidade.")
                                    
                                    for sec in data.get("SECOES", []):
                                        status = sec.get('status', 'N/A')
                                        icon = "✅"
                                        if "DIVERGENTE" in status: icon = "❌"
                                        elif "FALTANTE" in status: icon = "🚨"
                                        
                                        with st.expander(f"{icon} {sec['titulo']} - {status}"):
                                            cA, cB = st.columns(2)
                                            # Aqui o unsafe_allow_html vai renderizar os <mark> amarelos e vermelhos que a IA gerou
                                            cA.markdown(f"**Referência**\n<div style='background:#f9f9f9;padding:10px;font-size:0.9em;white-space: pre-wrap;'>{sec.get('ref','')}</div>", unsafe_allow_html=True)
                                            cB.markdown(f"**Candidato (Auditoria)**\n<div style='background:#f0fff4;padding:10px;font-size:0.9em;white-space: pre-wrap;'>{sec.get('bel','')}</div>", unsafe_allow_html=True)
                                else:
                                    st.error("Erro ao estruturar dados. Tente novamente.")
                                    with st.expander("Ver Resposta Bruta"): st.code(response.text)
                        else:
                            st.error("❌ Todos os modelos falharam.")
                        
                except Exception as e:
                    st.error(f"Erro geral: {e}")
