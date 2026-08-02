from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import time
import unicodedata
from collections import Counter
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any

import ddddocr
from PIL import Image, ImageOps
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.ui import WebDriverWait


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

# Tempo adicional após o carregamento da página.
TEMPO_ESPERA = 5.0

# Tempo máximo para carregar a página e encontrar os anúncios.
TIMEOUT_CARREGAMENTO = 60

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


def abrir_navegador() -> tuple[webdriver.Chrome, subprocess.Popen[Any]]:
    """Abre o Chrome visivelmente e conecta o Selenium a ele."""

    chrome = encontrar_chrome()
    porta = obter_porta_livre()

    PASTA_PERFIL_CHROME.mkdir(parents=True, exist_ok=True)

    comando_chrome = [
        str(chrome),
        f"--remote-debugging-port={porta}",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={PASTA_PERFIL_CHROME.resolve()}",
        "--window-size=1400,1000",
        "--no-first-run",
        "--no-default-browser-check",
        URL,
    ]

    processo = subprocess.Popen(comando_chrome)
    esperar_chrome(porta)

    opcoes = Options()
    opcoes.debugger_address = f"127.0.0.1:{porta}"

    navegador = webdriver.Chrome(options=opcoes)
    return navegador, processo


def selecionar_aba_liga(navegador: webdriver.Chrome) -> None:
    """Seleciona a aba da Liga Pokémon aberta pelo comando do Chrome."""

    for identificador in navegador.window_handles:
        navegador.switch_to.window(identificador)
        if "ligapokemon.com.br" in navegador.current_url.lower():
            return

    navegador.get(URL)


def esperar_pagina(navegador: webdriver.Chrome) -> None:
    """Espera a página e os dados JavaScript dos anúncios carregarem."""

    WebDriverWait(navegador, TIMEOUT_CARREGAMENTO).until(
        lambda driver: driver.execute_script(
            "return document.readyState"
        )
        == "complete"
    )

    # Espera adicional configurável. Não é necessário pressionar Enter.
    time.sleep(TEMPO_ESPERA)

    titulo = navegador.title.lower()
    if "just a moment" in titulo or "um momento" in titulo:
        raise RuntimeError(
            "A página ainda está na verificação do navegador. "
            "Aumente TEMPO_ESPERA ou abra o perfil uma vez e resolva "
            "a verificação manualmente."
        )

    WebDriverWait(navegador, TIMEOUT_CARREGAMENTO).until(
        lambda driver: driver.execute_script(
            """
            return Boolean(
                document.querySelector('#featuredImage') &&
                Array.isArray(window.cards_editions) &&
                Array.isArray(window.cards_stock)
            );
            """
        )
    )


def mostrar_todas_as_ofertas(navegador: webdriver.Chrome) -> None:
    """Pede ao código da página para revelar todos os anúncios carregados."""

    for _ in range(5):
        quantidade_antes = len(
            navegador.find_elements(
                By.CSS_SELECTOR,
                "#marketplace-stores > .store",
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
                "#marketplace-stores > .store",
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

        const imagem = document.querySelector('#featuredImage');
        const nome =
            imagem?.getAttribute('title')?.trim() ||
            imagem?.getAttribute('alt')?.trim() ||
            document.querySelector('h1')?.textContent?.trim() ||
            '';

        return {
            nome: nome,
            colecao: String(edicao.name || '').trim(),
            numeracao: String(edicao.num || '').trim()
        };
        """
    )

    if not isinstance(dados, dict):
        raise RuntimeError("Não foi possível obter os dados da carta.")

    return {
        "nome": str(dados.get("nome", "")).strip(),
        "colecao": str(dados.get("colecao", "")).strip(),
        "numeracao": str(dados.get("numeracao", "")).strip(),
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

    container = oferta.find_element(By.CSS_SELECTOR, ".price-with-image")
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
        "#marketplace-stores > .store",
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

        preco = decodificar_preco(
            navegador=navegador,
            oferta=oferta,
            ocr=ocr,
            cache=cache_digitos,
            oferta_id=oferta_id,
        )

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


def consultar() -> dict[str, Any]:
    """Executa a consulta e devolve os dados da oferta mais barata."""

    estado_desejado = normalizar_estado(ESTADO)
    idioma_desejado = normalizar_idioma(IDIOMA)

    navegador: webdriver.Chrome | None = None
    processo: subprocess.Popen[Any] | None = None

    try:
        print("Abrindo o Chrome...")
        navegador, processo = abrir_navegador()
        selecionar_aba_liga(navegador)

        print(
            f"Aguardando o carregamento e mais {TEMPO_ESPERA:g} segundos..."
        )
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


def main() -> None:
    try:
        resultado = consultar()
    except TimeoutException:
        print(
            "\nErro: a página demorou mais que o permitido para carregar."
        )
        print(
            "Aumente TIMEOUT_CARREGAMENTO ou TEMPO_ESPERA no início do código."
        )
        raise SystemExit(1)
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
    main()