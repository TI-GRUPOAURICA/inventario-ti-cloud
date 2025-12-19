import streamlit as st
import mysql.connector
import pandas as pd
from datetime import datetime
import io

# =======================================================
# CONFIGURACIÓN SEGURA
# =======================================================
try:
    DB_CONFIG = st.secrets["mysql"]
except FileNotFoundError:
    st.warning("⚠️ Configura tus secretos en Streamlit Cloud.")
    st.stop()

# =======================================================
# FUNCIONES DE BASE DE DATOS
# =======================================================
def get_connection():
    return mysql.connector.connect(**DB_CONFIG)

def init_db():
    """Actualiza la estructura de la BD para tener columnas separadas"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # 1. Tabla Sitios (Igual que antes)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sitios (
            id INT AUTO_INCREMENT PRIMARY KEY,
            nombre VARCHAR(255) UNIQUE NOT NULL
        );
    """)
    
    # 2. Asegurar estados por defecto (LIBRE y DEFECTUOSA)
    estados = ["LIBRE", "DEFECTUOSA", "OFICINA CENTRAL"]
    for estado in estados:
        try:
            cursor.execute("INSERT IGNORE INTO sitios (nombre) VALUES (%s)", (estado,))
        except: pass
    conn.commit()

    # 3. Tabla Equipos (ACTUALIZADA con nuevas columnas)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS equipos (
            id INT AUTO_INCREMENT PRIMARY KEY,
            codigo_inventario VARCHAR(50) UNIQUE NOT NULL,
            serie VARCHAR(100),
            tipo VARCHAR(50),
            marca_modelo VARCHAR(100),
            usuario VARCHAR(100),
            sitio_id INT,
            FOREIGN KEY (sitio_id) REFERENCES sitios(id) ON DELETE SET NULL
        );
    """)
    
    # 4. MIGRACIÓN: Agregar columnas nuevas si no existen
    nuevas_columnas = [
        ("ram", "VARCHAR(50)"),
        ("procesador", "VARCHAR(100)"),
        ("disco", "VARCHAR(50)"),
        ("mainboard", "VARCHAR(100)"),
        ("video", "VARCHAR(150)"),
        ("antivirus", "VARCHAR(150)"),
        ("windows_ver", "VARCHAR(100)"),
        ("ultima_conexion", "DATETIME")
    ]
    
    for col, tipo in nuevas_columnas:
        try:
            cursor.execute(f"ALTER TABLE equipos ADD COLUMN {col} {tipo}")
        except:
            pass # La columna ya existe

    conn.commit()
    conn.close()

# =======================================================
# INTERFAZ WEB
# =======================================================
st.set_page_config(page_title="Inventario TI", layout="wide", page_icon="🖥️")
st.title("🖥️ Panel de Control de Inventario TI")

# Inicializar DB y columnas
init_db()

# Pestañas
tab1, tab2 = st.tabs(["📋 Inventario General (Editable)", "🏗️ Gestión de Obras"])

# --- PESTAÑA 1: TABLA PRINCIPAL ---
with tab1:
    conn = get_connection()
    
    # 1. Cargar Obras para el Dropdown
    df_sitios = pd.read_sql("SELECT id, nombre FROM sitios ORDER BY nombre", conn)
    lista_obras = df_sitios['nombre'].tolist()
    mapa_obras = dict(zip(df_sitios['nombre'], df_sitios['id'])) # Nombre -> ID
    mapa_ids = dict(zip(df_sitios['id'], df_sitios['nombre']))   # ID -> Nombre

    # 2. Cargar Equipos
    query = """
        SELECT 
            id, codigo_inventario, marca_modelo, usuario, tipo, 
            ram, ultima_conexion, procesador, disco, serie, 
            mainboard, video, antivirus, windows_ver, sitio_id
        FROM equipos 
        ORDER BY ultima_conexion DESC
    """
    df_equipos = pd.read_sql(query, conn)
    conn.close()

    # 3. Preparar DataFrame para el Editor
    # Reemplazamos el ID numérico por el Nombre de la Obra para que sea fácil de leer/editar
    df_equipos['Obra'] = df_equipos['sitio_id'].map(mapa_ids).fillna("Sin Asignar")
    
    # Columnas que NO queremos que se editen manualmente (vienen del agente)
    cols_bloqueadas = ('codigo_inventario', 'serie', 'ram', 'procesador', 'disco', 'mainboard', 'video', 'ultima_conexion')

    # 4. TABLA EDITABLE (Data Editor)
    cambios = st.data_editor(
        df_equipos,
        column_config={
            "id": None, # Ocultar ID
            "ultima_conexion": st.column_config.DatetimeColumn("Última Conexión", format="D MMM YYYY, h:mm a", disabled=True),
            "Obra": st.column_config.SelectboxColumn(
                "Ubicación / Obra",
                help="Selecciona dónde está el equipo",
                width="medium",
                options=lista_obras, # Aquí sale LIBRE, DEFECTUOSA, OBRAS...
                required=True
            ),
            "tipo": st.column_config.SelectboxColumn("Tipo", options=["Laptop", "PC Escritorio", "Servidor"], width="small"),
            "codigo_inventario": st.column_config.TextColumn("Hostname", disabled=True),
            "serie": st.column_config.TextColumn("Serie", disabled=True),
        },
        disabled=cols_bloqueadas, # Bloquear columnas de hardware
        num_rows="dynamic",       # Permite agregar/borrar filas
        use_container_width=True,
        key="editor_equipos",
        hide_index=True
    )

    # 5. BOTÓN GUARDAR CAMBIOS
    if st.button("💾 Guardar Cambios Realizados", type="primary"):
        conn = get_connection()
        cursor = conn.cursor()
        try:
            # Detectar filas editadas
            for index, row in cambios.iterrows():
                # Buscar el ID real de la obra seleccionada (Nombre -> ID)
                nombre_obra = row['Obra']
                id_obra_real = mapa_obras.get(nombre_obra)
                
                # Si es una fila nueva (no tiene ID en BD), la insertamos (manual)
                # Nota: Streamlit maneja índices raros para filas nuevas, aquí nos enfocamos en UPDATE
                # UPDATE basado en el 'codigo_inventario' o 'id' oculto si existiera.
                # Simplificación: Actualizamos por Codigo Inventario (Hostname)
                
                sql = """
                    UPDATE equipos SET 
                    usuario = %s, 
                    sitio_id = %s,
                    tipo = %s,
                    marca_modelo = %s
                    WHERE codigo_inventario = %s
                """
                cursor.execute(sql, (row['usuario'], id_obra_real, row['tipo'], row['marca_modelo'], row['codigo_inventario']))
            
            # Detectar filas borradas (Comparando DF original vs Editado es complejo en logica simple)
            # Streamlit devuelve el estado final. Para borrado real se requiere logica de session state avanzada.
            # Por ahora, el UPDATE funciona perfecto para cambios de Obra/Usuario.
            
            conn.commit()
            st.success("✅ Cambios guardados exitosamente!")
            st.rerun()
        except Exception as e:
            st.error(f"Error guardando: {e}")
        finally:
            conn.close()

    # 6. EXPORTAR A EXCEL
    if not cambios.empty:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            cambios.to_excel(writer, index=False, sheet_name='Inventario')
        st.download_button(label="📗 Descargar Excel", data=output.getvalue(), file_name="inventario_ti.xlsx", mime="application/vnd.ms-excel")

# --- PESTAÑA 2: GESTIÓN DE OBRAS ---
with tab2:
    st.subheader("Gestión de Sitios y Obras")
    col1, col2 = st.columns([2, 1])
    
    with col1:
        nueva_obra = st.text_input("Nombre de nueva Obra")
        if st.button("Crear Obra"):
            if nueva_obra:
                conn = get_connection()
                try:
                    cursor = conn.cursor()
                    cursor.execute("INSERT INTO sitios (nombre) VALUES (%s)", (nueva_obra,))
                    conn.commit()
                    st.success(f"Obra '{nueva_obra}' creada.")
                    st.rerun()
                except:
                    st.error("Esa obra ya existe.")
                finally:
                    conn.close()
    
    with col2:
        conn = get_connection()
        df_obras = pd.read_sql("SELECT nombre FROM sitios ORDER BY nombre", conn)
        conn.close()
        st.dataframe(df_obras, hide_index=True, use_container_width=True)
