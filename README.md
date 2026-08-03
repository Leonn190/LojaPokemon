# Diva Cards — site Astro para vender cartas Pokémon

Site estático em Astro gerado a partir do arquivo `src/data/cartas.json` com 246 entradas do depósito.

## Rodar localmente

```bash
npm install
npm run dev
```

Depois abra o endereço que aparecer no terminal.

## Personalizar contato

Abra `src/config.ts` e coloque:

- `whatsappNumber`: número com DDI + DDD, só dígitos. Exemplo: `5513999999999`.
- `contactEmail`: email para pedido.
- `instagramUrl` e `mercadoLivreUrl`, se quiser mostrar esses links.

O site é estático: ele não cobra pagamento sozinho. O botão de pedido monta uma mensagem com as cartas do carrinho para WhatsApp/email.

## Publicar no GitHub Pages

1. Crie um repositório no GitHub.
2. Suba todos os arquivos deste projeto.
3. No GitHub: **Settings > Pages > Build and deployment > Source > GitHub Actions**.
4. Faça push na branch `main`.
5. A Action `.github/workflows/deploy.yml` vai instalar, buildar e publicar o site.

O `astro.config.mjs` tenta detectar automaticamente o nome do repositório no GitHub Actions para configurar o `base` correto. Se quiser forçar manualmente, configure a variável `ASTRO_BASE`, por exemplo `/nome-do-repo`.

## Aprovar e atualizar coleções

Na página **Criar coleção**, o colecionador pode iniciar do zero, importar um ZIP anterior ou entrar em uma coleção publicada. Ao terminar, ele baixa um arquivo `nome-da-colecao-vN.zip` e deve enviá-lo para `alexeidostoievsky@gmail.com`, solicitando formalmente a aprovação/atualização.

Coloque os ZIPs recebidos em `src/Coleções não formatadas/` e execute:

```bash
python src/regulador.py
```

O regulador consulta a Liga Pokémon, cria/atualiza a pasta correspondente em `src/coleções/` e salva imagens de cartas em `public/imagens/` com o padrão `Nome_Numeração`.

Para atualizar em massa os preços de uma coleção já aprovada:

```bash
python src/atualizador.py --colecao Leon19
```

Na primeira aba do Chrome, resolva a verificação da Liga se ela aparecer. Em seguida, o script processa o restante em grupos de até 10 abas. Os scripts requerem Chrome, Selenium, Pillow e ddddocr instalados no Python usado para executá-los.

## Atualizar cartas

Substitua `src/data/cartas.json` por uma versão nova do seu depósito e rode:

```bash
npm run build
```

Se passar, faça commit e push.
