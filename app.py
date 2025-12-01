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

# ----------------- ESTILOS PERSONALIZADOS -----------------
COLOR_PRIMARY = "#20c997" # Verde Minty
COLOR_DANGER = "#ff6b6b"

STYLES = {
    'upload_box': {
        'borderWidth': '2px', 'borderStyle': 'dashed', 'borderRadius': '15px',
        'borderColor': '#dee2e6', 'backgroundColor': '#f8f9fa',
        'padding': '20px', 'textAlign': 'center', 'cursor': 'pointer',
        'minHeight': '160px', 'display': 'flex', 'flexDirection': 'column', 
        'justifyContent': 'center', 'alignItems': 'center',
        'transition': 'all 0.2s ease-in-out'
    },
    'upload_box_active': {
        'borderWidth': '2px', 'borderStyle': 'solid', 'borderRadius': '15px',
        'borderColor': COLOR_PRIMARY, 'backgroundColor': '#e6fffa',
    },
    'bula_box': {
        'height': '400px', 'overflowY': 'auto', 'border': '1px solid #e9ecef',
        'borderRadius': '8px', 'padding': '25px', 'backgroundColor': '#ffffff',
        'fontFamily': '"Georgia", serif', 'fontSize': '15px', 'lineHeight': '1.7',
        'color': '#212529', 'boxShadow': 'inset 0 2px 4px rgba(0,0,0,0.02)'
    }
}

# ----------------- BACKEND (IA & ARQUIVOS) -----------------

def get_best_model():
    """Descobre qual modelo sua chave aceita (Corrige o erro 404)."""
    try:
        genai.configure(api_key=FIXED_API_KEY)
        # Tenta listar modelos
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
        
        # Fallback genérico se a lista falhar mas a chave funcionar
        return genai.GenerativeModel('models/gemini-1.5-flash')
        
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
            # OTIMIZAÇÃO: Reduz qualidade para 1.5x e limita páginas para evitar Timeout
            for i in range(min(8, len(doc))):
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

def build_upload_area(id_upload, id_store_name, id_clear, label):
    return html.Div([
        html.H6([html.I(className="far fa-file-alt me-2 text-muted"), label], className="fw-bold mb-2"),
        
        # Container relativo para posicionar o botão X
        html.Div([
            dcc.Upload(
                id=id_upload,
                children=html.Div([
                    # Conteúdo Vazio
                    html.Div([
                        html.I(className="fas fa-cloud-arrow-up fa-3x text-muted mb-2"),
                        html.H6("Arraste ou Clique", className="text-muted small fw-bold")
                    ], id=f"{id_upload}-empty"),
                    
                    # Conteúdo Preenchido (Invisível por padrão)
                    html.Div([
                        html.I(className="fas fa-file-circle-check fa-3x text-success mb-2"),
                        html.H6(id=id_store_name, className="text-success small fw-bold text-break")
                    ], id=f"{id_upload}-filled", style={"display": "none"})
                ]),
                style=STYLES['upload_box'],
                multiple=False,
                className="upload-component"
            ),
            
            # Botão X (Remover)
            html.Button(
                html.I(className="fas fa-times"),
                id=id_clear,
                className="btn btn-sm btn-danger position-absolute top-0 end-0 m-2 rounded-circle shadow-sm",
                style={"display": "none", "width": "30px", "height": "30px", "padding": "0"},
                title="Remover arquivo"
            )
        ], className="position-relative")
    ])

# ----------------- LAYOUT GERAL -----------------

sidebar = html.Div([
    html.Div([
        html.I(className="fas fa-shield-alt fa-2x text-primary me-2"),
        html.Span("Validador", className="h3 fw-bold align-middle text-dark")
    ], className="text-center py-4 border-bottom"),
    
    dbc.Nav([
        dbc.NavLink([html.I(className="fas fa-home w-25"), "Início"], href="/", active="exact", className="py-3 fw-bold"),
        dbc.NavLink([html.I(className="fas fa-pills w-25"), "Ref x Belfar"], href="/ref-bel", active="exact", className="py-3 fw-bold"),
        dbc.NavLink([html.I(className="fas fa-file-contract w-25"), "Conferência MKT"], href="/mkt", active="exact", className="py-3 fw-bold"),
        dbc.NavLink([html.I(className="fas fa-print w-25"), "Gráfica x Arte"], href="/graf", active="exact", className="py-3 fw-bold"),
    ], vertical=True, pills=True, className="px-3 py-4"),
], style={"position": "fixed", "top": 0, "left": 0, "bottom": 0, "width": "260px", "backgroundColor": "#fff", "borderRight": "1px solid #dee2e6", "zIndex": 100})

