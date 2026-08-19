# Firebase Functions legado · Vault TCG

Este diretório foi mantido porque fazia parte do ZIP recebido. Ele contém a Cloud Function antiga `sendVaultVerificationEmail`.

Na atualização atual, o **backend ativo para MYP, Gmail, alteração de senha e Vault+ é a API do Render** entregue no ZIP `VaultTCG-backend-render-atualizado.zip`. O frontend não faz mais fallback para o e-mail padrão do Firebase e não depende desta função para os novos fluxos.

Não remova este diretório automaticamente se ele ainda fizer parte do seu deploy Firebase, mas evite manter duas implementações concorrentes do mesmo envio.
