from __future__ import annotations

import importlib.util
import json
import re
import statistics
import subprocess
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


def garantir_dependencias() -> None:
    """Instala só as duas bibliotecas HTTP/HTML usadas neste teste."""
    dependencias = {
        "requests": "requests>=2.31",
        "bs4": "beautifulsoup4>=4.12",
    }
    faltando = [pacote for modulo, pacote in dependencias.items() if importlib.util.find_spec(modulo) is None]
    if faltando:
        print("Dependências do teste MYP ausentes. Instalando:")
        for pacote in faltando:
            print(f"  - {pacote}")
        subprocess.check_call([sys.executable, "-m", "pip", "install", *faltando])


def texto_limpo(valor: Any) -> str:
    return re.sub(r"\s+", " ", str(valor or "")).strip()


def sem_acentos(valor: str) -> str:
    normalizado = unicodedata.normalize("NFKD", valor or "")
    return "".join(c for c in normalizado if not unicodedata.combining(c))


def chave(valor: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", sem_acentos(valor).upper())


def normalizar_url(url: str) -> str:
    url = texto_limpo(url)
    if not url:
        raise ValueError("Link vazio.")
    if not re.match(r"^https?://", url, flags=re.I):
        url = "https://" + url
    partes = urlsplit(url)
    host = (partes.hostname or "").lower()
    if host not in {"mypcards.com", "www.mypcards.com"}:
        raise ValueError("Use um link do mypcards.com.")
    if "/pokemon/produto/" not in partes.path.lower():
        raise ValueError("O link precisa ser de uma página de produto Pokémon da MYP.")
    # Remove fragmentos e parâmetros de rastreamento. Mantém a URL limpa do produto.
    return urlunsplit((partes.scheme or "https", partes.netloc, partes.path, "", ""))


def baixar_html(url: str) -> tuple[str, str, int]:
    import requests

    cabecalhos = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/151.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1",
    }

    with requests.Session() as sessao:
        resposta = sessao.get(url, headers=cabecalhos, timeout=25, allow_redirects=True)
        status = resposta.status_code
        if status == 403:
            raise RuntimeError(
                "A MYP respondeu 403 para esta requisição. Isso não é CORS (CORS é bloqueio do navegador); "
                "é o servidor recusando a requisição HTTP. Tente novamente mais tarde ou a partir do backend real."
            )
        resposta.raise_for_status()
        html = resposta.text
        if len(html) < 3000:
            raise RuntimeError(f"HTML pequeno demais ({len(html)} bytes); a página pode ter sido bloqueada ou redirecionada.")
        return html, resposta.url, status


def _strings(soup) -> list[str]:
    return [texto_limpo(x) for x in soup.stripped_strings if texto_limpo(x)]


def valor_apos_rotulo(strings: list[str], rotulo: str) -> str:
    alvo = chave(rotulo)
    for i, item in enumerate(strings):
        item_key = chave(item)
        if item_key == alvo:
            if i + 1 < len(strings):
                return strings[i + 1]
        if item_key.startswith(alvo) and len(item_key) > len(alvo):
            # Ex.: "Tipo Energia Incolor" ou "Data de lançamento 31/03/2023"
            padrao = re.compile(r"^\s*" + re.escape(rotulo) + r"\s*[:\-]?\s*(.+)$", re.I)
            m = padrao.match(item)
            if m:
                return texto_limpo(m.group(1))
    return ""


def extrair_titulo_numero(soup, strings: list[str]) -> tuple[str, str]:
    titulo = ""
    for h1 in soup.find_all("h1"):
        candidato = texto_limpo(h1.get_text(" ", strip=True))
        if candidato and candidato.lower() not in {"pokemon", "pokémon"}:
            titulo = candidato
            if re.search(r"\([^)]*[0-9A-Za-z-]+\s*/\s*[0-9A-Za-z-]+[^)]*\)", candidato):
                break
    if not titulo:
        for item in strings:
            if re.search(r"\([^)]*[0-9A-Za-z-]+\s*/\s*[0-9A-Za-z-]+[^)]*\)", item):
                titulo = item
                break

    numero = ""
    m = re.search(r"\(([^()]*(?:[0-9A-Za-z-]+)\s*/\s*(?:[0-9A-Za-z-]+)[^()]*)\)", titulo)
    if m:
        numero = texto_limpo(m.group(1))
        numero = re.sub(r"\s*/\s*", "/", numero)

    nome = re.sub(r"\s*\([^()]*\)\s*$", "", titulo).strip()
    # Alguns títulos trazem tradução depois de '/'. Mantemos o nome principal PT-BR.
    if " / " in nome:
        nome = nome.split(" / ", 1)[0].strip()
    return nome, numero


