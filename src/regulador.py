from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import time
import unicodedata
import argparse
import csv
import json
import tempfile
import zipfile
from collections import Counter
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

import ddddocr
from PIL import Image, ImageOps
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement


# ============================================================
# CONFIGURAÇÕES: ALTERE SOMENTE ESTES VALORES
# ============================================================

URL = (
    "https://www.ligapokemon.com.br/?view=cards/card&"
    "card=Greninja-V-Union+%284+Cartas%29%20(SWSH155-U/71)&"
    "show=1&ed=SSPR&num=SWSH155-U"
)

# Exemplos de estado: M, NM, SP, MP, HP ou D.
ESTADO = "NM"

# Pode usar BR, PT, PT-BR, Português, ING, EN ou Inglês.
IDIOMA = "BR"

# Intervalo entre tentativas enquanto a Liga exibe a verificação anti-bot.
INTERVALO_TENTATIVA = 1.5

# O perfil é persistente: cookies e verificações ficam salvos.
PASTA_PERFIL_CHROME = Path(__file__).with_name("perfil_chrome_liga")

# Salva imagens somente quando o OCR não consegue ler algum preço.
PASTA_DEBUG = Path(__file__).with_name("debug_precos")


IDIOMAS = {
    "BR": "Português",
    "PT": "Português",
    "PTBR": "Português",
    "PORTUGUES": "Português",
    "PORTUGUÊS": "Português",
    "ING": "Inglês",
    "EN": "Inglês",
    "ENGLISH": "Inglês",
    "INGLES": "Inglês",
    "INGLÊS": "Inglês",
    "ESP": "Espanhol",
    "ES": "Espanhol",
    "JAP": "Japonês",
    "JP": "Japonês",
    "KOR": "Coreano",
    "KO": "Coreano",
}

ESTADOS = {
    "MINT": "M",
    "M": "M",
    "NEARMINT": "NM",
    "NM": "NM",
    "SLIGHTLYPLAYED": "SP",
    "SP": "SP",
    "MODERATELYPLAYED": "MP",
    "MP": "MP",
    "HEAVILYPLAYED": "HP",
    "HP": "HP",
    "DAMAGED": "D",
    "D": "D",
}


class ErroLeituraPreco(RuntimeError):
    """Erro ao reconhecer os algarismos visuais de um preço."""


def chave_texto(valor: str) -> str:
    """Remove acentos, espaços e pontuação para facilitar comparações."""

    normalizado = unicodedata.normalize("NFKD", valor or "")
    sem_acentos = "".join(
        caractere
        for caractere in normalizado
        if not unicodedata.combining(caractere)
    )
    return re.sub(r"[^A-Z0-9]", "", sem_acentos.upper())


def normalizar_idioma(idioma: str) -> str:
    chave = chave_texto(idioma)
    return IDIOMAS.get(chave, idioma.strip())


def normalizar_estado(estado: str) -> str:
    chave = chave_texto(estado)
    if chave not in ESTADOS:
        raise ValueError(
            "Estado inválido. Use M, NM, SP, MP, HP ou D."
        )
    return ESTADOS[chave]


def encontrar_chrome() -> Path:
    """Localiza o chrome.exe no Windows."""

    candidatos = [
        shutil.which("chrome"),
        os.path.expandvars(
            r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"
        ),
        os.path.expandvars(
            r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"
        ),
        os.path.expandvars(
            r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
        ),
    ]

    for candidato in candidatos:
        if candidato and Path(candidato).is_file():
            return Path(candidato)

    raise FileNotFoundError(
        "Google Chrome não encontrado. Informe manualmente o caminho "
        "do chrome.exe na função encontrar_chrome()."
    )


