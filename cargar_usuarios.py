import pandas as pd
import gspread
from database import SessionLocal, Usuario, init_db

def cargar_usuarios_desde_googlesheets():
    # Asegurar que las tablas existan
    init_db()

    # ID oficial de la hoja de Usuarios en Google Sheets
    file_id = "1WCrlVgCpJSS1lBn-uNKtEAG9ul5AZ-S1UnMxNm-C9HY"

    print("--- INICIANDO CARGA DE USUARIOS DESDE GOOGLE SHEETS ---")

    try:
        # Autenticar de forma segura con la cuenta de servicio
        client = gspread.service_account(filename='credentials.json')
        
        # Abrir la hoja de cálculo usando su ID oficial
        sheet = client.open_by_key(file_id).sheet1
        
        # Obtener todos los registros en formato de lista de diccionarios y pasarlos a pandas
        data = sheet.get_all_records()
        df = pd.DataFrame(data)

        if df.empty or len(df) < 1:
            print("❌ La hoja de cálculo de usuarios está vacía o no tiene registros válidos.")
            return

        # Limpiar nombres de columnas
        df.columns = [str(c).strip().lower() for c in df.columns]

        # Mapeo flexible de columnas
        col_cedula = next(
            (c for c in df.columns if "rut" in c or "cedula" in c or "id" in c),
            None,
        )
        col_nombre = next(
            (c for c in df.columns if "nom" in c or "usuario" in c), None
        )

        if not col_cedula or not col_nombre:
            print("❌ Error: No se encontraron las columnas necesarias en el Google Sheet.")
            print(f"📌 Columnas detectadas: {list(df.columns)}")
            return

        session = SessionLocal()
        procesados = 0

        try:
            for _, fila in df.iterrows():
                cedula_raw = fila[col_cedula]
                if pd.isna(cedula_raw):
                    continue
                
                # Evitar decimales si lee la cédula como número
                if isinstance(cedula_raw, float) and cedula_raw.is_integer():
                    cedula = str(int(cedula_raw)).strip()
                else:
                    cedula = str(cedula_raw).strip()

                nombre = str(fila[col_nombre]).strip()

                if not cedula or not nombre or cedula.lower() in ["nan", "none", ""]:
                    continue

                # Insertar o Actualizar Usuario
                usuario = (
                    session.query(Usuario)
                    .filter(Usuario.cedula == cedula)
                    .first()
                )
                if usuario:
                    usuario.nombre = nombre
                else:
                    usuario = Usuario(cedula=cedula, nombre=nombre)
                    session.add(usuario)

                procesados += 1

            session.commit()
            print("✅ Carga de usuarios desde Google Sheets finalizada con éxito.")
            print(f"📊 Registros procesados/actualizados: {procesados}")

        except Exception as e:
            session.rollback()
            print(f"❌ Error durante la transacción de usuarios: {e}")
        finally:
            session.close()

    except Exception as e:
        print(f"❌ Error al procesar el Google Sheet de usuarios: {e}")


if __name__ == "__main__":
    cargar_usuarios_desde_googlesheets()