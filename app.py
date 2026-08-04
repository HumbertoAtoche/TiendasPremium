import streamlit as st
import pandas as pd
from datetime import datetime
import io
import time
import gspread

# --- CONEXIÓN A PRUEBA DE ERRORES ---
@st.cache_resource
def conectar_google_sheets():
    try:
        # Modo Nube (Secrets de Streamlit)
        if "gcp_service_account" in st.secrets:
            # Creamos un diccionario copiable
            creds_dict = dict(st.secrets["gcp_service_account"])
            
            # Limpiamos los saltos de línea de la llave privada
            if "private_key" in creds_dict:
                pk = creds_dict["private_key"]
                pk = pk.replace("\\n", "\n")
                creds_dict["private_key"] = pk
            
            # Autenticación directa de gspread
            client = gspread.service_account_from_dict(creds_dict)
            
        # Modo Local
        else:
            client = gspread.service_account(filename="credentials.json")

        sheet = client.open("BD_PremiumMarket")
        return sheet

    except Exception as e:
        st.sidebar.error(f"⚠️ Error de Conexión: {e}")
        return None

doc_sheets = conectar_google_sheets()

# --- FUNCIONES DE LECTURA Y ESCRITURA EN LA NUBE ---
def obtener_colaboradores_gsheets():
    if doc_sheets:
        try:
            hoja = doc_sheets.worksheet("Colaboradores")
            datos = hoja.get_all_records()
            if datos:
                return pd.DataFrame(datos)
        except Exception as e:
            st.error(f"Error al leer Colaboradores: {e}")
            
    # Base de respaldo si la hoja está vacía o falla la lectura
    return pd.DataFrame([
        {"dni": "72819034", "nombre": "Fran", "cargo": "Cajero", "estado": "Activo", "clave": "12345", "rol": "operativo"},
        {"dni": "45129803", "nombre": "Luz Soplin", "cargo": "Supervisora", "estado": "Activo", "clave": "12345", "rol": "operativo"},
        {"dni": "00000000", "nombre": "Administrador", "cargo": "Gerente de Tienda", "estado": "Activo", "clave": "admin123", "rol": "admin"}
    ])

def guardar_colaborador_gsheets(dni, nombre, cargo, estado, clave, rol):
    if doc_sheets:
        try:
            hoja = doc_sheets.worksheet("Colaboradores")
            hoja.append_row([str(dni), nombre, cargo, estado, str(clave), rol])
        except Exception as e:
            st.error(f"❌ Error al guardar colaborador en Google Sheets: {e}")
    else:
        st.warning("⚠️ No hay conexión activa con Google Sheets")

def guardar_asistencia_gsheets(dni, nombre, tipo, fecha_hora, fecha):
    if doc_sheets:
        try:
            hoja = doc_sheets.worksheet("Asistencia")
            hoja.append_row([str(dni), nombre, tipo, fecha_hora, fecha])
        except Exception as e:
            st.error(f"❌ Error al guardar asistencia en Google Sheets: {e}")
    else:
        st.warning("⚠️ No hay conexión activa con Google Sheets")

def guardar_descuadre_gsheets(fecha, dni, nombre, tipo, monto, observacion, fecha_registro):
    if doc_sheets:
        try:
            hoja = doc_sheets.worksheet("Descuadres")
            hoja.append_row([fecha, str(dni), nombre, tipo, monto, observacion, fecha_registro])
        except Exception as e:
            st.error(f"❌ Error al guardar descuadre en Google Sheets: {e}")
    else:
        st.warning("⚠️ No hay conexión activa con Google Sheets")

