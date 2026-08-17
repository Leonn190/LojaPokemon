from __future__ import annotations

import os
import re
import json
import random
import hashlib
import shutil
import socket
import subprocess
import time
import unicodedata
import tempfile
import threading
from collections import Counter
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from statistics import mean
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from configuracao import (
    ESTADOS_ORDEM,
    FATORES_ESTADO,
    ESPERA_ESTABILIDADE_MAX,
    INTERVALO_TENTATIVA,
    MAX_TENTATIVAS_PAGINA,
    MINIMO,
    PASTA_IMAGENS,
    TENTATIVAS,
    USAR_OCR,
)
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

# O Chrome usa um perfil temporário por execução. Ele é apagado ao encerrar.

# Salva imagens somente quando o OCR não consegue ler algum preço.
PASTA_DEBUG = Path(__file__).with_name("debug_precos")
VERSAO_LEITOR_PRECO = 2
_LOCK_DEBUG = threading.Lock()
_MAX_IMAGENS_DEBUG = 250


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
        return bool(dados["completa"] and not dados["verificando"] and dados["temCarta"] and dados["temMercado"])
    except Exception:
        return False


def esperar_pagina(navegador: webdriver.Chrome) -> None:
    """Espera a página real substituir a verificação anti-bot."""

    for tentativa in range(1, MAX_TENTATIVAS_PAGINA + 1):
        if pagina_liga_pronta(navegador):
            print("Página da Liga carregada. Coletando dados do HTML...")
            return
        print(
            f"Página ainda não está pronta; tentando novamente em "
            f"{INTERVALO_TENTATIVA:g}s (tentativa {tentativa}/{MAX_TENTATIVAS_PAGINA})..."
        )
        time.sleep(INTERVALO_TENTATIVA)
    raise TimeoutError(
        "A página da Liga não ficou disponível. Verifique a janela do Chrome "
        "e conclua manualmente qualquer verificação de segurança."
    )


def esperar_ofertas_estaveis(navegador: webdriver.Chrome, timeout: float = ESPERA_ESTABILIDADE_MAX) -> None:
    """Espera somente o necessário até a quantidade de ofertas parar de mudar.

    Substitui o antigo sleep fixo: páginas rápidas seguem quase imediatamente e
    páginas lentas podem usar até ``timeout`` segundos para estabilizar.
    """

    inicio = time.monotonic()
    limite = inicio + max(0.8, float(timeout))
    anterior: int | None = None
    estaveis = 0
    while time.monotonic() < limite:
        try:
            atual = len(_elementos_ofertas(navegador))
        except Exception:
            atual = -1
        if atual == anterior:
            estaveis += 1
            if estaveis >= 3 and (time.monotonic() - inicio) >= 0.8:
                return
        else:
            anterior = atual
            estaveis = 0
        time.sleep(0.20)


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

        time.sleep(0.25)

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
    """Mantém SOMENTE dígitos realmente reconhecidos pelo OCR.

    A versão anterior convertia letras visualmente parecidas (I/l/L -> 1,
    O/Q -> 0 etc.). Em imagens pequenas ou cortadas isso transformava um
    palpite do OCR em um preço aparentemente válido, criando padrões como
    1,11 / 11,11 / 111,11. Aqui, letra é falha de OCR, não número.
    """

    return "".join(caractere for caractere in (texto or "") if caractere.isdigit())


def carregar_rgba(png: bytes) -> Image.Image:
    imagem = Image.open(BytesIO(png)).convert("RGBA")
    imagem.load()
    return imagem


def _imagem_tem_grafia_util(imagem_rgba: Image.Image) -> bool:
    """Rejeita screenshots em branco ou com o algarismo severamente cortado."""

    cinza = ImageOps.grayscale(imagem_rgba.convert("RGB"))
    minimo, maximo = cinza.getextrema()
    if maximo - minimo < 18:
        return False

    # Usa o canto inferior direito como aproximação do fundo e procura pixels
    # que realmente se afastam desse fundo. Isso funciona tanto em tema claro
    # quanto escuro e, principalmente, detecta o problema visto nos PNGs de
    # debug em que só 2-3 linhas do sprite apareciam.
    fundo = cinza.getpixel((max(0, cinza.width - 1), max(0, cinza.height - 1)))
    mascara = cinza.point(lambda px: 255 if abs(int(px) - int(fundo)) >= 18 else 0)
    bbox = mascara.getbbox()
    if bbox is None:
        return False
    largura_util = bbox[2] - bbox[0]
    altura_util = bbox[3] - bbox[1]
    if largura_util < max(2, int(imagem_rgba.width * 0.15)):
        return False
    if altura_util < max(4, int(imagem_rgba.height * 0.35)):
        return False
    return True


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
    """Reconhece apenas quando tratamentos independentes concordam.

    Um único palpite nunca mais é aceito. A imagem também precisa ter grafia
    suficiente; screenshots brancos ou cortados são falha explícita.
    """

    if not _imagem_tem_grafia_util(imagem_rgba):
        return None

    resultados: list[str] = []
    for fundo in ("white", "black"):
        for inverter in (False, True):
            variante = montar_variante_ocr(imagem_rgba, fundo=fundo, inverter=inverter)
            texto = ocr.classification(variante)
            digitos = limpar_resultado_ocr(str(texto))
            if len(digitos) == quantidade_esperada:
                resultados.append(digitos)

    if not resultados:
        return None

    vencedor, votos = Counter(resultados).most_common(1)[0]
    # Exige pelo menos 2 confirmações e 75% das leituras válidas concordando.
    # Evita que um único "I"/"l" interpretado como 1 contamine o cache/preço.
    if votos < 2 or (votos / len(resultados)) < 0.75:
        return None
    return vencedor


def chave_visual_digito(
    navegador: webdriver.Chrome,
    elemento: WebElement,
) -> str:
    """Cria uma chave estável para diagnóstico do sprite visual."""

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
    """Reconhece um algarismo sem confiar cegamente em cache antigo."""

    navegador.execute_script("arguments[0].scrollIntoView({block: 'center'});", elemento)
    time.sleep(0.03)
    imagem = carregar_rgba(elemento.screenshot_as_png)
    resultado = reconhecer_imagem(ocr, imagem, quantidade_esperada=1)

    # O cache só recebe leituras já validadas por consenso e grafia. Ele não é
    # consultado antes do OCR: isso elimina o efeito cascata em que um erro de
    # uma oferta envenenava centenas de preços posteriores no mesmo worker.
    if resultado:
        try:
            cache[chave_visual_digito(navegador, elemento)] = resultado
        except Exception:
            pass
    return resultado


