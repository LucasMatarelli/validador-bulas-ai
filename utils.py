import streamlit as st
import json
import os
from datetime import datetime
import google.generativeai as genai

# --- CONFIGURAÇÕES GERAIS ---
ARQUIVO_CONTADOR = "contador_diario.json"
LIMITE_POR_KEY = 20
LIMITE_TOTAL = 40  # 20 da Key 1 + 20 da Key 2

def gerenciar_uso_diario(incrementar=False):
    """Lê, reseta se mudou o dia e incrementa se pedido."""
    hoje = datetime.now().strftime("%Y-%m-%d")
    
    # Garante que arquivo existe
    if not os.path.exists(ARQUIVO_CONTADOR):
        dados = {"data": hoje, "contagem": 0}
        with open(ARQUIVO_CONTADOR, "w") as f: json.dump(dados, f)
    else:
        with open(ARQUIVO_CONTADOR, "r") as f:
            try: dados = json.load(f)
            except: dados = {"data": hoje, "contagem": 0}

    # Reseta se for outro dia
    if dados["data"] != hoje:
        dados = {"data": hoje, "contagem": 0}
        with open(ARQUIVO_CONTADOR, "w") as f: json.dump(dados, f)
        
    # Incrementa (apenas se a função foi chamada para isso)
    if incrementar and dados["contagem"] < LIMITE_TOTAL:
        dados["contagem"] += 1
        with open(ARQUIVO_CONTADOR, "w") as f: json.dump(dados, f)
        
    return dados["contagem"]

def mostrar_sidebar_contador():
    """Mostra o visual na barra lateral em QUALQUER página."""
    uso_atual = gerenciar_uso_diario(incrementar=False)
    restantes = LIMITE_TOTAL - uso_atual
    
    st.sidebar.image("https://cdn-icons-png.flaticon.com/512/3004/3004458.png", width=50)
    st.sidebar.title("Auditoria IA")
    st.sidebar.divider()

    if restantes > 0:
        st.sidebar.success(f"✅ Status: **ONLINE**")
        
        # Lógica visual das chaves
        chave_em_uso = "Principal (1)" if uso_atual < 20 else "Reserva (2)"
        
        st.sidebar.info(f"🔢 Uso Hoje: **{uso_atual}/{LIMITE_TOTAL}**")
        st.sidebar.caption(f"🔑 Chave Ativa: {chave_em_uso}")
        
        # Barra de progresso
        progresso = uso_atual / LIMITE_TOTAL
        st.sidebar.progress(progresso)
    else:
        st.sidebar.error("⛔ Limite Diário (40) Atingido")
        st.sidebar.warning("O sistema voltará amanhã.")

    st.sidebar.divider()
    st.sidebar.caption("v21.9 • Belfar Farmacêutica")

def configurar_modelo_inteligente():
    """Seleciona a Key 1 ou Key 2 dependendo do uso."""
    uso_atual = gerenciar_uso_diario(incrementar=False)
    
    if uso_atual >= LIMITE_TOTAL:
        return None # Bloqueado
    
    # TROCA DE CHAVES AUTOMÁTICA
    if uso_atual < LIMITE_POR_KEY:
        chave = st.secrets.get("GEMINI_API_KEY") # 0 a 19
    else:
        chave = st.secrets.get("GEMINI_API_KEY2") # 20 a 39
        
    if not chave:
        st.error("Erro: Chave de API não encontrada nos secrets.")
        return None

    genai.configure(api_key=chave)
    return genai.GenerativeModel(
        "models/gemini-1.5-flash", 
        generation_config={"response_mime_type": "application/json", "temperature": 0.0}
    )
