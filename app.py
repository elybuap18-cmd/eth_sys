import streamlit as st
import biosteam as bst
import thermosteam as tmo
import pandas as pd
import google.generativeai as genai
import os

# =================================================================
# 1. CONFIGURACIÓN DE LA PÁGINA Y ESTILOS
# =================================================================
st.set_page_config(page_title="BioSTEAM Interactive Lab", layout="wide")

st.markdown("""
    <style>
    .main {
        background-color: #f5f7f9;
    }
    .stMetric {
        background-color: #ffffff;
        padding: 15px;
        border-radius: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    </style>
    """, unsafe_allow_html=True)

# =================================================================
# 2. LÓGICA DEL PROCESO (ENCAPSULADA)
# =================================================================
def run_simulation(f_mosto, t_mosto, p_valve):
    # Limpiar flujos previos para evitar errores de ID duplicado
    bst.main_flowsheet.clear()
    
    # Configuración de compuestos
    chemicals = tmo.Chemicals(["Water", "Ethanol"])
    bst.settings.set_thermo(chemicals)

    # Definición de Corrientes dinámicas
    mosto = bst.Stream("1_MOSTO", 
                       Water=f_mosto * 0.9, 
                       Ethanol=f_mosto * 0.1, 
                       units="kg/hr", 
                       T=t_mosto + 273.15, 
                       P=101325)

    vinazas_retorno = bst.Stream("Vinazas_Retorno", Water=200, T=95+273.15, P=300000)

    # Selección de Equipos
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

    # Sistema y Simulación
    eth_sys = bst.System("eth_sys", path=(P100, W210, W220, V100, V1, W310, P200))
    
    try:
        eth_sys.simulate()
        return eth_sys, True
    except:
        return eth_sys, False

# =================================================================
# 3. FUNCIONES DE REPORTE Y AYUDA
# =================================================================
def get_tables(sistema):
    # Tabla Materia
    m_data = []
    for s in sistema.streams:
        if s.F_mass > 0.01:
            m_data.append({
                "Corriente": s.ID,
                "Temp (°C)": round(s.T - 273.15, 2),
                "Flujo (kg/h)": round(s.F_mass, 2),
                "% Etanol": f"{(s.imass['Ethanol']/s.F_mass):.1%}" if s.F_mass > 0 else "0%"
            })
    
    # Tabla Energía (Manejo robusto de .duty)
    e_data = []
    for u in sistema.units:
        duty = sum([h.duty for h in u.heat_utilities]) if u.heat_utilities else 0
        if abs(duty) > 0.1:
            e_data.append({
                "Equipo": u.ID,
                "Servicio": "Calentamiento" if duty > 0 else "Enfriamiento",
                "Carga (kW)": round(duty/3600, 2)
            })
    return pd.DataFrame(m_data), pd.DataFrame(e_data)

# =================================================================
# 4. INTERFAZ DE USUARIO (STREAMLIT)
# =================================================================
st.title("🧪 Destilación Flash con BioSTEAM & IA")
st.markdown("Simulación interactiva de separación de Etanol/Agua con tutoría de Inteligencia Artificial.")

with st.sidebar:
    st.header("⚙️ Parámetros de Operación")
    f_input = st.slider("Flujo Alimentación (kg/hr)", 100, 2000, 1000)
    t_input = st.slider("Temp. Alimentación (°C)", 15, 50, 25)
    p_input = st.slider("Presión en Válvula (bar)", 0.5, 2.0, 1.0)
    
    st.divider()
    st.write("Configura los valores para observar cómo cambia la recuperación de etanol en tiempo real.")

# Ejecutar Simulación
sys, success = run_simulation(f_input, t_input, p_input)

if success:
    df_mat, df_en = get_tables(sys)
    
    # Métricas clave
    prod = sys.get_stream("Producto_Final")
    col1, col2, col3 = st.columns(3)
    col1.metric("Pureza Etanol (Destilado)", df_mat.loc[df_mat['Corriente']=='Producto_Final', '% Etanol'].values[0])
    col2.metric("Recuperación (kg/h)", f"{prod.F_mass:.2f}")
    col3.metric("Estado Simulación", "✅ Convergió")

    # PFD y Tablas
    tab1, tab2, tab3 = st.tabs(["📊 Resultados", "🖼️ Diagrama PFD", "🤖 Tutor IA"])
    
    with tab1:
        c1, c2 = st.columns(2)
        c1.subheader("Balance de Materia")
        c1.dataframe(df_mat, use_container_width=True)
        c2.subheader("Balance de Energía")
        c2.dataframe(df_en, use_container_width=True)

    with tab2:
        st.subheader("Diagrama de Flujo del Proceso")
        try:
            sys.diagram(file="pfd", format="png")
            st.image("pfd.png")
        except:
            st.error("No se pudo renderizar el PFD (Verifica que Graphviz esté instalado).")

    with tab3:
        st.subheader("Análisis del Ingeniero IA")
        if "GEMINI_API_KEY" in st.secrets:
            if st.button("Generar Explicación Técnica"):
                with st.spinner("Consultando a Gemini..."):
                    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
                    model = genai.GenerativeModel('gemini-2.5-pro')
                    
                    prompt = f"""
                    Como experto en procesos, analiza estos datos de simulación:
                    {df_mat.to_string()}
                    
                    El usuario está operando a {p_input} bar. 
                    1. Explica brevemente qué está pasando en el tanque flash V1.
                    2. ¿Es coherente la pureza obtenida?
                    3. Da un consejo técnico para mejorar la eficiencia.
                    Responde de forma concisa y profesional.
                    """
                    response = model.generate_content(prompt)
                    st.markdown(response.text)
        else:
            st.warning("⚠️ Configura GEMINI_API_KEY en los Secrets de Streamlit para activar esta función.")
else:
    st.error("❌ La simulación no logró converger con los parámetros actuales. Intenta ajustar la presión o los flujos.")

st.divider()
st.caption("Desarrollado con BioSTEAM Framework y Streamlit Cloud.")
