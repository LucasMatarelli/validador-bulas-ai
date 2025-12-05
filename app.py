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

# ----------------- FUNÇÕES DE BACKEND -----------------

def get_gemini_model(api_key_input):
    """
    Tenta configurar a API com a chave fornecida e encontrar um modelo ativo.
    """
    # 1. Tenta pegar a chave do input manual ou do secrets/env
    api_key = api_key_input
    if not api_key:
        try:
            api_key = st.secrets["GEMINI_API_KEY"]
        except:
            api_key = os.environ.get("GEMINI_API_KEY")
    
    if not api_key:
        return None, "⚠️ Chave API não encontrada. Insira na barra lateral."

    # 2. Configura a biblioteca
    genai.configure(api_key=api_key)
    
    # 3. Lista de modelos para testar (Fallback em cascata)
    candidatos = [
        "gemini-1.5-flash",
        "gemini-1.5-flash-latest",
        "gemini-1.5-pro",
        "gemini-1.5-pro-latest",
        "gemini-pro"
    ]

    erro_detalhado = ""

    # 4. Loop de Teste: Tenta conectar em cada um até funcionar
    for nome_modelo in candidatos:
        try:
            model = genai.GenerativeModel(nome_modelo)
            # Teste rápido de ping (gera 1 token) para ver se a chave e o modelo batem
            model.generate_content("Oi", generation_config={"max_output_tokens": 1})
            return model, f"Conectado: {nome_modelo}"
        except Exception as e:
            # Guarda o erro para mostrar ao usuário se tudo falhar
            erro_detalhado = str(e)
            continue
            
    # Se chegou aqui, nenhum modelo funcionou
    if "403" in erro_detalhado or "API_KEY_INVALID" in erro_detalhado:
        return None, "🚫 Erro de Permissão: Sua API Key parece inválida ou expirada."
    elif "429" in erro_detalhado:
        return None, "⏳ Quota Excedida: Sua conta atingiu o limite gratuito do Google."
    else:
        return None, f"❌ Erro Técnico: {erro_detalhado}"

