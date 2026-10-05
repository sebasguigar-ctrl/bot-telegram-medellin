import io
import warnings
import pandas as pd
import requests
from urllib3.exceptions import InsecureRequestWarning
from database import SessionLocal, Producto, init_db

# Ignorar advertencias de SSL en entornos corporativos
warnings.simplefilter('ignore', InsecureRequestWarning)

import gspread
import pandas as pd
from database import SessionLocal, Producto, init_db

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
        
        # Traer todos los registros a un DataFrame de pandas
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        
        if df.empty or len(df) < 1:
            print("La hoja de cálculo está vacía o no tiene registros válidos.")
            return

        print(f"¡Se leyeron {len(df)} filas correctamente desde Google Sheets!")
        
        # (Aquí sigue el resto de la lógica de tu base de datos que ya tenías para recorrer el 'df' e insertarlo en SQLite)
        
    except Exception as e:
        print(f"Error al procesar el Google Sheet de bodega: {e}")


if __name__ == "__main__":
    cargar_desde_existencia_bodega()