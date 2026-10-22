"""
Envia os dados locais (gastos.csv e config.json) para o banco no Supabase. Rodar uma vez:

    cd Controle_de_gastos
    python migrar_para_supabase.py

Le a url e a chave de .streamlit/secrets.toml (secao [supabase]). Os arquivos locais
nao sao alterados. Se o banco ja tiver gastos, para sem mexer em nada; use --forcar
para substituir mesmo assim (o conteudo anterior fica no backup do botao Desfazer).
"""
import json
import sys
import tomllib
from pathlib import Path

import pandas as pd
from supabase import create_client

BASE = Path(__file__).parent
segredos = tomllib.loads((BASE / ".streamlit" / "secrets.toml").read_text(encoding="utf-8"))["supabase"]
cliente = create_client(segredos["url"], segredos["key"])

df = pd.read_csv(BASE / "gastos.csv", encoding="utf-8-sig")
df = df.dropna(subset=["Valor"])
linhas = [
    {
        "data": pd.Timestamp(r["Data"]).date().isoformat(),
        "descricao": "" if pd.isna(r["Descrição"]) else str(r["Descrição"]),
        "categoria": "Outros" if pd.isna(r["Categoria"]) else str(r["Categoria"]),
        "valor": float(r["Valor"]),
        "pagamento": "Débito/Pix" if pd.isna(r["Pagamento"]) else str(r["Pagamento"]),
    }
    for _, r in df.iterrows()
]

existentes = cliente.rpc("exportar_gastos").execute().data or []
if existentes and "--forcar" not in sys.argv:
    sys.exit(f"O banco já tem {len(existentes)} gasto(s). Nada foi alterado. "
             "Use --forcar para substituir.")

cliente.rpc("substituir_gastos", {"novos": linhas, "p_backup": bool(existentes)}).execute()
print(f"{len(linhas)} gastos enviados, somando R$ {df['Valor'].sum():,.2f}.")

config = BASE / "config.json"
if config.exists():
    cliente.table("config").upsert({"id": 1, "dados": json.loads(config.read_text(encoding="utf-8"))}).execute()
    print("Configurações (salário, meta e limites) enviadas.")

conferido = cliente.rpc("exportar_gastos").execute().data or []
print(f"Conferência: o banco agora tem {len(conferido)} gastos, somando "
      f"R$ {sum(float(g['valor']) for g in conferido):,.2f}.")
