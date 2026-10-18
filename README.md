# Acessilia Benchmark

Ferramentas para avaliar a conversão de documentos do Acessilia com Dr.DocBench
e OmniDocBench. O benchmark prepara os dados, seleciona amostras, executa a
inferência e produz relatórios de qualidade e tempo de execução.

O fluxo é manual. O Acessilia e os serviços que ele utiliza precisam estar
instalados e configurados separadamente. Agendamento em cluster, badges e
publicação de rankings ficam para etapas futuras.

## Início rápido

Execute a partir da raiz do repositório, com Linux, Git,
[uv](https://docs.astral.sh/uv/getting-started/installation/) e Python 3.11–3.13.
A instalação inicial requer internet. Reserve aproximadamente 1,8 GB para os dois
datasets, além de espaço para caches, ambientes, avaliadores e resultados.

O exemplo abaixo prepara o Dr.DocBench dev e avalia dez casos:

```bash
uv sync --extra datasets --group dev
uv run acessilia-datasets download drdocbench-dev
uv run acessilia-datasets verify drdocbench-dev
uv run acessilia-benchmark setup
uv run acessilia-benchmark doctor --acessilia-repo ../acessilia
uv run acessilia-benchmark prepare drdocbench-dev --run baseline-dr --limit 10
uv run acessilia-benchmark predict --run baseline-dr --acessilia-repo ../acessilia
uv run acessilia-benchmark evaluate --run baseline-dr
```

O relatório fica em `runs/baseline-dr/basic/report.md`. O perfil padrão `basic`
calcula métricas por componente, sem CDM ou Overall. O perfil `full` acrescenta
CDM e permite calcular Overall local quando as métricas necessárias estão
presentes; exige ferramentas de renderização adicionais.

Cada caso do Dr.DocBench contém uma janela de duas páginas; no OmniDocBench,
cada caso contém uma página. Portanto, `--limit 10` limita casos, não páginas
únicas. Use um nome de rodada diferente para repetir a inferência.

Para conferir a infraestrutura sem chamar o Acessilia:

```bash
uv run acessilia-benchmark smoke drdocbench-dev --run check-dr
```

A autoverificação usa referências conhecidas como previsões e não mede a
qualidade do Acessilia. Consulte o [guia de avaliação](evaluation/README.md) para
perfis, importação de previsões, artefatos e interpretação dos resultados.

## Datasets

| Identificador | Conteúdo | Revisão fixada |
| --- | --- | --- |
| `drdocbench-dev` | 986 páginas em 66 documentos do split dev do Dr.DocBench | `7a2bc3882dff68e883fb55d10d4df22865ce2b07` |
| `omnidocbench` | 1.651 imagens de páginas e anotações estruturadas | `aa1ee96d106dbe53d0ae59474d75c6e6d9b53fec` |

O [catálogo](datasets/registry.json) reúne revisões, fontes, inventários e commits
dos avaliadores. Os dados são obtidos das fontes oficiais e armazenados
localmente; este repositório distribui as ferramentas, sem incluir os corpora.
Veja [preparação e organização dos dados](datasets/README.md) para baixar o
OmniDocBench, usar outro disco e verificar a integridade dos arquivos.

## Resultados e limites

Os relatórios registram cobertura, métricas, origem das previsões e, quando há
inferência pelo benchmark, tempos por caso e páginas processadas por minuto.
Esses tempos incluem o processo do Core e os serviços chamados; não medem
isoladamente a latência do modelo, o uso de memória ou GPU-hora.

Overall local depende do dataset, da amostra e do protocolo. Resultados do
Dr.DocBench dev por janela não equivalem ao score oficial do desafio. Uma pequena
rodada real verifica o funcionamento do fluxo; uma baseline representativa
exige uma amostra mais ampla e condições de execução registradas.

## Condições de uso

As condições registradas no catálogo distinguem dados, anotações e código:

- **Dr.DocBench:** anotações CC0-1.0; os documentos originais mantêm os direitos
  dos respectivos titulares. Consulte a [dataset card oficial](https://huggingface.co/datasets/2077AIDataFoundation/DrDocBench).
- **OmniDocBench:** o aviso oficial destina o dataset a pesquisa e exclui uso
  comercial. A licença Apache-2.0 do avaliador é distinta das condições dos dados.
  Consulte o [aviso de copyright](https://github.com/opendatalab/OmniDocBench#copyright-statement).

## Desenvolvimento

O pacote instalável fica em `src/acessilia_benchmark/` e fornece as CLIs
`acessilia-benchmark` e `acessilia-datasets`. Também pode ser executado com
`uv run python -m acessilia_benchmark`.

- [Contribuição](CONTRIBUTING.md): ambiente, testes e convenções.
- [Arquitetura](docs/architecture.md): responsabilidades, dependências e ambientes.
- [Datasets](datasets/README.md): obtenção, integridade e estrutura dos arquivos.
- [Avaliação](evaluation/README.md): execução, métricas e leitura dos relatórios.
