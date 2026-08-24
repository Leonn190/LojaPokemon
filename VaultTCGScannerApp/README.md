# Vault TCG Scanner App

App desktop experimental para ficar na raiz do repositório do Vault TCG.

## Rodar

Recomendado: Python 3.11 ou 3.12 (EasyOCR/PyTorch costuma ter melhor compatibilidade nessas versões).

1. Rode `instalar.bat` ou `python -m pip install -r requirements.txt`.
2. Rode `main.py` ou `abrir_app.bat`.
3. Entre com a mesma conta/e-mail e senha usados no Vault TCG.

## Fluxo implementado

- Login na mesma conta Firebase do site.
- Tela inicial com `Registrar novas cartas`, `Nova cotização` (desativado) e fila local.
- Registro por `Câmera` automático; `Foto` fica desativado por enquanto.
- Vídeo à esquerda e cartas reconhecidas à direita.
- OCR + identificação + procura do link MYP rodam fora da thread da interface.
- `Resgatar cartas` fecha a câmera e abre a revisão.
- Na revisão é possível alterar idioma/estado, abrir MYP e remover cartas.
- `Salvar no app` guarda as cartas localmente, por conta, para continuar depois.
- A tela inicial mostra quantas cartas estão aguardando registro.

## Ainda não implementado (de propósito)

- Nova cotização.
- Registro final/sincronização das cartas no Firestore/site.
- Importação por foto.

## Observações

- A primeira abertura da câmera pode demorar porque o EasyOCR baixa/carrega modelos.
- É preciso internet para Firebase, Pokémon TCG API e MYP.
- Se a câmera não abrir, feche Discord/OBS/navegador ou outros apps que possam estar usando a webcam.
