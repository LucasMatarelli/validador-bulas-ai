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
    .main { background-color: #f4f6f8; }
    
    .stCard { background-color: white; padding: 25px; border-radius: 15px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); margin-bottom: 25px; border: 1px solid #e1e4e8; }
    
    mark.diff { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 3px; font-weight: bold; border-bottom: 2px solid #ffc107; } 
    mark.ort { background-color: #f8d7da; color: #721c24; padding: 2px 4px; border-radius: 3px; font-weight: bold; text-decoration: underline wavy red; } 
    mark.anvisa { background-color: #d1ecf1; color: #0c5460; padding: 2px 4px; border-radius: 3px; font-weight: bold; }

    .texto-bula { font-size: 1.0rem; line-height: 1.6; color: #333; font-family: 'Segoe UI', sans-serif; white-space: pre-wrap; }
    
    .stButton>button { width: 100%; background-color: #55a68e; color: white; font-weight: bold; border-radius: 10px; height: 50px; border: none; font-size: 16px; }
</style>
""", unsafe_allow_html=True)

# ----------------- CONSTANTES -----------------
SECOES_PACIENTE = [
    "APRESENTAÇÕES", "COMPOSIÇÃO",
    "1. PARA QUE ESTE MEDICAMENTO É INDICADO?",
    "2. COMO ESTE MEDICAMENTO FUNCIONA?",
    "3. QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
    "4. O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
    "5. ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
    "6. COMO DEVO USAR ESTE MEDICAMENTO?",
    "7. O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
    "8. QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?",
    "9. O QUE FAZER SE ALGUÉM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
    "DIZERES LEGAIS"
]

SECOES_PROFISSIONAL = [
    "APRESENTAÇÕES", "COMPOSIÇÃO",
    "1. INDICAÇÕES", "2. RESULTADOS DE EFICÁCIA",
    "3. CARACTERÍSTICAS FARMACOLÓGICAS", "4. CONTRAINDICAÇÕES",
    "5. ADVERTÊNCIAS E PRECAUÇÕES", "6. INTERAÇÕES MEDICAMENTOSAS",
    "7. CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO", "8. POSOLOGIA E MODO DE USAR",
    "9. REAÇÕES ADVERSAS", "10. SUPERDOSE", "DIZERES LEGAIS"
]

SECOES_VISUALIZACAO = ["APRESENTAÇÕES", "COMPOSIÇÃO"]

# ----------------- FUNÇÕES AUXILIARES -----------------

@st.cache_resource
def get_mistral_client():
    api_key = None
    try: api_key = st.secrets["MISTRAL_API_KEY"]
    except: pass 
    if not api_key: api_key = os.environ.get("MISTRAL_API_KEY")
    return Mistral(api_key=api_key) if api_key else None

def image_to_base64(image):
    buffered = io.BytesIO()
    image.save(buffered, format="JPEG", quality=90, optimize=True)
    return base64.b64encode(buffered.getvalue()).decode("utf-8")

def sanitize_text(text):
    if not text: return ""
    text = unicodedata.normalize('NFKC', text)
    text = text.replace('\xa0', ' ').replace('\u200b', '').replace('\u00ad', '').replace('\ufeff', '').replace('\t', ' ')
    return re.sub(r'\s+', ' ', text).strip()

def clean_noise(text):
    """Limpa cabeçalhos e rodapés que atrapalham a leitura contínua"""
    lines = text.split('\n')
    cleaned_lines = []
    # Padrões para remover (paginação, marcas, códigos de bula)
    ignore_patterns = [
        r'^\d+(\s*de\s*\d+)?$', r'^Página\s*\d+\s*de\s*\d+$', # Paginação
        r'^BELFAR$', r'^UBELFAR$', r'^SANOFI$', r'^MEDLEY$', r'^EUROFARMA$', # Marcas
        r'^Bula do (Paciente|Profissional)$', r'^Versão\s*\d+$',
        r'^\d+,\d+\s*mm$', r'^BUL\d+' # Códigos de gráfica e medidas
    ]
    
    for line in lines:
        l = line.strip()
        should_skip = False
        if len(l) < 50: # Só analisa linhas curtas para evitar deletar texto real
            for pattern in ignore_patterns:
                if re.match(pattern, l, re.IGNORECASE):
                    should_skip = True
                    break
        if not should_skip:
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines)

def extract_json(text):
    text = re.sub(r'```json|```', '', text).strip()
    try:
        start, end = text.find('{'), text.rfind('}') + 1
        return json.loads(text[start:end]) if start != -1 and end != -1 else json.loads(text)
    except: return None

@st.cache_data(show_spinner=False)
def process_file_content(file_bytes, filename):
    """
    Lê o arquivo preservando a ordem das colunas e força OCR se necessário.
    """
    try:
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            return {"type": "text", "data": sanitize_text(text)}
        
        elif filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            full_text = ""
            
            # 1. Tenta ler texto nativo ordenado por blocos (colunas)
            for page in doc: 
                blocks = page.get_text("blocks", sort=True)
                for b in blocks:
                    if b[6] == 0: # Tipo texto
                        # Adiciona marcador [FIM_DO_BLOCO] para ajudar o LLM a ver a quebra de coluna
                        full_text += b[4] + "\n[FIM_DO_BLOCO]\n" 
            
            # 2. Se tiver pouco texto (imagem/curvas), usa OCR (Zoom 3x)
            if len(full_text.strip()) < 200:
                images = []
                limit_pages = min(8, len(doc)) 
                for i in range(limit_pages):
                    page = doc[i]
                    # Zoom alto para ler letras pequenas
                    pix = page.get_pixmap(matrix=fitz.Matrix(3.0, 3.0)) 
                    try: img_byte_arr = io.BytesIO(pix.tobytes("jpeg"))
                    except: img_byte_arr = io.BytesIO(pix.tobytes("png"))
                    img = Image.open(img_byte_arr)
                    if img.width > 2500: img.thumbnail((2500, 2500), Image.Resampling.LANCZOS)
                    images.append(img)
                doc.close()
                return {"type": "images", "data": images}
            
            # 3. Limpa ruídos do texto nativo
            full_text = clean_noise(full_text)
            doc.close()
            return {"type": "text", "data": sanitize_text(full_text)}
            
    except Exception as e:
        return {"type": "text", "data": ""}

def auditar_secao_worker(client, secao, d1, d2, nome_doc1, nome_doc2, todas_secoes):
    eh_visualizacao = any(s in secao.upper() for s in SECOES_VISUALIZACAO)
    
    # 1. STOP WORDS GLOBAIS: Todos os outros títulos são barreiras.
    barreiras = [s for s in todas_secoes if s != secao]
    barreiras.extend(["DIZERES LEGAIS", "Anexo B", "Histórico de Alteração"])
    stop_markers_str = "\n".join([f"- {s}" for s in barreiras])

    # 2. REGRAS ESPECÍFICAS PARA CORRIGIR OS ERROS RELATADOS
    regra_especifica = ""
    
    if "1. PARA QUE" in secao.upper():
        regra_especifica = """
        ⚠️ REGRA CRÍTICA PARA SEÇÃO 1:
        - Esta seção deve conter APENAS as indicações terapêuticas.
        - **IMPORTANTE:** Se você encontrar "Atenção: Contém lactose", "Atenção: Contém açúcar" ou "Atenção: Contém corantes", **PARE**. Isso NÃO faz parte da Seção 1, pertence à Seção 3 ou 5.
        - Não inclua o quadro de "Atenção" no texto desta seção.
        """
    elif "7. O QUE DEVO FAZER" in secao.upper():
        regra_especifica = """
        ⚠️ REGRA DE LITERALIDADE MÁXIMA (SEÇÃO 7):
        - Você está PROIBIDO de reescrever.
        - Se o texto diz "deixou de tomar", ESCREVA "deixou de tomar".
        - Se o texto diz "se esquecer", ESCREVA "se esquecer".
        - NÃO TROQUE UM PELO OUTRO. Copie palavra por palavra.
        """
    elif "9. O QUE FAZER SE" in secao.upper():
        regra_especifica = """
        ⚠️ REGRA DE CAPTURA COMPLETA (SEÇÃO 9):
        - Esta seção geralmente tem duas partes: uma explicação e um alerta em negrito.
        - Capture TODOS os parágrafos até encontrar "DIZERES LEGAIS".
        - Inclua o trecho "Em caso de uso de grande quantidade...".
        """
    elif "3. QUANDO NÃO DEVO" in secao.upper():
        regra_especifica = """
        ⚠️ REGRA DE INCLUSÃO (SEÇÃO 3):
        - Inclua os avisos de "Atenção: Contém lactose/açúcar/corantes" que aparecem logo após as contraindicações. Eles pertencem a esta seção.
        """
    elif "4. O QUE DEVO SABER" in secao.upper():
        regra_especifica = """
        ⚠️ REGRA DE CONTINUIDADE (SEÇÃO 4):
        - Esta seção é longa e pode quebrar colunas.
        - Continue copiando mesmo após quebras de linha (`[FIM_DO_BLOCO]`) até encontrar o título "5. ONDE, COMO...".
        """

    # 3. PROMPT "ROBÔ" (SEM CRIATIVIDADE)
    prompt_text = f"""
    Você é um software de OCR (Reconhecimento Óptico de Caracteres) burro e literal.
    Sua única função é copiar e colar texto. Você não pensa, não resume e não corrige.
    
    TAREFA: Extrair o conteúdo da seção: "{secao}".
    
    REGRAS DE OURO:
    1. **ZERO CRIATIVIDADE**: Copie o texto EXATAMENTE como está no PDF.
       - Original: "deixou de tomar" -> Sua Saída: "deixou de tomar". (NUNCA mude para "esqueceu").
       - Original: "informe ao médico" -> Sua Saída: "informe ao médico".
    
    2. **RESPEITE OS MARCADORES**:
       - O texto tem marcadores `[FIM_DO_BLOCO]`. Eles indicam fim de coluna.
       - Se o texto da seção continua na próxima coluna, pule o marcador e continue copiando.
       - Se a próxima coluna começa com OUTRO TÍTULO, pare imediatamente.
    
    {regra_especifica}
    
    ⛔ TÍTULOS DE PARADA (Se encontrar qualquer um destes, PARE DE COPIAR imediatamente):
    {stop_markers_str}
    
    SAÍDA JSON:
    {{
      "titulo": "{secao}",
      "ref": "cole aqui o texto LITERAL do documento 1",
      "bel": "cole aqui o texto LITERAL do documento 2",
      "status": "CONFORME"
    }}
    """
    
    messages_content = [{"type": "text", "text": prompt_text}]

    limit = 60000
    for d, nome in [(d1, nome_doc1), (d2, nome_doc2)]:
        if d['type'] == 'text':
            if len(d['data']) < 50:
                 messages_content.append({"type": "text", "text": f"\n--- {nome}: (Vazio/Ilegível) ---\n"})
            else:
                 messages_content.append({"type": "text", "text": f"\n--- {nome} ---\n{d['data'][:limit]}"}) 
        else:
            messages_content.append({"type": "text", "text": f"\n--- {nome} (Imagens) ---"})
            # Envia mais páginas (até 6) para garantir captura de seções longas que quebram página
            for img in d['data'][:6]: 
                b64 = image_to_base64(img)
                messages_content.append({"type": "image_url", "image_url": f"data:image/jpeg;base64,{b64}"})

    for attempt in range(2):
        try:
            chat_response = client.chat.complete(
                model="pixtral-large-latest", 
                messages=[{"role": "user", "content": messages_content}],
                response_format={"type": "json_object"},
                temperature=0.0 # Temperatura zero para evitar alucinação
            )
            raw_content = chat_response.choices[0].message.content
            dados = extract_json(raw_content)
            
            if dados and 'ref' in dados:
                dados['titulo'] = secao
                
                if not eh_visualizacao:
                    # Limpeza para comparação apenas
                    t_ref = re.sub(r'\s+', ' ', str(dados.get('ref', '')).strip().lower())
                    t_bel = re.sub(r'\s+', ' ', str(dados.get('bel', '')).strip().lower())
                    t_ref = re.sub(r'<[^>]+>', '', t_ref)
                    t_bel = re.sub(r'<[^>]+>', '', t_bel)

                    if t_ref == t_bel:
                        dados['status'] = 'CONFORME'
                        # Remove marcações HTML se for conforme para visualização limpa
                        dados['ref'] = re.sub(r'<mark[^>]*>|</mark>', '', dados.get('ref', ''))
                        dados['bel'] = re.sub(r'<mark[^>]*>|</mark>', '', dados.get('bel', ''))
                    else:
                        dados['status'] = 'DIVERGENTE'
                
                if "DIZERES LEGAIS" in secao.upper():
                    dados['status'] = "VISUALIZACAO"

                return dados
                
        except Exception as e:
            if attempt == 0: time.sleep(1)
            else: return {"titulo": secao, "ref": f"Erro: {str(e)}", "bel": "Erro", "status": "ERRO"}
    
    return {"titulo": secao, "ref": "Erro extração", "bel": "Erro extração", "status": "ERRO"}

# ----------------- UI PRINCIPAL -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=80)
    st.title("Validador de bulas")
    client = get_mistral_client()
    if client: st.success("✅ Sistema Online")
    else: st.error("❌ Configuração pendente")
    st.divider()
    pagina = st.radio("Navegação:", ["🏠 Início", "💊 Ref x BELFAR", "📋 Conferência MKT", "🎨 Gráfica x Arte"])
    st.divider()
    st.caption("v5.5 - Regras Específicas Finais")

if pagina == "🏠 Início":
    st.markdown("<h1 style='text-align: center; color: #55a68e;'>Validador de Bulas</h1>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1: st.info("✅ **Correção Seção 1:** Ignora 'Atenção' (pertencem à Seção 3).")
    with c2: st.info("✅ **Correção Seção 7:** Proibido sinônimos (cópia literal).")

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
    with c1: f1 = st.file_uploader(label_box1, type=["pdf", "docx"], key="f1")
    with c2: f2 = st.file_uploader(label_box2, type=["pdf", "docx"], key="f2")
        
    st.write("") 
    if st.button("🚀 INICIAR AUDITORIA"):
        if not f1 or not f2 or not client:
            st.warning("⚠️ Verifique arquivos e API Key.")
        else:
            with st.status("🔄 Processando documentos...", expanded=True) as status:
                st.write("📖 Lendo arquivos...")
                d1 = process_file_content(f1.getvalue(), f1.name)
                d2 = process_file_content(f2.getvalue(), f2.name)
                
                st.write("🔍 Auditando seções...")
                resultados = []
                bar = st.progress(0)
                
                with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                    futures = {
                        executor.submit(auditar_secao_worker, client, sec, d1, d2, nome_doc1, nome_doc2, lista_secoes): sec 
                        for sec in lista_secoes
                    }
                    
                    for i, future in enumerate(concurrent.futures.as_completed(futures)):
                        res = future.result()
                        resultados.append(res)
                        bar.progress((i + 1) / len(lista_secoes))
                
                status.update(label="✅ Concluído!", state="complete", expanded=False)

            resultados.sort(key=lambda x: lista_secoes.index(x['titulo']) if x['titulo'] in lista_secoes else 999)
            
            conformes = sum(1 for r in resultados if "CONFORME" in r.get('status', ''))
            divergentes = sum(1 for r in resultados if "DIVERGENTE" in r.get('status', ''))
            
            k1, k2, k3 = st.columns(3)
            k1.metric("Total", len(lista_secoes))
            k2.metric("Conformes", conformes)
            k3.metric("Divergentes", divergentes, delta_color="inverse")
            
            st.divider()
            
            for res in resultados:
                status = res.get('status', 'ERRO')
                icon = "✅" if "CONFORME" in status else "⚠️" if "DIVERGENTE" in status else "👁️"
                cor = "#28a745" if "CONFORME" in status else "#ffc107" if "DIVERGENTE" in status else "#17a2b8"
                
                with st.expander(f"{icon} {res['titulo']} - {status}", expanded=("DIVERGENTE" in status)):
                    c_a, c_b = st.columns(2)
                    with c_a:
                        st.caption(nome_doc1)
                        st.markdown(f"<div class='texto-bula' style='background:#f9f9f9; padding:15px; border-left: 5px solid {cor};'>{res.get('ref', '')}</div>", unsafe_allow_html=True)
                    with c_b:
                        st.caption(nome_doc2)
                        st.markdown(f"<div class='texto-bula' style='background:#fff; border:1px solid #ddd; padding:15px; border-left: 5px solid {cor};'>{res.get('bel', '')}</div>", unsafe_allow_html=True)
