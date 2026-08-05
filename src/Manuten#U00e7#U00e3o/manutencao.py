from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import tempfile
import time
import zipfile
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from configuracao import (
    ARQUIVO_ATUALIZACAO,
    ARQUIVO_PERFIL,
    COLUNAS_ALBUNS,
    COLUNAS_BOOSTERS,
    COLUNAS_CARTAS,
    COLUNAS_KITS,
    chave_texto,
    pasta_colecoes,
    pasta_nao_formatadas,
)
from liga import (
    SessaoLiga,
    baixar_imagem,
    formatar_decimal_csv,
    normalizar_estado,
    normalizar_idioma,
    valor_preco,
)

MODO_MENOR = "menor"
MODO_MEDIA = "media"


def texto(valor: Any) -> str:
    return "" if valor is None else str(valor).strip()


def primeiro(linha: dict[str, Any], *nomes: str) -> str:
    for nome in nomes:
        valor = texto(linha.get(nome))
        if valor:
            return valor
    return ""


def inteiro(valor: Any, padrao: int = 1) -> int:
    encontrado = re.search(r"\d+", texto(valor))
    return max(1, int(encontrado.group(0))) if encontrado else padrao


def decimal(valor: Any) -> Decimal | None:
    bruto = texto(valor)
    if not bruto:
        return None
    bruto = bruto.replace("R$", "").replace(" ", "")
    if "," in bruto:
        bruto = bruto.replace(".", "").replace(",", ".")
    try:
        return Decimal(bruto)
    except InvalidOperation:
        return None


def ler_csv(caminho: Path) -> list[dict[str, str]]:
    if not caminho.is_file():
        return []
    with caminho.open("r", encoding="utf-8-sig", newline="") as arquivo:
        return [dict(linha) for linha in csv.DictReader(arquivo)]


