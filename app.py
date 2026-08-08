import streamlit as st
import pandas as pd
from datetime import datetime
import zoneinfo  # Manejo de zona horaria de Perú (UTC-5)
import io
import time
import gspread

# --- CONFIGURACIÓN DE ZONA HORARIA (PERÚ) ---
LIMA_TZ = zoneinfo.ZoneInfo("America/Lima")

def obtener_ahora_peru():
    """Devuelve un objeto datetime con la hora exacta de Perú"""
    return datetime.now(LIMA_TZ)

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="Tiendas Premium EIRL",
    page_icon="🏪",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CONEXIÓN A PRUEBA DE ERRORES ---
@st.cache_resource
def conectar_google_sheets():
    try:
        if "gcp_service_account" in st.secrets:
            creds_dict = dict(st.secrets["gcp_service_account"])
            if "private_key" in creds_dict:
                pk = creds_dict["private_key"]
                pk = pk.replace("\\n", "\n")
                creds_dict["private_key"] = pk
            client = gspread.service_account_from_dict(creds_dict)
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
                df = pd.DataFrame(datos)
                # Asegurar columnas adicionales si no existen en el Sheet
                for col in ["direccion", "telefono", "contacto_emergencia", "link_maps"]:
                    if col not in df.columns:
                        df[col] = ""
                return df
        except Exception as e:
            st.error(f"Error al leer Colaboradores: {e}")
            
    return pd.DataFrame([
        {"dni": "75522639", "nombre": "Fran Bazan Insapillo", "cargo": "Colaborador Multifuncional", "estado": "Activo", "clave": "12345", "rol": "operativo", "direccion": "Sin Registrar", "telefono": "-", "contacto_emergencia": "-", "link_maps": ""},
        {"dni": "75101522", "nombre": "Luz Soplin Chota", "cargo": "Colaborador Multifuncional", "estado": "Activo", "clave": "12345", "rol": "operativo", "direccion": "Sin Registrar", "telefono": "-", "contacto_emergencia": "-", "link_maps": ""},
        {"dni": "75895270", "nombre": "Administrador", "cargo": "Gerente de Tienda", "estado": "Activo", "clave": "admin123", "rol": "admin", "direccion": "Sede Central", "telefono": "-", "contacto_emergencia": "-", "link_maps": ""}
    ])

def guardar_colaborador_gsheets(dni, nombre, cargo, estado, clave, rol, direccion="", telefono="", contacto_emergencia="", link_maps=""):
    if doc_sheets:
        try:
            hoja = doc_sheets.worksheet("Colaboradores")
            hoja.append_row([str(dni), nombre, cargo, estado, str(clave), rol, direccion, str(telefono), contacto_emergencia, link_maps])
        except Exception as e:
            st.error(f"❌ Error al guardar colaborador en Google Sheets: {e}")

def actualizar_hoja_completa(nombre_hoja, df):
    if doc_sheets:
        try:
            hoja = doc_sheets.worksheet(nombre_hoja)
            hoja.clear()
            hoja.update([df.columns.values.tolist()] + df.astype(str).values.tolist())
        except Exception as e:
            st.error(f"❌ Error al actualizar {nombre_hoja} en Google Sheets: {e}")

def guardar_asistencia_gsheets(dni, nombre, tipo, fecha_hora, fecha, observacion=""):
    if doc_sheets:
        try:
            hoja = doc_sheets.worksheet("Asistencia")
            hoja.append_row([str(dni), nombre, tipo, fecha_hora, fecha, observacion])
        except Exception as e:
            st.error(f"❌ Error al guardar asistencia en Google Sheets: {e}")

def guardar_descuadre_gsheets(fecha, dni, nombre, tipo, monto, observacion, fecha_registro):
    if doc_sheets:
        try:
            hoja = doc_sheets.worksheet("Descuadres")
            hoja.append_row([fecha, str(dni), nombre, tipo, monto, observacion, fecha_registro])
        except Exception as e:
            st.error(f"❌ Error al guardar descuadre en Google Sheets: {e}")

