# FOR-COT-002 — Archivo de traspaso: Oferta Ganada → Control de Proyecto
### ORIOL Consultores C.A. · Metodología ATLAS (MET-002) · Versión 1 · 2026-09-27

Formato oficial del archivo que el Sistema de Cotización genera cuando una oferta queda **Ganada** y que el analista sube a mano en Control de Proyecto. Mecanismo y decisiones: ING-COT-003.

## 0. Cómo viaja
- **Vía principal:** por el **MCP**, en el cuerpo de `POST /nodos-sbc/traspasos` (`{"destino_nodo_id": ..., "traspaso": <este JSON>}`). El SBC destino lo recibe en su bandeja. Ver ING-COT-003 §9.
- **Contingencia:** descarga del archivo en el Sistema de Cotización y carga manual en el formulario Nuevo contrato de Control de Proyecto.

El contenido es el mismo en los dos casos.

## 1. Base: el respaldo de oferta que Control de Proyecto ya importa

El archivo **es** un `RESPALDO_OFERTA_CONTROL_PROYECTO_V1`. Es el mismo formato que Control de Proyecto ya acepta en el formulario de **Contrato** (campo "respaldo de oferta"):

- lo lee en `js/control_de_proyecto_app.js` → `leerDatosOfertaDesdeArchivo` y `aplicarOfertaAContrato`;
- lo guarda completo en `proyecto.master`;
- la única regla de validación es que existan `meta` y `frentes[]`.

Por eso la versión actual de Control de Proyecto **lo importa sin cambios**. Lo propio del Sistema de Cotización va en el bloque adicional `origen`, que Control de Proyecto hoy ignora.

- **Nombre del archivo:** `ORI-AAAA-MM-NNN_traspaso_control_proyecto.json`
- **Codificación:** UTF-8, JSON.

## 2. Estructura

| Campo | Tipo | Qué hace Control de Proyecto con él |
|---|---|---|
| `formato` | `"RESPALDO_OFERTA_CONTROL_PROYECTO_V1"` | Identifica el respaldo. |
| `generado` | ISO-8601 UTC | Informativo. |
| `nombre` | texto | Nombre de la oferta que se anota en el contrato. |
| `meta.titulo`, `meta.iva_pct`, `meta.moneda`, `meta.semanas_totales`, `meta.n_items` | | Encabezados, cronograma e informes. |
| `resumen.total_precio`, `resumen.iva_monto`, `resumen.total_general` | número | Monto de la oferta. |
| `frentes[].frente_label` | texto | **Lista de frentes de la valuación** (`frentesForValuacion`). |
| `frentes[].subtotal_precio` | número | Subtotal del frente. |
| `frentes[].items[]` | `item, descripcion, unidad, cantidad, precio_unitario, precio_total` | Partidas. La ejecución física se cruza por `item` dentro del frente. |
| `cronograma[]` | `actividad, frente_label, fase, semana_inicio, semana_fin, duracion_semanas` | Cronograma. Se filtra por `frente_label`. |
| `origen` | objeto | **Extensión FOR-COT-002** (sección 4). |

## 3. Granularidad según modalidad (ING-COT-003 §4)

En Control de Proyecto la valuación se desagrega **por frente**: cada `valuaciones[].frente_label` sale de `master.frentes[]`. La modalidad de la oferta decide cuántos frentes tiene el archivo:

| `modalidad` / `facturacion` | Frentes del archivo | Números de partida |
|---|---|---|
| `ejecucion` + `detallada` | uno por disciplina (en mayúsculas) | los de la oferta; no pueden repetirse dentro de una disciplina |
| `ejecucion` + `resumida` | uno solo: `GLOBAL` | renumerados 1..N; el original queda en `item_oferta` y `disciplina` |
| `suministro` | uno solo: `SUMINISTRO` | igual que resumida |

**Cronograma:** una actividad por disciplina con las semanas mínima y máxima de sus partidas. En suministro la actividad se llama `ENTREGA DE SUMINISTRO`.

## 4. Bloque `origen` (extensión)

```json
"origen": {
  "sistema": "sistema_cotizacion_oriol",
  "formato": "FOR-COT-002",
  "version": 1,
  "codigo_oferta": "ORI-2026-09-001",
  "cliente": { "razon_social": "PDVSA", "rif": "G-20000043-0", "tipo": "directo", "contacto": "..." },
  "modalidad": "ejecucion",
  "facturacion": "detallada",
  "tipo_orden_sugerido": "contrato_obra",
  "analista": "Ana Lista",
  "fecha_ganada": "2026-09-27T14:00:00Z",
  "sede_destino": "SBC proyectos.oriol.support",
  "huella_sha256": "…"
}
```

| Campo | Uso previsto en Control de Proyecto |
|---|---|
| `codigo_oferta` | Clave del traspaso en el MCP (uno por oferta). Se guarda en el contrato (`codigo_oferta`), y el SBC avisa si ya está en otro proyecto. |
| `cliente.rif` | Buscar la empresa en **Clientes** (el contrato exige cliente registrado; se identifica por RIF). |
| `tipo_orden_sugerido` | Preseleccionar `tipo_orden`: `orden_compra` para suministro, `contrato_obra` para ejecución. |
| `sede_destino` | Instancia donde debe importarse. Siempre un **SBC/núcleo**: el MASTER no opera obra. |
| `huella_sha256` | SHA-256 de `frentes` + `resumen`. Con la misma huella el MCP no reenvía; con una distinta crea una versión nueva. |

## 5. Ejemplo

`Documentacion/ejemplos/ORI-2026-09-001_traspaso_control_proyecto.json`
