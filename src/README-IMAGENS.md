# Estrutura das coleções, JSON e imagens

Cada colecionador possui uma pasta em `src/colecoes/`:

```text
src/
└── colecoes/
    └── Leon19/
        ├── perfil.json
        ├── inventario-cartas.json
        ├── inventario-boosters.json
        ├── inventario-kits.json
        ├── inventario-albuns.json
        └── historico/
            ├── cartas.jsonl
            └── boosters.jsonl
```

O site lê JSON como formato oficial. CSV continua aceito apenas por leitores de compatibilidade para importar/migrar versões antigas.

## Imagens

As imagens podem continuar nas pastas globais:

```text
public/
├── imagens/
├── imagensboosters/
└── imagenskits/
```

O campo `Imagem` dos JSONs tem prioridade. O Gerenciamento salva cartas e boosters baixados da Liga em `public/imagens/` e registra o nome do arquivo no próprio item. Se `Imagem` estiver vazio, o catálogo ainda usa as heurísticas antigas por nome/numeração como fallback.

Também continuam suportadas imagens por coleção em `public/colecoes/<slug>/...`.

## Kits

`inventario-kits.json` é uma lista. `Conteúdo` é uma lista de referências reais:

```json
[
  {
    "Id": "KIT-...",
    "Nome": "Kit Pikachu",
    "Conteúdo": [
      {
        "kind": "cards",
        "itemId": "XYP-XY124-BR-NM",
        "name": "Pikachu EX",
        "quantity": 1,
        "unitPrice": 1900.0
      }
    ]
  }
]
```

O preço do kit é recalculado pelo `itemId`. Nome é apenas informação visual/fallback legado.

## Álbuns

`inventario-albuns.json` guarda `Páginas` como array real, sem JSON serializado dentro de uma célula. Cada slot ocupado também carrega `itemId` da carta.

## Coleções não formatadas

O botão de download de uma coleção nova no editor gera um ZIP JSON pronto para `src/colecoes-nao-formatadas/`:

```text
perfil.json
inventario-cartas.json
inventario-boosters.json
inventario-kits.json
inventario-albuns.json
```

## Updates

O botão **Baixar só o update** gera:

```text
atualizacao.json
perfil.json
inventario-cartas.json
inventario-boosters.json
inventario-kits.json
inventario-albuns.json
```

Cartas e boosters novos podem vir em formato mínimo (link, quantidade, estado/idioma e `Id`); o Gerenciamento consulta a Liga antes de aplicar. Kits e álbuns usam `itemId`. Perfil, termos, kits e álbuns também são aplicados pelo atualizador.

O ZIP completo e o ZIP de update produzidos pela página não geram mais inventários CSV.
