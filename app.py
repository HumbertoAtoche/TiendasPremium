import streamlit as st
from database import crear_bd

# Crear la BD si no existe
crear_bd()

st.set_page_config(
    page_title="Tiendas Premium",
    page_icon="🏪",
    layout="wide"
)

st.markdown("""
<style>

[data-testid="stSidebar"]{
    background:#07456a;
}

[data-testid="stSidebar"] *{
    color:white;
}

.stButton>button{
    background:#ed701b;
    color:white;
    font-weight:bold;
    border:none;
    border-radius:8px;
}

.stButton>button:hover{
    background:#c95d13;
    color:white;
}

.kpi{
    background:white;
    padding:15px;
    border-radius:10px;
    box-shadow:0px 2px 8px rgba(0,0,0,.15);
    text-align:center;
}

</style>
""", unsafe_allow_html=True)

st.sidebar.title("🏪 Tiendas Premium")

st.title("🏪 Sistema de Control")

st.write("Bienvenido al sistema de marcación.")

st.info(
"""
Utiliza el menú de la izquierda para acceder a:

• Marcador de ingreso y salida

• Descuadre de caja

• Usuarios
"""
)