# --- ESTILOS CORPORATIVOS PREMIUM MARKET ---
st.markdown("""
<style>

/* ===========================
    FUENTE Y FONDO
=========================== */

html, body, [class*="css"]{
    font-family:'Montserrat', sans-serif;
}

.stApp{
    background:#F6F7F9;
}

/* ===========================
    SIDEBAR
=========================== */

[data-testid="stSidebar"]{
    background:#FFFFFF;
    border-right:1px solid #E5E7EB;
}

[data-testid="stSidebar"] *{
    font-family:'Montserrat', sans-serif;
}

/* ===========================
    TITULOS
=========================== */

h1,h2,h3,h4{
    color:#1F2937 !important;
    font-weight:700 !important;
}

/* ===========================
    HEADER
=========================== */

.market-header{
    background:#FFFFFF;
    border-radius:12px;
    padding:28px;
    border-top:5px solid #EC3237;
    border-left:1px solid #ECECEC;
    border-right:1px solid #ECECEC;
    border-bottom:1px solid #ECECEC;
    margin-bottom:24px;
}

.market-header h1{
    color:#1F2937!important;
    font-size:30px;
    margin:0;
}

.market-header p{
    color:#6B7280;
    margin-top:6px;
    font-size:15px;
}

/* ===========================
    BOTONES
=========================== */

.stButton>button{
    width:100%;
    height:48px;
    border-radius:8px;
    border:1px solid #EC3237;
    background:white;
    color:#EC3237;
    font-weight:600;
    transition:0.2s;
}

.stButton>button:hover{
    background:#EC3237;
    color:white;
}

/* Botón verde */
.btn-ingreso button{
    border-color:#00A959!important;
    color:#00A959!important;
}

.btn-ingreso button:hover{
    background:#00A959!important;
    color:white!important;
}

/* Botón rojo */
.btn-salida button{
    border-color:#EC3237!important;
    color:#EC3237!important;
}

.btn-salida button:hover{
    background:#EC3237!important;
    color:white!important;
}

/* ===========================
    INPUTS
=========================== */

input, textarea{
    border-radius:8px!important;
}

.stTextInput input,
.stNumberInput input,
.stDateInput input{
    border:1px solid #D1D5DB!important;
}

.stSelectbox div[data-baseweb="select"]{
    border-radius:8px;
}

/* ===========================
    TARJETAS KPI
=========================== */

.info-card{
    background:white;
    border:1px solid #E5E7EB;
    border-radius:12px;
    padding:22px;
    margin-bottom:18px;
}

.info-card-blue{
    border-top:4px solid #374151;
}

.info-card-green{
    border-top:4px solid #00A959;
}

.info-card-red{
    border-top:4px solid #EC3237;
}

.info-label{
    font-size:12px;
    color:#6B7280;
    text-transform:uppercase;
    letter-spacing:.8px;
    font-weight:700;
}

.info-value{
    margin-top:8px;
    font-size:30px;
    font-weight:700;
    color:#111827;
}

/* ===========================
    FORMULARIOS
=========================== */

[data-testid="stForm"]{
    background:white;
    border:1px solid #E5E7EB;
    border-radius:12px;
    padding:22px;
}

/* ===========================
    DATAFRAME
=========================== */

[data-testid="stDataFrame"]{
    border:1px solid #E5E7EB;
    border-radius:10px;
}

/* ===========================
    ALERTAS
=========================== */

.stAlert{
    border-radius:8px;
}

/* ===========================
    RADIO
=========================== */

.stRadio label{
    font-weight:500;
}

/* ===========================
    EXPANDER
=========================== */

.streamlit-expanderHeader{
    font-weight:600;
}

/* ===========================
    SEPARADORES
=========================== */

hr{
    border:none;
    border-top:1px solid #E5E7EB;
}

</style>
""", unsafe_allow_html=True)

# --- INICIALIZACIÓN DE SESSION STATE Y NUBE ---
if "usuario_login" not in st.session_state:
    st.session_state.usuario_login = None

if "empleados" not in st.session_state:
    st.session_state.empleados = obtener_colaboradores_gsheets()

if "asistencia" not in st.session_state:
    if doc_sheets:
        try:
            data_asist = doc_sheets.worksheet("Asistencia").get_all_records()
            st.session_state.asistencia = pd.DataFrame(data_asist)
        except Exception:
            st.session_state.asistencia = pd.DataFrame(columns=["dni", "nombre", "tipo", "fecha_hora", "fecha"])
    else:
        st.session_state.asistencia = pd.DataFrame(columns=["dni", "nombre", "tipo", "fecha_hora", "fecha"])