def build_tool_page(title, subtitle, scenario_id):
    # Seletor de Tipo (Apenas Cenário 1)
    options_div = html.Div()
    if scenario_id == "1":
        options_div = dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col(html.Label("Tipo de Bula:", className="fw-bold mt-2 text-end"), width=4),
                    dbc.Col(
                        dbc.RadioItems(
                            options=[
                                {"label": "Paciente", "value": "PACIENTE"},
                                {"label": "Profissional", "value": "PROFISSIONAL"},
                            ],
                            value="PACIENTE",
                            id="radio-tipo-bula",
                            inline=True,
                            className="btn-group-radio",
                            inputClassName="btn-check",
                            labelClassName="btn btn-outline-success px-4 rounded-pill fw-bold",
                            labelCheckedClassName="active"
                        ), width=8
                    )
                ], className="justify-content-center")
            ])
        ], className="mb-4 shadow-sm border-0 rounded-4 bg-white")

    return dbc.Container([
        html.Div([
            html.H2(title, className="fw-bold mb-2", style={"color": "#2c3e50"}),
            html.P(subtitle, className="text-muted"),
        ], className="mb-4 border-bottom pb-3"),
        
        options_div,
        
        dbc.Row([
            dbc.Col(build_upload_area("upload-1", "name-1", "clear-1", "Documento Referência / Padrão"), md=6, className="mb-4"),
            dbc.Col(build_upload_area("upload-2", "name-2", "clear-2", "Documento Belfar / Candidato"), md=6, className="mb-4"),
        ]),
        
        dbc.Button(
            [html.I(className="fas fa-rocket me-2"), "INICIAR AUDITORIA COMPLETA"],
            id="btn-run",
            color="primary",
            size="lg",
            className="w-100 py-3 fw-bold shadow hover-scale mb-5",
            style={"borderRadius": "10px"}
        ),
        
        dcc.Loading(id="loading", type="dot", color=COLOR_PRIMARY, children=html.Div(id="output-results")),
        dcc.Store(id="scenario-store", data=scenario_id)
    ], fluid=True)

# ----------------- APP -----------------
app.layout = html.Div([
    dcc.Location(id="url", refresh="callback-nav"), 
    sidebar,
    html.Div(id="page-content", style={"marginLeft": "260px", "padding": "2rem", "backgroundColor": "#f8f9fa", "minHeight": "100vh"})
])

# ----------------- CALLBACKS DE NAVEGAÇÃO -----------------
@app.callback(Output("page-content", "children"), [Input("url", "pathname")])
def render_page(pathname):
    if pathname == "/ref-bel": return build_tool_page("Ref x Belfar", "Comparação técnica de conteúdo.", "1")
    elif pathname == "/mkt": return build_tool_page("Conferência MKT", "Validação de itens obrigatórios.", "2")
    elif pathname == "/graf": return build_tool_page("Gráfica x Arte", "Comparação visual de pré-impressão.", "3")
    
    # Home Page
    return dbc.Container([
        html.Div(className="text-center py-5", children=[
            html.I(className="fas fa-microscope text-primary fa-4x mb-3"),
            html.H1("Validador Inteligente", className="display-4 fw-bold text-dark"),
            html.P("Selecione uma ferramenta abaixo para começar.", className="lead text-muted")
        ]),
        dbc.Row([
            dbc.Col(dbc.Card([dbc.CardBody([html.H4("Ref x Belfar", className="fw-bold"), dbc.Button("Acessar", href="/ref-bel", color="success", outline=True, className="mt-3 w-100")])], className="shadow-sm border-0 h-100 p-4 text-center"), md=4),
            dbc.Col(dbc.Card([dbc.CardBody([html.H4("Conferência MKT", className="fw-bold"), dbc.Button("Acessar", href="/mkt", color="warning", outline=True, className="mt-3 w-100")])], className="shadow-sm border-0 h-100 p-4 text-center"), md=4),
            dbc.Col(dbc.Card([dbc.CardBody([html.H4("Gráfica x Arte", className="fw-bold"), dbc.Button("Acessar", href="/graf", color="danger", outline=True, className="mt-3 w-100")])], className="shadow-sm border-0 h-100 p-4 text-center"), md=4),
        ])
    ])

