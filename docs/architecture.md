# Arquitetura do Acessilia Benchmark

O benchmark prepara amostras e avalia previsões. O Acessilia, chamado de Core
neste guia, converte documentos; a Toolbox fornece as capacidades e os serviços
usados pelo Core. O pacote do benchmark separa regras, execução e integração.

## Estrutura e responsabilidades

```text
src/acessilia_benchmark/
├── cli.py              # Argumentos e encaminhamento dos comandos
├── __main__.py         # python -m acessilia_benchmark
├── core/               # Catálogo, amostragem, integridade e pontuação
├── services/           # Preparação de ambientes, inferência e avaliação
├── adapters/           # Integração com o pipeline do Acessilia
├── reporting.py        # Normalização e apresentação dos resultados
├── io.py               # JSON atômico, hashes e caminhos seguros
└── processes.py        # Subprocessos com logs e timeout
```

| Módulo | Responsabilidade |
| --- | --- |
| `cli` | Argumentos e encaminhamento para os fluxos |
| `core.workspace` | Descoberta de caminhos e validação de nomes de rodadas |
| `core.catalog` | Catálogo, download e verificação dos snapshots |
| `core.sampling` / `core.runs` | Amostragem, planos, integridade e cobertura de previsões |
| `core.scoring` | Overall por protocolo, escala numérica e composição por janela |
| `services.runtime` / `services.render_tools` | Avaliadores fixados e ferramentas de renderização |
| `services.doctor` | Diagnóstico dos ambientes e da API Toolbox |
| `services.inference` / `adapters.acessilia` | Execução isolada e integração com o Core |
| `services.evaluation` / `reporting` | Avaliação, validação de artefatos e relatórios |
| `services.selfcheck` | Autoverificação com referências conhecidas |
| `io` / `processes` | Persistência e execução de processos compartilhadas |

`core/` não importa CLI, serviços ou adaptadores. `services/` coordena essas
regras com os ambientes externos. `adapters/` concentra os imports específicos
do Acessilia e executa em outro processo, usando o Python do Core. O diretório
`core/` do benchmark contém regras locais; ele não é o repositório Acessilia.

O contexto de arquivos é recebido como uma `Workspace` explícita. A CLI usa
`ACESSILIA_BENCHMARK_WORKSPACE` quando definido; caso contrário, procura o catálogo
no diretório atual, em seus pais e na raiz associada à instalação do pacote.
Os exemplos da documentação partem da raiz do checkout.

## Fluxo de uma rodada

1. `prepare` verifica o snapshot e grava seleção, revisões e hashes no plano.
2. `predict` envia imagens ao Core e registra previsões, tempos e evidências.
   `import-predictions` pode substituir essa etapa para saídas de outro sistema.
3. `evaluate` confere plano e previsões, executa o avaliador e gera relatórios.

`smoke` prepara uma rodada com previsões derivadas das referências e executa o
perfil `basic`. A origem fica identificada como autoverificação. O comando
verifica o caminho até o avaliador sem executar o Acessilia.

Os nomes de rodada identificam diretórios em `runs/`. Planos e previsões
existentes são preservados. Uma mesma rodada pode ser avaliada em `basic` e
`full`, cada qual em seu diretório; repetir o mesmo perfil exige outra rodada.

## Ambientes e reprodução

| Ambiente | Função |
| --- | --- |
| `.venv/` na raiz | Pacote, CLI, obtenção dos dados e ferramentas de desenvolvimento |
| `evaluation/.venv/` | Dependências dos dois avaliadores, com Python 3.11.17 |
| Ambiente do Acessilia | Pipeline do Core e clientes dos serviços de inferência |

O setup gera um lock Python local e o preserva nas execuções seguintes.
Dependências transitivas podem variar entre instalações novas; o hash do lock e
as versões instaladas são registrados nas rodadas. O manifesto de renderização
fixa URLs e checksums dos artefatos adicionais usados pelo perfil `full`.

Revisões e evidências locais não congelam versões de APIs, modelos ou caches
externos. O diagnóstico da saúde da API Toolbox também não comprova a execução
de seus provedores. Essas condições precisam de controle operacional e de uma
inferência real para validação.

## Arquivos versionados e locais

| Versionado | Local, ignorado pelo Git |
| --- | --- |
| Código, testes sintéticos, documentação e CI | Datasets em `data/` e avaliadores em `vendor/` |
| `pyproject.toml` e `evaluation/pyproject.toml` | Locks Python gerados, `.python-version` e ambientes |
| `datasets/registry.json` e `evaluation/render-tools.lock.json` | Rodadas em `runs/`, caches, builds e logs |
| Exemplos de configuração sem segredos | `.env`, variantes locais e `.aws/` |

A estrutura dos artefatos e os limites das métricas estão no
[guia de avaliação](../evaluation/README.md). As verificações para desenvolvimento
e o escopo da CI estão no [guia de contribuição](../CONTRIBUTING.md).
