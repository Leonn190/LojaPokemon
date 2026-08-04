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
import hashlib
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

# O Chrome usa um perfil temporário por execução. Ele é apagado ao encerrar.

# Salva imagens somente quando o OCR não consegue ler algum preço.
PASTA_DEBUG = Path(__file__).with_name("debug_precos")


IDIOMAS = {
    "BR": "Português",
    "PT": "Português",
    "PTBR": "Português",
    "PORTUGUES": "Português",
    "PORTUGUÊS": "Português",
    "PORTUGUESPTBR": "Português",
    "PORTUGUESBRASIL": "Português",
    "PORTUGUESBRASILEIRO": "Português",
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


def abrir_navegador(
    url: str,
    pasta_perfil_temporario: Path,
) -> tuple[webdriver.Chrome, subprocess.Popen[Any]]:
    """Abre um único Chrome com perfil descartável e conecta o Selenium."""

    chrome = encontrar_chrome()
    porta = obter_porta_livre()
    pasta_perfil_temporario.mkdir(parents=True, exist_ok=True)

    comando_chrome = [
        str(chrome),
        f"--remote-debugging-port={porta}",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={pasta_perfil_temporario.resolve()}",
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
        return bool(dados["completa"] and not dados["verificando"] and dados["temCarta"])
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
        r"""
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
        const cartaGlobal = window.card || window.cards_card || window.card_data || {};
        const anoHtml =
            document.querySelector('[data-release-year], .release-year, .card-year')?.textContent?.trim() ||
            (textoPagina.match(/(?:Ano|Year)\s*:?\s*(19\d{2}|20\d{2})/i) || [])[1] || '';
        const tipoHtml =
            document.querySelector('[data-rarity], .rarity, .card-rarity')?.textContent?.trim() || '';
        const ano = edicao.year || edicao.release_year || edicao.releaseYear || cartaGlobal.year || anoHtml;
        const tipo = edicao.rarity || edicao.rarity_name || edicao.rarityName || cartaGlobal.rarity || tipoHtml;

        return {
            nome: nome,
            colecao: String(edicao.name || colecaoHtml).trim(),
            numeracao: String(edicao.num || numeroHtml).trim(),
            ano: String(ano || '').trim(),
            tipo: String(tipo || '').trim(),
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
        "ano": str(dados.get("ano", "")).strip(),
        "tipo": str(dados.get("tipo", "")).strip(),
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

    chave_idioma_desejado = chave_texto(normalizar_idioma(idioma_desejado))

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

        if chave_texto(normalizar_idioma(idioma_oferta)) != chave_idioma_desejado:
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


def formatar_decimal_csv(valor: Decimal | None) -> str:
    if valor is None:
        return ""
    return f"{valor:.2f}".replace(".", ",")


class SessaoLiga:
    """Mantém um Chrome aberto e usa abas temporárias para todas as consultas."""

    def __init__(self) -> None:
        self._pasta_perfil_temporario: Path | None = None
        self.navegador: webdriver.Chrome | None = None
        self.processo: subprocess.Popen[Any] | None = None
        self.aba_base: str | None = None

    def __enter__(self) -> "SessaoLiga":
        print("Abrindo um único Chrome para toda a coleta...")
        self._pasta_perfil_temporario = Path(tempfile.mkdtemp(prefix="nexus-tcg-chrome-"))
        self.navegador, self.processo = abrir_navegador(
            "about:blank",
            self._pasta_perfil_temporario,
        )
        self.aba_base = self.navegador.current_window_handle
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.fechar()

    def _exigir_navegador(self) -> webdriver.Chrome:
        if self.navegador is None:
            raise RuntimeError("A sessão da Liga ainda não foi aberta.")
        return self.navegador

    def _abrir_aba(self, url: str) -> str:
        navegador = self._exigir_navegador()
        if self.aba_base in navegador.window_handles:
            navegador.switch_to.window(self.aba_base)
        elif navegador.window_handles:
            self.aba_base = navegador.window_handles[0]
            navegador.switch_to.window(self.aba_base)
        else:
            raise RuntimeError("O Chrome ficou sem nenhuma aba aberta.")

        navegador.switch_to.new_window("tab")
        identificador = navegador.current_window_handle
        navegador.get(url)
        return identificador

    def _fechar_aba(self, identificador: str) -> None:
        navegador = self._exigir_navegador()
        try:
            if identificador in navegador.window_handles:
                navegador.switch_to.window(identificador)
                if len(navegador.window_handles) > 1:
                    navegador.close()
        finally:
            handles = navegador.window_handles
            if not handles:
                raise RuntimeError("O Chrome ficou sem abas após a consulta.")
            if self.aba_base not in handles:
                self.aba_base = handles[0]
            navegador.switch_to.window(self.aba_base)

    def consultar_carta(self, url: str, idioma: str, estado: str) -> dict[str, Any]:
        estado_desejado = normalizar_estado(estado)
        idioma_desejado = normalizar_idioma(idioma)
        navegador = self._exigir_navegador()
        aba = self._abrir_aba(url)
        try:
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
                print(
                    "  Nenhuma oferta encontrada para "
                    f"idioma={idioma_desejado} e estado={estado_desejado}; "
                    "os dados da carta serão mantidos sem preço da Liga."
                )
                return {
                    **dados_carta,
                    "preco": None,
                    "idioma": idioma_desejado,
                    "estado": estado_desejado,
                    "loja": "",
                    "link_loja": "",
                }
            return {**dados_carta, **min(ofertas, key=lambda oferta: oferta["preco"])}
        finally:
            self._fechar_aba(aba)

    def consultar_booster(self, url: str) -> dict[str, Any]:
        navegador = self._exigir_navegador()
        aba = self._abrir_aba(url)
        try:
            print("Aguardando a página verdadeira da Liga Pokémon...")
            esperar_pagina(navegador)
            mostrar_todas_as_ofertas(navegador)
            dados = obter_dados_carta(navegador)
            ocr = ddddocr.DdddOcr(show_ad=False, beta=True)
            cache: dict[str, str] = {}
            precos: list[Decimal] = []
            seletor = "#marketplace-stores > .store, .marketplace-stores > .store"
            for indice, oferta in enumerate(navegador.find_elements(By.CSS_SELECTOR, seletor)):
                try:
                    precos.append(decodificar_preco(navegador, oferta, ocr, cache, str(indice)))
                except Exception:
                    continue
            return {**dados, "preco": min(precos) if precos else None}
        finally:
            self._fechar_aba(aba)

    def fechar(self) -> None:
        if self.navegador is not None:
            try:
                self.navegador.quit()
            except Exception:
                pass
            self.navegador = None
        if self.processo is not None and self.processo.poll() is None:
            try:
                self.processo.terminate()
                self.processo.wait(timeout=5)
            except Exception:
                try:
                    self.processo.kill()
                except Exception:
                    pass
        self.processo = None
        if self._pasta_perfil_temporario is not None:
            for _ in range(5):
                shutil.rmtree(self._pasta_perfil_temporario, ignore_errors=True)
                if not self._pasta_perfil_temporario.exists():
                    break
                time.sleep(0.4)
            self._pasta_perfil_temporario = None


def consultar(
    url: str = URL,
    idioma: str = IDIOMA,
    estado: str = ESTADO,
    sessao: SessaoLiga | None = None,
) -> dict[str, Any]:
    """Consulta uma carta usando a sessão existente ou uma sessão descartável."""

    if sessao is not None:
        return sessao.consultar_carta(url, idioma, estado)
    with SessaoLiga() as nova_sessao:
        return nova_sessao.consultar_carta(url, idioma, estado)


def consultar_booster(
    url: str,
    sessao: SessaoLiga | None = None,
) -> dict[str, Any]:
    """Consulta um booster usando a sessão existente ou uma sessão descartável."""

    if sessao is not None:
        return sessao.consultar_booster(url)
    with SessaoLiga() as nova_sessao:
        return nova_sessao.consultar_booster(url)


RAIZ_SRC = Path(__file__).resolve().parent
PASTA_COLECOES_NAO_FORMATADAS = RAIZ_SRC / "Coleções não formatadas"
PASTA_COLECOES_FORMATADAS = RAIZ_SRC / "coleções"
PASTA_IMAGENS_PUBLICAS = RAIZ_SRC.parent / "public" / "imagens"
ARQUIVO_ATUALIZACAO = "atualizacao.json"

# Mesma estrutura usada pela coleção Leon19.
COLUNAS_CARTAS = [
    "Nome", "Número", "Coleção", "Idioma", "Estado", "Ano", "Tipo",
    "Link Liga", "Link MYP", "Link Cardmarket", "Link Tcgplayer",
    "Link PriceCharting", "Minimo", "Venda Rapida", "Menor Liga", "Preço",
    "Quantidade",
]
COLUNAS_BOOSTERS = [
    "Tipo de pacote", "Quantidade", "Preço mínimo", "Venda rápida",
    "Preço Liga mais barato", "Preço",
]
COLUNAS_KITS = ["Nome", "Descrição", "Preço", "Quantidade", "Conteúdo", "Imagem"]


def texto_csv(valor: Any) -> str:
    return "" if valor is None else str(valor).strip()


def primeiro_valor(linha: dict[str, Any], *nomes: str) -> str:
    for nome in nomes:
        valor = texto_csv(linha.get(nome))
        if valor:
            return valor
    return ""


def ler_csv(caminho: Path) -> list[dict[str, str]]:
    if not caminho.is_file():
        return []
    with caminho.open("r", encoding="utf-8-sig", newline="") as arquivo:
        return [dict(linha) for linha in csv.DictReader(arquivo)]


def escrever_csv(caminho: Path, colunas: list[str], linhas: list[dict[str, Any]]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.DictWriter(
            arquivo,
            fieldnames=colunas,
            extrasaction="ignore",
            lineterminator="\n",
        )
        escritor.writeheader()
        escritor.writerows(linhas)


def nome_arquivo(valor: str) -> str:
    normalizado = unicodedata.normalize("NFKD", valor)
    normalizado = "".join(c for c in normalizado if not unicodedata.combining(c))
    return re.sub(r'[\\/:*?"<>|]+', "-", normalizado).strip(" .") or "imagem"


def encontrar_imagem_existente(nome: str) -> Path | None:
    if not PASTA_IMAGENS_PUBLICAS.is_dir():
        return None
    chave = chave_texto(nome_arquivo(nome))
    extensoes = {".jpg", ".jpeg", ".png", ".webp", ".avif"}
    for arquivo in PASTA_IMAGENS_PUBLICAS.iterdir():
        if arquivo.is_file() and arquivo.suffix.lower() in extensoes:
            if chave_texto(arquivo.stem) == chave:
                return arquivo
    return None


def baixar_imagem(url: str, nome: str) -> str:
    """Baixa somente quando ainda não existe uma imagem equivalente na pasta."""

    if not url:
        return ""
    PASTA_IMAGENS_PUBLICAS.mkdir(parents=True, exist_ok=True)
    existente = encontrar_imagem_existente(nome)
    if existente is not None:
        print(f"  Imagem já existente: {existente.name}")
        return existente.name

    url = urljoin("https://www.ligapokemon.com.br/", url)
    extensao = Path(urlparse(url).path).suffix.lower()
    if extensao not in {".jpg", ".jpeg", ".png", ".webp", ".avif"}:
        extensao = ".jpg"
    destino = PASTA_IMAGENS_PUBLICAS / f"{nome_arquivo(nome)}{extensao}"
    if destino.exists():
        return destino.name
    try:
        requisicao = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(requisicao, timeout=45) as resposta:
            conteudo = resposta.read()
        # A existência é conferida novamente para evitar gravação duplicada.
        existente = encontrar_imagem_existente(nome)
        if existente is not None:
            return existente.name
        destino.write_bytes(conteudo)
        return destino.name
    except Exception as erro:
        print(f"  Aviso: não foi possível baixar a imagem: {erro}")
        return ""


def idioma_da_colecao(valor: str) -> str:
    chave = chave_texto(valor)
    if chave in {"BR", "PT", "PTBR", "PORTUGUES", "PORTUGUESPTBR"}:
        return "Português (PT-BR)"
    if chave in {"ING", "EN", "ENGLISH", "INGLES"}:
        return "Inglês"
    return texto_csv(valor)


def quantidade_inteira(valor: Any, padrao: int = 1) -> int:
    correspondencia = re.search(r"\d+", texto_csv(valor))
    if not correspondencia:
        return padrao
    return max(1, int(correspondencia.group(0)))


def montar_linha_carta(linha: dict[str, Any], dados: dict[str, Any]) -> dict[str, Any]:
    menor = dados.get("preco")
    numero = texto_csv(dados.get("numeracao")) or primeiro_valor(linha, "Número", "Numeração")
    return {
        "Nome": texto_csv(dados.get("nome")) or primeiro_valor(linha, "Nome"),
        "Número": numero,
        "Coleção": texto_csv(dados.get("colecao")) or primeiro_valor(linha, "Coleção"),
        "Idioma": idioma_da_colecao(primeiro_valor(linha, "Idioma") or IDIOMA),
        "Estado": normalizar_estado(primeiro_valor(linha, "Estado") or ESTADO),
        "Ano": texto_csv(dados.get("ano")) or primeiro_valor(linha, "Ano"),
        "Tipo": texto_csv(dados.get("tipo")) or primeiro_valor(linha, "Tipo"),
        "Link Liga": primeiro_valor(linha, "Link Liga"),
        "Link MYP": primeiro_valor(linha, "Link MYP"),
        "Link Cardmarket": primeiro_valor(linha, "Link Cardmarket"),
        "Link Tcgplayer": primeiro_valor(linha, "Link Tcgplayer", "Link TCGPlayer"),
        "Link PriceCharting": primeiro_valor(linha, "Link PriceCharting"),
        "Minimo": primeiro_valor(linha, "Minimo", "Mínimo"),
        "Venda Rapida": primeiro_valor(linha, "Venda Rapida", "Venda Rápida"),
        "Menor Liga": formatar_decimal_csv(menor if isinstance(menor, Decimal) else None)
        or primeiro_valor(linha, "Menor Liga", "Preço Mais Baixo Liga"),
        "Preço": primeiro_valor(linha, "Preço"),
        "Quantidade": quantidade_inteira(primeiro_valor(linha, "Quantidade")),
    }


def montar_linha_booster(linha: dict[str, Any], dados: dict[str, Any]) -> dict[str, Any]:
    menor = dados.get("preco")
    return {
        "Tipo de pacote": texto_csv(dados.get("colecao") or dados.get("nome"))
        or primeiro_valor(linha, "Tipo de pacote", "Coleção"),
        "Quantidade": quantidade_inteira(primeiro_valor(linha, "Quantidade")),
        "Preço mínimo": primeiro_valor(linha, "Preço mínimo", "Minimo", "Mínimo"),
        "Venda rápida": primeiro_valor(linha, "Venda rápida", "Venda Rapida", "Venda Rápida"),
        "Preço Liga mais barato": formatar_decimal_csv(menor if isinstance(menor, Decimal) else None)
        or primeiro_valor(linha, "Preço Liga mais barato", "Preço Mais Baixo Liga", "Menor Liga"),
        "Preço": primeiro_valor(linha, "Preço"),
    }


def normalizar_linha_kit(linha: dict[str, Any]) -> dict[str, Any]:
    return {
        "Nome": primeiro_valor(linha, "Nome"),
        "Descrição": primeiro_valor(linha, "Descrição"),
        "Preço": primeiro_valor(linha, "Preço"),
        "Quantidade": quantidade_inteira(primeiro_valor(linha, "Quantidade")),
        "Conteúdo": primeiro_valor(linha, "Conteúdo"),
        "Imagem": primeiro_valor(linha, "Imagem"),
    }


def identificar_colecao(perfil: dict[str, Any], nome_padrao: str) -> str:
    bruto = texto_csv(perfil.get("collectionId")) or nome_padrao
    return re.sub(r"[^A-Za-z0-9_-]+", "-", bruto).strip("-") or "colecao"


def formatar_colecao(origem: Path, sessao: SessaoLiga) -> Path:
    """Converte uma coleção completa para a estrutura exata da Leon19."""

    perfil_origem = origem / "perfil.json"
    if not perfil_origem.is_file():
        raise FileNotFoundError(f"perfil.json não encontrado em {origem}")
    perfil = json.loads(perfil_origem.read_text(encoding="utf-8-sig"))
    identificador = identificar_colecao(perfil, origem.name)
    destino = PASTA_COLECOES_FORMATADAS / identificador
    destino.mkdir(parents=True, exist_ok=True)
    (destino / "perfil.json").write_text(
        json.dumps(perfil, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    cartas_formatadas: list[dict[str, Any]] = []
    for indice, linha in enumerate(ler_csv(origem / "inventario-cartas.csv"), start=1):
        link = primeiro_valor(linha, "Link Liga")
        idioma = primeiro_valor(linha, "Idioma") or IDIOMA
        estado = primeiro_valor(linha, "Estado") or ESTADO
        print(f"Carta {indice}: consultando Liga Pokémon em nova aba...")
        dados: dict[str, Any] = {}
        try:
            if link:
                dados = sessao.consultar_carta(link, idioma, estado)
            else:
                raise ValueError("Link Liga vazio")
        except Exception as erro:
            print(f"  Aviso: consulta não concluída ({erro}). Mantendo os dados enviados.")
        linha_formatada = montar_linha_carta(linha, dados)
        baixar_imagem(
            texto_csv(dados.get("imagem")),
            f"{linha_formatada['Nome']}_{linha_formatada['Número']}",
        )
        cartas_formatadas.append(linha_formatada)

    boosters_formatados: list[dict[str, Any]] = []
    for indice, linha in enumerate(ler_csv(origem / "inventario-boosters.csv"), start=1):
        link = primeiro_valor(linha, "Link Liga")
        print(f"Booster {indice}: consultando Liga Pokémon em nova aba...")
        dados: dict[str, Any] = {}
        try:
            if link:
                dados = sessao.consultar_booster(link)
            else:
                raise ValueError("Link Liga vazio")
        except Exception as erro:
            print(f"  Aviso: consulta não concluída ({erro}). Mantendo os dados enviados.")
        boosters_formatados.append(montar_linha_booster(linha, dados))

    kits = [normalizar_linha_kit(linha) for linha in ler_csv(origem / "inventario-kits.csv")]
    escrever_csv(destino / "inventario-cartas.csv", COLUNAS_CARTAS, cartas_formatadas)
    escrever_csv(destino / "inventario-boosters.csv", COLUNAS_BOOSTERS, boosters_formatados)
    escrever_csv(destino / "inventario-kits.csv", COLUNAS_KITS, kits)
    return destino


def chave_link(url: str) -> str:
    """Remove parâmetros de rastreamento e diferenças irrelevantes da Liga."""

    try:
        analisada = urlparse(url)
        pares = []
        for parte in analisada.query.split("&"):
            if not parte:
                continue
            nome = parte.split("=", 1)[0].lower()
            if nome.startswith("utm_") or nome in {"srsltid", "show"}:
                continue
            pares.append(parte)
        return f"{analisada.netloc.lower()}{analisada.path}?{'&'.join(sorted(pares))}"
    except Exception:
        return texto_csv(url)


def encontrar_colecao_destino(identificador: str) -> Path:
    PASTA_COLECOES_FORMATADAS.mkdir(parents=True, exist_ok=True)
    chave = chave_texto(identificador)
    for pasta in PASTA_COLECOES_FORMATADAS.iterdir():
        if not pasta.is_dir():
            continue
        if chave_texto(pasta.name) == chave:
            return pasta
        perfil = pasta / "perfil.json"
        if perfil.is_file():
            try:
                dados = json.loads(perfil.read_text(encoding="utf-8-sig"))
                if chave_texto(texto_csv(dados.get("collectionId"))) == chave:
                    return pasta
            except Exception:
                pass
    raise FileNotFoundError(f"Coleção de destino não encontrada: {identificador}")


def mesclar_carta(linhas: list[dict[str, Any]], nova: dict[str, Any]) -> None:
    chave_nova = (
        chave_link(texto_csv(nova.get("Link Liga"))),
        chave_texto(texto_csv(nova.get("Estado"))),
        chave_texto(texto_csv(nova.get("Idioma"))),
    )
    for existente in linhas:
        chave_existente = (
            chave_link(texto_csv(existente.get("Link Liga"))),
            chave_texto(texto_csv(existente.get("Estado"))),
            chave_texto(texto_csv(existente.get("Idioma"))),
        )
        if chave_existente == chave_nova:
            existente["Quantidade"] = quantidade_inteira(existente.get("Quantidade")) + quantidade_inteira(nova.get("Quantidade"))
            if texto_csv(nova.get("Menor Liga")):
                existente["Menor Liga"] = nova["Menor Liga"]
            return
    linhas.append(nova)


def mesclar_booster(linhas: list[dict[str, Any]], novo: dict[str, Any]) -> None:
    chave_nova = chave_texto(texto_csv(novo.get("Tipo de pacote")))
    for existente in linhas:
        if chave_texto(texto_csv(existente.get("Tipo de pacote"))) == chave_nova:
            existente["Quantidade"] = quantidade_inteira(existente.get("Quantidade")) + quantidade_inteira(novo.get("Quantidade"))
            if texto_csv(novo.get("Preço Liga mais barato")):
                existente["Preço Liga mais barato"] = novo["Preço Liga mais barato"]
            return
    linhas.append(novo)


def formatar_atualizacao(origem: Path, sessao: SessaoLiga) -> Path:
    """Consulta somente as adições e as incorpora à coleção indicada."""

    metadados = json.loads((origem / ARQUIVO_ATUALIZACAO).read_text(encoding="utf-8-sig"))
    identificador = primeiro_valor(
        metadados,
        "collectionId",
        "collection_id",
        "colecao",
    )
    if not identificador:
        raise ValueError("A atualização não informa collectionId.")
    destino = encontrar_colecao_destino(identificador)
    perfil_caminho = destino / "perfil.json"
    perfil: dict[str, Any] = {}
    if perfil_caminho.is_file():
        perfil = json.loads(perfil_caminho.read_text(encoding="utf-8-sig"))
    assinatura = "|".join([
        identificador,
        texto_csv(metadados.get("version")),
        texto_csv(metadados.get("generatedAt")),
    ])
    update_id = texto_csv(metadados.get("updateId")) or hashlib.sha256(assinatura.encode("utf-8")).hexdigest()[:20]
    aplicadas = [texto_csv(valor) for valor in perfil.get("appliedUpdates", [])]
    if update_id in aplicadas:
        print(f"Atualização {update_id} já aplicada; nenhuma linha foi duplicada.")
        return destino

    cartas = [montar_linha_carta(linha, {}) for linha in ler_csv(destino / "inventario-cartas.csv")]
    boosters = [montar_linha_booster(linha, {}) for linha in ler_csv(destino / "inventario-boosters.csv")]

    for indice, linha in enumerate(ler_csv(origem / "inventario-cartas.csv"), start=1):
        link = primeiro_valor(linha, "Link Liga")
        idioma = primeiro_valor(linha, "Idioma") or IDIOMA
        estado = primeiro_valor(linha, "Estado") or ESTADO
        print(f"Update carta {indice}: consultando Liga Pokémon em nova aba...")
        dados: dict[str, Any] = {}
        try:
            if link:
                dados = sessao.consultar_carta(link, idioma, estado)
            else:
                raise ValueError("Link Liga vazio")
        except Exception as erro:
            print(f"  Aviso: consulta não concluída ({erro}).")
        if not texto_csv(dados.get("nome")) and not texto_csv(dados.get("colecao")):
            print("  Carta do update ignorada porque a Liga não devolveu seus dados.")
            continue
        nova = montar_linha_carta(linha, dados)
        baixar_imagem(
            texto_csv(dados.get("imagem")),
            f"{nova['Nome']}_{nova['Número']}",
        )
        mesclar_carta(cartas, nova)

    for indice, linha in enumerate(ler_csv(origem / "inventario-boosters.csv"), start=1):
        link = primeiro_valor(linha, "Link Liga")
        print(f"Update booster {indice}: consultando Liga Pokémon em nova aba...")
        dados: dict[str, Any] = {}
        try:
            if link:
                dados = sessao.consultar_booster(link)
            else:
                raise ValueError("Link Liga vazio")
        except Exception as erro:
            print(f"  Aviso: consulta não concluída ({erro}).")
        if not texto_csv(dados.get("nome")) and not texto_csv(dados.get("colecao")):
            print("  Booster do update ignorado porque a Liga não devolveu seus dados.")
            continue
        mesclar_booster(boosters, montar_linha_booster(linha, dados))

    escrever_csv(destino / "inventario-cartas.csv", COLUNAS_CARTAS, cartas)
    escrever_csv(destino / "inventario-boosters.csv", COLUNAS_BOOSTERS, boosters)

    if perfil_caminho.is_file():
        versao_atual = int(perfil.get("version") or 1)
        versao_pacote = int(metadados.get("version") or 0)
        perfil["version"] = max(versao_atual + 1, versao_pacote)
        perfil["updatedAt"] = texto_csv(metadados.get("generatedAt")) or time.strftime("%Y-%m-%dT%H:%M:%S")
        perfil["appliedUpdates"] = [*aplicadas, update_id][-100:]
        perfil_caminho.write_text(json.dumps(perfil, ensure_ascii=False, indent=2), encoding="utf-8")
    return destino


def encontrar_raiz_pacote(pasta: Path) -> Path | None:
    if (pasta / "perfil.json").is_file() or (pasta / ARQUIVO_ATUALIZACAO).is_file():
        return pasta
    for nome in (ARQUIVO_ATUALIZACAO, "perfil.json"):
        for arquivo in pasta.rglob(nome):
            return arquivo.parent
    return None


def processar_pacote(raiz: Path, sessao: SessaoLiga) -> Path:
    if (raiz / ARQUIVO_ATUALIZACAO).is_file():
        return formatar_atualizacao(raiz, sessao)
    return formatar_colecao(raiz, sessao)


def formatar_pasta(entrada: Path = PASTA_COLECOES_NAO_FORMATADAS) -> list[Path]:
    """Formata coleções completas e aplica ZIPs de atualização."""

    entrada.mkdir(parents=True, exist_ok=True)
    itens = list(entrada.iterdir())
    resultados: list[Path] = []
    if not itens:
        return resultados

    with SessaoLiga() as sessao:
        for item in itens:
            try:
                if item.is_dir():
                    raiz = encontrar_raiz_pacote(item)
                    if raiz:
                        resultados.append(processar_pacote(raiz, sessao))
                    else:
                        print(f"Ignorado: {item.name} não possui perfil.json nem {ARQUIVO_ATUALIZACAO}.")
                elif item.suffix.lower() == ".zip":
                    with tempfile.TemporaryDirectory(prefix="nexus-tcg-pacote-") as temporario:
                        with zipfile.ZipFile(item) as arquivo:
                            arquivo.extractall(temporario)
                        raiz = encontrar_raiz_pacote(Path(temporario))
                        if raiz:
                            resultados.append(processar_pacote(raiz, sessao))
                        else:
                            print(f"Ignorado: {item.name} não possui perfil.json nem {ARQUIVO_ATUALIZACAO}.")
            except Exception as erro:
                print(f"Erro ao processar {item.name}: {erro}")
    return resultados


def mostrar_consulta_unica() -> None:
    resultado = consultar()
    print("\n========== RESULTADO ==========")
    print(f"Nome: {resultado['nome']}")
    print(f"Coleção: {resultado['colecao']}")
    print(f"Numeração: {resultado['numeracao']}")
    print(f"Idioma: {resultado['idioma']}")
    print(f"Estado: {resultado['estado']}")
    preco = resultado.get("preco")
    print(f"Menor preço: {formatar_reais(preco) if isinstance(preco, Decimal) else 'não encontrado'}")
    if resultado.get("loja"):
        print(f"Loja: {resultado['loja']}")
    if resultado.get("link_loja"):
        print(f"Link da oferta: {resultado['link_loja']}")


def main() -> None:
    argumentos = argparse.ArgumentParser(
        description="Formata coleções e aplica atualizações usando um único Chrome.",
    )
    argumentos.add_argument(
        "--consultar",
        action="store_true",
        help="Consulta somente a URL configurada no início do arquivo.",
    )
    argumentos.add_argument(
        "--entrada",
        type=Path,
        default=PASTA_COLECOES_NAO_FORMATADAS,
        help="Pasta com coleções completas ou ZIPs de atualização.",
    )
    opcoes = argumentos.parse_args()
    try:
        if opcoes.consultar:
            mostrar_consulta_unica()
            return
        resultados = formatar_pasta(opcoes.entrada)
        if resultados:
            print("\nProcessamento concluído:")
            for destino in resultados:
                print(f"  - {destino}")
        else:
            print("Nenhum pacote válido foi encontrado.")
    except Exception as erro:
        print(f"\nErro: {erro}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