def _capturar_digitos_pelo_container(
    navegador: webdriver.Chrome,
    container: WebElement,
    elementos: list[WebElement],
) -> list[Image.Image]:
    """Recorta os dígitos a partir do screenshot do preço inteiro.

    O Selenium pode rasterizar mal um elemento-filho com background-position.
    Capturar o contêiner já composto pelo Chrome e recortar pelas coordenadas
    dos filhos é muito mais resistente a esse tipo de corte.
    """

    navegador.execute_script("arguments[0].scrollIntoView({block: 'center'});", container)
    time.sleep(0.05)
    imagem = carregar_rgba(container.screenshot_as_png)
    geometria = navegador.execute_script(
        """
        const c = arguments[0].getBoundingClientRect();
        return Array.from(arguments).slice(1).map(el => {
            const r = el.getBoundingClientRect();
            return {x:r.left-c.left, y:r.top-c.top, w:r.width, h:r.height,
                    cw:c.width, ch:c.height};
        });
        """,
        container,
        *elementos,
    )
    if not geometria:
        return []
    cw = float(geometria[0].get("cw") or 0)
    ch = float(geometria[0].get("ch") or 0)
    if cw <= 0 or ch <= 0:
        return []
    sx = imagem.width / cw
    sy = imagem.height / ch
    recortes: list[Image.Image] = []
    for g in geometria:
        x1 = max(0, int(round(float(g.get("x") or 0) * sx)))
        y1 = max(0, int(round(float(g.get("y") or 0) * sy)))
        x2 = min(imagem.width, int(round((float(g.get("x") or 0) + float(g.get("w") or 0)) * sx)))
        y2 = min(imagem.height, int(round((float(g.get("y") or 0) + float(g.get("h") or 0)) * sy)))
        if x2 <= x1 or y2 <= y1:
            return []
        recortes.append(imagem.crop((x1, y1, x2, y2)))
    return recortes


def montar_imagem_preco_imagens(imagens: list[Image.Image]) -> Image.Image:
    altura = max(imagem.height for imagem in imagens)
    espacamento = 3
    largura = sum(imagem.width for imagem in imagens) + espacamento * max(0, len(imagens) - 1)
    resultado = Image.new("RGBA", (largura, altura), "white")
    x = 0
    for imagem in imagens:
        y = (altura - imagem.height) // 2
        resultado.alpha_composite(imagem.convert("RGBA"), (x, y))
        x += imagem.width + espacamento
    return resultado


def montar_imagem_preco(elementos: list[WebElement]) -> Image.Image:
    return montar_imagem_preco_imagens([carregar_rgba(elemento.screenshot_as_png) for elemento in elementos])


def _salvar_debug_preco(imagem: Image.Image, oferta_id: str, motivo: str) -> Path | None:
    """Deduplica PNGs de falha e mantém um índice leve em JSONL."""

    destino = BytesIO()
    imagem.convert("RGB").save(destino, format="PNG")
    conteudo = destino.getvalue()
    hash_curto = hashlib.sha256(conteudo).hexdigest()[:12]
    PASTA_DEBUG.mkdir(parents=True, exist_ok=True)
    arquivo = PASTA_DEBUG / f"falha_{hash_curto}.png"
    indice = PASTA_DEBUG / "falhas.jsonl"
    with _LOCK_DEBUG:
        existentes = len(list(PASTA_DEBUG.glob("falha_*.png")))
        salvo = arquivo.exists()
        if not salvo and existentes < _MAX_IMAGENS_DEBUG:
            arquivo.write_bytes(conteudo)
            salvo = True
        registro = {
            "ofertaId": str(oferta_id),
            "imagemHash": hash_curto,
            "imagem": arquivo.name if salvo else None,
            "motivo": motivo,
            "largura": imagem.width,
            "altura": imagem.height,
        }
        with indice.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(registro, ensure_ascii=False) + "\n")
    return arquivo if salvo else None


def _padrao_preco_suspeito(valor: Decimal) -> bool:
    """Detecta os padrões artificiais observados na cotização corrompida."""

    texto = f"{valor.quantize(Decimal('0.01')):.2f}"
    inteiro, centavos = texto.split(".")
    if centavos != "11":
        return False
    return bool(inteiro) and all(c in "17" for c in inteiro)


