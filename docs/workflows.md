# Baselines, regressões e execução em cluster

Este repositório mede tanto o pipeline completo do Acessilia quanto a extração
de estrutura de um provider. Os dois caminhos usam os mesmos snapshots,
planos, exportador Markdown do `docstruct` e avaliadores oficiais. Os dados e
ambientes devem estar preparados conforme o [README](../README.md).

## Comparar providers com o pipeline completo

Use a mesma seleção, seed e tamanho de janela nas rodadas. No Dr.DocBench,
`--window-size 1` inclui páginas isoladas e permite comparação por página com
o harness `scripts.bench` do Core. O padrão histórico continua sendo duas
páginas consecutivas; não é permitido misturar essas unidades na comparação.
No OmniDocBench, cada caso tem sempre uma página.

```bash
# Baseline de extração: usa scripts.bench.toolbox e scripts.bench.core do Core.
uv run --extra datasets acessilia-benchmark run drdocbench-dev \
  --run docling-dev --acessilia-repo ../acessilia \
  --engine structure --provider docling --window-size 1 --limit 30 --seed 42

# Outro provider, com a mesma amostra e o mesmo avaliador.
uv run --extra datasets acessilia-benchmark run drdocbench-dev \
  --run mineru-dev --acessilia-repo ../acessilia \
  --engine structure --provider mineru --window-size 1 --limit 30 --seed 42

# Pipeline completo: backend.service.process, configuração normal do Core.
uv run --extra datasets acessilia-benchmark run drdocbench-dev \
  --run acessilia-dev --acessilia-repo ../acessilia \
  --engine pipeline --window-size 1 --limit 30 --seed 42

uv run acessilia-benchmark compare docling-dev mineru-dev \
  --profile full --fail-on-regression --output results/docling-vs-mineru.json
```

O engine `structure` mede a extração do provider, a construção do documento
canônico e sua exportação. Não executa o restante da orquestração do produto.
`--provider` é exclusivo desse engine; o engine `pipeline` usa a configuração
do Core. Providers e modelos precisam estar disponíveis na Toolbox. O benchmark
não instala nem inicia esses serviços.

`compare` verifica planos, previsões e resultados selados. Recusa datasets,
revisões, entradas, agrupamentos, referências, avaliadores, ambientes de
avaliação e coberturas incompatíveis. Calcula deltas respeitando a direção:
Edit distance menor é melhor; TEDS, CDM e Overall maiores são melhores.
`--tolerance 0.5` permite perdas de até meio ponto na escala 0–100 por métrica;
as métricas originais do avaliador continuam em sua escala fracionária no JSON.
`--fail-on-regression` retorna código 1 quando há regressão de qualidade.

Métricas ausentes não viram zero e a perda de cobertura é recusada. O veredito
vale para a amostra inteira escolhida; não implementa o aceite tune/holdout do
harness do Core e não demonstra generalização. Reserve documentos independentes
para validação antes de escolher configurações. Resultados com perfil `basic`
podem ser comparados, mas não têm CDM ou Overall. Rodadas de autoverificação
só podem ser comparadas entre si e permanecem identificadas como fixtures.

Relatórios anteriores à introdução dos selos de avaliação permanecem legíveis,
mas não são aceitos pelo novo `compare`: prepare e avalie novas rodadas.

## Retomar uma inferência parcial

```bash
uv run acessilia-benchmark predict --run mineru-dev \
  --acessilia-repo ../acessilia --engine structure --provider mineru --resume

# Depois de concluir todos os casos:
uv run acessilia-benchmark evaluate --run mineru-dev --profile full
```

A retomada repete apenas falhas e casos pendentes. Confere os hashes das saídas
válidas, metadados, código do Core, adaptador, dependências declaradas,
interpretador e configuração registrada. Mudanças exigem outra rodada. Versões
de modelos e serviços externos ainda devem ser controladas pelo operador: um
endpoint estável pode servir outro modelo sem alterar os arquivos locais.

Cada tentativa mantém seus logs em `logs/N/`; a evidência anterior fica em
`attempts/N/`. O relatório runtime registra chamadas, chamadas falhas, estado
final por caso e tempos acumulados de todas as tentativas. Percentis passam a
representar o custo acumulado por caso, incluindo retomadas. Rodadas concluídas
e válidas não repetem inferência. Duas inferências simultâneas na mesma rodada
são bloqueadas. Checkpoints são salvos a cada caso; uma interrupção abrupta
durante a gravação pode exigir inspeção, pois evidências inconsistentes são
recusadas. Rodadas antigas sem hashes por caso não permitem retomada segura.

```bash
# Comparar custo e falhas, inclusive em rodadas parciais ou sem referências:
uv run acessilia-benchmark compare baseline-test candidate-test --profile runtime
```

Tempo inclui processo, entrada, cache e serviços. Comparar tempo entre engines
ou servidores distintos ajuda a entender o custo do fluxo, mas não isola
latência de modelo, GPU-hora ou efeito de cache.

## Preparar uma submissão Dr.DocBench

```bash
uv run --extra datasets acessilia-benchmark run drdocbench-test \
  --run submission-docling --acessilia-repo ../acessilia \
  --engine structure --provider docling --window-size 1
uv run acessilia-benchmark submit --run submission-docling
```

O pacote local `runs/submission-docling/submission/submission.zip` contém
`predictions.jsonl`, com `subject`, `document_id`, `page` e `markdown` por página.
O manifesto ao lado registra a revisão e os hashes do plano, das previsões e
do zip. A geração exige o snapshot íntegro e todas as páginas, sem falhas,
seleção parcial ou janelas de duas páginas. O comando não envia o pacote.
O split test não tem score local de qualidade; o resultado do desafio depende
do avaliador oficial da submissão. A aceitação pelo serviço externo não foi
verificada por testes locais de formato.

## Slurm

Instale previamente o pacote, baixe os snapshots e prepare os avaliadores e
renderizadores em storage compartilhado. O Core deve ter seu próprio ambiente.
Toolbox e providers precisam estar acessíveis a partir dos nós de execução.
O job deste benchmark reutiliza a configuração do Core; os jobs que iniciam
providers dentro da alocação continuam disponíveis em `scripts/bench/slurm/`
no repositório do Core.

```bash
export ACESSILIA_BENCHMARK_WORKSPACE=/shared/repos/acessilia-benchmark
export ACESSILIA_REPO=/shared/repos/acessilia
export ACESSILIA_PYTHON=/shared/repos/acessilia/.venv/bin/python
export RUN=docling-dev-cluster DATASET=drdocbench-dev
export ENGINE=structure PROVIDER=docling WINDOW_SIZE=1 LIMIT=30
sbatch -p SUA_PARTICAO -c 8 --mem=32G --time=04:00:00 \
  --export=ALL scripts/slurm/benchmark.sbatch
```

`PROFILE=auto` seleciona full ou runtime conforme as referências. `SEED`,
`TIMEOUT`, `EVALUATION_TIMEOUT` e `BENCHMARK_DATA_DIR` podem ser definidos.
Reenviar o mesmo `RUN` retoma o plano existente; mantenha dataset, seleção e
configuração. Recursos de GPU dependem dos serviços usados; ajuste a alocação
ao seu cluster. O script foi verificado localmente, sem submissão a Slurm.
