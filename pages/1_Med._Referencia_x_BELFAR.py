import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
import docx
import json
import re
import unicodedata
import difflib

# ----------------- 1. VISUAL & CSS -----------------
st.set_page_config(page_title="Med. Referência x BELFAR", page_icon="💊", layout="wide")

st.markdown("""
<style>
    [data-testid="stHeader"] { visibility: hidden; }

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
    .highlight-red { background-color: #ffcdd2; color: #b71c1c; padding: 2px 4px; border-radius: 4px; border: 1px solid #e57373; font-weight: bold; }
    .highlight-blue { background-color: #e3f2fd; color: #0d47a1; padding: 2px 6px; border-radius: 12px; border: 1px solid #2196f3; font-weight: bold; }
    
    .border-ok { border-left: 6px solid #4caf50 !important; }
    .border-warn { border-left: 6px solid #f44336 !important; }
    .border-info { border-left: 6px solid #2196f3 !important; }
    
    div[data-testid="stMetric"] {
        background-color: #f8f9fa; border: 1px solid #dee2e6; padding: 10px; border-radius: 5px; text-align: center;
    }
</style>
""", unsafe_allow_html=True)

MODELO_FIXO = "models/gemini-flash-latest"

# ----------------- 2. FUNÇÕES -----------------
def limpar_texto_profundo(texto):
    if not texto: return ""
    texto = unicodedata.normalize('NFKD', texto)
    texto = texto.replace('\u00a0', ' ').replace('\r', '')
    texto = re.sub(r'[\._]{3,}', ' ', texto) 
    texto = re.sub(r'[ \t]+', ' ', texto)
    return texto.strip()

def destacar_datas(html_texto):
    """Pinta datas de azul."""
    padrao = r'(?<!\d)(\d{2}/\d{2}/\d{4})(?!\d)'
    return re.sub(padrao, r'<span class="highlight-blue">\1</span>', html_texto)

def gerar_diff_html_red(texto_ref, texto_novo):
    if not texto_ref: texto_ref = ""
    if not texto_novo: texto_novo = ""
    
    TOKEN = " [[BR]] "
    ref_limpo = limpar_texto_profundo(texto_ref).replace('\n', TOKEN)
    novo_limpo = limpar_texto_profundo(texto_novo).replace('\n', TOKEN)
    
    a = ref_limpo.split()
    b = novo_limpo.split()
    
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    output = []
    eh_divergente = False
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        trecho = " ".join(b[j1:j2]).replace("[[BR]]", "\n")
        
        if tag == 'equal':
            output.append(trecho)
        elif tag in ['replace', 'insert']:
            if trecho.strip():
                output.append(f'<span class="highlight-red">{trecho}</span>')
                eh_divergente = True
            else:
                output.append(trecho)
        elif tag == 'delete':
            eh_divergente = True
            
    final_html = " ".join(output).replace(" \n ", "\n").replace("\n ", "\n").replace(" \n", "\n")
    final_html = destacar_datas(final_html)
    return final_html, eh_divergente

def extract_text_from_file(uploaded_file):
    try:
        text = ""
        if uploaded_file.name.lower().endswith('.pdf'):
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            for page in doc:
                blocks = page.get_text("dict", flags=11, sort=True)["blocks"]
                for b in blocks:
                    block_txt = ""
                    for l in b.get("lines", []):
                        line_txt = ""
                        for s in l.get("spans", []):
                            c = s["text"]
                            if (s["flags"] & 16) or "bold" in s["font"].lower(): line_txt += f"<b>{c}</b>"
                            else: line_txt += c
                        block_txt += line_txt + " "
                    text += block_txt + "\n"
        elif uploaded_file.name.lower().endswith('.docx'):
            doc = docx.Document(uploaded_file)
            for p in doc.paragraphs:
                p_txt = ""
                for r in p.runs:
                    if r.bold: p_txt += f"<b>{r.text}</b>"
                    else: p_txt += r.text
                text += p_txt + "\n\n"
        return limpar_texto_profundo(text)
    except: return ""

# ----------------- 3. CONFIGURAÇÃO SEÇÕES -----------------
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

# ----------------- 4. UI PRINCIPAL -----------------
st.title("💊 Med. Referência x BELFAR")

tipo = st.radio("Tipo:", ["Paciente", "Profissional"], horizontal=True)
secoes_ativas = SECOES_PACIENTE if tipo == "Paciente" else SECOES_PROFISSIONAL

st.divider()
c1, c2 = st.columns(2)
f1 = c1.file_uploader("📂 Referência", type=["pdf", "docx"], key="f1")
f2 = c2.file_uploader("📂 BELFAR", type=["pdf", "docx"], key="f2")

