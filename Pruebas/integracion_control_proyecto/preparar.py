"""Prueba cruzada, paso 1: oferta ganada en el Sistema de Cotización y, en
Control de Proyecto, el cliente (por RIF) y un proyecto vacío.

Requiere los DOS ambientes de desarrollo recién creados (BD nuevas), p. ej.
con Instalacion/desarrollo/levantar-con-control-proyecto.sh. Cambia la clave
temporal del admin de cada instancia y le activa el 2FA: las claves nuevas se
fijan con COT_CLAVE / CP_CLAVE y los secretos TOTP quedan en estado.json.

Uso: python preparar.py <carpeta_salida>   (con el .venv de Backend/, que trae pyotp)
"""
import json, os, sys, urllib.error, urllib.request, pyotp

def req(base, path, body=None, token=None, method=None, raw=False):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(base + path, data=data, method=method or ("POST" if data else "GET"))
    r.add_header("Content-Type", "application/json")
    if token: r.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(r) as resp:
        b = resp.read()
        return (b, dict(resp.headers)) if raw else (json.loads(b) if b else None)

def sesion(base, usuario, inicial, nueva):
    """clave temporal → nueva → 2FA → escenario. Devuelve la sesión completa."""
    try:
        d = req(base, "/auth/login", {"usuario": usuario, "password": inicial})
        if d["paso"] == "cambiar_password":
            d = req(base, "/auth/cambiar-password", {"usuario": usuario, "password_actual": inicial, "password_nueva": nueva})
    except urllib.error.HTTPError:
        d = None
    if d is None or d["paso"] == "totp":
        raise SystemExit("La cuenta ya tiene 2FA de una corrida previa: borra la BD de desarrollo.")
    refresh = d["refresh_token"]
    if d["paso"] == "2fa_setup":
        t = req(base, "/auth/2fa/setup", {}, d["access_token"])
        req(base, "/auth/2fa/verify", {"codigo": pyotp.TOTP(t["secret"]).now()}, d["access_token"])
        secreto = t["secret"]
    esc = req(base, "/auth/escenarios", token=d["access_token"])["escenarios"][0]
    e = req(base, "/auth/escenario", {"escenario_id": esc["id"]}, d["access_token"])
    return {"accessToken": e["access_token"], "refreshToken": e.get("refresh_token") or refresh,
            "usuario": e["usuario"], "nombre": e["nombre"], "rol": e["rol"], "escenario": e["escenario"],
            "totp_secret": secreto}

COT = os.environ.get("COT_API", "http://127.0.0.1:8100")
CP = os.environ.get("CP_API", "http://127.0.0.1:8000")
COT_CLAVE = os.environ.get("COT_CLAVE", "Cotizacion.Admin.2026")
CP_CLAVE = os.environ.get("CP_CLAVE", "ControlProyecto.Admin.2026")
out = sys.argv[1]

# --- Sistema de Cotización: oferta ganada (ejecución detallada) ---
sc = sesion(COT, "admin", "CambiaEstoYa.1", COT_CLAVE)
t = sc["accessToken"]
o = req(COT, "/ofertas", {"titulo": "Mantenimiento Mayor Grupos Electrógenos Centro Empresarial",
                          "cliente_razon_social": "PDVSA Petróleo S.A.", "cliente_rif": "J-00012345-6",
                          "modalidad": "ejecucion", "facturacion": "detallada",
                          "sede_destino": "SBC local (desarrollo)"}, t)
req(COT, f"/ofertas/{o['id']}/partidas", [
    {"disciplina": "Electricidad", "item": "1", "descripcion": "Mantenimiento de tablero de transferencia automática", "unidad": "UND", "cantidad": 2, "precio_unitario": 7658.13, "semana_inicio": 1, "duracion_semanas": 4},
    {"disciplina": "Electricidad", "item": "2", "descripcion": "Sustitución de cableado de control", "unidad": "ML", "cantidad": 120, "precio_unitario": 12.5, "semana_inicio": 3, "duracion_semanas": 3},
    {"disciplina": "Mecánica", "item": "1", "descripcion": "Limpieza y puesta a punto del grupo electrógeno", "unidad": "UNDS", "cantidad": 2, "precio_unitario": 11458.28, "semana_inicio": 2, "duracion_semanas": 6},
], t, method="PUT")
for e in ("enviada", "ganada"):
    req(COT, f"/ofertas/{o['id']}/estado", {"estado": e}, t)
cuerpo, cab = req(COT, f"/ofertas/{o['id']}/traspaso", token=t, raw=True)
nombre = cab["content-disposition"].split('filename="')[1].rstrip('"')
open(f"{out}/{nombre}", "wb").write(cuerpo)

# --- Control de Proyecto: cuenta propia, cliente por RIF y proyecto vacío ---
scp = sesion(CP, "admin", "CambiaEstoYa.1", CP_CLAVE)
tc = scp["accessToken"]
cli = req(CP, "/clientes", {"razon_social": "PDVSA Petróleo S.A.", "rif": "J-00012345-6"}, tc)
p = req(CP, "/proyectos?proyecto_id=mant-centro-2026&nombre=Mantenimiento%20Centro%20Empresarial%202026"
            "&cliente=PDVSA%20Petr%C3%B3leo%20S.A.&cliente_rif=J-00012345-6", {}, tc)
json.dump({"cp_clave": CP_CLAVE, "archivo": nombre, "oferta_id": o["id"], "codigo": o["codigo"], "cot_sesion": sc,
           "cp_sesion": scp, "cp_proyecto": p["id"], "cp_cliente": cli["id"]}, open(f"{out}/estado.json", "w"), indent=1)
print("oferta", o["codigo"], "→", nombre, "| CP cliente", cli["id"][:8], "proyecto", p["id"])
