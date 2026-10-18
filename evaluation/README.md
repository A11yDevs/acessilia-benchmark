# Avaliação manual

O fluxo de avaliação é `prepare → predict → evaluate`. Execute os comandos a
partir da raiz do repositório. A instalação do pacote e a obtenção dos dados
estão no [README principal](../README.md#início-rápido) e no
[guia de datasets](../datasets/README.md).

## 1. Preparar os ambientes

### Avaliadores

Com Linux, Git e uv disponíveis, execute:

```bash
uv run acessilia-benchmark setup
```

O comando obtém os dois avaliadores em `vendor/`, verifica os commits do
[catálogo](../datasets/registry.json) e prepara `evaluation/.venv/` com Python
3.11.17 e as dependências de `evaluation/pyproject.toml`. A instalação inicial
requer internet; os avaliadores usam um ambiente separado do pacote e do Core.

O primeiro setup gera `evaluation/uv.lock`, preservado nos setups seguintes.
Locks Python gerados e `.python-version` ficam fora do Git. Preserve o lock local
para reproduzir um ambiente anterior: a resolução transitiva pode variar entre
instalações novas. As rodadas registram seu hash e as versões instaladas.

Depois do setup e do download dos dados, o perfil `basic` executa offline e sem
GPU. O perfil `full` requer também as ferramentas de renderização descritas
[adiante](#perfil-full-e-ferramentas-de-renderização).

### Acessilia e Toolbox

Para executar `predict`, o checkout do Acessilia precisa estar instalado e
configurado, com os modelos e provedores necessários disponíveis. O benchmark
não inicia esses serviços. Confira o ambiente antes de preparar a inferência:

```bash
uv run acessilia-benchmark doctor --acessilia-repo ../acessilia
```

O interpretador do Core é procurado em `.venv/bin/python` e no ambiente Poetry.
Se necessário, informe `--python /caminho/do/ambiente/bin/python` a `doctor` e
`predict`. Links simbólicos do ambiente virtual são preservados.

Por padrão, `doctor` consulta `TOOLBOX_BASE_URL` ou `http://127.0.0.1:8002`;
`--toolbox-url` permite escolher outra URL para o diagnóstico. Essa opção não
altera a configuração usada pelo Core na inferência. O diagnóstico verifica
presença dos manifests dos dados, revisão dos avaliadores, módulos do Core e
saúde da API Toolbox. A integridade completa dos dados é verificada por
`verify` e `prepare`; a saúde da API não comprova execução dos provedores.

## 2. Conferir os avaliadores sem chamar modelos

Com os respectivos datasets baixados e o setup concluído:

```bash
uv run acessilia-benchmark smoke drdocbench-dev --run check-dr
uv run acessilia-benchmark smoke omnidocbench --run check-omni
```

Cada autoverificação seleciona dez casos determinísticos, incluindo texto,
tabelas e fórmulas, constrói previsões a partir das referências e executa o
perfil `basic`. Os resultados ficam marcados **AUTOVERIFICAÇÃO — NÃO É SCORE
DO ACESSILIA**. As representações Markdown e os algoritmos de correspondência
podem produzir diferenças mesmo quando a previsão vem da referência.

Use outro nome ao repetir uma rodada. `smoke` também aceita
`--data-dir /caminho/datasets` para dados em outro local.

## 3. Executar uma rodada real

Exemplo com dez casos do Dr.DocBench dev:

```bash
uv run acessilia-benchmark prepare drdocbench-dev --run baseline-dr --limit 10
uv run acessilia-benchmark predict --run baseline-dr --acessilia-repo ../acessilia
uv run acessilia-benchmark evaluate --run baseline-dr
```

Para OmniDocBench:

```bash
uv run acessilia-benchmark prepare omnidocbench --run baseline-omni --limit 10
uv run acessilia-benchmark predict --run baseline-omni --acessilia-repo ../acessilia
uv run acessilia-benchmark evaluate --run baseline-omni
```

### Seleção e entrada

`prepare` verifica os dados e congela os casos com seed 42. `--seed N` escolhe
outra amostra determinística; `--limit 0` seleciona todos os casos disponíveis.
A seleção alterna fontes documentais no OmniDocBench e assuntos no Dr.DocBench.
Use `--data-dir /caminho/datasets` se os dados estiverem em outro disco.

Cada caso do OmniDocBench contém uma página. Cada caso do Dr.DocBench reúne duas
páginas consecutivas, sem atravessar lacunas ou limites de documentos. As janelas
deslizam uma página por vez, podendo repetir páginas entre casos. O limite é de
casos, não de páginas únicas.

Para o Core, cada janela do Dr.DocBench é empacotada em PDF rasterizado a 72 dpi
via PyMuPDF. Os streams JPEG são preservados sem recompressão; não há camada
textual ou referências. Essa variante de entrada fica registrada e não presume
equivalência a uma chamada direta com duas imagens.

### Inferência e evidências

`predict` chama `backend.service.process` e o conversor
`canonical_to_drbench_md` do Acessilia. As requisições contêm apenas identificador
e imagens; as referências permanecem separadas da inferência.

Dados, histórico e logs locais do Core são isolados em `runs/<rodada>/runtime/`
por meio de `DATA_DIR`, `LOGS_DIR` e `TEMP_DIR`. O processo recebe
`PDDL_EXECUTE_DRY_RUN=false`, e o adaptador recusa resultados de dry-run ou
estados de execução inválidos. Configuração não secreta dos modelos e provedores,
commit do Core e hashes de seus arquivos de dependências ficam registrados.

`--timeout 1800` define o limite em segundos por caso. Em caso de timeout, o grupo
de processos locais é encerrado; uma requisição remota já enviada pode continuar
no servidor. Logs e falhas são registrados. Inferência incompleta não é pontuada.

Para repetir a inferência, prepare outra rodada. Para comparar execuções, use a
mesma seleção, commit, dependências, modelos, Toolbox, configuração e condição
de cache. Versões de serviços externos e aliases de modelos não são congelados
automaticamente pelo benchmark.

### Importar previsões de outro sistema

Depois de `prepare`, use `import-predictions` no lugar de `predict`:

```bash
uv run acessilia-benchmark import-predictions --run baseline-dr --source /caminho/markdown --label meu-sistema
uv run acessilia-benchmark evaluate --run baseline-dr
```

O diretório de origem deve seguir os nomes registrados em `plan.json`: no Dr,
`<assunto>/<uuid>_page_<início>-<fim>.md`; no Omni, o nome-base da imagem com
extensão `.md`. Todos os casos precisam estar presentes, sem Markdown extra.
Arquivos vazios são previsões vazias válidas.

A importação registra origem e hashes, sem atribuir identidade ou tempos de
execução ao Acessilia. Copiar arquivos diretamente para o diretório de previsões
da rodada não basta para avaliá-los.

## 4. Avaliar e interpretar os resultados

| Perfil | Métricas | Overall local | Requisitos adicionais |
| --- | --- | --- | --- |
| `basic` (padrão) | Distância de edição de texto, fórmulas, tabelas e ordem; TEDS de tabelas | Não calcula | Ambiente Python dos avaliadores |
| `full` | Métricas de `basic` e CDM de fórmulas | Calcula quando há componentes válidos | Ferramentas de renderização |

`evaluate --timeout 1800` limita a execução do avaliador em segundos. Antes de
avaliar, o ambiente Python é sincronizado offline com o lock local. Plano,
previsões e evidências são conferidos antes e depois da execução. Rodadas
incompletas, artefatos alterados ou resultados sem os componentes oficiais
esperados são recusados.

Cada perfil tem seu diretório: `runs/<rodada>/basic/` ou `runs/<rodada>/full/`.
É possível executar os dois perfis sobre as mesmas previsões, mas um diretório
de avaliação existente não é sobrescrito.

### Perfil full e ferramentas de renderização

```bash
uv run acessilia-benchmark evaluate --run baseline-dr --profile full
```

O perfil exige TeX Live com recursos CJK, Ghostscript e ImageMagick 7 (`magick`).
O Dr.DocBench também requer Node.js para seu tokenizador LaTeX. Para tabelas
LaTeX, pode ser necessário `latexmlc`. `setup` instala as dependências Python;
o comando de avaliação confere as ferramentas externas e registra suas versões.

Em Linux x86_64 com `dpkg-deb`, há um instalador local dos artefatos adicionais,
preparado para Ubuntu 24.04:

```bash
uv run acessilia-benchmark setup-render-tools
uv run acessilia-benchmark evaluate --run baseline-dr --profile full
```

O instalador usa URLs e SHA-256 do [manifesto de renderização](render-tools.lock.json)
para obter ImageMagick 7.1.2-34, fontes, pacotes CJK e `match-at` 0.1.0, dependência
do tokenizador Dr cujo arquivo compilado não acompanha o checkout. Os arquivos
ficam em `data/tools/` e no checkout local do tokenizador; pacotes do sistema não
são alterados. Execute `setup` antes do instalador.

Ainda são necessários TeX Live (latex-base, latex-extra, fontes recomendadas e
XeTeX), Ghostscript, fontconfig e Node.js no host. Em outras distribuições,
prepare o ambiente conforme a documentação do avaliador e disponibilize
`magick` no `PATH`.

A instalação pode ser repetida, mas não deve ocorrer enquanto avaliações estão
em curso. O perfil `full` descobre as ferramentas e fontes locais sem alterar o
ambiente do processo principal, preservando configurações explícitas. Falhas de
renderização detectadas e referências sem artefatos renderizados invalidam a
avaliação; não devem ser tratadas como perda de qualidade do sistema.

### Overall por dataset

O Overall local usa escala 0–100. O protocolo, os componentes e os motivos de
indisponibilidade ficam em `summary.json`, no campo `overall_details`.

- **OmniDocBench:** `100 * ((1 - Text ED) + TEDS + CDM) / 3`. Text ED usa
  `text_block.all.Edit_dist.ALL_page_avg`; TEDS e CDM usam `page.*.ALL`, conforme
  o [resumo do avaliador fixado](https://github.com/opendatalab/OmniDocBench/blob/f133a71e9e91c3621c7ce8994200a7b394a06eb3/src/runtime/eval_report.py).
  Os três componentes precisam ser finitos. Médias por página não são
  substituídas por médias de blocos ou do documento inteiro.
- **Dr.DocBench dev:** média dos componentes disponíveis por janela, seguida da
  média das janelas pontuáveis. Texto e ordem usam `(1 - ED) * 100`; TEDS e CDM
  usam a média dos blocos daquela janela multiplicada por 100. As distâncias
  por janela vêm dos JSONs oficiais `*_per_page_edit.json`.

A composição Dr segue a [dataset card](https://huggingface.co/datasets/2077AIDataFoundation/DrDocBench#supported-tasks)
aplicada à unidade multipágina do avaliador fixado. O
[desafio](https://drdocbench-challenge.abaka-pages.com/#evaluation) usa páginas
individuais; este resultado por janela não é um score oficial do desafio. Ordem
de leitura entra no Overall Dr, mas não no Overall Omni.

As métricas numéricas consumidas pela agregação usam frações em [0,1]. Valores
fora da escala e booleanos são recusados. Ausência de um tipo de elemento não
vira zero; uma métrica ausente em um bloco efetivamente pontuado é falha. No
Omni, a ausência de qualquer um dos três componentes impede calcular Overall.
Um Overall disponível em `full` não comprova posição no ranking.

### Artefatos da rodada

```text
runs/<rodada>/
  plan.json                  # seleção, revisões e hashes de entradas/referências
  requests/                  # identificador e imagens de cada caso
  prediction-manifest.json   # origem, hashes das previsões e evidências
  predictions/               # Markdown e, com predict, metadados por caso
  system.json                # Core e ambiente, quando predict foi usado
  inference.json             # tentativas e estado final, quando predict foi usado
  timings.jsonl              # tempo por tentativa, quando predict foi usado
  logs/                      # stdout/stderr do Core, quando predict foi usado
  runtime/                   # armazenamento isolado do Core
  basic/                     # full/ tem a mesma organização de avaliação
    config.json              # configuração fornecida ao avaliador
    execution.json           # comando, versões, hashes e estado da avaliação
    evaluator.log            # saída do avaliador oficial
    result/                  # métricas e pares de blocos oficiais
    summary.json             # métricas, cobertura, tempos e piores blocos
    report.md                # relatório legível com links para as imagens
```

O Omni também grava `ground-truth.json` com as referências selecionadas. Selos
`.sha256` acompanham os artefatos protegidos; eles detectam alterações, mas não
são assinaturas de autoria. Planos antigos com schema 1 exigem nova preparação;
preserve seus relatórios históricos.

Métricas não finitas são normalizadas como `null`, sem inventar score zero.
Confira a cobertura e os casos sem pares pontuados. Os blocos de maior erro
servem como triagem quantitativa; revise imagem, referência e previsão para
atribuir severidade ao problema.

Os tempos incluem inicialização do processo, conversão da janela em PDF, cache
e serviços chamados pelo Core. p50/p95 são por caso; a taxa de páginas por minuto
conta repetições entre janelas. Não há medição de GPU-hora, pico de memória,
latência interna isolada de modelo ou vazão concorrente.

## Validação e referências

Os [testes de desenvolvimento](../CONTRIBUTING.md#testes) distinguem testes
unitários, integrações com avaliadores e inferência real. Dados, previsões,
checkouts dos avaliadores e rodadas ficam locais e ignorados pelo Git.
Autoverificação e CI não comprovam disponibilidade de provedores, execução em
H100 ou qualidade do Acessilia.

- [Dr.DocBench](https://github.com/2077AI/DrDocBench): avaliador e protocolo multipágina.
- [OmniDocBench](https://github.com/opendatalab/OmniDocBench): avaliador, protocolo e ferramentas de renderização.
