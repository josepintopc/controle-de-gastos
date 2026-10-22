"""
Controle de Gastos - dashboard em Streamlit (tema amarelo e preto).

Como rodar (no terminal do VS Code):
    cd C:\\Users\\Usuario\\Documents\\Controle_de_gastos
    pip install -r requirements.txt
    python -m streamlit run Controledegastos.py

Os dados ficam em gastos.csv e as configuracoes (salario, meta e limites por
categoria) em config.json, ambos criados automaticamente na mesma pasta deste
arquivo. Antes de cada alteracao grande e feito um backup (gastos.bak.csv),
que permite desfazer a ultima mudanca.

Online (Streamlit Cloud + Supabase), os mesmos dados ficam num banco Postgres,
compartilhado com o conector do Claude. Veja armazenamento.py e o LEIA-ME.md.
"""
import datetime as dt
import html
import json
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# --------------------------------------------------------------------------
# Configuracao
# --------------------------------------------------------------------------
st.set_page_config(page_title="Controle de Gastos", page_icon="🟡", layout="wide")

import armazenamento  # noqa: E402 - le st.secrets, precisa vir depois do set_page_config

COLUMNS = ["Data", "Descrição", "Categoria", "Valor", "Pagamento"]
CATEGORIAS = [
    "Moradia", "Alimentação", "Assinaturas", "Transporte", "Cartão de Crédito",
    "Lazer", "Saúde", "Educação", "Imprevistos", "Outros",
]
PAGAMENTOS = ["Débito/Pix", "Cartão de crédito", "Dinheiro", "Boleto"]
MESES = [
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]

YELLOW = "#FFD60A"
BLACK = "#000000"
PANEL = "#141414"
MUTED = "#9A9A9A"
RED = "#FF4D4D"
PALETTE = ["#FFD60A", "#FFFFFF", "#B38F00", "#8C8C8C", "#FFE867",
           "#5C5C5C", "#FFF3B0", "#3D3D3D", "#D4AF00", "#BFBFBF"]

CSV_ENCODING = armazenamento.CSV_ENCODING
# O servidor na nuvem roda em UTC; as datas do app seguem o horario de Brasilia
FUSO = ZoneInfo("America/Sao_Paulo")


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def brl(valor: float) -> str:
    """Formata numero como moeda brasileira: R$ 1.234,56"""
    texto = f"{abs(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"-R$ {texto}" if valor < 0 else f"R$ {texto}"


def normalizar(df: pd.DataFrame) -> pd.DataFrame:
    """Garante colunas, tipos e valores padrao para qualquer tabela de gastos."""
    df = df.copy()
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = None
    df = df[COLUMNS].copy()
    df["Data"] = pd.to_datetime(df["Data"], errors="coerce")
    df["Valor"] = pd.to_numeric(df["Valor"], errors="coerce")
    df["Descrição"] = df["Descrição"].fillna("").astype(str)
    df["Categoria"] = df["Categoria"].fillna("Outros")
    df["Pagamento"] = df["Pagamento"].fillna("Débito/Pix")
    df = df.dropna(subset=["Valor"])
    return df.reset_index(drop=True)


def dados_exemplo() -> pd.DataFrame:
    hoje = dt.date.today()

    def d(dia):
        return dt.date(hoje.year, hoje.month, dia)

    linhas = [
        (d(5), "Aluguel", "Moradia", 1250.0, "Débito/Pix"),
        (d(10), "Água", "Moradia", 60.0, "Débito/Pix"),
        (d(10), "Energia", "Moradia", 250.0, "Débito/Pix"),
        (d(12), "Mercado do mês", "Alimentação", 1500.0, "Débito/Pix"),
        (d(8), "IA (assinatura)", "Assinaturas", 110.0, "Cartão de crédito"),
        (d(8), "Prime, Netflix, Meli, Spotify, YouTube Premium e Gmail Pro",
         "Assinaturas", 160.0, "Cartão de crédito"),
        (d(15), "Gasolina", "Transporte", 1000.0, "Débito/Pix"),
        (d(20), "Fatura do cartão (média)", "Cartão de Crédito", 2000.0, "Cartão de crédito"),
    ]
    return pd.DataFrame(linhas, columns=COLUMNS)


