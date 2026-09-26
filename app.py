import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta, time as dt_time
import calendar
import zoneinfo  # Manejo de zona horaria de Perú (UTC-5)
import io
import time
import gspread
import math
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import streamlit.components.v1 as components
# --- INTENTO DE IMPORTAR REPORTLAB PARA PDF (CON FALLBACK INTEGRADO) ---
try:
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

# =========================================================
# LOGOS DE TIENDAS PREMIUM — AGREGADO SIN MODIFICAR LA LÓGICA
# =========================================================
import os
import base64
import mimetypes

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(BASE_DIR, "assets", "logo (2).png")
LOGO_DISPONIBLE = os.path.isfile(LOGO_PATH)
LOGO_MIME = mimetypes.guess_type(LOGO_PATH)[0] or "image/png"

FAVICON_PATH = os.path.join(BASE_DIR, "assets", "logo (3).png")
FAVICON_DISPONIBLE = os.path.isfile(FAVICON_PATH)

@st.cache_data(show_spinner=False)
def _logo_base64_app39():
    if not LOGO_DISPONIBLE:
        return ""
    try:
        with open(LOGO_PATH, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")
    except Exception:
        return ""

def logo_tag_app39(height=52):
    b64 = _logo_base64_app39()
    if not b64:
        return ""
    return (
        f'<img src="data:{LOGO_MIME};base64,{b64}" alt="Tiendas Premium" '
        f'style="height:{height}px;max-width:100%;object-fit:contain;display:inline-block;">'
    )

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="Tiendas Premium EIRL",
    page_icon=FAVICON_PATH if FAVICON_DISPONIBLE else "🏪",
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
                    "fecha_inicio", "fecha_cese", "en_planilla"
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
        "fecha_inicio", "fecha_cese", "en_planilla"
    ])

def guardar_colaborador_gsheets(dni, nombre, cargo, estado, clave, rol, direccion="", telefono="", fecha_nacimiento="", foto="", contacto_emergencia="", numero_emergencia="", link_domicilio="", fecha_inicio="", fecha_cese="", en_planilla="Sí"):
    if doc_sheets:
        try:
            hoja = doc_sheets.worksheet("Colaboradores")
            encabezados_actuales = hoja.row_values(1)
            if "en_planilla" not in encabezados_actuales:
                hoja.update_cell(1, len(encabezados_actuales) + 1, "en_planilla")
                encabezados_actuales.append("en_planilla")
            hoja.append_row([
                str(dni), nombre, cargo, estado, str(clave), rol, 
                direccion, str(telefono), str(fecha_nacimiento), foto,
                contacto_emergencia, str(numero_emergencia), link_domicilio,
                str(fecha_inicio), str(fecha_cese), en_planilla
            ])
        except Exception as e:
            st.error(f"Error al guardar colaborador en Google Sheets: {e}")

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
            st.error(f"Error al guardar asistencia: {e}")

def guardar_descuadre_gsheets(fecha, dni, nombre, tipo, monto, observacion, fecha_registro):
    if doc_sheets:
        try:
            hoja = doc_sheets.worksheet("Descuadres")
            hoja.append_row([str(fecha), str(dni), nombre, tipo, float(monto), observacion, str(fecha_registro)])
        except Exception as e:
            st.error(f"Error al guardar descuadre: {e}")

# =========================================================
# NUEVO MÓDULO: INCIDENCIAS (Billete Falso, Botellas Rotas, Otros Daños)
# =========================================================
def obtener_incidencias_gsheets():
    columnas_inc = ["id_incidencia", "dni", "nombre", "fecha", "tipo_incidencia", "detalle",
                     "valor_reparacion", "fecha_registro", "registrado_por", "estado"]
    if doc_sheets:
        try:
            try:
                hoja = doc_sheets.worksheet("Incidencias")
            except gspread.exceptions.WorksheetNotFound:
                hoja = doc_sheets.add_worksheet(title="Incidencias", rows="300", cols="10")
                hoja.append_row(columnas_inc)
            datos = hoja.get_all_records()
            if datos:
                df = pd.DataFrame(datos)
                for col in columnas_inc:
                    if col not in df.columns:
                        df[col] = ""
                return df
        except Exception as e:
            st.warning(f"⚠️ No se pudo leer la hoja 'Incidencias' de Google Sheets: {e}")
    return pd.DataFrame(columns=columnas_inc)

def guardar_incidencia_gsheets(id_inc, dni, nombre, fecha, tipo_incidencia, detalle, valor_reparacion, fecha_registro, registrado_por, estado="Pendiente"):
    if doc_sheets:
        try:
            try:
                hoja = doc_sheets.worksheet("Incidencias")
            except gspread.exceptions.WorksheetNotFound:
                hoja = doc_sheets.add_worksheet(title="Incidencias", rows="300", cols="10")
                hoja.append_row(["id_incidencia", "dni", "nombre", "fecha", "tipo_incidencia", "detalle",
                                  "valor_reparacion", "fecha_registro", "registrado_por", "estado"])
            hoja.append_row([str(id_inc), str(dni), nombre, str(fecha), tipo_incidencia, detalle,
                              float(valor_reparacion), str(fecha_registro), registrado_por, estado])
            return True
        except Exception as e:
            st.error(f"❌ Error al guardar la incidencia en Google Sheets: {e}")
            return False
    else:
        st.error("❌ No hay conexión con Google Sheets. La incidencia no se guardó en la nube (solo quedó en esta sesión).")
        return False

# =========================================================
# NUEVO MÓDULO: BOTELLAS FIADAS (visible para todos los roles)
# =========================================================
def obtener_botellas_fiadas_gsheets():
    columnas_bf = ["id_fiado", "cliente_nombre", "cliente_dni", "cliente_direccion",
                   "cantidad_botellas", "tipo_botella", "dejo_dinero", "monto_dejado",
                   "fecha_prestamo", "registrado_por", "estado", "fecha_devolucion", "observacion"]
    if doc_sheets:
        try:
            try:
                hoja = doc_sheets.worksheet("BotellasFiadas")
            except gspread.exceptions.WorksheetNotFound:
                hoja = doc_sheets.add_worksheet(title="BotellasFiadas", rows="300", cols="13")
                hoja.append_row(columnas_bf)
            datos = hoja.get_all_records()
            if datos:
                df = pd.DataFrame(datos)
                for col in columnas_bf:
                    if col not in df.columns:
                        df[col] = ""
                return df
        except Exception as e:
            st.warning(f"⚠️ No se pudo leer la hoja 'BotellasFiadas' de Google Sheets: {e}")
    return pd.DataFrame(columns=columnas_bf)

def guardar_botella_fiada_gsheets(id_bf, cliente_nombre, cliente_dni, cliente_direccion, cantidad, tipo_botella, dejo_dinero, monto_dejado, fecha_prestamo, registrado_por, estado="Pendiente", fecha_devolucion="", observacion=""):
    if doc_sheets:
        try:
            try:
                hoja = doc_sheets.worksheet("BotellasFiadas")
            except gspread.exceptions.WorksheetNotFound:
                hoja = doc_sheets.add_worksheet(title="BotellasFiadas", rows="300", cols="13")
                hoja.append_row(["id_fiado", "cliente_nombre", "cliente_dni", "cliente_direccion",
                                  "cantidad_botellas", "tipo_botella", "dejo_dinero", "monto_dejado",
                                  "fecha_prestamo", "registrado_por", "estado", "fecha_devolucion", "observacion"])
            hoja.append_row([str(id_bf), cliente_nombre, str(cliente_dni), cliente_direccion,
                              int(cantidad), tipo_botella, dejo_dinero, float(monto_dejado),
                              str(fecha_prestamo), registrado_por, estado, str(fecha_devolucion), observacion])
            return True
        except Exception as e:
            st.error(f"❌ Error al guardar el registro de botellas fiadas en Google Sheets: {e}")
            return False
    else:
        st.error("❌ No hay conexión con Google Sheets. El registro no se guardó en la nube (solo quedó en esta sesión).")
        return False

def guardar_solicitud_gsheets(id_sol, fecha_reg, dni, nombre, tipo_sol, f_permiso, monto_adel, motivo, estado="Pendiente", respuesta="", requiere_recuperacion="No", fecha_recuperacion=""):
    if doc_sheets:
        try:
            hoja = doc_sheets.worksheet("Solicitudes")
            encabezados_actuales = hoja.row_values(1)
            for col in ["requiere_recuperacion", "fecha_recuperacion"]:
                if col not in encabezados_actuales:
                    hoja.update_cell(1, len(encabezados_actuales) + 1, col)
                    encabezados_actuales.append(col)
            hoja.append_row([str(id_sol), str(fecha_reg), str(dni), nombre, tipo_sol, str(f_permiso), float(monto_adel), motivo, estado, respuesta, str(requiere_recuperacion), str(fecha_recuperacion)])
        except Exception as e:
            st.error(f"Error al guardar solicitud: {e}")

def guardar_feriado_gsheets(fecha, descripcion):
    if doc_sheets:
        try:
            try:
                hoja = doc_sheets.worksheet("Feriados")
            except Exception:
                hoja = doc_sheets.add_worksheet(title="Feriados", rows="100", cols="5")
                hoja.append_row(["fecha", "descripcion"])
            hoja.append_row([str(fecha), descripcion])
        except Exception as e:
            st.error(f"Error al guardar feriado: {e}")
# =========================================================
# NUEVO MÓDULO: GESTIÓN DE VACACIONES / DESCANSO MÉDICO
# Agregado sin alterar ninguna función ni hoja existente.
# =========================================================
def obtener_vacaciones_gsheets():
    columnas_vac = ["id_vacacion", "dni", "nombre", "tipo", "fecha_inicio", "fecha_fin",
                     "dias_tomados", "observacion", "fecha_registro", "registrado_por",
                     "fecha_recuperacion", "horario_recuperacion", "estado_recuperacion"]
    if doc_sheets:
        try:
            try:
                hoja = doc_sheets.worksheet("Vacaciones")
            except gspread.exceptions.WorksheetNotFound:
                hoja = doc_sheets.add_worksheet(title="Vacaciones", rows="200", cols="13")
                hoja.append_row(columnas_vac)
            datos = hoja.get_all_records()
            if datos:
                df = pd.DataFrame(datos)
                for col in columnas_vac:
                    if col not in df.columns:
                        df[col] = ""
                return df
        except Exception as e:
            st.error(f"Error al leer Vacaciones: {e}")
    return pd.DataFrame(columns=columnas_vac)

def guardar_vacacion_gsheets(id_vac, dni, nombre, tipo, fecha_inicio, fecha_fin, dias_tomados, observacion, fecha_registro, registrado_por, fecha_recuperacion="", horario_recuperacion="", estado_recuperacion=""):
    if doc_sheets:
        try:
            try:
                hoja = doc_sheets.worksheet("Vacaciones")
            except gspread.exceptions.WorksheetNotFound:
                hoja = doc_sheets.add_worksheet(title="Vacaciones", rows="200", cols="13")
                hoja.append_row(["id_vacacion", "dni", "nombre", "tipo", "fecha_inicio", "fecha_fin",
                                  "dias_tomados", "observacion", "fecha_registro", "registrado_por",
                                  "fecha_recuperacion", "horario_recuperacion", "estado_recuperacion"])

            encabezados_actuales = hoja.row_values(1)
            for col_nueva in ["fecha_recuperacion", "horario_recuperacion", "estado_recuperacion"]:
                if col_nueva not in encabezados_actuales:
                    hoja.update_cell(1, len(encabezados_actuales) + 1, col_nueva)
                    encabezados_actuales.append(col_nueva)

            hoja.append_row([str(id_vac), str(dni), nombre, tipo, str(fecha_inicio), str(fecha_fin),
                              float(dias_tomados), observacion, str(fecha_registro), registrado_por,
                              str(fecha_recuperacion), horario_recuperacion, estado_recuperacion])
        except Exception as e:
            st.error(f"Error al guardar vacación: {e}")

def calcular_saldo_vacacional(nombre_colab, fecha_inicio_labores, df_vacaciones, en_planilla="Sí"):
    """
    Régimen REMYPE (Microempresa) en Perú: 15 días calendario de vacaciones por cada
    año completo de servicio (equivalente a 1.25 días acumulados por mes trabajado),
    y es el único beneficio social otorgado. Los trabajadores que NO están en
    planilla formal (en_planilla == "No") no generan este beneficio.
    Retorna un diccionario con el detalle del saldo disponible.
    """
    if str(en_planilla).strip().lower() != "sí" and str(en_planilla).strip().lower() != "si":
        return {"aplica": False, "dias_generados": 0.0, "dias_gozados": 0.0, "saldo_disponible": 0.0}

    dias_generados = 0.0
    f_ini = _parsear_fecha_nac_cumple(fecha_inicio_labores)
    if f_ini:
        hoy = obtener_ahora_peru().date()
        meses_completos = (hoy.year - f_ini.year) * 12 + (hoy.month - f_ini.month) - (1 if hoy.day < f_ini.day else 0)
        meses_completos = max(0, meses_completos)
        dias_generados = round(meses_completos * 1.25, 1)  # 15 días / 12 meses (REMYPE)

    if not df_vacaciones.empty:
        df_v = df_vacaciones[(df_vacaciones["nombre"] == nombre_colab) & (df_vacaciones["tipo"] == "Vacaciones")].copy()
        df_v["dias_num"] = pd.to_numeric(df_v["dias_tomados"], errors="coerce").fillna(0)
        dias_gozados = df_v["dias_num"].sum()
    else:
        dias_gozados = 0.0

    saldo_disponible = round(dias_generados - dias_gozados, 1)
    return {
        "aplica": True,
        "dias_generados": dias_generados,
        "dias_gozados": dias_gozados,
        "saldo_disponible": max(0.0, saldo_disponible)
    }

# =========================================================
# NUEVO MÓDULO: REGISTRO DE AUDITORÍA
# =========================================================
def obtener_auditoria_gsheets():
    columnas_aud = ["id_log", "fecha_hora", "usuario", "rol", "accion", "entidad", "detalle"]
    if doc_sheets:
        try:
            try:
                hoja = doc_sheets.worksheet("Auditoria")
            except gspread.exceptions.WorksheetNotFound:
                hoja = doc_sheets.add_worksheet(title="Auditoria", rows="500", cols="7")
                hoja.append_row(columnas_aud)
            datos = hoja.get_all_records()
            if datos:
                df = pd.DataFrame(datos)
                for col in columnas_aud:
                    if col not in df.columns:
                        df[col] = ""
                return df
        except Exception as e:
            st.warning(f"⚠️ No se pudo leer la hoja 'Auditoria' de Google Sheets: {e}")
    return pd.DataFrame(columns=columnas_aud)

def registrar_auditoria(accion, entidad, detalle=""):
    """Deja constancia de quién hizo qué y cuándo. Se llama en cada acción
    administrativa sensible (editar, eliminar, aprobar, dar de baja, etc.)."""
    try:
        usuario_aud = st.session_state.get("usuario_login", "Desconocido") or "Desconocido"
        _usuarios_globales = globals().get("USUARIOS", {})
        rol_aud = _usuarios_globales.get(usuario_aud, {}).get("rol", "-")
    except Exception:
        usuario_aud, rol_aud = "Desconocido", "-"

    fecha_h_aud = obtener_ahora_peru().strftime("%Y-%m-%d %H:%M:%S")
    id_log_aud = f"LOG-{int(time.time()*1000)}"

    nuevo_log = {
        "id_log": id_log_aud, "fecha_hora": fecha_h_aud, "usuario": usuario_aud,
        "rol": rol_aud, "accion": accion, "entidad": entidad, "detalle": detalle
    }
    if "auditoria" in st.session_state:
        st.session_state.auditoria = pd.concat([pd.DataFrame([nuevo_log]), st.session_state.auditoria], ignore_index=True)

    if doc_sheets:
        try:
            try:
                hoja = doc_sheets.worksheet("Auditoria")
            except gspread.exceptions.WorksheetNotFound:
                hoja = doc_sheets.add_worksheet(title="Auditoria", rows="500", cols="7")
                hoja.append_row(["id_log", "fecha_hora", "usuario", "rol", "accion", "entidad", "detalle"])
            hoja.append_row([id_log_aud, fecha_h_aud, usuario_aud, rol_aud, accion, entidad, str(detalle)])
        except Exception as e:
            st.warning(f"⚠️ No se pudo guardar en la hoja 'Auditoria' de Google Sheets: {e}")

# =========================================================
# NUEVO MÓDULO: CONFIGURACIÓN DEL SISTEMA (GPS / Notificaciones)
# =========================================================
def obtener_configuracion_gsheets():
    config_default = {
        "tienda_lat": "-12.046374", "tienda_lon": "-77.042793", "radio_metros": "150",
        "bloquear_fuera_rango": "No", "email_notificaciones": "humberto1098@outlook.com"
    }
    if doc_sheets:
        try:
            try:
                hoja = doc_sheets.worksheet("Configuracion")
            except gspread.exceptions.WorksheetNotFound:
                hoja = doc_sheets.add_worksheet(title="Configuracion", rows="20", cols="2")
                hoja.append_row(["clave", "valor"])
                for k, v in config_default.items():
                    hoja.append_row([k, v])
                return config_default
            datos = hoja.get_all_records()
            if datos:
                cfg = {row["clave"]: row["valor"] for row in datos if row.get("clave")}
                for k, v in config_default.items():
                    if k not in cfg:
                        cfg[k] = v
                return cfg
        except Exception as e:
            st.warning(f"⚠️ No se pudo leer la hoja 'Configuracion' de Google Sheets: {e}")
    return config_default

def guardar_configuracion_gsheets(clave, valor):
    if doc_sheets:
        try:
            try:
                hoja = doc_sheets.worksheet("Configuracion")
            except gspread.exceptions.WorksheetNotFound:
                hoja = doc_sheets.add_worksheet(title="Configuracion", rows="20", cols="2")
                hoja.append_row(["clave", "valor"])
            celdas = hoja.findall(str(clave), in_column=1)
            if celdas:
                hoja.update_cell(celdas[0].row, 2, str(valor))
            else:
                hoja.append_row([str(clave), str(valor)])
        except Exception as e:
            st.error(f"Error al guardar configuración: {e}")

def calcular_distancia_metros(lat1, lon1, lat2, lon2):
    """Fórmula de Haversine: distancia en metros entre dos coordenadas GPS."""
    try:
        R = 6371000
        lat1, lon1, lat2, lon2 = map(float, [lat1, lon1, lat2, lon2])
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda/2)**2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    except Exception:
        return None

# =========================================================
# NUEVO MÓDULO: NOTIFICACIONES POR CORREO
# =========================================================
def enviar_correo_alerta(asunto, cuerpo_html, destinatario=None):
    """Envía un correo usando las credenciales SMTP configuradas en st.secrets['email'].
    Requiere configurar en Settings > Secrets:
    [email]
    remitente = "tu_correo@outlook.com"
    clave_app = "tu_contraseña_de_aplicación"
    servidor = "smtp-mail.outlook.com"
    puerto = 587
    Si no está configurado, informa al usuario en vez de fallar silenciosamente."""
    if "email" not in st.secrets:
        return False, "No se ha configurado el envío de correo (falta la sección [email] en Secrets)."
    try:
        cfg_sys = obtener_configuracion_gsheets()
        dest_final = destinatario or cfg_sys.get("email_notificaciones", "humberto1098@outlook.com")

        remitente = st.secrets["email"]["remitente"]
        clave_app = st.secrets["email"]["clave_app"]
        servidor = st.secrets["email"].get("servidor", "smtp-mail.outlook.com")
        puerto = int(st.secrets["email"].get("puerto", 587))

        msg = MIMEMultipart("alternative")
        msg["Subject"] = asunto
        msg["From"] = remitente
        msg["To"] = dest_final
        msg.attach(MIMEText(cuerpo_html, "html"))

        with smtplib.SMTP(servidor, puerto) as server:
            server.starttls()
            server.login(remitente, clave_app)
            server.sendmail(remitente, dest_final, msg.as_string())
        return True, f"Correo enviado a {dest_final}"
    except Exception as e:
        return False, f"No se pudo enviar el correo: {e}"

