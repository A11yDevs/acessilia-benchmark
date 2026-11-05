# Avaliação e métricas

Para a maioria dos casos, use `run <dataset>`: ele prepara os dados e
avaliadores, executa a inferência e gera o relatório. Execute da raiz do
repositório; requisitos e downloads estão no [README](../README.md) e no guia de
[datasets](../datasets/README.md).

Os relatórios mostram avisos recebidos do Core. `reported_warnings` indica que
um caso precisa de revisão, mas não significa automaticamente uma falha;
`unknown` ou `not_available` significam evidência
insuficiente, por exemplo em previsões importadas ou metadados antigos. A
ausência de avisos não garante execução sem degradação: o Core pode não propagar
falhas de enriquecimento matemático. As métricas avaliam o Markdown produzido,
mesmo quando há avisos. Na comparação, `processing_review` sinaliza a revisão
independentemente da regressão de qualidade.

## Preparar os avaliadores e conferir o ambiente

```bash
uv run acessilia-benchmark setup
uv run acessilia-benchmark doctor --acessilia-repo ../acessilia
```

`setup` baixa os avaliadores oficiais nas revisões do
[catálogo](../datasets/registry.json) e prepara `evaluation/.venv/` com Python
3.11.17. A instalação inicial requer internet. O lock gerado é local e
preservado para manter o ambiente entre execuções.

`doctor` confere manifests, avaliadores, módulos do Core e a API Toolbox; não
chama provedores nem testa uma inferência. Por padrão, consulta
`TOOLBOX_BASE_URL` ou `http://127.0.0.1:8002`. `--toolbox-url` muda apenas a URL
do diagnóstico, não a configuração usada pelo Core. Para selecionar outro
Python, passe `--python` a `doctor` e `predict`.

O perfil `basic` roda offline depois do download e do setup. O perfil `full`
também precisa das ferramentas de renderização descritas abaixo.

## Autoverificar os avaliadores

```bash
uv run acessilia-benchmark smoke drdocbench-dev --run check-dr
uv run acessilia-benchmark smoke omnidocbench --run check-omni
```

`smoke` seleciona casos determinísticos, usa referências como previsões e roda
`basic`. Os resultados são identificados como **autoverificação; não são scores
do Acessilia**. Use outro nome a cada execução.

## Executar uma rodada

```bash
uv run --extra datasets acessilia-benchmark run drdocbench-dev \
  --acessilia-repo ../acessilia --limit 10
```

Por padrão, roda todos os casos. `--limit N` reduz a amostra; `--seed 42`
define uma seleção determinística. O perfil automático escolhe `full` para
Dr.DocBench dev e OmniDocBench, e `runtime` para Dr.DocBench test. Também é
possível executar cada etapa separadamente:

```bash
uv run acessilia-benchmark prepare drdocbench-dev --run baseline --limit 10
uv run acessilia-benchmark predict --run baseline --acessilia-repo ../acessilia
uv run acessilia-benchmark evaluate --run baseline
```

Cada rodada registra dataset, seleção, revisões e hashes. Dr.DocBench usa duas
páginas consecutivas por caso por padrão; `--window-size 1` seleciona uma página
por caso. Não cruza lacunas ou documentos, mas janelas podem se sobrepor. Omni
usa uma página por caso. O limite conta casos, não páginas únicas.

Para o Core, cada janela Dr é convertida em PDF rasterizado a 72 dpi por
PyMuPDF. JPEGs são preservados sem recompressão; o PDF não tem camada textual nem
referências. Essa entrada fica registrada no plano.

`predict` chama `backend.service.process` e o conversor Markdown do Core. As
requisições contêm identificador e imagens, sem referências.

O Core executa com diretórios isolados em `runs/<rodada>/runtime/` para dados,
logs e temporários. O adaptador desativa dry-run e recusa estados inválidos. O
commit do Core, dependências e configuração não secreta são registrados.
`--timeout` define o limite em segundos por caso; o processo local é encerrado
em timeout, mas uma requisição já enviada pode continuar no servidor. Rodadas
incompletas não são pontuadas. Modelos, serviços externos e caches precisam ser
controlados à parte para reproduzir a inferência.

## Importar previsões

Depois de `prepare`, use `import-predictions` em vez de `predict`:

```bash
uv run acessilia-benchmark import-predictions --run baseline \
  --source /caminho/markdown --label meu-sistema
uv run acessilia-benchmark evaluate --run baseline
```

Os nomes dos arquivos precisam corresponder aos casos em `plan.json`: Dr usa
`<assunto>/<uuid>_page_<início>-<fim>.md`; Omni usa o nome-base da imagem com
extensão `.md`. Todos os casos são obrigatórios e arquivos extras são recusados;
um arquivo vazio representa uma previsão vazia. A importação registra origem e
hashes, sem atribuir tempos ou identidade ao Acessilia. Copiar arquivos
diretamente para `predictions/` não os registra para avaliação.