# ----------------- CALLBACKS DE UPLOAD (ATUALIZADO) -----------------
# Esta função gerencia o estado visual do upload (Vazio vs Preenchido) e o botão Limpar
def manage_upload_state(contents, filename, n_clear):
    ctx = callback_context
    if not ctx.triggered: 
        return no_update, no_update, no_update, no_update, no_update
    
    trig_id = ctx.triggered[0]['prop_id'].split('.')[0]
    
    # Se clicou em limpar
    if 'clear' in trig_id:
        return None, "", {"display": "block"}, {"display": "none"}, {"display": "none"}
    
    # Se fez upload
    if contents:
        return contents, filename, {"display": "none"}, {"display": "block"}, {"display": "block"}
        
    return no_update, no_update, no_update, no_update, no_update

# Upload 1
@app.callback(
    [Output("upload-1", "contents"), Output("name-1", "children"),
     Output("upload-1-empty", "style"), Output("upload-1-filled", "style"), Output("clear-1", "style")],
    [Input("upload-1", "contents"), Input("clear-1", "n_clicks")],
    [State("upload-1", "filename")]
)
def update_u1(c, n_clear, n): return manage_upload_state(c, n, n_clear)

# Upload 2
@app.callback(
    [Output("upload-2", "contents"), Output("name-2", "children"),
     Output("upload-2-empty", "style"), Output("upload-2-filled", "style"), Output("clear-2", "style")],
    [Input("upload-2", "contents"), Input("clear-2", "n_clicks")],
    [State("upload-2", "filename")]
)
def update_u2(c, n_clear, n): return manage_upload_state(c, n, n_clear)