# =========================================================
# NUEVO MÓDULO: ONBOARDING / OFFBOARDING ESTRUCTURADO
# =========================================================
TAREAS_ONBOARDING_DEFAULT = [
    "Firma de contrato de trabajo",
    "Entrega de uniforme",
    "Entrega de fotocheck / credencial",
    "Capacitación inicial (caja, procesos, políticas)",
    "Registro formal en planilla (REMYPE)",
    "Creación de usuario en el sistema"
]
TAREAS_OFFBOARDING_DEFAULT = [
    "Carta de renuncia / documento de cese",
    "Devolución de uniforme",
    "Devolución de llaves / accesos",
    "Verificación de saldo de caja e inventario",
    "Liquidación de beneficios sociales",
    "Baja de usuario en el sistema"
]

def obtener_checklist_gsheets():
    columnas_chk = ["id_item", "dni", "nombre", "tipo", "tarea", "estado", "fecha_creacion", "fecha_completado"]
    if doc_sheets:
        try:
            try:
                hoja = doc_sheets.worksheet("Checklist")
            except gspread.exceptions.WorksheetNotFound:
                hoja = doc_sheets.add_worksheet(title="Checklist", rows="500", cols="8")
                hoja.append_row(columnas_chk)
            datos = hoja.get_all_records()
            if datos:
                df = pd.DataFrame(datos)
                for col in columnas_chk:
                    if col not in df.columns:
                        df[col] = ""
                return df
        except Exception as e:
            st.warning(f"⚠️ No se pudo leer la hoja 'Checklist' de Google Sheets: {e}")
    return pd.DataFrame(columns=columnas_chk)

def guardar_item_checklist_gsheets(id_item, dni, nombre, tipo, tarea, estado, fecha_creacion, fecha_completado=""):
    if doc_sheets:
        try:
            try:
                hoja = doc_sheets.worksheet("Checklist")
            except gspread.exceptions.WorksheetNotFound:
                hoja = doc_sheets.add_worksheet(title="Checklist", rows="500", cols="8")
                hoja.append_row(["id_item", "dni", "nombre", "tipo", "tarea", "estado", "fecha_creacion", "fecha_completado"])
            hoja.append_row([id_item, str(dni), nombre, tipo, tarea, estado, str(fecha_creacion), str(fecha_completado)])
        except Exception as e:
            st.error(f"Error al guardar checklist: {e}")

def _crear_checklist_generico(dni, nombre, tipo, tareas):
    fecha_c = obtener_ahora_peru().strftime("%Y-%m-%d %H:%M:%S")
    nuevas_filas = []
    for tarea in tareas:
        id_item = f"CHK-{int(time.time()*1000)}-{tareas.index(tarea)}"
        guardar_item_checklist_gsheets(id_item, dni, nombre, tipo, tarea, "Pendiente", fecha_c, "")
        nuevas_filas.append({
            "id_item": id_item, "dni": dni, "nombre": nombre, "tipo": tipo,
            "tarea": tarea, "estado": "Pendiente", "fecha_creacion": fecha_c, "fecha_completado": ""
        })
    if "checklist" in st.session_state:
        st.session_state.checklist = pd.concat([pd.DataFrame(nuevas_filas), st.session_state.checklist], ignore_index=True)
    registrar_auditoria(f"Crear Checklist de {tipo}", "Checklist", f"{nombre} — {len(tareas)} tarea(s) generadas")

def crear_checklist_onboarding(dni, nombre):
    _crear_checklist_generico(dni, nombre, "Onboarding", TAREAS_ONBOARDING_DEFAULT)

def crear_checklist_offboarding(dni, nombre):
    _crear_checklist_generico(dni, nombre, "Offboarding", TAREAS_OFFBOARDING_DEFAULT)

# =========================================================
# NUEVO MÓDULO: HISTORIAL DE BOLETAS (para Analítica / BI)
# =========================================================
def obtener_boletas_historial_gsheets():
    columnas_bh = ["id_boleta", "mes", "anio", "dni", "nombre", "cargo", "sueldo_basico",
                   "total_ingresos", "total_descuentos", "neto_pagar", "fecha_emision", "emitido_por"]
    if doc_sheets:
        try:
            try:
                hoja = doc_sheets.worksheet("Boletas_Historial")
            except gspread.exceptions.WorksheetNotFound:
                hoja = doc_sheets.add_worksheet(title="Boletas_Historial", rows="500", cols="12")
                hoja.append_row(columnas_bh)
            datos = hoja.get_all_records()
            if datos:
                df = pd.DataFrame(datos)
                for col in columnas_bh:
                    if col not in df.columns:
                        df[col] = ""
                return df
        except Exception as e:
            st.warning(f"⚠️ No se pudo leer la hoja 'Boletas_Historial' de Google Sheets: {e}")
    return pd.DataFrame(columns=columnas_bh)

def guardar_boleta_historial_gsheets(datos_b):
    if doc_sheets:
        try:
            try:
                hoja = doc_sheets.worksheet("Boletas_Historial")
            except gspread.exceptions.WorksheetNotFound:
                hoja = doc_sheets.add_worksheet(title="Boletas_Historial", rows="500", cols="12")
                hoja.append_row(["id_boleta", "mes", "anio", "dni", "nombre", "cargo", "sueldo_basico",
                                  "total_ingresos", "total_descuentos", "neto_pagar", "fecha_emision", "emitido_por"])
            id_b = f"BOL-{int(time.time()*1000)}"
            hoja.append_row([
                id_b, datos_b["mes"], datos_b["anio"], str(datos_b["dni"]), datos_b["nombre"], datos_b["cargo"],
                float(datos_b["sueldo_basico"]), float(datos_b["total_ingresos"]), float(datos_b["total_descuentos"]),
                float(datos_b["neto_pagar"]), obtener_ahora_peru().strftime("%Y-%m-%d %H:%M:%S"), datos_b.get("emitido_por", "")
            ])
            return id_b
        except Exception as e:
            st.error(f"Error al guardar historial de boleta: {e}")
    return None

def actualizar_hoja_completa(nombre_hoja, df):
    if doc_sheets:
        try:
            hoja = doc_sheets.worksheet(nombre_hoja)
            hoja.clear()
            datos = [df.columns.tolist()] + df.astype(str).values.tolist()
            hoja.update(datos)
        except Exception as e:
            st.error(f"Error al actualizar {nombre_hoja}: {e}")

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
    .bg-permiso {
        background-color: #ede9fe !important;
        color: #6d28d9 !important;
        border: 1px solid #c4b5fd !important;
    }
    .bg-permiso-pendiente {
        background-color: #fef3c7 !important;
        color: #92400e !important;
        border: 1px solid #fcd34d !important;
    }
    .bg-recuperacion {
        background-color: #cffafe !important;
        color: #0e7490 !important;
        border: 1px solid #67e8f9 !important;
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
    .bg-permiso-salud {
        background-color: #fce7f3 !important;
        color: #be185d !important;
        border: 1px solid #f9a8d4 !important;
    }
    .bg-recuperacion-salud {
        background-color: #e0e7ff !important;
        color: #4338ca !important;
        border: 1px solid #c7d2fe !important;
    }
    .bg-domingo-voluntario {
        background-color: #ccfbf1 !important;
        color: #0f766e !important;
        border: 1px solid #5eead4 !important;
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

    .app-footer {
        text-align: center;
        padding: 24px 10px 12px 10px;
        margin-top: 40px;
        border-top: 1px solid #E5E7EB;
        color: #6B7280;
        font-size: 0.8rem;
        line-height: 1.5;
    }
    .app-footer strong {
        color: #111827;
    }
    /* ESTILOS DE BOLETA DE PAGO EN HTML */
    .boleta-container {
        background-color: #ffffff;
        border: 2px solid #111827;
        padding: 24px;
        border-radius: 6px;
        max-width: 850px;
        margin: 0 auto 20px auto;
        color: #111827;
        font-family: 'Montserrat', sans-serif;
    }
    .boleta-header-title {
        text-align: center;
        font-size: 1.2rem;
        font-weight: 800;
        letter-spacing: 1px;
        border-bottom: 2px solid #111827;
        padding-bottom: 8px;
        margin-bottom: 15px;
    }
    .boleta-table {
        width: 100%;
        border-collapse: collapse;
        margin-bottom: 12px;
        font-size: 0.82rem;
    }
    .boleta-table th, .boleta-table td {
        border: 1px solid #000;
        padding: 6px 8px;
        text-align: left;
    }
    .boleta-table th {
        background-color: #f3f4f6;
        font-weight: 700;
    }
</style>
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

if "en_planilla" not in st.session_state.empleados.columns:
    st.session_state.empleados["en_planilla"] = "Sí"
else:
    st.session_state.empleados["en_planilla"] = st.session_state.empleados["en_planilla"].replace("", "Sí").fillna("Sí")

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
    columnas_solicitudes = [
        "id_solicitud", "fecha_registro", "dni", "nombre", "tipo_solicitud",
        "fecha_permiso", "monto_adelanto", "motivo", "estado", "respuesta_admin",
        "requiere_recuperacion", "fecha_recuperacion"
    ]
    if doc_sheets:
        try:
            data_sol = doc_sheets.worksheet("Solicitudes").get_all_records()
            st.session_state.solicitudes = pd.DataFrame(data_sol)
        except Exception:
            st.session_state.solicitudes = pd.DataFrame(columns=columnas_solicitudes)
    else:
        st.session_state.solicitudes = pd.DataFrame(columns=columnas_solicitudes)

    for col_sol in columnas_solicitudes:
        if col_sol not in st.session_state.solicitudes.columns:
            st.session_state.solicitudes[col_sol] = ""

if "feriados" not in st.session_state:
    if doc_sheets:
        try:
            data_fer = doc_sheets.worksheet("Feriados").get_all_records()
            st.session_state.feriados = pd.DataFrame(data_fer)
        except Exception:
            st.session_state.feriados = pd.DataFrame([
                {"fecha": "2026-01-01", "descripcion": "Año Nuevo"},
                {"fecha": "2026-04-02", "descripcion": "Jueves Santo"},
                {"fecha": "2026-04-03", "descripcion": "Viernes Santo"},
                {"fecha": "2026-05-01", "descripcion": "Día del Trabajo"},
                {"fecha": "2026-06-29", "descripcion": "San Pedro y San Pablo"},
                {"fecha": "2026-07-28", "descripcion": "Fiestas Patrias"},
                {"fecha": "2026-07-29", "descripcion": "Fiestas Patrias"},
                {"fecha": "2026-08-06", "descripcion": "Batalla de Junín"},
                {"fecha": "2026-08-30", "descripcion": "Santa Rosa de Lima"},
                {"fecha": "2026-10-08", "descripcion": "Combate de Angamos"},
                {"fecha": "2026-11-01", "descripcion": "Día de Todos los Santos"},
                {"fecha": "2026-12-08", "descripcion": "Inmaculada Concepción"},
                {"fecha": "2026-12-09", "descripcion": "Batalla de Ayacucho"},
                {"fecha": "2026-12-25", "descripcion": "Navidad"}
            ])
    else:
        st.session_state.feriados = pd.DataFrame([
            {"fecha": "2026-01-01", "descripcion": "Año Nuevo"},
            {"fecha": "2026-04-02", "descripcion": "Jueves Santo"},
            {"fecha": "2026-04-03", "descripcion": "Viernes Santo"},
            {"fecha": "2026-05-01", "descripcion": "Día del Trabajo"},
            {"fecha": "2026-06-29", "descripcion": "San Pedro y San Pablo"},
            {"fecha": "2026-07-28", "descripcion": "Fiestas Patrias"},
            {"fecha": "2026-07-29", "descripcion": "Fiestas Patrias"},
            {"fecha": "2026-08-06", "descripcion": "Batalla de Junín"},
            {"fecha": "2026-08-30", "descripcion": "Santa Rosa de Lima"},
            {"fecha": "2026-10-08", "descripcion": "Combate de Angamos"},
            {"fecha": "2026-11-01", "descripcion": "Día de Todos los Santos"},
            {"fecha": "2026-12-08", "descripcion": "Inmaculada Concepción"},
            {"fecha": "2026-12-09", "descripcion": "Batalla de Ayacucho"},
            {"fecha": "2026-12-25", "descripcion": "Navidad"}
        ])

# --- NUEVO: ESTADO DE SESIÓN PARA EL MÓDULO DE VACACIONES ---
if "vacaciones" not in st.session_state:
    st.session_state.vacaciones = obtener_vacaciones_gsheets()

# --- NUEVO: ESTADO DE SESIÓN PARA AUDITORÍA Y CONFIGURACIÓN ---
if "auditoria" not in st.session_state:
    st.session_state.auditoria = obtener_auditoria_gsheets()

if "config_sistema" not in st.session_state:
    st.session_state.config_sistema = obtener_configuracion_gsheets()

if "checklist" not in st.session_state:
    st.session_state.checklist = obtener_checklist_gsheets()

if "boletas_historial" not in st.session_state:
    st.session_state.boletas_historial = obtener_boletas_historial_gsheets()

if "incidencias" not in st.session_state:
    st.session_state.incidencias = obtener_incidencias_gsheets()

if "botellas_fiadas" not in st.session_state:
    st.session_state.botellas_fiadas = obtener_botellas_fiadas_gsheets()

USUARIOS = {}
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
            st.markdown(f'<div style="text-align:center; padding: 8px 0 12px 0;">{logo_tag_app39(72)}</div>', unsafe_allow_html=True)
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
                    st.session_state.login_timestamp = time.time()
                    st.session_state.ultima_actividad = time.time()
                    st.success("Acceso concedido")
                    time.sleep(0.3)
                    st.rerun()
                else:
                    st.error("Credenciales incorrectas")
    st.stop()

# --- NUEVO: CONTROL DE EXPIRACIÓN DE SESIÓN ---
# Sesión máxima de 10 horas desde el login, y cierre automático tras 30 minutos de inactividad.
SESION_MAX_SEGUNDOS = 10 * 60 * 60
INACTIVIDAD_MAX_SEGUNDOS = 30 * 60

if "login_timestamp" not in st.session_state:
    st.session_state.login_timestamp = time.time()
if "ultima_actividad" not in st.session_state:
    st.session_state.ultima_actividad = time.time()

_ahora_sesion = time.time()
_tiempo_desde_login = _ahora_sesion - st.session_state.login_timestamp
_tiempo_inactivo = _ahora_sesion - st.session_state.ultima_actividad

if _tiempo_desde_login > SESION_MAX_SEGUNDOS or _tiempo_inactivo > INACTIVIDAD_MAX_SEGUNDOS:
    _motivo_cierre = "duración máxima (10 horas)" if _tiempo_desde_login > SESION_MAX_SEGUNDOS else "inactividad (30 minutos)"
    st.session_state.usuario_login = None
    st.session_state.login_auditado = False
    st.warning(f"Tu sesión se cerró automáticamente por {_motivo_cierre}. Por favor, vuelve a iniciar sesión.")
    time.sleep(1.2)
    st.rerun()

st.session_state.ultima_actividad = _ahora_sesion

user_actual = st.session_state.usuario_login
rol_actual = USUARIOS[user_actual]["rol"]
dni_actual = USUARIOS[user_actual]["dni"]

if not st.session_state.get("login_auditado", False):
    registrar_auditoria("Inicio de Sesión", "Usuarios", f"{user_actual} ({rol_actual}) inició sesión.")
    st.session_state.login_auditado = True

# =========================================================
# 🎉 SALUDO DE CUMPLEAÑOS
# =========================================================
def _parsear_fecha_nac_cumple(f_str):
    """Parseador de fecha propio del módulo de cumpleaños (no depende de
    funciones definidas más abajo en el archivo, para evitar NameError
    al ejecutarse justo después del login)."""
    if not f_str or str(f_str).strip() in ["", "-", "None", "nan", "NaT"]:
        return None
    txt = str(f_str).split(" ")[0].strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(txt, fmt).date()
        except Exception:
            continue
    return None

def _es_cumpleanos_hoy(fecha_nac_str, hoy_date):
    """Compara día y mes de fecha_nacimiento contra la fecha actual (Perú)."""
    f_nac = _parsear_fecha_nac_cumple(fecha_nac_str)
    if f_nac is None:
        return False
    return (f_nac.day == hoy_date.day) and (f_nac.month == hoy_date.month)

def _mostrar_modal_cumpleanos(nombre_usuario):
    hoy_peru = obtener_ahora_peru().date()
    fila_usuario = st.session_state.empleados[st.session_state.empleados["nombre"] == nombre_usuario]

    if fila_usuario.empty:
        return

    fecha_nac_usuario = str(fila_usuario.iloc[0].get("fecha_nacimiento", "")).strip()

    if not _es_cumpleanos_hoy(fecha_nac_usuario, hoy_peru):
        return

    clave_flag = f"cumple_mostrado_{nombre_usuario}_{hoy_peru.isoformat()}"
    if st.session_state.get(clave_flag, False):
        return

    # Se marca como "ya mostrado" de inmediato (no al cerrar el modal),
    # para que aparezca una sola vez tras el login y no se reabra al
    # navegar por las secciones del sidebar.
    st.session_state[clave_flag] = True

    @st.dialog(" ¡Feliz Cumpleaños! ")
    def _dialogo_cumpleanos():
        st.markdown(f"""
            <div style="text-align:center; padding: 10px 0 4px 0;">
                <div style="font-size: 3rem; line-height: 1;">🎉🎂🎈</div>
                <h2 style="margin: 12px 0 4px 0; color:#EC3237;">¡Feliz Cumpleaños, {nombre_usuario.split(' ')[0]}!</h2>
                <p style="font-size: 0.98rem; color:#374151; margin: 14px auto 0 auto; max-width: 400px; line-height: 1.6; text-align:left;">
                    De parte de todo el equipo de <strong>Tiendas Premium E.I.R.L.</strong>, queremos
                    desearte un excelente día, lleno de alegría y buenos momentos junto a tus seres queridos.
                </p>
                <p style="font-size: 0.98rem; color:#374151; margin: 12px auto 0 auto; max-width: 400px; line-height: 1.6; text-align:left;">
                    Agradecemos tu compromiso, esfuerzo y dedicación como parte de nuestro equipo.
                </p>
                <p style="font-size: 0.98rem; color:#374151; margin: 12px auto 0 auto; max-width: 400px; line-height: 1.6; text-align:left;">
                    ¡Que este nuevo año de vida venga acompañado de muchos éxitos, salud y nuevas metas cumplidas!
                </p>
                <p style="font-size: 1.02rem; color:#111827; font-weight:600; margin: 14px auto 0 auto; max-width: 400px; line-height: 1.6;">
                    ¡Feliz cumpleaños y a seguir creciendo juntos!
                </p>
                <p style="font-size: 0.95rem; color:#6B7280; margin: 18px 0 0 0; font-style: italic;">
                    Con cariño,<br>
                    <strong>Tiendas Premium E.I.R.L.</strong> ❤️💚
                </p>
                <div style="font-size: 2rem; margin-top: 14px;"></div>
            </div>
        """, unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("¡Gracias! Continuar", use_container_width=True):
            st.rerun()

    _dialogo_cumpleanos()

_mostrar_modal_cumpleanos(user_actual)
# =========================================================
# FIN SALUDO DE CUMPLEAÑOS
# =========================================================

def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False)
    return output.getvalue()

def generar_excel_boleta(datos_b):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df_emp = pd.DataFrame([{
            "EMPRESA": datos_b["empresa"],
            "RUC": datos_b["ruc"],
            "PERÍODO": datos_b["periodo"],
            "COLABORADOR": datos_b["colaborador"],
            "DNI": datos_b["dni"],
            "CARGO": datos_b["cargo"],
            "FECHA INGRESO": datos_b["fecha_inicio"]
        }])
        df_emp.to_excel(writer, sheet_name="Boleta de Pago", index=False, startrow=0)

        df_calc = pd.DataFrame([
            {"CONCEPTO": "SUELDO BÁSICO", "CANTIDAD": f"{datos_b['dias_trabajados']} Días", "INGRESOS (S/.)": datos_b["sueldo_basico"], "DESCUENTOS (S/.)": 0.0},
            {"CONCEPTO": "PAGO FERIADOS TRABAJADOS (ADICIONAL)", "CANTIDAD": f"{datos_b['feriados_trabajados']} Días", "INGRESOS (S/.)": datos_b["monto_feriados"], "DESCUENTOS (S/.)": 0.0},
            {"CONCEPTO": "HORAS EXTRAS TRABAJADAS", "CANTIDAD": f"{datos_b['horas_extras_hrs']:.2f} Hrs", "INGRESOS (S/.)": datos_b["monto_horas_extras"], "DESCUENTOS (S/.)": 0.0},
            {"CONCEPTO": "DÍA DE DESCANSO TRABAJADO VOLUNTARIAMENTE (DOMINGO)", "CANTIDAD": f"{datos_b.get('domingos_voluntarios', 0)} Día(s)", "INGRESOS (S/.)": datos_b.get("monto_domingos_voluntarios", 0.0), "DESCUENTOS (S/.)": 0.0},
            {"CONCEPTO": "ADELANTO DE SUELDO", "CANTIDAD": "-", "INGRESOS (S/.)": 0.0, "DESCUENTOS (S/.)": datos_b["adelanto_sueldo"]},
            {"CONCEPTO": "DESCUENTOS POR FALTAS", "CANTIDAD": f"{datos_b['dias_faltas']} Días", "INGRESOS (S/.)": 0.0, "DESCUENTOS (S/.)": datos_b["monto_faltas"]},
            {"CONCEPTO": "DESCUADRES / FALTANTE DE CAJA", "CANTIDAD": "-", "INGRESOS (S/.)": 0.0, "DESCUENTOS (S/.)": datos_b["descuadre_caja"]},
            {"CONCEPTO": "DESCUADRES DE INVENTARIO", "CANTIDAD": "-", "INGRESOS (S/.)": 0.0, "DESCUENTOS (S/.)": datos_b.get("descuadre_inventario", 0.0)},
            {"CONCEPTO": "CONSUMOS POR PAGAR", "CANTIDAD": "-", "INGRESOS (S/.)": 0.0, "DESCUENTOS (S/.)": datos_b.get("consumos_pagar", 0.0)},
            {"CONCEPTO": "TOTALES", "CANTIDAD": "", "INGRESOS (S/.)": datos_b["total_ingresos"], "DESCUENTOS (S/.)": datos_b["total_descuentos"]},
            {"CONCEPTO": "NETO A PAGAR", "CANTIDAD": "", "INGRESOS (S/.)": datos_b["neto_pagar"], "DESCUENTOS (S/.)": 0.0}
        ])
        df_calc.to_excel(writer, sheet_name="Boleta de Pago", index=False, startrow=10)
    return output.getvalue()

def generar_pdf_boleta(datos_b):
    if not REPORTLAB_AVAILABLE:
        return None

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    story = []

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'TitleStyle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=14,
        alignment=1,
        spaceAfter=10
    )
    bold_style = ParagraphStyle('BoldStyle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9)
    normal_style = ParagraphStyle('NormalStyle', parent=styles['Normal'], fontName='Helvetica', fontSize=9)

    story.append(Paragraph(f"<b>{datos_b['empresa']}</b>", title_style))
    story.append(Paragraph(f"RUC: {datos_b['ruc']} | PERÍODO DE PAGO: {datos_b['periodo']}", ParagraphStyle('Sub', alignment=1, fontSize=10, fontName='Helvetica-Bold')))
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.black, spaceAfter=15))

    info_data = [
        [Paragraph("<b>COLABORADOR:</b>", bold_style), Paragraph(str(datos_b['colaborador']), normal_style), Paragraph("<b>DNI:</b>", bold_style), Paragraph(str(datos_b['dni']), normal_style)],
        [Paragraph("<b>CARGO:</b>", bold_style), Paragraph(str(datos_b['cargo']), normal_style), Paragraph("<b>FECHA INGRESO:</b>", bold_style), Paragraph(str(datos_b['fecha_inicio']), normal_style)],
        [Paragraph("<b>DÍAS LABORADOS:</b>", bold_style), Paragraph(str(datos_b['dias_trabajados']), normal_style), Paragraph("<b>DÍAS FALTAS:</b>", bold_style), Paragraph(str(datos_b['dias_faltas']), normal_style)],
        [Paragraph("<b>FERIADOS TRAB.:</b>", bold_style), Paragraph(str(datos_b['feriados_trabajados']), normal_style), Paragraph("<b>HORAS EXTRAS:</b>", bold_style), Paragraph(f"{datos_b['horas_extras_hrs']:.2f} hrs", normal_style)],
        [Paragraph("<b>DOM. VOLUNTARIOS:</b>", bold_style), Paragraph(str(datos_b.get('domingos_voluntarios', 0)), normal_style), Paragraph("", normal_style), Paragraph("", normal_style)]
    ]
    t_info = Table(info_data, colWidths=[110, 160, 110, 160])
    t_info.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.gray),
        ('BACKGROUND', (0,0), (0,-1), colors.whitesmoke),
        ('BACKGROUND', (2,0), (2,-1), colors.whitesmoke),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('PADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(t_info)
    story.append(Spacer(1, 15))

    calc_data = [
        [Paragraph("<b>CONCEPTO / RUBRO</b>", bold_style), Paragraph("<b>CANTIDAD</b>", bold_style), Paragraph("<b>INGRESOS (S/.)</b>", bold_style), Paragraph("<b>DESCUENTOS (S/.)</b>", bold_style)],
        [Paragraph("SUELDO BÁSICO", normal_style), Paragraph(f"{datos_b['dias_trabajados']} días", normal_style), Paragraph(f"{datos_b['sueldo_basico']:.2f}", normal_style), Paragraph("0.00", normal_style)],
        [Paragraph("PAGO FERIADOS TRABAJADOS (ADICIONAL)", normal_style), Paragraph(f"{datos_b['feriados_trabajados']} días", normal_style), Paragraph(f"{datos_b['monto_feriados']:.2f}", normal_style), Paragraph("0.00", normal_style)],
        [Paragraph("HORAS EXTRAS TRABAJADAS", normal_style), Paragraph(f"{datos_b['horas_extras_hrs']:.2f} hrs", normal_style), Paragraph(f"{datos_b['monto_horas_extras']:.2f}", normal_style), Paragraph("0.00", normal_style)],
        [Paragraph("DÍA DE DESCANSO TRABAJADO VOLUNTARIAMENTE (DOMINGO)", normal_style), Paragraph(f"{datos_b.get('domingos_voluntarios', 0)} día(s)", normal_style), Paragraph(f"{datos_b.get('monto_domingos_voluntarios', 0.0):.2f}", normal_style), Paragraph("0.00", normal_style)],
        [Paragraph("ADELANTO DE SUELDO", normal_style), Paragraph("-", normal_style), Paragraph("0.00", normal_style), Paragraph(f"{datos_b['adelanto_sueldo']:.2f}", normal_style)],
        [Paragraph("DESCUENTO POR FALTAS", normal_style), Paragraph(f"{datos_b['dias_faltas']} días", normal_style), Paragraph("0.00", normal_style), Paragraph(f"{datos_b['monto_faltas']:.2f}", normal_style)],
        [Paragraph("DESCUADRE / FALTANTE DE CAJA", normal_style), Paragraph("-", normal_style), Paragraph("0.00", normal_style), Paragraph(f"{datos_b['descuadre_caja']:.2f}", normal_style)],
        [Paragraph("DESCUADRES DE INVENTARIO", normal_style), Paragraph("-", normal_style), Paragraph("0.00", normal_style), Paragraph(f"{datos_b.get('descuadre_inventario', 0.0):.2f}", normal_style)],
        [Paragraph("CONSUMOS POR PAGAR", normal_style), Paragraph("-", normal_style), Paragraph("0.00", normal_style), Paragraph(f"{datos_b.get('consumos_pagar', 0.0):.2f}", normal_style)],
        [Paragraph("<b>TOTALES</b>", bold_style), Paragraph("", normal_style), Paragraph(f"<b>S/. {datos_b['total_ingresos']:.2f}</b>", bold_style), Paragraph(f"<b>S/. {datos_b['total_descuentos']:.2f}</b>", bold_style)],
        [Paragraph("<b>NETO A PAGAR</b>", ParagraphStyle('Neto', parent=bold_style, fontSize=11, textColor=colors.black)), Paragraph("", normal_style), Paragraph(f"<b>S/. {datos_b['neto_pagar']:.2f}</b>", ParagraphStyle('NetoVal', parent=bold_style, fontSize=11, textColor=colors.black)), Paragraph("", normal_style)]
    ]

    t_calc = Table(calc_data, colWidths=[200, 100, 120, 120])
    t_calc.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#E5E7EB')),
        ('BACKGROUND', (0,-2), (-1,-2), colors.whitesmoke),
        ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor('#F3F4F6')),
        ('SPAN', (0,-1), (1,-1)),
        ('SPAN', (2,-1), (3,-1)),
        ('ALIGN', (2,0), (-1,-1), 'RIGHT'),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))

    story.append(t_calc)
    story.append(Spacer(1, 40))

    # SOLUCIÓN DEL ERROR PARAPARSER: SEPARAR LA LÍNEA Y EL TEXTO EN PARÁGRAFOS INDEPENDIENTES
    f1_line = Paragraph("_______________________________", ParagraphStyle('Line1', alignment=1, fontSize=8, fontName='Helvetica'))
    f1_text = Paragraph("<b>EMPLEADOR / TIENDAS PREMIUM</b>", ParagraphStyle('Text1', alignment=1, fontSize=8, fontName='Helvetica-Bold'))
    
    f2_line = Paragraph("_______________________________", ParagraphStyle('Line2', alignment=1, fontSize=8, fontName='Helvetica'))
    f2_text = Paragraph("<b>RECIBÍ CONFORME (TRABAJADOR)</b>", ParagraphStyle('Text2', alignment=1, fontSize=8, fontName='Helvetica-Bold'))

    firmas = [
        [[f1_line, Spacer(1, 4), f1_text], [f2_line, Spacer(1, 4), f2_text]]
    ]
    t_firmas = Table(firmas, colWidths=[270, 270])
    t_firmas.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE')
    ]))
    story.append(t_firmas)

    doc.build(story)
    return buffer.getvalue()
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
                st.warning(f"Ya registraste un **{tipo}** continuo en tu jornada.")
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

        st.markdown("<div class='profile-field'>PERÍODO LABORAL / TIEMPO TRABAJADO:</div>", unsafe_allow_html=True)
        if estado_val.lower() in ["desactivado", "dado de baja"]:
            st.markdown(f"<div class='profile-val' style='color:#EC3237; font-weight:600;'>Se retiró de la empresa el {f_cese_val} (Inicio: {f_inicio_val})</div>", unsafe_allow_html=True)
        else:
            st.markdown(f"<div class='profile-val'>Inicio de labores: {f_inicio_val}</div>", unsafe_allow_html=True)
        st.markdown("<div style='height: 6px;'></div>", unsafe_allow_html=True)
        
        st.markdown("<div class='profile-field'>DIRECCIÓN DE DOMICILIO:</div>", unsafe_allow_html=True)
        if link_domicilio.startswith("http"):
            st.markdown(f"<div class='profile-val'>{direccion_val} — <a href='{link_domicilio}' target='_blank' style='color:#EC3237; text-decoration:none; font-weight:700;'> Ver en Google Maps </a></div>", unsafe_allow_html=True)
        else:
            st.markdown(f"<div class='profile-val'>{direccion_val}</div>", unsafe_allow_html=True)

        st.markdown("<div class='profile-field'>CONTACTO DE EMERGENCIA:</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='profile-val'>{c_emergencia} ({num_emergencia})</div>", unsafe_allow_html=True)