def extrair_edicao(valor: str) -> tuple[str, str]:
    valor = texto_limpo(valor)
    if not valor:
        return "", ""
    m = re.match(r"^(.*?)\s*\(([^()]+)\)\s*$", valor)
    if m:
        return texto_limpo(m.group(1)), texto_limpo(m.group(2))
    return valor, ""


# Coleções que o Vault TCG trabalha hoje. A identificação usa o nome retornado pela MYP.
COLECOES_POR_ERA = {
    "MegaEvolução": {
        "Megaevolução", "Fogo Fantasmagórico", "Heróis Excelsos", "Equilíbrio Perfeito",
        "Caos Ascendente", "Escuridão Absoluta",
    },
    "Scarlet Violet": {
        "Escarlate e Violeta", "Evoluções em Paldea", "Obsidiana em Chamas", "151",
        "Fenda Paradoxal", "Destinos de Paldea", "Forças Temporais", "Máscaras do Crepúsculo",
        "Fábulas Nebulosas", "Coroa Estelar", "Centelha Surpreendente", "Evoluções Prismáticas",
        "Amigos de Jornada", "Rivais Predestinados", "Fogo Branco", "Raio Negro",
    },
    "Sword and Shield": {
        "Espada e Escudo", "Rixa Rebelde", "Escuridão Incandescente", "Caminho do Campeão",
        "Voltagem Vívida", "Destinos Brilhantes", "Estilos de Batalha", "Reinado Arrepiante",
        "Céus em Evolução", "Golpe Fusão", "Astros Cintilantes", "Pokémon GO",
        "Origem Perdida", "Tempestade Prateada", "Zenith da Coroa", "Coroa de Zenith",
    },
    "Sun And Moon": {
        "Sol e Lua", "Guardiões Ascendentes", "Sombras Ardentes", "Lendas Luminescentes",
        "Invasão Carmim", "Ultra Prisma", "Luz Proibida", "Tempestade Celestial",
        "Dragões Soberanos", "Trovões Perdidos", "União de Aliados", "Detetive Pikachu",
        "Elos Inquebráveis", "Mentes Unidas", "Destinos Ocultos", "Eclipse Cósmico",
    },
    "XY": {
        "XY", "Flash de Fogo", "Punhos Furiosos", "Forças Fantasmagóricas", "Conflito Primitivo",
        "Céus Estrondosos", "Origens Ancestrais", "Turbo Revolução", "Turbo Colisão",
        "Fusão de Destinos", "Cerco de Vapor", "Evoluções", "Gerações",
    },
    "Black And White": {
        "Black & White", "Black and White", "Preto e Branco", "Poderes Emergentes", "Vitórias Nobres",
        "Próximos Destinos", "Exploradores da Escuridão", "Dragões Exaltados", "Fronteiras Cruzadas",
        "Tempestade de Plasma", "Congelamento de Plasma", "Explosão de Plasma", "Tesouros Lendários",
    },
}


def inferir_era(colecao: str, codigo_edicao: str, ano: int | None) -> str:
    k_col = chave(colecao)
    for era, nomes in COLECOES_POR_ERA.items():
        if any(chave(nome) == k_col or chave(nome) in k_col or k_col in chave(nome) for nome in nomes):
            return era

    codigo = chave(codigo_edicao)
    # Fallback pelos códigos/padrões modernos mais comuns.
    if codigo.startswith(("ME", "PBL", "PFL", "PHE", "PER", "CRI")):
        return "MegaEvolução"
    if codigo.startswith(("SV", "PAF", "TEF", "TWM", "SFA", "SCR", "SSP", "PRE", "JTG", "DRI")):
        return "Scarlet Violet"
    if codigo.startswith(("SWSH", "SSH", "RCL", "DAA", "VIV", "BST", "CRE", "EVS", "FST", "BRS", "ASR", "LOR", "SIT", "CRZ")):
        return "Sword and Shield"
    if codigo.startswith(("SM", "SUM", "GRI", "BUS", "CIN", "UPR", "FLI", "CES", "LOT", "TEU", "UNB", "UNM", "CEC")):
        return "Sun And Moon"
    if codigo.startswith(("XY", "EVO", "STS", "FCO", "BKP", "BKT", "AOR", "ROS", "PRC")):
        return "XY"
    if codigo.startswith(("BW", "PLS", "PLF", "PLB", "LTR")):
        return "Black And White"

    # Último fallback por ano, útil só quando a coleção é desconhecida no mapa.
    if ano is not None:
        if ano >= 2025:
            return "MegaEvolução" if "MEGA" in k_col else "Scarlet Violet"
        if ano >= 2023:
            return "Scarlet Violet"
        if ano >= 2020:
            return "Sword and Shield"
        if ano >= 2017:
            return "Sun And Moon"
        if ano >= 2014:
            return "XY"
        if ano >= 2011:
            return "Black And White"
    return "Não identificado"


