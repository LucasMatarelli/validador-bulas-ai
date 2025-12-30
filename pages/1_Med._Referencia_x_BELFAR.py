import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
import docx  # Para ler DOCX
import json
import difflib
import re
import unicodedata
from spellchecker import SpellChecker

# ----------------- 1. VISUAL & CSS -----------------
st.set_page_config(page_title="Conferência MKT", page_icon="💊", layout="wide")

st.markdown("""
<style>
    [data-testid="stHeader"] { visibility: hidden; }
    
    .texto-box { 
        font-family: 'Segoe UI', sans-serif;
        font-size: 0.95rem;
        line-height: 1.6;
        color: #212529;
        background-color: #ffffff;
        padding: 20px;
        border-radius: 8px;
        border: 1px solid #ced4da;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        white-space: pre-wrap; 
        text-align: left;
    }
    
    /* DIVERGÊNCIA (Amarelo) - Texto diferente */
    .highlight-yellow { 
        background-color: #fff3cd; color: #856404; 
        padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; font-weight: bold;
    }
    
    /* ERRO PORTUGUÊS (Vermelho) - Identificado pelo Corretor */
    .highlight-red { 
        background-color: #f8d7da; color: #721c24; 
        padding: 2px 4px; border-radius: 4px; border: 1px solid #f5c6cb; 
        text-decoration: underline wavy #dc3545;
        cursor: help;
    }
    
    /* DATA ANVISA (Azul) */
    .highlight-blue { 
        background-color: #d1ecf1; color: #0c5460; 
        padding: 2px 4px; border-radius: 4px; border: 1px solid #bee5eb; font-weight: bold; 
    }
    
    /* Bordas */
    .border-ok { border-left: 6px solid #28a745 !important; }
    .border-warn { border-left: 6px solid #ffc107 !important; } 
    .border-info { border-left: 6px solid #17a2b8 !important; }

    div[data-testid="stMetric"] {
        background-color: #f8f9fa; border: 1px solid #dee2e6; padding: 10px; border-radius: 5px; text-align: center;
    }
</style>
""", unsafe_allow_html=True)

# ----------------- 2. CONFIGURAÇÃO -----------------
MODELO_FIXO = "models/gemini-1.5-flash"

# ----------------- 3. FUNÇÕES AUXILIARES -----------------

def normalizar_para_comparacao(texto):
    """
    Remove sujeira invisível para evitar falsos positivos (Ex: 'As infecções').
    Se isso retornar igual para os dois textos, então visualmente eles são iguais.
    """
    if not texto: return ""
    # Normaliza Unicode (junta acentos)
    texto = unicodedata.normalize('NFC', texto)
    # Remove espaços não separáveis (\xa0), hifens opcionais e zero-width spaces
    texto = texto.replace('\xa0', ' ').replace('\u200b', '').replace('\xad', '')
    # Normaliza espaços múltiplos
    texto = re.sub(r'\s+', ' ', texto)
    return texto.strip()

def verificar_ortografia(texto_html):
    """
    Passa um pente fino no texto para achar erros de português (Vermelho).
    Ignora tags HTML já existentes (<br>, <b>, etc).
    """
    try:
        spell = SpellChecker(language='pt')
        # Regex poderosa: Separa tags HTML (<...>) de palavras reais
        tokens = re.split(r'(<[^>]+>|[^a-zA-ZáàâãéèêíïóôõöúçñÁÀÂÃÉÈÊÍÏÓÔÕÖÚÇÑ]+)', texto_html)
        
        novo_texto = []
        for token in tokens:
            # Se for tag HTML, espaço, pontuação ou palavra muito curta, ignora
            if token.startswith('<') or not token.strip() or len(token) < 3:
                novo_texto.append(token)
                continue
            
            # Verifica se a palavra existe no dicionário
            palavra_limpa = token.strip()
            # Se não estiver no dicionário -> Marca VERMELHO
            if palavra_limpa.lower() not in spell:
                novo_texto.append(f'<span class="highlight-red" title="Possível erro">{token}</span>')
            else:
                novo_texto.append(token)
                
        return "".join(novo_texto)
    except:
        return texto_html # Se der erro no spellchecker, devolve original

def destacar_datas(texto):
    # Detecta frases de aprovação Anvisa e destaca a data em azul
    padrao = r'(Esta\s+bula\s+foi\s+(?:atualizada\s+conforme\s+Bula\s+Padrão\s+)?aprovada\s+pela\s+Anvisa\s+em\s*)(\d{2}/\d{2}/\d{4}|\d{2}/\d{4})'
    def replacer(match):
        return f'{match.group(1)}<span class="highlight-blue">{match.group(2)}</span>'
    return re.sub(padrao, replacer, texto, count=1, flags=re.IGNORECASE | re.DOTALL)

