# Vault TCG Scanner App

App desktop do Vault TCG para reconhecer cartas Pokémon e cotizar a coleção usando a MYP.

## Instalação

Recomendado: Python 3.11 ou 3.12.

1. Execute `instalar.bat`.
2. O instalador cria uma `.venv` própria do app, evitando conflitos com bibliotecas do Python já instaladas no computador.
3. Depois execute `abrir_app.bat`.
4. Entre com a mesma conta Firebase usada no site Vault TCG.

## Fluxo atual

### Login
- Login por e-mail/senha na mesma conta Firebase do site.
- O token autenticado é reutilizado para ler e atualizar somente a coleção do próprio usuário no Firestore.
- Se o token expirar, o app tenta renová-lo usando o refresh token.

### Registrar novas cartas
Há dois métodos:

**Câmera**
- Abre a webcam.
- Detecta cartas automaticamente, sem botão de escanear.
- Faz OCR da numeração.
- Consulta a Pokémon TCG API para identificar a carta.
- Compara candidatos visualmente.
- Procura o link correto do produto na MYP.
- Mostra as cartas reconhecidas ao lado da câmera.
- `Resgatar cartas` leva para a tela de revisão.

**Foto**
- Aceita JPG, JPEG, PNG, WEBP e BMP.
- Permite selecionar uma ou várias fotos.
- Procura até 8 regiões de carta por imagem.
- Usa exatamente o mesmo pipeline de OCR, identificação e procura da MYP da câmera.
- Mostra progresso e as cartas já encontradas.
- Ao terminar, as cartas podem ser levadas para a mesma revisão do scanner por câmera.

### Revisão / fila local
- Ajuste de idioma e estado.
- Visualização dos detalhes da carta.
- Abertura do produto na MYP.
- Remoção de leituras indesejadas.
- Salvamento em uma fila local separada por usuário.

O registro final das novas cartas no Firestore continua separado; a fila local evita criar registros errados antes dessa etapa.

### Nova cotização
- Carrega diretamente `collections/{uid}/cards` do Firestore usando a sessão do usuário.
- Mostra nome, número, coleção, estado, quantidade, preço atual e se existe link MYP.
- Permite busca e seleção das cartas que serão cotizadas.
- A consulta MYP roda diretamente no computador usando a mesma lógica HTTP/HTML de `src/Gerenciamento/teste_myp.py`.
- Para cada carta, o app prioriza o menor anúncio visível do mesmo estado (`NM`, `SP`, `MP`, `HP` ou `D`). Se não houver anúncio daquele estado, usa o menor anúncio visível geral.
- A tela mostra progresso, sucessos, falhas e o valor cotado da seleção.
- A cotização primeiro fica somente em prévia.
- O botão `Salvar cotações no Vault` grava os novos campos MYP e o histórico no Firestore.
- O campo de preço manual da carta não é sobrescrito.

## Dados de cotização gravados

O app atualiza campos como:
- `pricingSource = MYP`
- `pricingSchemaVersion = 3`
- `cheapestGeneralPrice`
- `averageGeneralPrice`
- `minimumPrice`
- contagem de ofertas visíveis
- data/status da última cotização
- `priceHistory`

A leitura de `teste_myp.py` não inventa a semântica dos quatro indicadores-resumo quando a página da MYP não os rotula claramente. O app usa as ofertas realmente visíveis e o estado físico da carta como referência principal.

## Dependências principais

- CustomTkinter
- OpenCV
- EasyOCR
- Pillow
- Requests
- BeautifulSoup4
- NumPy

É preciso internet para autenticação Firebase, Firestore, Pokémon TCG API e MYP.
