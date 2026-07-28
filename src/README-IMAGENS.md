# Pasta de imagens

Coloque a pasta `imagens` dentro de `public`, ficando assim:

```text
public/
└── imagens/
    ├── Aegislash ex_135-182.jpg
    ├── Aerodactyl EX_XY97.jpg
    └── ...
```

Para cartas, o site procura automaticamente pelo padrão `Nome_Número.jpg`, trocando `/`, `–` e `—` por `-`, exatamente como no exemplo enviado. Também tenta `.jpeg`, `.png`, `.webp` e versões sem acentos.

Para boosters, o site tenta `Nome do booster.jpg`, `Nome do booster_Booster.jpg` e `Booster_Nome do booster.jpg`.

Os dois CSVs usados pelo site estão em `src/data/` e são lidos diretamente durante o build.
