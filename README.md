# Sistema de Cotización — ORIOL Consultores C.A.

Ofertas comerciales y traspaso de las ofertas **ganadas** a **Control de Proyecto**, bajo metodología ATLAS (MET-002).

- **Instancia propia:** base de datos, `SECRET_KEY` y cuentas de usuario separadas de Control de Proyecto (ING-COT-003 §6).
- **Mismo código de identidad:** reutiliza `identity/` de Control de Proyecto sin cambios.
- **Integración por archivo:** una oferta ganada se descarga como JSON (FOR-COT-002) y se sube a mano en el formulario de Contrato de Control de Proyecto. No hay llamadas de red entre las dos instancias.

## Estructura

```
Backend/
  app/
    identity/                   copia exacta de Control de Proyecto (login, 2FA, usuarios, escenarios)
    kernel/                     config, BD, modelos, esquemas, seguridad, bitácora
    plataforma/                 seguridad_ops y geoip_ops (copiados) + adaptadores
    colaboracion/mailer.py      adaptador: solo SMTP de alertas
    crm/                        ofertas: alta, partidas, estados
    conexion_control_proyecto/  archivo de traspaso, vinculación y eventos
  tests/
  herramientas/sincronizar_identity.sh
Frontend/
  sistema_cotizacion.html       aplicación (HTML + JS sin compilación, igual que Control de Proyecto)
  js/app.js · css/app.css · assets/logo-oriol.png
Pruebas/
  e2e_flujo_oferta.js           recorrido completo en navegador (Playwright)
Documentacion/
  ING-COT-003_Conexion_Cotizacion_Control_Proyecto.md
  FOR-COT-002_Archivo_Traspaso_Oferta_Ganada.md
  ejemplos/ORI-2026-09-001_traspaso_control_proyecto.json
```

## Arranque (desarrollo)

```bash
cd Backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # fija DATABASE_URL, SECRET_KEY (propia) e INITIAL_ADMIN_*
set -a; . ./.env; set +a
uvicorn app.main:app --reload --port 8100
pytest -q
```

## Frontend

```bash
cd Frontend && python3 -m http.server 8090
# abrir http://127.0.0.1:8090/sistema_cotizacion.html
```

La URL del backend se fija en `window.COTIZACION_API_BASE` dentro de `sistema_cotizacion.html` (por defecto `http://127.0.0.1:8100`).

La pantalla cubre:
- **Inicio de sesión:** los pasos de `identity/` (clave temporal, 2FA "Oriol COT" y elección del escenario).
- **Ofertas:** lista con filtro por estado y alta de ofertas.
- **Oferta abierta:**
  - datos generales;
  - selector de modalidad (suministro, ejecución resumida o ejecución detallada), que explica qué se crea en Control de Proyecto;
  - editor de partidas con subtotales por disciplina, IVA y total;
  - botones de cambio de estado.
- **Traspaso** (visible con la oferta ganada):
  1. **Descargar traspaso**;
  2. instrucciones para importarlo en el SBC;
  3. registro de la vinculación o del fallo.
- **Bitácora** de la oferta.

Los roles de solo lectura (auditor, o un escenario de solo lectura) ven la oferta sin controles de edición.

**Prueba en navegador:** con el backend recién creado en :8100 y el frontend en :8090, ejecuta `node Pruebas/e2e_flujo_oferta.js <carpeta_capturas>`.

## API de ofertas

| Método | Ruta | Rol | Qué hace |
|---|---|---|---|
| GET / POST | `/ofertas` | lectura: admin, analista, auditor · escritura: admin, analista | Lista las ofertas del escenario o crea una (asigna el código `ORI-AAAA-MM-NNN`). |
| GET / PATCH | `/ofertas/{id}` | igual | Consulta o edita la oferta. Una oferta ganada solo admite cambios en `sede_destino`, `notas` y `cliente_contacto`. |
| PUT | `/ofertas/{id}/partidas` | admin, analista | Reemplaza todas las partidas. |
| POST | `/ofertas/{id}/estado` | admin, analista | Cambia de estado. Para pasar a **ganada** exige modalidad, facturación, RIF y partidas. |
| GET | `/ofertas/{id}/traspaso` | admin, analista | Descarga el archivo FOR-COT-002 (solo con la oferta ganada). |
| POST | `/ofertas/{id}/vinculacion` | admin, analista | Registra el proyecto y el contrato creados en Control de Proyecto. |
| POST | `/ofertas/{id}/importacion-fallida` | admin, analista | Registra que la importación en Control de Proyecto falló. |
| GET | `/ofertas/{id}/eventos` | lectura | Bitácora de la oferta y de la conexión. |

Autenticación: `/auth/*`, `/usuarios` y `/escenarios`, igual que en Control de Proyecto.

## Mantener `identity/` al día

```bash
Backend/herramientas/sincronizar_identity.sh /ruta/a/oriol-control-de-proyecto
cd Backend && pytest -q
```
