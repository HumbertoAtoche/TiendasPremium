import re
import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta, time as dt_time
import calendar
import zoneinfo  # Manejo de zona horaria de Perú (UTC-5)
import io
import time
import gspread
# --- INTENTO DE IMPORTAR REPORTLAB PARA PDF (CON FALLBACK INTEGRADO) ---
try:
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, Image
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
""", unsafe_allow_html=True)

# =========================================================
# SISTEMA DE DISEÑO TIENDAS PREMIUM — FASE 1
# Capa visual que se superpone al CSS anterior. No altera lógica.
# =========================================================
st.markdown("""
<style>
:root{
  --tp-red:#EC3237; --tp-red-dk:#C9262B; --tp-red-soft:#FDECEC;
  --tp-ink:#0F172A; --tp-ink-2:#334155; --tp-mute:#64748B;
  --tp-bg:#F3F4F7; --tp-surface:#FFFFFF; --tp-line:#E3E6EC;
  --tp-ok:#0B8F57; --tp-ok-soft:#E3F6EC; --tp-warn:#B45309; --tp-warn-soft:#FEF3C7;
  --tp-bad:#B42318; --tp-bad-soft:#FEE4E2; --tp-info:#1D4ED8; --tp-info-soft:#E0EAFF;
  --tp-r-sm:10px; --tp-r-md:14px; --tp-r-lg:20px;
  --tp-sh-1:0 1px 2px rgba(15,23,42,.05),0 1px 3px rgba(15,23,42,.04);
  --tp-sh-2:0 8px 24px -8px rgba(15,23,42,.14);
}
.stApp{background:var(--tp-bg);}
.block-container{max-width:1240px;padding-top:4.2rem;padding-bottom:3rem;}
#MainMenu,footer,[data-testid="stDecoration"],[data-testid="stAppDeployButton"],[data-testid="stMainMenu"],.stDeployButton{visibility:hidden;display:none;}
header[data-testid="stHeader"]{background:transparent!important;}
[data-testid="stToolbar"]{visibility:visible!important;display:flex!important;}
/* Botón para abrir el menú de vistas (siempre visible) */
[data-testid="stExpandSidebarButton"],[data-testid="stSidebarCollapsedControl"],[data-testid="collapsedControl"]{
  display:flex!important;visibility:visible!important;opacity:1!important;z-index:1000;
  position:fixed;top:12px;left:12px;width:46px;height:46px;align-items:center;justify-content:center;
  background:var(--tp-ink)!important;border-radius:14px;box-shadow:var(--tp-sh-2);}