def gerar_diff_html(texto_ref, texto_novo):
    if not texto_ref: texto_ref = ""
    if not texto_novo: texto_novo = ""
    
    # 1. Tira a prova real: Se normalizado for igual, não marque amarelo!
    ref_norm = normalizar_para_comparacao(texto_ref)
    novo_norm = normalizar_para_comparacao(texto_novo)
    
    if ref_norm == novo_norm:
        # Se for igual, só verifica ortografia no novo (Vermelho) e retorna sem divergência
        html_novo = verificar_ortografia(texto_novo.replace('\n', '<br>'))
        return texto_ref.replace('\n', '<br>'), html_novo, False

    # 2. Se for diferente, faz o diff detalhado
    a = texto_ref.splitlines()
    b = texto_novo.splitlines()
    
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    html_output_ref = []
    html_output_novo = []
    eh_divergente = False
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        trecho_a = "\n".join(a[i1:i2])
        trecho_b = "\n".join(b[j1:j2])
        
        if tag == 'equal':
            html_output_ref.append(trecho_a)
            # Verifica ortografia no texto igual
            html_output_novo.append(verificar_ortografia(trecho_b))
        
        elif tag == 'replace':
            # Verifica novamente trecho a trecho se é só sujeira invisível
            if normalizar_para_comparacao(trecho_a) == normalizar_para_comparacao(trecho_b):
                html_output_ref.append(trecho_a)
                html_output_novo.append(verificar_ortografia(trecho_b))
            else:
                # Diferença REAL -> Amarelo
                html_output_ref.append(f'<span class="highlight-yellow">{trecho_a}</span>')
                html_output_novo.append(f'<span class="highlight-yellow">{trecho_b}</span>')
                eh_divergente = True

        elif tag == 'delete':
            html_output_ref.append(f'<span class="highlight-yellow">{trecho_a}</span>')
            eh_divergente = True
            
        elif tag == 'insert':
            html_output_novo.append(f'<span class="highlight-yellow">{trecho_b}</span>')
            eh_divergente = True
            
    final_ref = "\n".join(html_output_ref).replace("\n", "<br>")
    final_novo = "\n".join(html_output_novo).replace("\n", "<br>")
    
    return final_ref, final_novo, eh_divergente

# ----------------- 4. EXTRAÇÃO DE TEXTO -----------------
def extract_text_from_file(uploaded_file):
    try:
        text = ""
        if uploaded_file.name.lower().endswith('.pdf'):
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            for page in doc: 
                blocks = page.get_text("dict", flags=11, sort=True)["blocks"]
                for b in blocks:
                    block_text = ""
                    for l in b.get("lines", []):
                        line_txt = ""
                        for s in l.get("spans", []):
                            content = s["text"]
                            font_props = s["font"].lower()
                            is_bold = (s["flags"] & 16) or "bold" in font_props or "black" in font_props
                            if is_bold:
                                line_txt += f"<b>{content}</b>"
                            else:
                                line_txt += content
                        block_text += line_txt + " " 
                    text += block_text.strip() + "\n\n"
                    
        elif uploaded_file.name.lower().endswith('.docx'):
            doc = docx.Document(uploaded_file)
            for para in doc.paragraphs: 
                para_txt = ""
                for run in para.runs:
                    if run.bold:
                        para_txt += f"<b>{run.text}</b>"
                    else:
                        para_txt += run.text
                text += para_txt + "\n\n"
        return text
    except Exception as e:
        return ""

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

SECOES_SEM_COMPARACAO = ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]

# ----------------- 5. UI PRINCIPAL -----------------
st.title("💊 Med. Referência x BELFAR")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Referência", type=["pdf", "docx"], key="f1")
f2 = c2.file_uploader("📜 Bula BELFAR", type=["pdf", "docx"], key="f2")

