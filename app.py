import dash
from dash import dcc, html, Input, Output, State, callback_context, no_update
import dash_bootstrap_components as dbc
import google.generativeai as genai
import fitz  # PyMuPDF
import docx
import io
import base64
import json
import re
from PIL import Image

# ----------------- CONFIGURAÇÃO -----------------
FIXED_API_KEY = "AIzaSyB3ctao9sOsQmAylMoYni_1QvgZFxJ02tw"

# Inicializa o App com tema MINTY (Verde/Clean)
app = dash.Dash(
    __name__, 
    external_stylesheets=[dbc.themes.MINTY, "https://use.fontawesome.com/releases/v6.4.0/css/all.css"],
    title="Validador Belfar",
    suppress_callback_exceptions=True,
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}]
)
server = app.server

# ----------------- ESTILOS PERSONALIZADOS (VERDE) -----------------
COLOR_PRIMARY = "#55a68e"  # Verde do seu print
COLOR_BG = "#ffffff"

STYLES = {
    'upload_box': {
        'borderWidth': '2px', 'borderStyle': 'dashed', 'borderRadius': '12px',
        'borderColor': '#dee2e6', 'backgroundColor': '#f8f9fa',
        'padding': '30px', 'textAlign': 'center', 'cursor': 'pointer',
        'minHeight': '180px', 'display': 'flex', 'flexDirection': 'column', 
        'justifyContent': 'center', 'alignItems': 'center',
        'transition': 'all 0.2s ease-in-out'
    },
    'upload_box_active': {
        'borderColor': COLOR_PRIMARY, 'backgroundColor': '#e6fffa',
    },
    'file_card': {
        'border': f'2px solid {COLOR_PRIMARY}', 'borderRadius': '12px',
        'padding': '20px', 'textAlign': 'center', 'backgroundColor': '#fff',
        'minHeight': '180px', 'display': 'flex', 'flexDirection': 'column',
        'justifyContent': 'center', 'alignItems': 'center'
    },
    'bula_box': {
        'height': '400px', 'overflowY': 'auto', 'border': '1px solid #e9ecef',
        'borderRadius': '8px', 'padding': '25px', 'backgroundColor': '#ffffff',
        'fontFamily': '"Georgia", serif', 'fontSize': '15px', 'lineHeight': '1.7',
        'color': '#212529', 'boxShadow': 'inset 0 2px 4px rgba(0,0,0,0.02)'
    },
    'btn_primary': {
        'backgroundColor': COLOR_PRIMARY, 'border': 'none', 'fontWeight': 'bold',
        'padding': '15px', 'borderRadius': '8px', 'fontSize': '18px',
        'width': '100%', 'boxShadow': '0 4px 6px rgba(0,0,0,0.1)', 'color': 'white'
    }
}

# ----------------- BACKEND (IA & ARQUIVOS) -----------------

def get_best_model():
    """Descobre qual modelo sua chave aceita (Corrige o erro 404)."""
    try:
        genai.configure(api_key=FIXED_API_KEY)
        # Tenta listar modelos disponíveis para a chave
        available = [m.name for m in genai.list_models()]
        
        # Lista de preferência (Do mais novo para o mais antigo)
        preferencias = [
            'models/gemini-2.5-flash', 
            'models/gemini-2.0-flash', 
            'models/gemini-2.0-flash-001',
            'models/gemini-1.5-pro',
            'models/gemini-1.5-flash'
        ]
        
        # Tenta encontrar o melhor da lista
        for pref in preferencias:
            if pref in available:
                return genai.GenerativeModel(pref)
        
        # Se não achou nenhum específico, tenta qualquer um que seja 'gemini'
        for model_name in available:
            if 'gemini' in model_name and 'vision' not in model_name:
                return genai.GenerativeModel(model_name)

        return genai.GenerativeModel('models/gemini-1.5-flash') # Fallback final
        
    except Exception as e:
        print(f"Erro ao conectar API: {e}")
        return None

