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
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# ----------------- 1. VISUAL & CSS -----------------
st.set_page_config(page_title="Conferência MKT", page_icon="💊", layout="wide")

st.markdown("""
<style>
    [data-testid="stHeader"] { visibility: hidden; }
    
    .texto-box { 
        font-family: 'Segoe UI', sans-serif;
        font-size: 0.95rem;
        line-height: 1.7;
        color: #212529;
        background-color: #ffffff;
        padding: 25px;
        border-radius: 8px;
        border: 1px solid #ced4da;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        text-align: left;
    }
    
    .highlight-yellow { 
        background-color: #fff3cd; color: #856404; 
        padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; 
        font-weight: bold;
    }
    
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
    
    .topico-item {
        display: block;
        margin-left: 20px;
        margin-bottom: 4px;
        text-indent: -15px; 
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
# LISTA EXATA SOLICITADA PELO USUÁRIO
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

SECOES_PROFISSIONAL = SECOES_PACIENTE 
SECOES_SEM_COMPARACAO = ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]

# ----------------- 3. FUNÇÕES INTELIGENTES -----------------

def normalizacao_nuclear(texto):
    if not texto: return ""
    t = re.sub(r'<[^>]+>', '', texto)
    t = unicodedata.normalize('NFKD', t).encode('ASCII', 'ignore').decode('ASCII')
    t = re.sub(r'[^a-zA-Z0-9]', '', t)
    return t.lower()

def verificar_ortografia_inteligente(texto):
    try:
        spell = SpellChecker(language='pt')
        whitelist = {
            'mg', 'ml', 'mcg', 'ui', 'g', 'kg', 'l', 'dl', 'mmhg', 'bpm', 'kcal', 
            'crf', 'crm', 'anvisa', 'lote', 'val', 'fab', 'sac', 'cnpj', 'cep', 
            'dr', 'dra', 'vp', 'vps', 'bula', 'paciente', 'profissional', 'sac',
            'blister', 'cartucho', 'posologia', 'superdose', 'farmacocinetica',
            'biodisponibilidade', 'excipiente', 'excipientes', 'revestimento',
            'comprimido', 'capsula', 'solucao', 'suspensao', 'oral', 'intravenosa',
            'subcutanea', 'intramuscular', 'topico', 'oftalmico', 'nasal',
            'adulto', 'pediatrico', 'geriatrico', 'indicação', 'contraindicação',
            'advertencia', 'precaucao', 'interacao', 'reacao', 'adversa', 'sintoma',
            'tratamento', 'diagnostico', 'profilaxia', 'analgesico', 'antipiretico',
            'anti-inflamatorio', 'antibiotico', 'antiviral', 'antifungico',
            'cardiovascular', 'respiratorio', 'digestivo', 'nervoso', 'central',
            'periferico', 'renal', 'hepatico', 'sanguineo', 'imunologico',
            'endocrino', 'metabolico', 'musculoesqueletico', 'dermatologico',
            'predisponentes', 'sistemicos', 'sistêmicos', 'congenita', 'congênita',
            'aneurisma', 'dissecção', 'disseccao', 'valvar', 'valvula', 'regurgitação',
            'endocardite', 'marfan', 'ehlers-danlos', 'turner', 'sjogren', 'takayasu',
            'behcet', 'reumatoide', 'artrite', 'corticosteroides', 'fluorquinolonas',
            'hipersensibilidade', 'arritmia', 'protuberancia', 'abdômen', 'abdomen',
            'gonorreia', 'gonorréia', 'infeccao', 'infeção', 'trato', 'urinario',
            'uretra', 'cervix', 'tubulos', 'túbulos', 'renais', 'queimação', 'queimacao',
            'prostatite', 'prostata', 'cistite', 'ureia', 'bacteria', 'bacterias'
        }
        spell.word_frequency.load_words(whitelist)

        tokens = re.split(r'(<[^>]+>|\s+|[().,:;!?/\[\]])', texto)
        resultado = []
        
        for token in tokens:
            if not token.strip() or token.startswith('<') or not any(c.isalpha() for c in token):
                resultado.append(token)
                continue
            
            palavra_limpa = re.sub(r'[^a-zA-ZáàâãéèêíïóôõöúçñÁÀÂÃÉÈÊÍÏÓÔÕÖÚÇÑ-]', '', token)
            
            if (not palavra_limpa or len(palavra_limpa) < 4 or any(c.isdigit() for c in token) or '-' in palavra_limpa or palavra_limpa[0].isupper()):
                resultado.append(token)
                continue

            p_lower = palavra_limpa.lower()
            if p_lower in spell or p_lower in whitelist:
                resultado.append(token)
            else:
                resultado.append(token)

        return "".join(resultado)
    except:
        return texto

def melhorar_visual_topicos(texto_html):
    linhas = re.split(r'(<br>|\n)', texto_html)
    novo_texto = []
    for linha in linhas:
        if re.search(r'^\s*[-•*]\s+', re.sub(r'<[^>]+>', '', linha).strip()):
            linha_limpa = re.sub(r'^\s*[-•*]\s+', '', linha)
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
    
    if normalizacao_nuclear(texto_ref) == normalizacao_nuclear(texto_novo):
        html_novo = verificar_ortografia_inteligente(texto_novo)
        html_novo = melhorar_visual_topicos(html_novo.replace('\n', '<br>'))
        return texto_ref.replace('\n', '<br>'), html_novo, False

    ref_limpo = re.sub(r'<[^>]+>', '', texto_ref)
    novo_limpo = re.sub(r'<[^>]+>', '', texto_novo)
    
    r_html, n_html, diff_bool = diff_palavra_a_palavra(ref_limpo, novo_limpo)
    
    n_html_final = verificar_ortografia_inteligente(n_html)
    n_html_final = melhorar_visual_topicos(n_html_final)
    r_html_final = r_html.replace('\n', '<br>')
    
    return r_html_final, n_html_final, diff_bool

# ----------------- 4. EXTRAÇÃO E OCR -----------------

def ocr_via_gemini(uploaded_file, api_keys):
    """
    OCR ROBISTO:
    Itera sobre CHAVES e sobre MODELOS.
    """
    uploaded_file.seek(0)
    bytes_data = uploaded_file.read()
    
    prompt_ocr = "Transcreva TODO o texto deste documento fielmente. Não faça resumos, apenas extraia o texto exato."
    
    safety_settings = {
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    }

    log_erros_ocr = []

    # Loop Chaves -> Loop Modelos
    for i, key in enumerate(api_keys):
        try:
            genai.configure(api_key=key)
            
            for modelo in MODELOS_PARA_TENTAR:
                try:
                    model = genai.GenerativeModel(modelo)
                    response = model.generate_content(
                        [{'mime_type': 'application/pdf', 'data': bytes_data}, prompt_ocr],
                        safety_settings=safety_settings
                    )
                    if response.text:
                        return response.text, None # SUCESSO!
                except Exception as e_model:
                    err_msg = str(e_model)
                    log_erros_ocr.append(f"Key {i+1} | {modelo}: {err_msg}")
                    # Se for erro de Cota (429), pausa um pouco antes de tentar o próximo modelo/chave
                    if "429" in err_msg or "quota" in err_msg.lower():
                        time.sleep(2)
                    continue
        except Exception as e_key:
            log_erros_ocr.append(f"Key {i+1} Falha Config: {str(e_key)}")
            continue
            
    return "", " | ".join(log_erros_ocr)

def extract_text_from_file(uploaded_file, api_keys=None):
    text = ""
    try:
        # 1. Tenta extração nativa (rápida)
        if uploaded_file.name.lower().endswith('.pdf'):
            uploaded_file.seek(0)
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            for page in doc: 
                blocks = page.get_text("dict", flags=11, sort=True)["blocks"]
                for b in blocks:
                    block_text = ""
                    for l in b.get("lines", []):
                        line_txt = ""
                        for s in l.get("spans", []):
                            content = s["text"]
                            is_bold = (s["flags"] & 16) or "bold" in s["font"].lower()
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
        
        # 2. Verificação OCR
        texto_limpo = re.sub(r'<[^>]+>', '', text).strip()
        
        # Se tiver menos de 50 caracteres e for PDF, assume que é imagem
        if len(texto_limpo) < 50 and uploaded_file.name.lower().endswith('.pdf') and api_keys:
            st.warning(f"⚠️ '{uploaded_file.name}' parece ser imagem. Tentando OCR com todas as chaves e modelos...")
            
            texto_ocr, erro_ocr = ocr_via_gemini(uploaded_file, api_keys)
            
            if texto_ocr:
                st.success(f"✅ OCR realizado com sucesso em '{uploaded_file.name}'!")
                return texto_ocr
            else:
                st.error(f"Falha OCR em '{uploaded_file.name}'. Erros: {erro_ocr}")
                return ""

        return text
    except Exception as e:
        return f"Erro na leitura: {str(e)}"

# ----------------- 5. UI PRINCIPAL -----------------
st.title("💊 Conferência MKT")

tipo_bula = st.radio("Escolha o Tipo de Bula:", ("Paciente",), horizontal=True)

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula BELFAR", type=["pdf", "docx"], key="f1")
f2 = c2.file_uploader("📜 Bula MKT", type=["pdf", "docx"], key="f2")

if st.button("🚀 Processar Conferência"):
    keys_raw = [
        st.secrets.get("GEMINI_API_KEY"), 
        st.secrets.get("GEMINI_API_KEY2"), 
        st.secrets.get("GEMINI_API_KEY3")
    ]
    keys_validas = [k for k in keys_raw if k]

    if not keys_validas:
        st.error("Erro Crítico: Nenhuma API Key encontrada no secrets."); st.stop()

    if f1 and f2:
        secoes_alvo = SECOES_PACIENTE

        with st.spinner("Lendo arquivos (aplicando OCR se necessário com todas as chaves)..."):
            # O código vai tentar OCR nos DOIS arquivos se precisar
            t_anvisa = extract_text_from_file(f1, api_keys=keys_validas)
            t_mkt = extract_text_from_file(f2, api_keys=keys_validas)

            # Verificação final: se voltou vazio, para tudo.
            if not t_anvisa or len(t_anvisa) < 20:
                st.error(f"ERRO: O arquivo BELFAR está vazio ou ilegível mesmo com OCR."); st.stop()
            if not t_mkt or len(t_mkt) < 20:
                st.error(f"ERRO: O arquivo MKT está vazio ou ilegível mesmo com OCR."); st.stop()

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
            {{ "data_anvisa_ref": "...", "data_anvisa_mkt": "...", "secoes": [ {{ "titulo": "...", "texto_anvisa": "...", "texto_mkt": "..." }} ] }}
            """
            
            response = None
            sucesso = False
            log_erros = []

            # Loop Principal de Análise: Chave -> Modelos
            for idx_key, key in enumerate(keys_validas):
                if sucesso: break
                
                genai.configure(api_key=key)
                
                for modelo in MODELOS_PARA_TENTAR:
                    try:
                        model = genai.GenerativeModel(modelo, generation_config={"response_mime_type": "application/json", "temperature": 0.0})
                        response = model.generate_content(prompt)
                        sucesso = True
                        break 
                    except Exception as e:
                        erro_msg = str(e)
                        log_erros.append(f"Key {idx_key+1} | {modelo}: {erro_msg}")
                        # Se for erro de cota (429), espera um pouco mais
                        if "429" in erro_msg or "quota" in erro_msg.lower():
                            time.sleep(3)
                        else:
                            time.sleep(0.5)
                        continue

            if not sucesso:
                st.error("❌ Falha Total na Análise."); st.code("\n".join(log_erros)); st.stop()
            
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
                            html_mkt = destacar_datas(txt_mkt); html_ref = destacar_datas(txt_ref)
                        else:
                            html_mkt = verificar_ortografia_inteligente(txt_mkt); html_ref = txt_ref
                        html_mkt = melhorar_visual_topicos(html_mkt.replace('\n', '<br>'))
                        html_ref = html_ref.replace('\n', '<br>')
                    else:
                        html_ref, html_mkt, teve_diff = gerar_diff_html(txt_ref, txt_mkt)
                        status = "DIVERGENTE" if teve_diff else "CONFORME"
                        if teve_diff: divs_count += 1

                    secoes_finais.append({"titulo": titulo, "texto_anvisa": html_ref, "texto_mkt": html_mkt, "status": status})

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
                        with ce: st.caption("BELFAR"); st.markdown(f'<div class="texto-box {css}">{item["texto_anvisa"]}</div>', unsafe_allow_html=True)
                        with cd: st.caption("MKT"); st.markdown(f'<div class="texto-box {css}">{item["texto_mkt"]}</div>', unsafe_allow_html=True)

            except Exception as e:
                st.error(f"Erro ao processar JSON: {e}"); st.code(response.text)
    else:
        st.warning("Adicione os arquivos.")
