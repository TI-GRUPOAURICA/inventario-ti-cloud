import streamlit as st
import mysql.connector
import pandas as pd
from datetime import datetime
import io
import xlsxwriter

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
    
    # Tabla Sitios (Obras)
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
            tipo VARCHAR(50),
            marca_modelo VARCHAR(100),
            usuario VARCHAR(100),
            sitio_id INT,
            FOREIGN KEY (sitio_id) REFERENCES sitios(id) ON DELETE SET NULL
        );
    """)
    
    # --- MIGRACIÓN: AGREGAR COLUMNAS ---
    # Nota: La columna 'empresa' tiene un valor por defecto 'Sin Asignar'
    # Esto permite que tu Agente viejo siga funcionando sin cambios.
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
        ("detalles", "TEXT"),
        ("empresa", "VARCHAR(100) DEFAULT 'Sin Asignar'") 
    ]
    
    for col, tipo in nuevas_columnas:
        try:
            cursor.execute(f"ALTER TABLE equipos ADD COLUMN {col} {tipo}")
        except: pass 

    # Asegurar estados por defecto
    estados = ["LIBRE", "DEFECTUOSA", "OFICINA CENTRAL"]
    for estado in estados:
        try: cursor.execute("INSERT IGNORE INTO sitios (nombre) VALUES (%s)", (estado,))
        except: pass

    conn.commit()
    conn.close()

# =======================================================
# INTERFAZ WEB
# =======================================================
st.set_page_config(page_title="Inventario Multi-Empresa", layout="wide", page_icon="🏢")

# Inicializar DB
init_db()

# --- DEFINIR TUS EMPRESAS AQUÍ ---
LISTA_EMPRESAS = [
    "Sin Asignar", # <--- Importante para los nuevos equipos
    "MYJ Construccion e Ingenieria",
    "Design Ingenieria y Construccion",
    "TRALSA",
    "Fysem Ingenieros"
]

# --- BARRA LATERAL (FILTRO) ---
with st.sidebar:
    st.title("🔍 Filtros")
    # Filtro Principal
    filtro_empresa = st.selectbox(
        "Ver Empresa:", 
        ["TODAS"] + LISTA_EMPRESAS,
        index=0
    )
    
    st.divider()
    
    # Métricas rápidas
    conn = get_connection()
    if filtro_empresa == "TODAS":
        total = pd.read_sql("SELECT COUNT(*) as c FROM equipos", conn).iloc[0]['c']
        st.metric("Total Equipos (Global)", total)
    else:
        total = pd.read_sql(f"SELECT COUNT(*) as c FROM equipos WHERE empresa = '{filtro_empresa}'", conn).iloc[0]['c']
        st.metric(f"Total en {filtro_empresa[:15]}...", total)
    conn.close()

st.title("🖥️ Gestión Centralizada de Activos TI")

tab1, tab2 = st.tabs(["📋 Inventario & Asignación", "🏗️ Gestión de Obras"])

# --- PESTAÑA 1: TABLA PRINCIPAL ---
with tab1:
    conn = get_connection()
    
    # Cargar Obras
    df_sitios = pd.read_sql("SELECT id, nombre FROM sitios ORDER BY nombre", conn)
    lista_obras = df_sitios['nombre'].tolist()
    mapa_obras = dict(zip(df_sitios['nombre'], df_sitios['id'])) 
    mapa_ids = dict(zip(df_sitios['id'], df_sitios['nombre']))

    # CONSTRUIR QUERY SEGÚN EL FILTRO
    base_query = """
        SELECT 
            id, codigo_inventario, codigo_manual, marca_modelo, usuario, tipo, 
            detalles, sitio_id, ultima_conexion, ram, procesador, disco, 
            serie, mainboard, video, antivirus, windows_ver, empresa
        FROM equipos 
    """
    
    if filtro_empresa != "TODAS":
        base_query += f" WHERE empresa = '{filtro_empresa}'"
    
    base_query += " ORDER BY ultima_conexion DESC"

    df_equipos = pd.read_sql(base_query, conn)
    conn.close()

    # Mapear Obra
    df_equipos['Obra'] = df_equipos['sitio_id'].map(mapa_ids).fillna("Sin Asignar")
    
    # Columnas que NO se editan (vienen del agente)
    cols_bloqueadas = ('codigo_inventario', 'serie', 'ram', 'procesador', 'disco', 'mainboard', 'video', 'ultima_conexion', 'antivirus', 'windows_ver')

    # --- TABLA EDITABLE ---
    st.info("💡 Tip: Usa la columna **'Empresa Asignada'** para clasificar los equipos nuevos que llegan como 'Sin Asignar'.")
    
    cambios = st.data_editor(
        df_equipos,
        column_config={
            "id": None, "sitio_id": None, 
            
            # NUEVA COLUMNA SELECTORA DE EMPRESA
            "empresa": st.column_config.SelectboxColumn(
                "🏢 Empresa Asignada",
                help="Selecciona a qué cliente pertenece este equipo",
                width="medium",
                options=LISTA_EMPRESAS,
                required=True
            ),
            
            "codigo_manual": st.column_config.TextColumn("🟦 Colaborador", width="medium"),
            "detalles": st.column_config.TextColumn("📝 Detalles / Notas", width="large"),
            "usuario": st.column_config.TextColumn("Usuario (PC)", width="small", disabled=True),
            "Obra": st.column_config.SelectboxColumn("📍 Ubicación / Obra", width="medium", options=lista_obras, required=True),
            "codigo_inventario": st.column_config.TextColumn("Hostname", disabled=True),
            "ultima_conexion": st.column_config.DatetimeColumn("Última Conexión", format="D MMM YYYY, h:mm a", disabled=True),
            "tipo": st.column_config.SelectboxColumn("Tipo", options=["Laptop", "PC Escritorio", "Servidor"], width="small"),
            "mainboard": st.column_config.TextColumn("Placa", disabled=True),
            "video": st.column_config.TextColumn("Video", disabled=True),
            "antivirus": st.column_config.TextColumn("AV", disabled=True),
            "windows_ver": st.column_config.TextColumn("OS", disabled=True),
        },
        disabled=cols_bloqueadas, 
        num_rows="dynamic",       
        use_container_width=True,
        key="editor_global",
        hide_index=True,
        # ORDEN DE COLUMNAS: Empresa primero para clasificar rápido
        column_order=("empresa", "codigo_manual", "codigo_inventario", "usuario", "Obra", "detalles", "tipo", "marca_modelo", "ram", "disco", "serie", "ultima_conexion", "procesador") 
    )

    # --- BOTÓN GUARDAR ---
    if st.button("💾 Guardar Cambios y Asignaciones", type="primary"):
        conn = get_connection()
        cursor = conn.cursor()
        try:
            # 1. DETECTAR BORRADOS (Solo si no estamos en vista filtrada parcial que oculte IDs)
            # Para seguridad, el borrado mejor hacerlo con cuidado. Aquí mantenemos la lógica simple:
            if filtro_empresa == "TODAS":
                cursor.execute("SELECT id FROM equipos")
                ids_db = set(row[0] for row in cursor.fetchall())
                ids_screen = set(cambios['id'].dropna().astype(int).tolist())
                ids_del = ids_db - ids_screen
                if ids_del:
                    format_str = ','.join(['%s'] * len(ids_del))
                    cursor.execute(f"DELETE FROM equipos WHERE id IN ({format_str})", tuple(ids_del))

            # 2. ACTUALIZACIONES (Empresa, Obra, Notas, etc.)
            for index, row in cambios.iterrows():
                nombre_obra = row['Obra']
                id_obra_real = mapa_obras.get(nombre_obra)
                
                if row['codigo_inventario']:
                    sql = """
                        UPDATE equipos SET 
                        sitio_id = %s, tipo = %s,
                        codigo_manual = %s, detalles = %s, 
                        empresa = %s  -- <--- AQUÍ SE GUARDA LA EMPRESA QUE SELECCIONASTE
                        WHERE codigo_inventario = %s
                    """
                    vals = (
                        id_obra_real, row['tipo'], row['codigo_manual'], 
                        row['detalles'], row['empresa'], row['codigo_inventario']
                    )
                    cursor.execute(sql, vals)
            
            conn.commit()
            st.toast("✅ Asignaciones de empresa guardadas.", icon="🏢")
            st.rerun()
        except Exception as e:
            st.error(f"Error: {e}")
        finally:
            conn.close()

    # EXCEL
    if not cambios.empty:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            cambios.to_excel(writer, index=False, sheet_name="Inventario")
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
                except: st.error("Ya existe.")
                finally: conn.close()
    with col2:
        conn = get_connection()
        df_obras = pd.read_sql("SELECT nombre FROM sitios ORDER BY nombre", conn)
        conn.close()
        st.dataframe(df_obras, hide_index=True, use_container_width=True)