def process_file(contents, filename):
    if not contents: return None
    try:
        _, content_string = contents.split(',')
        decoded = base64.b64decode(content_string)
        
        if filename.lower().endswith('.docx'):
            doc = docx.Document(io.BytesIO(decoded))
            text = "\n".join([p.text for p in doc.paragraphs])
            return {"type": "text", "data": text}
            
        elif filename.lower().endswith('.pdf'):
            doc = fitz.open(stream=decoded, filetype="pdf")
            images = []
            # OTIMIZAÇÃO CRÍTICA: Limita a 6 páginas e reduz qualidade para evitar TIMEOUT
            for i in range(min(6, len(doc))):
                page = doc[i]
                pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
                img_byte_arr = io.BytesIO(pix.tobytes("jpeg"))
                images.append(Image.open(img_byte_arr))
            return {"type": "images", "data": images}
    except Exception as e:
        return None
    return None

def clean_json(text):
    text = text.replace("```json", "").replace("```", "").strip()
    text = re.sub(r'//.*', '', text)
    if text.startswith("json"): text = text[4:]
    return text

# ----------------- COMPONENTES VISUAIS -----------------

def build_upload_area(id_upload, id_filename, id_clear, label):
    return html.Div([
        html.H6([html.I(className="far fa-file-alt me-2 text-muted"), label], className="fw-bold mb-2"),
        
        # Container que troca entre Upload e Arquivo Carregado
        html.Div([
            # 1. Estado Vazio (Dropzone)
            html.Div(
                id=f"{id_upload}-container",
                children=dcc.Upload(
                    id=id_upload,
                    children=html.Div([
                        html.I(className="fas fa-cloud-upload-alt fa-3x", style={"color": "#adb5bd"}),
                        html.H6("Arraste ou Clique", className="mt-3 text-muted fw-bold")
                    ]),
                    style=STYLES['upload_box'],
                    multiple=False
                ),
                style={"display": "block"} 
            ),
            
            # 2. Estado Preenchido (Card com Nome e Botão X)
            html.Div(
                id=f"{id_upload}-success-container",
                children=[
                    html.Div([
                        html.I(className="fas fa-check-circle fa-4x text-success mb-3"),
                        html.H6(id=id_filename, className="text-success fw-bold text-break mb-3"),
                        
                        # Botão Remover
                        dbc.Button(
                            [html.I(className="fas fa-trash-alt me-2"), "Remover Arquivo"],
                            id=id_clear,
                            color="danger",
                            outline=True,
                            size="sm",
                            className="rounded-pill px-3"
                        )
                    ], style=STYLES['file_card'])
                ],
                style={"display": "none"} # Inicialmente invisível
            )
        ])
    ])

# ----------------- LAYOUT GERAL -----------------

sidebar = html.Div([
    html.Div([
        html.I(className="fas fa-shield-alt fa-2x mb-2", style={"color": COLOR_PRIMARY}),
        html.H3("Validador", className="fw-bold text-dark")
    ], className="text-center py-5"),
    
    dbc.Nav([
        dbc.NavLink([html.I(className="fas fa-home w-25"), "Início"], href="/", active="exact", className="py-3 fw-bold text-secondary"),
        dbc.NavLink([html.I(className="fas fa-pills w-25"), "Ref x Belfar"], href="/ref-bel", active="exact", className="py-3 fw-bold text-secondary"),
        dbc.NavLink([html.I(className="fas fa-file-contract w-25"), "Conferência MKT"], href="/mkt", active="exact", className="py-3 fw-bold text-secondary"),
        dbc.NavLink([html.I(className="fas fa-print w-25"), "Gráfica x Arte"], href="/graf", active="exact", className="py-3 fw-bold text-secondary"),
    ], vertical=True, pills=True, className="px-3"),
], style={"position": "fixed", "top": 0, "left": 0, "bottom": 0, "width": "260px", "backgroundColor": "#fff", "borderRight": "1px solid #f0f0f0", "zIndex": 100})

