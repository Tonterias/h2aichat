# execution/smoke/ — Comprobaciones manuales (smoke)

Verificaciones rápidas y **manuales** de la interfaz, con Playwright. **NO** son la
suite de tests del CI (esa está en `execution/tests/` y se ejecuta sola y bloquea el
deploy si falla). Estos se lanzan **a mano** cuando quieres ver con tus ojos que algo
concreto funciona.

## Cómo ejecutarlos
**Siempre desde la raíz del proyecto** (usan rutas relativas a `execution/`):

```bash
python execution/smoke/smoke_admin_config.py
```

Cada script arranca un servidor local en su propio puerto, hace la comprobación,
imprime un resumen y deja una **captura `.png`** en esta carpeta (ignorada por git).

## Qué comprueba cada uno
| Script | Comprueba |
|---|---|
| `smoke_admin_config.py` | Pantalla de configuración del sistema en `/admin` (campos, timeout/delay, perfiles). |
| `smoke_free_models.py`  | Qué IAs ve un usuario del plan **FREE** en su engranaje. |
| `smoke_admin_users.py`  | Tabla de usuarios en `/admin` (desplegables de plan, packs). |
| `smoke_user_gear.py`    | Que el **engranaje** del usuario (modal de preferencias) abre bien. |
| `smoke_plans.py`        | La card de planes. |

## Requisitos
```bash
pip install playwright && playwright install
```
