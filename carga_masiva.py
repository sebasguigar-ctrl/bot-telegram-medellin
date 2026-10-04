import sqlite3
import openpyxl
import pandas as pd
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "inventario.db"

from database import SessionLocal, Producto, Usuario, init_db

# 1. Asegurar que las tablas existan en la BD
init_db()

def cargar_usuarios_desde_excel(ruta_excel: str):
    """Carga masivamente usuarios desde un Excel (Columnas: 'nombre' y 'cedula')."""
    session = SessionLocal()
    try:
        df = pd.read_excel(ruta_excel, dtype=str)
        df.columns = [str(col).strip().lower() for col in df.columns]

        cont = 0
        for _, row in df.iterrows():
            ced = str(row["cedula"]).strip()
            nom = str(row["nombre"]).strip()

            if not session.query(Usuario).filter(Usuario.cedula == ced).first():
                session.add(Usuario(cedula=ced, nombre=nom))
                cont += 1

        session.commit()
        print(f"✅ Se cargaron {cont} usuarios correctamente.")
    except Exception as e:
        session.rollback()
        print(f"❌ Error al cargar usuarios: {e}")
    finally:
        session.close()


def cargar_materiales_desde_excel(ruta_excel: str, nombre_hoja=0):
    """Carga masivamente materiales resolviendo fórmulas y buscando la Columna G (CANTIDAD BODEGA)."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # Cargar evaluando formulas con openpyxl (data_only=True)
        wb = openpyxl.load_workbook(ruta_excel, data_only=True)
        sheet = wb.worksheets[0] if isinstance(nombre_hoja, int) else wb[nombre_hoja]
        
        data = list(sheet.values)
        if not data:
            print("⚠️ La hoja de Excel está vacía.")
            return

        cols = [str(c).replace('\n', ' ').replace('\r', '').strip() if c is not None else '' for c in data[0]]
        df = pd.DataFrame(data[1:], columns=cols)

        # Buscar la columna de cantidad (Columna G o por nombre)
        col_cant_match = [c for c in df.columns if 'CANTIDAD BODEGA' in c.upper()]
        if col_cant_match:
            col_cantidad = col_cant_match[0]
        else:
            col_cantidad = df.columns[6]  # Columna G (índice 6)

        col_codigo = df.columns[0]   # Columna A
        col_descrip = df.columns[1]  # Columna B

        cargados = 0
        con_stock = 0

        for _, row in df.iterrows():
            cod = str(row[col_codigo]).strip() if pd.notna(row[col_codigo]) else None
            desc = str(row[col_descrip]).strip() if pd.notna(row[col_descrip]) else "Sin Descripción"

            if not cod or cod.lower() in ["nan", "none", "", "codigo"]:
                continue

            # Convertir valor numérico de la celda de la Columna G
            raw_cant = row[col_cantidad]
            try:
                if pd.notna(raw_cant) and str(raw_cant).strip() != '':
                    cant = int(float(raw_cant))
                else:
                    cant = 0
            except (ValueError, TypeError):
                cant = 0

            # Guardar/Actualizar en SQLite
            cursor.execute("""
                INSERT INTO productos (codigo, descripcion, cantidad)
                VALUES (?, ?, ?)
                ON CONFLICT(codigo) DO UPDATE SET
                    descripcion = excluded.descripcion,
                    cantidad = excluded.cantidad
            """, (cod, desc, cant))

            cargados += 1
            if cant > 0:
                con_stock += 1

        conn.commit()
        print(f"✅ ¡Éxito! Se procesaron {cargados} productos ({con_stock} con stock > 0).")

    except Exception as e:
        conn.rollback()
        print(f"❌ Error al cargar materiales: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    print("--- INICIANDO CARGA MASIVA A LA BASE DE DATOS ---")

    # 1. Cargar Usuarios
    ruta_usuarios = Path(__file__).resolve().parent / "usuarios.xlsx"
    if ruta_usuarios.exists():
        print("Cargando usuarios desde usuarios.xlsx...")
        cargar_usuarios_desde_excel(str(ruta_usuarios))
    else:
        print(f"⚠️ No se encontró el archivo {ruta_usuarios}")

    # 2. Cargar Materiales / Productos
    ruta_bodega = Path(__file__).resolve().parent / "BODEGA - bot_tele_COPIA.xlsx"
    if not ruta_bodega.exists():
        # Ruta alternativa si el archivo está en el Escritorio
        ruta_bodega = Path(r"C:\Users\1872157.PRODUCTION\OneDrive - LLA\Escritorio\BODEGA - bot_tele_COPIA.xlsx")

    if ruta_bodega.exists():
        print("Cargando materiales desde Excel de Bodega...")
        cargar_materiales_desde_excel(str(ruta_bodega))
    else:
        print(f"⚠️ No se encontró el archivo de materiales en {ruta_bodega}")