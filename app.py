import streamlit as st
import pandas as pd
import numpy as np
import requests
from bs4 import BeautifulSoup
from geopy.distance import geodesic
import time
import zipfile
import io
import os
import tempfile
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from docx import Document
from docx.shared import Inches
from fpdf import FPDF
import plotly.graph_objects as go

# ==========================================
# CONFIGURAÇÃO INICIAL DA PÁGINA
# ==========================================
st.set_page_config(page_title="Gerador de seções via KMZ", layout="wide")

# Inicialização de Variáveis de Estado
if 'df_1m' not in st.session_state:
    st.session_state.df_1m = None
if 'df_resumo' not in st.session_state:
    st.session_state.df_resumo = None
if 'nome_base' not in st.session_state:
    st.session_state.nome_base = ""

# ==========================================
# FUNÇÕES DE PROCESSAMENTO E BACKEND
# ==========================================
def obter_elevacoes_reais(lats, lons, lote=20):
    elevacoes = []
    progress_bar = st.progress(0)
    total_lotes = (len(lats) // lote) + 1
    
    for i in range(0, len(lats), lote):
        batch_lat = lats[i:i+lote]
        batch_lon = lons[i:i+lote]
        lat_str = ",".join(map(str, batch_lat))
        lon_str = ",".join(map(str, batch_lon))
        url = f"https://api.open-meteo.com/v1/elevation?latitude={lat_str}&longitude={lon_str}"
        sucesso = False
        tentativas = 0
        
        while not sucesso and tentativas < 5:
            try:
                resp = requests.get(url, timeout=10)
                if resp.status_code == 429:
                    espera = (2 ** tentativas) + 5
                    st.toast(f"Limite da API atingido. Aguardando {espera}s...", icon="⏳")
                    time.sleep(espera)
                    tentativas += 1
                    continue
                resp.raise_for_status()
                data = resp.json()
                if 'elevation' in data:
                    elevacoes.extend(data['elevation'])
                    sucesso = True
                else:
                    elevacoes.extend([0.0] * len(batch_lat))
                    sucesso = True
            except Exception as e:
                tentativas += 1
                time.sleep(3)
                
        if not sucesso:
            elevacoes.extend([0.0] * len(batch_lat))
        time.sleep(1.0)
        progress_bar.progress(min((i // lote + 1) / total_lotes, 1.0))
        
    progress_bar.empty()
    return elevacoes

def processar_kml_denso(conteudo_kml, densidade_interp=1.0):
    soup = BeautifulSoup(conteudo_kml, 'xml')
    dados_1m, resumos = [], []
    
    # Procura por Placemarks
    placemarks = soup.find_all('Placemark')
    for placemark in placemarks:
        nome = placemark.find('name').text if placemark.find('name') else 'Eixo_Desconhecido'
        
        # Pega todas as LineStrings (garante compatibilidade com MultiGeometry ou formatações aninhadas)
        linhas = placemark.find_all('LineString')
        if not linhas:
            continue
        
        for linha_string in linhas:
            coords_text = linha_string.find('coordinates').text.strip()
            coords = [c.split(',') for c in coords_text.split() if len(c.split(',')) >= 2]
            if len(coords) < 2: continue
            
            lats_orig = [float(c[1]) for c in coords]
            lons_orig = [float(c[0]) for c in coords]
            
            has_altitude = all(len(c) >= 3 for c in coords)
            alts_orig = [float(c[2]) for c in coords] if has_altitude else [0.0] * len(coords)
            
            dists_orig = [0.0]
            for i in range(1, len(coords)):
                pt_ant, pt_atual = (lats_orig[i-1], lons_orig[i-1]), (lats_orig[i], lons_orig[i])
                dists_orig.append(dists_orig[-1] + geodesic(pt_ant, pt_atual).meters)
            dist_max = dists_orig[-1]
            
            # Densificação do percurso
            estacas = np.arange(0, dist_max + 1, densidade_interp)
            if estacas[-1] != dist_max: estacas = np.append(estacas, dist_max)
            
            lats_1m = np.interp(estacas, dists_orig, lats_orig)
            lons_1m = np.interp(estacas, dists_orig, lons_orig)

            if not has_altitude or all(a == 0.0 for a in alts_orig):
                st.info(f"Buscando altitudes online para '{nome}' via Open-Meteo...")
                elev_1m = np.array(obter_elevacoes_reais(lats_1m, lons_1m))
            else:
                elev_1m = np.interp(estacas, dists_orig, alts_orig)
                
            for e, la, lo, el in zip(estacas, lats_1m, lons_1m, elev_1m):
                dados_1m.append({'Trecho': nome, 'Estaca (m)': round(e, 2), 'Latitude': la, 'Longitude': lo, 'Cota (m)': round(el, 2)})
            
            diffs = np.diff(elev_1m)
            resumos.append({
                'Trecho': nome, 
                'Mín (m)': round(elev_1m.min(), 1), 
                'Méd (m)': round(elev_1m.mean(), 1), 
                'Máx (m)': round(elev_1m.max(), 1), 
                'Distância Total (m)': round(dist_max, 1), 
                'Ganho Elev (m)': round(diffs[diffs > 0].sum(), 2) if (diffs > 0).any() else 0.0, 
                'Perda Elev (m)': round(abs(diffs[diffs < 0].sum()), 2) if (diffs < 0).any() else 0.0
            })
        
    return pd.DataFrame(dados_1m), pd.DataFrame(resumos)

def renomear_em_lote(novo_nome_base):
    if st.session_state.df_resumo is not None and novo_nome_base.strip() != "":
        trechos_antigos = st.session_state.df_resumo['Trecho'].unique()
        mapa_nomes = {antigo: f"{novo_nome_base} - {i:02d}" for i, antigo in enumerate(trechos_antigos, 1)}
        
        st.session_state.df_1m['Trecho'] = st.session_state.df_1m['Trecho'].map(mapa_nomes)
        st.session_state.df_resumo['Trecho'] = st.session_state.df_resumo['Trecho'].map(mapa_nomes)
        st.success("Trechos renomeados e enumerados com sucesso!")

# ==========================================
# FUNÇÕES DE PLOTAGEM (PLOTLY E MATPLOTLIB)
# ==========================================
def plotar_perfil_plotly(df_t, row, cor, config):
    fig = go.Figure()
    
    modo_linha = 'lines+markers' if config['mostrar_pontos'] else 'lines'
    
    fig.add_trace(go.Scatter(
        x=df_t['Estaca (m)'], 
        y=df_t['Cota (m)'],
        mode=modo_linha,
        line=dict(color=cor, width=config['espessura_linha'], shape=config['shape_linha']),
        marker=dict(size=5, color=cor) if config['mostrar_pontos'] else None,
        fill='tozeroy',
        fillcolor=f"rgba{tuple(int(cor.lstrip('#')[i:i+2], 16) for i in (0, 2, 4)) + (0.15,)}",
        name='Relevo'
    ))

    idx_max = df_t['Cota (m)'].idxmax()
    idx_min = df_t['Cota (m)'].idxmin()
    cota_max = df_t.loc[idx_max]
    cota_min = df_t.loc[idx_min]
    
    if config['mostrar_max_min']:
        fig.add_trace(go.Scatter(
            x=[cota_max['Estaca (m)'], cota_min['Estaca (m)']],
            y=[cota_max['Cota (m)'], cota_min['Cota (m)']],
            mode='markers+text',
            marker=dict(color=['#0055ff', '#ff0000'], size=10, symbol='circle', line=dict(color='white', width=2)),
            text=[f"<b>Máx: {cota_max['Cota (m)']}m</b>", f"<b>Mín: {cota_min['Cota (m)']}m</b>"],
            textposition=["top center", "bottom center"],
            textfont=dict(size=11, color="black"),
            name='Máx / Mín',
            showlegend=False
        ))
    
    stats_text = (f"Mín: {row['Mín (m)']}m | Méd: {row['Méd (m)']}m | Máx: {row['Máx (m)']}m<br>"
                  f"Extensão: {row['Distância Total (m)']}m | Ganho: {row['Ganho Elev (m)']}m | Perda: {row['Perda Elev (m)']}m")

    yaxis_config = dict(
        dtick=config['grid_y_princ'], 
        minor=dict(dtick=config['grid_y_sec']), 
        showgrid=True, 
        gridcolor='lightgray',
        showticklabels=config['mostrar_eixo_y'],
        title="Cota Z (m)" if config['mostrar_eixo_y'] else ""
    )

    xaxis_config = dict(
        dtick=config['grid_x_princ'], 
        minor=dict(dtick=config['grid_x_sec']), 
        showgrid=True, 
        gridcolor='lightgray',
        showticklabels=config['mostrar_eixo_x'],
        title="Distância (m)" if config['mostrar_eixo_x'] else ""
    )

    fig.update_layout(
        title=dict(text=f"<b>{row['Trecho'].upper()}</b>", font=dict(size=20), x=0.5),
        xaxis=xaxis_config,
        yaxis=yaxis_config,
        template="plotly_white",
        annotations=[dict(
            x=0.99, y=0.05, xref='paper', yref='paper',
            text=stats_text, showarrow=False,
            bgcolor="rgba(255, 255, 255, 0.8)", bordercolor="black", borderwidth=1,
            xanchor='right', yanchor='bottom'
        )],
        margin=dict(l=40, r=40, t=60, b=40)
    )
    return fig

def plotar_perfil_matplotlib(df_t, row, cor, config):
    distancia = row['Distância Total (m)']
    largura_dinamica = max(8, min(40, distancia * 0.15))
    fig, ax = plt.subplots(figsize=(largura_dinamica, 6))

    if config['mostrar_pontos']:
        ax.plot(df_t['Estaca (m)'], df_t['Cota (m)'], color=cor, linewidth=config['espessura_linha'], marker='o', markersize=4)
    else:
        ax.plot(df_t['Estaca (m)'], df_t['Cota (m)'], color=cor, linewidth=config['espessura_linha'])
        
    ax.fill_between(df_t['Estaca (m)'], df_t['Cota (m)'], df_t['Cota (m)'].min() - 5, color=cor, alpha=0.15)

    if config['mostrar_max_min']:
        idx_max = df_t['Cota (m)'].idxmax()
        idx_min = df_t['Cota (m)'].idxmin()
        cmax, cmin = df_t.loc[idx_max], df_t.loc[idx_min]
        
        ax.scatter([cmax['Estaca (m)']], [cmax['Cota (m)']], color='#0055ff', s=70, zorder=5, edgecolors='white', linewidth=1.5)
        ax.scatter([cmin['Estaca (m)']], [cmin['Cota (m)']], color='#ff0000', s=70, zorder=5, edgecolors='white', linewidth=1.5)
        
        ax.annotate(f"Máx: {cmax['Cota (m)']}m", (cmax['Estaca (m)'], cmax['Cota (m)']), textcoords="offset points", xytext=(0,10), ha='center', fontsize=9, fontweight='bold')
        ax.annotate(f"Mín: {cmin['Cota (m)']}m", (cmin['Estaca (m)'], cmin['Cota (m)']), textcoords="offset points", xytext=(0,-15), ha='center', fontsize=9, fontweight='bold')

    ax.xaxis.set_major_locator(ticker.MultipleLocator(config['grid_x_princ']))
    ax.xaxis.set_minor_locator(ticker.MultipleLocator(config['grid_x_sec']))
    
    if config['mostrar_eixo_x']:
        ax.set_xlabel('Distância (m)')
    else:
        ax.set_xlabel('')
        ax.xaxis.set_ticklabels([])
        
    if config['mostrar_eixo_y']:
        ax.yaxis.set_major_locator(ticker.MultipleLocator(config['grid_y_princ']))
        ax.yaxis.set_minor_locator(ticker.MultipleLocator(config['grid_y_sec']))
        ax.set_ylabel('Cota Z (m)')
    else:
        ax.yaxis.set_ticklabels([])
        ax.yaxis.set_ticks_position('none')

    ax.grid(True, which='major', linestyle='-', color='#cccccc', alpha=0.7)
    ax.grid(True, which='minor', linestyle=':', color='#e0e0e0', alpha=0.5)
    ax.minorticks_on()

    ax.set_title(row['Trecho'].upper(), fontsize=14, fontweight='bold', pad=20)
    stats_text = f"Mín: {row['Mín (m)']}m | Méd: {row['Méd (m)']}m | Máx: {row['Máx (m)']}m\nExtensão: {row['Distância Total (m)']}m | Ganho: {row['Ganho Elev (m)']}m | Perda: {row['Perda Elev (m)']}m"
    plt.text(0.99, 0.05, stats_text, transform=ax.transAxes, fontsize=9, verticalalignment='bottom', horizontalalignment='right', bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

    plt.tight_layout()
    return fig

# ==========================================
# INTERFACE DO USUÁRIO
# ==========================================
st.title("🗺️ Extrator e Gerador de Perfil Topográfico")

st.header("1. Upload de Arquivo")
uploaded_file = st.file_uploader("Carregue seu KML ou KMZ (Pinos ou Linhas)", type=['kml', 'kmz'])

if uploaded_file is not None:
    if st.button("▶️ Processar Arquivo", type="primary"):
        with st.spinner("Analisando o arquivo e extraindo relevo..."):
            file_name = uploaded_file.name
            st.session_state.nome_base = file_name.rsplit('.', 1)[0]
            try:
                if file_name.lower().endswith('.kmz'):
                    with zipfile.ZipFile(uploaded_file, 'r') as kmz:
                        kml_name = [n for n in kmz.namelist() if n.endswith('.kml')][0]
                        kml_content = kmz.read(kml_name)
                else:
                    kml_content = uploaded_file.read()
                    
                df_1m, df_resumo = processar_kml_denso(kml_content, densidade_interp=1.0)
                
                if df_1m.empty:
                    st.error("Nenhuma coordenada válida foi encontrada! O arquivo parece estar vazio.")
                else:
                    st.session_state.df_1m = df_1m
                    st.session_state.df_resumo = df_resumo
                    st.success("Relevo extraído com sucesso!")
            except Exception as e:
                st.error(f"Erro no processamento do arquivo: {e}")

if st.session_state.df_1m is not None and not st.session_state.df_1m.empty:
    st.divider()
    
    col_sidebar, col_main = st.columns([1, 4])
    
    with col_sidebar:
        st.header("2. Gestão de Dados")
        
        novo_lote = st.text_input("Renomear por lote (Ex: Lote A):")
        if st.button("Aplicar Renomeação Sequencial", use_container_width=True):
            renomear_em_lote(novo_lote)
        
        trechos_disponiveis = st.session_state.df_resumo['Trecho'].unique().tolist()
        trecho_selecionado = st.selectbox("Selecione o Trecho para visualizar:", trechos_disponiveis)
        
        st.markdown("---")
        st.markdown("#### Estilo Básico")
        cor_grafico = st.color_picker("Cor do Relevo:", "#1c832a")

    with col_main:
        st.header("3. Prévia Interativa (Plotly)")
        
        container_grafico = st.container()
        container_controles = st.container()
        
        # --- AJUSTES TOTALMENTE SEPARADOS ABAIXO DO GRÁFICO ---
        with container_controles:
            st.markdown("<hr style='margin: 10px 0;'>", unsafe_allow_html=True)
            st.markdown("#### Ajustes Independentes (Cotas, Eixos e Detalhamento)")
            
            col_y, col_x, col_style = st.columns(3)
            
            with col_y:
                st.markdown("**Lateral Esquerda (Cotas Y)**")
                mostrar_eixo_y = st.toggle("Exibir Numeração Y", value=True)
                grid_y_princ = st.slider("Cota Maior Y (m):", min_value=1.0, max_value=50.0, value=5.0, step=1.0)
                grid_y_sec = st.slider("Cota Menor Y (m):", min_value=0.5, max_value=10.0, value=1.0, step=0.5)

            with col_x:
                st.markdown("**Inferior (Cotas X)**")
                mostrar_eixo_x = st.toggle("Exibir Numeração X", value=True)
                grid_x_princ = st.slider("Cota Maior X (m):", min_value=1.0, max_value=100.0, value=20.0, step=1.0)
                grid_x_sec = st.slider("Cota Menor X (m):", min_value=0.5, max_value=50.0, value=5.0, step=0.5)

            with col_style:
                st.markdown("**Estilo da Linha & Pontos**")
                mostrar_pontos = st.toggle("Ver Pontos (Marcadores)", value=False, help="Mostra os vértices exatos para revelar a densidade do levantamento")
                mostrar_max_min = st.toggle("Destacar Máx/Mín", value=True)
                shape_linha = st.radio("Interpolação:", options=['linear', 'spline'], format_func=lambda x: "Quadrada/Retas" if x == 'linear' else "Arredondada/Suave")
                espessura_linha = st.slider("Espessura:", min_value=0.5, max_value=5.0, value=2.0, step=0.1)

            config = {
                'mostrar_eixo_y': mostrar_eixo_y,
                'mostrar_eixo_x': mostrar_eixo_x,
                'grid_y_princ': grid_y_princ,
                'grid_y_sec': grid_y_sec,
                'grid_x_princ': grid_x_princ,
                'grid_x_sec': grid_x_sec,
                'mostrar_pontos': mostrar_pontos,
                'mostrar_max_min': mostrar_max_min,
                'shape_linha': shape_linha,
                'espessura_linha': espessura_linha
            }
            
        with container_grafico:
            df_trecho = st.session_state.df_1m[st.session_state.df_1m['Trecho'] == trecho_selecionado]
            row_resumo = st.session_state.df_resumo[st.session_state.df_resumo['Trecho'] == trecho_selecionado].iloc[0]
            
            fig_interativa = plotar_perfil_plotly(df_trecho, row_resumo, cor_grafico, config)
            st.plotly_chart(fig_interativa, use_container_width=True)

    st.divider()
    st.header("4. Exportação Profissional")
    
    if st.button("📦 Gerar & Exportar Pacote ZIP", type="primary"):
        with st.spinner("Compilando relatórios e renderizando imagens estáticas..."):
            zip_buffer = io.BytesIO()
            with tempfile.TemporaryDirectory() as tmpdirname:
                excel_path = os.path.join(tmpdirname, f"topografia_{st.session_state.nome_base}.xlsx")
                st.session_state.df_resumo.to_excel(excel_path, index=False)
                
                doc = Document()
                doc.add_heading(f'Relatório de Topografia: {st.session_state.nome_base}', 0)
                pdf = FPDF()
                
                pasta_img = os.path.join(tmpdirname, "perfis_exportados")
                os.makedirs(pasta_img, exist_ok=True)
                
                for _, row in st.session_state.df_resumo.iterrows():
                    t = row['Trecho']
                    df_t = st.session_state.df_1m[st.session_state.df_1m['Trecho'] == t]
                    
                    fig_estatica = plotar_perfil_matplotlib(df_t, row, cor_grafico, config)
                    img_name = f"{t.replace('/', '_')}.png"
                    img_path = os.path.join(pasta_img, img_name)
                    fig_estatica.savefig(img_path, dpi=120, bbox_inches='tight')
                    plt.close(fig_estatica)
                    
                    doc.add_heading(t.upper(), level=1)
                    stats_text = f"Mín: {row['Mín (m)']}m | Méd: {row['Méd (m)']}m | Máx: {row['Máx (m)']}m\nExtensão: {row['Distância Total (m)']}m | Ganho: {row['Ganho Elev (m)']}m | Perda: {row['Perda Elev (m)']}m"
                    doc.add_paragraph(stats_text)
                    doc.add_picture(img_path, width=Inches(6.0))
                    
                    largura_dinamica = max(8, min(40, row['Distância Total (m)'] * 0.15))
                    pdf.add_page(orientation='L' if largura_dinamica > 15 else 'P')
                    pdf.set_font("Arial", "B", 16)
                    pdf.cell(0, 10, t.upper(), ln=True)
                    pdf.set_font("Arial", "", 10)
                    pdf.multi_cell(0, 5, stats_text)
                    pdf_img_w = min(270 if largura_dinamica > 15 else 190, largura_dinamica * 12)
                    pdf.image(img_path, x=10, w=pdf_img_w)

                doc_path = os.path.join(tmpdirname, f"Relatorio_{st.session_state.nome_base}.docx")
                pdf_path = os.path.join(tmpdirname, f"Relatorio_{st.session_state.nome_base}.pdf")
                doc.save(doc_path)
                pdf.output(pdf_path)
                
                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                    zf.write(excel_path, os.path.basename(excel_path))
                    zf.write(doc_path, os.path.basename(doc_path))
                    zf.write(pdf_path, os.path.basename(pdf_path))
                    for root, _, files in os.walk(pasta_img):
                        for file in files:
                            file_path = os.path.join(root, file)
                            zf.write(file_path, os.path.join("perfis_exportados", file))
            
            zip_buffer.seek(0)
            
            st.success("Pacote gerado com sucesso!")
            st.download_button(
                label="📥 Baixar Pacote Completo (.ZIP)",
                data=zip_buffer,
                file_name=f"exportacao_customizada_{st.session_state.nome_base}.zip",
                mime="application/zip",
                type="primary",
                use_container_width=True
            )

# Rodapé Personalizado
st.markdown("<p style='text-align: center; color: gray; font-size: 12px;'>código atualizado 18/11/2026 - by @redmargoth</p>", unsafe_allow_html=True)
