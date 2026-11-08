# Arquitetura

O benchmark prepara datasets, executa ou importa previsões e avalia resultados.
O Acessilia Core converte documentos; a Toolbox fornece capacidades e serviços
usados pelo Core. Este repositório contém a CLI, os avaliadores e os adaptadores.

## Componentes

```text
src/acessilia_benchmark/
├── cli.py              # comandos e argumentos
├── core/               # catálogo, seleção, integridade e pontuação
├── services/           # inferência, avaliação e comparação
├── adapters/           # integração com o Acessilia
├── reporting.py        # relatórios
├── io.py               # persistência, hashes e caminhos
└── processes.py        # subprocessos, logs e timeout
```

| Área | Responsabilidade |
| --- | --- |
| `core/` | Catálogo de datasets, amostragem, planos, hashes e cobertura |
| `services/` | Preparar ambientes, chamar o Core, avaliar, comparar e gerar submissões |
| `adapters/` | Executar o Core em outro processo com seu próprio interpretador |
| `reporting.py` | Normalizar métricas e produzir relatórios legíveis |
| `io.py`, `processes.py` | Gravação atômica, integridade e processos com timeout |

O `core/` deste projeto contém regras do benchmark; não é o repositório Core.
Ele não importa CLI, serviços ou adaptadores. A CLI coordena os serviços. O
adaptador usa o exportador Markdown compartilhado do Core.

O engine `pipeline` chama `backend.service.process` e mede o fluxo completo. O
engine `structure` chama `ToolboxStructureClient`, configurado pela fábrica de
clientes do Core, e usa `scripts.bench.core.payload_to_canonical` e o exportador
Markdown compartilhado. Não executa toda a orquestração do produto e requer
`--provider`.

Na rota `structure`, `TOOLBOX_USE_REMOTE_CACHE=false` é encaminhado explicitamente
ao SDK. Os metadados de cada previsão registram a política solicitada e a
proveniência observada em `structure_execution`, incluindo `cache_hit`, versão
do provider e duração informada pelo serviço. Uma resposta com `cache_hit=true`
quando o cache foi desativado é recusada. Sem esse campo na resposta, o estado
observado permanece desconhecido; a solicitação de desativação sozinha não prova
execução sem cache. Isso controla o cache de execução da Toolbox; não limpa
pesos de modelos ou outros caches internos do provider.

## Fluxo de uma rodada

1. `prepare` verifica o snapshot, seleciona os casos e grava revisões e hashes.
2. `predict` chama o Core e registra previsões, tempos e evidências; ou
   `import-predictions` registra saídas de outro sistema.
3. `evaluate` confere os artefatos, executa o avaliador e gera os relatórios.

`run <dataset>` automatiza as três etapas com inferência. `smoke` verifica o
caminho do avaliador com previsões derivadas das referências; identifica os
resultados como autoverificação, não como score do Acessilia.

Cada rodada tem um diretório em `runs/`. Resultados e planos existentes são
preservados. Uma rodada pode ter perfis `basic` e `full`, em diretórios separados;
um perfil já existente não é sobrescrito. `predict --resume` repete casos
falhos ou pendentes depois de validar as evidências. Logs, tentativas e tempos
acumulados ficam registrados. Um lock impede inferências simultâneas na mesma
rodada.

O tamanho da janela Dr.DocBench é registrado no plano. Submissões exigem uma
página por caso e cobertura completa do test. Comparações recusam amostras,
agrupamentos ou protocolos incompatíveis. Veja [fluxos](workflows.md).

## Ambientes e reprodução

| Ambiente | Uso |
| --- | --- |
| Raiz do benchmark | Pacote, CLI, datasets e ferramentas de desenvolvimento |
| `evaluation/.venv/` | Avaliadores oficiais fixados, em Python 3.11.17 |
| Ambiente do Core | Pipeline e clientes dos serviços de inferência |

O primeiro setup dos avaliadores gera um lock local, preservado em usos
posteriores. A rodada registra o hash do lock e versões instaladas. O manifesto
`evaluation/render-tools.lock.json` fixa URLs e checksums de ferramentas de
renderização adicionais. Revisões locais não fixam versões de APIs, modelos ou
caches externos; controle-as separadamente para reproduzir uma inferência.

`doctor` verifica manifests, avaliadores, módulos/configuração do Core, saúde da
API Toolbox e dos providers selecionados em cada endpoint configurado. Não roda
inferência real. `predict` faz a mesma pré-verificação, recusa iniciar se um
provider estiver indisponível e registra a identidade/versionamento da Toolbox
em `system.json`; isso não garante sucesso de uma chamada ao modelo.

`Workspace.discover()` usa `ACESSILIA_BENCHMARK_WORKSPACE` quando definido;
caso contrário, procura os dados a partir do diretório de execução e da
instalação do pacote. Os exemplos deste projeto partem da raiz do checkout.

## Arquivos locais

| Versionados | Locais e ignorados pelo Git |
| --- | --- |
| Código, testes sintéticos, documentação, catálogo e manifestos de ferramentas | Datasets em `data/`, avaliadores em `vendor/` e rodadas em `runs/` |
| `pyproject.toml` e manifestos de renderização | Ambientes, locks gerados, caches, builds e logs |
| Exemplos de configuração sem segredos | `.env`, credenciais e configurações pessoais |

As métricas e seus limites estão em [avaliação](../evaluation/README.md); testes
e CI, em [contribuição](../CONTRIBUTING.md).