def inferir_grupo(tipo_carta: str) -> str:
    k = chave(tipo_carta)
    if any(x in k for x in ("SUPORTE", "APOIADOR", "ITEM", "ESTADIO", "FERRAMENTA", "TRAINER", "TREINADOR")):
        return "Treinador"
    if "ENERGIA" in k or "ENERGY" in k:
        return "Energia"
    if any(x in k for x in ("BASICO", "BASIC", "STAGE", "ESTAGIO", "POKEMON", "EVOLUCAO", "EX", "GX", "VMAX", "VSTAR")):
        return "Pokémon"
    return "Não identificado"


def inferir_classe(nome: str, raridade: str, grupo: str, era: str) -> str:
    n = chave(nome)
    r = chave(raridade)

    # Raridades modernas da MYP que correspondem diretamente à taxonomia usada no Vault.
    if "RARAHIPER" in r or "HYPERRARE" in r or "DOURADA" in r or "GOLD" in r:
        return "Golden"
    if "ILUSTRACAORARAESPECIAL" in r or "SPECIALILLUSTRATIONRARE" in r:
        return "Art Secreta"
    if "ILUSTRACAORARA" in r or "ILLUSTRATIONRARE" in r:
        return "Ilustração Rara"
    if "ULTRARARA" in r or "ULTRARARE" in r:
        return "Full Art"
    if "RARAARCOIRIS" in r or "RAINBOW" in r:
        return "Art Secreta"
    if "RARASECRETA" in r or "SECRETRARE" in r:
        return "Art Secreta"

    # Subclasses históricas identificáveis pelo próprio nome da carta.
    if grupo == "Pokémon":
        if "MEGA" in n and (n.endswith("EX") or "EX" in n):
            return "Mega Ex"
        if n.endswith("EX") or "POKEMONEX" in n:
            return "Ex"
        if n.endswith("GX") or "GX" in n:
            return "GX"
        if n.endswith("VMAX") or "VMAX" in n:
            return "VMAX"
        if n.endswith("VSTAR") or "VSTAR" in n:
            return "VSTAR"
        if re.search(r"\bV\b", nome, flags=re.I):
            return "V"
        if "TURBO" in n or "BREAK" in n:
            return "Turbo"
        if "RADIANTE" in n or "RADIANT" in n:
            return "Radiante"

    return "Normal"


def extrair_imagem(soup, nome: str) -> str:
    for seletor, atributo in (
        ('meta[property="og:image"]', "content"),
        ('meta[name="twitter:image"]', "content"),
        ('meta[property="twitter:image"]', "content"),
    ):
        tag = soup.select_one(seletor)
        if tag and tag.get(atributo):
            url = texto_limpo(tag.get(atributo))
            if url.startswith("http"):
                return url

    candidatos: list[tuple[int, str]] = []
    nome_k = chave(nome)
    for img in soup.find_all("img"):
        src = texto_limpo(img.get("src") or img.get("data-src") or img.get("data-lazy-src"))
        if not src or not src.startswith("http"):
            continue
        alt = texto_limpo(img.get("alt"))
        score = 0
        if "img.mypcards.com" in src:
            score += 3
        if nome_k and nome_k in chave(alt):
            score += 5
        if any(p in src.lower() for p in ("produto", "products", "cards", "pokemon")):
            score += 2
        if score:
            candidatos.append((score, src))
    candidatos.sort(reverse=True)
    return candidatos[0][1] if candidatos else ""


