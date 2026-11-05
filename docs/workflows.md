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

`compare` recusa diferenças de dataset, revisão, seleção, agrupamento,
referências, avaliador, ambiente de avaliação ou cobertura. Calcula deltas com
a direção correta: edit distance menor é melhor; TEDS, CDM e Overall maiores
são melhores. `--tolerance 0.5` permite uma perda de até meio ponto na escala
0–100. `--fail-on-regression` retorna código 1 quando encontra regressão de
qualidade. Métricas ausentes não viram zero.

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
caso. A comparação de custo funciona mesmo sem referências:

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
