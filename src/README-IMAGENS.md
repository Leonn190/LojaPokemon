# Estrutura das coleções e imagens

Cada colecionador possui uma pasta própria em `src/coleções/`:

```text
src/
└── coleções/
    └── Leon19/
        ├── perfil.json
        ├── inventario-cartas.csv
        ├── inventario-boosters.csv
        └── inventario-kits.csv
```

Para adicionar outro colecionador, duplique a pasta `Leon19`, altere o nome da nova pasta e edite os quatro arquivos. O site encontra todas as pastas automaticamente durante o build e reúne os itens nas páginas gerais.

## Imagens atuais

As imagens existentes podem continuar nas pastas globais:

```text
public/
├── imagens/
├── imagensboosters/
└── imagenskits/
```

O catálogo mantém a associação automática por nome e numeração, aceita `.jpg`, `.jpeg`, `.png`, `.webp` e `.avif` e respeita o `base` configurado para o GitHub Pages.

## Imagens por colecionador

Também é possível separar imagens de futuros usuários:

```text
public/
└── colecoes/
    └── nome-da-pasta-normalizado/
        ├── imagens/
        ├── imagensboosters/
        └── imagenskits/
```

O sistema procura primeiro as imagens específicas da coleção e depois usa as pastas globais como alternativa.

## Formato de kits

O arquivo `inventario-kits.csv` usa as colunas:

```text
Nome,Descrição,Preço,Quantidade,Conteúdo,Imagem
```

A coluna `Imagem` é opcional. Quando estiver vazia, o site exibe uma arte de fallback própria para kits.

## Formatador e updates

O script principal agora é `formatador.py`. Ele lê coleções completas e pacotes de atualização colocados em `src/Coleções não formatadas/`.

Durante uma execução, o script abre apenas um Chrome. Cada carta ou booster é consultado em uma nova aba; ao terminar, essa aba é fechada e uma aba-base permanece aberta. O perfil usado pelo Chrome é temporário e é apagado automaticamente ao encerrar, portanto nenhuma pasta `perfil_chrome_liga` é criada dentro do projeto.

O editor pode gerar um ZIP completo ou um ZIP contendo somente as adições. O ZIP de update usa esta estrutura:

```text
atualizacao.json
inventario-cartas.csv      # Link Liga,Quantidade,Estado,Idioma
inventario-boosters.csv    # Link Liga,Quantidade
```

`atualizacao.json` informa o `collectionId` da coleção de destino. O formatador consulta as novas linhas, acrescenta ou soma suas quantidades na coleção correspondente e registra o identificador do update para impedir que o mesmo pacote seja aplicado duas vezes.

As coleções formatadas seguem os mesmos cabeçalhos da pasta `src/coleções/Leon19/`. Antes de baixar uma imagem, o formatador procura um arquivo equivalente em `public/imagens/`; quando ele já existe, nenhum arquivo novo é criado.
