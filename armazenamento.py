"""
Onde os dados do Controle de Gastos ficam guardados.

- Sem segredos configurados: arquivos locais (gastos.csv, gastos.bak.csv e config.json),
  exatamente como antes.
- Com [supabase] em .streamlit/secrets.toml (ou nos Secrets do Streamlit Cloud): banco
  Postgres no Supabase, o mesmo usado pelo conector do Claude (supabase/functions/gastos-mcp).
"""
import json
import re
import shutil
import unicodedata
from pathlib import Path

import pandas as pd
import streamlit as st

BASE = Path(__file__).parent
DATA_FILE = BASE / "gastos.csv"
BACKUP_FILE = BASE / "gastos.bak.csv"
CONFIG_FILE = BASE / "config.json"
CATEGORIAS_FILE = BASE / "supabase" / "functions" / "gastos-mcp" / "categorias.json"

# utf-8-sig: acentos aparecem corretos quando o CSV e aberto no Excel do Windows
CSV_ENCODING = "utf-8-sig"

# Nomes das colunas no banco -> nomes usados no app
COLUNAS_BANCO = {"data": "Data", "descricao": "Descrição", "categoria": "Categoria",
                 "valor": "Valor", "pagamento": "Pagamento"}


def _segredos_supabase() -> dict | None:
    try:
        return dict(st.secrets["supabase"])
    except Exception:  # noqa: BLE001 - sem secrets.toml ou sem a secao [supabase]
        return None


_SEGREDOS = _segredos_supabase()
NUVEM = _SEGREDOS is not None


@st.cache_resource
def _cliente():
    from supabase import create_client
    return create_client(_SEGREDOS["url"], _SEGREDOS["key"])


def _para_linhas(df: pd.DataFrame) -> list[dict]:
    """DataFrame do app -> lista de dicionarios no formato do banco."""
    linhas = []
    for _, r in df.iterrows():
        linhas.append({
            "data": pd.Timestamp(r["Data"]).date().isoformat(),
            "descricao": str(r["Descrição"]),
            "categoria": str(r["Categoria"]),
            "valor": float(r["Valor"]),
            "pagamento": str(r["Pagamento"]),
        })
    return linhas


# --------------------------------------------------------------------------
# Gastos
# --------------------------------------------------------------------------
def ler_gastos() -> pd.DataFrame | None:
    """Tabela de gastos sem tratamento, ou None se ainda nao existe nenhuma."""
    if NUVEM:
        linhas = _cliente().rpc("exportar_gastos").execute().data or []
        return pd.DataFrame(linhas, columns=list(COLUNAS_BANCO)).rename(columns=COLUNAS_BANCO)
    if DATA_FILE.exists():
        return pd.read_csv(DATA_FILE, encoding=CSV_ENCODING)
    return None


def gravar_gastos(df: pd.DataFrame, backup: bool = True) -> None:
    """Substitui todos os gastos por df; guarda a versao anterior para permitir desfazer."""
    if NUVEM:
        _cliente().rpc("substituir_gastos", {"novos": _para_linhas(df), "p_backup": backup}).execute()
        return
    if backup and DATA_FILE.exists():
        shutil.copy2(DATA_FILE, BACKUP_FILE)
    df.to_csv(DATA_FILE, index=False, encoding=CSV_ENCODING)


def inserir_gasto(novo: pd.DataFrame) -> None:
    """Na nuvem insere so a linha nova, sem regravar o que o Claude lancou nesse meio tempo."""
    linha = _para_linhas(novo)[0]
    _cliente().rpc("inserir_gasto", {f"p_{k}": v for k, v in linha.items()}).execute()


def tem_backup() -> bool:
    if NUVEM:
        return bool(_cliente().table("backup").select("id").limit(1).execute().data)
    return BACKUP_FILE.exists()


def desfazer() -> None:
    """Volta os gastos para a versao anterior a ultima alteracao."""
    if NUVEM:
        _cliente().rpc("desfazer_gastos").execute()
        return
    shutil.copy2(BACKUP_FILE, DATA_FILE)
    BACKUP_FILE.unlink()


# --------------------------------------------------------------------------
# Configuracoes (salario, meta e limites)
# --------------------------------------------------------------------------
def ler_config() -> dict | None:
    if NUVEM:
        linhas = _cliente().table("config").select("dados").eq("id", 1).execute().data
        return linhas[0]["dados"] if linhas else None
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return None


def gravar_config(cfg: dict) -> None:
    if NUVEM:
        _cliente().table("config").upsert({"id": 1, "dados": cfg}).execute()
        return
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")


# --------------------------------------------------------------------------
# Categoria automatica (mesmas palavras-chave do conector do Claude)
# --------------------------------------------------------------------------
def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto)
                   if unicodedata.category(c) != "Mn").lower()


_PALAVRAS_CHAVE = json.loads(CATEGORIAS_FILE.read_text(encoding="utf-8"))["palavras_chave"]


def classificar(descricao: str) -> str:
    """Categoria pela primeira palavra-chave encontrada na descricao (ou "Outros")."""
    texto = _sem_acento(descricao)
    for categoria, palavras in _PALAVRAS_CHAVE.items():
        for palavra in palavras:
            if re.search(rf"(^|[^a-z0-9]){re.escape(palavra)}($|[^a-z0-9])", texto):
                return categoria
    return "Outros"