def renderizar_calendario_colaborador(nombre_colab, anio, mes):
    cal = calendar.Calendar(firstweekday=0)
    mes_dias = cal.monthdayscalendar(anio, mes)

    df_asist = st.session_state.asistencia.copy()
    if not df_asist.empty:
        df_asist = df_asist[df_asist["nombre"] == nombre_colab]

    # Solicitudes de permiso/recovery del colaborador.
    # Se muestran las solicitudes Pendientes y Aprobadas; las Rechazadas no se pintan.
    df_sol_colab = pd.DataFrame()
    if "solicitudes" in st.session_state and not st.session_state.solicitudes.empty:
        df_sol_colab = st.session_state.solicitudes.copy()
        if "nombre" in df_sol_colab.columns:
            df_sol_colab = df_sol_colab[df_sol_colab["nombre"].astype(str) == str(nombre_colab)]
        if "estado" in df_sol_colab.columns:
            df_sol_colab = df_sol_colab[df_sol_colab["estado"].astype(str).isin(["Pendiente", "Aprobado"])]

    permisos = {}
    recuperaciones = {}
    if not df_sol_colab.empty:
        for _, sol in df_sol_colab.iterrows():
            if str(sol.get("tipo_solicitud", "")).strip() != "Permiso Laboral":
                continue

            fecha_perm = parsear_fecha_segura(sol.get("fecha_permiso", ""))
            if fecha_perm and fecha_perm.month == mes and fecha_perm.year == anio:
                permisos[fecha_perm] = str(sol.get("estado", "Pendiente"))

            fecha_rec = parsear_fecha_segura(sol.get("fecha_recuperacion", ""))
            if fecha_rec and fecha_rec.month == mes and fecha_rec.year == anio:
                recuperaciones[fecha_rec] = str(sol.get("estado", "Pendiente"))

    # --- NUEVO: Permisos de Salud (a recuperar) registrados en el módulo de Vacaciones ---
    permisos_salud = {}
    recuperaciones_salud = {}
    if "vacaciones" in st.session_state and not st.session_state.vacaciones.empty:
        df_vac_colab = st.session_state.vacaciones[
            (st.session_state.vacaciones["nombre"].astype(str) == str(nombre_colab)) &
            (st.session_state.vacaciones["tipo"] == "Permiso de Salud (a recuperar)")
        ]
        for _, vac_row in df_vac_colab.iterrows():
            f_ini_ps = parsear_fecha_segura(vac_row.get("fecha_inicio", ""))
            f_fin_ps = parsear_fecha_segura(vac_row.get("fecha_fin", ""))
            estado_rec_ps = str(vac_row.get("estado_recuperacion", "Pendiente")) or "Pendiente"
            if f_ini_ps and f_fin_ps:
                d_iter = f_ini_ps
                while d_iter <= f_fin_ps:
                    if d_iter.month == mes and d_iter.year == anio:
                        permisos_salud[d_iter] = estado_rec_ps
                    d_iter += timedelta(days=1)

            f_rec_ps = parsear_fecha_segura(vac_row.get("fecha_recuperacion", ""))
            if f_rec_ps and f_rec_ps.month == mes and f_rec_ps.year == anio:
                recuperaciones_salud[f_rec_ps] = estado_rec_ps

    # --- NUEVO: Domingos trabajados voluntariamente (marcados en Terminal de Asistencia) ---
    domingos_voluntarios = set()
    if not df_asist.empty:
        df_dom_vol = df_asist[df_asist["observacion"].astype(str).str.contains("TRABAJO VOLUNTARIO EN DOMINGO", case=False, na=False)]
        for _, r_dv in df_dom_vol.iterrows():
            f_dv = parsear_fecha_segura(r_dv.get("fecha", ""))
            if f_dv and f_dv.month == mes and f_dv.year == anio:
                domingos_voluntarios.add(f_dv)

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
            <span> </span> <span>{nombre_colab}</span>
        </div>
        <table class='cal-table'>
            <thead>
                <tr>
                    <th>Lun</th><th>Mar</th><th>Mié</th><th>Jue</th>
                    <th>Vie</th><th>Sáb</th><th>Dom</th>
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

                # 1. Recuperación de Permiso de Salud: máxima prioridad, incluso si cae domingo.
                if fecha_dia in recuperaciones_salud:
                    estado_rec_s = recuperaciones_salud[fecha_dia]
                    txt_rec_s = "🩺 Recup. Salud ✓" if estado_rec_s == "Recuperado" else "🩺 Recup. Salud"
                    html += f"<td class='bg-recuperacion-salud'><span class='cal-day-num'>{d}</span><span class='cal-sub'>{txt_rec_s}</span></td>"

                # 2. Permiso de Salud (día del permiso en sí).
                elif fecha_dia in permisos_salud:
                    html += f"<td class='bg-permiso-salud'><span class='cal-day-num'>{d}</span><span class='cal-sub'>🩺 Permiso Salud</span></td>"

                # 3. Recuperación de Permiso Laboral: tiene prioridad incluso si cae domingo.
                elif fecha_dia in recuperaciones:
                    estado_rec = recuperaciones[fecha_dia]
                    txt_rec = "↻ Recuperación" if estado_rec == "Aprobado" else "↻ Recup. solicitada"
                    html += f"<td class='bg-recuperacion'><span class='cal-day-num'>{d}</span><span class='cal-sub'>{txt_rec}</span></td>"

                # 4. Permiso Laboral: tiene prioridad sobre Falta/Descanso.
                elif fecha_dia in permisos:
                    estado_perm = permisos[fecha_dia]
                    if estado_perm == "Aprobado":
                        html += f"<td class='bg-permiso'><span class='cal-day-num'>{d}</span><span class='cal-sub'>✓ Permiso</span></td>"
                    else:
                        html += f"<td class='bg-permiso-pendiente'><span class='cal-day-num'>{d}</span><span class='cal-sub'>⌛ Permiso</span></td>"

                # 5. Domingo trabajado voluntariamente (día de descanso, por elección propia).
                elif i == 6 and fecha_dia in domingos_voluntarios:
                    html += f"<td class='bg-domingo-voluntario'><span class='cal-day-num'>{d}</span><span class='cal-sub'>☀ Dom. Voluntario</span></td>"

                # 6. Asistencia real.
                elif i == 6:
                    html += f"<td class='bg-descanso'><span class='cal-day-num'>{d}</span><span class='cal-sub'>Descanso</span></td>"
                else:
                    if not df_asist.empty:
                        df_dia = df_asist[df_asist["fecha"].astype(str) == f_str]
                    else:
                        df_dia = pd.DataFrame()

                    if not df_dia.empty:
                        tiene_extra = (
                            (df_dia["es_extra"].astype(str) == "SI").any()
                            or df_dia["observacion"].astype(str).str.contains("TURNO EXTRA", case=False, na=False).any()
                        )
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
st.sidebar.markdown(f'<div style="text-align:center; padding: 8px 0 14px 0;">{logo_tag_app39(58)}</div>', unsafe_allow_html=True)
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
    menu = ["Dashboard General", "Centro de Alertas", "Analítica (BI)", "Gestión Colaboradores", "Onboarding / Offboarding", "Gestión de Vacaciones", "Boletas de Pago", "Solicitudes y Permisos", "Historial de Descuadres", "Incidencias y Daños", "Botellas Fiadas", "Historial de Asistencias", "Auditoría y Configuración"]
else:
    menu = ["Marcar Asistencia", "Registrar Descuadre", "Registrar Incidencia", "Botellas Fiadas", "Mi Ficha Técnica", "Mis Vacaciones", "Solicitar Permiso / Adelanto", "Mi Dashboard Mensual"]

choice = st.sidebar.radio("Navegación", menu)

st.sidebar.markdown("<br><br>", unsafe_allow_html=True)
st.sidebar.markdown('<div class="btn-logout">', unsafe_allow_html=True)
if st.sidebar.button("Cerrar Sesión", use_container_width=True):
    registrar_auditoria("Cierre de Sesión", "Usuarios", f"{user_actual} cerró sesión.")
    st.session_state.usuario_login = None
    st.session_state.login_auditado = False
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
            
            es_turno_extra = st.checkbox("Marcación Fuera de Horario / Turno Adicional")
            
            motivo_extra = ""
            if es_turno_extra:
                motivo_extra = st.selectbox(
                    "Motivo del Turno Adicional",
                    ["Cubrir Turno Mañana (Apoyo)", "Cubrir Turno Tarde (Apoyo)", "Permanencia Extra / Post-Turno", "Trabajo Voluntario en Domingo (Día de Descanso)", "Otro Sustento"]
                )
                if motivo_extra == "Trabajo Voluntario en Domingo (Día de Descanso)":
                    st.caption("☀ Se registrará como día de descanso trabajado por decisión propia. En tu boleta aparecerá como un día adicional pagado, distinto a tus faltas o tardanzas.")
            
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
                st.markdown(f"**Horas Trabajadas Hoy:** {formatear_horas_minutos(mins_tot)}")
                st.markdown(f"**Jornada Completa (5h 45m):** {formatear_horas_minutos(mins_lab)} / 5h 45m")
                if mins_ext > 0:
                    st.markdown(f"**Horas Extras Generadas:** <span style='color:#00A959; font-weight:700;'>{formatear_horas_minutos(mins_ext)}</span>", unsafe_allow_html=True)
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