[data-testid="stExpandSidebarButton"] *,[data-testid="stSidebarCollapsedControl"] *,[data-testid="collapsedControl"] *{color:#fff!important;fill:#fff!important;}
[data-testid="stExpandSidebarButton"]:hover,[data-testid="stSidebarCollapsedControl"]:hover{background:var(--tp-red)!important;}
[data-testid="stSidebarCollapseButton"] button,[data-testid="stSidebarCollapseButton"] *{color:#AEB8CC!important;}
h1,h2,h3,h4,h5{color:var(--tp-ink);letter-spacing:-.01em;}
h5{font-size:1.02rem!important;font-weight:650!important;margin:.4rem 0 .6rem!important;}
[data-testid="stMetricValue"],.info-value,.tp-kpi-val{font-variant-numeric:tabular-nums;}
:focus-visible{outline:3px solid rgba(236,50,55,.35)!important;outline-offset:2px;border-radius:8px;}

/* Encabezado de página */
.market-header{position:relative;background:var(--tp-surface);border:1px solid var(--tp-line);border-left:1px solid var(--tp-line);
  border-radius:var(--tp-r-lg);padding:22px 26px 20px;margin-bottom:22px;box-shadow:var(--tp-sh-1);}
.market-header::before{content:"";position:absolute;left:26px;top:0;width:36px;height:4px;background:var(--tp-red);border-radius:0 0 4px 4px;}
.market-header h1{font-size:1.45rem!important;font-weight:700!important;margin-top:6px!important;color:var(--tp-ink)!important;}
.market-header p{font-size:.9rem;color:var(--tp-mute);}

/* Tarjetas y contenedores */
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"]){border-radius:var(--tp-r-md);}
div[data-testid="stVerticalBlockBorderWrapper"]{border-color:var(--tp-line)!important;background:var(--tp-surface);box-shadow:var(--tp-sh-1);}
.info-card,.cal-card{border-radius:var(--tp-r-md)!important;border:1px solid var(--tp-line)!important;box-shadow:var(--tp-sh-1);}
div[data-testid="stForm"],div[data-testid="stExpander"]{border-radius:var(--tp-r-md)!important;border:1px solid var(--tp-line)!important;box-shadow:var(--tp-sh-1)!important;}
[data-testid="stMetric"]{background:var(--tp-surface);border:1px solid var(--tp-line);border-radius:var(--tp-r-md);padding:16px 18px;box-shadow:var(--tp-sh-1);}
[data-testid="stMetricLabel"] p{font-size:.78rem!important;font-weight:600;color:var(--tp-mute)!important;}
[data-testid="stMetricValue"]{font-weight:700;color:var(--tp-ink);}

/* Botones */
.stButton>button,.stDownloadButton>button,.stFormSubmitButton>button{min-height:46px;border-radius:var(--tp-r-sm)!important;font-weight:600!important;font-size:.9rem!important;
  box-shadow:var(--tp-sh-1);transition:transform .12s ease,box-shadow .12s ease,background-color .12s ease!important;}
.stButton>button:hover{transform:translateY(-1px);box-shadow:var(--tp-sh-2);}
.stButton>button:active{transform:translateY(0) scale(.98);}
.stDownloadButton>button{background:var(--tp-surface)!important;color:var(--tp-ink)!important;border:1px solid var(--tp-line)!important;}
.stDownloadButton>button:hover{border-color:var(--tp-ink)!important;background:#F8FAFC!important;}
.btn-ingreso>button,.btn-salida>button{min-height:64px!important;font-size:1.05rem!important;border-radius:var(--tp-r-md)!important;}
.btn-ingreso>button{background:var(--tp-ok)!important;}
.btn-ingreso>button:hover{background:#087548!important;}

/* Campos */
[data-baseweb="input"],[data-baseweb="select"]>div,[data-baseweb="textarea"],.stDateInput>div>div,.stNumberInput>div>div{border-radius:var(--tp-r-sm)!important;}
[data-baseweb="input"],[data-baseweb="textarea"],[data-baseweb="select"]>div{border:1px solid var(--tp-line)!important;background:var(--tp-surface)!important;}
[data-baseweb="input"]:focus-within,[data-baseweb="textarea"]:focus-within,[data-baseweb="select"]>div:focus-within{border-color:var(--tp-red)!important;box-shadow:0 0 0 3px rgba(236,50,55,.15)!important;}
[data-testid="stWidgetLabel"] p{font-size:.82rem;font-weight:600;color:var(--tp-ink-2);}

/* Pestañas */
.stTabs [data-baseweb="tab-list"]{gap:6px;overflow-x:auto;scrollbar-width:none;border-bottom:1px solid var(--tp-line);}
.stTabs [data-baseweb="tab-list"]::-webkit-scrollbar{display:none;}
.stTabs [data-baseweb="tab"]{height:46px;padding:0 14px;font-weight:600;color:var(--tp-mute);white-space:nowrap;}
.stTabs [aria-selected="true"]{color:var(--tp-ink)!important;}
.stTabs [data-baseweb="tab-highlight"]{background:var(--tp-red)!important;height:3px;border-radius:3px;}

/* Tablas, alertas, progreso */
[data-testid="stDataFrame"]{border:1px solid var(--tp-line);border-radius:var(--tp-r-md);overflow:hidden;box-shadow:var(--tp-sh-1);}
[data-testid="stAlert"]{border-radius:var(--tp-r-md);border:1px solid var(--tp-line);}
.stProgress>div>div>div>div{background:var(--tp-red)!important;border-radius:999px;}
.stProgress>div>div>div{border-radius:999px;}

/* Barra lateral como navegación */
[data-testid="stSidebar"]{background:linear-gradient(180deg,#0F172A 0%,#111C33 100%)!important;border-right:none;}
[data-testid="stSidebar"] [data-testid="stWidgetLabel"]{display:none;}
[data-testid="stSidebar"] [role="radiogroup"]{gap:2px;}
[data-testid="stSidebar"] [role="radiogroup"] label{position:relative;padding:10px 14px 10px 16px;border-radius:12px;cursor:pointer;transition:background .12s ease;}
[data-testid="stSidebar"] [role="radiogroup"] label>div:first-child{display:none;}
[data-testid="stSidebar"] [role="radiogroup"] label p{font-size:.88rem;font-weight:500;color:#AEB8CC!important;}
[data-testid="stSidebar"] [role="radiogroup"] label:hover{background:rgba(255,255,255,.06);}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked){background:rgba(236,50,55,.16);}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked)::before{content:"";position:absolute;left:0;top:10px;bottom:10px;width:3px;border-radius:3px;background:var(--tp-red);}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p{color:#FFFFFF!important;font-weight:650;}
.tp-user{display:flex;align-items:center;gap:12px;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.08);padding:12px;border-radius:14px;margin-bottom:18px;}
.tp-user b{display:block;font-size:.84rem;color:#fff!important;line-height:1.25;}
.tp-user span{font-size:.7rem;color:#8EA0BE!important;}
.btn-logout>button{border-radius:12px!important;border:1px solid rgba(255,255,255,.18)!important;box-shadow:none!important;}

/* Componentes reutilizables */
.tp-avatar{flex:0 0 auto;width:40px;height:40px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;
  background:var(--tp-red);color:#fff!important;font-weight:700;font-size:.85rem;letter-spacing:.02em;}
.tp-chip{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border-radius:999px;font-size:.74rem;font-weight:650;line-height:1.5;}
.tp-chip::before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor;}
.tp-chip.ok{background:var(--tp-ok-soft);color:var(--tp-ok);} .tp-chip.warn{background:var(--tp-warn-soft);color:var(--tp-warn);}
.tp-chip.bad{background:var(--tp-bad-soft);color:var(--tp-bad);} .tp-chip.info{background:var(--tp-info-soft);color:var(--tp-info);}
.tp-chip.neutral{background:#EEF1F5;color:var(--tp-ink-2);}
.tp-kpi{background:var(--tp-surface);border:1px solid var(--tp-line);border-radius:var(--tp-r-md);padding:16px 18px;box-shadow:var(--tp-sh-1);}
.tp-kpi-lbl{font-size:.78rem;font-weight:600;color:var(--tp-mute);}
.tp-kpi-val{font-size:1.7rem;font-weight:700;color:var(--tp-ink);margin-top:2px;}
.tp-kpi-sub{font-size:.78rem;color:var(--tp-mute);margin-top:2px;}
.app-footer{margin-top:40px;padding:22px 0;border-top:1px solid var(--tp-line);color:var(--tp-mute);font-size:.78rem;line-height:1.7;text-align:center;}

/* Pantallas medianas y celulares */
@media (max-width:900px){
  .block-container{padding:4.2rem .9rem 5rem;}
  .market-header{padding:18px 18px 16px;border-radius:var(--tp-r-md);margin-bottom:16px;}
  .market-header::before{left:18px;}
  .market-header h1{font-size:1.2rem!important;}
}
@media (max-width:640px){
  html,body,input,select,textarea{font-size:16px;}
  [data-testid="stHorizontalBlock"]{gap:.75rem!important;}
  .stButton>button,.stDownloadButton>button{min-height:50px;width:100%;}
  .btn-ingreso>button,.btn-salida>button{min-height:70px!important;}
  [data-testid="stMetric"],.tp-kpi{padding:14px 16px;}
  .cal-card{overflow-x:auto;-webkit-overflow-scrolling:touch;padding:14px!important;}
  .cal-table{min-width:540px;}
  .boleta-container{padding:16px!important;overflow-x:auto;}
  [data-testid="stDataFrame"]{overflow-x:auto;}
  .stTabs [data-baseweb="tab"]{padding:0 10px;font-size:.84rem;}
}
@supports (padding:max(0px)){.block-container{padding-bottom:max(3rem,env(safe-area-inset-bottom));}}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important;}}
</style>
""", unsafe_allow_html=True)

import streamlit.components.v1 as components
st.markdown("""
<style>
/* Barra lateral clara */
[data-testid="stSidebar"]{background:#FFFFFF!important;border-right:1px solid var(--tp-line)!important;}
[data-testid="stSidebar"] *{color:var(--tp-ink)!important;}
[data-testid="stSidebar"] [role="radiogroup"] label>div:not(:has([data-testid="stMarkdownContainer"])){display:none!important;}
[data-testid="stSidebar"] [role="radiogroup"] label p{color:var(--tp-ink-2)!important;font-weight:550;}
[data-testid="stSidebar"] [role="radiogroup"] label:hover{background:#F3F4F7;}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked){background:var(--tp-red-soft);}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p{color:var(--tp-red-dk)!important;font-weight:700;}
[data-testid="stSidebarCollapseButton"] *{color:var(--tp-mute)!important;}
.tp-user{background:#F6F7FA;border:1px solid var(--tp-line);}
.tp-user b{color:var(--tp-ink)!important;} .tp-user span{color:var(--tp-mute)!important;}
[data-testid="stSidebar"] .tp-avatar{color:#fff!important;}
.tp-avatar{width:46px;height:46px;object-fit:cover;box-shadow:0 0 0 2px #fff,0 0 0 4px var(--tp-red);}
.tp-brand{padding:2px 2px 16px;} .tp-brand-name{font-weight:800;font-size:1rem;letter-spacing:-.01em;}
[data-testid="stSidebar"] .tp-brand-name span{color:var(--tp-red)!important;} .tp-brand-sub{font-size:.72rem;color:var(--tp-mute)!important;}
.btn-logout>button{background:#fff!important;border:1px solid var(--tp-line)!important;}
.btn-logout>button:hover{background:var(--tp-red-soft)!important;border-color:var(--tp-red)!important;}
/* Marcación: tarjeta de estado y lista */
.tp-hero{box-sizing:border-box;min-height:132px;background:var(--tp-surface);border:1px solid var(--tp-line);border-radius:var(--tp-r-lg);padding:18px 20px;box-shadow:var(--tp-sh-1);}
.tp-hero-top{display:flex;gap:14px;align-items:center;margin-bottom:16px;}
.tp-hero-hi{font-weight:700;font-size:1.08rem;margin-bottom:5px;}
.tp-prog-lbl{display:flex;justify-content:space-between;font-size:.76rem;color:var(--tp-mute);font-weight:600;margin-bottom:6px;}
.tp-prog{height:8px;background:#EEF1F5;border-radius:999px;overflow:hidden;}
.tp-prog i{display:block;height:100%;background:linear-gradient(90deg,var(--tp-red),#F26B6F);border-radius:999px;}
.tp-row{display:flex;align-items:center;gap:12px;background:var(--tp-surface);border:1px solid var(--tp-line);border-radius:14px;padding:12px 14px;margin-bottom:8px;}
.tp-row-time{font-weight:700;font-variant-numeric:tabular-nums;min-width:48px;}
.tp-row-main{flex:1;min-width:0;} .tp-row-main b{display:block;font-size:.9rem;}
.tp-row-main span{display:block;font-size:.78rem;color:var(--tp-mute);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.tp-chips{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end;}
/* Barra inferior (celular) */
.st-key-tp_bottomnav{display:none;}
@media (max-width:900px){
  .st-key-tp_bottomnav{display:block;position:fixed;left:0;right:0;bottom:0;z-index:999;background:rgba(255,255,255,.96);backdrop-filter:blur(10px);
    border-top:1px solid var(--tp-line);padding:6px 8px calc(6px + env(safe-area-inset-bottom,0px));box-shadow:0 -8px 24px -12px rgba(15,23,42,.25);}
  .st-key-tp_bottomnav [data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important;gap:4px!important;}
  .st-key-tp_bottomnav [data-testid="stColumn"],.st-key-tp_bottomnav [data-testid="column"]{min-width:0!important;flex:1 1 0!important;width:auto!important;}
  .st-key-tp_bottomnav button{background:transparent!important;color:var(--tp-mute)!important;box-shadow:none!important;border:none!important;min-height:56px!important;padding:4px 2px!important;border-radius:12px!important;}
  .st-key-tp_bottomnav button>div{display:flex;flex-direction:column;align-items:center;gap:2px;}
  .st-key-tp_bottomnav button p{font-size:.68rem!important;font-weight:650!important;margin:0;color:inherit!important;}
  .st-key-tp_bottomnav button[kind="primary"],.st-key-tp_bottomnav [data-testid="stBaseButton-primary"]{background:var(--tp-red-soft)!important;color:var(--tp-red-dk)!important;}
  .st-key-tp_bottomnav button:hover{transform:none!important;}
  .tp-row{padding:10px 12px;}
}
</style>
""", unsafe_allow_html=True)

@st.cache_data(show_spinner=False, ttl=300)
def ui_foto_uri(dni, foto_nom=""):
    """Foto del colaborador desde la carpeta fotos/ (la misma de la ficha personal)."""
    cands = []
    if str(foto_nom).strip() not in ("", "nan", "None"):
        cands.append(str(foto_nom).strip())
    cands += [f"{dni}.{e}" for e in ("png", "jpg", "jpeg", "webp")]
    for base in (BASE_DIR, os.getcwd()):
        for c in cands:
            ruta = os.path.join(base, "fotos", c)
            if os.path.isfile(ruta):
                try:
                    mime = mimetypes.guess_type(ruta)[0] or "image/png"
                    with open(ruta, "rb") as f:
                        return f"data:{mime};base64,{base64.b64encode(f.read()).decode('ascii')}"
                except Exception:
                    pass
    return ""

import html as _html
st.markdown("""
<style>
/* Ajustes finales: botón de menú, cerrar sesión y opciones */
[data-testid="stSidebar"] [role="radiogroup"] label>*:not(input):not([data-testid="stMarkdownContainer"]):not(:has([data-testid="stMarkdownContainer"])){display:none!important;}
[data-testid="stSidebar"] .stButton>button{background:#fff!important;border:1.5px solid var(--tp-red)!important;box-shadow:none!important;}
[data-testid="stSidebar"] .stButton>button *{color:var(--tp-red)!important;font-weight:650;}
[data-testid="stSidebar"] .stButton>button:hover{background:var(--tp-red)!important;}
[data-testid="stSidebar"] .stButton>button:hover *{color:#fff!important;}
[data-testid="stExpandSidebarButton"],[data-testid="stSidebarCollapsedControl"],[data-testid="collapsedControl"]{background:#fff!important;border:1.5px solid var(--tp-red)!important;}
[data-testid="stExpandSidebarButton"] *,[data-testid="stSidebarCollapsedControl"] *,[data-testid="collapsedControl"] *{color:var(--tp-red)!important;fill:var(--tp-red)!important;}
[data-testid="stExpandSidebarButton"] button,[data-testid="stSidebarCollapsedControl"] button{background:transparent!important;}
[data-testid="stExpandSidebarButton"]:hover,[data-testid="stSidebarCollapsedControl"]:hover,[data-testid="collapsedControl"]:hover{background:var(--tp-red)!important;}
[data-testid="stExpandSidebarButton"]:hover *,[data-testid="stSidebarCollapsedControl"]:hover *,[data-testid="collapsedControl"]:hover *{color:#fff!important;fill:#fff!important;}
/* Tarjetas de solicitud + línea de tiempo */
.tp-card{background:var(--tp-surface);border:1px solid var(--tp-line);border-radius:16px;padding:16px 18px;margin-bottom:12px;box-shadow:var(--tp-sh-1);}
.tp-card-head{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;}
.tp-card-title{font-weight:700;font-size:.95rem;} .tp-card-sub{font-size:.76rem;color:var(--tp-mute);margin-top:2px;}
.tp-card-body{font-size:.86rem;color:var(--tp-ink-2);margin:10px 0 14px;line-height:1.55;}
.tp-resp{background:#F6F7FA;border-left:3px solid var(--tp-red);border-radius:8px;padding:10px 12px;font-size:.82rem;margin-top:12px;color:var(--tp-ink-2);}
.tp-tl{display:flex;}
.tp-tl-step{flex:1;position:relative;text-align:center;font-size:.7rem;font-weight:600;color:var(--tp-mute);}
.tp-tl-step::before{content:"";position:relative;z-index:1;display:block;width:14px;height:14px;margin:0 auto 6px;border-radius:50%;background:#fff;border:2px solid #CBD2DC;}
.tp-tl-step::after{content:"";position:absolute;top:6px;left:-50%;width:100%;height:2px;background:#CBD2DC;}
.tp-tl-step:first-child::after{display:none;}
.tp-tl-step.done{color:var(--tp-ink-2);} .tp-tl-step.done::before{background:var(--tp-ok);border-color:var(--tp-ok);} .tp-tl-step.done::after{background:var(--tp-ok);}
.tp-tl-step.now{color:var(--tp-warn);} .tp-tl-step.now::before{background:#F59E0B;border-color:#F59E0B;box-shadow:0 0 0 4px rgba(245,158,11,.2);} .tp-tl-step.now::after{background:var(--tp-ok);}
.tp-tl-step.bad{color:var(--tp-bad);} .tp-tl-step.bad::before{background:var(--tp-bad);border-color:var(--tp-bad);} .tp-tl-step.bad::after{background:var(--tp-bad);}
.tp-notif{display:flex;align-items:center;justify-content:space-between;gap:8px;background:var(--tp-warn-soft);border-radius:12px;padding:9px 12px;margin:-6px 0 14px;font-size:.78rem;font-weight:650;}
[data-testid="stSidebar"] .tp-notif,[data-testid="stSidebar"] .tp-notif *{color:var(--tp-warn)!important;}
/* Tabla en PC, tarjetas en celular */
.st-key-vista_tarjetas{display:none;}
@media (max-width:900px){.st-key-vista_tabla{display:none;}.st-key-vista_tarjetas{display:block;}}
</style>
""", unsafe_allow_html=True)

def ui_timeline(estado):
    e = str(estado).strip().lower()
    if e == "aprobado": c2, c3, t3 = "done", "done", "Aprobada"
    elif e == "rechazado": c2, c3, t3 = "done", "bad", "Rechazada"
    else: c2, c3, t3 = "now", "", "Resolución"
    return f'<div class="tp-tl"><div class="tp-tl-step done">Enviada</div><div class="tp-tl-step {c2}">En revisión</div><div class="tp-tl-step {c3}">{t3}</div></div>'

def ui_solicitud_card(r, admin=False):
    est, tipo = str(r["estado"]), str(r["tipo_solicitud"])
    chip = "warn" if est == "Pendiente" else ("ok" if est == "Aprobado" else "bad")
    if tipo == "Permiso Laboral":
        det = f"Fecha del permiso: <b>{r['fecha_permiso']}</b>"
        if str(r.get("requiere_recuperacion", "No")).strip().lower() in ["sí", "si", "yes", "true", "1"] and str(r.get("fecha_recuperacion", "")).strip():
            det += f" · Recuperación: <b>{r['fecha_recuperacion']}</b>"
    elif tipo.startswith("Trabajar Domingo"):
        det = f"Domingo a trabajar: <b>{r['fecha_permiso']}</b>"
    else:
        try: det = f"Monto solicitado: <b>S/. {float(r['monto_adelanto']):.2f}</b>"
        except Exception: det = "Adelanto de sueldo"
    resp = str(r.get("respuesta_admin", "")).strip()
    resp_html = f'<div class="tp-resp"><b>Respuesta:</b> {_html.escape(resp)}</div>' if resp else ""
    if admin:
        quien = (f'<div class="tp-op-head" style="margin:0">{ui_avatar(r["nombre"], r["dni"], "", 44)}<div><div class="tp-card-title">{_html.escape(str(r["nombre"]))}</div>'
                 f'<div class="tp-card-sub">DNI {r["dni"]} · {_html.escape(tipo)} · {r["fecha_registro"]}</div></div></div>')
    else:
        quien = f'<div><div class="tp-card-title">{_html.escape(tipo)}</div><div class="tp-card-sub">Registrada el {r["fecha_registro"]}</div></div>'
    return (f'<div class="tp-card{" flat" if admin else ""}"><div class="tp-card-head">{quien}{ui_chip(est, chip)}</div>'
            f'<div class="tp-card-body">{det}<br>{_html.escape(str(r["motivo"]))}</div>{ui_timeline(est)}{resp_html}</div>')

st.markdown("""
<style>
.tp-card.flat{border:none;box-shadow:none;padding:0;margin:0 0 8px;}
[class*="st-key-ap_"] button{background:var(--tp-ok)!important;color:#fff!important;border:none!important;}
[class*="st-key-ap_"] button:hover{background:#087548!important;}
[class*="st-key-rec_"] button{background:#fff!important;border:1.5px solid var(--tp-red)!important;}
[class*="st-key-rec_"] button *{color:var(--tp-red)!important;}
[class*="st-key-rec_"] button:hover{background:var(--tp-red-soft)!important;}
[class*="st-key-ap_"] button *{color:#fff!important;}
.tp-sec{display:flex;justify-content:space-between;align-items:center;gap:10px;margin:6px 0 16px;}
.tp-sec-title{font-size:1.12rem;font-weight:700;color:var(--tp-ink);} .tp-sec-sub{font-size:.8rem;color:var(--tp-mute);}
.tp-op-head{display:flex;align-items:center;gap:12px;margin-bottom:16px;} .tp-op-head .tp-chip{margin-left:auto;}
.tp-mgrid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px;margin-bottom:14px;}
.tp-m{background:#F6F7FA;border-radius:12px;padding:12px 14px;}
.tp-m-l{font-size:.66rem;font-weight:700;color:var(--tp-mute);text-transform:uppercase;letter-spacing:.07em;}
.tp-m-v{font-size:1.05rem;font-weight:700;margin-top:5px;color:var(--tp-ink);font-variant-numeric:tabular-nums;} .tp-m-v.pos{color:var(--tp-ok);}
.tp-m .tp-prog{margin-top:9px;height:6px;}
.tp-ngrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:10px;}
.tp-note{border:1px solid var(--tp-line);border-radius:12px;padding:12px 14px;}
.tp-note-t{font-size:.66rem;font-weight:700;color:var(--tp-mute);text-transform:uppercase;letter-spacing:.07em;margin-bottom:6px;}
.tp-note ul{margin:0;padding-left:16px;font-size:.84rem;color:var(--tp-ink-2);line-height:1.8;} .tp-note li.mute{color:var(--tp-mute);list-style:none;margin-left:-16px;}
@media (max-width:900px){.tp-mgrid{grid-template-columns:repeat(2,minmax(0,1fr));}}
</style>
""", unsafe_allow_html=True)

def ui_op_card(nombre, d, dni="", foto=""):
    e = _html.escape
    est_txt = re.sub(r"[^\w\s/-]", "", str(d["estado"])).strip() or "Sin estado"
    ch = "ok" if "turno" in est_txt.lower() else ("info" if "conclu" in est_txt.lower() else "neutral")
    m = re.search(r"(\d+)h\s*(\d+)m\s*/\s*(\d+)h\s*(\d+)m", str(d["horas_laborales_str"]))
    pct = min(100, int((int(m[1]) * 60 + int(m[2])) * 100 / max(1, int(m[3]) * 60 + int(m[4])))) if m else 0
    def kp(l, v, c=""):
        return f'<div class="tp-m"><div class="tp-m-l">{l}</div><div class="tp-m-v {c}">{v}</div></div>'
    kpis = (kp("1er ingreso", e(str(d["primer_ingreso"]))) + kp("Última salida", e(str(d["ultima_salida"]))) +
            f'<div class="tp-m"><div class="tp-m-l">Jornada base</div><div class="tp-m-v">{e(str(d["horas_laborales_str"]))}</div><div class="tp-prog"><i style="width:{pct}%"></i></div></div>' +
            kp("Horas extras", e(str(d["horas_extras_str"])), "pos" if d["minutos_extras"] > 0 else "") +
            kp("Puntualidad", ui_chip(e(re.sub(r"[^\w\s()+:.-]", "", str(d["tardanza"])).strip()), "ok" if "Puntual" in str(d["tardanza"]) else "bad")))
    li_t = "".join(f'<li><b>{e(str(t["tipo"]))} · {e(str(t["hora"]))}</b> {e(str(t["detalle"]))}</li>' for t in d["turnos_adicionales"]) or '<li class="mute">Sin marcaciones fuera de horario</li>'
    li_c = ""
    for x in d["descuadres_detalle"]:
        mv = float(x["monto"])
        li_c += f'<li><b>{e(str(x["tipo"]))}</b> {ui_chip(f"S/. {mv:.2f}", "ok" if mv >= 0 else "bad")} {e(str(x["obs"])) if x["obs"] else ""}</li>'
    li_c = li_c or '<li class="mute">Sin descuadres registrados</li>'
    notas = (f'<div class="tp-note"><div class="tp-note-t">Turnos adicionales</div><ul>{li_t}</ul></div>'
             f'<div class="tp-note"><div class="tp-note-t">Caja y descuadres</div><ul>{li_c}</ul></div>')
    if d["obs_asistencia"]:
        notas += f'<div class="tp-note"><div class="tp-note-t">Observaciones de marcación</div><ul>{"".join(f"<li>{e(str(o))}</li>" for o in d["obs_asistencia"])}</ul></div>'
    return (f'<div class="tp-card"><div class="tp-op-head">{ui_avatar(nombre, dni, foto, 48)}<div><div class="tp-card-title">{e(str(nombre))}</div>'
            f'<div class="tp-card-sub">Total trabajado: {e(str(d["tiempo_total_str"]))}</div></div>{ui_chip(est_txt, ch)}</div>'
            f'<div class="tp-mgrid">{kpis}</div><div class="tp-ngrid">{notas}</div></div>')

st.markdown("""
<style>
.tp-id{background:var(--tp-surface);border:1px solid var(--tp-line);border-radius:20px;box-shadow:var(--tp-sh-1);overflow:hidden;margin-bottom:16px;}
.tp-id-band{height:76px;background:linear-gradient(120deg,#0F172A 0%,#1E293B 58%,#EC3237 190%);}
.tp-id.off .tp-id-band{background:linear-gradient(120deg,#475569,#94A3B8);}
.tp-id-head{display:flex;gap:16px;align-items:flex-start;padding:0 20px;}
.tp-id-photo{flex:0 0 auto;width:96px;height:96px;margin-top:-44px;border-radius:20px;object-fit:cover;object-position:center top;border:4px solid #fff;box-shadow:var(--tp-sh-2);background:#EEF1F5;}
.tp-id-photo.ph{display:flex;align-items:center;justify-content:center;font-size:1.9rem;font-weight:700;color:#fff;background:var(--tp-red);}
.tp-id.off .tp-id-photo{filter:grayscale(1);}
.tp-id-who{padding-top:12px;min-width:0;} .tp-id-name{font-size:1.1rem;font-weight:700;color:var(--tp-ink);line-height:1.25;}
.tp-id-role{font-size:.82rem;color:var(--tp-mute);margin-top:2px;} .tp-id-chips{display:flex;gap:6px;margin-top:8px;flex-wrap:wrap;}
.tp-id-body{padding:18px 20px 20px;} .tp-id-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px 18px;}
.tp-f.wide{grid-column:1/-1;} .tp-f-l{font-size:.64rem;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:var(--tp-mute);}
.tp-f-v{font-size:.9rem;font-weight:600;color:var(--tp-ink);margin-top:3px;word-break:break-word;} .tp-f-v.bad{color:var(--tp-bad);}
.tp-id-sos{margin-top:16px;background:#F6F7FA;border-radius:12px;padding:11px 14px;}
a.tp-link{color:var(--tp-red);font-weight:700;text-decoration:none;} a.tp-link:hover{text-decoration:underline;}
.tp-row-main span.wrap{white-space:normal;} .tp-row-time{min-width:56px;}
@media (max-width:640px){.tp-id-grid{grid-template-columns:1fr;}.tp-id-photo{width:84px;height:84px;}}
</style>
""", unsafe_allow_html=True)

def ui_dni_foto(nombre):
    emp = st.session_state.empleados
    f = emp[emp["nombre"] == nombre]
    return (str(f.iloc[0]["dni"]), str(f.iloc[0].get("foto", ""))) if not f.empty else ("", "")

def ui_desc_card(nombre, df_c, dni="", foto=""):
    e = _html.escape
    MES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
    total = float(df_c["monto_num"].sum())
    filas = ""
    for _, r in df_c.sort_values("fecha", ascending=False).iterrows():
        mv = float(r["monto_num"]); dt = pd.to_datetime(r["fecha"], errors="coerce")
        f_corta = f"{dt.day} {MES[dt.month - 1]}" if pd.notnull(dt) else str(r["fecha"])
        obs = str(r.get("observacion", "")).strip() or "Sin motivo registrado"
        filas += (f'<div class="tp-row"><div class="tp-row-time">{f_corta}</div><div class="tp-row-main"><b>{e(str(r["tipo"]))}</b><span class="wrap">{e(obs)}</span></div>'
                  f'<div class="tp-chips">{ui_chip(("+" if mv > 0 else "") + f"S/. {mv:.2f}", "ok" if mv >= 0 else "bad")}</div></div>')
    return (f'<div class="tp-card"><div class="tp-op-head">{ui_avatar(nombre, dni, foto, 44)}<div><div class="tp-card-title">{e(str(nombre))}</div>'
            f'<div class="tp-card-sub">{len(df_c)} movimiento(s)</div></div>{ui_chip(("Balance +" if total > 0 else "Balance ") + f"S/. {total:.2f}", "ok" if total >= 0 else "bad")}</div>{filas}</div>')

def ui_rank_rows(df_r, tipo):
    out = ""
    for _, r in df_r.iterrows():
        d, f = ui_dni_foto(r["nombre"]); v = float(r["balance"])
        out += (f'<div class="tp-row">{ui_avatar(r["nombre"], d, f, 40)}<div class="tp-row-main"><b>{_html.escape(str(r["nombre"]))}</b></div>'
                f'<div class="tp-chips">{ui_chip(("+" if v > 0 else "") + f"S/. {v:.2f}", tipo)}</div></div>')
    return out

st.markdown("""
<style>
.tp-grid2{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px;margin-bottom:8px;} .tp-grid2 .tp-card{margin-bottom:0;}
.tp-saldo-n{font-size:2.1rem;font-weight:800;line-height:1.1;margin:14px 0 10px;color:var(--tp-ink);font-variant-numeric:tabular-nums;}
.tp-saldo-n span{font-size:.88rem;font-weight:600;color:var(--tp-mute);margin-left:6px;}
.tp-card.hero{padding:22px 24px;} .tp-card.hero .tp-saldo-n{font-size:2.8rem;}
.tp-prog.ok i{background:var(--tp-ok);} .tp-prog.warn i{background:#F59E0B;} .tp-prog.bad i{background:var(--tp-bad);}
[class*="st-key-recup_btn_"] button{background:var(--tp-ok)!important;border:none!important;}
[class*="st-key-recup_btn_"] button *{color:#fff!important;}
[class*="st-key-recup_btn_"] button:hover{background:#087548!important;}
</style>
""", unsafe_allow_html=True)

def ui_saldo_card(nombre, sv, dni="", foto="", hero=False):
    gen, goz, sal = float(sv["dias_generados"]), float(sv["dias_gozados"]), float(sv["saldo_disponible"])
    pct = max(0, min(100, int(sal * 100 / gen))) if gen > 0 else 0
    tono, etq = ("ok", "Saldo suficiente") if sal >= 7 else (("warn", "Saldo medio") if sal >= 3 else ("bad", "Saldo bajo"))
    return (f'<div class="tp-card{" hero" if hero else ""}"><div class="tp-op-head" style="margin-bottom:0">{ui_avatar(nombre, dni, foto, 52 if hero else 44)}'
            f'<div><div class="tp-card-title">{_html.escape(str(nombre))}</div><div class="tp-card-sub">Vacaciones · Régimen REMYPE</div></div>{ui_chip(etq, tono)}</div>'
            f'<div class="tp-saldo-n">{sal:g}<span>días disponibles</span></div><div class="tp-prog {tono}"><i style="width:{pct}%"></i></div>'
            f'<div class="tp-prog-lbl" style="margin:8px 0 0"><span>{gen:g} generados</span><span>{goz:g} gozados</span></div></div>')

def ui_vac_card(r, admin=False):
    e = _html.escape
    c = lambda k: ("" if str(r.get(k, "")).strip().lower() in ("nan", "none") else str(r.get(k, "")).strip())
    tipo, f_i, f_f = c("tipo"), c("fecha_inicio")[:10], c("fecha_fin")[:10]
    rango = f_i if f_i == f_f else f"{f_i} → {f_f}"
    dias = f"{c('dias_tomados')} día(s)"
    tchip = "info" if tipo == "Vacaciones" else ("warn" if tipo.startswith("Permiso") else "neutral")
    if admin:
        d, f = ui_dni_foto(c("nombre"))
        quien = f'<div class="tp-op-head" style="margin:0">{ui_avatar(c("nombre"), d, f, 44)}<div><div class="tp-card-title">{e(c("nombre"))}</div><div class="tp-card-sub">{rango} · {dias}</div></div></div>'
    else:
        quien = f'<div><div class="tp-card-title">{rango}</div><div class="tp-card-sub">{dias}</div></div>'
    cuerpo = e(c("observacion"))
    tl = ""
    if tipo.startswith("Permiso"):
        rec = c("estado_recuperacion") == "Recuperado"
        cuerpo += f'{"<br>" if cuerpo else ""}Recuperar el <b>{e(c("fecha_recuperacion") or "-")}</b> · {e(c("horario_recuperacion") or "horario no especificado")}'
        tl = f'<div class="tp-tl"><div class="tp-tl-step done">Permiso</div><div class="tp-tl-step {"done" if rec else "now"}">Por recuperar</div><div class="tp-tl-step {"done" if rec else ""}">Recuperado</div></div>'
    body = f'<div class="tp-card-body">{cuerpo}</div>' if cuerpo else '<div style="height:10px"></div>'
    return f'<div class="tp-card{" flat" if admin else ""}"><div class="tp-card-head">{quien}{ui_chip(e(tipo), tchip)}</div>{body}{tl}</div>'

import unicodedata

def _norm(x):
    return "".join(c for c in unicodedata.normalize("NFD", str(x).lower()) if unicodedata.category(c) != "Mn")

def _gs_hit(q, *vals):
    blob = _norm(" ".join(str(v) for v in vals))
    return all(t in blob for t in _norm(q).split())

def _limpiar_busqueda():
    st.session_state["gs_q"] = ""

def _gs_ir(dest, nombre_sol=None):
    st.session_state["nav_radio"] = dest
    st.session_state["gs_q"] = ""
    if nombre_sol:
        st.session_state["sol_busqueda"] = nombre_sol
        st.session_state["sol_estado_filtro"] = "Todos"

def _gs_titulo(txt, n):
    st.markdown(f'<div class="tp-note-t" style="margin:22px 0 10px">{txt} · {n}</div>', unsafe_allow_html=True)

def _gs_filtrar(df, q, cols):
    if df is None or df.empty:
        return pd.DataFrame()
    return df[df.apply(lambda r: _gs_hit(q, *[r.get(c, "") for c in cols]), axis=1)]

def render_busqueda(q, es_admin, dni_me, menu):
    e = _html.escape
    h1, h2 = st.columns([4, 1])
    h1.markdown(f'<div class="market-header" style="margin-bottom:8px"><h1>Resultados de búsqueda</h1><p>Buscando “{e(q)}” en {"todo el sistema" if es_admin else "tus datos"}</p></div>', unsafe_allow_html=True)
    h2.button("Limpiar búsqueda", key="gs_clear", on_click=_limpiar_busqueda, use_container_width=True)
    total = 0

    sec = [m for m in menu if _gs_hit(q, m)]
    if sec:
        total += len(sec); _gs_titulo("Ir a una sección", len(sec))
        cols = st.columns(min(len(sec), 3))
        for i, m in enumerate(sec[:6]):
            cols[i % len(cols)].button(m, key=f"gs_sec_{i}", on_click=_gs_ir, args=(m,), use_container_width=True)

    if es_admin:
        r_e = _gs_filtrar(st.session_state.empleados, q, ["nombre", "dni", "cargo"])
        if not r_e.empty:
            total += len(r_e); _gs_titulo("Colaboradores", len(r_e))
            for i, (_, r) in enumerate(r_e.head(6).iterrows()):
                act = str(r.get("estado", "")).lower() == "activo"
                c1, c2 = st.columns([4, 1])
                c1.markdown(f'<div class="tp-row">{ui_avatar(r["nombre"], r["dni"], str(r.get("foto", "")), 44)}<div class="tp-row-main"><b>{e(str(r["nombre"]))}</b><span>{e(str(r.get("cargo", "")))} · DNI {e(str(r["dni"]))}</span></div><div class="tp-chips">{ui_chip("Activo" if act else "Dado de baja", "ok" if act else "neutral")}</div></div>', unsafe_allow_html=True)
                c2.button("Ver ficha", key=f"gs_emp_{i}", on_click=_gs_ir, args=("Gestión Colaboradores",), use_container_width=True)

    sol = st.session_state.get("solicitudes")
    if sol is not None and not sol.empty and not es_admin:
        sol = sol[sol["dni"].astype(str) == str(dni_me)]
    r_s = _gs_filtrar(sol, q, ["nombre", "dni", "tipo_solicitud", "motivo", "estado", "respuesta_admin"])
    if not r_s.empty:
        r_s = r_s.sort_values("fecha_registro", ascending=False)
        total += len(r_s); _gs_titulo("Solicitudes y permisos", len(r_s))
        for _, r in r_s.head(5).iterrows():
            if es_admin:
                with ui_card_container(f"gs_s{_}"):
                    st.markdown(ui_solicitud_card(r, admin=True), unsafe_allow_html=True)
            else:
                st.markdown(ui_solicitud_card(r), unsafe_allow_html=True)
        un_solo = es_admin and r_s["nombre"].nunique() == 1
        st.button("Ver en Solicitudes" if es_admin else "Ir a mis solicitudes", key="gs_sol_go", on_click=_gs_ir,
                  args=("Solicitudes y Permisos" if es_admin else "Solicitar Permiso / Adelanto", str(r_s.iloc[0]["nombre"]) if un_solo else None))

    if es_admin:
        des = st.session_state.get("descuadres")
        if des is not None and not des.empty:
            des = des.copy(); des["monto_num"] = pd.to_numeric(des["monto"], errors="coerce").fillna(0)
            r_d = _gs_filtrar(des, q, ["nombre", "tipo", "observacion", "fecha"])
            if not r_d.empty:
                total += len(r_d); _gs_titulo("Descuadres de caja", len(r_d))
                for nom, g in list(r_d.groupby("nombre"))[:4]:
                    d_, f_ = ui_dni_foto(nom)
                    st.markdown(ui_desc_card(nom, g.head(8), d_, f_), unsafe_allow_html=True)
                st.button("Ver Auditoría de Descuadres", key="gs_des_go", on_click=_gs_ir, args=("Historial de Descuadres",))

    vac = st.session_state.get("vacaciones")
    if vac is not None and not vac.empty and not es_admin:
        vac = vac[vac["dni"].astype(str) == str(dni_me)]
    r_v = _gs_filtrar(vac, q, ["nombre", "tipo", "observacion", "fecha_inicio"])
    if not r_v.empty:
        total += len(r_v); _gs_titulo("Vacaciones y descansos", len(r_v))
        for _, r in r_v.sort_values("fecha_inicio", ascending=False).head(5).iterrows():
            if es_admin:
                with ui_card_container(f"gs_v{_}"):
                    st.markdown(ui_vac_card(r, admin=True), unsafe_allow_html=True)
            else:
                st.markdown(ui_vac_card(r), unsafe_allow_html=True)
        st.button("Ir a Vacaciones", key="gs_vac_go", on_click=_gs_ir, args=("Gestión de Vacaciones" if es_admin else "Mis Vacaciones",))

    if total == 0:
        st.markdown(f'<div class="tp-card" style="text-align:center;padding:36px 20px"><div class="tp-card-title">Sin resultados para “{e(q)}”</div><div class="tp-card-sub" style="margin-top:6px">Prueba con otro nombre, DNI o palabra, o revisa la ortografía.</div></div>', unsafe_allow_html=True)

st.markdown("""
<style>
[class*="st-key-tpc_"]{background:var(--tp-surface);border:1px solid var(--tp-line);border-radius:16px;padding:16px 18px;box-shadow:var(--tp-sh-1);margin-bottom:12px;}
</style>
""", unsafe_allow_html=True)

def ui_card_container(key):
    """Contenedor que ES la tarjeta blanca (foto, texto y botones dentro del mismo fondo)."""
    try:
        return st.container(key=f"tpc_{key}")
    except TypeError:
        return st.container(border=True)

st.markdown("""
<style>
.tp-cols{display:flex;align-items:flex-end;gap:10px;height:var(--h,220px);overflow-x:auto;padding-bottom:2px;}
.tp-col{flex:1;min-width:46px;height:100%;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;}
.tp-bars{display:flex;align-items:flex-end;justify-content:center;gap:4px;width:100%;height:calc(100% - 24px);padding-top:22px;box-sizing:border-box;border-bottom:1px solid var(--tp-line);}
.tp-bar{position:relative;flex:1;max-width:40px;border-radius:9px 9px 0 0;}
.tp-bar em{position:absolute;top:-18px;left:50%;transform:translateX(-50%);font-style:normal;font-size:.68rem;font-weight:700;color:var(--tp-ink-2);white-space:nowrap;}
.tp-col>span{font-size:.7rem;color:var(--tp-mute);margin-top:7px;white-space:nowrap;}
.tp-legs{display:flex;gap:16px;margin-top:12px;font-size:.76rem;color:var(--tp-ink-2);font-weight:600;}
.tp-leg i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;}
.tp-kpi{min-height:128px;}
.tp-hb{display:grid;grid-template-columns:minmax(80px,160px) 1fr auto;gap:12px;align-items:center;margin:11px 0;}
.tp-hb-l{font-size:.84rem;font-weight:600;color:var(--tp-ink);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.tp-hb-t{height:10px;background:#EEF1F5;border-radius:999px;overflow:hidden;} .tp-hb-t i{display:block;height:100%;border-radius:999px;}
.tp-hb-v{font-size:.82rem;font-weight:700;color:var(--tp-ink-2);font-variant-numeric:tabular-nums;}
.tp-rk{display:flex;align-items:center;gap:12px;padding:11px 0;border-bottom:1px solid #F0F2F6;} .tp-rk:last-child{border-bottom:none;}
.tp-rk-main{flex:1;min-width:0;} .tp-rk-main b{font-size:.88rem;} .tp-rk-main .tp-prog{margin-top:7px;height:6px;}
.tp-rk-pct{font-weight:800;min-width:58px;text-align:right;font-variant-numeric:tabular-nums;}
@media (max-width:640px){.tp-hb{grid-template-columns:1fr auto;}.tp-hb-t{grid-column:1/-1;order:3;}.tp-rk .tp-chips{display:none;}}
</style>
""", unsafe_allow_html=True)

_MES_ABR = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
_MESES_L = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

def _mes_a_num(v):
    t = str(v).strip()
    if t.isdigit():
        return int(t)
    n = _norm(t)
    for i, m in enumerate(_MESES_L):
        if n[:3] == _norm(m)[:3]:
            return i + 1
    return 0

def ui_mes_label(ym):
    try:
        y, m = str(ym).split("-")
        return f"{_MES_ABR[int(m) - 1]} {y[2:]}"
    except Exception:
        return str(ym)

def ui_dia_label(f):
    try:
        d = pd.to_datetime(f)
        return f"{d.day} {_MES_ABR[d.month - 1]}"
    except Exception:
        return str(f)

def ui_panel(titulo, sub, contenido):
    return f'<div class="tp-card"><div class="tp-card-title">{titulo}</div><div class="tp-card-sub">{sub}</div><div style="margin-top:16px">{contenido}</div></div>'

def ui_columnas(labels, series, alto=220, fmt="{:g}"):
    mx = max([max(v) for _, v, _ in series] + [1])
    cols = ""
    for i, l in enumerate(labels):
        barras = ""
        for n, v, c in series:
            h = max(3, int(v[i] / mx * 100)) if v[i] > 0 else 0
            barras += f'<div class="tp-bar" style="height:{h}%;background:{c}" title="{n}: {fmt.format(v[i])}"><em>{fmt.format(v[i]) if v[i] else ""}</em></div>'
        cols += f'<div class="tp-col"><div class="tp-bars">{barras}</div><span>{l}</span></div>'
    leyenda = "".join(f'<span class="tp-leg"><i style="background:{c}"></i>{n}</span>' for n, _, c in series) if len(series) > 1 else ""
    return f'<div style="--h:{alto}px"><div class="tp-cols">{cols}</div>{f"<div class=tp-legs>{leyenda}</div>" if leyenda else ""}</div>'

def ui_hbars(items, color="#EC3237", fmt="{:g}"):
    if not items:
        return '<div class="tp-card-sub">Sin datos para mostrar.</div>'
    mx = max([it[1] for it in items] + [1])
    out = ""
    for it in items:
        l, v = it[0], it[1]
        c = it[2] if len(it) > 2 else color
        fv = fmt(v) if callable(fmt) else fmt.format(v)
        out += (f'<div class="tp-hb"><div class="tp-hb-l" title="{_html.escape(str(l))}">{_html.escape(str(l))}</div>'
                f'<div class="tp-hb-t"><i style="width:{max(3, int(v / mx * 100))}%;background:{c}"></i></div><div class="tp-hb-v">{fv}</div></div>')
    return out

def ui_linea(labels, vals, color="#EC3237", fmt="{:g}", suf="", alto=230):
    n = len(vals)
    if n == 0:
        return ""
    W, H, px, top, bot = 640, alto, 34, 30, 30
    mx = max(max(vals), 1) * 1.15
    xs = [W / 2] if n == 1 else [px + (W - 2 * px) * i / (n - 1) for i in range(n)]
    ys = [H - bot - (H - top - bot) * v / mx for v in vals]
    linea = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    area = f"{xs[0]:.1f},{H - bot} {linea} {xs[-1]:.1f},{H - bot}"
    gid = f"g{abs(hash((tuple(vals), color))) % 10**7}"
    paso, txt = max(1, -(-n // 8)), ""
    for i, (x, y, v, l) in enumerate(zip(xs, ys, vals, labels)):
        txt += f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="#fff" stroke="{color}" stroke-width="2.5"><title>{l}: {fmt.format(v)}{suf}</title></circle>'
        if i % paso == 0 or i == n - 1:
            txt += (f'<text x="{x:.1f}" y="{y - 11:.1f}" text-anchor="middle" font-size="11" font-weight="700" fill="#334155">{fmt.format(v)}{suf}</text>'
                    f'<text x="{x:.1f}" y="{H - 9}" text-anchor="middle" font-size="11" fill="#64748B">{l}</text>')
    return (f'<svg viewBox="0 0 {W} {H}" width="100%" role="img"><defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{color}" stop-opacity=".28"/>'
            f'<stop offset="1" stop-color="{color}" stop-opacity="0"/></linearGradient></defs><line x1="{px - 10}" y1="{H - bot}" x2="{W - px + 10}" y2="{H - bot}" stroke="#E3E6EC"/>'
            f'<polygon points="{area}" fill="url(#{gid})"/><polyline points="{linea}" fill="none" stroke="{color}" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>{txt}</svg>')

st.markdown("""
<style>
/* Quita el espacio vacío superior: los bloques de estilo y el iframe invisible no deben ocupar lugar */
[data-testid="stElementContainer"]:has(style),.element-container:has(style),[data-testid="stElementContainer"]:has(iframe[height="0"]),.element-container:has(iframe[height="0"]){display:none!important;}
.stApp:has([data-testid="stSidebar"][aria-expanded="true"]) .block-container{padding-top:3.2rem;}
[data-testid="stToolbarActions"],[data-testid="stAppDeployButton"]{display:none!important;}
.tp-steps{margin:2px 0 14px;padding:0;list-style:none;counter-reset:paso;}
.tp-steps li{counter-increment:paso;position:relative;padding:5px 0 5px 34px;font-size:.84rem;line-height:1.45;color:var(--tp-ink-2);}
.tp-steps li::before{content:counter(paso);position:absolute;left:0;top:4px;width:23px;height:23px;border-radius:50%;background:var(--tp-red-soft);color:var(--tp-red-dk);font-weight:700;font-size:.74rem;display:flex;align-items:center;justify-content:center;}
.tp-steps-t{font-size:.7rem;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:var(--tp-mute);margin:8px 0 4px;display:flex;gap:8px;align-items:center;}
</style>
""", unsafe_allow_html=True)

@st.cache_resource(show_spinner=False)
def ui_icono_app():
    """Ícono cuadrado con fondo blanco y el logo centrado (180 px iPhone, 512 px Android)."""
    import io
    from PIL import Image, ImageDraw, ImageFont
    def _icono(sz):
        im = Image.new("RGBA", (sz, sz), (255, 255, 255, 255))
        try:
            ruta = FAVICON_PATH if os.path.exists(FAVICON_PATH) else LOGO_PATH
            lg = Image.open(ruta).convert("RGBA")
            lg.thumbnail((int(sz * 0.74), int(sz * 0.74)), Image.LANCZOS)
            im.paste(lg, ((sz - lg.width) // 2, (sz - lg.height) // 2), lg)
        except Exception:
            d = ImageDraw.Draw(im)
            d.rounded_rectangle((sz * .12, sz * .12, sz * .88, sz * .88), radius=sz * .2, fill=(236, 50, 55, 255))
            try:
                d.text((sz * .5, sz * .5), "P", fill="white", anchor="mm", font=ImageFont.load_default(size=int(sz * .5)))
            except Exception:
                pass
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    return _icono(180), _icono(512)

def ui_pwa_inyectar():
    """Pide al celular: ícono propio, nombre corto, color de marca y pantalla completa al añadir a inicio."""
    try:
        i180, i512 = ui_icono_app()
    except Exception:
        return
    js = """<script>(function(){try{
var d=window.parent.document,h=d.head;
function meta(n,c){var m=d.querySelector('meta[name="'+n+'"]');if(!m){m=d.createElement('meta');m.name=n;h.appendChild(m);}m.content=c;}
d.querySelectorAll('link[rel="apple-touch-icon"],link[rel="manifest"]').forEach(function(e){e.remove();});
var a=d.createElement('link');a.rel='apple-touch-icon';a.setAttribute('sizes','180x180');a.href='__I180__';h.appendChild(a);
meta('apple-mobile-web-app-capable','yes');meta('mobile-web-app-capable','yes');
meta('apple-mobile-web-app-title','Premium');meta('application-name','Premium');
meta('apple-mobile-web-app-status-bar-style','default');meta('theme-color','#EC3237');
var L=window.parent.location,mf={name:'Tiendas Premium',short_name:'Premium',start_url:L.origin+L.pathname,scope:L.origin+'/',display:'standalone',
background_color:'#FFFFFF',theme_color:'#EC3237',icons:[{src:'__I512__',sizes:'512x512',type:'image/png',purpose:'any'}]};
var m=d.createElement('link');m.rel='manifest';m.href='data:application/manifest+json,'+encodeURIComponent(JSON.stringify(mf));h.appendChild(m);
}catch(e){}})();</script>"""
    components.html(js.replace("__I180__", i180).replace("__I512__", i512), height=0)

def ui_guia_instalar(cont):
    ua = ""
    try:
        ua = str(st.context.headers.get("User-Agent", ""))
    except Exception:
        pass
    es_ios, es_and = any(x in ua for x in ("iPhone", "iPad", "iPod")), "Android" in ua
    ios = ('<div class="tp-steps-t">iPhone · Safari ' + (ui_chip("Tu dispositivo", "ok") if es_ios else "") + '</div><ol class="tp-steps">'
           '<li>Abre esta página en <b>Safari</b>.</li><li>Toca el botón <b>Compartir</b> (cuadro con flecha hacia arriba).</li>'
           '<li>Elige <b>Añadir a pantalla de inicio</b>.</li><li>Toca <b>Añadir</b>. Listo: aparece el ícono de Premium.</li></ol>')
    andr = ('<div class="tp-steps-t">Android · Chrome ' + (ui_chip("Tu dispositivo", "ok") if es_and else "") + '</div><ol class="tp-steps">'
            '<li>Abre esta página en <b>Chrome</b>.</li><li>Toca el menú <b>⋮</b> (arriba a la derecha).</li>'
            '<li>Elige <b>Instalar app</b> o <b>Añadir a pantalla de inicio</b>.</li><li>Confirma con <b>Instalar</b>.</li></ol>')
    with cont.expander("Instalar en tu celular"):
        st.markdown((andr + ios) if es_and else (ios + andr), unsafe_allow_html=True)
        st.caption("Cada vez que abras la app te pedirá tu DNI y contraseña por seguridad.")

st.markdown("""
<style>
.tp-kpi.al-bad{border-left:4px solid var(--tp-bad);} .tp-kpi.al-warn{border-left:4px solid #F59E0B;} .tp-kpi.al-info{border-left:4px solid var(--tp-info);} .tp-kpi.al-ok{border-left:4px solid var(--tp-ok);}
.tp-banner{display:flex;align-items:center;gap:16px;border-radius:20px;padding:20px 24px;border:1px solid var(--tp-line);box-shadow:var(--tp-sh-1);}
.tp-banner.ok{background:linear-gradient(120deg,#E3F6EC,#F4FBF7);border-color:#BFE8D2;} .tp-banner.warn{background:linear-gradient(120deg,#FEF3C7,#FFFBEB);border-color:#F8DE95;} .tp-banner.bad{background:linear-gradient(120deg,#FEE4E2,#FFF5F4);border-color:#F9C4C0;}
.tp-banner b{font-size:1.1rem;color:var(--tp-ink);display:block;} .tp-banner span.s{font-size:.84rem;color:var(--tp-ink-2);}
.tp-al-ico{flex:0 0 auto;width:42px;height:42px;border-radius:13px;display:flex;align-items:center;justify-content:center;}
.tp-al-ico.bad{background:var(--tp-bad-soft);color:var(--tp-bad);} .tp-al-ico.warn{background:var(--tp-warn-soft);color:var(--tp-warn);} .tp-al-ico.info{background:var(--tp-info-soft);color:var(--tp-info);} .tp-al-ico.ok{background:var(--tp-ok-soft);color:var(--tp-ok);}
/* Saludo de cumpleaños */
.tp-bd{position:relative;overflow:hidden;border-radius:22px;border:1px solid var(--tp-line);background:#fff;}
.tp-bd-top{position:relative;height:150px;background:linear-gradient(135deg,#EC3237 0%,#A3202A 55%,#0F172A 135%);}
.tp-bd-conf{position:absolute;inset:0;overflow:hidden;}
.tp-bd-top i{position:absolute;top:-16px;width:9px;height:15px;border-radius:2px;opacity:.95;animation:tpFall 3.4s linear infinite;}
@keyframes tpFall{to{transform:translateY(200px) rotate(320deg);opacity:0;}}
.tp-bd-photo{position:absolute;left:50%;top:94px;transform:translateX(-50%);z-index:2;}
.tp-bd-photo .tp-avatar{box-shadow:0 0 0 5px #fff,0 18px 34px -12px rgba(15,23,42,.5);}
.tp-bd-body{padding:68px 26px 22px;text-align:center;}
.tp-bd-k{font-size:.7rem;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:var(--tp-red);}
.tp-bd-h{font-size:1.65rem;font-weight:800;color:var(--tp-ink);letter-spacing:-.02em;margin:6px 0 10px;line-height:1.2;}
.tp-bd-msg{font-size:.92rem;line-height:1.65;color:var(--tp-ink-2);max-width:420px;margin:14px auto 0;}
.tp-bd-big{font-size:1rem;font-weight:700;color:var(--tp-ink);margin:14px 0 0;}
.tp-bd-sign{margin-top:16px;padding-top:14px;border-top:1px solid var(--tp-line);font-size:.8rem;color:var(--tp-mute);}
[data-testid="stDialog"] .stButton>button{min-height:52px;border:none!important;background:linear-gradient(135deg,#EC3237,#C9262B)!important;box-shadow:0 14px 26px -12px rgba(236,50,55,.7);}
[data-testid="stDialog"] .stButton>button *{color:#fff!important;font-weight:700;}
</style>
""", unsafe_allow_html=True)

# --- COMPONENTES UI REUTILIZABLES ---
def ui_iniciales(nombre):
    p = [x for x in str(nombre).split() if x]
    return (p[0][0] + (p[1][0] if len(p) > 1 else "")).upper() if p else "?"

def ui_avatar(nombre, dni="", foto="", size=46):
    uri = ui_foto_uri(str(dni), str(foto)) if dni else ""
    dim = f"width:{size}px;height:{size}px;"
    if uri:
        return f'<img class="tp-avatar" src="{uri}" alt="{nombre}" style="{dim}">'
    return f'<span class="tp-avatar" style="{dim}">{ui_iniciales(nombre)}</span>'

def ui_chip(texto, tipo="neutral"):
    """tipo: ok | warn | bad | info | neutral"""
    return f'<span class="tp-chip {tipo}">{texto}</span>'

def ui_kpi(etiqueta, valor, detalle=""):
    sub = f'<div class="tp-kpi-sub">{detalle}</div>' if detalle else ""
    return f'<div class="tp-kpi"><div class="tp-kpi-lbl">{etiqueta}</div><div class="tp-kpi-val">{valor}</div>{sub}</div>'

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

ui_pwa_inyectar()

# --- LOGIN EJECUTIVO ---
# Si prefieres NO mostrar nombre/foto al escribir un DNI (antes de autenticar), pon False.
LOGIN_MOSTRAR_FOTO = True

if not st.session_state.usuario_login:
    st.markdown("""
<style>
.stApp:has(.tp-lg-hero){background:radial-gradient(1100px 560px at 8% -10%,#FDECEC 0%,transparent 60%),radial-gradient(900px 520px at 100% 110%,#E4EBF8 0%,transparent 58%),var(--tp-bg);}
.stApp:has(.tp-lg-hero) .block-container{padding-top:1rem;padding-bottom:1rem;max-width:1120px;}
.tp-lg-hero{position:relative;overflow:hidden;border-radius:26px;padding:28px 32px;min-height:min(560px,calc(100vh - 56px));color:#fff;display:flex;flex-direction:column;justify-content:space-between;gap:18px;
  background:linear-gradient(150deg,#0B1220 0%,#111C33 55%,#1B2A4A 100%);box-shadow:0 30px 60px -30px rgba(15,23,42,.6);}
.tp-lg-hero::before{content:"";position:absolute;width:540px;height:540px;right:-190px;top:-170px;border-radius:50%;background:radial-gradient(circle,rgba(236,50,55,.55),rgba(236,50,55,0) 68%);}
.tp-lg-hero::after{content:"";position:absolute;inset:0;background-image:linear-gradient(rgba(255,255,255,.045) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.045) 1px,transparent 1px);background-size:44px 44px;-webkit-mask-image:linear-gradient(180deg,#000,transparent 88%);mask-image:linear-gradient(180deg,#000,transparent 88%);}
.tp-lg-hero>*{position:relative;z-index:1;}
.tp-lg-logo{display:inline-flex;background:#fff;border-radius:14px;padding:8px 16px;box-shadow:0 12px 30px -12px rgba(0,0,0,.6);}
.tp-lg-k{font-size:.72rem;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:#FF8A8E;margin:22px 0 8px;}
.tp-lg-h{font-size:clamp(1.55rem,1.5vw + 1rem,1.95rem);font-weight:800;line-height:1.15;letter-spacing:-.02em;margin:0 0 10px;color:#fff;}
.tp-lg-h em{font-style:normal;color:#FF6B70;}
.tp-lg-p{color:#B7C2D9;font-size:.88rem;line-height:1.55;max-width:430px;margin:0;}
.tp-lg-feat{display:grid;gap:8px;margin-top:18px;max-width:440px;}
.tp-lg-feat div{display:flex;align-items:center;gap:11px;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.1);border-radius:13px;padding:9px 12px;font-size:.82rem;font-weight:600;color:#E6ECF8;}
.tp-lg-feat i{flex:0 0 auto;width:28px;height:28px;border-radius:9px;background:rgba(236,50,55,.2);color:#FF8A8E;display:flex;align-items:center;justify-content:center;}
.tp-lg-quote{position:relative;padding:15px 18px 15px 24px;border-radius:15px;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.12);}
.tp-lg-quote::before{content:"";position:absolute;left:0;top:14px;bottom:14px;width:4px;border-radius:4px;background:#EC3237;}
.tp-lg-quote small{display:block;font-size:.66rem;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:#FF8A8E;margin-bottom:6px;}
.tp-lg-quote p{margin:0;font-size:1.08rem;font-weight:700;line-height:1.45;color:#fff;}
.tp-lg-who{display:flex;flex-direction:column;align-items:center;text-align:center;margin-bottom:6px;animation:tpPop .4s ease;}
.tp-lg-who .tp-avatar{box-shadow:0 0 0 3px #fff,0 0 0 6px var(--tp-red),0 14px 30px -10px rgba(236,50,55,.55);}
.tp-lg-t{font-size:1.4rem;font-weight:800;color:var(--tp-ink);margin-top:12px;letter-spacing:-.01em;}
.tp-lg-s{font-size:.84rem;color:var(--tp-mute);margin-top:3px;}
.tp-lg-lock{width:52px;height:52px;border-radius:16px;background:var(--tp-red-soft);color:var(--tp-red);display:flex;align-items:center;justify-content:center;}
@keyframes tpPop{from{opacity:0;transform:translateY(8px) scale(.97);}to{opacity:1;transform:none;}}
.st-key-tpc_login_form{padding:26px 28px 20px!important;border-radius:24px!important;box-shadow:var(--tp-sh-2)!important;}
.st-key-tpc_login_form [data-baseweb="input"]{min-height:46px;background:#F6F7FA!important;}
.st-key-tpc_login_form .stButton>button{min-height:50px;border:none!important;background:linear-gradient(135deg,#EC3237,#C9262B)!important;box-shadow:0 14px 26px -12px rgba(236,50,55,.7);}
.st-key-tpc_login_form .stButton>button *{color:#fff!important;font-weight:700;}
.tp-lg-note{text-align:center;font-size:.74rem;color:var(--tp-mute);margin-top:10px;}
@media (max-height:800px){.tp-lg-feat{display:none;}.tp-lg-hero{min-height:0;}}
@media (max-width:900px){.tp-lg-hero{min-height:0;padding:20px 22px;border-radius:22px;}.tp-lg-feat,.tp-lg-p{display:none;}.tp-lg-h{font-size:1.4rem;}.tp-lg-k{margin-top:14px;}.tp-lg-quote{padding:12px 14px 12px 20px;}.tp-lg-quote p{font-size:.95rem;}}
</style>
""", unsafe_allow_html=True)

    _ico = lambda d: f'<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{d}</svg>'
    _i1 = _ico("<circle cx='12' cy='12' r='9'/><path d='M12 7v5l3 2'/>")
    _i2 = _ico("<path d='M7 3h7l4 4v14H7z'/><path d='M14 3v4h4M9.5 13h5M9.5 17h5'/>")
    _i3 = _ico("<path d='M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z'/><path d='M9 12l2 2 4-4'/>")
    _lock = _ico("<rect x='5' y='11' width='14' height='9' rx='2'/><path d='M8 11V8a4 4 0 018 0v3'/>")
    _FRASES = [
        "Cada cliente que sale con una sonrisa es una venta que vuelve.",
        "Hoy es un buen día para superar la meta de ayer.",
        "Una buena actitud vende más que cualquier oferta.",
        "Atender con ganas es la mejor estrategia de ventas.",
        "Saluda, sonríe y ofrece: los pequeños detalles hacen grandes ventas.",
        "El éxito del equipo se construye una venta a la vez.",
        "Tu energía se contagia: empieza con pilas y se nota en la caja.",
        "Cada cliente es una oportunidad de hacerle el día mejor.",
        "La constancia convierte un buen turno en un gran mes.",
        "Trabajando en equipo, las metas se hacen más pequeñas.",
        "Una venta bien atendida es un cliente para toda la vida.",
        "Actitud positiva, ventas positivas.",
        "Tú eres la cara de Premium: haz que te recuerden.",
        "Hoy cuenta: ofrece, sonríe y deja huella.",
    ]
    _ahora_lg = obtener_ahora_peru()
    _frase = _FRASES[_ahora_lg.toordinal() % len(_FRASES)]
    _saludo_h = "Buenos días" if _ahora_lg.hour < 12 else ("Buenas tardes" if _ahora_lg.hour < 19 else "Buenas noches")
    _hero = f"""<div class="tp-lg-hero"><div>
<span class="tp-lg-logo">{logo_tag_app39(36)}</span>
<div class="tp-lg-k">{_saludo_h}, equipo Premium</div>
<div class="tp-lg-h">Tu equipo y tu operación, <em>en un solo lugar.</em></div>
<p class="tp-lg-p">Asistencia, planillas, vacaciones y solicitudes de Tiendas Premium, con información clara y al instante.</p>
<div class="tp-lg-feat">
<div><i>{_i1}</i>Asistencia y jornada en tiempo real</div>
<div><i>{_i2}</i>Boletas, vacaciones y permisos en línea</div>
</div></div>
<div class="tp-lg-quote"><small>Frase del día</small><p>{_frase}</p></div></div>"""
    try:
        c_hero, c_form = st.columns([1.15, 1], gap="large", vertical_alignment="center")
    except TypeError:
        c_hero, c_form = st.columns([1.15, 1], gap="large")
    with c_hero:
        st.markdown("".join(x.strip() for x in _hero.splitlines()), unsafe_allow_html=True)
    with c_form:
        with ui_card_container("login_form"):
            _saludo = st.empty()
            dni_input = st.text_input("DNI", placeholder="Tu número de DNI", max_chars=12, key="login_dni")
            clave_input = st.text_input("Contraseña", type="password", placeholder="Tu contraseña", key="login_clave")
            _u = next((n for n, d in USUARIOS.items() if str(d["dni"]).strip() == dni_input.strip()), None) if dni_input.strip() else None
            if _u and LOGIN_MOSTRAR_FOTO:
                _d, _f = ui_dni_foto(_u)
                _saludo.markdown(f'<div class="tp-lg-who">{ui_avatar(_u, _d, _f, 84)}<div class="tp-lg-t">Hola, {_html.escape(_u.split()[0])}</div><div class="tp-lg-s">Ingresa tu contraseña para continuar</div></div>', unsafe_allow_html=True)
            else:
                _saludo.markdown(f'<div class="tp-lg-who"><div class="tp-lg-lock">{_lock}</div><div class="tp-lg-t">Bienvenido</div><div class="tp-lg-s">Ingresa con tu DNI y tu contraseña</div></div>', unsafe_allow_html=True)
            st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
            _clic = st.button("Ingresar al sistema", use_container_width=True, key="login_btn")
            if _clic or (dni_input.strip() and clave_input):
                usuario_sel = next((n for n, d in USUARIOS.items() if str(d["dni"]).strip() == dni_input.strip()), None)
                if usuario_sel and clave_input == USUARIOS[usuario_sel]["clave"]:
                    st.session_state.usuario_login = usuario_sel
                    st.session_state.login_timestamp = time.time()
                    st.session_state.ultima_actividad = time.time()
                    st.success("Acceso concedido")
                    time.sleep(0.3)
                    st.rerun()
                else:
                    st.error("DNI o contraseña incorrectos. Revisa los datos e intenta de nuevo.")
            st.markdown('<div class="tp-lg-note">Conexión protegida · Cierre de sesión por inactividad</div>', unsafe_allow_html=True)
        ui_guia_instalar(st)
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

    # Se marca como "ya mostrado" de inmediato para que aparezca una sola vez tras el login.
    st.session_state[clave_flag] = True
    st.balloons()

    f_nac = _parsear_fecha_nac_cumple(fecha_nac_usuario)
    edad = hoy_peru.year - f_nac.year if f_nac else 0
    dni_c, foto_c = ui_dni_foto(nombre_usuario)
    colores = ["#FFFFFF", "#FFD166", "#06D6A0", "#FF8A8E", "#9CC9FF", "#FFFFFF", "#FFD166", "#FF8A8E"]
    confeti = "".join(f'<i style="left:{(i * 53) % 97 + 1}%;background:{colores[i % 8]};animation-delay:{(i % 7) * 0.45:.2f}s;animation-duration:{3 + (i % 4) * 0.5:.1f}s"></i>' for i in range(22))
    primer_nombre = _html.escape(nombre_usuario.split(" ")[0])
    chip_edad = ui_chip(f"Hoy cumples {edad} años", "ok") if 14 <= edad <= 90 else ""
    html_bd = (f'<div class="tp-bd"><div class="tp-bd-top"><div class="tp-bd-conf">{confeti}</div></div><div class="tp-bd-photo">{ui_avatar(nombre_usuario, dni_c, foto_c, 112)}</div>'
               f'<div class="tp-bd-body"><div class="tp-bd-k">Hoy es tu día</div><div class="tp-bd-h">¡Feliz cumpleaños, {primer_nombre}!</div>{chip_edad}'
               '<div class="tp-bd-msg">Hoy el protagonista eres tú. En Premium valoramos de verdad tu esfuerzo y todo lo que aportas cada día: tu trabajo hace la diferencia y este equipo no sería el mismo sin ti. '
               'Queremos que te sientas aquí como en casa, escuchado y respaldado. Que este nuevo año de vida te regale salud, alegrías y muchos motivos para sonreír.</div>'
               '<div class="tp-bd-big">Gracias por ser parte de esta familia.</div>'
               '<div class="tp-bd-sign">Con cariño,<br><b>tu familia Premium</b> · Tiendas Premium E.I.R.L.</div></div></div>')

    @st.dialog("Un día muy especial")
    def _dialogo_cumpleanos():
        st.markdown(html_bd, unsafe_allow_html=True)
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
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

# =========================================================
# BOLETA DE PAGO — DISEÑO CORPORATIVO UNIFICADO
# (Previsualización HTML, PDF y Excel comparten la misma estructura)
# =========================================================
import html as _html
from xml.sax.saxutils import escape as _xml_esc

BP_NAVY = "#0F172A"      # Azul noche corporativo
BP_SLATE = "#475569"     # Texto secundario
BP_MUTED = "#94A3B8"     # Valores en cero / etiquetas tenues
BP_RED = "#EC3237"       # Acento de marca
BP_LINE = "#E2E8F0"      # Bordes suaves
BP_SOFT = "#F8FAFC"      # Fondo suave
BP_SOFT2 = "#F1F5F9"     # Fondo de secciones
BP_NEG = "#B91C1C"       # Descuentos


def _bp_money(v):
    try:
        return f"{float(v):,.2f}"
    except Exception:
        return "0.00"


def _n_dias(n):
    try:
        return f"{n} día" if int(float(n)) == 1 else f"{n} días"
    except Exception:
        return f"{n} días"


def _estructura_boleta(d):
    """Fuente única de filas: se reutiliza en HTML, PDF y Excel."""
    ingresos = [
        ("SUELDO BÁSICO", _n_dias(d['dias_trabajados']), float(d["sueldo_basico"])),
        ("PAGO FERIADOS TRABAJADOS (ADICIONAL)", _n_dias(d['feriados_trabajados']), float(d["monto_feriados"])),
        ("HORAS EXTRAS TRABAJADAS", f"{float(d['horas_extras_hrs']):.2f} hrs", float(d["monto_horas_extras"])),
        ("DÍA DE DESCANSO TRABAJADO VOLUNTARIAMENTE (DOMINGO)", f"{d.get('domingos_voluntarios', 0)} día(s)", float(d.get("monto_domingos_voluntarios", 0.0))),
        ("BONO POR PUNTUALIDAD", "-", float(d.get("bono_puntualidad", 0.0))),
        ("BONO PRESENCIA Y UNIFORME", "-", float(d.get("bono_presencia_uniforme", 0.0))),
        ("BONO ORDEN Y LIMPIEZA", "-", float(d.get("bono_orden_limpieza", 0.0))),
    ]
    descuentos = [
        ("ADELANTO DE SUELDO", "-", float(d["adelanto_sueldo"])),
        ("DESCUENTO POR FALTAS", _n_dias(d['dias_faltas']), float(d["monto_faltas"])),
        ("DESCUADRE / FALTANTE DE CAJA", "-", float(d["descuadre_caja"])),
        ("DESCUADRES DE INVENTARIO", "-", float(d.get("descuadre_inventario", 0.0))),
        ("CONSUMOS POR PAGAR", "-", float(d.get("consumos_pagar", 0.0))),
        ("INCIDENCIAS Y DAÑOS", "-", float(d.get("incidencias_danos", 0.0))),
    ]
    resumen = [
        ("Días laborados", str(d["dias_trabajados"])),
        ("Días de falta", str(d["dias_faltas"])),
        ("Feriados trab.", str(d["feriados_trabajados"])),
        ("Horas extras", f"{float(d['horas_extras_hrs']):.2f} h"),
        ("Dom. voluntarios", str(d.get("domingos_voluntarios", 0))),
        ("Perm. recuperados", str(d.get("permisos_recuperados", 0))),
    ]
    return ingresos, descuentos, resumen


# ---------------------------------------------------------
# 1) PREVISUALIZACIÓN HTML
# ---------------------------------------------------------
def generar_html_boleta(d):
    esc = _html.escape
    ingresos, descuentos, resumen = _estructura_boleta(d)
    fecha_gen = obtener_ahora_peru().strftime("%d/%m/%Y %H:%M")
    ff = "font-family:'Montserrat','Segoe UI',Arial,sans-serif;"
    logo = logo_tag_app39(44)

    def filas(items, color_monto):
        out = []
        for concepto, cant, monto in items:
            muted = float(monto) == 0
            c_txt = BP_MUTED if muted else BP_NAVY
            c_monto = BP_MUTED if muted else color_monto
            out.append(
                f'<tr>'
                f'<td style="padding:9px 12px;border-bottom:1px solid {BP_LINE};color:{c_txt};font-size:.76rem;">{esc(concepto)}</td>'
                f'<td style="padding:9px 12px;border-bottom:1px solid {BP_LINE};color:{BP_SLATE if not muted else BP_MUTED};font-size:.76rem;text-align:center;white-space:nowrap;">{esc(cant)}</td>'
                f'<td style="padding:9px 12px;border-bottom:1px solid {BP_LINE};color:{c_monto};font-size:.8rem;font-weight:600;text-align:right;white-space:nowrap;">{_bp_money(monto)}</td>'
                f'</tr>'
            )
        return "".join(out)

    def seccion(titulo, color):
        return (
            f'<tr><td colspan="3" style="padding:8px 12px;background:{BP_SOFT2};border-left:4px solid {color};'
            f'font-size:.68rem;font-weight:800;letter-spacing:1.5px;color:{BP_NAVY};">{titulo}</td></tr>'
        )

    def subtotal(label, valor, color):
        return (
            f'<tr><td colspan="2" style="padding:10px 12px;border-top:1.5px solid {BP_NAVY};background:{BP_SOFT};'
            f'font-size:.72rem;font-weight:800;letter-spacing:.8px;color:{BP_NAVY};">{label}</td>'
            f'<td style="padding:10px 12px;border-top:1.5px solid {BP_NAVY};background:{BP_SOFT};'
            f'font-size:.85rem;font-weight:800;text-align:right;color:{color};white-space:nowrap;">S/. {_bp_money(valor)}</td></tr>'
        )

    th = f'padding:10px 12px;background:{BP_NAVY};color:#fff;font-size:.66rem;font-weight:700;letter-spacing:1.2px;'

    def celda_info(label, valor):
        return (
            f'<div style="padding:10px 14px;">'
            f'<div style="font-size:.6rem;font-weight:700;letter-spacing:1.2px;color:{BP_MUTED};text-transform:uppercase;">{label}</div>'
            f'<div style="font-size:.88rem;font-weight:700;color:{BP_NAVY};margin-top:2px;word-break:break-word;">{esc(str(valor))}</div>'
            f'</div>'
        )

    def celda_resumen(label, valor):
        return (
            f'<div style="padding:12px 6px;text-align:center;border-right:1px solid {BP_LINE};">'
            f'<div style="font-size:1.15rem;font-weight:800;color:{BP_NAVY};line-height:1.1;">{esc(valor)}</div>'
            f'<div style="font-size:.58rem;font-weight:700;letter-spacing:.8px;color:{BP_MUTED};text-transform:uppercase;margin-top:4px;">{esc(label)}</div>'
            f'</div>'
        )

    partes = []
    partes.append(
        f'<div style="{ff}background:#fff;color:{BP_NAVY};max-width:820px;margin:0 auto 20px auto;padding:30px 32px;'
        f'border:1px solid {BP_LINE};border-radius:12px;box-shadow:0 6px 24px rgba(15,23,42,.08);">'
    )
    # Encabezado
    partes.append(
        f'<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:14px;">'
        f'<div style="display:flex;align-items:center;gap:14px;">{logo}'
        f'<div><div style="font-size:1.05rem;font-weight:800;letter-spacing:.4px;">{esc(d["empresa"])}</div>'
        f'<div style="font-size:.72rem;color:{BP_SLATE};margin-top:2px;">RUC: {esc(d["ruc"])}</div></div></div>'
        f'<div style="text-align:right;">'
        f'<div style="font-size:.68rem;font-weight:800;letter-spacing:3px;color:{BP_RED};">BOLETA DE PAGO</div>'
        f'<div style="font-size:1.05rem;font-weight:800;margin-top:2px;">{esc(d["periodo"])}</div></div>'
        f'</div>'
    )
    partes.append(
        f'<div style="height:3px;margin:16px 0 18px 0;background:linear-gradient(90deg,{BP_RED} 0,{BP_RED} 90px,{BP_NAVY} 90px,{BP_NAVY} 100%);"></div>'
    )
    # Datos del colaborador
    partes.append(
        f'<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));background:{BP_SOFT};'
        f'border:1px solid {BP_LINE};border-radius:8px;">'
        + celda_info("Colaborador", d["colaborador"])
        + celda_info("DNI", d["dni"])
        + celda_info("Cargo", d["cargo"])
        + celda_info("Fecha de ingreso", d["fecha_inicio"])
        + '</div>'
    )
    # Resumen del período
    partes.append(
        f'<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(105px,1fr));margin-top:12px;'
        f'border:1px solid {BP_LINE};border-right:none;border-radius:8px;overflow:hidden;">'
        + "".join(celda_resumen(l, v) for l, v in resumen)
        + '</div>'
    )
    # Tabla de conceptos
    partes.append(
        f'<table style="width:100%;border-collapse:collapse;margin-top:18px;border:1px solid {BP_LINE};">'
        f'<thead><tr><th style="{th}text-align:left;">CONCEPTO</th>'
        f'<th style="{th}text-align:center;">CANTIDAD</th>'
        f'<th style="{th}text-align:right;">IMPORTE (S/.)</th></tr></thead><tbody>'
        + seccion("INGRESOS", "#16A34A") + filas(ingresos, BP_NAVY)
        + subtotal("TOTAL INGRESOS", d["total_ingresos"], BP_NAVY)
        + seccion("DESCUENTOS", BP_NEG) + filas(descuentos, BP_NEG)
        + subtotal("TOTAL DESCUENTOS", d["total_descuentos"], BP_NEG)
        + '</tbody></table>'
    )
    # Neto
    partes.append(
        f'<div style="display:flex;justify-content:space-between;align-items:center;margin-top:14px;padding:16px 20px;'
        f'background:{BP_NAVY};border-left:5px solid {BP_RED};border-radius:6px;">'
        f'<div style="color:#fff;font-size:.78rem;font-weight:800;letter-spacing:2px;">NETO A PAGAR</div>'
        f'<div style="color:#fff;font-size:1.5rem;font-weight:800;white-space:nowrap;">S/. {_bp_money(d["neto_pagar"])}</div>'
        f'</div>'
    )
    # Firmas
    firma = lambda txt: (
        f'<div style="flex:1;min-width:200px;text-align:center;">'
        f'<div style="border-top:1.5px solid {BP_NAVY};padding-top:6px;font-size:.66rem;font-weight:800;letter-spacing:1px;">{txt}</div></div>'
    )
    partes.append(
        f'<div style="display:flex;justify-content:space-around;gap:48px;flex-wrap:wrap;margin-top:62px;">'
        + firma("EMPLEADOR / TIENDAS PREMIUM") + firma("RECIBÍ CONFORME (TRABAJADOR)") + '</div>'
    )
    partes.append(
        f'<div style="margin-top:26px;padding-top:10px;border-top:1px solid {BP_LINE};text-align:center;'
        f'font-size:.6rem;color:{BP_MUTED};letter-spacing:.4px;">'
        f'Documento generado por el Sistema de Control Interno de {esc(d["empresa"])} · {fecha_gen}</div>'
    )
    partes.append('</div>')
    # Sin saltos de línea ni sangrías: evita que Markdown interprete bloques de código
    return "".join(partes)


# ---------------------------------------------------------
# 2) EXCEL
# ---------------------------------------------------------
def generar_excel_boleta(datos_b):
    import xlsxwriter
    ingresos, descuentos, resumen = _estructura_boleta(datos_b)
    fecha_gen = obtener_ahora_peru().strftime("%d/%m/%Y %H:%M")

    output = io.BytesIO()
    wb = xlsxwriter.Workbook(output, {"in_memory": True})
    ws = wb.add_worksheet("Boleta de Pago")
    ws.hide_gridlines(2)
    ws.set_column("A:D", 14)
    ws.set_column("E:E", 16)
    ws.set_column("F:F", 19)

    base = {"font_name": "Calibri", "font_size": 10, "valign": "vcenter", "font_color": BP_NAVY}
    def F(**kw):
        x = dict(base); x.update(kw)
        return wb.add_format(x)

    f_empresa = F(bold=True, font_size=16)
    f_ruc = F(font_size=9, font_color=BP_SLATE, bottom=2, bottom_color=BP_NAVY)
    f_doc = F(bold=True, font_size=9, font_color=BP_RED, align="right")
    f_per = F(bold=True, font_size=14, align="right")
    f_lbl = F(bold=True, font_size=8, font_color=BP_MUTED, bg_color=BP_SOFT, top=1, top_color=BP_LINE, left=1, left_color=BP_LINE, right=1, right_color=BP_LINE, indent=1)
    f_val = F(bold=True, font_size=11, bg_color=BP_SOFT, bottom=1, bottom_color=BP_LINE, left=1, left_color=BP_LINE, right=1, right_color=BP_LINE, indent=1)
    f_stat_v = F(bold=True, font_size=14, align="center", top=1, top_color=BP_LINE, left=1, left_color=BP_LINE, right=1, right_color=BP_LINE)
    f_stat_l = F(bold=True, font_size=8, font_color=BP_MUTED, align="center", bottom=1, bottom_color=BP_LINE, left=1, left_color=BP_LINE, right=1, right_color=BP_LINE)
    f_th = F(bold=True, font_size=9, font_color="#FFFFFF", bg_color=BP_NAVY, indent=1)
    f_th_c = F(bold=True, font_size=9, font_color="#FFFFFF", bg_color=BP_NAVY, align="center")
    f_th_r = F(bold=True, font_size=9, font_color="#FFFFFF", bg_color=BP_NAVY, align="right", indent=1)
    f_sec_ing = F(bold=True, font_size=9, bg_color=BP_SOFT2, left=5, left_color="#16A34A", indent=1)
    f_sec_des = F(bold=True, font_size=9, bg_color=BP_SOFT2, left=5, left_color=BP_NEG, indent=1)
    line = {"bottom": 1, "bottom_color": BP_LINE}
    f_c = F(indent=1, **line); f_c_m = F(indent=1, font_color=BP_MUTED, **line)
    f_q = F(align="center", font_color=BP_SLATE, **line); f_q_m = F(align="center", font_color=BP_MUTED, **line)
    f_m = F(align="right", num_format="#,##0.00", indent=1, **line)
    f_m_m = F(align="right", num_format="#,##0.00", indent=1, font_color=BP_MUTED, **line)
    f_m_neg = F(align="right", num_format="#,##0.00", indent=1, font_color=BP_NEG, **line)
    f_st_l = F(bold=True, font_size=9, bg_color=BP_SOFT, top=1, top_color=BP_NAVY, indent=1)
    f_st_ing = F(bold=True, bg_color=BP_SOFT, top=1, top_color=BP_NAVY, align="right", num_format='"S/." #,##0.00', indent=1)
    f_st_des = F(bold=True, bg_color=BP_SOFT, top=1, top_color=BP_NAVY, align="right", num_format='"S/." #,##0.00', font_color=BP_NEG, indent=1)
    f_net_l = F(bold=True, font_size=11, font_color="#FFFFFF", bg_color=BP_NAVY, left=5, left_color=BP_RED, indent=1)
    f_net_v = F(bold=True, font_size=14, font_color="#FFFFFF", bg_color=BP_NAVY, align="right", num_format='"S/." #,##0.00', indent=1)
    f_sig = F(bold=True, font_size=8, align="center", top=1, top_color=BP_NAVY)
    f_foot = F(italic=True, font_size=8, font_color=BP_MUTED, align="center", top=1, top_color=BP_LINE)

    # Encabezado
    ws.set_row(0, 24); ws.set_row(1, 24); ws.set_row(2, 18)
    logo_ok = False
    if LOGO_DISPONIBLE:
        try:
            from reportlab.lib.utils import ImageReader
            iw, ih = ImageReader(LOGO_PATH).getSize()
            esc_ = 44.0 / ih
            ws.insert_image("A1", LOGO_PATH, {"x_scale": esc_, "y_scale": esc_, "x_offset": 4, "y_offset": 2, "object_position": 1})
            logo_ok = True
        except Exception:
            logo_ok = False
    ws.merge_range("A1:C2", "" if logo_ok else datos_b["empresa"], f_empresa)
    ws.merge_range("D1:F1", "BOLETA DE PAGO", f_doc)
    ws.merge_range("D2:F2", datos_b["periodo"], f_per)
    _txt_ruc = f"{datos_b['empresa']}   ·   RUC: {datos_b['ruc']}" if logo_ok else f"RUC: {datos_b['ruc']}"
    ws.merge_range("A3:F3", _txt_ruc, f_ruc)

    # Datos del colaborador
    r = 4
    ws.merge_range(r, 0, r, 1, "COLABORADOR", f_lbl); ws.write(r, 2, "DNI", f_lbl)
    ws.merge_range(r, 3, r, 4, "CARGO", f_lbl); ws.write(r, 5, "FECHA DE INGRESO", f_lbl)
    ws.set_row(r + 1, 22)
    ws.merge_range(r + 1, 0, r + 1, 1, str(datos_b["colaborador"]), f_val)
    ws.write_string(r + 1, 2, str(datos_b["dni"]), f_val)
    ws.merge_range(r + 1, 3, r + 1, 4, str(datos_b["cargo"]), f_val)
    ws.write_string(r + 1, 5, str(datos_b["fecha_inicio"]), f_val)

    # Resumen del período
    r = 7
    ws.set_row(r, 26)
    for i, (lbl, val) in enumerate(resumen):
        ws.write(r, i, val, f_stat_v)
        ws.write(r + 1, i, lbl.upper(), f_stat_l)

    # Tabla de conceptos
    r = 10
    ws.set_row(r, 22)
    ws.merge_range(r, 0, r, 3, "CONCEPTO", f_th)
    ws.write(r, 4, "CANTIDAD", f_th_c)
    ws.write(r, 5, "IMPORTE (S/.)", f_th_r)

    def bloque(r, titulo, items, f_sec, es_descuento):
        ws.set_row(r, 20)
        ws.merge_range(r, 0, r, 5, titulo, f_sec)
        r += 1
        first = r
        for concepto, cant, monto in items:
            ws.set_row(r, 19)
            muted = float(monto) == 0
            ws.merge_range(r, 0, r, 3, concepto, f_c_m if muted else f_c)
            ws.write(r, 4, cant, f_q_m if muted else f_q)
            ws.write_number(r, 5, float(monto), f_m_m if muted else (f_m_neg if es_descuento else f_m))
            r += 1
        return first, r - 1, r

    ing_ini, ing_fin, r = bloque(11, "INGRESOS", ingresos, f_sec_ing, False)
    ws.set_row(r, 22)
    ws.merge_range(r, 0, r, 4, "TOTAL INGRESOS", f_st_l)
    ws.write_formula(r, 5, f"=SUM(F{ing_ini + 1}:F{ing_fin + 1})", f_st_ing, float(datos_b["total_ingresos"]))
    fila_ti = r + 1
    r += 1
    des_ini, des_fin, r = bloque(r, "DESCUENTOS", descuentos, f_sec_des, True)
    ws.set_row(r, 22)
    ws.merge_range(r, 0, r, 4, "TOTAL DESCUENTOS", f_st_l)
    ws.write_formula(r, 5, f"=SUM(F{des_ini + 1}:F{des_fin + 1})", f_st_des, float(datos_b["total_descuentos"]))
    fila_td = r + 1
    r += 2
    ws.set_row(r, 32)
    ws.merge_range(r, 0, r, 4, "NETO A PAGAR", f_net_l)
    ws.write_formula(r, 5, f"=MAX(0,F{fila_ti}-F{fila_td})", f_net_v, float(datos_b["neto_pagar"]))

    # Firmas
    r += 4
    ws.merge_range(r, 0, r, 1, "EMPLEADOR / TIENDAS PREMIUM", f_sig)
    ws.merge_range(r, 3, r, 5, "RECIBÍ CONFORME (TRABAJADOR)", f_sig)
    r += 3
    ws.merge_range(r, 0, r, 5, f"Documento generado por el Sistema de Control Interno de {datos_b['empresa']} · {fecha_gen}", f_foot)

    # Impresión: A4 vertical, una sola página
    ws.set_paper(9)
    ws.set_portrait()
    ws.fit_to_pages(1, 1)
    ws.center_horizontally()
    ws.set_margins(left=0.5, right=0.5, top=0.6, bottom=0.6)
    ws.print_area(0, 0, r, 5)
    wb.close()
    return output.getvalue()


# ---------------------------------------------------------
# 3) PDF
# ---------------------------------------------------------
def generar_pdf_boleta(datos_b):
    if not REPORTLAB_AVAILABLE:
        return None

    ingresos, descuentos, resumen = _estructura_boleta(datos_b)
    fecha_gen = obtener_ahora_peru().strftime("%d/%m/%Y %H:%M")
    X = _xml_esc

    buffer = io.BytesIO()
    MARGIN = 40
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=MARGIN, leftMargin=MARGIN, topMargin=36, bottomMargin=36,
        title=f"Boleta de Pago - {datos_b['colaborador']} - {datos_b['periodo']}",
        author=datos_b["empresa"]
    )
    W = A4[0] - 2 * MARGIN

    navy = colors.HexColor(BP_NAVY); red = colors.HexColor(BP_RED)
    line_c = colors.HexColor(BP_LINE); soft = colors.HexColor(BP_SOFT); soft2 = colors.HexColor(BP_SOFT2)
    neg = colors.HexColor(BP_NEG); green = colors.HexColor("#16A34A")

    def ps(name, **kw):
        kw.setdefault("fontName", "Helvetica")
        kw.setdefault("textColor", navy)
        return ParagraphStyle(name, **kw)

    s_emp = ps("emp", fontName="Helvetica-Bold", fontSize=13, leading=15)
    s_ruc = ps("ruc", fontSize=8, leading=10, textColor=colors.HexColor(BP_SLATE))
    s_doc = ps("doc", fontName="Helvetica-Bold", fontSize=8, leading=10, alignment=2, textColor=red, charSpace=2)
    s_per = ps("per", fontName="Helvetica-Bold", fontSize=13, leading=16, alignment=2)
    s_lbl = ps("lbl", fontName="Helvetica-Bold", fontSize=6.5, leading=8, textColor=colors.HexColor(BP_MUTED), charSpace=0.8)
    s_val = ps("val", fontName="Helvetica-Bold", fontSize=9.5, leading=12)
    s_sv = ps("sv", fontName="Helvetica-Bold", fontSize=13, leading=15, alignment=1)
    s_sl = ps("sl", fontName="Helvetica-Bold", fontSize=6, leading=8, alignment=1, textColor=colors.HexColor(BP_MUTED), charSpace=0.5)
    s_th = ps("th", fontName="Helvetica-Bold", fontSize=7.5, leading=9, textColor=colors.white, charSpace=0.8)
    s_th_c = ParagraphStyle("thc", parent=s_th, alignment=1)
    s_th_r = ParagraphStyle("thr", parent=s_th, alignment=2)
    s_sec = ps("sec", fontName="Helvetica-Bold", fontSize=7.5, leading=9, charSpace=1.2)
    s_c = ps("c", fontSize=8, leading=10)
    s_c_m = ps("cm", fontSize=8, leading=10, textColor=colors.HexColor(BP_MUTED))
    s_q = ps("q", fontSize=8, leading=10, alignment=1, textColor=colors.HexColor(BP_SLATE))
    s_q_m = ps("qm", fontSize=8, leading=10, alignment=1, textColor=colors.HexColor(BP_MUTED))
    s_m = ps("m", fontName="Helvetica-Bold", fontSize=8.5, leading=10, alignment=2)
    s_m_m = ps("mm", fontName="Helvetica-Bold", fontSize=8.5, leading=10, alignment=2, textColor=colors.HexColor(BP_MUTED))
    s_m_neg = ps("mn", fontName="Helvetica-Bold", fontSize=8.5, leading=10, alignment=2, textColor=neg)
    s_st = ps("st", fontName="Helvetica-Bold", fontSize=8, leading=10, charSpace=0.5)
    s_st_r = ps("str", fontName="Helvetica-Bold", fontSize=9, leading=11, alignment=2)
    s_st_r_neg = ps("strn", fontName="Helvetica-Bold", fontSize=9, leading=11, alignment=2, textColor=neg)
    s_net_l = ps("netl", fontName="Helvetica-Bold", fontSize=9.5, leading=12, textColor=colors.white, charSpace=1.8)
    s_net_v = ps("netv", fontName="Helvetica-Bold", fontSize=17, leading=20, textColor=colors.white, alignment=2)
    s_sig = ps("sig", fontName="Helvetica-Bold", fontSize=7, leading=9, alignment=1, charSpace=0.6)
    s_foot = ps("foot", fontSize=6.5, leading=8, alignment=1, textColor=colors.HexColor(BP_MUTED))

    story = []

    # --- Encabezado ---
    logo_flow = None
    if LOGO_DISPONIBLE:
        try:
            from reportlab.lib.utils import ImageReader
            iw, ih = ImageReader(LOGO_PATH).getSize()
            h_logo = 34
            logo_flow = Image(LOGO_PATH, width=h_logo * iw / ih, height=h_logo)
        except Exception:
            logo_flow = None

    txt_emp = [Paragraph(X(datos_b["empresa"]), s_emp), Paragraph(f"RUC: {X(str(datos_b['ruc']))}", s_ruc)]
    txt_per = [Paragraph("BOLETA DE PAGO", s_doc), Paragraph(X(datos_b["periodo"]), s_per)]
    if logo_flow:
        lw = logo_flow.drawWidth + 12
        t_head = Table([[logo_flow, txt_emp, txt_per]], colWidths=[lw, W * 0.66 - lw, W * 0.34])
    else:
        t_head = Table([[txt_emp, txt_per]], colWidths=[W * 0.62, W * 0.38])
    t_head.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(t_head)
    t_acc = Table([["", ""]], colWidths=[70, W - 70], rowHeights=[3])
    t_acc.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), red), ("BACKGROUND", (1, 0), (1, 0), navy),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(t_acc)
    story.append(Spacer(1, 14))

    # --- Datos del colaborador ---
    def celda(lbl, val):
        return [Paragraph(lbl.upper(), s_lbl), Spacer(1, 2), Paragraph(X(str(val)), s_val)]
    t_info = Table(
        [[celda("Colaborador", datos_b["colaborador"]), celda("DNI", datos_b["dni"]),
          celda("Cargo", datos_b["cargo"]), celda("Fecha de ingreso", datos_b["fecha_inicio"])]],
        colWidths=[W * 0.31, W * 0.17, W * 0.30, W * 0.22]
    )
    t_info.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), soft), ("BOX", (0, 0), (-1, -1), 0.6, line_c),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(t_info)
    story.append(Spacer(1, 8))

    # --- Resumen del período ---
    t_res = Table(
        [[Paragraph(X(v), s_sv) for _, v in resumen], [Paragraph(l.upper(), s_sl) for l, _ in resumen]],
        colWidths=[W / 6.0] * 6
    )
    t_res.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, line_c), ("INNERGRID", (0, 0), (-1, -1), 0, colors.white),
        *[("LINEAFTER", (i, 0), (i, -1), 0.6, line_c) for i in range(5)],
        ("TOPPADDING", (0, 0), (-1, 0), 9), ("BOTTOMPADDING", (0, 0), (-1, 0), 1),
        ("TOPPADDING", (0, 1), (-1, 1), 1), ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(t_res)
    story.append(Spacer(1, 14))

    # --- Tabla de conceptos ---
    data = [[Paragraph("CONCEPTO", s_th), Paragraph("CANTIDAD", s_th_c), Paragraph("IMPORTE (S/.)", s_th_r)]]
    estilos = [
        ("BACKGROUND", (0, 0), (-1, 0), navy),
        ("BOX", (0, 0), (-1, -1), 0.6, line_c),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 5.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5.5),
    ]

    def bloque(titulo, items, color_barra, es_desc, label_total, total):
        r = len(data)
        data.append([Paragraph(titulo, s_sec), "", ""])
        estilos.extend([
            ("SPAN", (0, r), (-1, r)), ("BACKGROUND", (0, r), (-1, r), soft2),
            ("LINEBEFORE", (0, r), (0, r), 3, color_barra),
        ])
        for concepto, cant, monto in items:
            muted = float(monto) == 0
            st_m = s_m_m if muted else (s_m_neg if es_desc else s_m)
            data.append([
                Paragraph(X(concepto), s_c_m if muted else s_c),
                Paragraph(X(cant), s_q_m if muted else s_q),
                Paragraph(_bp_money(monto), st_m),
            ])
            estilos.append(("LINEBELOW", (0, len(data) - 1), (-1, len(data) - 1), 0.4, line_c))
        r = len(data)
        data.append([
            Paragraph(label_total, s_st), "",
            Paragraph(f"S/. {_bp_money(total)}", s_st_r_neg if es_desc else s_st_r)
        ])
        estilos.extend([
            ("SPAN", (0, r), (1, r)), ("BACKGROUND", (0, r), (-1, r), soft),
            ("LINEABOVE", (0, r), (-1, r), 1, navy),
        ])

    bloque("INGRESOS", ingresos, green, False, "TOTAL INGRESOS", datos_b["total_ingresos"])
    bloque("DESCUENTOS", descuentos, neg, True, "TOTAL DESCUENTOS", datos_b["total_descuentos"])

    t_calc = Table(data, colWidths=[W * 0.60, W * 0.16, W * 0.24], repeatRows=1)
    t_calc.setStyle(TableStyle(estilos))
    story.append(t_calc)
    story.append(Spacer(1, 12))

    # --- Neto a pagar ---
    t_net = Table(
        [[Paragraph("NETO A PAGAR", s_net_l), Paragraph(f"S/. {_bp_money(datos_b['neto_pagar'])}", s_net_v)]],
        colWidths=[W * 0.5, W * 0.5]
    )
    t_net.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), navy), ("LINEBEFORE", (0, 0), (0, 0), 5, red),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 16), ("RIGHTPADDING", (0, 0), (-1, -1), 16),
        ("TOPPADDING", (0, 0), (-1, -1), 12), ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
    ]))
    story.append(t_net)
    story.append(Spacer(1, 52))

    # --- Firmas ---
    gap = 60
    cw = (W - gap) / 2.0
    t_firm = Table(
        [[Paragraph("EMPLEADOR / TIENDAS PREMIUM", s_sig), "", Paragraph("RECIBÍ CONFORME (TRABAJADOR)", s_sig)]],
        colWidths=[cw, gap, cw]
    )
    t_firm.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (0, 0), 1, navy), ("LINEABOVE", (2, 0), (2, 0), 1, navy),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t_firm)
    story.append(Spacer(1, 26))

    # --- Pie ---
    story.append(HRFlowable(width="100%", thickness=0.5, color=line_c, spaceAfter=6))
    story.append(Paragraph(f"Documento generado por el Sistema de Control Interno de {X(datos_b['empresa'])} · {fecha_gen}", s_foot))

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
    e = _html.escape
    g = lambda k, d="": str(row.get(k, d)).strip()
    dni_val, nombre_val, cargo_val, rol_val = g("dni"), g("nombre"), g("cargo"), g("rol")
    activo = g("estado", "Activo").lower() == "activo"
    f_nac = g("fecha_nacimiento")
    tel = g("telefono") or "-"
    direccion = g("direccion") or "-"
    link = g("link_domicilio")
    f_ini = g("fecha_inicio") or "-"
    f_cese = g("fecha_cese") or "-"
    uri = ui_foto_uri(dni_val, g("foto"))
    foto = f'<img class="tp-id-photo" src="{uri}" alt="{e(nombre_val)}">' if uri else f'<div class="tp-id-photo ph">{ui_iniciales(nombre_val)}</div>'
    chips = ui_chip("Activo" if activo else "Dado de baja", "ok" if activo else "neutral") + ui_chip(e(rol_val.capitalize()), "info") if rol_val else ui_chip("Activo" if activo else "Dado de baja", "ok" if activo else "neutral")
    def fld(l, v, wide=False, cls=""):
        return f'<div class="tp-f{" wide" if wide else ""}"><div class="tp-f-l">{l}</div><div class="tp-f-v {cls}">{v}</div></div>'
    dir_html = e(direccion) + (f' · <a class="tp-link" href="{e(link)}" target="_blank" rel="noopener">Ver en Google Maps</a>' if link.startswith("http") else "")
    campos = (fld("DNI / ID", e(dni_val)) + fld("Teléfono", e(tel)) +
              fld("Nacimiento / edad", f"{e(f_nac) if f_nac else '-'} ({e(str(calcular_edad(f_nac)))})") +
              (fld("Inicio de labores", e(f_ini)) if activo else fld("Retiro", f"{e(f_cese)} (inicio {e(f_ini)})", cls="bad")) +
              fld("Domicilio", dir_html, wide=True))
    sos = f'<div class="tp-id-sos"><div class="tp-f-l">Contacto de emergencia</div><div class="tp-f-v">{e(g("contacto_emergencia", "-") or "-")} · {e(g("numero_emergencia", "-") or "-")}</div></div>'
    st.markdown(f'<div class="tp-id{"" if activo else " off"}"><div class="tp-id-band"></div><div class="tp-id-head">{foto}<div class="tp-id-who"><div class="tp-id-name">{e(nombre_val)}</div>'
                f'<div class="tp-id-role">{e(cargo_val)}</div><div class="tp-id-chips">{chips}</div></div></div><div class="tp-id-body"><div class="tp-id-grid">{campos}</div>{sos}</div></div>', unsafe_allow_html=True)

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
st.sidebar.markdown('<div class="tp-brand"><div class="tp-brand-name">Tiendas <span>Premium</span></div><div class="tp-brand-sub">Sistema de control interno</div></div>', unsafe_allow_html=True)

_fila_me = st.session_state.empleados[st.session_state.empleados["dni"].astype(str) == str(dni_actual)]
_foto_actual = str(_fila_me.iloc[0].get("foto", "")) if not _fila_me.empty else ""
st.sidebar.markdown(f"""
    <div class="tp-user">
        {ui_avatar(user_actual, dni_actual, _foto_actual)}
        <div><b>{user_actual}</b><span>{str(rol_actual).capitalize()} · DNI {dni_actual}</span></div>
    </div>
""", unsafe_allow_html=True)
_sol_n = st.session_state.get("solicitudes")
if _sol_n is not None and not _sol_n.empty:
    _pend = _sol_n[_sol_n["estado"].astype(str) == "Pendiente"]
    if rol_actual != "admin":
        _pend = _pend[_pend["dni"].astype(str) == str(dni_actual)]
    if len(_pend):
        st.sidebar.markdown(f'<div class="tp-notif"><span>{"Solicitudes por revisar" if rol_actual == "admin" else "Tus solicitudes en revisión"}</span><span>{len(_pend)}</span></div>', unsafe_allow_html=True)

if rol_actual == "admin":
    menu = ["Dashboard General", "Centro de Alertas", "Analítica (BI)", "Gestión Colaboradores", "Onboarding / Offboarding", "Gestión de Vacaciones", "Boletas de Pago", "Solicitudes y Permisos", "Historial de Descuadres", "Incidencias y Daños", "Botellas Fiadas", "Historial de Asistencias", "Auditoría y Configuración"]
else:
    menu = ["Marcar Asistencia", "Registrar Descuadre", "Registrar Incidencia", "Botellas Fiadas", "Mi Ficha Técnica", "Mis Vacaciones", "Solicitar Permiso / Adelanto", "Mi Dashboard Mensual"]

st.sidebar.text_input("Buscar", key="gs_q", placeholder="Buscar personas, solicitudes, secciones…", label_visibility="collapsed")
if st.session_state.get("nav_radio") not in menu:
    st.session_state["nav_radio"] = menu[0]
choice = st.sidebar.radio("Navegación", menu, key="nav_radio", on_change=_limpiar_busqueda)

def _ir_a(destino):
    st.session_state["nav_radio"] = destino
    st.session_state["gs_q"] = ""

if rol_actual == "admin":
    _nav_items = [("Dashboard General", "Resumen", ":material/dashboard:"), ("Centro de Alertas", "Alertas", ":material/notifications:"),
                  ("Historial de Asistencias", "Asistencia", ":material/schedule:"), ("Solicitudes y Permisos", "Solicitudes", ":material/inbox:")]
else:
    _nav_items = [("Marcar Asistencia", "Marcar", ":material/fingerprint:"), ("Mi Dashboard Mensual", "Mi mes", ":material/calendar_month:"),
                  ("Solicitar Permiso / Adelanto", "Permisos", ":material/edit_note:"), ("Mi Ficha Técnica", "Ficha", ":material/badge:")]
try:
    with st.container(key="tp_bottomnav"):
        for _col, (_dest, _lbl, _ico) in zip(st.columns(len(_nav_items)), _nav_items):
            with _col:
                st.button(_lbl, key=f"bn_{_dest}", icon=_ico, use_container_width=True,
                          type="primary" if choice == _dest else "secondary", on_click=_ir_a, args=(_dest,))
except Exception:
    pass  # versiones antiguas de Streamlit: se usa solo el menú lateral

st.sidebar.markdown("<br><br>", unsafe_allow_html=True)
st.sidebar.markdown('<div class="btn-logout">', unsafe_allow_html=True)
ui_guia_instalar(st.sidebar)
if st.sidebar.button("Cerrar Sesión", use_container_width=True):
    registrar_auditoria("Cierre de Sesión", "Usuarios", f"{user_actual} cerró sesión.")
    st.session_state.usuario_login = None
    st.session_state.login_auditado = False
    st.rerun()
st.sidebar.markdown('</div>', unsafe_allow_html=True)

# -------------------- MÓDULOS OPERATIVOS --------------------

_gq = str(st.session_state.get("gs_q", "")).strip()
if len(_gq) >= 2:
    render_busqueda(_gq, rol_actual == "admin", dni_actual, menu)
    st.stop()

if choice == "Marcar Asistencia":
    st.markdown(f"""
        <div class="market-header">
            <h1>Terminal de Asistencia</h1>
            <p>Colaborador activo: <b>{user_actual}</b> | Jornada laboral requerida: <b>5h 45m</b></p>
        </div>
    """, unsafe_allow_html=True)

    _hoy_h = obtener_ahora_peru().strftime("%Y-%m-%d")
    _estado, _chip, _lab_h = "Aún no marcas ingreso hoy", "neutral", 0
    if not st.session_state.asistencia.empty:
        _mh = st.session_state.asistencia[(st.session_state.asistencia["fecha"].astype(str) == _hoy_h) & (st.session_state.asistencia["dni"].astype(str) == str(dni_actual))].copy()
        _mh["dt"] = pd.to_datetime(_mh["fecha_hora"], errors="coerce")
        _mh = _mh.dropna(subset=["dt"]).sort_values("dt")
        if not _mh.empty:
            _u = _mh.iloc[-1]
            if _u["tipo"] == "INGRESO":
                _estado, _chip = f"En turno desde las {_u['dt'].strftime('%H:%M')}", "ok"
            else:
                _estado, _chip = f"Salida registrada a las {_u['dt'].strftime('%H:%M')}", "info"
            _lab_h = calcular_jornada_y_horas_extras(_mh)[0]
    _pct_h = min(100, int(_lab_h * 100 / JORNADA_MINUTOS_BASE))
    _hc1, _hc2 = st.columns([1.5, 1])
    with _hc1:
        st.markdown(f'<div class="tp-hero"><div class="tp-hero-top">{ui_avatar(user_actual, dni_actual, _foto_actual, 54)}<div><div class="tp-hero-hi">Hola, {user_actual.split()[0]}</div>{ui_chip(_estado, _chip)}</div></div><div class="tp-prog-lbl"><span>Jornada de hoy</span><span>{formatear_horas_minutos(_lab_h)} de 5h 45m</span></div><div class="tp-prog"><i style="width:{_pct_h}%"></i></div></div>', unsafe_allow_html=True)
    with _hc2:
        components.html("""<body style="margin:0;font-family:Montserrat,Arial,sans-serif"><div style="box-sizing:border-box;height:132px;background:#fff;border:1px solid #E3E6EC;border-radius:20px;display:flex;flex-direction:column;align-items:center;justify-content:center;box-shadow:0 1px 3px rgba(15,23,42,.05)"><div id="t" style="font-size:2.3rem;font-weight:700;color:#0F172A;font-variant-numeric:tabular-nums">--:--:--</div><div id="d" style="font-size:.8rem;color:#64748B;font-weight:600;text-transform:capitalize"></div></div><script>function u(){var n=new Date(),o={timeZone:"America/Lima"};document.getElementById("t").textContent=n.toLocaleTimeString("es-PE",{timeZone:"America/Lima",hour12:false});document.getElementById("d").textContent=n.toLocaleDateString("es-PE",{timeZone:"America/Lima",weekday:"long",day:"numeric",month:"long"})}u();setInterval(u,1000)</script></body>""", height=134)
    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

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
                _filas = ""
                for _, _r in df_mismarcas.sort_values("fecha_hora", ascending=False).iterrows():
                    _es_ing = str(_r["tipo"]) == "INGRESO"
                    _obs = str(_r.get("observacion", "")).strip() or "Sin observación"
                    _chips = ui_chip("Ingreso" if _es_ing else "Salida", "ok" if _es_ing else "bad") + (ui_chip("Extra", "warn") if str(_r.get("es_extra", "")) == "SI" else "")
                    _filas += f'<div class="tp-row"><div class="tp-row-time">{str(_r["fecha_hora"])[11:16]}</div><div class="tp-row-main"><b>{"Ingreso" if _es_ing else "Salida"}</b><span>{_obs}</span></div><div class="tp-chips">{_chips}</div></div>'
                st.markdown(_filas, unsafe_allow_html=True)
                
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
            _MESES_HS = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                         "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
            _ahora_hs = obtener_ahora_peru()
            df_mis_sol["_f_reg_dt"] = pd.to_datetime(df_mis_sol["fecha_registro"], errors="coerce")

            _anios_hs = sorted({int(a) for a in df_mis_sol["_f_reg_dt"].dt.year.dropna().unique()} | {_ahora_hs.year}, reverse=True)
            _fh1, _fh2 = st.columns(2)
            _mes_hs = _fh1.selectbox(
                "Mes", [0] + list(range(1, 13)),
                index=_ahora_hs.month,
                format_func=lambda x: "Todos los meses" if x == 0 else _MESES_HS[x - 1],
                key="hist_sol_mes"
            )
            _anio_hs = _fh2.selectbox("Año", _anios_hs, index=_anios_hs.index(_ahora_hs.year), key="hist_sol_anio")

            df_mis_sol = df_mis_sol[df_mis_sol["_f_reg_dt"].dt.year == int(_anio_hs)]
            if _mes_hs != 0:
                df_mis_sol = df_mis_sol[df_mis_sol["_f_reg_dt"].dt.month == int(_mes_hs)]
            df_mis_sol = df_mis_sol.sort_values("_f_reg_dt", ascending=False)

            if df_mis_sol.empty:
                _txt_per = f"{_MESES_HS[_mes_hs - 1]} " if _mes_hs != 0 else ""
                st.info(f"No tienes solicitudes en {_txt_per}{_anio_hs}.")
            else:
                st.caption(f"{len(df_mis_sol)} solicitud(es) encontrada(s).")

            for _, r_sol in df_mis_sol.iterrows():
                st.markdown(ui_solicitud_card(r_sol), unsafe_allow_html=True)
                if r_sol['tipo_solicitud'] == "Trabajar Domingo (Descanso)" and r_sol["estado"] == "Aprobado":
                    st.success("Autorizado. Podrás marcar tu asistencia ese domingo desde 'Marcar Asistencia'.")
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
        st.markdown(f'<div class="tp-sec"><div><div class="tp-sec-title">Control operativo del día</div><div class="tp-sec-sub">Horas, puntualidad y caja por colaborador · {f_dash_str}</div></div>{ui_chip(f"{len(fichas_colaboradores)} colaboradores", "neutral")}</div>', unsafe_allow_html=True)
        _emp_op = st.session_state.empleados
        for nombre_col, datos in fichas_colaboradores.items():
            _fm = _emp_op[_emp_op["nombre"] == nombre_col]
            _dni_c = str(_fm.iloc[0]["dni"]) if not _fm.empty else ""
            _foto_c = str(_fm.iloc[0].get("foto", "")) if not _fm.empty else ""
            st.markdown(ui_op_card(nombre_col, datos, _dni_c, _foto_c), unsafe_allow_html=True)

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

        # --- PERMISOS RECUPERADOS (Permiso Laboral aprobado / Permiso de Salud a recuperar) ---
        # Si el colaborador pidió permiso o se enfermó pero ya recuperó el día, NO cuenta como falta.
        _asist_fechas_colab = set()
        if not df_asist_b.empty:
            _asist_fechas_colab = {parsear_fecha_segura(_x) for _x in df_asist_b[df_asist_b["nombre"] == colab_b_sel]["fecha"].astype(str).tolist()}
            _asist_fechas_colab.discard(None)

        fechas_recuperacion_colab = set()
        permisos_recuperados_cnt = 0
        permisos_recuperados_detalle = []

        # a) Permiso Laboral aprobado con día de recuperación (se considera recuperado si asistió ese día)
        df_sol_rec = st.session_state.solicitudes.copy()
        if not df_sol_rec.empty:
            df_sol_rec = df_sol_rec[
                (df_sol_rec["nombre"] == colab_b_sel) &
                (df_sol_rec["tipo_solicitud"] == "Permiso Laboral") &
                (df_sol_rec["estado"] == "Aprobado")
            ]
            for _, _s in df_sol_rec.iterrows():
                _f_perm = parsear_fecha_segura(_s.get("fecha_permiso", ""))
                _f_rec = parsear_fecha_segura(_s.get("fecha_recuperacion", ""))
                if not _f_rec:
                    continue
                fechas_recuperacion_colab.add(_f_rec)
                if (_f_perm and _f_perm.month == mes_b_sel and _f_perm.year == anio_b_sel
                        and _f_perm.weekday() != 6
                        and _f_perm not in _asist_fechas_colab
                        and _f_rec in _asist_fechas_colab):
                    permisos_recuperados_cnt += 1
                    permisos_recuperados_detalle.append(f"Permiso {_f_perm.strftime('%d/%m')} → recuperado el {_f_rec.strftime('%d/%m')}")

        # b) Permiso de Salud (a recuperar): recuperado si el admin lo marcó "Recuperado" o si asistió el día de recuperación
        df_vac_rec = st.session_state.vacaciones.copy()
        if not df_vac_rec.empty:
            df_vac_rec = df_vac_rec[
                (df_vac_rec["nombre"].astype(str) == colab_b_sel) &
                (df_vac_rec["tipo"] == "Permiso de Salud (a recuperar)")
            ]
            for _, _v in df_vac_rec.iterrows():
                _f_ini_v = parsear_fecha_segura(_v.get("fecha_inicio", ""))
                _f_fin_v = parsear_fecha_segura(_v.get("fecha_fin", ""))
                _f_rec_v = parsear_fecha_segura(_v.get("fecha_recuperacion", ""))
                if _f_rec_v:
                    fechas_recuperacion_colab.add(_f_rec_v)
                _recuperado_v = (str(_v.get("estado_recuperacion", "")).strip() == "Recuperado") or (_f_rec_v is not None and _f_rec_v in _asist_fechas_colab)
                if not (_f_ini_v and _f_fin_v and _recuperado_v):
                    continue
                _dias_sin_asist = []
                _d_it = _f_ini_v
                while _d_it <= _f_fin_v:
                    if (_d_it.month == mes_b_sel and _d_it.year == anio_b_sel
                            and _d_it.weekday() != 6 and _d_it not in _asist_fechas_colab):
                        _dias_sin_asist.append(_d_it)
                    _d_it += timedelta(days=1)
                if _dias_sin_asist:
                    permisos_recuperados_cnt += 1
                    _txt_rec_v = f" → recuperado el {_f_rec_v.strftime('%d/%m')}" if _f_rec_v else " → recuperado"
                    permisos_recuperados_detalle.append(f"Permiso de salud {_dias_sin_asist[0].strftime('%d/%m')}{_txt_rec_v}")

        if not df_asist_b.empty:
            df_asist_b["fecha_dt"] = pd.to_datetime(df_asist_b["fecha"], errors="coerce")
            df_asist_user = df_asist_b[
                (df_asist_b["nombre"] == colab_b_sel) & 
                (df_asist_b["fecha_dt"].dt.month == mes_b_sel) & 
                (df_asist_b["fecha_dt"].dt.year == anio_b_sel)
            ]
            
            if not df_asist_user.empty:
                _fechas_user = pd.to_datetime(df_asist_user["fecha"].drop_duplicates(), errors="coerce").dropna()
                dias_trabajados_cnt = int((_fechas_user.dt.weekday != 6).sum())
                
                df_asist_user["dt"] = pd.to_datetime(df_asist_user["fecha_hora"])
                for f_dia, grupo_dia in df_asist_user.groupby("fecha"):
                    _, mins_e, _, _ = calcular_jornada_y_horas_extras(grupo_dia)
                    hrs_extras_totales += (mins_e / 60.0)

                    if not st.session_state.feriados.empty and str(f_dia) in st.session_state.feriados["fecha"].astype(str).values:
                        dt_f = pd.to_datetime(f_dia)
                        if dt_f.weekday() != 6:  # No es domingo
                            feriados_trabajados_cnt += 1

                    dt_dia_check = pd.to_datetime(f_dia)
                    if dt_dia_check.weekday() == 6 and dt_dia_check.date() not in fechas_recuperacion_colab and grupo_dia["observacion"].astype(str).str.contains("TRABAJO VOLUNTARIO EN DOMINGO", case=False, na=False).any():
                        domingos_voluntarios_cnt += 1

        # Domingos de descanso semanal: son pagados, se suman a los días laborados (tope 30 días)
        domingos_descanso_pagados = 0
        if dias_trabajados_cnt + permisos_recuperados_cnt > 0:
            _f_ini_emp = parsear_fecha_segura(finicio_b_val)
            _f_cese_emp = parsear_fecha_segura(row_trab.iloc[0].get("fecha_cese", "")) if not row_trab.empty else None
            _dias_mes_b = pd.Period(f"{int(anio_b_sel)}-{int(mes_b_sel):02d}").days_in_month
            _hoy_b = ahora_p_b.date()
            for _d in pd.date_range(start=f"{int(anio_b_sel)}-{int(mes_b_sel):02d}-01", periods=_dias_mes_b):
                if _d.weekday() == 6:
                    _dd = _d.date()
                    if _dd > _hoy_b:
                        continue  # Domingos futuros aún no se devengan
                    if _f_ini_emp and _dd < _f_ini_emp:
                        continue
                    if _f_cese_emp and _dd > _f_cese_emp:
                        continue
                    domingos_descanso_pagados += 1
            dias_trabajados_cnt = min(30, dias_trabajados_cnt + domingos_descanso_pagados + permisos_recuperados_cnt)

        # Días transcurridos del mes: si el mes está en curso solo se evalúan los días que ya pasaron
        _hoy_falt = ahora_p_b.date()
        _inicio_mes_b = pd.Timestamp(year=int(anio_b_sel), month=int(mes_b_sel), day=1).date()
        if _inicio_mes_b > _hoy_falt:
            _dias_evaluables = 0  # Mes futuro
        elif (_inicio_mes_b.year, _inicio_mes_b.month) == (_hoy_falt.year, _hoy_falt.month):
            _dias_evaluables = min(30, _hoy_falt.day)  # Mes en curso
        else:
            _dias_evaluables = 30  # Mes cerrado
        dias_faltas_cnt = max(0, _dias_evaluables - dias_trabajados_cnt)

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

        # Incidencias y daños del mes (se excluyen las condonadas)
        incidencias_monto = 0.0
        incidencias_cnt = 0
        df_inc_b = st.session_state.incidencias.copy()
        if not df_inc_b.empty:
            df_inc_b["f_dt"] = pd.to_datetime(df_inc_b["fecha"], errors="coerce")
            df_inc_u = df_inc_b[
                (df_inc_b["nombre"] == colab_b_sel) &
                (df_inc_b["f_dt"].dt.month == mes_b_sel) &
                (df_inc_b["f_dt"].dt.year == anio_b_sel) &
                (df_inc_b["estado"].astype(str) != "Resuelto / Condonado")
            ]
            if not df_inc_u.empty:
                incidencias_cnt = len(df_inc_u)
                incidencias_monto = float(pd.to_numeric(df_inc_u["valor_reparacion"], errors="coerce").fillna(0).sum())

        st.markdown("---")
        st.markdown("##### Valores y Conceptos Calculados")
        
        if permisos_recuperados_cnt > 0:
            st.info("🔄 **Permisos recuperados (no se cuentan como falta):** " + " | ".join(permisos_recuperados_detalle))

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

        c_inc1, c_inc2 = st.columns(2)
        incidencias_in = c_inc1.number_input("Incidencias / Daños (S/.)", min_value=0.0, value=float(incidencias_monto), step=1.0, format="%.2f", key=f"boleta_incidencias_{colab_b_sel}_{mes_b_sel}_{anio_b_sel}")
        with c_inc2:
            st.caption(f"Se descuentan las incidencias del mes registradas por el colaborador ({incidencias_cnt} registrada(s)), excepto las marcadas como 'Resuelto / Condonado'.")

        c_b1, c_b2, c_b3 = st.columns(3)
        bono_puntualidad_in = c_b1.number_input("Bono por Puntualidad (S/.)", min_value=0.0, value=0.0, step=5.0, format="%.2f", key="boleta_bono_puntualidad")
        bono_presencia_in = c_b2.number_input("Bono Presencia y Uniforme (S/.)", min_value=0.0, value=0.0, step=5.0, format="%.2f", key="boleta_bono_presencia")
        bono_orden_in = c_b3.number_input("Bono Orden y Limpieza (S/.)", min_value=0.0, value=0.0, step=5.0, format="%.2f", key="boleta_bono_orden")

        # FÓRMULAS DE CÁLCULO
        valor_dia = sueldo_basico_in / 30.0 if sueldo_basico_in > 0 else 0.0
        valor_hora = valor_dia / 5.75 if valor_dia > 0 else 0.0

        monto_feriados_calc = feriados_trab_in * (valor_dia * 1.0)
        monto_horas_extras_calc = hrs_extras_in * (valor_hora * 1.25)
        monto_faltas_calc = dias_faltas_in * valor_dia
        monto_domingo_volunt_calc = domingo_volunt_in * (valor_dia * 1.0)

        total_ingresos_calc = sueldo_basico_in + monto_feriados_calc + monto_horas_extras_calc + monto_domingo_volunt_calc + bono_puntualidad_in + bono_presencia_in + bono_orden_in
        total_descuentos_calc = adelanto_in + monto_faltas_calc + descuadre_caja_in + desc_inventario_in + consumos_in + incidencias_in
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
            "permisos_recuperados": permisos_recuperados_cnt,
            "feriados_trabajados": feriados_trab_in,
            "horas_extras_hrs": hrs_extras_in,
            "sueldo_basico": sueldo_basico_in,
            "monto_feriados": monto_feriados_calc,
            "monto_horas_extras": monto_horas_extras_calc,
            "domingos_voluntarios": domingo_volunt_in,
            "monto_domingos_voluntarios": monto_domingo_volunt_calc,
            "bono_puntualidad": bono_puntualidad_in,
            "bono_presencia_uniforme": bono_presencia_in,
            "bono_orden_limpieza": bono_orden_in,
            "adelanto_sueldo": adelanto_in,
            "monto_faltas": monto_faltas_calc,
            "descuadre_caja": descuadre_caja_in,
            "descuadre_inventario": desc_inventario_in,
            "consumos_pagar": consumos_in,
            "incidencias_danos": incidencias_in,
            "total_ingresos": total_ingresos_calc,
            "total_descuentos": total_descuentos_calc,
            "neto_pagar": neto_pagar_calc
        }

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("##### Previsualización de la Boleta de Pago")

        st.markdown(generar_html_boleta(datos_boleta), unsafe_allow_html=True)

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
        # --- SELECTOR DE MES PARA LAS MÉTRICAS ---
        NOMBRES_MESES_SOL = [
            "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
            "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
        ]
        ahora_p_sol = obtener_ahora_peru()
        col_mes_sol, col_anio_sol, _col_sp_sol = st.columns([1, 1, 2])
        mes_sol_sel = col_mes_sol.selectbox(
            "Seleccionar Mes",
            [0] + list(range(1, 13)),
            index=ahora_p_sol.month,
            format_func=lambda x: "Todos los meses" if x == 0 else NOMBRES_MESES_SOL[x - 1],
            key="sol_mes_resumen"
        )
        anio_sol_sel = col_anio_sol.number_input(
            "Año", min_value=2024, max_value=2030, value=ahora_p_sol.year,
            key="sol_anio_resumen", disabled=(mes_sol_sel == 0)
        )

        df_sol_metricas = df_sol_base.copy()
        if mes_sol_sel != 0:
            _fecha_sol_dt = pd.to_datetime(df_sol_metricas["fecha_registro"], errors="coerce")
            df_sol_metricas = df_sol_metricas[
                (_fecha_sol_dt.dt.month == mes_sol_sel) & (_fecha_sol_dt.dt.year == anio_sol_sel)
            ]
        etiqueta_periodo_sol = "Total" if mes_sol_sel == 0 else NOMBRES_MESES_SOL[mes_sol_sel - 1]

        total_pend = len(df_sol_metricas[df_sol_metricas["estado"] == "Pendiente"])
        total_aprob = len(df_sol_metricas[df_sol_metricas["estado"] == "Aprobado"])
        total_rechaz = len(df_sol_metricas[df_sol_metricas["estado"] == "Rechazado"])
        monto_adel_aprob = pd.to_numeric(
            df_sol_metricas[(df_sol_metricas["tipo_solicitud"] == "Adelanto de Sueldo") & (df_sol_metricas["estado"] == "Aprobado")]["monto_adelanto"],
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
            st.markdown(f'<div class="info-card"><div class="info-label">Adelantos Aprobados ({etiqueta_periodo_sol})</div><div class="info-value">S/. {monto_adel_aprob:.2f}</div></div>', unsafe_allow_html=True)

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
            
            with ui_card_container(f"sol_{id_s}"):
                st.markdown(ui_solicitud_card(row_sol, admin=True), unsafe_allow_html=True)
                if tipo_s == "Permiso Laboral":
                    _fr = pd.to_datetime(str(row_sol.get("fecha_recuperacion", "")).strip(), errors="coerce")
                    if pd.notna(_fr) and _fr.dayofweek == 6:
                        st.caption("La recuperación está programada para domingo.")
                elif tipo_s == "Trabajar Domingo (Descanso)":
                    st.caption("Este domingo es normalmente su día de descanso semanal. Al aprobar, el colaborador podrá marcar asistencia ese día y se reflejará como día adicional en su boleta.")
                if est_s == "Pendiente":
                    c_obs, c_ap, c_rc = st.columns([2.4, 1, 1])
                    resp_admin_input = c_obs.text_input("Observación", key=f"resp_{id_s}", placeholder="Observación para el colaborador (opcional)", label_visibility="collapsed")
                    if c_ap.button("Aprobar", key=f"ap_{id_s}", use_container_width=True):
                        idx_real = st.session_state.solicitudes[st.session_state.solicitudes["id_solicitud"] == id_s].index
                        st.session_state.solicitudes.loc[idx_real, "estado"] = "Aprobado"
                        st.session_state.solicitudes.loc[idx_real, "respuesta_admin"] = resp_admin_input
                        actualizar_hoja_completa("Solicitudes", st.session_state.solicitudes)
                        registrar_auditoria("Aprobar Solicitud", "Solicitudes", f"{tipo_s} de {nom_s} ({id_s})")
                        st.toast("Solicitud Aprobada")
                        time.sleep(0.3)
                        st.rerun()
                    if c_rc.button("Rechazar", key=f"rec_{id_s}", use_container_width=True):
                        idx_real = st.session_state.solicitudes[st.session_state.solicitudes["id_solicitud"] == id_s].index
                        st.session_state.solicitudes.loc[idx_real, "estado"] = "Rechazado"
                        st.session_state.solicitudes.loc[idx_real, "respuesta_admin"] = resp_admin_input
                        actualizar_hoja_completa("Solicitudes", st.session_state.solicitudes)
                        registrar_auditoria("Rechazar Solicitud", "Solicitudes", f"{tipo_s} de {nom_s} ({id_s})")
                        st.toast("Solicitud Rechazada")
                        time.sleep(0.3)
                        st.rerun()

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

        _f_ini_mes = f"{int(anio_desc_sel)}-{mes_desc_sel:02d}-01"
        _validos = obtener_solo_colaboradores(_f_ini_mes)  # excluye a quienes ya cesaron antes del mes
        colabs_operativos = list(dict.fromkeys(_validos + [n for n in df_desc_mes["nombre"].unique().tolist() if n in obtener_solo_colaboradores()]))
        _per = f"{NOMBRES_MESES[mes_desc_sel-1]} {int(anio_desc_sel)}"

        if not df_desc_mes.empty:
            _sob = df_desc_mes[df_desc_mes["monto_num"] > 0]["monto_num"].sum()
            _fal = df_desc_mes[df_desc_mes["monto_num"] < 0]["monto_num"].sum()
            _bal = df_desc_mes["monto_num"].sum()
            kd1, kd2, kd3 = st.columns(3)
            kd1.markdown(ui_kpi(f"Sobrantes · {_per}", f"S/. {_sob:.2f}"), unsafe_allow_html=True)
            kd2.markdown(ui_kpi(f"Faltantes · {_per}", f"S/. {abs(_fal):.2f}"), unsafe_allow_html=True)
            kd3.markdown(ui_kpi(f"Balance neto · {_per}", f"S/. {_bal:.2f}"), unsafe_allow_html=True)
            st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
            _sin_mov = []
            for nombre_colab in colabs_operativos:
                df_c = df_desc_mes[df_desc_mes["nombre"] == nombre_colab]
                if df_c.empty:
                    _sin_mov.append(nombre_colab)
                    continue
                _d, _f = ui_dni_foto(nombre_colab)
                st.markdown(ui_desc_card(nombre_colab, df_c, _d, _f), unsafe_allow_html=True)
            if _sin_mov:
                st.markdown('<div class="tp-card"><div class="tp-note-t">Sin descuadres en el mes</div><div class="tp-chips" style="justify-content:flex-start">' + "".join(ui_chip(_html.escape(n), "neutral") for n in _sin_mov) + '</div></div>', unsafe_allow_html=True)
        else:
            st.info(f"No hay descuadres registrados en el mes de {_per}.")

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
            m1.markdown(ui_kpi("Total sobrantes (+)", f"S/. {sobrantes:.2f}"), unsafe_allow_html=True)
            m2.markdown(ui_kpi("Total faltantes (-)", f"S/. {abs(faltantes):.2f}"), unsafe_allow_html=True)
            m3.markdown(ui_kpi("Balance neto", f"S/. {balance:.2f}"), unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("##### Ranking de Colaboradores (según filtro aplicado)")

            df_rank_desc = df_desc_filtrado.groupby("nombre")["monto_num"].sum().reset_index().rename(columns={"monto_num": "balance"})
            df_rank_desc = df_rank_desc.sort_values("balance")

            if not df_rank_desc.empty:
                rk1, rk2 = st.columns(2)
                with rk1:
                    st.markdown("**Mayores faltantes**")
                    peores = df_rank_desc[df_rank_desc["balance"] < 0].head(5)
                    if not peores.empty:
                        st.markdown(ui_rank_rows(peores, "bad"), unsafe_allow_html=True)
                    else:
                        st.success("Nadie registra faltantes en este período.")
                with rk2:
                    st.markdown("**Mejores balances**")
                    mejores = df_rank_desc[df_rank_desc["balance"] >= 0].sort_values("balance", ascending=False).head(5)
                    if not mejores.empty:
                        st.markdown(ui_rank_rows(mejores, "ok"), unsafe_allow_html=True)
                    else:
                        st.info("Sin balances positivos registrados en este período.")

                st.bar_chart(df_rank_desc.set_index("nombre")["balance"])

            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("#####  Balance de Descuadres por Trabajador")
            
            for nombre_trab, df_trab in df_desc_filtrado.groupby("nombre"):
                _d, _f = ui_dni_foto(nombre_trab)
                st.markdown(ui_desc_card(nombre_trab, df_trab, _d, _f), unsafe_allow_html=True)

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
            cliente_dni_bf = bf2.text_input("DNI del Cliente (opcional)", value="12345678", key="bf_dni", help="Si el cliente no quiere dar su DNI, deja 12345678.")

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
                    if not cliente_dni_bf.strip():
                        cliente_dni_bf = "12345678"
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

            filas_punt = []
            for nom_p in sorted(df_asist_filtrado["nombre"].unique().tolist()):
                metrica_p = calcular_metricas_puntualidad(df_asist_filtrado, nom_p)
                if metrica_p["total_ingresos"] > 0:
                    filas_punt.append({"Colaborador": nom_p, "Ingresos": metrica_p["total_ingresos"], "Puntuales": metrica_p["puntuales"],
                                       "Tardanzas": metrica_p["tardanzas"], "Minutos": metrica_p["minutos_acumulados"], "Pct": metrica_p["ratio"]})
            tot_i = sum(f["Ingresos"] for f in filas_punt); tot_p = sum(f["Puntuales"] for f in filas_punt)
            tot_t = sum(f["Tardanzas"] for f in filas_punt); tot_m = sum(f["Minutos"] for f in filas_punt)
            a1, a2, a3, a4 = st.columns(4)
            a1.markdown(ui_kpi("Total de marcaciones", str(total_marcas), f"{colabs_unicos} colaborador(es)"), unsafe_allow_html=True)
            a2.markdown(ui_kpi("Ingresos registrados", str(ingresos_cnt), "marcas de entrada"), unsafe_allow_html=True)
            a3.markdown(ui_kpi("Puntualidad global", f"{tot_p / tot_i * 100 if tot_i else 100:.1f}%", f"{tot_p} de {tot_i} ingresos a tiempo"), unsafe_allow_html=True)
            a4.markdown(ui_kpi("Tardanzas", str(tot_t), f"{tot_m} min acumulados"), unsafe_allow_html=True)
            st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

            por_dia = df_asist_filtrado.groupby("fecha").size().sort_index().tail(31)
            if len(por_dia) > 1:
                st.markdown(ui_panel("Actividad por día", "Marcaciones registradas en el período", ui_columnas([ui_dia_label(d) for d in por_dia.index], [("Marcaciones", [int(v) for v in por_dia.values], "#0F172A")], alto=190)), unsafe_allow_html=True)
                st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

            if filas_punt:
                rk_html = ""
                for f in sorted(filas_punt, key=lambda x: x["Pct"]):
                    tono = "ok" if f["Pct"] >= 90 else ("warn" if f["Pct"] >= 75 else "bad")
                    d_, ft_ = ui_dni_foto(f["Colaborador"])
                    rk_html += (f'<div class="tp-rk">{ui_avatar(f["Colaborador"], d_, ft_, 40)}<div class="tp-rk-main"><b>{_html.escape(str(f["Colaborador"]))}</b>'
                                f'<div class="tp-prog {tono}"><i style="width:{f["Pct"]}%"></i></div></div><div class="tp-rk-pct">{f["Pct"]:g}%</div>'
                                f'<div class="tp-chips">{ui_chip(str(f["Ingresos"]) + " ingresos", "neutral")}{ui_chip(str(f["Tardanzas"]) + " tardanzas", "bad" if f["Tardanzas"] else "ok")}{ui_chip(str(f["Minutos"]) + " min", "warn" if f["Minutos"] else "neutral")}</div></div>')
                rk1, rk2 = st.columns([1.5, 1])
                rk1.markdown(ui_panel("Ranking de puntualidad", "Primero quienes necesitan más atención", rk_html), unsafe_allow_html=True)
                top_t = sorted([(f["Colaborador"], f["Tardanzas"]) for f in filas_punt if f["Tardanzas"] > 0], key=lambda x: -x[1])[:8]
                rk2.markdown(ui_panel("Tardanzas por colaborador", "Según el filtro aplicado", ui_hbars(top_t, "#EC3237")), unsafe_allow_html=True)
            else:
                st.info("No hay ingresos registrados para calcular puntualidad en este filtro.")

            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("##### Registro Detallado de Asistencias")
            try:
                _c_tab, _c_tar = st.container(key="vista_tabla"), st.container(key="vista_tarjetas")
            except TypeError:
                _c_tab, _c_tar = st.container(), None
            with _c_tab:
                st.dataframe(df_asist_filtrado, use_container_width=True, hide_index=True)
            if _c_tar is not None:
                with _c_tar:
                    _flt = ""
                    for _, _a in df_asist_filtrado.sort_values("fecha_hora", ascending=False).head(40).iterrows():
                        _ing = str(_a["tipo"]) == "INGRESO"
                        _ch = ui_chip("Ingreso" if _ing else "Salida", "ok" if _ing else "bad") + (ui_chip("Extra", "warn") if str(_a.get("es_extra", "")) == "SI" else "")
                        _flt += f'<div class="tp-row">{ui_avatar(_a["nombre"], _a.get("dni", ""), "", 40)}<div class="tp-row-main"><b>{_html.escape(str(_a["nombre"]))}</b><span>{str(_a["fecha_hora"])[:16]}</span></div><div class="tp-chips">{_ch}</div></div>'
                    st.markdown(_flt, unsafe_allow_html=True)
                    st.caption("Se muestran las 40 marcaciones más recientes. Exporta a Excel para ver todo.")
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

    e_ = _html.escape
    _svg = lambda d: f"<svg width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'>{d}</svg>"
    _IC = {
        "contratos": _svg("<rect x='4' y='5' width='16' height='15' rx='2'/><path d='M8 3v4M16 3v4M4 10h16'/>"),
        "tardanzas": _svg("<circle cx='12' cy='12' r='9'/><path d='M12 7v5l3 2'/>"),
        "solicitudes": _svg("<path d='M4 13l2-8h12l2 8v6H4z'/><path d='M4 13h5l1 2h4l1-2h5'/>"),
        "permisos": _svg("<rect x='4' y='4' width='16' height='16' rx='3'/><path d='M12 8v8M8 12h8'/>"),
        "ok": _svg("<path d='M5 12l4 4 10-10'/>"),
        "cumples": _svg("<rect x='3' y='9' width='18' height='12' rx='2'/><path d='M12 9v12M3 14h18'/><path d='M12 9c-3 0-4-4-1.5-4S12 9 12 9zM12 9c3 0 4-4 1.5-4S12 9 12 9z'/>"),
    }
    sol_df = st.session_state.solicitudes
    sol_pend_df = sol_df[sol_df["estado"] == "Pendiente"] if not sol_df.empty else sol_df
    vac_df = st.session_state.vacaciones
    perm_df = vac_df[(vac_df["tipo"] == "Permiso de Salud (a recuperar)") & (vac_df["estado_recuperacion"] != "Recuperado")] if not vac_df.empty else vac_df

    def _fila(nombre, sub, chip_html):
        d_, f_ = ui_dni_foto(nombre)
        return f'<div class="tp-row">{ui_avatar(nombre, d_, f_, 42)}<div class="tp-row-main"><b>{e_(str(nombre))}</b><span class="wrap">{sub}</span></div><div class="tp-chips">{chip_html}</div></div>'

    g_contr = [_fila(n, f"Cese programado el {f.strftime('%d/%m/%Y')} · evaluar renovación o cese", ui_chip(f"en {d} día(s)", "bad" if d <= 5 else "warn")) for n, f, d in sorted(contratos_por_vencer, key=lambda x: x[2])]
    g_tard = [_fila(n, f"{c} tardanzas este mes · {m} min de retraso acumulado", ui_chip(f"{c} tardanzas", "bad")) for n, c, m in sorted(tardanzas_recurrentes, key=lambda x: -x[1])]
    g_sol = [_fila(r["nombre"], f"{e_(str(r['tipo_solicitud']))} · {str(r['fecha_registro'])[:10]}", ui_chip("Pendiente", "warn")) for _, r in sol_pend_df.sort_values("fecha_registro", ascending=False).head(6).iterrows()]
    if len(sol_pend_df) > 6:
        g_sol.append(f'<div class="tp-card-sub" style="padding:4px 4px 0">y {len(sol_pend_df) - 6} solicitud(es) más…</div>')
    g_perm = [_fila(r["nombre"], f"Recuperar el {r['fecha_recuperacion']} · {e_(str(r['horario_recuperacion']) or 'horario no especificado')}", ui_chip("Sin recuperar", "warn")) for _, r in perm_df.iterrows()]
    g_cum = [_fila(n, f"Cumple años el {f.strftime('%d/%m')}", ui_chip("¡Hoy!", "ok") if d == 0 else ui_chip(f"en {d} día(s)", "info")) for n, f, d in sorted(cumples_prox, key=lambda x: x[2])]

    grupos = [
        {"k": "contratos", "t": "Contratos por vencer", "s": "Próximos 15 días", "n": len(contratos_por_vencer), "tono": "bad" if any(d <= 5 for _, _, d in contratos_por_vencer) else "warn", "f": g_contr, "dest": "Gestión Colaboradores", "btn": "Ir a Colaboradores"},
        {"k": "tardanzas", "t": "Tardanzas recurrentes", "s": "3 o más en el mes actual", "n": len(tardanzas_recurrentes), "tono": "bad", "f": g_tard, "dest": "Historial de Asistencias", "btn": "Ver asistencias"},
        {"k": "solicitudes", "t": "Solicitudes pendientes", "s": "Esperan tu respuesta", "n": len(sol_pend_df), "tono": "warn", "f": g_sol, "dest": "Solicitudes y Permisos", "btn": "Revisar solicitudes"},
        {"k": "permisos", "t": "Permisos de salud sin recuperar", "s": "Horas por recuperar", "n": len(perm_df), "tono": "warn", "f": g_perm, "dest": "Gestión de Vacaciones", "btn": "Ir a Vacaciones"},
        {"k": "cumples", "t": "Cumpleaños de la semana", "s": "Próximos 7 días", "n": len(cumples_prox), "tono": "info", "f": g_cum, "dest": None, "btn": ""},
    ]
    urgentes = sum(g["n"] for g in grupos if g["k"] != "cumples")
    if urgentes == 0:
        st.markdown(f'<div class="tp-banner ok"><span class="tp-al-ico ok">{_IC["ok"]}</span><div><b>Todo en orden</b><span class="s">No hay alertas que requieran tu atención ahora mismo.</span></div></div>', unsafe_allow_html=True)
    else:
        resumen = "".join(ui_chip(f"{g['n']} · {g['t']}", g["tono"]) for g in grupos if g["n"] and g["k"] != "cumples")
        st.markdown(f'<div class="tp-banner {"bad" if any(g["tono"] == "bad" and g["n"] for g in grupos) else "warn"}"><div><b>Tienes {urgentes} alerta(s) que requieren atención</b><span class="s" style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px">{resumen}</span></div></div>', unsafe_allow_html=True)
    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

    for col_k, g in zip(st.columns(5), grupos):
        tono_k = g["tono"] if g["n"] else "ok"
        col_k.markdown(f'<div class="tp-kpi al-{tono_k}"><div class="tp-kpi-lbl">{g["t"]}</div><div class="tp-kpi-val">{g["n"]}</div><div class="tp-kpi-sub">{"Requiere atención" if g["n"] and g["k"] != "cumples" else ("Para saludar" if g["n"] else "Sin novedades")}</div></div>', unsafe_allow_html=True)
    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)

    orden = {"bad": 0, "warn": 1, "info": 2}
    for g in sorted([x for x in grupos if x["n"]], key=lambda x: orden[x["tono"]]):
        with ui_card_container(f"al_{g['k']}"):
            st.markdown(f'<div class="tp-card flat"><div class="tp-card-head"><div class="tp-op-head" style="margin:0"><span class="tp-al-ico {g["tono"]}">{_IC[g["k"]]}</span><div><div class="tp-card-title">{g["t"]}</div><div class="tp-card-sub">{g["s"]}</div></div></div>{ui_chip(str(g["n"]), g["tono"])}</div></div><div style="height:10px"></div>' + "".join(g["f"]), unsafe_allow_html=True)
            if g["dest"]:
                _b1, _b2 = st.columns([3, 1.3])
                _b2.button(g["btn"], key=f"al_btn_{g['k']}", on_click=_gs_ir, args=(g["dest"],), use_container_width=True)

    sin_nov = [g for g in grupos if not g["n"]]
    if sin_nov:
        st.markdown('<div class="tp-card"><div class="tp-note-t">Sin novedades</div><div class="tp-chips" style="justify-content:flex-start">' + "".join(ui_chip(g["t"], "ok") for g in sin_nov) + '</div></div>', unsafe_allow_html=True)


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

        _cd1, _cd2 = st.columns(2)
        f_ini_vac = _cd1.date_input("Fecha de Inicio", value=obtener_ahora_peru().date(), key="vac_f_ini")
        f_fin_vac = _cd2.date_input("Fecha de Fin", value=obtener_ahora_peru().date(), key="vac_f_fin")
        if f_fin_vac >= f_ini_vac:
            st.caption(f"Total del período: **{(f_fin_vac - f_ini_vac).days + 1} día(s)**")

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
        _cards = ""
        for _, _fs in df_saldo_vac.sort_values("Saldo Disponible").iterrows():
            _d, _f = ui_dni_foto(_fs["Colaborador"])
            _cards += ui_saldo_card(_fs["Colaborador"], {"dias_generados": _fs["Días Generados"], "dias_gozados": _fs["Días Gozados"], "saldo_disponible": _fs["Saldo Disponible"]}, _d, _f)
        st.markdown(f'<div class="tp-grid2">{_cards}</div>', unsafe_allow_html=True)
        st.download_button("Exportar Saldos a Excel", to_excel(df_saldo_vac), "Saldos_Vacacionales.xlsx", use_container_width=True)
    else:
        st.info("No hay colaboradores activos en planilla con beneficio vacacional aplicable.")

    if filas_no_planilla:
        st.markdown('<div class="tp-card"><div class="tp-note-t">No están en planilla (sin beneficio vacacional)</div><div class="tp-chips" style="justify-content:flex-start">' + "".join(ui_chip(_html.escape(n), "neutral") for n in filas_no_planilla) + '</div></div>', unsafe_allow_html=True)

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
            with ui_card_container(f"vac_{idx_pr}"):
                st.markdown(ui_vac_card(r_pr, admin=True), unsafe_allow_html=True)
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
        _vac_ord = st.session_state.vacaciones.sort_values("fecha_registro", ascending=False)
        try:
            _c_tab, _c_tar = st.container(key="vista_tabla"), st.container(key="vista_tarjetas")
        except TypeError:
            _c_tab, _c_tar = st.container(), None
        with _c_tab:
            st.dataframe(_vac_ord, use_container_width=True, hide_index=True)
        if _c_tar is not None:
            with _c_tar:
                st.markdown("".join(ui_vac_card(_rv, admin=True) .replace('tp-card flat', 'tp-card') for _, _rv in _vac_ord.head(30).iterrows()), unsafe_allow_html=True)
                st.caption("Se muestran los 30 registros más recientes. Exporta a Excel para ver todo.")
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
        st.markdown(ui_saldo_card(user_actual, mi_saldo, dni_actual, _foto_actual, hero=True), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("##### Mi Historial de Descansos y Permisos")
    if not st.session_state.vacaciones.empty:
        df_mis_vac = st.session_state.vacaciones[st.session_state.vacaciones["nombre"] == user_actual]
        if not df_mis_vac.empty:
            for _, _rv in df_mis_vac.sort_values("fecha_inicio", ascending=False).iterrows():
                st.markdown(ui_vac_card(_rv), unsafe_allow_html=True)
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

    tab_bi1, tab_bi2, tab_bi3 = st.tabs(["Costo de planilla", "Rotación de personal", "Tendencia de puntualidad"])
    _hoy_bi = obtener_ahora_peru().date()
    _a_d = lambda f: ((f.date() if hasattr(f, "date") else f) if f else None)
    _SP = "<div style='height:14px'></div>"
    _inicio_todo = pd.Timestamp(2000, 1, 1).date()
    _fin_todo = pd.Timestamp(2100, 12, 31).date()

    with ui_card_container("bi_filtros"):
        fb1, fb2, fb3 = st.columns([1, 1.2, 1])
        pre_bi = fb1.selectbox("Período", ["Todo el historial", "Este mes", "Últimos 3 meses", "Últimos 6 meses", "Este año", "Personalizado"], key="bi_pre")
        if pre_bi == "Personalizado":
            rg_bi = fb2.date_input("Rango de fechas (de – hasta)", value=(_hoy_bi.replace(day=1), _hoy_bi), key="bi_rango")
            rg_bi = list(rg_bi) if isinstance(rg_bi, (tuple, list)) else [rg_bi]
            d_ini, d_fin = rg_bi[0], (rg_bi[1] if len(rg_bi) > 1 else rg_bi[0])
        else:
            _m0 = pd.Timestamp(_hoy_bi.replace(day=1))
            d_ini = {"Todo el historial": _inicio_todo, "Este mes": _m0.date(), "Últimos 3 meses": (_m0 - pd.DateOffset(months=2)).date(),
                     "Últimos 6 meses": (_m0 - pd.DateOffset(months=5)).date(), "Este año": _hoy_bi.replace(month=1, day=1)}[pre_bi]
            d_fin = _fin_todo if pre_bi == "Todo el historial" else _hoy_bi
            _lbl_rg = "Se analiza todo el registro" if pre_bi == "Todo el historial" else f"{d_ini:%d/%m/%Y} – {d_fin:%d/%m/%Y}"
            fb2.markdown(f'<div style="padding-top:27px">{ui_chip(_lbl_rg, "info")}</div>', unsafe_allow_html=True)
        colab_bi = fb3.selectbox("Colaborador", ["Todos"] + sorted(obtener_solo_colaboradores()), key="bi_colab")
    ym_ini, ym_fin = d_ini.strftime("%Y-%m"), d_fin.strftime("%Y-%m")
    st.markdown(_SP, unsafe_allow_html=True)

    def _cab_colab():
        if colab_bi != "Todos":
            _d, _f = ui_dni_foto(colab_bi)
            st.markdown(f'<div class="tp-row">{ui_avatar(colab_bi, _d, _f, 44)}<div class="tp-row-main"><b>{_html.escape(colab_bi)}</b><span>Analítica individual dentro del período seleccionado</span></div>{ui_chip("Vista individual", "info")}</div>', unsafe_allow_html=True)

    # ---------------- COSTO DE PLANILLA ----------------
    with tab_bi1:
        _cab_colab()
        if st.session_state.boletas_historial.empty:
            st.info("Aún no hay boletas guardadas en el historial. Ve a 'Boletas de Pago', genera una boleta y usa el botón 'Guardar esta Boleta en el Historial'.")
        else:
            df_bh = st.session_state.boletas_historial.copy()
            for _c in ["neto_pagar", "total_ingresos", "total_descuentos"]:
                df_bh[_c] = pd.to_numeric(df_bh[_c], errors="coerce").fillna(0)
            df_bh["_ym"] = pd.to_numeric(df_bh["anio"], errors="coerce").fillna(0).astype(int).astype(str) + "-" + df_bh["mes"].apply(_mes_a_num).astype(str).str.zfill(2)
            df_bh = df_bh[(df_bh["_ym"] >= ym_ini) & (df_bh["_ym"] <= ym_fin)]
            if colab_bi != "Todos":
                df_bh = df_bh[df_bh["nombre"] == colab_bi]
            if df_bh.empty:
                st.info("No hay boletas registradas para el período y colaborador seleccionados.")
            else:
                res = df_bh.groupby("_ym")["neto_pagar"].sum().sort_index()
                ing_m = df_bh.groupby("_ym")["total_ingresos"].sum().sort_index()
                des_m = df_bh.groupby("_ym")["total_descuentos"].sum().sort_index()
                ult, prev = float(res.iloc[-1]), (float(res.iloc[-2]) if len(res) > 1 else 0)
                delta = ui_chip(f'{"▲" if ult >= prev else "▼"} {abs((ult - prev) / prev * 100):.1f}% vs período anterior', "neutral") if prev else ui_chip("Primer período registrado", "neutral")
                tot_ing, tot_des = df_bh["total_ingresos"].sum(), df_bh["total_descuentos"].sum()
                b1, b2, b3, b4 = st.columns(4)
                b1.markdown(ui_kpi("Costo neto de planilla", f"S/. {df_bh['neto_pagar'].sum():,.2f}", f"{len(df_bh)} boletas · {df_bh['nombre'].nunique()} colaborador(es)"), unsafe_allow_html=True)
                b2.markdown(ui_kpi("Promedio mensual", f"S/. {res.mean():,.2f}", f"{len(res)} período(s) registrados"), unsafe_allow_html=True)
                b3.markdown(ui_kpi(f"Último período · {ui_mes_label(res.index[-1])}", f"S/. {ult:,.2f}", delta), unsafe_allow_html=True)
                b4.markdown(ui_kpi("Descuentos acumulados", f"S/. {tot_des:,.2f}", f"{tot_des / tot_ing * 100:.1f}% de los ingresos brutos" if tot_ing else "Sin ingresos registrados"), unsafe_allow_html=True)
                st.markdown(_SP, unsafe_allow_html=True)
                lbl = [ui_mes_label(i) for i in res.index]
                g1, g2 = st.columns([1.6, 1])
                with g1:
                    st.markdown(ui_panel("Costo neto por período", "Neto a pagar acumulado (S/.)", ui_columnas(lbl, [("Neto a pagar", [round(v) for v in res.values], "#EC3237")], fmt="{:,.0f}")), unsafe_allow_html=True)
                    st.markdown(_SP, unsafe_allow_html=True)
                    st.markdown(ui_panel("Ingresos vs. descuentos", "Evolución mensual (S/.)", ui_columnas(lbl, [("Ingresos", [round(v) for v in ing_m.values], "#0F172A"), ("Descuentos", [round(v) for v in des_m.values], "#F59E0B")], fmt="{:,.0f}")), unsafe_allow_html=True)
                with g2:
                    top = df_bh.groupby("nombre")["neto_pagar"].sum().sort_values(ascending=False).head(8)
                    st.markdown(ui_panel("Mayor costo acumulado", "Top 8 por neto pagado", ui_hbars(list(top.items()), "#0F172A", "S/. {:,.0f}")), unsafe_allow_html=True)
                    st.markdown(_SP, unsafe_allow_html=True)
                    topd = df_bh.groupby("nombre")["total_descuentos"].sum().sort_values(ascending=False).head(8)
                    st.markdown(ui_panel("Descuentos acumulados por trabajador", "Faltas, adelantos, descuadres y otros", ui_hbars([(n, v) for n, v in topd.items() if v > 0], "#F59E0B", "S/. {:,.0f}")), unsafe_allow_html=True)
                st.markdown(_SP, unsafe_allow_html=True)
                det = df_bh.groupby("nombre")[["total_ingresos", "total_descuentos", "neto_pagar"]].sum().sort_values("neto_pagar", ascending=False)
                mxn = max(det["neto_pagar"].max(), 1)
                filas_t = ""
                for nom, r in det.iterrows():
                    d_, f_ = ui_dni_foto(nom)
                    pd_ = r["total_descuentos"] / r["total_ingresos"] * 100 if r["total_ingresos"] else 0
                    filas_t += (f'<div class="tp-rk">{ui_avatar(nom, d_, f_, 40)}<div class="tp-rk-main"><b>{_html.escape(str(nom))}</b><div class="tp-prog"><i style="width:{int(r["neto_pagar"] / mxn * 100)}%"></i></div></div>'
                                f'<div class="tp-chips">{ui_chip("Ingresos S/. " + format(r["total_ingresos"], ",.0f"), "neutral")}{ui_chip("Desc. S/. " + format(r["total_descuentos"], ",.0f"), "warn")}{ui_chip(f"{pd_:.1f}% desc.", "bad" if pd_ >= 20 else "ok")}</div>'
                                f'<div class="tp-rk-pct" style="min-width:96px">S/. {r["neto_pagar"]:,.0f}</div></div>')
                st.markdown(ui_panel("Detalle por trabajador", "Neto pagado, ingresos y porcentaje de descuentos", filas_t), unsafe_allow_html=True)
                with st.expander("Ver detalle de boletas emitidas"):
                    st.dataframe(df_bh.drop(columns=["_ym"]).sort_values("fecha_emision", ascending=False), use_container_width=True, hide_index=True)
                    st.download_button("Exportar Historial de Boletas a Excel", to_excel(df_bh.drop(columns=["_ym"])), "Boletas_Historial.xlsx", use_container_width=True)

    # ---------------- ROTACIÓN Y PERMANENCIA ----------------
    with tab_bi2:
        _cab_colab()
        emp_bi = st.session_state.empleados.copy()
        if "rol" in emp_bi.columns:
            emp_bi = emp_bi[emp_bi["rol"] != "admin"]
        if colab_bi != "Todos":
            emp_bi = emp_bi[emp_bi["nombre"] == colab_bi]
        filas_e = []
        for _, r in emp_bi.iterrows():
            fi = _a_d(_parsear_fecha_nac_cumple(r.get("fecha_inicio", "")))
            fc = _a_d(_parsear_fecha_nac_cumple(r.get("fecha_cese", "")))
            if not fi:
                continue
            filas_e.append({"nombre": r["nombre"], "cargo": str(r.get("cargo", "")), "fi": fi, "fc": fc,
                            "activo": fc is None and str(r.get("estado", "")).lower() == "activo", "meses": max(0.0, ((fc or _hoy_bi) - fi).days / 30.4375)})
        if not filas_e:
            st.info("No hay suficientes datos de fechas de ingreso/cese para calcular rotación.")
        else:
            dft = pd.DataFrame(filas_e)
            fmt_t = lambda m: f"{int(m // 12)} a {int(m % 12)} m" if m >= 12 else f"{m:.1f} meses"
            altas_p = dft[(dft["fi"] >= d_ini) & (dft["fi"] <= d_fin)]
            bajas_p = dft[dft["fc"].apply(lambda x: x is not None and d_ini <= x <= d_fin)]
            n_act = int(dft["activo"].sum())
            altas_m = altas_p["fi"].apply(lambda x: x.strftime("%Y-%m")).value_counts().to_dict()
            bajas_m = bajas_p["fc"].apply(lambda x: x.strftime("%Y-%m")).value_counts().to_dict()
            r1, r2, r3, r4 = st.columns(4)
            r1.markdown(ui_kpi("Colaboradores activos", str(n_act), "equipo actual"), unsafe_allow_html=True)
            r2.markdown(ui_kpi("Altas en el período", str(len(altas_p)), "nuevos ingresos"), unsafe_allow_html=True)
            r3.markdown(ui_kpi("Bajas en el período", str(len(bajas_p)), "ceses registrados"), unsafe_allow_html=True)
            r4.markdown(ui_kpi("Tasa de rotación", f"{len(bajas_p) / max(1, n_act + len(bajas_p)) * 100:.0f}%", "bajas sobre el total del equipo"), unsafe_allow_html=True)
            st.markdown(_SP, unsafe_allow_html=True)
            d_baja, d_act = dft[~dft["activo"]], dft[dft["activo"]]
            mayor = dft.sort_values("meses", ascending=False).iloc[0]
            q1, q2, q3, q4 = st.columns(4)
            q1.markdown(ui_kpi("Permanencia promedio", fmt_t(dft["meses"].mean()), f"{len(dft)} colaborador(es) analizados"), unsafe_allow_html=True)
            q2.markdown(ui_kpi("Permanencia de quienes se fueron", fmt_t(d_baja["meses"].mean()) if len(d_baja) else "-", f"{len(d_baja)} baja(s) registradas" if len(d_baja) else "Aún sin bajas"), unsafe_allow_html=True)
            q3.markdown(ui_kpi("Antigüedad del personal activo", fmt_t(d_act["meses"].mean()) if len(d_act) else "-", "promedio actual"), unsafe_allow_html=True)
            q4.markdown(ui_kpi("Mayor permanencia", fmt_t(mayor["meses"]), _html.escape(str(mayor["nombre"]))), unsafe_allow_html=True)
            st.markdown(_SP, unsafe_allow_html=True)
            ev = [x.strftime("%Y-%m") for x in list(dft["fi"]) + [c for c in dft["fc"] if c is not None]]
            ini_m, fin_m = max(ym_ini, min(ev)), min(ym_fin, _hoy_bi.strftime("%Y-%m"))
            rango = [str(x) for x in pd.period_range(ini_m, fin_m, freq="M")][-24:] if ini_m <= fin_m else []
            g1, g2 = st.columns([1.6, 1])
            with g1:
                if rango:
                    st.markdown(ui_panel("Altas y bajas por mes", "Hasta 24 meses dentro del período", ui_columnas([ui_mes_label(m) for m in rango], [("Altas", [altas_m.get(m, 0) for m in rango], "#0B8F57"), ("Bajas", [bajas_m.get(m, 0) for m in rango], "#EC3237")])), unsafe_allow_html=True)
                else:
                    st.info("No hay movimientos dentro del período seleccionado.")
            with g2:
                cargos = d_act["cargo"].value_counts()
                st.markdown(ui_panel("Equipo activo por cargo", "Distribución actual", ui_hbars(list(cargos.items()), "#0F172A")), unsafe_allow_html=True)
            st.markdown(_SP, unsafe_allow_html=True)
            h1, h2 = st.columns([1.3, 1])
            top_p = dft.sort_values("meses", ascending=False).head(12)
            h1.markdown(ui_panel("Permanencia por colaborador", "Oscuro: activo · Rojo: dado de baja", ui_hbars([(r["nombre"], r["meses"], "#0F172A" if r["activo"] else "#EC3237") for _, r in top_p.iterrows()], fmt=fmt_t)), unsafe_allow_html=True)
            etq = ["< 3 meses", "3–6 meses", "6–12 meses", "1–2 años", "2+ años"]
            cat = pd.cut(dft["meses"], bins=[-0.01, 3, 6, 12, 24, 10**4], labels=etq)
            cnt_a = cat[dft["activo"]].value_counts().reindex(etq, fill_value=0)
            cnt_b = cat[~dft["activo"]].value_counts().reindex(etq, fill_value=0)
            h2.markdown(ui_panel("Distribución de permanencia", "Cuántos colaboradores hay en cada tramo", ui_columnas(etq, [("Activos", [int(v) for v in cnt_a.values], "#0F172A"), ("Dados de baja", [int(v) for v in cnt_b.values], "#EC3237")], alto=210)), unsafe_allow_html=True)

    # ---------------- PUNTUALIDAD ----------------
    with tab_bi3:
        _cab_colab()
        if st.session_state.asistencia.empty:
            st.info("No hay datos de asistencia registrados.")
        else:
            dfa = st.session_state.asistencia.copy()
            dfa["fecha_dt"] = pd.to_datetime(dfa["fecha"], errors="coerce")
            dfa = dfa.dropna(subset=["fecha_dt"])
            dfa = dfa[(dfa["fecha_dt"].dt.date >= d_ini) & (dfa["fecha_dt"].dt.date <= d_fin) & (dfa["nombre"].isin(obtener_solo_colaboradores()))]
            if colab_bi != "Todos":
                dfa = dfa[dfa["nombre"] == colab_bi]
            ing = dfa[(dfa["tipo"] == "INGRESO") & (dfa["es_extra"].astype(str) != "SI")].copy()
            if ing.empty:
                st.info("No hay ingresos registrados para el período y colaborador seleccionados.")
            else:
                tp = ing["fecha_hora"].apply(calcular_tardanza_ingreso)
                ing["tard"] = tp.map(lambda t: bool(t[1]))
                ing["mins"] = tp.map(lambda t: int(t[0]) if t[1] else 0)
                ing["ym"] = ing["fecha_dt"].dt.strftime("%Y-%m")
                ing["dow"] = ing["fecha_dt"].dt.dayofweek
                tard = ing[ing["tard"]]
                pm = ing.groupby("ym").agg(n=("tard", "size"), t=("tard", "sum"), m=("mins", "sum"))
                meses_p = list(pm.index)
                n_i, n_t, n_m = int(pm["n"].sum()), int(pm["t"].sum()), int(pm["m"].sum())
                dias_n = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
                dow_t = tard.groupby("dow").size().reindex(range(7), fill_value=0)
                por_per = ing.groupby("nombre")["tard"].sum()
                p1, p2, p3, p4 = st.columns(4)
                p1.markdown(ui_kpi("Puntualidad global", f"{(n_i - n_t) / n_i * 100:.1f}%", f"{n_i} ingresos evaluados"), unsafe_allow_html=True)
                p2.markdown(ui_kpi("Tardanzas totales", str(n_t), f"{n_m} min acumulados"), unsafe_allow_html=True)
                p3.markdown(ui_kpi("Mes con más tardanzas", ui_mes_label(pm["t"].idxmax()) if n_t else "-", f"{int(pm['t'].max())} tardanza(s)" if n_t else "Sin tardanzas"), unsafe_allow_html=True)
                p4.markdown(ui_kpi("Minutos por tardanza", f"{n_m / n_t:.1f}" if n_t else "0", "promedio"), unsafe_allow_html=True)
                st.markdown(_SP, unsafe_allow_html=True)
                q1, q2, q3, q4 = st.columns(4)
                q1.markdown(ui_kpi("Colaboradores 100% puntuales", f"{int((por_per == 0).sum())} de {len(por_per)}", "sin ninguna tardanza"), unsafe_allow_html=True)
                q2.markdown(ui_kpi("Día más crítico", dias_n[int(dow_t.idxmax())] if n_t else "-", f"{int(dow_t.max())} tardanza(s)" if n_t else "Sin tardanzas"), unsafe_allow_html=True)
                q3.markdown(ui_kpi("Tiempo perdido", f"{n_m / 60:.1f} h", "por tardanzas en el período"), unsafe_allow_html=True)
                q4.markdown(ui_kpi("Tardanza más larga", f"{int(tard['mins'].max())} min" if n_t else "-", _html.escape(str(tard.loc[tard['mins'].idxmax(), 'nombre'])) if n_t else "Sin tardanzas"), unsafe_allow_html=True)
                st.markdown(_SP, unsafe_allow_html=True)
                lbl = [ui_mes_label(m) for m in meses_p]
                g1, g2 = st.columns(2)
                g1.markdown(ui_panel("Tardanzas por mes", "Evolución en el período", ui_linea(lbl, [int(pm.loc[m, "t"]) for m in meses_p], "#EC3237")), unsafe_allow_html=True)
                g2.markdown(ui_panel("Puntualidad por mes", "% de ingresos a tiempo", ui_linea(lbl, [round(100 - pm.loc[m, "t"] / pm.loc[m, "n"] * 100, 1) for m in meses_p], "#0B8F57", "{:g}", "%")), unsafe_allow_html=True)
                st.markdown(_SP, unsafe_allow_html=True)
                k1, k2 = st.columns(2)
                k1.markdown(ui_panel("Tardanzas por día de la semana", "¿Qué días se llega más tarde?", ui_columnas(dias_n, [("Tardanzas", [int(v) for v in dow_t.values], "#EC3237")], alto=200)), unsafe_allow_html=True)
                grav = pd.cut(tard["mins"], bins=[0, 5, 15, 30, 60, 10**5], labels=["1–5 min", "6–15 min", "16–30 min", "31–60 min", "+60 min"]).value_counts().reindex(["1–5 min", "6–15 min", "16–30 min", "31–60 min", "+60 min"], fill_value=0)
                k2.markdown(ui_panel("Gravedad de las tardanzas", "Cuántos minutos se llega tarde", ui_columnas(list(grav.index), [("Tardanzas", [int(v) for v in grav.values], "#F59E0B")], alto=200)), unsafe_allow_html=True)
                por_dia = tard.groupby("fecha")["mins"].sum().sort_index().tail(31)
                if len(por_dia) > 1:
                    st.markdown(_SP, unsafe_allow_html=True)
                    st.markdown(ui_panel("Minutos de tardanza por día", "Últimos 31 días con tardanzas", ui_columnas([ui_dia_label(d) for d in por_dia.index], [("Minutos", [int(v) for v in por_dia.values], "#0F172A")], alto=190)), unsafe_allow_html=True)
                st.markdown(_SP, unsafe_allow_html=True)
                ext = {}
                try:
                    for (nom_x, f_x), gx in dfa.groupby(["nombre", "fecha"]):
                        gx = gx.copy()
                        gx["dt"] = pd.to_datetime(gx["fecha_hora"], errors="coerce")
                        gx = gx.dropna(subset=["dt"])
                        if not gx.empty:
                            ext[str(f_x)[:7]] = ext.get(str(f_x)[:7], 0) + calcular_jornada_y_horas_extras(gx)[1]
                except Exception:
                    ext = {}
                e1, e2 = st.columns(2)
                e1.markdown(ui_panel("Horas extras por mes", "Tiempo trabajado sobre la jornada base de 5h 45m", ui_linea(lbl, [round(ext.get(m, 0) / 60, 1) for m in meses_p], "#F59E0B", "{:g}", " h")), unsafe_allow_html=True)
                if colab_bi == "Todos":
                    top_t = sorted([(n, int(v)) for n, v in por_per.items() if v > 0], key=lambda x: -x[1])[:8]
                    e2.markdown(ui_panel("Colaboradores con más tardanzas", "Acumulado en el período", ui_hbars(top_t, "#EC3237")), unsafe_allow_html=True)
                else:
                    ult_t = tard.sort_values("fecha_hora", ascending=False).head(8)
                    filas_u = "".join(f'<div class="tp-row"><div class="tp-row-time">{ui_dia_label(r["fecha"])}</div><div class="tp-row-main"><b>Ingreso a las {str(r["fecha_hora"])[11:16]}</b></div><div class="tp-chips">{ui_chip(str(int(r["mins"])) + " min tarde", "bad")}</div></div>' for _, r in ult_t.iterrows()) or '<div class="tp-card-sub">Sin tardanzas en el período.</div>'
                    e2.markdown(ui_panel("Últimas tardanzas", "Detalle del colaborador", filas_u), unsafe_allow_html=True)

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