def build_tool_page(title, subtitle, scenario_id):
    # Seletor de Tipo (Pills Verdes)
    options_div = html.Div()
    if scenario_id == "1":
        options_div = dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col(html.Label("Selecione o Tipo de Bula:", className="fw-bold mt-2 text-end"), width="auto"),
                    dbc.Col(
                        dbc.RadioItems(
                            options=[
                                {"label": "Paciente", "value": "PACIENTE"},
                                {"label": "Profissional", "value": "PROFISSIONAL"},
                            ],
                            value="PACIENTE",
                            id="radio-tipo-bula",
                            inline=True,
                            className="btn-group-radio-green", # Classe customizada se quiser CSS extra
                            inputClassName="btn-check",
                            labelClassName="btn btn-outline-success px-4 rounded-pill fw-bold me-2",
                            labelCheckedClassName="active bg-success text-white"
                        )
                    )
                ], className="justify-content-center align-items-center")
            ])
        ], className="mb-5 shadow-sm border-0 rounded-pill py-2 bg-white")

    return dbc.Container([
        # options_div vem antes ou depois do título? No seu print é antes.
        options_div,

        dbc.Row([
            dbc.Col(build_upload_area("upload-1", "name-1", "clear-1", "Documento Referência / Padrão"), md=6, className="mb-4"),
            dbc.Col(build_upload_area("upload-2", "name-2", "clear-2", "Documento Belfar / Candidato"), md=6, className="mb-4"),
        ]),
        
        html.Div([
            dbc.Button(
                [html.I(className="fas fa-rocket me-2"), "INICIAR AUDITORIA COMPLETA"],
                id="btn-run",
                style=STYLES['btn_primary'],
                className="hover-scale"
            )
        ], className="mt-4 mb-5"),
        
        dcc.Loading(id="loading", type="dot", color=COLOR_PRIMARY, children=html.Div(id="output-results")),
        dcc.Store(id="scenario-store", data=scenario_id)
    ], fluid=True, className="py-4")

# ----------------- APP -----------------
app.layout = html.Div([
    dcc.Location(id="url", refresh="callback-nav"), 
    sidebar,
    html.Div(id="page-content", style={"marginLeft": "260px", "padding": "3rem", "backgroundColor": "#f8f9fa", "minHeight": "100vh"})
])

# ----------------- CALLBACKS -----------------

@app.callback(Output("page-content", "children"), [Input("url", "pathname")])
def render_page(pathname):
    if pathname == "/ref-bel": return build_tool_page("Ref x Belfar", "", "1")
    elif pathname == "/mkt": return build_tool_page("Conferência MKT", "", "2")
    elif pathname == "/graf": return build_tool_page("Gráfica x Arte", "", "3")
    
    # Home Page
    return dbc.Container([
        html.Div(className="text-center py-5", children=[
            html.I(className="fas fa-microscope fa-4x mb-3", style={"color": COLOR_PRIMARY}),
            html.H1("Validador Inteligente", className="display-4 fw-bold text-dark"),
            html.P("Selecione uma ferramenta abaixo para começar.", className="lead text-muted")
        ]),
        dbc.Row([
            dbc.Col(dbc.Card([dbc.CardBody([html.H4("Ref x Belfar", className="fw-bold"), dbc.Button("Acessar", href="/ref-bel", style={"backgroundColor": COLOR_PRIMARY, "border":"none"}, className="mt-3 w-100")])], className="shadow-sm border-0 h-100 p-4 text-center"), md=4),
            dbc.Col(dbc.Card([dbc.CardBody([html.H4("Conferência MKT", className="fw-bold"), dbc.Button("Acessar", href="/mkt", style={"backgroundColor": COLOR_PRIMARY, "border":"none"}, className="mt-3 w-100")])], className="shadow-sm border-0 h-100 p-4 text-center"), md=4),
            dbc.Col(dbc.Card([dbc.CardBody([html.H4("Gráfica x Arte", className="fw-bold"), dbc.Button("Acessar", href="/graf", style={"backgroundColor": COLOR_PRIMARY, "border":"none"}, className="mt-3 w-100")])], className="shadow-sm border-0 h-100 p-4 text-center"), md=4),
        ])
    ])

