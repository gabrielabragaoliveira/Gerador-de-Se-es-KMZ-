import streamlit as st
import pandas as pd
import numpy as np
import zipfile
import io
import re
from bs4 import BeautifulSoup

# ==========================================
# CONFIGURAÇÃO INICIAL DA PÁGINA
# ==========================================
st.set_page_config(page_title="Gerador de Seções (KMZ)", page_icon="🌐", layout="wide")

# Inicializa o estado de sessão para manter os dados após a recarga da tela
if "df_pontos" not in st.session_state:
    st.session_state.df_pontos = None
if "df_secoes" not in st.session_state:
    st.session_state.df_secoes = None

# ==========================================
# FUNÇÕES DE PROCESSAMENTO E BACKEND
# ==========================================
def extrair_coordenadas(conteudo_kml):
    """Extrai informações dos pinos (Points) do KML e retorna uma lista de dicionários."""
    soup = BeautifulSoup(conteudo_kml, 'xml')
    dados = []
    
    # Itera sobre todos os Placemarks no KML (Ignorando linhas e pegando só os pinos)
    for placemark in soup.find_all('Placemark'):
        ponto = placemark.find('Point')
        if ponto:
            nome = placemark.find('name').text if placemark.find('name') else 'Sem nome'
            
            coords_tag = ponto.find('coordinates')
            if coords_tag:
                coords_text = coords_tag.text.strip()
                # Coordenadas no KML são "lon,lat,alt"
                partes = coords_text.split(',')
                if len(partes) >= 3:
                    lon = float(partes[0].strip())
                    lat = float(partes[1].strip())
                    alt = float(partes[2].strip())
                    
                    dados.append({
                        'ID': nome,
                        'Longitude_X': lon,
                        'Latitude_Y': lat,
                        'Cota_Z': alt
                    })
    return dados

def agrupar_secoes(df_pontos, dist_maxima_metros):
    """
    Agrupa os pontos próximos em seções sem descartar NENHUMA elevação (Z).
    Gera colunas Z_1, Z_2, ... Z_N dinamicamente.
    OBS: Como KMZ usa coordenadas geográficas (graus), convertemos grosseiramente 
    a 'dist_maxima' de metros para graus para o cálculo matemático 2D rápido.
    1 grau geográfico ~ 111.000 metros.
    """
    dist_max_graus = dist_maxima_metros / 111000.0
    
    # É vital ordenar pelo ID para respeitar o "caminho" do topógrafo
    # Como o ID pode ser texto (ex: KML_1, KML_2), ordenamos de forma inteligente (natural sort)
    df_pontos['Numero_ID'] = df_pontos['ID'].str.extract('(\d+)').astype(float)
    df_pontos = df_pontos.sort_values(by='Numero_ID').reset_index(drop=True)
    
    secoes = []
    secao_atual = []
    
    for idx, row in df_pontos.iterrows():
        ponto = {'ID': row['ID'], 'X': row['Longitude_X'], 'Y': row['Latitude_Y'], 'Z': row['Cota_Z']}
        
        if len(secao_atual) == 0:
            secao_atual.append(ponto)
        else:
            ponto_ant = secao_atual[-1]
            # Distância 2D (em graus) entre o ponto atual e o anterior na linha do levantamento
            dist = np.sqrt((ponto['X'] - ponto_ant['X'])**2 + (ponto['Y'] - ponto_ant['Y'])**2)
            
            # Se a distância for menor que o limite, é da mesma seção
            if dist <= dist_max_graus:
                secao_atual.append(ponto)
            else:
                # Ocorreu um salto. Fecha a seção e salva.
                secoes.append(secao_atual)
                secao_atual = [ponto] # Inicia a próxima
                
    if secao_atual:
        secoes.append(secao_atual)

    # Preenchimento horizontal dinâmico (expandindo as colunas Z_N)
    resultados = []
    for i, sec in enumerate(secoes):
        # Ordena do mais baixo pro mais alto
        zs = sorted([p['Z'] for p in sec])
        
        linha_tabela = {
            'Secao': f'Seção {(i+1):03d}',
            'Qtd_Pontos_Lidos': len(sec),
            'Centro_Lat_Y': round(np.mean([p['Y'] for p in sec]), 7),
            'Centro_Lon_X': round(np.mean([p['X'] for p in sec]), 7)
        }
        
        # Preenche os Z de todos os pontos, sem descarte
        for j, z in enumerate(zs):
            linha_tabela[f'Z_Ponto_{j+1}'] = z
            
        resultados.append(linha_tabela)

    return pd.DataFrame(resultados)

