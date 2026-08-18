# Vault TCG — versão online com Firebase

O Vault TCG continua sendo um site Astro estático, mas contas, coleções, inventário, álbuns, movimentações e propostas passam a usar Firebase Authentication + Cloud Firestore. As imagens continuam sendo arquivos do diretório `public/`; o Firestore guarda apenas o caminho/URL da imagem.

## Estrutura online

- `users/{uid}`: dados privados da conta (e-mail e metadados do usuário).
- `collections/{uid}`: perfil da coleção. Toda conta possui exatamente uma coleção, mesmo que esteja vazia e privada.
- `collections/{uid}/cards`, `boosters`, `kits`, `products`, `albums`, `movements`: dados editáveis da coleção.
- `publicItems` e `publicAlbums`: espelhos usados pelos catálogos públicos. Quando uma coleção vira privada, seus espelhos públicos são removidos.
- `slugs/{slug}`: resolve a URL pública da coleção para o UID do dono.
- `proposals/{id}`: propostas enviadas por usuários autenticados.

## Rodar localmente

```bash
npm install
npm run dev
```

A configuração pública do app Web `nexustcg-ad9d3` já está incluída no cliente, portanto não é necessário criar `.env` para o projeto principal. O arquivo `.env.example` fica apenas como opção para substituir a configuração durante desenvolvimento.

## Deploy recomendado: Firebase Hosting

O projeto já contém `.firebaserc`, `firebase.json`, `firestore.rules` e `firestore.indexes.json` para o projeto `nexustcg-ad9d3`.

```bash
npm install
npx firebase login
npm run deploy:firebase
```

O comando faz o build do Astro e publica o Hosting, as regras e os índices. A configuração pública do app Web já acompanha o cliente. Authentication e Firestore continuam protegidos pelas regras e pela sessão do usuário; a API key Web não funciona como senha administrativa.

> Importante: mantenha o diretório `public/` do projeto original ao lado destes arquivos antes do build. É nele que continuam as imagens e outros assets estáticos.

## Se continuar no GitHub Pages

O workflow `.github/workflows/deploy.yml` continua disponível e o push na branch `main` faz o deploy pelo GitHub Pages. Não é mais necessário criar `PUBLIC_FIREBASE_API_KEY` nas Repository Variables; a variável continua aceita como override caso você queira trocar de projeto no futuro.

## Firebase Console

Antes de publicar, confirme:

1. Authentication → Provedores de login → **E-mail/senha** ativado.
2. Authentication → Configurações → Domínios autorizados contém o domínio usado pelo site (`localhost`, `*.web.app`/`*.firebaseapp.com` e/ou `leonn190.github.io`).
3. Publique as regras deste repositório com `npm run deploy:firebase` ou, se preferir, copie `firestore.rules` para a aba **Firestore → Regras** e clique em **Publicar**.

Não crie manualmente `users`, `collections`, `cards` etc. O próprio site cria os documentos quando a conta é criada e quando a coleção é editada.

## Fluxo da conta

Na página **Entrar** o visitante pode entrar ou criar uma conta. Criar uma conta também cria uma coleção vazia. A coleção pode permanecer privada e sem itens para quem quiser usar o Vault apenas como comprador.

Dentro do editor, as alterações são salvas automaticamente no Firestore. O botão **Salvar agora** força a sincronização. Não existe mais fluxo de baixar/enviar ZIP para atualizar a coleção.

Para enviar proposta, o comprador precisa estar autenticado. A proposta é registrada no Firestore e o fluxo existente de mensagem para WhatsApp é mantido como etapa de contato com o vendedor.

## Migrar coleções que já existiam no projeto

As coleções locais antigas continuam incluídas temporariamente apenas como fonte de migração. O dono deve:

1. Criar uma nova conta Firebase.
2. Deixar a coleção online vazia.
3. Abrir **Migrar uma coleção antiga** dentro do editor.
4. Selecionar a coleção e confirmar a senha antiga.
5. O navegador transfere cartas, boosters, kits, álbuns e movimentações para o Firestore.

As senhas antigas em texto puro foram removidas dos arquivos de perfil desta versão. A verificação de migração usa apenas verificadores derivados e não envia a senha antiga ao Firestore. Depois que todas as coleções antigas forem migradas, `src/colecoes`, `src/colecoes-nao-formatadas` e `src/data/legacy-claim-verifiers.json` podem ser removidos em uma limpeza posterior.

## Imagens

As imagens permanecem locais. Exemplos de valores salvos no Firestore:

```text
imagens/cartas/Giratina_V_186-196.webp
imagens/boosters/Evolving_Skies.webp
imagens/perfis/leon.webp
```

O arquivo real precisa existir dentro de `public/` no mesmo caminho. Não salve Base64 ou arquivos binários no Firestore.

## Backend MYP + Gmail no Render

Esta versão usa um backend separado para consultar a MYP sem abrir Chrome/Selenium e para enviar o Gmail de verificação sem expor a senha de app no frontend.

O repositório do backend é entregue no ZIP `Vault-TCG-Backend-Render.zip`. O `render.yaml` dele cria o serviço `vault-tcg-myp-api-leonn190`, portanto o frontend já usa por padrão:

```text
https://vault-tcg-myp-api-leonn190.onrender.com
```

Se você escolher outro nome/URL no Render, defina `PUBLIC_VAULT_API_URL` antes do build do Astro.

### Novo fluxo de cartas

No editor, em **Adicionar carta**, use **Preencher pela MYP**. Informe o link MYP e a API preenche nome, numeração, ano, Era, coleção, grupo, classe, tipo, imagem e cotação. O usuário escolhe Estado, Idioma e Quantidade; a Integridade recebe automaticamente um valor sugerido dentro da faixa do Estado e continua editável.

As novas referências salvas para cartas são:

- Mais Barato Certificado;
- Mais Barato Geral;
- Média Certificada;
- Média Geral;
- Mínimo = 50% do Mais Barato Certificado.

O botão **Atualizar cotações MYP** na Visão geral recota em sequência todas as cartas que possuam `linkMyp`. Registros antigos continuam legíveis para não quebrar o Firestore, mas novas cotações de cartas usam a MYP.
