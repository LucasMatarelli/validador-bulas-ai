import streamlit as st

# ----------------- CONFIGURAÇÃO DA PÁGINA (HOME) -----------------
st.set_page_config(
    page_title="Validador de Bulas",
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
        display: flex;
        flex-direction: column;
        justify-content: space-between;
    }
    .module-card:hover {
        transform: translateY(-5px);
        box-shadow: 0 8px 15px rgba(0,0,0,0.1);
        border-color: #55a68e;
    }
    
    /* Texto do cartão */
    .card-text {
        font-size: 0.95rem;
        color: #555;
        line-height: 1.5;
        margin-bottom: 15px;
        text-align: justify;
    }

    /* Detalhe técnico (curvas) */
    .tech-detail {
        font-size: 0.85rem;
        color: #666;
        background-color: #f8f9fa;
        padding: 10px;
        border-radius: 6px;
        margin-top: 10px;
        border-left: 3px solid #ccc;
    }

    /* Badges de Status */
    .badge {
        display: inline-block;
        padding: 4px 8px;
        border-radius: 4px;
        font-size: 0.8em;
        font-weight: bold;
        margin-top: 15px;
        width: fit-content;
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
    st.title("Validador de Bulas")
    st.caption("IA para validação de bulas")

st.divider()

# Grid de Módulos
col1, col2, col3 = st.columns(3, gap="medium")

# --- CARD 1: REFERÊNCIA X BELFAR ---
with col1:
    st.markdown("""
    <div class="module-card">
        <div>
            <div class="icon-large">💊</div>
            <h3>Medicamento Referência x BELFAR</h3>
            <div class="card-text">
                Compara a bula de referência com a bula BELFAR. Aponta as diferenças entre as duas com marca-texto amarelo, possíveis erros de português em rosa e a data da ANVISA em azul.
            </div>
        </div>
        <div class="badge badge-stable">gemni-lite</div>
    </div>
    """, unsafe_allow_html=True)

# --- CARD 2: CONFERÊNCIA MKT ---
with col2:
    st.markdown("""
    <div class="module-card">
        <div>
            <div class="icon-large">📋</div>
            <h3>Conferência MKT (Word/PDF vs PDF)</h3>
            <div class="card-text">
                Compara o arquivo da ANVISA (.docx ou .pdf) com o PDF final do Marketing. Aponta as diferenças entre os documentos em amarelo, possíveis erros de português em rosa e a data da ANVISA em azul.
            </div>
        </div>
        <div class="badge badge-new">gemni-lite</div>
    </div>
    """, unsafe_allow_html=True)

# --- CARD 3: GRÁFICA X ARTE ---
with col3:
    st.markdown("""
    <div class="module-card">
        <div>
            <div class="icon-large">🎨</div>
            <h3>Gráfica x Arte Vigente</h3>
            <div class="card-text">
                Compara o PDF da Gráfica (frequentemente 'em curva') com o PDF da Arte Vigente. O sistema lê ambos os arquivos e aponta as diferenças em amarelo, erros em rosa e a data da ANVISA em azul.
            </div>
            <div class="tech-detail">
                <strong>O que é um arquivo 'em curva'?</strong><br>
                É um PDF onde o texto virou vetor (imagem). Visualmente é texto, mas o computador vê apenas formas geométricas, exigindo OCR.
            </div>
        </div>
        <div class="badge badge-beta">gemni-lite</div>
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
