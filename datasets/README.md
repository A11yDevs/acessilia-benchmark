# Datasets

O [catálogo](registry.json) reúne os snapshots dos datasets e as configurações
dos avaliadores. A CLI `acessilia-datasets` obtém e verifica os arquivos,
preservando a organização original. A seleção dos casos e a execução dos
avaliadores pertencem ao [fluxo de avaliação](../evaluation/README.md).

## Obter e verificar os dados

Execute a partir da raiz do repositório. A instalação inicial e os downloads
requerem internet. Os dois snapshots ocupam aproximadamente 1,8 GB, além do
espaço temporário e do cache do downloader.

```bash
uv sync --extra datasets --group dev
uv run acessilia-datasets list
uv run acessilia-datasets download drdocbench-dev
uv run acessilia-datasets download omnidocbench
uv run acessilia-datasets verify drdocbench-dev
uv run acessilia-datasets verify omnidocbench
```

Cada snapshot fica em `data/<identificador>/<revisão>/`. O download pode ser
repetido após uma interrupção; arquivos já obtidos são reutilizados pelo
Hugging Face. Somente o split `dev` do Dr.DocBench é incluído.

Ao concluir o download, a ferramenta grava `download-manifest.json` com origem,
revisão, tamanhos e SHA-256 dos arquivos. `verify` confere os arquivos contra
esse manifesto e o inventário do catálogo. Essa verificação detecta alterações
nos arquivos; não valida a qualidade das anotações ou a execução dos avaliadores.

Para usar outro disco, informe `--data-dir` depois do identificador:

```bash
uv run acessilia-datasets download drdocbench-dev --data-dir /caminho/datasets
uv run acessilia-datasets verify drdocbench-dev --data-dir /caminho/datasets
uv run acessilia-benchmark prepare drdocbench-dev --run baseline-dr --data-dir /caminho/datasets
```

O cache do download fica em `<data-dir>/.cache/huggingface`, salvo quando
`HF_HOME` já está definido. Ao preparar uma rodada, use o mesmo diretório de
dados; o plano registra os caminhos das entradas e referências. O comando
`smoke` também aceita `--data-dir`.

## Dr.DocBench dev

Fonte: [2077AIDataFoundation/DrDocBench](https://huggingface.co/datasets/2077AIDataFoundation/DrDocBench).
Revisão: `7a2bc3882dff68e883fb55d10d4df22865ce2b07`.
Raiz padrão: `data/drdocbench-dev/<revisão>/`.

```text
dev/<assunto>/<document_uuid>/
  images/page_<N>.jpg                 # entrada
  json/<document_uuid>_page_<N>.json   # referência estruturada
  mds/<document_uuid>_<N>.md           # referência por página
  <document_uuid>.md                  # referência do documento
```

O snapshot contém 986 imagens em 66 documentos, incluindo 16 páginas em branco
cujos JSONs contêm listas vazias. O download também inclui os recortes de figuras
referenciados pelo Markdown. A numeração e os UUIDs originais são preservados.

O benchmark seleciona janelas de duas páginas consecutivas, sem atravessar
lacunas de numeração ou limites de documentos. Janelas vizinhas podem compartilhar
uma página. Na inferência, o Acessilia recebe um PDF formado pelas imagens da
janela; as referências estruturadas são usadas somente na avaliação.

O avaliador e seu commit estão fixados no catálogo. `acessilia-benchmark setup`
prepara o checkout; `evaluate` gera a configuração e executa seu ponto de entrada.
Não é necessário montar manualmente os argumentos do avaliador.

O split `test` e uma eventual trilha musical separada não fazem parte deste
fluxo. Resultados locais no dev, por janela, não equivalem ao ranking oficial.
As condições de uso estão resumidas no [README principal](../README.md#condições-de-uso).

## OmniDocBench

Fonte: [opendatalab/OmniDocBench](https://huggingface.co/datasets/opendatalab/OmniDocBench).
Revisão: `aa1ee96d106dbe53d0ae59474d75c6e6d9b53fec`.
Raiz padrão: `data/omnidocbench/<revisão>/`.

```text
images/                # 1.651 imagens de páginas
OmniDocBench.json      # anotações estruturadas
README.md              # documentação da revisão baixada
```

Cada caso corresponde a uma página. A imagem é a entrada do sistema;
`OmniDocBench.json` fornece a referência para o avaliador. As previsões são
arquivos Markdown com o mesmo nome-base das imagens.

Assim como no Dr.DocBench, o catálogo fixa o avaliador e o fluxo gera sua
configuração. As condições de uso dos dados são distintas da licença do código
do avaliador; consulte o [README principal](../README.md#condições-de-uso) e o
aviso oficial antes de usar ou redistribuir o corpus.

## Entradas, referências e resultados

Na inferência real, as requisições contêm apenas identificador e imagens.
Referências permanecem separadas e são usadas pelo avaliador. A autoverificação
`smoke` usa referências para construir previsões de teste, explicitamente
identificadas como fixtures; seus resultados não medem o Acessilia.

Dados baixados ficam em `data/`, avaliadores em `vendor/` e rodadas em `runs/`.
Esses diretórios são locais e ignorados pelo Git. Preserve revisão, split,
amostra, representação de entrada e protocolo ao comparar resultados.
