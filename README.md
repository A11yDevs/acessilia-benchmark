# Acessilia Benchmark

CLI para executar e avaliar a conversão de documentos pelo Acessilia em
Dr.DocBench e OmniDocBench. O fluxo baixa e verifica dados, executa inferência e
gera relatórios. Também há comparação de rodadas, retomada, submissão
Dr.DocBench, execução Slurm e autoverificação dos avaliadores.

## Início rápido

Requisitos: Linux, Git, [uv](https://docs.astral.sh/uv/getting-started/installation/)
e Python 3.11–3.13. Deixe o Core e os serviços Toolbox/provedores configurados.
Com os repositórios em pastas irmãs, execute da raiz deste repositório:

```bash
uv run --extra datasets acessilia-benchmark run drdocbench-dev --acessilia-repo ../acessilia
```

Esse comando roda todos os casos dev, usando janelas padrão de duas páginas.
Para uma amostra menor, acrescente `--limit 10`. O `run` baixa os dados ausentes,
prepara os avaliadores, faz a inferência e gera o relatório. O perfil `auto` usa
`full` para dev e OmniDocBench, e `runtime` para Dr.DocBench test. Teste não tem
referências locais para métricas de qualidade.

### Métricas iniciais nos três datasets

O fluxo abaixo usa uma página por caso Dr.DocBench e todos os casos dos três
datasets. Para uma amostra rápida, acrescente `--limit 10` a cada comando.

```bash
export ACESSILIA_REPO=../acessilia
uv run --extra datasets acessilia-benchmark run drdocbench-dev --window-size 1
uv run --extra datasets acessilia-benchmark run omnidocbench
uv run --extra datasets acessilia-benchmark run drdocbench-test --window-size 1
```

Opcionalmente, confira o ambiente antes de iniciar:

```bash
uv run acessilia-benchmark doctor --acessilia-repo ../acessilia
```

`doctor` verifica o ambiente do Core e a API da Toolbox; não testa inferência
nos provedores. A qualidade de uma rodada real também depende dos serviços,
modelos e provedores configurados no Core.

Cada rodada recebe um nome único. O relatório fica em
`runs/<rodada>/<perfil>/report.md` ou, para runtime, em
`runs/<rodada>/runtime-report/report.md`. Dev e Omni têm referências e geram métricas
de qualidade; test gera métricas de execução. Para detalhes de seleção, perfis e
limites, consulte [avaliação](evaluation/README.md).

## Opções e fluxos avançados

| Opção | Uso |
| --- | --- |
| `--limit 10` | Executar uma amostra de dez casos; sem essa opção, roda todos |
| `--window-size 1` | Usar uma página por caso Dr.DocBench; o padrão é duas |
| `--engine structure --provider docling` | Medir um provider da Toolbox sem executar o pipeline completo |
| `--run NOME` | Definir o nome da rodada |
| `--python CAMINHO` | Escolher o interpretador do Core |
| `--data-dir CAMINHO` | Guardar os datasets em outro local |
| `--skip-setup` | Reutilizar ambientes e renderizadores preparados |
| `--offline --skip-setup` | Não baixar dados nem preparar ambientes; os serviços ainda podem usar rede |

Para comparar providers e detectar regressões, rode a mesma amostra e protocolo:

```bash
uv run --extra datasets acessilia-benchmark run drdocbench-dev \
  --run docling-dev --acessilia-repo ../acessilia --engine structure \
  --provider docling --window-size 1 --limit 30
uv run acessilia-benchmark compare baseline candidate --profile full --fail-on-regression
```

`compare` confere amostra, cobertura e protocolo antes de calcular deltas.
Consulte [fluxos](docs/workflows.md) para retomada, importação de previsões,
submissão e Slurm. Os comandos individuais `prepare`, `predict` e `evaluate`
permitem controlar cada etapa.

## Docker

Com Docker Engine e Compose:

```bash
docker compose run --build --rm benchmark drdocbench-dev
```

O Core fica em `../acessilia` por padrão. Defina `ACESSILIA_REPO` para outro
checkout. O checkout precisa conter `.git` e um `uv.lock` atual. Dados e
resultados ficam em `data/` e `runs/` no host; defina `BENCHMARK_DATA_DIR` ou
`BENCHMARK_RUNS_DIR` para movê-los. Os avaliadores e seu ambiente permanecem em
volumes Docker, mesmo após remover o container. A configuração
de modelos e credenciais vem do próprio Core; Toolbox e provedores devem estar
acessíveis dentro do container. A URL padrão da Toolbox é
`http://host.docker.internal:8002`; use `TOOLBOX_BASE_URL` para alterá-la.
Veja [arquitetura](docs/architecture.md) para os limites de reprodução.

Para verificar os avaliadores sem chamar o Acessilia:

```bash
uv run acessilia-benchmark smoke drdocbench-dev --run check-dr
```

`smoke` usa referências conhecidas como previsões e não mede a qualidade do
Acessilia.

## Datasets e condições de uso

| Dataset | Conteúdo | Resultado local |
| --- | --- | --- |
| `drdocbench-dev` | 986 páginas, 66 documentos | Qualidade e execução; resultado por janela não é o score oficial |
| `drdocbench-test` | 509 páginas, 34 documentos; referências retidas | Apenas execução; sem score local de qualidade |
| `omnidocbench` | 1.651 imagens de página e anotações | Qualidade e execução |

Revisões, fontes e inventários estão em [`datasets/registry.json`](datasets/registry.json).
Os dados são baixados para uso local e não estão incluídos no repositório.
Consulte [datasets](datasets/README.md) para download, integridade, estrutura e
condições de uso. Não redistribua corpora sem confirmar os direitos aplicáveis.

## Documentação

- [Datasets](datasets/README.md): baixar, verificar e entender os snapshots.
- [Avaliação](evaluation/README.md): perfis, métricas, relatórios e avisos.
- [Fluxos](docs/workflows.md): comparação, retomada, submissão e Slurm.
- [Arquitetura](docs/architecture.md): componentes e ambientes isolados.
- [Contribuição](CONTRIBUTING.md): ambiente, testes e convenções.