def process_uploaded_file(uploaded_file):
    if not uploaded_file: return None
    try:
        file_bytes = uploaded_file.read()
        filename = uploaded_file.name.lower()
        
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            return {"type": "text", "data": text, "is_image": False}
            
        elif filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            full_text = ""
            for page in doc:
                full_text += page.get_text() + "\n"
            
            if len(full_text.strip()) > 50:
                doc.close()
                return {"type": "text", "data": full_text, "is_image": False}
            
            images = []
            limit_pages = min(12, len(doc))
            for i in range(limit_pages):
                page = doc[i]
                pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
                try:
                    img_byte_arr = io.BytesIO(pix.tobytes("jpeg", jpg_quality=85))
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
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=80)
    st.title("Validador de Bulas")
    
    st.markdown("### Configuração")
    # CAMPO MANUAL PARA INSERIR A API KEY CASO NÃO CARREGUE DO ARQUIVO
    manual_key = st.text_input("Cole sua API Key aqui (Opcional):", type="password")
    
    # Tenta conectar e mostra o status real
    model_instance, status_msg = get_gemini_model(manual_key)
    
    if model_instance:
        st.success(f"✅ {status_msg}")
    else:
        st.error(status_msg)
        if "Chave API não encontrada" in status_msg:
            st.info("👉 Cole sua chave no campo acima para corrigir.")
    
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
    elif pagina == "🎨 Gráfica x Arte": label1, label2 = "Arte Vigente", "Gráfica"
    
    c1, c2 = st.columns(2)
    f1 = c1.file_uploader(label1, type=["pdf", "docx"], key="f1")
    f2 = c2.file_uploader(label2, type=["pdf", "docx"], key="f2")
        
    if st.button("🚀 INICIAR AUDITORIA"):
        if not model_instance:
            st.error("⚠️ PARE: A API não está conectada. Verifique a mensagem de erro na barra lateral esquerda.")
        elif f1 and f2:
            with st.spinner("Lendo documentos e analisando com IA..."):
                try:
                    d1 = process_uploaded_file(f1)
                    d2 = process_uploaded_file(f2)
                    gc.collect()

                    if d1 and d2:
                        risco_copyright = d1['is_image'] or d2['is_image']
                        
                        payload = ["CONTEXTO: Comparação de textos técnicos."]
                        
                        if d1['type'] == 'text': payload.append(f"--- DOC 1 ---\n{d1['data']}")
                        else: payload.append("--- DOC 1 ---"); payload.extend(d1['data'])
                        
                        if d2['type'] == 'text': payload.append(f"--- DOC 2 ---\n{d2['data']}")
                        else: payload.append("--- DOC 2 ---"); payload.extend(d2['data'])

                        secoes_str = "\n".join([f"- {s}" for s in lista_secoes])
                        
                        prompt = f"""
                        Atue como Auditor Farmacêutico. Compare DOC 1 e DOC 2.
                        SEÇÕES PARA ANALISAR: {secoes_str}
                        
                        REGRAS:
                        1. Ignore formatação, foca apenas no CONTEÚDO do texto.
                        2. Marque diferenças críticas com <mark class='diff'> texto </mark>.
                        3. Marque erros ortográficos com <mark class='ort'> texto </mark>.
                        4. Data de publicação deve estar marcada como <mark class='anvisa'>dd/mm/aaaa</mark>.
                        
                        SAÍDA OBRIGATÓRIA EM JSON: 
                        {{ 
                            "METADADOS": {{ "score": 100, "datas": [] }}, 
                            "SECOES": [ 
                                {{ "titulo": "NOME DA SEÇÃO", "ref": "Texto doc 1", "bel": "Texto doc 2", "status": "OK ou DIVERGENTE" }} 
                            ] 
                        }}
                        """

                        try:
                            response = model_instance.generate_content(
                                [prompt] + payload,
                                generation_config={"response_mime_type": "application/json"}
                            )
                            
                            # Verifica se o Google bloqueou por Copyright
                            if hasattr(response.candidates[0], 'finish_reason') and response.candidates[0].finish_reason == 4:
                                st.error("⚠️ Bloqueio de Segurança (Copyright)")
                                st.warning("O arquivo enviado foi identificado como protegido. Tente usar a versão DOCX ou copiar o texto para o Word.")
                            else:
                                data = extract_json(response.text)
                                if data:
                                    meta = data.get("METADADOS", {})
                                    cM1, cM2, cM3 = st.columns(3)
                                    cM1.metric("Score de Igualdade", f"{meta.get('score',0)}%")
                                    cM2.metric("Seções Analisadas", len(data.get("SECOES", [])))
                                    cM3.metric("Datas Encontradas", str(meta.get("datas", [])))
                                    st.divider()
                                    
                                    for sec in data.get("SECOES", []):
                                        status = sec.get('status', 'N/A')
                                        icon = "✅"
                                        if "DIVERGENTE" in status: icon = "❌"
                                        elif "FALTANTE" in status: icon = "🚨"
                                        
                                        with st.expander(f"{icon} {sec['titulo']} - {status}"):
                                            cA, cB = st.columns(2)
                                            cA.markdown(f"**Referência (Original)**\n<div style='background:#f9f9f9;padding:10px;border-radius:5px;'>{sec.get('ref','')}</div>", unsafe_allow_html=True)
                                            cB.markdown(f"**Belfar (Comparação)**\n<div style='background:#e6fffa;padding:10px;border-radius:5px;'>{sec.get('bel','')}</div>", unsafe_allow_html=True)
                                else:
                                    st.error("Erro na interpretação da resposta. Tente novamente.")
                                    
                        except Exception as e:
                            st.error(f"Erro durante a geração: {e}")
                            
                except Exception as e:
                    st.error(f"Erro no processamento dos arquivos: {e}")
