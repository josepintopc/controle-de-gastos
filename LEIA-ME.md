# Controle de Gastos: online e lançado pelo Claude

```
App Claude (celular) ──► conector "gastos-mcp" (Supabase Edge Function) ┐
                                                                         ├─► banco Postgres (Supabase)
Navegador (celular/PC) ──► dashboard Streamlit (Streamlit Cloud) ───────┘
```

- **Sem configurar nada**, o app continua como antes: `python -m streamlit run Controledegastos.py --server.port 8502` usa `gastos.csv` e `config.json`.
- **Com `.streamlit/secrets.toml`** (ou os Secrets do Streamlit Cloud), o app passa a usar o banco do Supabase, o mesmo que o Claude alimenta.

## Arquivos

| Arquivo | Para quê |
|---|---|
| `Controledegastos.py` | Dashboard (o mesmo de antes; o formulário ganhou a categoria "Automática") |
| `armazenamento.py` | Decide entre CSV local e Supabase; classificação automática de categoria |
| `acesso.py` | Login Google e lista de e-mails autorizados (donos e leitores) |
| `supabase/migrations/…sql` | Tabelas `gastos`, `backup` e `config`, e as funções de salvar, inserir e desfazer |
| `supabase/functions/gastos-mcp/` | Conector MCP do Claude (`registrar_gasto`, `listar_gastos`) |
| `supabase/functions/gastos-mcp/categorias.json` | Categorias e palavras-chave, usadas pelo conector **e** pelo app |
| `migrar_para_supabase.py` | Envia o `gastos.csv` e o `config.json` atuais para o banco (uma vez) |

## Passo a passo para colocar online

