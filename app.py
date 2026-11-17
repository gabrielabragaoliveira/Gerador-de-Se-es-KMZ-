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
st.set_page_config(page_title="App de Topografia & Relevo", page_icon="⛰️", layout="wide")

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
    
    placemarks = soup.find_all('Placemark')
    for placemark in placemarks:
        nome = placemark.find('name').text if placemark.find('name') else 'Eixo_Desconhecido'
        linha = placemark.find('LineString')
        if not linha:
            linha = placemark.find('geometryCollection') or placemark.find('MultiGeometry')
        linha_string = placemark.find('LineString')
        if not linha_string: continue
        
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
        
        # A densidade determina quão "suave/redonda" a linha fica 
        # (1.0 = interpola a cada metro, 0.25 = a cada 25cm para curvas perfeitas)
        estacas = np.arange(0, dist_max + 1, densidade_interp)
        if estacas[-1] != dist_max: estacas = np.append(estacas, dist_max)
        
        # Interpolação splinesca (cubic) em vez de linear para deixar o gráfico mais suave
        if len(estacas) > 3:
            from scipy.interpolate import interp1d
            f_lat = interp1d(dists_orig, lats_orig, kind='cubic', fill_value="extrapolate")
            f_lon = interp1d(dists_orig, lons_orig, kind='cubic', fill_value="extrapolate")
            lats_1m = f_lat(estacas)
            lons_1m = f_lon(estacas)
        else:
             lats_1m = np.interp(estacas, dists_orig, lats_orig)
             lons_1m = np.interp(estacas, dists_orig, lons_orig)

        if not has_altitude or all(a == 0.0 for a in alts_orig):
            st.info(f"Buscando altitudes online para o trecho '{nome}' via Open-Meteo...")
            elev_1m = np.array(obter_elevacoes_reais(lats_1m, lons_1m))
        else:
            st.success(f"Usando altitudes nativas do KML para o trecho '{nome}'!")
            if len(estacas) > 3:
               f_alt = interp1d(dists_orig, alts_orig, kind='cubic', fill_value="extrapolate")
               elev_1m = f_alt(estacas)
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
def plotar_perfil_plotly(df_t, row, espessura, cor, shape_linha, config_eixos):
    fig = go.Figure()
    
    # Renderização da Linha (Controlada pelo shape param 'spline' para mais arredondada ou 'linear' para quadrada)
    fig.add_trace(go.Scatter(
        x=df_t['Estaca (m)'], 
        y=df_t['Cota (m)'],
        mode='lines',
        line=dict(color=cor, width=espessura, shape=shape_linha),
        fill='tozeroy',
        fillcolor=f"rgba{tuple(int(cor.lstrip('#')[i:i+2], 16) for i in (0, 2, 4)) + (0.15,)}",
        name='Relevo'
    ))

    # Bolinhas e Textos de Máxima e Mínima (Ativados pelos botões do menu inferior)
    idx_max = df_t['Cota (m)'].idxmax()
    idx_min = df_t['Cota (m)'].idxmin()
    cota_max = df_t.loc[idx_max]
    cota_min = df_t.loc[idx_min]
    
    if config_eixos['mostrar_max_min']:
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

    # Customização flexível do Eixo Y (Esquerda) e X (Inferior) através das seleções do menu inferior
    yaxis_config = dict(
        showgrid=True, 
        gridcolor='lightgray',
        showticklabels=config_eixos['mostrar_eixo_y'],
        title="Cota Z (m)" if config_eixos['mostrar_eixo_y'] else ""
    )

    xaxis_config = dict(
        showgrid=True, 
        gridcolor='lightgray',
        showticklabels=config_eixos['mostrar_eixo_x'],
        title="Distância (m)" if config_eixos['mostrar_eixo_x'] else ""
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

# ==========================================
# INTERFACE DO USUÁRIO
# ==========================================
st.title("🗺️ Extrator e Gerador de Perfil Topográfico")

st.header("1. Upload de Arquivo")
uploaded_file = st.file_uploader("Carregue seu KML ou KMZ", type=['kml', 'kmz'])

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
                    
                # A densidade de 0.25 injeta muito mais pontos para evitar que o gráfico fique "quadrado"
                df_1m, df_resumo = processar_kml_denso(kml_content, densidade_interp=0.25)
                st.session_state.df_1m = df_1m
                st.session_state.df_resumo = df_resumo
                st.success("Relevo extraído e densificado com sucesso!")
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
        container_controles_inferiores = st.container()
        
        # --- NOVO BLOCO DE AJUSTES INFERIORES ABAIXO DO GRÁFICO ---
        with container_controles_inferiores:
            st.markdown("<hr style='margin: 10px 0;'>", unsafe_allow_html=True)
            st.markdown("#### Ajustes de Renderização e Cotas")
            
            col_controles_1, col_controles_2, col_controles_3 = st.columns(3)
            
            with col_controles_1:
                st.markdown("**Visibilidade de Cotas / Eixos**")
                mostrar_eixo_y = st.toggle("Eixo Vertical (Y / Altura)", value=True)
                mostrar_eixo_x = st.toggle("Eixo Horizontal (X / Distância)", value=True)
                
            with col_controles_2:
                st.markdown("**Destaques no Desenho**")
                mostrar_max_min = st.toggle("Rotular Cota Máxima e Mínima", value=True)
                shape_linha = st.radio("Suavidade da Linha:", options=['spline', 'linear'], format_func=lambda x: "Arredondada (Muitos pontos)" if x == 'spline' else "Reta (Linhas duras)")

            with col_controles_3:
                st.markdown("**Estilo**")
                espessura_linha = st.slider("Espessura da Linha:", min_value=0.5, max_value=5.0, value=2.0, step=0.1)

            config_eixos = {
                'mostrar_eixo_y': mostrar_eixo_y,
                'mostrar_eixo_x': mostrar_eixo_x,
                'mostrar_max_min': mostrar_max_min
            }
            
        with container_grafico:
            df_trecho = st.session_state.df_1m[st.session_state.df_1m['Trecho'] == trecho_selecionado]
            row_resumo = st.session_state.df_resumo[st.session_state.df_resumo['Trecho'] == trecho_selecionado].iloc[0]
            
            fig_interativa = plotar_perfil_plotly(df_trecho, row_resumo, espessura_linha, cor_grafico, shape_linha, config_eixos)
            st.plotly_chart(fig_interativa, use_container_width=True)

# Rodapé Personalizado
st.markdown("<p style='text-align: center; color: gray; font-size: 12px;'>código atualizado 17/11/2026  -  by @redmargoth</p>", unsafe_allow_html=True)
