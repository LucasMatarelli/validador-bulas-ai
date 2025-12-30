import streamlit as st
import google.generativeai as genai

st.title("🕵️ Diagnóstico de Modelos Gemini")

# Pega a chave dos secrets
api_key = st.secrets.get("GEMINI_API_KEY")

if not api_key:
    st.error("Sem chave API configurada.")
else:
    genai.configure(api_key=api_key)
    
    st.write("Versão da biblioteca instalada:", genai.__version__)
    
    st.write("### Tentando listar modelos disponíveis para sua chave...")
    
    try:
        modelos = genai.list_models()
        encontrados = []
        for m in modelos:
            if 'generateContent' in m.supported_generation_methods:
                encontrados.append(m.name)
        
        if encontrados:
            st.success(f"✅ Encontrei {len(encontrados)} modelos disponíveis:")
            st.json(encontrados)
            st.info("Copie um desses nomes exatos e coloque na lista 'MODELOS_PARA_TENTAR' do seu código principal.")
        else:
            st.warning("A API conectou, mas não retornou nenhum modelo de geração de texto. Verifique se a API 'Generative Language API' está ativada no Google Cloud Console.")
            
    except Exception as e:
        st.error("❌ Erro ao listar modelos:")
        st.code(str(e))
