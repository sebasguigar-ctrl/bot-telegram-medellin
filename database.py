import os
import re
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from dotenv import load_dotenv
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

load_dotenv()

# Conexión a la base de datos (PostgreSQL en producción o SQLite local por defecto)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///inventario.db")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# --- MODELOS SQL (TABLAS DE LA BASE DE DATOS) ---
class Usuario(Base):
    __tablename__ = "usuarios"

    cedula = Column(String(20), primary_key=True)
    nombre = Column(String(100), nullable=False)


class Producto(Base):
    __tablename__ = "productos"

    codigo = Column(String(50), primary_key=True)
    nombre = Column(Text, nullable=False)
    cantidad = Column(Integer, default=0, nullable=False)


class Movimiento(Base):
    __tablename__ = "movimientos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fecha = Column(DateTime, default=datetime.now)
    mes = Column(String(20))
    codigo_producto = Column(String(50), ForeignKey("productos.codigo"), nullable=False)
    tipo = Column(String(10), nullable=False)  # 'ENTRADA' o 'SALIDA'
    cantidad = Column(Integer, nullable=False)
    contratista = Column(String(100), default="")
    cedula_usuario = Column(String(20), ForeignKey("usuarios.cedula"), nullable=True)
    nombre_usuario = Column(String(100), default="")

    producto = relationship("Producto")


def init_db():
    """Crea la estructura de tablas vacías en la base de datos."""
    Base.metadata.create_all(bind=engine)


# --- ALGORITMOS DE BÚSQUEDA INTELIGENTE ---
def normalizar_texto(texto) -> str:
    if texto is None:
        return ""
    texto = str(texto).strip()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return texto.lower()


def limpiar_y_tokenizar(texto: str) -> list[str]:
    norm = normalizar_texto(texto)
    norm = re.sub(r"(\d+)([a-zA-Z]+)", r"\1 \2", norm)
    norm = re.sub(r"([a-zA-Z]+)(\d+)", r"\1 \2", norm)
    return re.findall(r"\w+", norm)


def calcular_similitud(query: str, nombre_producto: str) -> float:
    q_norm = normalizar_texto(query)
    p_norm = normalizar_texto(nombre_producto)

    if q_norm == p_norm:
        return 1.0
    if q_norm in p_norm:
        return 0.9

    tokens_q = limpiar_y_tokenizar(query)
    tokens_p = limpiar_y_tokenizar(nombre_producto)

    if not tokens_q or not tokens_p:
        return 0.0

    coincidencias = 0.0
    for t_q in tokens_q:
        mejor_sim_token = 0.0
        for t_p in tokens_p:
            if t_q == t_p:
                mejor_sim_token = 1.0
                break
            elif t_q in t_p or t_p in t_q:
                sim = len(min(t_q, t_p, key=len)) / len(max(t_q, t_p, key=len))
                mejor_sim_token = max(mejor_sim_token, sim)
            else:
                ratio = SequenceMatcher(None, t_q, t_p).ratio()
                if ratio >= 0.70:
                    mejor_sim_token = max(mejor_sim_token, ratio)

        if mejor_sim_token > 0.5:
            coincidencias += mejor_sim_token

    puntaje_tokens = coincidencias / len(tokens_q)
    q_compact = "".join(tokens_q)
    p_compact = "".join(tokens_p)
    ratio_global = SequenceMatcher(None, q_compact, p_compact).ratio()

    return max(puntaje_tokens, ratio_global)


# --- OPERACIONES CON LA BASE DE DATOS ---
def buscar_usuario_por_cedula(cedula: str) -> str | None:
    session = SessionLocal()
    try:
        usuario = session.query(Usuario).filter(Usuario.cedula == str(cedula).strip()).first()
        return usuario.nombre if usuario else None
    finally:
        session.close()


def buscar_productos_por_nombre_o_codigo(texto_busqueda: str):
    busqueda_limpia = normalizar_texto(texto_busqueda)
    if not busqueda_limpia:
        return []

    session = SessionLocal()
    try:
        productos = session.query(Producto).all()
        resultados = []

        for prod in productos:
            cod_norm = normalizar_texto(prod.codigo)

            if busqueda_limpia == cod_norm:
                return [(prod.codigo, prod.nombre, prod.cantidad)]

            if busqueda_limpia in cod_norm:
                resultados.append((1.0, prod.codigo, prod.nombre, prod.cantidad))
                continue

            puntaje = calcular_similitud(texto_busqueda, prod.nombre)
            if puntaje >= 0.50:
                resultados.append((puntaje, prod.codigo, prod.nombre, prod.cantidad))

        resultados.sort(key=lambda x: x[0], reverse=True)
        return [(cod, nom, cant) for _, cod, nom, cant in resultados]
    finally:
        session.close()


def registrar_lote_movimientos(carrito: list, tipo: str, cedula_usuario: str, nombre_usuario: str, contratista: str = "") -> bool:
    session = SessionLocal()
    meses_es = {
        1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
        5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
        9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"
    }

    try:
        ahora = datetime.now()
        mes_str = meses_es.get(ahora.month, "")

        for item in carrito:
            cod = str(item["codigo"]).strip()
            cant = int(item["cantidad"])

            prod = session.query(Producto).filter(Producto.codigo == cod).first()
            if not prod:
                continue

            if tipo == "ENTRADA":
                prod.cantidad += cant
            elif tipo == "SALIDA":
                if prod.cantidad < cant:
                    raise ValueError(f"Stock insuficiente para {prod.nombre}. Disponible: {prod.cantidad}")
                prod.cantidad -= cant

            mov = Movimiento(
                fecha=ahora,
                mes=mes_str,
                codigo_producto=cod,
                tipo=tipo,
                cantidad=cant,
                contratista=contratista,
                cedula_usuario=cedula_usuario,
                nombre_usuario=nombre_usuario
            )
            session.add(mov)

        session.commit()
        return True
    except Exception as e:
        session.rollback()
        print(f"❌ Error procesando el lote: {e}")
        return False
    finally:
        session.close()


def extraer_datos_producto(fila):
    return fila[0], fila[1], fila[6]    