"""Prueba integrada del traspaso por el MCP, paso 1 (por API).

Requiere los TRES nodos de desarrollo recién creados y enrolados:
  Instalacion/desarrollo/levantar-con-control-proyecto.sh
  Instalacion/desarrollo/enrolar-mcp-local.sh

- Sistema de Cotización: cambia la clave temporal del admin (COT_CLAVE), le
  activa el 2FA, crea una oferta dirigida al SBC "sbc-local-dev" y la marca
  Ganada: el backend la publica sola en el MCP.
- Control de Proyecto: cambia la clave temporal del admin (CP_CLAVE) y activa
  su 2FA, para que el paso 2 entre por la interfaz.
Deja todo en <carpeta>/estado.json (incluye los secretos TOTP: solo desarrollo).

Uso: ../../Backend/.venv/bin/python preparar.py <carpeta>
"""
import json, os, sys, urllib.error, urllib.request, pyotp

COT = os.environ.get("COT_API", "http://127.0.0.1:8100")
CP = os.environ.get("CP_API", "http://127.0.0.1:8000")
COT_CLAVE = os.environ.get("COT_CLAVE", "Cotizacion.Admin.2026")
CP_CLAVE = os.environ.get("CP_CLAVE", "ControlProyecto.Admin.2026")


def req(base, path, body=None, token=None, method=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(base + path, data=data, method=method or ("POST" if data is not None else "GET"))
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r) as resp:
            b = resp.read()
            return json.loads(b) if b else None
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{base}{path} → HTTP {e.code}: {e.read().decode()[:300]}")


def sesion(base, clave_nueva):
    d = req(base, "/auth/login", {"usuario": "admin", "password": "CambiaEstoYa.1"})
    if d["paso"] == "cambiar_password":
        d = req(base, "/auth/cambiar-password", {"usuario": "admin", "password_actual": "CambiaEstoYa.1",
                                                  "password_nueva": clave_nueva})
    secreto = None
    if d["paso"] == "2fa_setup":
        t = req(base, "/auth/2fa/setup", {}, d["access_token"])
        req(base, "/auth/2fa/verify", {"codigo": pyotp.TOTP(t["secret"]).now()}, d["access_token"])
        secreto = t["secret"]
    esc = req(base, "/auth/escenarios", token=d["access_token"])["escenarios"][0]
    e = req(base, "/auth/escenario", {"escenario_id": esc["id"]}, d["access_token"])
    return e["access_token"], secreto


out = sys.argv[1]
t, cot_totp = sesion(COT, COT_CLAVE)
estado = req(COT, "/mcp/estado", token=t)
assert estado["ok"], estado
destino = next(d for d in estado["destinos"] if d["nombre"] == "sbc-local-dev")
o = req(COT, "/ofertas", {"titulo": "Mantenimiento Mayor Grupos Electrógenos Centro Empresarial",
                          "cliente_razon_social": "PDVSA Petróleo S.A.", "cliente_rif": "J-00012345-6",
                          "modalidad": "ejecucion", "facturacion": "detallada",
                          "mcp_destino_id": destino["id"], "sede_destino": destino["nombre"]}, t)
req(COT, f"/ofertas/{o['id']}/partidas", [
    {"disciplina": "Electricidad", "item": "1", "descripcion": "Mantenimiento de tablero de transferencia automática", "unidad": "UND", "cantidad": 2, "precio_unitario": 7658.13, "semana_inicio": 1, "duracion_semanas": 4},
    {"disciplina": "Electricidad", "item": "2", "descripcion": "Sustitución de cableado de control", "unidad": "ML", "cantidad": 120, "precio_unitario": 12.5, "semana_inicio": 3, "duracion_semanas": 3},
    {"disciplina": "Mecánica", "item": "1", "descripcion": "Limpieza y puesta a punto del grupo electrógeno", "unidad": "UNDS", "cantidad": 2, "precio_unitario": 11458.28, "semana_inicio": 2, "duracion_semanas": 6},
], t, method="PUT")
req(COT, f"/ofertas/{o['id']}/estado", {"estado": "enviada"}, t)
o = req(COT, f"/ofertas/{o['id']}/estado", {"estado": "ganada"}, t)
print(f"Cotización: {o['codigo']} ganada → MCP estado={o['mcp_estado']} v{o['mcp_version']}")
assert o["mcp_estado"] == "pendiente", o

_, cp_totp = sesion(CP, CP_CLAVE)
json.dump({"oferta_id": o["id"], "codigo": o["codigo"], "cot_clave": COT_CLAVE, "cot_totp": cot_totp,
           "cp_clave": CP_CLAVE, "cp_totp": cp_totp}, open(f"{out}/estado.json", "w"), indent=1)
