import streamlit as st
import pandas as pd
from datetime import datetime
import io
import time

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="Control Asistencia & Caja | Premium Market",
    page_icon="🛍️",
    layout="wide"
)

# --- ESTILOS CORPORATIVOS (Premium Market: Naranja & Azul Marino) ---
st.markdown("""
<style>
    .main { background-color: #F8FAFC; }
    
    /* Botones primarios (Naranja Premium) */
    .stButton>button {
        background-color: #FF6B00 !important;
        color: white !important;
        border-radius: 8px !important;
        border: none !important;
        font-weight: bold !important;
        height: 3.2em !important;
        transition: all 0.3s ease !important;
        box-shadow: 0 4px 6px -1px rgba(255, 107, 0, 0.2);
    }
    .stButton>button:hover {
        background-color: #E05E00 !important;
        transform: translateY(-2px);
        box-shadow: 0 6px 12px -1px rgba(255, 107, 0, 0.3);
    }

    /* Botón gigante de Ingreso */
    div[data-testid="stForm"] button[kind="primary"], .btn-ingreso > button {
        background-color: #10B981 !important; /* Verde para ingreso */
    }

    /* Botón gigante de Salida */
    .btn-salida > button {
        background-color: #EF4444 !important; /* Rojo para salida */
    }

    /* Headings */
    h1, h2, h3 { color: #0F172A !important; font-family: 'Inter', sans-serif; }

    /* Tarjetas Métricas */
    .info-card {
        background-color: white;
        padding: 20px;
        border-radius: 12px;
        border-left: 6px solid #FF6B00;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
        margin-bottom: 15px;
    }
    .info-card-blue { border-left-color: #0F172A; }
    .info-card-green { border-left-color: #10B981; }
    .info-card-red { border-left-color: #EF4444; }

    .info-label { color: #64748B; font-size: 0.8rem; font-weight: bold; text-transform: uppercase; letter-spacing: 0.5px; }
    .info-value { color: #0F172A; font-size: 1.6rem; font-weight: 800; margin-top: 5px; }

    /* Sidebar */
    [data-testid="stSidebar"] { background-color: #0F172A; }
    [data-testid="stSidebar"] * { color: #F8FAFC !important; }

    /* Custom Header */
    .market-header {
        background: linear-gradient(90deg, #0F172A 0%, #1E293B 100%);
        padding: 24px;
        border-radius: 12px;
        color: white;
        margin-bottom: 25px;
        border-bottom: 4px solid #FF6B00;
    }
    .market-header h1 { color: #FFFFFF !important; margin: 0; }
    .market-header p { color: #94A3B8; margin: 5px 0 0 0; }
</style>
""", unsafe_allow_html=True)

# --- INICIALIZACIÓN DE SESSION STATE (MEMORIA LOCAL) ---
if "usuario_login" not in st.session_state:
    st.session_state.usuario_login = None

if "empleados" not in st.session_state:
    st.session_state.empleados = pd.DataFrame([
        {"dni": "72819034", "nombre": "Carlos Mendoza", "cargo": "Cajero", "estado": "Activo"},
        {"dni": "45129803", "nombre": "Ana Lucía Torres", "cargo": "Supervisora", "estado": "Activo"},
        {"dni": "10923847", "nombre": "Marcos Rivas", "cargo": "Reposidor", "estado": "Activo"}
    ])

if "asistencia" not in st.session_state:
    st.session_state.asistencia = pd.DataFrame(columns=["dni", "nombre", "tipo", "fecha_hora", "fecha", "operador"])

if "descuadres" not in st.session_state:
    st.session_state.descuadres = pd.DataFrame(columns=["fecha", "dni", "nombre", "tipo", "monto", "observacion", "fecha_registro", "operador"])

# --- LOGIN / SELECCIÓN DE OPERADOR ---
if not st.session_state.usuario_login:
    st.markdown("<br><br>", unsafe_allow_html=True)
    c_log1, c_log2, c_log3 = st.columns([1, 1.2, 1])
    with c_log2:
        with st.container(border=True):
            st.title("🛍️ Premium Market")
            st.subheader("Acceso a Terminal")
            usr = st.text_input("Nombre de Usuario / Operador de Caja")
            if st.button("INGRESAR AL SISTEMA", use_container_width=True):
                if usr.strip():
                    st.session_state.usuario_login = usr.strip()
                    st.success(f"Bienvenido/a, {usr}")
                    time.sleep(0.4)
                    st.rerun()
                else:
                    st.error("Ingrese un nombre de operador para continuar.")
    st.stop()

