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
    page_title="Validador de Bulas Pro",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- ESTILOS CSS (ZOOM E LEITURA OTIMIZADA) -----------------
st.markdown("""
<style>
    header[data-testid="stHeader"] { display: none !important; }
    .main .block-container { padding-top: 20px !important; }
    .main { background-color: #f4f6f9; }

    h1, h2, h3 { color: #1e293b; font-family: 'Segoe UI', sans-serif; letter-spacing: -0.5px; }
    
    /* Navegação */
    .stRadio > div[role="radiogroup"] > label {
        background-color: white; border: 1px solid #e2e8f0; padding: 16px;
        border-radius: 8px; margin-bottom: 8px; transition: all 0.2s ease;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05); font-weight: 600; color: #475569;
    }
    .stRadio > div[role="radiogroup"] > label:hover {
        background-color: #eff6ff; border-color: #3b82f6; color: #1d4ed8;
    }

    /* Cards */
    .stCard { background-color: white; padding: 25px; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); margin-bottom: 20px; border: 1px solid #e2e8f0; }
    
    /* LEITURA: Fonte maior e monoespaçada para evitar confusão visual */
    .texto-bula {
        font-family: 'Consolas', 'Monaco', monospace !important;
        font-size: 1.1rem !important; 
        line-height: 1.8;
        color: #334155;
        white-space: pre-wrap; /* Mantém quebras de linha originais */
    }

    /* Cores das Marcações - Alto Contraste */
    mark.diff { background-color: #fef08a; color: #854d0e; padding: 2px 6px; border-radius: 4px; border: 1px solid #facc15; font-weight: bold; } 
    mark.ort { background-color: #fecaca; color: #991b1b; padding: 2px 6px; border-radius: 4px; border-bottom: 2px solid #ef4444; } 
    mark.anvisa { background-color: #bae6fd; color: #0369a1; padding: 2px 6px; border-radius: 4px; border: 1px solid #7dd3fc; font-weight: bold; }

    /* Botão */
    .stButton>button { 
        width: 100%; background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%); 
        color: white; font-weight: 700; border-radius: 10px; height: 60px; font-size: 18px; border: none;
        box-shadow: 0 4px 6px -1px rgba(37, 99, 235, 0.3); transition: transform 0.1s;
    }
    .stButton>button:hover { transform: translateY(-2px); box-shadow: 0 10px 15px -3px rgba(37, 99, 235, 0.4); }
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
    # Aumentei para 100% de qualidade para evitar artefatos de compressão nas letras pequenas
    image.save(buffered, format="JPEG", quality=100, subsampling=0) 
    return base64.b64encode(buffered.getvalue()).decode("utf-8")

def sanitize_text(text):
    if not text: return ""
    text = unicodedata.normalize('NFKC', text)
    # Remove caracteres invisíveis que atrapalham a IA
    text = text.replace('\xa0', ' ').replace('\u0000', '').replace('\u200b', '').replace('\t', ' ')
    return re.sub(r'\s+', ' ', text).strip()

@st.cache_data(show_spinner=False)
def process_file_content(file_bytes, filename):
    try:
        # --- DOCX ---
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            return {"type": "text", "data": sanitize_text(text)}
            
        # --- PDF (MOTOR DE ALTA RESOLUÇÃO) ---
        elif filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            
            # Estratégia Híbrida:
            # Se tiver pouco texto extraível, assumimos que é imagem/scan e forçamos o modo visual.
            full_text = ""
            for page in doc: full_text += page.get_text() + " "
            
            # Se for PDF de texto (não scan), usamos o texto puro pois é 100% preciso na extração
            if len(full_text.strip()) > 500:
                doc.close()
                return {"type": "text", "data": sanitize_text(full_text)}
            
            # Se for Scan ou pouquíssimo texto, ativamos o SUPER ZOOM
            images = []
            limit_pages = min(5, len(doc)) # Limite de páginas para não estourar memória
            for i in range(limit_pages):
                page = doc[i]
                
                # AQUI ESTÁ O SEGREDO DO ZOOM: Matrix(4.0, 4.0) = 300 DPI (Resolução de Impressão)
                # Antes estava 2.0 (Leitura de tela). 4.0 permite ler letras de 6pt.
                pix = page.get_pixmap(matrix=fitz.Matrix(4.0, 4.0))
                
                try: img_byte_arr = io.BytesIO(pix.tobytes("jpeg", jpg_quality=100))
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

# --- WORKER BLINDADO CONTRA ALUCINAÇÕES ---
def auditar_secao_worker(client, secao, d1, d2, nome_doc1, nome_doc2):
    
    eh_dizeres = "DIZERES LEGAIS" in secao.upper()
    eh_visualizacao = any(s in secao.upper() for s in SECOES_VISUALIZACAO)
    
    # Prompt Base Anti-Alucinação
    base_instruction = """
    DIRETRIZ DE SEGURANÇA MÁXIMA (ANTI-ALUCINAÇÃO):
    1. VOCÊ É UM ROBÔ OCR, NÃO UM EDITOR.
    2. COPIE EXATAMENTE O QUE VÊ. Se o texto diz "Frequencia" (sem acento), escreva "Frequencia". NÃO CORRIJA.
    3. Se o texto estiver ilegível, escreva [ILEGÍVEL], não invente.
    4. NÃO COMPLETE FRASES. Se a frase acaba no meio, pare onde ela acaba.
    """
    
    prompt_text = ""
    
    if eh_dizeres:
        prompt_text = f"""
        {base_instruction}
        Atue como Auditor Regulatório.
        TAREFA: Localizar "DIZERES LEGAIS".
        
        ALVO:
        - Busque por: "Farm. Resp.", "M.S.", "CNPJ", "SAC".
        - IGNORE "Como usar" ou "Posologia".
        
        SAÍDA:
        1. Copie o texto encontrado.
        2. Destaque datas (DD/MM/AAAA) com <mark class='anvisa'>DATA</mark>.
        3. Use <mark class='diff'> APENAS se houver divergência real de dados (CNPJ diferente, Endereço diferente).
        
        SAÍDA JSON: {{ "titulo": "{secao}", "ref": "...", "bel": "...", "status": "VISUALIZACAO" }}
        """
        
    elif eh_visualizacao:
        prompt_text = f"""
        {base_instruction}
        Atue como Extrator de Conteúdo.
        TAREFA: Extrair "{secao}".
        
        FILTRO (REMOVER):
        - Textos técnicos verticais de gráfica (cores, facas, códigos, dimensões).
        
        SAÍDA:
        - Transcreva o conteúdo limpo.
        - Use <mark class='diff'> se houver diferença de CONTEÚDO (ex: 10mg vs 20mg).
        - Ignore formatação.
        
        SAÍDA JSON: {{ "titulo": "{secao}", "ref": "...", "bel": "...", "status": "VISUALIZACAO" }}
        """
        
    else:
        # Prompt de Validação Estrita
        prompt_text = f"""
        {base_instruction}
        Atue como Comparador de Texto Estrito.
        TAREFA: Comparar "{secao}" palavra por palavra.
        
        1. Localize o início e fim exatos da seção "{secao}".
        2. Extraia o texto para 'ref' e 'bel' SEM CORRIGIR NADA.
        
        REGRAS DO AMARELO (<mark class='diff'>):
        - Use APENAS se a palavra estiver AUSENTE ou ESCRITA DIFERENTE (ex: erro de digitação, acentuação trocada).
        - Exemplo: "Cimelida" vs "Cimeleda" -> MARQUE.
        - Exemplo: "sodio" vs "sódio" -> MARQUE (Diferença de acento).
        
        O QUE NÃO MARCAR:
        - Pontuação isolada (vírgulas).
        - Sinônimos perfeitos (se o sentido for idêntico e óbvio).
        
        SAÍDA JSON: {{ "titulo": "{secao}", "ref": "...", "bel": "...", "status": "CONFORME ou DIVERGENTE" }}
        """
    
    messages_content = [{"type": "text", "text": prompt_text}]

    limit = 80000 # Aumentei o limite de caracteres para suportar textos maiores extraídos
    for d, nome in [(d1, nome_doc1), (d2, nome_doc2)]:
        if d['type'] == 'text':
            messages_content.append({"type": "text", "text": f"\n--- DOCUMENTO: {nome} (TEXTO PURO) ---\n{d['data'][:limit]}"}) 
        else:
            messages_content.append({"type": "text", "text": f"\n--- IMAGENS ALTA RESOLUÇÃO: {nome} ---"})
            for img in d['data'][:2]: # Envia as 2 primeiras páginas em HD
                b64 = image_to_base64(img)
                messages_content.append({"type": "image_url", "image_url": f"data:image/jpeg;base64,{b64}"})

    for attempt in range(2):
        try:
            chat_response = client.chat.complete(
                model="pixtral-large-latest", 
                messages=[{"role": "user", "content": messages_content}],
                response_format={"type": "json_object"},
                temperature=0.1 # Temperatura BAIXA para reduzir criatividade/alucinação
            )
            raw_content = chat_response.choices[0].message.content
            dados = extract_json(raw_content)
            
            if dados and 'ref' in dados:
                dados['titulo'] = secao
                
                if not eh_visualizacao and not eh_dizeres:
                    texto_completo = (str(dados.get('bel', '')) + str(dados.get('ref', ''))).lower()
                    tem_diff = 'class="diff"' in texto_completo or "class='diff'" in texto_completo
                    if not tem_diff:
                        dados['status'] = 'CONFORME'
                
                if eh_dizeres: dados['status'] = 'VISUALIZACAO'
                return dados
                
        except Exception:
            time.sleep(1)
            continue
    
    return {
        "titulo": secao,
        "ref": "Não foi possível extrair.",
        "bel": "Não foi possível extrair.",
        "status": "ERRO TÉCNICO"
    }

# ----------------- UI PRINCIPAL -----------------
with st.sidebar:
    st.title("🔎 Validador Pro")
    client = get_mistral_client()
    if client: st.success("✅ Motor de IA Ativo")
    else: st.error("❌ API Key Ausente")
    st.divider()
    pagina = st.radio("Modo de Operação:", ["🏠 Dashboard", "💊 Ref x BELFAR", "📋 MKT/Anvisa", "🎨 Arte/Gráfica"])
    st.divider()
    st.caption("v3.0 - High Definition Engine")

if pagina == "🏠 Dashboard":
    st.markdown("""
    <div style="text-align: center; padding: 40px 20px;">
        <h1 style="color: #2563eb;">Validador de Bulas 3.0</h1>
        <p style="font-size: 1.2em; color: #64748b;">Motor atualizado com Leitura HD e Anti-Alucinação.</p>
    </div>
    """, unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    c1.info("🔍 **Zoom 4x (300 DPI)**\n\nLê letras minúsculas com precisão de scanner.")
    c2.info("🤖 **Anti-Alucinação**\n\nProibido corrigir erros do original.")
    c3.info("📅 **Rastreio de Datas**\n\nCaptura datas em ambos os arquivos.")

else:
    st.markdown(f"## {pagina}")
    
    lista_secoes = SECOES_PACIENTE
    nome_doc1 = "REFERÊNCIA"
    nome_doc2 = "BELFAR"
    
    if pagina == "💊 Ref x BELFAR":
        tipo_bula = st.radio("Modelo:", ["Paciente", "Profissional"], horizontal=True)
        if tipo_bula == "Profissional": lista_secoes = SECOES_PROFISSIONAL
    elif pagina == "📋 MKT/Anvisa":
        nome_doc1 = "ANVISA"; nome_doc2 = "MKT"
    elif pagina == "🎨 Arte/Gráfica":
        nome_doc1 = "ARTE"; nome_doc2 = "GRÁFICA"
    
    st.divider()
    c1, c2 = st.columns(2)
    with c1: f1 = st.file_uploader(f"📂 {nome_doc1}", type=["pdf", "docx"], key="f1")
    with c2: f2 = st.file_uploader(f"📂 {nome_doc2}", type=["pdf", "docx"], key="f2")
        
    st.write("") 
    if st.button("INICIAR VALIDAÇÃO EM HD"):
        if not f1 or not f2:
            st.warning("⚠️ Selecione os dois arquivos.")
        else:
            if not client: st.stop()
            with st.spinner("🔄 Renderizando imagens em Alta Resolução (pode demorar um pouco)..."):
                b1 = f1.getvalue(); b2 = f2.getvalue()
                d1 = process_file_content(b1, f1.name.lower())
                d2 = process_file_content(b2, f2.name.lower())
                gc.collect()

            if not d1 or not d2:
                st.error("Erro ao processar arquivos. Verifique se não estão corrompidos.")
                st.stop()

            resultados_secoes = []
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                future_to_secao = {
                    executor.submit(auditar_secao_worker, client, secao, d1, d2, nome_doc1, nome_doc2): secao 
                    for secao in lista_secoes
                }
                completed = 0
                for future in concurrent.futures.as_completed(future_to_secao):
                    try:
                        data = future.result()
                        if data: resultados_secoes.append(data)
                    except: pass
                    completed += 1
                    progress_bar.progress(completed / len(lista_secoes))
                    status_text.text(f"Analisando Seção: {completed}/{len(lista_secoes)}")
            
            status_text.empty(); progress_bar.empty()
            resultados_secoes.sort(key=lambda x: lista_secoes.index(x['titulo']) if x['titulo'] in lista_secoes else 999)
            
            # Cálculo de Score
            total = len(resultados_secoes)
            conformes = sum(1 for x in resultados_secoes if "CONFORME" in x.get('status', ''))
            visuais = sum(1 for x in resultados_secoes if "VISUALIZACAO" in x.get('status', ''))
            score = int(((conformes + visuais) / total) * 100) if total > 0 else 0
            
            # Extração de datas
            datas_encontradas = []
            for r in resultados_secoes:
                if "DIZERES LEGAIS" in r['titulo']:
                    texto_combinado = r.get('ref', '') + " " + r.get('bel', '')
                    matches = re.findall(r'\d{2}/\d{2}/\d{4}', texto_combinado)
                    for m in matches:
                        if m not in datas_encontradas: datas_encontradas.append(m)
            datas_texto = " | ".join(datas_encontradas) if datas_encontradas else "N/D"

            # Métricas
            m1, m2, m3 = st.columns(3)
            m1.metric("Precisão", f"{score}%")
            m2.metric("Seções", total)
            m3.metric("Datas Encontradas", datas_texto)
            st.divider()
            
            # Exibição
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
                        st.markdown(f"<div class='texto-bula' style='background:#f1f5f9; padding:15px; border-radius:8px; border:1px solid #cbd5e1;'>{sec.get('ref', '')}</div>", unsafe_allow_html=True)
                    with cB:
                        st.markdown(f"**{nome_doc2}**")
                        st.markdown(f"<div class='texto-bula' style='background:#ffffff; border:1px solid #cbd5e1; padding:15px; border-radius:8px;'>{sec.get('bel', '')}</div>", unsafe_allow_html=True)
