# BUILD — Conexión: Oferta Aprobada (Sistema de Cotización) → Control de Proyecto
### Documento de build para Cursor · ING-COT-003 · ORIOL Consultores C.A. · Metodología ATLAS (MET-002)

> **Encaje con el esquemático general:** este documento desarrolla en detalle el punto que el `ESQUEMATICO_SISTEMA_COTIZACION_ORIOL.md` dejó abierto en §5.7 (BPM) y §10 (instrucción de arranque, punto 3 "reutilizar, no reinventar"): qué pasa técnicamente cuando una oferta se **gana**. No reemplaza al esquemático, lo extiende.

---

## 1. Objetivo de esta conexión

Hoy el ciclo de vida de una oferta termina, en la práctica, cuando el cliente la acepta — y ahí arranca, por separado y a mano, el ciclo de ejecución del proyecto (valuación → HES → factura → aviso de pago → cuentas por cobrar) que ya gestiona **Control de Proyecto**. Esta conexión cierra esa costura: cuando una oferta pasa a estado **Ganada**, debe originar (o alimentar) el proyecto correspondiente, sin que el analista tenga que volver a capturar cliente, partidas o montos a mano.

**Decisión de arquitectura confirmada por el usuario:** el Sistema de Cotización se construye reutilizando el mismo código y los mismos patrones de Control de Proyecto (FastAPI + SQLAlchemy modular, mismo módulo `identity/` tal cual está), pero se despliega como una **instancia nueva y separada** — con su propia base de datos y su propio `SECRET_KEY`, igual que MASTER y cada SBC son hoy instalaciones independientes entre sí. Los usuarios del Sistema de Cotización son **cuentas propias de esa instancia**, separadas de las de Control de Proyecto (detalle en §6).

**Precisión del usuario sobre cómo viaja la información:** las dos aplicaciones podrían no coexistir en el mismo entorno de red, así que no debe asumirse que una puede llamar a la API de la otra en tiempo real. El traspaso de la oferta ganada se hace mediante un **archivo específico** que el Sistema de Cotización genera y que Control de Proyecto consume — ver §5.

## 2. Punto de enganche exacto

En el Sistema de Cotización, el punto de enganche es la transición de estado dentro del módulo `crm/` (o `bpm/`, según cómo se implemente finalmente el pipeline — ver §5.6/§5.7 del esquemático) cuando una oferta pasa de `En negociación` a `Ganada`. Ese cambio de estado:

1. Se registra como evento en `eventos/` (§5.12 del esquemático) — `tipo: "oferta_ganada"`.
2. Dispara la generación del archivo de traspaso hacia Control de Proyecto (ver §5) — no una llamada de red en vivo, porque no debe asumirse que ambos sistemas están en la misma red.

**Tarea previa — RESUELTA (2026-09-27, ver §8):**
- **Alta del proyecto:** `POST /proyectos` → `crear_proyecto()` en `Backend/app/ciclo/proyecto_ops.py`.
- **Carga de la oferta dentro del proyecto:** no la hace el backend. La hace el formulario de **Contrato** del frontend, importando un *respaldo de oferta* (`js/control_de_proyecto_app.js`: `importarOfertaEnContrato`).

## 3. Qué información viaja de la oferta al proyecto