### 1. Supabase (banco + conector)
1. Crie uma conta em <https://supabase.com> e um projeto **Free**. Região sugerida: *East US (North Virginia)*, porque o Streamlit Cloud e o Claude rodam nos EUA e isso deixa o app mais rápido. *São Paulo* também funciona.
2. Gere um token secreto para o conector (guarde-o, ele vai na URL):
   ```powershell
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
3. Publique o banco e o conector. Peça ao Claude Code ("aplique a migração e publique o gastos-mcp no projeto X") ou rode na pasta `Controle_de_gastos`:
   ```powershell
   npx supabase login
   npx supabase link --project-ref <ref-do-projeto>
   npx supabase db push
   npx supabase secrets set MCP_TOKEN=<token-do-passo-2>
   npx supabase functions deploy gastos-mcp --no-verify-jwt --use-api
   ```
4. Em *Project Settings → API Keys*, copie a **URL do projeto** e a chave **service_role** (ou uma *secret key* `sb_secret_…`). **Nunca** compartilhe essa chave.

### 2. Levar os dados atuais para o banco
1. Copie `.streamlit/secrets.toml.example` para `.streamlit/secrets.toml` e preencha a URL e a chave.
2. Rode:
   ```powershell
   pip install -r requirements.txt
   python migrar_para_supabase.py
   ```
   O script mostra o total enviado e confere o banco. Os arquivos locais não são alterados.
3. Teste no PC: `python -m streamlit run Controledegastos.py --server.port 8502`. Agora os dados vêm do banco.

### 3. GitHub (repositório privado)
O `.gitignore` já impede que `gastos.csv`, `config.json`, `files.zip` e `secrets.toml` subam.
```powershell
cd Controle_de_gastos
git init
git add .
git status   # confira: nenhum .csv, config.json ou secrets.toml na lista
git commit -m "Controle de gastos com Supabase"
```
Crie um repositório **privado** em <https://github.com/new> e siga as instruções de "push an existing repository".

### 4. Streamlit Community Cloud (o link para o celular)
1. Entre em <https://share.streamlit.io> com o GitHub → **Create app** → escolha o repositório, branch `main` e o arquivo `Controledegastos.py`.
2. Em **Advanced settings → Secrets**, cole o conteúdo do seu `secrets.toml`.
3. Depois de publicado: **Share** → deixe o app **privado** e adicione só o seu e-mail.
4. No celular, abra o link e use **"Adicionar à tela inicial"** para ele virar um ícone.

> O `.streamlit/config.toml` do projeto não tem `[server]`: no Cloud, `address = "localhost"` impede o app de iniciar. No PC essa restrição fica em `%USERPROFILE%\.streamlit\config.toml`.

### 5. Conector no Claude
1. Em <https://claude.ai> → **Configurações → Conectores → Adicionar conector personalizado**.
2. Nome: `Controle de Gastos`. URL:
   ```
   https://<ref-do-projeto>.supabase.co/functions/v1/gastos-mcp/<token-do-passo-1.2>/mcp
   ```
3. Ele aparece também no app do celular. Numa conversa, ative o conector (ícone de ferramentas) ou crie um **Projeto "Gastos"** com ele ligado e a instrução: *"Quando eu disser um gasto, registre com o conector Controle de Gastos."*
4. Use assim: *"gastei 45 no ifood no crédito"*, *"uber 23,50 ontem"*, *"quanto já gastei com mercado este mês?"*

## Segurança: quem pode ver o app
São três travas. Os dados só aparecem para quem passa por todas:
1. **Streamlit Cloud privado.** Em ⋮ → Settings → Sharing, o app fica restrito a *Only specific people*.
2. **Google em modo "Em teste".** Só os "usuários de teste" cadastrados na tela de consentimento OAuth conseguem fazer login.
3. **Lista do próprio app.** O `acesso.py` só libera os e-mails da seção `[acesso]` nos Secrets:
   - `donos` veem e alteram tudo;
   - `leitores` só veem: não lançam, não editam, não importam e não desfazem.

**Autorizar alguém (como leitor):**
1. Adicione o e-mail Google da pessoa em `leitores`, nos Secrets do app (Streamlit Cloud → app → Settings → Secrets).
2. Adicione o mesmo e-mail como *usuário de teste* no Google Cloud (Tela de consentimento OAuth).
3. Convide a pessoa em **Share** no Streamlit Cloud. O plano gratuito permite convidar viewers no app privado.

**Remover o acesso de alguém:** faça o inverso nos três lugares. Basta tirar a pessoa de um deles para ela já não ver os dados.

**Login Google (configuração única):**
1. Em <https://console.cloud.google.com>, crie o projeto `controle-de-gastos`.
2. Em **APIs e serviços → Tela de consentimento OAuth**: tipo *Externo*, status **Em teste**, com você em *usuários de teste*.
3. Em **Credenciais → Criar credenciais → ID do cliente OAuth**, escolha *Aplicativo da Web* e cadastre os redirecionamentos `https://SEU-APP.streamlit.app/oauth2callback` e `http://localhost:8501/oauth2callback`.
4. Preencha `[auth]`, `[auth.google]` e `[acesso]` nos Secrets, seguindo o modelo em `.streamlit/secrets.toml.example`.

**Senhas do sistema:** trate como senha:
- a **URL do conector do Claude**: quem tiver o link consegue ler e lançar gastos;
- a chave **service_role**;
- o **client_secret** do Google.

Se a URL do conector vazar:
1. Gere outro token com `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
2. Troque o `MCP_TOKEN` no painel do Supabase (Edge Functions → Secrets).
3. Atualize a URL no claude.ai.

Ative a **verificação em duas etapas** no GitHub, no Google e no Supabase.

## Como a categoria é escolhida
1. O próprio Claude escolhe entre as 10 categorias do app a partir da frase.
2. Se ele não mandar categoria, o conector procura palavras-chave da descrição em `categorias.json` (ex.: *uber* → Transporte, *farmácia* → Saúde).
3. Nada encontrado → **Outros**. Para ensinar novas palavras, edite `categorias.json` e publique de novo o conector e o app.

## Bom saber
- **Desfazer** (menu lateral) volta a última alteração, inclusive um gasto lançado pelo Claude.
- O plano gratuito do Supabase **pausa o projeto após 7 dias sem uso**. Se isso acontecer, reative-o no painel do Supabase.
- O Streamlit Cloud "dorme" o app depois de um tempo sem visitas. Ao abrir o link, ele acorda em alguns segundos.
- Evite editar a tabela de Lançamentos no app **enquanto** lança gastos pelo Claude: ao salvar uma edição, a tabela é regravada com o que estava na tela.
