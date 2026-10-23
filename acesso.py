"""
Quem pode abrir o Controle de Gastos.

- Sem a secao [auth] nos segredos (uso no PC): sem login, acesso completo, como antes.
- Com [auth]: exige login Google (st.login) e confere o e-mail com a secao [acesso]:
      donos    -> veem e alteram tudo
      leitores -> so veem (sem lancar, editar, importar ou desfazer)
  Qualquer outro e-mail e barrado antes de qualquer dado ser carregado.
"""
import streamlit as st


def _secao(nome: str) -> dict | None:
    try:
        return dict(st.secrets[nome])
    except Exception:  # noqa: BLE001 - sem secrets.toml ou sem a secao
        return None


def _emails(acesso: dict, chave: str) -> set[str]:
    return {str(e).strip().lower() for e in acesso.get(chave, [])}


def verificar_acesso() -> bool:
    """Para a pagina se o visitante nao for autorizado. Devolve True se ele pode alterar dados."""
    if _secao("auth") is None:
        return True

    if not st.user.get("is_logged_in", False):
        st.markdown("<div class='titulo'>Controle de Gastos</div>", unsafe_allow_html=True)
        st.markdown("Acesso restrito. Entre com a sua conta Google autorizada.")
        st.button("Entrar com Google", icon=":material/login:", on_click=st.login, args=("google",))
        st.stop()

    acesso = _secao("acesso") or {}
    email = str(st.user.get("email", "")).strip().lower()
    verificado = bool(st.user.get("email_verified", False))
    dono = verificado and email in _emails(acesso, "donos")
    leitor = verificado and email in _emails(acesso, "leitores")

    if not (dono or leitor):
        st.markdown("<div class='titulo'>Controle de Gastos</div>", unsafe_allow_html=True)
        st.error(f"Acesso não autorizado para **{email or 'esta conta'}**.")
        st.button("Sair", icon=":material/logout:", on_click=st.logout)
        st.stop()

    with st.sidebar:
        st.caption(f"{email} · {'Dono' if dono else 'Leitor (somente leitura)'}")
        st.button("Sair", icon=":material/logout:", on_click=st.logout)
    return dono
