import streamlit as st

st.set_page_config(
    page_title="Sistema de Auditoria Belfar",
    page_icon="🏥",
    layout="wide"
)

st.title("🏥 Sistema Central de Auditoria")
st.markdown("""
### Bem-vindo ao Validador Inteligente

Selecione o módulo desejado no menu lateral:

1.  **💊 Med. Referência x BELFAR**: Comparação de texto puro (Algoritmo v21.9).
2.  **📋 Conferência MKT**: Validação de estrutura e conteúdo (Algoritmo v107).
3.  **🎨 Gráfica x Arte**: Comparação Visual usando **Gemini 2.0 Flash Lite** (Visão Computacional).

---
*Desenvolvido para garantir a segurança e conformidade das bulas.*
""")
