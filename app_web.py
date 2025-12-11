import streamlit as st
import mysql.connector
import pandas as pd

# ========================================================
# ⚙️ CONFIGURACIÓN: REEMPLAZA ESTO CON TUS DATOS DE TIDB
# ========================================================
# --- CONFIGURACIÓN SEGURA PARA LA NUBE ---
# Esto carga AUTOMÁTICAMENTE host, user, password y port desde los 'Secrets'
try:
    DB_CONFIG = st.secrets["mysql"]
except FileNotFoundError:
    st.warning("⚠️ No se detectaron secretos. Configúralos en Streamlit Cloud.")
    st.stop()
# ========================================================

def get_connection():
    # Esta función conecta a la nube
    return mysql.connector.connect(**DB_CONFIG)

def init_db():
    # Crea las tablas automáticamente si no existen
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
        st.error(f"❌ Error conectando a la base de datos: {err}")
        st.stop()

# --- INTERFAZ GRÁFICA WEB ---
st.set_page_config(page_title="Inventario TI Cloud", layout="wide", page_icon="☁️")
st.title("☁️ Sistema de Inventario TI")

# Intentamos inicializar la DB al cargar
init_db()

# Menú lateral
menu = st.sidebar.radio("Navegación", ["Gestión de Equipos", "Gestión de Obras"])

# ==========================================
# PESTAÑA: GESTIÓN DE OBRAS (SITIOS)
# ==========================================
if menu == "Gestión de Obras":
    st.header("🏢 Obras y Sitios")
    
    col1, col2 = st.columns([2, 1])
    with col1:
        nuevo_sitio = st.text_input("Nombre de la nueva Obra/Sitio")
    with col2:
        st.write("") # Espacio
        st.write("") # Espacio
        if st.button("Guardar Sitio", use_container_width=True):
            if nuevo_sitio:
                conn = get_connection()
                try:
                    cursor = conn.cursor()
                    cursor.execute("INSERT INTO sitios (nombre) VALUES (%s)", (nuevo_sitio,))
                    st.success(f"✅ Sitio '{nuevo_sitio}' creado.")
                except mysql.connector.Error as err:
                    st.error(f"Error: {err}")
                finally:
                    conn.close()
            else:
                st.warning("Escribe un nombre.")

    # Mostrar lista
    st.divider()
    conn = get_connection()
    df = pd.read_sql("SELECT id, nombre FROM sitios ORDER BY id DESC", conn)
    conn.close()
    st.dataframe(df, hide_index=True, use_container_width=True)

# ==========================================
# PESTAÑA: GESTIÓN DE EQUIPOS
# ==========================================
elif menu == "Gestión de Equipos":
    st.header("💻 Inventario de Equipos")

    # Cargar sitios para el selector
    conn = get_connection()
    sitios_df = pd.read_sql("SELECT id, nombre FROM sitios", conn)
    conn.close()
    
    if sitios_df.empty:
        st.warning("⚠️ Primero debes crear al menos una Obra en el menú lateral.")
    else:
        # Crear diccionario {Nombre: ID}
        opciones_sitios = dict(zip(sitios_df['nombre'], sitios_df['id']))

        with st.expander("➕ Agregar Nuevo Equipo", expanded=True):
            c1, c2, c3 = st.columns(3)
            codigo = c1.text_input("Código Inventario")
            tipo = c2.selectbox("Tipo", ["Laptop", "PC Escritorio"])
            sitio_sel = c3.selectbox("Asignar a Obra", list(opciones_sitios.keys()))
            
            c4, c5, c6 = st.columns(3)
            marca = c4.text_input("Marca/Modelo")
            usuario = c5.text_input("Usuario Asignado")
            
            # Lógica dinámica visual (Streamlit redibuja al cambiar 'tipo')
            serie, monitor = "", ""
            if tipo == "Laptop":
                serie = c6.text_input("Nº Serie")
            else:
                monitor = c6.text_input("Código de Monitor")
            
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
                        # ID del sitio seleccionado
                        id_sitio_real = opciones_sitios[sitio_sel]
                        vals = (codigo, serie, tipo, marca, usuario, carac, monitor, id_sitio_real)
                        
                        cursor.execute(query, vals)
                        st.success("✅ Equipo guardado en la nube.")
                        # Recargar página para limpiar form (truco streamlit)
                        st.rerun() 
                    except mysql.connector.Error as err:
                        st.error(f"Error de base de datos: {err}")
                    finally:
                        if 'conn' in locals() and conn.is_connected(): conn.close()
                else:
                    st.error("El código es obligatorio.")

        # --- FILTROS Y TABLA ---
        st.divider()
        f_col1, f_col2 = st.columns([3, 1])
        filtro = f_col1.selectbox("🔍 Filtrar por Obra", ["Todas"] + list(opciones_sitios.keys()))
        
        query = """
            SELECT e.id, e.codigo_inventario as 'Código', e.tipo as 'Tipo', 
                   e.serie as 'Serie', e.marca_modelo as 'Marca', 
                   e.usuario as 'Usuario', s.nombre as 'Obra', 
                   e.monitor_codigo as 'Monitor', e.caracteristicas as 'Specs'
            FROM equipos e
            JOIN sitios s ON e.sitio_id = s.id
        """
        
        conn = get_connection()
        if filtro != "Todas":
            df_equipos = pd.read_sql(query + " WHERE s.nombre = %s", conn, params=(filtro,))
        else:
            df_equipos = pd.read_sql(query + " ORDER BY e.id DESC", conn)
        conn.close()

        st.dataframe(df_equipos, hide_index=True, use_container_width=True)
        
        # Exportar
        if not df_equipos.empty:
            csv = df_equipos.to_csv(index=False).encode('utf-8')

            f_col2.download_button("📥 Descargar CSV", data=csv, file_name="inventario.csv", mime="text/csv")

