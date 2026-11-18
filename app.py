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
        
        estacas = np.arange(0, dist_max + 1, densidade_interp)
        if estacas[-1] != dist_max: estacas = np.append(estacas, dist_max)
        
        if len(estacas) > 3:
            from scipy.interpolate import interp1d
            f_lat = interp1d(dists_orig, lats_orig, kind='linear', fill_value="extrapolate")
            f_lon = interp1d(dists_orig, lons_orig, kind='linear', fill_value="extrapolate")
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
               f_alt = interp1d(dists_orig, alts_orig, kind='linear', fill_value="extrapolate")
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
        title="Cota Z (m)" if

st.markdown("<p style='text-align: center; color: gray; font-size: 12px;'>by @redmargoth</p>", unsafe_allow_html=True)
