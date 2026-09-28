# Sistema de Cotización — documentación completa

**ORIOL Consultores C.A. · metodología ATLAS (MET-002) · versión 0.3.9**

Este documento describe el **Sistema de Cotización** tal como está implementado: qué hace, qué no hace, cómo se relaciona con Control de Proyecto y el MCP, el menú 01–16, roles, datos, arranque y respaldos.

Ingeniería de la conexión con Control de Proyecto: [ING-COT-003](ING-COT-003_Conexion_Cotizacion_Control_Proyecto.md). Formato del archivo de traspaso: [FOR-COT-002](FOR-COT-002_Archivo_Traspaso_Oferta_Ganada.md). Arranque local: [`Instalacion/LEEME.md`](../Instalacion/LEEME.md).

---

## 1. Qué es y qué no es

El Sistema de Cotización es la instancia donde ORIOL **arma, negocia y gana** ofertas comerciales. Al ganar, la oferta se **traspasa** al nodo SBC de Control de Proyecto que ejecutará el contrato.

**Aquí vive**

- Alta de ofertas, partidas, margen, IVA y estados (borrador → enviada → en negociación → ganada / perdida / anulada).
- Cliente, productos y servicios, proveedores, contactos, tareas y documentos de la cotización.
- Informes técnicos de campo y reportes (oferta comercial e informe).
- Gemini (PDF, audio, WhatsApp) para armar partidas e informe.
- OnlyOffice embebido para anexos Word/Excel/PowerPoint/PDF.
- Un **único SBC destino** por instancia (Generales 16), cuyos escenarios se espejan aquí.
- Traspaso al ganar por el **MCP** (o, si no hay MCP, descarga del archivo FOR-COT-002).
- Identidad propia (login, 2FA «Oriol COT», usuarios, escenarios).
- Auditoría (personas), Eventos (sistema), Respaldo ZIP, bot de Telegram y asistente 01–16.

**No vive aquí (queda en Control de Proyecto)**

- Contrato, fianzas, ejecución física, valuaciones, HES, facturas, avisos de pago, estado de cuenta, CxC/CxP, acta de cierre.
- Oficina postal, Mailcow, numeración fiscal, tasa BCV, escáneres eSCL.
- Topología de sitios SBC, enrolamiento de nodos, cola de comandos a bordes.

Una oferta ganada **no ejecuta obra** en Cotización: crea (o alimenta) el expediente en el SBC.

---

## 2. Lugar en ATLAS (tres nodos)

Cada pieza es una **instalación independiente**: base de datos y `SECRET_KEY` propias. Las cuentas de un nodo no sirven en otro.

| Nodo | Papel | Frontend | API |
|---|---|---|---|
| **Sistema de Cotización** | Cotizar y, al ganar, publicar | :8090 | :8100 |
| **Control de Proyecto (SBC)** | Ciclo de obra | :8080 | :8000 |
| **MASTER CONTROL PROJECT (MCP)** | Enlace, destinos SBC, buzón de traspasos | :8081 | :8001 |

Flujo preferido (ING-COT-003 §9):

```
Cotización (:8100)  --publica oferta ganada-->  MCP (:8001)  --entrega-->  SBC (:8000)
SBC crea contrato  --acuse-->  MCP  --consulta periódica-->  Cotización (vincula proyecto/contrato)
```

Sin MCP queda la **contingencia**: el analista descarga el JSON FOR-COT-002 e importa a mano en Contrato de Control de Proyecto.

OnlyOffice (Document Server del NUC, puerto **8082**) es el mismo que usa Control de Proyecto. La URL de callback (`ONLYOFFICE_APP_URL`) es la API de **esta** instancia (`:8100`), no la de CP.

---

## 3. Principios de diseño

