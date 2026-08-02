import streamlit as st
import pandas as pd
from datetime import datetime, date
import io
import time
import gspread
from google.oauth2.service_account import Credentials

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="Control Asistencia & Caja | Premium Market",
    page_icon="🛍️",
    layout="wide"
)

# --- ESTILOS CORPORATIVOS ---
st.markdown("""
<style>
.main { background-color: #f8f9fa; }
.stButton>button {
    background-color: #1071B8;
    color: white;
    border-radius: 5px;
    border: none;
    font-weight: bold;
    width: 100%;
    height: 3em;
}
.stButton>button:hover { border: 2px solid #07456a; color: #07456a; }
h1, h2, h3 { color: #07456a !important; font-family: 'Segoe UI', sans-serif; }

.info-card {
    background-color: white;
    padding: 15px;
    border-radius: 10px;
    border-left: 5px solid #1071B8;
    box-shadow: 2px 2px 5px rgba(0,0,0,0.05);
    margin-bottom: 15px;
    height: 100%;
}

.info-label { color: #6c757d; font-size: 0.75rem; font-weight: bold; text-transform: uppercase; }
.info-value { color: #07456a; font-size: 1.1rem; font-weight: bold; }

[data-testid="stSidebar"] { background-color: #07456a; }
[data-testid="stSidebar"] * { color: white !important; }

.footer {
    position: fixed;
    bottom: 10px;
    left: 0;
    right: 0;
    text-align: center;
    color: #6c757d;
    font-size: 12px;
    font-weight: bold;
}
</style>
""", unsafe_allow_html=True)

# --- CONEXIÓN GOOGLE SHEETS ---
@st.cache_resource(show_spinner="Conectando con Google Sheets...")
def conectar_google_sheets():
    try:
        scope = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        
        # Cargar diccionario de Secrets
        sec_dict = dict(st.secrets["gcp_service_account"])
        
        # Limpieza de posibles caracteres de escape en la clave privada
        if "private_key" in sec_dict:
            sec_dict["private_key"] = sec_dict["private_key"].replace("\\n", "\n")
            
        creds = Credentials.from_service_account_info(sec_dict, scopes=scope)
        client = gspread.authorize(creds)
        
        # Abrir el libro por nombre exacto
        sheet = client.open("BD_PremiumMarket")
        return sheet
    except Exception as e:
        st.error(f"❌ Error al conectar con Google Sheets: {e}")
        return None

doc_sheets = conectar_google_sheets()

# --- FUNCIONES DE LECTURA DE HOJAS ---
def cargar_hoja(nombre_hoja):
    if doc_sheets is None:
        return pd.DataFrame()
    try:
        ws = doc_sheets.worksheet(nombre_hoja)
        records = ws.get_all_records()
        return pd.DataFrame(records)
    except Exception as e:
        st.error(f"Error al cargar la hoja '{nombre_hoja}': {e}")
        return pd.DataFrame()

def insertar_fila(nombre_hoja, fila):
    if doc_sheets is None:
        st.error("No hay conexión activa con Google Sheets.")
        return False
    try:
        ws = doc_sheets.worksheet(nombre_hoja)
        ws.append_row(fila)
        return True
    except Exception as e:
        st.error(f"Error al insertar datos en '{nombre_hoja}': {e}")
        return False

def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False)
    return output.getvalue()

# --- VALIDACIÓN DE CONEXIÓN EN INTERFAZ ---
if doc_sheets is None:
    st.warning("⚠️ No hay conexión activa con la base de datos de Google Sheets.")
    if st.button("🔄 Reintentar Conexión"):
        st.cache_resource.clear()
        st.rerun()

# --- NAVEGACIÓN Y SIDEBAR ---
st.sidebar.markdown('<div style="font-size: 50px; text-align: center;">🛍️</div>', unsafe_allow_html=True)
st.sidebar.title("PREMIUM MARKET")
menu = ["Asistencia", "Control de Caja", "Colaboradores", "Historial General"]
choice = st.sidebar.radio("Navegación:", menu)