# --- CSS MINIMALISTA Y EJECUTIVO ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@300;400;500;600;700&display=swap');

    html, body, [class*="css"], .stMarkdown, div, button, input, select, textarea {
        font-family: 'Montserrat', sans-serif !important;
    }

    .stApp {
        background-color: #FAFAFA;
    }

    header[data-testid="stHeader"] {
        background-color: transparent !important;
        z-index: 100;
    }

    header[data-testid="stHeader"] button {
        color: #111827 !important;
    }

    .market-header {
        background-color: #FFFFFF;
        padding: 20px 24px;
        border-radius: 8px;
        border: 1px solid #E5E7EB;
        border-left: 4px solid #EC3237;
        margin-bottom: 24px;
    }
    .market-header h1 {
        color: #111827 !important;
        margin: 0;
        font-size: 1.3rem !important;
        font-weight: 600 !important;
        letter-spacing: -0.3px;
    }
    .market-header p {
        color: #6B7280;
        margin: 4px 0 0 0;
        font-size: 0.85rem;
        font-weight: 400;
    }

    .info-card {
        background-color: #FFFFFF;
        padding: 18px 20px;
        border-radius: 8px;
        border: 1px solid #E5E7EB;
        margin-bottom: 15px;
    }
    .info-label {
        color: #6B7280;
        font-size: 0.7rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.8px;
    }
    .info-value {
        color: #111827;
        font-size: 1.4rem;
        font-weight: 700;
        margin-top: 4px;
    }

    .stButton>button {
        background-color: #111827 !important;
        color: #FFFFFF !important;
        border-radius: 6px !important;
        border: none !important;
        font-weight: 500 !important;
        font-size: 0.82rem !important;
        height: 2.8em !important;
        transition: all 0.2s ease !important;
        letter-spacing: 0.3px;
    }
    .stButton>button:hover {
        background-color: #374151 !important;
    }

    .btn-ingreso > button {
        background-color: #00A959 !important;
    }
    .btn-ingreso > button:hover {
        background-color: #008847 !important;
    }

    .btn-salida > button {
        background-color: #EC3237 !important;
    }
    .btn-salida > button:hover {
        background-color: #D02429 !important;
    }

    [data-testid="stSidebar"] {
        background-color: #111827 !important;
        border-right: 1px solid #1F2937;
    }
    [data-testid="stSidebar"] * {
        color: #E5E7EB !important;
    }
    
    .btn-logout > button {
        background-color: transparent !important;
        border: 1px solid #374151 !important;
        color: #9CA3AF !important;
    }
    .btn-logout > button:hover {
        background-color: #1F2937 !important;
        color: #FFFFFF !important;
    }

    div[data-testid="stForm"], div[data-testid="stExpander"] {
        border-radius: 8px !important;
        border: 1px solid #E5E7EB !important;
        background-color: #FFFFFF !important;
        padding: 20px !important;
        box-shadow: none !important;
    }

    .stDataFrame {
        border: 1px solid #E5E7EB;
        border-radius: 6px;
    }