def parse_brl(texto: str) -> float | None:
    m = re.search(r"R\$\s*([0-9][0-9\.]*[\.,][0-9]{2}|[0-9]+)", texto, flags=re.I)
    if not m:
        return None
    bruto = m.group(1).strip()
    if "," in bruto:
        bruto = bruto.replace(".", "").replace(",", ".")
    elif bruto.count(".") > 1:
        partes = bruto.split(".")
        bruto = "".join(partes[:-1]) + "." + partes[-1]
    try:
        return round(float(bruto), 2)
    except ValueError:
        return None


def extrair_ofertas(soup) -> list[dict[str, Any]]:
    padrao_estado = re.compile(r"\b(M|NM|SP|MP|HP|D)\s*-", flags=re.I)
    padrao_qtd = re.compile(r"\b(\d+)\s*(?:un\.?|unidade(?:s)?)\b", flags=re.I)
    ofertas: list[dict[str, Any]] = []
    vistos: set[tuple[Any, ...]] = set()

    # Caminho principal: linhas de tabela.
    for tr in soup.find_all("tr"):
        partes = [texto_limpo(x) for x in tr.stripped_strings if texto_limpo(x)]
        if not partes:
            continue
        estado_idx = next((i for i, p in enumerate(partes) if padrao_estado.search(p)), None)
        if estado_idx is None:
            continue
        preco_idx = next((i for i in range(estado_idx + 1, len(partes)) if parse_brl(partes[i]) is not None), None)
        if preco_idx is None:
            continue
        estado_match = padrao_estado.search(partes[estado_idx])
        estado = estado_match.group(1).upper() if estado_match else ""
        preco = parse_brl(partes[preco_idx])
        qtd = 1
        for p in partes[estado_idx + 1:preco_idx + 1]:
            mq = padrao_qtd.search(p)
            if mq:
                qtd = int(mq.group(1))
                break
        vendedor = partes[0] if estado_idx >= 1 else ""
        acabamento = ""
        if estado_idx >= 2:
            possivel = partes[estado_idx - 1]
            if chave(possivel) not in {chave(vendedor)} and len(possivel) <= 80:
                acabamento = possivel
        assinatura = (vendedor, acabamento, estado, qtd, preco)
        if preco is not None and assinatura not in vistos:
            vistos.add(assinatura)
            ofertas.append({
                "vendedor": vendedor,
                "acabamento": acabamento,
                "estado": estado,
                "quantidade": qtd,
                "preco": preco,
            })

    if ofertas:
        return ofertas

    # Fallback para páginas em que as ofertas não usam <tr>.
    strings = _strings(soup)
    for i, item in enumerate(strings):
        me = padrao_estado.search(item)
        if not me:
            continue
        estado = me.group(1).upper()
        preco = None
        qtd = 1
        preco_idx = None
        for j in range(i + 1, min(i + 7, len(strings))):
            mq = padrao_qtd.search(strings[j])
            if mq:
                qtd = int(mq.group(1))
            p = parse_brl(strings[j])
            if p is not None:
                preco = p
                preco_idx = j
                break
        if preco is None:
            continue
        vendedor = strings[i - 1] if i > 0 else ""
        acabamento = ""
        if i > 1 and len(strings[i - 1]) <= 60 and chave(strings[i - 1]) in {
            "FOIL", "REVERSEFOIL", "FULLART", "ALTEREDART", "HOLO", "HOLOGRAFICA"
        }:
            acabamento = strings[i - 1]
            vendedor = strings[i - 2]
        assinatura = (vendedor, acabamento, estado, qtd, preco)
        if assinatura not in vistos:
            vistos.add(assinatura)
            ofertas.append({
                "vendedor": vendedor,
                "acabamento": acabamento,
                "estado": estado,
                "quantidade": qtd,
                "preco": preco,
            })
    return ofertas


