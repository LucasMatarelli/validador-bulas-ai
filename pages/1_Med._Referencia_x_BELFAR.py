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
        line-height: 1.7; /* Mais espaçamento entre linhas */
        color: #212529;
        background-color: #ffffff;
        padding: 25px;
        border-radius: 8px;
        border: 1px solid #ced4da;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        text-align: left;
    }
    
    /* DIVERGÊNCIA (Amarelo) */
    .highlight-yellow { 
        background-color: #fff3cd; color: #856404; 
        padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; 
        font-weight: bold;
    }
    
    /* ERRO PORTUGUÊS (Vermelho) - Estilo mais sutil */
    .highlight-red { 
        background-color: #f8d7da; color: #721c24; 
        border-bottom: 2px solid #dc3545; 
        font-weight: bold;
        cursor: help;
    }
    
    .highlight-blue { 
        background-color: #d1ecf1; color: #0c5460; 
        padding: 2px 4px; border-radius: 4px; border: 1px solid #bee5eb; font-weight: bold; 
    }
    
    /* ESTILO PARA TÓPICOS/LISTAS */
    .topico-item {
        display: block;
        margin-left: 20px;
        margin-bottom: 4px;
        text-indent: -15px; /* Para o marcador ficar alinhado */
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

# ----------------- 3. FUNÇÕES INTELIGENTES -----------------

def normalizar_para_comparacao(texto):
    if not texto: return ""
    texto = re.sub(r'<[^>]+>', '', texto) 
    texto = unicodedata.normalize('NFKD', texto) 
    texto = ''.join([c for c in texto if not unicodedata.combining(c)])
    texto = re.sub(r'[^a-zA-Z0-9]', '', texto) 
    texto = texto.lower()
    return texto

def verificar_ortografia_inteligente(texto):
    """
    Algoritmo "Presunção de Inocência":
    Só marca erro se a palavra for MUITO parecida com uma palavra comum do dicionário (typo óbvio).
    Se for uma palavra desconhecida mas muito diferente das sugestões, assume que é termo técnico correto.
    """
    try:
        spell = SpellChecker(language='pt')
        
        # Adiciona termos médicos ultra comuns que o spellchecker padrão pode não ter
        whitelist_basica = {
            'mg', 'ml', 'mcg', 'ui', 'g', 'kg', 'crf', 'crm', 'anvisa', 'lote', 'val', 'fab', 'sac', 'cnpj', 
            'cep', 'dr', 'dra', 'vp', 'vps', 'bula', 'paciente', 'profissional', 'túbulos', 'tubulos',
            'queimação', 'queimacao', 'uréia', 'ureia', 'sistêmicos', 'sistemicos', 'predisponentes'
        }
        spell.word_frequency.load_words(whitelist_basica)

        # Regex para separar palavras mantendo a estrutura (pontuação, tags, espaços)
        # O split inclui hífens para tratar palavras compostas separadamente depois
        tokens = re.split(r'(<[^>]+>|\s+|[().,:;!?/])', texto)
        
        resultado = []
        
        for token in tokens:
            # Ignora tags, espaços, pontuação pura e tokens vazios
            if not token.strip() or token.startswith('<') or not any(c.isalpha() for c in token):
                resultado.append(token)
                continue
            
            # Limpeza básica da palavra (tira símbolos extras mas mantém acentos)
            palavra_limpa = re.sub(r'[^a-zA-ZáàâãéèêíïóôõöúçñÁÀÂÃÉÈÊÍÏÓÔÕÖÚÇÑ-]', '', token)
            
            # Se for palavra composta (ex: chama-se), verifica as partes
            if '-' in palavra_limpa:
                partes_hifen = palavra_limpa.split('-')
                token_reconstruido = []
                for idx, parte in enumerate(partes_hifen):
                    if validar_palavra(parte, spell, whitelist_basica):
                        token_reconstruido.append(parte)
                    else:
                        sugestao = obter_sugestao_segura(parte, spell)
                        if sugestao:
                            token_reconstruido.append(f'<span class="highlight-red" title="Sugestão: {sugestao}">{parte}</span>')
                        else:
                            token_reconstruido.append(parte)
                resultado.append("-".join(token_reconstruido))
                continue

            # Palavra normal
            if validar_palavra(palavra_limpa, spell, whitelist_basica):
                resultado.append(token)
            else:
                sugestao = obter_sugestao_segura(palavra_limpa, spell)
                if sugestao:
                    # Se achou uma correção óbvia, marca
                    resultado.append(f'<span class="highlight-red" title="Sugestão: {sugestao}">{token}</span>')
                else:
                    # Se não achou correção óbvia, ASSUME QUE ESTÁ CERTO (técnico)
                    resultado.append(token)
                    
        return "".join(resultado)
    except:
        return texto

def validar_palavra(palavra, spell, whitelist):
    """Retorna True se a palavra parece correta."""
    p_lower = palavra.lower()
    
    # 1. Está no dicionário ou whitelist?
    if p_lower in spell or p_lower in whitelist: return True
    
    # 2. É número misturado? (50mg)
    if any(c.isdigit() for c in palavra): return True
    
    # 3. É maiúscula inicial (provável nome próprio ou início de frase)?
    # Para ser conservador, não marcamos erro em palavras com maiúscula, a menos que tenhamos certeza.
    if palavra[0].isupper(): return True
    
    # 4. Checagem de plural simples (se remover o 's' e existir, tá valendo)
    if p_lower.endswith('s') and p_lower[:-1] in spell: return True
    
    return False

def obter_sugestao_segura(palavra, spell):
    """
    Só retorna sugestão se for um erro MUITO provável (distância pequena).
    Se a sugestão for muito diferente, retorna None (significa: não marque erro).
    """
    p_lower = palavra.lower()
    candidatos = spell.candidates(p_lower)
    
    if not candidatos: return None
    
    sugestao = spell.correction(p_lower)
    if not sugestao: return None
    
    # Cálculo de similaridade
    # Se a palavra tem tamanho > 4 e a diferença de tamanho pra sugestão é pequena
    len_orig = len(p_lower)
    len_sug = len(sugestao)
    
    # Se tamanhos muito diferentes, provavelmente não é a mesma palavra
    if abs(len_orig - len_sug) > 2: return None
    
    # Conta caracteres diferentes
    diff_chars = sum(1 for a, b in zip(p_lower, sugestao) if a != b) + abs(len_orig - len_sug)
    
    # LÓGICA RÍGIDA: Só marca erro se mudar no máximo 1 ou 2 letras.
    # Ex: "dissecção" (ñ existe) -> sugestão "dissecado" (muda muito) -> IGNORA (não marca erro)
    # Ex: "gorreia" -> sugestão "gonorreia" (muda 2 letras, fonética igual) -> MARCA ERRO
    
    limite_tolerancia = 1 if len_orig < 5 else 2
    
    if diff_chars <= limite_tolerancia:
        return sugestao
    
    return None

def melhorar_visual_topicos(texto_html):
    """
    Transforma marcadores de texto (-, •, *) em visual HTML bonito.
    """
    # Quebra em linhas considerando <br> ou \n
    linhas = re.split(r'(<br>|\n)', texto_html)
    novo_texto = []
    
    for linha in linhas:
        # Padrão: Começa com -, • ou * seguido de espaço, ou apenas o símbolo
        # O regex procura marcadores no início da parte de texto visível
        if re.search(r'^\s*[-•*]\s+', re.sub(r'<[^>]+>', '', linha).strip()):
            # Envolve em uma div com padding
            linha_limpa = re.sub(r'^\s*[-•*]\s+', '', linha) # Remove o marcador texto
            # Adiciona o marcador visual CSS
            novo_texto.append(f'<div class="topico-item">• {linha_limpa}</div>')
        else:
            novo_texto.append(linha)
            
    return "".join(novo_texto)

def destacar_datas(texto):
    padrao = r'(Esta\s+bula\s+foi\s+(?:atualizada\s+conforme\s+Bula\s+Padrão\s+)?aprovada\s+pela\s+Anvisa\s+em\s*)(\d{2}/\d{2}/\d{4}|\d{2}/\d{4})'
    def replacer(match):
        return f'{match.group(1)}<span class="highlight-blue">{match.group(2)}</span>'
    return re.sub(padrao, replacer, texto, count=1, flags=re.IGNORECASE | re.DOTALL)

def diff_palavra_a_palavra(texto_ref, texto_novo):
    palavras_ref = texto_ref.split()
    palavras_novo = texto_novo.split()
    matcher = difflib.SequenceMatcher(None, palavras_ref, palavras_novo)
    html_ref_list = []
    html_novo_list = []
    tem_diff = False
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            texto = " ".join(palavras_ref[i1:i2])
            html_ref_list.append(texto)
            html_novo_list.append(texto)
        elif tag == 'replace':
            html_ref_list.append(f'<span class="highlight-yellow">{" ".join(palavras_ref[i1:i2])}</span>')
            html_novo_list.append(f'<span class="highlight-yellow">{" ".join(palavras_novo[j1:j2])}</span>')
            tem_diff = True
        elif tag == 'delete':
            html_ref_list.append(f'<span class="highlight-yellow">{" ".join(palavras_ref[i1:i2])}</span>')
            tem_diff = True
        elif tag == 'insert':
            html_novo_list.append(f'<span class="highlight-yellow">{" ".join(palavras_novo[j1:j2])}</span>')
            tem_diff = True
            
    return " ".join(html_ref_list), " ".join(html_novo_list), tem_diff

def gerar_diff_html(texto_ref, texto_novo):
    if not texto_ref: texto_ref = ""
    if not texto_novo: texto_novo = ""
    
    # Se normalizado for igual, não faz diff pesado
    if normalizar_para_comparacao(texto_ref) == normalizar_para_comparacao(texto_novo):
        html_novo = verificar_ortografia_inteligente(texto_novo)
        # Aplica melhoria visual
        html_novo = melhorar_visual_topicos(html_novo.replace('\n', '<br>'))
        return texto_ref.replace('\n', '<br>'), html_novo, False

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
            for linha in linhas_ref[i1:i2]: html_ref_partes.append(linha)
            for linha in linhas_novo[j1:j2]: html_novo_partes.append(verificar_ortografia_inteligente(linha))
        elif tag == 'replace':
            t_ref, t_novo = "\n".join(linhas_ref[i1:i2]), "\n".join(linhas_novo[j1:j2])
            r_html, n_html, diff_bool = diff_palavra_a_palavra(t_ref, t_novo)
            if diff_bool: tem_divergencia = True
            html_ref_partes.append(r_html)
            html_novo_partes.append(verificar_ortografia_inteligente(n_html))
        elif tag == 'delete':
            html_ref_partes.append(f'<span class="highlight-yellow">{"/n".join(linhas_ref[i1:i2])}</span>')
            tem_divergencia = True
        elif tag == 'insert':
            html_novo_partes.append(f'<span class="highlight-yellow">{verificar_ortografia_inteligente("/n".join(linhas_novo[j1:j2]))}</span>')
            tem_divergencia = True

    # Junta tudo com quebra de linha HTML
    final_ref = '<br>'.join(html_ref_partes)
    final_novo = '<br>'.join(html_novo_partes)
    
    # Aplica o visual de tópicos no final
    final_novo = melhorar_visual_topicos(final_novo)
    
    return final_ref, final_novo, tem_divergencia

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
                            html_mkt = verificar_ortografia_inteligente(txt_mkt)
                            html_ref = txt_ref
                        
                        html_mkt = html_mkt.replace('\n', '<br>')
                        html_ref = html_ref.replace('\n', '<br>')
                        html_mkt = melhorar_visual_topicos(html_mkt)
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
