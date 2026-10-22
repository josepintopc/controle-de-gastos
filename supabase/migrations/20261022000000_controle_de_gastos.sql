-- Controle de Gastos: tabelas e funcoes usadas pelo app Streamlit e pelo conector MCP.
-- Tudo fica fechado por RLS (sem policies): so a chave de servico acessa.

create table if not exists public.gastos (
    id         bigint generated always as identity primary key,
    data       date          not null,
    descricao  text          not null default '',
    categoria  text          not null default 'Outros',
    valor      numeric(12,2) not null,
    pagamento  text          not null default 'Débito/Pix',
    criado_em  timestamptz   not null default now()
);
create index if not exists gastos_data_idx on public.gastos (data);

-- Copia da tabela antes da ultima alteracao (equivale ao gastos.bak.csv)
create table if not exists public.backup (
    id        int         primary key default 1 check (id = 1),
    linhas    jsonb       not null,
    criado_em timestamptz not null default now()
);

-- Salario, meta e limites (equivale ao config.json)
create table if not exists public.config (
    id    int   primary key default 1 check (id = 1),
    dados jsonb not null
);

alter table public.gastos enable row level security;
alter table public.backup enable row level security;
alter table public.config enable row level security;


create or replace function public.fazer_backup()
returns void
language sql
set search_path = public
as $$
    insert into backup (id, linhas, criado_em)
    values (1, coalesce((select jsonb_agg(to_jsonb(g) order by g.data, g.id) from gastos g), '[]'::jsonb), now())
    on conflict (id) do update set linhas = excluded.linhas, criado_em = excluded.criado_em;
$$;


-- Todos os gastos num unico JSON (evita o limite de 1000 linhas da API)
create or replace function public.exportar_gastos()
returns jsonb
language sql
stable
set search_path = public
as $$
    select coalesce(jsonb_agg(jsonb_build_object(
               'data', data, 'descricao', descricao, 'categoria', categoria,
               'valor', valor, 'pagamento', pagamento) order by data, id), '[]'::jsonb)
    from gastos;
$$;


-- Troca a tabela inteira pelas linhas recebidas (usado ao salvar edicoes e importar)
create or replace function public.substituir_gastos(novos jsonb, p_backup boolean default true)
returns void
language plpgsql
set search_path = public
as $$
begin
    if p_backup then
        perform fazer_backup();
    end if;
    delete from gastos where true;
    insert into gastos (data, descricao, categoria, valor, pagamento)
    select r.data, coalesce(r.descricao, ''), coalesce(r.categoria, 'Outros'),
           r.valor, coalesce(r.pagamento, 'Débito/Pix')
    from jsonb_to_recordset(novos)
         as r(data date, descricao text, categoria text, valor numeric, pagamento text)
    where r.valor is not null;
end;
$$;


-- Insere um gasto (formulario do app e conector do Claude)
create or replace function public.inserir_gasto(
    p_data date, p_descricao text, p_categoria text, p_valor numeric, p_pagamento text)
returns bigint
language plpgsql
set search_path = public
as $$
declare
    novo_id bigint;
begin
    perform fazer_backup();
    insert into gastos (data, descricao, categoria, valor, pagamento)
    values (p_data, p_descricao, p_categoria, p_valor, p_pagamento)
    returning id into novo_id;
    return novo_id;
end;
$$;


-- Volta a tabela para a copia de seguranca e apaga a copia
create or replace function public.desfazer_gastos()
returns boolean
language plpgsql
set search_path = public
as $$
begin
    if not exists (select 1 from backup where id = 1) then
        return false;
    end if;
    delete from gastos where true;
    insert into gastos (data, descricao, categoria, valor, pagamento)
    select r.data, r.descricao, r.categoria, r.valor, r.pagamento
    from backup b,
         jsonb_to_recordset(b.linhas)
         as r(data date, descricao text, categoria text, valor numeric, pagamento text)
    where b.id = 1;
    delete from backup where id = 1;
    return true;
end;
$$;


-- Funcoes so podem ser chamadas pela chave de servico
revoke execute on function public.fazer_backup() from public, anon, authenticated;
revoke execute on function public.exportar_gastos() from public, anon, authenticated;
revoke execute on function public.substituir_gastos(jsonb, boolean) from public, anon, authenticated;
revoke execute on function public.inserir_gasto(date, text, text, numeric, text) from public, anon, authenticated;
revoke execute on function public.desfazer_gastos() from public, anon, authenticated;
grant execute on function public.fazer_backup() to service_role;
grant execute on function public.exportar_gastos() to service_role;
grant execute on function public.substituir_gastos(jsonb, boolean) to service_role;
grant execute on function public.inserir_gasto(date, text, text, numeric, text) to service_role;
grant execute on function public.desfazer_gastos() to service_role;
