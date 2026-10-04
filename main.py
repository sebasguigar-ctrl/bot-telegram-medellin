import os
import asyncio
import ssl
import httpx
from cargar_usuarios import cargar_usuarios_desde_googlesheets
from cargar_materiales import cargar_desde_existencia_bodega
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.request import HTTPXRequest
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)
from database import init_db

from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
import os

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot activo 24/7")

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), SimpleHTTPRequestHandler)
    server.serve_forever()

# Inicia el servidor HTTP en un hilo secundario
Thread(target=run_web_server, daemon=True).start()

# Crea las tablas si no existen al iniciar
init_db()

# Botón global para finalizar sesión en cualquier pantalla
BOTON_FINALIZAR = InlineKeyboardButton("🔒 Finalizar Sesión", callback_data="finalizar_sesion")


# Importar funciones de la nueva base de datos SQL
from database import (
    buscar_productos_por_nombre_o_codigo,
    buscar_usuario_por_cedula,
    registrar_lote_movimientos,
)

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID_GRUPO = os.getenv("CHAT_ID_GRUPO")

# Definición de estados para el ConversationHandler
(
    SOLICITAR_CEDULA,  # (0)
    MENU_PRINCIPAL,
    MENU_BODEGA,
    BUSCAR_ENTRADA,
    CONFIRMAR_PROD_ENTRADA,
    SELECCIONAR_PROD_ENTRADA,
    CANTIDAD_ENTRADA,
    SELECCIONAR_EMPRESA_SALIDA,
    BUSCAR_SALIDA,
    CONFIRMAR_PROD_SALIDA,
    SELECCIONAR_PROD_SALIDA,
    CANTIDAD_SALIDA,
    PREGUNTAR_OTRO,
    CONFIRMAR_LOTE_ENTRADA,
    CONFIRMAR_LOTE_SALIDA,
    BUSCAR_CONSULTA,
    SELECCIONAR_PROD_CONSULTA,
    SIN_STOCK_SALIDA,  # <-- NUEVO ESTADO AGREGADO (17)
) = range(18)  # <-- CAMBIADO A 18


def extraer_datos_producto(fila):
    """Extrae código, nombre y cantidad de una tupla de la base de datos."""
    try:
        if not fila:
            return "", "MATERIAL DESCONOCIDO", 0

        cod = str(fila[0]).strip() if len(fila) > 0 else ""
        raw_nombre = fila[1] if len(fila) > 1 else "SIN NOMBRE"
        nombre = raw_nombre.decode("utf-8", errors="ignore") if isinstance(raw_nombre, bytes) else str(raw_nombre).strip()

        try:
            cant = int(fila[2]) if len(fila) > 2 else 0
        except (ValueError, TypeError):
            cant = 0

        return cod, nombre, cant
    except Exception:
        return "", "MATERIAL DESCONOCIDO", 0


# --- MENÚ PRINCIPAL GENERAL ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Si ya se autenticó en esta sesión, va directo al menú
    if context.user_data.get("autenticado", False):
        return await mostrar_menu_principal(update, context)

    # Si es nuevo, pide la cédula
    context.user_data.clear()
    texto = "👋 *¡Bienvenido al asistente Liberty - Medellín!*\n\nPor favor, ingresa tu **número de cédula** para identificarte:"
    
    query = update.callback_query
    if query:
        await query.answer()
        await query.message.edit_text(texto, parse_mode="Markdown")
    else:
        await update.message.reply_text(texto, parse_mode="Markdown")

    return SOLICITAR_CEDULA