# --- FUNCIONES DE APOYO ---
def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False)
    return output.getvalue()

def registrar_marca(dni, nombre, tipo):
    ahora = datetime.now()
    nueva_marca = {
        "dni": dni,
        "nombre": nombre,
        "tipo": tipo,
        "fecha_hora": ahora.strftime("%Y-%m-%d %H:%M:%S"),
        "fecha": ahora.strftime("%Y-%m-%d"),
        "operador": st.session_state.usuario_login
    }
    st.session_state.asistencia = pd.concat([pd.DataFrame([nueva_marca]), st.session_state.asistencia], ignore_index=True)

# --- SIDEBAR NAVEGACIÓN ---
st.sidebar.markdown('<div style="font-size: 60px; text-align: center;">🛍️</div>', unsafe_allow_html=True)
st.sidebar.markdown("<h2 style='text-align: center;'>PREMIUM MARKET</h2>", unsafe_allow_html=True)
st.sidebar.markdown(f"<p style='text-align: center; font-size:13px;'>👤 Operador: <b>{st.session_state.usuario_login}</b></p>", unsafe_allow_html=True)

if st.sidebar.button("🚪 Cambiar Operador", use_container_width=True):
    st.session_state.usuario_login = None
    st.rerun()

st.sidebar.markdown("---")

menu = ["⏱️ Marcar Asistencia", "💰 Descuadres de Caja", "👥 Gestión Empleados", "📊 Dashboard Diario"]
choice = st.sidebar.radio("Módulos:", menu)

# -------------------- 1. MARCAR ASISTENCIA --------------------
if choice == "⏱️ Marcar Asistencia":
    st.markdown("""
        <div class="market-header">
            <h1>Terminal de Asistencia</h1>
            <p>Registro rápido de entradas y salidas de personal</p>
        </div>
    """, unsafe_allow_html=True)

    emp_activos = st.session_state.empleados[st.session_state.empleados["estado"] == "Activo"]

    if emp_activos.empty:
        st.warning("No hay empleados activos para registrar marcas.")
    else:
        col_main, col_preview = st.columns([1.2, 1])

        with col_main:
            with st.container(border=True):
                st.subheader("Seleccionar Colaborador")
                opciones_emp = {f"{row['nombre']} ({row['dni']})": row['dni'] for _, row in emp_activos.iterrows()}
                emp_sel_key = st.selectbox("Buscar por nombre o DNI:", list(opciones_emp.keys()))
                dni_sel = opciones_emp[emp_sel_key]
                nombre_sel = emp_sel_key.split(" (")[0]

                st.markdown("<br>", unsafe_allow_html=True)
                c1, c2 = st.columns(2)

                with c1:
                    st.markdown('<div class="btn-ingreso">', unsafe_allow_html=True)
                    if st.button("⏰ MARCAR INGRESO", use_container_width=True):
                        registrar_marca(dni_sel, nombre_sel, "INGRESO")
                        st.toast(f"Ingreso registrado: {nombre_sel}", icon="✅")
                    st.markdown('</div>', unsafe_allow_html=True)

                with c2:
                    st.markdown('<div class="btn-salida">', unsafe_allow_html=True)
                    if st.button("🚪 MARCAR SALIDA", use_container_width=True):
                        registrar_marca(dni_sel, nombre_sel, "SALIDA")
                        st.toast(f"Salida registrada: {nombre_sel}", icon="🚪")
                    st.markdown('</div>', unsafe_allow_html=True)

        with col_preview:
            st.subheader("Últimas Marcas de Hoy")
            hoy_str = datetime.now().strftime("%Y-%m-%d")
            df_hoy = st.session_state.asistencia[st.session_state.asistencia["fecha"] == hoy_str]

            if not df_hoy.empty:
                st.dataframe(
                    df_hoy[["nombre", "tipo", "fecha_hora"]],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "nombre": "EMPLEADO",
                        "tipo": "MARCA",
                        "fecha_hora": "HORA"
                    }
                )
            else:
                st.info("Sin registros el día de hoy.")