def decodificar_preco(
    navegador: webdriver.Chrome,
    oferta: WebElement,
    ocr: ddddocr.DdddOcr,
    cache: dict[str, str],
    oferta_id: str,
) -> Decimal:
    """Lê o preço visual com validação forte e sem aceitar palpites isolados."""

    texto_oferta = (oferta.get_attribute("innerText") or "").replace("\xa0", " ")
    encontrado_texto = re.search(r"R\$\s*([0-9.]+,[0-9]{2})", texto_oferta)
    if encontrado_texto:
        return Decimal(encontrado_texto.group(1).replace(".", "").replace(",", "."))

    if not USAR_OCR:
        raise ErroLeituraPreco(f"Oferta {oferta_id} usa preço visual e usarOCR está desativado no config.json.")

    container = buscar_elemento_opcional(oferta, ".price-with-image, .price_with_image, [data-price-image]")
    if container is None:
        raise ErroLeituraPreco(f"Oferta {oferta_id} não possui um preço legível; ela será ignorada.")
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
        imagem_fundo = str(navegador.execute_script("return getComputedStyle(arguments[0]).backgroundImage;", filho))
        if imagem_fundo and imagem_fundo != "none":
            elementos_digitos.append(filho)

    if not elementos_digitos:
        raise ErroLeituraPreco(f"Nenhum algarismo encontrado na oferta {oferta_id}.")
    if indice_separador is None:
        indice_separador = max(1, len(elementos_digitos) - 2)

    # Método principal: screenshot do contêiner já composto pelo Chrome.
    imagens = _capturar_digitos_pelo_container(navegador, container, elementos_digitos)
    if not imagens or len(imagens) != len(elementos_digitos):
        imagens = [carregar_rgba(elemento.screenshot_as_png) for elemento in elementos_digitos]

    reconhecidos = [reconhecer_imagem(ocr, imagem, 1) for imagem in imagens]
    imagem_preco = montar_imagem_preco_imagens(imagens)
    completo = reconhecer_imagem(ocr, imagem_preco, quantidade_esperada=len(elementos_digitos))

    if any(d is None for d in reconhecidos):
        reconhecidos = list(completo) if completo else reconhecidos
    elif completo and completo != "".join(str(d) for d in reconhecidos):
        arquivo = _salvar_debug_preco(imagem_preco, oferta_id, "OCR do preço inteiro divergiu do OCR dos dígitos")
        complemento = f" Debug: {arquivo}" if arquivo else ""
        raise ErroLeituraPreco(f"Leituras OCR divergentes na oferta {oferta_id}.{complemento}")

    if any(d is None for d in reconhecidos):
        arquivo = _salvar_debug_preco(imagem_preco, oferta_id, "imagem branca/cortada ou OCR sem consenso")
        complemento = f" Imagem de diagnóstico: {arquivo}" if arquivo else ""
        raise ErroLeituraPreco(f"Não foi possível reconhecer com segurança o preço da oferta {oferta_id}.{complemento}")

    digitos = "".join(str(d) for d in reconhecidos)
    parte_inteira = digitos[:indice_separador]
    parte_decimal = digitos[indice_separador:]
    if not parte_inteira or len(parte_decimal) != 2:
        raise ErroLeituraPreco(
            f"Preço reconhecido em formato inesperado na oferta {oferta_id}: {parte_inteira},{parte_decimal}"
        )

    valor = Decimal(f"{parte_inteira}.{parte_decimal}")
    # Para os padrões que apareceram em massa na execução corrompida, exigimos
    # também confirmação do OCR do preço inteiro. Assim um 711,11 isolado não
    # passa somente porque quatro dígitos individuais foram classificados como
    # 7/1 por engano.
    if _padrao_preco_suspeito(valor) and completo != digitos:
        arquivo = _salvar_debug_preco(imagem_preco, oferta_id, "padrão 1/7 com centavos 11 sem confirmação integral")
        complemento = f" Debug: {arquivo}" if arquivo else ""
        raise ErroLeituraPreco(
            f"Preço OCR suspeito {valor} na oferta {oferta_id} sem confirmação independente.{complemento}"
        )
    return valor

def buscar_elemento_opcional(
    raiz: WebElement,
    seletor: str,
) -> WebElement | None:
    try:
        return raiz.find_element(By.CSS_SELECTOR, seletor)
    except NoSuchElementException:
        return None



def _elementos_ofertas(navegador: webdriver.Chrome) -> list[WebElement]:
    """Encontra blocos de oferta tanto no marketplace quanto na buylist."""

    seletores = (
        "#marketplace-stores > .store",
        ".marketplace-stores > .store",
        "#buylist-stores > .store",
        ".buylist-stores > .store",
        ".stores-buylist > .store",
        ".buylist .store",
        "[data-store-id]",
        ".store-row",
        ".offer-row",
    )
    encontrados: list[WebElement] = []
    vistos: set[str] = set()
    def adicionar(elemento: WebElement) -> None:
        try:
            if not elemento.is_displayed():
                return
            chave = elemento.id
        except Exception:
            return
        if chave not in vistos:
            vistos.add(chave)
            encontrados.append(elemento)

    for seletor in seletores:
        for elemento in navegador.find_elements(By.CSS_SELECTOR, seletor):
            adicionar(elemento)

    # Fallback: parte do site muda os nomes dos contêineres, mas mantém o
    # componente visual do preço. Nesse caso, sobe até o bloco da loja.
    for preco in navegador.find_elements(
        By.CSS_SELECTOR,
        ".price-with-image, .price_with_image, [data-price-image]",
    ):
        try:
            bloco = preco.find_element(
                By.XPATH,
                "./ancestor::*[contains(@class,'store') or contains(@class,'offer') "
                "or @data-store-id or self::tr or self::li][1]",
            )
        except Exception:
            try:
                bloco = preco.find_element(By.XPATH, "..")
            except Exception:
                continue
        adicionar(bloco)
    return encontrados


def _extrair_idioma_estado(oferta: WebElement) -> tuple[str, str]:
    idioma = ""
    estado = ""
    seletores_idioma = (
        ".infos-quality-and-language.desktop-only .lang img[title]",
        ".infos-quality-and-language .lang img[title]",
        ".lang img[title]",
        "img[title*='Portugu']",
        "img[title*='Ingl']",
        "[data-language]",
    )
    for seletor in seletores_idioma:
        elemento = buscar_elemento_opcional(oferta, seletor)
        if elemento is None:
            continue
        idioma = (
            elemento.get_attribute("title")
            or elemento.get_attribute("data-language")
            or elemento.get_attribute("alt")
            or elemento.get_attribute("textContent")
            or ""
        ).strip()
        if idioma:
            break

    seletores_estado = (
        ".infos-quality-and-language.desktop-only .quality",
        ".infos-quality-and-language .quality",
        ".quality",
        "[data-condition]",
        "[data-quality]",
    )
    for seletor in seletores_estado:
        elemento = buscar_elemento_opcional(oferta, seletor)
        if elemento is None:
            continue
        bruto = (
            elemento.get_attribute("data-condition")
            or elemento.get_attribute("data-quality")
            or elemento.get_attribute("textContent")
            or ""
        ).strip().upper()
        correspondencia = re.search(r"(?:^|\b)(NM|SP|MP|HP|D|M)(?:\b|$)", bruto)
        if correspondencia:
            estado = correspondencia.group(1)
            break

    texto = (oferta.get_attribute("innerText") or "").upper()
    if not estado:
        correspondencia = re.search(r"(?:ESTADO|CONDIÇÃO|CONDICAO|QUALITY)?\s*[:\-]?\s*\b(NM|SP|MP|HP|D|M)\b", texto)
        if correspondencia:
            estado = correspondencia.group(1)
    if not idioma:
        if re.search(r"PORTUGU[EÊ]S|PT[- ]?BR|\bBR\b", texto):
            idioma = "Português"
        elif re.search(r"INGL[EÊ]S|ENGLISH|\bING\b|\bEN\b", texto):
            idioma = "Inglês"
    return idioma, estado


