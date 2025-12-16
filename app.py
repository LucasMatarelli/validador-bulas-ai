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
from difflib import SequenceMatcher

# ----------------- CONFIGURAÇÃO DA PÁGINA -----------------
st.set_page_config(
    page_title="Validador Sniper",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- ESTILOS CSS (VISUAL LIMPO) -----------------
st.markdown("""
<style>
    header[data-testid="stHeader"] { display: none !important; }
    .main .block-container { padding-top: 20px !important; }
    
    .stButton>button { 
        width: 100%; background-color: #2e7d32; color: white; 
        font-weight: bold; border-radius: 8px; height: 60px; font-size: 18px;
    }
    .stButton>button:hover { background-color: #1b5e20; }
    
    /* Cores de Marcação */
    mark.diff { background-color: #fff9c4; color: #f57f17; padding: 2px 6px; border-radius: 4px; border: 1px solid #fbc02d; font-weight: bold; }
    mark.ort { background-color: #ffcdd2; color: #c62828; padding: 2px 6px; border-radius: 4px; border-bottom: 2px solid #b71c1c; font-weight: bold; }
    mark.anvisa { background-color: #e1f5fe; color: #0277bd; padding: 2px 6px; border-radius: 4px; border: 1px solid #4fc3f7; font-weight: bold; }
    
    /* Caixas de Texto */
    .box-ref { background-color: #f5f5f5; padding: 15px; border-radius: 8px; border-left: 5px solid #9e9e9e; white-space: pre-wrap; line-height: 1.6; }
    .box-bel { background-color: #e8f5e9; padding: 15px; border-radius: 8px; border-left: 5px solid #2e7d32; white-space: pre-wrap; line-height: 1.6; }
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

SAFETY = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# ----------------- FUNÇÕES DO SISTEMA -----------------

def configure_gemini():
    api_key = None
    try: api_key = st.secrets["GEMINI_API_KEY"]
    except: api_key = os.environ.get("GEMINI_API_KEY")
    
    if not api_key: return False
    genai.configure(api_key=api_key)
    return True

def process_file(uploaded_file):
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
            full_text = ""
            for page in doc: full_text += page.get_text() + "\n"
            
            # Se tem muito texto, usa modo texto (mais rápido e preciso)
            if len(full_text.strip()) > 500:
                doc.close()
                return {"type": "text", "data": full_text}
            
            # Se for imagem scanneada, usa OCR via Visão
            images = []
            limit = min(12, len(doc))
            for i in range(limit):
                pix = doc[i].get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
                try: img_byte_arr = io.BytesIO(pix.tobytes("jpeg", jpg_quality=95))
                except: img_byte_arr = io.BytesIO(pix.tobytes("png"))
                images.append(Image.open(img_byte_arr))
            doc.close()
            gc.collect()
            return {"type": "images", "data": images}
    except Exception as e:
        st.error(f"Erro ao ler arquivo: {e}")
        return None

def extract_json(text):
    text = text.replace("```json", "").replace("```", "").strip()
    text = re.sub(r'//.*', '', text) # remove comentários
    try: return json.loads(text, strict=False)
    except: pass
    
    # Tentativa de resgate do JSON
    try:
        if '"SECOES":' in text:
            start = text.find('{')
            end = text.rfind('}') + 1
            if start != -1 and end != -1:
                return json.loads(text[start:end], strict=False)
    except: pass
    return None

def normalize_titles(data, allowed):
    if not data or "SECOES" not in data: return data
    clean = []
    
    # Cria mapa de normalização
    def norm(t): return re.sub(r'[^A-ZÃÕÁÉÍÓÚÇ]', '', t.upper())
    allowed_map = {norm(t): t for t in allowed}
    
    for sec in data["SECOES"]:
        t_raw = sec.get("titulo", "")
        t_norm = norm(t_raw)
        
        match = allowed_map.get(t_norm)
        if not match:
            # Fuzzy match simples
            for k, v in allowed_map.items():
                if k in t_norm or t_norm in k or SequenceMatcher(None, k, t_norm).ratio() > 0.8:
                    match = v
                    break
        
        if match:
            sec["titulo"] = match
            clean.append(sec)
            
    data["SECOES"] = clean
    return data

# ----------------- INTERFACE -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=70)
    st.markdown("### Validador Sniper 🎯")
    st.info("Modelo fixo: **Gemini 1.5 Flash**\n(O mais seguro e estável)")
    
    status_api = configure_gemini()
    if status_api: st.success("API Conectada")
    else: st.error("Sem Chave API")

    st.divider()
    pag = st.radio("Menu", ["Auditoria", "Ajuda"])

if pag == "Ajuda":
    st.markdown("### 💡 Dica Importante")
    st.warning("Se der erro de 'Quota', troque a chave API imediatamente por uma nova.")

else:
    st.markdown("<h1 style='color:#2e7d32;text-align:center;'>Validador Farmacêutico Blindado</h1>", unsafe_allow_html=True)
    
    # Seleção de tipo
    tipo = st.radio("Tipo de Bula:", ["Paciente", "Profissional"], horizontal=True)
    lista_secoes = SECOES_PROFISSIONAL if tipo == "Profissional" else SECOES_PACIENTE
    
    c1, c2 = st.columns(2)
    f1 = c1.file_uploader("📂 Referência (PDF/Word)", type=["pdf", "docx"])
    f2 = c2.file_uploader("📂 Candidato (PDF/Word)", type=["pdf", "docx"])
    
    if st.button("🚀 INICIAR AUDITORIA (SEM ERROS)"):
        if f1 and f2 and status_api:
            # 1. Processamento
            with st.spinner("📖 Lendo arquivos..."):
                d1 = process_file(f1)
                d2 = process_file(f2)
                gc.collect()

            if d1 and d2:
                # 2. Definição do Modelo (FIXO NO FLASH PARA EVITAR ERRO DE COTA)
                # O "models/" antes do nome ajuda a evitar erros de versão
                model = genai.GenerativeModel("models/gemini-1.5-flash")
                
                # 3. Montagem do Prompt
                secoes_txt = "\n".join([f"- {s}" for s in lista_secoes])
                
                prompt = f"""
                Você é um Auditor Farmacêutico Sênior da ANVISA.
                Sua tarefa é comparar dois documentos (Referência vs Candidato) e validar as seções.

                LISTA DE SEÇÕES OBRIGATÓRIAS:
                {secoes_txt}

                DIRETRIZES RIGOROSAS:
                1. Extraia o texto INTEGRAL de cada seção (não resuma).
                2. Se o texto quebrar colunas, junte corretamente.
                3. Compare letra por letra (case insensitive para status, mas mostre a diferença).
                4. Ignore números de página ou rodapés soltos.

                FORMATAÇÃO HTML PARA O CAMPO 'bel' (Candidato):
                - Se houver diferença de texto: use <mark class='diff'>palavra_candidato</mark>
                - Se houver erro ortográfico óbvio: use <mark class='ort'>erro</mark>
                - Para a data em 'DIZERES LEGAIS': use <mark class='anvisa'>DD/MM/AAAA</mark>

                SAÍDA JSON EXATA:
                {{
                    "METADADOS": {{ "datas": ["..."] }},
                    "SECOES": [
                        {{
                            "titulo": "TÍTULO EXATO DA LISTA",
                            "ref": "Texto completo da referência...",
                            "bel": "Texto do candidato com as marcações <mark>...",
                            "status": "OK" | "DIVERGENTE" | "FALTANTE"
                        }}
                    ]
                }}
                """

                payload = ["CONTEXTO: Auditoria de Bulas."]
                if d1['type'] == 'text': payload.append(f"--- REFERÊNCIA (TEXTO) ---\n{d1['data']}")
                else: payload.extend(["--- REFERÊNCIA (IMAGENS) ---"] + d1['data'])
                
                if d2['type'] == 'text': payload.append(f"--- CANDIDATO (TEXTO) ---\n{d2['data']}")
                else: payload.extend(["--- CANDIDATO (IMAGENS) ---"] + d2['data'])

                # 4. Chamada da API
                try:
                    with st.spinner("🤖 Analisando com Gemini 1.5 Flash..."):
                        response = model.generate_content(
                            [prompt] + payload,
                            generation_config={"response_mime_type": "application/json", "max_output_tokens": 15000, "temperature": 0.0},
                            safety_settings=SAFETY,
                            request_options={"timeout": 600}
                        )
                        
                        data = extract_json(response.text)
                        
                        if data and "SECOES" in data:
                            # 5. Normalização e Exibição
                            norm_data = normalize_titles(data, lista_secoes)
                            secs = norm_data["SECOES"]
                            datas = norm_data.get("METADADOS", {}).get("datas", [])

                            st.success("✅ Auditoria Finalizada!")
                            st.divider()

                            # Placar
                            col_a, col_b, col_c = st.columns(3)
                            erros = sum(1 for s in secs if s['status'] != "OK")
                            score = 100 - int((erros / max(1, len(secs))) * 100)
                            
                            col_a.metric("Score de Aprovação", f"{score}%")
                            col_b.metric("Seções Encontradas", f"{len(secs)}/{len(lista_secoes)}")
                            
                            data_display = datas[0] if datas else "N/A"
                            col_c.markdown(f"**Data Anvisa**<br><span style='font-size:1.2em;font-weight:bold;color:#0277bd'>{data_display}</span>", unsafe_allow_html=True)

                            st.markdown("---")

                            # Renderização das Seções
                            if not secs:
                                st.warning("⚠️ Nenhuma seção padrão foi identificada. Verifique se o arquivo é uma bula válida.")
                            
                            for s in secs:
                                icon = "✅"
                                if s['status'] == "DIVERGENTE": icon = "❌"
                                elif s['status'] == "FALTANTE": icon = "🚨"
                                
                                with st.expander(f"{icon} {s['titulo']} - {s['status']}"):
                                    c_ref, c_bel = st.columns(2)
                                    c_ref.markdown(f"**Referência**<div class='box-ref'>{s.get('ref','Vazio')}</div>", unsafe_allow_html=True)
                                    c_bel.markdown(f"**Candidato**<div class='box-bel'>{s.get('bel','Vazio')}</div>", unsafe_allow_html=True)

                        else:
                            st.error("Erro: A IA não retornou o formato JSON correto. Tente novamente.")
                            
                except Exception as e:
                    err_msg = str(e).lower()
                    if "429" in err_msg or "quota" in err_msg:
                        st.error("🚨 LIMITE DE COTA ATINGIDO!")
                        st.info("Solução: Crie uma nova API KEY no Google AI Studio e substitua no arquivo secrets/código.")
                    elif "404" in err_msg:
                         st.error("🚨 Modelo não encontrado. Erro de conexão com 'models/gemini-1.5-flash'.")
                    else:
                        st.error(f"Erro inesperado: {e}")
        else:
            st.warning("⚠️ Preencha todos os campos e verifique a API.")