# -------------------- 2. DESCUADRES DE CAJA --------------------
elif choice == "💰 Descuadres de Caja":
    st.markdown("""
        <div class="market-header">
            <h1>Control de Descuadres de Caja</h1>
            <p>Registro y auditoría de diferencias operativas de caja</p>
        </div>
    """, unsafe_allow_html=True)

    t1, t2 = st.tabs(["Novedad de Caja", "Historial de Descuadres"])

    with t1:
        with st.form("form_descuadre", clear_on_submit=True):
            st.subheader("Registrar Inconsistencia")
            emp_activos = st.session_state.empleados[st.session_state.empleados["estado"] == "Activo"]
            
            c1, c2 = st.columns(2)
            opciones_emp = {f"{row['nombre']} ({row['dni']})": row['dni'] for _, row in emp_activos.iterrows()}
            emp_sel_key = c1.selectbox("Cajero Responsable:", list(opciones_emp.keys())) if opciones_emp else c1.text_input("Cajero Responsable")
            
            f_operacion = c2.date_input("Fecha Operativa", datetime.now())

            c3, c4 = st.columns(2)
            tipo_desc = c3.selectbox("Tipo de Descuadre", ["Sobrante (+)", "Faltante (-)"])
            monto = c4.number_input("Monto (S/.)", min_value=0.01, step=0.50, format="%.2f")

            obs = st.text_area("Observaciones o Sustento")

            if st.form_submit_button("REGISTRAR DESCUADRE"):
                if opciones_emp:
                    dni_sel = opciones_emp[emp_sel_key]
                    nombre_sel = emp_sel_key.split(" (")[0]
                else:
                    dni_sel = "S/D"
                    nombre_sel = emp_sel_key
                
                nuevo_row = {
                    "fecha": str(f_operacion),
                    "dni": dni_sel,
                    "nombre": nombre_sel,
                    "tipo": "Sobrante" if "+" in tipo_desc else "Faltante",
                    "monto": monto if "+" in tipo_desc else -monto,
                    "observacion": obs,
                    "fecha_registro": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "operador": st.session_state.usuario_login
                }
                st.session_state.descuadres = pd.concat([pd.DataFrame([nuevo_row]), st.session_state.descuadres], ignore_index=True)
                st.toast("Descuadre guardado exitosamente", icon="💰")

    with t2:
        if not st.session_state.descuadres.empty:
            st.dataframe(
                st.session_state.descuadres,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "monto": st.column_config.NumberColumn("MONTO (S/.)", format="S/. %.2f")
                }
            )
            st.download_button("Exportar Excel", to_excel(st.session_state.descuadres), "Descuadres_Caja.xlsx")
        else:
            st.info("No hay descuadres registrados.")

# -------------------- 3. GESTIÓN EMPLEADOS --------------------
elif choice == "👥 Gestión Empleados":
    st.markdown("""
        <div class="market-header">
            <h1>Directorio de Personal</h1>
            <p>Mantenimiento de colaboradores activos e inactivos</p>
        </div>
    """, unsafe_allow_html=True)

    col_add, col_list = st.columns([1, 1.5])

    with col_add:
        with st.form("form_emp", clear_on_submit=True):
            st.subheader("Agregar Nuevo Empleado")
            dni_in = st.text_input("DNI / Identificación")
            nom_in = st.text_input("Nombre Completo")
            cargo_in = st.selectbox("Cargo", ["Cajero", "Supervisora", "Reposidor", "Gerente de Tienda", "Seguridad"])

            if st.form_submit_button("GUARDAR EMPLEADO"):
                if not dni_in or not nom_in:
                    st.error("DNI y Nombre son obligatorios")
                elif dni_in in st.session_state.empleados["dni"].values:
                    st.error("El DNI ya se encuentra registrado")
                else:
                    nuevo_e = {"dni": dni_in, "nombre": nom_in, "cargo": cargo_in, "estado": "Activo"}
                    st.session_state.empleados = pd.concat([st.session_state.empleados, pd.DataFrame([nuevo_e])], ignore_index=True)
                    st.toast(f"Empleado {nom_in} añadido", icon="👥")
                    st.rerun()

    with col_list:
        st.subheader("Lista de Colaboradores")
        df_emp = st.session_state.empleados.copy()

        for idx, row in df_emp.iterrows():
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([2, 1, 1, 0.8])
                c1.markdown(f"**{row['nombre']}** \n`DNI: {row['dni']}` — *{row['cargo']}*")
                c2.markdown(f"**Estado:** {row['estado']}")
                
                label_btn = "Desactivar" if row["estado"] == "Activo" else "Activar"
                if c3.button(label_btn, key=f"btn_st_{row['dni']}"):
                    st.session_state.empleados.at[idx, "estado"] = "Inactivo" if row["estado"] == "Activo" else "Activo"
                    st.rerun()

                # Botón para ELIMINAR REGISTRO DEFINITIVAMENTE
                if c4.button("🗑️", key=f"btn_del_{row['dni']}", help="Eliminar empleado"):
                    st.session_state.empleados = st.session_state.empleados.drop(idx).reset_index(drop=True)
                    st.toast(f"Empleado {row['nombre']} eliminado", icon="🗑️")
                    st.rerun()