if "descuadres" not in st.session_state:
    if doc_sheets:
        try:
            data_desc = doc_sheets.worksheet("Descuadres").get_all_records()
            st.session_state.descuadres = pd.DataFrame(data_desc)
        except Exception:
            st.session_state.descuadres = pd.DataFrame(columns=["fecha", "dni", "nombre", "tipo", "monto", "observacion", "fecha_registro"])
    else:
        st.session_state.descuadres = pd.DataFrame(columns=["fecha", "dni", "nombre", "tipo", "monto", "observacion", "fecha_registro"])

# Diccionario dinámico de usuarios cargado desde Google Sheets
USUARIOS = {}
for _, row in st.session_state.empleados.iterrows():
    if str(row.get("estado", "")).lower() == "activo":
        USUARIOS[str(row["nombre"])] = {
            "clave": str(row["clave"]),
            "rol": str(row["rol"]),
            "dni": str(row["dni"])
        }

# --- PANTALLA DE ACCESO (LOGIN) ---
if not st.session_state.usuario_login:
    st.markdown("<br><br>", unsafe_allow_html=True)
    c_log1, c_log2, c_log3 = st.columns([1, 1.2, 1])
    with c_log2:
        with st.container(border=True):
            st.markdown("<h2 style='text-align: center;'>🛍️ Premium Market</h2>", unsafe_allow_html=True)
            st.markdown("<p style='text-align: center; color: #64748B;'>Selecciona tu usuario para ingresar</p>", unsafe_allow_html=True)
            
            usuario_sel = st.selectbox("Seleccionar Usuario:", list(USUARIOS.keys()))
            clave_input = st.text_input("Contraseña:", type="password")
            
            if st.button("INGRESAR AL SISTEMA"):
                if clave_input == USUARIOS[usuario_sel]["clave"]:
                    st.session_state.usuario_login = usuario_sel
                    st.success(f"¡Bienvenido/a {usuario_sel}!")
                    time.sleep(0.4)
                    st.rerun()
                else:
                    st.error("Contraseña incorrecta")
    st.stop()

# --- DATOS DEL USUARIO ACTUAL ---
user_actual = st.session_state.usuario_login
rol_actual = USUARIOS[user_actual]["rol"]
dni_actual = USUARIOS[user_actual]["dni"]

# --- FUNCIONES DE APOYO ---
def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False)
    return output.getvalue()

def registrar_marca(dni, nombre, tipo):
    ahora = datetime.now()
    fecha_h = ahora.strftime("%Y-%m-%d %H:%M:%S")
    fecha_s = ahora.strftime("%Y-%m-%d")
    
    nueva_marca = {
        "dni": str(dni),
        "nombre": nombre,
        "tipo": tipo,
        "fecha_hora": fecha_h,
        "fecha": fecha_s
    }
    st.session_state.asistencia = pd.concat([pd.DataFrame([nueva_marca]), st.session_state.asistencia], ignore_index=True)
    guardar_asistencia_gsheets(dni, nombre, tipo, fecha_h, fecha_s)

# --- SIDEBAR NAVEGACIÓN ---
st.sidebar.markdown('<div style="font-size: 60px; text-align: center;">🛍️</div>', unsafe_allow_html=True)
st.sidebar.markdown("<h2 style='text-align: center;'>PREMIUM MARKET</h2>", unsafe_allow_html=True)
st.sidebar.markdown(f"<p style='text-align: center; font-size:13px;'>👤 Usuario: <b>{user_actual}</b><br><small>({rol_actual.upper()})</small></p>", unsafe_allow_html=True)

if doc_sheets:
    st.sidebar.caption("🟢 Conectado a Google Sheets")
else:
    st.sidebar.caption("🔴 Modo Offline (Verifica Secrets / credentials.json)")

if st.sidebar.button("🚪 Cerrar Sesión"):
    st.session_state.usuario_login = None
    st.rerun()

st.sidebar.markdown("---")

