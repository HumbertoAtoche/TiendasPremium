import streamlit as st
import pandas as pd
from datetime import datetime
import pytz
import io

# ==========================================
# 1. CONFIGURACIÓN DE PÁGINA Y ESTILOS UI
# ==========================================
st.set_page_config(
    page_title="Control Operativo - Tiendas Premium",
    page_icon="🏪",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Estilos personalizados (CSS Inyectado)
st.markdown("""
    <style>
    /* Estilos generales y tipografía */
    .stApp {
        background-color: #F8FAFC;
    }
    
    /* Encabezado Principal */
    .market-header {
        background: linear-gradient(135deg, #1E3A8A 0%, #3B82F6 100%);
        padding: 24px 30px;
        border-radius: 14px;
        color: white;
        margin-bottom: 25px;
        box-shadow: 0 4px 12px rgba(30, 58, 138, 0.15);
    }
    .market-header h1 {
        margin: 0;
        font-size: 2rem;
        font-weight: 700;
        color: #FFFFFF !important;
        letter-spacing: -0.02em;
    }
    .market-header p {
        margin: 6px 0 0 0;
        opacity: 0.9;
        font-size: 1rem;
        font-weight: 400;
    }
    
    /* Tarjetas Métricas KPI */
    .info-card {
        background-color: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 12px;
        padding: 20px;
        text-align: center;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.02);
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .info-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 12px rgba(0, 0, 0, 0.05);
    }
    .info-label {
        font-size: 0.825rem;
        color: #64748B;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .info-value {
        font-size: 1.75rem;
        font-weight: 700;
        color: #0F172A;
        margin-top: 6px;
    }
    
    /* Secciones y Contenedores */
    .section-card {
        background: #FFFFFF;
        padding: 24px;
        border-radius: 12px;
        border: 1px solid #E2E8F0;
        margin-bottom: 20px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.02);
    }

    /* Tablas y Dataframes */
    .stDataFrame {
        border-radius: 8px;
        overflow: hidden;
    }
    
    /* Botones Personalizados */
    .stButton>button {
        border-radius: 8px;
        font-weight: 600;
    }
    </style>
""", unsafe_allow_html=True)


# ==========================================
# 2. FUNCIONES AUXILIARES Y PERSISTENCIA
# ==========================================
def obtener_ahora_peru():
    """Retorna la fecha y hora actual configurada para Perú (America/Lima)."""
    tz = pytz.timezone('America/Lima')
    return datetime.now(tz)

def conectar_gsheets():
    """
    Inicializa la conexión con Google Sheets si están configurados los Secrets.
    Si no existen secrets, trabaja en modo Local/Memoria.
    """
    try:
        from streamlit_gsheets import GSheetsConnection
        conn = st.connection("gsheets", type=GSheetsConnection)
        return conn
    except Exception:
        return None

def cargar_datos_hoja(nombre_hoja):
    """Carga un DataFrame desde Google Sheets o devuelve DataFrame vacío."""
    conn = conectar_gsheets()
    if conn:
        try:
            df = conn.read(worksheet=nombre_hoja, ttl=0)
            return df
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()

def guardar_colaborador_gsheets(dni, nombre, cargo, estado, clave, rol):
    """Registra o actualiza un colaborador en Google Sheets."""
    conn = conectar_gsheets()
    if conn:
        try:
            df_actual = conn.read(worksheet="Colaboradores", ttl=0)
            nuevo_registro = pd.DataFrame([{
                "dni": str(dni),
                "nombre": str(nombre),
                "cargo": str(cargo),
                "estado": str(estado),
                "clave": str(clave),
                "rol": str(rol)
            }])
            df_final = pd.concat([df_actual, nuevo_registro], ignore_index=True)
            conn.update(worksheet="Colaboradores", data=df_final)
        except Exception as e:
            st.error(f"Error al sincronizar con Google Sheets: {e}")

def actualizar_hoja_completa(nombre_hoja, df):
    """Actualiza masivamente una pestaña completa en Google Sheets."""
    conn = conectar_gsheets()
    if conn:
        try:
            conn.update(worksheet=nombre_hoja, data=df)
        except Exception as e:
            st.warning(f"No se pudo guardar en la nube (Google Sheets): {e}")

def obtener_solo_colaboradores():
    """Obtiene la lista de nombres de colaboradores activos."""
    if "empleados" in st.session_state and not st.session_state.empleados.empty:
        df_emp = st.session_state.empleados
        if "estado" in df_emp.columns:
            activos = df_emp[df_emp["estado"] == "Activo"]
            return activos["nombre"].tolist()
        return df_emp["nombre"].tolist()
    return []

def to_excel(df):
    """Convierte un DataFrame de pandas a un archivo binario de Excel (.xlsx)."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Reporte')
        workbook  = writer.book
        worksheet = writer.sheets['Reporte']
        
        # Formato básico de celdas
        header_format = workbook.add_format({
            'bold': True,
            'text_wrap': True,
            'valign': 'top',
            'fg_color': '#1E3A8A',
            'font_color': '#FFFFFF',
            'border': 1
        })
        
        for col_num, value in enumerate(df.columns.values):
            worksheet.write(0, col_num, value, header_format)
            worksheet.set_column(col_num, col_num, 20)
            
    return output.getvalue()


# ==========================================
# 3. INICIALIZACIÓN DEL ESTADO DE SESIÓN
# ==========================================
if "empleados" not in st.session_state:
    df_cloud = cargar_datos_hoja("Colaboradores")
    if not df_cloud.empty:
        st.session_state.empleados = df_cloud
    else:
        st.session_state.empleados = pd.DataFrame([
            {"dni": "72819203", "nombre": "Juan Pérez", "cargo": "Cajero", "estado": "Activo", "clave": "1234", "rol": "operativo"},
            {"dni": "10928374", "nombre": "Maria Lopez", "cargo": "Supervisora", "estado": "Activo", "clave": "admin123", "rol": "admin"},
            {"dni": "45678912", "nombre": "Carlos Mendoza", "cargo": "Reposidor", "estado": "Activo", "clave": "5678", "rol": "operativo"}
        ])

if "descuadres" not in st.session_state:
    df_cloud_desc = cargar_datos_hoja("Descuadres")
    if not df_cloud_desc.empty:
        st.session_state.descuadres = df_cloud_desc
    else:
        st.session_state.descuadres = pd.DataFrame(columns=["fecha", "nombre", "monto", "tipo", "observacion"])

if "asistencia" not in st.session_state:
    df_cloud_asist = cargar_datos_hoja("Asistencia")
    if not df_cloud_asist.empty:
        st.session_state.asistencia = df_cloud_asist
    else:
        st.session_state.asistencia = pd.DataFrame(columns=["fecha_hora", "fecha", "nombre", "tipo"])

if "arqueos" not in st.session_state:
    df_cloud_arq = cargar_datos_hoja("Arqueos")
    if not df_cloud_arq.empty:
        st.session_state.arqueos = df_cloud_arq
    else:
        st.session_state.arqueos = pd.DataFrame(columns=[
            "fecha_hora", "fecha", "cajero", "b200", "b100", "b50", "b20", "b10",
            "m5", "m2", "m1", "m_cent", "total_efectivo", "total_tarjeta", "total_general", "observacion"
        ])

if "rol_actual" not in st.session_state:
    st.session_state.rol_actual = "admin"

rol_actual = st.session_state.rol_actual


# ==========================================
# 4. MENÚ LATERAL Y NAVEGACIÓN
# ==========================================
st.sidebar.title("🏪 Tiendas Premium")
st.sidebar.caption("Sistema Integrado de Control Operativo")
st.sidebar.markdown("---")

choice = st.sidebar.radio("Módulos del Sistema:", [
    "Reloj Marcador (Asistencia)",
    "Arqueo de Caja",
    "Registro de Descuadre",
    "Gestión de Personal",
    "Historial de Descuadres",
    "Historial de Asistencias",
    "Historial de Arqueos"
])

st.sidebar.markdown("---")
st.sidebar.subheader("🔒 Configuración de Rol")
rol_seleccionado = st.sidebar.selectbox("Rol Visualizado:", ["admin", "operativo"], index=0 if rol_actual == "admin" else 1)
st.session_state.rol_actual = rol_seleccionado


# ==========================================
# BLOQUE 1: RELOJ MARCADOR (ASISTENCIA)
# ==========================================
if choice == "Reloj Marcador (Asistencia)":
    st.markdown("""
        <div class="market-header">
            <h1>Reloj Marcador de Personal</h1>
            <p>Control automatizado de asistencia, entradas y salidas de turno</p>
        </div>
    """, unsafe_allow_html=True)

    col_marc1, col_marc2 = st.columns([1, 1.2], gap="large")

    with col_marc1:
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("⏱️ Registrar Marcación")
        
        colabs = obtener_solo_colaboradores()
        if not colabs:
            st.warning("No hay colaboradores activos registrados en la base de datos.")
        else:
            colab_sel = st.selectbox("Seleccione su Nombre Completo", colabs)
            clave_ingresada = st.text_input("Ingrese su Contraseña Personal", type="password", help="Su clave personal de 4 a 8 dígitos")
            tipo_marca = st.radio("Seleccione Tipo de Registro", ["INGRESO", "SALIDA"], horizontal=True)

            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Confirmar Registro de Asistencia", type="primary", use_container_width=True):
                if not clave_ingresada:
                    st.error("Por favor ingrese su contraseña para validar la marcación.")
                else:
                    emp_match = st.session_state.empleados[
                        (st.session_state.empleados["nombre"] == colab_sel) & 
                        (st.session_state.empleados["clave"] == clave_ingresada)
                    ]
                    
                    if not emp_match.empty:
                        ahora = obtener_ahora_peru()
                        nueva_marca = {
                            "fecha_hora": ahora.strftime("%Y-%m-%d %H:%M:%S"),
                            "fecha": str(ahora.date()),
                            "nombre": colab_sel,
                            "tipo": tipo_marca
                        }
                        st.session_state.asistencia = pd.concat([st.session_state.asistencia, pd.DataFrame([nueva_marca])], ignore_index=True)
                        actualizar_hoja_completa("Asistencia", st.session_state.asistencia)
                        st.success(f"✅ ¡Marcación de **{tipo_marca}** exitosa para **{colab_sel}** a las {ahora.strftime('%H:%M:%S')}!")
                        st.rerun()
                    else:
                        st.error("❌ Contraseña incorrecta. Verifique sus credenciales.")
        st.markdown('</div>', unsafe_allow_html=True)

    with col_marc2:
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("📋 Registros de Hoy")
        hoy_str = str(obtener_ahora_peru().date())
        
        if not st.session_state.asistencia.empty:
            df_hoy = st.session_state.asistencia[st.session_state.asistencia["fecha"] == hoy_str]
            if not df_hoy.empty:
                st.dataframe(
                    df_hoy[["fecha_hora", "nombre", "tipo"]].sort_values(by="fecha_hora", ascending=False),
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "fecha_hora": "HORA Y FECHA",
                        "nombre": "COLABORADOR",
                        "tipo": "TIPO MARCA"
                    }
                )
            else:
                st.info("No se registran marcas de asistencia en la fecha actual.")
        else:
            st.info("El historial de asistencia se encuentra completamente vacío.")
        st.markdown('</div>', unsafe_allow_html=True)


# ==========================================
# BLOQUE 2: ARQUEO Y CIERRE DE CAJA
# ==========================================
elif choice == "Arqueo de Caja":
    st.markdown("""
        <div class="market-header">
            <h1>Arqueo y Cierre de Caja</h1>
            <p>Conteo físico detallado de billetes, monedas y transacciones bancarias/POS</p>
        </div>
    """, unsafe_allow_html=True)

    colabs = obtener_solo_colaboradores()
    if not colabs:
        st.error("Debe registrar al menos un colaborador antes de realizar arqueos.")
    else:
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        cajero_sel = st.selectbox("Cajero Responsable del Cierre", colabs)
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown("### 💵 Desglose de Efectivo Físico en Soles (S/.)")
        
        c1, c2, c3 = st.columns(3, gap="medium")

        with c1:
            st.markdown('<div class="section-card">', unsafe_allow_html=True)
            st.markdown("##### Billetes Altas Denominaciones")
            cant_b200 = st.number_input("Billetes S/. 200", min_value=0, step=1, key="b200")
            cant_b100 = st.number_input("Billetes S/. 100", min_value=0, step=1, key="b100")
            cant_b50  = st.number_input("Billetes S/. 50", min_value=0, step=1, key="b50")
            
            sub_b200 = cant_b200 * 200
            sub_b100 = cant_b100 * 100
            sub_b50  = cant_b50 * 50
            st.caption(f"Subtotal: S/. {sub_b200 + sub_b100 + sub_b50:.2f}")
            st.markdown('</div>', unsafe_allow_html=True)

        with c2:
            st.markdown('<div class="section-card">', unsafe_allow_html=True)
            st.markdown("##### Billetes Bajas Denominaciones")
            cant_b20 = st.number_input("Billetes S/. 20", min_value=0, step=1, key="b20")
            cant_b10 = st.number_input("Billetes S/. 10", min_value=0, step=1, key="b10")
            cant_m5  = st.number_input("Monedas S/. 5", min_value=0, step=1, key="m5")
            
            sub_b20 = cant_b20 * 20
            sub_b10 = cant_b10 * 10
            sub_m5  = cant_m5 * 5
            st.caption(f"Subtotal: S/. {sub_b20 + sub_b10 + sub_m5:.2f}")
            st.markdown('</div>', unsafe_allow_html=True)

        with c3:
            st.markdown('<div class="section-card">', unsafe_allow_html=True)
            st.markdown("##### Monedas y Fraccionarios")
            cant_m2    = st.number_input("Monedas S/. 2", min_value=0, step=1, key="m2")
            cant_m1    = st.number_input("Monedas S/. 1", min_value=0, step=1, key="m1")
            cant_mcent = st.number_input("Centavos Totales (S/.)", min_value=0.0, step=0.10, format="%.2f", key="mcent")
            
            sub_m2 = cant_m2 * 2
            sub_m1 = cant_m1 * 1
            st.caption(f"Subtotal: S/. {sub_m2 + sub_m1 + cant_mcent:.2f}")
            st.markdown('</div>', unsafe_allow_html=True)

        total_efectivo = sub_b200 + sub_b100 + sub_b50 + sub_b20 + sub_b10 + sub_m5 + sub_m2 + sub_m1 + cant_mcent

        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        col_pos, col_obs = st.columns([1, 1], gap="medium")

        with col_pos:
            st.markdown("##### 💳 Ventas Electrónicas y Tarjetas")
            total_tarjetas = st.number_input("Monto Total POS / Yape / Plin / Transferencias (S/.)", min_value=0.0, step=1.0, format="%.2f")
            total_arqueo = total_efectivo + total_tarjetas
            
            st.markdown("---")
            st.markdown(f"#### Total Efectivo: **S/. {total_efectivo:.2f}**")
            st.markdown(f"#### Total Electrónico: **S/. {total_tarjetas:.2f}**")
            st.markdown(f"### Total Arqueado General: <span style='color:#00A959;'>S/. {total_arqueo:.2f}</span>", unsafe_allow_html=True)

        with col_obs:
            st.markdown("##### 📝 Observaciones y Registro")
            obs_caja = st.text_area("Observaciones de Cierre / Justificaciones de Sobrantes o Faltantes", height=130)

            if st.button("💾 Guardar y Finalizar Arqueo de Caja", type="primary", use_container_width=True):
                ahora = obtener_ahora_peru()
                nuevo_arqueo = {
                    "fecha_hora": ahora.strftime("%Y-%m-%d %H:%M:%S"),
                    "fecha": str(ahora.date()),
                    "cajero": cajero_sel,
                    "b200": cant_b200, "b100": cant_b100, "b50": cant_b50,
                    "b20": cant_b20, "b10": cant_b10, "m5": cant_m5,
                    "m2": cant_m2, "m1": cant_m1, "m_cent": cant_mcent,
                    "total_efectivo": total_efectivo,
                    "total_tarjeta": total_tarjetas,
                    "total_general": total_arqueo,
                    "observacion": obs_caja
                }
                st.session_state.arqueos = pd.concat([st.session_state.arqueos, pd.DataFrame([nuevo_arqueo])], ignore_index=True)
                actualizar_hoja_completa("Arqueos", st.session_state.arqueos)
                st.toast("✅ Arqueo de caja guardado con éxito", icon="🎉")
                st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)


# ==========================================
# BLOQUE 3: REGISTRO DE DESCUADRE
# ==========================================
elif choice == "Registro de Descuadre":
    st.markdown("""
        <div class="market-header">
            <h1>Registro de Descuadre de Caja</h1>
            <p>Módulo de declaración de faltantes y sobrantes detectados en caja</p>
        </div>
    """, unsafe_allow_html=True)

    colabs = obtener_solo_colaboradores()
    if not colabs:
        st.error("No existen colaboradores en la base de datos.")
    else:
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        with st.form("form_descuadre", clear_on_submit=True):
            col_d1, col_d2 = st.columns(2, gap="medium")
            
            with col_d1:
                colab_desc = st.selectbox("Colaborador / Cajero Responsable", colabs)
                tipo_desc = st.selectbox("Naturaleza del Descuadre", ["Faltante", "Sobrante"])
            
            with col_d2:
                monto_desc = st.number_input("Monto Absoluto del Descuadre (S/.)", min_value=0.01, step=0.50, format="%.2f")
                fecha_desc = st.date_input("Fecha de Ocurrencia", value=obtener_ahora_peru().date())

            obs_desc = st.text_area("Explicación Detallada / Motivo del Descuadre", height=100)

            st.markdown("<br>", unsafe_allow_html=True)
            submit_desc = st.form_submit_button("🚨 Registrar Descuadre de Caja", type="primary", use_container_width=True)

            if submit_desc:
                monto_final = monto_desc if tipo_desc == "Sobrante" else -monto_desc
                nuevo_registro = {
                    "fecha": str(fecha_desc),
                    "nombre": colab_desc,
                    "monto": monto_final,
                    "tipo": tipo_desc,
                    "observacion": obs_desc
                }
                st.session_state.descuadres = pd.concat([st.session_state.descuadres, pd.DataFrame([nuevo_registro])], ignore_index=True)
                actualizar_hoja_completa("Descuadres", st.session_state.descuadres)
                st.success(f"Descuadre del tipo {tipo_desc} por S/. {monto_desc:.2f} registrado correctamente.")
                st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)


# ==========================================
# BLOQUE 4: GESTIÓN DE PERSONAL
# ==========================================
elif choice == "Gestión de Personal":
    st.markdown("""
        <div class="market-header">
            <h1>Gestión e Inventario de Personal</h1>
            <p>Administración de usuarios, roles, cargos y accesos al sistema</p>
        </div>
    """, unsafe_allow_html=True)

    col_form, col_list = st.columns([1, 1.4], gap="large")

    with col_form:
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.markdown("#### 👤 Registrar Nuevo Colaborador")
        
        with st.form("form_nuevo_colaborador", clear_on_submit=True):
            dni_in = st.text_input("Número de DNI / Documento Identidad", max_chars=12)
            nom_in = st.text_input("Nombre y Apellidos Completos")
            cargo_in = st.selectbox("Cargo Operativo", ["Cajero", "Supervisora", "Reposidor", "Gerente de Tienda", "Auditor"])
            rol_in = st.selectbox("Nivel de Acceso (Rol)", ["operativo", "admin"])
            clave_in = st.text_input("Contraseña del Sistema", type="password")

            st.markdown("<br>", unsafe_allow_html=True)
            btn_add_colab = st.form_submit_button("➕ Guardar Colaborador", type="primary", use_container_width=True)

            if btn_add_colab:
                if not dni_in or not nom_in or not clave_in:
                    st.error("Todos los campos marcados son obligatorios.")
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
                    st.success(f"Colaborador {nom_in} creado exitosamente.")
                    st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    with col_list:
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.markdown("#### 📑 Directorio Activo de Colaboradores")
        
        if not st.session_state.empleados.empty:
            st.dataframe(
                st.session_state.empleados[["dni", "nombre", "cargo", "rol", "estado"]],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "dni": "DOCUMENTO DNI",
                    "nombre": "NOMBRE COMPLETO",
                    "cargo": "CARGO OPERATIVO",
                    "rol": "PERMISOS",
                    "estado": "ESTADO"
                }
            )

            if rol_actual == "admin":
                st.markdown("---")
                st.markdown("##### ⚙️ Acciones Administrativas")
                with st.expander("🗑️ Dar de Baja / Eliminar Colaborador"):
                    lista_colabs = st.session_state.empleados["nombre"].tolist()
                    colab_a_eliminar = st.selectbox("Seleccionar Colaborador a Retirar", lista_colabs)
                    confirm_del_colab = st.checkbox(f"Confirmo la eliminación permanente de {colab_a_eliminar}")

                    if st.button("Eliminar Registro de Personal", type="primary"):
                        if confirm_del_colab:
                            st.session_state.empleados = st.session_state.empleados[st.session_state.empleados["nombre"] != colab_a_eliminar].reset_index(drop=True)
                            actualizar_hoja_completa("Colaboradores", st.session_state.empleados)
                            st.toast(f"Colaborador {colab_a_eliminar} retirado del sistema")
                            st.rerun()
                        else:
                            st.warning("Debe confirmar el check antes de procesar el borrado.")
        else:
            st.info("Sin datos de personal registrados.")
        st.markdown('</div>', unsafe_allow_html=True)


# ==========================================
# BLOQUE 5: HISTORIAL DE DESCUADRES
# ==========================================
elif choice == "Historial de Descuadres":
    st.markdown("""
        <div class="market-header">
            <h1>Auditoría y Reporte de Descuadres</h1>
            <p>Histórico analítico para revisión contable y gestión de auditoría</p>
        </div>
    """, unsafe_allow_html=True)

    if not st.session_state.descuadres.empty:
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.markdown("##### 🔍 Filtros de Auditoría")
        f_col1, f_col2 = st.columns([1.5, 1], gap="medium")

        with f_col1:
            rango_fechas_desc = st.date_input("Rango de Fechas de Eventos", value=(obtener_ahora_peru().date(), obtener_ahora_peru().date()), key="desc_fechas")
        with f_col2:
            colabs_desc = ["Todos"] + [c for c in st.session_state.descuadres["nombre"].unique().tolist()]
            colab_desc_sel = st.selectbox("Filtrar por Colaborador", colabs_desc, key="desc_colab")

        df_desc_filtrado = st.session_state.descuadres.copy()

        # Filtrado por rango de fechas
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

        # Filtrado por colaborador
        if colab_desc_sel != "Todos":
            df_desc_filtrado = df_desc_filtrado[df_desc_filtrado["nombre"] == colab_desc_sel]

        st.markdown('</div>', unsafe_allow_html=True)

        if not df_desc_filtrado.empty:
            df_desc_filtrado["monto_num"] = pd.to_numeric(df_desc_filtrado["monto"], errors="coerce").fillna(0)
            sobrantes = df_desc_filtrado[df_desc_filtrado["monto_num"] > 0]["monto_num"].sum()
            faltantes = df_desc_filtrado[df_desc_filtrado["monto_num"] < 0]["monto_num"].sum()
            balance = df_desc_filtrado["monto_num"].sum()

            m1, m2, m3 = st.columns(3, gap="medium")
            with m1:
                st.markdown(f'<div class="info-card"><div class="info-label">Total Sobrantes (+)</div><div class="info-value" style="color:#00A959;">S/. {sobrantes:.2f}</div></div>', unsafe_allow_html=True)
            with m2:
                st.markdown(f'<div class="info-card"><div class="info-label">Total Faltantes (-)</div><div class="info-value" style="color:#EC3237;">S/. {abs(faltantes):.2f}</div></div>', unsafe_allow_html=True)
            with m3:
                color_balance = "#00A959" if balance >= 0 else "#EC3237"
                st.markdown(f'<div class="info-card"><div class="info-label">Balance Neto Descuadres</div><div class="info-value" style="color:{color_balance};">S/. {balance:.2f}</div></div>', unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown('<div class="section-card">', unsafe_allow_html=True)
            st.dataframe(
                df_desc_filtrado.drop(columns=["monto_num"], errors="ignore"),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "fecha": "FECHA DE EVENTO",
                    "nombre": "COLABORADOR",
                    "monto": st.column_config.NumberColumn("MONTO REGISTRADO", format="S/. %.2f"),
                    "tipo": "TIPO DESCUADRE",
                    "observacion": "DETALLE / JUSTIFICACIÓN"
                }
            )

            st.download_button(
                "📥 Exportar Reporte de Descuadres a Excel",
                data=to_excel(df_desc_filtrado.drop(columns=["monto_num"], errors="ignore")),
                file_name="Reporte_Descuadres_Tiendas_Premium.xlsx",
                mime="application/vnd.ms-excel"
            )
            st.markdown('</div>', unsafe_allow_html=True)

            if rol_actual == "admin":
                st.markdown('<div class="section-card">', unsafe_allow_html=True)
                st.markdown("##### 🛠️ Edición Administrativa de Descuadres")
                col_mod, col_del = st.columns(2, gap="medium")

                with col_mod:
                    with st.expander("✏️ Editar Registro de Descuadre"):
                        opciones_desc = [f"{i} | {r['fecha']} | {r['nombre']} | S/. {r['monto']}" for i, r in st.session_state.descuadres.iterrows()]
                        sel_mod = st.selectbox("Seleccionar Registro a Editar", opciones_desc, key="mod_desc_sel")

                        if sel_mod:
                            idx_mod = int(sel_mod.split(" | ")[0])
                            row_mod = st.session_state.descuadres.loc[idx_mod]

                            nuevo_monto = st.number_input("Nuevo Monto Absoluto (S/.)", value=abs(float(row_mod["monto"])), step=0.50, format="%.2f")
                            tipo_options = ["Sobrante", "Faltante"]
                            idx_tipo = tipo_options.index(row_mod["tipo"]) if row_mod["tipo"] in tipo_options else 0
                            nuevo_tipo = st.selectbox("Nuevo Tipo", tipo_options, index=idx_tipo)
                            nueva_obs = st.text_area("Nueva Observación", value=str(row_mod["observacion"]))

                            if st.button("Guardar Cambios en Descuadre"):
                                monto_calc = nuevo_monto if nuevo_tipo == "Sobrante" else -nuevo_monto
                                st.session_state.descuadres.at[idx_mod, "monto"] = monto_calc
                                st.session_state.descuadres.at[idx_mod, "tipo"] = nuevo_tipo
                                st.session_state.descuadres.at[idx_mod, "observacion"] = nueva_obs
                                actualizar_hoja_completa("Descuadres", st.session_state.descuadres)
                                st.success("Registro modificado correctamente.")
                                st.rerun()

                with col_del:
                    with st.expander("🗑️ Eliminar Registro de Descuadre"):
                        opciones_desc_del = [f"{i} | {r['fecha']} | {r['nombre']} | S/. {r['monto']}" for i, r in st.session_state.descuadres.iterrows()]
                        sel_del = st.selectbox("Seleccionar Registro a Eliminar", opciones_desc_del, key="del_desc_sel")
                        confirm_del_desc = st.checkbox("Confirmo la eliminación completa del registro de descuadre")

                        if st.button("Eliminar Descuadre Definitivamente", type="primary"):
                            if confirm_del_desc:
                                idx_del = int(sel_del.split(" | ")[0])
                                st.session_state.descuadres = st.session_state.descuadres.drop(idx_del).reset_index(drop=True)
                                actualizar_hoja_completa("Descuadres", st.session_state.descuadres)
                                st.toast("Registro de descuadre eliminado")
                                st.rerun()
                            else:
                                st.warning("Por favor confirme la casilla de verificación.")
                st.markdown('</div>', unsafe_allow_html=True)
        else:
            st.info("No se hallaron registros de descuadres con los filtros aplicados.")
    else:
        st.info("No hay descuadres registrados en la base de datos.")


# ==========================================
# BLOQUE 6: HISTORIAL DE ASISTENCIAS
# ==========================================
elif choice == "Historial de Asistencias":
    st.markdown("""
        <div class="market-header">
            <h1>Reporte General de Asistencias</h1>
            <p>Consolidado e historial completo de marcaciones de entrada y salida</p>
        </div>
    """, unsafe_allow_html=True)

    if not st.session_state.asistencia.empty:
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.markdown("##### 🔍 Filtros de Búsqueda de Asistencia")
        fa_col1, fa_col2 = st.columns([1.5, 1], gap="medium")

        with fa_col1:
            rango_fechas_asist = st.date_input("Seleccionar Rango de Fechas", value=(obtener_ahora_peru().date(), obtener_ahora_peru().date()), key="asist_fechas")
        with fa_col2:
            colabs_asist = ["Todos"] + [c for c in st.session_state.asistencia["nombre"].unique().tolist()]
            colab_asist_sel = st.selectbox("Colaborador Evaluado", colabs_asist, key="asist_colab")

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

        st.markdown('</div>', unsafe_allow_html=True)

        if not df_asist_filtrado.empty:
            total_marcas = len(df_asist_filtrado)
            ingresos_cnt = len(df_asist_filtrado[df_asist_filtrado["tipo"] == "INGRESO"])
            salidas_cnt  = len(df_asist_filtrado[df_asist_filtrado["tipo"] == "SALIDA"])
            colabs_unicos = df_asist_filtrado["nombre"].nunique()

            a1, a2, a3, a4 = st.columns(4, gap="medium")
            with a1:
                st.markdown(f'<div class="info-card"><div class="info-label">Total Marcas</div><div class="info-value">{total_marcas}</div></div>', unsafe_allow_html=True)
            with a2:
                st.markdown(f'<div class="info-card"><div class="info-label">Ingresos / Turnos</div><div class="info-value" style="color:#00A959;">{ingresos_cnt}</div></div>', unsafe_allow_html=True)
            with a3:
                st.markdown(f'<div class="info-card"><div class="info-label">Salidas Registradas</div><div class="info-value" style="color:#3B82F6;">{salidas_cnt}</div></div>', unsafe_allow_html=True)
            with a4:
                st.markdown(f'<div class="info-card"><div class="info-label">Personal Distinto</div><div class="info-value">{colabs_unicos}</div></div>', unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown('<div class="section-card">', unsafe_allow_html=True)
            st.dataframe(
                df_asist_filtrado.sort_values(by="fecha_hora", ascending=False),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "fecha_hora": "FECHA Y HORA REGISTRO",
                    "fecha": "FECHA JORNADA",
                    "nombre": "COLABORADOR",
                    "tipo": "TIPO REGISTRO"
                }
            )

            st.download_button(
                "📥 Exportar Asistencias a Excel",
                data=to_excel(df_asist_filtrado),
                file_name="Reporte_Asistencias_General.xlsx",
                mime="application/vnd.ms-excel"
            )
            st.markdown('</div>', unsafe_allow_html=True)

            if rol_actual == "admin":
                st.markdown('<div class="section-card">', unsafe_allow_html=True)
                st.markdown("##### ⚙️ Eliminación Administrativa")
                with st.expander("🗑️ Eliminar Registro Incorrecto de Asistencia"):
                    opciones_asist = [f"{i} | {r['fecha_hora']} | {r['nombre']} | {r['tipo']}" for i, r in st.session_state.asistencia.iterrows()]
                    sel_asist_del = st.selectbox("Seleccionar Marcación a Eliminar", opciones_asist)
                    confirm_del_asist = st.checkbox("Confirmo la eliminación del registro de asistencia seleccionado")

                    if st.button("Eliminar Registro de Asistencia", type="primary"):
                        if confirm_del_asist:
                            idx_asist = int(sel_asist_del.split(" | ")[0])
                            st.session_state.asistencia = st.session_state.asistencia.drop(idx_asist).reset_index(drop=True)
                            actualizar_hoja_completa("Asistencia", st.session_state.asistencia)
                            st.toast("Registro de asistencia eliminado con éxito")
                            st.rerun()
                        else:
                            st.warning("Confirme la casilla antes de proceder.")
                st.markdown('</div>', unsafe_allow_html=True)
        else:
            st.info("No hay marcas con los criterios especificados.")
    else:
        st.info("Sin datos de asistencia registrados.")


# ==========================================
# BLOQUE 7: HISTORIAL DE ARQUEOS
# ==========================================
elif choice == "Historial de Arqueos":
    st.markdown("""
        <div class="market-header">
            <h1>Historial General de Arqueos de Caja</h1>
            <p>Consulta detallada de cierres de caja y desgloses de efectivo</p>
        </div>
    """, unsafe_allow_html=True)

    if not st.session_state.arqueos.empty:
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.markdown("##### 🔍 Filtros de Búsqueda de Arqueos")
        farq_col1, farq_col2 = st.columns([1.5, 1], gap="medium")

        with farq_col1:
            rango_fechas_arq = st.date_input("Rango de Fechas", value=(obtener_ahora_peru().date(), obtener_ahora_peru().date()), key="arq_fechas")
        with farq_col2:
            cajeros_arq = ["Todos"] + [c for c in st.session_state.arqueos["cajero"].unique().tolist()]
            cajero_arq_sel = st.selectbox("Cajero", cajeros_arq, key="arq_cajero")

        df_arq_filtrado = st.session_state.arqueos.copy()

        if isinstance(rango_fechas_arq, tuple):
            if len(rango_fechas_arq) == 2:
                f_inicio, f_fin = str(rango_fechas_arq[0]), str(rango_fechas_arq[1])
                df_arq_filtrado = df_arq_filtrado[
                    (df_arq_filtrado["fecha"].astype(str) >= f_inicio) & 
                    (df_arq_filtrado["fecha"].astype(str) <= f_fin)
                ]
            elif len(rango_fechas_arq) == 1:
                f_inicio = str(rango_fechas_arq[0])
                df_arq_filtrado = df_arq_filtrado[df_arq_filtrado["fecha"].astype(str) == f_inicio]

        if cajero_arq_sel != "Todos":
            df_arq_filtrado = df_arq_filtrado[df_arq_filtrado["cajero"] == cajero_arq_sel]

        st.markdown('</div>', unsafe_allow_html=True)

        if not df_arq_filtrado.empty:
            df_arq_filtrado["efectivo_num"] = pd.to_numeric(df_arq_filtrado["total_efectivo"], errors="coerce").fillna(0)
            df_arq_filtrado["tarjeta_num"] = pd.to_numeric(df_arq_filtrado["total_tarjeta"], errors="coerce").fillna(0)
            df_arq_filtrado["general_num"] = pd.to_numeric(df_arq_filtrado["total_general"], errors="coerce").fillna(0)

            tot_efec = df_arq_filtrado["efectivo_num"].sum()
            tot_tarj = df_arq_filtrado["tarjeta_num"].sum()
            tot_gen  = df_arq_filtrado["general_num"].sum()

            q1, q2, q3 = st.columns(3, gap="medium")
            with q1:
                st.markdown(f'<div class="info-card"><div class="info-label">Efectivo Total Acumulado</div><div class="info-value" style="color:#00A959;">S/. {tot_efec:.2f}</div></div>', unsafe_allow_html=True)
            with q2:
                st.markdown(f'<div class="info-card"><div class="info-label">Total Tarjeta / Electrónico</div><div class="info-value" style="color:#3B82F6;">S/. {tot_tarj:.2f}</div></div>', unsafe_allow_html=True)
            with q3:
                st.markdown(f'<div class="info-card"><div class="info-label">Gran Total Cierres</div><div class="info-value" style="color:#1E3A8A;">S/. {tot_gen:.2f}</div></div>', unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown('<div class="section-card">', unsafe_allow_html=True)
            
            # Formato de visualización ordenado
            cols_ver = ["fecha_hora", "cajero", "total_efectivo", "total_tarjeta", "total_general", "observacion"]
            cols_existentes = [c for c in cols_ver if c in df_arq_filtrado.columns]

            st.dataframe(
                df_arq_filtrado[cols_existentes].sort_values(by="fecha_hora", ascending=False),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "fecha_hora": "FECHA Y HORA",
                    "cajero": "CAJERO RESPONSABLE",
                    "total_efectivo": st.column_config.NumberColumn("EFECTIVO (S/.)", format="S/. %.2f"),
                    "total_tarjeta": st.column_config.NumberColumn("TARJETA/POS (S/.)", format="S/. %.2f"),
                    "total_general": st.column_config.NumberColumn("TOTAL ARQUEO (S/.)", format="S/. %.2f"),
                    "observacion": "OBSERVACIÓN"
                }
            )

            st.download_button(
                "📥 Exportar Arqueos a Excel",
                data=to_excel(df_arq_filtrado.drop(columns=["efectivo_num", "tarjeta_num", "general_num"], errors="ignore")),
                file_name="Reporte_Arqueos_Caja.xlsx",
                mime="application/vnd.ms-excel"
            )
            st.markdown('</div>', unsafe_allow_html=True)

            if rol_actual == "admin":
                st.markdown('<div class="section-card">', unsafe_allow_html=True)
                st.markdown("##### ⚙️ Gestión de Registros de Arqueo")
                with st.expander("🗑️ Eliminar Arqueo Registrado"):
                    opciones_arq = [f"{i} | {r['fecha_hora']} | {r['cajero']} | Total: S/. {r['total_general']}" for i, r in st.session_state.arqueos.iterrows()]
                    sel_arq_del = st.selectbox("Seleccionar Arqueo a Eliminar", opciones_arq)
                    confirm_del_arq = st.checkbox("Confirmo la eliminación permanente de este cierre de caja")

                    if st.button("Eliminar Registro de Arqueo", type="primary"):
                        if confirm_del_arq:
                            idx_arq = int(sel_arq_del.split(" | ")[0])
                            st.session_state.arqueos = st.session_state.arqueos.drop(idx_arq).reset_index(drop=True)
                            actualizar_hoja_completa("Arqueos", st.session_state.arqueos)
                            st.toast("Arqueo eliminado exitosamente")
                            st.rerun()
                        else:
                            st.warning("Debe confirmar el check de seguridad antes de borrar.")
                st.markdown('</div>', unsafe_allow_html=True)
        else:
            st.info("No se hallaron cierres de caja en el rango seleccionado.")
    else:
        st.info("No se registran arqueos en la base de datos.")


# ==========================================
# PIE DE PÁGINA CORPORATIVO
# ==========================================
st.markdown("<br><br>", unsafe_allow_html=True)
st.markdown("""
    <div style="text-align:center; padding: 20px; color:#94A3B8; font-size:12px; border-top: 1px solid #E2E8F0;">
        Tiendas Premium S.A.C. &copy; 2026 — Sistema de Control Operativo y Asistencia<br>
        Desarrollado para la Gestión y Auditoría de Cajas
    </div>
""", unsafe_allow_html=True)