1. **Instancia propia.** SQLite o PostgreSQL propio. `SECRET_KEY` distinta. Usuarios distintos (ING-COT-003 §6).
2. **`identity/` tal cual.** Login, 2FA, refresh, usuarios y escenarios se copian de Control de Proyecto. Excepción: no se crean escenarios a mano si ya hay un SBC elegido (salen del latido del nodo).
3. **Un SBC por instancia.** El administrador lo fija en Generales (16). Las ofertas no eligen SBC suelto cuando ese destino está configurado.
4. **Escenarios = razón social + periodo de contratación.** Vienen del SBC seleccionado (MCP `destinos[].escenarios`). Aquí se asignan usuarios y el escenario por defecto del login.
5. **Gemini, Telegram y OnlyOffice cifrados** en Generales. No van en el código. El GET no vuelve a mostrar tokens ni JWT.
6. **Auditoría ≠ Eventos.** Personas (login, CRUD) vs sistema (MCP, bloqueos, Telegram, disco, respaldos).

---

## 4. Menú (pasos 01–16)

| Paso | Opción | Quién la ve | Qué hace |
|---:|---|---|---|
| 01 | Panel | todos | KPI del escenario: ofertas, catálogo, MCP enlazado. |
| 02 | Ofertas | todos | Ciclo comercial, Gemini, anexos, OnlyOffice, traspaso al ganar. Un borrador se puede eliminar. |
| 03 | Informes | todos | Levantamiento de campo. Gemini redacta informe + oferta. |
| 04 | Reportes | todos | Imprimir oferta e informe técnico; abrir Word/Excel en OnlyOffice; eliminar informe. |
| 05 | Clientes | todos | Ficha fiscal (RIF). Se puede inscribir uno nuevo desde oferta. |
| 06 | Productos y servicios | todos | Catálogo cotizable, serial, garantía, entrega en semanas, top 10. |
| 07 | Proveedores | todos | Quiénes envían ofertas que se cargan en la cotización. |
| 08 | Contactos | todos | Personas de cliente u organismo. |
| 09 | Tareas | todos | Pendientes comerciales (visita, envío, negociación). |
| 10 | Documentos | todos | Referencias (URL o nota). Los archivos de la oferta se abren en 02. |
| 11 | Usuarios | admin | Cuentas de **esta** instancia. Telegram se vincula con el botón de la barra. |
| 12 | Auditoría | admin, auditor, NOC | Actividad de personas. |
| 13 | Eventos | admin, auditor, NOC | Visor de sistema: MCP, errores, denegados, Telegram, disco. |
| 14 | Respaldo | admin (generar/restaurar), auditor (listar/descargar) | ZIP de datos o de aplicación. |
| 15 | Escenarios | admin | Periodos del SBC. Asignar usuarios y marcar el por defecto. |
| 16 | Generales | admin | Empresa, Gemini, MCP/SBC, Telegram y OnlyOffice **en bloques**. |

El analista y el técnico recorren 01–10. El chatbot y Telegram exponen **solo** los pasos del rol.

---

## 5. Roles

| Rol | Escritura comercial | Administración |
|---|---|---|
| `admin` | sí | Usuarios, escenarios, Generales, Eventos, Respaldo, modo Mejora del asistente |
| `analista` | sí | no |
| `tecnico` | según escenario | no |
| `auditor` | no (consulta) | Auditoría, Eventos, listar/descargar Respaldo |
| `TECNICO_NOC_SOC` | no | Auditoría y Eventos |

El 2FA es obligatorio en producción (`REQUIRE_2FA=true`). La cuenta aparece en la app autenticadora como **Oriol COT**, distinta de la de Control de Proyecto.

Un escenario cerrado o de solo lectura deja la oferta sin edición aunque el rol sea de escritura.

---

## 6. Ciclo de una oferta

Estados: `borrador` → `enviada` → `en_negociacion` → `ganada` | `perdida` | `anulada`.

Al **ganar** se exige modalidad, facturación (si es ejecución), RIF y partidas. Si un producto requiere serial, se pide. Entonces:

1. Se genera el paquete FOR-COT-002 (frentes según modalidad).
2. Si hay MCP y SBC en Generales, se **publica sola** en el buzón del MCP.
3. El SBC crea el contrato; Cotización lee el acuse (`MCP_POLL_SECONDS`, por defecto 15 s en local) y deja proyecto y contrato vinculados.

