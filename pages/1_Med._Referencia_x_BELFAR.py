import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
import docx
import json
import difflib
import re
import unicodedata
import time
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
    
    /* DIVERGÊNCIA (Amarelo) - Texto diferente ou faltando */
    .highlight-yellow { 
        background-color: #fff3cd; color: #856404; 
        padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; 
        font-weight: bold;
    }
    
    /* ERRO PORTUGUÊS (Vermelho) - Apenas erros ortográficos REAIS */
    .highlight-red { 
        background-color: #f8d7da; color: #721c24; 
        padding: 0px 2px; border-radius: 4px; border-bottom: 2px solid #dc3545; 
        text-decoration: none;
        font-weight: bold;
    }
    
    .highlight-blue { 
        background-color: #d1ecf1; color: #0c5460; 
        padding: 2px 4px; border-radius: 4px; border: 1px solid #bee5eb; font-weight: bold; 
    }
    
    .border-ok { border-left: 6px solid #28a745 !important; }
    .border-warn { border-left: 6px solid #ffc107 !important; } 
    .border-info { border-left: 6px solid #17a2b8 !important; }

    div[data-testid="stMetric"] {
        background-color: #f8f9fa; border: 1px solid #dee2e6; padding: 10px; border-radius: 5px; text-align: center;
    }
</style>
""", unsafe_allow_html=True)

# ----------------- 2. CONFIGURAÇÃO -----------------
MODELOS_PARA_TENTAR = [
    "models/gemini-2.5-flash", 
    "models/gemini-2.0-flash", 
    "models/gemini-1.5-flash", 
    "gemini-1.5-flash"
]

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

SECOES_SEM_COMPARACAO = ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]

# ----------------- 3. FUNÇÕES DE LIMPEZA E COMPARAÇÃO -----------------

def normalizar_para_comparacao(texto):
    """
    Normalização para verificar se o conteúdo é idêntico.
    """
    if not texto: return ""
    texto = re.sub(r'<[^>]+>', '', texto) # Remove HTML
    texto = unicodedata.normalize('NFKD', texto) # Normaliza acentos
    texto = ''.join([c for c in texto if not unicodedata.combining(c)])
    texto = re.sub(r'[^a-zA-Z0-9]', '', texto) # Mantem letras e números apenas
    texto = texto.lower()
    return texto

def verificar_ortografia(texto):
    """
    Marca de VERMELHO apenas erros ÓBVIOS (ex: 'gorreia' x 'gonorreia').
    NÃO marca termos médicos, plurais complexos ou palavras técnicas.
    """
    try:
        spell = SpellChecker(language='pt')
        
        # LISTA MANUAL DE TERMOS DA BULA QUE NÃO SÃO ERROS
        termos_validos = {
            # Unidades e Siglas
            'mg', 'ml', 'mcg', 'ui', 'g', 'kg', 'l', 'dl', 'mmhg', 'bpm', 'kcal', 
            'crf', 'crm', 'anvisa', 'lote', 'val', 'fab', 'sac', 'cnpj', 'cep', 'dr', 'dra',
            # Palavras da imagem que estavam marcando erro
            'predisponentes', 'congenita', 'congênita', 'abdomen', 'abdômen', 
            'sistemicos', 'sistêmicos', 'historico', 'histórico', 'aneurisma', 
            'aortico', 'aórtico', 'aortica', 'aórtica', 'dissecção', 'disseccao',
            'valvar', 'valvula', 'válvula', 'regurgitação', 'mitral', 'endocardite',
            'marfan', 'ehlers-danlos', 'turner', 'sjogren', 'takayasu', 'behcet', 
            'reumatoide', 'artrite', 'corticosteroides', 'fluorquinolonas',
            'hipersensibilidade', 'arritmia', 'protuberância', 'protuberancia',
            'posologia', 'superdose', 'blister', 'farmacocinetica', 'biodisponibilidade'
        }
        
        # Carrega palavras extras
        spell.word_frequency.load_words(termos_validos)
        
        partes = re.split(r'(<[^>]+>|\s+|[().,:;!?])', texto) 
        resultado = []
        
        for parte in partes:
            # Se for tag HTML, espaço ou pontuação, mantém igual
            if parte.startswith('<') or parte.isspace() or not any(c.isalpha() for c in parte):
                resultado.append(parte)
                continue
            
            # Limpa para verificar a palavra (remove aspas, traços soltos, etc)
            palavra_limpa = re.sub(r'[^a-zA-ZáàâãéèêíïóôõöúçñÁÀÂÃÉÈÊÍÏÓÔÕÖÚÇÑ-]', '', parte)
            
            if not palavra_limpa or len(palavra_limpa) <= 2:
                resultado.append(parte)
                continue
            
            # Se tiver número no meio (ex: 50mg), ignora
            if any(c.isdigit() for c in parte):
                resultado.append(parte)
                continue

            # Se começa com maiúscula (Título ou Início de frase), ignoramos para evitar falsos positivos
            if palavra_limpa[0].isupper():
                resultado.append(parte)
                continue
            
            palavra_lower = palavra_limpa.lower()
            
            # 1. Verifica se está no dicionário ou na lista branca
            if palavra_lower in spell or palavra_lower in termos_validos:
                resultado.append(parte)
            else:
                # 2. SE NÃO ESTIVER NO DICIONÁRIO:
                # Assume que é um termo técnico válido, A MENOS QUE pareça muito com uma palavra comum.
                
                candidatos = spell.candidates(palavra_lower)
                if candidatos:
                    sugestao = spell.correction(palavra_lower)
                    
                    # Distância de Levenshtein manual simplificada
                    diff_len = abs(len(sugestao) - len(palavra_lower))
                    
                    # SÓ MARCA SE:
                    # 1. A sugestão for muito próxima (erro de digitação óbvio)
                    # 2. E a palavra original não parecer plural ou termo médico complexo
                    if diff_len <= 1 and sugestao != palavra_lower:
                        # Checa quantos caracteres mudam
                        diff_chars = sum(1 for a, b in zip(sugestao, palavra_lower) if a != b)
                        
                        # Se mudou apenas 1 letra (ex: gorreia -> gonorreia), marca.
                        # Se mudou mais, assume que é outra palavra que o dicionário não conhece.
                        if diff_chars <= 1:
                             resultado.append(f'<span class="highlight-red" title="Sugestão: {sugestao}">{parte}</span>')
                        else:
                            resultado.append(parte)
                    else:
                        resultado.append(parte) # Assume correto (termo técnico)
                else:
                    resultado.append(parte) # Sem sugestão = termo técnico raro

        return ''.join(resultado)
    except:
        return texto

def destacar_datas(texto):
    padrao = r'(Esta\s+bula\s+foi\s+(?:atualizada\s+conforme\s+Bula\s+Padrão\s+)?aprovada\s+pela\s+Anvisa\s+em\s*)(\d{2}/\d{2}/\d{4}|\d{2}/\d{4})'
    def replacer(match):
        return f'{match.group(1)}<span class="highlight-blue">{match.group(2)}</span>'
    return re.sub(padrao, replacer, texto, count=1, flags=re.IGNORECASE | re.DOTALL)

def diff_palavra_a_palavra(texto_ref, texto_novo):
    """
    Compara duas strings palavra por palavra e retorna HTML com amarelo SÓ nas palavras diferentes.
    """
    # Separa por palavras 
    palavras_ref = texto_ref.split()
    palavras_novo = texto_novo.split()
    
    matcher = difflib.SequenceMatcher(None, palavras_ref, palavras_novo)
    
    html_ref_list = []
    html_novo_list = []
    tem_diff = False
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            # Palavras iguais: sem destaque
            texto_igual = " ".join(palavras_ref[i1:i2])
            html_ref_list.append(texto_igual)
            html_novo_list.append(texto_igual) 
            
        elif tag == 'replace':
            # Palavras mudaram: destaca amarelo
            trecho_antigo = " ".join(palavras_ref[i1:i2])
            trecho_novo = " ".join(palavras_novo[j1:j2])
            
            html_ref_list.append(f'<span class="highlight-yellow">{trecho_antigo}</span>')
            html_novo_list.append(f'<span class="highlight-yellow">{trecho_novo}</span>')
            tem_diff = True
            
        elif tag == 'delete':
            # Palavra sumiu no NOVO: destaca amarelo no REF
            trecho_deletado = " ".join(palavras_ref[i1:i2])
            html_ref_list.append(f'<span class="highlight-yellow">{trecho_deletado}</span>')
            tem_diff = True
            
        elif tag == 'insert':
            # Palavra nova no NOVO: destaca amarelo no NOVO
            trecho_inserido = " ".join(palavras_novo[j1:j2])
            html_novo_list.append(f'<span class="highlight-yellow">{trecho_inserido}</span>')
            tem_diff = True
            
    return " ".join(html_ref_list), " ".join(html_novo_list), tem_diff

def gerar_diff_html(texto_ref, texto_novo):
    """
    Gera o HTML comparativo. Se as linhas forem diferentes, ativa a comparação palavra por palavra.
    """
    if not texto_ref: texto_ref = ""
    if not texto_novo: texto_novo = ""
    
    if normalizar_para_comparacao(texto_ref) == normalizar_para_comparacao(texto_novo):
        return texto_ref.replace('\n', '<br>'), verificar_ortografia(texto_novo.replace('\n', '<br>')), False

    ref_limpo = re.sub(r'<[^>]+>', '', texto_ref)
    novo_limpo = re.sub(r'<[^>]+>', '', texto_novo)
    
    linhas_ref = ref_limpo.split('\n')
    linhas_novo = novo_limpo.split('\n')
    
    matcher = difflib.SequenceMatcher(None, linhas_ref, linhas_novo)
    
    html_ref_partes = []
    html_novo_partes = []
    tem_divergencia = False
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            for linha in linhas_ref[i1:i2]:
                html_ref_partes.append(linha)
            for linha in linhas_novo[j1:j2]:
                html_novo_partes.append(verificar_ortografia(linha))
                
        elif tag == 'replace':
            t_ref_bloco = "\n".join(linhas_ref[i1:i2])
            t_novo_bloco = "\n".join(linhas_novo[j1:j2])
            
            ref_diff_html, novo_diff_html, diff_bool = diff_palavra_a_palavra(t_ref_bloco, t_novo_bloco)
            
            if diff_bool: tem_divergencia = True
            html_ref_partes.append(ref_diff_html)
            html_novo_partes.append(verificar_ortografia(novo_diff_html))

        elif tag == 'delete':
            bloco = "\n".join(linhas_ref[i1:i2])
            html_ref_partes.append(f'<span class="highlight-yellow">{bloco}</span>')
            tem_divergencia = True
            
        elif tag == 'insert':
            bloco = "\n".join(linhas_novo[j1:j2])
            html_novo_partes.append(f'<span class="highlight-yellow">{verificar_ortografia(bloco)}</span>')
            tem_divergencia = True

    return '<br>'.join(html_ref_partes), '<br>'.join(html_novo_partes), tem_divergencia

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
                            if is_bold: line_txt += f"<b>{content}</b>"
                            else: line_txt += content
                        block_text += line_txt + " " 
                    text += block_text.strip() + "\n\n"
        elif uploaded_file.name.lower().endswith('.docx'):
            doc = docx.Document(uploaded_file)
            for para in doc.paragraphs: 
                para_txt = ""
                for run in para.runs:
                    if run.bold: para_txt += f"<b>{run.text}</b>"
                    else: para_txt += run.text
                text += para_txt + "\n\n"
        return text
    except: return ""

# ----------------- 5. UI PRINCIPAL -----------------
st.title("💊 Med. Referência x BELFAR")

tipo_bula = st.radio(
    "Escolha o Tipo de Bula:",
    ("Paciente", "Profissional"),
    horizontal=True
)

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Referência", type=["pdf", "docx"], key="f1")
f2 = c2.file_uploader("📜 Bula BELFAR", type=["pdf", "docx"], key="f2")

if st.button("🚀 Processar Conferência"):
    
    # 1. BLINDAGEM DE CHAVES (Tenta as 3 chaves)
    keys_raw = [
        st.secrets.get("GEMINI_API_KEY"),
        st.secrets.get("GEMINI_API_KEY2"),
        st.secrets.get("GEMINI_API_KEY3")
    ]
    keys_validas = [k for k in keys_raw if k]

    if not keys_validas:
        st.error("Erro Crítico: Nenhuma API Key encontrada.")
        st.stop()

    if f1 and f2:
        secoes_alvo = SECOES_PACIENTE if tipo_bula == "Paciente" else SECOES_PROFISSIONAL

        with st.spinner("Lendo arquivos e conectando à IA..."):
            f1.seek(0); f2.seek(0)
            t_anvisa = extract_text_from_file(f1)
            t_mkt = extract_text_from_file(f2)

            if len(t_anvisa) < 20 or len(t_mkt) < 20:
                st.error("Arquivo vazio ou ilegível."); st.stop()

            prompt = f"""
            Você é um Extrator de Dados Farmacêuticos Rigoroso.
            
            INPUT TEXTO 1 (REF): {t_anvisa[:150000]}
            INPUT TEXTO 2 (MKT): {t_mkt[:150000]}

            SUA MISSÃO:
            1. Extrair DATA DE APROVAÇÃO (frase exata "aprovada pela Anvisa em...").
            2. Extrair TODO o conteúdo de cada seção. NÃO RESUMA.
            3. Manter formatação <b> e NÃO corrigir português.

            LISTA DE SEÇÕES ESPERADAS: {secoes_alvo}

            SAÍDA JSON:
            {{
                "data_anvisa_ref": "dd/mm/aaaa",
                "data_anvisa_mkt": "dd/mm/aaaa",
                "secoes": [
                    {{
                        "titulo": "NOME DA SEÇÃO",
                        "texto_anvisa": "...",
                        "texto_mkt": "..."
                    }}
                ]
            }}
            """
            
            # --- TENTATIVA MULTI-CHAVE E MULTI-MODELO ---
            response = None
            sucesso = False
            log_erros = []

            for idx_key, key in enumerate(keys_validas):
                if sucesso: break
                
                genai.configure(api_key=key)
                
                for modelo in MODELOS_PARA_TENTAR:
                    try:
                        model = genai.GenerativeModel(
                            modelo, 
                            generation_config={"response_mime_type": "application/json", "temperature": 0.0}
                        )
                        response = model.generate_content(prompt)
                        sucesso = True
                        break 
                    except Exception as e:
                        log_erros.append(f"Key {idx_key+1} | {modelo}: {str(e)}")
                        time.sleep(0.5)
                        continue

            if not sucesso:
                st.error("❌ Falha Total. Detalhes:")
                st.code("\n".join(log_erros))
                st.stop()
            
            # --- RESULTADO E COMPARAÇÃO ---
            try:
                resultado = json.loads(response.text)
                data_ref = resultado.get("data_anvisa_ref", "-")
                data_mkt = resultado.get("data_anvisa_mkt", "-")
                dados_secoes = resultado.get("secoes", [])
                
                secoes_finais = []
                divs_count = 0

                for item in dados_secoes:
                    titulo = item.get('titulo', '').strip()
                    txt_ref = item.get('texto_anvisa', '').strip()
                    txt_mkt = item.get('texto_mkt', '').strip()
                    
                    titulo_upper = titulo.upper()
                    eh_blindada = any(b in titulo_upper for b in SECOES_SEM_COMPARACAO)

                    if eh_blindada:
                        status = "CONFORME"
                        if "DIZERES LEGAIS" in titulo_upper:
                            html_mkt = destacar_datas(txt_mkt)
                            html_ref = destacar_datas(txt_ref)
                        else:
                            html_mkt = verificar_ortografia(txt_mkt)
                            html_ref = txt_ref
                        html_mkt = html_mkt.replace('\n', '<br>')
                        html_ref = html_ref.replace('\n', '<br>')
                    else:
                        html_ref, html_mkt, teve_diff = gerar_diff_html(txt_ref, txt_mkt)
                        status = "DIVERGENTE" if teve_diff else "CONFORME"
                        if teve_diff: divs_count += 1

                    secoes_finais.append({
                        "titulo": titulo, "texto_anvisa": html_ref, "texto_mkt": html_mkt, "status": status
                    })

                st.markdown("### 📊 Resumo")
                c1, c2, c3 = st.columns(3)
                c1.metric("Data Ref", data_ref)
                c2.metric("Data MKT", data_mkt, delta="Igual" if data_ref == data_mkt else "Diferente")
                c3.metric("Seções", len(secoes_finais))

                sub1, sub2 = st.columns(2)
                sub1.info(f"✅ Conformes: {len(secoes_finais) - divs_count}")
                if divs_count > 0: sub2.warning(f"⚠️ Divergentes: {divs_count}")
                else: sub2.success("✨ Divergências: 0")

                st.divider()

                for item in secoes_finais:
                    status = item['status']
                    titulo = item['titulo']
                    
                    if "DIZERES LEGAIS" in titulo.upper(): icon, css, aberto = "⚖️", "border-info", True
                    elif any(b in titulo.upper() for b in SECOES_SEM_COMPARACAO): icon, css, aberto = "🔒", "border-ok", False
                    elif status == "CONFORME": icon, css, aberto = "✅", "border-ok", False
                    else: icon, css, aberto = "⚠️", "border-warn", True

                    with st.expander(f"{icon} {titulo}", expanded=aberto):
                        ce, cd = st.columns(2)
                        with ce:
                            st.caption("Referência")
                            st.markdown(f'<div class="texto-box {css}">{item["texto_anvisa"]}</div>', unsafe_allow_html=True)
                        with cd:
                            st.caption("Validado")
                            st.markdown(f'<div class="texto-box {css}">{item["texto_mkt"]}</div>', unsafe_allow_html=True)

            except Exception as e:
                st.error(f"Erro ao processar JSON: {e}")
                st.code(response.text)
    else:
        st.warning("Adicione os arquivos.")
