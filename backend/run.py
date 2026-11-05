import os
import uvicorn

if __name__ == "__main__":
    # ROL=espejo → este contenedor es el worker del espejo de Notion, no la API
    # (servicio babilonia-espejo en EasyPanel: misma imagen, sin depender del campo "comando").
    if os.getenv("ROL", "").strip().lower() == "espejo":
        import sys
        from app.services.espejo.worker import main as worker_espejo
        sys.exit(worker_espejo(sys.argv[1:]))
    port = int(os.getenv("PORT", "8020"))
    reload = os.getenv("RELOAD", "1") == "1"
    # Multi-worker: que un request lento (Notion/OpenAI/DB) no congele todo el
    # backend. Con reload activo uvicorn ignora workers, así que solo aplica en prod.
    workers = int(os.getenv("WEB_CONCURRENCY", "4"))
    kwargs = {
        "host": "0.0.0.0",
        "port": port,
        "timeout_keep_alive": int(os.getenv("KEEP_ALIVE", "30")),
    }
    if reload:
        kwargs["reload"] = True
    else:
        kwargs["workers"] = workers
    uvicorn.run("app.main:app", **kwargs)
