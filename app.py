import streamlit as st

# SOLUCIÓN AL ERROR ModuleNotFoundError: No module named 'altair.vegalite.v4'
try:
    import altair as alt
    if not hasattr(alt, 'vegalite'):
        import altair.vegalite as vegalite
    # Mapeo manual para compatibilidad con versiones antiguas que busca Streamlit/BioSTEAM
    import sys
    import altair as alt
    sys.modules['altair.vegalite.v4'] = alt
except ImportError:
    pass

import biosteam as bst
import thermosteam as tmo
import pandas as pd
import google.generativeai as genai

# =================================================================
# 1. CONFIGURACIÓN DE LA PÁGINA
# =================================================================
st.set_page_config(page_title="BioSTEAM Lab - IA", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .stMetric { background-color: #ffffff; border: 1px solid #e0e0e0; padding: 10px; border-radius: 8px; }
    </style>
    """, unsafe_allow_html=True)

# =================================================================
# 2. LÓGICA DE SIMULACIÓN (BioSTEAM)
# =================================================================
def run_simulation(f_mosto, t_mosto, p_valve):
    # Limpieza de memoria técnica
    bst.main_flowsheet.clear()
    
    # Termodinámica
    chemicals = tmo.Chemicals(["Water", "Ethanol"])
    bst.settings.set_thermo(chemicals)

    # Corrientes
    mosto = bst.Stream("1_MOSTO", 
                       Water=f_mosto * 0.9, 
                       Ethanol=f_mosto * 0.1, 
                       units="kg/hr", 
                       T=t_mosto + 273.15, 
                       P=101325)

    vinazas_retorno = bst.Stream("Vinazas_Retorno", Water=200, T=95+273.15, P=300000)

    # Equipos
    P100 = bst.Pump("P100", ins=mosto, P=4*101325)
    
    W210 = bst.HXprocess("W210", 
                        ins=(P100-0, vinazas_retorno), 
                        outs=("3_Mosto_Pre", "Drenaje"),
                        phase0="l", phase1="l")
    W210.outs[0].T = 85 + 273.15

    W220 = bst.HXutility("W220", ins=W210-0, outs="Mezcla", T=92+273.15)
    
    V100 = bst.IsenthalpicValve("V100", ins=W220-0, outs="Mezcla_Bif", P=p_valve * 1e5)
    
    V1 = bst.Flash("V1", ins=V100-0, outs=("Vapor_Caliente", "Vinazas"), P=p_valve * 1e5, Q=0)
    
    W310 = bst.HXutility("W310", ins=V1-0, outs="Producto_Final", T=25+273.15)
    
    P200 = bst.Pump("P200", ins=V1-1, outs=vinazas_retorno, P=3*101325)

    # Ejecución del Sistema
    eth_sys = bst.System("eth_sys", path=(P100, W210, W220, V100, V1, W310, P200))
    
    try:
        eth_sys.simulate()
        return eth_sys, True
    except Exception as e:
        return None, False

# =================================================================
# 3. EXTRACCIÓN DE DATOS
# =================================================================
def get_report_tables(sistema):
    # Tabla de Materia
    m_data = []
    for s in sistema.streams:
        if s.F_mass > 0.1:
            m_data.append({
                "Corriente": s.ID,
                "T (°C)": round(s.T - 273.15, 2),
                "Presión (bar)": round(s.P / 1e5, 2),
                "Flujo (kg/h)": round(s.F_mass, 2),
                "% Etanol": f"{(s.imass['Ethanol']/s.F_mass):.1%}"
            })
    
    # Tabla de Energía (Solución .duty)
    e_data = []
    for u in sistema.units:
        duty = sum([h.duty for h in u.heat_utilities]) if u.heat_utilities else 0
        if abs(duty) > 1:
            e_data.append({
                "Equipo": u.ID,
                "Función": "Calentamiento" if duty > 0 else "Enfriamiento",
                "Carga (kW)": round(duty/3600, 2)
            })
    return pd.DataFrame(m_data), pd.DataFrame(e_data)

# =================================================================
# 4. INTERFAZ STREAMLIT
# =================================================================
st.title("🚀 Simulador BioSTEAM con IA")
st.info("Ajusta los parámetros en la barra lateral para recalcular el balance de materia y energía.")

with st.sidebar:
    st.header("🎮 Panel de Control")
    f_in = st.number_input("Flujo Alimentación (kg/h)", 500, 5000, 1000)
    t_in = st.slider("Temp. Entrada (°C)", 10, 60, 25)
    p_v = st.slider("Presión Flash (bar)", 0.2, 2.0, 1.0)
    st.divider()
    st.write("Estado: Producción Activa")

# Ejecutar simulación
sys, success = run_simulation(f_in, t_in, p_v)

if success:
    df_m, df_e = get_report_tables(sys)
    
    # Dashboards de métricas
    prod_stream = sys.get_stream("Producto_Final")
    c1, c2, c3 = st.columns(3)
    c1.metric("Pureza Destilado", df_m.loc[df_m['Corriente']=='Producto_Final', '% Etanol'].values[0])
    c2.metric("Producción Total", f"{prod_stream.F_mass:.2f} kg/h")
    c3.metric("Eficiencia Flash", "Óptima")

    tab_res, tab_pfd, tab_ia = st.tabs(["📊 Resultados Numéricos", "🖼️ Diagrama de Proceso", "🤖 Tutor Ingeniero"])
    
    with tab_res:
        col_left, col_right = st.columns(2)
        with col_left:
            st.subheader("Balance de Materia")
            st.table(df_m)
        with col_right:
            st.subheader("Consumo Energético")
            st.dataframe(df_e, use_container_width=True)

    with tab_pfd:
        st.subheader("Diagrama de Flujo (PFD)")
        try:
            sys.diagram(file="proceso", format="png")
            st.image("proceso.png")
        except:
            st.warning("Diagrama no disponible en este entorno (Falta Graphviz).")

    with tab_ia:
        st.subheader("Análisis de Inteligencia Artificial")
        if "GEMINI_API_KEY" in st.secrets:
            if st.button("Obtener Recomendaciones del Tutor"):
                with st.spinner("Analizando datos..."):
                    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
                    model = genai.GenerativeModel('gemini-2.5-pro')
                    
                    propuesta = f"""
                    Datos de la planta de etanol:
                    {df_m.to_string()}
                    Presión de operación: {p_v} bar.
                    
                    Explica técnicamente qué ocurre con la separación si bajo la presión del flash.
                    Da 3 consejos breves para mejorar el rendimiento.
                    """
                    res = model.generate_content(propuesta)
                    st.write(res.text)
        else:
            st.error("Por favor, añade la 'GEMINI_API_KEY' en los Secrets de Streamlit.")
else:
    st.error("Error en la convergencia. Los parámetros físicos no son viables.")

st.divider()
st.caption("Ingeniería de Procesos | Streamlit & BioSTEAM")
