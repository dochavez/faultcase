"""Deploy the FaultCase FastAPI app on Modal.

Secrets live in Modal, never in this file: a secret named ``faultcase``
holding META_API_KEY, BASETEN_API_KEY, BASETEN_MODEL, FIREWORKS_API_KEY
and INVITE_CODE.

Deploy with: modal deploy modal_app.py
"""

import sys

import modal

REMOTE_ROOT = "/root/faultcase"

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install_from_requirements("requirements.txt")
    .add_local_dir("faultcase", f"{REMOTE_ROOT}/faultcase")
    .add_local_dir("config", f"{REMOTE_ROOT}/config")
    .add_local_dir("filters", f"{REMOTE_ROOT}/filters")
    .add_local_dir("playbooks", f"{REMOTE_ROOT}/playbooks")
    .add_local_dir("prompts", f"{REMOTE_ROOT}/prompts")
    .add_local_dir("schemas", f"{REMOTE_ROOT}/schemas")
    .add_local_dir("templates", f"{REMOTE_ROOT}/templates")
    .add_local_dir("static", f"{REMOTE_ROOT}/static")
    # Only the fixture files the app needs: never failures.evtx (private).
    .add_local_file(
        "fixtures/real_case/events_41.json",
        f"{REMOTE_ROOT}/fixtures/real_case/events_41.json",
    )
    .add_local_file(
        "fixtures/real_case/expected.json",
        f"{REMOTE_ROOT}/fixtures/real_case/expected.json",
    )
    .add_local_file(
        "fixtures/real_case/demo_case.json",
        f"{REMOTE_ROOT}/fixtures/real_case/demo_case.json",
    )
    .add_local_dir(
        "fixtures/real_case/windbg", f"{REMOTE_ROOT}/fixtures/real_case/windbg"
    )
)

app = modal.App("faultcase")


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("faultcase")],
    timeout=600,  # agent runs take a few minutes on slow providers
    max_containers=1,  # cases live in memory: one container keeps links working
    scaledown_window=1200,  # keep the container (and its cases) for 20 minutes
)
@modal.asgi_app()
def fastapi_app():
    sys.path.insert(0, REMOTE_ROOT)
    from faultcase.app import app as web_app

    return web_app
