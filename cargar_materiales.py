import io
import warnings
import requests
from urllib3.exceptions import InsecureRequestWarning
from database import SessionLocal, Producto, init_db, extraer_datos_producto

# Ignorar advertencias de SSL en entornos corporativos
warnings.simplefilter('ignore', InsecureRequestWarning)

import gspread

def cargar_desde_existencia_bodega():
    """Carga los productos directamente desde Google Sheets usando gspread de forma segura."""
    init_db()
    
    print("--- INICIANDO CARGA DE MATERIALES DESDE GOOGLE SHEETS ---")
    try:
        # Autenticar de forma segura con la cuenta de servicio
        client = gspread.service_account(filename='credentials.json')
        
        # Abrir la hoja BODEGA usando su ID oficial
        file_id = "1DgmmISpHeTSJ6ByEKaxJSsF1HSDgZAxTCP_bXpYQ5IA"
        sheet = client.open_by_key(file_id).sheet1
        
        # Traer todas las filas como una lista cruda (ignorando la cabecera con [1:])
        filas = sheet.get_all_values()
        
        if not filas or len(filas) <= 1:
            print("La hoja de cálculo está vacía o solo tiene la cabecera.")
            return

        # La primera fila (índice 0) son los títulos, los datos reales empiezan desde la fila 1 en adelante
        registros_datos = filas[1:]
        print(f"¡Se leyeron {len(registros_datos)} filas correctamente desde Google Sheets!")
        
        session = SessionLocal()
        try:
            for fila in registros_datos:
                # Nos aseguramos de que la fila tenga al menos hasta la columna G (índice 6)
                if len(fila) <= 6:
                    continue
                
                # Extraemos usando las posiciones correctas: A(0)=Código, B(1)=Nombre, G(6)=Cantidad
                codigo, nombre, cantidad_str = extraer_datos_producto(fila)
                
                if not codigo or not str(codigo).strip():
                    continue
                
                # Limpiar y convertir la cantidad de forma segura (quitando puntos o comas si los hubiera)
                try:
                    cantidad = int(str(cantidad_str).strip().replace('.', '').replace(',', ''))
                except ValueError:
                    cantidad = 0
                
                # Guardar o actualizar en la base de datos
                prod = session.query(Producto).filter(Producto.codigo == str(codigo).strip()).first()
                if prod:
                    prod.nombre = str(nombre).strip()
                    prod.cantidad = cantidad
                else:
                    nuevo_prod = Producto(
                        codigo=str(codigo).strip(),
                        nombre=str(nombre).strip(),
                        cantidad=cantidad
                    )
                    session.add(nuevo_prod)
            
            session.commit()
            print("¡Base de datos actualizada exitosamente con los materiales y cantidades de la columna G!")
        except Exception as db_err:
            session.rollback()
            print(f"Error al guardar en la base de datos: {db_err}")
        finally:
            session.close()
        
    except Exception as e:
        print(f"Error al procesar el Google Sheet de bodega: {e}")


if __name__ == "__main__":
    cargar_desde_existencia_bodega()