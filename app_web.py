import streamlit as st
import mysql.connector
import pandas as pd
from datetime import datetime
import io
import xlsxwriter # Asegura que esté importado

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
    conn = get_connection()
    cursor = conn.cursor()
    
    # Tabla Sitios
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sitios (
            id INT AUTO_INCREMENT PRIMARY KEY,
            nombre VARCHAR(255) UNIQUE NOT NULL
        );
    """)
    
    # Estados por defecto
    estados = ["LIBRE", "DEFECTUOSA", "OFICINA CENTRAL"]
    for estado in estados:
        try:
            cursor.execute("INSERT IGNORE INTO sitios (nombre) VALUES (%s)", (estado,))
        except: pass
    conn.commit()

    # Tabla Equipos
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
    
    # Nuevas columnas
    nuevas_columnas = [
        ("ram", "VARCHAR(50)"),
        ("procesador", "VARCHAR(100)"),
        ("disco", "VARCHAR(50)"),
        ("mainboard", "VARCHAR(100)"),
        ("video", "VARCHAR(150)"),
        ("antivirus", "VARCHAR(150)"),
        ("windows_ver", "VARCHAR(100)"),
        ("ultima_conexion", "DATETIME"),
        ("codigo_manual", "VARCHAR(50)"), 
        ("detalles", "TEXT")              
    ]
    
    for col, tipo in nuevas_columnas:
        try:
            cursor.execute(f"ALTER TABLE equipos ADD COLUMN {col} {tipo}")
        except: pass 

    conn.commit()
    conn.close()

# =======================================================
# INTERFAZ WEB
# =======================================================
st.set_page_config(page_title="Inventario TI", layout="wide", page_icon="🖥️")
st.title("🖥️ Panel de Control de Inventario TI")

init_db()

tab1, tab2 = st.tabs(["📋 Inventario General (Editable)", "🏗️ Gestión de Obras"])

# --- PESTAÑA 1: TABLA PRINCIPAL ---
with tab1:
    conn = get_connection()
    
    # Cargar Obras
    df_sitios = pd.read_sql("SELECT id, nombre FROM sitios ORDER BY nombre", conn)
    lista_obras = df_sitios['nombre'].tolist()
    mapa_obras = dict(zip(df_sitios['nombre'], df_sitios['id'])) 
    mapa_ids = dict(zip(df_sitios['id'], df_sitios['nombre']))

    # Cargar Equipos
    query = """
        SELECT 
            id, codigo_inventario, codigo_manual, marca_modelo, usuario, tipo, 
            detalles, sitio_id, ultima_conexion, ram, procesador, disco, 
            serie, mainboard, video, antivirus, windows_ver
        FROM equipos 
        ORDER BY ultima_conexion DESC
    """
    df_equipos = pd.read_sql(query, conn)
    conn.close()

    # Preparar DataFrame
    df_equipos['Obra'] = df_equipos['sitio_id'].map(mapa_ids).fillna("Sin Asignar")
    
    cols_bloqueadas = ('codigo_inventario', 'serie', 'ram', 'procesador', 'disco', 'mainboard', 'video', 'ultima_conexion', 'antivirus', 'windows_ver')

    # TABLA EDITABLE
    cambios = st.data_editor(
        df_equipos,
        column_config={
            "id": None, # Oculto
            "sitio_id": None, 
            "codigo_manual": st.column_config.TextColumn("🟦 Colaborador", help="Digita aquí el código manual", width="small"),
            "detalles": st.column_config.TextColumn("📝 Detalles / Notas", width="large"),
            "usuario": st.column_config.TextColumn("Usuario Asignado", width="medium"),
            "Obra": st.column_config.SelectboxColumn("📍 Ubicación", width="medium", options=lista_obras, required=True),
            "codigo_inventario": st.column_config.TextColumn("Hostname (PC)", disabled=True),
            "ultima_conexion": st.column_config.DatetimeColumn("Última Conexión", format="D MMM YYYY, h:mm a", disabled=True),
            "tipo": st.column_config.SelectboxColumn("Tipo", options=["Laptop", "PC Escritorio", "Servidor"], width="small"),
            "mainboard": st.column_config.TextColumn("Placa Madre", disabled=True),
            "video": st.column_config.TextColumn("Tarjeta Video", disabled=True),
            "antivirus": st.column_config.TextColumn("Antivirus", disabled=True),
            "windows_ver": st.column_config.TextColumn("Sist. Operativo", disabled=True),
        },
        disabled=cols_bloqueadas, 
        num_rows="dynamic",       
        use_container_width=True,
        key="editor_equipos",
        hide_index=True,
        column_order=("codigo_manual", "codigo_inventario", "usuario", "Obra", "detalles", "tipo", "marca_modelo", "ram", "disco", "serie", "procesador", "mainboard", "video", "antivirus", "ultima_conexion") 
    )

    # --- LÓGICA DE GUARDADO Y BORRADO ---
    if st.button("💾 Guardar Cambios Realizados", type="primary"):
        conn = get_connection()
        cursor = conn.cursor()
        try:
            # 1. DETECTAR FILAS BORRADAS
            # Obtenemos todos los IDs que existen realmente en la base de datos
            cursor.execute("SELECT id FROM equipos")
            ids_en_db = set(row[0] for row in cursor.fetchall())
            
            # Obtenemos los IDs que quedan en la tabla visible (ignorando los nuevos vacíos)
            ids_en_pantalla = set(cambios['id'].dropna().astype(int).tolist())
            
            # La diferencia son los que el usuario borró
            ids_a_borrar = ids_en_db - ids_en_pantalla
            
            if ids_a_borrar:
                # Borramos esos IDs de la base de datos
                lista_borrar = list(ids_a_borrar)
                format_strings = ','.join(['%s'] * len(lista_borrar))
                cursor.execute(f"DELETE FROM equipos WHERE id IN ({format_strings})", tuple(lista_borrar))
                st.toast(f"🗑️ Se eliminaron {len(lista_borrar)} equipos.", icon="🗑️")

            # 2. ACTUALIZAR FILAS MODIFICADAS O NUEVAS
            for index, row in cambios.iterrows():
                nombre_obra = row['Obra']
                id_obra_real = mapa_obras.get(nombre_obra)
                
                # Si tiene ID, actualizamos. Si es nuevo (sin ID), insertamos.
                # Nota: Para simplificar, usamos el Hostname como clave de actualización
                if row['codigo_inventario']:
                    sql = """
                        UPDATE equipos SET 
                        usuario = %s, 
                        sitio_id = %s,
                        tipo = %s,
                        marca_modelo = %s,
                        codigo_manual = %s,
                        detalles = %s
                        WHERE codigo_inventario = %s
                    """
                    vals = (
                        row['usuario'], id_obra_real, row['tipo'], row['marca_modelo'], 
                        row['codigo_manual'], row['detalles'], 
                        row['codigo_inventario']
                    )
                    cursor.execute(sql, vals)
            
            conn.commit()
            st.success("✅ Base de datos actualizada correctamente!")
            st.rerun() # Recarga la página para ver los cambios limpios
            
        except Exception as e:
            st.error(f"Error guardando: {e}")
        finally:
            conn.close()

    # EXPORTAR EXCEL
    if not cambios.empty:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            cambios.to_excel(writer, index=False, sheet_name='Inventario')
        st.download_button(label="📗 Descargar Excel", data=output.getvalue(), file_name="inventario_ti.xlsx", mime="application/vnd.ms-excel")

# --- PESTAÑA 2: OBRAS ---
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
                except: st.error("Esa obra ya existe.")
                finally: conn.close()
    with col2:
        conn = get_connection()
        df_obras = pd.read_sql("SELECT nombre FROM sitios ORDER BY nombre", conn)
        conn.close()
        st.dataframe(df_obras, hide_index=True, use_container_width=True)


