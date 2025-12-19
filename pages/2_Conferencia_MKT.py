import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
import docx  # Para ler DOCX
import json
import difflib # Biblioteca matemática
import re
import unicodedata

# ----------------- 1. VISUAL & CSS -----------------
st.set_page_config(page_title="MKT Final", page_icon="📢", layout="wide")

st.markdown("""
<style>
    /* --- ESCONDER MENU SUPERIOR (CONFORME SOLICITADO) --- */
    [data-testid="stHeader"] {
        visibility: hidden;
    }

    .texto-box { 
        font-family: 'Segoe UI', sans-serif;
        font-size: 0.95rem;
        line-height: 1.6;
        color: #333;
        background-color: #ffffff;
        padding: 18px;
        border-radius: 8px;
        border: 1px solid #e0e0e0;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        white-space: pre-wrap; 
        text-align: justify;
    }
    
    /* Highlight Amarelo (Apenas diferenças reais) */
    .highlight-yellow { background-color: #fff9c4; color: #000; padding: 2px 0; border: 1px solid #fbc02d; font-weight: bold; }
    .highlight-blue { background-color: #bbdefb; color: #0d47a1; padding: 2px 4px; font-weight: bold; }
    
    .border-ok { border-left: 6px solid #4caf50 !important; }
    .border-warn { border-left: 6px solid #ff9800 !important; } 
    .border-info { border-left: 6px solid #2196f3 !important; }

    div[data-testid="stMetric"] {
        background-color: #f8f9fa;
        border: 1px solid #dee2e6;
        padding: 10px;
        border-radius: 5px;
        text-align: center;
    }
</style>
""", unsafe_allow_html=True)

# ----------------- 2. CONFIGURAÇÃO MODELO -----------------
MODELO_FIXO = "models/gemini-flash-latest"

# ----------------- 3. FUNÇÃO DE COMPARAÇÃO INTELIGENTE -----------------
def normalizar_para_comparacao(texto):
    """Remove caracteres invisíveis e padroniza o texto para evitar falso erro."""
    if not texto: return ""
    # Normaliza unicode (ex: ã vira ã padrão)
    texto = unicodedata.normalize('NFKD', texto)
    # Remove caracteres de controle estranhos
    texto = "".join([c for c in texto if not unicodedata.combining(c)])
    return texto

def gerar_diff_html(texto_ref, texto_novo):
    """
    Compara palavra por palavra com autojunk=False para não se perder.
    """
    if not texto_ref: texto_ref = ""
    if not texto_novo: texto_novo = ""

    # Normaliza antes de quebrar
    ref_norm = normalizar_para_comparacao(texto_ref)
    novo_norm = normalizar_para_comparacao(texto_novo)

    # Quebra em palavras (split remove todos os espaços extras e quebras de linha)
    a = ref_norm.split()
    b = novo_norm.split()
    
    # autojunk=False É O SEGREDO para ele não ignorar palavras comuns e não marcar tudo amarelo
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    
    html_output = []
    eh_divergente = False
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        # Reconstrói o texto usando as palavras da lista 'b' (novo)
        trecho_novo = " ".join(b[j1:j2])
        
        if tag == 'equal':
            html_output.append(trecho_novo)
        elif tag == 'replace':
            # Diferença real
            html_output.append(f'<span class="highlight-yellow">{trecho_novo}</span>')
            eh_divergente = True
        elif tag == 'insert':
            # Texto novo adicionado
            html_output.append(f'<span class="highlight-yellow">{trecho_novo}</span>')
            eh_divergente = True
        elif tag == 'delete':
            # Texto deletado (não mostramos para manter o visual limpo, mas conta como erro)
            eh_divergente = True 
            
    return " ".join(html_output), eh_divergente

# ----------------- 4. EXTRAÇÃO DE TEXTO -----------------
def extract_text_from_file(uploaded_file):
    try:
        text = ""
        if uploaded_file.name.lower().endswith('.pdf'):
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            for page in doc: 
                text += page.get_text("text") + "\n"
        elif uploaded_file.name.lower().endswith('.docx'):
            doc = docx.Document(uploaded_file)
            for para in doc.paragraphs: 
                text += para.text + "\n"
        return text
    except: return ""

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

# ----------------- 5. UI PRINCIPAL -----------------
st.title("📢 Conferência MKT (Relatório Estruturado)")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Anvisa (Referência)", type=["pdf", "docx"], key="f1")
f2 = c2.file_uploader("🎨 Arte MKT (Para Validar)", type=["pdf", "docx"], key="f2")

