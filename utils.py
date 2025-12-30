import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
import docx
import io
import json
import os
import re
import difflib
import unicodedata
from PIL import Image
from datetime import datetime
from spellchecker import SpellChecker

# --- CONFIGURAÇÕES DE CSS (Incluindo o Vermelho) ---
def injetar_css():
    st.markdown("""
    <style>
        .texto-box { 
            font-family: 'Segoe UI', sans-serif;
            font-size: 0.95rem;
            line-height: 1.6;
            color: #212529;
            background-color: #ffffff;
            padding: 20px;
            border-radius: 8px;
            border: 1px solid #ced4da;
            white-space: pre-wrap; 
        }
        
        /* DIVERGÊNCIA (Amarelo) - Texto diferente entre os arquivos */
        .highlight-yellow { 
            background-color: #fff3cd; color: #856404; 
            padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; 
            font-weight: bold;
        }
        
        /* ERRO DE PORTUGUÊS (Vermelho) - Identificado pelo Corretor */
        .highlight-red { 
            background-color: #f8d7da; color: #721c24; 
            padding: 2px 4px; border-radius: 4px; border: 1px solid #f5c6cb; 
            text-decoration: underline wavy #dc3545;
        }
        
        /* DATA (Azul) */
        .highlight-blue { 
            background-color: #d1ecf1; color: #0c5460; 
            padding: 2px 4px; border-radius: 4px; border: 1px solid #bee5eb; font-weight: bold; 
        }
    </style>
    """, unsafe_allow_html=True)

# --- FUNÇÕES DE LIMPEZA E COMPARAÇÃO ---

def normalizar_para_comparacao(texto):
    """
    Remove sujeira invisível que causa falsos positivos (como no 'As infecções').
    """
    if not texto: return ""
    # 1. Normaliza Unicode (junta acentos separados 'a'+'~' vira 'ã')
    texto = unicodedata.normalize('NFC', texto)
    # 2. Remove espaços não separáveis (\xa0) e outros caracteres invisíveis
    texto = texto.replace('\xa0', ' ').replace('\u200b', '')
    # 3. Remove espaços duplicados
    texto = re.sub(r'\s+', ' ', texto)
    return texto.strip()

def verificar_ortografia(texto_html):
    """
    Passa um pente fino no texto para achar erros de português (Vermelho).
    Ignora tags HTML já existentes.
    """
    try:
        spell = SpellChecker(language='pt')
        # Regex para separar palavras ignorando tags HTML (<...>)
        tokens = re.split(r'(<[^>]+>|[^a-zA-ZáàâãéèêíïóôõöúçñÁÀÂÃÉÈÊÍÏÓÔÕÖÚÇÑ]+)', texto_html)
        
        novo_texto = []
        for token in tokens:
            # Se for tag HTML ou pontuação/espaço, mantém
            if token.startswith('<') or not token.strip() or len(token) < 3:
                novo_texto.append(token)
                continue
            
            # Verifica se a palavra existe no dicionário
            # (Limpeza simples para o corretor não pegar pontuação colada)
            palavra_limpa = token.strip()
            if palavra_limpa.lower() not in spell:
                # É um erro provável -> Marca de VERMELHO
                novo_texto.append(f'<span class="highlight-red" title="Possível erro">{token}</span>')
            else:
                novo_texto.append(token)
                
        return "".join(novo_texto)
    except:
        return texto_html # Se der erro no spellchecker, devolve original

def gerar_diff_html(texto_ref, texto_novo):
    """
    Gera o HTML comparativo.
    - Amarelo: Diferença entre Arte e Gráfica.
    - Vermelho: Erro de português (apenas no texto NOVO).
    """
    # 1. Normalização para evitar o erro do "As infecções"
    ref_norm = normalizar_para_comparacao(texto_ref)
    novo_norm = normalizar_para_comparacao(texto_novo)
    
    # Se depois de limpar tudo for igual, retorna sem amarelo
    if ref_norm == novo_norm:
        # Ainda passamos o corretor (vermelho) no texto novo
        html_final = verificar_ortografia(texto_novo)
        return texto_ref, html_final, False

    # 2. Prepara para o Difflib (tokenização por quebras de linha artificiais para manter estrutura)
    a = texto_ref.splitlines()
    b = texto_novo.splitlines()
    
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    
    html_ref = []
    html_novo = []
    tem_divergencia = False

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        trecho_a = "\n".join(a[i1:i2])
        trecho_b = "\n".join(b[j1:j2])
        
        if tag == 'equal':
            html_ref.append(trecho_a)
            # Verifica ortografia mesmo no texto igual
            html_novo.append(verificar_ortografia(trecho_b))
            
        elif tag == 'replace':
            # AQUI ESTÁ A CORREÇÃO PRINCIPAL:
            # Verifica se a diferença é só sujeira invisível
            if normalizar_para_comparacao(trecho_a) == normalizar_para_comparacao(trecho_b):
                html_ref.append(trecho_a)
                html_novo.append(verificar_ortografia(trecho_b))
            else:
                # Diferença real -> AMARELO
                html_ref.append(f'<span class="highlight-yellow">{trecho_a}</span>')
                html_novo.append(f'<span class="highlight-yellow">{trecho_b}</span>')
                tem_divergencia = True
                
        elif tag == 'delete':
            html_ref.append(f'<span class="highlight-yellow">{trecho_a}</span>')
            tem_divergencia = True
            
        elif tag == 'insert':
            html_novo.append(f'<span class="highlight-yellow">{trecho_b}</span>')
            tem_divergencia = True

    final_ref = "\n".join(html_ref).replace("\n", "<br>")
    final_novo = "\n".join(html_novo).replace("\n", "<br>")
    
    return final_ref, final_novo, tem_divergencia

# ... (Mantenha o resto das funções: gerenciar_uso_diario, processar_arquivo, etc.) ...
