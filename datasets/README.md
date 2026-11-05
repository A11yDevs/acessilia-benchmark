# Datasets

O [catálogo](registry.json) define as únicas opções de dataset integradas ao
benchmark: `drdocbench-dev`, `drdocbench-test` e `omnidocbench`. Também fixa as
fontes, revisões, inventários e avaliadores. Use `acessilia-datasets` para baixar
e verificar os snapshots; `prepare` seleciona os casos para uma rodada. Os dados
ficam em `data/` e não são versionados.

## Baixar e verificar

Execute da raiz do repositório. A instalação inicial e os downloads requerem
internet; os três snapshots Dr/Omni ocupam aproximadamente 1,8 GB.

```bash
uv sync --extra datasets --group dev
uv run acessilia-datasets list
for dataset in drdocbench-dev drdocbench-test omnidocbench; do
  uv run acessilia-datasets download "$dataset"
  uv run acessilia-datasets verify "$dataset"
done
```

Os arquivos ficam em `data/<dataset>/<revisão>/`. Downloads interrompidos podem
ser repetidos. O manifesto registra origem, revisão, tamanho e SHA-256;
`verify` confere esses dados contra o catálogo. Isso detecta arquivos ausentes
ou alterados, mas não valida a qualidade das anotações nem a execução do
avaliador.

Para usar outro disco, passe `--data-dir` aos comandos de dados e avaliação:

```bash
uv run acessilia-datasets download drdocbench-dev --data-dir /dados/benchmark
uv run acessilia-datasets verify drdocbench-dev --data-dir /dados/benchmark
uv run acessilia-benchmark prepare drdocbench-dev --run baseline --data-dir /dados/benchmark
```

O cache do Hugging Face fica em `<data-dir>/.cache/huggingface`, salvo se
`HF_HOME` estiver definido. Use o mesmo diretório em todas as etapas de uma
rodada; o plano registra os caminhos usados.

## Dr.DocBench dev

Fonte: [dataset oficial](https://huggingface.co/datasets/2077AIDataFoundation/DrDocBench),
revisão `7a2bc3882dff68e883fb55d10d4df22865ce2b07`. O snapshot tem 986 páginas em
66 documentos, incluindo 16 páginas em branco. As imagens, anotações JSON,
referências Markdown e recortes de figuras mantêm os nomes e a organização
originais.

O benchmark usa duas páginas consecutivas por caso por padrão. `--window-size 1`
seleciona páginas individuais; janelas não atravessam lacunas ou documentos, e
janelas de duas páginas podem se sobrepor. As referências estruturadas são usadas
na avaliação, não enviadas ao Core. Scores locais por janela não equivalem ao
resultado oficial por página. As anotações são CC0-1.0; os documentos mantêm os
direitos dos titulares. Consulte o [cartão oficial](https://huggingface.co/datasets/2077AIDataFoundation/DrDocBench).

## Dr.DocBench test

Usa a mesma fonte e revisão do dev. O snapshot contém 509 páginas em 34 documentos;
as referências são retidas pelos autores. A seleção usa janelas consecutivas e
estratificação por assunto. Use `--window-size 1` para casos por página e para
gerar uma submissão.

`prepare` e `predict` funcionam sem referências; avaliação automática escolhe o
perfil `runtime`, que informa cobertura, duração, p50/p95, falhas, timeouts e
vazão. Não há métricas locais de qualidade ou Overall. Uma submissão exige todas
as páginas, sem falhas ou seleção parcial; `submit` gera o arquivo local, sem
enviá-lo ao serviço do desafio. Veja [fluxos](../docs/workflows.md).

## OmniDocBench

Fonte: [dataset oficial](https://huggingface.co/datasets/opendatalab/OmniDocBench),
revisão `aa1ee96d106dbe53d0ae59474d75c6e6d9b53fec`. Contém 1.651 imagens de
página e anotações estruturadas; cada caso representa uma página. O catálogo
também fixa o commit do avaliador.

O aviso dos autores destina os dados a pesquisa e exclui uso comercial. A licença
Apache-2.0 do avaliador não se aplica automaticamente ao corpus. Leia o
[aviso de copyright](https://github.com/opendatalab/OmniDocBench#copyright-statement)
antes de usar ou redistribuir os dados.

## Entradas e resultados

Inferências reais recebem identificador e imagens, sem referências. `smoke` é
autoverificação: constrói previsões de teste a partir das referências e não mede
o Acessilia. Os avaliadores ficam em `vendor/` e as rodadas em `runs/`; esses
arquivos também são locais e ignorados pelo Git. Para comparar resultados, fixe
dataset, revisão, amostra, unidade de entrada e protocolo.
