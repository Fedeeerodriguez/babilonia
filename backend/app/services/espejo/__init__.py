"""Espejo de Notion: copia de las bases NOTION_DB_* en nuestra base (ESPEJO_DATABASE_URL), al día en
1–2 minutos, para que Tommy y el gestor de tickets no consulten Notion en vivo.

  notion_api.py  pedidos a Notion con límite global (3/s) y conteo
  repo.py        lectura/escritura del esquema notion_espejo (backend/sql/notion_espejo.sql)
  sync.py        carga completa, incremental por last_edited_time y páginas avisadas por webhook
  worker.py      proceso aparte que corre el sync en bucle (servicio espejo-worker en EasyPanel)

Ver docs/ESPEJO_NOTION.md.
"""