# Callback Genérico de Upload (Gerencia estados Vazio/Preenchido)
def manage_upload_state(contents, filename, n_clear):
    ctx = callback_context
    if not ctx.triggered: 
        return no_update, no_update, no_update, no_update
    
    trig_id = ctx.triggered[0]['prop_id'].split('.')[0]
    
    # Se clicou em limpar
    if 'clear' in trig_id:
        return None, "", {"display": "block"}, {"display": "none"}
    
    # Se fez upload
    if contents:
        return contents, filename, {"display": "none"}, {"display": "block"}
        
    return no_update, no_update, no_update, no_update

@app.callback(
    [Output("upload-1", "contents"), Output("name-1", "children"),
     Output("upload-1-container", "style"), Output("upload-1-success-container", "style")],
    [Input("upload-1", "contents"), Input("clear-1", "n_clicks")],
    [State("upload-1", "filename")]
)
def update_u1(c, n_clear, n): return manage_upload_state(c, n, n_clear)

@app.callback(
    [Output("upload-2", "contents"), Output("name-2", "children"),
     Output("upload-2-container", "style"), Output("upload-2-success-container", "style")],
    [Input("upload-2", "contents"), Input("clear-2", "n_clicks")],
    [State("upload-2", "filename")]
)
def update_u2(c, n_clear, n): return manage_upload_state(c, n, n_clear)

