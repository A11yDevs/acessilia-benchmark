# Contribuindo com o Acessilia Benchmark

## Ambiente de desenvolvimento

Execute os comandos a partir da raiz do repositório, com Python 3.11–3.13 e
[uv](https://docs.astral.sh/uv/getting-started/installation/):

```bash
uv sync --extra datasets --group dev
uv run --no-sync ruff check src tests
uv run --no-sync ruff format --check src tests
uv run --no-sync pytest -q
uv build
```

O ambiente raiz contém o pacote e as ferramentas de desenvolvimento.
`evaluation/.venv/` isola as dependências dos avaliadores. O Acessilia usa seu
próprio ambiente; consulte a [arquitetura](docs/architecture.md) antes de alterar
as dependências entre esses componentes.

## Testes

Os testes unitários usam dados sintéticos, sem baixar corpora ou chamar modelos.
A configuração padrão do pytest executa somente `tests/unit/`.

Para as integrações, prepare **ambos os datasets** conforme o
[guia de dados](datasets/README.md) e os avaliadores conforme o
[guia de avaliação](evaluation/README.md):

```bash
uv run acessilia-benchmark setup
uv run --no-sync pytest tests/integration -q
# Inclui CDM e Overall; requer também as ferramentas de renderização:
uv run --no-sync pytest tests/integration --run-full -q
# Apenas OmniDocBench, com ambos os perfis:
uv run --no-sync pytest tests/integration -k omnidocbench --run-full -q
```

Sem `--run-full`, os dois testes do perfil `full` são omitidos explicitamente.
Cada integração cria rodadas exclusivas em `runs/`; os artefatos ficam locais
para inspeção. Os testes executam os avaliadores com previsões derivadas das
referências. Para medir o Acessilia, execute `prepare`, `predict` e `evaluate`
com os serviços necessários disponíveis.

A [CI](.github/workflows/ci.yml) verifica lint, formatação, testes unitários,
comandos de entrada e build. Ela não baixa datasets nem executa inferência real.

## Organização e estilo

Mantenha catálogo, amostragem, integridade e pontuação em `core/`; coordenação e
ambientes de execução em `services/`; integração específica do Acessilia em
`adapters/`; e apresentação em `reporting.py`. A CLI recebe argumentos e
encaminha a execução. `core/` não deve importar CLI, serviços ou adaptadores.

Use inglês para nomes de código, docstrings e comentários. A documentação de uso
fica em português, assim como as mensagens atuais da CLI. Comentários devem
explicar restrições, decisões de protocolo e isolamento de ambientes. Prefira
imports diretos do módulo responsável, sem reexportações por conveniência.

Atualize testes de comportamento ao alterar seleção, cobertura, execução ou
interpretação de métricas. Ao atualizar um avaliador, revise seu commit no
catálogo, as dependências declaradas e o protocolo de avaliação.

## Arquivos e commits

Versione código, testes sintéticos, documentação, catálogo, dependências
declaradas e o manifesto `evaluation/render-tools.lock.json`. Esse manifesto
fixa URLs e checksums das ferramentas de renderização; ele é diferente dos
locks Python gerados localmente.

Mantenha `uv.lock`, `poetry.lock`, `.python-version`, dados baixados, avaliadores
obtidos, rodadas, logs, ambientes, credenciais e configurações locais fora do Git.

Use Conventional Commits em inglês e separe mudanças por assunto, mantendo os
testes junto da funcionalidade correspondente. Por exemplo:

```text
feat(runs): validate prediction coverage before evaluation
fix(evaluation): reject incomplete formula metrics
docs(benchmark): clarify full profile prerequisites
```

Ao relatar uma validação, identifique amostra, revisões, perfil, modelos,
provedores e limites. Diferencie testes unitários, integrações com avaliadores e
inferência real; registre falhas e testes omitidos com seus motivos.
