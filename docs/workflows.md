# Comparar, retomar e enviar rodadas

Este guia cobre os fluxos avançados. Para uma rodada simples, use o comando
`run` do [README](../README.md). Comparações válidas precisam usar a mesma
revisão dos dados, seleção, seed, janela e perfil.

## Comparar o pipeline e providers

O engine `pipeline` executa o fluxo completo do Acessilia. `structure` mede a
extração de estrutura de um provider, a montagem do documento canônico e sua
exportação; não executa o restante da orquestração do produto. Providers e
modelos precisam estar disponíveis na Toolbox.

```bash
export ACESSILIA_REPO=../acessilia
uv run --extra datasets acessilia-benchmark run drdocbench-dev \
  --run docling-dev --engine structure --provider docling \
  --window-size 1 --limit 30 --seed 42
uv run --extra datasets acessilia-benchmark run drdocbench-dev \
  --run mineru-dev --engine structure --provider mineru \
  --window-size 1 --limit 30 --seed 42
uv run --extra datasets acessilia-benchmark run drdocbench-dev \
  --run acessilia-dev --engine pipeline --window-size 1 --limit 30 --seed 42
uv run acessilia-benchmark compare docling-dev mineru-dev \
  --profile full --fail-on-regression
```

Dr.DocBench usa duas páginas por caso por padrão. Use `--window-size 1` para
comparar páginas individuais ou alinhar a unidade com uma submissão. No Omni,
cada caso sempre representa uma página.

## Reproduzir o split OmniDocBench-80

O manifesto `selections/omnidocbench-80.json` fixa 80 páginas da revisão
registrada, sem repetir IDs, caminhos ou índices de registro original. A seleção
mantém cinco grupos de desafio — texto comum, OCR difícil, tabelas, fórmulas e
layout complexo — com 16 páginas em cada grupo. Cada grupo contém 4 páginas fáceis,
6 médias e 6 difíceis, segundo heurísticas específicas da categoria.

O gerador usa a seed 42. Dentro das faixas de dificuldade, escolhe páginas para
manter próximas do snapshot as distribuições marginais de origem, idioma e layout,
além de diversificar características internas de cada desafio. Para resolver
casos elegíveis em mais de um grupo, a prioridade é OCR, fórmulas, texto comum,
tabelas e layout; uma página selecionada fica indisponível para os demais grupos.
O manifesto registra as contagens da população, da amostra e a distância de
variação total (TV) para origem, idioma, layout e a combinação origem×idioma. Na
versão fixada, TV é 0,030 para origem, 0,021 para idioma, 0,025 para layout e
0,055 para origem×idioma. Esses valores medem essas distribuições separadamente;
não medem a distribuição conjunta de origem, idioma e layout, nem a
representatividade dos resultados por categoria.

As cotas iguais por desafio mantêm deliberadamente casos difíceis na amostra e
alteram a composição natural do dataset. Portanto, o `Overall local` é a média
sem pesos destas 80 páginas; não é uma estimativa do OmniDocBench completo, um
holdout ou um resultado oficial. O manifesto registra para cada página o índice
zero-based e o caminho exato no JSON original. O arquivo
`selections/omnidocbench-80-mapping.csv` permite revisar os 80 vínculos. Execute
a rodada completa:

```bash
uv run --extra datasets acessilia-benchmark run omnidocbench \
  --run omni80 --acessilia-repo ../acessilia \
  --selection-file selections/omnidocbench-80.json
```

Ou prepare previsões para inferência/importação posterior:

```bash
uv run acessilia-benchmark prepare omnidocbench --run omni80 \
  --selection-file selections/omnidocbench-80.json
uv run acessilia-benchmark predict --run omni80 --acessilia-repo ../acessilia
uv run acessilia-benchmark evaluate --run omni80 --profile full
```

O comando copia o manifesto para a rodada e sela sua identidade no plano. A
seleção só aceita o snapshot de anotações correspondente, usa `--seed 42` e não
pode ser combinada com `--limit` ou `smoke`. Os relatórios mostram métricas e
cobertura por categoria de desafio e por faixa de dificuldade. `compare` calcula
deltas para a mesma seleção e cobertura.

O JSON oficial não fornece um identificador explícito de documento; o manifesto
inclui apenas uma inferência pelo nome do arquivo quando possível. A seleção não
comprova independência documental nem mede generalização para documentos inéditos.

