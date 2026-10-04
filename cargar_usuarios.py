import pandas as pd
from pathlib import Path
from database import SessionLocal, Usuario, init_db


def cargar_usuarios_desde_excel(ruta_excel):
    # Asegurar que las tablas existan
    init_db()

    ruta = Path(ruta_excel)
    if not ruta.exists():
        print(f"❌ Error: El archivo '{ruta_excel}' no existe.")
        return

    try:
        df = pd.read_excel(ruta)

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
            print("❌ Error: No se encontraron las columnas necesarias en el Excel.")
            print(f"📌 Columnas detectadas: {list(df.columns)}")
            return

        session = SessionLocal()
        procesados = 0

        try:
            for _, fila in df.iterrows():
                cedula = str(fila[col_cedula]).strip()
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
            print("✅ Carga de usuarios finalizada con éxito.")
            print(f"📊 Registros procesados/actualizados: {procesados}")

        except Exception as e:
            session.rollback()
            print(f"❌ Error durante la transacción de usuarios: {e}")
        finally:
            session.close()

    except Exception as e:
        print(f"❌ Error al procesar el archivo Excel: {e}")


if __name__ == "__main__":
    print("--- INICIANDO CARGA DE USUARIOS ---")
    ruta_usuarios = Path(__file__).resolve().parent / "usuarios.xlsx"

    if ruta_usuarios.exists():
        print(f"Cargando desde: {ruta_usuarios.name}")
        cargar_usuarios_desde_excel(str(ruta_usuarios))
    else:
        print(f"⚠️ No se encontró el archivo '{ruta_usuarios.name}'")