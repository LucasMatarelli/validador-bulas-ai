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
    
    /* ERRO PORTUGUÊS (Vermelho) - Apenas erros ortográficos */
    .highlight-red { 
        background-color: #f8d7da; color: #721c24; 
        padding: 2px 4px; border-radius: 4px; border: 1px solid #f5c6cb; 
        text-decoration: underline wavy #dc3545;
        cursor: help;
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
    Normalização AGRESSIVA para eliminar falsos positivos.
    Remove espaços, pontuação, tags HTML e caracteres invisíveis.
    """
    if not texto: return ""
    
    # Remove tags HTML
    texto = re.sub(r'<[^>]+>', '', texto)
    
    # Normaliza Unicode
    texto = unicodedata.normalize('NFKD', texto)
    
    # Remove acentos
    texto = ''.join([c for c in texto if not unicodedata.combining(c)])
    
    # Remove pontuação e caracteres especiais
    texto = re.sub(r'[^\w\s]', '', texto)
    
    # Remove espaços múltiplos e converte para minúsculas
    texto = re.sub(r'\s+', ' ', texto).strip().lower()
    
    return texto

def verificar_ortografia(texto):
    """
    Marca de VERMELHO apenas palavras com erro ortográfico.
    Ignora tags HTML, números, siglas e termos técnicos curtos.
    """
    try:
        spell = SpellChecker(language='pt')
        
        # Palavras técnicas comuns em bulas que não devem ser marcadas
        termos_tecnicos = {
            'mg', 'ml', 'mcg', 'ui', 'frascoampola', 'comprimido', 'capsula',
            'anvisa', 'rg', 'cpf', 'cnpj', 'cep', 'tel', 'sac', 'lote', 'val',
            'mg/ml', 'mcg/ml', 'ui/ml'
        }
        spell.word_frequency.load_words(termos_tecnicos)
        
        # Divide o texto preservando as tags HTML
        partes = re.split(r'(<[^>]+>)', texto)
        resultado = []
        
        for parte in partes:
            if parte.startswith('<'):
                # É uma tag HTML, mantém como está
                resultado.append(parte)
            else:
                # É texto normal, verifica ortografia palavra por palavra
                palavras = re.findall(r'\b\w+\b|\W+', parte)
                for palavra in palavras:
                    # Ignora se não for palavra ou se for muito curta
                    if not re.match(r'\w+', palavra) or len(palavra) <= 2:
                        resultado.append(palavra)
                        continue
                    
                    # Ignora números
                    if palavra.isdigit():
                        resultado.append(palavra)
                        continue
                    
                    # Verifica ortografia
                    if palavra.lower() not in spell and palavra.lower() not in termos_tecnicos:
                        resultado.append(f'<span class="highlight-red" title="Possível erro ortográfico">{palavra}</span>')
                    else:
                        resultado.append(palavra)
        
        return ''.join(resultado)
    except:
        return texto

def destacar_datas(texto):
    padrao = r'(Esta\s+bula\s+foi\s+(?:atualizada\s+conforme\s+Bula\s+Padrão\s+)?aprovada\s+pela\s+Anvisa\s+em\s*)(\d{2}/\d{2}/\d{4}|\d{2}/\d{4})'
    def replacer(match):
        return f'{match.group(1)}<span class="highlight-blue">{match.group(2)}</span>'
    return re.sub(padrao, replacer, texto, count=1, flags=re.IGNORECASE | re.DOTALL)

def gerar_diff_html(texto_ref, texto_novo):
    """
    Gera HTML com marcações:
    - Amarelo: apenas diferenças REAIS de conteúdo
    - Vermelho: erros ortográficos no texto novo
    """
    if not texto_ref: texto_ref = ""
    if not texto_novo: texto_novo = ""
    
    # Primeiro verifica se são iguais após normalização
    ref_norm = normalizar_para_comparacao(texto_ref)
    novo_norm = normalizar_para_comparacao(texto_novo)
    
    if ref_norm == novo_norm:
        # Textos são iguais, apenas aplica verificação ortográfica
        html_ref = texto_ref.replace('\n', '<br>')
        html_novo = verificar_ortografia(texto_novo.replace('\n', '<br>'))
        return html_ref, html_novo, False
    
    # Textos são diferentes, faz comparação linha por linha
    linhas_ref = texto_ref.split('\n')
    linhas_novo = texto_novo.split('\n')
    
    matcher = difflib.SequenceMatcher(None, linhas_ref, linhas_novo, autojunk=False)
    
    html_ref_partes = []
    html_novo_partes = []
    tem_divergencia = False
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            # Linhas iguais
            for linha in linhas_ref[i1:i2]:
                html_ref_partes.append(linha)
            for linha in linhas_novo[j1:j2]:
                html_novo_partes.append(verificar_ortografia(linha))
                
        elif tag == 'replace':
            # Verifica se a diferença é real ou só formatação
            trecho_ref = '\n'.join(linhas_ref[i1:i2])
            trecho_novo = '\n'.join(linhas_novo[j1:j2])
            
            if normalizar_para_comparacao(trecho_ref) == normalizar_para_comparacao(trecho_novo):
                # Diferença apenas de formatação, não marca
                html_ref_partes.append(trecho_ref)
                html_novo_partes.append(verificar_ortografia(trecho_novo))
            else:
                # Diferença real de conteúdo
                html_ref_partes.append(f'<span class="highlight-yellow">{trecho_ref}</span>')
                html_novo_partes.append(f'<span class="highlight-yellow">{verificar_ortografia(trecho_novo)}</span>')
                tem_divergencia = True
                
        elif tag == 'delete':
            # Texto removido
            trecho = '\n'.join(linhas_ref[i1:i2])
            html_ref_partes.append(f'<span class="highlight-yellow">{trecho}</span>')
            tem_divergencia = True
            
        elif tag == 'insert':
            # Texto adicionado
            trecho = '\n'.join(linhas_novo[j1:j2])
            html_novo_partes.append(f'<span class="highlight-yellow">{verificar_ortografia(trecho)}</span>')
            tem_divergencia = True
    
    html_ref = '<br>'.join(html_ref_partes)
    html_novo = '<br>'.join(html_novo_partes)
    
    return html_ref, html_novo, tem_divergencia

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
                        # Usa a lógica corrigida de comparação
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
