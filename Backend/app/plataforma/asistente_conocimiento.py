"""Catálogo de opciones del Sistema de Cotización y respuestas del asistente."""
from __future__ import annotations

import re
import unicodedata

_TODOS = ("admin", "analista", "tecnico", "auditor")
_ADMIN = ("admin",)
_ADMIN_AUDITOR = ("admin", "auditor")
_ADMIN_AUDITOR_NOC = ("admin", "auditor", "TECNICO_NOC_SOC")
_ESCRITURA = ("admin", "analista")

GRUPOS = {
    "comercial": "Ciclo comercial",
    "catalogo": "Fichas",
    "admin": "Administración",
}

OPCIONES = (
    {
        "id": "panel", "paso": 1, "destino": "panel", "etiqueta": "Panel",
        "grupo": "comercial", "roles": _TODOS,
        "keywords": ("panel", "inicio", "kpi", "resumen", "tablero", "mcp"),
        "ayuda": (
            "En Panel (01) ves ofertas abiertas y ganadas, clientes, productos, "
            "informes y si el MCP está enlazado. El SBC único se elige en Generales (16)."
        ),
    },
    {
        "id": "ofertas", "paso": 2, "destino": "ofertas", "etiqueta": "Ofertas",
        "grupo": "comercial", "roles": _TODOS,
        "keywords": ("oferta", "cotizacion", "cotización", "partida", "margen", "borrador",
                     "ganada", "perdida", "traspaso", "sbc", "gemini", "ocr", "proveedor",
                     "onlyoffice", "word", "excel"),
        "ayuda": (
            "En Ofertas (02) creas la cotización: cliente (o inscribes uno nuevo en 05), "
            "margen, partidas (también desde el catálogo 06), anexos PDF/audio/WhatsApp "
            "para que Gemini arme partidas e informe. Si OnlyOffice está en Generales (16), "
            "«Abrir» edita Word, Excel, PowerPoint o PDF sin salir. Al ganar se pide serial si el "
            "producto lo requiere y se envía al SBC único de Generales (16) por el MCP. "
            "Un borrador se puede eliminar si el proceso no avanza."
        ),
    },
    {
        "id": "informes", "paso": 3, "destino": "informes", "etiqueta": "Informes",
        "grupo": "comercial", "roles": _TODOS,
        "keywords": ("informe", "tecnico", "técnico", "campo", "levantamiento", "audio", "whatsapp"),
        "ayuda": (
            "En Informes (03) queda el levantamiento de campo. Gemini lee PDF, audio "
            "y chat de WhatsApp y redacta el informe técnico más la oferta comercial."
        ),
    },
    {
        "id": "reportes", "paso": 4, "destino": "reportes", "etiqueta": "Reportes",
        "grupo": "comercial", "roles": _TODOS,
        "keywords": ("reporte", "imprimir", "pdf", "oferta comercial", "informe", "word", "excel", "onlyoffice"),
        "ayuda": (
            "En Reportes (04) imprimes la oferta comercial y el informe técnico. "
            "Si el informe es Word o Excel, «Abrir» lo edita en OnlyOffice (configurado en 16). "
            "Un informe técnico se puede eliminar."
        ),
    },
    {
        "id": "clientes", "paso": 5, "destino": "clientes", "etiqueta": "Clientes",
        "grupo": "catalogo", "roles": _TODOS,
        "keywords": ("cliente", "rif", "razon social", "razón social", "inscribir"),
        "ayuda": (
            "En Clientes (05) está la ficha fiscal. El RIF viaja en el traspaso para "
            "que el SBC reconozca al cliente. Desde nueva oferta puedes inscribir uno nuevo."
        ),
    },
    {
        "id": "productos", "paso": 6, "destino": "productos", "etiqueta": "Productos y servicios",
        "grupo": "catalogo", "roles": _TODOS,
        "keywords": ("producto", "servicio", "catalogo", "catálogo", "serial", "garantia",
                     "garantía", "entrega", "top 10"),
        "ayuda": (
            "En Productos y servicios (06) el catálogo cotizable: código, si requiere serial, "
            "garantía y entrega en semanas. Se buscan desde las partidas. Al ganar la venta "
            "se pide el serial. Las estadísticas muestran los 10 más cotizados, a quién, cuándo y el monto."
        ),
    },
    {
        "id": "proveedores", "paso": 7, "destino": "proveedores", "etiqueta": "Proveedores",
        "grupo": "catalogo", "roles": _TODOS,
        "keywords": ("proveedor", "oferta proveedor"),
        "ayuda": "En Proveedores (07) el catálogo de quienes envían ofertas que cargas en la cotización.",
    },
    {
        "id": "contactos", "paso": 8, "destino": "contactos", "etiqueta": "Contactos",
        "grupo": "catalogo", "roles": _TODOS,
        "keywords": ("contacto", "persona"),
        "ayuda": "En Contactos (08) las personas del cliente u organismo. Se pueden vincular a una ficha.",
    },
    {
        "id": "tareas", "paso": 9, "destino": "tareas", "etiqueta": "Tareas",
        "grupo": "catalogo", "roles": _TODOS,
        "keywords": ("tarea", "pendiente", "visita", "negociacion", "negociación"),
        "ayuda": "En Tareas (09) los pendientes comerciales del escenario: visita, envío, negociación.",
    },
    {
        "id": "documentos", "paso": 10, "destino": "documentos", "etiqueta": "Documentos",
        "grupo": "catalogo", "roles": _TODOS,
        "keywords": ("documento", "pliego", "plano", "anexo", "url"),
        "ayuda": (
            "En Documentos (10) referencias a pliegos, planos o anexos (URL o nota). "
            "Los archivos de la oferta se abren con OnlyOffice desde Ofertas (02). "
            "El archivo de obra se guarda en Control de Proyecto."
        ),
    },
    {
        "id": "usuarios", "paso": 11, "destino": "usuarios", "etiqueta": "Usuarios",
        "grupo": "admin", "roles": _ADMIN,
        "keywords": ("usuario", "cuenta", "clave", "2fa", "telegram"),
        "ayuda": (
            "En Usuarios (11) las cuentas de ESTA instancia (no se comparten con Control de Proyecto). "
            "El emparejamiento de Telegram se hace con el botón de la barra, no pegando el chat a mano."
        ),
    },
    {
        "id": "auditoria", "paso": 12, "destino": "auditoria", "etiqueta": "Auditoría",
        "grupo": "admin", "roles": _ADMIN_AUDITOR_NOC,
        "keywords": ("auditoria", "auditoría", "bitacora", "bitácora", "actividad"),
        "ayuda": (
            "En Auditoría (12) lo que hacen las personas: login, ofertas, fichas y administración. "
            "Los fallos de MCP, Telegram o disco van a Eventos (13)."
        ),
    },
    {
        "id": "eventos", "paso": 13, "destino": "eventos", "etiqueta": "Eventos",
        "grupo": "admin", "roles": _ADMIN_AUDITOR_NOC,
        "keywords": ("evento", "eventos", "error", "mcp", "umbral", "bloqueo", "sistema",
                     "visor", "disco"),
        "ayuda": (
            "En Eventos (13) el visor de sucesos de esta instancia: errores de MCP, bloqueos, "
            "Telegram vinculados y uso de disco. No es la bitácora de personas (eso es Auditoría 12)."
        ),
    },
    {
        "id": "respaldo", "paso": 14, "destino": "respaldo", "etiqueta": "Respaldo",
        "grupo": "admin", "roles": _ADMIN_AUDITOR,
        "keywords": ("respaldo", "backup", "restaurar", "zip", "sql", "restaurar cotizacion"),
        "ayuda": (
            "En Respaldo (14) el administrador genera un ZIP de datos (SQL + anexos) o de la "
            "aplicación (HTML y código, sin .env ni claves). El auditor puede listar y descargar. "
            "Restaurar datos pide exactamente la frase «restaurar cotizacion»."
        ),
    },
    {
        "id": "escenarios", "paso": 15, "destino": "escenarios", "etiqueta": "Escenarios",
        "grupo": "admin", "roles": _ADMIN,
        "keywords": ("escenario", "escenarios", "periodo", "período", "razon social", "sbc"),
        "ayuda": (
            "En Escenarios (15) los periodos de contratación salen del SBC que el "
            "administrador eligió en Generales (16). No se crean periodos aquí: se "
            "espejan los del nodo (razón social + vigencia). El administrador asigna "
            "usuarios y marca el escenario por defecto para el login."
        ),
    },
    {
        "id": "generales", "paso": 16, "destino": "generales", "etiqueta": "Generales",
        "grupo": "admin", "roles": _ADMIN,
        "keywords": ("generales", "margen", "gemini", "mcp", "sbc", "iva", "telegram", "bot", "token",
                     "onlyoffice", "office", "word", "excel", "empresa"),
        "ayuda": (
            "En Generales (16) hay cinco bloques que se guardan por separado: Empresa (IVA y margen), "
            "Gemini, MCP y el único SBC (de ahí salen los escenarios 15), Telegram (@BotFather) "
            "y OnlyOffice (Document Server del NUC, URL de esta API en :8100 y JWT). "
            "El token y el JWT no se vuelven a mostrar."
        ),
    },
)


