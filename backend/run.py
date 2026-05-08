import os
import uvicorn

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8020"))
    reload = os.getenv("RELOAD", "1") == "1"
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=reload)