def escrever_csv(caminho: Path, colunas: list[str], linhas: list[dict[str, Any]]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_name(f".{caminho.name}.tmp")
    with temporario.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.DictWriter(
            arquivo,
            fieldnames=colunas,
            extrasaction="ignore",
            lineterminator="\n",
        )
        escritor.writeheader()
        escritor.writerows(linhas)
    temporario.replace(caminho)


def ler_json(caminho: Path) -> dict[str, Any]:
    if not caminho.is_file():
        return {}
    dados = json.loads(caminho.read_text(encoding="utf-8-sig"))
    return dados if isinstance(dados, dict) else {}


def escrever_json(caminho: Path, dados: dict[str, Any]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_name(f".{caminho.name}.tmp")
    temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    temporario.replace(caminho)


def _encontrar_raiz(pasta: Path, marcador: str) -> Path | None:
    if (pasta / marcador).is_file():
        return pasta
    for arquivo in pasta.rglob(marcador):
        return arquivo.parent
    return None


def _pacote_contem(item: Path, marcador: str) -> bool:
    if item.is_dir():
        return _encontrar_raiz(item, marcador) is not None
    if item.suffix.lower() != ".zip":
        return False
    try:
        with zipfile.ZipFile(item) as arquivo:
            return any(Path(nome).name.lower() == marcador.lower() for nome in arquivo.namelist())
    except (OSError, zipfile.BadZipFile):
        return False


def listar_pacotes(marcador: str) -> list[Path]:
    pasta = pasta_nao_formatadas()
    return sorted(
        (item for item in pasta.iterdir() if _pacote_contem(item, marcador)),
        key=lambda item: item.name.casefold(),
    )


@contextmanager
def abrir_pacote(item: Path, marcador: str) -> Iterator[Path]:
    if item.is_dir():
        raiz = _encontrar_raiz(item, marcador)
        if raiz is None:
            raise FileNotFoundError(f"{marcador} não encontrado em {item}")
        yield raiz
        return

    with tempfile.TemporaryDirectory(prefix="nexus-manutencao-") as temporario:
        destino = Path(temporario)
        with zipfile.ZipFile(item) as arquivo:
            raiz_segura = destino.resolve()
            for membro in arquivo.infolist():
                alvo = (destino / membro.filename).resolve()
                if raiz_segura != alvo and raiz_segura not in alvo.parents:
                    raise ValueError(f"Caminho inseguro dentro do ZIP: {membro.filename}")
            arquivo.extractall(destino)
        raiz = _encontrar_raiz(destino, marcador)
        if raiz is None:
            raise FileNotFoundError(f"{marcador} não encontrado em {item.name}")
        yield raiz


def listar_colecoes() -> list[Path]:
    pasta = pasta_colecoes()
    return sorted(
        (item for item in pasta.iterdir() if item.is_dir() and (item / ARQUIVO_PERFIL).is_file()),
        key=lambda item: item.name.casefold(),
    )


def identificar_colecao(perfil: dict[str, Any], padrao: str) -> str:
    bruto = texto(perfil.get("collectionId")) or padrao
    return re.sub(r"[^A-Za-z0-9_-]+", "-", bruto).strip("-") or "colecao"


def idioma_saida(valor: str) -> str:
    normalizado = normalizar_idioma(valor)
    if chave_texto(normalizado) == chave_texto("Português"):
        return "Português (PT-BR)"
    if chave_texto(normalizado) == chave_texto("Inglês"):
        return "Inglês"
    return normalizado


def _precos(dados: dict[str, Any], modo: str, preservar: dict[str, Any] | None = None) -> dict[str, str]:
    preservar = preservar or {}
    menor = dados.get("menor")
    medio = dados.get("medio")
    minimo = dados.get("minimo")
    rapida = dados.get("venda_rapida")
    escolhido = valor_preco(dados, modo)
    alteracao = texto(dados.get("alteracao"))
    if menor is None and not alteracao:
        alteracao = "nenhuma oferta compatível encontrada"
    return {
        "Minimo": formatar_decimal_csv(minimo) or primeiro(preservar, "Minimo", "Mínimo", "Preço mínimo"),
        "Venda Rapida": formatar_decimal_csv(rapida) or primeiro(preservar, "Venda Rapida", "Venda Rápida", "Venda rápida"),
        "Menor Liga": formatar_decimal_csv(menor) or primeiro(preservar, "Menor Liga", "Preço Liga mais barato"),
        "Preço Médio Liga": formatar_decimal_csv(medio) or primeiro(preservar, "Preço Médio Liga", "Preço médio Liga"),
        "Preço": formatar_decimal_csv(escolhido) or primeiro(preservar, "Preço"),
        "Alteração de preço": alteracao,
    }


def montar_carta_nova(linha: dict[str, Any], dados: dict[str, Any], modo: str) -> dict[str, Any]:
    precos = _precos(dados, modo, linha)
    nome = texto(dados.get("nome")) or primeiro(linha, "Nome")
    numero = texto(dados.get("numeracao")) or primeiro(linha, "Número", "Numeração")
    colecao = texto(dados.get("colecao")) or primeiro(linha, "Coleção")
    return {
        "Nome": nome,
        "Número": numero,
        "Coleção": colecao,
        "Idioma": idioma_saida(primeiro(linha, "Idioma") or "BR"),
        "Estado": normalizar_estado(primeiro(linha, "Estado") or "NM"),
        "Ano": "",
        "Tipo": "",
        "Link Liga": primeiro(linha, "Link Liga", "Liga", "Link"),
        "Link MYP": "",
        "Link Cardmarket": "",
        "Link Tcgplayer": "",
        "Link PriceCharting": "",
        **precos,
        "Quantidade": inteiro(primeiro(linha, "Quantidade")),
        "À venda": primeiro(linha, "À venda", "Venda") or "Sim",
    }


def cotizar_carta(linha: dict[str, Any], dados: dict[str, Any], modo: str) -> dict[str, Any]:
    nova = dict(linha)
    nova.update(_precos(dados, modo, linha))
    # Cotização altera somente preços; os dados cadastrais permanecem intocados.
    return {coluna: nova.get(coluna, "") for coluna in COLUNAS_CARTAS}


def montar_booster_novo(linha: dict[str, Any], dados: dict[str, Any], modo: str) -> dict[str, Any]:
    precos = _precos(dados, modo, linha)
    return {
        "Tipo de pacote": primeiro(linha, "Tipo de pacote", "Coleção", "Nome") or texto(dados.get("nome") or dados.get("colecao")),
        "Quantidade": inteiro(primeiro(linha, "Quantidade")),
        "Preço mínimo": precos["Minimo"],
        "Venda rápida": precos["Venda Rapida"],
        "Preço Liga mais barato": precos["Menor Liga"],
        "Preço médio Liga": precos["Preço Médio Liga"],
        "Preço": precos["Preço"],
        "Alteração de preço": precos["Alteração de preço"],
        "Link Liga": primeiro(linha, "Link Liga", "Liga", "Link"),
        "À venda": primeiro(linha, "À venda", "Venda") or "Sim",
    }


def cotizar_booster(linha: dict[str, Any], dados: dict[str, Any], modo: str) -> dict[str, Any]:
    nova = dict(linha)
    precos = _precos(dados, modo, linha)
    nova.update(
        {
            "Preço mínimo": precos["Minimo"],
            "Venda rápida": precos["Venda Rapida"],
            "Preço Liga mais barato": precos["Menor Liga"],
            "Preço médio Liga": precos["Preço Médio Liga"],
            "Preço": precos["Preço"],
            "Alteração de preço": precos["Alteração de preço"],
        }
    )
    return {coluna: nova.get(coluna, "") for coluna in COLUNAS_BOOSTERS}



def normalizar_carta_existente(linha: dict[str, Any]) -> dict[str, Any]:
    return {
        "Nome": primeiro(linha, "Nome"),
        "Número": primeiro(linha, "Número", "Numeração"),
        "Coleção": primeiro(linha, "Coleção"),
        "Idioma": primeiro(linha, "Idioma"),
        "Estado": primeiro(linha, "Estado"),
        "Ano": primeiro(linha, "Ano"),
        "Tipo": primeiro(linha, "Tipo"),
        "Link Liga": primeiro(linha, "Link Liga"),
        "Link MYP": primeiro(linha, "Link MYP"),
        "Link Cardmarket": primeiro(linha, "Link Cardmarket"),
        "Link Tcgplayer": primeiro(linha, "Link Tcgplayer", "Link TCGPlayer"),
        "Link PriceCharting": primeiro(linha, "Link PriceCharting"),
        "Minimo": primeiro(linha, "Minimo", "Mínimo", "Preço mínimo"),
        "Venda Rapida": primeiro(linha, "Venda Rapida", "Venda Rápida", "Venda rápida"),
        "Menor Liga": primeiro(linha, "Menor Liga", "Preço Liga mais barato"),
        "Preço Médio Liga": primeiro(linha, "Preço Médio Liga", "Preço médio Liga"),
        "Preço": primeiro(linha, "Preço"),
        "Alteração de preço": primeiro(linha, "Alteração de preço"),
        "Quantidade": inteiro(primeiro(linha, "Quantidade")),
        "À venda": primeiro(linha, "À venda", "Venda") or "Sim",
    }


def normalizar_booster_existente(linha: dict[str, Any]) -> dict[str, Any]:
    return {
        "Tipo de pacote": primeiro(linha, "Tipo de pacote", "Coleção", "Nome"),
        "Quantidade": inteiro(primeiro(linha, "Quantidade")),
        "Preço mínimo": primeiro(linha, "Preço mínimo", "Minimo", "Mínimo"),
        "Venda rápida": primeiro(linha, "Venda rápida", "Venda Rapida", "Venda Rápida"),
        "Preço Liga mais barato": primeiro(linha, "Preço Liga mais barato", "Menor Liga"),
        "Preço médio Liga": primeiro(linha, "Preço médio Liga", "Preço Médio Liga"),
        "Preço": primeiro(linha, "Preço"),
        "Alteração de preço": primeiro(linha, "Alteração de preço"),
        "Link Liga": primeiro(linha, "Link Liga"),
        "À venda": primeiro(linha, "À venda", "Venda") or "Sim",
    }

def normalizar_kit(linha: dict[str, Any]) -> dict[str, Any]:
    return {
        "Nome": primeiro(linha, "Nome"),
        "Descrição": primeiro(linha, "Descrição"),
        "Preço": primeiro(linha, "Preço"),
        "Quantidade": inteiro(primeiro(linha, "Quantidade")),
        "Conteúdo": primeiro(linha, "Conteúdo"),
        "Conteúdo JSON": primeiro(linha, "Conteúdo JSON"),
        "Valor avulso": primeiro(linha, "Valor avulso", "Preço bruto"),
        "Desconto": primeiro(linha, "Desconto"),
        "Imagem": primeiro(linha, "Imagem"),
        "À venda": primeiro(linha, "À venda", "Venda") or "Sim",
    }


def normalizar_album(linha: dict[str, Any]) -> dict[str, Any]:
    formato = primeiro(linha, "Formato") or "3x3"
    paginas_json = primeiro(linha, "Páginas JSON", "Paginas JSON") or "[]"
    try:
        paginas = json.loads(paginas_json)
        if not isinstance(paginas, list):
            paginas = []
        paginas_json = json.dumps(paginas, ensure_ascii=False, separators=(",", ":"))
    except json.JSONDecodeError:
        paginas_json = "[]"
    return {
        "ID": primeiro(linha, "ID", "Id", "id"),
        "Nome": primeiro(linha, "Nome"),
        "Descrição": primeiro(linha, "Descrição"),
        "Formato": formato,
        "Páginas JSON": paginas_json,
        "Progresso": primeiro(linha, "Progresso"),
        "Quantidade": inteiro(primeiro(linha, "Quantidade")),
        "Imagem": primeiro(linha, "Imagem"),
        "À venda": primeiro(linha, "À venda", "Venda") or "Não",
    }


def _indice_itens(linhas: list[dict[str, Any]], campo_nome: str) -> dict[str, Decimal]:
    indice: dict[str, Decimal] = {}
    for linha in linhas:
        nome = primeiro(linha, campo_nome, "Nome", "Coleção")
        preco = decimal(primeiro(linha, "Preço", "Menor Liga", "Preço Liga mais barato"))
        if nome and preco is not None:
            indice.setdefault(chave_texto(nome), preco)
    return indice


def _conteudo_legado(conteudo: str) -> list[dict[str, Any]]:
    itens: list[dict[str, Any]] = []
    for trecho in re.split(r"\s*[|;]\s*", conteudo):
        trecho = trecho.strip()
        if not trecho:
            continue
        encontrado = re.match(r"(\d+)\s*[xX]\s*(.+)", trecho)
        if encontrado:
            quantidade, nome = int(encontrado.group(1)), encontrado.group(2).strip()
        else:
            quantidade, nome = 1, trecho
        itens.append({"kind": "cards", "name": nome, "quantity": quantidade, "unitPrice": None})
    return itens


def atualizar_kits(
    kits: list[dict[str, Any]],
    cartas: list[dict[str, Any]],
    boosters: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    precos_cartas = _indice_itens(cartas, "Nome")
    precos_boosters = _indice_itens(boosters, "Tipo de pacote")
    atualizados: list[dict[str, Any]] = []

    for kit_original in kits:
        kit = normalizar_kit(kit_original)
        try:
            itens = json.loads(kit["Conteúdo JSON"] or "[]")
            if not isinstance(itens, list):
                itens = []
        except json.JSONDecodeError:
            itens = []
        if not itens:
            itens = _conteudo_legado(kit["Conteúdo"])

        bruto_antigo = decimal(kit.get("Valor avulso"))
        preco_antigo = decimal(kit.get("Preço"))
        desconto_texto = texto(kit.get("Desconto"))
        desconto_percentual: Decimal | None = None
        desconto_absoluto: Decimal | None = None
        if desconto_texto.endswith("%"):
            desconto_percentual = decimal(desconto_texto[:-1])
        else:
            desconto_absoluto = decimal(desconto_texto)
        if desconto_absoluto is None and desconto_percentual is None and bruto_antigo is not None and preco_antigo is not None:
            desconto_absoluto = max(Decimal("0"), bruto_antigo - preco_antigo)

        bruto_novo = Decimal("0")
        itens_novos: list[dict[str, Any]] = []
        for item in itens:
            if not isinstance(item, dict):
                continue
            novo_item = dict(item)
            nome = texto(item.get("name") or item.get("nome"))
            quantidade = inteiro(item.get("quantity") or item.get("quantidade"))
            tipo = chave_texto(item.get("kind") or item.get("tipo"))
            mapa = precos_boosters if tipo in {"BOOSTERS", "BOOSTER", "PACOTES", "PACOTE"} else precos_cartas
            preco_unitario = mapa.get(chave_texto(nome))
            if preco_unitario is None:
                preco_unitario = decimal(item.get("unitPrice") or item.get("precoUnitario")) or Decimal("0")
                if nome:
                    print(f"  Kit {kit['Nome']}: preço de '{nome}' não localizado; valor anterior preservado.")
            novo_item["quantity"] = quantidade
            novo_item["unitPrice"] = float(preco_unitario)
            itens_novos.append(novo_item)
            bruto_novo += preco_unitario * quantidade

        bruto_novo = bruto_novo.quantize(Decimal("0.01"))
        if desconto_percentual is not None:
            desconto_valor = (bruto_novo * desconto_percentual / Decimal("100")).quantize(Decimal("0.01"))
        else:
            desconto_valor = min(bruto_novo, desconto_absoluto or Decimal("0"))
        preco_novo = (bruto_novo - desconto_valor).quantize(Decimal("0.01"))

        kit["Conteúdo JSON"] = json.dumps(itens_novos, ensure_ascii=False, separators=(",", ":"))
        if itens_novos:
            kit["Conteúdo"] = " | ".join(f"{item['quantity']}x {texto(item.get('name') or item.get('nome'))}" for item in itens_novos)
            kit["Valor avulso"] = formatar_decimal_csv(bruto_novo)
            kit["Desconto"] = formatar_decimal_csv(desconto_valor)
            kit["Preço"] = formatar_decimal_csv(preco_novo)
        atualizados.append(kit)
    return atualizados


def _consultar_cartas(
    linhas: list[dict[str, Any]],
    sessao: SessaoLiga,
    modo: str,
    somente_precos: bool,
    interromper_em_erro: bool = False,
) -> list[dict[str, Any]]:
    resultado: list[dict[str, Any]] = []
    for indice, linha in enumerate(linhas, start=1):
        link = primeiro(linha, "Link Liga", "Liga", "Link")
        idioma = primeiro(linha, "Idioma") or "BR"
        estado = primeiro(linha, "Estado") or "NM"
        print(f"Carta {indice}/{len(linhas)}: {primeiro(linha, 'Nome') or link}")
        dados: dict[str, Any] = {}
        try:
            if not link:
                raise ValueError("Link Liga vazio")
            dados = sessao.consultar_carta(link, idioma, estado)
        except Exception as erro:
            if interromper_em_erro:
                raise RuntimeError(f"Falha ao consultar a carta {indice}: {erro}") from erro
            print(f"  Aviso: consulta não concluída ({erro}).")
        nova = cotizar_carta(linha, dados, modo) if somente_precos else montar_carta_nova(linha, dados, modo)
        if not somente_precos:
            baixar_imagem(texto(dados.get("imagem")), f"{nova['Nome']}_{nova['Número']}")
        resultado.append(nova)
    return resultado


def _consultar_boosters(
    linhas: list[dict[str, Any]],
    sessao: SessaoLiga,
    modo: str,
    somente_precos: bool,
    interromper_em_erro: bool = False,
) -> list[dict[str, Any]]:
    resultado: list[dict[str, Any]] = []
    for indice, linha in enumerate(linhas, start=1):
        link = primeiro(linha, "Link Liga", "Liga", "Link")
        print(f"Booster {indice}/{len(linhas)}: {primeiro(linha, 'Tipo de pacote', 'Coleção', 'Nome') or link}")
        dados: dict[str, Any] = {}
        try:
            if not link:
                raise ValueError("Link Liga vazio")
            dados = sessao.consultar_booster(link)
        except Exception as erro:
            if interromper_em_erro:
                raise RuntimeError(f"Falha ao consultar o booster {indice}: {erro}") from erro
            print(f"  Aviso: consulta não concluída ({erro}).")
        nova = cotizar_booster(linha, dados, modo) if somente_precos else montar_booster_novo(linha, dados, modo)
        resultado.append(nova)
    return resultado


def formatar_nova_colecao(item: Path, modo: str) -> Path:
    with abrir_pacote(item, ARQUIVO_PERFIL) as origem:
        perfil = ler_json(origem / ARQUIVO_PERFIL)
        identificador = identificar_colecao(perfil, origem.name)
        destino = pasta_colecoes() / identificador
        destino.mkdir(parents=True, exist_ok=True)
        perfil["collectionId"] = identificador
        perfil["pricingMode"] = modo
        perfil["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")

        cartas_origem = ler_csv(origem / "inventario-cartas.csv")
        boosters_origem = ler_csv(origem / "inventario-boosters.csv")
        cartas: list[dict[str, Any]] = []
        boosters: list[dict[str, Any]] = []
        if cartas_origem or boosters_origem:
            with SessaoLiga() as sessao:
                cartas = _consultar_cartas(cartas_origem, sessao, modo, somente_precos=False)
                boosters = _consultar_boosters(boosters_origem, sessao, modo, somente_precos=False)
        kits = atualizar_kits(
            [normalizar_kit(linha) for linha in ler_csv(origem / "inventario-kits.csv")],
            cartas,
            boosters,
        )
        albuns = [normalizar_album(linha) for linha in ler_csv(origem / "inventario-albuns.csv")]

        escrever_json(destino / ARQUIVO_PERFIL, perfil)
        escrever_csv(destino / "inventario-cartas.csv", COLUNAS_CARTAS, cartas)
        escrever_csv(destino / "inventario-boosters.csv", COLUNAS_BOOSTERS, boosters)
        escrever_csv(destino / "inventario-kits.csv", COLUNAS_KITS, kits)
        if albuns or (origem / "inventario-albuns.csv").is_file():
            escrever_csv(destino / "inventario-albuns.csv", COLUNAS_ALBUNS, albuns)
        return destino


def _chave_link(url: str) -> str:
    try:
        partes = urlsplit(url)
        parametros = [
            (chave, valor)
            for chave, valor in parse_qsl(partes.query, keep_blank_values=True)
            if chave.lower() not in {"show", "srsltid"} and not chave.lower().startswith("utm_")
        ]
        return chave_texto(urlunsplit((partes.scheme, partes.netloc, partes.path, str(sorted(parametros)), "")))
    except Exception:
        return chave_texto(url)


def _mesclar_cartas(existentes: list[dict[str, Any]], novas: list[dict[str, Any]]) -> None:
    for nova in novas:
        chave_nova = (_chave_link(primeiro(nova, "Link Liga")), chave_texto(nova.get("Idioma")), chave_texto(nova.get("Estado")))
        encontrada = None
        for atual in existentes:
            chave_atual = (_chave_link(primeiro(atual, "Link Liga")), chave_texto(atual.get("Idioma")), chave_texto(atual.get("Estado")))
            if chave_atual == chave_nova:
                encontrada = atual
                break
        if encontrada is None:
            existentes.append(nova)
        else:
            encontrada["Quantidade"] = inteiro(encontrada.get("Quantidade")) + inteiro(nova.get("Quantidade"))
            for coluna in ("Minimo", "Venda Rapida", "Menor Liga", "Preço Médio Liga", "Preço", "Alteração de preço"):
                if texto(nova.get(coluna)):
                    encontrada[coluna] = nova[coluna]


def _mesclar_boosters(existentes: list[dict[str, Any]], novos: list[dict[str, Any]]) -> None:
    for novo in novos:
        chave_nova = _chave_link(primeiro(novo, "Link Liga")) or chave_texto(novo.get("Tipo de pacote"))
        encontrada = next((atual for atual in existentes if (_chave_link(primeiro(atual, "Link Liga")) or chave_texto(atual.get("Tipo de pacote"))) == chave_nova), None)
        if encontrada is None:
            existentes.append(novo)
        else:
            encontrada["Quantidade"] = inteiro(encontrada.get("Quantidade")) + inteiro(novo.get("Quantidade"))
            for coluna in ("Preço mínimo", "Venda rápida", "Preço Liga mais barato", "Preço médio Liga", "Preço", "Alteração de preço"):
                if texto(novo.get(coluna)):
                    encontrada[coluna] = novo[coluna]


def _mesclar_kits(existentes: list[dict[str, Any]], novos: list[dict[str, Any]]) -> None:
    for novo in novos:
        encontrada = next((atual for atual in existentes if chave_texto(atual.get("Nome")) == chave_texto(novo.get("Nome"))), None)
        if encontrada is None:
            existentes.append(novo)
        else:
            encontrada["Quantidade"] = inteiro(encontrada.get("Quantidade")) + inteiro(novo.get("Quantidade"))
            for coluna in COLUNAS_KITS:
                if coluna != "Quantidade" and texto(novo.get(coluna)):
                    encontrada[coluna] = novo[coluna]


def _mesclar_albuns(existentes: list[dict[str, Any]], novos: list[dict[str, Any]]) -> None:
    for novo_original in novos:
        novo = normalizar_album(novo_original)
        identificador = chave_texto(novo.get("ID"))
        nome = chave_texto(novo.get("Nome"))
        encontrada = next(
            (
                atual
                for atual in existentes
                if (identificador and chave_texto(atual.get("ID")) == identificador)
                or (nome and chave_texto(atual.get("Nome")) == nome)
            ),
            None,
        )
        if encontrada is None:
            existentes.append(novo)
            continue
        for coluna in COLUNAS_ALBUNS:
            encontrada[coluna] = novo.get(coluna, "")


def _localizar_destino(identificador: str) -> Path:
    chave = chave_texto(identificador)
    for colecao in listar_colecoes():
        perfil = ler_json(colecao / ARQUIVO_PERFIL)
        if chave_texto(colecao.name) == chave or chave_texto(perfil.get("collectionId")) == chave:
            return colecao
    raise FileNotFoundError(f"Coleção de destino não encontrada: {identificador}")


def modo_da_colecao(colecao: Path, padrao: str = MODO_MENOR) -> str:
    modo = texto(ler_json(colecao / ARQUIVO_PERFIL).get("pricingMode")).lower()
    return modo if modo in {MODO_MENOR, MODO_MEDIA} else padrao


def atualizar_colecao(item: Path, modo_padrao: str = MODO_MENOR, destino_manual: Path | None = None) -> Path:
    marcador = ARQUIVO_ATUALIZACAO if _pacote_contem(item, ARQUIVO_ATUALIZACAO) else "inventario-cartas.csv"
    with abrir_pacote(item, marcador) as origem:
        metadados = ler_json(origem / ARQUIVO_ATUALIZACAO)
        identificador = primeiro(metadados, "collectionId", "collection_id", "colecao")
        destino = destino_manual or (_localizar_destino(identificador) if identificador else None)
        if destino is None:
            raise ValueError("A atualização não informa collectionId; selecione a coleção de destino.")

        perfil_caminho = destino / ARQUIVO_PERFIL
        perfil = ler_json(perfil_caminho)
        modo = modo_da_colecao(destino, modo_padrao)
        assinatura = "|".join((identificador or destino.name, texto(metadados.get("version")), texto(metadados.get("generatedAt"))))
        update_id = texto(metadados.get("updateId")) or hashlib.sha256(assinatura.encode("utf-8")).hexdigest()[:20]
        aplicadas = [texto(valor) for valor in perfil.get("appliedUpdates", [])]
        if update_id in aplicadas:
            print(f"Atualização {update_id} já aplicada; nada foi duplicado.")
            return destino

        cartas_existentes = [normalizar_carta_existente(linha) for linha in ler_csv(destino / "inventario-cartas.csv")]
        boosters_existentes = [normalizar_booster_existente(linha) for linha in ler_csv(destino / "inventario-boosters.csv")]
        kits_existentes = [normalizar_kit(linha) for linha in ler_csv(destino / "inventario-kits.csv")]
        albuns_existentes = [normalizar_album(linha) for linha in ler_csv(destino / "inventario-albuns.csv")]
        cartas_origem = ler_csv(origem / "inventario-cartas.csv")
        boosters_origem = ler_csv(origem / "inventario-boosters.csv")

        cartas_novas: list[dict[str, Any]] = []
        boosters_novos: list[dict[str, Any]] = []
        if cartas_origem or boosters_origem:
            with SessaoLiga() as sessao:
                cartas_novas = _consultar_cartas(cartas_origem, sessao, modo, somente_precos=False, interromper_em_erro=True)
                boosters_novos = _consultar_boosters(boosters_origem, sessao, modo, somente_precos=False, interromper_em_erro=True)
        _mesclar_cartas(cartas_existentes, cartas_novas)
        _mesclar_boosters(boosters_existentes, boosters_novos)
        _mesclar_kits(kits_existentes, [normalizar_kit(linha) for linha in ler_csv(origem / "inventario-kits.csv")])
        _mesclar_albuns(albuns_existentes, ler_csv(origem / "inventario-albuns.csv"))
        kits_existentes = atualizar_kits(kits_existentes, cartas_existentes, boosters_existentes)

        escrever_csv(destino / "inventario-cartas.csv", COLUNAS_CARTAS, cartas_existentes)
        escrever_csv(destino / "inventario-boosters.csv", COLUNAS_BOOSTERS, boosters_existentes)
        escrever_csv(destino / "inventario-kits.csv", COLUNAS_KITS, kits_existentes)
        if albuns_existentes or (origem / "inventario-albuns.csv").is_file() or (destino / "inventario-albuns.csv").is_file():
            escrever_csv(destino / "inventario-albuns.csv", COLUNAS_ALBUNS, albuns_existentes)

        perfil["pricingMode"] = modo
        perfil["updatedAt"] = texto(metadados.get("generatedAt")) or time.strftime("%Y-%m-%dT%H:%M:%S")
        perfil["version"] = max(int(perfil.get("version") or 1) + 1, int(metadados.get("version") or 0))
        perfil["appliedUpdates"] = [*aplicadas, update_id][-100:]
        escrever_json(perfil_caminho, perfil)
        return destino


def cotizar_colecao(colecao: Path, modo_padrao: str = MODO_MENOR) -> Path:
    modo = modo_da_colecao(colecao, modo_padrao)
    cartas_origem = ler_csv(colecao / "inventario-cartas.csv")
    boosters_origem = ler_csv(colecao / "inventario-boosters.csv")
    with SessaoLiga() as sessao:
        cartas = _consultar_cartas(cartas_origem, sessao, modo, somente_precos=True)
        boosters = _consultar_boosters(boosters_origem, sessao, modo, somente_precos=True)
    kits = atualizar_kits(ler_csv(colecao / "inventario-kits.csv"), cartas, boosters)

    escrever_csv(colecao / "inventario-cartas.csv", COLUNAS_CARTAS, cartas)
    escrever_csv(colecao / "inventario-boosters.csv", COLUNAS_BOOSTERS, boosters)
    escrever_csv(colecao / "inventario-kits.csv", COLUNAS_KITS, kits)
    perfil = ler_json(colecao / ARQUIVO_PERFIL)
    perfil["pricingMode"] = modo
    perfil["quotedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    escrever_json(colecao / ARQUIVO_PERFIL, perfil)
    return colecao
