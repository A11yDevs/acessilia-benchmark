# Acessilia Benchmark

Ferramentas para avaliar a conversão de documentos do Acessilia com Dr.DocBench
e OmniDocBench. O benchmark prepara os dados, seleciona amostras, executa a
inferência e produz relatórios de qualidade e tempo de execução.

O comando `run` automatiza a preparação, inferência e geração de métricas.
O Acessilia e os serviços que ele utiliza precisam estar configurados.
Agendamento em cluster, badges e publicação de rankings ficam para etapas futuras.

## Início rápido

Execute a partir da raiz do repositório, com Linux, Git,
[uv](https://docs.astral.sh/uv/getting-started/installation/) e Python 3.11–3.13.
A instalação inicial requer internet. Reserve aproximadamente 1,9 GB para os três
snapshots, além de espaço para caches, ambientes, avaliadores e resultados.

Com um checkout do Core e seus serviços configurados, execute:

```bash
uv run --extra datasets acessilia-benchmark run drdocbench-dev --acessilia-repo ../acessilia
```

O comando baixa os dados ausentes, verifica a integridade, prepara os avaliadores,
executa todo o dataset e gera os relatórios. O perfil automático usa `full` com
CDM e Overall quando aplicáveis; sem referências, usa `runtime`. Se faltarem
ferramentas de CDM, a preparação falha sem reduzir o perfil silenciosamente.
Os requisitos de renderização estão no [guia de avaliação](evaluation/README.md).

A rodada recebe um nome único e mostra o caminho do relatório ao terminar:
`runs/NOME/full/report.md` ou `runs/NOME/runtime-report/report.md`.

| Opção | Quando usar |
| --- | --- |
| `--limit 10` | Executar uma amostra menor; o padrão é todo o dataset |
| `--run NOME` | Escolher o nome da rodada; resultados existentes são preservados |
| `--python CAMINHO` | Escolher o interpretador do Core em vez de detectar .venv/Poetry |
| `--data-dir CAMINHO` | Armazenar snapshots em outro diretório |
| `--skip-setup` | Reutilizar ambientes e renderizadores já preparados |
| `--offline --skip-setup` | Não baixar dados nem preparar ambientes; inferência ainda pode usar rede |

Defina `ACESSILIA_REPO` e, opcionalmente, `ACESSILIA_PYTHON` no ambiente para
omitir esses caminhos. Os comandos individuais `prepare`, `predict` e `evaluate`
continuam disponíveis. No Dr.DocBench, cada caso contém duas páginas; no
OmniDocBench, uma. `--limit` conta casos, não páginas únicas.

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
| `drdocbench-test` | 509 páginas em 34 documentos; referências retidas; métricas de execução | `7a2bc3882dff68e883fb55d10d4df22865ce2b07` |
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