def extrair_precos_resumo(strings: list[str]) -> list[float]:
    """Extrai os números-resumo exibidos pela MYP sem inventar rótulos que o HTML não fornece claramente."""
    inicio = -1
    fim = len(strings)
    for i, s in enumerate(strings):
        if chave(s).startswith("EDICAO"):
            inicio = i
            break
    if inicio < 0:
        return []
    for i in range(inicio + 1, min(len(strings), inicio + 80)):
        if chave(strings[i]) in {"LOJISTASECERTIFICADOS", "DEMAISVENDEDORES", "OUTRASEDICOES"}:
            fim = i
            break
    valores: list[float] = []
    for s in strings[inicio + 1:fim]:
        for bruto in re.findall(r"R\$\s*[0-9][0-9\.]*[\.,][0-9]{2}", s, flags=re.I):
            p = parse_brl(bruto)
            if p is not None and p not in valores:
                valores.append(p)
        if len(valores) >= 6:
            break
    return valores


def resumo_ofertas(ofertas: list[dict[str, Any]]) -> dict[str, Any]:
    precos = sorted(float(x["preco"]) for x in ofertas if x.get("preco") is not None)
    if not precos:
        return {
            "ofertas_lidas": 0,
            "menor": None,
            "segundo_menor": None,
            "terceiro_menor": None,
            "media": None,
            "mediana": None,
            "por_estado": {},
        }

    por_estado: dict[str, dict[str, Any]] = {}
    for estado in ("M", "NM", "SP", "MP", "HP", "D"):
        vals = sorted(float(x["preco"]) for x in ofertas if x.get("estado") == estado and x.get("preco") is not None)
        if vals:
            por_estado[estado] = {
                "quantidade_de_anuncios": len(vals),
                "menor": round(vals[0], 2),
                "media": round(statistics.mean(vals), 2),
                "mediana": round(statistics.median(vals), 2),
            }

    return {
        "ofertas_lidas": len(precos),
        "menor": round(precos[0], 2),
        "segundo_menor": round(precos[1], 2) if len(precos) > 1 else None,
        "terceiro_menor": round(precos[2], 2) if len(precos) > 2 else None,
        "media": round(statistics.mean(precos), 2),
        "mediana": round(statistics.median(precos), 2),
        "por_estado": por_estado,
    }


def extrair_dados_html(html: str, url_final: str) -> dict[str, Any]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    strings = _strings(soup)

    nome, numeracao = extrair_titulo_numero(soup, strings)
    codigo_myp = valor_apos_rotulo(strings, "Código")
    edicao_bruta = valor_apos_rotulo(strings, "Edição")
    colecao, codigo_edicao = extrair_edicao(edicao_bruta)
    raridade = valor_apos_rotulo(strings, "Raridade")
    tipo_carta = valor_apos_rotulo(strings, "Tipo Carta")
    tipo_energia = valor_apos_rotulo(strings, "Tipo Energia")
    data_lancamento = valor_apos_rotulo(strings, "Data de lançamento")
    ilustrador = valor_apos_rotulo(strings, "Ilustrador")
    hp = valor_apos_rotulo(strings, "HP")

    ano = None
    if data_lancamento:
        m_ano = re.search(r"\b(19|20)\d{2}\b", data_lancamento)
        if m_ano:
            ano = int(m_ano.group(0))

    # Fallback da numeração pelo código interno MYP.
    if not numeracao and codigo_myp and "_" in codigo_myp:
        possivel = codigo_myp.rsplit("_", 1)[-1]
        if "/" in possivel:
            numeracao = possivel

    era = inferir_era(colecao, codigo_edicao, ano)
    grupo = inferir_grupo(tipo_carta)
    classe = inferir_classe(nome, raridade, grupo, era)
    imagem = extrair_imagem(soup, nome)
    ofertas = extrair_ofertas(soup)
    precos = resumo_ofertas(ofertas)
    resumo_myp = extrair_precos_resumo(strings)

    # Para Treinador/Energia, Tipo de energia costuma vir como n/a; no Vault o campo "Tipo"
    # só é realmente útil para Pokémon. Preservamos o valor cru também.
    tipo = tipo_energia if chave(tipo_energia) not in {"", "NA", "N/A"} else ""

    return {
        "fonte": "MYP Cards",
        "link_myp": url_final,
        "nome": nome,
        "numeracao": numeracao,
        "ano": ano,
        "era": era,
        "colecao": colecao,
        "codigo_edicao": codigo_edicao,
        "grupo": grupo,
        "classe": classe,
        "tipo": tipo,
        "tipo_carta_myp": tipo_carta,
        "raridade_myp": raridade,
        "codigo_myp": codigo_myp,
        "data_lancamento": data_lancamento,
        "hp": hp,
        "ilustrador": ilustrador,
        "imagem": imagem,
        # Estes 3 dados são propriedade da cópia física do usuário, não do produto genérico da MYP.
        "idioma": None,
        "estado": None,
        "integridade": None,
        "campos_manuais": ["idioma", "estado", "integridade"],
        "precos_resumo_exibidos_myp": resumo_myp,
        "precos_calculados_das_ofertas_visiveis": precos,
        "ofertas_visiveis": ofertas,
    }


