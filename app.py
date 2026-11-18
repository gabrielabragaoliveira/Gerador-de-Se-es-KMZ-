import streamlit as st
import pandas as pd
import numpy as np
import zipfile
import io
import os
import tempfile
from bs4 import BeautifulSoup
from geopy.distance import geodesic
import plotly.graph_objects as go
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from docx import Document
from docx.shared import Inches
from fpdf import FPDF

# ==========================================
# CONFIGURAÇÃO INICIAL DA PÁGINA
# ==========================================
st.set_page_config(page_title="Gerador de Seções Transversais", page_icon="🛤️", layout="wide")

if 'df_graficos' not in st.session_state:
    st.session_state.df_graficos = None
if 'df_tabela_larga' not in st.session_state:
    st.session_state.df_tabela_larga = None
if 'nome_base' not in st.session_state:
    st.session_state.nome_base = ""
if 'resumos' not in st.session_state:
    st.session_state.resumos = None

# ==========================================
# FUNÇÕES DE PROCESSAMENTO E BACKEND
# ==========================================
def extrair_coordenadas(conteudo_kml):
    soup = BeautifulSoup(conteudo_kml, 'xml')
    dados = []
    
    for placemark in soup.find_all('Placemark'):
        nome = placemark.find('name').text if placemark.find('name') else 'Sem nome'
        
        # 1. Tenta extrair se for um PINO/PONTO (<Point>)
        if placemark.find('Point'):
            coords_tag = placemark.find('Point').find('coordinates')
            if coords_tag:
                partes = coords_tag.text.strip().split(',')
                if len(partes) >= 2:
                    lon = float(partes[0].strip())
                    lat = float(partes[1].strip())
                    alt = float(partes[2].strip()) if len(partes) >= 3 else 0.0
                    dados.append({'ID': nome, 'Longitude_X': lon, 'Latitude_Y': lat, 'Cota_Z': alt})
                    
        # 2. Tenta extrair se for uma LINHA/PERFIL (<LineString>)
        elif placemark.find('LineString'):
            coords_tag = placemark.find('LineString').find('coordinates')
            if coords_tag:
                # Linhas possuem múltiplos pontos separados por espaço ou quebra de linha
                pontos_str = coords_tag.text.strip().split()
                for pt in pontos_str:
                    partes = pt.split(',')
                    if len(partes) >= 2:
                        lon = float(partes[0].strip())
                        lat = float(partes[1].strip())
                        alt = float(partes[2].strip()) if len(partes) >= 3 else 0.0
                        dados.append({'ID': nome, 'Longitude_X': lon, 'Latitude_Y': lat, 'Cota_Z': alt})
                        
    return dados