def salvar_dados(df: pd.DataFrame, backup: bool = True) -> None:
    """Salva os dados; guarda a versao anterior para permitir desfazer."""
    armazenamento.gravar_gastos(normalizar(df), backup=backup)


def adicionar_gasto(df: pd.DataFrame, novo: pd.DataFrame) -> None:
    """Na nuvem insere so a linha nova; no PC regrava o CSV com ela no fim."""
    if armazenamento.NUVEM:
        armazenamento.inserir_gasto(normalizar(novo))
    else:
        salvar_dados(pd.concat([df, novo], ignore_index=True))


def carregar_dados() -> pd.DataFrame:
    try:
        bruto = armazenamento.ler_gastos()
    except (pd.errors.EmptyDataError, UnicodeDecodeError):
        st.warning("O arquivo gastos.csv estava vazio ou ilegível. Comecei com os dados de exemplo.")
        bruto = None
    if bruto is not None:
        return normalizar(bruto)
    df = normalizar(dados_exemplo())
    salvar_dados(df, backup=False)
    return df


def carregar_config() -> dict:
    padrao = {"salario": 9000.0, "meta": 1000.0, "limites": {}}
    try:
        return {**padrao, **(armazenamento.ler_config() or {})}
    except (json.JSONDecodeError, OSError):
        return padrao


def salvar_config(cfg: dict) -> None:
    armazenamento.gravar_config(cfg)


def mes_anterior(ano: int, mes: int) -> tuple[int, int]:
    return (ano - 1, 12) if mes == 1 else (ano, mes - 1)


def total_do_mes(df: pd.DataFrame, ano: int, mes: int) -> float:
    m = (df["Data"].dt.year == ano) & (df["Data"].dt.month == mes)
    return float(df.loc[m, "Valor"].sum())


def validar_linhas(df: pd.DataFrame) -> list[str]:
    """Devolve avisos sobre linhas problematicas de uma tabela editada."""
    avisos = []
    sem_desc = int((df["Descrição"].fillna("").astype(str).str.strip() == "").sum())
    sem_valor = int(df["Valor"].isna().sum())
    zerados = int((df["Valor"].fillna(1) <= 0).sum())
    if sem_desc:
        avisos.append(f"{sem_desc} linha(s) sem descrição.")
    if sem_valor:
        avisos.append(f"{sem_valor} linha(s) sem valor — elas serão descartadas ao salvar.")
    if zerados:
        avisos.append(f"{zerados} linha(s) com valor zero ou negativo.")
    return avisos


