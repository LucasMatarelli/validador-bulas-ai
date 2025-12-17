import streamlit as st

# ----------------- CONFIGURAÇÃO DA PÁGINA (HOME) -----------------
st.set_page_config(
    page_title="Central de Auditoria Belfar",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- ESTILOS CSS (VISUAL PREMIUM) -----------------
st.markdown("""
<style>
    /* Remove cabeçalho padrão chato */
    header[data-testid="stHeader"] { display: none !important; }
    
    /* Fundo e tipografia */
    .main { background-color: #f4f6f8; font-family: 'Segoe UI', sans-serif; }
    
    /* Títulos */
    h1 { color: #2c3e50; font-weight: 700; }
    h2, h3 { color: #34495e; }
    
    /* Cartões de Módulo */
    .module-card {
        background-color: white;
        padding: 25px;
        border-radius: 12px;
        border: 1px solid #e1e4e8;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        transition: transform 0.2s, box-shadow 0.2s;
        height: 100%;
    }
    .module-card:hover {
        transform: translateY(-5px);
        box-shadow: 0 8px 15px rgba(0,0,0,0.1);
        border-color: #55a68e;
    }
    
    /* Badges de Status */
    .badge {
        display: inline-block;
        padding: 4px 8px;
        border-radius: 4px;
        font-size: 0.8em;
        font-weight: bold;
        margin-top: 10px;
    }
    .badge-stable { background-color: #e3f2fd; color: #1565c0; border: 1px solid #90caf9; } /* Azul */
    .badge-new { background-color: #e8f5e9; color: #2e7d32; border: 1px solid #a5d6a7; } /* Verde */
    .badge-beta { background-color: #fff3e0; color: #ef6c00; border: 1px solid #ffe0b2; } /* Laranja */
    
    /* Ícones grandes */
    .icon-large { font-size: 3rem; margin-bottom: 15px; display: block; text-align: center; }
    
    /* Sidebar */
    [data-testid="stSidebar"] { background-color: #ffffff; border-right: 1px solid #eee; }
</style>
""", unsafe_allow_html=True)

# ----------------- UI PRINCIPAL -----------------

# Cabeçalho
c_logo, c_title = st.columns([1, 5])
with c_logo:
    st.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=80)
with c_title:
    st.title("Sistema Central de Auditoria")
    st.caption("Controle de Qualidade Farmacêutica Inteligente")

st.divider()

# Grid de Módulos
col1, col2, col3 = st.columns(3, gap="medium")

with col1:
    st.markdown("""
    <div class="module-card">
        <div class="icon-large">💊</div>
        <h3>Med. Referência x BELFAR</h3>
        <p>Comparação algorítmica de texto puro.</p>
        <ul>
            <li>Extração PDF/Word</li>
            <li>Checagem de Seções</li>
            <li>Conformidade ANVISA</li>
        </ul>
        <div class="badge badge-stable">v21.9 • Estável</div>
    </div>
    """, unsafe_allow_html=True)

with col2:
    st.markdown("""
    <div class="module-card">
        <div class="icon-large">📋</div>
        <h3>Conferência MKT</h3>
        <p>Validação estrutural e ortográfica avançada.</p>
        <ul>
            <li>Motor Híbrido (Mistral AI)</li>
            <li>Detecção de Erros PT-BR</li>
            <li>Análise de Contexto</li>
        </ul>
        <div class="badge badge-new">v107 • IA Híbrida</div>
    </div>
    """, unsafe_allow_html=True)

with col3:
    st.markdown("""
    <div class="module-card">
        <div class="icon-large">🎨</div>
        <h3>Gráfica x Arte</h3>
        <p>Conferência visual de pré-impressão.</p>
        <ul>
            <li>Visão Computacional (Gemini)</li>
            <li>Layout, Fontes e Cores</li>
            <li>OCR de Alta Resolução</li>
        </ul>
        <div class="badge badge-beta">IA Visual • Gemini Flash</div>
    </div>
    """, unsafe_allow_html=True)

st.divider()

# Instrução de Uso
st.info("👈 **Para começar, selecione um dos módulos no menu lateral à esquerda.**")

# Rodapé Discreto
st.markdown("""
<div style="text-align: center; color: #999; font-size: 0.8em; margin-top: 50px;">
    Sistema Interno de Qualidade • Desenvolvido para Segurança do Paciente
</div>
""", unsafe_allow_html=True)