if st.button("🚀 Processar Conferência"):
    
    keys_disponiveis = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2")]
    keys_validas = [k for k in keys_disponiveis if k]

    if not keys_validas:
        st.error("Nenhuma chave API encontrada.")
        st.stop()

    if f1 and f2:
        with st.spinner("Extraindo textos e comparando..."):
            f1.seek(0); f2.seek(0)
            t_anvisa = extract_text_from_file(f1)
            t_mkt = extract_text_from_file(f2)

            if len(t_anvisa) < 50 or len(t_mkt) < 50:
                st.error("Erro: Arquivo vazio ou ilegível."); st.stop()

            # PROMPT DE EXTRAÇÃO PURA (SEM ANÁLISE)
            prompt = f"""
            Você é um Extrator de Dados Literais.
            
            INPUT:
            TEXTO 1 (REF): {t_anvisa[:100000]}
            TEXTO 2 (MKT): {t_mkt[:100000]}

            SUA MISSÃO:
            1. Localize as seções da lista abaixo nos dois textos.
            2. Extraia o conteúdo LIMPO. Junte linhas quebradas para formar frases contínuas.
            3. **IMPORTANTE:** Copie o texto fielmente. Não corrija nada.
            4. **NÃO COMPARE:** Apenas me entregue o texto extraído de cada lado.
            
            LISTA DE SEÇÕES: {SECOES_PACIENTE}

            SAÍDA JSON:
            {{
                "data_anvisa_ref": "dd/mm/aaaa",
                "data_anvisa_mkt": "dd/mm/aaaa",
                "secoes": [
                    {{
                        "titulo": "NOME DA SEÇÃO",
                        "texto_anvisa": "Conteúdo extraído da referência",
                        "texto_mkt": "Conteúdo extraído do mkt"
                    }}
                ]
            }}
            """
            
            response = None
            ultimo_erro = ""

            for i, api_key in enumerate(keys_validas):
                try:
                    genai.configure(api_key=api_key)
                    model = genai.GenerativeModel(MODELO_FIXO, generation_config={"response_mime_type": "application/json", "temperature": 0.0})
                    response = model.generate_content(prompt, request_options={'retry': None})
                    break 
                except Exception as e:
                    ultimo_erro = str(e)
                    if i < len(keys_validas) - 1: continue
                    else: st.error(f"Erro Fatal: {ultimo_erro}"); st.stop()

            if response:
                try:
                    resultado = json.loads(response.text)
                    data_ref = resultado.get("data_anvisa_ref", "-")
                    data_mkt = resultado.get("data_anvisa_mkt", "-")
                    dados_secoes = resultado.get("secoes", [])

                    secoes_finais = []
                    divergentes_count = 0

                    for item in dados_secoes:
                        titulo = item.get('titulo', '')
                        txt_ref = item.get('texto_anvisa', '').strip()
                        txt_mkt = item.get('texto_mkt', '').strip()
                        
                        # Marca Data em Azul nos Dizeres Legais
                        if "DIZERES LEGAIS" in titulo.upper():
                            padrao_data = r"(\d{2}/\d{2}/\d{4})"
                            txt_ref = re.sub(padrao_data, r'<span class="highlight-blue">\1</span>', txt_ref)
                            txt_mkt = re.sub(padrao_data, r'<span class="highlight-blue">\1</span>', txt_mkt)

                        # Seções BLINDADAS
                        if titulo in ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]:
                            status = "CONFORME"
                            html_mkt = txt_mkt 
                        else:
                            # Comparação Matemática com Autojunk=False
                            html_mkt, teve_diff = gerar_diff_html(txt_ref, txt_mkt)
                            if teve_diff:
                                status = "DIVERGENTE"
                                divergentes_count += 1
                            else:
                                status = "CONFORME"
                        
                        secoes_finais.append({
                            "titulo": titulo,
                            "texto_anvisa": txt_ref,
                            "texto_mkt": html_mkt,
                            "status": status
                        })

                    # --- EXIBIÇÃO ---
                    st.markdown("### 📊 Resumo da Conferência")
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Ref.", data_ref)
                    c2.metric("MKT", data_mkt, delta="Igual" if data_ref == data_mkt else "Diferente")
                    c3.metric("Seções", len(secoes_finais))

                    sub1, sub2 = st.columns(2)
                    sub1.info(f"✅ **Conformes:** {len(secoes_finais) - divergentes_count}")
                    if divergentes_count > 0:
                        sub2.warning(f"⚠️ **Divergentes:** {divergentes_count}")
                    else:
                        sub2.success("✨ **Divergências:** 0")

                    st.divider()

                    for item in secoes_finais:
                        status = item['status']
                        titulo = item['titulo']
                        
                        if "DIZERES LEGAIS" in titulo.upper():
                            icon = "⚖️"; css = "border-info"; aberto = True
                        elif status == "CONFORME":
                            icon = "✅"; css = "border-ok"; aberto = False
                        else:
                            icon = "⚠️"; css = "border-warn"; aberto = True

                        with st.expander(f"{icon} {titulo}", expanded=aberto):
                            col_esq, col_dir = st.columns(2)
                            with col_esq:
                                st.caption("📜 Referência")
                                st.markdown(f'<div class="texto-box {css}">{item["texto_anvisa"]}</div>', unsafe_allow_html=True)
                            with col_dir:
                                st.caption("🎨 Validado")
                                st.markdown(f'<div class="texto-box {css}">{item["texto_mkt"]}</div>', unsafe_allow_html=True)

                except Exception as e:
                    st.error(f"Erro ao processar JSON: {e}")
    else:
        st.warning("Adicione os arquivos.")
