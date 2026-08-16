import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta, time as dt_time
import calendar
import zoneinfo  # Manejo de zona horaria de Perú (UTC-5)
import io
import time
import gspread

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="Tiendas Premium EIRL",
    page_icon="🏪",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CONFIGURACIÓN DE ZONA HORARIA (PERÚ) ---
LIMA_TZ = zoneinfo.ZoneInfo("America/Lima")

def obtener_ahora_peru():
    return datetime.now(LIMA_TZ)

# --- REGLAS DE HORARIOS, JORNADA Y TOLERANCIA ---
JORNADA_MINUTOS_BASE = 345  # 5 horas con 45 minutos (5 * 60 + 45 = 345 min)

HORA_INICIO_MANANA = dt_time(8, 45)
HORA_LIMITE_MANANA = dt_time(8, 55)   # 10 min de tolerancia (hasta 8:55 am)

HORA_INICIO_TARDE = dt_time(15, 15)   # 3:15 pm
HORA_LIMITE_TARDE = dt_time(15, 25)   # 10 min de tolerancia (hasta 3:25 pm)

def calcular_tardanza_ingreso(fecha_hora_str):
    """
    Evalúa la hora de ingreso según los turnos de mañana y tarde.
    Retorna: (minutos_tardanza, es_tardanza, turno)
    """
    try:
        dt_marca = datetime.strptime(str(fecha_hora_str), "%Y-%m-%d %H:%M:%S")
        hora_marca = dt_marca.time()

        if hora_marca < dt_time(13, 0):
            turno = "Mañana"
            hora_prog = HORA_INICIO_MANANA
            hora_limite = HORA_LIMITE_MANANA
        else:
            turno = "Tarde"
            hora_prog = HORA_INICIO_TARDE
            hora_limite = HORA_LIMITE_TARDE

        if hora_marca <= hora_limite:
            return 0, False, turno
        else:
            dt_prog = datetime.combine(dt_marca.date(), hora_prog)
            minutos = int((dt_marca - dt_prog).total_seconds() // 60)
            return max(0, minutos), True, turno
    except Exception:
        return 0, False, "Desconocido"

def calcular_jornada_y_horas_extras(df_marcas_dia):
    """
    Calcula el tiempo total laborado en el día procesando pares (INGRESO -> SALIDA).
    Compara con la jornada requerida de 5h 45m (345 min).
    Retorna:
      - minutos_laborales: Minutos aplicados a la jornada normal (máx 345 min)
      - minutos_extras: Minutos laborados por encima de los 345 min
      - minutos_totales: Tiempo total trabajado en el día
      - turnos_adicionales: Lista con detalles de marcaciones o coberturas extras
    """
    if df_marcas_dia.empty:
        return 0, 0, 0, []

    df_ord = df_marcas_dia.sort_values("dt").reset_index(drop=True)
    
    segundos_totales = 0
    i = 0
    n = len(df_ord)

    while i < n:
        row_actual = df_ord.iloc[i]
        if row_actual["tipo"] == "INGRESO":
            dt_ingreso = row_actual["dt"]
            if i + 1 < n and df_ord.iloc[i + 1]["tipo"] == "SALIDA":
                dt_salida = df_ord.iloc[i + 1]["dt"]
                segundos_totales += (dt_salida - dt_ingreso).total_seconds()
                i += 2
            else:
                hoy_str = obtener_ahora_peru().strftime("%Y-%m-%d")
                if str(row_actual["fecha"]) == hoy_str:
                    ahora = obtener_ahora_peru().replace(tzinfo=None)
                    if ahora > dt_ingreso:
                        segundos_totales += (ahora - dt_ingreso).total_seconds()
                i += 1
        else:
            i += 1

    minutos_totales = int(segundos_totales // 60)
    
    minutos_laborales = min(minutos_totales, JORNADA_MINUTOS_BASE)
    minutos_extras = max(0, minutos_totales - JORNADA_MINUTOS_BASE)

    df_extras = df_ord[df_ord["es_extra"].astype(str) == "SI"]
    turnos_adicionales = []
    for _, r_ext in df_extras.iterrows():
        obs_clean = r_ext["observacion"].replace("[TURNO EXTRA]", "").strip()
        turnos_adicionales.append({
            "tipo": r_ext["tipo"],
            "hora": r_ext["dt"].strftime("%H:%M:%S"),
            "detalle": obs_clean if obs_clean else "Marcación en turno adicional"
        })

    return minutos_laborales, minutos_extras, minutos_totales, turnos_adicionales

def formatear_horas_minutos(minutos):
    h = minutos // 60
    m = minutos % 60
    return f"{h}h {m}m"

def calcular_metricas_puntualidad(df_asistencia, nombre_colab=None):
    if df_asistencia.empty:
        return {"total_ingresos": 0, "puntuales": 0, "tardanzas": 0, "minutos_acumulados": 0, "ratio": 100.0}

    df_ingresos = df_asistencia[
        (df_asistencia["tipo"] == "INGRESO") & 
        (df_asistencia["es_extra"].astype(str) != "SI")
    ].copy()

    if nombre_colab:
        df_ingresos = df_ingresos[df_ingresos["nombre"] == nombre_colab]

    if df_ingresos.empty:
        return {"total_ingresos": 0, "puntuales": 0, "tardanzas": 0, "minutos_acumulados": 0, "ratio": 100.0}

    total_ingresos = len(df_ingresos)
    tardanzas_cnt = 0
    puntuales_cnt = 0
    minutos_totales = 0

    for _, row in df_ingresos.iterrows():
        mins, es_tardanza, _ = calcular_tardanza_ingreso(row["fecha_hora"])
        if es_tardanza:
            tardanzas_cnt += 1
            minutos_totales += mins
        else:
            puntuales_cnt += 1

    ratio = (puntuales_cnt / total_ingresos * 100) if total_ingresos > 0 else 100.0

    return {
        "total_ingresos": total_ingresos,
        "puntuales": puntuales_cnt,
        "tardanzas": tardanzas_cnt,
        "minutos_acumulados": minutos_totales,
        "ratio": round(ratio, 1)
    }

# --- CONEXIÓN A GOOGLE SHEETS ---
@st.cache_resource
def conectar_google_sheets():
    try:
        if "gcp_service_account" in st.secrets:
            creds_dict = dict(st.secrets["gcp_service_account"])
            if "private_key" in creds_dict:
                pk = creds_dict["private_key"].replace("\\n", "\n")
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
                columnas_req = [
                    "dni", "nombre", "cargo", "estado", "clave", "rol", 
                    "direccion", "telefono", "fecha_nacimiento", "foto",
                    "contacto_emergencia", "numero_emergencia", "link_domicilio",
                    "fecha_inicio", "fecha_cese"
                ]
                for col in columnas_req:
                    if col not in df.columns:
                        df[col] = ""
                return df
        except Exception as e:
            st.error(f"Error al leer Colaboradores: {e}")
            
    return pd.DataFrame(columns=[
        "dni", "nombre", "cargo", "estado", "clave", "rol", 
        "direccion", "telefono", "fecha_nacimiento", "foto",
        "contacto_emergencia", "numero_emergencia", "link_domicilio",
        "fecha_inicio", "fecha_cese"
    ])

def guardar_colaborador_gsheets(dni, nombre, cargo, estado, clave, rol, direccion="", telefono="", fecha_nacimiento="", foto="", contacto_emergencia="", numero_emergencia="", link_domicilio="", fecha_inicio="", fecha_cese=""):
    if doc_sheets:
        try:
            hoja = doc_sheets.worksheet("Colaboradores")
            hoja.append_row([
                str(dni), nombre, cargo, estado, str(clave), rol, 
                direccion, str(telefono), str(fecha_nacimiento), foto,
                contacto_emergencia, str(numero_emergencia), link_domicilio,
                str(fecha_inicio), str(fecha_cese)
            ])
        except Exception as e:
            st.error(f"❌ Error al guardar colaborador en Google Sheets: {e}")

def calcular_edad(fecha_nac):
    if not fecha_nac or str(fecha_nac).strip() in ["", "-", "None"]:
        return "-"
    try:
        f_nac = datetime.strptime(str(fecha_nac).split(" ")[0].strip(), "%Y-%m-%d").date()
        hoy = date.today()
        edad = hoy.year - f_nac.year - ((hoy.month, hoy.day) < (f_nac.month, f_nac.day))
        return f"{edad} años"
    except Exception:
        return "-"

def guardar_asistencia_gsheets(dni, nombre, tipo, fecha_hora, fecha, observacion="", es_extra="NO"):
    if doc_sheets:
        try:
            hoja = doc_sheets.worksheet("Asistencia")
            hoja.append_row([str(dni), nombre, tipo, str(fecha_hora), str(fecha), observacion, es_extra])
        except Exception as e:
            st.error(f"❌ Error al guardar asistencia: {e}")

def guardar_descuadre_gsheets(fecha, dni, nombre, tipo, monto, observacion, fecha_registro):
    if doc_sheets:
        try:
            hoja = doc_sheets.worksheet("Descuadres")
            hoja.append_row([str(fecha), str(dni), nombre, tipo, float(monto), observacion, str(fecha_registro)])
        except Exception as e:
            st.error(f"❌ Error al guardar descuadre: {e}")

def guardar_solicitud_gsheets(id_sol, fecha_reg, dni, nombre, tipo_sol, f_permiso, monto_adel, motivo, estado="Pendiente", respuesta=""):
    if doc_sheets:
        try:
            hoja = doc_sheets.worksheet("Solicitudes")
            hoja.append_row([str(id_sol), str(fecha_reg), str(dni), nombre, tipo_sol, str(f_permiso), float(monto_adel), motivo, estado, respuesta])
        except Exception as e:
            st.error(f"❌ Error al guardar solicitud: {e}")

def actualizar_hoja_completa(nombre_hoja, df):
    if doc_sheets:
        try:
            hoja = doc_sheets.worksheet(nombre_hoja)
            hoja.clear()
            datos = [df.columns.tolist()] + df.astype(str).values.tolist()
            hoja.update(datos)
        except Exception as e:
            st.error(f"❌ Error al actualizar {nombre_hoja}: {e}")

# --- CSS MINIMALISTA Y ESTILOS ---
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

    .cal-card {
        background: #ffffff;
        border: 1px solid #e5e7eb;
        border-radius: 10px;
        padding: 14px;
        margin-bottom: 20px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.02);
    }
    .cal-title {
        font-size: 0.85rem;
        font-weight: 600;
        color: #1f2937;
        margin-bottom: 10px;
        display: flex;
        align-items: center;
        gap: 6px;
    }
    .cal-table {
        width: 100%;
        border-collapse: separate;
        border-spacing: 3px;
        font-size: 0.75rem;
    }
    .cal-table th {
        background-color: #f8fafc;
        color: #64748b;
        font-weight: 600;
        padding: 6px 2px;
        text-align: center;
        border-radius: 4px;
        font-size: 0.7rem;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .cal-table td {
        height: 36px;
        text-align: center;
        vertical-align: middle;
        border-radius: 6px;
        font-weight: 600;
        color: #334155;
        background-color: #ffffff;
        border: 1px solid #f1f5f9;
        transition: all 0.15s ease;
    }
    
    .cal-day-num {
        font-size: 0.82rem;
        line-height: 1;
    }
    .cal-sub {
        font-size: 0.6rem;
        font-weight: 500;
        margin-top: 2px;
        display: block;
        opacity: 0.9;
    }

    .bg-asistio {
        background-color: #dcfce7 !important;
        color: #15803d !important;
        border: 1px solid #bbf7d0 !important;
    }
    .bg-falta {
        background-color: #fee2e2 !important;
        color: #b91c1c !important;
        border: 1px solid #fca5a5 !important;
    }
    .bg-extra {
        background-color: #fef9c3 !important;
        color: #a16207 !important;
        border: 1px solid #fef08a !important;
    }
    .bg-descanso {
        background-color: #f3f4f6 !important;
        color: #6b7280 !important;
        border: 1px solid #e5e7eb !important;
    }
    .bg-inicio {
        background-color: #e0f2fe !important;
        color: #0369a1 !important;
        border: 1px solid #bae6fd !important;
    }
    .bg-cese {
        background-color: #f3e8ff !important;
        color: #6b21a8 !important;
        border: 1px solid #e9d5ff !important;
    }
    .bg-vacio {
        background-color: transparent !important;
        border: none !important;
    }
    .bg-futuro {
        background-color: #ffffff !important;
        color: #94a3b8 !important;
        border: 1px dashed #e2e8f0 !important;
    }

    .legend-container {
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        margin-bottom: 16px;
        background: #ffffff;
        padding: 10px 14px;
        border-radius: 8px;
        border: 1px solid #e5e7eb;
    }
    .legend-item {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 0.78rem;
        font-weight: 500;
        color: #4b5563;
    }
    .legend-badge {
        width: 12px;
        height: 12px;
        border-radius: 3px;
        display: inline-block;
    }

    .profile-name {
        font-weight: 700;
        font-size: 1.05rem;
        color: #111827;
    }
    .profile-role {
        font-size: 0.82rem;
        color: #4B5563;
        margin-bottom: 6px;
    }
    .profile-field {
        font-size: 0.68rem;
        font-weight: 700;
        color: #6B7280;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-top: 6px;
    }
    .profile-val {
        font-size: 0.85rem;
        font-weight: 500;
        color: #111827;
    }
</style>
""", unsafe_allow_html=True)

# --- INICIALIZACIÓN DE SESSION STATE ---
if "usuario_login" not in st.session_state:
    st.session_state.usuario_login = None

if "empleados" not in st.session_state:
    st.session_state.empleados = obtener_colaboradores_gsheets()

for col in ["fecha_inicio", "fecha_cese"]:
    if col not in st.session_state.empleados.columns:
        st.session_state.empleados[col] = ""

if "asistencia" not in st.session_state:
    if doc_sheets:
        try:
            data_asist = doc_sheets.worksheet("Asistencia").get_all_records()
            st.session_state.asistencia = pd.DataFrame(data_asist)
        except Exception:
            st.session_state.asistencia = pd.DataFrame(columns=["dni", "nombre", "tipo", "fecha_hora", "fecha", "observacion", "es_extra"])
    else:
        st.session_state.asistencia = pd.DataFrame(columns=["dni", "nombre", "tipo", "fecha_hora", "fecha", "observacion", "es_extra"])

for col in ["observacion", "es_extra"]:
    if col not in st.session_state.asistencia.columns:
        st.session_state.asistencia[col] = "NO" if col == "es_extra" else ""

if "descuadres" not in st.session_state:
    if doc_sheets:
        try:
            data_desc = doc_sheets.worksheet("Descuadres").get_all_records()
            st.session_state.descuadres = pd.DataFrame(data_desc)
        except Exception:
            st.session_state.descuadres = pd.DataFrame(columns=["fecha", "dni", "nombre", "tipo", "monto", "observacion", "fecha_registro"])
    else:
        st.session_state.descuadres = pd.DataFrame(columns=["fecha", "dni", "nombre", "tipo", "monto", "observacion", "fecha_registro"])

if "solicitudes" not in st.session_state:
    if doc_sheets:
        try:
            data_sol = doc_sheets.worksheet("Solicitudes").get_all_records()
            st.session_state.solicitudes = pd.DataFrame(data_sol)
        except Exception:
            st.session_state.solicitudes = pd.DataFrame(columns=["id_solicitud", "fecha_registro", "dni", "nombre", "tipo_solicitud", "fecha_permiso", "monto_adelanto", "motivo", "estado", "respuesta_admin"])
    else:
        st.session_state.solicitudes = pd.DataFrame(columns=["id_solicitud", "fecha_registro", "dni", "nombre", "tipo_solicitud", "fecha_permiso", "monto_adelanto", "motivo", "estado", "respuesta_admin"])

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
            
            if st.button("Ingresar al Sistema", use_container_width=True):
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

def registrar_marca(dni, nombre, tipo, observacion="", es_extra=False):
    ahora_peru = obtener_ahora_peru()
    hoy_str = ahora_peru.strftime("%Y-%m-%d")
    str_extra = "SI" if es_extra else "NO"

    if not st.session_state.asistencia.empty and not es_extra:
        df_hoy_user = st.session_state.asistencia[
            (st.session_state.asistencia["fecha"].astype(str) == hoy_str) & 
            (st.session_state.asistencia["dni"].astype(str) == str(dni)) &
            (st.session_state.asistencia["es_extra"].astype(str) != "SI")
        ]
        if not df_hoy_user.empty:
            ultima_marca = df_hoy_user.iloc[0]["tipo"]
            if ultima_marca == tipo:
                st.warning(f"⚠️ Ya registraste un **{tipo}** continuo en tu jornada.")
                return False

    fecha_h = ahora_peru.strftime("%Y-%m-%d %H:%M:%S")
    fecha_s = ahora_peru.strftime("%Y-%m-%d")
    
    obs_final = f"[TURNO EXTRA] {observacion}".strip() if es_extra else observacion

    nueva_marca = {
        "dni": str(dni),
        "nombre": nombre,
        "tipo": tipo,
        "fecha_hora": fecha_h,
        "fecha": fecha_s,
        "observacion": obs_final,
        "es_extra": str_extra
    }
    st.session_state.asistencia = pd.concat([pd.DataFrame([nueva_marca]), st.session_state.asistencia], ignore_index=True)
    guardar_asistencia_gsheets(dni, nombre, tipo, fecha_h, fecha_s, obs_final, str_extra)
    return True

def obtener_solo_colaboradores(fecha_eval=None):
    if "rol" in st.session_state.empleados.columns:
        df_colab = st.session_state.empleados[st.session_state.empleados["rol"] != "admin"].copy()
    else:
        df_colab = st.session_state.empleados[st.session_state.empleados["nombre"] != "Administrador"].copy()
    
    if fecha_eval is not None:
        f_eval_str = str(fecha_eval)
        colabs_validos = []
        for _, row in df_colab.iterrows():
            f_cese = str(row.get("fecha_cese", "")).strip()
            if f_cese and f_cese != "-" and f_cese != "None":
                if f_eval_str > f_cese:
                    continue
            colabs_validos.append(row["nombre"])
        return colabs_validos
        
    return df_colab["nombre"].unique().tolist()

def parsear_fecha_segura(f_str):
    if not f_str or str(f_str).strip() in ["", "-", "None"]:
        return None
    try:
        return datetime.strptime(str(f_str).split(" ")[0].strip(), "%Y-%m-%d").date()
    except Exception:
        return None

def renderizar_tarjeta_colaborador(row):
    dni_val = str(row.get("dni", "")).strip()
    nombre_val = str(row.get("nombre", "")).strip()
    cargo_val = str(row.get("cargo", "")).strip()
    rol_val = str(row.get("rol", "")).strip()
    estado_val = str(row.get("estado", "Activo")).strip()
    direccion_val = str(row.get("direccion", "-")).strip() or "-"
    telefono_val = str(row.get("telefono", "-")).strip() or "-"
    f_nac_val = str(row.get("fecha_nacimiento", "")).strip()
    edad_val = calcular_edad(f_nac_val)
    
    c_emergencia = str(row.get("contacto_emergencia", "-")).strip() or "-"
    num_emergencia = str(row.get("numero_emergencia", "-")).strip() or "-"
    link_domicilio = str(row.get("link_domicilio", "")).strip()
    f_inicio_val = str(row.get("fecha_inicio", "")).strip() or "-"
    f_cese_val = str(row.get("fecha_cese", "")).strip() or "-"

    foto_nom = str(row.get("foto", "")).strip()
    if not foto_nom:
        foto_nom = f"{dni_val}.png"
    foto_url = f"fotos/{foto_nom}"

    with st.container(border=True):
        c_img, c_info = st.columns([1, 2])
        
        with c_img:
            try:
                st.image(foto_url, use_container_width=True)
            except Exception:
                st.image("https://via.placeholder.com/150?text=Sin+Foto", use_container_width=True)
        
        with c_info:
            st.markdown(f"<div class='profile-name'>{nombre_val}</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='profile-role'>{cargo_val} • <span style='color:#6B7280;'>{rol_val}</span></div>", unsafe_allow_html=True)
            
            badge_color = "#00A959" if estado_val.lower() == "activo" else "#6B7280"
            texto_estado = "ACTIVO" if estado_val.lower() == "activo" else "DADO DE BAJA"
            st.markdown(f"<span style='background-color:{badge_color}; color:#fff; padding:2px 8px; border-radius:10px; font-size:0.65rem; font-weight:700;'>{texto_estado}</span>", unsafe_allow_html=True)
            st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)

            st.markdown("<div class='profile-field'>DNI / ID:</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='profile-val'>{dni_val}</div>", unsafe_allow_html=True)

            st.markdown("<div class='profile-field'>TELÉFONO DE CONTACTO:</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='profile-val'>{telefono_val}</div>", unsafe_allow_html=True)

            st.markdown("<div class='profile-field'>FECHA NAC. / EDAD:</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='profile-val'>{f_nac_val if f_nac_val else '-'} ({edad_val})</div>", unsafe_allow_html=True)

        st.markdown("---")

        st.markdown("<div class='profile-field'>📅 PERÍODO LABORAL / TIEMPO TRABAJADO:</div>", unsafe_allow_html=True)
        if estado_val.lower() in ["desactivado", "dado de baja"]:
            st.markdown(f"<div class='profile-val' style='color:#EC3237; font-weight:600;'>Se retiró de la empresa el {f_cese_val} (Inicio: {f_inicio_val})</div>", unsafe_allow_html=True)
        else:
            st.markdown(f"<div class='profile-val'>Inicio de labores: {f_inicio_val}</div>", unsafe_allow_html=True)
        st.markdown("<div style='height: 6px;'></div>", unsafe_allow_html=True)
        
        st.markdown("<div class='profile-field'>📍 DIRECCIÓN DE DOMICILIO:</div>", unsafe_allow_html=True)
        if link_domicilio.startswith("http"):
            st.markdown(f"<div class='profile-val'>{direccion_val} — <a href='{link_domicilio}' target='_blank' style='color:#EC3237; text-decoration:none; font-weight:700;'> Ver en Google Maps 🗺️</a></div>", unsafe_allow_html=True)
        else:
            st.markdown(f"<div class='profile-val'>{direccion_val}</div>", unsafe_allow_html=True)

        st.markdown("<div class='profile-field'>🚨 CONTACTO DE EMERGENCIA:</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='profile-val'>{c_emergencia} ({num_emergencia})</div>", unsafe_allow_html=True)

def renderizar_calendario_colaborador(nombre_colab, anio, mes):
    cal = calendar.Calendar(firstweekday=0)
    mes_dias = cal.monthdayscalendar(anio, mes)
    
    df_asist = st.session_state.asistencia.copy()
    if not df_asist.empty:
        df_asist = df_asist[df_asist["nombre"] == nombre_colab]
    
    row_emp = st.session_state.empleados[st.session_state.empleados["nombre"] == nombre_colab]
    f_inicio_lab = None
    f_cese_lab = None
    if not row_emp.empty:
        f_inicio_lab = parsear_fecha_segura(row_emp.iloc[0].get("fecha_inicio", ""))
        f_cese_lab = parsear_fecha_segura(row_emp.iloc[0].get("fecha_cese", ""))

    hoy = obtener_ahora_peru().date()

    html = f"""
    <div class='cal-card'>
        <div class='cal-title'>
            <span>👤</span> <span>{nombre_colab}</span>
        </div>
        <table class='cal-table'>
            <thead>
                <tr>
                    <th>Lun</th>
                    <th>Mar</th>
                    <th>Mié</th>
                    <th>Jue</th>
                    <th>Vie</th>
                    <th>Sáb</th>
                    <th>Dom</th>
                </tr>
            </thead>
            <tbody>
    """

    for semana in mes_dias:
        html += "<tr>"
        for i, d in enumerate(semana):
            if d == 0:
                html += "<td class='bg-vacio'></td>"
            else:
                fecha_dia = date(anio, mes, d)
                f_str = fecha_dia.strftime("%Y-%m-%d")
                
                if i == 6:
                    html += f"<td class='bg-descanso'><span class='cal-day-num'>{d}</span><span class='cal-sub'>Descanso</span></td>"
                else:
                    if not df_asist.empty:
                        df_dia = df_asist[df_asist["fecha"].astype(str) == f_str]
                    else:
                        df_dia = pd.DataFrame()

                    if not df_dia.empty:
                        tiene_extra = (df_dia["es_extra"].astype(str) == "SI").any() or df_dia["observacion"].str.contains("TURNO EXTRA").any()
                        if tiene_extra:
                            html += f"<td class='bg-extra'><span class='cal-day-num'>{d}</span><span class='cal-sub'>★ Extra</span></td>"
                        else:
                            sub_txt = "1er Día" if (f_inicio_lab and fecha_dia == f_inicio_lab) else "✓ Asistió"
                            html += f"<td class='bg-asistio'><span class='cal-day-num'>{d}</span><span class='cal-sub'>{sub_txt}</span></td>"
                    else:
                        if f_inicio_lab and fecha_dia < f_inicio_lab:
                            html += f"<td class='bg-futuro'><span class='cal-day-num'>{d}</span></td>"
                        elif f_cese_lab and fecha_dia == f_cese_lab:
                            html += f"<td class='bg-cese'><span class='cal-day-num'>{d}</span><span class='cal-sub'>Cese</span></td>"
                        elif f_cese_lab and fecha_dia > f_cese_lab:
                            html += f"<td class='bg-futuro'><span class='cal-day-num'>{d}</span></td>"
                        elif fecha_dia == f_inicio_lab:
                            html += f"<td class='bg-inicio'><span class='cal-day-num'>{d}</span><span class='cal-sub'>1er Día</span></td>"
                        elif fecha_dia < hoy:
                            html += f"<td class='bg-falta'><span class='cal-day-num'>{d}</span><span class='cal-sub'>✕ Falta</span></td>"
                        else:
                            html += f"<td class='bg-futuro'><span class='cal-day-num'>{d}</span></td>"
        html += "</tr>"
    html += "</tbody></table></div>"
    return html

# --- SIDEBAR ---
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
    menu = ["Dashboard General", "Gestión Colaboradores", "Solicitudes y Permisos", "Historial de Descuadres", "Historial de Asistencias"]
else:
    menu = ["Marcar Asistencia", "Registrar Descuadre", "Mi Ficha Técnica", "Solicitar Permiso / Adelanto", "Mi Dashboard Mensual"]

choice = st.sidebar.radio("Navegación", menu)

st.sidebar.markdown("<br><br>", unsafe_allow_html=True)
st.sidebar.markdown('<div class="btn-logout">', unsafe_allow_html=True)
if st.sidebar.button("Cerrar Sesión", use_container_width=True):
    st.session_state.usuario_login = None
    st.rerun()
st.sidebar.markdown('</div>', unsafe_allow_html=True)

# -------------------- MÓDULOS OPERATIVOS --------------------

if choice == "Marcar Asistencia":
    st.markdown(f"""
        <div class="market-header">
            <h1>Terminal de Asistencia</h1>
            <p>Colaborador activo: <b>{user_actual}</b> | Jornada laboral requerida: <b>5h 45m</b></p>
        </div>
    """, unsafe_allow_html=True)

    col_main, col_preview = st.columns([1.1, 1])

    with col_main:
        with st.container(border=True):
            st.markdown("<h4 style='margin:0; font-size:1rem; color:#111827;'>Registro de Turno</h4>", unsafe_allow_html=True)
            st.caption("Selecciona el tipo de marcación que deseas realizar:")
            
            es_turno_extra = st.checkbox("⏰ Marcación Fuera de Horario / Turno Adicional")
            
            motivo_extra = ""
            if es_turno_extra:
                motivo_extra = st.selectbox(
                    "Motivo del Turno Adicional",
                    ["Cubrir Turno Mañana (Apoyo)", "Cubrir Turno Tarde (Apoyo)", "Permanencia Extra / Post-Turno", "Otro Sustento"]
                )
            
            obs_marca = st.text_input("Observación / Justificación (Opcional)", placeholder="Ej. Reemplazo por renuncia, apoyo en caja, etc.")
            
            if es_turno_extra and motivo_extra:
                obs_marca = f"[{motivo_extra}] {obs_marca}".strip()

            st.markdown("<br>", unsafe_allow_html=True)

            c1, c2 = st.columns(2)
            with c1:
                st.markdown('<div class="btn-ingreso">', unsafe_allow_html=True)
                if st.button("Marcar Ingreso", use_container_width=True):
                    if registrar_marca(dni_actual, user_actual, "INGRESO", obs_marca, es_turno_extra):
                        st.toast("Ingreso registrado correctamente")
                        time.sleep(0.3)
                        st.rerun()
                st.markdown('</div>', unsafe_allow_html=True)

            with c2:
                st.markdown('<div class="btn-salida">', unsafe_allow_html=True)
                if st.button("Marcar Salida", use_container_width=True):
                    if registrar_marca(dni_actual, user_actual, "SALIDA", obs_marca, es_turno_extra):
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
            ].copy()

            if not df_mismarcas.empty:
                st.dataframe(
                    df_mismarcas[["tipo", "fecha_hora", "observacion", "es_extra"]],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "tipo": "TIPO", 
                        "fecha_hora": "FECHA / HORA",
                        "observacion": "OBSERVACIÓN",
                        "es_extra": "EXTRA"
                    }
                )
                
                df_mismarcas["dt"] = pd.to_datetime(df_mismarcas["fecha_hora"])
                mins_lab, mins_ext, mins_tot, _ = calcular_jornada_y_horas_extras(df_mismarcas)
                
                st.markdown("---")
                st.markdown(f"**⏱️ Horas Trabajadas Hoy:** {formatear_horas_minutos(mins_tot)}")
                st.markdown(f"**📌 Jornada Completa (5h 45m):** {formatear_horas_minutos(mins_lab)} / 5h 45m")
                if mins_ext > 0:
                    st.markdown(f"**⭐ Horas Extras Generadas:** <span style='color:#00A959; font-weight:700;'>{formatear_horas_minutos(mins_ext)}</span>", unsafe_allow_html=True)
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

        if st.form_submit_button("Guardar Registro", use_container_width=True):
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
            time.sleep(0.3)
            st.rerun()

elif choice == "Mi Ficha Técnica":
    st.markdown(f"""
        <div class="market-header">
            <h1>Mi Ficha Técnica</h1>
            <p>Información laboral y de contacto registrada para <b>{user_actual}</b></p>
        </div>
    """, unsafe_allow_html=True)

    mi_row = st.session_state.empleados[st.session_state.empleados["dni"].astype(str) == str(dni_actual)]
    if not mi_row.empty:
        renderizar_tarjeta_colaborador(mi_row.iloc[0])
    else:
        st.error("No se encontró tu información en la base de datos de colaboradores.")

elif choice == "Solicitar Permiso / Adelanto":
    st.markdown(f"""
        <div class="market-header">
            <h1>Solicitudes de Permiso y Adelantos</h1>
            <p>Gestión de permisos laborales y adelantos de sueldo para <b>{user_actual}</b></p>
        </div>
    """, unsafe_allow_html=True)

    t_sol, t_hist = st.tabs(["📝 Nueva Solicitud", "📋 Mi Historial de Solicitudes"])

    with t_sol:
        tipo_sol = st.selectbox("Tipo de Solicitud", ["Permiso Laboral", "Adelanto de Sueldo"])

        with st.form("form_nueva_solicitud", clear_on_submit=True):
            st.markdown("<h4 style='margin:0; font-size:1rem; color:#111827; margin-bottom:12px;'>Formulario de Petición</h4>", unsafe_allow_html=True)
            
            hoy_peru = obtener_ahora_peru().date()
            fecha_minima_permiso = hoy_peru + timedelta(days=7)
            
            f_permiso_val = ""
            monto_adel_val = 0.0

            if tipo_sol == "Permiso Laboral":
                st.info("ℹ️ **Regla de Permisos:** Toda solicitud de permiso debe realizarse con un mínimo de **7 días de anticipación**.")
                f_permiso_sel = st.date_input(
                    "Fecha solicitada para el permiso", 
                    value=fecha_minima_permiso, 
                    min_value=fecha_minima_permiso
                )
                f_permiso_val = str(f_permiso_sel)
            else:
                st.info("ℹ️ **Adelanto de Sueldo:** Ingresa el monto total a solicitar y la justificación.")
                monto_adel_val = st.number_input("Monto a Solicitar (S/.)", min_value=10.0, step=10.0, format="%.2f")
                f_permiso_val = str(hoy_peru)

            motivo_sol = st.text_area("Motivo o Justificación detallada", placeholder="Escribe aquí el motivo de tu solicitud...")

            if st.form_submit_button("Enviar Solicitud", use_container_width=True):
                if not motivo_sol.strip():
                    st.error("Por favor ingresa un motivo para tu solicitud.")
                else:
                    if tipo_sol == "Permiso Laboral":
                        diff_dias = (f_permiso_sel - hoy_peru).days
                        if diff_dias < 7:
                            st.error("❌ Los permisos requieren como mínimo 7 días de anticipación.")
                            st.stop()

                    id_nuevo = f"SOL-{int(time.time())}"
                    f_reg_now = obtener_ahora_peru().strftime("%Y-%m-%d %H:%M:%S")

                    nueva_peticion = {
                        "id_solicitud": id_nuevo,
                        "fecha_registro": f_reg_now,
                        "dni": str(dni_actual),
                        "nombre": user_actual,
                        "tipo_solicitud": tipo_sol,
                        "fecha_permiso": f_permiso_val,
                        "monto_adelanto": monto_adel_val,
                        "motivo": motivo_sol.strip(),
                        "estado": "Pendiente",
                        "respuesta_admin": ""
                    }

                    st.session_state.solicitudes = pd.concat([pd.DataFrame([nueva_peticion]), st.session_state.solicitudes], ignore_index=True)
                    guardar_solicitud_gsheets(id_nuevo, f_reg_now, dni_actual, user_actual, tipo_sol, f_permiso_val, monto_adel_val, motivo_sol.strip())
                    st.success("✅ Solicitud enviada con éxito. Un administrador la revisará pronto.")
                    time.sleep(0.5)
                    st.rerun()

    with t_hist:
        st.markdown("<h4 style='font-size:1rem; color:#111827; margin-bottom:12px;'>Historial de Solicitudes</h4>", unsafe_allow_html=True)
        
        df_mis_sol = st.session_state.solicitudes[st.session_state.solicitudes["dni"].astype(str) == str(dni_actual)].copy() if not st.session_state.solicitudes.empty else pd.DataFrame()

        if not df_mis_sol.empty:
            for _, r_sol in df_mis_sol.iterrows():
                est = r_sol["estado"]
                badge_c = "#EAB308" if est == "Pendiente" else ("#00A959" if est == "Aprobado" else "#EC3237")
                
                det_txt = f"**Fecha Permiso:** {r_sol['fecha_permiso']}" if r_sol['tipo_solicitud'] == "Permiso Laboral" else f"**Monto Solicitado:** S/. {float(r_sol['monto_adelanto']):.2f}"
                
                with st.expander(f"📌 {r_sol['tipo_solicitud']} — {r_sol['fecha_registro']} [{est}]"):
                    st.markdown(f"<span style='background-color:{badge_c}; color:#fff; padding:3px 10px; border-radius:12px; font-size:0.75rem; font-weight:700;'>{est}</span>", unsafe_allow_html=True)
                    st.markdown(f"<br>{det_txt}", unsafe_allow_html=True)
                    st.markdown(f"**Motivo:** {r_sol['motivo']}")
                    if str(r_sol.get('respuesta_admin', '')).strip():
                        st.markdown(f"**Respuesta Admin:** {r_sol['respuesta_admin']}")
        else:
            st.info("No registras solicitudes en tu historial.")

elif choice == "Mi Dashboard Mensual":
    st.markdown(f"""
        <div class="market-header">
            <h1>Rendimiento Mensual</h1>
            <p>Resumen acumulado para <b>{user_actual}</b></p>
        </div>
    """, unsafe_allow_html=True)

    df_mis_desc = pd.DataFrame()
    df_mis_asist = pd.DataFrame()

    if not st.session_state.descuadres.empty:
        df_mis_desc = st.session_state.descuadres[st.session_state.descuadres["dni"].astype(str) == str(dni_actual)]
    
    if not st.session_state.asistencia.empty:
        df_mis_asist = st.session_state.asistencia[st.session_state.asistencia["dni"].astype(str) == str(dni_actual)].copy()

    monto_total = pd.to_numeric(df_mis_desc["monto"]).sum() if not df_mis_desc.empty else 0.0
    dias_trabajados = df_mis_asist["fecha"].nunique() if not df_mis_asist.empty else 0

    minutos_extras_mes = 0
    if not df_mis_asist.empty:
        df_mis_asist["dt"] = pd.to_datetime(df_mis_asist["fecha_hora"])
        for _, grupo_dia in df_mis_asist.groupby("fecha"):
            _, mins_e, _, _ = calcular_jornada_y_horas_extras(grupo_dia)
            minutos_extras_mes += mins_e

    metricas_p = calcular_metricas_puntualidad(st.session_state.asistencia, user_actual)

    k1, k2, k3, k4 = st.columns(4)
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
                <div class="info-label">Horas Extras Acumuladas</div>
                <div class="info-value" style="color: #00A959;">{formatear_horas_minutos(minutos_extras_mes)}</div>
            </div>
        ''', unsafe_allow_html=True)

    with k3:
        st.markdown(f'''
            <div class="info-card">
                <div class="info-label">Minutos Tardanza</div>
                <div class="info-value" style="color: {'#111827' if metricas_p['minutos_acumulados'] == 0 else '#EC3237'};">{metricas_p['minutos_acumulados']} m</div>
            </div>
        ''', unsafe_allow_html=True)

    with k4:
        st.markdown(f'''
            <div class="info-card">
                <div class="info-label">Balance Descuadres</div>
                <div class="info-value" style="color: {'#00A959' if monto_total >= 0 else '#EC3237'};">S/. {monto_total:.2f}</div>
            </div>
        ''', unsafe_allow_html=True)

    st.markdown("<h4 style='font-size:1rem; color:#111827; margin-top:10px;'>Historial Personal</h4>", unsafe_allow_html=True)
    if not df_mis_desc.empty:
        st.dataframe(
            df_mis_desc[["fecha", "tipo", "monto", "observacion"]],
            use_container_width=True,
            hide_index=True,
            column_config={"monto": st.column_config.NumberColumn("MONTO", format="S/. %.2f")}
        )
    else:
        st.info("Sin registros de descuadres en el período.")

# -------------------- MÓDULOS ADMIN --------------------

elif choice == "Dashboard General":
    st.markdown("""
        <div class="market-header">
            <h1>Panel de Control General</h1>
            <p>Vista ejecutiva de la operación, tardanzas y horas extras en tiempo real</p>
        </div>
    """, unsafe_allow_html=True)

    st.markdown("##### 📅 Calendarios Mensuales de Asistencia (Rol Operativo)")
    col_mes, col_anio = st.columns(2)
    
    ahora_p = obtener_ahora_peru()
    mes_sel = col_mes.selectbox("Mes", list(range(1, 13)), index=ahora_p.month - 1)
    anio_sel = col_anio.number_input("Año", min_value=2024, max_value=2030, value=ahora_p.year)

    st.markdown("""
        <div class="legend-container">
            <div class="legend-item">
                <span class="legend-badge" style="background-color: #dcfce7; border: 1px solid #bbf7d0;"></span>
                <span>Asistió</span>
            </div>
            <div class="legend-item">
                <span class="legend-badge" style="background-color: #fee2e2; border: 1px solid #fca5a5;"></span>
                <span>Inasistencia (Falta)</span>
            </div>
            <div class="legend-item">
                <span class="legend-badge" style="background-color: #fef9c3; border: 1px solid #fef08a;"></span>
                <span>Turno Adicional</span>
            </div>
            <div class="legend-item">
                <span class="legend-badge" style="background-color: #f3f4f6; border: 1px solid #e5e7eb;"></span>
                <span>Descanso Programado</span>
            </div>
            <div class="legend-item">
                <span class="legend-badge" style="background-color: #e0f2fe; border: 1px solid #bae6fd;"></span>
                <span>Primer Día</span>
            </div>
            <div class="legend-item">
                <span class="legend-badge" style="background-color: #f3e8ff; border: 1px solid #e9d5ff;"></span>
                <span>Cese / Baja</span>
            </div>
        </div>
    """, unsafe_allow_html=True)

    st.markdown("##### 🔍 Filtros de Consulta")
    col_f1, col_f2 = st.columns([1.5, 1])
    
    with col_f1:
        fecha_dash = st.date_input("Fecha de Consulta", obtener_ahora_peru(), key="dash_fecha")
    
    f_dash_str = str(fecha_dash)
    colaboradores_ops = obtener_solo_colaboradores(fecha_eval=fecha_dash)

    with col_f2:
        lista_colabs = ["Todos"] + colaboradores_ops
        colab_dash = st.selectbox("Filtrar Colaborador", lista_colabs, key="dash_colab")

    if colaboradores_ops:
        colabs_a_renderizar = colaboradores_ops if colab_dash == "Todos" else [colab_dash]
        with st.expander("👁️ Ver Calendarios de Asistencia por Trabajador", expanded=True):
            cols_cal = st.columns(2)
            for idx, c_nom in enumerate(colabs_a_renderizar):
                with cols_cal[idx % 2]:
                    html_cal = renderizar_calendario_colaborador(c_nom, int(anio_sel), int(mes_sel))
                    st.markdown(html_cal, unsafe_allow_html=True)
    else:
        st.info("No hay colaboradores con rol operativo activos para la fecha consultada.")

    st.markdown("---")

    df_asist_dash = st.session_state.asistencia.copy()
    df_desc_dash = st.session_state.descuadres.copy()
    
    fichas_colaboradores = {}
    en_turno_cnt = 0
    concluido_cnt = 0
    total_minutos_extras_dia = 0

    if not df_asist_dash.empty:
        df_asist_dash = df_asist_dash[df_asist_dash["fecha"].astype(str) == f_dash_str]
        
        if colab_dash != "Todos":
            df_asist_dash = df_asist_dash[df_asist_dash["nombre"] == colab_dash]

        if not df_asist_dash.empty:
            df_asist_dash["dt"] = pd.to_datetime(df_asist_dash["fecha_hora"])
            
            for nombre_colab, grupo in df_asist_dash.groupby("nombre"):
                if nombre_colab not in colaboradores_ops:
                    continue

                grupo_ordenado = grupo.sort_values("dt")
                
                ingresos = grupo_ordenado[grupo_ordenado["tipo"] == "INGRESO"]
                salidas = grupo_ordenado[grupo_ordenado["tipo"] == "SALIDA"]
                
                hora_primer_ingreso = ingresos.iloc[0]["dt"].strftime("%H:%M:%S") if not ingresos.empty else "--:--:--"
                hora_ultima_salida = salidas.iloc[-1]["dt"].strftime("%H:%M:%S") if not salidas.empty else "--:--:--"
                ultima_marca = grupo_ordenado.iloc[-1]
                
                tardanza_txt = "Puntual"
                if not ingresos.empty:
                    ing_regulares = ingresos[ingresos["es_extra"].astype(str) != "SI"]
                    ing_eval = ing_regulares.iloc[0] if not ing_regulares.empty else ingresos.iloc[0]
                    mins_t, es_t, turno_p = calcular_tardanza_ingreso(ing_eval["fecha_hora"])
                    if es_t:
                        tardanza_txt = f"⚠️ Tardanza ({mins_t} min)"

                if ultima_marca["tipo"] == "INGRESO":
                    estado = "🟢 En Turno"
                    en_turno_cnt += 1
                else:
                    estado = "⚪ Concluido"
                    concluido_cnt += 1

                mins_lab, mins_ext, mins_tot, turnos_adicionales = calcular_jornada_y_horas_extras(grupo_ordenado)
                total_minutos_extras_dia += mins_ext

                obs_asistencia = [
                    f"[{r['tipo']} {r['dt'].strftime('%H:%M')}] {r['observacion']}" 
                    for _, r in grupo_ordenado.iterrows() 
                    if str(r.get('observacion', '')).strip() != ""
                ]

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
                    "primer_ingreso": hora_primer_ingreso,
                    "ultima_salida": hora_ultima_salida,
                    "tiempo_total_str": formatear_horas_minutos(mins_tot),
                    "horas_laborales_str": f"{formatear_horas_minutos(mins_lab)} / 5h 45m",
                    "horas_extras_str": formatear_horas_minutos(mins_ext),
                    "minutos_extras": mins_ext,
                    "tardanza": tardanza_txt,
                    "turnos_adicionales": turnos_adicionales,
                    "balance_descuadre": monto_desc_user,
                    "descuadres_detalle": descuadres_user,
                    "obs_asistencia": obs_asistencia
                }

    total_descuadre_monto = 0.0
    if not df_desc_dash.empty:
        df_desc_dash = df_desc_dash[df_desc_dash["fecha"].astype(str) == f_dash_str]
        if colab_dash != "Todos":
            df_desc_dash = df_desc_dash[df_desc_dash["nombre"] == colab_dash]
        else:
            df_desc_dash = df_desc_dash[df_desc_dash["nombre"].isin(colaboradores_ops)]
        total_descuadre_monto = pd.to_numeric(df_desc_dash["monto"], errors="coerce").sum() if not df_desc_dash.empty else 0.0

    st.markdown("<br>", unsafe_allow_html=True)
    k1, k2, k3, k4, k5 = st.columns(5)
    metricas_gen = calcular_metricas_puntualidad(st.session_state.asistencia)
    
    with k1:
        st.markdown(f'<div class="info-card"><div class="info-label">En Turno Ahora</div><div class="info-value" style="color: #00A959;">{en_turno_cnt}</div></div>', unsafe_allow_html=True)
    with k2:
        st.markdown(f'<div class="info-card"><div class="info-label">Turno Concluido</div><div class="info-value" style="color: #6B7280;">{concluido_cnt}</div></div>', unsafe_allow_html=True)
    with k3:
        st.markdown(f'<div class="info-card"><div class="info-label">Horas Extras Hoy</div><div class="info-value" style="color: #00A959;">{formatear_horas_minutos(total_minutos_extras_dia)}</div></div>', unsafe_allow_html=True)
    with k4:
        st.markdown(f'<div class="info-card"><div class="info-label">Puntualidad Global</div><div class="info-value" style="color: {"#00A959" if metricas_gen["ratio"] >= 90 else "#EC3237"};">{metricas_gen["ratio"]}%</div></div>', unsafe_allow_html=True)
    with k5:
        st.markdown(f'<div class="info-card"><div class="info-label">Balance Descuadres</div><div class="info-value" style="color: {"#00A959" if total_descuadre_monto >= 0 else "#EC3237"};">S/. {total_descuadre_monto:.2f}</div></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    if fichas_colaboradores:
        st.markdown("<h4 style='font-size:1rem; color:#111827; margin-bottom:15px;'>📄 Control Operativo y Horas Extras por Colaborador</h4>", unsafe_allow_html=True)

        for nombre_col, datos in fichas_colaboradores.items():
            with st.expander(f"👤 {nombre_col} — {datos['estado']} | Total Trab.: {datos['tiempo_total_str']} | Extras: {datos['horas_extras_str']}", expanded=True):
                fc1, fc2, fc3, fc4, fc5 = st.columns(5)
                
                with fc1:
                    st.caption("🕒 1ER INGRESO")
                    st.markdown(f"**{datos['primer_ingreso']}**")
                
                with fc2:
                    st.caption("🛑 ÚLTIMA SALIDA")
                    st.markdown(f"**{datos['ultima_salida']}**")
                
                with fc3:
                    st.caption("⏱️ JORNADA BASE")
                    st.markdown(f"**{datos['horas_laborales_str']}**")

                with fc4:
                    st.caption("⭐ HORAS EXTRAS")
                    color_ext = "#00A959" if datos["minutos_extras"] > 0 else "#111827"
                    st.markdown(f"<span style='color:{color_ext}; font-weight:700;'>{datos['horas_extras_str']}</span>", unsafe_allow_html=True)

                with fc5:
                    st.caption("⏰ PUNTUALIDAD")
                    color_tard = "#00A959" if "Puntual" in datos["tardanza"] else "#EC3237"
                    st.markdown(f"<span style='color:{color_tard}; font-weight:700;'>{datos['tardanza']}</span>", unsafe_allow_html=True)

                st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
                
                if datos["turnos_adicionales"]:
                    st.markdown("**:alarm_clock: Turnos Adicionales / Coberturas Marcadas:**")
                    for t_add in datos["turnos_adicionales"]:
                        st.markdown(f"- **[{t_add['tipo']} - {t_add['hora']}]:** {t_add['detalle']}")
                else:
                    st.markdown("**:alarm_clock: Turnos Adicionales:** No registró marcaciones fuera de horario hoy.")

                if datos["descuadres_detalle"]:
                    st.markdown("**:bar_chart: Detalle de Caja / Descuadre:**")
                    for d_item in datos["descuadres_detalle"]:
                        m_val = float(d_item['monto'])
                        signo_color = "green" if m_val >= 0 else "red"
                        obs_txt = f" — *Sustento:* {d_item['obs']}" if d_item['obs'] else ""
                        st.markdown(f"- **{d_item['tipo']}:** :{signo_color}[S/. {m_val:.2f}]{obs_txt}")
                else:
                    st.markdown("**:bar_chart: Detalle de Caja:** Sin descuadres registrados en la fecha.")

                if datos["obs_asistencia"]:
                    st.markdown("**:speech_balloon: Observaciones de Marcación:**")
                    for obs_item in datos["obs_asistencia"]:
                        st.markdown(f"- {obs_item}")

    else:
        st.info(f"No hay registros de marcación para la fecha {f_dash_str}.")

elif choice == "Gestión Colaboradores":
    st.markdown("""
        <div class="market-header">
            <h1>Gestión de Colaboradores</h1>
            <p>Mantenimiento de personal, registros y Fichas Técnicas</p>
        </div>
    """, unsafe_allow_html=True)

    tab_fichas, tab_nuevo, tab_directorio = st.tabs(["📇 Fichas Técnicas", "➕ Registrar Colaborador", "📋 Directorio General"])

    with tab_fichas:
        st.markdown("<h4 style='font-size:1rem; color:#111827; margin-bottom:15px;'>Tarjetas de Identificación del Personal</h4>", unsafe_allow_html=True)
        
        colabs_df = st.session_state.empleados.copy()
        
        if colabs_df.empty:
            st.info("No existen colaboradores registrados.")
        else:
            colabs_df["orden_estado"] = colabs_df["estado"].astype(str).str.lower().apply(lambda x: 0 if x == "activo" else 1)
            colabs_df = colabs_df.sort_values(by="orden_estado").reset_index(drop=True)

            grid_cols = st.columns(2)
            for i, row in colabs_df.iterrows():
                col_idx = i % 2
                with grid_cols[col_idx]:
                    renderizar_tarjeta_colaborador(row)

    with tab_nuevo:
        with st.form("form_emp_completo", clear_on_submit=True):
            st.markdown("<h4 style='margin:0; font-size:0.95rem; color:#111827; margin-bottom:12px;'>Datos Personales del Trabajador</h4>", unsafe_allow_html=True)
            
            f1, f2 = st.columns(2)
            dni_in = f1.text_input("DNI / Identificación")
            nom_in = f2.text_input("Nombre y Apellidos Completos")

            f3, f4 = st.columns(2)
            cargo_in = f3.selectbox("Cargo", ["Cajero", "Supervisora", "Reposidor", "Gerente de Tienda"])
            rol_in = f4.selectbox("Rol de Sistema", ["operativo", "admin"])

            f5, f6 = st.columns(2)
            dir_in = f5.text_input("Dirección de Domicilio")
            tel_in = f6.text_input("Número de Contacto / Teléfono")

            f7, f8 = st.columns(2)
            fnac_in = f7.date_input("Fecha de Nacimiento", value=date(1995, 1, 1))
            clave_in = f8.text_input("Contraseña de Acceso", type="password")

            finicio_in = st.date_input("Fecha de Inicio de Labores", value=obtener_ahora_peru().date())

            st.markdown("<h4 style='margin:12px 0 0 0; font-size:0.95rem; color:#111827;'>Información de Emergencia y Ubicación</h4>", unsafe_allow_html=True)
            
            e1, e2 = st.columns(2)
            c_emerg_in = e1.text_input("Contacto de Emergencia (Nombre / Parentesco)", placeholder="Ej. Maria Insapillo (Madre)")
            num_emerg_in = e2.text_input("Teléfono de Emergencia", placeholder="Ej. 987654321")

            link_maps_in = st.text_input("Enlace Ubicación Domicilio (Google Maps Link)", placeholder="https://maps.app.goo.gl/...")

            st.caption("📌 Nota: La imagen debe guardarse en la carpeta `fotos/` del repositorio como: `<DNI>.png` o `<DNI>.jpg`")

            if st.form_submit_button("Guardar Registro", use_container_width=True):
                if not dni_in or not nom_in or not clave_in:
                    st.error("DNI, Nombre y Contraseña son obligatorios.")
                else:
                    foto_nombre = f"{str(dni_in).strip()}.png"
                    fnac_str = str(fnac_in)
                    finicio_str = str(finicio_in)
                    
                    nuevo_e = {
                        "dni": str(dni_in).strip(),
                        "nombre": nom_in.strip(),
                        "cargo": cargo_in,
                        "estado": "Activo",
                        "clave": str(clave_in).strip(),
                        "rol": rol_in,
                        "direccion": dir_in.strip(),
                        "telefono": str(tel_in).strip(),
                        "fecha_nacimiento": fnac_str,
                        "foto": foto_nombre,
                        "contacto_emergencia": c_emerg_in.strip(),
                        "numero_emergencia": str(num_emerg_in).strip(),
                        "link_domicilio": link_maps_in.strip(),
                        "fecha_inicio": finicio_str,
                        "fecha_cese": ""
                    }
                    st.session_state.empleados = pd.concat([st.session_state.empleados, pd.DataFrame([nuevo_e])], ignore_index=True)
                    guardar_colaborador_gsheets(
                        dni_in, nom_in, cargo_in, "Activo", clave_in, rol_in, 
                        dir_in, tel_in, fnac_str, foto_nombre,
                        c_emerg_in.strip(), num_emerg_in.strip(), link_maps_in.strip(),
                        finicio_str, ""
                    )
                    st.toast("Colaborador y Ficha Técnica registrados")
                    time.sleep(0.3)
                    st.rerun()

    with tab_directorio:
        st.markdown("<h4 style='margin:0; font-size:0.95rem; color:#111827; margin-bottom:12px;'>Directorio Consolidado</h4>", unsafe_allow_html=True)
        cols_mostrar = [
            c for c in ["dni", "nombre", "cargo", "rol", "telefono", "direccion", "fecha_nacimiento", "contacto_emergencia", "numero_emergencia", "estado", "fecha_inicio", "fecha_cese"] 
            if c in st.session_state.empleados.columns
        ]
        st.dataframe(
            st.session_state.empleados[cols_mostrar],
            use_container_width=True,
            hide_index=True
        )

        if rol_actual == "admin" and not st.session_state.empleados.empty:
            st.markdown("<br>", unsafe_allow_html=True)
            with st.expander("Desactivar / Dar de Baja a Colaborador"):
                colabs_activos = st.session_state.empleados[st.session_state.empleados["estado"].astype(str).str.lower() == "activo"]["nombre"].tolist()
                
                if colabs_activos:
                    colab_a_desactivar = st.selectbox("Seleccionar colaborador a dar de baja", colabs_activos)
                    f_cese_input = st.date_input("Fecha de Salida / Cese", value=obtener_ahora_peru().date())
                    confirm_desactivar = st.checkbox(f"Confirmar baja del colaborador {colab_a_desactivar}")
                    
                    if st.button("Dar de Baja al Colaborador", type="primary", use_container_width=True):
                        if confirm_desactivar:
                            idx = st.session_state.empleados[st.session_state.empleados["nombre"] == colab_a_desactivar].index
                            if not idx.empty:
                                st.session_state.empleados.loc[idx, "estado"] = "Desactivado"
                                st.session_state.empleados.loc[idx, "fecha_cese"] = str(f_cese_input)
                                actualizar_hoja_completa("Colaboradores", st.session_state.empleados)
                                st.toast(f"Colaborador {colab_a_desactivar} desactivado correctamente")
                                time.sleep(0.3)
                                st.rerun()
                        else:
                            st.warning("Marca la casilla de confirmación antes de dar de baja.")
                else:
                    st.info("No hay colaboradores activos para dar de baja.")

elif choice == "Solicitudes y Permisos":
    st.markdown("""
        <div class="market-header">
            <h1>Gestión de Solicitudes y Permisos</h1>
            <p>Bandeja de aprobación para administración</p>
        </div>
    """, unsafe_allow_html=True)

    if not st.session_state.solicitudes.empty:
        df_sol = st.session_state.solicitudes.copy()
        
        estado_filtro = st.selectbox("Filtrar por Estado", ["Todos", "Pendiente", "Aprobado", "Rechazado"])
        if estado_filtro != "Todos":
            df_sol = df_sol[df_sol["estado"] == estado_filtro]

        st.markdown("<br>", unsafe_allow_html=True)

        for idx, row_sol in df_sol.iterrows():
            id_s = row_sol["id_solicitud"]
            nom_s = row_sol["nombre"]
            tipo_s = row_sol["tipo_solicitud"]
            est_s = row_sol["estado"]
            
            color_st = "#EAB308" if est_s == "Pendiente" else ("#00A959" if est_s == "Aprobado" else "#EC3237")
            
            with st.expander(f"📥 {tipo_s} - {nom_s} ({row_sol['fecha_registro']}) [{est_s}]"):
                c_sol1, c_sol2 = st.columns([2, 1])
                
                with c_sol1:
                    st.markdown(f"**Trabajador:** {nom_s} (DNI: {row_sol['dni']})")
                    st.markdown(f"**Tipo de Solicitud:** {tipo_s}")
                    if tipo_s == "Permiso Laboral":
                        st.markdown(f"**Fecha Solicitada:** {row_sol['fecha_permiso']}")
                    else:
                        st.markdown(f"**Monto Solicitado:** S/. {float(row_sol['monto_adelanto']):.2f}")
                    st.markdown(f"**Motivo:** {row_sol['motivo']}")
                    st.markdown(f"**Estado Actual:** <span style='color:{color_st}; font-weight:700;'>{est_s}</span>", unsafe_allow_html=True)

                with c_sol2:
                    if est_s == "Pendiente":
                        st.markdown("**:gear: Acciones:**")
                        resp_admin_input = st.text_input(f"Observación Admin", key=f"resp_{id_s}")
                        
                        btn_col1, btn_col2 = st.columns(2)
                        if btn_col1.button("Aprobar", key=f"ap_{id_s}", use_container_width=True):
                            idx_real = st.session_state.solicitudes[st.session_state.solicitudes["id_solicitud"] == id_s].index
                            st.session_state.solicitudes.loc[idx_real, "estado"] = "Aprobado"
                            st.session_state.solicitudes.loc[idx_real, "respuesta_admin"] = resp_admin_input
                            actualizar_hoja_completa("Solicitudes", st.session_state.solicitudes)
                            st.toast("Solicitud Aprobada")
                            time.sleep(0.3)
                            st.rerun()

                        if btn_col2.button("Rechazar", key=f"rec_{id_s}", use_container_width=True):
                            idx_real = st.session_state.solicitudes[st.session_state.solicitudes["id_solicitud"] == id_s].index
                            st.session_state.solicitudes.loc[idx_real, "estado"] = "Rechazado"
                            st.session_state.solicitudes.loc[idx_real, "respuesta_admin"] = resp_admin_input
                            actualizar_hoja_completa("Solicitudes", st.session_state.solicitudes)
                            st.toast("Solicitud Rechazada")
                            time.sleep(0.3)
                            st.rerun()
                    else:
                        if str(row_sol.get("respuesta_admin", "")).strip():
                            st.markdown(f"**Respuesta emitida:** {row_sol['respuesta_admin']}")
    else:
        st.info("No hay solicitudes registradas en el sistema.")

elif choice == "Historial de Descuadres":
    st.markdown("""
        <div class="market-header">
            <h1>Auditoría de Descuadres</h1>
            <p>Histórico completo para contabilidad</p>
        </div>
    """, unsafe_allow_html=True)

    if not st.session_state.descuadres.empty:
        st.markdown("##### 📅 Resumen Mensual de Descuadres por Trabajador")
        
        col_m_desc, col_a_desc = st.columns(2)
        ahora_p_desc = obtener_ahora_peru()
        
        NOMBRES_MESES = [
            "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
            "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
        ]
        
        mes_desc_sel = col_m_desc.selectbox(
            "Seleccionar Mes", 
            list(range(1, 13)), 
            index=ahora_p_desc.month - 1,
            format_func=lambda x: NOMBRES_MESES[x-1],
            key="mes_resumen_desc"
        )
        anio_desc_sel = col_a_desc.number_input("Año Resumen", min_value=2024, max_value=2030, value=ahora_p_desc.year, key="anio_resumen_desc")

        df_desc_mes = st.session_state.descuadres.copy()
        df_desc_mes["fecha_dt"] = pd.to_datetime(df_desc_mes["fecha"], errors="coerce")
        df_desc_mes["monto_num"] = pd.to_numeric(df_desc_mes["monto"], errors="coerce").fillna(0)
        
        df_desc_mes = df_desc_mes[
            (df_desc_mes["fecha_dt"].dt.month == mes_desc_sel) & 
            (df_desc_mes["fecha_dt"].dt.year == anio_desc_sel)
        ]

        colabs_operativos = obtener_solo_colaboradores()

        if not df_desc_mes.empty:
            for nombre_colab in colabs_operativos:
                df_c = df_desc_mes[df_desc_mes["nombre"] == nombre_colab]
                
                if not df_c.empty:
                    monto_total_colab = df_c["monto_num"].sum()
                    color_monto = "#00A959" if monto_total_colab >= 0 else "#EC3237"
                    signo_total = "+" if monto_total_colab > 0 else ""
                    
                    with st.expander(f"👤 **{nombre_colab}** | Balance Mes de {NOMBRES_MESES[mes_desc_sel-1]}: S/. {monto_total_colab:.2f}", expanded=True):
                        st.markdown(f"<div style='font-size:1.05rem; font-weight:700; color:{color_monto}; margin-bottom:8px;'>Balance Total: {signo_total} S/. {monto_total_colab:.2f}</div>", unsafe_allow_html=True)
                        st.markdown("**Desglose diario del mes:**")
                        
                        df_c_sorted = df_c.sort_values("fecha", ascending=False)
                        for _, row_d in df_c_sorted.iterrows():
                            m_val = row_d["monto_num"]
                            signo_d = "+" if m_val > 0 else ""
                            color_d = "green" if m_val >= 0 else "red"
                            
                            f_obj = row_d["fecha_dt"]
                            fecha_bonita = f"{f_obj.day} de {NOMBRES_MESES[f_obj.month - 1]}" if pd.notnull(f_obj) else row_d["fecha"]
                            
                            obs_txt = f" — *Motivo:* {row_d['observacion']}" if str(row_d.get('observacion', '')).strip() != "" else ""
                            st.markdown(f"- **{signo_d}{m_val:.2f} soles** el día {fecha_bonita}{obs_txt}")
                else:
                    st.markdown(f"👤 **{nombre_colab}**: *Sin descuadres registrados en {NOMBRES_MESES[mes_desc_sel-1]}.*")
        else:
            st.info(f"No hay descuadres registrados en el mes de {NOMBRES_MESES[mes_desc_sel-1]} de {anio_desc_sel}.")

        st.markdown("---")

        st.markdown("##### 🔍 Filtros de Búsqueda")
        f_col1, f_col2 = st.columns([1.5, 1])
        
        with f_col1:
            rango_fechas_desc = st.date_input("Rango de Fechas", value=(obtener_ahora_peru(), obtener_ahora_peru()), key="desc_fechas")
        with f_col2:
            colabs_desc = ["Todos"] + [c for c in st.session_state.descuadres["nombre"].unique().tolist() if c in obtener_solo_colaboradores()]
            colab_desc_sel = st.selectbox("Colaborador", colabs_desc, key="desc_colab")

        df_desc_filtrado = st.session_state.descuadres.copy()
        
        if isinstance(rango_fechas_desc, tuple):
            if len(rango_fechas_desc) == 2:
                f_inicio, f_fin = str(rango_fechas_desc[0]), str(rango_fechas_desc[1])
                df_desc_filtrado = df_desc_filtrado[
                    (df_desc_filtrado["fecha"].astype(str) >= f_inicio) & 
                    (df_desc_filtrado["fecha"].astype(str) <= f_fin)
                ]
            elif len(rango_fechas_desc) == 1:
                f_inicio = str(rango_fechas_desc[0])
                df_desc_filtrado = df_desc_filtrado[df_desc_filtrado["fecha"].astype(str) == f_inicio]

        if colab_desc_sel != "Todos":
            df_desc_filtrado = df_desc_filtrado[df_desc_filtrado["nombre"] == colab_desc_sel]

        if not df_desc_filtrado.empty:
            df_desc_filtrado["monto_num"] = pd.to_numeric(df_desc_filtrado["monto"], errors="coerce").fillna(0)
            sobrantes = df_desc_filtrado[df_desc_filtrado["monto_num"] > 0]["monto_num"].sum()
            faltantes = df_desc_filtrado[df_desc_filtrado["monto_num"] < 0]["monto_num"].sum()
            balance = df_desc_filtrado["monto_num"].sum()

            m1, m2, m3 = st.columns(3)
            with m1:
                st.markdown(f'<div class="info-card"><div class="info-label">Total Sobrantes (+)</div><div class="info-value" style="color:#00A959;">S/. {sobrantes:.2f}</div></div>', unsafe_allow_html=True)
            with m2:
                st.markdown(f'<div class="info-card"><div class="info-label">Total Faltantes (-)</div><div class="info-value" style="color:#EC3237;">S/. {abs(faltantes):.2f}</div></div>', unsafe_allow_html=True)
            with m3:
                st.markdown(f'<div class="info-card"><div class="info-label">Balance Neto</div><div class="info-value" style="color:{"#00A959" if balance >= 0 else "#EC3237"};">S/. {balance:.2f}</div></div>', unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("##### 👤 Balance de Descuadres por Trabajador")
            
            for nombre_trab, df_trab in df_desc_filtrado.groupby("nombre"):
                monto_trab_total = df_trab["monto_num"].sum()
                color_monto = "#00A959" if monto_trab_total >= 0 else "#EC3237"
                signo_monto = "+" if monto_trab_total > 0 else ""
                
                with st.expander(f"👤 **{nombre_trab}** — Balance Neto: {signo_monto} S/. {monto_trab_total:.2f}"):
                    st.markdown(f"<span style='color:{color_monto}; font-weight:700; font-size:1.1rem;'>Total Acumulado: {signo_monto} S/. {monto_trab_total:.2f}</span>", unsafe_allow_html=True)
                    st.markdown("**:bar_chart: Detalle de movimientos:**")
                    
                    df_trab_sorted = df_trab.sort_values("fecha", ascending=False)
                    for _, r_t in df_trab_sorted.iterrows():
                        m_val = r_t["monto_num"]
                        s_color = "green" if m_val >= 0 else "red"
                        signo_item = "+" if m_val > 0 else ""
                        obs_item = f" — *Motivo:* {r_t['observacion']}" if str(r_t.get('observacion', '')).strip() != "" else ""
                        st.markdown(f"- **El día {r_t['fecha']}:** :{s_color}[{r_t['tipo']} ({signo_item}S/. {m_val:.2f})]{obs_item}")

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("##### 📋 Matriz Consolidada de Descuadres")
        st.dataframe(
            df_desc_filtrado.drop(columns=["monto_num"], errors="ignore"),
            use_container_width=True,
            hide_index=True,
            column_config={"monto": st.column_config.NumberColumn("MONTO", format="S/. %.2f")}
        )
        st.download_button("Exportar a Excel", to_excel(df_desc_filtrado.drop(columns=["monto_num"], errors="ignore")), "Descuadres_General.xlsx", use_container_width=True)

        if rol_actual == "admin":
            st.markdown("<br>", unsafe_allow_html=True)
            col_mod, col_del = st.columns(2)

            with col_mod:
                with st.expander("Modificar Descuadre"):
                    opciones_desc = [f"{i} | {r['fecha']} | {r['nombre']} | S/. {r['monto']}" for i, r in st.session_state.descuadres.iterrows()]
                    sel_mod = st.selectbox("Seleccionar Registro a Editar", opciones_desc, key="mod_desc_sel")
                    
                    if sel_mod:
                        idx_mod = int(sel_mod.split(" | ")[0])
                        row_mod = st.session_state.descuadres.loc[idx_mod]
                        
                        nuevo_monto = st.number_input("Nuevo Monto (S/.)", value=float(row_mod["monto"]), step=0.50, format="%.2f")
                        tipo_options = ["Sobrante", "Faltante"]
                        idx_tipo = tipo_options.index(row_mod["tipo"]) if row_mod["tipo"] in tipo_options else 0
                        nuevo_tipo = st.selectbox("Nuevo Tipo", tipo_options, index=idx_tipo)
                        nueva_obs = st.text_area("Nueva Observación", value=str(row_mod["observacion"]))

                        if st.button("Guardar Cambios en Descuadre", use_container_width=True):
                            st.session_state.descuadres.at[idx_mod, "monto"] = nuevo_monto
                            st.session_state.descuadres.at[idx_mod, "tipo"] = nuevo_tipo
                            st.session_state.descuadres.at[idx_mod, "observacion"] = nueva_obs
                            actualizar_hoja_completa("Descuadres", st.session_state.descuadres)
                            st.toast("Descuadre actualizado correctamente")
                            time.sleep(0.3)
                            st.rerun()

            with col_del:
                with st.expander("Eliminar Descuadre"):
                    opciones_desc_del = [f"{i} | {r['fecha']} | {r['nombre']} | S/. {r['monto']}" for i, r in st.session_state.descuadres.iterrows()]
                    sel_del = st.selectbox("Seleccionar Registro a Eliminar", opciones_desc_del, key="del_desc_sel")
                    confirm_del_desc = st.checkbox("Confirmar eliminación del descuadre")

                    if st.button("Eliminar Descuadre", type="primary", use_container_width=True):
                        if confirm_del_desc:
                            idx_del = int(sel_del.split(" | ")[0])
                            st.session_state.descuadres = st.session_state.descuadres.drop(idx_del).reset_index(drop=True)
                            actualizar_hoja_completa("Descuadres", st.session_state.descuadres)
                            st.toast("Descuadre eliminado correctamente")
                            time.sleep(0.3)
                            st.rerun()
                        else:
                            st.warning("Marca la casilla de confirmación antes de eliminar.")
    else:
        st.info("Sin descuadres registrados.")

elif choice == "Historial de Asistencias":
    st.markdown("""
        <div class="market-header">
            <h1>Reporte de Asistencias</h1>
            <p>Histórico de marcas de ingreso y salida</p>
        </div>
    """, unsafe_allow_html=True)

    if not st.session_state.asistencia.empty:
        st.markdown("##### 🔍 Filtros de Búsqueda")
        fa_col1, fa_col2 = st.columns([1.5, 1])
        
        with fa_col1:
            rango_fechas_asist = st.date_input("Rango de Fechas", value=(obtener_ahora_peru(), obtener_ahora_peru()), key="asist_fechas")
        with fa_col2:
            colabs_asist = ["Todos"] + [c for c in st.session_state.asistencia["nombre"].unique().tolist() if c in obtener_solo_colaboradores()]
            colab_asist_sel = st.selectbox("Colaborador", colabs_asist, key="asist_colab")

        df_asist_filtrado = st.session_state.asistencia.copy()
        
        if isinstance(rango_fechas_asist, tuple):
            if len(rango_fechas_asist) == 2:
                f_inicio, f_fin = str(rango_fechas_asist[0]), str(rango_fechas_asist[1])
                df_asist_filtrado = df_asist_filtrado[
                    (df_asist_filtrado["fecha"].astype(str) >= f_inicio) & 
                    (df_asist_filtrado["fecha"].astype(str) <= f_fin)
                ]
            elif len(rango_fechas_asist) == 1:
                f_inicio = str(rango_fechas_asist[0])
                df_asist_filtrado = df_asist_filtrado[df_asist_filtrado["fecha"].astype(str) == f_inicio]

        if colab_asist_sel != "Todos":
            df_asist_filtrado = df_asist_filtrado[df_asist_filtrado["nombre"] == colab_asist_sel]

        if not df_asist_filtrado.empty:
            total_marcas = len(df_asist_filtrado)
            ingresos_cnt = len(df_asist_filtrado[df_asist_filtrado["tipo"] == "INGRESO"])
            colabs_unicos = df_asist_filtrado["nombre"].nunique()

            a1, a2, a3 = st.columns(3)
            with a1:
                st.markdown(f'<div class="info-card"><div class="info-label">Total Marcaciones</div><div class="info-value">{total_marcas}</div></div>', unsafe_allow_html=True)
            with a2:
                st.markdown(f'<div class="info-card"><div class="info-label">Jornadas Iniciadas</div><div class="info-value" style="color:#00A959;">{ingresos_cnt}</div></div>', unsafe_allow_html=True)
            with a3:
                st.markdown(f'<div class="info-card"><div class="info-label">Colaboradores Evaluados</div><div class="info-value">{colabs_unicos}</div></div>', unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        st.dataframe(df_asist_filtrado, use_container_width=True, hide_index=True)
        st.download_button("Exportar a Excel", to_excel(df_asist_filtrado), "Asistencias_General.xlsx", use_container_width=True)

        if rol_actual == "admin":
            st.markdown("<br>", unsafe_allow_html=True)
            with st.expander("Eliminar Registro de Asistencia"):
                opciones_asist = [f"{i} | {r['fecha_hora']} | {r['nombre']} | {r['tipo']}" for i, r in st.session_state.asistencia.iterrows()]
                sel_asist_del = st.selectbox("Seleccionar Marcación a Eliminar", opciones_asist)
                confirm_del_asist = st.checkbox("Confirmar eliminación del registro de asistencia")

                if st.button("Eliminar Registro", type="primary", use_container_width=True):
                    if confirm_del_asist:
                        idx_asist = int(sel_asist_del.split(" | ")[0])
                        st.session_state.asistencia = st.session_state.asistencia.drop(idx_asist).reset_index(drop=True)
                        actualizar_hoja_completa("Asistencia", st.session_state.asistencia)
                        st.toast("Marcación eliminada correctamente")
                        time.sleep(0.3)
                        st.rerun()
                    else:
                        st.warning("Marca la casilla de confirmación antes de eliminar.")
    else:
        st.info("Sin registros de asistencia.")
