# Instalación local — Sistema de Cotización

Usa el mismo esquema de desarrollo que Control de Proyecto (`Instalacion/desarrollo/` de `oriol-control-de-proyecto`). Los puertos son distintos para que **ambos sistemas convivan en la misma PC**:

| Sistema | Frontend | API |
|---|---|---|
| Sistema de Cotización | http://127.0.0.1:8090 | :8100 |
| Control de Proyecto | http://127.0.0.1:8080 | :8000 |
| MASTER CONTROL PROJECT | http://127.0.0.1:8081 | :8001 |

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

## Los dos sistemas juntos (para probar el traspaso)

Clona `oriol-control-de-proyecto` **al lado** de este repositorio, o indica su ruta con `CONTROL_PROYECTO_DIR`. Luego ejecuta:

```bash
Instalacion/desarrollo/levantar-con-control-proyecto.sh
```

Esto levanta el Sistema de Cotización y, con el script propio de Control de Proyecto (`Instalacion/desarrollo/levantar.sh`), también Control de Proyecto. Cada uno queda con su propia base de datos y sus propias cuentas.

### Flujo manual
1. **Sistema de Cotización:** crea la oferta, cargas las partidas, eliges la modalidad y la pasas a **Enviada → Ganada**. Luego pulsas **Descargar traspaso**.
2. **Control de Proyecto:** en **Clientes (12)** registra la empresa con el mismo RIF. Luego elige o crea el proyecto y pulsa **Nuevo contrato**:
   - **Empresa del contrato** = esa empresa;
   - **Tipo de contrato** = el que corresponda;
   - en **Importar respaldo de oferta → Archivo de oferta** sube el archivo descargado;
   - pulsa **Crear contrato**.
3. En **Valuaciones** de Control de Proyecto aparecen los frentes de la oferta: uno por disciplina, o `GLOBAL` / `SUMINISTRO` según la modalidad.
4. **Sistema de Cotización:** registra la vinculación con el ID del proyecto y el número de contrato.

### Prueba automática del traspaso
Requiere los dos ambientes **recién creados** (bases de datos nuevas) y Playwright.

```bash
cd Pruebas/integracion_control_proyecto
../../Backend/.venv/bin/pip install pyotp        # si falta (viene con requirements.txt)
../../Backend/.venv/bin/python preparar.py /tmp/cruce   # oferta ganada + cliente y proyecto en CP
node importar_cp.js /tmp/cruce                           # importa con el formulario real de CP
```

Resultado esperado:
```
frentes en Valuaciones de CP: Todos los frentes | ELECTRICIDAD | MECÁNICA
errores JS en CP: ninguno
```

`preparar.py` hace dos cosas sobre las cuentas **admin** de las dos instancias:
- cambia la clave temporal: a `COT_CLAVE` en Cotización (por defecto `Cotizacion.Admin.2026`) y a `CP_CLAVE` en Control de Proyecto (por defecto `ControlProyecto.Admin.2026`);
- activa el 2FA. Los secretos TOTP quedan en `estado.json`.

Úsalo solo en desarrollo.

### Reiniciar desde cero

```bash
Instalacion/desarrollo/detener.sh
../oriol-control-de-proyecto/Instalacion/desarrollo/detener.sh
rm -f Backend/sistema_cotizacion.db ../oriol-control-de-proyecto/Backend/control_proyecto.db
```

## Observado al probar con Control de Proyecto 1.5.2.11
- **El proyecto sigue en estado `oferta` tras importar.** El frontend de Control de Proyecto lo pasa a `contrato` en memoria, pero `PUT /proyectos/{id}` (`ProyectoCtrlUpdate`) no recibe `estado`. Es un comportamiento de Control de Proyecto, independiente del traspaso.
- **El bloque `origen` se conserva** dentro de `proyecto.master`, aunque Control de Proyecto todavía no lo lea (ING-COT-003 §8.3).
- **Error de arranque de Control de Proyecto en equipos sin el comando `ip`**, por ejemplo algunos contenedores. Su `levantar.sh` termina con error antes de avisar "listo", aunque los servicios quedan arriba. Compruébalo con `Instalacion/desarrollo/estado.sh`.
