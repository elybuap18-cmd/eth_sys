import streamlit as st
import biosteam as bst
import thermosteam as tmo
import pandas as pd
import google.generativeai as genai
from PIL import Image
import os

# =================================================================
# 1. CONFIGURACIÓN DE IA (GEMINI)
# =================================================================
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"]) 
    model = genai.GenerativeModel('gemini-2.5-pro')
else:
    st.warning("⚠️ No se encontró la GEMINI_API_KEY en los Secrets de Streamlit.")

# =================================================================
# 2. LÓGICA DE SIMULACIÓN (ENCAPSULADA)
# =================================================================
def ejecutar_simulacion(flujo_total, pct_etanol, p_flash_kpa, t_mosto_c):
    """
    Encapsula la lógica de BioSTEAM. 
    Usa bst.main_flowsheet.clear() para evitar errores de IDs duplicados.
    """
    bst.main_flowsheet.clear() 
    
    # Configuración Termodinámica
    chemicals = tmo.Chemicals(["Water", "Ethanol"])
    bst.settings.set_thermo(chemicals)

    # Definición de Corrientes con parámetros dinámicos
    # Convertimos % másico a flujos individuales
    f_etanol = flujo_total * (pct_etanol / 100)
    f_agua = flujo_total - f_etanol

    mosto = bst.Stream("1-MOSTO",
                      Water=f_agua, Ethanol=f_etanol, units="kg/hr",
                      T=t_mosto_c + 273.15, P=101325)

    vinazas_retorno = bst.Stream("Vinazas-Retorno",
                                Water=200, Ethanol=0, units="kg/hr",
                                T=95 + 273.15, P=300000)

    # Definición de Equipos
    P100 = bst.Pump("P100", ins=mosto, P=4 * 101325)
    
    W210 = bst.HXprocess("W210",
                        ins=(P100-0, vinazas_retorno),
                        outs=("3-Mosto-Pre", "Drenaje"),
                        phase0="l", phase1="l")
    W210.outs[0].T = 85 + 273.15

    W220 = bst.HXutility("W220", ins=W210-0, outs="Mezcla", T=92 + 273.15)
    
    V100 = bst.IsenthalpicValve("V100", ins=W220-0, outs="Mezcla-Bifasica", P=101325)

    # Tanque Flash (P_flash de entrada es en kPa, BioSTEAM usa Pa)
    V1 = bst.Flash("V1", ins=V100-0, outs=("Vapor-Caliente", "Vinazas"), 
                   P=p_flash_kpa * 1000, Q=0)

    W310 = bst.HXutility("W310", ins=V1-0, outs="Producto-Final", T=25 + 273.15)

    P200 = bst.Pump("P200", ins=V1-1, outs=vinazas_retorno, P=3 * 101325)

    # Sistema y Simulación
    eth_sys = bst.System("planta_etanol", path=(P100, W210, W220, V100, V1, W310, P200))
    
    try:
        eth_sys.simulate()
        return eth_sys, None
    except Exception as e:
        return None, str(e)

# =================================================================
# 3. GENERACIÓN DE REPORTES (MANEJO DE ERRORES DE ENERGÍA)
# =================================================================
def generar_tablas(sistema):
    # Tabla de Materia
    datos_mat = []
    for s in sistema.streams:
        if s.F_mass > 0.01:
            datos_mat.append({
                "Corriente": s.ID,
                "Temp (°C)": round(s.T - 273.15, 2),
                "P (bar)": round(s.P / 1e5, 2),
                "Flujo (kg/h)": round(s.F_mass, 2),
                "% Etanol": f"{(s.imass['Ethanol']/s.F_mass if s.F_mass>0 else 0):.1%}"
            })
    df_m = pd.DataFrame(datos_mat)

    # Tabla de Energía (Uso de heat_utilities para evitar error .duty)
    datos_en = []
    for u in sistema.units:
        # Recuperación de calor interna
        if isinstance(u, bst.HXprocess):
            calor = (u.outs[0].H - u.ins[0].H) / 3600
            datos_en.append({"Equipo": u.ID, "Servicio": "Recuperación", "kW": round(calor, 2)})
        
        # Servicios auxiliares (Vapor/Agua)
        elif hasattr(u, 'heat_utilities') and u.heat_utilities:
            calor = sum(hu.duty for hu in u.heat_utilities) / 3600
            tipo = "Calentamiento" if calor > 0 else "Enfriamiento"
            dat