# --------------------------------------------------------------------------
# Estilo
# --------------------------------------------------------------------------
st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Archivo:wght@400;600;800;900&display=swap');

    html, body, .stApp, p, h1, h2, h3, h4, label, input, textarea, button,
    div[data-testid="stMarkdownContainer"] {{
        font-family: 'Archivo', sans-serif;
    }}
    .stApp {{ background: {BLACK}; }}
    #MainMenu, footer {{ visibility: hidden; }}
    header[data-testid="stHeader"] {{ background: transparent; }}
    .block-container {{ padding-top: 2.2rem; max-width: 1200px; }}
    section[data-testid="stSidebar"] {{ background: {PANEL}; border-right: 1px solid #262626; }}

    .titulo {{ font-size: 1.05rem; font-weight: 600; color: {MUTED}; margin-bottom: 14px; }}

    .hero {{ background: {YELLOW}; color: {BLACK}; border-radius: 6px; padding: 28px 32px; }}
    .hero.negativo {{ background: {RED}; }}
    .hero .mes {{ font-size: 1rem; font-weight: 600; }}
    .hero .valor {{ font-size: 4.2rem; font-weight: 900; line-height: 1.05; letter-spacing: -0.02em; }}
    .hero .texto {{ font-size: 1.05rem; font-weight: 600; margin-top: 4px; }}
    .hero .trilho {{ height: 10px; background: rgba(0,0,0,.18); border-radius: 5px; margin-top: 20px; }}
    .hero .trilho span {{ display: block; height: 100%; background: {BLACK}; border-radius: 5px; }}

    .item {{ display: flex; justify-content: space-between; gap: 16px; padding-top: 10px;
             font-size: .95rem; color: #EDEDED; }}
    .item b {{ color: {YELLOW}; font-weight: 800; white-space: nowrap; }}
    .barra {{ height: 4px; background: #262626; border-radius: 2px; margin-top: 4px; }}
    .barra span {{ display: block; height: 100%; background: {YELLOW}; border-radius: 2px; }}

    div[data-testid="stMetric"] {{ background: {PANEL}; border-left: 4px solid {YELLOW};
             border-radius: 4px; padding: 10px 16px; }}

    div.stButton > button, div[data-testid="stFormSubmitButton"] > button,
    div[data-testid="stDownloadButton"] > button {{
        background: {YELLOW}; color: {BLACK}; border: none; font-weight: 800; border-radius: 4px;
    }}
    div.stButton > button:hover, div[data-testid="stFormSubmitButton"] > button:hover,
    div[data-testid="stDownloadButton"] > button:hover {{
        background: #FFE867; color: {BLACK};
    }}
    button[data-baseweb="tab"] {{ font-weight: 600; }}
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------
# Dados e barra lateral
# --------------------------------------------------------------------------
df = carregar_dados()
cfg = carregar_config()
hoje = dt.datetime.now(FUSO).date()

# Versao da tabela editavel: muda a cada salvamento para zerar as edicoes pendentes
if "versao_editor" not in st.session_state:
    st.session_state.versao_editor = 0

with st.sidebar:
    st.markdown("### Período")
    ano = int(st.number_input("Ano", min_value=2000, max_value=2100, value=hoje.year, step=1,
                              help="Ano que você quer analisar."))
    mes_nome = st.selectbox("Mês", MESES, index=hoje.month - 1,
                            help="Todos os números e gráficos da página usam este mês.")
    mes = MESES.index(mes_nome) + 1

    st.markdown("### Seus números")
    salario = st.number_input(
        "Salário líquido (R$)", min_value=0.0, value=float(cfg["salario"]), step=100.0,
        format="%.2f", help="O que cai na sua conta por mês, já com os descontos.")
    meta = st.number_input(
        "Meta de economia mensal (R$)", min_value=0.0, value=float(cfg["meta"]), step=100.0,
        format="%.2f", help="Quanto você quer guardar por mês. A barra do painel mostra o progresso.")
    if meta > salario > 0:
        st.warning("Sua meta é maior que o salário — ela não poderá ser atingida.")

    with st.expander("Limites por categoria (opcional)"):
        st.caption("Defina um teto mensal para uma categoria. Use 0 para não ter limite. "
                   "Você será avisado quando chegar perto ou passar.")
        limites = {}
        for cat in CATEGORIAS:
            limites[cat] = st.number_input(
                cat, min_value=0.0, value=float(cfg["limites"].get(cat, 0.0)),
                step=50.0, format="%.2f", key=f"lim_{cat}")

    if salario != cfg["salario"] or meta != cfg["meta"] or limites != cfg["limites"]:
        cfg = {"salario": salario, "meta": meta, "limites": limites}
        salvar_config(cfg)

    st.markdown("### Novo gasto")
    with st.form("novo_gasto", clear_on_submit=True):
        f_data = st.date_input("Data", value=hoje, format="DD/MM/YYYY")
        f_desc = st.text_input("Descrição", placeholder="Ex.: Mercado, Uber, Netflix")
        f_cat = st.selectbox("Categoria", ["Automática"] + CATEGORIAS,
                             help="Automática: escolhe a categoria pela descrição (ex.: Uber → Transporte).")
        f_valor = st.number_input("Valor (R$)", min_value=0.0, step=10.0, format="%.2f")
        f_pag = st.selectbox("Pagamento", PAGAMENTOS)
        enviar = st.form_submit_button("Adicionar", width="stretch")
    if enviar:
        if f_valor <= 0 or not f_desc.strip():
            st.warning("Preencha a descrição e um valor maior que zero.")
        else:
            if f_cat == "Automática":
                f_cat = armazenamento.classificar(f_desc)
            repetido = ((df["Data"] == pd.Timestamp(f_data)) & (df["Valor"] == f_valor)
                        & (df["Descrição"].str.lower() == f_desc.strip().lower())).any()
            novo = pd.DataFrame([[pd.Timestamp(f_data), f_desc.strip(), f_cat, f_valor, f_pag]],
                                columns=COLUMNS)
            adicionar_gasto(df, novo)
            st.session_state.versao_editor += 1
            st.session_state.aviso_pos = (
                "Atenção: já existia um gasto idêntico (mesma data, descrição e valor). "
                "Se foi sem querer, apague um deles na aba Lançamentos." if repetido else None)
            st.toast(f"Adicionado: {f_desc.strip()} — {brl(f_valor)} ({f_cat})",
                     icon=":material/check_circle:")
            st.rerun()

    with st.expander("Importar da planilha Excel"):
        st.caption("Use o arquivo Controle_de_Gastos.xlsx (aba Lançamentos). "
                   "Isso **substitui** todos os dados atuais do app.")
        arquivo = st.file_uploader("Arquivo .xlsx", type="xlsx")
        if arquivo is not None:
            try:
                bruto = pd.read_excel(arquivo, sheet_name="Lançamentos", header=3, usecols="A:E")
                bruto = bruto.rename(columns={"Valor (R$)": "Valor",
                                              "Forma de pagamento": "Pagamento"})
                importado = normalizar(bruto).dropna(subset=["Data"])
                st.info(f"Encontrei {len(importado)} lançamentos, somando {brl(importado['Valor'].sum())}. "
                        f"Hoje o app tem {len(df)}.")
                ok = st.checkbox("Entendo que os dados atuais serão substituídos")
                if st.button("Importar e substituir", disabled=not ok):
                    salvar_dados(importado)
                    st.session_state.versao_editor += 1
                    st.toast(f"{len(importado)} lançamentos importados!", icon=":material/check_circle:")
                    st.rerun()
            except Exception as erro:  # noqa: BLE001
                st.error(f"Não consegui ler a planilha. Confira se ela tem a aba 'Lançamentos'. Detalhe: {erro}")

    if armazenamento.tem_backup():
        with st.expander("Desfazer"):
            st.caption("Volta os dados para a versão anterior à última alteração "
                       "(inclusive um gasto lançado pelo Claude).")
            if st.button("Desfazer última alteração", icon=":material/undo:"):
                armazenamento.desfazer()
                st.session_state.versao_editor += 1
                st.toast("Última alteração desfeita.", icon=":material/undo:")
                st.rerun()


# --------------------------------------------------------------------------
# Calculos do mes selecionado
# --------------------------------------------------------------------------
mascara = (df["Data"].dt.year == ano) & (df["Data"].dt.month == mes)
mes_df = df[mascara].copy()

gasto = float(mes_df["Valor"].sum())
sobra = salario - gasto
pct_salario = (gasto / salario * 100) if salario > 0 else 0.0
pct_meta = (sobra / meta * 100) if meta > 0 else 0.0
por_categoria = (mes_df.groupby("Categoria")["Valor"].sum().sort_values(ascending=False)
                 if not mes_df.empty else pd.Series(dtype=float))

ano_ant, mes_ant = mes_anterior(ano, mes)
gasto_ant = total_do_mes(df, ano_ant, mes_ant)
por_categoria_ant = df[(df["Data"].dt.year == ano_ant) & (df["Data"].dt.month == mes_ant)] \
    .groupby("Categoria")["Valor"].sum()


def montar_alertas() -> list[tuple[str, str]]:
    """Lista (nivel, mensagem) com o que o usuario precisa saber agora."""
    alertas = []
    if gasto == 0:
        return alertas
    if salario > 0 and gasto > salario:
        alertas.append(("error", f"Você gastou **{brl(gasto - salario)} a mais** do que ganha neste mês."))
    elif meta > 0 and sobra < meta:
        alertas.append(("warning", f"Faltam **{brl(meta - sobra)}** para bater a meta de economia."))
    elif meta > 0:
        alertas.append(("success", "Meta de economia atingida neste mês. Parabéns!"))
    for cat, v in por_categoria.items():
        lim = limites.get(cat, 0.0)
        if lim > 0 and v > lim:
            alertas.append(("error", f"**{cat}** passou do limite: {brl(v)} de {brl(lim)}."))
        elif lim > 0 and v >= 0.8 * lim:
            alertas.append(("warning", f"**{cat}** está em {v / lim * 100:.0f}% do limite ({brl(v)} de {brl(lim)})."))
    if gasto_ant > 0 and gasto > gasto_ant * 1.2:
        alertas.append(("info", f"Seus gastos estão {((gasto / gasto_ant) - 1) * 100:.0f}% acima de "
                                f"{MESES[mes_ant - 1].lower()}."))
    return alertas


# --------------------------------------------------------------------------
# Pagina
# --------------------------------------------------------------------------
st.markdown("<div class='titulo'>Controle de Gastos</div>", unsafe_allow_html=True)

if st.session_state.get("aviso_pos"):
    st.warning(st.session_state.pop("aviso_pos"), icon=":material/content_copy:")

if df.empty or gasto == 0:
    with st.expander("Primeiros passos: como usar o app", expanded=df.empty):
        st.markdown(
            "1. **Menu lateral → Seus números:** informe seu salário líquido e quanto quer economizar por mês.\n"
            "2. **Novo gasto:** registre cada despesa com data, categoria e valor.\n"
            "3. **Visão geral:** veja quanto sobrou, para onde foi o dinheiro e se você está no caminho da meta.\n"
            "4. **Orçamento:** acompanhe os limites que definir para cada categoria.\n"
            "5. **Lançamentos:** edite, filtre ou apague registros. Tudo é salvo em `gastos.csv`."
        )

aba_geral, aba_orc, aba_lanc = st.tabs(["Visão geral", "Orçamento", "Lançamentos"])

# ---- Visao geral ----------------------------------------------------------
with aba_geral:
    col_hero, col_stats = st.columns([3, 2], gap="medium")

    with col_hero:
        if gasto == 0:
            rotulo, mensagem = "Sem gastos lançados", "Adicione um gasto no menu lateral para começar."
        else:
            rotulo = "Sobraram" if sobra >= 0 else "Faltaram"
            if meta == 0:
                mensagem = "Defina uma meta de economia no menu lateral."
            elif sobra >= meta:
                mensagem = f"Meta de {brl(meta)} atingida ({pct_meta:.0f}% da meta)."
            else:
                mensagem = f"Faltam {brl(meta - sobra)} para a meta de {brl(meta)}."
        largura = max(0.0, min(100.0, pct_meta)) if gasto > 0 else 0.0
        classe = "hero negativo" if (gasto > 0 and sobra < 0) else "hero"
        st.markdown(
            f"""
            <div class="{classe}">
              <div class="mes">{mes_nome} de {ano}. {rotulo}</div>
              <div class="valor">{brl(abs(sobra)) if gasto > 0 else brl(salario)}</div>
              <div class="texto">{html.escape(mensagem)}</div>
              <div class="trilho"><span style="width:{largura:.0f}%"></span></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col_stats:
        maior = por_categoria.index[0] if len(por_categoria) else "—"
        maior_pct = (por_categoria.iloc[0] / gasto * 100) if len(por_categoria) and gasto else 0
        delta = (f"{brl(gasto - gasto_ant)} vs {MESES[mes_ant - 1][:3].lower()}"
                 if gasto_ant > 0 and gasto > 0 else None)
        st.metric("Total gasto", brl(gasto), delta=delta, delta_color="inverse",
                  help="Soma de todos os lançamentos do mês. A seta compara com o mês anterior: "
                       "vermelho = gastou mais, verde = gastou menos.")
        st.metric("Parte do salário gasta", f"{pct_salario:.1f}%",
                  help="Total gasto dividido pelo salário líquido.")
        st.metric("Onde mais gastou", str(maior),
                  delta=f"{maior_pct:.0f}% dos gastos" if maior_pct else None, delta_color="off",
                  help="A categoria com o maior total no mês.")

    alertas = montar_alertas()
    if alertas:
        st.write("")
        st.markdown("**O que merece sua atenção**")
        for nivel, texto in alertas:
            getattr(st, nivel)(texto)

    st.write("")
    graf1, graf2 = st.columns(2, gap="medium")

    # Rosca por categoria
    with graf1:
        st.markdown("**Para onde foi o dinheiro**")
        st.caption("Passe o mouse nas fatias para ver valor e percentual. "
                   "Clique numa categoria da legenda para ocultá-la.")
        if por_categoria.empty:
            st.info("Sem dados neste mês.")
        else:
            fig = go.Figure(go.Pie(
                labels=por_categoria.index, values=por_categoria.values, hole=0.62,
                marker=dict(colors=PALETTE, line=dict(color=BLACK, width=2)),
                textinfo="none", sort=False,
                hovertemplate="%{label}<br>R$ %{value:,.2f}<br>%{percent}<extra></extra>",
            ))
            fig.update_layout(
                height=340, margin=dict(l=0, r=0, t=10, b=0),
                paper_bgcolor="rgba(0,0,0,0)", font=dict(color="#F5F5F5"),
                legend=dict(font=dict(size=12)),
                separators=",.",
                annotations=[dict(text=f"<b>{brl(gasto)}</b>", x=0.5, y=0.5,
                                  showarrow=False, font=dict(size=16, color=YELLOW))],
            )
            st.plotly_chart(fig, width="stretch")

    # Evolucao mensal no ano
    with graf2:
        st.markdown(f"**Gasto e economia em {ano}**")
        st.caption("A linha vermelha tracejada é a sua meta de economia. "
                   "Meses sem lançamentos aparecem vazios.")
        do_ano = df[df["Data"].dt.year == ano]
        mensal = (do_ano.groupby(do_ano["Data"].dt.month)["Valor"].sum()
                  .reindex(range(1, 13), fill_value=0))
        economia = [(salario - v) if v > 0 else 0 for v in mensal.values]
        rotulos = [m[:3] for m in MESES]
        fig2 = go.Figure()
        fig2.add_bar(x=rotulos, y=mensal.values, name="Gasto", marker_color=YELLOW,
                     hovertemplate="%{x}<br>Gasto: R$ %{y:,.2f}<extra></extra>")
        fig2.add_bar(x=rotulos, y=economia, name="Economia", marker_color="#FFFFFF",
                     hovertemplate="%{x}<br>Economia: R$ %{y:,.2f}<extra></extra>")
        fig2.add_scatter(x=rotulos, y=[meta] * 12, name="Meta", mode="lines",
                         line=dict(color=RED, width=2, dash="dash"), hoverinfo="skip")
        fig2.update_layout(
            height=340, barmode="group", margin=dict(l=0, r=0, t=10, b=0),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#F5F5F5"),
            separators=",.",
            legend=dict(orientation="h", y=-0.15),
            yaxis=dict(gridcolor="#262626", tickprefix="R$ "),
            xaxis=dict(showgrid=False),
        )
        st.plotly_chart(fig2, width="stretch")

    # Maiores gastos do mes
    st.markdown("**Os cinco maiores gastos do mês**")
    if mes_df.empty:
        st.caption("Nada lançado neste mês ainda.")
    else:
        top = mes_df.sort_values("Valor", ascending=False).head(5)
        topo = float(top["Valor"].max()) or 1.0
        linhas = "".join(
            f"""<div class="item"><span>{html.escape(str(r['Descrição']))}</span><b>{brl(r['Valor'])}</b></div>
                <div class="barra"><span style="width:{r['Valor'] / topo * 100:.0f}%"></span></div>"""
            for _, r in top.iterrows()
        )
        st.markdown(linhas, unsafe_allow_html=True)

# ---- Orcamento ------------------------------------------------------------
with aba_orc:
    st.markdown(f"**Orçamento de {mes_nome} de {ano}**")
    st.caption("Cada barra mostra quanto do limite da categoria já foi usado. "
               "Defina os limites no menu lateral, em *Limites por categoria*.")
    cats_com_dado = [c for c in CATEGORIAS if por_categoria.get(c, 0) > 0 or limites.get(c, 0) > 0]
    if not cats_com_dado:
        st.info("Nenhum gasto ou limite neste mês. Registre um gasto ou defina um limite para ver o orçamento.")
    else:
        for cat in cats_com_dado:
            v = float(por_categoria.get(cat, 0.0))
            lim = float(limites.get(cat, 0.0))
            anterior = float(por_categoria_ant.get(cat, 0.0))
            cmp_txt = ""
            if anterior > 0 and v > 0:
                cmp_txt = f" · {((v / anterior) - 1) * 100:+.0f}% vs {MESES[mes_ant - 1][:3].lower()}"
            if lim > 0:
                usado = v / lim
                icone = ":material/error:" if usado > 1 else (":material/warning:" if usado >= 0.8
                                                              else ":material/check_circle:")
                st.markdown(f"{icone} **{cat}**")
                st.progress(min(usado, 1.0),
                            text=f"{brl(v)} de {brl(lim)} ({usado * 100:.0f}%){cmp_txt}")
            else:
                st.markdown(f":material/remove: **{cat}** — {brl(v)}{cmp_txt}")
                st.caption("Sem limite definido.")

    if not por_categoria.empty:
        with st.expander("Ver tabela detalhada por categoria"):
            tabela = pd.DataFrame({
                "Categoria": por_categoria.index,
                "Total": por_categoria.values,
                "% do gasto": por_categoria.values / gasto * 100,
                "Mês anterior": [float(por_categoria_ant.get(c, 0.0)) for c in por_categoria.index],
            })
            st.dataframe(
                tabela, hide_index=True, width="stretch",
                column_config={
                    "Total": st.column_config.NumberColumn(format="R$ %.2f"),
                    "% do gasto": st.column_config.NumberColumn(format="%.1f%%"),
                    "Mês anterior": st.column_config.NumberColumn(format="R$ %.2f"),
                },
                alt="Total gasto por categoria no mês, com percentual e valor do mês anterior",
            )

# ---- Lancamentos ----------------------------------------------------------
with aba_lanc:
    st.markdown(f"**Lançamentos de {mes_nome} de {ano}**")
    modo = st.segmented_control("Modo", ["Editar", "Filtrar e consultar"], default="Editar",
                                label_visibility="collapsed",
                                help="Editar: altera a tabela do mês. Filtrar: só consulta, sem risco de mudar nada.")

    if modo == "Filtrar e consultar":
        st.caption("Modo somente leitura: use os filtros para encontrar gastos específicos.")
        f1, f2, f3 = st.columns([2, 2, 3])
        with f1:
            f_cats = st.multiselect("Categorias", CATEGORIAS, placeholder="Todas")
        with f2:
            f_pags = st.multiselect("Pagamento", PAGAMENTOS, placeholder="Todos")
        with f3:
            busca = st.text_input("Buscar na descrição", placeholder="Ex.: mercado")
        vista = mes_df
        if f_cats:
            vista = vista[vista["Categoria"].isin(f_cats)]
        if f_pags:
            vista = vista[vista["Pagamento"].isin(f_pags)]
        if busca.strip():
            vista = vista[vista["Descrição"].str.contains(busca.strip(), case=False, na=False, regex=False)]
        if vista.empty:
            st.info("Nenhum lançamento com esses filtros.")
        else:
            m1, m2 = st.columns(2)
            m1.metric("Lançamentos encontrados", len(vista))
            m2.metric("Soma", brl(float(vista["Valor"].sum())))
            st.dataframe(
                vista.sort_values("Data"), hide_index=True, width="stretch",
                column_config={
                    "Data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                    "Valor": st.column_config.NumberColumn("Valor (R$)", format="R$ %.2f"),
                },
                alt="Lançamentos do mês filtrados",
            )
    else:
        st.caption("Clique numa célula para editar. Para adicionar, use a última linha da tabela; "
                   "para apagar, marque a linha à esquerda e aperte Delete. "
                   "**Nada é gravado até você clicar em Salvar alterações.**")
        original = mes_df.sort_values("Data").reset_index(drop=True)
        editado = st.data_editor(
            original,
            num_rows="dynamic",
            hide_index=True,
            key=f"editor_{ano}_{mes}_{st.session_state.versao_editor}",
            width="stretch",
            column_config={
                "Data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                "Descrição": st.column_config.TextColumn("Descrição"),
                "Categoria": st.column_config.SelectboxColumn("Categoria", options=CATEGORIAS),
                "Valor": st.column_config.NumberColumn("Valor (R$)", format="R$ %.2f", min_value=0.0),
                "Pagamento": st.column_config.SelectboxColumn("Pagamento", options=PAGAMENTOS),
            },
            alt="Tabela editável de lançamentos do mês",
        )

        # Resumo das mudancas pendentes, antes de gravar
        pendente = normalizar(editado).to_csv(index=False) != normalizar(original).to_csv(index=False)
        removidas = max(len(original) - len(editado), 0)
        adicionadas = max(len(editado) - len(original), 0)
        avisos = validar_linhas(editado)

        if pendente:
            st.info(
                f"**Alterações pendentes** — linhas: {len(original)} → {len(editado)} "
                f"({adicionadas} nova(s), {removidas} removida(s)); "
                f"total do mês: {brl(gasto)} → {brl(float(pd.to_numeric(editado['Valor'], errors='coerce').sum()))}.",
                icon=":material/edit_note:")
        else:
            st.caption("Sem alterações pendentes.")
        for aviso in avisos:
            st.warning(aviso)

        confirmar = True
        if removidas > 0:
            confirmar = st.checkbox(f"Confirmo a remoção de {removidas} lançamento(s)")

        c1, c2 = st.columns([1, 3])
        with c1:
            if st.button("Salvar alterações", disabled=not pendente or not confirmar,
                         help="Grava as mudanças em gastos.csv. Você poderá desfazer pelo menu lateral."):
                editado = editado.copy()
                editado["Data"] = pd.to_datetime(editado["Data"], errors="coerce").fillna(
                    pd.Timestamp(ano, mes, 1))
                novo_df = pd.concat([df[~mascara], normalizar(editado)], ignore_index=True)
                salvar_dados(novo_df)
                st.session_state.versao_editor += 1
                st.toast("Alterações salvas! Dá para desfazer no menu lateral.",
                         icon=":material/check_circle:")
                st.rerun()
        with c2:
            st.download_button("Baixar todos os dados (CSV)",
                               data=df.to_csv(index=False).encode(CSV_ENCODING),
                               file_name="gastos.csv", mime="text/csv",
                               help="Cópia de segurança de todos os meses, abre direto no Excel.")