if rol_actual == "admin":
    menu = ["📊 Dashboard General", "👥 Gestión Colaboradores", "💰 Historial de Descuadres", "⏱️ Historial de Asistencias"]
else:
    menu = ["⏱️ Marcar Asistencia", "💰 Registrar Descuadre", "📊 Mi Dashboard Mensual"]

choice = st.sidebar.radio("Módulos:", menu)

# -------------------- MÓDULOS OPERATIVOS (CAJEROS / SUPERVISORES) --------------------

if choice == "⏱️ Marcar Asistencia":
    st.markdown(f"""
        <div class="market-header">
            <h1>Terminal de Asistencia</h1>
            <p>Hola <b>{user_actual}</b>, registra tu ingreso o salida de turno</p>
        </div>
    """, unsafe_allow_html=True)

    col_main, col_preview = st.columns([1.2, 1])

    with col_main:
        with st.container(border=True):
            st.subheader(f"Marcar Horario: {user_actual}")
            st.caption(f"DNI Asociado: {dni_actual}")
            st.markdown("<br>", unsafe_allow_html=True)

            c1, c2 = st.columns(2)
            with c1:
                st.markdown('<div class="btn-ingreso">', unsafe_allow_html=True)
                if st.button("⏰ MARCAR INGRESO"):
                    registrar_marca(dni_actual, user_actual, "INGRESO")
                    st.toast(f"Ingreso registrado: {user_actual}", icon="✅")
                st.markdown('</div>', unsafe_allow_html=True)

            with c2:
                st.markdown('<div class="btn-salida">', unsafe_allow_html=True)
                if st.button("🚪 MARCAR SALIDA"):
                    registrar_marca(dni_actual, user_actual, "SALIDA")
                    st.toast(f"Salida registrada: {user_actual}", icon="🚪")
                st.markdown('</div>', unsafe_allow_html=True)

    with col_preview:
        st.subheader("Tus Marcas de Hoy")
        hoy_str = datetime.now().strftime("%Y-%m-%d")
        
        if not st.session_state.asistencia.empty:
            df_mismarcas = st.session_state.asistencia[
                (st.session_state.asistencia["fecha"].astype(str) == hoy_str) & 
                (st.session_state.asistencia["dni"].astype(str) == str(dni_actual))
            ]

            if not df_mismarcas.empty:
                st.dataframe(
                    df_mismarcas[["tipo", "fecha_hora"]],
                    use_container_width=True,
                    hide_index=True,
                    column_config={"tipo": "MARCA", "fecha_hora": "HORA Y FECHA"}
                )
            else:
                st.info("Aún no tienes marcas registradas hoy.")
        else:
            st.info("Aún no tienes marcas registradas hoy.")

elif choice == "💰 Registrar Descuadre":
    st.markdown(f"""
        <div class="market-header">
            <h1>Registro de Descuadre de Caja</h1>
            <p>Responsable de Turno: <b>{user_actual}</b></p>
        </div>
    """, unsafe_allow_html=True)

    with st.form("form_descuadre_user", clear_on_submit=True):
        st.subheader("Reportar Novedad de Caja")
        
        c1, c2 = st.columns(2)
        f_operacion = c1.date_input("Fecha Operativa", datetime.now())
        tipo_desc = c2.selectbox("Tipo de Descuadre", ["Sobrante (+)", "Faltante (-)"])

        monto = st.number_input("Monto en Soles (S/.)", min_value=0.01, step=0.50, format="%.2f")
        obs = st.text_area("Sustento o Motivo de la diferencia")

        if st.form_submit_button("REGISTRAR DESCUADRE"):
            monto_final = monto if "+" in tipo_desc else -monto
            tipo_final = "Sobrante" if "+" in tipo_desc else "Faltante"
            f_reg = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            nuevo_row = {
                "fecha": str(f_operacion),
                "dni": str(dni_actual),
                "nombre": user_actual,
                "tipo": tipo_final,
                "monto": monto_final,
                "observacion": obs,
                "fecha_registro": f_reg
            }
            st.session_state.descuadres = pd.concat([pd.DataFrame([nuevo_row]), st.session_state.descuadres], ignore_index=True)
            guardar_descuadre_gsheets(str(f_operacion), dni_actual, user_actual, tipo_final, monto_final, obs, f_reg)
            st.toast("Descuadre procesado", icon="💰")

