import streamlit as st
import google.generativeai as genai
import json
import difflib
import re
import time
import os
import tempfile
import asyncio
import nest_asyncio
from llama_parse import LlamaParse

# Necessário para o LlamaParse rodar liso dentro do Streamlit sem dar erro de thread
nest_asyncio.apply()

# ----------------- 1. VISUAL & CSS -----------------
st.set_page_config(page_title="Med. Referência x BELFAR", page_icon="💊", layout="wide")

st.markdown("""
<style>
    [data-testid="stHeader"] { visibility: hidden; }
    
    .texto-box { 
        font-family: 'Segoe UI', sans-serif;
        font-size: 0.95rem;
        line-height: 1.6;
        color: #212529;
        background-color: #ffffff;
        padding: 25px;
        border-radius: 8px;
        border: 1px solid #ced4da;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    
    /* DIVERGÊNCIA (Amarelo) */
    .highlight-yellow { background-color: #fff3cd; color: #856404; padding: 0px 2px; border-radius: 3px; border: 1px solid #ffeeba; font-weight: bold; }
    .highlight-blue { background-color: #d1ecf1; color: #0c5460; padding: 2px 4px; border-radius: 4px; border: 1px solid #bee5eb; font-weight: bold; }
    .border-ok { border-left: 6px solid #28a745 !important; }
    .border-warn { border-left: 6px solid #ffc107 !important; } 
    .border-info { border-left: 6px solid #17a2b8 !important; }
    div[data-testid="stMetric"] { background-color: #f8f9fa; border: 1px solid #dee2e6; padding: 10px; border-radius: 5px; text-align: center; }
</style>
""", unsafe_allow_html=True)

# ----------------- 2. CONFIGURAÇÃO -----------------
MODELOS_PARA_TENTAR = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-pro"
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

def destacar_datas(texto):
    padrao = r'(Esta\s+bula\s+foi\s+(?:atualizada\s+conforme\s+Bula\s+Padrão\s+)?aprovada\s+pela\s+Anvisa\s+em\s*)(\d{2}/\d{2}/\d{4}|\d{2}/\d{4})'
    def replacer(match):
        return f'{match.group(1)}<span class="highlight-blue">{match.group(2)}</span>'
    return re.sub(padrao, replacer, texto, count=1, flags=re.IGNORECASE | re.DOTALL)

def formatar_html(texto):
    if not texto: return ""
    texto = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', texto)
    texto = re.sub(r'(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)', r'<i>\1</i>', texto)
    texto = re.sub(r'\_(.*?)\_', r'<i>\1</i>', texto)
    texto = texto.replace('\r\n', '\n').replace('\r', '\n')
    texto = re.sub(r'\n{2,}', '@@BLOCO@@', texto)
    padrao_lista = r'\n(?=\s*(?:<[^>]+>)*\s*(?:[-\u2013\u2014•*]|[a-zA-Z]\)|[0-9]+\.)\s+)'
    texto = re.sub(padrao_lista, '@@BLOCO@@', texto)
    texto = texto.replace('\n', ' ')
    texto = re.sub(r'[ \t]+', ' ', texto)
    blocos = texto.split('@@BLOCO@@')
    resultado = []
    for bloco in blocos:
        bloco_limpo = bloco.strip()
        if not bloco_limpo: continue
        texto_sem_tags = re.sub(r'<[^>]+>', '', bloco_limpo).strip()
        if re.match(r'^([-\u2013\u2014•*]|[a-zA-Z]\)|[0-9]+\.)\s+', texto_sem_tags):
            resultado.append(f'<div style="margin-left: 20px; text-indent: -15px; margin-bottom: 8px; text-align: justify;">{bloco_limpo}</div>')
        else:
            resultado.append(f'<div style="margin-bottom: 12px; text-align: justify;">{bloco_limpo}</div>')
    return "".join(resultado)