def _extrair_extra(oferta: WebElement) -> str:
    """Extrai a variação física da oferta (Foil/Reverse Foil/Normal), quando exibida."""
    seletores = (
        ".extras", ".extra", ".card-extra", ".infos-extra",
        "[data-extra]", "[data-finish]", "[data-foil]",
    )
    candidatos: list[str] = []
    for seletor in seletores:
        elemento = buscar_elemento_opcional(oferta, seletor)
        if elemento is None:
            continue
        bruto = (
            elemento.get_attribute("data-extra")
            or elemento.get_attribute("data-finish")
            or elemento.get_attribute("data-foil")
            or elemento.get_attribute("textContent")
            or ""
        ).strip()
        if bruto:
            candidatos.append(bruto)
    candidatos.append((oferta.get_attribute("innerText") or "").strip())
    texto = " ".join(candidatos).upper()
    if re.search(r"REVERSE\s*FOIL|FOIL\s*REVERS", texto):
        return "Reverse Foil"
    if re.search(r"(?:^|\s)FOIL(?:\s|$)", texto):
        return "Foil"
    if re.search(r"NORMAL\s*/?\s*SEM\s*EXTRAS|SEM\s*EXTRAS", texto):
        return "Normal / Sem Extras"
    return ""


def obter_todas_as_ofertas(
    navegador: webdriver.Chrome,
    origem: str,
    ocr: ddddocr.DdddOcr | None = None,
    cache_digitos: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Lê todas as ofertas visíveis e informa também falhas de leitura/OCR.

    Isso evita confundir "uma oferta lida" com "uma única oferta existente".
    """

    elementos = _elementos_ofertas(navegador)
    estatisticas: dict[str, Any] = {
        "detectadas": len(elementos),
        "lidas": 0,
        "falhas": 0,
        "erros": [],
    }
    if not elementos:
        return [], estatisticas

    if ocr is None:
        ocr = ddddocr.DdddOcr(show_ad=False, beta=True)
    if cache_digitos is None:
        cache_digitos = {}
    ofertas: list[dict[str, Any]] = []

    for indice, oferta in enumerate(elementos, start=1):
        idioma, estado = _extrair_idioma_estado(oferta)
        extra = _extrair_extra(oferta)
        identificador_dom = oferta.get_attribute("id") or f"{origem}-{indice}"
        correspondencia_oferta = re.search(r"(\d+)$", identificador_dom)
        oferta_id = correspondencia_oferta.group(1) if correspondencia_oferta else identificador_dom

        link_elemento = buscar_elemento_opcional(oferta, ".link-store, a[href*='id='], a[href]")
        link_loja = link_elemento.get_attribute("href") if link_elemento is not None else ""
        correspondencia_loja = re.search(r"[?&]id=(\d+)", link_loja or "")
        loja_id = correspondencia_loja.group(1) if correspondencia_loja else ""
        nome_loja = ""
        try:
            nome_loja = navegador.execute_script(
                """
                const id = String(arguments[0]);
                return window.cards_stores?.[id]?.lj_name || '';
                """,
                loja_id,
            )
        except Exception:
            pass
        if not nome_loja:
            nome_elemento = buscar_elemento_opcional(
                oferta,
                ".store-name, .name-store, .seller-name, [data-store-name]",
            )
            if nome_elemento is not None:
                nome_loja = (
                    nome_elemento.get_attribute("data-store-name")
                    or nome_elemento.get_attribute("textContent")
                    or ""
                ).strip()

        try:
            preco = decodificar_preco(
                navegador=navegador,
                oferta=oferta,
                ocr=ocr,
                cache=cache_digitos,
                oferta_id=oferta_id,
            )
        except (ErroLeituraPreco, NoSuchElementException) as erro:
            print(f"  Oferta {oferta_id} não pôde ser lida: {erro}")
            estatisticas["falhas"] += 1
            estatisticas["erros"].append({
                "ofertaId": str(oferta_id),
                "loja": str(nome_loja or "").strip(),
                "idioma": str(idioma or "").strip(),
                "estado": str(estado or "").strip().upper(),
                "extra": str(extra or "").strip(),
                "linkLoja": str(link_loja or "").strip(),
                "erro": str(erro),
            })
            continue

        ofertas.append(
            {
                "preco": preco,
                "idioma": idioma,
                "estado": estado,
                "extra": extra,
                "loja": str(nome_loja or "").strip(),
                "link_loja": str(link_loja or "").strip(),
                "oferta_id": oferta_id,
                "origem": origem,
            }
        )
        estatisticas["lidas"] += 1
    return ofertas, estatisticas


def validar_confiabilidade_coleta(
    ofertas: list[dict[str, Any]],
    estatisticas: dict[str, Any],
    origem: str,
) -> None:
    """Interrompe a cotização quando a leitura aparenta estar corrompida.

    O objetivo é preferir um item pendente a gravar um preço falso. Isso é
    especialmente importante para marketplace, onde o menor valor afeta todas
    as métricas derivadas.
    """

    detectadas = int(estatisticas.get("detectadas") or 0)
    lidas = int(estatisticas.get("lidas") or 0)
    falhas = int(estatisticas.get("falhas") or 0)

    if detectadas > 0 and lidas == 0:
        raise ErroLeituraPreco(
            f"{origem}: havia {detectadas} oferta(s), mas nenhum preço pôde ser lido com segurança."
        )

    # Se quase tudo falhou e sobrou somente um palpite, não usamos esse único
    # valor como referência de mercado.
    if detectadas >= 3 and lidas <= 1 and falhas >= 2:
        raise ErroLeituraPreco(
            f"{origem}: leitura insuficiente ({lidas}/{detectadas}); cotização mantida pendente."
        )

    valores = [o.get("preco") for o in ofertas if isinstance(o.get("preco"), Decimal)]
    if origem == "marketplace" and valores:
        padroes = [v for v in valores if _padrao_preco_suspeito(v)]
        contagem = Counter(padroes)
        repeticao = contagem.most_common(1)[0][1] if contagem else 0

        # Defesa específica contra o padrão observado na execução corrompida:
        # 1,11 / 7,11 / 11,11 / 71,11 / 111,11 / 711,11 etc.
        if len(padroes) >= 3 and len(padroes) >= max(3, int(len(valores) * 0.50)):
            raise ErroLeituraPreco(
                f"{origem}: padrão OCR artificial detectado em {len(padroes)}/{len(valores)} preços; "
                "os valores foram recusados para não contaminar a coleção."
            )
        if repeticao >= 3:
            valor, qtd = contagem.most_common(1)[0]
            raise ErroLeituraPreco(
                f"{origem}: preço suspeito {valor} repetido {qtd} vezes; cotização mantida pendente."
            )


def normalizar_url_liga(url: str, show: int) -> str:
    """Troca somente o parâmetro show, preservando a carta e a edição."""

    partes = urlsplit(url.strip())
    parametros = [(chave, valor) for chave, valor in parse_qsl(partes.query, keep_blank_values=True) if chave.lower() != "show"]
    parametros.append(("show", str(show)))
    return urlunsplit((partes.scheme or "https", partes.netloc, partes.path, urlencode(parametros), partes.fragment))


def _idioma_curto(idioma: str) -> str:
    chave = chave_texto(normalizar_idioma(idioma))
    if chave == chave_texto("Português"):
        return "BR"
    if chave == chave_texto("Inglês"):
        return "ING"
    return normalizar_idioma(idioma)


def _ajustar_estado(preco: Decimal, encontrado: str, desejado: str) -> tuple[Decimal, Decimal]:
    """Converte o preço entre estados usando a diferença direta da tabela.

    A tabela é lida como deságio em relação a NM/M. Assim, se SP=0.90 e
    NM=1.00, um preço SP estimado para NM recebe +10% (e não +11,11%).
    Isso mantém exatamente a regra operacional usada no gerenciamento.
    """
    if encontrado not in FATORES_ESTADO or desejado not in FATORES_ESTADO:
        return preco, Decimal("1")
    fator_encontrado = Decimal(str(FATORES_ESTADO[encontrado]))
    fator_desejado = Decimal(str(FATORES_ESTADO[desejado]))
    fator = Decimal("1") + (fator_desejado - fator_encontrado)
    if fator <= 0:
        return preco, Decimal("1")
    return (preco * fator).quantize(Decimal("0.01")), fator

def selecionar_ofertas_aproximadas(
    ofertas: list[dict[str, Any]],
    idioma_desejado: str | None,
    estado_desejado: str | None,
    permitir_sem_filtros: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Seleciona idioma/estado equivalentes e aplica a tabela de condição quando necessário."""

    if not ofertas:
        return [], []
    notas: list[str] = []
    candidatas = list(ofertas)

    idioma_normalizado = normalizar_idioma(idioma_desejado or "") if idioma_desejado else ""
    estado_normalizado = normalizar_estado(estado_desejado) if estado_desejado else ""

    if idioma_normalizado:
        chave_desejada = chave_texto(idioma_normalizado)
        exatas = [o for o in candidatas if o.get("idioma") and chave_texto(normalizar_idioma(str(o["idioma"]))) == chave_desejada]
        if exatas:
            candidatas = exatas
        else:
            # Português e Inglês são tratados como equivalentes quando a Liga não
            # possui a variante exata. Não há ajuste monetário por idioma.
            equivalentes = {chave_texto("Português"): "Inglês", chave_texto("Inglês"): "Português"}
            oposto = equivalentes.get(chave_desejada, "")
            alternativas = [o for o in candidatas if oposto and o.get("idioma") and chave_texto(normalizar_idioma(str(o["idioma"]))) == chave_texto(oposto)]
            sem_idioma = [o for o in candidatas if not str(o.get("idioma") or "").strip()]
            if alternativas:
                candidatas = alternativas
                notas.append(f"idioma equivalente: {idioma_normalizado} → {oposto}")
            elif sem_idioma:
                candidatas = sem_idioma
                notas.append(f"idioma desejado {idioma_normalizado}; ofertas sem identificação de idioma usadas")
            elif permitir_sem_filtros:
                notas.append("idioma não identificado/compatível; conjunto geral usado como último recurso")
            else:
                return [], notas

    estado_escolhido = ""
    if estado_normalizado:
        exatas_estado = [o for o in candidatas if str(o.get("estado") or "").upper() == estado_normalizado]
        if exatas_estado:
            candidatas = exatas_estado
            estado_escolhido = estado_normalizado
        else:
            estados_disponiveis = {
                str(o.get("estado") or "").upper()
                for o in candidatas
                if str(o.get("estado") or "").upper() in ESTADOS_ORDEM
            }
            if estados_disponiveis:
                indice_desejado = ESTADOS_ORDEM.index(estado_normalizado)
                menor_distancia = min(abs(ESTADOS_ORDEM.index(e) - indice_desejado) for e in estados_disponiveis)
                proximos = [e for e in estados_disponiveis if abs(ESTADOS_ORDEM.index(e) - indice_desejado) == menor_distancia]
                # Em empate, escolhe o estado que produz o menor preço ajustado.
                def custo_estado(estado: str) -> Decimal:
                    valores = [_ajustar_estado(o["preco"], estado, estado_normalizado)[0] for o in candidatas if str(o.get("estado") or "").upper() == estado]
                    return min(valores) if valores else Decimal("Infinity")
                estado_escolhido = min(proximos, key=custo_estado)
                candidatas = [o for o in candidatas if str(o.get("estado") or "").upper() == estado_escolhido]
                _, fator = _ajustar_estado(Decimal("100"), estado_escolhido, estado_normalizado)
                percentual = (fator - Decimal("1")) * Decimal("100")
                sinal = "+" if percentual >= 0 else ""
                notas.append(
                    f"estado desejado {estado_normalizado}; estado encontrado {estado_escolhido}; "
                    f"estimativa {sinal}{percentual.quantize(Decimal('0.01'))}%"
                )
            elif permitir_sem_filtros:
                sem_estado = [o for o in candidatas if not str(o.get("estado") or "").strip()]
                if sem_estado:
                    candidatas = sem_estado
                    notas.append("ofertas sem identificação de estado")
                else:
                    notas.append("estado da buylist não compatível; maior oferta geral usada")
            else:
                return [], notas

    ajustadas: list[dict[str, Any]] = []
    for oferta in candidatas:
        nova = dict(oferta)
        estado_encontrado = str(oferta.get("estado") or estado_escolhido or estado_normalizado).upper()
        nova["preco_original"] = oferta["preco"]
        nova["idioma_original"] = str(oferta.get("idioma") or "")
        nova["estado_original"] = str(oferta.get("estado") or estado_encontrado or "")
        nova["foi_estimado"] = False
        if estado_normalizado and estado_encontrado in ESTADOS_ORDEM:
            nova["preco"], fator = _ajustar_estado(oferta["preco"], estado_encontrado, estado_normalizado)
            nova["fator_estimativa"] = fator
            nova["foi_estimado"] = fator != Decimal("1")
        if idioma_normalizado and nova["idioma_original"]:
            nova["idioma_aproximado"] = chave_texto(normalizar_idioma(nova["idioma_original"])) != chave_texto(idioma_normalizado)
            nova["foi_estimado"] = nova["foi_estimado"] or nova["idioma_aproximado"]
        ajustadas.append(nova)
    return ajustadas, notas


def resumir_precos(
    marketplace: list[dict[str, Any]],
    buylist: list[dict[str, Any]],
    idioma: str | None,
    estado: str | None,
) -> dict[str, Any]:
    vendas, notas_venda = selecionar_ofertas_aproximadas(marketplace, idioma, estado)
    compras, notas_compra = selecionar_ofertas_aproximadas(
        buylist, idioma, estado, permitir_sem_filtros=True,
    )

    def _media(ofertas: list[dict[str, Any]], campo: str) -> Decimal | None:
        valores = [o[campo] for o in ofertas if o.get(campo) is not None]
        if not valores:
            return None
        return (sum(valores, Decimal("0")) / Decimal(len(valores))).quantize(Decimal("0.01"))

    def _mediana(ofertas: list[dict[str, Any]], campo: str) -> Decimal | None:
        valores = sorted(o[campo] for o in ofertas if o.get(campo) is not None)
        if not valores:
            return None
        meio = len(valores) // 2
        if len(valores) % 2:
            return valores[meio].quantize(Decimal("0.01"))
        return ((valores[meio - 1] + valores[meio]) / Decimal("2")).quantize(Decimal("0.01"))

    def _menores(ofertas: list[dict[str, Any]], campo: str) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
        valores = sorted(o[campo] for o in ofertas if o.get(campo) is not None)
        return tuple((valores[i] if i < len(valores) else None) for i in range(3))  # type: ignore[return-value]

    def _quantidade_participantes(ofertas: list[dict[str, Any]]) -> int:
        chaves: set[str] = set()
        for indice, oferta in enumerate(ofertas):
            loja = chave_texto(str(oferta.get("loja") or ""))
            oferta_id = str(oferta.get("oferta_id") or "").strip()
            chaves.add(f"loja:{loja}" if loja else (f"oferta:{oferta_id}" if oferta_id else f"linha:{indice}"))
        return len(chaves)

    menor, segundo_menor, terceiro_menor = _menores(vendas, "preco")
    medio = _media(vendas, "preco")
    mediana = _mediana(vendas, "preco")

    # Correção de variante da buylist: algumas cartas têm ofertas Normal e Foil
    # misturadas na mesma página. Só fazemos essa segunda checagem quando o maior
    # valor de compra ficaria acima do menor preço do marketplace, situação típica
    # do falso positivo visto em promos Foil. A variante do marketplace mais barato
    # é a referência; se ela não estiver identificada, Foil é usado apenas quando
    # a página de compra traz explicitamente essa tag.
    compras_filtradas = list(compras)
    max_compra_inicial = max((o["preco"] for o in compras_filtradas), default=None)
    if menor is not None and max_compra_inicial is not None and max_compra_inicial > menor and compras_filtradas:
        oferta_referencia = min(vendas, key=lambda o: o["preco"]) if vendas else None
        extra_ref = str((oferta_referencia or {}).get("extra") or "").strip().casefold()
        if extra_ref:
            mesma_variante = [o for o in compras_filtradas if str(o.get("extra") or "").strip().casefold() == extra_ref]
            if mesma_variante:
                compras_filtradas = mesma_variante
                notas_compra.append(f"variante da buylist igualada ao marketplace: {(oferta_referencia or {}).get('extra')}")
        else:
            foil = [o for o in compras_filtradas if str(o.get("extra") or "").strip().casefold() == "foil"]
            if foil:
                compras_filtradas = foil
                notas_compra.append("buylist acima do marketplace: apenas ofertas com tag Foil consideradas")

    venda_rapida = max((o["preco"] for o in compras_filtradas), default=None)
    minimo = (menor * Decimal(str(MINIMO))).quantize(Decimal("0.01")) if menor is not None else None

    menor_coletado, segundo_menor_coletado, terceiro_menor_coletado = _menores(vendas, "preco_original")
    medio_coletado = _media(vendas, "preco_original")
    mediana_coletada = _mediana(vendas, "preco_original")
    venda_rapida_coletado = max((o.get("preco_original", o["preco"]) for o in compras_filtradas), default=None)
    minimo_coletado = (menor_coletado * Decimal(str(MINIMO))).quantize(Decimal("0.01")) if menor_coletado is not None else None

    notas = [*notas_venda]
    notas.extend(f"buylist: {nota}" for nota in notas_compra)
    idiomas_encontrados = sorted({str(o.get("idioma_original") or o.get("idioma") or "") for o in vendas if str(o.get("idioma_original") or o.get("idioma") or "")})
    estados_encontrados = sorted({str(o.get("estado_original") or o.get("estado") or "") for o in vendas if str(o.get("estado_original") or o.get("estado") or "")})
    houve_estimativa = any(bool(o.get("foi_estimado")) for o in [*vendas, *compras_filtradas])

    idioma_normalizado = normalizar_idioma(idioma or "") if idioma else ""
    estado_normalizado = normalizar_estado(estado) if estado else ""
    chave_idioma = chave_texto(idioma_normalizado) if idioma_normalizado else ""
    vendas_especificas = [
        o for o in marketplace
        if (not chave_idioma or (o.get("idioma") and chave_texto(normalizar_idioma(str(o.get("idioma") or ""))) == chave_idioma))
        and (not estado_normalizado or str(o.get("estado") or "").upper() == estado_normalizado)
    ]
    compras_especificas = [
        o for o in buylist
        if (not chave_idioma or (o.get("idioma") and chave_texto(normalizar_idioma(str(o.get("idioma") or ""))) == chave_idioma))
        and (not estado_normalizado or str(o.get("estado") or "").upper() == estado_normalizado)
    ]

    return {
        "menor": menor,
        "segundo_menor": segundo_menor,
        "terceiro_menor": terceiro_menor,
        "medio": medio,
        "mediana": mediana,
        "minimo": minimo,
        "venda_rapida": venda_rapida,
        "menor_coletado": menor_coletado,
        "segundo_menor_coletado": segundo_menor_coletado,
        "terceiro_menor_coletado": terceiro_menor_coletado,
        "medio_coletado": medio_coletado,
        "mediana_coletada": mediana_coletada,
        "minimo_coletado": minimo_coletado,
        "venda_rapida_coletado": venda_rapida_coletado,
        "alteracao": "; ".join(dict.fromkeys(notas)),
        "quantidade_ofertas": len(vendas),
        "quantidade_buylist": len(compras_filtradas),
        "vendedores_geral": _quantidade_participantes(marketplace),
        "vendedores_especificos": _quantidade_participantes(vendas_especificas),
        "compradores_geral": _quantidade_participantes(buylist),
        "compradores_especificos": _quantidade_participantes(compras_especificas),
        "idiomas_encontrados": idiomas_encontrados,
        "estados_encontrados": estados_encontrados,
        "houve_estimativa": houve_estimativa,
        "ofertas_selecionadas": vendas,
        "buylist_selecionada": compras_filtradas,
    }


class SessaoLiga:
    """Mantém um Chrome independente por worker e reutiliza a mesma aba."""

    def __init__(self, worker_id: int = 1, atraso_inicial: float = 0.0) -> None:
        self.worker_id = max(1, int(worker_id))
        self.atraso_inicial = max(0.0, float(atraso_inicial))
        self._pasta_perfil_temporario: Path | None = None
        self.navegador: webdriver.Chrome | None = None
        self.processo: subprocess.Popen[Any] | None = None
        self.aba_base: str | None = None
        self._cache: dict[tuple[str, str, str], dict[str, Any]] = {}
        # OCR e cache persistem durante toda a vida do worker.
        self._ocr: ddddocr.DdddOcr | None = None
        self._cache_digitos: dict[str, str] = {}

    def __enter__(self) -> "SessaoLiga":
        if self.atraso_inicial:
            time.sleep(self.atraso_inicial)
        print(f"[Worker {self.worker_id}] Abrindo Chrome independente...")
        self._pasta_perfil_temporario = Path(tempfile.mkdtemp(prefix=f"nexus-tcg-w{self.worker_id}-"))
        self.navegador, self.processo = abrir_navegador("about:blank", self._pasta_perfil_temporario)
        self.aba_base = self.navegador.current_window_handle
        if USAR_OCR:
            self._ocr = ddddocr.DdddOcr(show_ad=False, beta=True)
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.fechar()

    def _exigir_navegador(self) -> webdriver.Chrome:
        if self.navegador is None:
            raise RuntimeError("A sessão da Liga ainda não foi aberta.")
        return self.navegador

    def _coletar_pagina(self, url: str, origem: str, coletar_dados: bool) -> tuple[dict[str, str], list[dict[str, Any]], dict[str, Any]]:
        """Navega na mesma aba do worker e usa espera adaptativa, sem sleep fixo."""
        ultimo_erro: Exception | None = None
        for tentativa in range(1, TENTATIVAS + 1):
            navegador = self._exigir_navegador()
            try:
                print(f"  [W{self.worker_id}] Abrindo {origem} (tentativa {tentativa}/{TENTATIVAS})...")
                if self.aba_base in navegador.window_handles:
                    navegador.switch_to.window(self.aba_base)
                # Evita que vários workers façam requisições sincronizadas à Liga.
                # Não corrige OCR (isso é tratado acima), mas reduz a chance de
                # verificações de segurança quando 3-5 Chromes estão ativos.
                if JITTER_WORKERS:
                    time.sleep(random.uniform(0.0, JITTER_WORKERS))
                navegador.get(url)
                esperar_pagina(navegador)
                esperar_ofertas_estaveis(navegador)
                mostrar_todas_as_ofertas(navegador)
                dados = obter_dados_carta(navegador) if coletar_dados else {}
                ofertas, estatisticas = obter_todas_as_ofertas(
                    navegador, origem, ocr=self._ocr, cache_digitos=self._cache_digitos
                )
                estatisticas["worker"] = self.worker_id
                return dados, ofertas, estatisticas
            except Exception as erro:
                ultimo_erro = erro
                if tentativa < TENTATIVAS:
                    print(f"  [W{self.worker_id}] Falha temporária: {erro}. Tentando novamente...")
                    time.sleep(min(1.0, INTERVALO_TENTATIVA))
        if ultimo_erro is not None:
            raise ultimo_erro
        raise RuntimeError("Falha desconhecida ao coletar página da Liga.")

    def consultar_carta(self, url: str, idioma: str, estado: str) -> dict[str, Any]:
        idioma_normalizado = normalizar_idioma(idioma)
        estado_normalizado = normalizar_estado(estado)
        chave = (normalizar_url_liga(url, 1), chave_texto(idioma_normalizado), estado_normalizado)
        if chave in self._cache:
            return dict(self._cache[chave])

        dados, marketplace, stats_marketplace = self._coletar_pagina(normalizar_url_liga(url, 1), "marketplace", True)
        validar_confiabilidade_coleta(marketplace, stats_marketplace, "marketplace")
        _, buylist, stats_buylist = self._coletar_pagina(normalizar_url_liga(url, 10), "buylist", False)
        # A buylist não define o Menor Liga, mas também não aceitamos uma página
        # que tinha ofertas e terminou sem nenhuma leitura válida.
        validar_confiabilidade_coleta(buylist, stats_buylist, "buylist")
        precos = resumir_precos(marketplace, buylist, idioma_normalizado, estado_normalizado)
        resultado = {
            **dados,
            **precos,
            "idioma": idioma_normalizado,
            "estado": estado_normalizado,
            "marketplace": marketplace,
            "buylist": buylist,
            "coleta": {"marketplace": stats_marketplace, "buylist": stats_buylist},
        }
        self._cache[chave] = dict(resultado)
        return resultado

    def consultar_booster(self, url: str) -> dict[str, Any]:
        chave = (normalizar_url_liga(url, 1), "BOOSTER", "")
        if chave in self._cache:
            return dict(self._cache[chave])
        dados, marketplace, stats_marketplace = self._coletar_pagina(normalizar_url_liga(url, 1), "marketplace", True)
        validar_confiabilidade_coleta(marketplace, stats_marketplace, "marketplace")
        _, buylist, stats_buylist = self._coletar_pagina(normalizar_url_liga(url, 10), "buylist", False)
        validar_confiabilidade_coleta(buylist, stats_buylist, "buylist")
        valores_venda = sorted(o["preco"] for o in marketplace if o.get("preco") is not None)
        valores_compra = [o["preco"] for o in buylist if o.get("preco") is not None]
        menor = valores_venda[0] if valores_venda else None
        segundo_menor = valores_venda[1] if len(valores_venda) > 1 else None
        terceiro_menor = valores_venda[2] if len(valores_venda) > 2 else None
        medio = None
        mediana = None
        if valores_venda:
            medio = (sum(valores_venda, Decimal("0")) / Decimal(len(valores_venda))).quantize(Decimal("0.01"))
            meio = len(valores_venda) // 2
            mediana = (
                valores_venda[meio]
                if len(valores_venda) % 2
                else (valores_venda[meio - 1] + valores_venda[meio]) / Decimal("2")
            ).quantize(Decimal("0.01"))
        venda_rapida = max(valores_compra, default=None)
        minimo = (menor * Decimal(str(MINIMO))).quantize(Decimal("0.01")) if menor is not None else None

        def quantidade_participantes(ofertas: list[dict[str, Any]]) -> int:
            chaves: set[str] = set()
            for indice, oferta in enumerate(ofertas):
                loja = chave_texto(str(oferta.get("loja") or ""))
                oferta_id = str(oferta.get("oferta_id") or "").strip()
                chaves.add(f"loja:{loja}" if loja else (f"oferta:{oferta_id}" if oferta_id else f"linha:{indice}"))
            return len(chaves)
        resultado = {
            **dados,
            "menor": menor,
            "segundo_menor": segundo_menor,
            "terceiro_menor": terceiro_menor,
            "medio": medio,
            "mediana": mediana,
            "minimo": minimo,
            "venda_rapida": venda_rapida,
            "menor_coletado": menor,
            "segundo_menor_coletado": segundo_menor,
            "terceiro_menor_coletado": terceiro_menor,
            "medio_coletado": medio,
            "mediana_coletada": mediana,
            "minimo_coletado": minimo,
            "venda_rapida_coletado": venda_rapida,
            "idiomas_encontrados": sorted({str(o.get("idioma") or "") for o in marketplace if str(o.get("idioma") or "")}),
            "estados_encontrados": sorted({str(o.get("estado") or "") for o in marketplace if str(o.get("estado") or "")}),
            "houve_estimativa": False,
            "alteracao": "",
            "quantidade_ofertas": len(valores_venda),
            "quantidade_buylist": len(valores_compra),
            "vendedores_geral": quantidade_participantes(marketplace),
            "vendedores_especificos": quantidade_participantes(marketplace),
            "compradores_geral": quantidade_participantes(buylist),
            "compradores_especificos": quantidade_participantes(buylist),
            "marketplace": marketplace,
            "buylist": buylist,
            "coleta": {"marketplace": stats_marketplace, "buylist": stats_buylist},
        }
        self._cache[chave] = dict(resultado)
        return resultado

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
        self._ocr = None
        self._cache_digitos.clear()
        if self._pasta_perfil_temporario is not None:
            for _ in range(5):
                shutil.rmtree(self._pasta_perfil_temporario, ignore_errors=True)
                if not self._pasta_perfil_temporario.exists():
                    break
                time.sleep(0.4)
            self._pasta_perfil_temporario = None


def formatar_decimal_csv(valor: Decimal | None) -> str:
    if valor is None:
        return ""
    return f"{valor.quantize(Decimal('0.01')):.2f}".replace(".", ",")


def valor_preco(dados: dict[str, Any], modo: str) -> Decimal | None:
    return dados.get("medio") if modo == "media" else dados.get("menor")


def baixar_imagem(url: str, nome: str) -> str:
    """Baixa a imagem somente se ainda não existir uma equivalente."""

    if not url or not nome:
        return ""
    PASTA_IMAGENS.mkdir(parents=True, exist_ok=True)
    chave = chave_texto(nome)
    extensoes = {".jpg", ".jpeg", ".png", ".webp", ".avif"}
    for arquivo in PASTA_IMAGENS.iterdir():
        if arquivo.is_file() and arquivo.suffix.lower() in extensoes and chave_texto(arquivo.stem) == chave:
            return arquivo.name

    url_absoluta = urljoin("https://www.ligapokemon.com.br/", url)
    extensao = Path(urlparse(url_absoluta).path).suffix.lower()
    if extensao not in extensoes:
        extensao = ".jpg"
    nome_seguro = re.sub(r'[\\/:*?"<>|]+', "-", nome).strip(" .") or "imagem"
    destino = PASTA_IMAGENS / f"{nome_seguro}{extensao}"
    try:
        requisicao = Request(url_absoluta, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(requisicao, timeout=45) as resposta:
            destino.write_bytes(resposta.read())
        return destino.name
    except Exception as erro:
        print(f"  Aviso: imagem não baixada ({erro}).")
        return ""
