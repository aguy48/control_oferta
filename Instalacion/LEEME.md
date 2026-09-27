# Instalación local — Sistema de Cotización

Usa el mismo esquema de desarrollo que Control de Proyecto (`Instalacion/desarrollo/` de `oriol-control-de-proyecto`). Los puertos son distintos para que **ambos sistemas convivan en la misma PC**:

| Sistema | Frontend | API |
|---|---|---|
| Sistema de Cotización | http://127.0.0.1:8090 | :8100 |
| Control de Proyecto | http://127.0.0.1:8080 | :8000 |
| MASTER CONTROL PROJECT (MCP) | http://127.0.0.1:8081 | :8001 |

## Requisitos
- Linux o macOS con `python3` (3.11 o superior) y `python3-venv`. Si `uv` está instalado, se usa `uv`.
- `curl`.
- Opcional: `notify-send` y `xdg-open`, para avisos y para abrir el navegador.

## Solo el Sistema de Cotización

```bash
Instalacion/desarrollo/levantar.sh        # crea Backend/.venv y Backend/.env la primera vez
Instalacion/desarrollo/estado.sh
Instalacion/desarrollo/detener.sh         # no borra datos
Instalacion/desarrollo/instalar-icono.sh  # opcional: ícono en el escritorio y en el menú
```

**Primer arranque:**
- Se crea `Backend/.env` con una base SQLite propia (`Backend/sistema_cotizacion.db`) y una `SECRET_KEY` aleatoria.
- Se crea el usuario **admin / CambiaEstoYa.1**. Al entrar se pide cambiar la clave y activar el 2FA; la app autenticadora lo muestra como "Oriol COT".
- Las cuentas son **independientes** de las de Control de Proyecto (ING-COT-003 §6).

**Variables opcionales:**
- `COTIZACION_API_PORT` y `COTIZACION_WEB_PORT`: cambian los puertos.
- `COTIZACION_DEV_BIND=127.0.0.1`: no expone el servicio a la LAN.
- `COTIZACION_NO_ABRIR=1`: no abre el navegador.

## Los tres nodos juntos (traspaso por el MCP)

El traspaso de ofertas ganadas viaja **Cotización → MCP → SBC** (ING-COT-003 §9). En local participan:
- el Sistema de Cotización;
- Control de Proyecto en el papel de **SBC** (:8000);
- el **MASTER CONTROL PROJECT / MCP** (:8001).

Clona `oriol-control-de-proyecto` **al lado** de este repositorio, o indica su ruta con `CONTROL_PROYECTO_DIR`. Usa una rama que tenga el buzón del MCP (`claude/traspaso-mcp`, mientras no esté en `main`).

```bash
Instalacion/desarrollo/levantar-con-control-proyecto.sh   # los tres nodos
Instalacion/desarrollo/enrolar-mcp-local.sh               # una vez: nodos y tokens en el MCP local
```

`enrolar-mcp-local.sh` hace tres cosas:
1. Crea en el MCP local el sitio `local-dev` con dos nodos: `sbc-local-dev` (rol `sbc_app`) y `cotizacion-local-dev` (rol `cotizacion`).
2. Enlaza Control de Proyecto :8000 al MCP (lo mismo que "Este nodo", paso 28).
3. Escribe `MCP_URL` y `MCP_TOKEN` en `Backend/.env` de Cotización y lo reinicia.

Se puede repetir: si los nodos ya existen, les rota el token.

### Flujo manual
1. **Sistema de Cotización:**
   - en *Datos de la oferta*, elige **SBC destino = sbc-local-dev**;
   - carga las partidas y elige la modalidad;
   - pasa la oferta a **Enviada → Ganada**. Se publica sola en el MCP.