def diff_palavra_a_palavra(texto_ref, texto_novo):
    tokens_ref = []
    tokens_novo = []
    matcher = difflib.SequenceMatcher(None, tokens_ref, tokens_novo, autojunk=False)
    matcher.set_seqs(tokens_ref, tokens_novo)
    html_ref_list = []
    html_novo_list = []
    tem_diff = False
    
    def limpar_espacos(t):
        t = t.replace('\xa0', ' ').replace('\u200b', '').replace('\xad', '')
        t = re.sub(r'[ \t]+', ' ', t) 
        t = re.sub(r' ([.,;:?!])', r'\1', t) 
        return t
        
    texto_ref = limpar_espacos(texto_ref)
    texto_novo = limpar_espacos(texto_novo)
    tokens_ref = [t for t in re.split(r'(\s+)', texto_ref) if t]
    tokens_novo = [t for t in re.split(r'(\s+)', texto_novo) if t]

    matcher = difflib.SequenceMatcher(None, tokens_ref, tokens_novo, autojunk=False)
    matcher.set_seqs(tokens_ref, tokens_novo)
    
    def envolver_diferenca(tokens):
        res = []
        for t in tokens:
            if re.match(r'^\s+$', t) or not t: 
                res.append(t)
            else:
                res.append(f'<span class="highlight-yellow">{t}</span>')
        return "".join(res)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            html_ref_list.append("".join(tokens_ref[i1:i2]))
            html_novo_list.append("".join(tokens_novo[j1:j2]))
        elif tag in ['replace', 'delete', 'insert']:
            if tag in ['replace', 'delete']:
                html_ref_list.append(envolver_diferenca(tokens_ref[i1:i2]))
                if "".join(tokens_ref[i1:i2]).strip(): tem_diff = True
            if tag in ['replace', 'insert']:
                html_novo_list.append(envolver_diferenca(tokens_novo[j1:j2]))
                if "".join(tokens_novo[j1:j2]).strip(): tem_diff = True
                
    return "".join(html_ref_list), "".join(html_novo_list), tem_diff

def extract_text_from_file_with_llamaparse(uploaded_file, api_key):
    try:
        suffix = f".{uploaded_file.name.split('.')[-1]}"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(uploaded_file.getvalue())
            temp_path = tmp.name

        parser = LlamaParse(
            api_key=api_key,
            result_type="markdown",
            verbose=False,
            language="pt"
        )
        docs = parser.load_data(temp_path)
        texto_completo = "\\n\\n".join([doc.text for doc in docs])
        os.unlink(temp_path)
        
        texto_completo = re.sub(r'(\w)-\s+(\w)', r'\1-\2', texto_completo)
        texto_completo = re.sub(r'(?i)(?:bula\s+)?p[áa]gina\s+\d+\s+de\s+\d+', '', texto_completo)
        texto_completo = re.sub(r'(?i)\b\d*\s*VP\d+\s*=\s*[a-zA-Z0-9_]+\s*\d*', '', texto_completo)
        texto_completo = re.sub(r'(?i)\b[a-zA-Z0-9_]+_bula_(?:paciente|profissional)\s*\d*', '', texto_completo)
        
        return texto_completo
    except Exception as e:
        st.error(f"Erro na extração LlamaParse: {e}")
        return ""

# ============= CRIA O MENU LATERAL =============
st.markdown("""
<style>
    [data-testid="stHeader"] { visibility: hidden; }
    section[data-testid="stSidebar"] { display: block !important; visibility: visible !important; width: 250px !important; min-width: 250px !important; max-width: 250px !important; margin-left: 0 !important; transform: translateX(0) !important; transition: none !important; position: relative !important; background-color: #f0f2f6 !important; z-index: 999 !important; }
    section[data-testid="stSidebar"] > div:first-child { width: 250px !important; min-width: 250px !important; }
    section[data-testid="stSidebar"][aria-expanded="false"], section[data-testid="stSidebar"][aria-expanded="true"] { margin-left: 0 !important; transform: translateX(0) !important; }
    button[kind="header"], [data-testid="collapsedControl"], button[data-testid="baseButton-header"] { display: none !important; }
</style>
""", unsafe_allow_html=True)

# ----------------- 5. UI PRINCIPAL -----------------
st.title("💊 Med. Referência x BELFAR")