</style>
""", unsafe_allow_html=True)

# --- INITIALIZATION ---
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
            st.session_state.asistencia = pd.DataFrame(columns=["dni", "nombre", "tipo", "fecha_hora", "fecha", "observacion"])
    else:
        st.session_state.asistencia = pd.DataFrame(columns=["dni", "nombre", "tipo", "fecha_hora", "fecha", "observacion"])

# Asegurar columna de observación en Asistencia
if "observacion" not in st.session_state.asistencia.columns:
    st.session_state.asistencia["observacion"] = ""

if "descuadres" not in st.session_state:
    if doc_sheets:
        try:
            data_desc = doc_sheets.worksheet("Descuadres").get_all_records()
            st.session_state.descuadres = pd.DataFrame(data_desc)
        except Exception:
            st.session_state.descuadres = pd.DataFrame(columns=["fecha", "dni", "nombre", "tipo", "monto", "observacion", "fecha_registro"])
    else:
        st.session_state.descuadres = pd.DataFrame(columns=["fecha", "dni", "nombre", "tipo", "monto", "observacion", "fecha_registro"])

USUARIOS = {}
for _, row in st.session_state.empleados.iterrows():
    if str(row.get("estado", "")).lower() == "activo":
        USUARIOS[str(row["nombre"])] = {
            "clave": str(row["clave"]),
            "rol": str(row["rol"]),
            "dni": str(row["dni"])
        }

# --- LOGIN MINIMALISTA ---
if not st.session_state.usuario_login:
    st.markdown("<br><br>", unsafe_allow_html=True)
    c_log1, c_log2, c_log3 = st.columns([1, 1, 1])
    with c_log2:
        with st.container(border=True):
            st.markdown("""
                <div style='text-align: center; padding-bottom: 12px;'>
                    <span style='font-size: 0.75rem; font-weight: 700; letter-spacing: 1.5px; color: #EC3237;'>TIENDAS PREMIUM</span>
                    <h3 style='margin: 4px 0 0 0; font-weight: 600; color: #111827; font-size: 1.1rem;'>Iniciar Sesión</h3>
                </div>
            """, unsafe_allow_html=True)
            
            usuario_sel = st.selectbox("Usuario", list(USUARIOS.keys()))
            clave_input = st.text_input("Contraseña", type="password")
            st.markdown("<br>", unsafe_allow_html=True)
            
            if st.button("Ingresar al Sistema", width="stretch"):
                if clave_input == USUARIOS[usuario_sel]["clave"]:
                    st.session_state.usuario_login = usuario_sel
                    st.success("Acceso concedido")
                    time.sleep(0.3)
                    st.rerun()
                else:
                    st.error("Credenciales incorrectas")
    st.stop()

user_actual = st.session_state.usuario_login
rol_actual = USUARIOS[user_actual]["rol"]
dni_actual = USUARIOS[user_actual]["dni"]

def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False)
    return output.getvalue()

# MEJORA 1 y 3: Validación anti-doble marcación y soporte de observación/motivo
def registrar_marca(dni, nombre, tipo, observacion=""):
    hoy_str = obtener_ahora_peru().strftime("%Y-%m-%d")
    
    # Validar si la última marcación registrada hoy es del mismo tipo
    if not st.session_state.asistencia.empty:
        df_hoy_user = st.session_state.asistencia[
            (st.session_state.asistencia["fecha"].astype(str) == hoy_str) & 
            (st.session_state.asistencia["dni"].astype(str) == str(dni))
        ]
        if not df_hoy_user.empty:
            ultima_marca = df_hoy_user.iloc[0]["tipo"]
            if ultima_marca == tipo:
                st.warning(f"⚠️ Ya registraste un **{tipo}** previamente en esta jornada.")
                return False

    ahora_peru = obtener_ahora_peru()
    fecha_h = ahora_peru.strftime("%Y-%m-%d %H:%M:%S")
    fecha_s = ahora_peru.strftime("%Y-%m-%d")
    
    nueva_marca = {
        "dni": str(dni),
        "nombre": nombre,
        "tipo": tipo,
        "fecha_hora": fecha_h,
        "fecha": fecha_s,
        "observacion": observacion
    }
    st.session_state.asistencia = pd.concat([pd.DataFrame([nueva_marca]), st.session_state.asistencia], ignore_index=True)
    guardar_asistencia_gsheets(dni, nombre, tipo, fecha_h, fecha_s, observacion)
    return True

# Helper para obtener solo colaboradores (excluyendo Administradores)
def obtener_solo_colaboradores():
    if "rol" in st.session_state.empleados.columns:
        df_colab = st.session_state.empleados[st.session_state.empleados["rol"] != "admin"]
    else:
        df_colab = st.session_state.empleados[st.session_state.empleados["nombre"] != "Administrador"]
    return df_colab["nombre"].unique().tolist()

# Helper para renderizar card visual de ficha técnica
def renderizar_card_ficha(emp_info):
    st.markdown(f"""
    <div style="border:1px solid #E5E7EB; border-radius:8px; padding:18px; background-color:#FFFFFF; margin-bottom:15px;">
        <h3 style="margin:0 0 10px 0; font-size:1.1rem; color:#111827;">👤 {emp_info.get('nombre', '')}</h3>
        <p style="margin:2px 0; font-size:0.85rem; color:#4B5563;"><b>Cargo:</b> {emp_info.get('cargo', '')} | <b>DNI:</b> {emp_info.get('dni', '')}</p>
        <p style="margin:2px 0; font-size:0.85rem; color:#4B5563;"><b>Rol:</b> {emp_info.get('rol', '')} | <b>Estado:</b> {emp_info.get('estado', '')}</p>
        <hr style="margin:10px 0; border:0; border-top:1px solid #E5E7EB;">
        <p style="margin:4px 0; font-size:0.85rem; color:#111827;"><b>📍 Dirección:</b> {emp_info.get('direccion', 'Sin registrar')}</p>
        <p style="margin:4px 0; font-size:0.85rem; color:#111827;"><b>📞 Teléfono:</b> {emp_info.get('telefono', 'Sin registrar')}</p>
        <p style="margin:4px 0; font-size:0.85rem; color:#111827;"><b>🚨 Contacto de Emergencia:</b> {emp_info.get('contacto_emergencia', 'Sin registrar')}</p>
    </div>
    """, unsafe_allow_html=True)
    maps_link = emp_info.get('link_maps', '')
    if pd.notna(maps_link) and str(maps_link).strip().startswith("http"):
        st.markdown(f"👉 [Ver Ubicación en Google Maps]({maps_link})")

# --- SIDEBAR ELEGANTE ---
st.sidebar.markdown("""
    <div style='padding: 8px 0 16px 0;'>
        <div style='font-size: 0.85rem; font-weight: 700; letter-spacing: 1px; color: #FFFFFF;'>
            TIENDAS <span style='color: #EC3237;'>PREMIUM</span>
        </div>
        <div style='font-size: 0.7rem; color: #6B7280; margin-top:2px;'>Sistema de Control Interno</div>
    </div>
