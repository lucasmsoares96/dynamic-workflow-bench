# dynamic-workflow-bench

Benchmark de consumo de tokens do Claude Code: quanto o *dynamic workflow* custa a mais do que simplesmente delegar ao mesmo subagente, sem workflow.

Na tarefa T1, o cenario B (dynamic workflow) consumiu **+132,9% em tokens totais** e **+74,2% em input nao cacheado** em relacao ao cenario C (ferramenta Agent, sem workflow), pelas somas das execucoes validas. A direcao foi consistente nas 9 execucoes pareadas (B maior que C em total em todas), mas a magnitude e instavel e a amostra e pequena: 3 modelos x 3 repeticoes, um unico dia. Os numeros descrevem esta tarefa trivial, nao uma lei geral.

---

## 1. Pergunta e hipotese

**Pergunta.** Quanto o dynamic workflow do Claude Code consome a mais que delegar ao mesmo subagente pela ferramenta Agent, sem workflow? Ou seja: qual e o custo marginal do orquestrador do workflow?

**Hipotese.** O workflow acrescenta uma thread principal que precisa carregar definicoes de ferramentas, o prompt do workflow e o resultado do subagente no proprio contexto, e cada turno dela reenvia esse contexto. Logo, B (workflow) deve consumir mais que C (Agent direto) em condicoes identicas de tarefa, modelo e subagente.

A comparacao ingenua A contra B (agente direto contra workflow) nao responde a essa pergunta: ela mistura o custo do workflow com o custo de *ter* um orquestrador. Por isso o desenho final tem tres cenarios, nao dois. Ver a secao de historia da metodologia.

## 2. Ambiente

| Item | Valor |
|---|---|
| Harness | Claude Code CLI 2.1.304, invocado como `claude -p` (modo nao interativo, `--output-format json`) |
| Proxy | CLIProxyAPI local em `http://127.0.0.1:8317` |
| Medicao | Cada requisicao HTTP que o proxy atende e gravada na tabela `usage_events` de um SQLite em `~/Library/Application Support/com.cpa.gui/usage-records/usage.db` |
| Sistema | macOS (Darwin 24.6.0) |
| Linguagem | Python 3, somente biblioteca padrao (nenhuma dependencia externa) |
| Modelos | `claude-haiku-5-5`, `deepseek-v4.1-flash`, `gemini-3.8-flash-high` |

O banco do proxy e a fonte de verdade dos tokens: ele registra o consumo real de cada chamada, inclusive as chamadas feitas pelo subagente, que nao aparecem no JSON de saida do `claude`.

## 3. Metodologia

### 3.1 Tarefa T1

T1 e uma tarefa de leitura simples sobre o projeto de fixture em `project/`:

