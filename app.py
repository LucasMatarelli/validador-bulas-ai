import dash
from dash import dcc, html, Input, Output, State, callback_context, no_update, ALL
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

# Configuração Visual (Tema Bootstrap MINTY = Clean/Profissional)
app = dash.Dash(
    __name__, 
    external_stylesheets=[dbc.themes.MINTY, "https://use.fontawesome.com/releases/v5.15.4/css/all.css"],
    title="Validador Belfar",
    suppress_callback_exceptions=True
)
server = app.server

# ----------------- BACKEND (IA & PROCESSAMENTO) -----------------

def get_gemini_model():
    try:
        genai.configure(api_key=FIXED_API_KEY)
        # Prioriza modelos disponíveis
        return genai.GenerativeModel('models/gemini-1.5-flash')
    except: return None

def process_uploaded_file(contents, filename):
    """Lê PDF (como imagem) ou DOCX (como texto) do upload base64."""
    if not contents: return None
    
    try:
        content_type, content_string = contents.split(',')
        decoded = base64.b64decode(content_string)
        
        if filename.lower().endswith('.docx'):
            doc = docx.Document(io.BytesIO(decoded))
            text = "\n".join([p.text for p in doc.paragraphs])
            return {"type": "text", "data": text}

        elif filename.lower().endswith('.pdf'):
            doc = fitz.open(stream=decoded, filetype="pdf")
            images = []
            # Renderiza até 10 páginas para não sobrecarregar
            for i in range(min(10, len(doc))):
                page = doc[i]
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                img_byte_arr = io.BytesIO(pix.tobytes("jpeg"))
                images.append(Image.open(img_byte_arr))
            return {"type": "images", "data": images}
            
    except Exception as e:
        print(f"Erro ao processar {filename}: {e}")
        return None
    return None

# ----------------- COMPONENTES VISUAIS -----------------

def upload_component(id_name, label):
    return dbc.Card([
        dbc.CardBody([
            html.H6(label, className="card-subtitle mb-2 text-muted fw-bold"),
            dcc.Upload(
                id=id_name,
                children=html.Div([
                    html.I(className="fas fa-cloud-upload-alt fa-2x text-primary mb-2"),
                    html.Br(),
                    'Arraste ou ', html.A('Selecione', className="fw-bold")
                ]),
                style={
                    'width': '100%', 'height': '100px', 'lineHeight': '30px',
                    'borderWidth': '2px', 'borderStyle': 'dashed', 'borderRadius': '10px',
                    'textAlign': 'center', 'borderColor': '#dee2e6', 'backgroundColor': '#f8f9fa',
                    'cursor': 'pointer', 'padding': '20px'
                },
                multiple=False
            ),
            html.Div(id=f"{id_name}-filename", className="mt-2 small text-success text-center fw-bold")
        ])
    ], className="mb-3 shadow-sm border-0")

def metric_card(title, value, icon, color):
    return dbc.Card([
        dbc.CardBody([
            html.Div([
                html.I(className=f"fas {icon} fa-2x text-{color}"),
                html.Div([
                    html.H3(value, className=f"text-{color} mb-0"),
                    html.Small(title, className="text-muted")
                ], className="ms-3")
            ], className="d-flex align-items-center")
        ])
    ], className="shadow-sm border-0 mb-3")

# ----------------- LAYOUTS DE PÁGINA -----------------

sidebar = html.Div([
    html.div(className="text-center py-4", children=[
        html.I(className="fas fa-microscope fa-3x text-primary mb-2"),
        html.H4("Validador Belfar", className="fw-bold text-dark"),
        html.Small("Versão Dash 1.0", className="text-muted")
    ]),
    html.Hr(),
    dbc.Nav([
        dbc.NavLink([html.I(className="fas fa-home me-2"), "Página Inicial"], href="/", active="exact"),
        dbc.NavLink([html.I(className="fas fa-pills me-2"), "Ref x Belfar"], href="/ref-bel", active="exact"),
        dbc.NavLink([html.I(className="fas fa-clipboard-check me-2"), "Conferência MKT"], href="/mkt", active="exact"),
        dbc.NavLink([html.I(className="fas fa-print me-2"), "Gráfica x Arte"], href="/graf", active="exact"),
    ], vertical=True, pills=True, className="px-2"),
    html.Div([
        dbc.Alert([
            html.I(className="fas fa-plug me-2"), "Sistema Conectado"
        ], color="success", className="m-3 small py-2")
    ], className="mt-auto")
], style={"position": "fixed", "top": 0, "left": 0, "bottom": 0, "width": "250px", "padding": "1rem", "backgroundColor": "#fff", "borderRight": "1px solid #dee2e6"})