if st.button("🚀 Processar Conferência"):
    keys = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2"), st.secrets.get("GEMINI_API_KEY3")]
    valid_keys = [k for k in keys if k]
    if not valid_keys: st.error("Sem chaves API."); st.stop()

    if f1 and f2:
        with st.spinner("Processando..."):
            f1.seek(0); f2.seek(0)
            t_ref = extract_text_from_file(f1)
            t_bel = extract_text_from_file(f2)

            if len(t_ref) < 20: st.error("Arquivo Ref vazio."); st.stop()

            prompt = f"""
            Você é um Auditor Farmacêutico Rígido.
            INPUT REF: {t_ref[:150000]}
            INPUT BEL: {t_bel[:150000]}
            
            TAREFA:
            1. Extraia o texto COMPLETO das seções abaixo. NÃO RESUMA.
            2. Mantenha formatação (negrito <b>, quebras de linha).
            3. Ignore pontilhados (....).
            
            SEÇÕES: {secoes_ativas}
            
            JSON:
            {{
                "data_anvisa_ref": "dd/mm/aaaa",
                "data_anvisa_belfar": "dd/mm/aaaa",
                "secoes": [ {{"titulo": "...", "texto_ref": "...", "texto_belfar": "..."}} ]
            }}
            """

            resp = None
            for k in valid_keys:
                try:
                    genai.configure(api_key=k)
                    model = genai.GenerativeModel(MODELO_FIXO, generation_config={"response_mime_type": "application/json"})
                    resp = model.generate_content(prompt)
                    break
                except: continue
            
            if resp:
                try:
                    res = json.loads(resp.text)
                    data_ref = res.get("data_anvisa_ref", "-")
                    data_bel = res.get("data_anvisa_belfar", "-")
                    lista = res.get("secoes", [])
                    
                    final_list = []
                    err_count = 0

                    secoes_isentas = ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]

                    for item in lista:
                        tit = item.get("titulo", "").strip()
                        tit_upper = tit.upper()
                        tr = item.get("texto_ref", "").strip()
                        tb = item.get("texto_belfar", "").strip()
                        
                        eh_isenta = any(x in tit_upper for x in secoes_isentas)
                        
                        if eh_isenta:
                            # Se é isenta, status sempre CONFORME e não roda diff vermelho
                            status = "CONFORME"
                            
                            # Tratamento para Dizeres Legais (Azul na data)
                            if "DIZERES LEGAIS" in tit_upper:
                                html_ref = destacar_datas(tr.replace('\n', '<br>'))
                                html_bel = destacar_datas(tb.replace('\n', '<br>'))
                            else:
                                # Outras isentas (Apresentações/Composição): Texto puro limpo
                                html_ref = tr.replace('\n', '<br>')
                                html_bel = tb.replace('\n', '<br>')
                                
                        else:
                            # Seções normais: Roda o Diff Vermelho
                            html_bel, is_diff = gerar_diff_html_red(tr, tb)
                            html_ref = destacar_datas(tr.replace('\n', '<br>'))
                            status = "DIVERGENTE" if is_diff else "CONFORME"
                            if is_diff: err_count += 1
                        
                        final_list.append({
                            "titulo": tit, 
                            "ref_html": html_ref, 
                            "bel_html": html_bel.replace('\n', '<br>'), 
                            "status": status
                        })

                    st.markdown("### 📊 Resumo")
                    c_a, c_b, c_c = st.columns(3)
                    c_a.metric("Ref.", data_ref)
                    c_b.metric("BELFAR", data_bel)
                    c_c.metric("Seções", len(final_list))
                    
                    if err_count == 0: st.success("✅ Tudo Conforme")
                    else: st.error(f"🚨 {err_count} Divergências Encontradas (Exceto Isentas)")

                    st.divider()
                    for it in final_list:
                        status = it["status"]
                        tit_show = it["titulo"]
                        
                        # Definição de Ícones e Cores
                        if "DIZERES LEGAIS" in tit_show.upper():
                            icon = "⚖️"; css = "border-info"; aberto = False
                        elif any(x in tit_show.upper() for x in ["APRESENTAÇÕES", "COMPOSIÇÃO"]):
                            icon = "📋"; css = "border-info"; aberto = False
                        elif status == "DIVERGENTE":
                            icon = "⚠️"; css = "border-warn"; aberto = True
                        else:
                            icon = "✅"; css = "border-ok"; aberto = False

                        with st.expander(f"{icon} {tit_show}", expanded=aberto):
                            cL, cR = st.columns(2)
                            cL.markdown(f'<div class="texto-box {css}">{it["ref_html"]}</div>', unsafe_allow_html=True)
                            cR.markdown(f'<div class="texto-box {css}">{it["bel_html"]}</div>', unsafe_allow_html=True)

                except Exception as e: st.error(f"Erro JSON: {e}")
    else: st.warning("Envie os arquivos.")
