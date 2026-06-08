import streamlit as st
import re
import fitz
from difflib import SequenceMatcher
import pandas as pd

# Tópicos padronizados da ANVISA para ancoragem
TOPICOS = [
    r"1\. PARA QUE ESTE MEDICAMENTO É INDICADO",
    r"2\. COMO ESTE MEDICAMENTO FUNCIONA",
    r"3\. QUANDO NÃO DEVO USAR ESTE MEDICAMENTO",
    r"4\. O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO",
    r"5\. ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO",
    r"6\. COMO DEVO USAR ESTE MEDICAMENTO",
    r"7\. O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO",
    r"8\. QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR",
    r"9\. O QUE FAZER SE ALGUÉM USAR UMA QUANTIDADE MAIOR"
]

def extract_sections(pdf_file):
    """Fatia o PDF em um dicionário de tópicos."""
    doc = fitz.open("pdf", pdf_file.getvalue())
    full_text = ""
    for page in doc:
        full_text += page.get_text("text") + " "
    
    sections = {}
    
    # Busca cada tópico no texto
    for i in range(len(TOPICOS)):
        pattern = TOPICOS[i]
        # Regex para capturar tudo entre o tópico atual e o próximo
        next_pattern = TOPICOS[i+1] if i+1 < len(TOPICOS) else r"DIZERES LEGAIS"
        regex = f"{pattern}(.*?){next_pattern}"
        match = re.search(regex, full_text, re.DOTALL | re.IGNORECASE)
        
        if match:
            sections[pattern.replace(r"\\.", ".")] = match.group(1).strip()
    
    return sections

# UI de Auditoria
st.title("🛡️ Validador de Estrutura e Conteúdo")
c1, c2 = st.columns(2)
f1 = c1.file_uploader("Referência", type=["pdf"])
f2 = c2.file_uploader("BELFAR", type=["pdf"])

if st.button("🚀 Auditar Tópicos e Conteúdo"):
    s1 = extract_sections(f1)
    s2 = extract_sections(f2)
    
    # 1. Auditoria de Estrutura
    st.subheader("📊 Auditoria de Estrutura")
    missing_in_bel = [t for t in s1.keys() if t not in s2.keys()]
    
    if missing_in_bel:
        st.error(f"Tópicos faltando na BELFAR: {missing_in_bel}")
    else:
        st.success("Estrutura de tópicos validada!")

    # 2. Auditoria de Conteúdo (Dentro de cada tópico)
    st.subheader("🔍 Divergências de Conteúdo")
    for topic, content in s1.items():
        if topic in s2:
            # Compara apenas o conteúdo daquele tópico específico
            matcher = SequenceMatcher(None, content, s2[topic])
            if matcher.ratio() < 0.9: # Se a similaridade for baixa
                st.warning(f"Divergência detectada em: {topic}")
                # Exibe resumo da divergência
                st.write(f"Similaridade: {matcher.ratio():.2f}")