if st.button("🚀 Processar Conferência"):
    # Tenta pegar qualquer chave disponível
    key = st.secrets.get("GEMINI_API_KEY") or st.secrets.get("GEMINI_API_KEY2") or st.secrets.get("GEMINI_API_KEY3")

    if not key:
        st.error("Nenhuma chave API encontrada.")
        st.stop()

    if f1 and f2:
        with st.spinner("Conferindo... (Detectando símbolos, ignorando espaços vazios e checando português)..."):
            f1.seek(0); f2.seek(0)
            t_anvisa = extract_text_from_file(f1)
            t_mkt = extract_text_from_file(f2)

            if len(t_anvisa) < 20 or len(t_mkt) < 20:
                st.error("Erro: Arquivo vazio ou ilegível."); st.stop()

            prompt = f"""
            Você é um Extrator de Dados Farmacêuticos Rigoroso.
            
            INPUT TEXTO 1 (REF): 
            {t_anvisa[:150000]}
            
            INPUT TEXTO 2 (MKT): 
            {t_mkt[:150000]}

            SUA MISSÃO:
            1. **DATA DE APROVAÇÃO:** Procure EXATAMENTE por frases como "Esta bula foi aprovada pela Anvisa em (DATA)" ou "Esta bula foi atualizada conforme Bula Padrão aprovada pela Anvisa em (DATA)". Extraia APENAS essa data específica.
            
            2. **CONTEÚDO COMPLETO:** - Extraia TODO o texto entre um título e outro.
               - NÃO PARE no meio. NÃO RESUMA.
            
            3. **FORMATAÇÃO:**
               - MANTENHA as tags <b> e </b> originais.
               - NÃO CORRIJA O PORTUGUÊS. Copie ipsis litteris.

            LISTA DE SEÇÕES ESPERADAS: {SECOES_PACIENTE}

            SAÍDA JSON:
            {{
                "data_anvisa_ref": "dd/mm/aaaa",
                "data_anvisa_mkt": "dd/mm/aaaa",
                "secoes": [
                    {{
                        "titulo": "NOME DA SEÇÃO",
                        "texto_anvisa": "Texto completo com <b> e \\n",
                        "texto_mkt": "Texto completo com <b> e \\n"
                    }}
                ]
            }}
            """
            
            try:
                genai.configure(api_key=key)
                model = genai.GenerativeModel(MODELO_FIXO, generation_config={"response_mime_type": "application/json", "temperature": 0.0})
                response = model.generate_content(prompt)
                
                resultado = json.loads(response.text)
                data_ref = resultado.get("data_anvisa_ref", "Não encontrada")
                data_mkt = resultado.get("data_anvisa_mkt", "Não encontrada")
                dados_secoes = resultado.get("secoes", [])
                
                secoes_finais = []
                divergentes_count = 0

                for item in dados_secoes:
                    titulo = item.get('titulo', '').strip()
                    txt_ref = item.get('texto_anvisa', '').strip()
                    txt_mkt = item.get('texto_mkt', '').strip()
                    
                    titulo_upper = titulo.upper()
                    eh_secao_blindada = any(blindada in titulo_upper for blindada in SECOES_SEM_COMPARACAO)

                    if eh_secao_blindada:
                        status = "CONFORME"
                        if "DIZERES LEGAIS" in titulo_upper:
                            html_mkt = destacar_datas(txt_mkt)
                            html_ref = destacar_datas(txt_ref)
                        else:
                            html_mkt = verificar_ortografia(txt_mkt) # Ainda checa português
                            html_ref = txt_ref
                        
                        # Ajusta quebras de linha para visualização
                        html_mkt = html_mkt.replace('\n', '<br>')
                        html_ref = html_ref.replace('\n', '<br>')
                    
                    else:
                        # AQUI ESTÁ A MÁGICA: Gera diff ignorando "As infecções" falso positivo
                        # e marcando vermelho em erros de português
                        html_ref, html_mkt, teve_diff = gerar_diff_html(txt_ref, txt_mkt)
                        status = "DIVERGENTE" if teve_diff else "CONFORME"
                        if teve_diff: divergentes_count += 1

                    secoes_finais.append({
                        "titulo": titulo,
                        "texto_anvisa": html_ref,
                        "texto_mkt": html_mkt,
                        "status": status
                    })

                st.markdown("### 📊 Resumo da Conferência")
                c1, c2, c3 = st.columns(3)
                c1.metric("Data Anvisa (Ref)", data_ref)
                c2.metric("Data Anvisa (MKT)", data_mkt, delta="Igual" if data_ref == data_mkt else "Diferente")
                c3.metric("Seções", len(secoes_finais))

                sub1, sub2 = st.columns(2)
                sub1.info(f"✅ **Conformes:** {len(secoes_finais) - divergentes_count}")
                if divergentes_count > 0: sub2.warning(f"⚠️ **Divergentes:** {divergentes_count}")
                else: sub2.success("✨ **Divergências:** 0")

                st.divider()

                for item in secoes_finais:
                    status = item['status']
                    titulo = item['titulo']
                    
                    if "DIZERES LEGAIS" in titulo.upper():
                        icon = "⚖️"; css = "border-info"; aberto = True
                    elif any(b in titulo.upper() for b in SECOES_SEM_COMPARACAO):
                        icon = "🔒"; css = "border-ok"; aberto = False
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
                st.error(f"Erro ao processar: {e}")
                # st.code(response.text) # Descomente para debug
    else:
        st.warning("Adicione os arquivos.")