| Dato en la oferta (Sistema de Cotización) | Destino sugerido en Control de Proyecto | Nota |
|---|---|---|
| Código de oferta `ORI-AAAA-MM-NNN` | Referencia cruzada / código externo del proyecto | Debe quedar visible en ambos sistemas para trazabilidad bidireccional |
| Cliente (nombre, tipo directo/aliado, contacto) | Cliente/aliado del proyecto | Si Control de Proyecto ya maneja "aliados" (ver Red de Empresas Aliadas), mapear directo/aliado 1 a 1 |
| Disciplinas y partidas ganadoras (con sus montos de venta) | Estructura inicial de valuación / BOM de obra | Depende de `modalidad`/`facturación` — ver §4 |
| Modalidad (`suministro`/`ejecucion`) y facturación (`resumida`/`detallada`) | Tipo de registro a crear en Control de Proyecto (entrega simple, proyecto consolidado o proyecto detallado) | Campo nuevo en `ofertas`, ver §4 |
| Monto total de venta, IVA, moneda | Monto contractual del proyecto | Base para la primera valuación |
| Tiempos de entrega/ejecución por partida (§5.3 del esquemático) | Cronograma inicial del proyecto | Insumo, no necesariamente un campo 1 a 1 |
| Analista responsable | Responsable técnico / creador del proyecto | Viaja como dato (nombre/identificador) en el archivo — no hay usuario compartido entre instancias (§6); si Control de Proyecto necesita asignarlo a un usuario propio, se mapea allá, no aquí |
| Documento final de oferta (PDF/Word, con marca ORIOL) | Adjunto inicial del expediente del proyecto | Para que el equipo de ejecución tenga el contrato de origen a la mano |

## 4. Granularidad del proyecto — modalidad configurable por oferta

No es una única regla fija: la granularidad es una **opción que se escoge por oferta**, porque el tipo de trabajo varía. Definido por el usuario:

- **Oferta de suministro** (sin mano de obra): la oferta entrega únicamente materiales/equipos, sin partidas de instalación ni tiempos de ejecución. En Control de Proyecto esto puede no necesitar el ciclo completo de obra (valuación → HES → …), sino una entrega y facturación directa.
- **Oferta de ejecución en obra, con varias disciplinas**, que se lleva y factura de dos formas posibles:
  - **Resumida:** un solo proyecto con una valuación consolidada, sin desagregar por disciplina.
  - **Detallada:** un proyecto con valuación (o estructura) desagregada por disciplina/partida.

Esto se modela agregando dos campos a `ofertas` (tabla del §6 del esquemático):

```
ofertas.modalidad     [suministro | ejecucion]
ofertas.facturacion   [resumida | detallada]   -- solo aplica si modalidad = ejecucion
```

El analista/supervisor fija esta modalidad al momento de aprobar la oferta (o antes, al armarla), y el archivo de traspaso que se genera hacia Control de Proyecto (§5) debe declararla explícitamente, para que del otro lado se sepa si crear:

1. un registro de entrega/factura simple (`suministro`),
2. un proyecto único con una valuación consolidada (`ejecucion` + `resumida`), o
3. un proyecto con valuación/estructura por disciplina (`ejecucion` + `detallada`).

**Verificado en el código de Control de Proyecto:** la "valuación por disciplina" no son subproyectos ni fases. Es el **frente**:
- cada valuación (`ctrl.valuaciones[]`) lleva `contrato_id` y `frente_label`;
- la lista de frentes sale de `master.frentes[]` (la oferta importada); sin oferta solo existe `GLOBAL`.

Por lo tanto:
- caso 1 (suministro) → un solo frente `SUMINISTRO`;
- caso 2 (resumida) → un solo frente `GLOBAL`;
- caso 3 (detallada) → un frente por disciplina.

Detalle en FOR-COT-002 §3.

## 5. Mecanismo técnico de integración (por archivo, no por red en vivo)

Como las dos aplicaciones podrían no coexistir en el mismo entorno de red, no se asume una llamada API en vivo entre ellas. El traspaso se hace con un **archivo específico**: el Sistema de Cotización lo genera al ganar la oferta, y Control de Proyecto lo consume para crear el proyecto.

```
Sistema de Cotización — instancia propia
        │  oferta → estado "Ganada"
        ▼
  conexion_control_proyecto/   (módulo del Sistema de Cotización)
        │  genera el archivo de traspaso: código de oferta, cliente, disciplinas/partidas,
        │  modalidad/facturación, montos, tiempos, analista, documento de oferta
        ▼
[archivo de traspaso]  →  entrega a Control de Proyecto (mecanismo de entrega — ver pregunta abajo)
        ▼
Control de Proyecto — lee/importa el archivo y crea/actualiza el proyecto
        │  el proyecto queda con la referencia al código de oferta que trae el archivo
```