""", unsafe_allow_html=True)

st.sidebar.markdown(f"""
    <div style='background-color: #1F2937; padding: 10px 12px; border-radius: 6px; margin-bottom: 16px;'>
        <div style='font-size: 0.8rem; font-weight: 600; color: #F9FAFB;'>{user_actual}</div>
        <div style='font-size: 0.68rem; color: #9CA3AF; text-transform: uppercase;'>{rol_actual} • DNI {dni_actual}</div>
    </div>
""", unsafe_allow_html=True)

if rol_actual == "admin":
    menu = ["Dashboard General", "Gestión Colaboradores", "Historial de Descuadres", "Historial de Asistencias"]
else:
    menu = ["Marcar Asistencia", "Registrar Descuadre", "Mi Dashboard Mensual", "Mi Ficha Técnica"]

choice = st.sidebar.radio("Navegación", menu)

st.sidebar.markdown("<br><br>", unsafe_allow_html=True)
st.sidebar.markdown('<div class="btn-logout">', unsafe_allow_html=True)
if st.sidebar.button("Cerrar Sesión", width="stretch"):
    st.session_state.usuario_login = None
    st.rerun()
st.sidebar.markdown('</div>', unsafe_allow_html=True)

# -------------------- MÓDULOS OPERATIVOS --------------------

if choice == "Marcar Asistencia":
    st.markdown(f"""
        <div class="market-header">
            <h1>Terminal de Asistencia</h1>
            <p>Colaborador activo: <b>{user_actual}</b></p>
        </div>
    """, unsafe_allow_html=True)

    col_main, col_preview = st.columns([1.1, 1])

    with col_main:
        with st.container(border=True):
            st.markdown("<h4 style='margin:0; font-size:1rem; color:#111827;'>Registro de Turno</h4>", unsafe_allow_html=True)
            st.caption("Selecciona el tipo de marcación que deseas realizar:")
            
            # MEJORA 3: Opcion de sustento/nota voluntaria
            obs_marca = st.text_input("Observación / Justificación (Opcional)", placeholder="Ej. Retraso por tráfico, permiso, etc.")
            st.markdown("<br>", unsafe_allow_html=True)

            c1, c2 = st.columns(2)
            with c1:
                st.markdown('<div class="btn-ingreso">', unsafe_allow_html=True)
                if st.button("Marcar Ingreso", width="stretch"):
                    if registrar_marca(dni_actual, user_actual, "INGRESO", obs_marca):
                        st.toast("Ingreso registrado correctamente")
                        time.sleep(0.3)
                        st.rerun()
                st.markdown('</div>', unsafe_allow_html=True)

            with c2:
                st.markdown('<div class="btn-salida">', unsafe_allow_html=True)
                if st.button("Marcar Salida", width="stretch"):
                    if registrar_marca(dni_actual, user_actual, "SALIDA", obs_marca):
                        st.toast("Salida registrada correctamente")
                        time.sleep(0.3)
                        st.rerun()
                st.markdown('</div>', unsafe_allow_html=True)

    with col_preview:
        st.markdown("<h4 style='margin:0; font-size:1rem; color:#111827; margin-bottom:12px;'>Marcaciones de Hoy</h4>", unsafe_allow_html=True)
        hoy_str = obtener_ahora_peru().strftime("%Y-%m-%d")
        
        if not st.session_state.asistencia.empty:
            df_mismarcas = st.session_state.asistencia[
                (st.session_state.asistencia["fecha"].astype(str) == hoy_str) & 
                (st.session_state.asistencia["dni"].astype(str) == str(dni_actual))
            ]

            if not df_mismarcas.empty:
                st.dataframe(
                    df_mismarcas[["tipo", "fecha_hora", "observacion"]],
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "tipo": "TIPO", 
                        "fecha_hora": "FECHA / HORA",
                        "observacion": "OBSERVACIÓN"
                    }
                )
            else:
                st.info("No hay marcaciones registradas la jornada de hoy.")
        else:
            st.info("No hay marcaciones registradas la jornada de hoy.")

elif choice == "Registrar Descuadre":
    st.markdown(f"""
        <div class="market-header">
            <h1>Registro de Descuadre de Caja</h1>
            <p>Responsable del reporte: <b>{user_actual}</b></p>
        </div>
    """, unsafe_allow_html=True)

    with st.form("form_descuadre_user", clear_on_submit=True):
        st.markdown("<h4 style='margin:0; font-size:1rem; color:#111827; margin-bottom:16px;'>Detalle del Movimiento</h4>", unsafe_allow_html=True)
        
        c1, c2 = st.columns(2)
        f_operacion = c1.date_input("Fecha Operativa", obtener_ahora_peru())
        tipo_desc = c2.selectbox("Tipo de Diferencia", ["Sobrante (+)", "Faltante (-)"])

        monto = st.number_input("Monto (S/.)", min_value=0.01, step=0.50, format="%.2f")
        obs = st.text_area("Sustento o motivo")

        if st.form_submit_button("Guardar Registro"):
            monto_final = monto if "+" in tipo_desc else -monto
            tipo_final = "Sobrante" if "+" in tipo_desc else "Faltante"
            f_reg = obtener_ahora_peru().strftime("%Y-%m-%d %H:%M:%S")

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
            st.toast("Descuadre registrado en la nube")

elif choice == "Mi Dashboard Mensual":
    st.markdown(f"""
        <div class="market-header">
            <h1>Rendimiento Mensual</h1>
            <p>Resumen consolidado para <b>{user_actual}</b></p>
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
            <div class="info-card">
                <div class="info-label">Días Trabajados</div>
                <div class="info-value">{dias_trabajados}</div>
            </div>
        ''', unsafe_allow_html=True)

    with k2:
        st.markdown(f'''
            <div class="info-card">
                <div class="info-label">Balance Acumulado Descuadres</div>
                <div class="info-value" style="color: {'#00A959' if monto_total >= 0 else '#EC3237'};">S/. {monto_total:.2f}</div>
            </div>
        ''', unsafe_allow_html=True)

    st.markdown("<h4 style='font-size:1rem; color:#111827; margin-top:10px;'>Historial Personal</h4>", unsafe_allow_html=True)
    if not df_mis_desc.empty:
        st.dataframe(
            df_mis_desc[["fecha", "tipo", "monto", "observacion"]],
            width="stretch",
            hide_index=True,
            column_config={"monto": st.column_config.NumberColumn("MONTO", format="S/. %.2f")}
        )
    else:
        st.info("Sin registros de descuadres en el período.")

elif choice == "Mi Ficha Técnica":
    st.markdown(f"""
        <div class="market-header">
            <h1>Mi Ficha Técnica</h1>
            <p>Información personal registrada en la empresa</p>
        </div>
    """, unsafe_allow_html=True)
    
    df_me = st.session_state.empleados[st.session_state.empleados["dni"].astype(str) == str(dni_actual)]
    if not df_me.empty:
        renderizar_card_ficha(df_me.iloc[0].to_dict())
    else:
        st.info("No se encontraron datos registrados.")

# -------------------- MÓDULOS ADMIN --------------------

elif choice == "Dashboard General":
    st.markdown("""
        <div class="market-header">
            <h1>Panel de Control General</h1>
            <p>Vista ejecutiva de la operación en tiempo real</p>
        </div>
    """, unsafe_allow_html=True)

    st.markdown("##### 🔍 Filtros de Consulta")
    col_f1, col_f2 = st.columns([1.5, 1])
    
    with col_f1:
        fecha_dash = st.date_input("Fecha de Consulta", obtener_ahora_peru(), key="dash_fecha")
    with col_f2:
        lista_colabs = ["Todos"] + obtener_solo_colaboradores()
        colab_dash = st.selectbox("Filtrar Colaborador", lista_colabs, key="dash_colab")

    f_dash_str = str(fecha_dash)
    
    # 1. Procesamiento de Asistencias y Descuadres del día
    df_asist_dash = st.session_state.asistencia.copy()
    df_desc_dash = st.session_state.descuadres.copy()
    
    fichas_colaboradores = {}  # Guardará el detalle estructurado por persona
    
    en_turno_cnt = 0
    concluido_cnt = 0

    if not df_asist_dash.empty:
        df_asist_dash = df_asist_dash[df_asist_dash["fecha"].astype(str) == f_dash_str]
        
        if colab_dash != "Todos":
            df_asist_dash = df_asist_dash[df_asist_dash["nombre"] == colab_dash]

        if not df_asist_dash.empty:
            df_asist_dash["dt"] = pd.to_datetime(df_asist_dash["fecha_hora"])
            
            for nombre_colab, grupo in df_asist_dash.groupby("nombre"):
                grupo_ordenado = grupo.sort_values("dt")
                
                ingresos = grupo_ordenado[grupo_ordenado["tipo"] == "INGRESO"]
                salidas = grupo_ordenado[grupo_ordenado["tipo"] == "SALIDA"]
                
                hora_ingreso = ingresos.iloc[0]["dt"].strftime("%H:%M:%S") if not ingresos.empty else "--:--:--"
                
                ultima_marca = grupo_ordenado.iloc[-1]
                
                if ultima_marca["tipo"] == "INGRESO":
                    estado = "🟢 En Turno"
                    hora_salida = "--:--:--"
                    en_turno_cnt += 1
                    
                    dt_ingreso = ingresos.iloc[0]["dt"]
                    if f_dash_str == obtener_ahora_peru().strftime("%Y-%m-%d"):
                        ahora = obtener_ahora_peru().replace(tzinfo=None)
                        segundos = (ahora - dt_ingreso).total_seconds()
                    else:
                        segundos = 0
                else:
                    estado = "⚪ Concluido"
                    hora_salida = salidas.iloc[-1]["dt"].strftime("%H:%M:%S") if not salidas.empty else "--:--:--"
                    concluido_cnt += 1
                    
                    dt_ingreso = ingresos.iloc[0]["dt"] if not ingresos.empty else None
                    dt_salida = salidas.iloc[-1]["dt"] if not salidas.empty else None
                    
                    if dt_ingreso and dt_salida:
                        segundos = (dt_salida - dt_ingreso).total_seconds()
                    else:
                        segundos = 0
                
                if segundos > 0:
                    horas = int(segundos // 3600)
                    minutos = int((segundos % 3600) // 60)
                    total_horas_str = f"{horas}h {minutos}m"
                else:
                    total_horas_str = "0h 0m"
                
                # Recopilar observaciones de asistencia
                obs_asistencia = [
                    f"[{r['tipo']}] {r['observacion']}" 
                    for _, r in grupo_ordenado.iterrows() 
                    if str(r.get('observacion', '')).strip() != ""
                ]

                # Recopilar descuadres específicos de este colaborador en la fecha
                descuadres_user = []
                monto_desc_user = 0.0
                if not df_desc_dash.empty:
                    df_d_u = df_desc_dash[
                        (df_desc_dash["fecha"].astype(str) == f_dash_str) & 
                        (df_desc_dash["nombre"] == nombre_colab)
                    ]
                    if not df_d_u.empty:
                        monto_desc_user = pd.to_numeric(df_d_u["monto"], errors="coerce").sum()
                        for _, r_d in df_d_u.iterrows():
                            descuadres_user.append({
                                "tipo": r_d["tipo"],
                                "monto": r_d["monto"],
                                "obs": r_d.get("observacion", "")
                            })

                fichas_colaboradores[nombre_colab] = {
                    "estado": estado,
                    "ingreso": hora_ingreso,
                    "salida": hora_salida,
                    "tiempo_total": total_horas_str,
                    "balance_descuadre": monto_desc_user,
                    "descuadres_detalle": descuadres_user,
                    "obs_asistencia": obs_asistencia
                }

    # Balance general de descuadres para los KPIs
    total_descuadre_monto = 0.0
    if not df_desc_dash.empty:
        df_desc_dash = df_desc_dash[df_desc_dash["fecha"].astype(str) == f_dash_str]
        if colab_dash != "Todos":
            df_desc_dash = df_desc_dash[df_desc_dash["nombre"] == colab_dash]
        total_descuadre_monto = pd.to_numeric(df_desc_dash["monto"], errors="coerce").sum() if not df_desc_dash.empty else 0.0

    # 2. Métricas Principales (KPIs)
    st.markdown("<br>", unsafe_allow_html=True)
    k1, k2, k3 = st.columns(3)
    with k1:
        st.markdown(f'<div class="info-card"><div class="info-label">En Turno Ahora</div><div class="info-value" style="color: #00A959;">{en_turno_cnt}</div></div>', unsafe_allow_html=True)
    with k2:
        st.markdown(f'<div class="info-card"><div class="info-label">Turno Concluido</div><div class="info-value" style="color: #6B7280;">{concluido_cnt}</div></div>', unsafe_allow_html=True)
    with k3:
        st.markdown(f'<div class="info-card"><div class="info-label">Balance Descuadres Hoy</div><div class="info-value" style="color: {"#00A959" if total_descuadre_monto >= 0 else "#EC3237"};">S/. {total_descuadre_monto:.2f}</div></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # 3. Desglose en Fichas Técnicas por Colaborador
    if fichas_colaboradores:
        st.markdown("<h4 style='font-size:1rem; color:#111827; margin-bottom:15px;'>📄 Ficha Técnica por Colaborador</h4>", unsafe_allow_html=True)

        for nombre_col, datos in fichas_colaboradores.items():
            with st.expander(f"👤 {nombre_col} — {datos['estado']}", expanded=True):
                fc1, fc2, fc3, fc4 = st.columns(4)
                
                with fc1:
                    st.caption("🕒 HORARIO INGRESO")
                    st.markdown(f"**{datos['ingreso']}**")
                
                with fc2:
                    st.caption("🛑 HORARIO SALIDA")
                    st.markdown(f"**{datos['salida']}**")
                
                with fc3:
                    st.caption("⏳ TIEMPO TRABAJADO")
                    st.markdown(f"**{datos['tiempo_total']}**")
                
                with fc4:
                    st.caption("💰 BALANCE DESCUADRE")
                    color_desc = "#00A959" if datos["balance_descuadre"] >= 0 else "#EC3237"
                    st.markdown(f"<span style='color:{color_desc}; font-weight:700;'>S/. {datos['balance_descuadre']:.2f}</span>", unsafe_allow_html=True)

                st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
                
                # Detalle de descuadres
                if datos["descuadres_detalle"]:
                    st.markdown("**:bar_chart: Detalle de Caja / Descuadre:**")
                    for d_item in datos["descuadres_detalle"]:
                        m_val = float(d_item['monto'])
                        signo_color = "green" if m_val >= 0 else "red"
                        obs_txt = f" — *Sustento:* {d_item['obs']}" if d_item['obs'] else ""
                        st.markdown(f"- **{d_item['tipo']}:** :{signo_color}[S/. {m_val:.2f}]{obs_txt}")
                else:
                    st.markdown("**:bar_chart: Detalle de Caja:** Sin descuadres registrados en la fecha.")

                # Detalle de observaciones en marcaciones
                if datos["obs_asistencia"]:
                    st.markdown("**:speech_balloon: Observaciones en Marcación:**")
                    for obs_item in datos["obs_asistencia"]:
                        st.markdown(f"- {obs_item}")

    else:
        st.info(f"No hay registros de marcación para la fecha {f_dash_str}.")

elif choice == "Gestión Colaboradores":
    st.markdown("""
        <div class="market-header">
            <h1>Gestión de Colaboradores</h1>
            <p>Mantenimiento de personal y accesos</p>
        </div>
    """, unsafe_allow_html=True)

    col_add, col_list = st.columns([1, 1.3])

    with col_add:
        with st.form("form_emp", clear_on_submit=True):
            st.markdown("<h4 style='margin:0; font-size:0.95rem; color:#111827; margin-bottom:12px;'>Nuevo Colaborador</h4>", unsafe_allow_html=True)
            dni_in = st.text_input("DNI / Identificación")
            nom_in = st.text_input("Nombre Completo")
            cargo_in = st.selectbox("Cargo", ["Cajero", "Supervisora", "Reposidor", "Gerente de Tienda"])
            rol_in = st.selectbox("Rol", ["operativo", "admin"])
            clave_in = st.text_input("Contraseña", type="password")
            
            # --- NUEVOS CAMPOS ---
            st.markdown("---")
            st.caption("Ficha Técnica / Datos Personales")
            dir_in = st.text_input("Dirección de Domicilio")
            tel_in = st.text_input("Número Teléfono / Celular")
            contacto_in = st.text_input("Contacto de Emergencia (Nombre y Teléfono)")
            maps_in = st.text_input("Link de Google Maps Domicilio")

            if st.form_submit_button("Guardar en Nube"):
                if not dni_in or not nom_in or not clave_in:
                    st.error("Campos requeridos incompletos.")
                else:
                    nuevo_e = {
                        "dni": str(dni_in),
                        "nombre": nom_in,
                        "cargo": cargo_in,
                        "estado": "Activo",
                        "clave": str(clave_in),
                        "rol": rol_in,
                        "direccion": dir_in,
                        "telefono": str(tel_in),
                        "contacto_emergencia": contacto_in,
                        "link_maps": maps_in
                    }
                    st.session_state.empleados = pd.concat([st.session_state.empleados, pd.DataFrame([nuevo_e])], ignore_index=True)
                    guardar_colaborador_gsheets(dni_in, nom_in, cargo_in, "Activo", clave_in, rol_in, dir_in, tel_in, contacto_in, maps_in)
                    st.toast("Colaborador agregado correctamente")
                    st.rerun()

    with col_list:
        tab_tabla, tab_fichas, tab_del = st.tabs(["📋 Directorio", "🎴 Fichas Técnicas", "🗑️ Eliminar"])
        
        with tab_tabla:
            st.markdown("<h4 style='margin:0; font-size:0.95rem; color:#111827; margin-bottom:12px;'>Directorio de Personal</h4>", unsafe_allow_html=True)
            cols_mostrar = [c for c in ["dni", "nombre", "cargo", "rol", "estado", "direccion", "telefono"] if c in st.session_state.empleados.columns]
            st.dataframe(
                st.session_state.empleados[cols_mostrar],
                width="stretch",
                hide_index=True
            )

        with tab_fichas:
            st.markdown("<h4 style='margin:0; font-size:0.95rem; color:#111827; margin-bottom:12px;'>Consulta Individual de Ficha</h4>", unsafe_allow_html=True)
            if not st.session_state.empleados.empty:
                colabs_lista = st.session_state.empleados["nombre"].tolist()
                colab_sel_ficha = st.selectbox("Seleccionar Colaborador para ver Ficha", colabs_lista, key="sel_ficha_admin")
                emp_data = st.session_state.empleados[st.session_state.empleados["nombre"] == colab_sel_ficha].iloc[0].to_dict()
                renderizar_card_ficha(emp_data)
            else:
                st.info("No hay colaboradores registrados.")

        with tab_del:
            if rol_actual == "admin" and not st.session_state.empleados.empty:
                lista_colabs = st.session_state.empleados["nombre"].tolist()
                colab_a_eliminar = st.selectbox("Seleccionar colaborador a eliminar", lista_colabs)
                confirm_del_colab = st.checkbox(f"Confirmar eliminación de {colab_a_eliminar}")
                
                if st.button("Eliminar Colaborador", type="primary"):
                    if confirm_del_colab:
                        st.session_state.empleados = st.session_state.empleados[st.session_state.empleados["nombre"] != colab_a_eliminar]
                        actualizar_hoja_completa("Colaboradores", st.session_state.empleados)
                        st.toast(f"Colaborador {colab_a_eliminar} eliminado.")
                        st.rerun()
                    else:
                        st.error("Por favor, marca la casilla de confirmación.")