## Perfis e métricas

| Perfil | Métricas | Requisitos |
| --- | --- | --- |
| `basic` oficial | Texto, fórmulas, tabelas e ordem; TEDS de tabelas | Python dos avaliadores |
| `full` | `basic`, CDM de fórmulas e Overall local quando disponível | Ferramentas de renderização |
| `runtime` | Cobertura, duração, p50/p95, sucesso, falhas, timeouts e vazão | Evidências de inferência; sem referências |

`evaluate --profile auto` usa o perfil correspondente ao dataset. Também é
possível avaliar as mesmas previsões com `basic` e `full`; cada perfil tem seu
próprio diretório e resultados existentes não são sobrescritos. `runtime` usa
medições seladas da inferência, não calcula qualidade ou Overall e não produz
métricas de tempo para previsões importadas sem evidências.

### Perfil `full`

```bash
uv run acessilia-benchmark evaluate --run baseline --profile full
```

Requer TeX Live com CJK, Ghostscript, ImageMagick 7 (`magick`) e Node.js para o
tokenizador DrDocBench; tabelas LaTeX podem requerer `latexmlc`. Em Linux x86_64
com `dpkg-deb`, instale os artefatos fixados e depois prepare os avaliadores:

```bash
uv run acessilia-benchmark setup
uv run acessilia-benchmark setup-render-tools
```

O instalador guarda ferramentas e fontes em `data/tools/` e não altera os
pacotes do sistema. Em outras distribuições, instale os requisitos conforme os
avaliadores e deixe `magick` no `PATH`. Não instale ferramentas enquanto uma
avaliação estiver rodando. Falhas de renderização invalidam a avaliação; não
devem ser interpretadas como perda de qualidade do sistema.

### Overall local

O Overall usa escala 0–100. Componentes, protocolo e motivos de indisponibilidade
ficam em `summary.json`, em `overall_details`.

- **OmniDocBench:** `100 × ((1 − Text ED) + TEDS + CDM) / 3`. Text ED usa
  `text_block.all.Edit_dist.ALL_page_avg`; TEDS e CDM usam `page.*.ALL`, conforme
  o [avaliador fixado](https://github.com/opendatalab/OmniDocBench/blob/f133a71e9e91c3621c7ce8994200a7b394a06eb3/src/runtime/eval_report.py).
  Os três componentes precisam ser finitos; médias por página não são trocadas
  por médias de blocos ou documento.
- **Dr.DocBench dev:** média dos componentes disponíveis por janela, seguida da
  média das janelas pontuáveis. Texto e ordem usam `(1 − ED) × 100`; TEDS e CDM
  usam a média dos blocos da janela multiplicada por 100. Edit distance vem dos
  JSONs oficiais `*_per_page_edit.json`.

A composição Dr segue a [dataset card](https://huggingface.co/datasets/2077AIDataFoundation/DrDocBench#supported-tasks)
aplicada à entrada multipágina do avaliador. O desafio oficial usa páginas
individuais; o Overall local por janela não equivale ao score do desafio. Ordem
de leitura entra no Overall Dr, mas não no Omni. Métricas ausentes não viram
zero; componentes fora de [0,1] ou valores booleanos são recusados. Um Overall
disponível não comprova posição em ranking.

## Relatórios e limites

Os relatórios ficam em `runs/<rodada>/<perfil>/`; runtime fica em
`runs/<rodada>/runtime-report/`. `summary.json` contém dados estruturados e
`report.md` facilita a leitura. Os artefatos incluem plano,
requisições, previsões, manifesto de hashes, configuração, logs e resultados do
avaliador conforme as etapas executadas. Selos `.sha256` detectam alterações,
mas não comprovam autoria. Planos antigos com schema 1 exigem nova preparação;
relatórios históricos continuam legíveis.

Revise cobertura, casos sem pares pontuados e blocos de maior erro. Atribua
severidade conferindo imagem, referência e previsão. Os tempos incluem inicializar
processos, converter janelas, cache e serviços. p50/p95 são por caso e a vazão
conta páginas repetidas entre janelas. Não há medição de GPU-hora, pico de
memória, latência interna do modelo ou concorrência.

O split test DrDocBench não tem referências locais e gera apenas relatório
runtime. `predict` já o produz, inclusive com falhas; para regenerar, execute
`evaluate --profile runtime`. A submissão oficial requer cobertura completa e
avaliação externa. Testes unitários, autoverificação e CI não comprovam
provedores, produção ou qualidade real do Acessilia. Veja
[contribuição](../CONTRIBUTING.md) e os avaliadores oficiais de
[Dr.DocBench](https://github.com/2077AI/DrDocBench) e
[OmniDocBench](https://github.com/opendatalab/OmniDocBench).