# -------------------- 4. DASHBOARD DIARIO --------------------
elif choice == "📊 Dashboard Diario":
    st.markdown("""
        <div class="market-header">
            <h1>Monitoreo Operativo en Tiempo Real</h1>
            <p>Estatus general de asistencia y balance diario de caja</p>
        </div>
    """, unsafe_allow_html=True)

    hoy_str = datetime.now().strftime("%Y-%m-%d")
    df_asist_hoy = st.session_state.asistencia[st.session_state.asistencia["fecha"] == hoy_str]

    # Procesar estado actual por empleado
    trabajando = []
    salieron = []

    if not df_asist_hoy.empty:
        ultimas_marcas = df_asist_hoy.sort_values("fecha_hora").groupby("dni").last()
        for dni, row in ultimas_marcas.iterrows():
            if row["tipo"] == "INGRESO":
                trabajando.append(row["nombre"])
            else:
                salieron.append(row["nombre"])

    # Cálculos de Descuadres del día
    df_desc_hoy = st.session_state.descuadres[st.session_state.descuadres["fecha"] == hoy_str]
    total_descuadre_monto = df_desc_hoy["monto"].sum() if not df_desc_hoy.empty else 0.0

    # KPIs
    k1, k2, k3 = st.columns(3)
    with k1:
        st.markdown(f'''
            <div class="info-card info-card-green">
                <div class="info-label">Trabajando Ahora</div>
                <div class="info-value">{len(trabajando)} Empleados</div>
            </div>
        ''', unsafe_allow_html=True)

    with k2:
        st.markdown(f'''
            <div class="info-card info-card-blue">
                <div class="info-label">Ya Salieron Hoy</div>
                <div class="info-value">{len(salieron)} Empleados</div>
            </div>
        ''', unsafe_allow_html=True)

    with k3:
        color_card = "info-card-red" if total_descuadre_monto < 0 else "info-card"
        st.markdown(f'''
            <div class="info-card {color_card}">
                <div class="info-label">Balance Descuadres Hoy</div>
                <div class="info-value">S/. {total_descuadre_monto:.2f}</div>
            </div>
        ''', unsafe_allow_html=True)

    # Detalle de Estados (CORREGIDO: Usando st.caption en lugar de st.gray)
    col_t1, col_t2 = st.columns(2)

    with col_t1:
        st.subheader("🟢 Laborando Actualmente")
        if trabajando:
            for nom in trabajando:
                st.success(f"👤 {nom}")
        else:
            st.info("Sin personal laborando actualmente.")

    with col_t2:
        st.subheader("🚪 Turno Finalizado")
        if salieron:
            for nom in salieron:
                st.caption(f"👤 **{nom}** (Salida registrada)")
        else:
            st.info("Sin registros de salida en la fecha.")

st.markdown("---")
st.markdown('<div style="text-align:center; color:#64748B; font-weight:bold; font-size:12px;">Premium Market System v2.0 | Control de Gestión</div>', unsafe_allow_html=True)