elif choice == "Registrar Incidencia":
    st.markdown(f"""
        <div class="market-header">
            <h1>Registro de Incidencias y Daños</h1>
            <p>Billetes falsos, botellas rotas u otros daños — responsable: <b>{user_actual}</b></p>
        </div>
    """, unsafe_allow_html=True)

    st.caption("Registra aquí cualquier billete falso recibido, botella rota (gaseosa o cerveza), o cualquier otro daño (silla, pared, vitrina, etc.). El valor de reparación queda visible para administración.")

    tipo_inc_sel = st.selectbox(
        "Tipo de Incidencia",
        ["Billete Falso", "Botella Rota (Gaseosa)", "Botella Rota (Cerveza)", "Otro Daño (Silla, Pared, Vitrina, etc.)"],
        key="inc_tipo_sel"
    )

    with st.form("form_incidencia_user", clear_on_submit=True):
        f_inc = st.date_input("Fecha del Incidente", obtener_ahora_peru(), key="inc_fecha")

        if tipo_inc_sel == "Billete Falso":
            valor_inc = st.number_input("Valor del Billete Falso (S/.)", min_value=0.0, step=1.0, format="%.2f", key="inc_valor_billete")
            detalle_inc = st.text_area("Detalle (denominación, cómo se detectó, etc.)", key="inc_detalle_billete")
        elif "Botella Rota" in tipo_inc_sel:
            cantidad_bot_rota = st.number_input("Cantidad de Botellas Rotas", min_value=1, step=1, key="inc_cantidad_botella")
            valor_unit_bot = st.number_input("Valor de Reposición por Botella (S/.)", min_value=0.0, step=0.50, format="%.2f", key="inc_valor_unit_botella")
            valor_inc = cantidad_bot_rota * valor_unit_bot
            detalle_inc = st.text_area("Detalle (cómo ocurrió)", key="inc_detalle_botella")
            st.caption(f"Valor total estimado de reparación: **S/. {valor_inc:.2f}**")
        else:
            detalle_inc = st.text_area("Describe el daño (ej: 'Rompió la silla del área de mesas', 'Golpeó la pared del almacén')", key="inc_detalle_otro")
            valor_inc = st.number_input("Valor Estimado de Reparación (S/.)", min_value=0.0, step=1.0, format="%.2f", key="inc_valor_otro")

        if st.form_submit_button("Guardar Incidencia", use_container_width=True):
            f_reg_inc = obtener_ahora_peru().strftime("%Y-%m-%d %H:%M:%S")
            id_inc_nuevo = f"INC-{int(time.time()*1000)}"

            guardado_ok = guardar_incidencia_gsheets(
                id_inc_nuevo, dni_actual, user_actual, f_inc, tipo_inc_sel, detalle_inc,
                valor_inc, f_reg_inc, user_actual, "Pendiente"
            )
            if guardado_ok:
                nueva_fila_inc = {
                    "id_incidencia": id_inc_nuevo, "dni": dni_actual, "nombre": user_actual,
                    "fecha": str(f_inc), "tipo_incidencia": tipo_inc_sel, "detalle": detalle_inc,
                    "valor_reparacion": valor_inc, "fecha_registro": f_reg_inc,
                    "registrado_por": user_actual, "estado": "Pendiente"
                }
                st.session_state.incidencias = pd.concat([pd.DataFrame([nueva_fila_inc]), st.session_state.incidencias], ignore_index=True)
                registrar_auditoria("Registrar Incidencia", "Incidencias", f"{user_actual}: {tipo_inc_sel} — S/. {valor_inc:.2f}")
                st.toast("Incidencia registrada correctamente")
                time.sleep(0.3)
                st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("##### Mis Incidencias Registradas")
    if not st.session_state.incidencias.empty:
        mis_inc = st.session_state.incidencias[st.session_state.incidencias["nombre"] == user_actual]
        if not mis_inc.empty:
            st.dataframe(
                mis_inc[["fecha", "tipo_incidencia", "detalle", "valor_reparacion", "estado"]].sort_values("fecha", ascending=False),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("Aún no tienes incidencias registradas.")
    else:
        st.info("Aún no tienes incidencias registradas.")

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

    t_sol, t_hist = st.tabs(["Nueva Solicitud", "Mi Historial de Solicitudes"])

    with t_sol:
        tipo_sol = st.selectbox("Tipo de Solicitud", ["Permiso Laboral", "Adelanto de Sueldo", "Trabajar Domingo (Descanso)"])

        hoy_peru = obtener_ahora_peru().date()
        fecha_minima_permiso = hoy_peru + timedelta(days=7)
        f_permiso_val = ""
        monto_adel_val = 0.0
        requiere_recuperacion = False
        fecha_recuperacion_sel = None

        if tipo_sol == "Permiso Laboral":
            st.info("**Regla de Permisos:** Toda solicitud de permiso debe realizarse con un mínimo de **7 días de anticipación**.")
            f_permiso_sel = st.date_input("Fecha solicitada para el permiso", value=fecha_minima_permiso, min_value=fecha_minima_permiso, key="fecha_permiso_nueva")
            f_permiso_val = str(f_permiso_sel)

            st.markdown("##### Recuperación del día")
            requiere_recuperacion = st.checkbox("¿Deseas recuperar el día del permiso?", value=False, key="requiere_recuperacion_nueva")
            if requiere_recuperacion:
                st.success("Selecciona el día en que deseas recuperar el permiso. **Los domingos también están habilitados.**")
                fecha_min_rec = f_permiso_sel + timedelta(days=1)
                fecha_recuperacion_sel = st.date_input("Día a recuperar", value=fecha_min_rec, min_value=fecha_min_rec, key="fecha_recuperacion_nueva", help="Puedes seleccionar cualquier fecha, incluido domingo.")
                dias_semana = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
                st.caption(f"Permiso: **{f_permiso_sel.strftime('%d/%m/%Y')}** | Día a recuperar: **{fecha_recuperacion_sel.strftime('%d/%m/%Y')} ({dias_semana[fecha_recuperacion_sel.weekday()]})**")

            with st.form("form_nuevo_permiso", clear_on_submit=True):
                motivo_sol = st.text_area("Motivo o Justificación detallada", placeholder="Escribe aquí el motivo de tu solicitud...")
                enviar_solicitud = st.form_submit_button("Enviar Solicitud", use_container_width=True)

        elif tipo_sol == "Trabajar Domingo (Descanso)":
            st.info("**Trabajar tu día de descanso:** Si tu descanso semanal es el domingo y deseas trabajar ese día, solicita autorización previa aquí. Una vez aprobada, podrás marcar tu asistencia ese domingo y en tu boleta se reflejará claramente como un día adicional trabajado (no como una falta ni un domingo normal de descanso).")

            proximos_domingos = []
            cursor_dom = hoy_peru
            while len(proximos_domingos) < 8:
                cursor_dom += timedelta(days=1)
                if cursor_dom.weekday() == 6:
                    proximos_domingos.append(cursor_dom)

            domingo_sel = st.selectbox(
                "Domingo que deseas trabajar",
                proximos_domingos,
                format_func=lambda d: d.strftime("%d/%m/%Y"),
                key="domingo_trabajo_sel"
            )
            f_permiso_val = str(domingo_sel)

            with st.form("form_domingo_trabajo", clear_on_submit=True):
                motivo_sol = st.text_area("Motivo o Justificación (opcional)", placeholder="Ej. Necesito cubrir turno, quiero generar ingreso adicional, etc.")
                enviar_solicitud = st.form_submit_button("Enviar Solicitud", use_container_width=True)
        else:
            st.info("**Adelanto de Sueldo:** Ingresa el monto total a solicitar y la justificación.")
            with st.form("form_nuevo_adelanto", clear_on_submit=True):
                monto_adel_val = st.number_input("Monto a Solicitar (S/.)", min_value=10.0, step=10.0, format="%.2f")
                f_permiso_val = str(hoy_peru)
                motivo_sol = st.text_area("Motivo o Justificación detallada", placeholder="Escribe aquí el motivo de tu solicitud...")
                enviar_solicitud = st.form_submit_button("Enviar Solicitud", use_container_width=True)

        if enviar_solicitud:
                if tipo_sol != "Trabajar Domingo (Descanso)" and not motivo_sol.strip():
                    st.error("Por favor ingresa un motivo para tu solicitud.")
                else:
                    if tipo_sol == "Permiso Laboral":
                        diff_dias = (f_permiso_sel - hoy_peru).days
                        if diff_dias < 7:
                            st.error("Los permisos requieren como mínimo 7 días de anticipación.")
                            st.stop()

                        if requiere_recuperacion and fecha_recuperacion_sel is not None:
                            if fecha_recuperacion_sel == f_permiso_sel:
                                st.error("La fecha de recuperación debe ser diferente a la fecha del permiso.")
                                st.stop()
                            fecha_recuperacion_val = str(fecha_recuperacion_sel)
                        else:
                            fecha_recuperacion_val = ""
                    else:
                        fecha_recuperacion_val = ""

                    if tipo_sol == "Trabajar Domingo (Descanso)":
                        ya_existe_dom = False
                        if not st.session_state.solicitudes.empty:
                            df_check_dom = st.session_state.solicitudes[
                                (st.session_state.solicitudes["dni"].astype(str) == str(dni_actual)) &
                                (st.session_state.solicitudes["tipo_solicitud"] == "Trabajar Domingo (Descanso)") &
                                (st.session_state.solicitudes["fecha_permiso"].astype(str) == f_permiso_val) &
                                (st.session_state.solicitudes["estado"].isin(["Pendiente", "Aprobado"]))
                            ]
                            ya_existe_dom = not df_check_dom.empty
                        if ya_existe_dom:
                            st.warning("Ya tienes una solicitud pendiente o aprobada para trabajar ese domingo.")
                            st.stop()
                        motivo_sol = motivo_sol.strip() if motivo_sol else "Solicita trabajar su día de descanso semanal (domingo)."

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
                        "respuesta_admin": "",
                        "requiere_recuperacion": "Sí" if (tipo_sol == "Permiso Laboral" and requiere_recuperacion) else "No",
                        "fecha_recuperacion": fecha_recuperacion_val
                    }

                    st.session_state.solicitudes = pd.concat([pd.DataFrame([nueva_peticion]), st.session_state.solicitudes], ignore_index=True)
                    guardar_solicitud_gsheets(
                        id_nuevo, f_reg_now, dni_actual, user_actual, tipo_sol,
                        f_permiso_val, monto_adel_val, motivo_sol.strip(),
                        requiere_recuperacion=("Sí" if (tipo_sol == "Permiso Laboral" and requiere_recuperacion) else "No"),
                        fecha_recuperacion=fecha_recuperacion_val
                    )
                    st.success("Solicitud enviada con éxito. Un administrador la revisará pronto.")
                    time.sleep(0.5)
                    st.rerun()

    with t_hist:
        st.markdown("<h4 style='font-size:1rem; color:#111827; margin-bottom:12px;'>Historial de Solicitudes</h4>", unsafe_allow_html=True)
        
        df_mis_sol = st.session_state.solicitudes[st.session_state.solicitudes["dni"].astype(str) == str(dni_actual)].copy() if not st.session_state.solicitudes.empty else pd.DataFrame()

        if not df_mis_sol.empty:
            for _, r_sol in df_mis_sol.iterrows():
                est = r_sol["estado"]
                badge_c = "#EAB308" if est == "Pendiente" else ("#00A959" if est == "Aprobado" else "#EC3237")

                if r_sol['tipo_solicitud'] == "Permiso Laboral":
                    det_txt = f"**Fecha Permiso:** {r_sol['fecha_permiso']}"
                elif r_sol['tipo_solicitud'] == "Trabajar Domingo (Descanso)":
                    det_txt = f"**Domingo a Trabajar:** {r_sol['fecha_permiso']}"
                else:
                    det_txt = f"**Monto Solicitado:** S/. {float(r_sol['monto_adelanto']):.2f}"

                with st.expander(f" {r_sol['tipo_solicitud']} — {r_sol['fecha_registro']} [{est}]"):
                    st.markdown(f"<span style='background-color:{badge_c}; color:#fff; padding:3px 10px; border-radius:12px; font-size:0.75rem; font-weight:700;'>{est}</span>", unsafe_allow_html=True)
                    st.markdown(f"<br>{det_txt}", unsafe_allow_html=True)
                    st.markdown(f"**Motivo:** {r_sol['motivo']}")
                    if r_sol['tipo_solicitud'] == "Permiso Laboral":
                        _req_rec = str(r_sol.get("requiere_recuperacion", "No")).strip().lower()
                        _f_rec = str(r_sol.get("fecha_recuperacion", "")).strip()
                        if _req_rec in ["sí", "si", "yes", "true", "1"] and _f_rec:
                            st.markdown(f"**Recuperación:** {_f_rec}")
                    if r_sol['tipo_solicitud'] == "Trabajar Domingo (Descanso)" and est == "Aprobado":
                        st.success("Autorizado. Podrás marcar tu asistencia ese domingo desde 'Marcar Asistencia'.")
                    if str(r_sol.get('respuesta_admin', '')).strip():
                        st.markdown(f"**Respuesta Admin:** {r_sol['respuesta_admin']}")
        else:
            st.info("No registras solicitudes en tu historial.")

elif choice == "Mi Dashboard Mensual":
    ahora_dash = obtener_ahora_peru()

    NOMBRES_MESES_DASH = [
        "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
        "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
    ]

    st.markdown(f"""
        <div class="market-header">
            <h1>Rendimiento Mensual</h1>
            <p>Resumen del período seleccionado para <b>{user_actual}</b></p>
        </div>
    """, unsafe_allow_html=True)

    col_mes_dash, col_anio_dash = st.columns(2)
    mes_dash_sel = col_mes_dash.selectbox(
        "Seleccionar Mes",
        list(range(1, 13)),
        index=ahora_dash.month - 1,
        format_func=lambda x: NOMBRES_MESES_DASH[x - 1],
        key="mes_mi_dashboard"
    )
    anio_dash_sel = col_anio_dash.number_input(
        "Seleccionar Año",
        min_value=2024,
        max_value=2030,
        value=ahora_dash.year,
        step=1,
        key="anio_mi_dashboard"
    )

    periodo_dash = f"{NOMBRES_MESES_DASH[mes_dash_sel - 1]} {int(anio_dash_sel)}"
    st.caption(
        f"Indicadores correspondientes únicamente a **{periodo_dash}**. "
        "Las horas extras y demás métricas no acumulan meses anteriores."
    )

    df_mis_desc = pd.DataFrame()
    df_mis_asist = pd.DataFrame()

    if not st.session_state.descuadres.empty:
        df_mis_desc = st.session_state.descuadres[
            st.session_state.descuadres["dni"].astype(str) == str(dni_actual)
        ].copy()

        if not df_mis_desc.empty:
            df_mis_desc["fecha_dt"] = pd.to_datetime(df_mis_desc["fecha"], errors="coerce")
            df_mis_desc = df_mis_desc[
                (df_mis_desc["fecha_dt"].dt.month == mes_dash_sel) &
                (df_mis_desc["fecha_dt"].dt.year == int(anio_dash_sel))
            ]

    if not st.session_state.asistencia.empty:
        df_mis_asist = st.session_state.asistencia[
            st.session_state.asistencia["dni"].astype(str) == str(dni_actual)
        ].copy()

        if not df_mis_asist.empty:
            df_mis_asist["fecha_dt"] = pd.to_datetime(df_mis_asist["fecha"], errors="coerce")
            df_mis_asist = df_mis_asist[
                (df_mis_asist["fecha_dt"].dt.month == mes_dash_sel) &
                (df_mis_asist["fecha_dt"].dt.year == int(anio_dash_sel))
            ]

    monto_total = (
        pd.to_numeric(df_mis_desc["monto"], errors="coerce").sum()
        if not df_mis_desc.empty else 0.0
    )

    dias_trabajados = (
        df_mis_asist["fecha"].nunique()
        if not df_mis_asist.empty else 0
    )

    minutos_extras_mes = 0
    if not df_mis_asist.empty:
        df_mis_asist["dt"] = pd.to_datetime(df_mis_asist["fecha_hora"], errors="coerce")
        for _, grupo_dia in df_mis_asist.groupby("fecha"):
            _, mins_e, _, _ = calcular_jornada_y_horas_extras(grupo_dia)
            minutos_extras_mes += mins_e

    metricas_p = calcular_metricas_puntualidad(df_mis_asist, user_actual)

    k1, k2, k3, k4 = st.columns(4)

    with k1:
        st.markdown(f"""
            <div class="info-card">
                <div class="info-label">Días Trabajados</div>
                <div class="info-value">{dias_trabajados}</div>
            </div>
        """, unsafe_allow_html=True)

    with k2:
        st.markdown(f"""
            <div class="info-card">
                <div class="info-label">Horas Extras Acumuladas</div>
                <div class="info-value" style="color: #00A959;">{formatear_horas_minutos(minutos_extras_mes)}</div>
            </div>
        """, unsafe_allow_html=True)

    with k3:
        st.markdown(f"""
            <div class="info-card">
                <div class="info-label">Minutos Tardanza</div>
                <div class="info-value" style="color: {'#111827' if metricas_p['minutos_acumulados'] == 0 else '#EC3237'};">{metricas_p['minutos_acumulados']} m</div>
            </div>
        """, unsafe_allow_html=True)

    with k4:
        st.markdown(f"""
            <div class="info-card">
                <div class="info-label">Balance Descuadres</div>
                <div class="info-value" style="color: {'#00A959' if monto_total >= 0 else '#EC3237'};">S/. {monto_total:.2f}</div>
            </div>
        """, unsafe_allow_html=True)

    st.markdown(
        f"<h4 style='font-size:1rem; color:#111827; margin-top:10px;'>"
        f"Historial Personal — {periodo_dash}</h4>",
        unsafe_allow_html=True
    )

    if not df_mis_desc.empty:
        st.dataframe(
            df_mis_desc[["fecha", "tipo", "monto", "observacion"]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "monto": st.column_config.NumberColumn("MONTO", format="S/. %.2f")
            }
        )
    else:
        st.info(f"Sin registros de descuadres en {periodo_dash}.")

# -------------------- MÓDULOS ADMIN --------------------

