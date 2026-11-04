![FaultCase — From fault to case](docs/img/banner.svg)

[![Python 3.11](https://img.shields.io/badge/python-3.11-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Tests](https://github.com/dochavez/faultcase/actions/workflows/tests.yml/badge.svg)](https://github.com/dochavez/faultcase/actions)
[![Built with Muse Spark Open](https://img.shields.io/badge/Built_with-Muse_Spark_Open-purple)](https://www.meta.ai/)

[Read in English](README.md)

**Idea en una línea:** FaultCase convierte los fallos repetidos de un equipo con Windows 10 u 11 (portátil o de escritorio) en un caso de garantía listo para enviar al fabricante.

![Flujo completo: recopilación → diagnóstico → acción](docs/img/flow.gif)

## Índice

- [Una noche frente a un minuto](#una-noche-frente-a-un-minuto)
- [El problema](#el-problema)
- [Pruébalo en 1 minuto](#pruébalo-en-1-minuto)
- [Capturas de pantalla](#capturas-de-pantalla)
- [Cómo funciona](#cómo-funciona)
- [Modelos y proveedores](#modelos-y-proveedores)
- [Cómo trabajan juntos Muse, Baseten y Fireworks](#cómo-trabajan-juntos-muse-baseten-y-fireworks)
- [Cómo se construyó con Muse Code](#cómo-se-construyó-con-muse-code)
- [Privacidad y seguridad](#privacidad-y-seguridad)
- [Decisiones de diseño](#decisiones-de-diseño)
- [Limitaciones](#limitaciones)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Ejecutar las pruebas](#ejecutar-las-pruebas)
- [Configuración](#configuración)
- [Hoja de ruta](#hoja-de-ruta)
- [Preguntas frecuentes](#preguntas-frecuentes)
- [Licencia](#licencia)
- [Agradecimientos](#agradecimientos)

## Una noche frente a un minuto

Llegar a la conclusión del caso de demostración a mano tomó una noche entera. FaultCase hace el mismo trabajo desde una sola carga de archivos:

| Hecho a mano (una noche) | FaultCase (alrededor de un minuto) |
|---|---|
| Filtrar el Visor de eventos por eventos 41 / 6008 de Kernel-Power | `filters/device-diagnostics.xml` + `adapters/windows/evtx.py` |
| Ejecutar WinDbg `!analyze -v` en 4 volcados de memoria | `adapters/windows/windbg.py` (o `cdb.exe` local) |
| Comparar cubos de fallo y marcas de tiempo de controladores entre volcados | `rules.py`: `same_module`, `persists_across_driver_versions` |
| Contar incidentes, congelamientos y meses de historial | Bloque de resumen de `rules.py` (determinista, con pruebas) |
| Averiguar el modelo exacto de la laptop y la BIOS | Exportación de msinfo32 o lectura CIM local |
| Redactar el informe para el fabricante en dos idiomas | Redactor de casos con Muse Spark, EN + ES |

## El problema

Cuando una laptop nueva se reinicia sola una y otra vez, el problema cae entre tres empresas: Microsoft es dueña del sistema operativo, NVIDIA del controlador y Lenovo de la garantía. Cada una solo ve su propia parte. El usuario termina con fotos borrosas de un pantallazo azul y un equipo de soporte que le pide datos que no sabe dónde encontrar.

Este proyecto nació de un caso real: una Lenovo Legion Pro 7 16IAX10H (tipo de máquina 83F5, GPU NVIDIA, comprada en enero de 2026) con 6 incidentes en 6 meses (del 2026-04-22 al 2026-10-23). Cuatro fallos dejaron volcados de memoria, todos culpando a `nvlddmkm.sys` en dos compilaciones distintas del controlador (2026-03-04 y 2026-02-14); otros dos congelamientos no dejaron ningún volcado. Ese caso real anonimizado se incluye como la demostración de un clic.

## Pruébalo en 1 minuto

**Demostración en vivo:** [https://dochavez--faultcase-fastapi-app.us-east.modal.run/](https://dochavez--faultcase-fastapi-app.us-east.modal.run/)

Abre la URL de demostración y haz clic en **Try a sample case**: sin cuenta, sin código de invitación, instantáneo y gratis (el caso de demostración está precalculado; ver `scripts/build_demo_case.py`).

O ejecútalo localmente (Python 3.11, sin claves de API para la demo):

**Windows (PowerShell):**

```powershell
git clone https://github.com/dochavez/faultcase.git
cd faultcase
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env   # fill in API keys only for new diagnoses, not for the demo
uvicorn faultcase.app:app --reload
```

**macOS / Linux:**

```bash
git clone https://github.com/dochavez/faultcase.git
cd faultcase
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in API keys only for new diagnoses, not for the demo
uvicorn faultcase.app:app --reload
```

Después abre http://127.0.0.1:8000 y haz clic en **Try a sample case**.

<details>
<summary>Analiza tu propia laptop Windows</summary>

1. Abre la aplicación y haz clic en **Download device-diagnostics.xml** (paso 1 de la pantalla de recopilación).
2. En tu laptop: Visor de eventos → Acción → **Import Custom View…** → selecciona el archivo descargado.
3. Acción → **Save All Events in Custom View As…** → guarda el archivo `.evtx`.
4. De vuelta en la aplicación, sube el `.evtx` (máx. 20 MB) con tu código de invitación. Opcionalmente añade una exportación de msinfo32 (Windows + R → `msinfo32` → Archivo → Exportar), un informe de batería (`powercfg /batteryreport` en el Terminal), marca **Also analyze my memory dumps** si tienes `cdb.exe` y derechos de administrador, o deja que la aplicación lea los datos del equipo directamente en una ejecución local en Windows.
5. Lee el diagnóstico y abre la pantalla de acción para ver el informe para el fabricante (inglés/español), la lista de verificación previa al reclamo y el paquete de evidencias.

</details>

## Capturas de pantalla

**Recopilar**: etiqueta Windows 10/11, guía paso a paso del Visor de eventos con capturas, archivos obligatorios y opcionales, caso de ejemplo:

![Pantalla de recopilación](docs/img/collect-es.png)

**Diagnóstico**: tarjeta del veredicto con el problema principal y dos caminos (*Intentar solucionarlo primero* o *Preparar mi caso de garantía*), 8 tarjetas de estado por componente, gráfico de reinicios por mes, línea de tiempo, *Explicar con Muse* y detalles técnicos para el técnico del fabricante:

![Pantalla de diagnóstico](docs/img/diagnosis-es.png)

**Explicar con Muse**: a petición, Muse Spark convierte los hechos contados en palabras sencillas: qué significa cada hallazgo, qué hacer, próximos pasos y un glosario:

![Explicar con Muse](docs/img/explain-es.png)

**Intentar solucionarlo primero**: a petición, Muse Spark convierte las soluciones seguras de los playbooks para los componentes con problemas en un plan ordenado (por qué, cómo, minutos, riesgo, cómo comprobar, cuándo parar). Los pasos marcados se añaden al informe para el fabricante en el navegador:

![Intentar solucionarlo primero](docs/img/fix-es.png)

**Acción**: qué hacer ahora (con el enlace de soporte del fabricante), informe EN/ES, lista previa, ZIP de evidencias y número de serie rellenado solo en el navegador:

![Pantalla de acción](docs/img/action-es.png)

Versiones en inglés: [collect-en.png](docs/img/collect-en.png), [diagnosis-en.png](docs/img/diagnosis-en.png), [explain-en.png](docs/img/explain-en.png), [fix-en.png](docs/img/fix-en.png), [action-en.png](docs/img/action-en.png). Se regeneran con `python scripts/screenshots.py` (herramientas de desarrollo: `pip install playwright pillow` y `playwright install chromium`; solo el caso de ejemplo, sin llamadas a modelos).

## Cómo funciona

Tres pantallas (FastAPI + Jinja2 + HTMX, inglés/español): **recopila** la evidencia, lee el **diagnóstico** y actúa en la pantalla de **acción**. Python hace todos los conteos; los modelos de Meta solo interpretan y redactan.

![Arquitectura de FaultCase](docs/img/diagrams/architecture-es.png)

Lo que hace el núcleo determinista antes de llamar a cualquier modelo:

- **Lee** cada registro con `python-evtx`, incluido el nivel del evento de Windows (crítico, error, advertencia, información).
- **Normaliza** contra 8 playbooks (`playbooks/*.yaml`): estabilidad, almacenamiento, hardware, temperatura, Wi-Fi, USB, batería y software. Solo los eventos de estabilidad forman incidentes: 41 y 6008 a menos de 60 s, y un informe 1001 a menos de 15 min de su 41.
- **Ignora ruido conocido** con reglas explícitas: dispositivos virtuales de Hyper-V o de software (`ROOT\`, `SWD\`), el controlador WUDFRd, el evento 6062 del Wi-Fi Intel, desconexiones de Wi-Fi iniciadas por el usuario o el sistema, NTFS 98 informativo, corrupción en copias de sombra de volumen y actualizaciones correctas.
- **Calcula** patrones etiquetados como `fact` o `hypothesis`, un estado por componente (problema, requiere atención, sin problemas, sin datos) y un resumen exacto (incidentes, fechas, meses, volcados, dirección del controlador).
- **Compacta** la carga: por componente, conteos y como máximo 20 eventos representativos anonimizados, con un tope de 30k tokens.

En la exportación real anonimizada esto convierte 7.159 eventos en una petición de ~9,5k tokens:

![De una exportación real a un caso](docs/img/diagrams/pipeline-es.png)

Una subida, de principio a fin:

![Una petición de principio a fin](docs/img/diagrams/request-es.png)

## Modelos y proveedores

| Rol | Modelo | Proveedor |
|---|---|---|
| Análisis técnico de la evidencia | Muse Spark Open | Baseten y Fireworks en paralelo (segunda opinión) |
| Redacción del caso EN/ES y resumen para el usuario | Muse Spark (`muse-spark-1.1`) | Meta Model API (Fireworks de respaldo) |
| *Explicar con Muse*: explicación sencilla a petición | Muse Spark (`muse-spark-1.1`) | Meta Model API (Fireworks de respaldo) |
| *Intentar solucionarlo primero*: plan de autoayuda con las soluciones seguras de los playbooks, a petición | Muse Spark (`muse-spark-1.1`) | Meta Model API (Fireworks de respaldo) |
| Construcción de este proyecto | Muse Code | Terminal |

Las rutas viven en `config/providers.yaml`: `evidence_analysis: [baseten, fireworks]`, `case_writing: [meta, fireworks]`, `explanation: [meta, fireworks]`, `fix_plan: [meta, fireworks]`.

- **Segunda opinión.** Ambos proveedores de pesos abiertos analizan los mismos hallazgos redactados al mismo tiempo. Si el veredicto y la confianza coinciden, se conservan; si difieren, la confianza baja un nivel y se añade un hallazgo de tipo `hypothesis`. Si un proveedor falla, o responde más de 60 s después del primero (`second_opinion_wait_seconds`), se continúa con la opinión disponible. Se alterna con `analysis_mode: second_opinion | single`.
- **Caché de prompts.** Cada solicitud pone primero el contenido estático (prompt del sistema, reglas de playbooks, claves de salida) y los datos del caso al final, para que los proveedores reutilicen los prefijos en caché. Los tokens en caché se leen de `usage.prompt_tokens_details` y se registran en `logs/usage.jsonl`.
- **Solicitudes de cobertura (hedged).** Si el proveedor principal tarda más de `hedge_after_seconds` (25 por defecto), se inicia el siguiente proveedor y gana la primera respuesta válida; una línea `hedge` registra al ganador.
- **Esfuerzo de razonamiento por rol.** `medium` en ambos roles (omitido para el análisis en Baseten, cuya generación restringida se bloquea con él); los parámetros rechazados se reintentan una vez sin ellos y se recuerdan durante la sesión.
- **Límites de completado.** `max_tokens` por rol (16384 análisis, 24576 redacción, 8192 explicación y plan de solución; los dos primeros medidos desde los completados exitosos más grandes más un margen). `finish_reason == "length"` se registra como `truncated` y se reintenta una vez.

### Benchmark (medido el 2026-11-02)

`scripts/benchmark.py` ejecuta `build_case` 3 veces en el caso real más 6 casos sintéticos (`fixtures/synthetic/`: laptop sana, fallo de disco, fallo aislado, Wi-Fi, USB, batería). Resultados completos: [docs/benchmark.md](docs/benchmark.md).

| Provider | Role | Calls ok/total | Correct | p50 ms | p95 ms | Prompt | Compl | Cached | Est. cost | Fallbacks | Hedge wins |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseten | evidence_analysis | 21/21 | 100% (21/21) | 19975 | 26104 | 46611 | 59619 | 28928 | $0.5268 | 0 | 0 |
| fireworks | evidence_analysis | 21/21 | 100% (21/21) | 16465 | 31516 | 46590 | 36432 | 32128 | $0.3364 | 0 | 0 |
| meta | case_writing | 21/21 | 100% (21/21) | 12347 | 16926 | 50314 | 80466 | 26467 | $1.0570 | 0 | 0 |

Tasa de acuerdo de la segunda opinión: **71%** (15/21 ejecuciones con dos opiniones). Totales: 21 ejecuciones, 0 coberturas, $1.9202 estimados (precios de ejemplo en `config/providers.yaml`).

<details>
<summary>Cómo se juzga la corrección</summary>

El veredicto final del caso real debe estar en `acceptable_verdicts` de `fixtures/real_case/expected.json`. Cada otro veredicto acierta cuando contiene una palabra clave esperada (sin distinguir mayúsculas); las listas de palabras clave viven en `fixtures/synthetic/*.json`. Solo se guardan veredictos y métricas, nunca claves de API ni datos personales.

</details>

## Cómo trabajan juntos Muse, Baseten y Fireworks

![Cómo trabajan juntos Muse, Baseten y Fireworks](docs/img/diagrams/integration-es.png)

*Explicar con Muse*, a petición y en caché:

![Secuencia de Explicar con Muse](docs/img/diagrams/explain-es.png)

Resiliencia: qué pasa en cada fallo y qué ve el usuario:

![Qué pasa cuando algo falla](docs/img/diagrams/resilience-es.png)

Fuentes de los diagramas: `docs/diagrams/` (se regeneran con `python docs/diagrams/build_diagrams.py` y `mmdc`).

## Cómo se construyó con Muse Code

Cada función siguiente es un commit revisado, construido con Muse Code (agente de terminal), según `git log`:

| Commit | Función |
|---|---|
| [`bf8c73d`](https://github.com/dochavez/faultcase/commit/bf8c73d) | Set up environment and package skeleton |
| [`a58ac1e`](https://github.com/dochavez/faultcase/commit/a58ac1e) | Add provider smoke test |
| [`c8b765c`](https://github.com/dochavez/faultcase/commit/c8b765c) | Add Windows adapter: evtx and WinDbg parsers |
| [`723de43`](https://github.com/dochavez/faultcase/commit/723de43) | Add normalization and redaction |
| [`b673bbb`](https://github.com/dochavez/faultcase/commit/b673bbb) | Add rules engine and golden real-case test |
| [`3ca3e26`](https://github.com/dochavez/faultcase/commit/3ca3e26) | Add model router with fallback |
| [`e462f40`](https://github.com/dochavez/faultcase/commit/e462f40) | Add case-building agent |
| [`3d3bbc2`](https://github.com/dochavez/faultcase/commit/3d3bbc2) | Add three-screen web app |
| [`cf17104`](https://github.com/dochavez/faultcase/commit/cf17104) | Add Modal deployment |
| [`99b012c`](https://github.com/dochavez/faultcase/commit/99b012c) | Add local minidump analysis |
| [`13ba425`](https://github.com/dochavez/faultcase/commit/13ba425) | Serve precomputed demo case |
| [`5392efa`](https://github.com/dochavez/faultcase/commit/5392efa) | Add msinfo32 export parser |
| [`c3a3812`](https://github.com/dochavez/faultcase/commit/c3a3812) | Read device details locally with CIM queries |
| [`ef0cb2e`](https://github.com/dochavez/faultcase/commit/ef0cb2e) | Add browser-only serial number field |
| [`bc55cd8`](https://github.com/dochavez/faultcase/commit/bc55cd8) | Add cross-provider second opinion for evidence analysis |
| [`1789446`](https://github.com/dochavez/faultcase/commit/1789446) | Order prompts for caching and log cached tokens |
| [`15733e0`](https://github.com/dochavez/faultcase/commit/15733e0) | Add hedged requests |
| [`dd19a0a`](https://github.com/dochavez/faultcase/commit/dd19a0a) | Configure reasoning effort per role |
| [`aaf89fd`](https://github.com/dochavez/faultcase/commit/aaf89fd) | Add provider benchmark and results |
| [`bc56b7e`](https://github.com/dochavez/faultcase/commit/bc56b7e) | Compare second opinions on enum verdicts |
| [`289912f`](https://github.com/dochavez/faultcase/commit/289912f) | Cap completion length and detect truncation |
| [`7c2a89c`](https://github.com/dochavez/faultcase/commit/7c2a89c) | Make Baseten analysis reliable |
| [`eaf9b3f`](https://github.com/dochavez/faultcase/commit/eaf9b3f) | Add Wi-Fi playbook with verified event IDs |
| [`870c344`](https://github.com/dochavez/faultcase/commit/870c344) | Add USB playbook with verified event IDs |
| [`4381749`](https://github.com/dochavez/faultcase/commit/4381749) | Add battery playbook, parser and upload |
| [`36acb22`](https://github.com/dochavez/faultcase/commit/36acb22) | Add component fixtures, benchmark cases and golden tests |
| [`8152610`](https://github.com/dochavez/faultcase/commit/8152610) | Group diagnosis by component, report sections per component |
| [`de72d48`](https://github.com/dochavez/faultcase/commit/de72d48) | On-demand explanation backend: `explain_case`, `prompts/explainer.md`, `explanation` route |

La **regla de la prueba dorada** mantuvo honesto al agente: `fixtures/real_case/expected.json` define las conclusiones que el sistema debe alcanzar y nunca debe editarse para que las pruebas pasen (`tests/test_real_case.py` verifica cada campo; la prueba en vivo verifica el veredicto, la confianza y las afirmaciones prohibidas).

<details>
<summary>Dos ejemplos reales de prompts (recortados, originales en inglés)</summary>

> Add automatic device identification so reports show the real model of the computer being analyzed. […] 1. Parser. Create `faultcase/adapters/windows/msinfo.py` that parses a System Information export (msinfo32 > File > Export […] often UTF-16 with BOM; detect the encoding). […] Never extract or keep the user name or computer name. […] 4. Serial number in the web version: on the Action screen add a "Serial number (optional)" field that replaces `{{SERIAL}}` […] using JavaScript in the browser only. The serial must never be sent to the server. […]

> Make better use of both open-weights providers and measure it. […] 1. Second opinion. For the evidence_analysis role, call Baseten and Fireworks in parallel […]. Compare verdicts: if they agree, keep the confidence; if they disagree, lower confidence by one level and add a finding of type "hypothesis" […]. 5. Benchmark. Create `scripts/benchmark.py` that runs build_case N times (default 3) on the real case plus 3 synthetic cases […] For each provider and role record: verdict correctness […], latency p50 and p95, […] estimated cost using the prices in providers.yaml […], fallback and hedge counts, and second-opinion agreement rate. […]

</details>

## Privacidad y seguridad

Cada garantía está respaldada por una prueba:

| Garantía | Respaldada por |
|---|---|
| Nombres de usuario y de equipo, MACs y correos eliminados del texto | `test_redact_text_removes_personal_data` |
| Ningún dato personal ni número de serie llega a los modelos | `test_personal_data_and_serial_never_reach_models` |
| El número de serie se sustituye localmente, solo si se proporciona | `test_serial_replaced_locally_only_when_provided` |
| El campo web de número de serie nunca envía nada al servidor | `test_serial_canary_never_reaches_server` |
| Las cargas de datos del equipo se redactan antes de usarse | `test_build_device_redacts_personal_data` |
| El ZIP de evidencias nunca contiene `.evtx`/`.dmp` crudos | `test_demo_flow_uses_precomputed_file` |
| Los modelos reciben conteos y ≤ 20 eventos por componente, nunca el registro crudo (tope de 30k tokens) | `test_twenty_thousand_events_fit_the_token_budget` |
| *Explicar con Muse* recibe solo hallazgos anonimizados | `test_explain_case_sends_only_redacted_findings` |
| *Intentar solucionarlo primero* solo adapta soluciones seguras de los componentes con problemas | `test_fix_plan_uses_only_safe_fixes_of_involved_components` |
| Los eventos inofensivos conocidos nunca cuentan como fallos | `test_known_benign_events_are_not_counted` |
| Los identificadores de cubo de fallo se eliminan del informe | `test_strip_bucket_ids_from_reports` |
| Solo los campos analizados salen del análisis local de volcados | `test_analyze_dump_returns_only_parsed_fields` |
| El registro de uso nunca guarda prompts ni claves | `test_baseten_fails_fireworks_answers` |

Además: solo lectura (el producto nunca modifica el sistema del usuario), cargas procesadas en memoria o en una carpeta temporal y eliminadas justo después, y claves de API enmascaradas a sus últimos 4 caracteres dondequiera que se muestren.

## Decisiones de diseño

- **Primero las reglas deterministas.** Los conteos, fechas, códigos y patrones se calculan en Python con `rules.py` desde `playbooks/*.yaml`. Los modelos interpretan y redactan; nunca cuentan ni inventan datos.
- **Salida estructurada.** Cada respuesta de un modelo se valida contra un esquema JSON; si falla, el enrutador reintenta una vez y pasa al siguiente proveedor.
- **No es un chatbot.** Tres pantallas, un flujo: recopilación → diagnóstico → acción. Sin conversación abierta.
- **No analiza imágenes.** La evidencia son registros de eventos, resúmenes de volcados e información del sistema, nunca fotos.
- **Hecho frente a hipótesis.** Cada conclusión lleva su etiqueta; la correlación con transiciones de energía, por ejemplo, siempre es una hipótesis.
- **El usuario decide y envía.** El producto prepara evidencias y borradores; no da asesoría legal.

## Limitaciones

- Solo Windows 10 y 11 (portátiles y de escritorio). `faultcase/adapters/` solo tiene `windows/`; Linux y macOS necesitan sus propios adaptadores y playbooks, no solo instrucciones. La app se lo avisa a quien entra desde macOS o Linux.
- Un `.evtx` sin volcados de memoria da un caso más débil (los congelamientos sin volcado se reportan como tales).
- Los hallazgos de Wi-Fi y USB necesitan una exportación hecha con el filtro actual (canales WLAN-AutoConfig y Kernel-PnP); las exportaciones antiguas simplemente muestran esos componentes como sanos.
- Los hallazgos de batería necesitan el HTML de `powercfg /batteryreport` (subido, o generado localmente en Windows); sin él, el informe lo dice.
- El mismo cubo o hash de fallo significa la misma *categoría* de fallo; no prueba el mismo defecto que en otras máquinas (una prueba en vivo afirma que el texto nunca dice eso).
- Los casos viven en memoria: un reinicio o 20 minutos sin uso los borra (a propósito, por privacidad).
- La salida en vivo de los modelos varía entre ejecuciones; la demo está precalculada para ser instantánea, gratis y estable.

## Estructura del proyecto

```
faultcase/                 # Paquete Python
  adapters/windows/        # evtx, windbg, fixture_events, msinfo, wmi, cdb (solo local)
  app.py                   # FastAPI, 3 pantallas + /demo
  agent.py                 # hallazgos → análisis (Baseten/Fireworks) → caso (Meta)
  normalize.py             # eventos crudos → schemas/evidence.schema.json
  redact.py                # eliminación de datos personales
  rules.py                 # playbooks → hallazgos deterministas
  router.py                # proveedores con respaldo, cobertura y registro de uso
  demo.py / i18n.py        # demo precalculada, cadenas EN/ES
templates/ static/         # páginas Jinja2, CSS, capturas de la guía del Visor de eventos
config/                    # providers.yaml (rutas, roles, precios)
filters/ playbooks/        # device-diagnostics.xml; disk/hardware/software/stability/thermal/wifi/usb/battery
prompts/ schemas/          # evidence_analysis.md, case_writer.md, explainer.md, fix_planner.md; esquemas evidence/case
fixtures/                  # real_case/, synthetic/, msinfo/
scripts/                   # smoke_test.py, build_demo_case.py, benchmark.py, screenshots.py
tests/                     # suite pytest (las pruebas en vivo necesitan claves)
docs/                      # benchmark.md/.json, img/, diagrams/ (fuentes)
modal_app.py               # despliegue en Modal
```

## Ejecutar las pruebas

```bash
pytest            # suite completa, sin red ni claves de API
pytest -m live    # construye el caso real con modelos reales (necesita claves en .env)
```

## Configuración

`.env` (ver `.env.example`): `META_API_KEY`, `BASETEN_API_KEY`, `FIREWORKS_API_KEY`, `BASETEN_MODEL` (por defecto `meta-models/muse-spark-open-1026`), `INVITE_CODE` (opcional: si existe, las cargas y la regeneración de la demo lo piden; si está vacío el campo no aparece y los análisis en vivo se limitan con `UPLOADS_PER_HOUR`, 6 por visitante por defecto, y `UPLOADS_PER_DAY`, 60 por defecto).

<details>
<summary>Referencia de <code>config/providers.yaml</code></summary>

- `providers.*`: `base_url`, `api_key_env`, `model`/`model_env`, precios de ejemplo `price_per_1k_*`.
- `routes`: `evidence_analysis: [baseten, fireworks]`, `case_writing: [meta, fireworks]`, `explanation: [meta, fireworks]`, `fix_plan: [meta, fireworks]`.
- `roles.*`: `analysis_mode` (`second_opinion` para análisis, `single` para redacción), `reasoning_effort` (`medium`, omitido para el análisis en Baseten), `max_tokens` (16384/24576/8192), `second_opinion_wait_seconds: 60`.
- `settings`: `timeout_seconds: 90`, `max_retries_per_provider: 1`, `hedge_after_seconds: 25`, `log_usage: true`.

</details>

## Hoja de ruta

- Más playbooks (Bluetooth, impresoras).
- Adaptadores para Linux y macOS.
- Ejecuciones de benchmark más grandes con más casos sintéticos.

## Preguntas frecuentes

**¿Necesito claves de API?**
No para la demo (`/demo` sirve un caso precalculado). Sí en `.env` para nuevos diagnósticos y `pytest -m live`.

**¿Qué datos salen de mi máquina?**
Solo hallazgos redactados: conteos, códigos, fechas, nombres de controladores. Los volcados de memoria nunca salen de la máquina, y el número de serie se inserta solo en el navegador.

**¿Por qué dos modelos para un análisis?**
Baseten y Fireworks analizan la misma evidencia de forma independiente; el acuerdo conserva la confianza, el desacuerdo la baja y lo dice. El benchmark mide a ambos (actualmente 71% de acuerdo, 15/21).

**¿Solo Windows?**
Sí: equipos con Windows 10 y 11, portátiles y de escritorio (el informe de batería solo aplica a portátiles). La evidencia es propia de Windows (`.evtx`, WinDbg, msinfo32, CIM, `powercfg`), pero el análisis funciona en cualquier sistema: el servidor en Modal y CI corren en Linux. Linux y macOS están en la hoja de ruta como adaptadores aparte.

**¿Muse me puede ayudar a resolverlo sin abrir un ticket?**
Sí: *Intentar solucionarlo primero* da un plan ordenado construido solo con las soluciones seguras de FaultCase para tus hallazgos (controlador del fabricante, BIOS, diagnóstico de hardware, prueba sin suspensión, ajuste de energía del Wi-Fi…), con cuánto tarda cada paso y cómo saber si funcionó. Tú haces cada paso; FaultCase nunca cambia tu equipo. Si la evidencia apunta a hardware lo dice, y los pasos que marcaste pasan al informe de garantía.

**¿Qué hace "Explicar con Muse"?**
A petición, Muse Spark lee los hechos contados (nunca el registro crudo) y los explica con palabras sencillas: qué significa cada hallazgo, qué hacer, los próximos pasos y un glosario para los detalles técnicos. Se ejecuta una vez por caso e idioma y se guarda; el caso de ejemplo la trae precalculada.

**¿Quién envía el informe al fabricante?**
Tú. FaultCase prepara el paquete de evidencias y el borrador bilingüe; no actúa en tu nombre.

## Licencia

Código: MIT (ver [LICENSE](LICENSE)). Muse Spark Open se usa bajo la Muse Model License, que exige mostrar "Built with Muse Spark Open" en el producto.

## Agradecimientos

A Meta por los modelos Muse y el acceso API del hackathon, a Baseten y Fireworks por servir Muse Spark Open, y a los mantenedores de `python-evtx` por el análisis multiplataforma de registros de eventos.