- **Formato del archivo — RESUELTO:** Control de Proyecto **ya importa ofertas por archivo**, en el formato `RESPALDO_OFERTA_CONTROL_PROYECTO_V1` (JSON con `meta`, `resumen`, `frentes[]` y `cronograma[]`). El traspaso usa ese mismo formato más un bloque adicional `origen`. Queda documentado como **FOR-COT-002** (`Documentacion/FOR-COT-002_Archivo_Traspaso_Oferta_Ganada.md`).
- **Trazabilidad e idempotencia:** el nombre del archivo debe incluir el código de oferta (`ORI-AAAA-MM-NNN`), para saber cuál oferta lo originó y para que Control de Proyecto no cree el mismo proyecto dos veces si el archivo se procesa más de una vez.
- **Confirmación de recepción:** al no haber respuesta síncrona de un endpoint, hace falta otra forma de saber que Control de Proyecto sí levantó el proyecto — un archivo de confirmación que genere Control de Proyecto, un estado visible en algún panel, o una revisión periódica. Queda por definir junto con el mecanismo de entrega.
- **Instancia destino — RESUELTO:** según `Documentacion/PARA_CLAUDE_arquitectura_nucleo_borde.md` de Control de Proyecto, *"El MASTER no opera obra… No hay ciclo contrato en el MASTER"*. El archivo se importa siempre en el **SBC (o núcleo)** que opera ese contrato. La oferta guarda `sede_destino` y lo manda en `origen.sede_destino`.

**Mecanismo de entrega confirmado por el usuario: descarga + importación manual.** Cuando la oferta pasa a "Ganada", el Sistema de Cotización pone a disposición del analista/supervisor un botón para **descargar** el archivo de traspaso; esa persona lo lleva y lo **sube a mano** en una pantalla de importación de Control de Proyecto. No hay carpeta vigilada ni envío automático por correo.

Esto simplifica algunas cosas y deja otras por resolver:
- **Confirmación de recepción — implementada a mano:** la persona vuelve al Sistema de Cotización y registra el resultado:
  - `POST /ofertas/{id}/vinculacion` con el id del proyecto y el número de contrato de Control de Proyecto, o
  - `POST /ofertas/{id}/importacion-fallida` con el motivo.
- **A quién de Control de Proyecto le corresponde:** al SBC o núcleo indicado en `sede_destino` (ver arriba), nunca al MASTER.

- **Dirección inversa (opcional, fase posterior):** Control de Proyecto podría, más adelante, generar su propio archivo (o notificación) con hitos de ejecución (ej. "proyecto cerrado") para que el Sistema de Cotización lo importe y refleje el estado real en su CRM (§5.6 del esquemático) más allá de "Ganada". No es parte del alcance mínimo de esta conexión.

## 6. Identidad — decisión final: instancia propia, cuentas separadas

Verificado en el código real de Control de Proyecto: `identity/` está montado dentro del mismo proceso FastAPI (`main.py`: `identity.montar(app)`), publica `/auth/login`, `/auth/refresh`, `/auth/logout`, `/auth/me`, `/auth/escenario`, `/auth/2fa/setup`, `/auth/2fa/verify`, `/usuarios`, `/escenarios`, y guarda `Usuario`, `RefreshToken`, `Escenario`, `UsuarioEscenario` en `kernel/models.py` sobre el único `DATABASE_URL` de esa instalación — sin OIDC/JWKS pensado para un segundo servicio.

