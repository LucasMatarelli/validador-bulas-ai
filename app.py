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
    """
    Processa o arquivo. Se detectar 'CURVA' no nome ou falhar ao extrair texto,
    converte para imagens para o Gemini 'ver' o conteúdo.
    """
    if not uploaded_file: return None
    try:
        file_bytes = uploaded_file.read()
        filename = uploaded_file.name.lower()
        
        # --- DETECÇÃO DE ARQUIVO EM CURVAS ---
        # Palavras-chave que indicam arquivo de gráfica sem texto editável
        keywords_curva = ["curva", "traço", "outline", "convertido", "vetor"]
        is_curva = any(k in filename for k in keywords_curva)
        
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            return {"type": "text", "data": text, "is_image": False}
            
        elif filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            
            # 1. Tenta extrair texto (SOMENTE se não for detectado como curva)
            full_text = ""
            if not is_curva:
                for page in doc:
                    full_text += page.get_text() + "\n"
            
            # 2. Se achou texto suficiente e não é curva, retorna texto (mais barato/rápido)
            if len(full_text.strip()) > 100 and not is_curva:
                doc.close()
                return {"type": "text", "data": full_text, "is_image": False}
            
            # 3. FALLBACK PARA IMAGEM (Se for curva OU se o texto extraído for inútil)
            images = []
            # Limita a 6 páginas para economizar cota (Bulas geralmente cabem nisso)
            limit_pages = min(6, len(doc)) 
            
            for i in range(limit_pages):
                page = doc[i]
                # Aumentei um pouco a resolução (1.5) para ler letras pequenas em curvas
                pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
                try:
                    img_byte_arr = io.BytesIO(pix.tobytes("jpeg", jpg_quality=85))
                except:
                    img_byte_arr = io.BytesIO(pix.tobytes("png"))
                images.append(Image.open(img_byte_arr))
            
            doc.close()
            gc.collect()
            
            # Adiciona aviso visual se foi forçado por curva
            if is_curva:
                st.toast(f"📂 Arquivo '{filename}' detectado como CURVAS. Usando visão computacional.", icon="👁️")
                
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
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=80)
    st.title("Validador de Bulas")
    
    model_instance, model_name = get_gemini_model()
    
    if model_instance:
        st.success(f"✅ {model_name}")
    else:
        st.error("❌ Verifique a Chave API")
    
    st.divider()
    pagina = st.radio("Navegação:", ["🏠 Início", "💊 Ref x BELFAR", "📋 Conferência MKT", "🎨 Gráfica x Arte"])
    st.divider()

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
            with st.spinner("Analisando documentos..."):
                try:
                    # Processamento dos arquivos
                    d1 = process_uploaded_file(f1)
                    d2 = process_uploaded_file(f2)
                    gc.collect()

                    if d1 and d2:
                        risco_copyright = d1['is_image'] or d2['is_image']
                        
                        # Montagem do Payload Híbrido (Texto + Imagem)
                        payload = ["CONTEXTO: Comparação rigorosa de bulas de remédio."]
                        
                        # Adiciona DOC 1
                        if d1['type'] == 'text': 
                            payload.append(f"--- DOC 1 (TEXTO REFERÊNCIA) ---\n{d1['data']}")
                        else: 
                            payload.append("--- DOC 1 (IMAGEM/CURVAS) ---")
                            payload.extend(d1['data'])
                        
                        # Adiciona DOC 2
                        if d2['type'] == 'text': 
                            payload.append(f"--- DOC 2 (TEXTO CANDIDATO) ---\n{d2['data']}")
                        else: 
                            payload.append("--- DOC 2 (IMAGEM/CURVAS) ---")
                            payload.extend(d2['data'])

                        secoes_str = "\n".join([f"- {s}" for s in lista_secoes])
                        
                        prompt = f"""
                        Atue como Auditor de Controle de Qualidade Farmacêutica.
                        Compare DOC 1 e DOC 2.
                        Nota: Um ou ambos os arquivos podem ser imagens de arte final (curvas). Use OCR visual para ler o conteúdo.
                        
                        SEÇÕES PARA ANALISAR: {secoes_str}
                        
                        REGRAS:
                        1. Ignore diferenças de quebra de linha ou formatação visual. Foque no CONTEÚDO do texto.
                        2. Se um texto estiver em imagem (curva), transcreva-o mentalmente para comparar.
                        3. Marque diferenças críticas com <mark class='diff'>texto diferente</mark>.
                        4. Identifique erros ortográficos com <mark class='ort'>erro</mark>.
                        5. Encontre e destaque a data da bula no formato <mark class='anvisa'>dd/mm/aaaa</mark>.
                        
                        SAÍDA JSON OBRIGATÓRIA: 
                        {{ 
                            "METADADOS": {{ "score": 0 a 100, "datas": ["data1", "data2"] }}, 
                            "SECOES": [ 
                                {{ 
                                    "titulo": "Nome da Seção", 
                                    "ref": "Texto extraído da Referência (resumido se igual)", 
                                    "bel": "Texto extraído do Doc Avaliado", 
                                    "status": "OK" ou "DIVERGENTE" ou "FALTANTE" 
                                }} 
                            ] 
                        }}
                        """

                        # ==============================================================
                        # CASCATA DE SOBREVIVÊNCIA 3.0 (COM SUPORTE A VISÃO)
                        # ==============================================================
                        response = None
                        sucesso = False
                        error_log = []
                        
                        # Lista de Modelos para tentar (Ordem: Melhor -> Mais Rápido -> Legado)
                        # O Gemini 3 e os Flashs recentes suportam Visão (Imagens)
                        
                        # Tenta listar dinamicamente o que a conta suporta
                        try:
                            all_models = genai.list_models()
                            available_models = [m.name for m in all_models if 'generateContent' in m.supported_generation_methods]
                            
                            # Função de prioridade para ordenação
                            def sort_priority(name):
                                if "gemini-3" in name: return 0      # Tenta o 3.0 primeiro
                                if "flash" in name and "1.5" in name: return 1 # Depois Flash 1.5
                                if "pro" in name and "1.5" in name: return 2   # Depois Pro 1.5
                                return 10
                            
                            available_models.sort(key=sort_priority)
                            
                            if not available_models:
                                available_models = ["models/gemini-1.5-flash", "models/gemini-1.5-pro"]
                                
                        except:
                            available_models = ["models/gemini-1.5-flash"] # Fallback manual

                        st.caption(f"🛡️ Estratégia de IA: Tentando {len(available_models)} modelos disponíveis...")

                        for model_name in available_models:
                            try:
                                # Se for imagem, pulamos modelos antigos que não veem imagem (ex: gemini-pro-vision é ok, mas gemini-pro texto não)
                                # Mas hoje em dia a maioria dos listados suporta multimodalidade.
                                
                                model_run = genai.GenerativeModel(model_name)
                                response = model_run.generate_content(
                                    [prompt] + payload,
                                    generation_config={"response_mime_type": "application/json"},
                                    safety_settings=SAFETY_SETTINGS
                                )
                                sucesso = True
                                st.success(f"✅ Processado com sucesso via: {model_name}")
                                break # Sai do loop se funcionar
                                
                            except Exception as e:
                                error_msg = str(e)
                                error_log.append(f"{model_name}: {error_msg}")
                                if "429" in error_msg or "Quota" in error_msg:
                                    continue # Tenta próximo
                                elif "404" in error_msg:
                                    continue # Tenta próximo
                                else:
                                    # Se for outro erro, as vezes vale tentar o proximo modelo
                                    continue

                        # --- RESULTADO FINAL ---
                        if not sucesso:
                            st.error("❌ FALHA CRÍTICA: Não foi possível processar (Cotas ou Erro de Imagem).")
                            with st.expander("Ver Logs Técnicos"):
                                st.write(error_log)
                                st.info("Dica: Arquivos em curva são pesados para a IA. Tente reduzir o número de páginas se possível.")

                        # ==============================================================
                        # RENDERIZAÇÃO
                        # ==============================================================
                        if sucesso and response:
                            if hasattr(response.candidates[0], 'finish_reason') and response.candidates[0].finish_reason == 4:
                                st.error("⚠️ Bloqueio de Segurança (Copyright)")
                            else:
                                data = extract_json(response.text)
                                if data:
                                    meta = data.get("METADADOS", {})
                                    cM1, cM2, cM3 = st.columns(3)
                                    cM1.metric("Score", f"{meta.get('score',0)}%")
                                    cM2.metric("Seções", len(data.get("SECOES", [])))
                                    cM3.metric("Datas", str(meta.get("datas", [])))
                                    st.divider()
                                    
                                    for sec in data.get("SECOES", []):
                                        status = sec.get('status', 'N/A')
                                        icon = "✅"
                                        if "DIVERGENTE" in status: icon = "❌"
                                        elif "FALTANTE" in status: icon = "🚨"
                                        
                                        with st.expander(f"{icon} {sec['titulo']} - {status}"):
                                            cA, cB = st.columns(2)
                                            cA.markdown(f"**Referência**\n<div style='background:#f9f9f9;padding:10px;'>{sec.get('ref','')}</div>", unsafe_allow_html=True)
                                            cB.markdown(f"**Belfar**\n<div style='background:#f0fff4;padding:10px;'>{sec.get('bel','')}</div>", unsafe_allow_html=True)
                                else:
                                    st.error("Erro ao ler resposta da IA (JSON Inválido). Tente novamente.")
                        
                except Exception as e:
                    st.error(f"Erro geral: {e}")