content_style = {"marginLeft": "270px", "padding": "2rem"}

# Layout Home
home_layout = html.Div([
    html.H1("Bem-vindo ao Validador Inteligente", className="display-5 fw-bold text-primary mb-4"),
    dbc.Alert("👈 Selecione uma ferramenta no menu lateral para começar.", color="info", className="mb-5"),
    
    dbc.Row([
        dbc.Col(dbc.Card([
            dbc.CardBody([
                html.H4("1. Ref x Belfar", className="card-title text-primary"),
                html.P("Compara bula referência com a candidata. Analisa texto técnico, posologia e dosagens. Suporta PDF e DOCX.", className="card-text"),
                dbc.Button("Acessar", href="/ref-bel", color="primary", outline=True, size="sm")
            ])
        ], className="h-100 shadow-sm"), md=4),
        
        dbc.Col(dbc.Card([
            dbc.CardBody([
                html.H4("2. Conferência MKT", className="card-title text-warning"),
                html.P("Verificação rápida de itens obrigatórios de marketing e legal (Logos, SAC, Frases de alerta).", className="card-text"),
                dbc.Button("Acessar", href="/mkt", color="warning", outline=True, size="sm")
            ])
        ], className="h-100 shadow-sm"), md=4),
        
        dbc.Col(dbc.Card([
            dbc.CardBody([
                html.H4("3. Gráfica x Arte", className="card-title text-danger"),
                html.P("Validação visual pixel-perfect. Compara a arte original com a prova da gráfica para achar manchas ou erros.", className="card-text"),
                dbc.Button("Acessar", href="/graf", color="danger", outline=True, size="sm")
            ])
        ], className="h-100 shadow-sm"), md=4),
    ])
])

# Layout Ferramenta Genérica
def build_tool_page(title, subtitle, scenario_id):
    options_div = html.Div()
    if scenario_id == "1":
        options_div = dbc.Card([
            dbc.CardBody([
                html.Label("Tipo de Bula:", className="fw-bold me-3"),
                dbc.RadioItems(
                    options=[
                        {"label": "Paciente", "value": "PACIENTE"},
                        {"label": "Profissional", "value": "PROFISSIONAL"},
                    ],
                    value="PACIENTE",
                    id="radio-tipo-bula",
                    inline=True
                )
            ])
        ], className="mb-4 bg-light border-0")

    return html.Div([
        html.H2(title, className="fw-bold text-dark"),
        html.P(subtitle, className="text-muted mb-4"),
        
        options_div,
        
        dbc.Row([
            dbc.Col(upload_component("upload-1", "📄 Documento Referência / Padrão"), md=6),
            dbc.Col(upload_component("upload-2", "📄 Documento Belfar / Candidato"), md=6),
        ]),
        
        dbc.Button([html.I(className="fas fa-rocket me-2"), "INICIAR AUDITORIA COMPLETA"], 
                   id="btn-run", color="danger", size="lg", className="w-100 mb-5 shadow"),
        
        dcc.Loading(id="loading", type="default", children=html.Div(id="output-results")),
        
        # Armazena o ID do cenário atual
        dcc.Store(id="scenario-store", data=scenario_id)
    ])

# ----------------- APP PRINCIPAL -----------------

app.layout = html.Div([
    dcc.Location(id="url"),
    sidebar,
    html.Div(id="page-content", style=content_style)
])

# Callback de Navegação
@app.callback(Output("page-content", "children"), [Input("url", "pathname")])
def render_page_content(pathname):
    if pathname == "/ref-bel":
        return build_tool_page("1. Medicamento Referência x BELFAR", "Comparação técnica de conteúdo e dosagens.", "1")
    elif pathname == "/mkt":
        return build_tool_page("2. Conferência MKT", "Checklist de itens obrigatórios de marketing.", "2")
    elif pathname == "/graf":
        return build_tool_page("3. Gráfica x Arte Vigente", "Comparação visual de pré-impressão.", "3")
    return home_layout

# Callbacks de Nome de Arquivo
@app.callback(Output("upload-1-filename", "children"), Input("upload-1", "filename"))
def update_f1(name): return f"Arquivo: {name}" if name else ""

@app.callback(Output("upload-2-filename", "children"), Input("upload-2", "filename"))
def update_f2(name): return f"Arquivo: {name}" if name else ""