elif choice == "📊 Mi Dashboard Mensual":
    st.markdown(f"""
        <div class="market-header">
            <h1>Tu Rendimiento del Mes</h1>
            <p>Resumen personal para <b>{user_actual}</b></p>
        </div>
    """, unsafe_allow_html=True)

    df_mis_desc = pd.DataFrame()
    df_mis_asist = pd.DataFrame()

    if not st.session_state.descuadres.empty:
        df_mis_desc = st.session_state.descuadres[st.session_state.descuadres["dni"].astype(str) == str(dni_actual)]
    
    if not st.session_state.asistencia.empty:
        df_mis_asist = st.session_state.asistencia[st.session_state.asistencia["dni"].astype(str) == str(dni_actual)]

    monto_total = pd.to_numeric(df_mis_desc["monto"]).sum() if not df_mis_desc.empty else 0.0
    dias_trabajados = df_mis_asist["fecha"].nunique() if not df_mis_asist.empty else 0

    k1, k2 = st.columns(2)
    with k1:
        st.markdown(f'''
            <div class="info-card info-card-blue">
                <div class="info-label">Días Registrados este Mes</div>
                <div class="info-value">{dias_trabajados} Días</div>
            </div>
        ''', unsafe_allow_html=True)

    with k2:
        color_card = "info-card-red" if monto_total < 0 else "info-card-green"
        st.markdown(f'''
            <div class="info-card {color_card}">
                <div class="info-label">Balance Total Descuadres</div>
                <div class="info-value">S/. {monto_total:.2f}</div>
            </div>
        ''', unsafe_allow_html=True)

    st.subheader("Historial de mis descuadres")
    if not df_mis_desc.empty:
        st.dataframe(
            df_mis_desc[["fecha", "tipo", "monto", "observacion"]],
            use_container_width=True,
            hide_index=True,
            column_config={"monto": st.column_config.NumberColumn("MONTO", format="S/. %.2f")}
        )
    else:
        st.success("¡Excelente! No registras descuadres acumulados.")

# -------------------- MÓDULOS DE ADMINISTRADOR --------------------

elif choice == "📊 Dashboard General":
    st.markdown("""
        <div class="market-header">
            <h1>Panel de Control General</h1>
            <p>Consolidado operativo en tiempo real</p>
        </div>
    """, unsafe_allow_html=True)

    hoy_str = datetime.now().strftime("%Y-%m-%d")
    trabajando = []
    salieron = []

    if not st.session_state.asistencia.empty:
        df_asist_hoy = st.session_state.asistencia[st.session_state.asistencia["fecha"].astype(str) == hoy_str]
        if not df_asist_hoy.empty:
            ultimas_marcas = df_asist_hoy.sort_values("fecha_hora").groupby("dni").last()
            for dni, row in ultimas_marcas.iterrows():
                if row["tipo"] == "INGRESO":
                    trabajando.append(row["nombre"])
                else:
                    salieron.append(row["nombre"])

    total_descuadre_monto = 0.0
    if not st.session_state.descuadres.empty:
        df_desc_hoy = st.session_state.descuadres[st.session_state.descuadres["fecha"].astype(str) == hoy_str]
        total_descuadre_monto = pd.to_numeric(df_desc_hoy["monto"]).sum() if not df_desc_hoy.empty else 0.0

    k1, k2, k3 = st.columns(3)
    with k1:
        st.markdown(f'<div class="info-card info-card-green"><div class="info-label">En Turno Ahora</div><div class="info-value">{len(trabajando)}</div></div>', unsafe_allow_html=True)
    with k2:
        st.markdown(f'<div class="info-card info-card-blue"><div class="info-label">Turno Finalizado</div><div class="info-value">{len(salieron)}</div></div>', unsafe_allow_html=True)
    with k3:
        st.markdown(f'<div class="info-card info-card-red"><div class="info-label">Balance Descuadres Hoy</div><div class="info-value">S/. {total_descuadre_monto:.2f}</div></div>', unsafe_allow_html=True)

    col_t1, col_t2 = st.columns(2)
    with col_t1:
        st.subheader("🟢 En Turno")
        if trabajando:
            for nom in trabajando:
                st.success(f"👤 {nom}")
        else:
            st.info("Nadie en turno actualmente.")

    with col_t2:
        st.subheader("🚪 Finalizaron")
        if salieron:
            for nom in salieron:
                st.caption(f"👤 **{nom}** (Salida registrada)")
        else:
            st.info("Sin registros de salida hoy.")

