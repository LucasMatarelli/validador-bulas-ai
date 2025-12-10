import streamlit as st
from mistralai import Mistral
import fitz  # PyMuPDF
import docx
import io
import json
import re
import os
import gc
import base64
import concurrent.futures
import time
import unicodedata
from PIL import Image

# ----------------- CONFIGURAÇÃO DA PÁGINA -----------------
st.set_page_config(
    page_title="Validador de Bulas",
    page_icon="💊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- ESTILOS CSS -----------------
st.markdown("""
<style>
    header[data-testid="stHeader"] { display: none !important; }
    .main .block-container { padding-top: 20px !important; }
    .main { background-color: #f8f9fa; }

    h1, h2, h3 { color: #2c3e50; font-family: 'Segoe UI', sans-serif; }
    
    .stRadio > div[role="radiogroup"] > label {
        background-color: white; border: 1px solid #e9ecef; padding: 15px;
        border-radius: 10px; margin-bottom: 10px; transition: all 0.3s ease;
        box-shadow: 0 2px 5px rgba(0,0,0,0.03); display: flex; align-items: center; font-weight: 500;
    }
    .stRadio > div[role="radiogroup"] > label:hover {
        background-color: #e8f5e9; border-color: #55a68e; color: #55a68e; transform: translateX(5px); cursor: pointer;
    }

    .stCard { background-color: white; padding: 25px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); margin-bottom: 20px; border: 1px solid #f1f1f1; }
    
    /* Cores das Marcações */
    mark.diff { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; } 
    mark.ort { background-color: #f8d7da; color: #721c24; padding: 2px 4px; border-radius: 4px; border-bottom: 2px solid #dc3545; } 
    mark.anvisa { background-color: #cff4fc; color: #055160; padding: 2px 4px; border-radius: 4px; border: 1px solid #b6effb; font-weight: bold; }

    .stButton>button { 
        width: 100%; background: linear-gradient(90deg, #55a68e 0%, #448c75 100%); 
        color: white; font-weight: bold; border-radius: 12px; height: 60px; font-size: 18px; border: none;
        box-shadow: 0 4px 15px rgba(85, 166, 142, 0.3); transition: transform 0.2s;
    }
    .stButton>button:hover { transform: scale(1.02); box-shadow: 0 6px 20px rgba(85, 166, 142, 0.4); }
</style>
""", unsafe_allow_html=True)

# ----------------- CONSTANTES (LISTAS CORRETAS) -----------------
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

SECOES_VISUALIZACAO = ["APRESENTAÇÕES", "COMPOSIÇÃO"]

# ----------------- FUNÇÕES AUXILIARES -----------------

def get_mistral_client():
    api_key = None
    try: api_key = st.secrets["MISTRAL_API_KEY"]
    except: pass 
    if not api_key: api_key = os.environ.get("MISTRAL_API_KEY")
    return Mistral(api_key=api_key) if api_key else None

def image_to_base64(image):
    buffered = io.BytesIO()
    image.save(buffered, format="JPEG", quality=85) 
    return base64.b64encode(buffered.getvalue()).decode("utf-8")

def sanitize_text(text):
    if not text: return ""
    text = unicodedata.normalize('NFKC', text)
    text = text.replace('\xa0', ' ').replace('\u0000', '').replace('\u200b', '').replace('\t', ' ')
    return re.sub(r'\s+', ' ', text).strip()

# --- REMOVEDOR DE NUMERAÇÃO INICIAL ---
def remove_numbering(text):
    if not text: return ""
    clean = re.sub(r'^\s*\d+[\.\)]\s*', '', text) 
    return clean

@st.cache_data(show_spinner=False)
def process_file_content(file_bytes, filename):
    try:
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            return {"type": "text", "data": sanitize_text(text)}
        elif filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            full_text = ""
            for page in doc: full_text += page.get_text() + " "
            
            if len(full_text.strip()) > 100:
                doc.close()
                return {"type": "text", "data": sanitize_text(full_text)}
            
            images = []
            limit_pages = min(5, len(doc))
            for i in range(limit_pages):
                page = doc[i]
                pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
                try: img_byte_arr = io.BytesIO(pix.tobytes("jpeg", jpg_quality=90))
                except: img_byte_arr = io.BytesIO(pix.tobytes("png"))
                images.append(Image.open(img_byte_arr))
            doc.close()
            gc.collect()
            return {"type": "images", "data": images}
    except: return None
    return None

def extract_json(text):
    text = re.sub(r'```json|```', '', text).strip()
    if text.startswith("json"): text = text[4:]
    try:
        start, end = text.find('{'), text.rfind('}') + 1
        return json.loads(text[start:end]) if start != -1 and end != -1 else json.loads(text)
    except: return None

# --- WORKER COM LIMITES RÍGIDOS DE SEÇÃO ---
def auditar_secao_worker(client, secao, d1, d2, nome_doc1, nome_doc2, proxima_secao):
    
    eh_dizeres = "DIZERES LEGAIS" in secao.upper()
    eh_visualizacao = any(s in secao.upper() for s in SECOES_VISUALIZACAO)
    
    # INSTRUÇÃO DE PARADA OBRIGATÓRIA
    limite_instrucao = ""
    if proxima_secao:
        limite_instrucao = f"""
        CRÍTICO: O conteúdo desta seção VAI ATÉ você encontrar o título da próxima seção que é: '{proxima_secao}'.
        PARE A LEITURA IMEDIATAMENTE ANTES desse título.
        NÃO inclua o texto da próxima seção.
        """
    else:
        limite_instrucao = "Este é o último tópico. O texto vai até o fim do arquivo."

    prompt_text = ""
    
    if eh_dizeres:
        prompt_text = f"""
        Atue como Auditor de Bulas.
        TAREFA: Extrair "DIZERES LEGAIS".
        
        ONDE PROCURAR: Rodapé (CNPJ, Farm. Resp, SAC).
        ATENÇÃO: Se o texto começar com "Como devo usar", VOCÊ PEGOU A SEÇÃO ERRADA.
        
        REGRAS:
        1. Copie o texto fielmente.
        2. Destaque a data (DD/MM/AAAA) com <mark class='anvisa'>DATA</mark>.
        3. NÃO use tag amarela.
        
        SAÍDA JSON: {{ "titulo": "{secao}", "ref": "...", "bel": "...", "status": "VISUALIZACAO" }}
        """
    elif eh_visualizacao:
        prompt_text = f"""
        Atue como Formatador.
        TAREFA: Transcrever "{secao}".
        {limite_instrucao}
        REGRAS: Apenas transcreva o texto. Sem marcações.
        SAÍDA JSON: {{ "titulo": "{secao}", "ref": "...", "bel": "...", "status": "VISUALIZACAO" }}
        """
    else:
        # Prompt de Comparação com Limite Rígido
        prompt_text = f"""
        Atue como Auditor de Texto Rigoroso.
        TAREFA: Comparar "{secao}" entre Doc 1 e Doc 2.
        
        DELIMITAÇÃO OBRIGATÓRIA:
        1. O texto começa DEPOIS do título "{secao}".
        2. {limite_instrucao}
        
        REGRAS DE COMPARAÇÃO (AMARELO):
        1. Se o Doc 2 tem um trecho/frase que NÃO existe no Doc 1 -> MARQUE ESSE TRECHO EM AMARELO NO DOC 2.
        2. Se o Doc 1 tem um trecho que SUMIU no Doc 2 -> MARQUE ESSE TRECHO EM AMARELO NO DOC 1.
        3. IGNORE diferenças de formatação, pontuação colada ou espaços.
        4. Use <mark class='diff'>TRECHO</mark> para destacar as diferenças.
        
        SAÍDA JSON: {{ "titulo": "{secao}", "ref": "...", "bel": "...", "status": "CONFORME ou DIVERGENTE" }}
        """
    
    messages_content = [{"type": "text", "text": prompt_text}]

    limit = 60000 
    for d, nome in [(d1, nome_doc1), (d2, nome_doc2)]:
        if d['type'] == 'text':
            messages_content.append({"type": "text", "text": f"\n--- {nome} ---\n{d['data'][:limit]}"}) 
        else:
            messages_content.append({"type": "text", "text": f"\n--- IMAGEM {nome} ---"})
            for img in d['data'][:2]:
                b64 = image_to_base64(img)
                messages_content.append({"type": "image_url", "image_url": f"data:image/jpeg;base64,{b64}"})

    for attempt in range(2):
        try:
            chat_response = client.chat.complete(
                model="pixtral-large-latest", 
                messages=[{"role": "user", "content": messages_content}],
                response_format={"type": "json_object"}
            )
            raw_content = chat_response.choices[0].message.content
            dados = extract_json(raw_content)
            
            if dados and 'ref' in dados:
                dados['titulo'] = secao
                dados['ref'] = remove_numbering(dados.get('ref', ''))
                dados['bel'] = remove_numbering(dados.get('bel', ''))

                if not eh_visualizacao and not eh_dizeres:
                    texto_completo = (str(dados.get('bel', '')) + str(dados.get('ref', ''))).lower()
                    tem_diff = 'class="diff"' in texto_completo or "class='diff'" in texto_completo
                    tem_ort = 'class="ort"' in texto_completo or "class='ort'" in texto_completo
                    if not tem_diff and not tem_ort:
                        dados['status'] = 'CONFORME'
                
                if eh_dizeres: dados['status'] = 'VISUALIZACAO'
                return dados
                
        except Exception:
            time.sleep(1)
            continue
    
    return {
        "titulo": secao,
        "ref": d1['data'][:3000] + "...",
        "bel": d2['data'][:3000] + "...",
        "status": "ERRO LEITURA"
    }

# ----------------- UI PRINCIPAL -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=80)
    st.title("Validador de bulas")
    client = get_mistral_client()
    if client: st.success("✅ Sistema Online")
    else: st.error("❌ Offline")
    st.divider()
    pagina = st.radio("Navegação:", ["🏠 Início", "💊 Ref x BELFAR", "📋 Conferência MKT", "🎨 Gráfica x Arte"])
    st.divider()

if pagina == "🏠 Início":
    st.markdown("""
    <div style="text-align: center; padding: 40px 20px;">
        <h1 style="color: #55a68e; font-size: 3em;">Validador de Bulas</h1>
        <p style="font-size: 1.2em; color: #7f8c8d;">Auditoria com Limites de Seção Precisos.</p>
    </div>
    """, unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    c1.info("Limites: Para de ler no título seguinte.")
    c2.info("Diferenças: Marca texto adicionado/removido.")
    c3.info("Anvisa: Data azul nos Dizeres.")

else:
    st.markdown(f"## {pagina}")
    
    lista_secoes = SECOES_PACIENTE
    nome_doc1 = "REFERÊNCIA"
    nome_doc2 = "BELFAR"
    
    if pagina == "💊 Ref x BELFAR":
        label_box1 = "📄 Referência"
        label_box2 = "📄 BELFAR"
        col_tipo, _ = st.columns([1, 2])
        with col_tipo:
            tipo_bula = st.radio("Tipo:", ["Paciente", "Profissional"], horizontal=True)
            if tipo_bula == "Profissional": lista_secoes = SECOES_PROFISSIONAL
    elif pagina == "📋 Conferência MKT":
        label_box1 = "📄 ANVISA"
        label_box2 = "📄 MKT"
        nome_doc1 = "ANVISA"
        nome_doc2 = "MKT"
    elif pagina == "🎨 Gráfica x Arte":
        label_box1 = "📄 Arte Vigente"
        label_box2 = "📄 Gráfica"
        nome_doc1 = "ARTE VIGENTE"
        nome_doc2 = "GRÁFICA"
    
    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"##### {label_box1}")
        f1 = st.file_uploader("", type=["pdf", "docx"], key="f1")
    with c2:
        st.markdown(f"##### {label_box2}")
        f2 = st.file_uploader("", type=["pdf", "docx"], key="f2")
        
    st.write("") 
    if st.button("INICIAR AUDITORIA"):
        if not f1 or not f2:
            st.warning("⚠️ Selecione os arquivos.")
        else:
            if not client: st.stop()
            with st.spinner("🚀 Processando arquivos..."):
                b1 = f1.getvalue()
                b2 = f2.getvalue()
                d1 = process_file_content(b1, f1.name.lower())
                d2 = process_file_content(b2, f2.name.lower())
                gc.collect()
            if not d1 or not d2:
                st.error("Erro leitura.")
                st.stop()

            resultados_secoes = []
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                future_to_secao = {}
                for i, secao in enumerate(lista_secoes):
                    # PASSA A PRÓXIMA SEÇÃO COMO DELIMITADOR
                    proxima = lista_secoes[i+1] if i + 1 < len(lista_secoes) else None
                    future = executor.submit(auditar_secao_worker, client, secao, d1, d2, nome_doc1, nome_doc2, proxima)
                    future_to_secao[future] = secao
                
                completed = 0
                for future in concurrent.futures.as_completed(future_to_secao):
                    try:
                        data = future.result()
                        if data: resultados_secoes.append(data)
                    except: pass
                    completed += 1
                    progress_bar.progress(completed / len(lista_secoes))
                    status_text.text(f"Analisando: {completed}/{len(lista_secoes)}")
            
            status_text.empty()
            progress_bar.empty()

            resultados_secoes.sort(key=lambda x: lista_secoes.index(x['titulo']) if x['titulo'] in lista_secoes else 999)
            
            total = len(resultados_secoes)
            conformes = sum(1 for x in resultados_secoes if "CONFORME" in x.get('status', ''))
            visuais = sum(1 for x in resultados_secoes if "VISUALIZACAO" in x.get('status', ''))
            score = int(((conformes + visuais) / total) * 100) if total > 0 else 0
            
            datas_texto = "N/D"
            for r in resultados_secoes:
                if "DIZERES LEGAIS" in r['titulo']:
                    match = re.search(r'\d{2}/\d{2}/\d{4}', r.get('bel', '') + r.get('ref', ''))
                    if match: datas_texto = match.group(0)

            m1, m2, m3 = st.columns(3)
            m1.metric("Conformidade", f"{score}%")
            m2.metric("Seções", total)
            m3.metric("Data Ref.", datas_texto)
            st.divider()
            
            for sec in resultados_secoes:
                status = sec.get('status', 'N/A')
                titulo = sec.get('titulo', '').upper()
                
                icon = "✅"
                if "DIVERGENTE" in status: icon = "❌"
                elif "FALTANTE" in status: icon = "🚨"
                elif "ERRO" in status: icon = "⚠️"
                elif "VISUALIZACAO" in status: icon = "👁️"
                
                with st.expander(f"{icon} {titulo} — {status}"):
                    cA, cB = st.columns(2)
                    with cA:
                        st.markdown(f"**{nome_doc1}**")
                        st.markdown(f"<div class='texto-bula' style='background:#f9f9f9; padding:15px; border-radius:5px;'>{sec.get('ref', 'Texto não extraído')}</div>", unsafe_allow_html=True)
                    with cB:
                        st.markdown(f"**{nome_doc2}**")
                        st.markdown(f"<div class='texto-bula' style='background:#fff; border:1px solid #eee; padding:15px; border-radius:5px;'>{sec.get('bel', 'Texto não extraído')}</div>", unsafe_allow_html=True)