# ==========================================
# INTERFACE DO USUÁRIO
# ==========================================
st.title("🌐 Gerador de Seções Transversais (KMZ)")
st.markdown("Extraia todos os pontos dos Pinos de um arquivo KMZ e agrupe-os em Seções mantendo toda a nuvem de elevações (Z).")

# --- PASSO 1: UPLOAD E PROCESSAMENTO ---
st.header("1. Upload de Arquivo KMZ / KML")
col_upload, col_settings = st.columns([2, 1])

with col_upload:
    uploaded_file = st.file_uploader("Selecione seu arquivo KMZ ou KML", type=['kmz', 'kml'])

with col_settings:
    st.info("⚙️ **Configuração de Agrupamento:**")
    distancia_corte = st.number_input("Distância Máx. para mesma Seção (m):", min_value=0.1, value=1.0, step=0.1, help="Se o topógrafo andar mais que essa distância para bater o próximo pino, o sistema considerará que é uma nova seção transversal.")

if st.button("▶️ Extrair e Gerar Seções", type="primary"):
    if uploaded_file is not None:
        with st.spinner("Extraindo coordenadas e calculando agrupamentos..."):
            file_name = uploaded_file.name
            try:
                # Leitura do Arquivo (KMZ ou KML)
                if file_name.lower().endswith('.kmz'):
                    with zipfile.ZipFile(uploaded_file, 'r') as kmz:
                        # Busca qualquer arquivo kml dentro do zip
                        kml_name = [n for n in kmz.namelist() if n.lower().endswith('.kml')][0]
                        kml_content = kmz.read(kml_name)
                else:
                    kml_content = uploaded_file.read()
                
                # Passo 1: Extrai todos os Pinos
                dados_brutos = extrair_coordenadas(kml_content)
                df_pontos = pd.DataFrame(dados_brutos)
                
                if df_pontos.empty:
                    st.warning("⚠️ Nenhum pino com elevação (Point) foi encontrado neste arquivo.")
                else:
                    # Passo 2: Agrupa e expande a tabela
                    df_secoes = agrupar_secoes(df_pontos, distancia_corte)
                    
                    st.session_state.df_pontos = df_pontos
                    st.session_state.df_secoes = df_secoes
                    st.success(f"✅ Sucesso! {len(df_pontos)} pinos lidos e agrupados em {len(df_secoes)} seções.")
                    
            except Exception as e:
                st.error(f"❌ Erro ao processar o arquivo: {e}")
    else:
        st.warning("Envie um arquivo primeiro!")

# --- PRÉVIA DOS DADOS ---
if st.session_state.df_secoes is not None:
    st.divider()
    st.header("2. Prévia das Seções Geradas")
    st.markdown("A tabela abaixo mostra todas as seções criadas. Nenhuma elevação foi descartada. As colunas `Z_Ponto_N` se expandem automaticamente de acordo com a seção mais densa (com mais pontos) do seu levantamento.")
    
    # Exibe o Dataframe em tela cheia na prévia
    st.dataframe(st.session_state.df_secoes, use_container_width=True)
    
    # --- PASSO 2: PAINEL DE EDIÇÃO E SELEÇÃO (ABAIXO DA PRÉVIA) ---
    st.divider()
    st.header("3. Painel de Seleção e Edição Individual")
    
    col_sel1, col_sel2 = st.columns([1, 2])
    
    with col_sel1:
        # A lista de nomes é gerada diretamente pela coluna de seções da tabela
        lista_secoes = st.session_state.df_secoes['Secao'].tolist()
        secao_escolhida = st.selectbox("🎯 Escolha a Seção desejada para visualizar seus pontos:", lista_secoes)
    
    with col_sel2:
        st.markdown(f"**Detalhes Isolados da {secao_escolhida}:**")
        if secao_escolhida:
            # Puxa a linha específica da tabela gerada
            linha_isolada = st.session_state.df_secoes[st.session_state.df_secoes['Secao'] == secao_escolhida]
            # Transpõe para exibir as cotas verticalmente e facilitar a leitura
            st.dataframe(linha_isolada.T.dropna(), use_container_width=True)
            
    # --- EXPORTAÇÃO FINAL ---
    st.divider()
    st.markdown("### 📥 Exportar Base Completa")
    
    # Converte o Dataframe final para Excel em Memória
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        st.session_state.df_secoes.to_excel(writer, index=False, sheet_name='Secoes_KMZ')
    buffer.seek(0)
    
    st.download_button(
        label="📊 Baixar Tabela Completa Expandida (Excel .xlsx)",
        data=buffer,
        file_name="Tabela_Secoes_KMZ_Expandida.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary"
    )
    
# Rodapé Personalizado
st.markdown("<p style='text-align: center; color: gray; font-size: 12px; margin-top: 50px;'>código atualizado 17/11/2026 - by @redmargoth</p>", unsafe_allow_html=True)
