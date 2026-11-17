import numpy as np
import matplotlib.pyplot as plt
import ipywidgets as widgets
from IPython.display import display, clear_output
from datetime import datetime
import os

# Verificação do ambiente Colab para download nativo
try:
    from google.colab import files
    IN_COLAB = True
except ImportError:
    IN_COLAB = False

import docx
from docx.shared import Inches
from fpdf import FPDF

style = {'description_width': 'initial'}

# Campos de entrada de dados
via_prin_input = widgets.FloatText(value=10.0, description='Largura Via Principal (m):', style=style)
via_sec_input = widgets.FloatText(value=8.0, description='Largura Via Secundária (m):', style=style)
canteiro_input = widgets.FloatText(value=10.0, description='Largura Canteiro (m):', style=style)
dist_eixos_input = widgets.FloatText(value=6.0, description='Distância entre Eixos (m):', style=style)
largura_veic_input = widgets.FloatText(value=2.6, description='Largura do Veículo (m):', style=style)

# Estado global para armazenar os dados do último relatório gerado
estado_relatorio = {
    "texto": [],
    "imagem": "tractrix_plot.png"
}

# Botões de comando
calc_button = widgets.Button(description='Processar Simulação', button_style='success')
reset_button = widgets.Button(description='Limpar / Reset', button_style='danger')
btn_docx = widgets.Button(description='Baixar DOCX', button_style='primary', disabled=True, icon='file-word-o')
btn_pdf = widgets.Button(description='Baixar PDF', button_style='info', disabled=True, icon='file-pdf-o')

output = widgets.Output()

def plot_tractrix(b):
    with output:
        clear_output()
        btn_docx.disabled = True
        btn_pdf.disabled = True
        
        vp = via_prin_input.value
        vs = via_sec_input.value
        ct = canteiro_input.value
        a = dist_eixos_input.value
        lv = largura_veic_input.value
        
        data_atual = datetime.now().strftime("%d/%m/%Y %H:%M")
        
        # --- CÁLCULOS FÍSICOS E DIMENSIONAIS ---
        theta_45 = 0.785
        tanh_45 = np.tanh(theta_45)
        cosh_45 = np.cosh(theta_45)
        
        x_45 = a * (theta_45 - tanh_45) + vs/2
        y_45 = a / cosh_45 + vp/2
        x_interno_45 = x_45 - (lv/2)
        
        arraste_max = a * (1.57 - np.tanh(1.57)) 
        arraste_real = a - (a / np.cosh(1.57)) 
        largura_varredura = lv + arraste_real
        
        # --- PLOTAGEM DO GRÁFICO ---
        fig, ax = plt.subplots(figsize=(10, 8))
        ax.set_title("Trajetória de Conversão - Curva Tractrix (IPR 740)")
        
        ax.axhline(0, color='black', linewidth=2, label='Bordo Externo (Via Principal)')
        ax.axhline(vp, color='gray', linestyle='--', label='Bordo Interno (Via Principal)')
        ax.axhline(vp + ct, color='green', linewidth=4, label='Canteiro Central')
        
        ax.axvline(0, color='blue', linewidth=2, label='Bordo Externo (Via Secundária)')
        ax.axvline(vs, color='lightblue', linestyle='--', label='Bordo Interno (Via Secundária)')
        
        theta = np.linspace(0.01, np.pi/2, 100)
        x_tractrix = a * (theta - np.tanh(theta)) + vs/2
        y_tractrix = a / np.cosh(theta) + vp/2
        
        x_externo = x_tractrix + (lv / 2)
        x_interno = x_tractrix - (lv / 2)
        
        ax.plot(x_tractrix, y_tractrix, color='red', linewidth=2, label='Eixo Central do Veículo')
        ax.plot(x_externo, y_tractrix, color='orange', linestyle=':', label='Gabarito Externo')
        ax.plot(x_interno, y_tractrix, color='orange', linestyle=':', label='Gabarito Interno')
        
        ax.set_xlim(-5, vs + 15)
        ax.set_ylim(-5, vp + ct + 5)
        ax.set_aspect('equal', adjustable='box')
        ax.grid(True, linestyle=':', alpha=0.6)
        ax.legend(loc='upper right', bbox_to_anchor=(1.35, 1))
        plt.tight_layout()
        
        # Salvar imagem temporária para o relatório
        fig.savefig(estado_relatorio["imagem"], dpi=150, bbox_inches='tight')
        plt.show()

        # --- ARMAZENAMENTO E EXIBIÇÃO DOS RESULTADOS ---
        linhas_relatorio = [
            f"RELATÓRIO DE DIMENSIONAMENTO E GABARITOS DE GIRO | Gerado em: {data_atual}",
            "="*70,
            f"-> PONTO CRÍTICO DA CURVA (45 graus):",
            f"   Coordenada X (Avanço na Via Secundária): {x_45:.2f} m",
            f"   Coordenada Y (Avanço na Via Principal): {y_45:.2f} m",
            f"   Bordo Interno do Veículo (Eixo X): {x_interno_45:.2f} m",
            "",
            f"-> ANÁLISE DE ARRASTE E VARREDURA:",
            f"   Largura da Varredura (Faixa Consumida pelo Veículo): ~{largura_varredura:.2f} m",
            "",
            f"-> DIRETRIZES FÍSICAS RECOMENDADAS PARA O PROJETO:",
            f"   Raio de Concordância da Esquina (Meio-Fio): Mínimo 9.0 m a 12.0 m",
            f"   Recuo do Canteiro Central: 2.0 m a 3.0 m antes do prolongamento da via transversal",
            ""
        ]
        
        if x_interno_45 < (vs/2):
            linhas_relatorio.extend([
                "   [ALERTA DE SEGURANÇA]: A traseira invade a faixa oposta da via secundária!",
                "   Recuo sugerido para linha de retenção de semáforo: Mínimo 4.0 m da interseção."
            ])
        else:
            linhas_relatorio.append("   [OK]: O veículo consegue realizar a manobra sem invadir a faixa oposta.")
            
        linhas_relatorio.extend([
            "="*70,
            "Nota: Calculado usando o Manual de Projeto Geométrico de Travessias Urbanas, DNIT (2010)."
        ])
        
        estado_relatorio["texto"] = linhas_relatorio
        
        for linha in linhas_relatorio:
            print(linha)
            
        # Habilitar botões de download após o cálculo
        btn_docx.disabled = False
        btn_pdf.disabled = False