def processar_secoes_transversais(df_pontos, dist_corte_graus):
    # Tenta extrair um número do ID para seguir a ordem do levantamento. Se não tiver número, assume 0.
    df_pontos['Numero_ID'] = df_pontos['ID'].str.extract(r'(\d+)').astype(float).fillna(0)
    df_pontos = df_pontos.sort_values(by='Numero_ID').reset_index(drop=True)
    
    secoes = []
    secao_atual = []
    
    # Agrupa os pontos em seções transversais baseadas na distância de corte
    for idx, row in df_pontos.iterrows():
        ponto = {'ID': row['ID'], 'X': row['Longitude_X'], 'Y': row['Latitude_Y'], 'Z': row['Cota_Z']}
        
        if len(secao_atual) == 0:
            secao_atual.append(ponto)
        else:
            ponto_ant = secao_atual[-1]
            dist = np.sqrt((ponto['X'] - ponto_ant['X'])**2 + (ponto['Y'] - ponto_ant['Y'])**2)
            
            if dist <= dist_corte_graus:
                secao_atual.append(ponto)
            else:
                secoes.append(secao_atual)
                secao_atual = [ponto]
                
    if secao_atual:
        secoes.append(secao_atual)

    # Prepara os DataFrames para Gráficos (Longo) e para Excel (Largo)
    dados_graficos = []
    dados_tabela_larga = []
    resumos = {}

    for i, sec in enumerate(secoes):
        # Usa o ID real que você deu lá no Google Earth como nome base (ex: 1, 2, 3...)
        nome_real = sec[0]['ID']
        nome_secao = f'Seção {nome_real}' if str(nome_real).isdigit() else f'{nome_real} ({i+1:02d})'
        
        dist_acumulada = 0.0
        elevacoes = []
        
        for j, p in enumerate(sec):
            if j == 0:
                dist_acumulada = 0.0
            else:
                p_ant = sec[j-1]
                dist_metros = geodesic((p_ant['Y'], p_ant['X']), (p['Y'], p['X'])).meters
                dist_acumulada += dist_metros
                
            dados_graficos.append({
                'Secao': nome_secao,
                'Ponto': p['ID'],
                'Distancia_m': round(dist_acumulada, 2),
                'Cota_Z': p['Z']
            })
            elevacoes.append(p['Z'])
        
        # Estatísticas da Seção
        z_array = np.array(elevacoes)
        resumos[nome_secao] = {
            'Min': round(z_array.min(), 2),
            'Max': round(z_array.max(), 2),
            'Med': round(z_array.mean(), 2),
            'Extensao': round(dist_acumulada, 2)
        }

        # Tabela Larga (Para o Excel)
        linha_tabela = {
            'Secao': nome_secao,
            'Qtd_Pontos': len(sec),
            'Extensao_Total_m': round(dist_acumulada, 2)
        }
        for j, z in enumerate(elevacoes):
            linha_tabela[f'Z_Ponto_{j+1}'] = z
        dados_tabela_larga.append(linha_tabela)

    return pd.DataFrame(dados_graficos), pd.DataFrame(dados_tabela_larga), resumos

# ==========================================
# FUNÇÕES DE GRÁFICO (SEÇÃO TRANSVERSAL)
# ==========================================
def plotar_secao_plotly(df_sec, nome_secao, stats, cor, config):
    fig = go.Figure()
    modo_linha = 'lines+markers' if config['mostrar_pontos'] else 'lines'
    
    fig.add_trace(go.Scatter(
        x=df_sec['Distancia_m'], 
        y=df_sec['Cota_Z'],
        mode=modo_linha,
        line=dict(color=cor, width=config['espessura_linha'], shape=config['shape_linha']),
        marker=dict(size=6, color=cor) if config['mostrar_pontos'] else None,
        fill='tozeroy',
        fillcolor=f"rgba{tuple(int(cor.lstrip('#')[i:i+2], 16) for i in (0, 2, 4)) + (0.15,)}",
        name='Terreno'
    ))

    if config['mostrar_max_min']:
        idx_max = df_sec['Cota_Z'].idxmax()
        idx_min = df_sec['Cota_Z'].idxmin()
        cmax, cmin = df_sec.loc[idx_max], df_sec.loc[idx_min]
        
        fig.add_trace(go.Scatter(
            x=[cmax['Distancia_m'], cmin['Distancia_m']],
            y=[cmax['Cota_Z'], cmin['Cota_Z']],
            mode='markers+text',
            marker=dict(color=['#0055ff', '#ff0000'], size=10, symbol='circle', line=dict(color='white', width=2)),
            text=[f"<b>Máx: {cmax['Cota_Z']}m</b>", f"<b>Mín: {cmin['Cota_Z']}m</b>"],
            textposition=["top center", "bottom center"],
            textfont=dict(size=11, color="black"),
            showlegend=False
        ))
    
    texto_stats = f"Mín: {stats['Min']}m | Méd: {stats['Med']}m | Máx: {stats['Max']}m<br>Extensão Transversal: {stats['Extensao']}m"

    fig.update_layout(
        title=dict(text=f"<b>{nome_secao.upper()}</b>", font=dict(size=20), x=0.5),
        xaxis=dict(dtick=config['grid_x_princ'], minor=dict(dtick=config['grid_x_sec']), showgrid=True, gridcolor='lightgray', title="Distância Transversal (m)" if config['mostrar_eixo_x'] else "", showticklabels=config['mostrar_eixo_x']),
        yaxis=dict(dtick=config['grid_y_princ'], minor=dict(dtick=config['grid_y_sec']), showgrid=True, gridcolor='lightgray', title="Cota Z (m)" if config['mostrar_eixo_y'] else "", showticklabels=config['mostrar_eixo_y']),
        template="plotly_white",
        annotations=[dict(x=0.99, y=0.05, xref='paper', yref='paper', text=texto_stats, showarrow=False, bgcolor="rgba(255, 255, 255, 0.8)", bordercolor="black", borderwidth=1, xanchor='right', yanchor='bottom')],
        margin=dict(l=40, r=40, t=60, b=40)
    )
    return fig