# ----------------- CALLBACK PRINCIPAL (IA) -----------------
@app.callback(
    Output("output-results", "children"),
    Input("btn-run", "n_clicks"),
    [State("upload-1", "contents"), State("upload-1", "filename"),
     State("upload-2", "contents"), State("upload-2", "filename"),
     State("scenario-store", "data"), State("radio-tipo-bula", "value")]
)
def run_analysis(n_clicks, c1, n1, c2, n2, scenario, tipo_bula):
    if not n_clicks: return no_update
    if not c1 and not c2: return dbc.Alert("⚠️ Faça o upload dos dois arquivos!", color="warning", className="fw-bold")

    try:
        # 1. Obter Modelo (Agora com Auto-Descoberta)
        model = get_best_model()
        if not model: return dbc.Alert("Erro: Nenhum modelo de IA disponível na sua conta Google.", color="danger")

        # 2. Processar Arquivos
        d1 = process_file(c1, n1) if c1 else None
        d2 = process_file(c2, n2) if c2 else None
        
        # Monta Payload
        payload = []
        if d1: payload.append("--- ARQUIVO 1 ---"); payload.extend([d1['data']] if d1['type']=='text' else d1['data'])
        if d2: payload.append("--- ARQUIVO 2 ---"); payload.extend([d2['data']] if d2['type']=='text' else d2['data'])

        # 3. Prompt (Mantendo a lógica das seções)
        secoes_str = "POSOLOGIA, COMPOSIÇÃO" # Default
        
        if scenario == "1":
            from_paciente = [
                "PARA QUE ESTE MEDICAMENTO É INDICADO", "COMO ESTE MEDICAMENTO FUNCIONA", 
                "QUANDO NÃO DEVO USAR", "O QUE DEVO SABER ANTES DE USAR", 
                "ONDE POSSO GUARDAR", "COMO DEVO USAR", "O QUE DEVO FAZER SE ESQUECER", 
                "QUAIS MALES PODE CAUSAR", "SUPERDOSE"
            ]
            from_prof = [
                "INDICAÇÕES", "RESULTADOS DE EFICÁCIA", "CARACTERÍSTICAS FARMACOLÓGICAS", 
                "CONTRAINDICAÇÕES", "ADVERTÊNCIAS E PRECAUÇÕES", "INTERAÇÕES MEDICAMENTOSAS", 
                "POSOLOGIA E MODO DE USAR", "REAÇÕES ADVERSAS", "SUPERDOSE"
            ]
            lista = from_prof if tipo_bula == "PROFISSIONAL" else from_paciente
            secoes_str = ", ".join(lista)
            
            prompt = f"""
            Atue como Auditor de Qualidade Farmacêutica.
            Compare os documentos. Extraia e compare estas seções: {secoes_str}.
            
            Retorne um JSON:
            {{
                "METADADOS": {{ "score": 90, "datas": ["dd/mm/aaaa"] }},
                "SECOES": [
                    {{ "titulo": "NOME SEÇÃO", "ref": "texto...", "bel": "texto...", "status": "CONFORME" | "DIVERGENTE" | "FALTANTE" }}
                ]
            }}
            
            Use HTML <mark style='background-color: #fff3cd; color: #856404;'>texto</mark> para diferenças.
            Use HTML <mark style='background-color: #f8d7da; border-bottom: 2px solid red;'>erro</mark> para erros de português.
            """
        elif scenario == "2":
            prompt = "Verifique MKT: VENDA SOB PRESCRIÇÃO, Logo, SAC. Retorne JSON."
        else:
            prompt = "Comparação Visual. Liste defeitos em JSON."

        # 4. Chamada IA
        response = model.generate_content([prompt] + payload)
        data = json.loads(clean_json(response.text))
        
        # 5. Renderização
        meta = data.get("METADADOS", {})
        score = meta.get("score", 0)
        
        cards = dbc.Row([
            dbc.Col(dbc.Card([html.H2(f"{score}%", className="text-success fw-bold"), "Conformidade"], body=True, className="text-center shadow-sm"), md=4),
            dbc.Col(dbc.Card([html.H2(str(len(data.get("SECOES", []))), className="text-primary fw-bold"), "Seções"], body=True, className="text-center shadow-sm"), md=4),
            dbc.Col(dbc.Card([html.H2(", ".join(meta.get("datas", [])[:2]) or "-", className="text-info fw-bold", style={"fontSize":"1rem"}), "Datas"], body=True, className="text-center shadow-sm"), md=4),
        ], className="mb-4")

        items = []
        for sec in data.get("SECOES", []):
            icon = "✅"
            if "DIVERGENTE" in sec['status']: icon = "❌"
            elif "FALTANTE" in sec['status']: icon = "🚨"
            
            content = dbc.Row([
                dbc.Col([html.Strong("Referência", className="text-primary"), html.Div(dcc.Markdown(sec.get('ref',''), dangerously_allow_html=True), style=STYLES['bula_box'])], md=6),
                dbc.Col([html.Strong("Belfar", className="text-success"), html.Div(dcc.Markdown(sec.get('bel',''), dangerously_allow_html=True), style=STYLES['bula_box'])], md=6)
            ])
            items.append(dbc.AccordionItem(content, title=f"{icon} {sec['titulo']} — {sec['status']}", item_id=sec['titulo']))

        return html.Div([cards, dbc.Accordion(items, start_collapsed=False, always_open=True)])

    except Exception as e:
        return dbc.Alert(f"Erro na análise: {str(e)}", color="danger")

# Handler final
app.validation_layout = html.Div([
    build_upload_area("upload-1","","clear-1",""), 
    build_upload_area("upload-2","","clear-2",""),
    dcc.Store(id="scenario-store"), dcc.RadioItems(id="radio-tipo-bula"),
    sidebar, build_home_layout()
])

if __name__ == "__main__":
    app.run_server(debug=True)
