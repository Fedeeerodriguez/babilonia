"""Ingesta de la base de conocimiento de PRODUCTOS al vector store del RAG.

Sube los .md de docs/productos/ a la tabla `documents` (content, metadata jsonb,
embedding vector) del Postgres del RAG (DOCUMENTS_DATABASE_URL).

Metadata ORDENADA para que sea fácil de encontrar/filtrar:
  - source: "productos"            (categoría raíz -> permite borrar/re-subir todo junto)
  - categoria: "ahorro"|"inversion"|"proteccion"|"seguro_general"
  - producto: "OptiMaxx Plus" ...  (nombre legible)
  - clave: "PLU3" ...              (clave Allianz)
  - file_name, doc_slug, chunk_index

Uso:
  cd backend
  # 1) exportá la contraseña vigente del RAG (o dejá que tome DOCUMENTS_DATABASE_URL del .env si ya está bien)
  #    RAG_DSN="postgresql://postgres.vpeeeeanqumeyemhdxta:<PASS>@aws-1-us-east-1.pooler.supabase.com:5432/postgres"
  venv/Scripts/python.exe scripts/ingest_productos_rag.py            # sube (idempotente por doc_slug)
  venv/Scripts/python.exe scripts/ingest_productos_rag.py --dry-run  # no inserta, solo muestra
"""
from __future__ import annotations
import os, sys, json, glob, re
import psycopg2
from openai import OpenAI

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
PRODUCTOS_DIR = os.path.normpath(os.path.join(BACKEND, "..", "docs", "productos"))

CHUNK_SIZE, CHUNK_OVERLAP = 1000, 150

# Clasificación por slug de archivo -> metadata ordenada
CATALOGO = {
    "01_optimaxx_plus":        ("OptiMaxx Plus",        "PLU3", "ahorro"),
    "02_optimaxx_educacion":   ("OptiMaxx Educación",   "OP3D", "ahorro"),
    "03_optimaxx_patrimonial": ("OptiMaxx Patrimonial", "OPPT", "inversion"),
    "04_optimaxx_elite":       ("OptiMaxx Elite",       "SVIP", "inversion"),
    "05_optimaxx_proteccion":  ("OptiMaxx Protección",  "VIPP", "proteccion"),
    "06_allianz_auto":         ("Allianz Auto",         "AUIN", "seguro_general"),
    "00_INDICE":               ("Índice de productos",  "",     "indice"),
}

SOURCE = "productos"


def load_env():
    env = {}
    p = os.path.join(BACKEND, ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def chunk(text: str):
    text = text.strip()
    if not text:
        return []
    out, i = [], 0
    while i < len(text):
        out.append(text[i:i + CHUNK_SIZE])
        i += CHUNK_SIZE - CHUNK_OVERLAP
    return out


def main():
    dry = "--dry-run" in sys.argv
    env = load_env()
    dsn = os.getenv("RAG_DSN") or env.get("DOCUMENTS_DATABASE_URL")
    tbl = env.get("DOCUMENTS_TABLE", "documents")
    embed_model = env.get("OPENAI_EMBED_MODEL", "text-embedding-3-small")
    openai_key = os.getenv("OPENAI_API_KEY") or env.get("OPENAI_API_KEY")

    files = sorted(glob.glob(os.path.join(PRODUCTOS_DIR, "*.md")))
    print(f"Encontrados {len(files)} documentos en {PRODUCTOS_DIR}")

    conn = None
    if not dry:
        conn = psycopg2.connect(dsn)
    client = OpenAI(api_key=openai_key) if not dry else None

    total_chunks = 0
    for f in files:
        slug = os.path.splitext(os.path.basename(f))[0]
        producto, clave, categoria = CATALOGO.get(slug, (slug, "", "otros"))
        content = open(f, encoding="utf-8").read()
        chunks = chunk(content)
        print(f"  - {slug:26s} {categoria:14s} {clave:5s} -> {len(chunks)} chunks")
        total_chunks += len(chunks)
        if dry:
            continue

        cur = conn.cursor()
        # idempotente: borra chunks previos de este doc antes de reinsertar
        cur.execute(f"DELETE FROM {tbl} WHERE metadata->>'doc_slug' = %s", (slug,))
        resp = client.embeddings.create(model=embed_model, input=chunks)
        for idx, (ch, e) in enumerate(zip(chunks, resp.data)):
            meta = {
                "source": SOURCE, "categoria": categoria, "producto": producto,
                "clave": clave, "file_name": os.path.basename(f), "doc_slug": slug,
                "chunk_index": idx,
                "doc_tipo": "indice" if slug == "00_INDICE" else "ficha_curada",
            }
            cur.execute(
                f"INSERT INTO {tbl} (content, metadata, embedding) "
                f"VALUES (%s, CAST(%s AS jsonb), CAST(%s AS vector))",
                (ch, json.dumps(meta, ensure_ascii=False), str(e.embedding)),
            )
        conn.commit()
        cur.close()

    if conn:
        conn.close()
    print(f"\nTotal chunks: {total_chunks}. {'(dry-run, nada insertado)' if dry else 'INSERTADO OK.'}")


if __name__ == "__main__":
    main()