def plotar_secao_matplotlib(df_sec, nome_secao, stats, cor, config):
    largura = max(8, min(20, stats['Extensao'] * 0.3))
    fig, ax = plt.subplots(figsize=(largura, 5))

    if config['mostrar_pontos']:
        ax.plot(df_sec['Distancia_m'], df_sec['Cota_Z'], color=cor, linewidth=config['espessura_linha'], marker='o', markersize=5)
    else:
        ax.plot(df_sec['Distancia_m'], df_sec['Cota_Z'], color=cor, linewidth=config['espessura_linha'])
        
    ax.fill_between(df_sec['Distancia_m'], df_sec['Cota_Z'], df_sec['Cota_Z'].min() - 2, color=cor, alpha=0.15)

    if config['mostrar_max_min']:
        idx_max = df_sec['Cota_Z'].idxmax()
        idx_min = df_sec['Cota_Z'].idxmin()
        cmax, cmin = df_sec.loc[idx_max], df_sec.loc[idx_min]
        ax.scatter([cmax['Distancia_m']], [cmax['Cota_Z']], color='#0055ff', s=70, zorder=5, edgecolors='white', linewidth=1.5)
        ax.scatter([cmin['Distancia_m']], [cmin['Cota_Z']], color='#ff0000', s=70, zorder=5, edgecolors='white', linewidth=1.5)
        ax.annotate(f"Máx: {cmax['Cota_Z']}m", (cmax['Distancia_m'], cmax['Cota_Z']), textcoords="offset points", xytext=(0,10), ha='center', fontsize=9, fontweight='bold')
        ax.annotate(f"Mín: {cmin['Cota_Z']}m", (cmin['Distancia_m'], cmin['Cota_Z']), textcoords="offset points", xytext=(0,-15), ha='center', fontsize=9, fontweight='bold')

    ax.xaxis.set_major_locator(ticker.MultipleLocator(config['grid_x_princ']))
    ax.xaxis.set_minor_locator(ticker.MultipleLocator(config['grid_x_sec']))
    
    if config['mostrar_eixo_x']: ax.set_xlabel('Distância Transversal (m)')
    else: ax.xaxis.set_ticklabels([])
        
    if config['mostrar_eixo_y']:
        ax.yaxis.set_major_locator(ticker.MultipleLocator(config['grid_y_princ']))
        ax.yaxis.set_minor_locator(ticker.MultipleLocator(config['grid_y_sec']))
        ax.set_ylabel('Cota Z (m)')
    else: ax.yaxis.set_ticklabels([])

    ax.grid(True, which='major', linestyle='-', color='#cccccc', alpha=0.7)
    ax.grid(True, which='minor', linestyle=':', color='#e0e0e0', alpha=0.5)
    ax.minorticks_on()
    ax.set_title(nome_secao.upper(), fontsize=14, fontweight='bold', pad=20)
    
    texto_stats = f"Mín: {stats['Min']}m | Méd: {stats['Med']}m | Máx: {stats['Max']}m\nExtensão: {stats['Extensao']}m"
    plt.text(0.99, 0.05, texto_stats, transform=ax.transAxes, fontsize=9, verticalalignment='bottom', horizontalalignment='right', bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
    plt.tight_layout()
    return fig

# ==========================================
# INTERFACE DO USUÁRIO
# ==========================================
st.title("🛤️ Gerador de Gráficos: Seções Transversais")
st.markdown("Extraia as linhas do KMZ (Perfis) e gere os gráficos individuais de cada linha transversal desenhada.")

st.header("1. Upload de Arquivo KMZ / KML")
col_upload, col_settings = st.columns([2, 1])

with col_upload:
    uploaded_file = st.file_uploader("Selecione seu arquivo (Pinos ou Linhas ao longo das seções)", type=['kmz', 'kml'])

with col_settings:
    distancia_corte = st.number_input("Distância Máx. para mesma Seção (m):", min_value=1.0, value=30.0, step=1.0, help="Distância máxima entre um ponto e outro para serem considerados da mesma linha transversal.")
    dist_graus = distancia_corte / 111000.0

if st.button("▶️ Gerar Seções e Gráficos", type="primary"):
    if uploaded_file is not None:
        with st.spinner("Processando agrupamentos e extraindo vértices..."):
            st.session_state.nome_base = uploaded_file.name.rsplit('.', 1)[0]
            try:
                if uploaded_file.name.lower().endswith('.kmz'):
                    with zipfile.ZipFile(uploaded_file, 'r') as kmz:
                        kml_name = [n for n in kmz.namelist() if n.lower().endswith('.kml')][0]
                        kml_content = kmz.read(kml_name)
                else:
                    kml_content = uploaded_file.read()
                
                # CHAMA A NOVA FUNÇÃO QUE LÊ PINOS E LINHAS (PERFIS)
                dados_brutos = extrair_coordenadas(kml_content)
                df_pontos = pd.DataFrame(dados_brutos)
                
                if not df_pontos.empty:
                    df_g, df_t, stats = processar_secoes_transversais(df_pontos, dist_graus)
                    st.session_state.df_graficos = df_g
                    st.session_state.df_tabela_larga = df_t
                    st.session_state.resumos = stats
                    st.success(f"✅ {len(df_t)} seções processadas e geradas com sucesso!")
                else:
                    st.warning("⚠️ Nenhuma coordenada foi encontrada neste arquivo. Verifique se o KMZ contém Linhas (Caminhos) ou Pinos válidos.")
                    
            except Exception as e:
                st.error(f"❌ Erro interno de extração: {e}")

if st.session_state.df_graficos is not None:
    st.divider()
    
    col_sidebar, col_main = st.columns([1, 4])
    
    with col_sidebar:
        st.header("2. Seleção")
        lista_secoes = st.session_state.df_tabela_larga['Secao'].tolist()
        secao_selecionada = st.selectbox("Visualizar Seção:", lista_secoes)
        cor_grafico = st.color_picker("Cor do Terreno:", "#7a1c83")

    with col_main:
        st.header("3. Gráfico da Seção Transversal")
        
        container_grafico = st.container()
        container_controles = st.container()
        
        with container_controles:
            st.markdown("<hr style='margin: 10px 0;'>", unsafe_allow_html=True)
            st.markdown("#### Ajustes de Eixos e Layout do Gráfico")
            
            c1, c2, c3 = st.columns(3)
            with c1:
                mostrar_eixo_y = st.toggle("Eixo Vertical (Cota Z)", value=True)
                grid_y_princ = st.slider("Cota Maior Y (m):", min_value=1.0, max_value=50.0, value=5.0, step=1.0)
                grid_y_sec = st.slider("Cota Menor Y (m):", min_value=0.5, max_value=10.0, value=1.0, step=0.5)

            with c2:
                mostrar_eixo_x = st.toggle("Eixo Horizontal (Distância)", value=True)
                grid_x_princ = st.slider("Dist. Maior X (m):", min_value=1.0, max_value=50.0, value=10.0, step=1.0)
                grid_x_sec = st.slider("Dist. Menor X (m):", min_value=0.5, max_value=25.0, value=2.0, step=0.5)

            with c3:
                mostrar_pontos = st.toggle("Ver Pontos (Vértices Reais)", value=True)
                mostrar_max_min = st.toggle("Destacar Máx/Mín", value=True)
                shape_linha = st.radio("Traçado:", options=['linear', 'spline'], format_func=lambda x: "Retas (Fiel)" if x == 'linear' else "Curvas (Suavizado)")
                espessura_linha = st.slider("Espessura:", min_value=0.5, max_value=5.0, value=2.0, step=0.1)

            config = {'mostrar_eixo_y': mostrar_eixo_y, 'mostrar_eixo_x': mostrar_eixo_x, 'grid_y_princ': grid_y_princ, 'grid_y_sec': grid_y_sec, 'grid_x_princ': grid_x_princ, 'grid_x_sec': grid_x_sec, 'mostrar_pontos': mostrar_pontos, 'mostrar_max_min': mostrar_max_min, 'shape_linha': shape_linha, 'espessura_linha': espessura_linha}
            
        with container_grafico:
            df_sec = st.session_state.df_graficos[st.session_state.df_graficos['Secao'] == secao_selecionada]
            stats_sec = st.session_state.resumos[secao_selecionada]
            fig_interativa = plotar_secao_plotly(df_sec, secao_selecionada, stats_sec, cor_grafico, config)
            st.plotly_chart(fig_interativa, use_container_width=True)

    st.divider()
    st.header("4. Exportação do Relatório Completo")
    
    if st.button("📦 Gerar Pacote (Excel, PDF, DOCX e Imagens)", type="primary"):
        with st.spinner("Desenhando gráficos e compilando relatórios..."):
            zip_buffer = io.BytesIO()
            with tempfile.TemporaryDirectory() as tmpdirname:
                excel_path = os.path.join(tmpdirname, f"secoes_{st.session_state.nome_base}.xlsx")
                st.session_state.df_tabela_larga.to_excel(excel_path, index=False)
                
                doc = Document()
                doc.add_heading(f'Relatório de Seções: {st.session_state.nome_base}', 0)
                pdf = FPDF()
                
                pasta_img = os.path.join(tmpdirname, "secoes_graficos")
                os.makedirs(pasta_img, exist_ok=True)
                
                for secao in st.session_state.df_tabela_larga['Secao']:
                    df_s = st.session_state.df_graficos[st.session_state.df_graficos['Secao'] == secao]
                    st_s = st.session_state.resumos[secao]
                    
                    fig_estatica = plotar_secao_matplotlib(df_s, secao, st_s, cor_grafico, config)
                    img_path = os.path.join(pasta_img, f"{secao.replace(' ', '_')}.png")
                    fig_estatica.savefig(img_path, dpi=120, bbox_inches='tight')
                    plt.close(fig_estatica)
                    
                    doc.add_heading(secao.upper(), level=1)
                    doc.add_picture(img_path, width=Inches(6.0))
                    
                    pdf.add_page(orientation='L')
                    pdf.set_font("Arial", "B", 16)
                    pdf.cell(0, 10, secao.upper(), ln=True)
                    pdf.image(img_path, x=10, w=270)

                doc_path = os.path.join(tmpdirname, "Relatorio_Secoes.docx")
                pdf_path = os.path.join(tmpdirname, "Relatorio_Secoes.pdf")
                doc.save(doc_path)
                pdf.output(pdf_path)
                
                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                    zf.write(excel_path, os.path.basename(excel_path))
                    zf.write(doc_path, os.path.basename(doc_path))
                    zf.write(pdf_path, os.path.basename(pdf_path))
                    for root, _, files in os.walk(pasta_img):
                        for file in files:
                            zf.write(os.path.join(root, file), os.path.join("graficos_png", file))
            
            zip_buffer.seek(0)
            st.success("Relatórios gerados com sucesso!")
            st.download_button(label="📥 Baixar Pacote Completo (.ZIP)", data=zip_buffer, file_name=f"secoes_transversais_{st.session_state.nome_base}.zip", mime="application/zip", type="primary")

st.markdown("<p style='text-align: center; color: gray; font-size: 12px;'>código atualizado 18/11/2026 - by @redmargoth</p>", unsafe_allow_html=True)