def _sin_acentos(texto: str) -> str:
    nfd = unicodedata.normalize("NFD", texto or "")
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn").lower()


def opciones_para_rol(rol: str) -> list[dict]:
    return [dict(o) for o in OPCIONES if rol in o["roles"]]


def rango_menu(visibles: list[dict] | None = None, rol: str | None = None) -> str:
    ops = visibles if visibles is not None else opciones_para_rol(rol or "admin")
    if not ops:
        return "01 Panel al 16 Generales"
    a, b = ops[0], ops[-1]
    return f"{a['paso']:02d} {a['etiqueta']} al {b['paso']:02d} {b['etiqueta']}"


def _sugerencias(ops: list[dict]) -> list[dict]:
    if len(ops) <= 8:
        fuente = ops
    else:
        vistos = set()
        fuente = []
        for o in list(ops[:4]) + list(ops[-4:]):
            if o["id"] in vistos:
                continue
            vistos.add(o["id"])
            fuente.append(o)
    return [
        {
            "paso": o["paso"], "etiqueta": o["etiqueta"], "id": o["id"],
            "mensaje": o["id"], "destino": o["destino"],
        }
        for o in fuente
    ]


def _puntos(texto: str, opcion: dict) -> int:
    t = _sin_acentos(texto)
    score = 0
    if re.fullmatch(rf"0*{opcion['paso']}", t.strip()):
        return 100
    m_paso = re.search(r"\bpaso\s*0*(\d{1,2})\b", t)
    if m_paso and int(m_paso.group(1)) == opcion["paso"]:
        return 100
    if t.strip() == _sin_acentos(opcion["id"]):
        return 90
    if t.strip() == _sin_acentos(opcion["etiqueta"]):
        return 80
    for kw in opcion.get("keywords") or ():
        k = _sin_acentos(kw)
        if k and k in t:
            score += 8 + min(len(k), 12)
    if _sin_acentos(opcion["etiqueta"]) in t:
        score += 20
    return score


