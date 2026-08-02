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
