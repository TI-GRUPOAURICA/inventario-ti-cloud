import streamlit as st
import mysql.connector
import pandas as pd

# =======================================================
# CONFIGURACIÓN DE BASE DE DATOS (MODO NUBE)
# =======================================================

# Intentamos cargar la configuración desde los Secretos de Streamlit
try:
    # Esto lee automáticamente host, port, user, password de la "Caja Fuerte"
    DB_CONFIG = st.secrets["mysql"]
except FileNotFoundError:
    st.warning("⚠️ No se encontraron los secretos. Asegúrate de configurarlos en Streamlit Cloud (Settings > Secrets).")
    st.stop()

# =======================================================
# FUNCIONES DE BASE DE DATOS
# =======================================================

def get_connection():
    # Conecta a la base de datos usando la configuración cargada
    return mysql.connector.connect(**DB_CONFIG)

def init_db():
    # Crea las tablas si no existen (solo la primera vez)
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Tabla Sitios
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sitios (
                id INT AUTO_INCREMENT PRIMARY KEY,
                nombre VARCHAR(255) UNIQUE NOT NULL
            );
        """)
        
        # Tabla Equipos
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS equipos (
                id INT AUTO_INCREMENT PRIMARY KEY,
                codigo_inventario VARCHAR(50) UNIQUE NOT NULL,
                serie VARCHAR(100),
                tipo VARCHAR(50) NOT NULL,
                marca_modelo VARCHAR(100),
                usuario VARCHAR(100),
                caracteristicas TEXT,
                monitor_codigo VARCHAR(50),
                sitio_id INT,
                FOREIGN KEY (sitio_id) REFERENCES sitios(id) ON DELETE CASCADE
            );
        """)
        conn.close()
    except mysql.connector.Error as err:
        st.error(f"❌ Error al iniciar base de datos: {err}")

# =======================================================
# INTERFAZ DE USUARIO (WEB)
# =======================================================

st.set_page_config(page_title="Inventario TI Cloud", layout="wide", page_icon="☁️")
st.title("☁️ Sistema de Inventario TI")

# Inicializar DB
init_db()

# Menú Lateral
menu = st.sidebar.radio("Navegación", ["Gestión de Equipos", "Gestión de Obras"])

# --- PESTAÑA 1: GESTIÓN DE OBRAS ---
if menu == "Gestión de Obras":
    st.header("🏢 Gestión de Obras / Sitios")
    
    col1, col2 = st.columns([2, 1])
    with col1:
        nuevo_sitio = st.text_input("Nombre de la nueva Obra")
    with col2:
        st.write("") 
        st.write("") 
        if st.button("Guardar Sitio", use_container_width=True):
            if nuevo_sitio:
                try:
                    conn = get_connection()
                    cursor = conn.cursor()
                    cursor.execute("INSERT INTO sitios (nombre) VALUES (%s)", (nuevo_sitio,))
                    conn.commit()
                    st.success(f"✅ Sitio '{nuevo_sitio}' creado.")
                    conn.close()
                    st.rerun()
                except mysql.connector.Error as err:
                    st.error(f"Error: {err}")
            else:
                st.warning("Escribe un nombre.")

    st.divider()
    try:
        conn = get_connection()
        df = pd.read_sql("SELECT id, nombre FROM sitios ORDER BY id DESC", conn)
        conn.close()
        st.dataframe(df, hide_index=True, use_container_width=True)
    except:
        st.info("No hay sitios creados aún.")

# --- PESTAÑA 2: GESTIÓN DE EQUIPOS ---
elif menu == "Gestión de Equipos":
    st.header("💻 Inventario de Equipos")

    # Cargar sitios
    try:
        conn = get_connection()
        sitios_df = pd.read_sql("SELECT id, nombre FROM sitios", conn)
        conn.close()
    except:
        sitios_df = pd.DataFrame()

    if sitios_df.empty:
        st.warning("⚠️ Primero crea una Obra en el menú 'Gestión de Obras'.")
    else:
        opciones_sitios = dict(zip(sitios_df['nombre'], sitios_df['id']))

        with st.expander("➕ Registrar Nuevo Equipo", expanded=True):
            c1, c2, c3 = st.columns(3)
            codigo = c1.text_input("Código Inventario")
            tipo = c2.selectbox("Tipo", ["Laptop", "PC Escritorio"])
            sitio_sel = c3.selectbox("Asignar a Obra", list(opciones_sitios.keys()))
            
            c4, c5, c6 = st.columns(3)
            marca = c4.text_input("Marca/Modelo")
            usuario = c5.text_input("Usuario")
            
            serie, monitor = "", ""
            if tipo == "Laptop":
                serie = c6.text_input("Nº Serie")
            else:
                monitor = c6.text_input("Cód. Monitor")
            
            carac = st.text_area("Características")
            
            if st.button("Guardar Equipo", type="primary"):
                if codigo:
                    try:
                        conn = get_connection()
                        cursor = conn.cursor()
                        query = """
                            INSERT INTO equipos 
                            (codigo_inventario, serie, tipo, marca_modelo, usuario, caracteristicas, monitor_codigo, sitio_id)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """
                        vals = (codigo, serie, tipo, marca, usuario, carac, monitor, opciones_sitios[sitio_sel])
                        cursor.execute(query, vals)
                        conn.commit()
                        st.success("✅ Guardado correctamente.")
                        conn.close()
                        st.rerun()
                    except mysql.connector.Error as err:
                        st.error(f"Error: {err}")
                else:
                    st.error("El código es obligatorio.")

        # Tabla y Filtros
        st.divider()
        f_col1, f_col2 = st.columns([3, 1])
        filtro = f_col1.selectbox("🔍 Filtrar por Obra", ["Todas"] + list(opciones_sitios.keys()))
        
        query_base = """
            SELECT e.id, e.codigo_inventario as 'Código', e.tipo as 'Tipo', 
                   e.serie as 'Serie', e.marca_modelo as 'Marca', 
                   e.usuario as 'Usuario', s.nombre as 'Obra', 
                   e.monitor_codigo as 'Monitor', e.caracteristicas as 'Specs'
            FROM equipos e
            JOIN sitios s ON e.sitio_id = s.id
        """
        
        conn = get_connection()
        if filtro != "Todas":
            df_equipos = pd.read_sql(query_base + " WHERE s.nombre = %s", conn, params=(filtro,))
        else:
            df_equipos = pd.read_sql(query_base + " ORDER BY e.id DESC", conn)
        conn.close()

        st.dataframe(df_equipos, hide_index=True, use_container_width=True)
        
        if not df_equipos.empty:
            csv = df_equipos.to_csv(index=False).encode('utf-8')
            f_col2.download_button("📥 Descargar CSV", data=csv, file_name="inventario.csv", mime="text/csv")

