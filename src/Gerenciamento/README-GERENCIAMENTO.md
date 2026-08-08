# Nexus TCG — Gerenciamento

## Formato oficial

Os inventários ativos são listas de objetos JSON:

- `inventario-cartas.json`
- `inventario-boosters.json`
- `inventario-kits.json`
- `inventario-albuns.json`

CSV existe apenas como **compatibilidade de migração**. Pacotes novos gerados pelo site usam JSON.

O histórico completo não fica mais dentro de cada item. Cada coleção formatada usa:

```text
historico/
├── cartas.jsonl
└── boosters.jsonl
```

Cada linha é uma cotização independente com `itemId`, `cotacaoId`, data, preços, status, erro e `sucesso`. O inventário mantém apenas `Última cotação` quando houve sucesso. Assim, uma falha não faz o item parecer atualizado e o inventário não cresce indefinidamente.

## IDs e referências

Cartas e boosters possuem `Id` estável. Kits e álbuns referenciam os produtos por `itemId`:

```json
{
  "kind": "cards",
  "itemId": "XYP-XY124-BR-NM",
  "name": "Pikachu EX",
  "quantity": 1,
  "unitPrice": 1900.0
}
```

O nome continua existindo apenas para exibição e compatibilidade com dados antigos. Na migração, nome/link só são usados como fallback quando o pacote ainda não possui `itemId`.

## Imagens

Quando a Liga fornece uma imagem, `baixar_imagem()` devolve o nome do arquivo e esse valor passa a ser salvo em `Imagem` no JSON. Isso vale para cartas e boosters. Se a imagem já existir em `public/imagens/`, ela é reutilizada.

## Status de suspeita

O status agora guarda, além da mensagem, a **evidência** usada para chegar à conclusão: loja, preço, idioma, estado, oferta, link e valores comparados quando disponíveis.

Para cartas:

- estado melhor e mais barato no mesmo idioma;
- outro idioma mais barato, exceto quando a carta desejada já é em inglês;
- buylist acima de venda equivalente;
- suspeita leve quando existe realmente apenas uma oferta utilizável;
- aviso próprio quando ofertas foram detectadas mas parte delas falhou no OCR.

A comparação buylist × venda é feita em camadas. Primeiro procura mesmo idioma + mesmo estado. Depois aceita mesmo idioma + outro estado somente após converter o preço pelos fatores configurados. Não compara idiomas diferentes como se fossem o mesmo produto.

A coleta registra separadamente quantas ofertas foram `detectadas`, quantas foram `lidas` e quantas tiveram `falhas`. Por isso, 5 ofertas detectadas com 4 falhas de OCR não viram falsamente “só existe uma loja”.

## Estado e preço estimado

Os fatores padrão ficam em `config.json`:

- M = 1.00
- NM = 1.00
- SP = 0.90
- MP = 0.75
- HP = 0.50
- D = 0.30

A conversão entre estados usa a razão entre os fatores. O valor coletado e o valor estimado continuam separados.

## Formatação parcial e retry

Durante uma formatação existe `formatacao-em-andamento.json`.

- sucesso → item é salvo e marcado como concluído;
- falha → vai para `errosPendentes` e **não** é marcado como processado;
- ao terminar a primeira passagem, somente os itens que falharam são repetidos automaticamente;
- se ainda houver falhas, o progresso permanece e a próxima execução retoma só os pendentes.

Uma versão parcial antiga que tenha gravado `erro_cotizacao` como item concluído é corrigida ao retomar.

## Cotização parcial e retry

Durante a cotização existe `cotizacao-em-andamento.json`. O comportamento é o mesmo: falhas não entram em `processados`, são registradas no histórico com `sucesso: false` e são repetidas. Somente uma cotização bem-sucedida atualiza `Última cotação`.

É possível cotizar:

1. coleção inteira;
2. apenas cartas;
3. apenas boosters;
4. apenas itens à venda;
5. apenas itens sem preço;
6. apenas itens não cotizados há X dias.

O relatório final só é gerado quando não existem mais consultas pendentes.

## Atualização de coleção

Updates JSON podem conter:

- `atualizacao.json`;
- `perfil.json`;
- `inventario-cartas.json`;
- `inventario-boosters.json`;
- `inventario-kits.json`;
- `inventario-albuns.json`.

Novas cartas/boosters são consultadas antes de alterar o inventário. Se alguma consulta falhar, a atualização do inventário é cancelada. Quando tudo termina, perfil, cartas, boosters, kits e álbuns são promovidos na mesma transação. `updateId` impede aplicação duplicada.

Kits enviados com `operation: "upsert"` substituem a versão do mesmo `Id`; álbuns de update também representam o estado completo do álbum.

## Relatórios

Cada cotização concluída salva em `relatorios/`:

- `cotizacao-<data>.json`;
- `cotizacao-<data>.txt`.

Os relatórios continuam contendo totais, variações, buylist, média Liga, menor Liga, itens sem oferta e status por item.

## Configuração

`config.json` controla espera, tentativas, OCR, venda rápida, salvamento parcial e fatores por estado. O `main.py` instala dependências ausentes automaticamente; também é possível usar:

```bash
pip install -r requirements.txt
```
