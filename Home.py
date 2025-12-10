import streamlit as st
from utils import get_mistral_client

st.set_page_config(
    page_title="Validador de Bulas",
    page_icon="💊",
    layout="wide"
)

# --- CSS GLOBAL ---
st.markdown("""
<style>
    /* Oculta barra superior */
    header[data-testid="stHeader"] { display: none !important; }
    .main .block-container { padding-top: 20px !important; }
    h1 { color: #55a68e; font-family: 'Segoe UI', sans-serif; }
    .stButton>button { width: 100%; border-radius: 10px; height: 50px; background-color: #55a68e; color: white; }
</style>
""", unsafe_allow_html=True)

st.title("Validador de Bulas")
st.markdown("### Selecione o tipo de auditoria no menu lateral 👈")

client = get_mistral_client()
if client:
    st.success("✅ Sistema Online e Pronto para uso.")
else:
    st.error("❌ Erro: Configure a API KEY no secrets ou variáveis de ambiente.")

c1, c2, c3 = st.columns(3)
with c1:
    st.info("**💊 Ref x Belfar**\n\nComparação padrão de bulas Paciente/Profissional.")
with c2:
    st.info("**📋 Anvisa x MKT**\n\nConferência de textos regulatórios.")
with c3:
    st.info("**🎨 Arte x Gráfica**\n\nValidação de layout e conteúdo final.")