Modalidad (qué se crea en Control de Proyecto):

| En Cotización | En el SBC |
|---|---|
| Suministro | Un frente `SUMINISTRO` (orden de compra) |
| Ejecución resumida | Un frente `GLOBAL` |
| Ejecución detallada | Un frente por disciplina |

Código de oferta: `ORI-AAAA-MM-NNN`, correlativo por mes y escenario.

---

## 7. Fichas y catálogo

- **Clientes:** razón social, RIF, tipo directo/aliado. El RIF identifica al cliente en el SBC.
- **Productos y servicios:** código, si requiere serial, garantía, semanas de entrega. Búsqueda desde partidas. Estadística de los 10 más cotizados (a quién, cuándo, monto).
- **Proveedores:** origen de las ofertas que se anexan.
- **Contactos / tareas / documentos:** del escenario, no del ciclo de obra.

---

## 8. Gemini, anexos y reportes

Tipos de anexo habituales: oferta/factura de proveedor, informe técnico, oferta comercial ORIOL, RIF, audio, chat de WhatsApp, imagen.

Gemini (clave en Generales 16, modelo por defecto `gemini-2.5-flash`) lee PDF, audio y WhatsApp y propone partidas más informe. Si no hay clave, hay extracción heurística (tablas, RIF, líneas de cantidad × precio).

**Reportes (04):** impresión HTML de la oferta comercial y del informe técnico. Si el archivo es office, «Abrir» usa OnlyOffice. Un informe técnico se puede eliminar.

---

## 9. OnlyOffice

Mismo Document Server del NUC (`192.168.88.201:8082` en el laboratorio). JWT cifrado en Generales. Origen permitido: **anexo**. No se abre el ciclo de obra de CP desde aquí.

---

## 10. Telegram y asistente

Bot **distinto** del de Control de Proyecto. Token de @BotFather en Generales (16). Cada usuario se vincula con el botón Telegram de la barra (código de un solo uso); no se pega el `chat_id` a mano.

- Botones / números = guía del paso (el teclado es el catálogo del rol).
- `/status` = resumen de la instancia (admin/auditor).
- `/ayuda`, `/desvincular`.

El **asistente** (FAB 01–16) tiene modo Ayuda para todos y modo **Mejora** solo para el administrador (recomendaciones: Generales por bloques, Eventos 13, Respaldo 14, 2FA).

---

## 11. Auditoría, Eventos y Respaldo

**Auditoría (12)** — lo que hacen las personas: login, ofertas, fichas, administración.

**Eventos (13)** — visor de sistema: errores de MCP, bloqueos, denegados, Telegram vinculados, uso de disco, respaldos. KPI de 24 h.

**Respaldo (14)**

| Tipo | Contenido | Restaurar |
|---|---|---|
| `datos_` | SQLite + `STORAGE_DIR` (anexos), sin ZIP anidados ni `.env` | Frase exacta: `restaurar cotizacion` (solo admin, solo ZIP de datos) |
| `aplicacion_` | Frontend HTML/JS/CSS/assets + `Backend/app` + VERSION/README, **sin** `.env` ni venv | No se restaura desde la UI |

Los ZIP quedan en `STORAGE_DIR/respaldos/`.

---

## 12. Generales (16) — cinco bloques

Cada bloque hace **PUT solo de sus campos** (`exclude_unset`). Guardar Empresa no borra el SBC ni el token de Telegram.

1. **Empresa** — razón social, RIF, IVA, moneda, margen por defecto, dirección.
2. **Gemini** — modelo y clave (no se vuelve a mostrar).
3. **MCP y SBC** — URL del MCP, token del nodo `cotizacion`, **un** SBC destino. De ese nodo salen los escenarios (15).
4. **Telegram** — token, username, polling o webhook, caducidad del código de emparejar.
5. **OnlyOffice** — URL del Document Server, URL de esta API (`:8100`), JWT (o quitar JWT).

---

## 13. Cómo está armado el código

