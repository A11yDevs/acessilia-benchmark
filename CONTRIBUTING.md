# Contribuir

Use Python 3.11–3.13 e [uv](https://docs.astral.sh/uv/getting-started/installation/).
Execute os comandos da raiz do repositório:

```bash
uv sync --extra datasets --group dev
uv run --no-sync ruff check src tests
uv run --no-sync ruff format --check src tests
uv run --no-sync pytest -q
uv build
```

## Testes

`pytest` executa somente `tests/unit/`: testes sintéticos, sem baixar datasets
ou chamar modelos. Para as integrações, baixe DrDocBench dev e OmniDocBench e
prepare os avaliadores conforme os guias de [datasets](datasets/README.md) e
[avaliação](evaluation/README.md):

```bash
uv run acessilia-benchmark setup
uv run --no-sync pytest tests/integration -q
# Inclui CDM e Overall; requer também as ferramentas de renderização.
uv run --no-sync pytest tests/integration --run-full -q
uv run --no-sync pytest tests/integration -k omnidocbench --run-full -q
```

Sem `--run-full`, os testes que exigem o perfil `full` são omitidos. Integrações
usam previsões derivadas das referências e não medem o Acessilia. Para validar
inferência, rode `run` com Core, Toolbox e provedores disponíveis. A
[CI](.github/workflows/ci.yml) verifica lint, formatação, unitários, CLI e build;
não baixa corpora nem executa inferência.

## Organização e estilo

- Mantenha catálogo, seleção, integridade e pontuação em `core/`.
- Mantenha execução e coordenação em `services/`, integração com Core em
  `adapters/` e relatórios em `reporting.py`.
- `core/` não importa CLI, serviços ou adaptadores.
- Use inglês em código, docstrings e comentários; a documentação de uso fica
  em português.
- Atualize testes quando mudar seleção, cobertura, execução ou métricas.
- Ao alterar um avaliador, confira o commit do catálogo, dependências e protocolo.

## Arquivos e commits

Versione código, testes sintéticos, documentação, catálogo, dependências
declaradas e `evaluation/render-tools.lock.json`. Mantenha fora do Git os locks
Python gerados, `.python-version`, dados, avaliadores baixados, rodadas, logs,
ambientes, credenciais e configurações locais.

Use Conventional Commits em inglês e separe mudanças por assunto, por exemplo:

```text
feat(runs): validate prediction coverage before evaluation
fix(evaluation): reject incomplete formula metrics
docs(benchmark): clarify full profile prerequisites
```

Ao relatar validação, diferencie testes unitários, integração com avaliadores e
inferência real. Informe amostra, revisões, perfil, modelos, provedores e limites;
inclua falhas e testes omitidos.