> List every file named AGENTS.md in this project, ignoring anything under node_modules. For each give its path relative to the project root (forward slashes) and the text of its first Markdown heading (without the leading # characters; skip any YAML frontmatter and any text before the heading). Return count and files.

O gabarito tem 6 arquivos em `project/expected_t1.json`:

| Caminho | Primeiro heading |
|---|---|
| `AGENTS.md` | Fixture Root Guide |
| `backend/AGENTS.md` | Backend Standards |
| `backend/apps/api/AGENTS.md` | API Conventions |
| `docs/deep/nested/AGENTS.md` | Deeply Nested Docs Rules |
| `frontend/AGENTS.md` | Frontend Guide |
| `frontend/apps/web/AGENTS.md` | Web App Notes |

A fixture foi montada com casos limite deliberados:

- `frontend/AGENTS.md` tem frontmatter YAML antes do heading: e preciso pular o frontmatter e o texto antes do `#`.
- `backend/apps/api/AGENTS.md` tem texto antes do heading, cujo primeiro heading real e `##` (nivel 2), e ainda um `# Late Top Heading` mais abaixo: e preciso pegar o primeiro heading, nao o primeiro `#`.
- `docs/deep/nested/AGENTS.md` exercita uma pasta aninhada com um arquivo que nao esta na raiz nem em um nivel so.
- `node_modules/pkg/AGENTS.md` e um AGENTS.md valido que **deve ser excluido**: se o resultado trouxer 7 arquivos, a instrucao de ignorar `node_modules` foi violada.

A resposta e exigida via `--json-schema` (structured output) e comparada com o gabarito por conjunto de pares (caminho, heading) mais a contagem, apos normalizacao.

### 3.2 Cenarios

Os tres cenarios executam exatamente a mesma tarefa. O que muda e quem faz o trabalho.

| Cenario | Comando | O que acontece |
|---|---|---|
| **A** | `claude -p --agent bench-researcher "<tarefa>"` | O agente *e* a thread principal. Nao ha orquestrador nem subagente. Mede o trabalho puro em um contexto unico. |
| **B** | `claude -p "/bench-t1 <tarefa>"` | Thread principal padrao (sem `--agent`) chama o workflow pre-montado `bench-t1`, que dispara `bench-researcher` como subagente. |
| **C** | `claude -p "<tarefa>" + instrucao de delegar` | Thread principal padrao (sem `--agent`), sem workflow, que delega uma vez ao *mesmo* subagente pela ferramenta Agent e devolve o resultado dele. |

O prompt de C e o de A acrescido de uma instrucao fixa de delegar (texto literal, com duas quebras de linha iniciais):

```
\n\nDo not do this work yourself. Use the Agent tool exactly once with subagent_type
"bench-researcher", passing the task above verbatim, and return the subagent's result unchanged.
```

O prompt de B e `/bench-t1 ` prefixado a mesma tarefa, sem acrescimo de instrucao: o workflow repassa a tarefa inalterada ao subagente. Assim, B e C diferem apenas no mecanismo (Workflow contra Agent), e C acrescenta ao enunciado somente a ordem de delegar, para que a thread principal nao resolva o servico sozinha.

**Por que as razoes importam.**

- **B sobre C** isola o custo do **workflow**: mesmo orquestrador nos dois, mesmo subagente, mesmo modelo; B passa por um workflow, C nao.
- **C sobre A** isolam o custo de **ter um orquestrador**: C tem thread principal delegando, A nao tem thread principal separada.
- **B sobre A** e o numero da comparacao ingenua: soma orquestrador e workflow, sem separar os dois.

### 3.3 Flags reais de ferramentas e o achado do `--tools`

Base de comando (identica nos tres cenarios):

```
claude -p --output-format json --setting-sources project --strict-mcp-config
       --model <id> --append-system-prompt " " --json-schema <schema>
       --permission-prompts none --tools=<...> --allowedTools=<...>
```

| Cenario | `--tools` | `--allowedTools` |
|---|---|---|
| A | `Read,Grep,Glob,StructuredOutput` | `Read,Grep,Glob` |
| B | `Agent,Workflow,StructuredOutput,Read,Grep,Glob` | `Workflow,Agent` |
| C | `Agent,Workflow,StructuredOutput,Read,Grep,Glob` | `Agent` |

B recebe ainda `--settings '{"enableWorkflows": true, "skipWorkflowUsageWarning": true}'`.

Achados empiricos que fixaram esse desenho (sondas de haiku, uma tentativa cada):

- `--tools` e variadico como `--allowedTools`: `--tools A,B <prompt>` engole o prompt e falha com "Input must be provided either through stdin or as a prompt argument". Por isso se usa a forma `--tools=`.
- **`--tools` restringe tambem o subagente.** Sem `Read,Grep,Glob` na lista, o `bench-researcher` falha com as ferramentas de busca negadas (`subagent failed=1`). Por isso B e C recebem `Read,Grep,Glob` na thread principal, simetricos. Quem impede a thread principal de fazer o trabalho sozinha e o `--allowedTools` (sem `Read/Grep/Glob`), nao a ausencia da definicao da ferramenta.
- O subagente continua com `Read,Grep,Glob` do proprio frontmatter (a permissao vem do agente, nao da thread principal) e devolve o resultado correto.
- `--tools=Agent` expoe a ferramenta interna "Task" (nome exibido no init do stream-json) e e o que faz o spawn funcionar.

### 3.4 Como se verifica que houve delegacao

Para B e C, uma execucao sem evidencia de que o subagente rodou e marcada **INVALIDA** ("nao delegou"). Dois sinais, basta um:

1. `subagent_stats.spawned >= 1` no JSON de saida do `claude`. E exato, mas so enxerga o spawn feito pela ferramenta Agent. **No cenario B o agente do workflow roda numa session-task (campo `origin`), fora dessa contagem**: `spawned=0` mesmo delegando corretamente. Por isso o sinal 2 existe.
2. **Heuristica de duas faixas de input no banco:** `min(input) * 2 <= max(input)`. O subagente carrega um contexto bem menor (4 a 6 mil tokens) que a thread principal (9 a 23 mil, com as definicoes de ferramentas e o prompt do workflow). Uma execucao que delegou tem necessariamente uma chamada pequena ao lado de uma grande.

Valores medidos nas sondas (haiku, T1): A 3.806..5.219 (uma faixa); C 4.197..10.378 (duas faixas); B 4.423..23.274 (duas faixas); thread principal que nao delegou 6.777..8.240 (uma faixa, corretamente invalida).

**Limites do criterio 2**, que precisam ser explicitos:

- Se o contexto do subagente crescer ate mais da metade do da thread principal, o sinal pode falhar por baixo e gerar um falso "nao delegou".
- Se a thread principal tiver chamadas de tamanhos muito dispares (por exemplo, compactacao no meio da execucao), o sinal pode passar por alto e gerar um falso "delegou".
- O sinal 1 e o forte quando existe; o sinal 2 cobre o caso de B, onde o sinal 1 e sempre zero.

Na rodada final, as 27 execucoes passaram: A nao exige sinal, e todas as 9 execucoes B e 9 execucoes C foram consideradas delegadas.

### 3.5 Achado: `StructuredOutput` precisa estar em `tools:` do agente

Confirmado empiricamente na 2.1.304:

- Sem `--agent` e com `--json-schema`, o JSON de saida traz `structured_output` (dict).
- Com `--agent bench-researcher` e `--json-schema`, **nao** vinha `structured_output`: a resposta vinha em texto livre (uma tabela) no campo `result`.
- O mesmo agente, com `StructuredOutput` acrescentado a lista `tools:` do frontmatter, volta a devolver `structured_output`.

Causa: a restricao de ferramentas do agente exclui a ferramenta de saida estruturada. O ajuste esta no agente usado por A, B e C, simetrico nos tres.

Como defesa adicional, o extrator cai para um parser de JSON no texto de `result` se `structured_output` faltar. Na rodada final, todos os 27 resultados vieram por `structured_output`, entao a comparacao nao depende do parser de texto.

### 3.6 Fixacao de modelo

Cada execucao pede um modelo explicito com `--model <id>` e fixa o modelo das camadas de delegacao por variavel de ambiente:

```
CLAUDE_CODE_SUBAGENT_MODEL=inherit
CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1
CLAUDE_CODE_WORKFLOW_SUBAGENT_MODEL=<id>
CLAUDE_CODE_WORKFLOW_MAX_CONCURRENT_AGENTS=1
```

O agente `bench-researcher` **nao** declara `model` no frontmatter: se declarasse, ele sobreporia a fixacao acima. Como verificacao, cada execucao e invalidada se aparecer no banco qualquer modelo diferente do solicitado (`modelo(s) diferente(s) do pedido`). Isso nao ocorreu em nenhuma das 27 execucoes da rodada final.

### 3.7 Isolamento

- `--setting-sources project`: ignora configuracoes de usuario/global, usando apenas o `.claude/` de `project/`.
- `--strict-mcp-config`: nenhum servidor MCP participa.
- `cwd` = `project/`, que tem um git proprio (o git init aninhado), reproduzindo um projeto real.
- `stdin=DEVNULL`: sem stdin redirecionado o `claude` espera 3 segundos.

### 3.8 Gemini via `claude -p`

O Gemini, chamado assim, exige um system prompt nao vazio: sem `--append-system-prompt`, a chamada falha. Usa-se `--append-system-prompt " "` (um espaco), aplicado a **todos** os modelos por simetria, para que nenhum cenario ganhe uma diferenca de prompt.

### 3.9 Medicao

- **User-Agent unico por execucao.** Cada execucao gera `bench-<uuid4>` e o injeta via `ANTHROPIC_CUSTOM_HEADERS: User-Agent: <ua>`. O proxy grava esse valor na coluna `user_agent` de cada linha, inclusive nas chamadas feitas pelo subagente (que herdam o ambiente). A atribuicao no banco e, portanto, por execucao, nao por processo.
- **Espera de estabilizacao.** Depois que o processo `claude` termina, o bench consulta a contagem de linhas daquele User-Agent ate ela ficar estavel por 10 segundos, com limite maximo de 90 segundos. Sem isso, linhas do subagente que chegam com atraso ficariam de fora. Se a contagem nao estabilizar, a execucao e invalidada.
- **Parcelas registradas por linha:**

| Parcela | Definicao |
|---|---|
| input nao cacheado | `input_tokens - cache_read_tokens` |
| cache_read | `cache_read_tokens` |
| cache_creation | `cache_creation_tokens` |
| output | `output_tokens` |
| total | `total_tokens` (= input + output) |

- **Tokens de chamadas com falha ficam nos totais** (consumo real). As falhas sao contadas e reportadas separadamente.

### 3.10 Desenho

3 modelos x 3 repeticoes x 3 cenarios = **27 execucoes**.

A ordem dos cenarios rotaciona por repeticao, para que nenhum cenario seja sempre o primeiro e sofra sempre o mesmo efeito de ordem ou de aquecimento de cache:

- rep 1: A, B, C
- rep 2: B, C, A
- rep 3: C, A, B

No macOS, o script se reexecuta sob `caffeinate -i` para o Mac nao dormir no meio da rodada (`--no-caffeinate` desliga). O `runs.json` e gravado incrementalmente a cada execucao, com escrita atomica via arquivo temporario e `os.replace`.

## 4. Resultados da rodada final (2026-10-20 08:13:42)

**Validade:** 27 execucoes, 27 validas, 27 corretas. Nenhuma invalidada por "nao delegou", nenhuma com resultado incorreto, nenhum modelo divergente do pedido. B e C produziram resultado identico ao gabarito e entre si em todas as 9 comparacoes pareadas (`B==C=SIM` nas repeticoes 1, 2 e 3 dos tres modelos). A tarefa foi resolvida corretamente nos tres cenarios e nos tres modelos.

### 4.1 Medianas por modelo e cenario

| Modelo | Metrica | A | B | C |
|---|---|---:|---:|---:|
| haiku | total | 14.374 | 119.134 | 89.688 |
| haiku | input nao cacheado | 1.418 | 7.985 | 5.260 |
| deepseek | total | 16.809 | 94.192 | 32.299 |
| deepseek | input nao cacheado | 3.445 | 8.454 | 1.612 |
| gemini | total | 51.909 | 186.693 | 90.217 |
| gemini | input nao cacheado | 48.018 | 169.578 | 85.034 |

As medianas mostram a mesma direcao das somas, mas a dispersao dentro de cada celula e grande (n=3). As somas abaixo sao mais estaveis do que a mediana para comparar cenarios, porque o consumo real de uma execucao atipica nao desaparece ao se tirar a mediana.

### 4.2 Somas e razoes

Soma das execucoes validas, consumo real (falhas incluidas):

| Escopo | Metrica | A | B | C | B/C | C/A | B/A |
|---|---|---:|---:|---:|---:|---:|---:|
| **GERAL** | total | 239.738 | 1.585.993 | 681.100 | **+132,9%** | +184,1% | +561,6% |
| **GERAL** | input nao cacheado | 149.518 | 569.009 | 326.636 | **+74,2%** | +118,5% | +280,6% |
| haiku | total | 43.170 | 407.240 | 269.182 | +51,3% | +523,5% | +843,3% |
| haiku | input nao cacheado | 4.059 | 28.679 | 16.790 | +70,8% | +313,6% | +606,6% |
| deepseek | total | 51.560 | 254.378 | 97.477 | +161,0% | +89,1% | +393,4% |
| deepseek | input nao cacheado | 9.121 | 26.733 | 21.340 | +25,3% | +134,0% | +193,1% |
| gemini | total | 145.008 | 924.375 | 314.441 | +194,0% | +116,8% | +537,5% |
| gemini | input nao cacheado | 136.338 | 513.597 | 288.506 | +78,0% | +111,6% | +276,7% |

Leitura: o workflow (B/C) custa mais que a delegacao direta em todos os modelos e nas duas metricas. O efeito e maior no gemini e no deepseek em total, e menor no haiku.

### 4.3 Comparacao pareada B contra C por repeticao

| Modelo | Rep | B total | C total | Delta total | B nao cacheado | C nao cacheado | Delta nao cacheado |
|---|---:|---:|---:|---:|---:|---:|---:|
| haiku | 1 | 176.689 | 108.933 | +62,2% | 13.850 | 7.061 | +96,1% |
| haiku | 2 | 119.134 | 70.561 | +68,8% | 7.985 | 4.469 | +78,7% |
| haiku | 3 | 111.417 | 89.688 | +24,2% | 6.844 | 5.260 | +30,1% |
| deepseek | 1 | 94.192 | 32.299 | +191,6% | 14.610 | 18.284 | **-20,1%** |
| deepseek | 2 | 100.956 | 33.012 | +205,8% | 8.454 | 1.612 | +424,4% |
| deepseek | 3 | 59.230 | 32.166 | +84,1% | 3.669 | 1.444 | +154,1% |
| gemini | 1 | 630.131 | 149.170 | +322,4% | 241.998 | 140.432 | +72,3% |
| gemini | 2 | 186.693 | 75.054 | +148,7% | 169.578 | 63.040 | +169,0% |
| gemini | 3 | 107.551 | 90.217 | +19,2% | 102.021 | 85.034 | +20,0% |

B foi maior que C em **total nas 9 de 9** execucoes pareadas, com delta de +19,2% a +322,4%. Em **input nao cacheado foram 8 de 9**, com a unica excecao em deepseek repeticao 1 (-20,1%).

## 5. Historia da metodologia: por que existe o cenario C

A primeira rodada (2026-10-20 06:16:32) comparou apenas **A e B**, 18 execucoes (3 modelos x 3 repeticoes x 2 cenarios), todas validas e corretas. O resultado agregado foi:

| Escopo | A | B | B sobre A |
|---|---:|---:|---:|
| GERAL | 226.283 | 1.277.242 | **+464,4%** |
| haiku | 48.946 | 399.529 | +716,3% |
| deepseek | 59.807 | 182.928 | +205,9% |
| gemini | 117.530 | 694.785 | +491,2% |

Esse "+464%" foi interpretado inicialmente como custo do dynamic workflow. A decomposicao por chamada no banco, porem, mostrou outra coisa.

Olhando as linhas de cada execucao B no banco e separando-as em duas faixas de tamanho de input (a faixa pequena corresponde ao subagente, a grande a thread principal):

| Modelo | Rep | Chamadas pequenas (subagente) | Soma | Chamadas grandes (thread principal) | Soma | % do total de B vindo das grandes | Faixa de input das grandes |
|---|---:|---:|---:|---:|---:|---:|---|
| haiku | 1 | 3 | 16.512 | 7 | 154.647 | 90,4% | 19.883 a 23.359 |
| haiku | 2 | 3 | 16.514 | 5 | 108.833 | 86,8% | 19.883 a 22.394 |
| haiku | 3 | 3 | 16.831 | 4 | 86.192 | 83,7% | 19.883 a 22.892 |
| deepseek | 1 | 3 | 11.260 | 3 | 40.514 | 78,3% | 12.536 a 14.146 |
| deepseek | 2 | 3 | 10.783 | 4 | 55.117 | 83,6% | 12.536 a 14.525 |
| deepseek | 3 | 3 | 10.795 | 4 | 54.459 | 83,5% | 12.536 a 14.405 |

Duas conclusoes saem dai:

1. **No haiku e no deepseek, as chamadas do subagente dentro de B somavam aproximadamente o mesmo que o A inteiro.** Comparando com o A da *mesma repeticao*, a razao vai de 83% a 120% (haiku: 115,4%, 114,5% e 83,2%; deepseek: 119,8% e 115,5% nas repeticoes 1 e 3; a repeticao 2 do deepseek fica em 26,3% porque o A daquela repeticao foi um outlier de 41.065 tokens contra 9.3 mil nas outras duas). Ou seja, o trabalho do subagente custa o mesmo nos dois cenarios, como esperado.
2. **78% a 90% do total de B vinha de chamadas grandes de 12 a 23 mil tokens de input da thread principal**, intercaladas com as chamadas do subagente a cada 2 a 3 segundos.

Portanto **A contra B media o custo do orquestrador, nao o custo do workflow**: quase todo o excedente era a thread principal do workflow carregando e reenviando contexto, nao o mecanismo do workflow em si. Essa foi a motivacao para introduzir o cenario C, que tem o mesmo orquestrador e o mesmo subagente de B, mas delega pela ferramenta Agent. Comparar B com C remove o custo comum do orquestrador e deixa so a diferenca de mecanismo.

**Advertencia sobre essa decomposicao:** o banco nao registra qual thread (principal ou subagente) fez cada chamada. A atribuicao acima e **inferida pelo tamanho do input**: chamadas pequenas sao atribuidas ao subagente, chamadas grandes a thread principal. E uma inferencia coerente com os dados (a faixa pequena tem 3 chamadas por execucao, consistente com um subagente, e a faixa grande tem de 3 a 7), mas nao e uma medicao direta. Nas execucoes do gemini a separacao e menos nitida (67,8% a 82,9% nas grandes, com as faixas mais proximas), o que reforca o cuidado.

## 6. Ressalvas

Esta secao existe para que os numeros acima nao sejam lidos como mais solidos do que sao.

**Amostra e desenho.**

- **n=3 por celula e um unico dia.** Nao ha intervalo de confianca util com 3 pontos; as medianas sao pouco informativas e as somas carregam o peso de qualquer outlier.
- **Nenhuma rodada foi repetida em outro momento.** Cache de prompt do provedor, carga da maquina e estado do proxy variam entre execucoes e nao foram controlados.

**Direcao consistente, magnitude instavel.**

- A direcao se sustenta: B maior que C em total nas 9 de 9 execucoes pareadas (+19,2% a +322,4%) e em input nao cacheado em 8 de 9 (excecao: deepseek repeticao 1, -20,1%).
- A magnitude nao se sustenta. O contraste mais claro e o deepseek em input nao cacheado: **+424,4% pela mediana da repeticao 2** contra **+25,3% pela soma** de todas as execucoes. Dependendo de como se agrega, a resposta honesta varia de "quase nada" a "quatro vezes mais". Nenhum dos dois e o numero errado; ambos medem coisas diferentes com n=3.

**Outlier do Gemini na repeticao 1 do cenario B.**

A execucao B/gemini/rep1 consumiu **630.131 tokens**, contra 186.693 na rep2 e 107.551 na rep3 do mesmo cenario e modelo. O banco mostra 31 chamadas: 8 delas com input entre 37.859 e 70.765 tokens, muito acima das demais. Nao houve falha nem retentativa registrada nessa execucao. A hipotese, nao verificada, e que o contexto da thread principal cresceu por acumulo ao longo de 17 turnos (contra 2 turnos nas repeticoes 2 e 3 de B/gemini).

Esse unico par infla o resultado agregado:

| Base de calculo | B sobre C total | B sobre C input nao cacheado |
|---|---:|---:|
| Todas as execucoes | +132,9% | +74,2% |
| Sem o par gemini rep 1 (B e C removidos, 24 execucoes) | **+79,7%** | **+75,6%** |

Excluindo o par inteiro (mantendo a paridade de uma comparacao pareada), B sobre C cai para cerca de +80% no total e permanece em +76% no input nao cacheado. Se apenas a execucao B fosse removida e C mantida, o total cairia para +40,3% e o input nao cacheado para +0,1%, mas essa forma de exclusao quebra o pareamento e nao e usada aqui.

**Possivel subcontagem no Gemini B repeticao 3.**

O banco tem hoje **24 linhas** com o User-Agent da execucao B/gemini/rep3, mas o runner somou apenas **13** dentro da janela de estabilizacao: 11 linhas chegaram depois que a contagem estabilizou. Isso nao foi verificado, e a mesma divergencia aparece, em menor grau, em duas execucoes C do gemini (15 contra 17, e 18 contra 20). A causa provavel e latencia do proxy ao gravar linhas de execucoes longas com muitas chamadas. Efeito: o total de B/gemini esta **subestimado**, o que tornaria o B sobre C real ainda maior que o reportado, nao menor.

**Medicao de cache.**

- **O Gemini quase nao reporta `cache_read`** (quase sempre 0, com um caso de 1.858 e outro de 379.423). Por isso a parcela de cache do gemini nao deve ser comparada com a dos outros modelos, e o "input nao cacheado" do gemini acaba sendo praticamente igual ao input total.
- **O total soma cache com o mesmo peso do resto** (`total_tokens = input + output`, e `input` inclui `cache_read`). Em custo real, token lido de cache e mais barato que token novo em quase todos os provedores. O numero "total" deste README e, portanto, um limite superior do custo relativo; nao e uma estimativa de fatura.
- Por isso `input nao cacheado` e reportado lado a lado com `total`: e a metrica menos contaminada pela diferenca de comportamento de cache entre provedores.

**Validade externa.**

- **T1 e uma tarefa trivial**, que custa em torno de 14 mil a 52 mil tokens no cenario A. O custo do workflow parece, em grande parte, **fixo por execucao** (carregar o contexto do orquestrador alguma vezes), nao proporcional ao tamanho da tarefa. Se a tarefa fosse maior, a porcentagem de excedente provavelmente cairia, porque o trabalho util cresceria e o custo fixo do orquestrador nao. Nenhuma tarefa maior foi medida: **T2 e T3 nao existem**, o bench tem apenas T1.
- Os cenarios nao sao otimizados: o prompt de C inclui a instrucao explicita de delegar, que nao existe em B nem em A. Isso da a C uma pequena vantagem de instrucao, na direcao de **subestimar** o B sobre C. O efeito e presumivelmente pequeno (poucas linhas de prompt), mas nao foi medido.

**Ruido de execucao.**

- Houve **uma falha 502 do proxy** em deepseek A repeticao 3, sem tokens (a linha foi registrada como falha mas com total 0). Ela esta contada em "falhas" e nao afeta os totais.
- **Outros agentes rodavam na maquina durante a rodada.** Isso nao afeta a atribuicao de tokens, que e por User-Agent unico e vem do banco do proxy, mas pode afetar as duracoes de parede reportadas nos arquivos de resultado.

## 7. Como reproduzir

### 7.1 Pre-requisitos

1. `claude` no PATH (Claude Code CLI 2.1.304, a versao usada aqui).
2. CLIProxyAPI respondendo em `http://127.0.0.1:8317`, com `GET /v1/models` listando `claude-haiku-5-5`, `deepseek-v4.1-flash` e `gemini-3.8-flash-high`.
3. Token de acesso disponivel em `ANTHROPIC_AUTH_TOKEN` no ambiente, ou no bloco `env` de `~/.claude/settings.json`.
4. Banco de uso do proxy acessivel (padrao `~/Library/Application Support/com.cpa.gui/usage-records/usage.db`), com a tabela `usage_events`.

Verificacoes de pre-voo sao automaticas: o script aborta com mensagem clara se `claude` nao existir, se o token estiver ausente, se o proxy nao responder a `/v1/models`, se algum modelo pedido faltar na lista, ou se o projeto de teste nao existir. Se a leitura direta do banco falhar, ele avisa e usa uma copia de snapshot.

### 7.2 Execucao

```bash
python3 bench.py
```

Sem argumentos, roda a matriz completa: 3 modelos x 3 repeticoes x 3 cenarios = 27 execucoes. Os resultados vao para `results/<AAAAMMDD_HHMMSS>/`, com `runs.json` (dados brutos por execucao) e `report.txt` (relatorio formatado).

Aviso: a rodada completa executa 27 sessoes reais de modelo e consome tokens pagos no provedor configurado. Nada aqui e simulado.

### 7.3 Opcoes (conforme o `argparse` do script)

| Opcao | Padrao | Efeito |
|---|---|---|
| `--tests` | `t1` | Testes a rodar, separados por virgula (so existe `t1`) |
| `--models` | `haiku,deepseek,gemini` | Modelos a rodar, separados por virgula |
| `--reps` | `3` | Repeticoes por modelo |
| `--timeout` | `900` | Timeout por execucao, em segundos |
| `--base-url` | `http://127.0.0.1:8317` | URL do proxy |
| `--usage-db` | `~/Library/Application Support/com.cpa.gui/usage-records/usage.db` | Banco de uso |
| `--stable` | `10` | Segundos de estabilidade da contagem de linhas |
| `--max-wait` | `90` | Espera maxima pela estabilizacao, em segundos |
| `--sleep-slack` | `120` | Folga entre duracao de parede e janela do banco antes de sinalizar suspensao |
| `--project` | `./project` | Projeto de teste (cwd do `claude`) |
| `--selftest` | - | Roda as verificacoes internas, sem tocar em modelo |
| `--dry-run` | - | Imprime o plano e os comandos completos, sem executar |
| `--no-caffeinate` | - | Nao reexecuta sob `caffeinate` no macOS |

Exemplos:

```bash
python3 bench.py --dry-run                       # imprime o plano de 27 execucoes
python3 bench.py --selftest                      # verificacoes internas, sem modelo
python3 bench.py --models haiku --reps 1         # rodada minima: 3 execucoes
python3 bench.py --models haiku,deepseek --reps 2
```

Nenhum comando do `--dry-run` ou do `--selftest` chama modelo ou consome tokens.

### 7.4 Comportamento no Ctrl+C

Ao interromper com Ctrl+C, o script encerra o processo `claude` em andamento (o filho roda em grupo de processo proprio, com `SIGTERM` e depois `SIGKILL`), grava o `runs.json` parcial com as execucoes ja concluidas, marca `meta.partial` com a execucao interrompida, gera um `report.txt` encabecado por `*** RELATORIO PARCIAL ***` e sai com codigo 130. Nada do que ja foi medido e perdido.

O `runs.json` tambem e gravado apos **cada** execucao, com escrita atomica, entao uma queda abrupta tambem preserva o que ja rodou.

## 8. Estrutura do repositorio

```
dynamic-workflow-bench/
├── bench.py                  # o benchmark completo, so stdlib
├── project/                  # fixture: projeto de teste com git proprio
│   ├── .claude/
│   │   ├── agents/bench-researcher.md      # agente usado em A, B e C
│   │   └── workflows/bench-t1.js           # workflow usado em B
│   ├── AGENTS.md                           # gabarito 1/6
│   ├── backend/AGENTS.md                   # gabarito 2/6
│   ├── backend/apps/api/AGENTS.md          # gabarito 3/6 (heading ## apos texto)
│   ├── docs/deep/nested/AGENTS.md          # gabarito 4/6 (pasta aninhada)
│   ├── frontend/AGENTS.md                  # gabarito 5/6 (frontmatter antes do heading)
│   ├── frontend/apps/web/AGENTS.md         # gabarito 6/6
│   ├── node_modules/pkg/AGENTS.md          # deve ser EXCLUIDO pelo gabarito
│   ├── expected_t1.json                    # gabarito de T1 (6 arquivos)
│   ├── NOTES.md, main.py, src/main.py, pyproject.toml, .python-version, README.md
├── results/
│   ├── 20261020_061632/      # rodada 1: 18 execucoes, apenas A e B
│   │   ├── report.txt
│   │   └── runs.json
│   └── 20261020_081342/      # rodada final: 27 execucoes, A, B e C
│       ├── report.txt
│       └── runs.json
└── .gitignore                # __pycache__/, *.pyc, work/
```

`project/node_modules/` esta versionado de proposito: o `AGENTS.md` dentro dele e parte da fixture, e o caso que a tarefa deve excluir. Qualquer regra global de git que ignore `node_modules` precisa ser contornada com `git add -f project/node_modules/pkg/AGENTS.md`.

Os demais diretorios de `results/` da investigacao original (rodadas de fumaca) nao foram incluidos: apenas as duas rodadas completas acima.