elif choice == "👥 Gestión Colaboradores":
    st.markdown("""
        <div class="market-header">
            <h1>Gestión de Colaboradores</h1>
            <p>Mantenimiento de personal y credenciales</p>
        </div>
    """, unsafe_allow_html=True)

    col_add, col_list = st.columns([1, 1.3])

    with col_add:
        with st.form("form_emp", clear_on_submit=True):
            st.subheader("Agregar Nuevo Colaborador")
            dni_in = st.text_input("DNI / Identificación")
            nom_in = st.text_input("Nombre Completo")
            cargo_in = st.selectbox("Cargo", ["Cajero", "Supervisora", "Reposidor", "Gerente de Tienda"])
            rol_in = st.selectbox("Rol en Sistema", ["operativo", "admin"])
            clave_in = st.text_input("Contraseña de Acceso", type="password")

            if st.form_submit_button("GUARDAR EN NUBE"):
                if not dni_in or not nom_in or not clave_in:
                    st.error("DNI, Nombre y Contraseña son obligatorios")
                else:
                    nuevo_e = {
                        "dni": str(dni_in),
                        "nombre": nom_in,
                        "cargo": cargo_in,
                        "estado": "Activo",
                        "clave": str(clave_in),
                        "rol": rol_in
                    }
                    st.session_state.empleados = pd.concat([st.session_state.empleados, pd.DataFrame([nuevo_e])], ignore_index=True)
                    guardar_colaborador_gsheets(dni_in, nom_in, cargo_in, "Activo", clave_in, rol_in)
                    st.toast(f"Colaborador {nom_in} guardado", icon="👥")
                    st.rerun()

    with col_list:
        st.subheader("Directorio General")
        st.dataframe(
            st.session_state.empleados[["dni", "nombre", "cargo", "rol", "estado"]],
            use_container_width=True,
            hide_index=True
        )

elif choice == "💰 Historial de Descuadres":
    st.markdown("""
        <div class="market-header">
            <h1>Auditoría Completa de Descuadres</h1>
            <p>Reporte general para contabilidad y administración</p>
        </div>
    """, unsafe_allow_html=True)

    if not st.session_state.descuadres.empty:
        st.dataframe(
            st.session_state.descuadres,
            use_container_width=True,
            hide_index=True,
            column_config={"monto": st.column_config.NumberColumn("MONTO (S/.)", format="S/. %.2f")}
        )
        st.download_button("Exportar Excel", to_excel(st.session_state.descuadres), "Descuadres_General.xlsx")
    else:
        st.info("Sin descuadres registrados en la base de datos.")

elif choice == "⏱️ Historial de Asistencias":
    st.markdown("""
        <div class="market-header">
            <h1>Reporte General de Marcaciones</h1>
            <p>Consolidado histórico de entradas y salidas</p>
        </div>
    """, unsafe_allow_html=True)

    if not st.session_state.asistencia.empty:
        st.dataframe(st.session_state.asistencia, use_container_width=True, hide_index=True)
        st.download_button("Exportar Excel", to_excel(st.session_state.asistencia), "Asistencias_General.xlsx")
    else:
        st.info("Sin asistencias registradas.")

st.markdown("---")
st.markdown('<div style="text-align:center; color:#64748B; font-weight:bold; font-size:12px;">Premium Market System v3.0 | Google Sheets Integration</div>', unsafe_allow_html=True)