def dinheiro(valor: Any) -> str:
    if valor is None:
        return "—"
    return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def imprimir_resultado(dados: dict[str, Any], status_http: int) -> None:
    print("\n" + "=" * 72)
    print("TESTE MYP — CONSULTA DIRETA POR HTTP (SEM CHROME / SEM SELENIUM)")
    print("=" * 72)
    print(f"HTTP: {status_http}")
    print(f"Link: {dados['link_myp']}")

    print("\nDADOS PARA O VAULT TCG")
    print("-" * 72)
    campos = [
        ("Nome", dados.get("nome")),
        ("Numeração", dados.get("numeracao")),
        ("Ano", dados.get("ano")),
        ("Era", dados.get("era")),
        ("Coleção", dados.get("colecao")),
        ("Código da edição", dados.get("codigo_edicao")),
        ("Grupo", dados.get("grupo")),
        ("Classe", dados.get("classe")),
        ("Tipo", dados.get("tipo")),
        ("Imagem", dados.get("imagem")),
    ]
    for rotulo, valor in campos:
        print(f"{rotulo:18}: {valor if valor not in (None, '') else '—'}")

    print("\nMETADADOS EXTRAS DA MYP")
    print("-" * 72)
    extras = [
        ("Código MYP", dados.get("codigo_myp")),
        ("Tipo carta MYP", dados.get("tipo_carta_myp")),
        ("Raridade MYP", dados.get("raridade_myp")),
        ("Lançamento", dados.get("data_lancamento")),
        ("HP", dados.get("hp")),
        ("Ilustrador", dados.get("ilustrador")),
    ]
    for rotulo, valor in extras:
        print(f"{rotulo:18}: {valor if valor not in (None, '') else '—'}")

    print("\nPREÇOS CALCULADOS DAS OFERTAS VISÍVEIS")
    print("-" * 72)
    p = dados["precos_calculados_das_ofertas_visiveis"]
    print(f"Ofertas lidas       : {p['ofertas_lidas']}")
    print(f"Menor preço         : {dinheiro(p['menor'])}")
    print(f"2º menor preço      : {dinheiro(p['segundo_menor'])}")
    print(f"3º menor preço      : {dinheiro(p['terceiro_menor'])}")
    print(f"Média               : {dinheiro(p['media'])}")
    print(f"Mediana             : {dinheiro(p['mediana'])}")
    for estado, info in p.get("por_estado", {}).items():
        print(
            f"  {estado:<2} -> menor {dinheiro(info['menor'])} | "
            f"média {dinheiro(info['media'])} | mediana {dinheiro(info['mediana'])} | "
            f"{info['quantidade_de_anuncios']} anúncio(s)"
        )

    if dados.get("precos_resumo_exibidos_myp"):
        print("\nNÚMEROS-RESUMO EXIBIDOS PELA MYP")
        print("-" * 72)
        print(" | ".join(dinheiro(x) for x in dados["precos_resumo_exibidos_myp"]))
        print("(Mantidos sem rótulo para não inventar o significado de cada indicador da interface.)")

    print("\nCAMPOS QUE O LINK NÃO CONSEGUE SABER")
    print("-" * 72)
    print("Idioma, Estado e Integridade pertencem à SUA cópia física; ficam para seleção manual.")


def main() -> None:
    garantir_dependencias()
    print("=" * 72)
    print("TESTE MYP — sem abrir Chrome")
    print("=" * 72)
    link = input("Cole o link de uma carta Pokémon da MYP: ").strip()
    url = normalizar_url(link)

    print("\nConsultando a MYP diretamente por HTTP...")
    html, url_final, status = baixar_html(url)
    dados = extrair_dados_html(html, url_final)
    imprimir_resultado(dados, status)

    destino = Path(__file__).with_name("resultado_myp.json")
    destino.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nJSON completo salvo em: {destino}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelado.")
    except Exception as erro:
        print(f"\nERRO: {erro}")
        sys.exit(1)