# Callback PRINCIPAL (Processamento IA)
@app.callback(
    Output("output-results", "children"),
    Input("btn-run", "n_clicks"),
    [State("upload-1", "contents"), State("upload-1", "filename"),
     State("upload-2", "contents"), State("upload-2", "filename"),
     State("scenario-store", "data"),
     State("radio-tipo-bula", "value")]  # radio-tipo-bula pode não existir em outras páginas, Dash lida com isso se id for None? Não, precisa tratar.
)
def run_audit(n_clicks, c1, n1, c2, n2, scenario, tipo_bula):
    if not n_clicks: return no_update
    if not c1 and not c2: return dbc.Alert("⚠️ Faça upload dos arquivos!", color="warning")

    try:
        model = get_gemini_model()
        if not model: return dbc.Alert("Erro de configuração API.", color="danger")

        # Processa Arquivos
        data1 = process_uploaded_file(c1, n1) if c1 else None
        data2 = process_uploaded_file(c2, n2) if c2 else None
        
        # Monta Payload
        payload = []
        if data1:
            if data1['type'] == 'text': payload.append(f"--- REF TEXTO ---\n{data1['data']}")
            else: payload.extend(data1['data'])
        if data2:
            if data2['type'] == 'text': payload.append(f"--- BELFAR TEXTO ---\n{data2['data']}")
            else: payload.extend(data2['data'])

        # Define Prompt
        prompt = ""
        if scenario == "1":
            secoes = "POSOLOGIA, COMPOSIÇÃO, CONTRAINDICAÇÕES" if tipo_bula == "PROFISSIONAL" else "PARA QUE SERVE, COMO USAR, QUANDO NÃO USAR, MALES QUE PODE CAUSAR"
            prompt = f"""
            Atue como Auditor Farmacêutico.
            Compare os dois documentos (Ref vs Belfar). Analise texto (DOCX) ou imagem (PDF).
            Extraia e compare estas seções: {secoes}.
            
            SAÍDA JSON OBRIGATÓRIA:
            {{
                "METADADOS": {{"score": 95, "datas": ["dd/mm/aaaa"]}},
                "SECOES": [
                    {{"titulo": "Nome Seção", "ref": "texto ref...", "bel": "texto bel...", "status": "CONFORME" | "DIVERGENTE" | "FALTANTE"}}
                ]
            }}
            Use tags HTML <mark style='background-color: #ffff00'>texto</mark> para destacar diferenças no texto.
            """
        elif scenario == "2":
            prompt = "Verifique MKT: VENDA SOB PRESCRIÇÃO, Logo, SAC. Retorne JSON com status de cada item."
        else:
            prompt = "Comparação Visual. Liste defeitos visuais em JSON."

        # Chama IA
        response = model.generate_content([prompt] + payload)
        
        # Limpa e Parseia JSON
        txt = response.text.replace("```json", "").replace("```", "").strip()
        data = json.loads(txt)
        
        # --- RENDERIZAÇÃO DOS RESULTADOS ---
        meta = data.get("METADADOS", {})
        score = meta.get("score", 0)
        
        # Cards de Métricas
        cards = dbc.Row([
            dbc.Col(metric_card("Conformidade", f"{score}%", "fa-check-circle", "success"), md=4),
            dbc.Col(metric_card("Datas ANVISA", str(len(meta.get("datas", []))), "fa-calendar-alt", "info"), md=4),
            dbc.Col(metric_card("Motor IA", "Gemini 1.5", "fa-robot", "primary"), md=4),
        ])
        
        # Acordeão
        items = []
        for sec in data.get("SECOES", []):
            status_color = "danger" if "DIVERGENTE" in sec['status'] else "success"
            icon = "❌" if "DIVERGENTE" in sec['status'] else "✅"
            
            content = dbc.Row([
                dbc.Col([html.Strong("Referência"), html.Div(dcc.Markdown(sec.get('ref', '-'), dangerously_allow_html=True), className="border p-3 bg-light rounded")], md=6),
                dbc.Col([html.Strong("Belfar"), html.Div(dcc.Markdown(sec.get('bel', '-'), dangerously_allow_html=True), className="border p-3 bg-white rounded")], md=6),
            ])
            
            items.append(dbc.AccordionItem(content, title=f"{icon} {sec['titulo']} — {sec['status']}", item_id=sec['titulo']))
            
        return html.Div([
            html.H4("📊 Resultado da Auditoria", className="mb-4"),
            cards,
            dbc.Accordion(items, start_collapsed=False, always_open=True)
        ])

    except Exception as e:
        return dbc.Alert(f"Erro na análise: {str(e)}", color="danger")

# Corrige erro de callback com input inexistente na pagina inicial
app.validation_layout = html.Div([
    upload_component("upload-1", ""), upload_component("upload-2", ""),
    dcc.Store(id="scenario-store"), dcc.RadioItems(id="radio-tipo-bula"),
    sidebar, home_layout
])

if __name__ == "__main__":
    app.run_server(debug=True)