tipo_bula = st.radio("Escolha o Tipo de Bula:", ("Paciente", "Profissional"), horizontal=True)

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
    llama_key = st.secrets.get("LLAMAPARSE_API_KEY")

    if not keys_validas:
        st.error("Erro Crítico: Nenhuma API Key do Gemini encontrada nos Secrets.")
        st.stop()
        
    if not llama_key:
        st.error("Erro Crítico: LLAMAPARSE_API_KEY não encontrada nos Secrets. Adicione sua chave do LlamaParse.")
        st.stop()

    if f1 and f2:
        secoes_alvo = SECOES_PACIENTE if tipo_bula == "Paciente" else SECOES_PROFISSIONAL

        with st.spinner("Lendo PDFs com IA LlamaParse (Isso pode levar alguns segundos)..."):
            t_anvisa = extract_text_from_file_with_llamaparse(f1, llama_key)
            t_mkt = extract_text_from_file_with_llamaparse(f2, llama_key)

            if len(t_anvisa) < 20 or len(t_mkt) < 20:
                st.error("Arquivo vazio ou ilegível."); st.stop()

        with st.spinner("Analisando divergências com Gemini..."):
            prompt = f"""
            Você é um Extrator de Dados Farmacêuticos Rigoroso.
            
            INPUT TEXTO 1 (REF): {t_anvisa[:150000]}
            INPUT TEXTO 2 (MKT): {t_mkt[:150000]}

            SUA MISSÃO:
            1. Extrair DATA DE APROVAÇÃO (frase exata "aprovada pela Anvisa em...").
            2. Extrair TODO o conteúdo de cada seção. NÃO RESUMA NENHUMA FRASE.
            3. O texto fornecido foi extraído em Markdown. Preserve marcações de negrito e quebras de linha.
            4. MANTER todas as tags **negrito** e *itálico* EXATAMENTE como aparecem no texto.
            5. PRESERVAR AS QUEBRAS DE PARÁGRAFOS (\\n\\n). Nunca junte dois parágrafos que estavam separados.

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
                        model_instance = genai.GenerativeModel(
                            modelo, 
                            generation_config={"response_mime_type": "application/json", "temperature": 0.0}
                        )
                        response = model_instance.generate_content(prompt)
                        sucesso = True
                        break 
                    except Exception as e:
                        log_erros.append(f"Key {idx_key+1} | {modelo}: {str(e)}")
                        time.sleep(0.5)
                        continue

            if not sucesso:
                st.error("❌ Falha Total. Todas as chaves e modelos falharam. Detalhes:")
                st.code("\\n".join(log_erros))
                st.stop()
            
            try:
                texto_resposta = response.text.strip()
                if texto_resposta.startswith('```json'):
                    texto_resposta = texto_resposta[7:-3]
                elif texto_resposta.startswith('
```'):
                    texto_resposta = texto_resposta[3:-3]
                
                resultado = json.loads(texto_resposta)
                
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
                            html_mkt = destacar_datas(formatar_html(txt_mkt))
                            html_ref = destacar_datas(formatar_html(txt_ref))
                        else:
                            html_mkt = formatar_html(txt_mkt)
                            html_ref = formatar_html(txt_ref)
                    else:
                        html_ref_raw, html_mkt_raw, teve_diff = diff_palavra_a_palavra(formatar_html(txt_ref), formatar_html(txt_mkt))
                        html_ref = html_ref_raw
                        html_mkt = html_mkt_raw
                        status = "DIVERGENTE" if teve_diff else "CONFORME"
                        if teve_diff: divs_count += 1

                    secoes_finais.append({
                        "titulo": titulo, "texto_anvisa": html_ref, "texto_mkt": html_mkt, "status": status
                    })

                st.markdown("### 📊 Resumo")
                c1, c2, c3 = st.columns(3)
                c1.metric("Data Referência", data_ref)
                c2.metric("Data BELFAR", data_mkt, delta="Igual" if data_ref == data_mkt else "Diferente")
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
                            st.caption("BELFAR")
                            st.markdown(f'<div class="texto-box {css}">{item["texto_mkt"]}</div>', unsafe_allow_html=True)

            except Exception as e:
                st.error(f"Erro ao processar JSON: {e}")
                st.code(response.text)
    else:
        st.warning("Adicione os arquivos.")