**Decisión final confirmada por el usuario:**
- El Sistema de Cotización vive en una **instancia nueva y dedicada** (no en MASTER ni en un SBC existente).
- Esa instancia **reutiliza el código** de `identity/` (mismo módulo, mismo esquema de tablas) — no se construye un sistema de autenticación distinto.
- Pero tiene **su propia base de datos y su propio `SECRET_KEY`**, y por lo tanto **cuentas de usuario separadas** de las de Control de Proyecto: el analista se loguea con una cuenta en el Sistema de Cotización y, si necesita acceso a Control de Proyecto, con otra cuenta allá — sin sesión única ni sincronización automática entre ambas.

Implicaciones concretas para Cursor:
- No hace falta compartir `SECRET_KEY` entre instancias ni validar tokens de una instancia en la otra.
- No hace falta un token de servicio a servicio: al ser descarga + importación manual (§5), no hay llamada autenticada entre los dos backends — la única autenticación en juego es la de la persona que sube el archivo, con su propia cuenta de Control de Proyecto.
- Si el mismo analista necesita cuenta en ambos sistemas, hoy se crea manualmente en cada instancia (no hay aprovisionamiento automático); documentar esto en el manual de administrador (MAN-COT-001) para que quede claro al dar de alta a alguien.

## 7. Checklist de implementación para Cursor

1. [x] Leer el código real de Control de Proyecto y localizar dónde/cómo se crea hoy un proyecto/obra (manual) y cómo se modela una valuación por disciplina dentro de un mismo proyecto (§4), para no inventar un contrato de datos que no calce con el modelo real.
2. [x] Agregar los campos `modalidad` y `facturacion` a `ofertas` (§4) y el control en el constructor de oferta para que el analista/supervisor los fije.
3. [x] Levantar la instancia nueva del Sistema de Cotización reutilizando el código de `identity/` con su propio `DATABASE_URL`/`SECRET_KEY` (§6) — sin lógica de sesión compartida con Control de Proyecto.
4. [~] (Sistema de Cotización listo: botón **Descargar traspaso**; falta la mejora de lectura de `origen` en Control de Proyecto, ver §8.3; destino resuelto: SBC/núcleo) Construir el botón de descarga del archivo de traspaso en el Sistema de Cotización (visible cuando la oferta está "Ganada") y, del lado de Control de Proyecto, la pantalla de importación manual que lo lee y crea el proyecto — confirmar con el usuario a cuál instancia (MASTER o un SBC específico) debe apuntar esa pantalla.
5. [x] (a mano: `POST /ofertas/{id}/vinculacion`) Definir cómo se marca de vuelta en el Sistema de Cotización que una oferta ya quedó vinculada a un proyecto (¿a mano, con el id/código que devuelve la importación, o se deja para una fase posterior?) — ver nota de confirmación de recepción en §5.
6. [x] Implementar en el Sistema de Cotización el módulo `conexion_control_proyecto/` que genera el archivo de traspaso según la modalidad, con el código de oferta en el nombre para trazabilidad e idempotencia (§5).
7. [x] (`ofertas.proyecto_cp_id` y `contrato_cp_numero`) Guardar en la oferta la referencia cruzada al proyecto creado (id/código) para trazabilidad bidireccional.
8. [x] (bitácora, `GET /ofertas/{id}/eventos` y panel "Bitácora de la oferta" en el frontend) Registrar el evento `oferta_ganada` → `proyecto_creado` (o `proyecto_creacion_fallida`) en la bitácora de eventos (§5.12 del esquemático) y exponerlo en el panel de monitoreo.
9. [ ] Escribir el procedimiento (PROC-COT-003) que documente, para el equipo, qué pasa exactamente cuando se marca una oferta como Ganada, incluyendo cómo elegir la modalidad correcta, cómo descargar/subir el archivo de traspaso, y cómo dar de alta a un analista que necesite cuenta en ambos sistemas.

## 8. Hallazgos en el código de Control de Proyecto e implementación (2026-09-27)

Revisado `aguy48/oriol-control-de-proyecto`, commit `2d4b140`, versión 1.5.2.11.