2. **Control de Proyecto** (:8080), pestaña **Contrato (04) → Ofertas recibidas del MCP**:
   - pulsa **Buscar ahora en el MCP**; si no, llega en el próximo latido (30 s);
   - pulsa **Crear contrato**: pide el proyecto (el actual o uno nuevo) y ofrece registrar el cliente por RIF si falta;
   - se abre **Nuevo contrato** prellenado: completa número y monto del documento firmado y pulsa **Crear contrato**.
3. **Sistema de Cotización:** la oferta queda **vinculada sola**, con proyecto y contrato. Se actualiza cada 15 s, o con **Consultar acuse**.

Si no hay MCP (sin `MCP_URL`), la tarjeta muestra la **descarga manual**: *Contingencia* en el flujo de abajo.

### Prueba automática por el MCP
Requiere los tres nodos **recién creados** (bases de datos nuevas) y enrolados.

```bash
cd Pruebas/integracion_mcp
../../Backend/.venv/bin/python preparar.py /tmp/mcp   # oferta ganada → publicada en el MCP
node flujo_mcp.js /tmp/mcp                           # bandeja del SBC → contrato → vinculación en Cotización
```

Resultado esperado:
```
frentes en Valuaciones de CP: Todos los frentes | ELECTRICIDAD | MECÁNICA
Cotización: Proyecto ori-2026-09-001 · contrato 4600012345 · … · confirmado por el MCP
errores JS: ninguno
```

## Contingencia: descarga manual (sin MCP)

### Flujo manual
1. **Sistema de Cotización:** con la oferta **Ganada**, abre *Contingencia* en la tarjeta de traspaso y pulsa **Descargar traspaso**.
2. **Control de Proyecto:** en **Clientes (12)** registra la empresa con el mismo RIF. Luego pulsa **Nuevo contrato** y, en **Importar respaldo de oferta → Archivo de oferta**, sube el archivo y guarda.
3. **Sistema de Cotización:** registra a mano la vinculación, o que la importación falló.

### Prueba automática de la contingencia
Requiere Cotización y Control de Proyecto **recién creados** y Playwright.

```bash
cd Pruebas/integracion_control_proyecto
../../Backend/.venv/bin/python preparar.py /tmp/cruce
node importar_cp.js /tmp/cruce
```

`preparar.py` (de las dos pruebas) cambia la clave temporal de los **admin** y les activa el 2FA:
- las claves nuevas se toman de `COT_CLAVE` y `CP_CLAVE`;
- los secretos TOTP quedan en `estado.json`.

Úsalo solo en desarrollo.

### Reiniciar desde cero

```bash
Instalacion/desarrollo/detener.sh
../oriol-control-de-proyecto/Instalacion/desarrollo/detener.sh
../oriol-control-de-proyecto/Instalacion/desarrollo/detener-master.sh
rm -f Backend/sistema_cotizacion.db ../oriol-control-de-proyecto/Backend/control_proyecto.db \
      ../oriol-control-de-proyecto/Backend/control_proyecto_master.db ../oriol-control-de-proyecto/Backend/data/sbc_enlace.json
sed -i '/^MCP_/d' Backend/.env      # luego: levantar-con-control-proyecto.sh y enrolar-mcp-local.sh
```

## Observado al probar con Control de Proyecto 1.5.2.11
- **El proyecto sigue en estado `oferta` tras importar.** El frontend de Control de Proyecto lo pasa a `contrato` en memoria, pero `PUT /proyectos/{id}` (`ProyectoCtrlUpdate`) no recibe `estado`. Es un comportamiento de Control de Proyecto, independiente del traspaso.
- **El bloque `origen` se conserva** dentro de `proyecto.master`. Con la rama `claude/traspaso-mcp`, además, el contrato guarda `codigo_oferta` y avisa si la oferta ya está en otro proyecto.
- **Error de arranque de Control de Proyecto en equipos sin el comando `ip`**, por ejemplo algunos contenedores. Su `levantar.sh` termina con error antes de avisar "listo", aunque los servicios quedan arriba. Compruébalo con `Instalacion/desarrollo/estado.sh`.