# -------------------- MÓDULO ASISTENCIA --------------------
if choice == "Asistencia":
    st.header("Registro de Asistencia")
    
    df_colab = cargar_hoja("Colaboradores")
    
    if not df_colab.empty and "dni" in df_colab.columns:
        lista_colab = df_colab["dni"].astype(str) + " - " + df_colab["nombres"].astype(str)
        
        with st.form("form_asistencia", clear_on_submit=True):
            col1, col2 = st.columns(2)
            colaborador_sel = col1.selectbox("Seleccionar Colaborador", lista_colab)
            tipo_marcacion = col2.selectbox("Tipo de Registro", ["Ingreso", "Salida Almuerzo", "Retorno Almuerzo", "Salida"])
            
            obs = st.text_area("Observaciones")
            
            if st.form_submit_button("REGISTRAR MARCACIÓN"):
                dni = colaborador_sel.split(" - ")[0]
                nombre = colaborador_sel.split(" - ")[1]
                fecha_hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                exito = insertar_fila("Asistencia", [dni, nombre, tipo_marcacion, fecha_hora, obs])
                if exito:
                    st.toast(f"Marcación de {tipo_marcacion} registrada para {nombre}", icon="✅")
                    time.sleep(1)
                    st.rerun()
    else:
        st.info("No se encontraron colaboradores registrados en la base de datos.")

# -------------------- MÓDULO CAJA --------------------
elif choice == "Control de Caja":
    st.header("Control de Caja Chiclayo / Sedes")
    
    tab1, tab2 = st.tabs(["Nuevo Movimiento", "Resumen del Día"])
    
    with tab1:
        with st.form("form_caja", clear_on_submit=True):
            c1, c2 = st.columns(2)
            tipo_mov = c1.selectbox("Tipo de Movimiento", ["Ingreso", "Egreso"])
            monto = c2.number_input("Monto (S/)", min_value=0.0, step=0.10)
            
            concepto = st.text_input("Concepto / Descripción")
            metodo = st.selectbox("Medio de Pago", ["Efectivo", "Yape/Plin", "Tarjeta", "Transferencia"])
            
            if st.form_submit_button("GUARDAR MOVIMIENTO"):
                fecha_hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                exito = insertar_fila("Caja", [fecha_hora, tipo_mov, monto, concepto, metodo])
                if exito:
                    st.toast("Movimiento de caja guardado con éxito", icon="💵")
                    time.sleep(1)
                    st.rerun()
                    
    with tab2:
        df_caja = cargar_hoja("Caja")
        if not df_caja.empty:
            st.dataframe(df_caja, use_container_width=True)
            st.download_button("Exportar Caja (Excel)", to_excel(df_caja), "Reporte_Caja.xlsx")
        else:
            st.info("No hay movimientos de caja registrados.")

# -------------------- MÓDULO COLABORADORES --------------------
elif choice == "Colaboradores":
    st.header("Gestión de Colaboradores")
    
    df_colab = cargar_hoja("Colaboradores")
    
    with st.expander("➕ Registrar Nuevo Colaborador"):
        with st.form("form_nuevo_colab", clear_on_submit=True):
            f1, f2 = st.columns(2)
            dni_in = f1.text_input("DNI")
            nombres_in = f2.text_input("Nombres y Apellidos")
            cargo_in = st.text_input("Cargo")
            
            if st.form_submit_button("REGISTRAR COLABORADOR"):
                if dni_in and nombres_in:
                    exito = insertar_fila("Colaboradores", [dni_in, nombres_in, cargo_in, "Activo"])
                    if exito:
                        st.toast("Colaborador registrado exitosamente", icon="👤")
                        time.sleep(1)
                        st.rerun()
                else:
                    st.error("DNI y Nombres son campos obligatorios.")
                    
    st.subheader("Lista de Colaboradores")
    if not df_colab.empty:
        st.dataframe(df_colab, use_container_width=True, hide_index=True)
    else:
        st.info("No hay registros de colaboradores.")

# -------------------- HISTORIAL GENERAL --------------------
elif choice == "Historial General":
    st.header("Historial y Auditoría General")
    
    opcion_hoja = st.selectbox("Seleccione la hoja a consultar:", ["Asistencia", "Caja", "Colaboradores"])
    df_hist = cargar_hoja(opcion_hoja)
    
    if not df_hist.empty:
        st.dataframe(df_hist, use_container_width=True)
        st.download_button(
            f"DESCARGAR {opcion_hoja.upper()}", 
            to_excel(df_hist), 
            f"Reporte_{opcion_hoja}_{datetime.now().strftime('%Y%m%d')}.xlsx"
        )
    else:
        st.info(f"No hay registros en la hoja {opcion_hoja}.")

st.markdown('<div class="footer">Desarrollado por Control de Gestión | Premium Market</div>', unsafe_allow_html=True)
