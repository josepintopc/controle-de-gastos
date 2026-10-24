// Conector MCP do Controle de Gastos: deixa o app Claude (celular ou web)
// registrar e consultar gastos na mesma base usada pelo dashboard Streamlit.
//
// URL para colar no claude.ai (Conectores > Adicionar conector personalizado):
//   https://<projeto>.supabase.co/functions/v1/gastos-mcp/<MCP_TOKEN>/mcp
// Com MCP_TOKEN_LANCAR no lugar de MCP_TOKEN, o conector so registra gastos
// (sem listar_gastos e sem totais na confirmacao), para outra pessoa lancar.
import { Hono } from 'hono'
import { McpServer, StreamableHttpTransport } from 'mcp-lite'
import { z } from 'zod'
import { createClient } from '@supabase/supabase-js'
import dados from './categorias.json' with { type: 'json' }

const CATEGORIAS = dados.categorias as [string, ...string[]]
const PAGAMENTOS = dados.pagamentos as [string, ...string[]]
const PALAVRAS_CHAVE = dados.palavras_chave as Record<string, string[]>
const MESES = [
  'janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
  'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro',
]

const supabase = createClient(
  Deno.env.get('SUPABASE_URL')!,
  Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!,
)

// --------------------------------------------------------------------------
// Utilidades
// --------------------------------------------------------------------------
function brl(valor: number): string {
  return valor.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}

function semAcento(texto: string): string {
  return texto.normalize('NFD').replace(/\p{Diacritic}/gu, '').toLowerCase()
}

/** Categoria pela primeira palavra-chave encontrada na descricao (ou "Outros"). */
function classificar(descricao: string): string {
  const texto = semAcento(descricao)
  for (const [categoria, palavras] of Object.entries(PALAVRAS_CHAVE)) {
    for (const palavra of palavras) {
      if (new RegExp(`(^|[^a-z0-9])${palavra}($|[^a-z0-9])`).test(texto)) return categoria
    }
  }
  return 'Outros'
}

/** Data de hoje (AAAA-MM-DD) no horario de Brasilia. */
function hojeBrasilia(): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Sao_Paulo' }).format(new Date())
}

function intervaloDoMes(ano: number, mes: number): [string, string] {
  const inicio = `${ano}-${String(mes).padStart(2, '0')}-01`
  const [anoFim, mesFim] = mes === 12 ? [ano + 1, 1] : [ano, mes + 1]
  return [inicio, `${anoFim}-${String(mesFim).padStart(2, '0')}-01`]
}

type Gasto = { data: string; descricao: string; categoria: string; valor: number; pagamento: string }

async function gastosDoMes(ano: number, mes: number): Promise<Gasto[]> {
  const [inicio, fim] = intervaloDoMes(ano, mes)
  const { data, error } = await supabase
    .from('gastos')
    .select('data, descricao, categoria, valor, pagamento')
    .gte('data', inicio)
    .lt('data', fim)
    .order('data')
  if (error) throw new Error(error.message)
  return (data ?? []).map((g) => ({ ...g, valor: Number(g.valor) }))
}

async function limites(): Promise<Record<string, number>> {
  const { data } = await supabase.from('config').select('dados').eq('id', 1).maybeSingle()
  return (data?.dados?.limites ?? {}) as Record<string, number>
}

/** Mesma regra do dashboard: avisa ao passar do limite ou a partir de 80% dele. */
function alertaDeLimite(categoria: string, gasto: number, limite: number): string | null {
  if (!limite || limite <= 0) return null
  if (gasto > limite) return `Atenção: ${categoria} passou do limite: ${brl(gasto)} de ${brl(limite)}.`
  if (gasto >= 0.8 * limite) {
    return `Atenção: ${categoria} está em ${Math.round((gasto / limite) * 100)}% do limite (${brl(gasto)} de ${brl(limite)}).`
  }
  return null
}

function texto(t: string) {
  return { content: [{ type: 'text' as const, text: t }] }
}

// --------------------------------------------------------------------------
// Ferramentas
// --------------------------------------------------------------------------
function novoServidor(): McpServer {
  return new McpServer({
    name: 'controle-de-gastos',
    version: '1.0.0',
    schemaAdapter: (schema) => z.toJSONSchema(schema as z.ZodType),
  })
}

const mcp = novoServidor()

const RegistrarGasto = z.object({
  descricao: z.string().min(1)
    .describe('Descrição curta do gasto, com a primeira letra maiúscula. Ex.: "iFood", "Farmácia", "Uber para o trabalho".'),
  valor: z.number().positive().describe('Valor em reais. "32,90" vira 32.9.'),
  categoria: z.enum(CATEGORIAS).optional()
    .describe('Categoria que melhor descreve o gasto. Se não tiver certeza, omita e o servidor classifica pela descrição.'),
  data: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional()
    .describe('Data no formato AAAA-MM-DD. Omita para usar hoje. "ontem" = hoje menos 1 dia.'),
  pagamento: z.enum(PAGAMENTOS).optional()
    .describe('Forma de pagamento. "crédito"/"cartão" = Cartão de crédito; "pix"/"débito" = Débito/Pix. Omita se não for dito (vira Débito/Pix).'),
})

