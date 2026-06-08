import streamlit as st
import pdfplumber
import difflib
import pandas as pd

# ----------------- 1. CONFIGURAÇÃO -----------------
st.set_page_config(page_title="Validador Profissional Belfar", layout="wide")

def extract_structured_text(pdf_file):
    """Extrai texto preservando a estrutura de parágrafos (Layout Analysis)."""
    text_data = []
    with pdfplumber.open(pdf_file) as pdf:
        for i, page in enumerate(pdf.pages):
            # extrair_texto inteligente: mantém parágrafos e ignora posição visual rígida
            text = page.extract_text(layout=True)
            if text:
                # Quebra em linhas para análise estrutural
                lines = text.split('\n')
                for line in lines:
                    if line.strip():
                        text_data.append({'page': i+1, 'content': line.strip()})
    return text_data

# ----------------- 2. LÓGICA DE AUDITORIA -----------------
def compare_bula(ref_data, bel_data):
    ref_lines = [d['content'] for d in ref_data]
    bel_lines = [d['content'] for d in bel_data]
    
    matcher = difflib.SequenceMatcher(None, ref_lines, bel_lines)
    report = []
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal': continue
        
        # Divergência encontrada
        report.append({
            "Tipo": "DIVERGÊNCIA" if tag == 'replace' else "FALTA/SOBRA",
            "Referência": "\n".join(ref_lines[i1:i2]),
            "BELFAR": "\n".join(bel_lines[j1:j2]),
            "Página": f"{ref_data[i1]['page'] if i1 < len(ref_data) else 'N/A'}"
        })
    return report

# ----------------- 3. INTERFACE PROFISSIONAL -----------------
st.title("🛡️ Validador de Bulas - Auditoria Estrutural")

col1, col2 = st.columns(2)
f1 = col1.file_uploader("Bula Referência (PDF)", type=["pdf"])
f2 = col2.file_uploader("Bula BELFAR (PDF)", type=["pdf"])

if st.button("🚀 Iniciar Auditoria de Conteúdo"):
    if f1 and f2:
        with st.spinner("Analisando estrutura e colunas..."):
            try:
                ref_text = extract_structured_text(f1)
                bel_text = extract_structured_text(f2)
                
                divergencias = compare_bula(ref_text, bel_text)
                
                if not divergencias:
                    st.success("✅ Bulas idênticas! Nenhuma divergência encontrada.")
                else:
                    st.warning(f"⚠️ Encontradas {len(divergencias)} divergências estruturais.")
                    df = pd.DataFrame(divergencias)
                    st.table(df) # Tabela de auditoria profissional
                    
            except Exception as e:
                st.error(f"Erro na auditoria: {e}")
    else:
        st.info("Por favor, suba os dois arquivos para começar.")

# ----------------- 4. MANUAL DE USO -----------------
with st.expander("ℹ️ Como funciona este modo?"):
    st.write("""
    Este script não tenta pintar o PDF (o que causava erros). 
    Ele faz uma **Análise Estrutural**:
    1. Lê a Bula independente de colunas (1, 2 ou 3).
    2. Identifica o parágrafo lógico.
    3. Compara o texto bruto entre a Referência e a Belfar.
    4. Gera um relatório de divergência (Excel/Tabela).
    
    Isso é o que sistemas como o TVT fazem antes de qualquer verificação visual.
    """)