### 8.1 Cómo guarda Control de Proyecto un proyecto
- **Modelo `Proyecto`** (`Backend/app/kernel/models.py`): `id`, `escenario_id`, `nombre`, `cliente`, `cliente_rif` y `estado` (`oferta` → `contrato`…). Además dos columnas JSON:
  - `master`: la oferta importada;
  - `ctrl`: todo el ciclo (contratos, valuaciones, HES, facturas, avisos, CxP).
- **Cliente:** tabla `clientes`, identificado por **RIF**. El formulario de Contrato no deja guardar si la empresa no está registrada.
- **Contrato** (`ctrl.contratos[]`):
  - `modalidad`: `obra` o `servicios`;
  - `tipo_orden`: `orden_compra`, `orden_servicio`, `contrato_obra` o `contrato_servicio`;
  - además monto, `iva_pct`, `plazo_semanas`, fechas, etc.
- **Importación de oferta existente:** JSON V1 o Excel, cargado desde el formulario de Contrato. Reemplaza `master` después de pedir confirmación y pasa el proyecto a estado `contrato`. **No** verifica código de oferta; ver 8.3.
- **"Aliados":** no existe ese concepto en Control de Proyecto. El tipo directo/aliado viaja solo como dato en `origen.cliente.tipo`.

### 8.2 Qué se construyó en `control_oferta`
- **Instancia propia** (`Backend/`), con su propia `DATABASE_URL` y su propio `SECRET_KEY`.
  - `identity/` es copia exacta de Control de Proyecto. Script de sincronización: `Backend/herramientas/sincronizar_identity.sh`.
  - `seguridad_ops` y `geoip_ops` también se copian tal cual.
  - Telegram, mailer y la política MASTER→SBC usan adaptadores mínimos con la misma interfaz.
- **`crm/`: ofertas.**
  - Código `ORI-AAAA-MM-NNN` correlativo por mes.
  - Partidas por disciplina, con semana de inicio y duración.
  - Estados: `borrador → enviada → en_negociacion → ganada | perdida | anulada`.
  - Para pasar a **Ganada** se exige: modalidad, facturación (si es ejecución), RIF y partidas válidas.
  - Una oferta ganada queda congelada; solo cambian `sede_destino`, `notas` y `cliente_contacto`.
- **`conexion_control_proyecto/`:**
  - descarga del traspaso (FOR-COT-002);
  - vinculación manual;
  - registro de importación fallida;
  - bitácora de la conexión: `oferta_ganada`, `traspaso_generado`, `proyecto_vinculado` y `proyecto_creacion_fallida`.
- **Pruebas:** `Backend/tests/` (18). El archivo de ejemplo se validó con la regla literal de importación del frontend de Control de Proyecto.

### 8.3 Pendiente
1. **Control de Proyecto** (cambio pequeño, compatible con lo actual): al importar un respaldo que traiga `origen`:
   - prellenar el cliente por `origen.cliente.rif`;
   - preseleccionar `tipo_orden`;
   - guardar `codigo_oferta` en el contrato y avisar si ese código ya se importó en el escenario;
   - registrar `oferta_importada` en la bitácora.
2. ~~Frontend del Sistema de Cotización~~ — hecho: `Frontend/sistema_cotizacion.html`, con recorrido completo probado en navegador (`Pruebas/e2e_flujo_oferta.js`).
3. **Documento final de la oferta (PDF/Word con marca ORIOL):** falta generarlo y guardarlo. Hoy se sube aparte como adjunto del contrato en Control de Proyecto.
4. **Rol "supervisor":** no existe en `identity/`; hoy lo cubre `admin`. Si hace falta, se agrega como rol en ambas instancias.
5. **PROC-COT-003** y la nota del manual de administrador (MAN-COT-001) sobre cuentas separadas.

---
*Documento de build (ING-COT-003) complementario a `ESQUEMATICO_SISTEMA_COTIZACION_ORIOL.md`, para que Cursor desarrolle la conexión entre el Sistema de Cotización y Control de Proyecto de ORIOL Consultores C.A. bajo metodología ATLAS (MET-002).*
