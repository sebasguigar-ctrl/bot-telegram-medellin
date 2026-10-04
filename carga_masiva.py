import sqlite3
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
    """Carga masivamente materiales resolviendo duplicados según la estructura real de productos."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        df = pd.read_excel(ruta_excel, sheet_name=nombre_hoja)
        
        cargados = 0
        for _, row in df.iterrows():
            cod = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ""
            nom = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else "Sin Descripción"
            cant_raw = row.iloc[2] if len(row) > 2 else 0

            if not cod or cod.lower() in ["nan", "none", ""]:
                continue

            try:
                cant = int(cant_raw) if not pd.isna(cant_raw) else 0
            except (ValueError, TypeError):
                cant = 0

            # Solo insertamos codigo, nombre y cantidad
            cursor.execute("""
                INSERT INTO productos (codigo, nombre, cantidad)
                VALUES (?, ?, ?)
                ON CONFLICT(codigo) DO UPDATE SET
                    nombre = excluded.nombre,
                    cantidad = excluded.cantidad
            """, (cod, nom, cant))
            
            cargados += 1

        conn.commit()
        print(f"✅ ¡Éxito! Se procesaron {cargados} productos correctamente.")
    except Exception as e:
        conn.rollback()
        print(f"❌ Error al cargar materiales: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    print("--- INICIANDO CARGA MASIVA A LA BASE DE DATOS ---")
    
    # 1. Cargar Usuarios
    ruta_usuarios = Path(__file__).parent / "usuarios.xlsx"
    if ruta_usuarios.exists():
        print("Cargando usuarios desde usuarios.xlsx...")
        cargar_usuarios_desde_excel(str(ruta_usuarios))
    else:
        print(f"⚠️ No se encontró el archivo {ruta_usuarios}")

    # 2. Cargar Materiales / Productos
    # Se pasa nombre_hoja=0 para que lea automáticamente la PRIMERA pestaña sin importar su nombre exacto
    ruta_bodega = r"C:\Users\1872157.PRODUCTION\OneDrive - LLA\Escritorio\BODEGA - bot_tele_COPIA.xlsx"
    if Path(ruta_bodega).exists():
        print("Cargando materiales desde Excel de Bodega...")
        cargar_materiales_desde_excel(ruta_bodega, nombre_hoja=0)
    else:
        print(f"⚠️️ No se encontró el archivo de materiales en {ruta_bodega}")