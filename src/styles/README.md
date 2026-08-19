# Organização dos estilos

`global.css` é o ponto de entrada importado pelo `BaseLayout.astro`. Ele não deve voltar a concentrar regras: use o módulo correspondente abaixo.

- `00-foundation.css` — tokens, base, navegação, componentes globais e responsividade inicial.
- `10-catalog-interactions.css` — cartões, modais e interações do catálogo.
- `20-platform-editor.css` — estrutura multi-colecionador, cadastro e editor.
- `30-collections-albums.css` — coleções expansíveis e organizador de álbuns.
- `40-proposals.css` — propostas, checkout por WhatsApp e termos.
- `50-collection-visuals.css` — composições visuais de kits/coleções/álbuns.
- `60-collector-management.css` — personalização e blocos de inventário/análise.
- `70-refinements.css` — refinamentos incrementais de inventário e álbuns.
- `80-premium-effects.css` — efeitos visuais premium de cartas/boosters/kits.
- `90-home-experience.css` — hero da home, explorar e ajustes da vitrine.
- `95-management.css` — tabela do gerenciamento, cotização e análise avançada.
- `99-vault-plus.css` — Vault+, segurança por e-mail e modal de cotização geral.

## Regra de manutenção

Prefira alterar a regra mais recente dentro do módulo responsável em vez de adicionar um novo override no fim de outro arquivo. Variáveis locais (`--...`) devem ser usadas quando um conjunto de medidas pertence ao mesmo componente.
