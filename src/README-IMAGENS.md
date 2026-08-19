# Imagens e dados locais de migração

A versão atual do Vault TCG usa o Firebase como fonte oficial dos dados de contas e coleções. As pastas `src/colecoes/` e `src/colecoes-nao-formatadas/` permanecem temporariamente no projeto apenas para permitir a migração das coleções que já existiam antes do Firebase.

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

## Coleções antigas

Os arquivos `perfil.json`, `inventario-cartas.json`, `inventario-boosters.json`, `inventario-kits.json`, `inventario-produtos.json`, `inventario-albuns.json` e históricos existentes são lidos apenas para a ferramenta **Migrar uma coleção antiga** da página Entrar/Minha coleção.

Depois da migração, o inventário editável passa a viver em:

```text
collections/{uid}/cards
collections/{uid}/boosters
collections/{uid}/kits
collections/{uid}/products
collections/{uid}/albums
```

Não existe mais fluxo de baixar ZIP/update para salvar alterações do site. O editor grava diretamente no Firestore.

## Limpeza futura

Quando todos os donos das coleções antigas tiverem criado a conta Firebase e concluído a migração, as pastas locais de coleção e `src/data/legacy-claim-verifiers.json` podem ser removidas do projeto. As imagens de `public/` continuam normalmente.