# Callback PRINCIPAL (IA)
@app.callback(
    Output("output-results", "children"),
    Input("btn-run", "n_clicks"),
    [State("upload-1", "contents"), State("upload-1", "filename"),
     State("upload-2", "contents"), State("upload-2", "filename"),
     State("scenario-store", "data"), State("radio-tipo-bula", "value")]
)
def run_analysis(n_clicks, c1, n1, c2, n2, scenario, tipo_bula):
    if not n_clicks: return no_update
    if not c1 and not c2: return dbc.Alert("⚠️ Faça o upload dos arquivos!", color="warning", className="fw-bold")

    try:
        model = get_best_model()
        if not model: return dbc.Alert("Erro: Nenhum modelo de IA disponível na sua conta Google.", color="danger")

        # Processamento
        d1 = process_file(c1, n1) if c1 else None
        d2 = process_file(c2, n2) if c2 else None
        
        payload = []
        if d1: payload.append("--- ARQUIVO 1 ---"); payload.extend([d1['data']] if d1['type']=='text' else d1['data'])
        if d2: payload.append("--- ARQUIVO 2 ---"); payload.extend([d2['data']] if d2['type']=='text' else d2['data'])

        # Lógica Seções
        from_paciente = [
            "APRESENTAÇÕES", "COMPOSIÇÃO", "PARA QUE ESTE MEDICAMENTO É INDICADO", 
            "COMO ESTE MEDICAMENTO FUNCIONA", "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO", 
            "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO", "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO", 
            "COMO DEVO USAR ESTE MEDICAMENTO", "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO", 
            "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR", "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO", 
            "DIZERES LEGAIS"
        ]
        from_prof = [
            "APRESENTAÇÕES", "COMPOSIÇÃO", "INDICAÇÕES", "RESULTADOS DE EFICÁCIA", 
            "CARACTERÍSTICAS FARMACOLÓGICAS", "CONTRAINDICAÇÕES", "ADVERTÊNCIAS E PRECAUÇÕES", 
            "INTERAÇÕES MEDICAMENTOSAS", "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO", 
            "POSOLOGIA E MODO DE USAR", "REAÇÕES ADVERSAS", "SUPERDOSE", "DIZERES LEGAIS"
        ]
        
        # Define lista ativa
        if scenario == "1" and tipo_bula == "PROFISSIONAL":
            lista = from_prof
            nome_tipo = "Profissional"
        else:
            lista = from_paciente
            nome_tipo = "Paciente"
        
        secoes_str = "\n".join([f"- {s}" for s in lista])
        nao_comparar_str = "APRESENTAÇÕES, COMPOSIÇÃO, DIZERES LEGAIS"

        prompt = f"""
        Atue como Auditor de Qualidade Farmacêutica.
        Analise os documentos (Ref vs Alvo).
        
        TAREFA: Extraia o texto COMPLETO de cada seção.
        LISTA ({nome_tipo}):
        {secoes_str}
        
        REGRAS DE FORMATAÇÃO (Retorne texto com estas tags HTML):
        1. Divergências de sentido: <mark style='background-color: #fff3cd; color: #856404; padding: 2px 4px; border: 1px solid #ffeeba;'>texto diferente</mark>
           (IGNORE divergências nas seções: {nao_comparar_str}).
        2. Erros de Português: <mark style='background-color: #f8d7da; color: #721c24; padding: 2px 4px; border-radius: 4px; border-bottom: 2px solid #dc3545;'>erro</mark>
        3. Datas ANVISA: <mark style='background-color: #cff4fc; color: #055160; padding: 2px 4px; border-radius: 4px; border: 1px solid #b6effb; font-weight: bold;'>dd/mm/aaaa</mark>
        
        SAÍDA JSON:
        {{
            "METADADOS": {{ "score": 90, "datas": ["..."] }},
            "SECOES": [
                {{ "titulo": "NOME SEÇÃO", "ref": "texto...", "bel": "texto...", "status": "CONFORME" | "DIVERGENTE" | "FALTANTE" | "INFORMATIVO" }}
            ]
        }}
        """
        
        res = model.generate_content([prompt] + payload)
        data = json.loads(clean_json(res.text))
        
        meta = data.get("METADADOS", {})
        score = meta.get("score", 0)
        datas = meta.get("datas", []) 
        if not datas: datas = meta.get("datas_anvisa", []) 

        cards = dbc.Row([
            dbc.Col(dbc.Card([html.H2(f"{score}%", className="text-success fw-bold"), "Conformidade"], body=True, className="text-center shadow-sm border-0"), md=4),
            dbc.Col(dbc.Card([html.H2(str(len(data.get("SECOES", []))), className="text-primary fw-bold"), "Seções"], body=True, className="text-center shadow-sm border-0"), md=4),
            dbc.Col(dbc.Card([html.H2(", ".join(datas[:2]) if datas else "-", className="text-info fw-bold", style={"fontSize":"1rem"}), "Datas"], body=True, className="text-center shadow-sm border-0"), md=4),
        ], className="mb-4")

        items = []
        for sec in data.get("SECOES", []):
            status = sec.get('status', 'N/A')
            icon = "✅"
            if "DIVERGENTE" in status: icon = "❌"
            elif "FALTANTE" in status: icon = "🚨"
            elif "INFORMATIVO" in status: icon = "ℹ️"

            content = dbc.Row([
                dbc.Col([html.Strong("Referência", className="text-primary"), html.Div(dcc.Markdown(sec.get('ref',''), dangerously_allow_html=True), style=STYLES['bula_box'])], md=6),
                dbc.Col([html.Strong("Belfar", className="text-success"), html.Div(dcc.Markdown(sec.get('bel',''), dangerously_allow_html=True), style=STYLES['bula_box'])], md=6)
            ])
            items.append(dbc.AccordionItem(content, title=f"{icon} {sec['titulo']} — {status}", item_id=sec['titulo']))

        return html.Div([cards, dbc.Accordion(items, start_collapsed=False, always_open=True, className="shadow-sm bg-white rounded")])

    except Exception as e:
        return dbc.Alert(f"Erro: {e}", color="danger")

# Handler final
app.validation_layout = html.Div([
    build_upload_area("upload-1","","clear-1",""), 
    build_upload_area("upload-2","","clear-2",""),
    dcc.Store(id="scenario-store"), dcc.RadioItems(id="radio-tipo-bula"),
    sidebar, build_home_layout()
])

if __name__ == "__main__":
    app.run_server(debug=True)
