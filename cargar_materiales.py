import io
import warnings
import pandas as pd
import requests
from urllib3.exceptions import InsecureRequestWarning
from database import SessionLocal, Producto, init_db

# Ignorar advertencias de SSL en entornos corporativos
warnings.simplefilter('ignore', InsecureRequestWarning)

def cargar_desde_existencia_bodega():
    """Carga los productos directamente desde Google Sheets omitiendo restricciones corporativas de SSL."""
    init_db()

    # URL de exportación CSV de Google Sheets para Bodega
    file_id = "1ja9zwTpO4GWzSHsh3ChMvadyxGw5XmtN"
    gid = "1306378031"
    url = f"https://docs.google.com/spreadsheets/d/{file_id}/export?format=csv&gid={gid}"

    print("--- INICIANDO CARGA DE MATERIALES DESDE GOOGLE SHEETS ---")

    try:
        # Usamos verify=False para evitar el bloqueo del certificado de la empresa
        response = requests.get(url, timeout=30, verify=False)
        response.raise_for_status()
        
        df = pd.read_csv(io.StringIO(response.text))

        if df.empty or len(df) < 1:
            print("⚠️ El Google Sheet de bodega está vacío o no contiene datos.")
            return

        # Limpiar nombres de columnas
        df.columns = [
            str(col).replace("\n", " ").replace("\r", "").strip()
            if col is not None
            else ""
            for col in df.columns
        ]

        col_codigo = df.columns[0]  # Columna A (Codigo)
        col_descrip = df.columns[1]  # Columna B (Material Description)

        # Buscar columna de cantidad
        col_cant_match = [c for c in df.columns if "CANTIDAD BODEGA" in c.upper()]
        if col_cant_match:
            col_cantidad = col_cant_match[0]
        else:
            col_cantidad = df.columns[6] if len(df.columns) > 6 else None

        session = SessionLocal()
        cargados = 0
        con_stock = 0

        try:
            for _, row in df.iterrows():
                cod_raw = row[col_codigo]
                if pd.isna(cod_raw):
                    continue

                # Formatear el código correctamente sin decimales flotantes (.0)
                if isinstance(cod_raw, float) and cod_raw.is_integer():
                    cod = str(int(cod_raw)).strip()
                else:
                    cod = str(cod_raw).strip()

                if not cod or cod.lower() in ["nan", "none", "", "codigo"]:
                    continue

                nombre = (
                    str(row[col_descrip]).strip()
                    if pd.notna(row[col_descrip])
                    else "Sin Descripción"
                )

                # Procesar valor numérico de la cantidad
                cant = 0
                if col_cantidad and pd.notna(row[col_cantidad]):
                    try:
                        cant = int(float(row[col_cantidad]))
                    except (ValueError, TypeError):
                        cant = 0

                if cant > 0:
                    con_stock += 1

                # Insertar o Actualizar Producto en la BD
                producto = (
                    session.query(Producto).filter(Producto.codigo == cod).first()
                )
                if producto:
                    producto.nombre = nombre
                    producto.cantidad = cant
                else:
                    producto = Producto(codigo=cod, nombre=nombre, cantidad=cant)
                    session.add(producto)

                cargados += 1

            session.commit()
            print(f"✅ ¡Éxito! Se cargaron/actualizaron {cargados} productos desde Google Sheets ({con_stock} con stock real).")

        except Exception as e:
            session.rollback()
            print(f"❌ Error durante la carga de materiales: {e}")
        finally:
            session.close()

    except Exception as e:
        print(f"❌ Error al procesar el Google Sheet de bodega: {e}")


if __name__ == "__main__":
    cargar_desde_existencia_bodega()