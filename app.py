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
    h1, h2, h3 { color: #2c3e50; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
    
    .stRadio > div[role="radiogroup"] > label {
        background-color: white; border: 1px solid #e1e4e8; padding: 12px 15px;
        border-radius: 8px; margin-bottom: 8px; transition: all 0.2s;
        box-shadow: 0 2px 4px rgba(0,0,0,0.02);
    }
    .stRadio > div[role="radiogroup"] > label:hover {
        background-color: #f0fbf7; border-color: #55a68e; color: #55a68e; cursor: pointer;
    }

    .stCard {
        background-color: white; padding: 25px; border-radius: 15px;
        box-shadow: 0 10px 20px rgba(0,0,0,0.05); margin-bottom: 25px;
        border: 1px solid #e1e4e8; transition: transform 0.2s; height: 100%;
    }
    .stCard:hover { transform: translateY(-5px); box-shadow: 0 15px 30px rgba(0,0,0,0.1); border-color: #55a68e; }

    .card-title { color: #55a68e; font-size: 1.2rem; font-weight: bold; margin-bottom: 15px; border-bottom: 2px solid #f0f2f5; padding-bottom: 10px; }
    .card-text { font-size: 0.95rem; color: #555; line-height: 1.6; }
    .highlight-blue { background-color: #cff4fc; color: #055160; padding: 0 4px; border-radius: 4px; font-weight: 500; }

    /* Marcações de texto */
    mark.diff { 
        background-color: #fff3cd; 
        color: #856404; 
        padding: 2px 4px; 
        border-radius: 3px; 
        font-weight: 500;
        border-bottom: 2px solid #ffc107;
    } 
    mark.ort { 
        background-color: #f8d7da; 
        color: #721c24; 
        padding: 2px 4px; 
        border-radius: 3px; 
        font-weight: 600;
        border-bottom: 2px solid #dc3545;
        text-decoration: underline wavy #dc3545;
    } 
    mark.anvisa { 
        background-color: #d1ecf1; 
        color: #0c5460; 
        padding: 3px 6px; 
        border-radius: 3px; 
        font-weight: bold;
        border: 1.5px solid #17a2b8;
        box-shadow: 0 1px 3px rgba(23, 162, 184, 0.2);
    }

    .stButton>button { 
        width: 100%; 
        background-color: #55a68e; 
        color: white; 
        font-weight: bold; 
        border-radius: 10px; 
        height: 55px; 
        border: none; 
        font-size: 16px; 
        box-shadow: 0 4px 6px rgba(85, 166, 142, 0.2); 
    }
    .stButton>button:hover { 
        background-color: #448c75; 
        box-shadow: 0 6px 8px rgba(85, 166, 142, 0.3); 
    }
    
    .texto-bula { 
        font-size: 1.05rem; 
        line-height: 1.7; 
        color: #333; 
    }
    
    /* Animação de loading */
    .loading-spinner {
        border: 3px solid #f3f3f3;
        border-top: 3px solid #55a68e;
        border-radius: 50%;
        width: 40px;
        height: 40px;
        animation: spin 1s linear infinite;
        margin: 20px auto;
    }
    
    @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
</style>
""", unsafe_allow_html=True)

# ----------------- CONSTANTES -----------------
SECOES_PACIENTE = [
    "APRESENTAÇÕES",
    "COMPOSIÇÃO",
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
    "APRESENTAÇÕES",
    "COMPOSIÇÃO",
    "1. INDICAÇÕES",
    "2. RESULTADOS DE EFICÁCIA",
    "3. CARACTERÍSTICAS FARMACOLÓGICAS",
    "4. CONTRAINDICAÇÕES",
    "5. ADVERTÊNCIAS E PRECAUÇÕES",
    "6. INTERAÇÕES MEDICAMENTOSAS",
    "7. CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO",
    "8. POSOLOGIA E MODO DE USAR",
    "9. REAÇÕES ADVERSAS",
    "10. SUPERDOSE",
    "DIZERES LEGAIS"
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
    """Converte imagem para base64 otimizado"""
    buffered = io.BytesIO()
    image.save(buffered, format="JPEG", quality=80, optimize=True)
    return base64.b64encode(buffered.getvalue()).decode("utf-8")

def sanitize_text(text):
    """Remove caracteres invisíveis e normaliza texto"""
    if not text: return ""
    text = unicodedata.normalize('NFKC', text)
    text = text.replace('\xa0', ' ').replace('\u200b', '').replace('\u00ad', '').replace('\ufeff', '').replace('\t', ' ')
    return re.sub(r'\s+', ' ', text).strip()

def clean_noise(text):
    """Remove cabeçalhos de página e rodapés comuns que poluem a extração"""
    lines = text.split('\n')
    cleaned_lines = []
    # Termos comuns de cabeçalho/rodapé para ignorar se a linha for curta
    lixo_comum = ["BELFAR", "UBELFAR", "SANOFI", "MEDLEY", "EMS", "EUROFARMA", "Página", "Bula do Paciente"]
    
    for line in lines:
        l = line.strip()
        # Ignora linhas que são apenas números ou paginação (ex: "1 de 9")
        if re.match(r'^(\d+|Página \d+ de \d+|Pag\.? \d+)$', l, re.IGNORECASE):
            continue
        # Ignora nomes de laboratório se a linha for curta (evita apagar texto do corpo)
        eh_lixo = False
        if len(l) < 40:
            for termo in lixo_comum:
                if termo.upper() in l.upper():
                    eh_lixo = True
                    break
        
        if not eh_lixo:
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines)

@st.cache_data(show_spinner=False)
def process_file_content(file_bytes, filename):
    """Processa arquivo com cache otimizado e LEITURA DE COLUNAS COM MARCADORES"""
    try:
        if filename.endswith('.docx'):
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join([p.text for p in doc.paragraphs])
            return {"type": "text", "data": sanitize_text(text)}
        
        elif filename.endswith('.pdf'):
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            full_text = ""
            
            # --- CORREÇÃO DE LEITURA DE COLUNAS ---
            # sort=True é essencial para ler a coluna 1 toda antes da 2
            for page in doc: 
                blocks = page.get_text("blocks", sort=True)
                for b in blocks:
                    if b[6] == 0:  # Tipo 0 = texto
                        # Adiciona marcador visual para separar parágrafos/blocos
                        full_text += b[4] + "\n\n" 
            
            # Limpa ruídos (cabeçalhos)
            full_text = clean_noise(full_text)

            if len(full_text.strip()) > 100:
                doc.close()
                return {"type": "text", "data": sanitize_text(full_text)}
            
            # OCR (fallback)
            images = []
            limit_pages = min(5, len(doc))
            for i in range(limit_pages):
                page = doc[i]
                pix = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5))
                try: 
                    img_byte_arr = io.BytesIO(pix.tobytes("jpeg"))
                except: 
                    img_byte_arr = io.BytesIO(pix.tobytes("png"))
                img = Image.open(img_byte_arr)
                if img.width > 2000:
                    img.thumbnail((2000, 2000), Image.Resampling.LANCZOS)
                images.append(img)
            
            doc.close()
            gc.collect()
            return {"type": "images", "data": images}
    except Exception as e:
        st.error(f"Erro ao processar arquivo: {str(e)}")
        return None
    return None

def extract_json(text):
    text = re.sub(r'```json|```', '', text).strip()
    try:
        start, end = text.find('{'), text.rfind('}') + 1
        return json.loads(text[start:end]) if start != -1 and end != -1 else json.loads(text)
    except: return None

def auditar_secao_worker(client, secao, d1, d2, nome_doc1, nome_doc2, todas_secoes):
    """Worker otimizado com prompt LITERAL e barreiras de seção"""
    
    eh_visualizacao = any(s in secao.upper() for s in SECOES_VISUALIZACAO)
    
    # Barreiras de parada: TODOS os outros títulos de seção.
    # Isso impede que o texto da Seção 3 vaze para a Seção 1.
    barreiras = [s for s in todas_secoes if s != secao]
    barreiras.extend(["DIZERES LEGAIS", "Anexo B", "Histórico de Alteração"])
    stop_markers_str = "\n".join([f"- {s}" for s in barreiras])

    prompt_text = f"""
    Você é um robô de extração de texto OCR extremamente LITERAL.
    
    SUA TAREFA:
    Extrair o texto da seção "{secao}" e comparar.
    
    REGRAS INEGOCIÁVEIS (LEIA COM ATENÇÃO):
    1. **CÓPIA FIEL:** Copie o texto EXATAMENTE como está no documento. 
       - SE O TEXTO DIZ "deixou de tomar", VOCÊ DEVE ESCREVER "deixou de tomar".
       - É PROIBIDO escrever "se esquecer" ou usar sinônimos.
       - É PROIBIDO resumir.
    
    2. **LIMITES RIGOROSOS:**
       - Comece a copiar IMEDIATAMENTE após o título "{secao}".
       - **PARE IMEDIATAMENTE** se encontrar o título de QUALQUER OUTRA SEÇÃO da lista abaixo.
       - Se você vir "Atenção: Contém..." e logo acima dele não for o final da seção atual, mas sim o início de outra (ex: Seção 3), NÃO inclua esse "Atenção".
    
    ⛔ TÍTULOS DE PARADA (Se encontrar qualquer um destes, PARE DE COPIAR):
    {stop_markers_str}
    
    EXEMPLO DA SEÇÃO 9 (SUPERDOSE):
    Esta seção geralmente tem dois blocos: "Se você tomar..." e "Em caso de uso...". Capture AMBOS até chegar em "DIZERES LEGAIS".
    
    SAÍDA JSON:
    {{
      "titulo": "{secao}",
      "ref": "texto completo e LITERAL do doc de referência...",
      "bel": "texto completo e LITERAL do doc belfar...",
      "status": "CONFORME" (se iguais) ou "DIVERGENTE" (se diferentes)
    }}
    """
    
    messages_content = [{"type": "text", "text": prompt_text}]

    # Limite de texto
    limit = 60000
    for d, nome in [(d1, nome_doc1), (d2, nome_doc2)]:
        if d['type'] == 'text':
            messages_content.append({"type": "text", "text": f"\n--- {nome} ---\n{d['data'][:limit]}"}) 
        else:
            messages_content.append({"type": "text", "text": f"\n--- {nome} (Imagem) ---"})
            for img in d['data'][:2]: 
                b64 = image_to_base64(img)
                messages_content.append({"type": "image_url", "image_url": f"data:image/jpeg;base64,{b64}"})

    max_retries = 2
    for attempt in range(max_retries):
        try:
            chat_response = client.chat.complete(
                model="pixtral-large-latest", 
                messages=[{"role": "user", "content": messages_content}],
                response_format={"type": "json_object"},
                temperature=0.0
            )
            raw_content = chat_response.choices[0].message.content
            dados = extract_json(raw_content)
            
            if dados and 'ref' in dados:
                dados['titulo'] = secao
                
                if not eh_visualizacao:
                    # Normalização básica para comparação (remove espaços extras)
                    t_ref = re.sub(r'\s+', ' ', str(dados.get('ref', '')).strip().lower())
                    t_bel = re.sub(r'\s+', ' ', str(dados.get('bel', '')).strip().lower())
                    
                    # Remove marcações HTML antigas se a IA colocou por engano
                    t_ref = re.sub(r'<[^>]+>', '', t_ref)
                    t_bel = re.sub(r'<[^>]+>', '', t_bel)

                    if t_ref == t_bel:
                        dados['status'] = 'CONFORME'
                        # Remove marcações visuais se estiver conforme
                        dados['ref'] = re.sub(r'<mark[^>]*>|</mark>', '', dados.get('ref', ''))
                        dados['bel'] = re.sub(r'<mark[^>]*>|</mark>', '', dados.get('bel', ''))
                    else:
                        dados['status'] = 'DIVERGENTE'
                
                if "DIZERES LEGAIS" in secao.upper():
                    dados['status'] = "VISUALIZACAO"

                return dados
                
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            else:
                return {"titulo": secao, "ref": f"Erro: {str(e)}", "bel": "Erro", "status": "ERRO"}
    
    return {"titulo": secao, "ref": "Falha processamento", "bel": "Falha", "status": "ERRO"}

# ----------------- UI PRINCIPAL -----------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=80)
    st.title("Validador de bulas")
    client = get_mistral_client()
    if client: 
        st.success("✅ Sistema Online")
    else: 
        st.error("❌ Configuração pendente")
    st.divider()
    pagina = st.radio("Navegação:", ["🏠 Início", "💊 Ref x BELFAR", "📋 Conferência MKT", "🎨 Gráfica x Arte"])
    st.divider()
    st.caption("v3.1 - Correção Literal")

if pagina == "🏠 Início":
    st.markdown("""
    <div style="text-align: center; padding: 40px 20px;">
        <h1 style="color: #55a68e; font-size: 3em;">Validador de Bulas</h1>
        <p style="font-size: 1.2em; color: #7f8c8d;">Auditoria Inteligente e Precisa</p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("""
        <div class="stCard">
            <div class="card-title">🎯 Marcação Precisa</div>
            <p class="card-text">
            <mark class="diff">Amarelo</mark>: diferenças de conteúdo<br>
            <mark class="ort">Vermelho</mark>: erros ortográficos<br>
            <mark class="anvisa">Azul</mark>: datas Anvisa
            </p>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown("""
        <div class="stCard">
            <div class="card-title">⚡ Performance</div>
            <p class="card-text">
            Processamento paralelo de seções.<br>
            Cache inteligente.<br>
            Otimização de imagens e OCR.
            </p>
        </div>
        """, unsafe_allow_html=True)

    with col3:
        st.markdown("""
        <div class="stCard">
            <div class="card-title">🔍 Análise Completa</div>
            <p class="card-text">
            Comparação palavra por palavra.<br>
            Detecção automática de erros.<br>
            Extração de dados regulatórios.
            </p>
        </div>
        """, unsafe_allow_html=True)

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
            if tipo_bula == "Profissional": 
                lista_secoes = SECOES_PROFISSIONAL
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
    if st.button("🚀 INICIAR AUDITORIA"):
        if not f1 or not f2:
            st.warning("⚠️ Selecione ambos os arquivos.")
        elif not client:
            st.error("❌ Cliente Mistral não configurado. Verifique a API Key.")
            st.stop()
        else:
            with st.status("🔄 Processando documentos...", expanded=True) as status:
                st.write("📖 Lendo arquivos...")
                
                b1 = f1.getvalue()
                b2 = f2.getvalue()
                d1 = process_file_content(b1, f1.name.lower())
                d2 = process_file_content(b2, f2.name.lower())
                gc.collect()

                if not d1 or not d2:
                    st.error("❌ Erro ao processar arquivos.")
                    st.stop()
                
                st.write("✅ Arquivos carregados")
                st.write(f"🔍 Analisando {len(lista_secoes)} seções...")
                
                resultados_secoes = []
                progress_bar = st.progress(0)
                
                # Processamento paralelo otimizado com timeout individual
                with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                    # Passamos lista_secoes para o worker saber onde parar
                    future_to_secao = {
                        executor.submit(auditar_secao_worker, client, secao, d1, d2, nome_doc1, nome_doc2, lista_secoes): secao 
                        for secao in lista_secoes
                    }
                    
                    completed = 0
                    for future in concurrent.futures.as_completed(future_to_secao, timeout=180):
                        try:
                            data = future.result(timeout=120)  # 120s por seção
                            if data: 
                                resultados_secoes.append(data)
                        except concurrent.futures.TimeoutError:
                            secao = future_to_secao[future]
                            resultados_secoes.append({
                                "titulo": secao,
                                "ref": "⏱️ Tempo limite excedido (seção muito extensa)",
                                "bel": "⏱️ Tempo limite excedido (seção muito extensa)",
                                "status": "TIMEOUT"
                            })
                        except Exception as e:
                            secao = future_to_secao[future]
                            resultados_secoes.append({
                                "titulo": secao,
                                "ref": f"⚠️ Erro: {str(e)[:150]}",
                                "bel": f"⚠️ Erro: {str(e)[:150]}",
                                "status": "ERRO"
                            })
                        
                        completed += 1
                        progress_bar.progress(completed / len(lista_secoes))
                        st.write(f"✓ Seção {completed}/{len(lista_secoes)} concluída")
                
                status.update(label="✅ Análise concluída!", state="complete", expanded=False)
            
            # Ordena resultados
            resultados_secoes.sort(
                key=lambda x: lista_secoes.index(x['titulo']) if x['titulo'] in lista_secoes else 999
            )
            
            # Métricas
            total = len(resultados_secoes)
            conformes = sum(1 for x in resultados_secoes if "CONFORME" in str(x.get('status', '')))
            divergentes = sum(1 for x in resultados_secoes if "DIVERGENTE" in str(x.get('status', '')))
            visuais = sum(1 for x in resultados_secoes if "VISUALIZACAO" in str(x.get('status', '')))
            erros = sum(1 for x in resultados_secoes if "ERRO" in str(x.get('status', '')) or "TIMEOUT" in str(x.get('status', '')))
            
            score = int(((conformes + visuais) / max(total, 1)) * 100)  # Evita divisão por zero
            
            # Extrai datas
            datas_encontradas = []
            for r in resultados_secoes:
                if "DIZERES LEGAIS" in r['titulo']:
                    texto_combinado = str(r.get('ref', '')) + " " + str(r.get('bel', ''))
                    matches = re.findall(r'\d{2}/\d{2}/\d{4}', texto_combinado)
                    for m in matches:
                        if m not in datas_encontradas: 
                            datas_encontradas.append(m)
            
            datas_texto = " | ".join(sorted(set(datas_encontradas))) if datas_encontradas else "N/D"

            # Dashboard de métricas
            m1, m2, m3, m4 = st.columns(4)
            
            # Cor dinâmica baseada no score
            score_color = "🟢" if score >= 90 else "🟡" if score >= 70 else "🔴"
            m1.metric("Conformidade", f"{score_color} {score}%", f"{conformes} seções")
            m2.metric("Divergências", divergentes, delta_color="inverse" if divergentes > 0 else "off")
            m3.metric("Total Seções", total)
            m4.metric("Datas Anvisa", len(datas_encontradas))
            
            # Alerta de erros
            if erros > 0:
                st.warning(f"⚠️ {erros} seção(ões) com erro de processamento. Verifique abaixo.")
            
            if datas_encontradas:
                st.info(f"📅 **Datas encontradas:** {datas_texto}")
            
            st.divider()
            
            # Legenda
            st.markdown("""
            **Legenda de Marcações:** <mark class='diff'>Amarelo</mark> = Diferença de conteúdo | 
            <mark class='ort'>Vermelho</mark> = Erro ortográfico | 
            <mark class='anvisa'>Azul</mark> = Data Anvisa
            """, unsafe_allow_html=True)
            
            st.divider()
            
            # Resultados por seção com ícones dinâmicos
            for sec in resultados_secoes:
                status = sec.get('status', 'N/A')
                titulo = sec.get('titulo', '').upper()
                
                # Ícones e cores por status
                if "CONFORME" in status:
                    icon = "✅"
                    cor_borda = "#28a745"
                elif "DIVERGENTE" in status:
                    icon = "⚠️"
                    cor_borda = "#ffc107"
                elif "VISUALIZACAO" in status:
                    icon = "👁️"
                    cor_borda = "#17a2b8"
                elif "TIMEOUT" in status:
                    icon = "⏱️"
                    cor_borda = "#fd7e14"
                elif "ERRO" in status:
                    icon = "❌"
                    cor_borda = "#dc3545"
                else:
                    icon = "❓"
                    cor_borda = "#6c757d"
                
                # Expande automaticamente apenas divergências e erros
                expandir = "DIVERGENTE" in status or "ERRO" in status or "TIMEOUT" in status
                
                with st.expander(f"{icon} {titulo} — {status}", expanded=expandir):
                    cA, cB = st.columns(2)
                    with cA:
                        st.markdown(f"**{nome_doc1}**")
                        st.markdown(
                            f"<div class='texto-bula' style='background:#f9f9f9; padding:15px; border-radius:5px; border-left: 4px solid {cor_borda};'>{str(sec.get('ref', 'Texto não extraído'))}</div>", 
                            unsafe_allow_html=True
                        )
                    with cB:
                        st.markdown(f"**{nome_doc2}**")
                        st.markdown(
                            f"<div class='texto-bula' style='background:#fff; border:1px solid #ddd; padding:15px; border-radius:5px; border-left: 4px solid {cor_borda};'>{str(sec.get('bel', 'Texto não extraído'))}</div>", 
                            unsafe_allow_html=True
                        )
            
            # Resumo final com recomendações
            st.divider()
            
            if score >= 95:
                st.success(f"🎉 **Excelente!** {conformes + visuais}/{total} seções conformes. Documentos altamente compatíveis.")
            elif score >= 80:
                st.success(f"✅ **Bom resultado!** {conformes + visuais}/{total} seções conformes. Revise as divergências encontradas.")
            elif score >= 60:
                st.warning(f"⚠️ **Atenção necessária.** {divergentes} divergência(s) encontrada(s). Revisão manual recomendada.")
            else:
                st.error(f"❌ **Revisão crítica necessária.** Múltiplas divergências detectadas. Verifique cada seção cuidadosamente.")