`compare` recusa diferenças de dataset, revisão, seleção, agrupamento,
referências, avaliador, ambiente de avaliação ou cobertura. Calcula deltas com
a direção correta: edit distance menor é melhor; TEDS, CDM e Overall maiores
são melhores. `--tolerance 0.5` permite uma perda de até meio ponto na escala
0–100. `--fail-on-regression` retorna código 1 quando encontra regressão de
qualidade. `--fail-on-processing-review` retorna código 1 quando qualquer lado
tem avisos ou evidência insuficiente, permitindo bloquear gates sem diagnóstico
confiável. Métricas ausentes não viram zero.

O resultado se aplica à amostra escolhida; não é um aceite tune/holdout nem
comprova generalização. Reserve documentos independentes para validação. O
perfil `basic` não inclui CDM ou Overall. Rodadas `smoke` são fixtures e só
podem ser comparadas com outras autoverificações. Relatórios antigos, anteriores
aos selos de avaliação, não são aceitos pelo comparador atual.

## Retomar inferência

```bash
uv run acessilia-benchmark predict --run mineru-dev \
  --acessilia-repo ../acessilia --engine structure --provider mineru --resume
uv run acessilia-benchmark evaluate --run mineru-dev --profile full
```

`--resume` repete casos falhos ou pendentes. Confere hashes das previsões
válidas, metadados, código do Core, adaptador, dependências e interpretador;
mudanças exigem uma nova rodada. Logs e tentativas anteriores são preservados,
e os tempos acumulam as chamadas de todas as tentativas. Duas inferências
simultâneas na mesma rodada são bloqueadas. Checkpoints são gravados por caso;
uma interrupção durante a gravação pode exigir inspeção. Rodadas antigas sem
hashes por caso não podem ser retomadas com segurança.

O relatório runtime inclui chamadas, falhas, estado final e tempo acumulado por
caso. `failures_by_kind` acumula todas as tentativas e separa timeout do processo
benchmark, timeout do provider, provider indisponível e falha não classificada.
Essa classificação usa assinaturas conhecidas nos logs; o texto bruto do log não
é copiado para os relatórios, e `compare --profile runtime` mostra os deltas por
categoria entre as rodadas. A comparação de custo funciona mesmo sem referências:

```bash
uv run acessilia-benchmark compare baseline-test candidate-test --profile runtime
```

O tempo inclui processo, preparação da entrada, cache e serviços. Não mede
isoladamente latência do modelo, memória, GPU-hora ou vazão concorrente.

## Criar uma submissão Dr.DocBench

Gere previsões para todas as páginas do split test usando uma página por caso:

```bash
uv run --extra datasets acessilia-benchmark run drdocbench-test \
  --run submission --acessilia-repo ../acessilia --window-size 1
uv run acessilia-benchmark submit --run submission
```

O pacote local fica em `runs/submission/submission/submission.zip`. Seu
`predictions.jsonl` contém `subject`, `document_id`, `page` e `markdown` por
página; o manifesto registra revisão e hashes. A geração exige o snapshot
íntegro, cobertura completa e nenhuma falha. O comando não envia o pacote. O
test não tem score local de qualidade; a avaliação depende do serviço oficial.
Os testes locais não confirmam a aceitação externa do formato.

## Executar em Slurm

Baixe os dados e prepare avaliadores/renderizadores em storage compartilhado.
O Core precisa de seu próprio ambiente; Toolbox e providers devem estar
acessíveis nos nós de execução.

```bash
export ACESSILIA_BENCHMARK_WORKSPACE=/shared/repos/acessilia-benchmark
export ACESSILIA_REPO=/shared/repos/acessilia
export ACESSILIA_PYTHON=/shared/repos/acessilia/.venv/bin/python
export RUN=docling-dev-cluster DATASET=drdocbench-dev
export ENGINE=structure PROVIDER=docling WINDOW_SIZE=1 LIMIT=30
sbatch -p SUA_PARTICAO -c 8 --mem=32G --time=04:00:00 \
  --export=ALL scripts/slurm/benchmark.sbatch
```

`PROFILE=auto` escolhe `full` ou `runtime` conforme as referências. Também é
possível definir `SEED`, `TIMEOUT`, `EVALUATION_TIMEOUT` e `BENCHMARK_DATA_DIR`.
Reutilizar `RUN` retoma uma rodada existente após validar dataset, janela,
limite e seed. O script foi verificado localmente, sem submissão a um cluster.
Jobs que iniciam providers dentro da alocação ficam em `scripts/bench/slurm/`
no repositório Core.