elif choice == "Dashboard General":
    st.markdown("""
        <div class="market-header">
            <h1>Panel de Control General</h1>
            <p>Vista ejecutiva de la operación, tardanzas y horas extras en tiempo real</p>
        </div>
    """, unsafe_allow_html=True)

    st.markdown("##### Calendarios Mensuales de Asistencia")
    col_mes, col_anio = st.columns(2)
    
    ahora_p = obtener_ahora_peru()
    NOMBRES_MESES = [
        "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
        "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
    ]
    mes_sel = col_mes.selectbox("Mes", list(range(1, 13)), index=ahora_p.month - 1, format_func=lambda x: NOMBRES_MESES[x-1])
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
            <div class="legend-item">
                <span class="legend-badge" style="background-color: #ede9fe; border: 1px solid #c4b5fd;"></span>
                <span>Permiso Aprobado</span>
            </div>
            <div class="legend-item">
                <span class="legend-badge" style="background-color: #fef3c7; border: 1px solid #fcd34d;"></span>
                <span>Permiso Pendiente</span>
            </div>
            <div class="legend-item">
                <span class="legend-badge" style="background-color: #cffafe; border: 1px solid #67e8f9;"></span>
                <span>Recuperación</span>
            </div>
            <div class="legend-item">
                <span class="legend-badge" style="background-color: #fce7f3; border: 1px solid #f9a8d4;"></span>
                <span>Permiso de Salud</span>
            </div>
            <div class="legend-item">
                <span class="legend-badge" style="background-color: #e0e7ff; border: 1px solid #c7d2fe;"></span>
                <span>Recuperación de Salud (Domingo)</span>
            </div>
            <div class="legend-item">
                <span class="legend-badge" style="background-color: #ccfbf1; border: 1px solid #5eead4;"></span>
                <span>Domingo Trabajado Voluntariamente</span>
            </div>
        </div>
    """, unsafe_allow_html=True)

    st.markdown("##### Filtros de Consulta")
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
        with st.expander("Ver Calendarios de Asistencia por Trabajador", expanded=True):
            cols_cal = st.columns(2)
            for idx, c_nom in enumerate(colabs_a_renderizar):
                with cols_cal[idx % 2]:
                    html_cal = renderizar_calendario_colaborador(c_nom, int(anio_sel), int(mes_sel))
                    st.markdown(html_cal, unsafe_allow_html=True)
    else:
        st.info("No hay colaboradores con rol operativo activos para la fecha consultada.")

    st.markdown("---")

    # --- CÁLCULO DE HORAS EXTRAS MENSUALES POR TRABAJADOR ---
    st.markdown(f"##### Horas Extras Mensuales del Período ({NOMBRES_MESES[mes_sel-1]} {int(anio_sel)})")
    
    df_asist_mes = st.session_state.asistencia.copy()
    horas_extras_mensuales = {}

    if not df_asist_mes.empty:
        df_asist_mes["fecha_dt"] = pd.to_datetime(df_asist_mes["fecha"], errors="coerce")
        df_asist_mes = df_asist_mes[
            (df_asist_mes["fecha_dt"].dt.month == mes_sel) & 
            (df_asist_mes["fecha_dt"].dt.year == anio_sel)
        ]

        colabs_eval_mes = colaboradores_ops if colab_dash == "Todos" else ([colab_dash] if colab_dash in colaboradores_ops else [])

        for nom_col in colabs_eval_mes:
            df_col_mes = df_asist_mes[df_asist_mes["nombre"] == nom_col].copy()
            mins_extras_colab = 0
            if not df_col_mes.empty:
                df_col_mes["dt"] = pd.to_datetime(df_col_mes["fecha_hora"])
                for _, grupo_dia in df_col_mes.groupby("fecha"):
                    _, mins_e, _, _ = calcular_jornada_y_horas_extras(grupo_dia)
                    mins_extras_colab += mins_e
            horas_extras_mensuales[nom_col] = mins_extras_colab

    if horas_extras_mensuales:
        cols_he = st.columns(min(len(horas_extras_mensuales), 4))
        for idx_he, (nom_he, mins_he) in enumerate(horas_extras_mensuales.items()):
            col_target = cols_he[idx_he % min(len(horas_extras_mensuales), 4)]
            with col_target:
                color_he = "#00A959" if mins_he > 0 else "#6B7280"
                st.markdown(f'''
                    <div class="info-card">
                        <div class="info-label">{nom_he}</div>
                        <div class="info-value" style="color: {color_he};">{formatear_horas_minutos(mins_he)}</div>
                    </div>
                ''', unsafe_allow_html=True)
    else:
        st.info(f"No hay registros de horas extras para el mes de {NOMBRES_MESES[mes_sel-1]} {int(anio_sel)}.")

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
        st.markdown("<h4 style='font-size:1rem; color:#111827; margin-bottom:15px;'> Control Operativo y Horas Extras por Colaborador</h4>", unsafe_allow_html=True)

        for nombre_col, datos in fichas_colaboradores.items():
            with st.expander(f" {nombre_col} — {datos['estado']} | Total Trab.: {datos['tiempo_total_str']} | Extras: {datos['horas_extras_str']}", expanded=True):
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

    tab_fichas, tab_nuevo, tab_directorio = st.tabs(["Fichas Técnicas", "Registrar Colaborador", "Directorio General"])

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

            f3b, f4b = st.columns(2)
            en_planilla_in = f3b.selectbox("¿Está en Planilla?", ["Sí", "No"], index=0, help="Marca 'No' para trabajadores jóvenes/informales que no están en planilla formal. No se les calculará beneficio vacacional.")

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

            st.caption("Nota: La imagen debe guardarse en la carpeta `fotos/` del repositorio como: `<DNI>.png` o `<DNI>.jpg`")

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
                        "fecha_cese": "",
                        "en_planilla": en_planilla_in
                    }
                    st.session_state.empleados = pd.concat([st.session_state.empleados, pd.DataFrame([nuevo_e])], ignore_index=True)
                    guardar_colaborador_gsheets(
                        dni_in, nom_in, cargo_in, "Activo", clave_in, rol_in, 
                        dir_in, tel_in, fnac_str, foto_nombre,
                        c_emerg_in.strip(), num_emerg_in.strip(), link_maps_in.strip(),
                        finicio_str, "", en_planilla_in
                    )
                    registrar_auditoria("Crear Colaborador", "Colaboradores", f"{nom_in.strip()} (DNI {dni_in}) — cargo: {cargo_in}")
                    crear_checklist_onboarding(str(dni_in).strip(), nom_in.strip())
                    st.toast("Colaborador y Ficha Técnica registrados")
                    time.sleep(0.3)
                    st.rerun()

    with tab_directorio:
        st.markdown("<h4 style='margin:0; font-size:0.95rem; color:#111827; margin-bottom:12px;'>Directorio Consolidado</h4>", unsafe_allow_html=True)
        cols_mostrar = [
            c for c in ["dni", "nombre", "cargo", "rol", "telefono", "direccion", "fecha_nacimiento", "contacto_emergencia", "numero_emergencia", "estado", "fecha_inicio", "fecha_cese", "en_planilla"] 
            if c in st.session_state.empleados.columns
        ]
        st.dataframe(
            st.session_state.empleados[cols_mostrar],
            use_container_width=True,
            hide_index=True
        )

        if rol_actual == "admin" and not st.session_state.empleados.empty:
            st.markdown("<br>", unsafe_allow_html=True)
            with st.expander("Actualizar Estado de Planilla (REMYPE)"):
                st.caption("Los trabajadores marcados como 'No' (jóvenes/informales sin planilla) no acumulan beneficio vacacional en el sistema.")
                colabs_todos_ep = st.session_state.empleados["nombre"].tolist()
                if colabs_todos_ep:
                    colab_ep_sel = st.selectbox("Seleccionar colaborador", colabs_todos_ep, key="ep_sel")
                    fila_ep = st.session_state.empleados[st.session_state.empleados["nombre"] == colab_ep_sel].iloc[0]
                    valor_actual_ep = fila_ep.get("en_planilla", "Sí") or "Sí"
                    nuevo_ep = st.selectbox("¿Está en Planilla?", ["Sí", "No"], index=0 if valor_actual_ep == "Sí" else 1, key="ep_valor")
                    if st.button("Guardar Estado de Planilla", use_container_width=True, key="ep_btn"):
                        idx_ep = st.session_state.empleados[st.session_state.empleados["nombre"] == colab_ep_sel].index
                        st.session_state.empleados.loc[idx_ep, "en_planilla"] = nuevo_ep
                        actualizar_hoja_completa("Colaboradores", st.session_state.empleados)
                        registrar_auditoria("Actualizar Estado de Planilla", "Colaboradores", f"{colab_ep_sel} → en_planilla={nuevo_ep}")
                        st.toast(f"Estado de planilla de {colab_ep_sel} actualizado a '{nuevo_ep}'")
                        time.sleep(0.3)
                        st.rerun()

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
                                dni_baja_ep = str(st.session_state.empleados.loc[idx[0], "dni"])
                                st.session_state.empleados.loc[idx, "estado"] = "Desactivado"
                                st.session_state.empleados.loc[idx, "fecha_cese"] = str(f_cese_input)
                                actualizar_hoja_completa("Colaboradores", st.session_state.empleados)
                                registrar_auditoria("Dar de Baja Colaborador", "Colaboradores", f"{colab_a_desactivar} — cese: {f_cese_input}")
                                crear_checklist_offboarding(dni_baja_ep, colab_a_desactivar)
                                st.toast(f"Colaborador {colab_a_desactivar} desactivado correctamente")
                                time.sleep(0.3)
                                st.rerun()
                        else:
                            st.warning("Marca la casilla de confirmación antes de dar de baja.")
                else:
                    st.info("No hay colaboradores activos para dar de baja.")

# --- MÓDULO NUEVO: BOLETAS DE PAGO & FERIADOS (SOLO ADMIN) ---
elif choice == "Boletas de Pago":
    st.markdown("""
        <div class="market-header">
            <h1>Generación de Boletas de Pago</h1>
            <p>Emisión, cálculo automático y descarga de boletas de pago para colaboradores</p>
        </div>
    """, unsafe_allow_html=True)

    tab_boleta, tab_feriados = st.tabs(["Generar Boleta de Pago", "Gestión de Feriados"])

    with tab_feriados:
        st.markdown("<h4 style='font-size:1rem; color:#111827; margin-bottom:12px;'>Días Feriados Registrados</h4>", unsafe_allow_html=True)
        st.caption("Los feriados trabajados de Lunes a Sábado se pagan con recargo adicional (17.66 / día sobre base S/. 530.00). Los feriados en domingo no aplican por ser día de descanso.")
        
        c_f1, c_f2 = st.columns([1, 2])
        with c_f1:
            with st.form("form_nuevo_feriado", clear_on_submit=True):
                st.markdown("**Agregar Feriado**")
                f_feriado = st.date_input("Fecha del Feriado", value=obtener_ahora_peru().date())
                desc_feriado = st.text_input("Descripción / Evento", placeholder="Ej. Fiestas Patrias")
                if st.form_submit_button("Guardar Feriado", use_container_width=True):
                    if not desc_feriado.strip():
                        st.error("Ingresa una descripción para el feriado.")
                    else:
                        str_f_fer = str(f_feriado)
                        if not st.session_state.feriados.empty and str_f_fer in st.session_state.feriados["fecha"].astype(str).values:
                            st.warning("Esa fecha ya se encuentra registrada como feriado.")
                        else:
                            nuevo_f = {"fecha": str_f_fer, "descripcion": desc_feriado.strip()}
                            st.session_state.feriados = pd.concat([st.session_state.feriados, pd.DataFrame([nuevo_f])], ignore_index=True)
                            guardar_feriado_gsheets(str_f_fer, desc_feriado.strip())
                            st.toast("Feriado agregado con éxito")
                            time.sleep(0.3)
                            st.rerun()

        with c_f2:
            if not st.session_state.feriados.empty:
                df_fer_ord = st.session_state.feriados.sort_values("fecha").reset_index(drop=True)
                st.dataframe(df_fer_ord, use_container_width=True, hide_index=True)
            else:
                st.info("No hay feriados registrados.")

    with tab_boleta:
        st.markdown("<h4 style='font-size:1rem; color:#111827; margin-bottom:12px;'>Parámetros y Selección de Trabajador</h4>", unsafe_allow_html=True)
        
        b_c1, b_c2, b_c3 = st.columns([1.5, 1, 1])
        colabs_list = obtener_solo_colaboradores()
        
        if not colabs_list:
            st.warning("No hay colaboradores disponibles para emitir boletas.")
            st.stop()

        colab_b_sel = b_c1.selectbox("Colaborador", colabs_list, key="boleta_colab_sel")
        
        ahora_p_b = obtener_ahora_peru()
        NOMBRES_MESES_B = [
            "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
            "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
        ]
        mes_b_sel = b_c2.selectbox("Mes de Boleta", list(range(1, 13)), index=ahora_p_b.month - 1, format_func=lambda x: NOMBRES_MESES_B[x-1], key="boleta_mes_sel")
        anio_b_sel = b_c3.number_input("Año", min_value=2024, max_value=2030, value=ahora_p_b.year, key="boleta_anio_sel")

        row_trab = st.session_state.empleados[st.session_state.empleados["nombre"] == colab_b_sel]
        dni_b_val = str(row_trab.iloc[0]["dni"]) if not row_trab.empty and "dni" in row_trab.columns else "-"
        cargo_b_val = str(row_trab.iloc[0]["cargo"]) if not row_trab.empty and "cargo" in row_trab.columns else "-"
        finicio_b_val = str(row_trab.iloc[0]["fecha_inicio"]) if not row_trab.empty and "fecha_inicio" in row_trab.columns else "-"

        # --- RECOPILACIÓN Y CÁLCULOS AUTOMÁTICOS ---
        df_asist_b = st.session_state.asistencia.copy()
        dias_trabajados_cnt = 0
        hrs_extras_totales = 0.0
        feriados_trabajados_cnt = 0
        domingos_voluntarios_cnt = 0

        if not df_asist_b.empty:
            df_asist_b["fecha_dt"] = pd.to_datetime(df_asist_b["fecha"], errors="coerce")
            df_asist_user = df_asist_b[
                (df_asist_b["nombre"] == colab_b_sel) & 
                (df_asist_b["fecha_dt"].dt.month == mes_b_sel) & 
                (df_asist_b["fecha_dt"].dt.year == anio_b_sel)
            ]
            
            if not df_asist_user.empty:
                dias_trabajados_cnt = df_asist_user["fecha"].nunique()
                
                df_asist_user["dt"] = pd.to_datetime(df_asist_user["fecha_hora"])
                for f_dia, grupo_dia in df_asist_user.groupby("fecha"):
                    _, mins_e, _, _ = calcular_jornada_y_horas_extras(grupo_dia)
                    hrs_extras_totales += (mins_e / 60.0)

                    if not st.session_state.feriados.empty and str(f_dia) in st.session_state.feriados["fecha"].astype(str).values:
                        dt_f = pd.to_datetime(f_dia)
                        if dt_f.weekday() != 6:  # No es domingo
                            feriados_trabajados_cnt += 1

                    dt_dia_check = pd.to_datetime(f_dia)
                    if dt_dia_check.weekday() == 6 and grupo_dia["observacion"].astype(str).str.contains("TRABAJO VOLUNTARIO EN DOMINGO", case=False, na=False).any():
                        domingos_voluntarios_cnt += 1

        dias_faltas_cnt = max(0, 30 - dias_trabajados_cnt)

        # Buscar adelantos aprobados
        df_sol_b = st.session_state.solicitudes.copy()
        adelanto_sueldo_monto = 0.0
        if not df_sol_b.empty:
            df_sol_user = df_sol_b[
                (df_sol_b["nombre"] == colab_b_sel) & 
                (df_sol_b["tipo_solicitud"] == "Adelanto de Sueldo") & 
                (df_sol_b["estado"] == "Aprobado")
            ]
            if not df_sol_user.empty:
                df_sol_user["f_reg_dt"] = pd.to_datetime(df_sol_user["fecha_registro"], errors="coerce")
                df_sol_m = df_sol_user[
                    (df_sol_user["f_reg_dt"].dt.month == mes_b_sel) & 
                    (df_sol_user["f_reg_dt"].dt.year == anio_b_sel)
                ]
                adelanto_sueldo_monto = pd.to_numeric(df_sol_m["monto_adelanto"], errors="coerce").sum()

        # Descuadres de caja (solo faltantes negativos)
        df_desc_b = st.session_state.descuadres.copy()
        descuadre_caja_monto = 0.0
        if not df_desc_b.empty:
            df_desc_b["f_dt"] = pd.to_datetime(df_desc_b["fecha"], errors="coerce")
            df_desc_u = df_desc_b[
                (df_desc_b["nombre"] == colab_b_sel) & 
                (df_desc_b["f_dt"].dt.month == mes_b_sel) & 
                (df_desc_b["f_dt"].dt.year == anio_b_sel)
            ]
            if not df_desc_u.empty:
                faltantes = df_desc_u[pd.to_numeric(df_desc_u["monto"], errors="coerce") < 0]
                descuadre_caja_monto = abs(pd.to_numeric(faltantes["monto"], errors="coerce").sum())

        st.markdown("---")
        st.markdown("##### Valores y Conceptos Calculados")
        
        c_i1, c_i2, c_i3 = st.columns(3)
        sueldo_basico_in = c_i1.number_input("Sueldo Básico (S/.)", min_value=0.0, value=530.0, step=10.0, format="%.2f")
        dias_trab_in = c_i2.number_input("Días Laborados", min_value=0, max_value=31, value=int(dias_trabajados_cnt))
        feriados_trab_in = c_i3.number_input("Feriados Trab. (Adicional)", min_value=0, max_value=10, value=int(feriados_trabajados_cnt))

        c_i4, c_i5, c_i6 = st.columns(3)
        hrs_extras_in = c_i4.number_input("Horas Extras (Hrs)", min_value=0.0, value=float(hrs_extras_totales), step=0.5, format="%.2f")
        adelanto_in = c_i5.number_input("Adelanto de Sueldo (S/.)", min_value=0.0, value=float(adelanto_sueldo_monto), step=5.0, format="%.2f")
        dias_faltas_in = c_i6.number_input("Días Faltas", min_value=0, max_value=30, value=int(dias_faltas_cnt))

        c_i7, c_i8, c_i9 = st.columns(3)
        descuadre_caja_in = c_i7.number_input("Descuadre / Faltante Caja (S/.)", min_value=0.0, value=float(descuadre_caja_monto), step=1.0, format="%.2f")
        desc_inventario_in = c_i8.number_input("Descuadre Inventario (S/.)", min_value=0.0, value=0.0, step=1.0, format="%.2f")
        consumos_in = c_i9.number_input("Consumos por Pagar (S/.)", min_value=0.0, value=0.0, step=1.0, format="%.2f")

        c_i10, c_i11 = st.columns(2)
        domingo_volunt_in = c_i10.number_input(
            "Días de Descanso Trabajados Voluntariamente (Domingo)", min_value=0, max_value=5, value=int(domingos_voluntarios_cnt),
            help="Domingos marcados en Terminal de Asistencia como 'Trabajo Voluntario en Domingo (Día de Descanso)', o registrados manualmente aquí."
        )
        with c_i11:
            st.caption("Se paga como día adicional (100% del valor día), separado del sueldo básico, dejando constancia de que originalmente era su descanso.")

        # FÓRMULAS DE CÁLCULO
        valor_dia = sueldo_basico_in / 30.0 if sueldo_basico_in > 0 else 0.0
        valor_hora = valor_dia / 5.75 if valor_dia > 0 else 0.0

        monto_feriados_calc = feriados_trab_in * (valor_dia * 1.0)
        monto_horas_extras_calc = hrs_extras_in * (valor_hora * 1.25)
        monto_faltas_calc = dias_faltas_in * valor_dia
        monto_domingo_volunt_calc = domingo_volunt_in * (valor_dia * 1.0)

        total_ingresos_calc = sueldo_basico_in + monto_feriados_calc + monto_horas_extras_calc + monto_domingo_volunt_calc
        total_descuentos_calc = adelanto_in + monto_faltas_calc + descuadre_caja_in + desc_inventario_in + consumos_in
        neto_pagar_calc = max(0.0, total_ingresos_calc - total_descuentos_calc)

        datos_boleta = {
            "empresa": "TIENDAS PREMIUM E.I.R.L.",
            "ruc": "20612107786",
            "periodo": f"{NOMBRES_MESES_B[mes_b_sel-1].upper()} {anio_b_sel}",
            "colaborador": colab_b_sel,
            "dni": dni_b_val,
            "cargo": cargo_b_val,
            "fecha_inicio": finicio_b_val,
            "dias_trabajados": dias_trab_in,
            "dias_faltas": dias_faltas_in,
            "feriados_trabajados": feriados_trab_in,
            "horas_extras_hrs": hrs_extras_in,
            "sueldo_basico": sueldo_basico_in,
            "monto_feriados": monto_feriados_calc,
            "monto_horas_extras": monto_horas_extras_calc,
            "domingos_voluntarios": domingo_volunt_in,
            "monto_domingos_voluntarios": monto_domingo_volunt_calc,
            "adelanto_sueldo": adelanto_in,
            "monto_faltas": monto_faltas_calc,
            "descuadre_caja": descuadre_caja_in,
            "descuadre_inventario": desc_inventario_in,
            "consumos_pagar": consumos_in,
            "total_ingresos": total_ingresos_calc,
            "total_descuentos": total_descuentos_calc,
            "neto_pagar": neto_pagar_calc
        }

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("##### Previsualización de la Boleta de Pago")

        st.markdown(f"""
            <div class="boleta-container">
                <div class="boleta-header-title">TIENDAS PREMIUM E.I.R.L.</div>
                <div style="text-align:center; font-size:0.85rem; font-weight:700; margin-bottom:15px;">
                    RUC: 20612107786 | PERÍODO DE PAGO: {datos_boleta['periodo']}
                </div>
                <table class="boleta-table">
                    <tr>
                        <th style="width:15%;">COLABORADOR:</th>
                        <td style="width:35%;">{datos_boleta['colaborador']}</td>
                        <th style="width:15%;">DNI:</th>
                        <td style="width:35%;">{datos_boleta['dni']}</td>
                    </tr>
                    <tr>
                        <th>CARGO:</th>
                        <td>{datos_boleta['cargo']}</td>
                        <th>FECHA INGRESO:</th>
                        <td>{datos_boleta['fecha_inicio']}</td>
                    </tr>
                    <tr>
                        <th>DÍAS LABORADOS:</th>
                        <td>{datos_boleta['dias_trabajados']}</td>
                        <th>DÍAS FALTAS:</th>
                        <td>{datos_boleta['dias_faltas']}</td>
                    </tr>
                    <tr>
                        <th>FERIADOS TRAB.:</th>
                        <td>{datos_boleta['feriados_trabajados']}</td>
                        <th>HORAS EXTRAS:</th>
                        <td>{datos_boleta['horas_extras_hrs']:.2f} hrs</td>
                    </tr>
                    <tr>
                        <th>DOM. VOLUNTARIOS:</th>
                        <td>{datos_boleta.get('domingos_voluntarios', 0)}</td>
                        <th></th>
                        <td></td>
                    </tr>
                </table>
                <table class="boleta-table">
                    <thead>
                        <tr>
                            <th>CONCEPTO / RUBRO</th>
                            <th>CANTIDAD</th>
                            <th style="text-align:right;">INGRESOS (S/.)</th>
                            <th style="text-align:right;">DESCUENTOS (S/.)</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr>
                            <td>SUELDO BÁSICO</td>
                            <td>{datos_boleta['dias_trabajados']} días</td>
                            <td style="text-align:right;">{datos_boleta['sueldo_basico']:.2f}</td>
                            <td style="text-align:right;">0.00</td>
                        </tr>
                        <tr>
                            <td>PAGO FERIADOS TRABAJADOS (ADICIONAL)</td>
                            <td>{datos_boleta['feriados_trabajados']} días</td>
                            <td style="text-align:right;">{datos_boleta['monto_feriados']:.2f}</td>
                            <td style="text-align:right;">0.00</td>
                        </tr>
                        <tr>
                            <td>HORAS EXTRAS TRABAJADAS</td>
                            <td>{datos_boleta['horas_extras_hrs']:.2f} hrs</td>
                            <td style="text-align:right;">{datos_boleta['monto_horas_extras']:.2f}</td>
                            <td style="text-align:right;">0.00</td>
                        </tr>
                        <tr>
                            <td>DÍA DE DESCANSO TRABAJADO VOLUNTARIAMENTE (DOMINGO)</td>
                            <td>{datos_boleta.get('domingos_voluntarios', 0)} día(s)</td>
                            <td style="text-align:right;">{datos_boleta.get('monto_domingos_voluntarios', 0.0):.2f}</td>
                            <td style="text-align:right;">0.00</td>
                        </tr>
                        <tr>
                            <td>ADELANTO DE SUELDO</td>
                            <td>-</td>
                            <td style="text-align:right;">0.00</td>
                            <td style="text-align:right;">{datos_boleta['adelanto_sueldo']:.2f}</td>
                        </tr>
                        <tr>
                            <td>DESCUENTO POR FALTAS</td>
                            <td>{datos_boleta['dias_faltas']} días</td>
                            <td style="text-align:right;">0.00</td>
                            <td style="text-align:right;">{datos_boleta['monto_faltas']:.2f}</td>
                        </tr>
                        <tr>
                            <td>DESCUADRE / FALTANTE DE CAJA</td>
                            <td>-</td>
                            <td style="text-align:right;">0.00</td>
                            <td style="text-align:right;">{datos_boleta['descuadre_caja']:.2f}</td>
                        </tr>
                        <tr>
                            <td>DESCUADRES DE INVENTARIO</td>
                            <td>-</td>
                            <td style="text-align:right;">0.00</td>
                            <td style="text-align:right;">{datos_boleta['descuadre_inventario']:.2f}</td>
                        </tr>
                        <tr>
                            <td>CONSUMOS POR PAGAR</td>
                            <td>-</td>
                            <td style="text-align:right;">0.00</td>
                            <td style="text-align:right;">{datos_boleta['consumos_pagar']:.2f}</td>
                        </tr>
                        <tr style="background-color:#f3f4f6; font-weight:700;">
                            <td>TOTALES</td>
                            <td>-</td>
                            <td style="text-align:right;">S/. {datos_boleta['total_ingresos']:.2f}</td>
                            <td style="text-align:right;">S/. {datos_boleta['total_descuentos']:.2f}</td>
                        </tr>
                        <tr style="background-color:#111827; color:#ffffff; font-weight:700; font-size:0.95rem;">
                            <td colspan="2">NETO A PAGAR</td>
                            <td colspan="2" style="text-align:right;">S/. {datos_boleta['neto_pagar']:.2f}</td>
                        </tr>
                    </tbody>
                </table>
                <br><br>
                <div style="display:flex; justify-content:space-around; text-align:center; font-size:0.8rem; margin-top:20px;">
                    <div>
                        ___________________________________<br>
                        <b>EMPLEADOR / TIENDAS PREMIUM</b>
                    </div>
                    <div>
                        ___________________________________<br>
                        <b>RECIBÍ CONFORME (TRABAJADOR)</b>
                    </div>
                </div>
            </div>
        """, unsafe_allow_html=True)

        st.markdown("##### Opciones de Exportación")
        col_exp1, col_exp2 = st.columns(2)

        excel_data = generar_excel_boleta(datos_boleta)
        col_exp1.download_button(
            label="Descargar Boleta en Excel (.xlsx)",
            data=excel_data,
            file_name=f"Boleta_{colab_b_sel.replace(' ', '_')}_{datos_boleta['periodo']}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

        pdf_bytes = generar_pdf_boleta(datos_boleta)
        if pdf_bytes:
            col_exp2.download_button(
                label="Descargar Boleta en PDF (.pdf)",
                data=pdf_bytes,
                file_name=f"Boleta_{colab_b_sel.replace(' ', '_')}_{datos_boleta['periodo']}.pdf",
                mime="application/pdf",
                use_container_width=True
            )
        else:
            col_exp2.warning("La librería `reportlab` no está instalada en el entorno.")

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("💾 Guardar esta Boleta en el Historial (para Analítica / BI)", use_container_width=True):
            id_bol_hist = guardar_boleta_historial_gsheets({
                "mes": NOMBRES_MESES_B[mes_b_sel-1], "anio": anio_b_sel, "dni": dni_b_val,
                "nombre": colab_b_sel, "cargo": cargo_b_val, "sueldo_basico": sueldo_basico_in,
                "total_ingresos": total_ingresos_calc, "total_descuentos": total_descuentos_calc,
                "neto_pagar": neto_pagar_calc, "emitido_por": user_actual
            })
            if id_bol_hist:
                registrar_auditoria("Emitir Boleta", "Boletas", f"{colab_b_sel} — {datos_boleta['periodo']} — Neto: S/. {neto_pagar_calc:.2f}")
                st.toast("Boleta guardada en el historial de analítica")
elif choice == "Solicitudes y Permisos":
    st.markdown("""
        <div class="market-header">
            <h1>Gestión de Solicitudes y Permisos</h1>
            <p>Bandeja de aprobación para administración</p>
        </div>
    """, unsafe_allow_html=True)

    if not st.session_state.solicitudes.empty:
        df_sol_base = st.session_state.solicitudes.copy()

        # --- MÉTRICAS RESUMEN ---
        total_pend = len(df_sol_base[df_sol_base["estado"] == "Pendiente"])
        total_aprob = len(df_sol_base[df_sol_base["estado"] == "Aprobado"])
        total_rechaz = len(df_sol_base[df_sol_base["estado"] == "Rechazado"])
        monto_adel_aprob = pd.to_numeric(
            df_sol_base[(df_sol_base["tipo_solicitud"] == "Adelanto de Sueldo") & (df_sol_base["estado"] == "Aprobado")]["monto_adelanto"],
            errors="coerce"
        ).sum()

        sm1, sm2, sm3, sm4 = st.columns(4)
        with sm1:
            st.markdown(f'<div class="info-card"><div class="info-label">Pendientes</div><div class="info-value" style="color:{"#EAB308" if total_pend else "#111827"};">{total_pend}</div></div>', unsafe_allow_html=True)
        with sm2:
            st.markdown(f'<div class="info-card"><div class="info-label">Aprobadas</div><div class="info-value" style="color:#00A959;">{total_aprob}</div></div>', unsafe_allow_html=True)
        with sm3:
            st.markdown(f'<div class="info-card"><div class="info-label">Rechazadas</div><div class="info-value" style="color:#EC3237;">{total_rechaz}</div></div>', unsafe_allow_html=True)
        with sm4:
            st.markdown(f'<div class="info-card"><div class="info-label">Adelantos Aprobados (Total)</div><div class="info-value">S/. {monto_adel_aprob:.2f}</div></div>', unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # --- FILTROS ---
        fc1, fc2, fc3 = st.columns([1, 1, 1.4])
        with fc1:
            estado_filtro = st.selectbox("Filtrar por Estado", ["Pendiente", "Todos", "Aprobado", "Rechazado"], key="sol_estado_filtro")
        with fc2:
            tipos_disp = ["Todos"] + sorted(df_sol_base["tipo_solicitud"].dropna().unique().tolist())
            tipo_filtro = st.selectbox("Filtrar por Tipo", tipos_disp, key="sol_tipo_filtro")
        with fc3:
            busqueda_sol = st.text_input("Buscar por colaborador", placeholder="Escribe un nombre...", key="sol_busqueda")

        df_sol = df_sol_base.copy()
        if estado_filtro != "Todos":
            df_sol = df_sol[df_sol["estado"] == estado_filtro]
        if tipo_filtro != "Todos":
            df_sol = df_sol[df_sol["tipo_solicitud"] == tipo_filtro]
        if busqueda_sol.strip():
            df_sol = df_sol[df_sol["nombre"].astype(str).str.contains(busqueda_sol.strip(), case=False, na=False)]

        df_sol = df_sol.sort_values("fecha_registro", ascending=False)
        st.caption(f"Mostrando {len(df_sol)} de {len(df_sol_base)} solicitud(es) registradas.")
        st.markdown("<br>", unsafe_allow_html=True)

        if df_sol.empty:
            st.info("Ninguna solicitud coincide con los filtros seleccionados.")

        for idx, row_sol in df_sol.iterrows():
            id_s = row_sol["id_solicitud"]
            nom_s = row_sol["nombre"]
            tipo_s = row_sol["tipo_solicitud"]
            est_s = row_sol["estado"]
            
            color_st = "#EAB308" if est_s == "Pendiente" else ("#00A959" if est_s == "Aprobado" else "#EC3237")
            icono_tipo = "🗓️" if tipo_s == "Permiso Laboral" else ("💰" if tipo_s == "Adelanto de Sueldo" else "☀️")
            
            with st.expander(f"{icono_tipo} {tipo_s} - {nom_s} ({row_sol['fecha_registro']}) [{est_s}]"):
                c_sol1, c_sol2 = st.columns([2, 1])
                
                with c_sol1:
                    st.markdown(f"**Trabajador:** {nom_s} (DNI: {row_sol['dni']})")
                    st.markdown(f"**Tipo de Solicitud:** {tipo_s}")
                    if tipo_s == "Permiso Laboral":
                        st.markdown(f"**Fecha Solicitada:** {row_sol['fecha_permiso']}")
                        fecha_rec_admin = str(row_sol.get("fecha_recuperacion", "")).strip()
                        if fecha_rec_admin:
                            st.markdown(f"**Fecha de Recuperación:** {fecha_rec_admin}")
                            if pd.notna(pd.to_datetime(fecha_rec_admin, errors="coerce")):
                                fecha_rec_dt = pd.to_datetime(fecha_rec_admin, errors="coerce")
                                if fecha_rec_dt.dayofweek == 6:
                                    st.caption("🟢 La recuperación está programada para domingo.")
                    elif tipo_s == "Trabajar Domingo (Descanso)":
                        st.markdown(f"**Domingo que desea trabajar:** {row_sol['fecha_permiso']}")
                        st.caption("☀ Este domingo es normalmente su día de descanso semanal. Al aprobar, el colaborador podrá marcar asistencia ese día y se reflejará como día adicional en su boleta.")
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
                            registrar_auditoria("Aprobar Solicitud", "Solicitudes", f"{tipo_s} de {nom_s} ({id_s})")
                            st.toast("Solicitud Aprobada")
                            time.sleep(0.3)
                            st.rerun()

                        if btn_col2.button("Rechazar", key=f"rec_{id_s}", use_container_width=True):
                            idx_real = st.session_state.solicitudes[st.session_state.solicitudes["id_solicitud"] == id_s].index
                            st.session_state.solicitudes.loc[idx_real, "estado"] = "Rechazado"
                            st.session_state.solicitudes.loc[idx_real, "respuesta_admin"] = resp_admin_input
                            actualizar_hoja_completa("Solicitudes", st.session_state.solicitudes)
                            registrar_auditoria("Rechazar Solicitud", "Solicitudes", f"{tipo_s} de {nom_s} ({id_s})")
                            st.toast("Solicitud Rechazada")
                            time.sleep(0.3)
                            st.rerun()
                    else:
                        if str(row_sol.get("respuesta_admin", "")).strip():
                            st.markdown(f"**Respuesta emitida:** {row_sol['respuesta_admin']}")

        st.markdown("<br>", unsafe_allow_html=True)
        st.download_button("Exportar Solicitudes Filtradas a Excel", to_excel(df_sol), "Solicitudes.xlsx", use_container_width=True)
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
        st.markdown("##### Resumen Mensual de Descuadres por Trabajador")
        
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
                    
                    with st.expander(f" **{nombre_colab}** | Balance Mes de {NOMBRES_MESES[mes_desc_sel-1]}: S/. {monto_total_colab:.2f}", expanded=True):
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
                    st.markdown(f" **{nombre_colab}**: *Sin descuadres registrados en {NOMBRES_MESES[mes_desc_sel-1]}.*")
        else:
            st.info(f"No hay descuadres registrados en el mes de {NOMBRES_MESES[mes_desc_sel-1]} de {anio_desc_sel}.")

        st.markdown("---")

        st.markdown("##### Filtros de Búsqueda")
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
            st.markdown("##### Ranking de Colaboradores (según filtro aplicado)")

            df_rank_desc = df_desc_filtrado.groupby("nombre")["monto_num"].sum().reset_index().rename(columns={"monto_num": "balance"})
            df_rank_desc = df_rank_desc.sort_values("balance")

            if not df_rank_desc.empty:
                rk1, rk2 = st.columns(2)
                with rk1:
                    st.markdown("**⚠️ Mayores Faltantes**")
                    peores = df_rank_desc[df_rank_desc["balance"] < 0].head(5)
                    if not peores.empty:
                        for _, r_pk in peores.iterrows():
                            st.markdown(f"- **{r_pk['nombre']}**: <span style='color:#EC3237; font-weight:700;'>S/. {r_pk['balance']:.2f}</span>", unsafe_allow_html=True)
                    else:
                        st.success("Nadie registra faltantes en este período.")
                with rk2:
                    st.markdown("**✅ Mejores Balances**")
                    mejores = df_rank_desc[df_rank_desc["balance"] >= 0].sort_values("balance", ascending=False).head(5)
                    if not mejores.empty:
                        for _, r_mk in mejores.iterrows():
                            st.markdown(f"- **{r_mk['nombre']}**: <span style='color:#00A959; font-weight:700;'>+S/. {r_mk['balance']:.2f}</span>", unsafe_allow_html=True)
                    else:
                        st.info("Sin balances positivos registrados en este período.")

                st.bar_chart(df_rank_desc.set_index("nombre")["balance"])

            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("#####  Balance de Descuadres por Trabajador")
            
            for nombre_trab, df_trab in df_desc_filtrado.groupby("nombre"):
                monto_trab_total = df_trab["monto_num"].sum()
                color_monto = "#00A959" if monto_trab_total >= 0 else "#EC3237"
                signo_monto = "+" if monto_trab_total > 0 else ""
                
                with st.expander(f" **{nombre_trab}** — Balance Neto: {signo_monto} S/. {monto_trab_total:.2f}"):
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
        st.markdown("##### Matriz Consolidada de Descuadres")
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
                            valor_anterior_desc = f"S/. {row_mod['monto']} ({row_mod['tipo']})"
                            st.session_state.descuadres.at[idx_mod, "monto"] = nuevo_monto
                            st.session_state.descuadres.at[idx_mod, "tipo"] = nuevo_tipo
                            st.session_state.descuadres.at[idx_mod, "observacion"] = nueva_obs
                            actualizar_hoja_completa("Descuadres", st.session_state.descuadres)
                            registrar_auditoria("Editar Descuadre", "Descuadres", f"{row_mod['nombre']} ({row_mod['fecha']}): {valor_anterior_desc} → S/. {nuevo_monto} ({nuevo_tipo})")
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
                            row_del_desc = st.session_state.descuadres.loc[idx_del]
                            st.session_state.descuadres = st.session_state.descuadres.drop(idx_del).reset_index(drop=True)
                            actualizar_hoja_completa("Descuadres", st.session_state.descuadres)
                            registrar_auditoria("Eliminar Descuadre", "Descuadres", f"{row_del_desc['nombre']} ({row_del_desc['fecha']}): S/. {row_del_desc['monto']} ({row_del_desc['tipo']})")
                            st.toast("Descuadre eliminado correctamente")
                            time.sleep(0.3)
                            st.rerun()
                        else:
                            st.warning("Marca la casilla de confirmación antes de eliminar.")
    else:
        st.info("Sin descuadres registrados.")

elif choice == "Incidencias y Daños":
    st.markdown("""
        <div class="market-header">
            <h1>Incidencias y Daños</h1>
            <p>Billetes falsos, botellas rotas y otros daños reportados por el personal</p>
        </div>
    """, unsafe_allow_html=True)

    if not st.session_state.incidencias.empty:
        df_inc_admin = st.session_state.incidencias.copy()
        df_inc_admin["valor_reparacion"] = pd.to_numeric(df_inc_admin["valor_reparacion"], errors="coerce").fillna(0)

        im1, im2, im3, im4 = st.columns(4)
        with im1:
            st.markdown(f'<div class="info-card"><div class="info-label">Total Incidencias</div><div class="info-value">{len(df_inc_admin)}</div></div>', unsafe_allow_html=True)
        with im2:
            st.markdown(f'<div class="info-card"><div class="info-label">Valor Total a Reparar</div><div class="info-value" style="color:#EC3237;">S/. {df_inc_admin["valor_reparacion"].sum():.2f}</div></div>', unsafe_allow_html=True)
        with im3:
            pend_inc_cnt = len(df_inc_admin[df_inc_admin["estado"] == "Pendiente"])
            st.markdown(f'<div class="info-card"><div class="info-label">Pendientes de Resolver</div><div class="info-value" style="color:{"#EAB308" if pend_inc_cnt else "#111827"};">{pend_inc_cnt}</div></div>', unsafe_allow_html=True)
        with im4:
            billetes_falsos_total = df_inc_admin[df_inc_admin["tipo_incidencia"] == "Billete Falso"]["valor_reparacion"].sum()
            st.markdown(f'<div class="info-card"><div class="info-label">Total en Billetes Falsos</div><div class="info-value">S/. {billetes_falsos_total:.2f}</div></div>', unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        fi1, fi2 = st.columns(2)
        with fi1:
            tipos_inc_disp = ["Todos"] + sorted(df_inc_admin["tipo_incidencia"].dropna().unique().tolist())
            tipo_inc_filtro = st.selectbox("Filtrar por Tipo", tipos_inc_disp, key="inc_filtro_tipo_admin")
        with fi2:
            colabs_inc_disp = ["Todos"] + sorted(df_inc_admin["nombre"].dropna().unique().tolist())
            colab_inc_filtro = st.selectbox("Filtrar por Colaborador", colabs_inc_disp, key="inc_filtro_colab_admin")

        df_inc_filtrado = df_inc_admin.copy()
        if tipo_inc_filtro != "Todos":
            df_inc_filtrado = df_inc_filtrado[df_inc_filtrado["tipo_incidencia"] == tipo_inc_filtro]
        if colab_inc_filtro != "Todos":
            df_inc_filtrado = df_inc_filtrado[df_inc_filtrado["nombre"] == colab_inc_filtro]

        st.markdown("##### Ranking por Colaborador (valor total a reparar)")
        df_rank_inc = df_inc_filtrado.groupby("nombre")["valor_reparacion"].sum().reset_index().sort_values("valor_reparacion", ascending=False)
        if not df_rank_inc.empty:
            st.bar_chart(df_rank_inc.set_index("nombre")["valor_reparacion"])

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("##### Detalle de Incidencias")
        st.dataframe(
            df_inc_filtrado.sort_values("fecha_registro", ascending=False),
            use_container_width=True,
            hide_index=True
        )
        st.download_button("Exportar Incidencias a Excel", to_excel(df_inc_filtrado), "Incidencias.xlsx", use_container_width=True)

        st.markdown("<br>", unsafe_allow_html=True)
        with st.expander("Marcar Incidencia como Resuelta / Descontada"):
            opciones_inc_resolver = [
                f"{i} | {r['nombre']} | {r['tipo_incidencia']} | S/. {r['valor_reparacion']:.2f} | {r['estado']}"
                for i, r in st.session_state.incidencias.iterrows()
            ]
            sel_inc_resolver = st.selectbox("Seleccionar Incidencia", opciones_inc_resolver, key="inc_resolver_sel")
            nuevo_estado_inc = st.selectbox("Nuevo Estado", ["Pendiente", "Descontado en Boleta", "Resuelto / Condonado"], key="inc_nuevo_estado")
            if st.button("Actualizar Estado", use_container_width=True, key="inc_resolver_btn"):
                idx_inc_resolver = int(sel_inc_resolver.split(" | ")[0])
                st.session_state.incidencias.at[idx_inc_resolver, "estado"] = nuevo_estado_inc
                actualizar_hoja_completa("Incidencias", st.session_state.incidencias)
                registrar_auditoria("Actualizar Estado de Incidencia", "Incidencias", f"Incidencia #{idx_inc_resolver} → {nuevo_estado_inc}")
                st.toast("Estado actualizado")
                time.sleep(0.3)
                st.rerun()
    else:
        st.info("No hay incidencias registradas todavía.")

elif choice == "Botellas Fiadas":
    st.markdown(f"""
        <div class="market-header">
            <h1>Botellas Fiadas a Clientes</h1>
            <p>Visible para todos los turnos y roles — responsable actual: <b>{user_actual}</b></p>
        </div>
    """, unsafe_allow_html=True)

    st.caption("Registra aquí cuando se le fíen botellas (gaseosa o cerveza) a un cliente. Cualquier colaborador o el administrador podrá ver este registro en cualquier turno, hasta que las botellas sean devueltas.")

    with st.container(border=True):
        st.markdown("##### Registrar Botellas Fiadas")
        with st.form("form_botella_fiada", clear_on_submit=True):
            bf1, bf2 = st.columns(2)
            cliente_nombre_bf = bf1.text_input("Nombre del Cliente", key="bf_nombre")
            cliente_dni_bf = bf2.text_input("DNI del Cliente", key="bf_dni")

            cliente_dir_bf = st.text_input("Dirección / Dónde Vive", key="bf_direccion")

            bf3, bf4, bf5 = st.columns(3)
            cantidad_bf = bf3.number_input("Cantidad de Botellas", min_value=1, step=1, key="bf_cantidad")
            tipo_botella_bf = bf4.selectbox("Tipo de Botella", ["Gaseosa", "Cerveza", "Mixto (Gaseosa y Cerveza)"], key="bf_tipo")
            dejo_dinero_bf = bf5.selectbox("¿Dejó Dinero de Garantía?", ["No", "Sí"], key="bf_dejo_dinero")

            monto_dejado_bf = 0.0
            if dejo_dinero_bf == "Sí":
                monto_dejado_bf = st.number_input("Monto Dejado (S/.)", min_value=0.0, step=1.0, format="%.2f", key="bf_monto_dejado")

            obs_bf = st.text_area("Observación (opcional)", key="bf_obs")

            if st.form_submit_button("Guardar Registro de Botellas Fiadas", use_container_width=True):
                if not cliente_nombre_bf.strip():
                    st.error("Debes ingresar el nombre del cliente.")
                else:
                    id_bf_nuevo = f"BF-{int(time.time()*1000)}"
                    f_prestamo_bf = obtener_ahora_peru().strftime("%Y-%m-%d %H:%M:%S")

                    guardado_bf_ok = guardar_botella_fiada_gsheets(
                        id_bf_nuevo, cliente_nombre_bf.strip(), cliente_dni_bf.strip(), cliente_dir_bf.strip(),
                        cantidad_bf, tipo_botella_bf, dejo_dinero_bf, monto_dejado_bf, f_prestamo_bf,
                        user_actual, "Pendiente", "", obs_bf
                    )
                    if guardado_bf_ok:
                        nueva_fila_bf = {
                            "id_fiado": id_bf_nuevo, "cliente_nombre": cliente_nombre_bf.strip(), "cliente_dni": cliente_dni_bf.strip(),
                            "cliente_direccion": cliente_dir_bf.strip(), "cantidad_botellas": cantidad_bf, "tipo_botella": tipo_botella_bf,
                            "dejo_dinero": dejo_dinero_bf, "monto_dejado": monto_dejado_bf, "fecha_prestamo": f_prestamo_bf,
                            "registrado_por": user_actual, "estado": "Pendiente", "fecha_devolucion": "", "observacion": obs_bf
                        }
                        st.session_state.botellas_fiadas = pd.concat([pd.DataFrame([nueva_fila_bf]), st.session_state.botellas_fiadas], ignore_index=True)
                        registrar_auditoria("Registrar Botellas Fiadas", "BotellasFiadas", f"{cliente_nombre_bf.strip()} — {cantidad_bf} botella(s) de {tipo_botella_bf}")
                        st.toast("Botellas fiadas registradas correctamente")
                        time.sleep(0.3)
                        st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("##### 🍾 Botellas Pendientes de Devolución (todos los turnos)")

    if not st.session_state.botellas_fiadas.empty:
        df_bf_pend = st.session_state.botellas_fiadas[st.session_state.botellas_fiadas["estado"] != "Devuelta"]
        if not df_bf_pend.empty:
            for idx_bf, r_bf in df_bf_pend.iterrows():
                with st.container(border=True):
                    cbf1, cbf2 = st.columns([3, 1])
                    with cbf1:
                        st.markdown(f"**{r_bf['cliente_nombre']}** — DNI: {r_bf['cliente_dni'] or 'No registrado'}")
                        st.caption(f"📍 {r_bf['cliente_direccion'] or 'Sin dirección registrada'}")
                        st.markdown(f"**{r_bf['cantidad_botellas']} botella(s)** de **{r_bf['tipo_botella']}** — Fiado el {r_bf['fecha_prestamo']} por {r_bf['registrado_por']}")
                        if str(r_bf['dejo_dinero']).strip().lower() in ["sí", "si"]:
                            st.success(f"💰 Dejó S/. {float(r_bf['monto_dejado']):.2f} de garantía")
                        else:
                            st.warning("⚠️ No dejó dinero de garantía")
                        if str(r_bf.get("observacion", "")).strip():
                            st.caption(f"Obs: {r_bf['observacion']}")
                    with cbf2:
                        if st.button("✅ Marcar Devueltas", key=f"bf_dev_{idx_bf}", use_container_width=True):
                            st.session_state.botellas_fiadas.at[idx_bf, "estado"] = "Devuelta"
                            st.session_state.botellas_fiadas.at[idx_bf, "fecha_devolucion"] = obtener_ahora_peru().strftime("%Y-%m-%d %H:%M:%S")
                            actualizar_hoja_completa("BotellasFiadas", st.session_state.botellas_fiadas)
                            registrar_auditoria("Marcar Botellas Devueltas", "BotellasFiadas", f"{r_bf['cliente_nombre']} — {r_bf['cantidad_botellas']} botella(s)")
                            st.toast("Botellas marcadas como devueltas")
                            time.sleep(0.3)
                            st.rerun()
        else:
            st.success("No hay botellas pendientes de devolución en este momento.")
    else:
        st.info("No hay registros de botellas fiadas todavía.")

    st.markdown("<br>", unsafe_allow_html=True)
    with st.expander("📜 Historial de Botellas Ya Devueltas"):
        if not st.session_state.botellas_fiadas.empty:
            df_bf_devueltas = st.session_state.botellas_fiadas[st.session_state.botellas_fiadas["estado"] == "Devuelta"]
            if not df_bf_devueltas.empty:
                st.dataframe(
                    df_bf_devueltas.sort_values("fecha_devolucion", ascending=False),
                    use_container_width=True,
                    hide_index=True
                )
                st.download_button("Exportar Historial a Excel", to_excel(df_bf_devueltas), "Botellas_Devueltas.xlsx", use_container_width=True)
            else:
                st.info("Aún no hay botellas devueltas registradas.")

elif choice == "Historial de Asistencias":
    st.markdown("""
        <div class="market-header">
            <h1>Reporte de Asistencias</h1>
            <p>Histórico de marcas de ingreso y salida</p>
        </div>
    """, unsafe_allow_html=True)

    if not st.session_state.asistencia.empty:
        st.markdown("##### Filtros de Búsqueda")
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
                st.markdown(f'<div class="info-card"><div class="info-label">Ingresos Registrados</div><div class="info-value" style="color:#00A959;">{ingresos_cnt}</div></div>', unsafe_allow_html=True)
            with a3:
                st.markdown(f'<div class="info-card"><div class="info-label">Colaboradores Activos</div><div class="info-value">{colabs_unicos}</div></div>', unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("##### Ranking de Puntualidad (según filtro aplicado)")

            filas_punt = []
            for nom_p in sorted(df_asist_filtrado["nombre"].unique().tolist()):
                metrica_p = calcular_metricas_puntualidad(df_asist_filtrado, nom_p)
                if metrica_p["total_ingresos"] > 0:
                    filas_punt.append({
                        "Colaborador": nom_p,
                        "Ingresos": metrica_p["total_ingresos"],
                        "Puntuales": metrica_p["puntuales"],
                        "Tardanzas": metrica_p["tardanzas"],
                        "Minutos Acumulados": metrica_p["minutos_acumulados"],
                        "% Puntualidad": metrica_p["ratio"]
                    })

            if filas_punt:
                df_punt = pd.DataFrame(filas_punt).sort_values("% Puntualidad")
                st.dataframe(
                    df_punt,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "% Puntualidad": st.column_config.ProgressColumn("% Puntualidad", format="%.1f%%", min_value=0, max_value=100)
                    }
                )
                st.bar_chart(df_punt.set_index("Colaborador")["Tardanzas"])
            else:
                st.info("No hay ingresos registrados para calcular puntualidad en este filtro.")

            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("##### Registro Detallado de Asistencias")
            st.dataframe(
                df_asist_filtrado,
                use_container_width=True,
                hide_index=True
            )
            st.download_button("Exportar Asistencias a Excel", to_excel(df_asist_filtrado), "Asistencias_General.xlsx", use_container_width=True)
        else:
            st.info("No se encontraron registros de asistencia para los filtros seleccionados.")
    else:
        st.info("No hay marcaciones de asistencia registradas en el sistema.")

elif choice == "Centro de Alertas":
    st.markdown("""
        <div class="market-header">
            <h1>Centro de Alertas y Notificaciones</h1>
            <p>Avisos automáticos que el sistema detecta a partir de tus propios datos</p>
        </div>
    """, unsafe_allow_html=True)

    hoy_alerta = obtener_ahora_peru().date()
    df_emp_activos = st.session_state.empleados[st.session_state.empleados["estado"].astype(str).str.lower() == "activo"].copy()

    # --- 1. CONTRATOS POR VENCER (próximos 15 días) ---
    contratos_por_vencer = []
    for _, r_emp in df_emp_activos.iterrows():
        f_cese = _parsear_fecha_nac_cumple(r_emp.get("fecha_cese", ""))
        if f_cese:
            dias_rest = (f_cese - hoy_alerta).days
            if 0 <= dias_rest <= 15:
                contratos_por_vencer.append((r_emp["nombre"], f_cese, dias_rest))

    # --- 2. CUMPLEAÑOS EN LOS PRÓXIMOS 7 DÍAS ---
    cumples_prox = []
    for _, r_emp in df_emp_activos.iterrows():
        f_nac = _parsear_fecha_nac_cumple(r_emp.get("fecha_nacimiento", ""))
        if f_nac:
            prox_cumple = f_nac.replace(year=hoy_alerta.year)
            if prox_cumple < hoy_alerta:
                prox_cumple = prox_cumple.replace(year=hoy_alerta.year + 1)
            dias_para_cumple = (prox_cumple - hoy_alerta).days
            if 0 <= dias_para_cumple <= 7:
                cumples_prox.append((r_emp["nombre"], prox_cumple, dias_para_cumple))

    # --- 3. TARDANZAS RECURRENTES EN EL MES ACTUAL (3 o más) ---
    tardanzas_recurrentes = []
    if not st.session_state.asistencia.empty:
        mes_actual_str = hoy_alerta.strftime("%Y-%m")
        df_asist_mes = st.session_state.asistencia[
            st.session_state.asistencia["fecha"].astype(str).str.startswith(mes_actual_str)
        ]
        for nombre_c in df_asist_mes["nombre"].unique():
            metrica_c = calcular_metricas_puntualidad(df_asist_mes, nombre_c)
            if metrica_c["tardanzas"] >= 3:
                tardanzas_recurrentes.append((nombre_c, metrica_c["tardanzas"], metrica_c["minutos_acumulados"]))

    # --- 4. SOLICITUDES PENDIENTES DE RESPUESTA ---
    solicitudes_pend = 0
    if not st.session_state.solicitudes.empty:
        solicitudes_pend = len(st.session_state.solicitudes[st.session_state.solicitudes["estado"] == "Pendiente"])

    # --- 5. PERMISOS DE SALUD PENDIENTES DE RECUPERAR ---
    permisos_pend_recup = 0
    if not st.session_state.vacaciones.empty:
        permisos_pend_recup = len(st.session_state.vacaciones[
            (st.session_state.vacaciones["tipo"] == "Permiso de Salud (a recuperar)") &
            (st.session_state.vacaciones["estado_recuperacion"] != "Recuperado")
        ])

    al1, al2, al3, al4, al5 = st.columns(5)
    with al1:
        st.markdown(f'<div class="info-card"><div class="info-label">Contratos por Vencer</div><div class="info-value" style="color:{"#EC3237" if contratos_por_vencer else "#111827"};">{len(contratos_por_vencer)}</div></div>', unsafe_allow_html=True)
    with al2:
        st.markdown(f'<div class="info-card"><div class="info-label">Cumpleaños esta Semana</div><div class="info-value" style="color:#EC3237;">{len(cumples_prox)}</div></div>', unsafe_allow_html=True)
    with al3:
        st.markdown(f'<div class="info-card"><div class="info-label">Tardanzas Recurrentes</div><div class="info-value" style="color:{"#EC3237" if tardanzas_recurrentes else "#111827"};">{len(tardanzas_recurrentes)}</div></div>', unsafe_allow_html=True)
    with al4:
        st.markdown(f'<div class="info-card"><div class="info-label">Solicitudes Pendientes</div><div class="info-value" style="color:{"#EC3237" if solicitudes_pend else "#111827"};">{solicitudes_pend}</div></div>', unsafe_allow_html=True)
    with al5:
        st.markdown(f'<div class="info-card"><div class="info-label">Permisos de Salud sin Recuperar</div><div class="info-value" style="color:{"#EC3237" if permisos_pend_recup else "#111827"};">{permisos_pend_recup}</div></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    with st.container(border=True):
        st.markdown("##### ⏳ Contratos próximos a vencer (15 días)")
        if contratos_por_vencer:
            for nom_c, f_c, d_r in sorted(contratos_por_vencer, key=lambda x: x[2]):
                st.warning(f"**{nom_c}** — Cese programado el **{f_c.strftime('%d/%m/%Y')}** (en {d_r} día(s)). Evaluar renovación o cese.")
        else:
            st.success("No hay contratos por vencer en los próximos 15 días.")

    st.markdown("<br>", unsafe_allow_html=True)

    with st.container(border=True):
        st.markdown("##### 🎂 Cumpleaños de la próxima semana")
        if cumples_prox:
            for nom_c, f_c, d_r in sorted(cumples_prox, key=lambda x: x[2]):
                etiqueta = "¡Hoy!" if d_r == 0 else f"en {d_r} día(s)"
                st.info(f"**{nom_c}** cumple años el **{f_c.strftime('%d/%m')}** ({etiqueta}).")
        else:
            st.info("Sin cumpleaños en los próximos 7 días.")

    st.markdown("<br>", unsafe_allow_html=True)

    with st.container(border=True):
        st.markdown("##### ⏰ Colaboradores con tardanzas recurrentes (mes actual)")
        if tardanzas_recurrentes:
            for nom_c, cnt_t, mins_t in sorted(tardanzas_recurrentes, key=lambda x: -x[1]):
                st.error(f"**{nom_c}** — {cnt_t} tardanza(s) este mes, acumulando {mins_t} minuto(s) de retraso.")
        else:
            st.success("Ningún colaborador supera las 3 tardanzas este mes.")

    st.markdown("<br>", unsafe_allow_html=True)

    with st.container(border=True):
        st.markdown("##### 📝 Solicitudes esperando respuesta")
        if solicitudes_pend:
            st.warning(f"Tienes **{solicitudes_pend}** solicitud(es) pendiente(s) de revisión en la sección 'Solicitudes y Permisos'.")
        else:
            st.success("No hay solicitudes pendientes por atender.")

    st.markdown("<br>", unsafe_allow_html=True)

    with st.container(border=True):
        st.markdown("##### 🏥 Permisos de salud sin recuperar")
        if permisos_pend_recup:
            df_pend_recup_alerta = st.session_state.vacaciones[
                (st.session_state.vacaciones["tipo"] == "Permiso de Salud (a recuperar)") &
                (st.session_state.vacaciones["estado_recuperacion"] != "Recuperado")
            ]
            for _, r_pr_a in df_pend_recup_alerta.iterrows():
                st.warning(f"**{r_pr_a['nombre']}** debe recuperar el **{r_pr_a['fecha_recuperacion']}** ({r_pr_a['horario_recuperacion'] or 'horario no especificado'}). Gestionar en 'Gestión de Vacaciones'.")
        else:
            st.success("No hay permisos de salud pendientes de recuperación.")

elif choice == "Gestión de Vacaciones":
    st.markdown("""
        <div class="market-header">
            <h1>Gestión de Vacaciones y Permisos de Salud</h1>
            <p>Régimen REMYPE — 15 días de vacaciones al año (único beneficio social), único para personal en planilla</p>
        </div>
    """, unsafe_allow_html=True)

    lista_colabs_activos = st.session_state.empleados[st.session_state.empleados["estado"].astype(str).str.lower() == "activo"]["nombre"].tolist()

    with st.container(border=True):
        st.markdown("##### Registrar Descanso / Permiso")

        c_tipo1, c_tipo2 = st.columns(2)
        with c_tipo1:
            colab_vac_sel = st.selectbox("Colaborador", lista_colabs_activos, key="vac_colab_sel")
        with c_tipo2:
            tipo_vac_sel = st.selectbox(
                "Tipo",
                ["Vacaciones", "Permiso de Salud (a recuperar)", "Licencia sin Goce"],
                key="vac_tipo_sel",
                help="'Permiso de Salud' no se otorga como descanso médico pagado: se registra como permiso y el trabajador debe recuperar el día, usualmente el domingo."
            )

        fila_emp_check = st.session_state.empleados[st.session_state.empleados["nombre"] == colab_vac_sel]
        en_planilla_check = str(fila_emp_check.iloc[0].get("en_planilla", "Sí")) if not fila_emp_check.empty else "Sí"
        if tipo_vac_sel == "Vacaciones" and en_planilla_check.strip().lower() not in ("sí", "si"):
            st.warning(f"**{colab_vac_sel}** no está en planilla formal, por lo que no genera beneficio vacacional. Puedes registrar igual el descanso, pero no se contabilizará contra ningún saldo.")

        f_ini_vac = st.date_input("Fecha de Inicio", value=obtener_ahora_peru().date(), key="vac_f_ini")
        f_fin_vac = st.date_input("Fecha de Fin", value=obtener_ahora_peru().date(), key="vac_f_fin")

        fecha_recup_val = ""
        horario_recup_val = ""
        if tipo_vac_sel == "Permiso de Salud (a recuperar)":
            st.markdown("##### Recuperación del día (usualmente domingo)")
            hoy_v = obtener_ahora_peru().date()
            dias_hasta_domingo = (6 - hoy_v.weekday()) % 7
            dias_hasta_domingo = dias_hasta_domingo if dias_hasta_domingo > 0 else 7
            proximo_domingo = hoy_v + timedelta(days=dias_hasta_domingo)
            r1, r2 = st.columns(2)
            with r1:
                fecha_recup_sel = st.date_input("Fecha a Recuperar", value=proximo_domingo, key="vac_f_recup")
            with r2:
                horario_recup_val = st.text_input("Horario de Recuperación", value="3:30 pm - 9:00 pm", key="vac_horario_recup")
            fecha_recup_val = str(fecha_recup_sel)
            dias_semana_v = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
            st.caption(f"Se recuperará el **{fecha_recup_sel.strftime('%d/%m/%Y')} ({dias_semana_v[fecha_recup_sel.weekday()]})**, de **{horario_recup_val}**.")
            st.info("Este horario equivale a la jornada completa del día a recuperar, según política de la empresa (no se compara minuto a minuto contra la jornada base de 5h45m usada para el cálculo de horas extras diarias).")

        with st.form("form_registro_vacacion", clear_on_submit=True):
            obs_vac = st.text_area("Observación (opcional)", key="vac_obs")
            enviar_vac = st.form_submit_button("Registrar", use_container_width=True)

            if enviar_vac:
                if f_fin_vac < f_ini_vac:
                    st.error("La fecha de fin no puede ser anterior a la fecha de inicio.")
                else:
                    dias_calc = (f_fin_vac - f_ini_vac).days + 1
                    fila_emp_vac = st.session_state.empleados[st.session_state.empleados["nombre"] == colab_vac_sel].iloc[0]
                    id_vac_nuevo = f"VAC-{int(time.time())}"
                    estado_recup_val = "Pendiente" if tipo_vac_sel == "Permiso de Salud (a recuperar)" else ""

                    guardar_vacacion_gsheets(
                        id_vac_nuevo, fila_emp_vac["dni"], colab_vac_sel, tipo_vac_sel,
                        f_ini_vac, f_fin_vac, dias_calc, obs_vac,
                        obtener_ahora_peru().strftime("%Y-%m-%d %H:%M:%S"), user_actual,
                        fecha_recup_val, horario_recup_val, estado_recup_val
                    )
                    nuevo_row_vac = {
                        "id_vacacion": id_vac_nuevo, "dni": fila_emp_vac["dni"], "nombre": colab_vac_sel,
                        "tipo": tipo_vac_sel, "fecha_inicio": str(f_ini_vac), "fecha_fin": str(f_fin_vac),
                        "dias_tomados": dias_calc, "observacion": obs_vac,
                        "fecha_registro": obtener_ahora_peru().strftime("%Y-%m-%d %H:%M:%S"), "registrado_por": user_actual,
                        "fecha_recuperacion": fecha_recup_val, "horario_recuperacion": horario_recup_val,
                        "estado_recuperacion": estado_recup_val
                    }
                    st.session_state.vacaciones = pd.concat([pd.DataFrame([nuevo_row_vac]), st.session_state.vacaciones], ignore_index=True)
                    st.toast(f"{tipo_vac_sel} registrado(a) para {colab_vac_sel} ({dias_calc} día(s))")
                    time.sleep(0.3)
                    st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("##### Saldo Vacacional por Colaborador (solo personal en planilla)")

    filas_saldo = []
    filas_no_planilla = []
    for _, r_emp_v in st.session_state.empleados[st.session_state.empleados["estado"].astype(str).str.lower() == "activo"].iterrows():
        en_pl = str(r_emp_v.get("en_planilla", "Sí")) or "Sí"
        saldo_info = calcular_saldo_vacacional(r_emp_v["nombre"], r_emp_v.get("fecha_inicio", ""), st.session_state.vacaciones, en_planilla=en_pl)
        if saldo_info["aplica"]:
            filas_saldo.append({
                "Colaborador": r_emp_v["nombre"],
                "Días Generados": saldo_info["dias_generados"],
                "Días Gozados": saldo_info["dias_gozados"],
                "Saldo Disponible": saldo_info["saldo_disponible"]
            })
        else:
            filas_no_planilla.append(r_emp_v["nombre"])

    if filas_saldo:
        df_saldo_vac = pd.DataFrame(filas_saldo)
        st.dataframe(
            df_saldo_vac,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Días Generados": st.column_config.NumberColumn(format="%.1f días"),
                "Días Gozados": st.column_config.NumberColumn(format="%.1f días"),
                "Saldo Disponible": st.column_config.NumberColumn(format="%.1f días"),
            }
        )
        st.download_button("Exportar Saldos a Excel", to_excel(df_saldo_vac), "Saldos_Vacacionales.xlsx", use_container_width=True)
    else:
        st.info("No hay colaboradores activos en planilla con beneficio vacacional aplicable.")

    if filas_no_planilla:
        st.caption(f"⚪ No están en planilla (sin beneficio vacacional): {', '.join(filas_no_planilla)}")

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("##### Permisos de Salud Pendientes de Recuperar")

    if not st.session_state.vacaciones.empty:
        df_pend_recup = st.session_state.vacaciones[
            (st.session_state.vacaciones["tipo"] == "Permiso de Salud (a recuperar)") &
            (st.session_state.vacaciones["estado_recuperacion"] != "Recuperado")
        ]
    else:
        df_pend_recup = pd.DataFrame()

    if not df_pend_recup.empty:
        for idx_pr, r_pr in df_pend_recup.iterrows():
            with st.container(border=True):
                pr1, pr2 = st.columns([3, 1])
                with pr1:
                    st.markdown(f"**{r_pr['nombre']}** — Permiso del **{r_pr['fecha_inicio']}**")
                    st.caption(f"Recuperar el **{r_pr['fecha_recuperacion']}**, horario: **{r_pr['horario_recuperacion'] or 'No especificado'}**")
                with pr2:
                    if st.button("Marcar Recuperado", key=f"recup_btn_{idx_pr}", use_container_width=True):
                        st.session_state.vacaciones.at[idx_pr, "estado_recuperacion"] = "Recuperado"
                        actualizar_hoja_completa("Vacaciones", st.session_state.vacaciones)
                        registrar_auditoria("Marcar Permiso Recuperado", "Vacaciones", f"{r_pr['nombre']} — recuperación del {r_pr['fecha_recuperacion']}")
                        st.toast("Marcado como recuperado")
                        time.sleep(0.3)
                        st.rerun()
    else:
        st.success("No hay permisos de salud pendientes de recuperación.")

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("##### Historial de Descansos Registrados")
    if not st.session_state.vacaciones.empty:
        st.dataframe(
            st.session_state.vacaciones.sort_values("fecha_registro", ascending=False),
            use_container_width=True,
            hide_index=True
        )
        st.download_button("Exportar Historial a Excel", to_excel(st.session_state.vacaciones), "Historial_Vacaciones.xlsx", use_container_width=True)

        with st.expander("Eliminar Registro de Descanso"):
            opciones_vac_del = [f"{i} | {r['nombre']} | {r['tipo']} | {r['fecha_inicio']} a {r['fecha_fin']}" for i, r in st.session_state.vacaciones.iterrows()]
            sel_vac_del = st.selectbox("Seleccionar Registro a Eliminar", opciones_vac_del, key="vac_del_sel")
            confirm_vac_del = st.checkbox("Confirmar eliminación", key="vac_del_confirm")
            if st.button("Eliminar Registro", type="primary", use_container_width=True, key="vac_del_btn"):
                if confirm_vac_del:
                    idx_vac_del = int(sel_vac_del.split(" | ")[0])
                    row_vac_del = st.session_state.vacaciones.loc[idx_vac_del]
                    st.session_state.vacaciones = st.session_state.vacaciones.drop(idx_vac_del).reset_index(drop=True)
                    actualizar_hoja_completa("Vacaciones", st.session_state.vacaciones)
                    registrar_auditoria("Eliminar Registro de Descanso", "Vacaciones", f"{row_vac_del['nombre']} — {row_vac_del['tipo']} ({row_vac_del['fecha_inicio']} a {row_vac_del['fecha_fin']})")
                    st.toast("Registro eliminado correctamente")
                    time.sleep(0.3)
                    st.rerun()
                else:
                    st.warning("Marca la casilla de confirmación antes de eliminar.")
    else:
        st.info("Sin descansos registrados todavía.")

elif choice == "Mis Vacaciones":
    st.markdown("""
        <div class="market-header">
            <h1>Mi Saldo de Vacaciones</h1>
            <p>Consulta tus días generados, gozados y disponibles</p>
        </div>
    """, unsafe_allow_html=True)

    fila_mi_emp = st.session_state.empleados[st.session_state.empleados["nombre"] == user_actual]
    fecha_ingreso_mi = fila_mi_emp.iloc[0].get("fecha_inicio", "") if not fila_mi_emp.empty else ""
    en_planilla_mi = str(fila_mi_emp.iloc[0].get("en_planilla", "Sí")) if not fila_mi_emp.empty else "Sí"

    mi_saldo = calcular_saldo_vacacional(user_actual, fecha_ingreso_mi, st.session_state.vacaciones, en_planilla=en_planilla_mi)

    if not mi_saldo["aplica"]:
        st.warning("No estás registrado en planilla formal, por lo que no acumulas beneficio vacacional en el sistema. Si tienes dudas sobre tu situación laboral, consulta con administración.")
    else:
        mv1, mv2, mv3 = st.columns(3)
        with mv1:
            st.markdown(f'<div class="info-card"><div class="info-label">Días Generados</div><div class="info-value">{mi_saldo["dias_generados"]}</div></div>', unsafe_allow_html=True)
        with mv2:
            st.markdown(f'<div class="info-card"><div class="info-label">Días Gozados</div><div class="info-value">{mi_saldo["dias_gozados"]}</div></div>', unsafe_allow_html=True)
        with mv3:
            st.markdown(f'<div class="info-card"><div class="info-label">Saldo Disponible</div><div class="info-value" style="color:#00A959;">{mi_saldo["saldo_disponible"]}</div></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("##### Mi Historial de Descansos y Permisos")
    if not st.session_state.vacaciones.empty:
        df_mis_vac = st.session_state.vacaciones[st.session_state.vacaciones["nombre"] == user_actual]
        if not df_mis_vac.empty:
            st.dataframe(
                df_mis_vac[["tipo", "fecha_inicio", "fecha_fin", "dias_tomados", "fecha_recuperacion", "horario_recuperacion", "estado_recuperacion", "observacion"]].sort_values("fecha_inicio", ascending=False),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("Aún no tienes descansos registrados.")
    else:
        st.info("Aún no tienes descansos registrados.")

elif choice == "Analítica (BI)":
    st.markdown("""
        <div class="market-header">
            <h1>Analítica y Business Intelligence</h1>
            <p>Indicadores ejecutivos para la toma de decisiones</p>
        </div>
    """, unsafe_allow_html=True)

    tab_bi1, tab_bi2, tab_bi3 = st.tabs(["💰 Costo de Planilla", "🔄 Rotación de Personal", "⏰ Tendencia de Puntualidad"])

    with tab_bi1:
        st.markdown("##### Evolución del Costo de Planilla (Boletas Guardadas)")
        if not st.session_state.boletas_historial.empty:
            df_bh = st.session_state.boletas_historial.copy()
            df_bh["neto_pagar"] = pd.to_numeric(df_bh["neto_pagar"], errors="coerce").fillna(0)
            df_bh["periodo_bi"] = df_bh["mes"].astype(str) + " " + df_bh["anio"].astype(str)
            resumen_mes = df_bh.groupby("periodo_bi")["neto_pagar"].sum()
            st.bar_chart(resumen_mes)
            st.metric("Costo Total Histórico Registrado", f"S/. {df_bh['neto_pagar'].sum():.2f}")
            st.dataframe(df_bh.sort_values("fecha_emision", ascending=False), use_container_width=True, hide_index=True)
            st.download_button("Exportar Historial de Boletas a Excel", to_excel(df_bh), "Boletas_Historial.xlsx", use_container_width=True)
        else:
            st.info("Aún no hay boletas guardadas en el historial. Ve a 'Boletas de Pago', genera una boleta y usa el botón 'Guardar esta Boleta en el Historial'.")

    with tab_bi2:
        st.markdown("##### Altas y Bajas de Personal por Mes")
        df_emp_bi = st.session_state.empleados.copy()
        altas_por_mes = {}
        bajas_por_mes = {}
        for _, r_bi in df_emp_bi.iterrows():
            f_alta = _parsear_fecha_nac_cumple(r_bi.get("fecha_inicio", ""))
            if f_alta:
                key_a = f_alta.strftime("%Y-%m")
                altas_por_mes[key_a] = altas_por_mes.get(key_a, 0) + 1
            f_baja = _parsear_fecha_nac_cumple(r_bi.get("fecha_cese", ""))
            if f_baja:
                key_b = f_baja.strftime("%Y-%m")
                bajas_por_mes[key_b] = bajas_por_mes.get(key_b, 0) + 1

        meses_todos_bi = sorted(set(list(altas_por_mes.keys()) + list(bajas_por_mes.keys())))
        if meses_todos_bi:
            df_rot = pd.DataFrame({
                "Altas": [altas_por_mes.get(m, 0) for m in meses_todos_bi],
                "Bajas": [bajas_por_mes.get(m, 0) for m in meses_todos_bi]
            }, index=meses_todos_bi)
            st.bar_chart(df_rot)
            total_activos_bi = len(df_emp_bi[df_emp_bi["estado"].astype(str).str.lower() == "activo"])
            total_bajas_bi = sum(bajas_por_mes.values())
            r1, r2 = st.columns(2)
            r1.metric("Colaboradores Activos Hoy", total_activos_bi)
            r2.metric("Total de Bajas Históricas", total_bajas_bi)
        else:
            st.info("No hay suficientes datos de fechas de ingreso/cese para calcular rotación.")

    with tab_bi3:
        st.markdown("##### Tardanzas Totales por Mes (Todos los Colaboradores)")
        if not st.session_state.asistencia.empty:
            df_asist_bi = st.session_state.asistencia.copy()
            df_asist_bi["fecha_dt_bi"] = pd.to_datetime(df_asist_bi["fecha"], errors="coerce")
            df_asist_bi = df_asist_bi.dropna(subset=["fecha_dt_bi"])
            df_asist_bi["periodo_bi"] = df_asist_bi["fecha_dt_bi"].dt.strftime("%Y-%m")

            tardanzas_por_mes = {}
            for periodo_m, grupo_m in df_asist_bi.groupby("periodo_bi"):
                total_tard_mes = 0
                for nom_m in grupo_m["nombre"].unique():
                    met_m = calcular_metricas_puntualidad(grupo_m, nom_m)
                    total_tard_mes += met_m["tardanzas"]
                tardanzas_por_mes[periodo_m] = total_tard_mes

            if tardanzas_por_mes:
                st.bar_chart(pd.Series(tardanzas_por_mes, name="Tardanzas"))
            else:
                st.info("No hay tardanzas registradas todavía.")
        else:
            st.info("No hay datos de asistencia registrados.")

elif choice == "Onboarding / Offboarding":
    st.markdown("""
        <div class="market-header">
            <h1>Onboarding y Offboarding Estructurado</h1>
            <p>Checklist de incorporación y salida de colaboradores</p>
        </div>
    """, unsafe_allow_html=True)

    if st.session_state.checklist.empty:
        st.info("No hay checklists generados todavía. Se crean automáticamente al registrar un nuevo colaborador o al dar de baja a uno existente.")
    else:
        colabs_con_checklist = sorted(st.session_state.checklist["nombre"].unique().tolist())
        colab_chk_sel = st.selectbox("Seleccionar Colaborador", colabs_con_checklist, key="chk_colab_sel")

        df_chk_colab = st.session_state.checklist[st.session_state.checklist["nombre"] == colab_chk_sel]

        for tipo_chk in ["Onboarding", "Offboarding"]:
            df_tipo_chk = df_chk_colab[df_chk_colab["tipo"] == tipo_chk]
            if df_tipo_chk.empty:
                continue

            completados = len(df_tipo_chk[df_tipo_chk["estado"] == "Completado"])
            total_items = len(df_tipo_chk)
            pct_chk = int((completados / total_items) * 100) if total_items else 0

            with st.container(border=True):
                icono_chk = "🚀" if tipo_chk == "Onboarding" else "🚪"
                st.markdown(f"##### {icono_chk} Checklist de {tipo_chk} ({completados}/{total_items})")
                st.progress(pct_chk / 100.0)

                for idx_chk, row_chk in df_tipo_chk.iterrows():
                    marcado = row_chk["estado"] == "Completado"
                    nuevo_marcado = st.checkbox(row_chk["tarea"], value=marcado, key=f"chk_{row_chk['id_item']}")
                    if nuevo_marcado != marcado:
                        st.session_state.checklist.at[idx_chk, "estado"] = "Completado" if nuevo_marcado else "Pendiente"
                        st.session_state.checklist.at[idx_chk, "fecha_completado"] = obtener_ahora_peru().strftime("%Y-%m-%d %H:%M:%S") if nuevo_marcado else ""
                        actualizar_hoja_completa("Checklist", st.session_state.checklist)
                        registrar_auditoria(f"Actualizar Ítem de {tipo_chk}", "Checklist", f"{colab_chk_sel}: '{row_chk['tarea']}' → {'Completado' if nuevo_marcado else 'Pendiente'}")
                        st.rerun()

        st.markdown("<br>", unsafe_allow_html=True)
        st.download_button("Exportar Checklists a Excel", to_excel(st.session_state.checklist), "Checklists.xlsx", use_container_width=True)

elif choice == "Auditoría y Configuración":
    st.markdown("""
        <div class="market-header">
            <h1>Auditoría y Configuración del Sistema</h1>
            <p>Trazabilidad de cambios y ajustes de seguridad</p>
        </div>
    """, unsafe_allow_html=True)

    tab_aud, tab_cfg = st.tabs(["📋 Registro de Auditoría", "⚙️ Configuración"])

    with tab_aud:
        if not st.session_state.auditoria.empty:
            df_aud = st.session_state.auditoria.copy()
            fa1, fa2 = st.columns(2)
            with fa1:
                usuarios_aud_disp = ["Todos"] + sorted(df_aud["usuario"].dropna().unique().tolist())
                usuario_aud_filtro = st.selectbox("Filtrar por Usuario", usuarios_aud_disp)
            with fa2:
                acciones_aud_disp = ["Todas"] + sorted(df_aud["accion"].dropna().unique().tolist())
                accion_aud_filtro = st.selectbox("Filtrar por Acción", acciones_aud_disp)

            if usuario_aud_filtro != "Todos":
                df_aud = df_aud[df_aud["usuario"] == usuario_aud_filtro]
            if accion_aud_filtro != "Todas":
                df_aud = df_aud[df_aud["accion"] == accion_aud_filtro]

            st.dataframe(df_aud.sort_values("fecha_hora", ascending=False), use_container_width=True, hide_index=True)
            st.download_button("Exportar Auditoría a Excel", to_excel(df_aud), "Auditoria.xlsx", use_container_width=True)
        else:
            st.info("Aún no hay eventos registrados en la auditoría.")

    with tab_cfg:
        cfg_actual = st.session_state.config_sistema

        st.markdown("##### 🔒 Sesión")
        st.caption(f"Las sesiones se cierran automáticamente tras 30 minutos de inactividad o 10 horas desde el inicio de sesión. Sesión actual iniciada: {datetime.fromtimestamp(st.session_state.login_timestamp).strftime('%d/%m/%Y %H:%M:%S')}.")

# --- PIE DE PÁGINA (FOOTER ESTILO WEB/APP) ---
st.markdown("""
<div class="app-footer">
    Desarrollado por <strong>Humberto Atoche Obeso</strong><br>
    <strong>Tiendas Premium E.I.R.L.</strong> • RUC 20612107786<br>
    Todos los derechos reservados
</div>
""", unsafe_allow_html=True)
