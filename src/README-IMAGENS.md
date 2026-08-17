# Imagens e dados locais

A versão atual do Vault TCG usa o Firebase como fonte oficial dos dados de contas e coleções. As pastas `src/colecoes/` e `src/colecoes-nao-formatadas/` permanecem no projeto como dados locais/compatibilidade do catálogo. A migração de coleções de contas antigas pela interface foi removida.

## Imagens continuam locais

Mantenha o diretório `public/` do site original ao lado deste `src/`. Exemplos de caminhos aceitos no editor:

```text
public/imagens/...
public/imagensboosters/...
public/imagenskits/...
public/colecoes/<slug>/...
```

No Firestore é salvo somente o caminho relativo, por exemplo:

```text
imagens/Giratina_V_186-196.webp
imagensboosters/Evolving_Skies.webp
```

Não salve a imagem em Base64 dentro do Firestore.

## Coleções e dados locais

Os arquivos locais de coleção permanecem somente como dados de catálogo/compatibilidade. Não existe mais opção de migrar uma conta ou coleção antiga pela interface.

O inventário editável das contas atuais vive em:

```text
collections/{uid}/cards
collections/{uid}/boosters
collections/{uid}/kits
collections/{uid}/products
collections/{uid}/albums
collections/{uid}/movements
```

Não existe mais fluxo de baixar ZIP/update para salvar alterações do site. O editor grava diretamente no Firestore.

## Limpeza futura

A interface não oferece mais migração de contas antigas e o arquivo de verificadores legado foi removido. As imagens de `public/` continuam normalmente.