def obter_porta_livre() -> int:
    """Obtém uma porta local livre para a conexão com o Chrome."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def esperar_chrome(porta: int, timeout: float = 30) -> None:
    """Espera o Chrome liberar a porta de depuração."""

    limite = time.monotonic() + timeout

    while time.monotonic() < limite:
        try:
            with socket.create_connection(
                ("127.0.0.1", porta),
                timeout=0.5,
            ):
                return
        except OSError:
            time.sleep(0.25)

    raise TimeoutError(
        "O Chrome abriu, mas a porta de depuração não respondeu."
    )


def abrir_navegador(url: str = URL, perfil: Path | None = None) -> tuple[webdriver.Chrome, subprocess.Popen[Any]]:
    """Abre o Chrome visivelmente e conecta o Selenium a ele."""

    chrome = encontrar_chrome()
    porta = obter_porta_livre()

    pasta_perfil = perfil or PASTA_PERFIL_CHROME
    pasta_perfil.mkdir(parents=True, exist_ok=True)

    comando_chrome = [
        str(chrome),
        f"--remote-debugging-port={porta}",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={pasta_perfil.resolve()}",
        "--window-size=1400,1000",
        "--no-first-run",
        "--no-default-browser-check",
        url,
    ]

    processo = subprocess.Popen(comando_chrome)
    esperar_chrome(porta)

    opcoes = Options()
    opcoes.debugger_address = f"127.0.0.1:{porta}"

    navegador = webdriver.Chrome(options=opcoes)
    return navegador, processo


def selecionar_aba_liga(navegador: webdriver.Chrome, url: str = URL) -> None:
    """Seleciona a aba da Liga Pokémon aberta pelo comando do Chrome."""

    for identificador in navegador.window_handles:
        navegador.switch_to.window(identificador)
        if "ligapokemon.com.br" in navegador.current_url.lower():
            return

    navegador.get(url)


def pagina_liga_pronta(navegador: webdriver.Chrome) -> bool:
    """Verifica o HTML real; não depende de uma variável JavaScript da Liga."""

    try:
        dados = navegador.execute_script(
            """
            const texto = (document.body?.innerText || '').toLowerCase();
            const titulo = (document.title || '').toLowerCase();
            const verificando =
              titulo.includes('just a moment') || titulo.includes('um momento') ||
              texto.includes('checking your browser') || texto.includes('verifique se você é humano') ||
              texto.includes('verificação de segurança');
            return {
              completa: document.readyState === 'complete',
              verificando,
              temCarta: Boolean(document.querySelector('#featuredImage, .featured-image img, .card-image img')),
              temMercado: Boolean(document.querySelector('#marketplace-stores, .marketplace-stores, .store')),
            };
            """
        )
        return bool(dados["completa"] and not dados["verificando"] and dados["temCarta"] and dados["temMercado"])
    except Exception:
        return False


def esperar_pagina(navegador: webdriver.Chrome) -> None:
    """Tenta até a página verdadeira substituir a verificação anti-bot."""

    tentativa = 1
    while True:
        if pagina_liga_pronta(navegador):
            print("Página da Liga carregada. Coletando dados do HTML...")
            return
        print(f"Página ainda não está pronta; tentando novamente em {INTERVALO_TENTATIVA:g}s (tentativa {tentativa})...")
        tentativa += 1
        time.sleep(INTERVALO_TENTATIVA)


def mostrar_todas_as_ofertas(navegador: webdriver.Chrome) -> None:
    """Pede ao código da página para revelar todos os anúncios carregados."""

    for _ in range(5):
        quantidade_antes = len(
            navegador.find_elements(
                By.CSS_SELECTOR,
                "#marketplace-stores > .store, .marketplace-stores > .store",
            )
        )

        navegador.execute_script(
            """
            if (
                window.screenfilter &&
                typeof window.screenfilter.showAll === 'function'
            ) {
                window.screenfilter.showAll(1);
            }
            """
        )

        time.sleep(0.4)

        quantidade_depois = len(
            navegador.find_elements(
                By.CSS_SELECTOR,
                "#marketplace-stores > .store, .marketplace-stores > .store",
            )
        )

        if quantidade_depois == quantidade_antes:
            break


def obter_dados_carta(navegador: webdriver.Chrome) -> dict[str, str]:
    """Obtém nome, coleção e numeração da edição selecionada."""

    dados = navegador.execute_script(
        """
        const edicoes = Array.isArray(window.cards_editions)
            ? window.cards_editions
            : [];

        const chaveSelecionada = window.param?.eddefaultKey;
        const edicao =
            edicoes.find(item => item.idkey === chaveSelecionada) ||
            edicoes[0] ||
            {};

        const imagem = document.querySelector('#featuredImage, .featured-image img, .card-image img');
        const nome =
            imagem?.getAttribute('title')?.trim() ||
            imagem?.getAttribute('alt')?.trim() ||
            document.querySelector('h1')?.textContent?.trim() ||
            '';

        const textoPagina = document.body?.innerText || '';
        const numeroHtml =
            document.querySelector('[data-card-number], .card-number, .number')?.textContent?.trim() ||
            (textoPagina.match(/(?:N[úu]mero|Number)\s*:?\s*([A-Z0-9/-]+)/i) || [])[1] || '';
        const colecaoHtml =
            document.querySelector('[data-edition-name], .edition-name, .card-edition')?.textContent?.trim() ||
            '';

        return {
            nome: nome,
            colecao: String(edicao.name || colecaoHtml).trim(),
            numeracao: String(edicao.num || numeroHtml).trim(),
            imagem: imagem?.getAttribute('src') || ''
        };
        """
    )

    if not isinstance(dados, dict):
        raise RuntimeError("Não foi possível obter os dados da carta.")

    return {
        "nome": str(dados.get("nome", "")).strip(),
        "colecao": str(dados.get("colecao", "")).strip(),
        "numeracao": str(dados.get("numeracao", "")).strip(),
        "imagem": str(dados.get("imagem", "")).strip(),
    }


def limpar_resultado_ocr(texto: str) -> str:
    """Converte confusões comuns do OCR e mantém somente algarismos."""

    substituicoes = str.maketrans(
        {
            "O": "0",
            "o": "0",
            "Q": "0",
            "I": "1",
            "i": "1",
            "l": "1",
            "L": "1",
            "Z": "2",
            "S": "5",
            "s": "5",
            "B": "8",
            "G": "6",
            "g": "9",
        }
    )

    convertido = (texto or "").translate(substituicoes)
    return "".join(caractere for caractere in convertido if caractere.isdigit())


def carregar_rgba(png: bytes) -> Image.Image:
    imagem = Image.open(BytesIO(png)).convert("RGBA")
    imagem.load()
    return imagem


def montar_variante_ocr(
    imagem_rgba: Image.Image,
    fundo: str,
    inverter: bool,
) -> bytes:
    """Amplia e melhora uma pequena imagem antes de enviá-la ao OCR."""

    base = Image.new("RGBA", imagem_rgba.size, fundo)
    base.alpha_composite(imagem_rgba)
    cinza = ImageOps.grayscale(base.convert("RGB"))
    cinza = ImageOps.autocontrast(cinza)

    if inverter:
        cinza = ImageOps.invert(cinza)

    escala = 12
    ampliada = cinza.resize(
        (max(1, cinza.width * escala), max(1, cinza.height * escala)),
        Image.Resampling.LANCZOS,
    )

    ampliada = ImageOps.expand(ampliada, border=24, fill=255)

    destino = BytesIO()
    ampliada.save(destino, format="PNG")
    return destino.getvalue()


def reconhecer_imagem(
    ocr: ddddocr.DdddOcr,
    imagem_rgba: Image.Image,
    quantidade_esperada: int,
) -> str | None:
    """Executa diferentes tratamentos e escolhe o resultado mais frequente."""

    resultados: list[str] = []

    for fundo in ("white", "black"):
        for inverter in (False, True):
            variante = montar_variante_ocr(
                imagem_rgba,
                fundo=fundo,
                inverter=inverter,
            )
            texto = ocr.classification(variante)
            digitos = limpar_resultado_ocr(str(texto))

            if len(digitos) == quantidade_esperada:
                resultados.append(digitos)

    if not resultados:
        return None

    return Counter(resultados).most_common(1)[0][0]


def chave_visual_digito(
    navegador: webdriver.Chrome,
    elemento: WebElement,
) -> str:
    """Cria uma chave para não executar OCR repetido no mesmo algarismo."""

    return str(
        navegador.execute_script(
            """
            const estilo = getComputedStyle(arguments[0]);
            return [
                estilo.backgroundImage,
                estilo.backgroundPosition,
                estilo.width,
                estilo.height
            ].join('|');
            """,
            elemento,
        )
    )


def reconhecer_digito(
    navegador: webdriver.Chrome,
    elemento: WebElement,
    ocr: ddddocr.DdddOcr,
    cache: dict[str, str],
) -> str | None:
    """Reconhece um único algarismo visual da Liga Pokémon."""

    chave = chave_visual_digito(navegador, elemento)
    if chave in cache:
        return cache[chave]

    navegador.execute_script(
        "arguments[0].scrollIntoView({block: 'center'});",
        elemento,
    )
    time.sleep(0.05)

    imagem = carregar_rgba(elemento.screenshot_as_png)
    resultado = reconhecer_imagem(
        ocr,
        imagem,
        quantidade_esperada=1,
    )

    if resultado:
        cache[chave] = resultado

    return resultado


def montar_imagem_preco(elementos: list[WebElement]) -> Image.Image:
    """Junta as capturas dos algarismos para um segundo método de OCR."""

    imagens = [carregar_rgba(elemento.screenshot_as_png) for elemento in elementos]

    altura = max(imagem.height for imagem in imagens)
    espacamento = 3
    largura = sum(imagem.width for imagem in imagens)
    largura += espacamento * max(0, len(imagens) - 1)

    resultado = Image.new("RGBA", (largura, altura), "white")

    x = 0
    for imagem in imagens:
        y = (altura - imagem.height) // 2
        resultado.alpha_composite(imagem, (x, y))
        x += imagem.width + espacamento

    return resultado


def decodificar_preco(
    navegador: webdriver.Chrome,
    oferta: WebElement,
    ocr: ddddocr.DdddOcr,
    cache: dict[str, str],
    oferta_id: str,
) -> Decimal:
    """Lê o preço visual de um anúncio e o converte em Decimal."""

    texto_oferta = (oferta.get_attribute("innerText") or "").replace("\xa0", " ")
    encontrado_texto = re.search(r"R\$\s*([0-9.]+,[0-9]{2})", texto_oferta)
    if encontrado_texto:
        return Decimal(encontrado_texto.group(1).replace(".", "").replace(",", "."))

    container = buscar_elemento_opcional(
        oferta,
        ".price-with-image, .price_with_image, [data-price-image]",
    )
    if container is None:
        raise ErroLeituraPreco(
            f"Oferta {oferta_id} não possui um preço legível; ela será ignorada."
        )
    filhos = container.find_elements(By.XPATH, "./div")

    elementos_digitos: list[WebElement] = []
    indice_separador: int | None = None

    for filho in filhos:
        classes = filho.get_attribute("class") or ""
        estilo_inline = filho.get_attribute("style") or ""

        if "imgnum-monet" in classes:
            continue

        if "v2.png" in estilo_inline:
            indice_separador = len(elementos_digitos)
            continue

        imagem_fundo = str(
            navegador.execute_script(
                "return getComputedStyle(arguments[0]).backgroundImage;",
                filho,
            )
        )

        if imagem_fundo and imagem_fundo != "none":
            elementos_digitos.append(filho)

    if not elementos_digitos:
        raise ErroLeituraPreco(
            f"Nenhum algarismo encontrado na oferta {oferta_id}."
        )

    if indice_separador is None:
        # Os preços da página usam sempre dois dígitos para os centavos.
        indice_separador = max(1, len(elementos_digitos) - 2)

    reconhecidos: list[str | None] = [
        reconhecer_digito(
            navegador,
            elemento,
            ocr,
            cache,
        )
        for elemento in elementos_digitos
    ]

    if any(digito is None for digito in reconhecidos):
        # Segunda tentativa: reconhece o preço completo de uma vez.
        imagem_preco = montar_imagem_preco(elementos_digitos)
        completo = reconhecer_imagem(
            ocr,
            imagem_preco,
            quantidade_esperada=len(elementos_digitos),
        )

        if completo:
            reconhecidos = list(completo)
        else:
            PASTA_DEBUG.mkdir(parents=True, exist_ok=True)
            arquivo_debug = PASTA_DEBUG / f"preco_{oferta_id}.png"
            imagem_preco.convert("RGB").save(arquivo_debug)

            raise ErroLeituraPreco(
                "Não foi possível reconhecer o preço da oferta "
                f"{oferta_id}. A imagem foi salva em: {arquivo_debug}"
            )

    digitos = "".join(str(digito) for digito in reconhecidos)
    parte_inteira = digitos[:indice_separador]
    parte_decimal = digitos[indice_separador:]

    if not parte_inteira or len(parte_decimal) != 2:
        raise ErroLeituraPreco(
            f"Preço reconhecido em formato inesperado na oferta {oferta_id}: "
            f"{parte_inteira},{parte_decimal}"
        )

    return Decimal(f"{parte_inteira}.{parte_decimal}")


def buscar_elemento_opcional(
    raiz: WebElement,
    seletor: str,
) -> WebElement | None:
    try:
        return raiz.find_element(By.CSS_SELECTOR, seletor)
    except NoSuchElementException:
        return None


def obter_ofertas(
    navegador: webdriver.Chrome,
    idioma_desejado: str,
    estado_desejado: str,
) -> list[dict[str, Any]]:
    """Filtra os anúncios e reconhece os preços correspondentes."""

    elementos = navegador.find_elements(
        By.CSS_SELECTOR,
        "#marketplace-stores > .store, .marketplace-stores > .store",
    )

    if not elementos:
        return []

    ocr = ddddocr.DdddOcr(show_ad=False, beta=True)
    cache_digitos: dict[str, str] = {}
    ofertas: list[dict[str, Any]] = []

    chave_idioma_desejado = chave_texto(idioma_desejado)

    for oferta in elementos:
        idioma_elemento = buscar_elemento_opcional(
            oferta,
            ".infos-quality-and-language.desktop-only .lang img[title]",
        )
        estado_elemento = buscar_elemento_opcional(
            oferta,
            ".infos-quality-and-language.desktop-only .quality",
        )

        if idioma_elemento is None or estado_elemento is None:
            idioma_elemento = buscar_elemento_opcional(
                oferta,
                ".infos-quality-and-language .lang img[title]",
            )
            estado_elemento = buscar_elemento_opcional(
                oferta,
                ".infos-quality-and-language .quality",
            )

        if idioma_elemento is None or estado_elemento is None:
            continue

        idioma_oferta = (
            idioma_elemento.get_attribute("title") or ""
        ).strip()
        estado_oferta = (
            estado_elemento.get_attribute("textContent") or ""
        ).strip().upper()

        if chave_texto(idioma_oferta) != chave_idioma_desejado:
            continue

        if estado_oferta != estado_desejado:
            continue

        identificador_dom = oferta.get_attribute("id") or ""
        correspondencia_oferta = re.search(r"(\d+)$", identificador_dom)
        oferta_id = (
            correspondencia_oferta.group(1)
            if correspondencia_oferta
            else identificador_dom
        )

        link_elemento = buscar_elemento_opcional(oferta, ".link-store")
        link_loja = (
            link_elemento.get_attribute("href")
            if link_elemento is not None
            else ""
        )

        correspondencia_loja = re.search(r"[?&]id=(\d+)", link_loja or "")
        loja_id = correspondencia_loja.group(1) if correspondencia_loja else ""

        nome_loja = navegador.execute_script(
            """
            const id = String(arguments[0]);
            return window.cards_stores?.[id]?.lj_name || '';
            """,
            loja_id,
        )

        try:
            preco = decodificar_preco(
                navegador=navegador,
                oferta=oferta,
                ocr=ocr,
                cache=cache_digitos,
                oferta_id=oferta_id,
            )
        except (ErroLeituraPreco, NoSuchElementException) as erro:
            print(f"  Oferta {oferta_id} ignorada: {erro}")
            continue

        ofertas.append(
            {
                "preco": preco,
                "idioma": idioma_oferta,
                "estado": estado_oferta,
                "loja": str(nome_loja or "").strip(),
                "link_loja": str(link_loja or "").strip(),
                "oferta_id": oferta_id,
            }
        )

    return ofertas


def formatar_reais(valor: Decimal) -> str:
    formatado = f"{valor:,.2f}"
    formatado = formatado.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatado}"


def consultar(url: str = URL, idioma: str = IDIOMA, estado: str = ESTADO, perfil: Path | None = None) -> dict[str, Any]:
    """Executa a consulta e devolve os dados da oferta mais barata."""

    estado_desejado = normalizar_estado(estado)
    idioma_desejado = normalizar_idioma(idioma)

    navegador: webdriver.Chrome | None = None
    processo: subprocess.Popen[Any] | None = None

    try:
        print("Abrindo o Chrome...")
        navegador, processo = abrir_navegador(url, perfil)
        selecionar_aba_liga(navegador, url)

        print("Aguardando a página verdadeira da Liga Pokémon...")
        esperar_pagina(navegador)
        mostrar_todas_as_ofertas(navegador)

        dados_carta = obter_dados_carta(navegador)
        ofertas = obter_ofertas(
            navegador=navegador,
            idioma_desejado=idioma_desejado,
            estado_desejado=estado_desejado,
        )

        if not ofertas:
            raise LookupError(
                "Nenhuma oferta encontrada para "
                f"idioma={idioma_desejado} e estado={estado_desejado}."
            )

        menor = min(ofertas, key=lambda oferta: oferta["preco"])

        return {
            **dados_carta,
            **menor,
        }

    finally:
        if navegador is not None:
            try:
                navegador.quit()
            except Exception:
                pass

        if processo is not None and processo.poll() is None:
            try:
                processo.terminate()
            except Exception:
                pass


RAIZ_SRC = Path(__file__).resolve().parent
PASTA_COLECOES_NAO_FORMATADAS = RAIZ_SRC / "Coleções não formatadas"
PASTA_COLECOES_FORMATADAS = RAIZ_SRC / "coleções"
PASTA_IMAGENS_PUBLICAS = RAIZ_SRC.parent / "public" / "imagens"

COLUNAS_CARTAS = [
    "Nome", "Numeração", "Coleção", "Idioma", "Estado", "Ano",
    "Link Liga", "Preço Mais Baixo Liga", "Imagem", "Preço", "Quantidade", "À venda",
]
COLUNAS_BOOSTERS = ["Coleção", "Link Liga", "Preço Mais Baixo Liga", "Preço", "Quantidade", "À venda"]
COLUNAS_KITS = ["Nome", "Descrição", "Conteúdo", "Quantidade", "Preço", "À venda"]


def texto_csv(valor: Any) -> str:
    return str(valor or "").strip()


def ler_csv(caminho: Path) -> list[dict[str, str]]:
    if not caminho.is_file():
        return []
    with caminho.open("r", encoding="utf-8-sig", newline="") as arquivo:
        return [dict(linha) for linha in csv.DictReader(arquivo)]


def escrever_csv(caminho: Path, colunas: list[str], linhas: list[dict[str, Any]]) -> None:
    with caminho.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=colunas, extrasaction="ignore")
        escritor.writeheader()
        escritor.writerows(linhas)


def nome_arquivo(valor: str) -> str:
    normalizado = unicodedata.normalize("NFKD", valor)
    normalizado = "".join(c for c in normalizado if not unicodedata.combining(c))
    return re.sub(r'[\\/:*?"<>|]+', "-", normalizado).strip(" .") or "imagem"


def baixar_imagem(url: str, nome: str) -> str:
    """Salva a imagem da carta em public/imagens e devolve seu nome."""

    if not url:
        return ""
    PASTA_IMAGENS_PUBLICAS.mkdir(parents=True, exist_ok=True)
    url = urljoin("https://www.ligapokemon.com.br/", url)
    extensao = Path(urlparse(url).path).suffix.lower()
    if extensao not in {".jpg", ".jpeg", ".png", ".webp", ".avif"}:
        extensao = ".jpg"
    destino = PASTA_IMAGENS_PUBLICAS / f"{nome_arquivo(nome)}{extensao}"
    try:
        requisicao = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(requisicao, timeout=45) as resposta:
            destino.write_bytes(resposta.read())
        return destino.name
    except Exception as erro:
        print(f"  Aviso: não foi possível baixar a imagem: {erro}")
        return ""


def consultar_booster(url: str, perfil: Path | None = None) -> dict[str, Any]:
    """Lê nome/coleção e o menor preço sem filtrar idioma ou estado."""

    navegador: webdriver.Chrome | None = None
    processo: subprocess.Popen[Any] | None = None
    try:
        navegador, processo = abrir_navegador(url, perfil)
        selecionar_aba_liga(navegador, url)
        esperar_pagina(navegador)
        mostrar_todas_as_ofertas(navegador)
        dados = obter_dados_carta(navegador)
        ocr = ddddocr.DdddOcr(show_ad=False, beta=True)
        cache: dict[str, str] = {}
        precos: list[Decimal] = []
        for indice, oferta in enumerate(navegador.find_elements(By.CSS_SELECTOR, "#marketplace-stores > .store, .marketplace-stores > .store")):
            try:
                precos.append(decodificar_preco(navegador, oferta, ocr, cache, str(indice)))
            except Exception:
                continue
        return {**dados, "preco": min(precos) if precos else None}
    finally:
        if navegador is not None:
            try:
                navegador.quit()
            except Exception:
                pass
        if processo is not None and processo.poll() is None:
            try:
                processo.terminate()
            except Exception:
                pass


def encontrar_raiz_colecao(pasta: Path) -> Path | None:
    if (pasta / "perfil.json").is_file():
        return pasta
    for perfil in pasta.rglob("perfil.json"):
        return perfil.parent
    return None


def formatar_colecao(origem: Path) -> Path:
    """Converte uma coleção enviada para a pasta usada pelo site."""

    perfil_origem = origem / "perfil.json"
    if not perfil_origem.is_file():
        raise FileNotFoundError(f"perfil.json não encontrado em {origem}")
    perfil = json.loads(perfil_origem.read_text(encoding="utf-8-sig"))
    identificador = re.sub(
        r"[^A-Za-z0-9_-]+", "-", str(perfil.get("collectionId") or origem.name)
    ).strip("-") or "colecao"
    destino = PASTA_COLECOES_FORMATADAS / identificador
    destino.mkdir(parents=True, exist_ok=True)
    (destino / "perfil.json").write_text(json.dumps(perfil, ensure_ascii=False, indent=2), encoding="utf-8")
    perfil_chrome = PASTA_PERFIL_CHROME

    cartas_formatadas: list[dict[str, Any]] = []
    for indice, linha in enumerate(ler_csv(origem / "inventario-cartas.csv"), start=1):
        link = texto_csv(linha.get("Link Liga"))
        idioma = texto_csv(linha.get("Idioma"))
        estado = texto_csv(linha.get("Estado"))
        print(f"Carta {indice}: consultando Liga Pokémon...")
        dados: dict[str, Any] = {}
        try:
            dados = consultar(link, idioma, estado, perfil_chrome)
        except Exception as erro:
            print(f"  Aviso: consulta não concluída ({erro}). Mantendo os dados enviados.")
        nome = texto_csv(dados.get("nome") or linha.get("Nome"))
        numeracao = texto_csv(dados.get("numeracao") or linha.get("Numeração") or linha.get("Número"))
        imagem = baixar_imagem(texto_csv(dados.get("imagem")), f"{nome}_{numeracao}")
        menor = dados.get("preco")
        cartas_formatadas.append({
            "Nome": nome,
            "Numeração": numeracao,
            "Coleção": texto_csv(dados.get("colecao") or linha.get("Coleção")),
            "Idioma": idioma,
            "Estado": estado,
            "Ano": texto_csv(linha.get("Ano")),
            "Link Liga": link,
            "Preço Mais Baixo Liga": formatar_reais(menor) if isinstance(menor, Decimal) else "",
            "Imagem": imagem,
            "Preço": texto_csv(linha.get("Preço")),
            "Quantidade": texto_csv(linha.get("Quantidade")) or "1",
            "À venda": texto_csv(linha.get("À venda") or linha.get("Venda")) or "Sim",
        })

    boosters_formatados: list[dict[str, Any]] = []
    for indice, linha in enumerate(ler_csv(origem / "inventario-boosters.csv"), start=1):
        link = texto_csv(linha.get("Link Liga"))
        print(f"Booster {indice}: consultando Liga Pokémon...")
        dados: dict[str, Any] = {}
        try:
            dados = consultar_booster(link, perfil_chrome)
        except Exception as erro:
            print(f"  Aviso: consulta não concluída ({erro}). Mantendo os dados enviados.")
        menor = dados.get("preco")
        boosters_formatados.append({
            "Coleção": texto_csv(dados.get("colecao") or dados.get("nome") or linha.get("Coleção") or linha.get("Tipo de pacote")),
            "Link Liga": link,
            "Preço Mais Baixo Liga": formatar_reais(menor) if isinstance(menor, Decimal) else "",
            "Preço": texto_csv(linha.get("Preço")),
            "Quantidade": texto_csv(linha.get("Quantidade")) or "1",
            "À venda": texto_csv(linha.get("À venda") or linha.get("Venda")) or "Sim",
        })

    kits = ler_csv(origem / "inventario-kits.csv")
    escrever_csv(destino / "inventario-cartas.csv", COLUNAS_CARTAS, cartas_formatadas)
    escrever_csv(destino / "inventario-boosters.csv", COLUNAS_BOOSTERS, boosters_formatados)
    escrever_csv(destino / "inventario-kits.csv", COLUNAS_KITS, kits)
    return destino


def regular_pasta(entrada: Path = PASTA_COLECOES_NAO_FORMATADAS) -> list[Path]:
    """Formata todas as pastas/ZIPs entregues em Coleções não formatadas."""

    entrada.mkdir(parents=True, exist_ok=True)
    resultados: list[Path] = []
    for item in entrada.iterdir():
        if item.is_dir():
            raiz = encontrar_raiz_colecao(item)
            if raiz:
                resultados.append(formatar_colecao(raiz))
        elif item.suffix.lower() == ".zip":
            with tempfile.TemporaryDirectory(prefix="loja-pokemon-") as temporario:
                with zipfile.ZipFile(item) as arquivo:
                    arquivo.extractall(temporario)
                raiz = encontrar_raiz_colecao(Path(temporario))
                if raiz:
                    resultados.append(formatar_colecao(raiz))
                else:
                    print(f"Ignorado: {item.name} não possui perfil.json.")
    return resultados


def main() -> None:
    try:
        resultado = consultar()
    except Exception as erro:
        print(f"\nErro: {erro}")
        raise SystemExit(1)

    print("\n========== RESULTADO ==========")
    print(f"Nome: {resultado['nome']}")
    print(f"Coleção: {resultado['colecao']}")
    print(f"Numeração: {resultado['numeracao']}")
    print(f"Idioma: {resultado['idioma']}")
    print(f"Estado: {resultado['estado']}")
    print(f"Menor preço: {formatar_reais(resultado['preco'])}")

    if resultado.get("loja"):
        print(f"Loja: {resultado['loja']}")

    if resultado.get("link_loja"):
        print(f"Link da oferta: {resultado['link_loja']}")


if __name__ == "__main__":
    argumentos = argparse.ArgumentParser(
        description="Formata coleções enviadas e consulta a Liga Pokémon."
    )
    argumentos.add_argument(
        "--consultar",
        action="store_true",
        help="Mantém o modo antigo: consulta a URL configurada no início do arquivo.",
    )
    argumentos.add_argument(
        "--entrada",
        type=Path,
        default=PASTA_COLECOES_NAO_FORMATADAS,
        help="Pasta com ZIPs ou pastas ainda não formatadas.",
    )
    opcoes = argumentos.parse_args()
    if opcoes.consultar:
        main()
    else:
        saidas = regular_pasta(opcoes.entrada)
        if not saidas:
            print(f"Nenhuma coleção encontrada em: {opcoes.entrada}")
        else:
            for saida in saidas:
                print(f"Coleção formatada em: {saida}")