const DESCRICAO_REGISTRAR =
  'Registra um gasto no Controle de Gastos do usuário. Use sempre que ele contar que gastou/pagou/comprou algo ' +
  '(ex.: "gastei 45 no ifood no crédito", "uber 23,50", "farmácia 32,90 ontem"). ' +
  'Extraia descrição, valor, categoria, data e pagamento da frase. Registre um gasto por chamada; ' +
  'se a frase tiver vários gastos, chame a ferramenta uma vez para cada um. '

/** Grava o gasto; com `completo`, a resposta traz tambem o total do mes e o alerta de limite. */
async function registrar(args: z.infer<typeof RegistrarGasto>, completo: boolean) {
  const descricao = args.descricao.trim()
  const categoria = args.categoria ?? classificar(descricao)
  const data = args.data ?? hojeBrasilia()
  const pagamento = args.pagamento ?? 'Débito/Pix'

  const { error } = await supabase.rpc('inserir_gasto', {
    p_data: data, p_descricao: descricao, p_categoria: categoria,
    p_valor: args.valor, p_pagamento: pagamento,
  })
  if (error) return texto(`Não consegui registrar o gasto: ${error.message}`)

  const [a, m, d] = data.split('-')
  const registrado = `Registrado: ${descricao} | ${brl(args.valor)} | ${categoria} | ${pagamento} | ${d}/${m}/${a}.`
  if (!completo) return texto(registrado)

  const [ano, mes] = data.split('-').map(Number)
  const doMes = await gastosDoMes(ano, mes)
  const total = doMes.reduce((s, g) => s + g.valor, 0)
  const naCategoria = doMes.filter((g) => g.categoria === categoria).reduce((s, g) => s + g.valor, 0)
  const alerta = alertaDeLimite(categoria, naCategoria, (await limites())[categoria] ?? 0)

  const linhas = [registrado, `Total de ${MESES[mes - 1]}: ${brl(total)} (${categoria}: ${brl(naCategoria)}).`]
  if (alerta) linhas.push(alerta)
  return texto(linhas.join('\n'))
}

mcp.tool('registrar_gasto', {
  description: DESCRICAO_REGISTRAR + 'Depois, confirme ao usuário o que foi lançado e repita qualquer alerta de limite.',
  inputSchema: RegistrarGasto,
  handler: (args: z.infer<typeof RegistrarGasto>) => registrar(args, true),
})

const ListarGastos = z.object({
  mes: z.number().int().min(1).max(12).optional().describe('Mês (1 a 12). Omita para o mês atual.'),
  ano: z.number().int().min(2000).max(2100).optional().describe('Ano. Omita para o ano atual.'),
})

mcp.tool('listar_gastos', {
  description:
    'Mostra os gastos de um mês: total, total por categoria (com limites) e a lista de lançamentos. ' +
    'Use para perguntas como "quanto gastei esse mês?" ou "quanto já foi de mercado?".',
  inputSchema: ListarGastos,
  handler: async (args: z.infer<typeof ListarGastos>) => {
    const [anoHoje, mesHoje] = hojeBrasilia().split('-').map(Number)
    const ano = args.ano ?? anoHoje
    const mes = args.mes ?? mesHoje
    const doMes = await gastosDoMes(ano, mes)
    if (doMes.length === 0) return texto(`Nenhum gasto lançado em ${MESES[mes - 1]} de ${ano}.`)

    const lim = await limites()
    const porCategoria = new Map<string, number>()
    for (const g of doMes) porCategoria.set(g.categoria, (porCategoria.get(g.categoria) ?? 0) + g.valor)
    const total = doMes.reduce((s, g) => s + g.valor, 0)

    const linhas = [`${MESES[mes - 1]} de ${ano}: ${brl(total)} em ${doMes.length} lançamento(s).`, '', 'Por categoria:']
    for (const [cat, v] of [...porCategoria].sort((x, y) => y[1] - x[1])) {
      const l = lim[cat] ?? 0
      linhas.push(`- ${cat}: ${brl(v)}${l > 0 ? ` de ${brl(l)} (${Math.round((v / l) * 100)}%)` : ''}`)
    }
    linhas.push('', 'Lançamentos:')
    for (const g of doMes) {
      const [a, m, d] = g.data.split('-')
      linhas.push(`- ${d}/${m}/${a} | ${g.descricao} | ${brl(g.valor)} | ${g.categoria} | ${g.pagamento}`)
    }
    return texto(linhas.join('\n'))
  },
})

// Servidor reduzido para quem so lanca gastos: nao lista nem mostra totais
const mcpLancar = novoServidor()

mcpLancar.tool('registrar_gasto', {
  description: DESCRICAO_REGISTRAR + 'Depois, confirme ao usuário o que foi lançado.',
  inputSchema: RegistrarGasto,
  handler: (args: z.infer<typeof RegistrarGasto>) => registrar(args, false),
})

// --------------------------------------------------------------------------
// HTTP: so responde quando o token secreto da URL confere
// --------------------------------------------------------------------------
const httpCompleto = new StreamableHttpTransport().bind(mcp)
const httpLancar = new StreamableHttpTransport().bind(mcpLancar)
const app = new Hono()

app.all('/gastos-mcp/:token/mcp', async (c) => {
  const token = c.req.param('token')
  const completo = Deno.env.get('MCP_TOKEN')
  const lancar = Deno.env.get('MCP_TOKEN_LANCAR')
  if (completo && token === completo) return await httpCompleto(c.req.raw)
  if (lancar && token === lancar) return await httpLancar(c.req.raw)
  return c.notFound()
})

app.all('*', (c) => c.notFound())

export default { fetch: app.fetch }
