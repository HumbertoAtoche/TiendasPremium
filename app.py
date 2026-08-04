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

# --- ESTILOS CORPORATIVOS TIENDAS PREMIUM ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700;800&display=swap');

    html, body, [class*="css"], .stMarkdown, div, button, input, select, textarea {
        font-family: 'Montserrat', sans-serif !important;
    }

    .main {
        background-color: #f8fafc;
    }

    /* Botones primarios y generales */
    .stButton>button {
        background-color: #ec3237 !important;
        color: white !important;
        border-radius: 8px !important;
        border: none !important;
        font-weight: 700 !important;
        height: 3.2em !important;
        transition: all 0.25s ease-in-out !important;
        box-shadow: 0 4px 10px rgba(236, 50, 55, 0.2) !important;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .stButton>button:hover {
        background-color: #d02429 !important;
        transform: translateY(-2px);
        box-shadow: 0 6px 14px rgba(236, 50, 55, 0.3) !important;
    }

    /* Botones semánticos especiales */
    .btn-ingreso > button {
        background-color: #00a959 !important;
        box-shadow: 0 4px 10px rgba(0, 169, 89, 0.2) !important;
    }
    .btn-ingreso > button:hover {
        background-color: #008847 !important;
        box-shadow: 0 6px 14px rgba(0, 169, 89, 0.3) !important;
    }

    .btn-salida > button {
        background-color: #ec3237 !important;
        box-shadow: 0 4px 10px rgba(236, 50, 55, 0.2) !important;
    }
    .btn-salida > button:hover {
        background-color: #d02429 !important;
    }

    /* Encabezados y Textos */
    h1, h2, h3, h4 {
        color: #1e293b !important;
        font-family: 'Montserrat', sans-serif !important;
        font-weight: 700 !important;
    }

    /* Tarjetas Métricas */
    .info-card {
        background-color: #ffffff;
        padding: 22px;
        border-radius: 12px;
        border-left: 6px solid #ec3237;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.04);
        margin-bottom: 15px;
    }
    .info-card-brand { border-left-color: #ec3237; }
    .info-card-green { border-left-color: #00a959; }
    .info-card-dark  { border-left-color: #1e293b; }

    .info-label {
        color: #64748b;
        font-size: 0.75rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.8px;
    }
    .info-value {
        color: #0f172a;
        font-size: 1.75rem;
        font-weight: 800;
        margin-top: 6px;
    }

    /* Barra lateral */
    [data-testid="stSidebar"] {
        background-color: #1e293b !important;
    }
    [data-testid="stSidebar"] * {
        color: #f8fafc !important;
    }
    [data-testid="stSidebar"] .stRadio label {
        font-weight: 500;
        padding: 6px 0;
    }

    /* Banner de Cabecera Principal */
    .market-header {
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
        padding: 28px 24px;
        border-radius: 14px;
        color: white;
        margin-bottom: 25px;
        border-bottom: 4px solid #ec3237;
        box-shadow: 0 6px 16px rgba(0, 0, 0, 0.06);
    }
    .market-header h1 {
        color: #ffffff !important;
        margin: 0;
        font-size: 1.8rem;
    }
    .market-header p {
        color: #cbd5e1;
        margin: 6px 0 0 0;
        font-size: 0.95rem;
    }

    /* Formularios y Cajas */
    div[data-testid="stForm"] {
        border-radius: 12px;
        border: 1px solid #e2e8f0;
        background-color: #ffffff;
        padding: 24px;
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
            st.markdown("<h2 style='text-align: center; color: #ec3237 !important;'>🛒 TIENDAS PREMIUM</h2>", unsafe_allow_html=True)
            st.markdown("<p style='text-align: center; color: #64748B; font-size:0.9rem;'>Acceso al Portal Corporativo</p>", unsafe_allow_html=True)
            st.markdown("<hr style='margin:10px 0 20px 0; border-color:#f1f5f9;'>", unsafe_allow_html=True)
            
            usuario_sel = st.selectbox("Seleccionar Usuario:", list(USUARIOS.keys()))
            clave_input = st.text_input("Contraseña:", type="password")
            st.markdown("<br>", unsafe_allow_html=True)
            
            if st.button("INGRESAR AL SISTEMA", width="stretch"):
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
st.sidebar.markdown('<div style="font-size: 55px; text-align: center; margin-top: -10px;">🛒</div>', unsafe_allow_html=True)
st.sidebar.markdown("<h2 style='text-align: center; color: #ffffff !important; font-size:1.3rem; letter-spacing:1px;'>TIENDAS PREMIUM</h2>", unsafe_allow_html=True)
st.sidebar.markdown(f"<p style='text-align: center; font-size:12px; color:#cbd5e1;'>👤 <b>{user_actual}</b><br><span style='color:#00a959; font-weight:bold;'>({rol_actual.upper()})</span></p>", unsafe_allow_html=True)

if doc_sheets:
    st.sidebar.caption("🟢 Conectado a Google Sheets")
else:
    st.sidebar.caption("🔴 Modo Offline (Verifica Secrets / credentials.json)")

st.sidebar.markdown("<br>", unsafe_allow_html=True)

if st.sidebar.button("🚪 Cerrar Sesión", width="stretch"):
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
            <p>Colaborador: <b>{user_actual}</b> — Registra la entrada o salida de tu turno laboral.</p>
        </div>
    """, unsafe_allow_html=True)

    col_main, col_preview = st.columns([1.2, 1])

    with col_main:
        with st.container(border=True):
            st.subheader(f"Registro Rápido: {user_actual}")
            st.caption(f"DNI Asociado: {dni_actual}")
            st.markdown("<br>", unsafe_allow_html=True)

            c1, c2 = st.columns(2)
            with c1:
                st.markdown('<div class="btn-ingreso">', unsafe_allow_html=True)
                if st.button("⏰ MARCAR INGRESO", width="stretch"):
                    registrar_marca(dni_actual, user_actual, "INGRESO")
                    st.toast(f"Ingreso registrado: {user_actual}", icon="✅")
                st.markdown('</div>', unsafe_allow_html=True)

            with c2:
                st.markdown('<div class="btn-salida">', unsafe_allow_html=True)
                if st.button("🚪 MARCAR SALIDA", width="stretch"):
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
                    width="stretch",
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
            st.toast("Descuadre procesado correctamente", icon="💰")

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
            <div class="info-card info-card-dark">
                <div class="info-label">Días Registrados este Mes</div>
                <div class="info-value">{dias_trabajados} Días</div>
            </div>
        ''', unsafe_allow_html=True)

    with k2:
        color_card = "info-card-brand" if monto_total < 0 else "info-card-green"
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
            width="stretch",
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
            <p>Consolidado operativo en tiempo real — Tiendas Premium</p>
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
        st.markdown(f'<div class="info-card info-card-dark"><div class="info-label">Turno Finalizado</div><div class="info-value">{len(salieron)}</div></div>', unsafe_allow_html=True)
    with k3:
        color_k3 = "info-card-brand" if total_descuadre_monto < 0 else "info-card-green"
        st.markdown(f'<div class="info-card {color_k3}"><div class="info-label">Balance Descuadres Hoy</div><div class="info-value">S/. {total_descuadre_monto:.2f}</div></div>', unsafe_allow_html=True)

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
            <p>Mantenimiento de personal y credenciales corporativas</p>
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
            width="stretch",
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
            width="stretch",
            hide_index=True,
            column_config={"monto": st.column_config.NumberColumn("MONTO (S/.)", format="S/. %.2f")}
        )
        st.download_button("EXPORTAR EXCEL", to_excel(st.session_state.descuadres), "Descuadres_General.xlsx")
    else:
        st.info("Sin descuadres registrados en la base de datos.")

elif choice == "⏱️ Historial de Asistencias":
    st.markdown("""
        <div class="market-header">
            <h1>Reporte General de Marcaciones</h1>
            <p>Consolidado histórico de entradas y salidas de personal</p>
        </div>
    """, unsafe_allow_html=True)

    if not st.session_state.asistencia.empty:
        st.dataframe(st.session_state.asistencia, width="stretch", hide_index=True)
        st.download_button("EXPORTAR EXCEL", to_excel(st.session_state.asistencia), "Asistencias_General.xlsx")
    else:
        st.info("Sin asistencias registradas.")

st.markdown("---")
st.markdown('<div style="text-align:center; color:#64748B; font-weight:600; font-size:12px; font-family: \'Montserrat\', sans-serif;">Tiendas Premium System v3.0 | Google Sheets Integration</div>', unsafe_allow_html=True)
