# Nexus TCG — Gerenciamento

## Formato oficial

Os inventários ativos são listas de objetos JSON:

- `inventario-cartas.json`
- `inventario-boosters.json`
- `inventario-kits.json`
- `inventario-produtos.json`
- `inventario-albuns.json`

CSV existe apenas como **compatibilidade de migração**. Pacotes novos gerados pelo site usam JSON.

O histórico completo não fica mais dentro de cada item. Cada coleção formatada usa:

```text
historico/
├── cartas.jsonl
└── boosters.jsonl
```

Cada linha é uma cotização independente com `itemId`, `cotacaoId`, data, preços, status, erro e `sucesso`. O histórico de mercado guarda `Minimo Certeiro`, `Minimo`, `Menor Liga`, `Segundo Menor Liga`, `Terceiro Menor Liga`, `Media Liga`, `Mediana Liga`, `Venda Rapida` e os contadores de compradores/vendedores; o campo `Preço` não entra no histórico porque é uma escolha manual do colecionador. O inventário mantém apenas `Última cotação` quando houve sucesso. Assim, uma falha não faz o item parecer atualizado e o inventário não cresce indefinidamente.

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

A comparação buylist × venda é feita em camadas. Primeiro procura idioma + estado compatíveis. Português e inglês podem ser usados como equivalentes quando a variante exata não existe, sem fator de idioma. Se o estado exato não existe, a tabela de condição é aplicada. Quando a maior buylist ultrapassa o menor marketplace, a variante física também é conferida (por exemplo, Foil contra Foil), evitando misturar uma oferta Normal com uma carta Foil.

A coleta registra separadamente quantas ofertas foram `detectadas`, quantas foram `lidas` e quantas tiveram `falhas`. Por isso, 5 ofertas detectadas com 4 falhas de OCR não viram falsamente “só existe uma loja”.

## Estado e preço estimado

Os fatores padrão ficam em `config.json`:

- M = 1.00
- NM = 1.00
- SP = 0.90
- MP = 0.75
- HP = 0.50
- D = 0.30

A conversão entre estados usa a diferença direta entre os fatores. Exemplo: SP = 0,90 para NM = 1,00 resulta em **+10%** sobre o preço SP. O valor coletado e o valor estimado continuam separados.

As referências calculadas pelo gerenciador são:

- `Minimo Certeiro` = `Menor Liga × 0,60`;
- `Minimo` = maior buylist compatível;
- `Menor Liga` = menor oferta compatível;
- `Segundo Menor Liga` e `Terceiro Menor Liga` = próximas ofertas compatíveis, úteis para medir profundidade;
- `Media Liga` = média das ofertas compatíveis;
- `Mediana Liga` = mediana das ofertas compatíveis;
- `Venda Rapida` = `Menor Liga × 0,95`;
- `Vendedores Geral` / `Compradores Geral` = participantes encontrados no mercado inteiro;
- `Vendedores Específicos` / `Compradores Específicos` = participantes da mesma combinação de idioma + estado da carta (para boosters, o próprio produto).

`Preço` nunca é recalculado pelo gerenciador: somente o usuário altera esse campo.

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
- `inventario-produtos.json`;
- `inventario-albuns.json`.

Novas cartas/boosters são consultadas antes de alterar o inventário. Se alguma consulta falhar, a atualização do inventário é cancelada. Quando tudo termina, perfil, cartas, boosters, kits, produtos e álbuns são promovidos na mesma transação. `updateId` impede aplicação duplicada.

Kits enviados com `operation: "upsert"` substituem a versão do mesmo `Id`; álbuns de update também representam o estado completo do álbum. Edições de usuário em cartas/boosters podem usar `operation: "patch"`. Campos cadastrais e links também podem ser corrigidos; se link da Liga, idioma ou estado mudar, as referências de mercado atuais são invalidadas e o item passa a exigir nova cotização.

## Relatórios

Cada cotização concluída salva em `relatorios/`:

- `cotizacao-<data>.json`;
- `cotizacao-<data>.txt`.

Os relatórios contêm totais e variações das referências de mercado, incluindo média e mediana, além de itens sem oferta, erros e status por item.

## Configuração

`config.json` controla espera, tentativas, OCR, venda rápida, salvamento parcial e fatores por estado. O `main.py` instala dependências ausentes automaticamente; também é possível usar:

```bash
pip install -r requirements.txt
```

## Modos de velocidade da Liga

Toda operação que consulta a Liga (formatação, atualização de novos itens e cotização) agora pergunta o modo de execução:

1. Conservador — 1 worker / 1 Chrome
2. Normal — 2 workers / 2 Chromes
3. Rápido — 3 workers / 3 Chromes
4. Turbo — 4 workers / 4 Chromes
5. Super Turbo — 5 workers / 5 Chromes

Cada worker possui Chrome, WebDriver, perfil temporário, OCR e cache próprios. Os workers coletam em paralelo, mas os inventários/históricos continuam sendo gravados pela thread principal para evitar corrupção de JSON.

### Otimizações adicionais

- OCR inicializado uma única vez por worker e cache de dígitos reaproveitado entre páginas.
- A mesma aba do Chrome é reutilizada pelo worker em vez de abrir/fechar uma aba para cada marketplace/buylist.
- A espera fixa após o carregamento foi substituída por espera adaptativa de estabilidade das ofertas.
- Workers começam com pequeno `jitter` para não disparar todos os acessos no mesmo instante.
- Falhas são repetidas somente para os itens que falharam.

### Progresso e relatórios

Durante as consultas o terminal mostra, por item: worker, duração, menor/2º/3º preço, média, mediana, buylist, vendedores/compradores e, na cotização, variação desde a cotização anterior. Também mostra barra de progresso, percentual, tempo decorrido e ETA.

Ao final são gravados relatórios JSON e TXT em `relatorios/`, com modo, quantidade de workers, duração, quantidade de itens, sucessos/erros e detalhes por item. Cotizações retomadas acumulam as métricas das execuções até a conclusão.