async def validar_cedula(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    cedula = update.message.text.strip()
    nombre = buscar_usuario_por_cedula(cedula)

    if nombre:
        context.user_data["autenticado"] = True
        context.user_data["nombre_usuario"] = nombre
        await update.message.reply_text(f"✅ *¡¡Todo en orden, {nombre}! *🚀", parse_mode="Markdown")
        return await mostrar_menu_principal(update, context)
    else:
        await update.message.reply_text("❌ *Cédula no registrada en el sistema.*\nPor favor, verifica e ingresa tu cédula de nuevo:", parse_mode="Markdown")
        return SOLICITAR_CEDULA


async def mostrar_menu_principal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Limpia datos de búsquedas anteriores
    for clave in ["carrito_entrada", "carrito_salida", "empresa_salida", "prod_codigo", "prod_nombre", "prod_max", "resultados_busqueda", "resultados_busqueda_sal", "resultados_busqueda_cons"]:
        context.user_data.pop(clave, None)

    nombre = context.user_data.get("nombre_usuario", "Usuario")

    keyboard = [
        [InlineKeyboardButton("📦 Bodega ", callback_data="op_bodega")],
        [InlineKeyboardButton("👷 Instalaciones (Próximamente)", callback_data="op_cliente")],
        [BOTON_FINALIZAR],
    ]
    
    texto = "Selecciona a dónde quieres ir:"

    query = update.callback_query
    if query:
        await query.answer()
        await query.message.edit_text(texto, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await update.message.reply_text(texto, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    return MENU_PRINCIPAL

# --- SUBMENÚ BODEGA ---
async def menu_bodega(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # 🧹 Vaciar carritos y datos temporales al volver al Menú de Bodega
    context.user_data.pop("carrito_entrada", None)
    context.user_data.pop("carrito_salida", None)
    context.user_data.pop("empresa_salida", None)
    context.user_data.pop("prod_codigo", None)
    context.user_data.pop("prod_nombre", None)
    context.user_data.pop("prod_max", None)
    context.user_data.pop("resultados_busqueda", None)
    context.user_data.pop("resultados_busqueda_sal", None)
    context.user_data.pop("resultados_busqueda_cons", None)

    query = update.callback_query
    if query:
        await query.answer()

    keyboard = [
        [InlineKeyboardButton("🟢 Registrar Entrada De Material", callback_data="op_entrada")],
        [InlineKeyboardButton("🔴 Registrar Salida De Material", callback_data="op_salida")],
        [InlineKeyboardButton("🔍 Consultar Stock De Material", callback_data="op_consulta")],
        [InlineKeyboardButton("🏠 Menú Principal", callback_data="menu_principal")],
        [BOTON_FINALIZAR],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    texto = (
        "📦 *Módulo de Bodega*\n\n"
        "¿Qué movimiento de bodega deseas realizar hoy?:"
    )

    if query:
        await query.message.edit_text(texto, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(texto, reply_markup=reply_markup, parse_mode="Markdown")

    return MENU_BODEGA


# --- MÓDULO CLIENTE (DESARROLLO FUTURO) ---
async def menu_cliente(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer(text="⚠️ Módulo de clientes en construcción.", show_alert=True)
    return MENU_PRINCIPAL


# ==========================================
# FLUJO DE CONSULTA DE STOCK (🔍)
# ==========================================

async def iniciar_consulta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query:
        await query.answer()
        target = query.message.edit_text
    else:
        target = update.message.reply_text

    keyboard = [
        [InlineKeyboardButton("📦 Volver Menú Bodega", callback_data="op_bodega")],
        [BOTON_FINALIZAR],
    ]

    await target(
        "🔍 *Consulta de Stock*\n\n"
        "Por favor, escribe el **código** o el **nombre parcial** del material que deseas consultar:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return BUSCAR_CONSULTA


async def buscar_producto_consulta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    busqueda = update.message.text.strip()
    resultados = buscar_productos_por_nombre_o_codigo(busqueda)

    keyboard_atras = [
        [InlineKeyboardButton("📦 Volver Menú Bodega", callback_data="op_bodega")],
        [BOTON_FINALIZAR]
    ]

    if not resultados:
        await update.message.reply_text(
            f"❌ *No se encontraron materiales coincidentes con* '*{busqueda}*'.\n\n"
            f"Intenta escribiendo nuevamente el código o nombre:",
            reply_markup=InlineKeyboardMarkup(keyboard_atras),
            parse_mode="Markdown",
        )
        return BUSCAR_CONSULTA

    # Guardamos la lista de resultados y el texto ingresado
    context.user_data["resultados_busqueda_cons"] = {}
    context.user_data["busqueda_texto_cons"] = busqueda

    for i, fila in enumerate(resultados[:15]):
        cod, nombre, cant = extraer_datos_producto(fila)
        context.user_data["resultados_busqueda_cons"][str(i)] = (cod, nombre, cant)

    # Caso 1: Solo hay 1 resultado encontrado
    if len(resultados) == 1:
        cod, nombre, cant = context.user_data["resultados_busqueda_cons"]["0"]

        keyboard = [
            [InlineKeyboardButton("🔍 Consultar OTRO material", callback_data="reiniciar_busqueda_cons")],
            [InlineKeyboardButton("📦 Volver Menú Bodega", callback_data="op_bodega")],
            [BOTON_FINALIZAR]
        ]

        await update.message.reply_text(
            f"🔍 *Información del Material:*\n\n"
            f"• *Código:* `{cod}`\n"
            f"• *Nombre:* {nombre}\n"
            f"• *Stock disponible:* *{cant} un.*\n",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )
        return BUSCAR_CONSULTA

    # Caso 2: Múltiples resultados
    keyboard = []
    for i, (cod, nombre, cant) in context.user_data["resultados_busqueda_cons"].items():
        keyboard.append([InlineKeyboardButton(f"🧰 [{cant} un.] {nombre}", callback_data=f"sel_cons_{i}")])

    keyboard.append([InlineKeyboardButton("🔍 Cambiar Búsqueda", callback_data="reiniciar_busqueda_cons")])
    keyboard.append([InlineKeyboardButton("📦 Volver Menú Bodega", callback_data="op_bodega")])
    keyboard.append([BOTON_FINALIZAR])

    msg_extra = f"\n_(Mostrando 15 de {len(resultados)} coincidencias. Sé más específico si no ves el tuyo)_" if len(resultados) > 15 else ""

    await update.message.reply_text(
        f"🔍 *Materiales encontrados para '{busqueda}':*{msg_extra}\n\n"
        f"Selecciona el material correspondiente para consultar su stock:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return SELECCIONAR_PROD_CONSULTA


async def mostrar_detalle_consulta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    indice_str = query.data.replace("sel_cons_", "")
    item = context.user_data.get("resultados_busqueda_cons", {}).get(indice_str)

    if not item:
        await query.message.reply_text("❌ Error al seleccionar el material. Inténtalo de nuevo.")
        return BUSCAR_CONSULTA

    cod, nombre, cant = item
    total_resultados = len(context.user_data.get("resultados_busqueda_cons", {}))

    # Si hay varios productos, mostramos el botón de regresar a la lista de coincidencia
    if total_resultados > 1:
        boton_volver = InlineKeyboardButton("⬅ Volver a Lista de Resultados", callback_data="volver_resultados_cons")
    else:
        boton_volver = InlineKeyboardButton("🔍 Consultar OTRO material", callback_data="reiniciar_busqueda_cons")

    keyboard = [
        [boton_volver],
        [InlineKeyboardButton("🔍 Cambiar Búsqueda", callback_data="reiniciar_busqueda_cons")],
        [InlineKeyboardButton("📦 Volver Menú Bodega", callback_data="op_bodega")],
        [BOTON_FINALIZAR]
    ]

    await query.edit_message_text(
        f"🔍 *Información del Material:*\n\n"
        f"• *Código:* `{cod}`\n"
        f"• *Nombre:* {nombre}\n"
        f"• *Stock disponible:* *{cant} un.*\n",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return SELECCIONAR_PROD_CONSULTA


async def volver_a_lista_resultados_consulta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Regresa a la lista previa de botones de coincidencia de consulta."""
    query = update.callback_query
    await query.answer()

    resultados = context.user_data.get("resultados_busqueda_cons", {})
    busqueda = context.user_data.get("busqueda_texto_cons", "")

    keyboard = []
    for i, (cod, nombre, cant) in resultados.items():
        keyboard.append([InlineKeyboardButton(f"🧰 [{cant} un.] {nombre}", callback_data=f"sel_cons_{i}")])

    keyboard.append([InlineKeyboardButton("🔍 Cambiar Búsqueda", callback_data="reiniciar_busqueda_cons")])
    keyboard.append([InlineKeyboardButton("📦 Volver Menú Bodega", callback_data="op_bodega")])
    keyboard.append([BOTON_FINALIZAR])

    await query.edit_message_text(
        f"🔍 *Materiales encontrados para '{busqueda}':*\n\n"
        f"Selecciona el material correspondiente para consultar su stock:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return SELECCIONAR_PROD_CONSULTA


# --- FLUJO DE ENTRADA (🟢) ---

async def iniciar_entrada(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query:
        await query.answer()
        target = query.message.edit_text
    else:
        target = update.message.reply_text

    if query and query.data == "op_entrada_nueva":
        context.user_data["carrito_entrada"] = []
    elif "carrito_entrada" not in context.user_data:
        context.user_data["carrito_entrada"] = []

    keyboard = []

    # 🟢 Si ya hay materiales en el carrito, mostramos opción de regresar al carrito sin perder nada
    if context.user_data.get("carrito_entrada"):
        keyboard.append([InlineKeyboardButton("⬅️ Volver al Carrito", callback_data="volver_al_carrito")])

    keyboard.append([InlineKeyboardButton("📦 Volver Menú Bodega", callback_data="op_bodega")])
    keyboard.append([BOTON_FINALIZAR])

    await target(
        "🟢 *Registro de Entrada*\n\n"
        "Por favor, escribe el **código** o el **nombre parcial** del material que deseas ingresar:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return BUSCAR_ENTRADA

async def mostrar_resumen_carrito(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    carrito = context.user_data.get("carrito_entrada", [])

    if not carrito:
        return await iniciar_entrada(update, context)

    resumen_texto = "🛒 *Lista de materiales a ingresar:*\n\n"
    for idx, item in enumerate(carrito, 1):
        resumen_texto += f"{idx}. `{item['codigo']}` - {item['nombre']}: *+{item['cantidad']} un.*\n"

    keyboard_post = [
        [InlineKeyboardButton("🟢 Agregar OTRO material", callback_data="op_entrada_otro")],
        [InlineKeyboardButton("✅ CONFIRMAR Y GUARDAR TODO", callback_data="procesar_lote_entrada")],
        [InlineKeyboardButton("📦 Volver Menú Bodega", callback_data="op_bodega")],
        [BOTON_FINALIZAR],
    ]

    await query.edit_message_text(
        f"{resumen_texto}\n"
        f"¿Deseas agregar más materiales o procesar el ingreso definitivo?",
        reply_markup=InlineKeyboardMarkup(keyboard_post),
        parse_mode="Markdown",
    )
    return PREGUNTAR_OTRO

async def regresar_al_carrito(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    resumen_texto = "🛒 *Lista de materiales a ingresar:*\n\n"
    for idx, item in enumerate(context.user_data.get("carrito_entrada", []), 1):
        resumen_texto += f"{idx}. `{item['codigo']}` - {item['nombre']}: *+{item['cantidad']} un.*\n"

    keyboard_post = [
        [InlineKeyboardButton("🟢 Agregar OTRO material", callback_data="op_entrada_otro")],
        [InlineKeyboardButton("✅ CONFIRMAR Y GUARDAR TODO", callback_data="procesar_lote_entrada")],
        [InlineKeyboardButton("📦 Volver Menú Bodega", callback_data="op_bodega")],
        [BOTON_FINALIZAR],
    ]

    await query.edit_message_text(
        f"{resumen_texto}\n"
        f"¿Deseas agregar más materiales o procesar el ingreso definitivo?",
        reply_markup=InlineKeyboardMarkup(keyboard_post),
        parse_mode="Markdown",
    )
    return PREGUNTAR_OTRO


async def buscar_producto_entrada(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    busqueda = update.message.text.strip()
    resultados = buscar_productos_por_nombre_o_codigo(busqueda)

    if not resultados:
        keyboard_atras = [
            [InlineKeyboardButton("⬅️️ Volver a Escribir", callback_data="reiniciar_busqueda_ent")],
            [InlineKeyboardButton("📦 Volver Menú Bodega", callback_data="op_bodega")],
            [BOTON_FINALIZAR]
        ]
        await update.message.reply_text(
            f"❌ *No se encontraron materiales coincidentes con* '*{busqueda}*'.\n\n"
            f"Intenta escribiendo nuevamente el código o nombre:",
            reply_markup=InlineKeyboardMarkup(keyboard_atras),
            parse_mode="Markdown",
        )
        return BUSCAR_ENTRADA

    # Guardamos los resultados en la memoria temporal del usuario
    context.user_data["resultados_busqueda"] = {}
    context.user_data["busqueda_texto"] = busqueda
    
    for i, fila in enumerate(resultados[:15]):
        cod, nombre, cant = extraer_datos_producto(fila)
        context.user_data["resultados_busqueda"][str(i)] = (cod, nombre, cant)

    # Si solo hay 1 coincidencia
    if len(resultados) == 1:
        cod, nombre, cant = context.user_data["resultados_busqueda"]["0"]
        context.user_data["prod_codigo"] = cod
        context.user_data["prod_nombre"] = nombre

        keyboard = [
            [InlineKeyboardButton("⬅️ Nueva Búsqueda", callback_data="reiniciar_busqueda_ent")],
            [InlineKeyboardButton("📦 Volver Menú Bodega", callback_data="op_bodega")],
            [BOTON_FINALIZAR]
        ]

        await update.message.reply_text(
            f"🟢 *Material encontrado:*\n\n"
            f"• *Código:* `{cod}`\n"
            f"• *Nombre:* {nombre}\n"
            f"• *Stock actual:* {cant}\n\n"
            f"Por favor, ingresa la **cantidad a ingresar** (número entero positivo):",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )
        return CANTIDAD_ENTRADA

    # Si hay múltiples coincidencias
    keyboard = []
    for i, (cod, nombre, cant) in context.user_data["resultados_busqueda"].items():
        keyboard.append([InlineKeyboardButton(f"🧰 [{cant} un.] {nombre}", callback_data=f"sel_ent_{i}")])

    keyboard.append([InlineKeyboardButton("⬅️ Nueva Búsqueda", callback_data="reiniciar_busqueda_ent")])
    keyboard.append([InlineKeyboardButton("📦 Volver Menú Bodega", callback_data="op_bodega")])
    keyboard.append([BOTON_FINALIZAR])

    msg_extra = f"\n_(Mostrando 15 de {len(resultados)} coincidencias. Sé más específico si no ves el tuyo)_" if len(resultados) > 15 else ""

    await update.message.reply_text(
        f"🟢 *Materiales encontrados para '{busqueda}':*{msg_extra}\n\n"
        f"Selecciona el material correspondiente:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return SELECCIONAR_PROD_ENTRADA


async def confirmar_seleccion_entrada(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data.startswith("sel_ent_"):
        indice_str = query.data.replace("sel_ent_", "")
        item = context.user_data.get("resultados_busqueda", {}).get(indice_str)

        if not item:
            await query.message.reply_text("❌ Error al seleccionar el material. Inténtalo de nuevo.")
            return BUSCAR_ENTRADA

        cod, nombre, cant = item
        context.user_data["prod_codigo"] = cod
        context.user_data["prod_nombre"] = nombre
    else:
        cod = context.user_data.get("prod_codigo")
        nombre = context.user_data.get("prod_nombre")
        resultados = buscar_productos_por_nombre_o_codigo(cod)
        _, _, cant = extraer_datos_producto(resultados[0]) if resultados else (cod, nombre, 0)

    # Si provenía de una lista de varios resultados, mostramos el botón de volver a la lista
    total_resultados = len(context.user_data.get("resultados_busqueda", {}))
    if total_resultados > 1:
        boton_volver = InlineKeyboardButton("⬅️ Volver a Lista de Resultados", callback_data="volver_resultados_ent")
    else:
        boton_volver = InlineKeyboardButton("⬅️ Nueva Búsqueda", callback_data="reiniciar_busqueda_ent")

    keyboard = [
        [boton_volver],
        [InlineKeyboardButton("📦 Volver Menú Bodega", callback_data="op_bodega")],
        [BOTON_FINALIZAR]
    ]

    await query.edit_message_text(
        f"🟢 *Material Seleccionado:* {nombre}\n\n"
        f"• *Código:* `{cod}`\n"
        f"• *Stock actual:* {cant} un.\n\n"
        f"Por favor, ingresa la **cantidad a ingresar** (número entero positivo):",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return CANTIDAD_ENTRADA


async def volver_a_lista_resultados_entrada(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """NUEVA FUNCIÓN: Regresa a la lista previa de entrada."""
    query = update.callback_query
    await query.answer()

    resultados = context.user_data.get("resultados_busqueda", {})
    busqueda = context.user_data.get("busqueda_texto", "")

    keyboard = []
    for i, (cod, nombre, cant) in resultados.items():
        keyboard.append([InlineKeyboardButton(f"🧰 [{cant} un.] {nombre}", callback_data=f"sel_ent_{i}")])

    keyboard.append([InlineKeyboardButton("⬅️ Nueva Búsqueda", callback_data="reiniciar_busqueda_ent")])
    keyboard.append([InlineKeyboardButton("📦 Volver Menú Bodega", callback_data="op_bodega")])
    keyboard.append([BOTON_FINALIZAR])

    await query.edit_message_text(
        f"🟢 *Materiales encontrados para '{busqueda}':*\n\n"
        f"Selecciona el material correspondiente:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return SELECCIONAR_PROD_ENTRADA


async def guardar_cantidad_entrada(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    texto = update.message.text.strip()
    keyboard_error = [
        [InlineKeyboardButton("📦 Volver Menú Bodega", callback_data="op_bodega")],
    ]

    if not texto.isdigit() or int(texto) <= 0:
        await update.message.reply_text(
            "❌ Por favor ingresa un número entero positivo válido.",
            reply_markup=InlineKeyboardMarkup(keyboard_error),
        )
        return CANTIDAD_ENTRADA

    cantidad = int(texto)
    cod = context.user_data["prod_codigo"]
    nombre = context.user_data["prod_nombre"]

    if "carrito_entrada" not in context.user_data:
        context.user_data["carrito_entrada"] = []

    # Verificar si el código ya existe en el carrito para no crear otro ítem
    encontrado = False
    for item in context.user_data["carrito_entrada"]:
        if item["codigo"] == cod:
            item["cantidad"] += cantidad
            encontrado = True
            break

    if not encontrado:
        context.user_data["carrito_entrada"].append({
            "codigo": cod,
            "nombre": nombre,
            "cantidad": cantidad
        })

    resumen_texto = "🛒 *Lista de materiales a ingresar:*\n\n"
    for idx, item in enumerate(context.user_data["carrito_entrada"], 1):
        resumen_texto += f"{idx}. `{item['codigo']}` - {item['nombre']}: *+{item['cantidad']} un.*\n"

    keyboard_post = [
        [InlineKeyboardButton("🟢 Agregar OTRO material", callback_data="op_entrada_otro")],
        [InlineKeyboardButton("✅ CONFIRMAR Y GUARDAR TODO", callback_data="procesar_lote_entrada")],
        [InlineKeyboardButton("📦 Volver Menú Bodega", callback_data="op_bodega")],
        [BOTON_FINALIZAR],
    ]

    await update.message.reply_text(
        f"✅ *Material agregado a la lista temporal.*\n\n"
        f"{resumen_texto}\n"
        f"¿Deseas agregar más materiales o procesar el ingreso definitivo?",
        reply_markup=InlineKeyboardMarkup(keyboard_post),
        parse_mode="Markdown",
    )
    return PREGUNTAR_OTRO


async def procesar_lote_entrada(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    # Extraer el carrito y datos del usuario
    carrito = context.user_data.pop("carrito_entrada", [])
    cedula_usuario = context.user_data.get("cedula_usuario", "")
    nombre_usuario = context.user_data.get("nombre_usuario", "")

    if not carrito:
        await query.edit_message_text("⚠️ No hay materiales acumulados para registrar.", reply_markup=None)
        return ConversationHandler.END

    # Guardar todo el lote en la base de datos SQL
    exito = registrar_lote_movimientos(
        carrito=carrito,
        tipo="ENTRADA",
        cedula_usuario=cedula_usuario,
        nombre_usuario=nombre_usuario
    )

    if not exito:
        await query.edit_message_text("❌ Hubo un error al registrar la entrada en la base de datos.", reply_markup=None)
        return ConversationHandler.END

    # Construir resumen para mostrar en Telegram
    resumen_final = f"🟢 *¡Entrada registrada con éxito!*\n👤 *Usuario:* {nombre_usuario}\n\n"
    for item in carrito:
        resumen_final += f"• `{item['codigo']}` | {item['nombre']}: *+{item['cantidad']} un.*\n"

    # Mostrar resumen al usuario
    await query.edit_message_text(
        resumen_final + "\n\n🔒 *Sesión cerrada automáticamente.*",
        reply_markup=None,
        parse_mode="Markdown"
    )

    # Notificar al grupo de Telegram si está configurado
    if CHAT_ID_GRUPO:
        await context.bot.send_message(
            chat_id=CHAT_ID_GRUPO,
            text=resumen_final,
            parse_mode="Markdown",
        )

    # 1. Borra TODOS los datos almacenados
    context.user_data.clear()

    # 2. Termina formalmente la conversación
    return ConversationHandler.END


# --- FLUJO DE SALIDA (🔴) ---

async def preguntar_empresa_salida(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Paso 1: Pregunta para cuál empresa (LINEA o LIBERTY) es la salida."""
    query = update.callback_query
    if query:
        await query.answer()
        target = query.message.edit_text
    else:
        target = update.message.reply_text

    if query and query.data in ["op_salida", "op_salida_nueva"]:
        context.user_data["carrito_salida"] = []
        context.user_data.pop("empresa_salida", None)
    elif "carrito_salida" not in context.user_data:
        context.user_data["carrito_salida"] = []

    keyboard = [
        [
            InlineKeyboardButton("🌐 LINEA", callback_data="empresa_LINEA"),
            InlineKeyboardButton("⚡ LIBERTY", callback_data="empresa_LIBERTY"),
        ],
        [InlineKeyboardButton("📦 Volver Menú Bodega", callback_data="op_bodega")],
        [BOTON_FINALIZAR],
    ]

    await target(
        "🔴 *Registro de Salida*\n\n"
        "¿A quién se le entregará el material?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return SELECCIONAR_EMPRESA_SALIDA


async def guardar_empresa_y_pedir_producto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    empresa = query.data.replace("empresa_", "")
    context.user_data["empresa_salida"] = empresa

    keyboard = []
    if context.user_data.get("carrito_salida"):
        keyboard.append([InlineKeyboardButton("⬅️ Volver al Carrito", callback_data="volver_al_carrito_sal")])

    keyboard.append([InlineKeyboardButton("📦 Volver Menú Bodega", callback_data="op_bodega")])
    keyboard.append([BOTON_FINALIZAR])

    await query.edit_message_text(
        f"🔴 *Registro de Salida — Empresa: {empresa}*\n\n"
        "Por favor, escribe el **código** o el **nombre parcial** del material que deseas retirar:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return BUSCAR_SALIDA


async def regresar_al_carrito_salida(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    empresa = context.user_data.get("empresa_salida", "N/A")
    resumen_texto = f"🛒 *Lista de materiales a retirar (Empresa: {empresa}):*\n\n"
    for idx, item in enumerate(context.user_data.get("carrito_salida", []), 1):
        resumen_texto += f"{idx}. `{item['codigo']}` - {item['nombre']}: *- {item['cantidad']} un.*\n"

    keyboard_post = [
        [InlineKeyboardButton("🔴 Agregar OTRO material", callback_data="op_salida_otro")],
        [InlineKeyboardButton("✅ CONFIRMAR Y GUARDAR SALIDA", callback_data="procesar_lote_salida")],
        [InlineKeyboardButton("📦 Volver Menú Bodega", callback_data="op_bodega")],
        [BOTON_FINALIZAR],
    ]

    await query.edit_message_text(
        f"{resumen_texto}\n"
        f"¿Deseas agregar más materiales o procesar el retiro definitivo?",
        reply_markup=InlineKeyboardMarkup(keyboard_post),
        parse_mode="Markdown",
    )
    return PREGUNTAR_OTRO


async def iniciar_busqueda_directa_salida(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query:
        await query.answer()

    empresa = context.user_data.get("empresa_salida", "N/A")

    keyboard = []
    if context.user_data.get("carrito_salida"):
        keyboard.append([InlineKeyboardButton("⬅️ Volver al Carrito", callback_data="volver_al_carrito_sal")])

    keyboard.append([InlineKeyboardButton("📦 Volver Menú Bodega", callback_data="op_bodega")])
    keyboard.append([BOTON_FINALIZAR])

    target = query.edit_message_text if query else update.message.reply_text

    await target(
        f"🔴 *Registro de Salida — Empresa: {empresa}*\n\n"
        "Por favor, escribe el **código** o el **nombre parcial** del material que deseas retirar:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return BUSCAR_SALIDA


async def buscar_producto_salida(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    texto = update.message.text.strip()
    resultados = buscar_productos_por_nombre_o_codigo(texto)

    keyboard_atras = [
        [InlineKeyboardButton("⬅️ Volver / Nueva Búsqueda", callback_data="reiniciar_busqueda_sal")],
        [InlineKeyboardButton("📦 Volver Menú Bodega", callback_data="op_bodega")],
        [BOTON_FINALIZAR],
    ]

    if not resultados:
        await update.message.reply_text(
            f"❌ *No se encontraron materiales coincidentes con* '*{texto}*'.\n\n"
            f"Escribe otro código o nombre de material:",
            reply_markup=InlineKeyboardMarkup(keyboard_atras),
            parse_mode="Markdown",
        )
        return BUSCAR_SALIDA

    context.user_data["resultados_busqueda_sal"] = {}
    context.user_data["busqueda_texto_sal"] = texto

    for i, fila in enumerate(resultados[:15]):
        cod, nombre, cant = extraer_datos_producto(fila)
        context.user_data["resultados_busqueda_sal"][str(i)] = (cod, nombre, cant)

    if len(resultados) == 1:
        cod, nombre, cantidad_actual = context.user_data["resultados_busqueda_sal"]["0"]

        if cantidad_actual <= 0:
            keyboard_sin_stock = [
                [InlineKeyboardButton("🔍 Buscar Otro Material", callback_data="reiniciar_busqueda_sal")],
                [InlineKeyboardButton("📦 Volver Menú Bodega", callback_data="op_bodega")],
                [BOTON_FINALIZAR]
            ]
            await update.message.reply_text(
                f"⚠️ *Sin Stock Disponible*\n\n"
                f"• *Material:* {nombre}\n"
                f"• *Código:* `{cod}`\n"
                f"• *Stock actual:* *0 un.*\n\n"
                f"No es posible registrar salidas de este material.\n"
                f"Por favor, selecciona una opción:",
                reply_markup=InlineKeyboardMarkup(keyboard_sin_stock),
                parse_mode="Markdown",
            )
            return SIN_STOCK_SALIDA

        context.user_data["prod_codigo"] = cod
        context.user_data["prod_nombre"] = nombre
        context.user_data["prod_max"] = cantidad_actual

        keyboard = [
            [InlineKeyboardButton("⬅️ Nueva Búsqueda", callback_data="reiniciar_busqueda_sal")],
            [InlineKeyboardButton("📦 Volver Menú Bodega", callback_data="op_bodega")],
            [BOTON_FINALIZAR]
        ]
        await update.message.reply_text(
            f"🔴 *Material encontrado:*\n\n"
            f"• *Material:* {nombre}\n"
            f"• *Código:* `{cod}`\n"
            f"• *Stock Disponible:* {cantidad_actual} un.\n\n"
            f"Por favor, ingresa la **cantidad a retirar** (número entero positivo):",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )
        return CANTIDAD_SALIDA

    keyboard = []
    for i, (cod, nombre, cant) in context.user_data["resultados_busqueda_sal"].items():
        keyboard.append([InlineKeyboardButton(f"🧰 [{cant} un.] {nombre}", callback_data=f"sel_sal_{i}")])

    keyboard.append([InlineKeyboardButton("⬅️ Nueva Búsqueda", callback_data="reiniciar_busqueda_sal")])
    keyboard.append([InlineKeyboardButton("📦 Volver Menú Bodega", callback_data="op_bodega")])
    keyboard.append([BOTON_FINALIZAR])

    msg_extra = f"\n_(Mostrando 15 de {len(resultados)} coincidencias. Sé más específico si no ves el tuyo)_" if len(resultados) > 15 else ""

    await update.message.reply_text(
        f"🔴 *Materiales encontrados para '{texto}':*{msg_extra}\n\n"
        f"Selecciona el material correspondiente:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return SELECCIONAR_PROD_SALIDA


async def confirmar_seleccion_salida(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data.startswith("sel_sal_"):
        indice_str = query.data.replace("sel_sal_", "")
        item = context.user_data.get("resultados_busqueda_sal", {}).get(indice_str)

        if not item:
            await query.message.reply_text("❌ Error al seleccionar el material. Inténtalo de nuevo.")
            return BUSCAR_SALIDA

        cod, nombre, cant = item
    else:
        cod = context.user_data.get("prod_codigo")
        nombre = context.user_data.get("prod_nombre")
        cant = context.user_data.get("prod_max", 0)

    total_resultados = len(context.user_data.get("resultados_busqueda_sal", {}))
    if total_resultados > 1:
        boton_volver = InlineKeyboardButton("⬅️️ Volver a Lista de Resultados", callback_data="volver_resultados_sal")
    else:
        boton_volver = InlineKeyboardButton("🔍 Buscar Otro Material", callback_data="reiniciar_busqueda_sal")

    if cant <= 0:
        keyboard = [
            [boton_volver],
            [InlineKeyboardButton("🔍 Buscar Otro Material", callback_data="reiniciar_busqueda_sal")],
            [InlineKeyboardButton("📦 Volver Menú Bodega", callback_data="op_bodega")],
            [BOTON_FINALIZAR]
        ]

        await query.edit_message_text(
            f"⚠️ *Sin Stock Disponible*\n\n"
            f"• *Código:* `{cod}`\n"
            f"• *Nombre:* {nombre}\n"
            f"• *Stock actual:* *0 un.*\n\n"
            f"No es posible registrar salidas de un material sin stock. Selecciona una opción:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )
        return SIN_STOCK_SALIDA

    context.user_data["prod_codigo"] = cod
    context.user_data["prod_nombre"] = nombre
    context.user_data["prod_max"] = cant

    keyboard = [
        [boton_volver],
        [InlineKeyboardButton("📦 Volver Menú Bodega", callback_data="op_bodega")],
        [BOTON_FINALIZAR]
    ]

    await query.edit_message_text(
        f"🔴 *Material Seleccionado:* {nombre}\n\n"
        f"• *Código:* `{cod}`\n"
        f"• *Stock disponible:* {cant} un.\n\n"
        f"Por favor, ingresa la **cantidad a retirar** (número entero positivo):",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return CANTIDAD_SALIDA

async def volver_a_lista_resultados_salida(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """NUEVA FUNCIÓN: Regresa a la lista previa de salida."""
    query = update.callback_query
    await query.answer()

    resultados = context.user_data.get("resultados_busqueda_sal", {})
    busqueda = context.user_data.get("busqueda_texto_sal", "")

    keyboard = []
    for i, (cod, nombre, cant) in resultados.items():
        keyboard.append([InlineKeyboardButton(f"🧰 [{cant} un.] {nombre}", callback_data=f"sel_sal_{i}")])

    keyboard.append([InlineKeyboardButton("⬅️ Nueva Búsqueda", callback_data="reiniciar_busqueda_sal")])
    keyboard.append([InlineKeyboardButton("📦 Volver Menú Bodega", callback_data="op_bodega")])
    keyboard.append([BOTON_FINALIZAR])

    await query.edit_message_text(
        f"🔴 *Materiales encontrados para '{busqueda}':*\n\n"
        f"Selecciona el material correspondiente:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return SELECCIONAR_PROD_SALIDA


async def forzar_boton_sin_stock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Intercepta cualquier texto que envíe el usuario estando sin stock y lo fuerza a usar un botón."""
    keyboard_sin_stock = [
        [InlineKeyboardButton("⬅️ Volver / Cambiar Material", callback_data="reiniciar_busqueda_sal")],
        [InlineKeyboardButton("📦 Volver Menú Bodega", callback_data="op_bodega")],
        [BOTON_FINALIZAR]
    ]
    await update.message.reply_text(
        "⚠️ *Opción inválida por texto.*\n\n"
        "El material no tiene stock. Debes presionar uno de los siguientes botones para continuar:",
        reply_markup=InlineKeyboardMarkup(keyboard_sin_stock),
        parse_mode="Markdown",
    )
    return SIN_STOCK_SALIDA


async def guardar_cantidad_salida(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    texto = update.message.text.strip()
    max_disp = context.user_data.get("prod_max", 0)

    keyboard_error = [
        [InlineKeyboardButton("📦 Volver Menú Bodega", callback_data="op_bodega")],
    ]

    if not texto.isdigit() or int(texto) <= 0:
        await update.message.reply_text(
            "❌ Por favor ingresa un número entero positivo válido.",
            reply_markup=InlineKeyboardMarkup(keyboard_error),
        )
        return CANTIDAD_SALIDA

    cantidad = int(texto)
    if cantidad > max_disp:
        await update.message.reply_text(
            f"⚠️ La cantidad supera el stock disponible ({max_disp} un.). Ingresa una cantidad menor:",
            reply_markup=InlineKeyboardMarkup(keyboard_error),
        )
        return CANTIDAD_SALIDA

    cod = context.user_data["prod_codigo"]
    nombre = context.user_data["prod_nombre"]

    if "carrito_salida" not in context.user_data:
        context.user_data["carrito_salida"] = []

    context.user_data["carrito_salida"].append({
        "codigo": cod,
        "nombre": nombre,
        "cantidad": cantidad
    })

    empresa = context.user_data.get("empresa_salida", "N/A")
    resumen_texto = f"🛒 *Lista de materiales a retirar (Empresa: {empresa}):*\n\n"
    for idx, item in enumerate(context.user_data["carrito_salida"], 1):
        resumen_texto += f"{idx}. `{item['codigo']}` - {item['nombre']}: *- {item['cantidad']} un.*\n"

    keyboard_post = [
        [InlineKeyboardButton("🔴 Agregar OTRO material", callback_data="op_salida_otro")],
        [InlineKeyboardButton("✅ CONFIRMAR Y GUARDAR SALIDA", callback_data="procesar_lote_salida")],
        [InlineKeyboardButton("📦 Volver Menú Bodega", callback_data="op_bodega")],
        [BOTON_FINALIZAR],
    ]

    await update.message.reply_text(
        f"✅ *Material agregado a la lista temporal.*\n\n"
        f"{resumen_texto}\n"
        f"¿Deseas agregar más materiales o procesar el retiro definitivo?",
        reply_markup=InlineKeyboardMarkup(keyboard_post),
        parse_mode="Markdown",
    )
    return PREGUNTAR_OTRO


async def procesar_lote_salida(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    # Extraer el carrito y datos de la sesión
    carrito = context.user_data.pop("carrito_salida", [])
    empresa = context.user_data.get("empresa_salida", "DESCONOCIDA")
    cedula_usuario = context.user_data.get("cedula_usuario", "")
    nombre_usuario = context.user_data.get("nombre_usuario", "")

    if not carrito:
        await query.edit_message_text(
            "⚠️ No hay materiales acumulados para retirar.",
            reply_markup=None,
        )
        return ConversationHandler.END

    # Guardar todo el lote en la base de datos SQL
    exito = registrar_lote_movimientos(
        carrito=carrito,
        tipo="SALIDA",
        cedula_usuario=cedula_usuario,
        nombre_usuario=nombre_usuario,
        contratista=empresa
    )

    if not exito:
        await query.edit_message_text(
            "❌ Hubo un error al registrar la salida en la base de datos.",
            reply_markup=None
        )
        return ConversationHandler.END

    # Construir resumen para mostrar en Telegram
    resumen_final = (
        f"🔴 *¡Salida registrada con éxito!*\n"
        f"👤 *Usuario:* {nombre_usuario}\n"
        f"🏢 *Despachado a:* {empresa}\n\n"
    )

    for item in carrito:
        resumen_final += f"• `{item['codigo']}` | {item['nombre']}: *-{item['cantidad']} un.*\n"

    # Mostrar resumen al usuario
    await query.edit_message_text(
        resumen_final + "\n\n🔒 *Sesión cerrada automáticamente.*",
        reply_markup=None,
        parse_mode="Markdown"
    )

    # Notificar al grupo de Telegram
    if CHAT_ID_GRUPO:
        await context.bot.send_message(
            chat_id=CHAT_ID_GRUPO,
            text=resumen_final,
            parse_mode="Markdown",
        )

    # Limpiar sesión de usuario
    context.user_data.clear()
    return ConversationHandler.END


async def finalizar_sesion_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()

    query = update.callback_query
    texto_final = "👋 *Sesión finalizada correctamente.* ¡Hasta pronto!"

    if query:
        await query.answer()
        await query.edit_message_text(texto_final, reply_markup=None, parse_mode="Markdown")
    else:
        await update.message.reply_text(texto_final, reply_markup=None, parse_mode="Markdown")

    return ConversationHandler.END


# Forzar a httpx a no verificar SSL globalmente en toda la ejecución
_original_init = httpx.AsyncClient.__init__
def _unverified_init(self, *args, **kwargs):
    kwargs["verify"] = False
    _original_init(self, *args, **kwargs)

httpx.AsyncClient.__init__ = _unverified_init


# --- CONFIGURACIÓN Y HANDLERS ---
def main():
    # Desactivar verificación SSL de Python
    ssl._create_default_https_context = ssl._create_unverified_context

    app = (
        ApplicationBuilder()
        .token(TELEGRAM_TOKEN)
        .read_timeout(30)
        .write_timeout(30)
        .connect_timeout(30)
        .pool_timeout(30)
        .build()
    )

  # Handlers de navegación que deben responder en cualquier estado de la bodega
    nav_handlers = [
        CallbackQueryHandler(menu_bodega, pattern="^op_bodega$"),
        CallbackQueryHandler(start, pattern="^menu_principal$"),
    ]

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex(r"(?i)^hola$"), start),
        ],
        states={
            SOLICITAR_CEDULA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, validar_cedula),
            ],
            MENU_PRINCIPAL: [
                CallbackQueryHandler(menu_bodega, pattern="^op_bodega$"),
                CallbackQueryHandler(menu_cliente, pattern="^op_cliente$"),
            ],
            MENU_BODEGA: [
                CallbackQueryHandler(iniciar_entrada, pattern="^(op_entrada|op_entrada_nueva)$"),
                CallbackQueryHandler(preguntar_empresa_salida, pattern="^(op_salida|op_salida_nueva)$"),
                CallbackQueryHandler(iniciar_consulta, pattern="^op_consulta$"),
                CallbackQueryHandler(start, pattern="^menu_principal$"),
            ],
            BUSCAR_CONSULTA: [
                *nav_handlers,
                MessageHandler(filters.TEXT & ~filters.COMMAND, buscar_producto_consulta),
                CallbackQueryHandler(iniciar_consulta, pattern="^reiniciar_busqueda_cons$"),
            ],
            SELECCIONAR_PROD_CONSULTA: [
                *nav_handlers,
                CallbackQueryHandler(mostrar_detalle_consulta, pattern="^sel_cons_.*"),
                CallbackQueryHandler(volver_a_lista_resultados_consulta, pattern="^volver_resultados_cons$"),
                CallbackQueryHandler(iniciar_consulta, pattern="^reiniciar_busqueda_cons$"),
    ],
            BUSCAR_ENTRADA: [
                *nav_handlers,
                MessageHandler(filters.TEXT & ~filters.COMMAND, buscar_producto_entrada),
                CallbackQueryHandler(iniciar_entrada, pattern="^reiniciar_busqueda_ent$"),
                CallbackQueryHandler(regresar_al_carrito, pattern="^volver_al_carrito$"),
            ],
            CONFIRMAR_PROD_ENTRADA: [
                *nav_handlers,
                CallbackQueryHandler(confirmar_seleccion_entrada, pattern="^confirmar_prod_ent$"),
                CallbackQueryHandler(iniciar_entrada, pattern="^reiniciar_busqueda_ent$"),
            ],
            SELECCIONAR_PROD_ENTRADA: [
                *nav_handlers,
                CallbackQueryHandler(confirmar_seleccion_entrada, pattern="^sel_ent_"),
                CallbackQueryHandler(iniciar_entrada, pattern="^reiniciar_busqueda_ent$"),
            ],
            CANTIDAD_ENTRADA: [
                *nav_handlers,
                MessageHandler(filters.TEXT & ~filters.COMMAND, guardar_cantidad_entrada),
                CallbackQueryHandler(iniciar_entrada, pattern="^reiniciar_busqueda_ent$"),
                CallbackQueryHandler(volver_a_lista_resultados_entrada, pattern="^volver_resultados_ent$"),
                CallbackQueryHandler(volver_a_lista_resultados_salida, pattern="^volver_resultados_sal$"),
            ],
            SELECCIONAR_EMPRESA_SALIDA: [
                *nav_handlers,
                CallbackQueryHandler(guardar_empresa_y_pedir_producto, pattern="^empresa_(LINEA|LIBERTY)$"),
            ],
            BUSCAR_SALIDA: [
                *nav_handlers,
                MessageHandler(filters.TEXT & ~filters.COMMAND, buscar_producto_salida),
                CallbackQueryHandler(iniciar_busqueda_directa_salida, pattern="^reiniciar_busqueda_sal$"),
                CallbackQueryHandler(regresar_al_carrito_salida, pattern="^volver_al_carrito_sal$"),
            ],
            CONFIRMAR_PROD_SALIDA: [
                *nav_handlers,
                CallbackQueryHandler(confirmar_seleccion_salida, pattern="^confirmar_prod_sal$"),
                CallbackQueryHandler(iniciar_busqueda_directa_salida, pattern="^reiniciar_busqueda_sal$"),
            ],
            SELECCIONAR_PROD_SALIDA: [
                *nav_handlers,
                CallbackQueryHandler(confirmar_seleccion_salida, pattern="^sel_sal_"),
                CallbackQueryHandler(iniciar_busqueda_directa_salida, pattern="^reiniciar_busqueda_sal$"),
            ],
            CANTIDAD_SALIDA: [
                *nav_handlers,
                MessageHandler(filters.TEXT & ~filters.COMMAND, guardar_cantidad_salida),
                CallbackQueryHandler(iniciar_busqueda_directa_salida, pattern="^reiniciar_busqueda_sal$"),
                CallbackQueryHandler(volver_a_lista_resultados_entrada, pattern="^volver_resultados_ent$"),
                CallbackQueryHandler(volver_a_lista_resultados_salida, pattern="^volver_resultados_sal$"),
            ],
            
            # 🔴 NUEVO ESTADO: Control de Sin Stock en Salida
            SIN_STOCK_SALIDA: [
                *nav_handlers,
                CallbackQueryHandler(iniciar_busqueda_directa_salida, pattern="^reiniciar_busqueda_sal$"),
                CallbackQueryHandler(volver_a_lista_resultados_salida, pattern="^volver_resultados_sal$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, forzar_boton_sin_stock),
            ],

            PREGUNTAR_OTRO: [
                *nav_handlers,
                CallbackQueryHandler(iniciar_entrada, pattern="^op_entrada_otro$"),
                CallbackQueryHandler(iniciar_busqueda_directa_salida, pattern="^op_salida_otro$"),
                CallbackQueryHandler(procesar_lote_entrada, pattern="^procesar_lote_entrada$"),
                CallbackQueryHandler(procesar_lote_salida, pattern="^procesar_lote_salida$"),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(finalizar_sesion_manual, pattern="^finalizar_sesion$"),
            CommandHandler("cancelar", finalizar_sesion_manual),
            MessageHandler(filters.Regex(r"(?i)^finalizar sesión$"), finalizar_sesion_manual),
        ]
    )

    app.add_handler(conv_handler)

    print("🤖 Bot de Bodega iniciado correctamente...")
    app.run_polling()


if __name__ == "__main__":
    try:
        print("🔄 Sincronizando datos desde Google Sheets antes de iniciar...")
        cargar_usuarios_desde_googlesheets()
        cargar_desde_existencia_bodega()
        
        main()
    except (KeyboardInterrupt, SystemExit):
        pass