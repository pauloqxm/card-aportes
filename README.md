# Deploy no Railway

Esta pasta contém **apenas os arquivos necessários** para o deploy no Railway.

## Conteúdo

- **api.py** — Aplicação FastAPI (endpoints + servir estáticos)
- **engine.py** — Lógica de processamento e geração de imagem
- **requirements.txt** — Dependências Python
- **Procfile** — Comando de start: `uvicorn api:app --host 0.0.0.0 --port $PORT`
- **runtime.txt** — Python 3.11
- **static/** — Frontend (index.html, style.css, app.js)
- **fonts/** — Opcional: coloque arquivos .ttf aqui para acentos no card
- **base_card.png** — Opcional: imagem de fundo para formato Feed (adicione na raiz desta pasta)

## Deploy via GitHub

1. Crie um repositório no GitHub **somente com o conteúdo desta pasta** (a pasta `Railway` é a raiz do repo), ou use um monorepo e no Railway configure **Root Directory** = `Railway`.
2. No [Railway](https://railway.app): **New Project** → **Deploy from GitHub** → selecione o repositório.
3. Se o repositório tiver a pasta `Railway` como subpasta, em **Settings** do serviço defina **Root Directory** = `Railway`.
4. O Railway usará o Procfile automaticamente. Após o deploy, a URL do app aparecerá no painel.

## Deploy enviando só esta pasta

Se preferir um repositório só para o deploy:

1. Copie todo o conteúdo de `Railway/` para uma nova pasta (ex.: `card-aportes-deploy`).
2. Inicialize um repositório Git nessa pasta e envie para o GitHub.
3. Conecte esse repositório ao Railway. Não é necessário configurar Root Directory.
