# Pasta de imagens

A pasta deve continuar em `public/imagens`, exatamente assim:

```text
public/
└── imagens/
    ├── Aegislash ex_135-182.jpg
    ├── Aerodactyl EX_XY97.jpg
    └── ...
```

Durante o build, o catálogo lê os nomes reais existentes em `public/imagens` e associa primeiro os arquivos cujo nome e numeração correspondem aos dados do inventário. Como segurança, também tenta automaticamente variações com `_`, `-` ou espaço, extensões `.jpg`, `.jpeg`, `.png` e `.webp`, além de nomes sem acentos.

O caminho das imagens respeita automaticamente o `base` configurado no Astro/GitHub Pages, inclusive quando o repositório é publicado em uma subpasta.

Os dois CSVs usados pelo site estão em `src/data/` e são lidos durante o build.
