import streamlit as st
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime
import io
import os
import tempfile
from docx import Document
from docx.shared import Inches
from fpdf import FPDF

# ==========================================
# CONFIGURAÇÃO INICIAL DA PÁGINA
# ==========================================
st.set_page_config(page_title="Simulador de Curva 0ff Track", page_icon="🛣️", layout="wide")

st.title("🛣️ Simulador de Curva 0ff Track")
st.markdown("Controle de Dimensões Viárias baseado no Manual de Projeto Geométrico de Travessias Urbanas (IPR-740, DNIT).")

# ==========================================
# 1. ENTRADA DE DADOS (Parâmetros)
# ==========================================
st.header("1. Parâmetros Viários e do Veículo")
col1, col2, col3 = st.columns(3)

with col1:
    vp = st.number_input("Largura Via Principal (m):", min_value=1.0, value=10.0, step=0.5)
    vs = st.number_input("Largura Via Secundária (m):", min_value=1.0, value=8.0, step=0.5)
with col2:
    ct = st.number_input("Largura Canteiro (m):", min_value=0.0, value=10.0, step=0.5)
    a = st.number_input("Distância entre Eixos (m):", min_value=1.0, value=6.0, step=0.5)
with col3:
    lv = st.number_input("Largura do Veículo (m):", min_value=1.0, value=2.6, step=0.1)

# ==========================================
# 2. PROCESSAMENTO E SIMULAÇÃO
# ==========================================
if st.button("▶️ Processar Simulação", type="primary", use_container_width=True):
    st.divider()
    st.header("2. Resultados da Simulação")
    
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
    
    # Exibe o gráfico no Streamlit
    st.pyplot(fig)
    
    # --- ARMAZENAMENTO DO RELATÓRIO ---
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
    
    # Alertas visuais
    if x_interno_45 < (vs/2):
        linhas_relatorio.extend([
            "   [ALERTA DE SEGURANÇA]: A traseira invade a faixa oposta da via secundária!",
            "   Recuo sugerido para linha de retenção de semáforo: Mínimo 4.0 m da interseção."
        ])
        st.error("⚠️ **ALERTA DE SEGURANÇA:** A traseira invade a faixa oposta da via secundária! Recuo sugerido para linha de retenção de semáforo: Mínimo 4.0 m da interseção.")
    else:
        linhas_relatorio.append("   [OK]: O veículo consegue realizar a manobra sem invadir a faixa oposta.")
        st.success("✅ **OK:** O veículo consegue realizar a manobra sem invadir a faixa oposta.")
        
    linhas_relatorio.extend([
        "="*70,
        "Nota: Calculado usando o Manual de Projeto Geométrico de Travessias Urbanas, DNIT (2010)."
    ])

    with st.expander("📄 Ver Memorial Descritivo Completo"):
        for linha in linhas_relatorio:
            st.text(linha)

    # ==========================================
    # 3. EXPORTAÇÃO (DOCX e PDF)
    # ==========================================
    st.header("3. Exportar Memorial Descritivo")
    
    with st.spinner("Gerando documentos para download..."):
        with tempfile.TemporaryDirectory() as tmpdirname:
            # Salva imagem temporária em alta qualidade
            img_path = os.path.join(tmpdirname, "tractrix_plot.png")
            fig.savefig(img_path, dpi=150, bbox_inches='tight')
            
            # --- Gerar DOCX ---
            doc = Document()
            doc.add_heading('Relatório Simulador de Curva 0ff Track', 0)
            for linha in linhas_relatorio:
                doc.add_paragraph(linha)
            doc.add_picture(img_path, width=Inches(5.5))
            
            doc_io = io.BytesIO()
            doc.save(doc_io)
            doc_io.seek(0)
            
            # --- Gerar PDF ---
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", size=10)
            for linha in linhas_relatorio:
                # Trata caracteres no FPDF
                texto_limpo = linha.encode('latin-1', 'replace').decode('latin-1')
                pdf.cell(0, 6, txt=texto_limpo, ln=True)
            pdf.image(img_path, x=15, y=None, w=170)
            
            pdf_path = os.path.join(tmpdirname, "relatorio.pdf")
            pdf.output(pdf_path)
            
            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()

        col_dl1, col_dl2 = st.columns(2)
        with col_dl1:
            st.download_button(
                label="📄 Baixar DOCX",
                data=doc_io,
                file_name="Relatorio_Simulador_Curva_0ff_Track.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True
            )
        with col_dl2:
            st.download_button(
                label="📕 Baixar PDF",
                data=pdf_bytes,
                file_name="Relatorio_Simulador_Curva_0ff_Track.pdf",
                mime="application/pdf",
                use_container_width=True
            )

# Rodapé Personalizado (Isolado no fim da tela)
st.markdown("<br><br><hr><p style='text-align: center; color: gray; font-size: 12px;'>código atualizado 17/11/2026 - by @redmargoth</p>", unsafe_allow_html=True)