```
control_oferta/
  VERSION                         0.3.9
  Backend/app/
    identity/                     copia de Control de Proyecto (login, 2FA, usuarios, escenarios)
    kernel/                       config, BD, modelos, esquemas, crypto, bitácora
    crm/                          ofertas, anexos, Gemini, fichas, reportes, panel
    plataforma/                   generales, asistente, Telegram, OnlyOffice, eventos, respaldo
    conexion_control_proyecto/    MCP, traspaso, sincronización de escenarios del SBC
  Frontend/                       HTML + JS sin build (sistema_cotizacion.html, js/, css/)
  Instalacion/desarrollo/         levantar, detener, estado, enrolar MCP local
  Documentacion/                  este archivo, ING-COT-003, FOR-COT-002
  Pruebas/                        e2e Playwright, integración MCP, contingencia por archivo
```

Frontend estático. La URL de la API se inyecta (`window.COTIZACION_API_BASE`, por defecto `http://127.0.0.1:8100`).

---

## 14. API (grupos)

Autenticación Bearer (JWT de `identity/`). Escritura comercial: admin y analista.

| Prefijo | Uso |
|---|---|
| `/auth/*` | Login, 2FA, escenario de sesión, refresh |
| `/usuarios`, `/escenarios` | Cuentas y periodos (admin) |
| `/ofertas` | Alta, partidas, estado, traspaso, MCP enviar |
| `/anexos`, `/analisis`, `/informes`, `/reportes` | Archivos, Gemini, impresión |
| `/clientes`, `/productos`, `/proveedores`, `/contactos`, `/tareas`, `/documentos` | Fichas |
| `/panel` | KPI |
| `/mcp/*` | Estado, destinos, sincronizar acuses y escenarios |
| `/generales`, `/generales/onlyoffice`, `/generales/telegram/probar` | Ajustes por bloques |
| `/onlyoffice/*` | Config y editor embebido |
| `/asistente/*` | Catálogo y consulta (ayuda / mejora) |
| `/telegram/*` | Estado, emparejar, webhook |
| `/auditoria`, `/eventos`, `/respaldos` | Personas, sistema, ZIP |
| `/health` | `{ status, version, modo: "cotizacion", mcp }` |

---

## 15. Datos locales (no van a GitHub)

| Qué | Dónde | Git |
|---|---|---|
| Base SQLite | `Backend/sistema_cotizacion.db` | ignorada (`*.db`) |
| Anexos y ZIP de respaldo | `STORAGE_DIR` (`Backend/data/` por defecto) | ignorada |
| Secretos | `Backend/.env` | ignorada |
| Entorno Python | `Backend/.venv/` | ignorado |

Plantilla de variables: `Backend/.env.example` (sin claves reales). Tokens y JWT en Generales se guardan **cifrados** en la base.

---

## 16. Arranque y pruebas

```bash
Instalacion/desarrollo/levantar.sh                         # Cotización :8090 / :8100
Instalacion/desarrollo/levantar-con-control-proyecto.sh    # + SBC :8000 y MCP :8001
Instalacion/desarrollo/enrolar-mcp-local.sh                # una vez: nodos locales
cd Backend && .venv/bin/pytest -q
```

Primer arranque: crea venv, `.env` con `SECRET_KEY` aleatoria, usuario admin inicial (hay que cambiar clave y activar 2FA).

Prueba de traspaso MCP (tres nodos recién creados y enrolados): `Pruebas/integracion_mcp/`.

---

## 17. Historial breve de esta línea

| Versión | Qué quedó |
|---|---|
| 0.3.3 | SBC único y MCP en Generales (no por oferta) |
| 0.3.4 | Asistente + Telegram |
| 0.3.5 | OnlyOffice (origen anexo) |
| 0.3.6 | Reportes: imprimir, abrir office, eliminar informe |
| 0.3.7 | Escenarios desde el SBC seleccionado |
| 0.3.8 | Eventos (13), Respaldo (14), Generales en bloques (16) |
| 0.3.9 | Ayuda (chatbot, barra de paso, Telegram, modo Mejora) alineada al menú 01–16 |
