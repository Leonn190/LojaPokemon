# Nexus TCG — Gerenciamento

## Formato atual

Os inventários ativos são JSONs contendo listas de objetos:

- `inventario-cartas.json`
- `inventario-boosters.json`
- `inventario-kits.json`
- `inventario-albuns.json`

CSVs antigos são aceitos para migração. Depois que a coleção é migrada, eles são movidos para `legado-csv/` e deixam de ser usados como inventário ativo.

### Exemplo resumido de carta

```json
{
  "Id": "PRE-014-131-BR-NM",
  "Nome": "Flareon ex",
  "Número": "014/131",
  "Coleção": "PRE",
  "Idioma": "Português (PT-BR)",
  "Estado": "NM",
  "Ano": "2026",
  "Tipo": "Ultra Rara",
  "Minimo": 80.0,
  "Venda Rapida": 104.5,
  "Menor Liga": 110.0,
  "Preço Médio Liga": 122.5,
  "Preço": 122.5,
  "Preço coletado": {
    "Menor Liga": 110.0,
    "Preço Médio Liga": 122.5,
    "Minimo": 80.0,
    "Idioma encontrado": ["Português"],
    "Estado encontrado": ["NM"],
    "é estimativa": false
  },
  "Preço estimado": {
    "Menor Liga": 110.0,
    "Preço Médio Liga": 122.5,
    "Minimo": 80.0,
    "Idioma encontrado": ["Português"],
    "Estado encontrado": ["NM"],
    "é estimativa": false
  },
  "Status": {
    "nível": "OK",
    "motivos": []
  },
  "Histórico de preços": [
    {
      "cotacaoId": "cot-20260807-123456-abcdef",
      "data": "2026-08-07T12:34:56-03:00",
      "Preço": 122.5,
      "Preço Médio Liga": 122.5,
      "Menor Liga": 110.0,
      "Minimo": 80.0
    }
  ],
  "Quantidade": 1,
  "À venda": true
}
```

## Status de suspeita

Para cartas, a cotização marca automaticamente:

- **Suspeita:** existe exemplar em estado melhor e mais barato, no mesmo idioma.
- **Suspeita:** existe exemplar equivalente em outro idioma por preço menor. Essa regra não é aplicada quando a carta desejada é em inglês.
- **Suspeita:** alguma buylist compra acima do preço pelo qual existe uma oferta de venda.
- **Suspeita leve:** só existe uma oferta compatível na cotização.

Pode haver mais de um motivo ao mesmo tempo.

## Estado e preço estimado

Os fatores padrão ficam em `config.json`:

- M = 1.00
- NM = 1.00
- SP = 0.90
- MP = 0.75
- HP = 0.50
- D = 0.30

A conversão entre quaisquer estados é feita pela razão entre os fatores. Assim, não existe mais um desconto fixo de 20% por degrau.

Exemplos:

- R$100 NM -> SP = R$90.
- R$90 SP -> NM = R$100.
- R$100 NM -> MP = R$75.

Sempre ficam separados o valor efetivamente coletado e o valor estimado para a condição desejada.

## Cotização parcial e retomada

Durante a cotização é criado `cotizacao-em-andamento.json`. Cada item concluído é salvo imediatamente. Se o processo for interrompido, a próxima execução oferece continuar exatamente dos itens restantes.

É possível cotizar:

1. coleção inteira;
2. apenas cartas;
3. apenas boosters;
4. apenas itens à venda;
5. apenas itens sem preço;
6. apenas itens não cotizados há X dias.

## Atualização de coleção

Atualização funciona de forma diferente da cotização: **não salva parcialmente**. Todas as novas cartas/boosters são consultadas em memória primeiro. Se uma delas falhar, o inventário oficial não é alterado. Quando tudo termina, os JSONs novos são promovidos por uma transação com staging/backup.

## Relatórios

Cada cotização concluída salva dois arquivos em `relatorios/`:

- `cotizacao-<data>.json` — estruturado, indicado para o site ou análises futuras;
- `cotizacao-<data>.txt` — leitura humana.

O relatório inclui totais antigos/novos, variação percentual, buylist total, total pela média da Liga, total pelo menor preço da Liga, erros, itens sem ofertas, suspeitas e a variação individual de cada item em:

- preço médio da Liga;
- menor preço da Liga;
- maior buylist (`Minimo`);
- preço configurado da coleção.

## Configuração

`config.json` controla espera, tentativas, OCR, venda rápida, salvamento parcial e fatores por estado. O `main.py` continua instalando automaticamente dependências ausentes. O `requirements.txt` também está disponível para instalação manual:

```bash
pip install -r requirements.txt
```