def reset_fields(b):
    via_prin_input.value = 10.0
    via_sec_input.value = 8.0
    canteiro_input.value = 10.0
    dist_eixos_input.value = 6.0
    largura_veic_input.value = 2.6
    btn_docx.disabled = True
    btn_pdf.disabled = True
    with output:
        clear_output()
        print("\n--- Parâmetros resetados. Aguardando processamento... ---")

def gerar_docx(b):
    doc = docx.Document()
    doc.add_heading('Relatório Simulador de Curva 0ff Track', 0)
    for linha in estado_relatorio["texto"]:
        doc.add_paragraph(linha)
    if os.path.exists(estado_relatorio["imagem"]):
        doc.add_picture(estado_relatorio["imagem"], width=Inches(5.5))
    
    filename = 'Relatorio_Simulador_Curva_0ff_Track.docx'
    doc.save(filename)
    if IN_COLAB:
        files.download(filename)
        
def gerar_pdf(b):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=10)
    for linha in estado_relatorio["texto"]:
        # Substituindo caracteres não suportados pelo Latin-1 nativo do FPDF
        texto_limpo = linha.encode('latin-1', 'replace').decode('latin-1')
        pdf.cell(0, 6, txt=texto_limpo, ln=True)
        
    if os.path.exists(estado_relatorio["imagem"]):
        pdf.image(estado_relatorio["imagem"], x=15, y=None, w=170)
        
    filename = 'Relatorio_Simulador_Curva_0ff_Track.pdf'
    pdf.output(filename)
    if IN_COLAB:
        files.download(filename)

calc_button.on_click(plot_tractrix)
reset_button.on_click(reset_fields)
btn_docx.on_click(gerar_docx)
btn_pdf.on_click(gerar_pdf)

# Construção do painel 
ui = widgets.VBox([
    widgets.HTML("<h4>Simulador de Curva 0ff Track - Controle de Dimensões Viárias</h4>"),
    via_prin_input, via_sec_input, canteiro_input, dist_eixos_input, largura_veic_input,
    widgets.HBox([calc_button, reset_button]),
    widgets.HTML("<hr><b>Exportar Memorial Descritivo:</b>"),
    widgets.HBox([btn_docx, btn_pdf]),
    output
])

display(ui)

st.markdown("<p style='text-align: center; color: gray; font-size: 12px;'>código atualizado 17/11/2026  -  by @redmargoth</p>", unsafe_allow_html=True)
