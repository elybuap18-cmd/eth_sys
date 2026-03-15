import streamlit as st

# Parche para error de Altair
import sys
try:
    import altair as alt
    sys.modules['altair.vegalite.v4'] = alt
except ImportError:
    pass

import biosteam as bst
import thermosteam as tmo
import pandas as pd
import google.generativeai as genai

# =================================================================
# 1. CONFIGURACIÓN
# =================================================================
st.set_page_config(page_title="BioSTEAM Lab - IA", layout="wide")

# =================================================================
# 2. LÓGICA DE SIMULACIÓN
# =================================================================
def run_simulation(f_mosto, t_mosto, p_valve):
    bst.main_flowsheet.clear()
    chemicals = tmo.Chemicals(["Water", "Ethanol"])
    bst.settings.set_thermo(chemicals)

    mosto = bst.Stream("1_MOSTO", 
                       Water=f_mosto * 0.9, 
                       Ethanol=f_mosto * 0.1, 
                       units="kg/hr", 
                       T=t_mosto + 273.15, 
                       P=101325)

    vinazas_retorno = bst.Stream("Vinazas_Retorno", Water=200, T=95+273.15, P=300000)

    P100 = bst.Pump("P100", ins=mosto, P=4*101325)
    W210 = bst.HXprocess("W210", ins=(P100-0, vinazas_retorno), outs=("3_Mosto_Pre", "Drenaje"))
    W210.outs[0].T = 85 + 273.15

    W220 = bst.HXutility("W220", ins=W210-0, outs="Mezcla", T=92+273.15)
    V100 = bst.IsenthalpicValve("V100", ins=W220-0, outs="Mezcla_Bif", P=p_valve * 1e5)
    V1 = bst.Flash("V1", ins=V100-0, outs=("Vapor_Caliente", "Vinazas"), P=p_valve * 1e5, Q=0)
    
    # IMPORTANTE: ID "Producto_Final" para la métrica
    W310 = bst.HXutility("W310", ins=V1-0, outs="Producto_Final", T=25+273.15)
    
    P200 = bst.Pump("P200", ins=V1-1, outs=vinazas_retorno, P=3*101325)

    eth_sys = bst.System("eth_sys", path=(P100, W210, W220, V100, V1, W310, P200))
    
    try:
        eth_sys.simulate()
        return eth_sys, True
    except:
        return None, False

# =================================================================
# 3. INTERFAZ
# =================================================================
st.title("🚀 Simulador BioSTEAM con IA")

with st.sidebar:
    st.header("🎮 Panel de Control")
    f_in = st.number_input("Flujo Alimentación (kg/h)", 500, 5000, 1000)
    t_in = st.slider("Temp. Entrada (°C)", 10, 60, 25)
    p_v = st.slider("Presión Flash (bar)", 0.2, 2.0, 1.0)

sys_obj, success = run_simulation(f_in, t_in, p_v)

if success:
    # --- Cambio Clave: Acceso a corrientes vía bst.main_flowsheet ---
    f_sheet = bst.main_flowsheet
    prod_stream = f_sheet.stream.Producto_Final
    
    # Métricas
    c1, c2, c3 = st.columns(3)
    pureza = (prod_stream.imass['Ethanol'] / prod_stream.F_mass) if prod_stream.F_mass > 0 else 0
    c1.metric("Pureza Etanol", f"{pureza:.1%}")
    c2.metric("Producción Total", f"{prod_stream.F_mass:.2f} kg/h")
    c3.metric("Estado", "✅ Operativo")

    # Tablas
    tab_res, tab_ia = st.tabs(["📊 Resultados", "🤖 Tutor IA"])
    
    with tab_res:
        # Generar tabla de corrientes manualmente para mayor control
        m_data = []
        for s in f_sheet.stream:
            if s.F_mass > 0.1:
                m_data.append({
                    "Corriente": s.ID,
                    "T (°C)": round(s.T - 273.15, 2),
                    "Flujo (kg/h)": round(s.F_mass, 2),
                    "% Etanol": f"{(s.imass['Ethanol']/s.F_mass):.1%}" if s.F_mass > 0 else "0%"
                })
        st.table(pd.DataFrame(m_data))

    with tab_ia:
        if "GEMINI_API_KEY" in st.secrets:
            if st.button("Analizar con IA"):
                genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
                model = genai.GenerativeModel('gemini-1.5-flash')
                prompt = f"Analiza estos resultados de destilación: {pd.DataFrame(m_data).to_string()}. Da un consejo técnico."
                res = model.generate_content(prompt)
                st.write(res.text)
        else:
            st.warning("Configura tu API Key en Secrets.")
else:
    st.error("Error en la simulación. Revisa los parámetros.")
