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
    .stButton>button { width: 100%; background-color: #55a68e; color: white; font-weight: bold; border-radius: 10px; height: 55px; border: none; font-size: 16px; }
    
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
            
            # MODO IMAGEM (ULTRA RESOLUÇÃO PARA BULAS GRANDES)
            images = []
            limit_pages = min(8, len(doc)) 
            
            for i in range(limit_pages):
                page = doc[i]
                # Aumentei o zoom para 3.5 para o Lite ler melhor letras pequenas
                pix = page.get_pixmap(matrix=fitz.Matrix(3.5, 3.5))
                try:
                    img_byte_arr = io.BytesIO(pix.tobytes("jpeg", jpg_quality=95))
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
    """
    Normaliza e GARANTE que todas as seções apareçam, mesmo que vazias.
    """
    if not data_json or "SECOES" not in data_json:
        return {"METADADOS": {}, "SECOES": []}
    
    # Cria um mapa das seções que a IA encontrou
    found_map = {}
    
    # Mapa de referência (Upper Case -> Título Original)
    allowed_map_upper = {t.strip().upper(): t for t in allowed_titles}
    
    for sec in data_json["SECOES"]:
        titulo_ia = sec.get("titulo", "").strip().upper()
        
        # Tenta achar correspondência exata ou parcial
        matched_title = None
        
        if titulo_ia in allowed_map_upper:
            matched_title = allowed_map_upper[titulo_ia]
        else:
            # Fuzzy match simples
            for k, v in allowed_map_upper.items():
                if k in titulo_ia or titulo_ia in k:
                    matched_title = v
                    break
        
        if matched_title:
            found_map[matched_title] = sec
    
    # Reconstrói a lista final na ordem correta, preenchendo buracos
    final_sections = []
    for standard_title in allowed_titles:
        if standard_title in found_map:
            # Se achou, usa o da IA
            section_data = found_map[standard_title]
            section_data["titulo"] = standard_title # Corrige o nome para o padrão
            final_sections.append(section_data)
        else:
            # Se não achou, cria um placeholder de erro
            final_sections.append({
                "titulo": standard_title,
                "ref": "Texto não identificado nesta seção.",
                "bel": "Texto não identificado nesta seção.",
                "status": "🚨 FALTANTE (IA NÃO ENCONTROU)"
            })
            
    data_json["SECOES"] = final_sections
    return data_json

# ----------------- UI LATERAL -----------------
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
    
if st.button("🚀 INICIAR AUDITORIA (BUSCA COMPLETA)"):
    if f1 and f2 and api_key:
        with st.spinner("Analisando colunas, fluxo e layout..."):
            try:
                d1 = process_uploaded_file(f1)
                d2 = process_uploaded_file(f2)
                gc.collect()

                if d1 and d2:
                    payload = ["CONTEXTO: Auditoria Farmacêutica (Layout Complexo em Colunas)."]
                    
                    if d1['type'] == 'text': payload.append(f"--- DOC 1 (TEXTO) ---\n{d1['data']}")
                    else: payload.append("--- DOC 1 (IMAGENS) ---"); payload.extend(d1['data'])
                    
                    if d2['type'] == 'text': payload.append(f"--- DOC 2 (TEXTO) ---\n{d2['data']}")
                    else: payload.append("--- DOC 2 (IMAGENS) ---"); payload.extend(d2['data'])

                    # Checklist explicito no prompt
                    secoes_str = "\n".join([f"{i+1}. {s}" for i, s in enumerate(SECOES_PADRAO)])
                    
                    # PROMPT DE VARREDURA OBRIGATÓRIA
                    prompt = f"""
                    Você é um Auditor de Qualidade Sênior.
                    
                    SUA MISSÃO: Encontrar e extrair o texto de **TODAS AS 12 SEÇÕES OBRIGATÓRIAS** listadas abaixo.
                    
                    CHECKLIST DE SEÇÕES (Você DEVE encontrar todas):
                    {secoes_str}
                    
                    ⚠️ REGRAS DE BUSCA (NÃO PULE NADA):
                    1. **VARREDURA TOTAL:** O documento TEM 12 seções. Se você achou menos, continue lendo colunas laterais, rodapés e caixas de texto.
                    2. **NÃO PARE:** A seção "DIZERES LEGAIS" geralmente está no finalzinho, em letras miúdas. Encontre-a.
                    3. **OUTPUT OBRIGATÓRIO:** Gere um JSON com 12 itens no array "SECOES". Se uma seção estiver vazia no arquivo, retorne o texto "N/A" para ela, mas NÃO A OMITA do JSON.
                    
                    SAÍDA JSON ESTRITA: 
                    {{ 
                        "METADADOS": {{ "score": 0, "datas": [] }}, 
                        "SECOES": [ 
                            {{ 
                                "titulo": "TÍTULO EXATO DA LISTA", 
                                "ref": "Texto completo...", 
                                "bel": "Texto completo...", 
                                "status": "OK" 
                            }} 
                        ] 
                    }}
                    """

                    response = None
                    sucesso = False
                    error_log = []
                    
                    # TENTA PEGAR O MODELO FLASH LITE PRIMEIRO (COMO VOCÊ PEDIU)
                    try:
                        all_models = genai.list_models()
                        available_models = [m.name for m in all_models if 'generateContent' in m.supported_generation_methods]
                        
                        def sort_priority(name):
                            # Prioriza modelos FLASH e LITE pela velocidade
                            if "flash" in name and "lite" in name: return 0  # Prioridade Máxima
                            if "flash" in name: return 1
                            if "gemini-1.5-pro" in name: return 2
                            return 50
                        
                        available_models.sort(key=sort_priority)
                        # Remove duplicatas
                        seen = set()
                        available_models = [x for x in available_models if not (x in seen or seen.add(x))]
                        
                        if not available_models: available_models = ["models/gemini-1.5-flash"]
                    except:
                        available_models = ["models/gemini-1.5-flash"]

                    st.caption(f"🔄 Varrendo documento com IA...")

                    for model_name in available_models:
                        if "robotics" in model_name: continue
                                
                        try:
                            model_run = genai.GenerativeModel(model_name)
                            # Aumentei para 100k tokens para garantir que cabe tudo
                            response = model_run.generate_content(
                                [prompt] + payload,
                                generation_config={
                                    "response_mime_type": "application/json",
                                    "max_output_tokens": 100000 
                                },
                                safety_settings=SAFETY_SETTINGS
                            )
                            sucesso = True
                            st.toast(f"✅ Concluído via: {model_name}", icon="🤖")
                            break 
                        except Exception as e:
                            error_log.append(f"{model_name}: {str(e)}")
                            continue

                    # --- RENDERIZAÇÃO ---
                    if sucesso and response:
                        raw_data = extract_json(response.text)
                        if raw_data:
                            # AQUI A MÁGICA: Preenche as faltantes via código se a IA falhar
                            data = normalize_sections(raw_data, SECOES_PADRAO)
                            
                            meta = data.get("METADADOS", {})
                            cM1, cM2, cM3 = st.columns(3)
                            
                            qtd_secoes_ia = sum(1 for s in data.get("SECOES", []) if "FALTANTE" not in s.get("status", ""))
                            
                            # Lógica visual de erro se faltar seção
                            cor_secoes = "normal"
                            msg_secoes = f"{qtd_secoes_ia}/12"
                            if qtd_secoes_ia < 12: 
                                cor_secoes = "off"
                                msg_secoes += " (Incompleto)"
                            
                            cM1.metric("Score", f"{meta.get('score',0)}%")
                            cM2.metric("Seções Detectadas", msg_secoes, delta_color=cor_secoes)
                            cM3.metric("Datas", str(meta.get("datas", [])))
                            st.divider()
                            
                            if qtd_secoes_ia < 12:
                                st.warning(f"⚠️ A IA encontrou apenas {qtd_secoes_ia} seções reais. As {12 - qtd_secoes_ia} faltantes estão marcadas abaixo.")
                            
                            for sec in data.get("SECOES", []):
                                status = sec.get('status', 'N/A')
                                icon = "✅"
                                if "DIVERGENTE" in status: icon = "❌"
                                elif "FALTANTE" in status: icon = "🚨" # Ícone de alerta para as que a IA pulou
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
