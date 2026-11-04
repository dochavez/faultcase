"""Render the README diagrams (EN + ES) from HTML/CSS to PNG with Playwright.

Usage: python docs/diagrams/build_diagrams.py
Writes docs/img/diagrams/<name>-<lang>.png. Numbers in the pipeline diagram
come from one real anonymized export (counts only, no event content).
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "img" / "diagrams"

CSS = """
* { box-sizing: border-box; }
body { margin: 0; background: #fff; font-family: Inter, 'Segoe UI', Helvetica, Arial, sans-serif; color: #0f172a; }
.canvas { width: 1500px; padding: 36px 40px 40px; }
h1 { font-size: 30px; margin: 0 0 6px; letter-spacing: -0.01em; }
.sub { font-size: 19px; color: #475569; margin: 0 0 26px; }
.band { border: 2px solid var(--b); background: var(--bg); border-radius: 16px; padding: 16px 18px 18px; }
.band-title { font-size: 17px; font-weight: 800; text-transform: uppercase; letter-spacing: .06em; color: var(--b); margin: 0 0 12px; display: flex; gap: 10px; align-items: center; }
.band-title .tag { font-size: 14px; text-transform: none; letter-spacing: 0; font-weight: 700; background: #fff; border: 1.5px solid var(--b); border-radius: 999px; padding: 2px 10px; }
.row { display: flex; gap: 14px; align-items: stretch; }
.card { flex: 1; background: #fff; border: 1.5px solid #cbd5e1; border-radius: 12px; padding: 12px 14px; box-shadow: 0 1px 2px rgba(15,23,42,.06); }
.card b { display: block; font-size: 20px; margin-bottom: 4px; }
.card .m { font-size: 16px; color: #334155; line-height: 1.38; }
.card code, .m code { font-family: 'JetBrains Mono', Consolas, monospace; font-size: 15px; background: #f1f5f9; border-radius: 5px; padding: 0 4px; }
.num { display: inline-flex; width: 28px; height: 28px; border-radius: 50%; background: #0f172a; color: #fff; font-size: 15px; font-weight: 800; align-items: center; justify-content: center; margin-right: 8px; vertical-align: 2px; }
.arrow { flex: 0 0 34px; display: flex; align-items: center; justify-content: center; font-size: 30px; color: #475569; font-weight: 700; }
.down { display: flex; justify-content: center; align-items: center; gap: 14px; margin: 10px 0; color: #334155; font-size: 17px; font-weight: 600; }
.down .a { font-size: 30px; color: #475569; line-height: 1; }
.down .pill { background: #f8fafc; border: 1.5px solid #cbd5e1; border-radius: 999px; padding: 4px 14px; }
.privacy { border: 2.5px solid #b91c1c !important; background: #fef2f2 !important; }
.privacy b { color: #991b1b; }
.ai { border: 2px solid #7c3aed !important; background: #faf5ff !important; }
.ai b { color: #5b21b6; }
.local { border: 2px dashed #b45309 !important; background: #fffbeb !important; }
.chip { display: inline-block; font-size: 14px; font-weight: 700; border-radius: 999px; padding: 2px 10px; margin: 6px 6px 0 0; background: #ede9fe; color: #4c1d95; }
.chip.g { background: #dcfce7; color: #14532d; }
.chip.r { background: #fee2e2; color: #7f1d1d; }
.chip.s { background: #e2e8f0; color: #0f172a; }
.legend { display: flex; gap: 22px; margin-top: 18px; font-size: 15px; color: #475569; }
.legend span::before { content: ""; display: inline-block; width: 16px; height: 16px; border-radius: 4px; margin-right: 6px; vertical-align: -3px; border: 2px solid var(--c); background: var(--f); }
.side { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 14px; margin-top: 14px; }
.side .card { background: #f8fafc; }
/* funnel */
.f-row { display: grid; grid-template-columns: 330px 1fr; gap: 18px; align-items: center; margin: 12px 0; }
.f-label { font-size: 18px; font-weight: 700; text-align: right; color: #1e293b; }
.f-label small { display: block; font-weight: 500; color: #64748b; font-size: 15px; }
.f-bar { min-width: max-content; height: 58px; border-radius: 10px; display: flex; align-items: center; padding: 0 18px; color: #fff; font-size: 24px; font-weight: 800; white-space: nowrap; }
.f-note { font-size: 16px; color: #334155; margin-left: 14px; font-weight: 600; }
/* integration table */
.grid3 { display: grid; grid-template-columns: 300px 40px 1fr 40px 400px; align-items: stretch; row-gap: 16px; }
.grid3 .arrow { flex: none; }
.foot { margin-top: 22px; }
.res { display: grid; grid-template-columns: 430px 40px 1fr 40px 300px; margin: 10px 0; align-items: stretch; }
.res .arrow { flex: none; }
.res.head { font-weight: 800; color: #475569; font-size: 16px; text-transform: uppercase; letter-spacing: .05em; margin-bottom: 4px; }
"""

T = {
 "en": {
  "arch_t": "FaultCase architecture",
  "arch_s": "Read-only collection on Windows, deterministic analysis in Python, Meta models only for interpretation and writing.",
  "pc": "Windows 10 / 11 computer", "pc_tag": "read-only · nothing to install",
  "ev_b": "Event Viewer export", "ev_m": "Custom view <code>device-diagnostics.xml</code> → one <code>.evtx</code><br>System · Application · WLAN-AutoConfig · Kernel-PnP",
  "mi_b": "System information", "mi_m": "<code>msinfo32</code> → File › Export (.txt)<br>model · machine type · BIOS · GPU driver",
  "pw_b": "Battery report", "pw_m": "<code>powercfg /batteryreport</code> (.html)<br>design vs full-charge capacity · cycles",
  "lm_b": "Local mode (optional)", "lm_m": "Same app on the PC: <code>cdb.exe</code> on <code>C:\\Windows\\Minidump</code>, CIM/WMI device read. Raw <code>.dmp</code> never leaves.",
  "up": "HTTPS upload · .evtx required · ≤ 20 MB",
  "br": "Browser", "br_tag": "Jinja2 + HTMX · English / Spanish",
  "s1_b": "Collect", "s1_m": "Guide with screenshots · required / optional uploads · sample case",
  "s2_b": "Diagnosis", "s2_m": "Verdict · 8 health cards · monthly chart · <i>Explain it with Muse</i> · <i>Try to fix it first</i>",
  "s3_b": "Action", "s3_m": "EN/ES manufacturer report · next steps · checklist · evidence ZIP · serial filled in the browser",
  "srv": "FastAPI on Modal", "srv_tag": "1 container · cases in memory only",
  "p1_b": "Adapters", "p1_m": "<code>evtx.py</code> (python-evtx, event level) · <code>msinfo.py</code> · <code>battery_report.py</code> · <code>windbg.py</code>",
  "p2_b": "normalize.py", "p2_m": "Match by event ID + provider → <code>evidence.schema.json</code>. Incidents: 41 + 6008 ≤ 60 s, 1001 ≤ 15 min",
  "p3_b": "redact.py — privacy boundary", "p3_m": "User · computer name · serial · MAC · e-mail · <code>C:\\Users</code> paths. Nothing reaches a model before this step.",
  "p4_b": "rules.py + 8 playbooks", "p4_m": "No AI. Known-benign filter · patterns labeled fact / hypothesis · component status · exact summary",
  "p5_b": "agent.py", "p5_m": "Compact payload: ≤ 20 events per component, 30k-token cap · reconcile two opinions · JSON-schema guard",
  "p6_b": "router.py", "p6_m": "<code>providers.yaml</code> routes · 1 retry · fallback · hedge 25 s · second-opinion wait 60 s · <code>usage.jsonl</code>",
  "to_models": "redacted findings only", "back": "validated case · plain-language explanation · fix plan → Diagnosis",
  "md": "Meta models", "md_tag": "OpenAI-compatible endpoints",
  "bt_m": "Muse Spark Open<br><code>meta-models/muse-spark-open-1026</code>", "fw_m": "Muse Spark Open<br><code>accounts/fireworks/models/muse-spark-open</code>", "mt_m": "Muse Spark<br><code>muse-spark-1.1</code>",
  "r_an": "evidence_analysis", "r_fb": "fallback", "r_cw": "case_writing", "r_ex": "explanation (on demand)", "r_fx": "fix_plan (on demand)",
  "side1_b": "Case store", "side1_m": "In memory, gone after 20 min idle. Never written to disk.",
  "side2_b": "Cost guard", "side2_m": "6 live analyses per visitor per hour, 60 per day. Sample case is free.",
  "side3_b": "Evidence ZIP", "side3_m": "Findings + EN/ES report + dump summaries. Never <code>.evtx</code> or <code>.dmp</code>.",
  "lg_ai": "Meta model call", "lg_priv": "privacy boundary", "lg_loc": "local only",
  "fun_t": "From a real 4 MB export to one warranty case",
  "fun_s": "Measured on the real anonymized case. Rules do the counting; models receive a compact, redacted summary.",
  "f1": "Events parsed", "f1s": "python-evtx, every record", "f2": "Matched a playbook", "f2s": "4,884 unrelated events dropped",
  "f3": "Counted as evidence", "f3s": "1,398 known-benign ignored", "f3n": "Hyper-V devices, WUDFRd, Intel 6062, shadow copies…",
  "f4": "Findings", "f4s": "deterministic, tested", "f4v": "6 incidents · 15 patterns · 8 statuses",
  "f5": "Sent to each model", "f5s": "redacted, compact", "f5v": "≈ 9.5k tokens", "f5n": "instead of ≈ 199k for the raw events (−95%)",
  "int_t": "How Muse, Baseten and Fireworks work together",
  "int_s": "Every value below comes from config/providers.yaml and faultcase/router.py.",
  "col1": "Role", "col2": "Policy", "col3": "Provider · model",
  "i1_b": "evidence_analysis", "i1_m": "Interprets the redacted findings → verdict enum + confidence + labeled findings",
  "i1_p": "<b>Second opinion</b>Both providers in parallel on the same JSON. Agreement = same verdict enum and confidence level; disagreement lowers confidence and adds a hypothesis. Once one answers, wait ≤ 60 s for the other.",
  "i1_r": "<b>Baseten</b>Muse Spark Open · reasoning omitted<br><b style='margin-top:8px'>Fireworks</b>Muse Spark Open · reasoning medium",
  "i2_b": "case_writing", "i2_m": "Writes the EN/ES manufacturer report, user summary and checklist",
  "i2_p": "<b>Single + fallback</b>Primary Meta; on error, timeout or invalid JSON (after 1 retry) Fireworks. Hedge: start the next provider after 25 s. Output validated against <code>case.schema.json</code>.",
  "i2_r": "<b>Meta Model API</b>Muse Spark (muse-spark-1.1)<br><b style='margin-top:8px'>Fireworks</b>fallback",
  "i3_b": "explanation", "i3_m": "Plain-language walkthrough, per-component meaning and action, glossary",
  "i3_p": "<b>On demand, cached</b>Runs only when the user clicks <i>Explain it with Muse</i>. Cached per case and language; the sample case ships it precomputed.",
  "i3_r": "<b>Meta Model API</b>Muse Spark<br><b style='margin-top:8px'>Fireworks</b>fallback",
  "i4_b": "fix_plan", "i4_m": "Ordered self-help plan before a claim: why, how, minutes, risk, how to check",
  "i4_p": "<b>On demand, grounded</b>Only adapts the <code>safe_fixes</code> of the components that need attention; no registry edits or destructive commands. Says when a warranty repair is the likely outcome.",
  "i4_r": "<b>Meta Model API</b>Muse Spark<br><b style='margin-top:8px'>Fireworks</b>fallback",
  "build": "Build & ship", "b1": "<b>Muse Code</b>terminal agent used to build the core pipeline",
  "b2": "<b>GitHub</b>CI on windows-latest + ubuntu-latest", "b3": "<b>Modal</b><code>modal deploy modal_app.py</code> · secrets in Modal",
  "obs": "Every call → <code>logs/usage.jsonl</code>: provider, model, latency, prompt / completion / cached tokens, fallback, error type. Never prompts or keys.",
  "res_t": "What happens when something fails",
  "res_s": "The router and the agent recover on their own; the user only sees a message when nothing else can be done.",
  "rc1": "Situation", "rc2": "What FaultCase does", "rc3": "What the user sees",
  "res": [
   ("Invalid JSON, schema error or truncated answer", "Retry the same provider once (<code>max_retries_per_provider: 1</code>)", "Nothing", "g"),
   ("Provider error or timeout (90 s)", "Next provider in the route · logged as <code>fallback_used</code>", "A slightly longer wait", "g"),
   ("Primary slower than 25 s", "Hedge: start the next provider too; the first valid answer wins", "A shorter wait", "g"),
   ("Second opinion: one provider fails or answers > 60 s after the other", "Continue with the surviving opinion; agreement recorded as unknown", "Nothing", "g"),
   ("Compact payload still above 30k tokens", "Stop before any model call (<code>PayloadTooLargeError</code>)", "Export a shorter period", "y"),
   ("Visitor above 6 live analyses per hour", "Refuse before any model call", "Try again later or use the sample case", "y"),
   ("Every provider in the route failed", "<code>RouterError</code> with provider, error type and message in <code>usage.jsonl</code>; nothing stored", "Clear error, upload again", "r"),
  ],
 },
 "es": {
  "arch_t": "Arquitectura de FaultCase",
  "arch_s": "Recolección de solo lectura en Windows, análisis determinista en Python y modelos de Meta solo para interpretar y redactar.",
  "pc": "Equipo con Windows 10 / 11", "pc_tag": "solo lectura · nada que instalar",
  "ev_b": "Exportación del Visor de eventos", "ev_m": "Vista personalizada <code>device-diagnostics.xml</code> → un <code>.evtx</code><br>System · Application · WLAN-AutoConfig · Kernel-PnP",
  "mi_b": "Información del sistema", "mi_m": "<code>msinfo32</code> → Archivo › Exportar (.txt)<br>modelo · tipo de máquina · BIOS · controlador GPU",
  "pw_b": "Informe de batería", "pw_m": "<code>powercfg /batteryreport</code> (.html)<br>capacidad de diseño vs carga completa · ciclos",
  "lm_b": "Modo local (opcional)", "lm_m": "La app en el propio PC: <code>cdb.exe</code> sobre <code>C:\\Windows\\Minidump</code>, lectura CIM/WMI. El <code>.dmp</code> nunca sale.",
  "up": "Subida HTTPS · .evtx obligatorio · ≤ 20 MB",
  "br": "Navegador", "br_tag": "Jinja2 + HTMX · inglés / español",
  "s1_b": "Recopilar", "s1_m": "Guía con capturas · subidas obligatorias / opcionales · caso de ejemplo",
  "s2_b": "Diagnóstico", "s2_m": "Veredicto · 8 tarjetas · gráfico mensual · <i>Explicar con Muse</i> · <i>Intentar solucionarlo</i>",
  "s3_b": "Acción", "s3_m": "Informe EN/ES · próximos pasos · lista previa · ZIP de evidencias · serie solo en el navegador",
  "srv": "FastAPI en Modal", "srv_tag": "1 contenedor · casos solo en memoria",
  "p1_b": "Adaptadores", "p1_m": "<code>evtx.py</code> (python-evtx, nivel del evento) · <code>msinfo.py</code> · <code>battery_report.py</code> · <code>windbg.py</code>",
  "p2_b": "normalize.py", "p2_m": "Coincidencia por ID de evento + proveedor → <code>evidence.schema.json</code>. Incidentes: 41 + 6008 ≤ 60 s, 1001 ≤ 15 min",
  "p3_b": "redact.py — frontera de privacidad", "p3_m": "Usuario · nombre del equipo · serie · MAC · correo · rutas <code>C:\\Users</code>. Nada llega a un modelo antes de este paso.",
  "p4_b": "rules.py + 8 playbooks", "p4_m": "Sin IA. Filtro de eventos inofensivos · patrones como hecho / hipótesis · estado por componente · resumen exacto",
  "p5_b": "agent.py", "p5_m": "Carga compacta: ≤ 20 eventos por componente, tope de 30k tokens · reconciliar dos opiniones · validación JSON",
  "p6_b": "router.py", "p6_m": "Rutas de <code>providers.yaml</code> · 1 reintento · respaldo · hedge 25 s · espera de segunda opinión 60 s · <code>usage.jsonl</code>",
  "to_models": "solo hallazgos anonimizados", "back": "caso validado · explicación sencilla · plan de solución → Diagnóstico",
  "md": "Modelos de Meta", "md_tag": "endpoints compatibles con OpenAI",
  "bt_m": "Muse Spark Open<br><code>meta-models/muse-spark-open-1026</code>", "fw_m": "Muse Spark Open<br><code>accounts/fireworks/models/muse-spark-open</code>", "mt_m": "Muse Spark<br><code>muse-spark-1.1</code>",
  "r_an": "evidence_analysis", "r_fb": "respaldo", "r_cw": "case_writing", "r_ex": "explanation (a petición)", "r_fx": "fix_plan (a petición)",
  "side1_b": "Almacén de casos", "side1_m": "En memoria; desaparece tras 20 min sin uso. Nunca se escribe en disco.",
  "side2_b": "Control de costo", "side2_m": "6 análisis en vivo por visitante por hora, 60 al día. El ejemplo es gratis.",
  "side3_b": "ZIP de evidencias", "side3_m": "Hallazgos + informe EN/ES + resúmenes de volcados. Nunca <code>.evtx</code> ni <code>.dmp</code>.",
  "lg_ai": "llamada a modelo de Meta", "lg_priv": "frontera de privacidad", "lg_loc": "solo local",
  "fun_t": "De una exportación real de 4 MB a un caso de garantía",
  "fun_s": "Medido sobre el caso real anonimizado. Las reglas cuentan; los modelos reciben un resumen compacto y anonimizado.",
  "f1": "Eventos leídos", "f1s": "python-evtx, todos los registros", "f2": "Coinciden con un playbook", "f2s": "4.884 eventos ajenos descartados",
  "f3": "Contados como evidencia", "f3s": "1.398 inofensivos ignorados", "f3n": "dispositivos Hyper-V, WUDFRd, Intel 6062, shadow copies…",
  "f4": "Hallazgos", "f4s": "deterministas, con tests", "f4v": "6 incidentes · 15 patrones · 8 estados",
  "f5": "Enviado a cada modelo", "f5s": "anonimizado, compacto", "f5v": "≈ 9,5k tokens", "f5n": "en lugar de ≈ 199k con los eventos crudos (−95 %)",
  "int_t": "Cómo trabajan juntos Muse, Baseten y Fireworks",
  "int_s": "Todos los valores salen de config/providers.yaml y faultcase/router.py.",
  "col1": "Rol", "col2": "Política", "col3": "Proveedor · modelo",
  "i1_b": "evidence_analysis", "i1_m": "Interpreta los hallazgos anonimizados → veredicto + confianza + hallazgos etiquetados",
  "i1_p": "<b>Segunda opinión</b>Ambos proveedores en paralelo sobre el mismo JSON. Acuerdo = mismo veredicto y nivel de confianza; el desacuerdo baja la confianza y añade una hipótesis. Con una respuesta, espera ≤ 60 s la otra.",
  "i1_r": "<b>Baseten</b>Muse Spark Open · sin razonamiento<br><b style='margin-top:8px'>Fireworks</b>Muse Spark Open · razonamiento medio",
  "i2_b": "case_writing", "i2_m": "Redacta el informe EN/ES para el fabricante, el resumen y la lista previa",
  "i2_p": "<b>Único + respaldo</b>Meta primero; ante error, tiempo agotado o JSON inválido (tras 1 reintento) Fireworks. Hedge: lanza el siguiente a los 25 s. Validado contra <code>case.schema.json</code>.",
  "i2_r": "<b>Meta Model API</b>Muse Spark (muse-spark-1.1)<br><b style='margin-top:8px'>Fireworks</b>respaldo",
  "i3_b": "explanation", "i3_m": "Explicación sencilla, significado y acción por componente, glosario",
  "i3_p": "<b>A petición, en caché</b>Solo se ejecuta cuando el usuario pulsa <i>Explicar con Muse</i>. Se guarda por caso e idioma; el ejemplo la trae precalculada.",
  "i3_r": "<b>Meta Model API</b>Muse Spark<br><b style='margin-top:8px'>Fireworks</b>respaldo",
  "i4_b": "fix_plan", "i4_m": "Plan de autoayuda ordenado antes de reclamar: por qué, cómo, minutos, riesgo, cómo comprobar",
  "i4_p": "<b>A petición, acotado</b>Solo adapta las <code>safe_fixes</code> de los componentes con problemas; nada de registro ni comandos destructivos. Dice cuándo lo probable es la garantía.",
  "i4_r": "<b>Meta Model API</b>Muse Spark<br><b style='margin-top:8px'>Fireworks</b>respaldo",
  "build": "Construcción y despliegue", "b1": "<b>Muse Code</b>agente de terminal con el que se construyó el núcleo",
  "b2": "<b>GitHub</b>CI en windows-latest + ubuntu-latest", "b3": "<b>Modal</b><code>modal deploy modal_app.py</code> · secretos en Modal",
  "obs": "Cada llamada → <code>logs/usage.jsonl</code>: proveedor, modelo, latencia, tokens de prompt / respuesta / caché, respaldo, tipo de error. Nunca prompts ni claves.",
  "res_t": "Qué pasa cuando algo falla",
  "res_s": "El router y el agente se recuperan solos; el usuario solo ve un mensaje cuando no queda otra opción.",
  "rc1": "Situación", "rc2": "Qué hace FaultCase", "rc3": "Qué ve el usuario",
  "res": [
   ("JSON inválido, error de esquema o respuesta truncada", "Reintenta una vez el mismo proveedor (<code>max_retries_per_provider: 1</code>)", "Nada", "g"),
   ("Error del proveedor o tiempo agotado (90 s)", "Siguiente proveedor de la ruta · registrado como <code>fallback_used</code>", "Una espera algo mayor", "g"),
   ("El principal tarda más de 25 s", "Hedge: lanza también el siguiente; gana la primera respuesta válida", "Una espera menor", "g"),
   ("Segunda opinión: un proveedor falla o responde > 60 s después del otro", "Continúa con la opinión disponible; el acuerdo queda como desconocido", "Nada", "g"),
   ("La carga compacta supera 30k tokens", "Se detiene antes de llamar a un modelo (<code>PayloadTooLargeError</code>)", "Exportar un periodo más corto", "y"),
   ("Visitante con más de 6 análisis en vivo por hora", "Se rechaza antes de llamar a un modelo", "Intentar más tarde o usar el ejemplo", "y"),
   ("Fallaron todos los proveedores de la ruta", "<code>RouterError</code> con proveedor, tipo de error y mensaje en <code>usage.jsonl</code>; no se guarda nada", "Error claro, volver a subir", "r"),
  ],
 },
}


def band(color, bg, title, tag, inner):
    return (f'<div class="band" style="--b:{color};--bg:{bg}"><div class="band-title">{title}'
            f'<span class="tag">{tag}</span></div>{inner}</div>')


def card(title, body, cls="", num=None, extra=""):
    n = f'<span class="num">{num}</span>' if num else ""
    return f'<div class="card {cls}"><b>{n}{title}</b><div class="m">{body}</div>{extra}</div>'


def arch(t):
    pc = band("#0e7490", "#ecfeff", "🖥 " + t["pc"], t["pc_tag"], '<div class="row">'
              + card(t["ev_b"], t["ev_m"]) + card(t["mi_b"], t["mi_m"]) + card(t["pw_b"], t["pw_m"])
              + card(t["lm_b"], t["lm_m"], "local") + "</div>")
    br = band("#4338ca", "#eef2ff", "🌐 " + t["br"], t["br_tag"], '<div class="row">'
              + card(t["s1_b"], t["s1_m"], num="1") + '<div class="arrow">→</div>'
              + card(t["s2_b"], t["s2_m"], num="2") + '<div class="arrow">→</div>'
              + card(t["s3_b"], t["s3_m"], num="3") + "</div>")
    row1 = ('<div class="row">' + card(t["p1_b"], t["p1_m"], num="a") + '<div class="arrow">→</div>'
            + card(t["p2_b"], t["p2_m"], num="b") + '<div class="arrow">→</div>'
            + card(t["p3_b"], t["p3_m"], "privacy", num="c") + "</div>")
    row2 = ('<div class="down" style="justify-content:flex-end;margin:6px 120px 6px 0"><span class="a">↓</span></div>'
            '<div class="row">' + card(t["p6_b"], t["p6_m"], num="f") + '<div class="arrow">←</div>'
            + card(t["p5_b"], t["p5_m"], num="e") + '<div class="arrow">←</div>'
            + card(t["p4_b"], t["p4_m"], num="d") + "</div>")
    side = ('<div class="side">' + card(t["side1_b"], t["side1_m"]) + card(t["side2_b"], t["side2_m"])
            + card(t["side3_b"], t["side3_m"]) + "</div>")
    srv = band("#334155", "#f8fafc", "☁ " + t["srv"], t["srv_tag"], row1 + row2 + side)
    md = band("#7c3aed", "#faf5ff", "✦ " + t["md"], t["md_tag"], '<div class="row">'
              + card("Baseten", t["bt_m"], "ai", extra=f'<span class="chip">{t["r_an"]}</span>')
              + card("Fireworks", t["fw_m"], "ai", extra=f'<span class="chip">{t["r_an"]}</span><span class="chip s">{t["r_fb"]}</span>')
              + card("Meta Model API", t["mt_m"], "ai", extra=f'<span class="chip">{t["r_cw"]}</span><span class="chip g">{t["r_ex"]}</span><span class="chip g">{t["r_fx"]}</span>')
              + "</div>")
    down = lambda label: f'<div class="down"><span class="a">↓</span><span class="pill">{label}</span><span class="a">↓</span></div>'
    up = lambda label: f'<div class="down"><span class="a">↑</span><span class="pill">{label}</span><span class="a">↑</span></div>'
    legend = (f'<div class="legend"><span style="--c:#7c3aed;--f:#faf5ff">{t["lg_ai"]}</span>'
              f'<span style="--c:#b91c1c;--f:#fef2f2">{t["lg_priv"]}</span>'
              f'<span style="--c:#b45309;--f:#fffbeb">{t["lg_loc"]}</span></div>')
    return (f'<h1>{t["arch_t"]}</h1><p class="sub">{t["arch_s"]}</p>' + pc + down(t["up"]) + br
            + down("POST /upload · /demo · /case/{id}/explain · /case/{id}/fix") + srv + down(t["to_models"]) + md
            + up(t["back"]) + legend)


def funnel(t):
    rows = [
        (t["f1"], t["f1s"], "7,159" if t is T["en"] else "7.159", 100, "#1e293b", ""),
        (t["f2"], t["f2s"], "2,275" if t is T["en"] else "2.275", 62, "#334155", ""),
        (t["f3"], t["f3s"], "877", 38, "#4338ca", t["f3n"]),
        (t["f4"], t["f4s"], t["f4v"], 30, "#0e7490", ""),
        (t["f5"], t["f5s"], t["f5v"], 22, "#7c3aed", t["f5n"]),
    ]
    html = f'<h1>{t["fun_t"]}</h1><p class="sub">{t["fun_s"]}</p>'
    for label, small, value, width, color, note in rows:
        html += (f'<div class="f-row"><div class="f-label">{label}<small>{small}</small></div>'
                 f'<div style="display:flex;align-items:center"><div class="f-bar" style="width:{width}%;background:{color}">{value}</div>'
                 f'<span class="f-note">{note}</span></div></div>')
    return html


def integration(t):
    head = (f'<div class="grid3" style="margin-bottom:8px;font-weight:800;color:#475569;font-size:16px;text-transform:uppercase;letter-spacing:.05em">'
            f'<div>{t["col1"]}</div><div></div><div>{t["col2"]}</div><div></div><div>{t["col3"]}</div></div>')
    body = '<div class="grid3">'
    for i in ("1", "2", "3", "4"):
        body += (card(t[f"i{i}_b"], t[f"i{i}_m"]) + '<div class="arrow">→</div>'
                 + f'<div class="card"><div class="m" style="font-size:17px">{t[f"i{i}_p"]}</div></div>'
                 + '<div class="arrow">→</div>'
                 + f'<div class="card ai"><div class="m" style="font-size:17px">{t[f"i{i}_r"]}</div></div>')
    body += "</div>"
    body = body.replace("<div class=\"m\" style=\"font-size:17px\"><b>", "<div class=\"m\" style=\"font-size:17px\"><b style=\"display:block;font-size:19px;margin-bottom:4px\">")
    foot = band("#0f172a", "#f8fafc", "⚙ " + t["build"], "Muse Code → GitHub → Modal",
                '<div class="row">' + f'<div class="card"><div class="m">{t["b1"]}</div></div><div class="arrow">→</div>'
                + f'<div class="card"><div class="m">{t["b2"]}</div></div><div class="arrow">→</div>'
                + f'<div class="card"><div class="m">{t["b3"]}</div></div></div>'
                + f'<p class="m" style="margin:12px 2px 0;font-size:16px;color:#334155">{t["obs"]}</p>')
    foot = foot.replace('<div class="m"><b>', '<div class="m"><b style="display:block;font-size:19px;margin-bottom:4px">')
    return f'<h1>{t["int_t"]}</h1><p class="sub">{t["int_s"]}</p>' + head + body + f'<div class="foot">{foot}</div>'


def resilience(t):
    colors = {"g": ("#dcfce7", "#14532d"), "y": ("#fef9c3", "#713f12"), "r": ("#fee2e2", "#7f1d1d")}
    html = f'<h1>{t["res_t"]}</h1><p class="sub">{t["res_s"]}</p>'
    html += ('<div class="res head"><div>' + t["rc1"] + '</div><div></div><div>' + t["rc2"]
             + '</div><div></div><div>' + t["rc3"] + '</div></div>')
    for situation, action, seen, level in t["res"]:
        bg, fg = colors[level]
        html += (f'<div class="res"><div class="card"><div class="m" style="font-size:18px;color:#0f172a;font-weight:600">{situation}</div></div>'
                 f'<div class="arrow">→</div><div class="card"><div class="m" style="font-size:17px">{action}</div></div>'
                 f'<div class="arrow">→</div><div class="card" style="background:{bg};border-color:{fg}">'
                 f'<div class="m" style="font-size:18px;color:{fg};font-weight:700">{seen}</div></div></div>')
    return html


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1500, "height": 900}, device_scale_factor=2)
        for lang, t in T.items():
            for name, builder in (("architecture", arch), ("pipeline", funnel),
                                  ("integration", integration), ("resilience", resilience)):
                page.set_content(f"<html><head><meta charset='utf-8'><style>{CSS}</style></head>"
                                 f"<body><div class='canvas'>{builder(t)}</div></body></html>")
                page.locator(".canvas").screenshot(path=str(OUT / f"{name}-{lang}.png"))
                print("wrote", name, lang)
        browser.close()


if __name__ == "__main__":
    main()