def responder_ayuda(mensaje: str, rol: str, nombre: str | None = None, contexto: dict | None = None) -> dict:
    visibles = opciones_para_rol(rol)
    texto = (mensaje or "").strip()
    if not texto:
        return respuesta_bienvenida(rol, nombre)
    t = _sin_acentos(texto)
    if any(p in t for p in ("secuencia", "menu", "menú", "opciones", "pasos")):
        return _respuesta_secuencia(visibles)
    ranked = sorted(((_puntos(texto, o), o) for o in visibles), key=lambda x: -x[0])
    mejor_score, mejor = ranked[0] if ranked else (0, None)
    if mejor is None or mejor_score < 8:
        return {
            "respuesta": (
                f"No ubiqué esa consulta. Las opciones van del {rango_menu(visibles)}. "
                "Pregunta por el nombre o por el número."
            ),
            "sugerencias": _sugerencias(visibles),
            "destino": None,
            "opcion_id": None,
            "_sin_match": True,
        }
    return {
        "respuesta": f"{mejor['paso']:02d} {mejor['etiqueta']}. {mejor['ayuda']}",
        "sugerencias": _sugerencias([mejor] + [o for o in visibles if o["id"] != mejor["id"]]),
        "destino": mejor["destino"],
        "opcion_id": mejor["id"],
    }


def respuesta_bienvenida(rol: str, nombre: str | None = None, contexto: dict | None = None) -> dict:
    visibles = opciones_para_rol(rol)
    quien = (nombre or "Hola").split()[0]
    extra = ""
    if rol == "admin":
        extra = (
            " Como administrador también tienes Usuarios (11), Eventos (13), Respaldo (14), "
            "Escenarios (15) y Generales (16: empresa, MCP, Telegram y OnlyOffice) y el modo Mejora."
        )
    elif rol == "auditor":
        extra = " Tu rol es de consulta: recorres ofertas, Auditoría (12), Eventos (13) y Respaldo (14) sin modificar."
    elif rol == "TECNICO_NOC_SOC":
        extra = " Tu rol es de consulta: recorres ofertas, Auditoría (12) y Eventos (13)."
    return {
        "respuesta": (
            f"{quien}, ya estás autenticado en el Sistema de Cotización. "
            "El ciclo de obra (contrato, HES, factura) vive en Control de Proyecto: "
            "aquí se cotiza y, al ganar, se traspasa al SBC único por el MCP."
            f"{extra} El menú va del {rango_menu(visibles)}. Pregunta por un paso o «secuencia»."
        ),
        "sugerencias": _sugerencias(visibles),
        "destino": None,
        "opcion_id": None,
    }


def _respuesta_secuencia(visibles: list[dict]) -> dict:
    lineas = []
    grupo_actual = None
    for o in visibles:
        if o["grupo"] != grupo_actual:
            grupo_actual = o["grupo"]
            lineas.append(f"\n{GRUPOS.get(grupo_actual, grupo_actual)}:")
        lineas.append(f"  {o['paso']:02d}  {o['etiqueta']}")
    return {
        "respuesta": "Este es el orden de las opciones que puedes usar:\n" + "\n".join(lineas).strip(),
        "sugerencias": _sugerencias(visibles),
        "destino": None,
        "opcion_id": None,
    }
