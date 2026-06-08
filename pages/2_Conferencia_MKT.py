import streamlit as st
import fitz
import re
import unicodedata
from difflib import SequenceMatcher
import pandas as pd

# Lista padrão de cabeçalhos de bula que devem existir
TOPICOS_OBRIGATORIOS = [
    "identificação do medicamento", "apresentações", "composição", 
    "informações ao paciente", "para que este medicamento é indicado", 
    "como este medicamento funciona", "quando não devo usar", 
    "o que devo saber antes", "como devo usar", 
    "o que devo fazer quando eu me esquecer", "quais os males", 
    "o que fazer se alguém usar", "dizeres legais"
]

def clean_text(text):
    text = unicodedata.normalize('NFKD', text).lower()
    return re.sub(r'[^\w\s]', '', text).strip()

def check_structure(text_list):
    """Verifica quais tópicos obrigatórios estão presentes no texto."""
    found = []
    full_text = " ".join(text_list)
    for topico in TOPICOS_OBRIGATORIOS:
        if topico in full_text:
            found.append(topico)
    return found

st.set_page_config(layout="wide")
st.title("🛡️ Validador Belfar - Nível Enterprise")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("Bula Referência", type=["pdf"])
f2 = c2.file_uploader("Bula BELFAR/MKT", type=["pdf"])

if f1 and f2:
    doc_ref = fitz.open("pdf", f1.getvalue())
    doc_bel = fitz.open("pdf", f2.getvalue())
    
    if st.button("🚀 Iniciar Auditoria Completa (Estrutura + Conteúdo)"):
        # 1. Auditoria de Estrutura
        t1 = [clean_text(w) for p in doc_ref for w in p.get_text("text").split()]
        t2 = [clean_text(w) for p in doc_bel for w in p.get_text("text").split()]
        
        struct_ref = check_structure(t1)
        struct_bel = check_structure(t2)
        
        st.subheader("📊 Auditoria de Estrutura (Tópicos)")
        col_a, col_b = st.columns(2)
        col_a.write("Tópicos na Referência: " + str(len(struct_ref)))
        col_b.write("Tópicos na BELFAR: " + str(len(struct_bel)))
        
        # Mostra o que falta
        faltantes = [t for t in TOPICOS_OBRIGATORIOS if t not in struct_bel]
        if faltantes:
            st.error(f"⚠️ A Bula BELFAR está sem estes tópicos: {', '.join(faltantes)}")
        else:
            st.success("✅ Todos os tópicos obrigatórios estão presentes!")

        # 2. Auditoria de Conteúdo (Divergências)
        st.subheader("🔍 Divergências de Conteúdo")
        matcher = SequenceMatcher(None, t1, t2)
        divergencias = []
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag != 'equal':
                divergencias.append({"Referência": " ".join(t1[i1:i2]), "BELFAR": " ".join(t2[j1:j2])})
        
        if divergencias:
            st.table(pd.DataFrame(divergencias).head(20)) # Mostra as primeiras 20 divergências
        else:
            st.success("✅ Conteúdo idêntico!")
