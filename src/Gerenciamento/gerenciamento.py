from __future__ import annotations

import copy
import hashlib
import json
import re
import tempfile
import time
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from armazenamento import (
    anexar_historico,
    arquivar_csvs_legados,
    escrever_inventario,
    escrever_json_obj,
    ler_inventario,
    ler_json_obj,
    migrar_historicos_embutidos,
    migrar_inventarios_legados,
    recuperar_transacoes_pendentes,
    transacao_arquivos,
)
from configuracao import (
    ARQUIVO_ATUALIZACAO,
    ARQUIVO_PERFIL,
    ARQUIVOS_INVENTARIO,
    SALVAR_PARCIAL,
    chave_texto,
    pasta_colecoes,
    pasta_nao_formatadas,
)
from liga import SessaoLiga, baixar_imagem, normalizar_estado, normalizar_idioma
from precificacao import (
    agora_iso,
    gerar_status_booster,
    gerar_status_carta,
    identificador_booster,
    identificador_carta,
    numero,
    preco_objeto,
    registrar_historico,
)
from relatorios import registrar_variacoes, salvar_relatorio

MODO_MENOR = "menor"
MODO_MEDIA = "media"
ARQUIVO_COTIZACAO_PARCIAL = "cotizacao-em-andamento.json"
ARQUIVO_FORMATACAO_PARCIAL = "formatacao-em-andamento.json"


def texto(valor: Any) -> str:
    return "" if valor is None else str(valor).strip()


def primeiro(linha: dict[str, Any], *nomes: str) -> Any:
    for nome in nomes:
        valor = linha.get(nome)
        if valor is not None and texto(valor) != "":
            return valor
    return ""


def inteiro(valor: Any, padrao: int = 1) -> int:
    if isinstance(valor, int):
        return max(1, valor)
    encontrado = re.search(r"\d+", texto(valor))
    return max(1, int(encontrado.group(0))) if encontrado else padrao


def inteiro_nao_negativo(valor: Any, padrao: int = 0) -> int:
    """Inteiro para contadores de mercado, onde zero é um valor válido."""
    if isinstance(valor, bool):
        return int(valor)
    if isinstance(valor, (int, float)):
        return max(0, int(valor))
    encontrado = re.search(r"\d+", texto(valor))
    return max(0, int(encontrado.group(0))) if encontrado else padrao


def _sim_nao(valor: Any, padrao: bool = True) -> bool:
    if isinstance(valor, bool):
        return valor
    chave = chave_texto(valor)
    if chave in {"NAO", "N", "FALSE", "0"}:
        return False
    if chave in {"SIM", "S", "TRUE", "1"}:
        return True
    return padrao


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
    return sorted((item for item in pasta.iterdir() if _pacote_contem(item, marcador)), key=lambda p: p.name.casefold())


@contextmanager
def abrir_pacote(item: Path, marcador: str) -> Iterator[Path]:
    if item.is_dir():
        raiz = _encontrar_raiz(item, marcador)
        if raiz is None:
            raise FileNotFoundError(f"{marcador} não encontrado em {item}")
        yield raiz
        return
    with tempfile.TemporaryDirectory(prefix="nexus-gerenciamento-") as temporario:
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
    return sorted((p for p in pasta.iterdir() if p.is_dir() and (p / ARQUIVO_PERFIL).is_file()), key=lambda p: p.name.casefold())


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


def _precos_atuais(dados: dict[str, Any], modo: str, preservar: dict[str, Any] | None = None) -> dict[str, Any]:
    """Atualiza apenas referências de mercado; o campo Preço é sempre do usuário."""
    preservar = preservar or {}
    minimo_certeiro = numero(dados.get("minimo_certeiro"))
    minimo = numero(dados.get("minimo"))
    menor = numero(dados.get("menor"))
    segundo_menor = numero(dados.get("segundo_menor"))
    terceiro_menor = numero(dados.get("terceiro_menor"))
    medio = numero(dados.get("medio"))
    mediana = numero(dados.get("mediana"))
    rapida = numero(dados.get("venda_rapida"))
    return {
        "Minimo Certeiro": minimo_certeiro if minimo_certeiro is not None else numero(primeiro(preservar, "Minimo Certeiro", "Mínimo Certeiro")),
        "Minimo": minimo if minimo is not None else numero(primeiro(preservar, "Minimo", "Mínimo", "Preço mínimo")),
        "Menor Liga": menor if menor is not None else numero(primeiro(preservar, "Menor Liga", "Preço Liga mais barato")),
        "Segundo Menor Liga": segundo_menor if segundo_menor is not None else numero(primeiro(preservar, "Segundo Menor Liga")),
        "Terceiro Menor Liga": terceiro_menor if terceiro_menor is not None else numero(primeiro(preservar, "Terceiro Menor Liga")),
        "Media Liga": medio if medio is not None else numero(primeiro(preservar, "Media Liga", "Preço Médio Liga", "Preço médio Liga")),
        "Mediana Liga": mediana if mediana is not None else numero(primeiro(preservar, "Mediana Liga")),
        "Venda Rapida": rapida if rapida is not None else numero(primeiro(preservar, "Venda Rapida", "Venda Rápida", "Venda rápida")),
        "Vendedores Geral": int(dados["vendedores_geral"] if dados.get("vendedores_geral") is not None else (primeiro(preservar, "Vendedores Geral") or 0)),
        "Vendedores Específicos": int(dados["vendedores_especificos"] if dados.get("vendedores_especificos") is not None else (primeiro(preservar, "Vendedores Específicos") or 0)),
        "Compradores Geral": int(dados["compradores_geral"] if dados.get("compradores_geral") is not None else (primeiro(preservar, "Compradores Geral") or 0)),
        "Compradores Específicos": int(dados["compradores_especificos"] if dados.get("compradores_especificos") is not None else (primeiro(preservar, "Compradores Específicos") or 0)),
        "Preço": numero(primeiro(preservar, "Preço")),
        "Alteração de preço": texto(dados.get("alteracao")) or texto(primeiro(preservar, "Alteração de preço")),
    }


def normalizar_carta_existente(linha: dict[str, Any]) -> dict[str, Any]:
    carta = dict(linha)
    carta.update({
        "Nome": texto(primeiro(linha, "Nome")),
        "Número": texto(primeiro(linha, "Número", "Numeração")),
        "Coleção": texto(primeiro(linha, "Coleção")),
        "Idioma": texto(primeiro(linha, "Idioma")) or "Português (PT-BR)",
        "Estado": texto(primeiro(linha, "Estado")) or "NM",
        "Ano": texto(primeiro(linha, "Ano")),
        "Tipo": texto(primeiro(linha, "Tipo")),
        "Link Liga": texto(primeiro(linha, "Link Liga", "Liga", "Link")),
        "Link MYP": texto(primeiro(linha, "Link MYP")),
        "Link Cardmarket": texto(primeiro(linha, "Link Cardmarket")),
        "Link Tcgplayer": texto(primeiro(linha, "Link Tcgplayer", "Link TCGPlayer")),
        "Link PriceCharting": texto(primeiro(linha, "Link PriceCharting")),
        "Minimo Certeiro": numero(primeiro(linha, "Minimo Certeiro", "Mínimo Certeiro")),
        "Minimo": numero(primeiro(linha, "Minimo", "Mínimo", "Preço mínimo")),
        "Menor Liga": numero(primeiro(linha, "Menor Liga", "Preço Liga mais barato")),
        "Segundo Menor Liga": numero(primeiro(linha, "Segundo Menor Liga")),
        "Terceiro Menor Liga": numero(primeiro(linha, "Terceiro Menor Liga")),
        "Media Liga": numero(primeiro(linha, "Media Liga", "Preço Médio Liga", "Preço médio Liga")),
        "Mediana Liga": numero(primeiro(linha, "Mediana Liga")),
        "Venda Rapida": numero(primeiro(linha, "Venda Rapida", "Venda Rápida", "Venda rápida")),
        "Vendedores Geral": inteiro_nao_negativo(primeiro(linha, "Vendedores Geral")),
        "Vendedores Específicos": inteiro_nao_negativo(primeiro(linha, "Vendedores Específicos")),
        "Compradores Geral": inteiro_nao_negativo(primeiro(linha, "Compradores Geral")),
        "Compradores Específicos": inteiro_nao_negativo(primeiro(linha, "Compradores Específicos")),
        "Preço": numero(primeiro(linha, "Preço")),
        "Alteração de preço": texto(primeiro(linha, "Alteração de preço")),
        "Quantidade": inteiro(primeiro(linha, "Quantidade")),
        "Imagem": texto(primeiro(linha, "Imagem")),
        "À venda": _sim_nao(primeiro(linha, "À venda", "Venda"), True),
    })
    for legado in ("Preço Médio Liga", "Preço médio Liga", "Mínimo Certeiro"):
        carta.pop(legado, None)
    if not isinstance(carta.get("Status"), dict):
        carta["Status"] = {"nível": "OK", "motivos": []}
    if not isinstance(carta.get("Última cotação"), dict):
        carta.pop("Última cotação", None)
    # Histórico completo vive em historico/cartas.jsonl.
    carta.pop("Histórico de preços", None)
    carta["Id"] = texto(carta.get("Id")) or identificador_carta(carta)
    return carta


def normalizar_booster_existente(linha: dict[str, Any]) -> dict[str, Any]:
    booster = dict(linha)
    booster.update({
        "Tipo de pacote": texto(primeiro(linha, "Tipo de pacote", "Coleção", "Nome")),
        "Quantidade": inteiro(primeiro(linha, "Quantidade")),
        "Minimo Certeiro": numero(primeiro(linha, "Minimo Certeiro", "Mínimo Certeiro")),
        "Minimo": numero(primeiro(linha, "Minimo", "Preço mínimo", "Mínimo")),
        "Menor Liga": numero(primeiro(linha, "Menor Liga", "Preço Liga mais barato")),
        "Segundo Menor Liga": numero(primeiro(linha, "Segundo Menor Liga")),
        "Terceiro Menor Liga": numero(primeiro(linha, "Terceiro Menor Liga")),
        "Media Liga": numero(primeiro(linha, "Media Liga", "Preço médio Liga", "Preço Médio Liga")),
        "Mediana Liga": numero(primeiro(linha, "Mediana Liga")),
        "Venda Rapida": numero(primeiro(linha, "Venda Rapida", "Venda rápida", "Venda Rápida")),
        "Vendedores Geral": inteiro_nao_negativo(primeiro(linha, "Vendedores Geral")),
        "Vendedores Específicos": inteiro_nao_negativo(primeiro(linha, "Vendedores Específicos")),
        "Compradores Geral": inteiro_nao_negativo(primeiro(linha, "Compradores Geral")),
        "Compradores Específicos": inteiro_nao_negativo(primeiro(linha, "Compradores Específicos")),
        "Preço": numero(primeiro(linha, "Preço")),
        "Alteração de preço": texto(primeiro(linha, "Alteração de preço")),
        "Link Liga": texto(primeiro(linha, "Link Liga", "Liga", "Link")),
        "Imagem": texto(primeiro(linha, "Imagem")),
        "À venda": _sim_nao(primeiro(linha, "À venda", "Venda"), True),
    })
    for legado in ("Preço mínimo", "Venda rápida", "Preço Liga mais barato", "Preço médio Liga", "Preço Médio Liga", "Mínimo Certeiro"):
        booster.pop(legado, None)
    if not isinstance(booster.get("Status"), dict):
        booster["Status"] = {"nível": "OK", "motivos": []}
    if not isinstance(booster.get("Última cotação"), dict):
        booster.pop("Última cotação", None)
    booster.pop("Histórico de preços", None)
    booster["Id"] = texto(booster.get("Id")) or identificador_booster(booster)
    return booster


def normalizar_produto(linha: dict[str, Any]) -> dict[str, Any]:
    produto = dict(linha)
    nome = texto(primeiro(linha, "Nome", "Produto")) or "Produto Pokémon"
    produto.update({
        "Nome": nome,
        "Link Liga": texto(primeiro(linha, "Link Liga", "Liga", "Link")),
        "Preço": numero(primeiro(linha, "Preço")),
        "Imagem": texto(primeiro(linha, "Imagem")),
        "À venda": _sim_nao(primeiro(linha, "À venda", "Venda"), True),
    })
    produto["Id"] = texto(primeiro(linha, "Id", "ID")) or f"PRODUTO-{chave_texto(nome) or hashlib.sha1(nome.encode('utf-8')).hexdigest()[:12].upper()}"
    produto.pop("ID", None)
    produto.pop("Quantidade", None)
    produto.pop("quantity", None)
    return produto


def _conteudo_legado(conteudo: str) -> list[dict[str, Any]]:
    itens: list[dict[str, Any]] = []
    for trecho in re.split(r"\s*[|;]\s*", conteudo):
        trecho = trecho.strip()
        if not trecho:
            continue
        encontrado = re.match(r"(\d+)\s*[xX×]\s*(.+)", trecho)
        quantidade, nome = (int(encontrado.group(1)), encontrado.group(2).strip()) if encontrado else (1, trecho)
        itens.append({"kind": "cards", "itemId": "", "name": nome, "quantity": quantidade, "unitPrice": None})
    return itens


def _normalizar_kind(valor: Any) -> str:
    chave = chave_texto(valor)
    return "boosters" if chave in {"BOOSTER", "BOOSTERS", "PACOTE", "PACOTES"} else "cards"


def _normalizar_conteudo_kit(conteudo: Any) -> list[dict[str, Any]]:
    if not isinstance(conteudo, list):
        return []
    itens: list[dict[str, Any]] = []
    for bruto in conteudo:
        if not isinstance(bruto, dict):
            continue
        item = dict(bruto)
        item["kind"] = _normalizar_kind(bruto.get("kind") or bruto.get("tipo"))
        item["itemId"] = texto(bruto.get("itemId") or bruto.get("item_id") or bruto.get("Id"))
        item["name"] = texto(bruto.get("name") or bruto.get("nome")) or "Item"
        item["quantity"] = inteiro(bruto.get("quantity") or bruto.get("quantidade"))
        item["unitPrice"] = numero(bruto.get("unitPrice") if bruto.get("unitPrice") is not None else bruto.get("precoUnitario"))
        itens.append(item)
    return itens


def normalizar_kit(linha: dict[str, Any]) -> dict[str, Any]:
    kit = dict(linha)
    conteudo = linha.get("Conteúdo")
    if not isinstance(conteudo, list):
        bruto_json = primeiro(linha, "Conteúdo JSON")
        if bruto_json:
            try:
                conteudo = json.loads(texto(bruto_json))
            except json.JSONDecodeError:
                conteudo = []
        if not isinstance(conteudo, list) or not conteudo:
            conteudo = _conteudo_legado(texto(primeiro(linha, "Conteúdo", "Resumo do conteúdo")))
    conteudo = _normalizar_conteudo_kit(conteudo)
    nome = texto(primeiro(linha, "Nome")) or "Kit sem nome"
    kit.update({
        "Nome": nome,
        "Descrição": texto(primeiro(linha, "Descrição")),
        "Preço": numero(primeiro(linha, "Preço")),
        "Quantidade": inteiro(primeiro(linha, "Quantidade")),
        "Conteúdo": conteudo,
        "Valor avulso": numero(primeiro(linha, "Valor avulso", "Preço bruto")),
        "Desconto": primeiro(linha, "Desconto"),
        "Imagem": texto(primeiro(linha, "Imagem")),
        "À venda": _sim_nao(primeiro(linha, "À venda", "Venda"), True),
    })
    kit["Id"] = texto(kit.get("Id")) or f"KIT-{hashlib.sha1(nome.encode('utf-8')).hexdigest()[:12].upper()}"
    kit.pop("Conteúdo JSON", None)
    kit.pop("Resumo do conteúdo", None)
    return kit


def _paginas_album(linha: dict[str, Any]) -> list[Any]:
    paginas = linha.get("Páginas")
    if isinstance(paginas, list):
        return paginas
    bruto = primeiro(linha, "Páginas JSON", "Paginas JSON")
    if bruto:
        try:
            parsed = json.loads(texto(bruto))
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            pass
    return []


def normalizar_album(linha: dict[str, Any]) -> dict[str, Any]:
    album = dict(linha)
    nome = texto(primeiro(linha, "Nome")) or "Álbum sem nome"
    album_id = texto(primeiro(linha, "Id", "ID")) or f"ALBUM-{hashlib.sha1(nome.encode('utf-8')).hexdigest()[:12].upper()}"
    album.update({
        "Id": album_id,
        "Nome": nome,
        "Descrição": texto(primeiro(linha, "Descrição")),
        "Formato": texto(primeiro(linha, "Formato")) or "3x3",
        "Páginas": _paginas_album(linha),
        "Progresso": primeiro(linha, "Progresso"),
        "Quantidade": inteiro(primeiro(linha, "Quantidade")),
        "Imagem": texto(primeiro(linha, "Imagem")),
        "À venda": _sim_nao(primeiro(linha, "À venda", "Venda"), False),
    })
    album.pop("ID", None)
    album.pop("Páginas JSON", None)
    album.pop("Paginas JSON", None)
    return album


def _status_erro_cotizacao(erro: str) -> dict[str, Any]:
    return {
        "nível": "Suspeita",
        "motivos": [{
            "nivel": "suspeita",
            "codigo": "erro_cotizacao",
            "mensagem": f"Erro na cotização: {erro}",
            "evidencia": {"erro": erro},
        }],
    }


def montar_carta_nova(
    linha: dict[str, Any], dados: dict[str, Any], modo: str, cotacao_id: str, data: str, erro: str = ""
) -> tuple[dict[str, Any], dict[str, Any]]:
    carta = normalizar_carta_existente(linha)
    carta["Nome"] = texto(dados.get("nome")) or carta["Nome"]
    carta["Número"] = texto(dados.get("numeracao")) or carta["Número"]
    carta["Coleção"] = texto(dados.get("colecao")) or carta["Coleção"]
    carta["Ano"] = texto(dados.get("ano")) or carta["Ano"]
    carta["Tipo"] = texto(dados.get("tipo")) or carta["Tipo"]
    carta["Idioma"] = idioma_saida(texto(primeiro(linha, "Idioma")) or "BR")
    carta["Estado"] = normalizar_estado(texto(primeiro(linha, "Estado")) or "NM")
    if not erro:
        carta.update(_precos_atuais(dados, modo, carta))
        carta["Preço coletado"] = preco_objeto(dados, False)
        carta["Preço estimado"] = preco_objeto(dados, True)
    status = _status_erro_cotizacao(erro) if erro else gerar_status_carta(dados, carta["Idioma"], carta["Estado"])
    carta["Status"] = status
    carta["Id"] = identificador_carta(carta)
    registro = registrar_historico(carta, cotacao_id, data, status, erro)
    return carta, registro


def cotizar_carta(
    linha: dict[str, Any], dados: dict[str, Any], modo: str, cotacao_id: str, data: str, erro: str = ""
) -> tuple[dict[str, Any], dict[str, Any]]:
    carta = normalizar_carta_existente(linha)
    # Nunca toca nos dados cadastrais (Ano, Tipo, links etc.) durante cotização.
    if not erro:
        carta.update(_precos_atuais(dados, modo, carta))
        carta["Preço coletado"] = preco_objeto(dados, False)
        carta["Preço estimado"] = preco_objeto(dados, True)
    status = _status_erro_cotizacao(erro) if erro else gerar_status_carta(dados, carta["Idioma"], carta["Estado"])
    if not erro:
        carta["Status"] = status
    registro = registrar_historico(carta, cotacao_id, data, status, erro)
    return carta, registro


def montar_booster_novo(
    linha: dict[str, Any], dados: dict[str, Any], modo: str, cotacao_id: str, data: str, erro: str = ""
) -> tuple[dict[str, Any], dict[str, Any]]:
    booster = normalizar_booster_existente(linha)
    booster["Tipo de pacote"] = booster["Tipo de pacote"] or texto(dados.get("nome") or dados.get("colecao"))
    if not erro:
        precos = _precos_atuais(dados, modo, booster)
        booster.update({
            **precos,
            "Preço coletado": preco_objeto(dados, False),
            "Preço estimado": preco_objeto(dados, True),
        })
    status = _status_erro_cotizacao(erro) if erro else gerar_status_booster(dados)
    booster["Status"] = status
    booster["Id"] = identificador_booster(booster)
    registro = registrar_historico(booster, cotacao_id, data, status, erro)
    return booster, registro


def cotizar_booster(
    linha: dict[str, Any], dados: dict[str, Any], modo: str, cotacao_id: str, data: str, erro: str = ""
) -> tuple[dict[str, Any], dict[str, Any]]:
    booster = normalizar_booster_existente(linha)
    if not erro:
        precos = _precos_atuais(dados, modo, booster)
        booster.update({
            **precos,
            "Preço coletado": preco_objeto(dados, False),
            "Preço estimado": preco_objeto(dados, True),
        })
    status = _status_erro_cotizacao(erro) if erro else gerar_status_booster(dados)
    if not erro:
        booster["Status"] = status
    registro = registrar_historico(booster, cotacao_id, data, status, erro)
    return booster, registro


def _registro_falha(linha: dict[str, Any], tipo: str, cotacao_id: str, erro: str) -> dict[str, Any]:
    item = normalizar_carta_existente(linha) if tipo == "cartas" else normalizar_booster_existente(linha)
    status = _status_erro_cotizacao(erro)
    return registrar_historico(item, cotacao_id, agora_iso(), status, erro)


def _preco_item(linha: dict[str, Any]) -> Decimal | None:
    preco = numero(primeiro(linha, "Preço", "Menor Liga", "Preço Liga mais barato"))
    return Decimal(str(preco)) if preco is not None else None


def _chaves_nome_produto(linha: dict[str, Any], tipo: str) -> set[str]:
    if tipo == "boosters":
        nome = texto(primeiro(linha, "Tipo de pacote", "Nome", "Coleção"))
        return {chave_texto(nome)} if nome else set()
    nome = texto(primeiro(linha, "Nome"))
    numero_carta = texto(primeiro(linha, "Número", "Numeração"))
    chaves = {chave_texto(nome)} if nome else set()
    if nome and numero_carta:
        chaves.add(chave_texto(f"{nome} ({numero_carta})"))
        chaves.add(chave_texto(f"{nome} {numero_carta}"))
    return {x for x in chaves if x}


def _indices_produtos(linhas: list[dict[str, Any]], tipo: str) -> tuple[dict[str, Decimal], dict[str, tuple[str, str, Decimal]], dict[str, list[str]]]:
    por_id: dict[str, Decimal] = {}
    dados_id: dict[str, tuple[str, str, Decimal]] = {}
    por_nome: dict[str, list[str]] = {}
    for linha in linhas:
        normalizada = normalizar_booster_existente(linha) if tipo == "boosters" else normalizar_carta_existente(linha)
        item_id = texto(normalizada.get("Id"))
        preco = _preco_item(normalizada)
        nome = texto(primeiro(normalizada, "Tipo de pacote", "Nome"))
        if not item_id or preco is None:
            continue
        por_id[item_id] = preco
        dados_id[item_id] = (nome, tipo, preco)
        for chave in _chaves_nome_produto(normalizada, tipo):
            por_nome.setdefault(chave, []).append(item_id)
    return por_id, dados_id, por_nome


def atualizar_kits(kits: list[dict[str, Any]], cartas: list[dict[str, Any]], boosters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    precos_cartas, dados_cartas, nomes_cartas = _indices_produtos(cartas, "cards")
    precos_boosters, dados_boosters, nomes_boosters = _indices_produtos(boosters, "boosters")
    atualizados: list[dict[str, Any]] = []

    for original in kits:
        kit = normalizar_kit(original)
        bruto_antigo = Decimal(str(numero(kit.get("Valor avulso")) or 0))
        preco_antigo = Decimal(str(numero(kit.get("Preço")) or 0))
        desconto_bruto = kit.get("Desconto")
        desconto_percentual: Decimal | None = None
        desconto_absoluto: Decimal | None = None
        if isinstance(desconto_bruto, str) and desconto_bruto.strip().endswith("%"):
            try:
                desconto_percentual = Decimal(desconto_bruto.strip()[:-1].replace(",", "."))
            except Exception:
                pass
        else:
            valor_desc = numero(desconto_bruto)
            if valor_desc is not None:
                desconto_absoluto = Decimal(str(valor_desc))
        if desconto_percentual is None and desconto_absoluto is None and bruto_antigo and preco_antigo:
            desconto_absoluto = max(Decimal("0"), bruto_antigo - preco_antigo)

        bruto = Decimal("0")
        itens_novos: list[dict[str, Any]] = []
        for item in kit.get("Conteúdo", []):
            if not isinstance(item, dict):
                continue
            novo = dict(item)
            tipo = _normalizar_kind(item.get("kind") or item.get("tipo"))
            item_id = texto(item.get("itemId") or item.get("item_id"))
            nome = texto(item.get("name") or item.get("nome"))
            quantidade = inteiro(item.get("quantity") or item.get("quantidade"))
            precos = precos_boosters if tipo == "boosters" else precos_cartas
            dados_por_id = dados_boosters if tipo == "boosters" else dados_cartas
            nomes = nomes_boosters if tipo == "boosters" else nomes_cartas

            resolvido = item_id if item_id in precos else ""
            if not resolvido and nome:
                candidatos = sorted(set(nomes.get(chave_texto(nome), [])))
                if len(candidatos) == 1:
                    resolvido = candidatos[0]
                elif len(candidatos) > 1:
                    novo["referenceStatus"] = "ambiguous"
            preco_unit = precos.get(resolvido) if resolvido else None
            if preco_unit is None:
                preco_unit = Decimal(str(numero(item.get("unitPrice") if item.get("unitPrice") is not None else item.get("precoUnitario")) or 0))
                if not novo.get("referenceStatus"):
                    novo["referenceStatus"] = "missing"
            else:
                novo.pop("referenceStatus", None)
                nome_resolvido = dados_por_id.get(resolvido, (nome, tipo, preco_unit))[0]
                if nome_resolvido and not nome:
                    nome = nome_resolvido

            novo["kind"] = tipo
            novo["itemId"] = resolvido
            novo["name"] = nome or "Item"
            novo["quantity"] = quantidade
            novo["unitPrice"] = float(preco_unit.quantize(Decimal("0.01")))
            novo.pop("item_id", None)
            itens_novos.append(novo)
            bruto += preco_unit * quantidade

        bruto = bruto.quantize(Decimal("0.01"))
        if desconto_percentual is not None:
            desconto_valor = (bruto * desconto_percentual / Decimal("100")).quantize(Decimal("0.01"))
            kit["Desconto"] = f"{desconto_percentual}%"
        else:
            desconto_valor = min(bruto, desconto_absoluto or Decimal("0"))
            kit["Desconto"] = float(desconto_valor)
        kit["Conteúdo"] = itens_novos
        kit["Valor avulso"] = float(bruto)
        kit["Preço"] = float((bruto - desconto_valor).quantize(Decimal("0.01")))
        atualizados.append(kit)
    return atualizados


def _chave_link_referencia(link: str) -> str:
    if not link:
        return ""
    partes = urlsplit(link)
    params = [(k.lower(), v) for k, v in parse_qsl(partes.query, keep_blank_values=True) if k.lower() not in {"show", "srsltid"} and not k.lower().startswith("utm_")]
    params.sort()
    return chave_texto(f"{partes.netloc}{partes.path}{params}")


def atualizar_albuns(albuns: list[dict[str, Any]], cartas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cartas_norm = [normalizar_carta_existente(x) for x in cartas]
    por_id = {texto(c.get("Id")): c for c in cartas_norm if texto(c.get("Id"))}
    por_link: dict[str, list[dict[str, Any]]] = {}
    por_nome: dict[str, list[dict[str, Any]]] = {}
    for carta in cartas_norm:
        link_key = _chave_link_referencia(texto(carta.get("Link Liga")))
        if link_key:
            por_link.setdefault(link_key, []).append(carta)
        for key in _chaves_nome_produto(carta, "cards"):
            por_nome.setdefault(key, []).append(carta)

    resultado: list[dict[str, Any]] = []
    for bruto in albuns:
        album = normalizar_album(bruto)
        paginas_novas: list[Any] = []
        for pagina in album.get("Páginas", []):
            slots = pagina.get("slots") if isinstance(pagina, dict) else pagina if isinstance(pagina, list) else []
            if not isinstance(slots, list):
                slots = []
            novos_slots: list[Any] = []
            for slot in slots:
                if not isinstance(slot, dict):
                    novos_slots.append(None if slot is None else slot)
                    continue
                novo = dict(slot)
                item_id = texto(slot.get("itemId") or slot.get("cardId"))
                carta = por_id.get(item_id)
                if carta is None:
                    link_key = _chave_link_referencia(texto(slot.get("linkLiga") or slot.get("link")))
                    candidatos = por_link.get(link_key, []) if link_key else []
                    if len(candidatos) == 1:
                        carta = candidatos[0]
                if carta is None:
                    nome = texto(slot.get("name") or slot.get("nome"))
                    numero_slot = texto(slot.get("number") or slot.get("numero"))
                    candidatos = por_nome.get(chave_texto(f"{nome} ({numero_slot})"), []) if nome and numero_slot else por_nome.get(chave_texto(nome), [])
                    candidatos = list({texto(c.get("Id")): c for c in candidatos}.values())
                    if len(candidatos) == 1:
                        carta = candidatos[0]
                if carta is not None:
                    novo.update({
                        "itemId": carta["Id"],
                        "linkLiga": carta.get("Link Liga", ""),
                        "language": carta.get("Idioma", ""),
                        "condition": carta.get("Estado", ""),
                        "name": carta.get("Nome", ""),
                        "number": carta.get("Número", ""),
                        "collection": carta.get("Coleção", ""),
                    })
                    novo.pop("cardId", None)
                novos_slots.append(novo)
            paginas_novas.append({"slots": novos_slots})
        album["Páginas"] = paginas_novas
        resultado.append(album)
    return resultado


def _remapear_referencias_ids(
    kits: list[dict[str, Any]], albuns: list[dict[str, Any]], mapa_ids: dict[str, str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Atualiza referências criadas no site quando o Gerenciamento enriquece o Id após consultar a Liga."""
    if not mapa_ids:
        return kits, albuns

    def novo_id(valor: Any) -> str:
        atual = texto(valor)
        return texto(mapa_ids.get(atual)) or atual

    for kit in kits:
        conteudo = kit.get("Conteúdo")
        if not isinstance(conteudo, list):
            continue
        for entrada in conteudo:
            if not isinstance(entrada, dict):
                continue
            ref = texto(entrada.get("itemId") or entrada.get("item_id"))
            if ref:
                entrada["itemId"] = novo_id(ref)
                entrada.pop("item_id", None)

    for album in albuns:
        paginas = album.get("Páginas")
        if not isinstance(paginas, list):
            continue
        for pagina in paginas:
            slots = pagina.get("slots") if isinstance(pagina, dict) else pagina if isinstance(pagina, list) else []
            if not isinstance(slots, list):
                continue
            for slot in slots:
                if not isinstance(slot, dict):
                    continue
                ref = texto(slot.get("itemId") or slot.get("cardId"))
                if ref:
                    slot["itemId"] = novo_id(ref)
                    slot.pop("cardId", None)
    return kits, albuns


def _consultar_uma_carta(linha: dict[str, Any], sessao: SessaoLiga) -> tuple[dict[str, Any], str]:
    link = texto(primeiro(linha, "Link Liga", "Liga", "Link"))
    if not link:
        return {}, "Link Liga vazio"
    try:
        return sessao.consultar_carta(link, texto(primeiro(linha, "Idioma")) or "BR", texto(primeiro(linha, "Estado")) or "NM"), ""
    except Exception as erro:
        return {}, str(erro)


def _consultar_um_booster(linha: dict[str, Any], sessao: SessaoLiga) -> tuple[dict[str, Any], str]:
    link = texto(primeiro(linha, "Link Liga", "Liga", "Link"))
    if not link:
        return {}, "Link Liga vazio"
    try:
        return sessao.consultar_booster(link), ""
    except Exception as erro:
        return {}, str(erro)


def _status_tem_erro_cotizacao(item: dict[str, Any]) -> bool:
    status = item.get("Status")
    if not isinstance(status, dict):
        return False
    motivos = status.get("motivos")
    return isinstance(motivos, list) and any(
        isinstance(motivo, dict) and texto(motivo.get("codigo")) == "erro_cotizacao"
        for motivo in motivos
    )


def _upsert_id(itens: list[dict[str, Any]], novo: dict[str, Any]) -> None:
    item_id = texto(novo.get("Id"))
    for indice, atual in enumerate(itens):
        if texto(atual.get("Id")) == item_id:
            itens[indice] = novo
            return
    itens.append(novo)


def formatar_nova_colecao(item: Path, modo: str) -> Path:
    with abrir_pacote(item, ARQUIVO_PERFIL) as origem:
        perfil = ler_json_obj(origem / ARQUIVO_PERFIL)
        identificador = identificar_colecao(perfil, origem.name)
        destino = pasta_colecoes() / identificador
        destino.mkdir(parents=True, exist_ok=True)
        migrar_historicos_embutidos(destino)

        estado_path = destino / ARQUIVO_FORMATACAO_PARCIAL
        estado = ler_json_obj(estado_path)
        if not estado:
            estado = {
                "formatacaoId": f"formatacao-{uuid.uuid4().hex[:12]}",
                "data": agora_iso(),
                "cartas": [],
                "boosters": [],
                "errosPendentes": {"cartas": {}, "boosters": {}},
                "mapeamentoIds": {},
            }
        estado.setdefault("errosPendentes", {"cartas": {}, "boosters": {}})
        estado.setdefault("mapeamentoIds", {})
        estado["errosPendentes"].setdefault("cartas", {})
        estado["errosPendentes"].setdefault("boosters", {})
        cotacao_id, data = estado["formatacaoId"], estado["data"]
        mapa_ids: dict[str, str] = estado["mapeamentoIds"]
        perfil.update({"collectionId": identificador, "pricingMode": modo, "updatedAt": agora_iso(), "formattingComplete": False})
        escrever_json_obj(destino / ARQUIVO_PERFIL, perfil)

        cartas_origem = ler_inventario(origem, "cartas")
        boosters_origem = ler_inventario(origem, "boosters")
        cartas = [normalizar_carta_existente(x) for x in ler_inventario(destino, "cartas")]
        boosters = [normalizar_booster_existente(x) for x in ler_inventario(destino, "boosters")]
        processadas = set(estado.get("cartas") or [])
        processados_boosters = set(estado.get("boosters") or [])

        # Compatibilidade com estados parciais criados pela versão antiga: um item
        # salvo com erro nunca pode continuar contado como concluído.
        for carta in list(cartas):
            if _status_tem_erro_cotizacao(carta):
                processadas.discard(texto(carta.get("Id")))
                cartas.remove(carta)
        for booster in list(boosters):
            if _status_tem_erro_cotizacao(booster):
                processados_boosters.discard(texto(booster.get("Id")))
                boosters.remove(booster)

        def salvar_estado() -> None:
            estado["cartas"] = sorted(processadas)
            estado["boosters"] = sorted(processados_boosters)
            escrever_json_obj(estado_path, estado)
            if SALVAR_PARCIAL:
                escrever_inventario(destino, "cartas", cartas)
                escrever_inventario(destino, "boosters", boosters)

        pendentes_cartas = [
            (indice, linha, identificador_carta(normalizar_carta_existente(linha)))
            for indice, linha in enumerate(cartas_origem, 1)
            if identificador_carta(normalizar_carta_existente(linha)) not in processadas
        ]
        pendentes_boosters = [
            (indice, linha, identificador_booster(normalizar_booster_existente(linha)))
            for indice, linha in enumerate(boosters_origem, 1)
            if identificador_booster(normalizar_booster_existente(linha)) not in processados_boosters
        ]

        if pendentes_cartas or pendentes_boosters:
            with SessaoLiga() as sessao:
                # Uma tentativa normal + uma repetição automática apenas dos que falharam.
                for tentativa in (1, 2):
                    falhas_cartas: list[tuple[int, dict[str, Any], str]] = []
                    for indice, linha, chave_pre in pendentes_cartas:
                        if chave_pre in processadas:
                            continue
                        prefixo = "Repetindo" if tentativa == 2 else "Carta"
                        print(f"{prefixo} {indice}/{len(cartas_origem)}: {texto(primeiro(linha, 'Nome')) or primeiro(linha, 'Link Liga', 'Link')}")
                        dados, erro = _consultar_uma_carta(linha, sessao)
                        if erro:
                            estado["errosPendentes"]["cartas"][chave_pre] = {"erro": erro, "tentativa": tentativa, "em": agora_iso()}
                            anexar_historico(destino, "cartas", _registro_falha(linha, "cartas", cotacao_id, erro))
                            falhas_cartas.append((indice, linha, chave_pre))
                            salvar_estado()
                            continue
                        nova, registro = montar_carta_nova(linha, dados, modo, cotacao_id, data)
                        imagem = baixar_imagem(texto(dados.get("imagem")), f"{nova['Nome']}_{nova['Número']}")
                        if imagem:
                            nova["Imagem"] = imagem
                        _upsert_id(cartas, nova)
                        mapa_ids[chave_pre] = nova["Id"]
                        id_origem = texto(linha.get("Id") or linha.get("id"))
                        if id_origem:
                            mapa_ids[id_origem] = nova["Id"]
                        anexar_historico(destino, "cartas", registro)
                        processadas.add(chave_pre)
                        estado["errosPendentes"]["cartas"].pop(chave_pre, None)
                        salvar_estado()

                    falhas_boosters: list[tuple[int, dict[str, Any], str]] = []
                    for indice, linha, chave_pre in pendentes_boosters:
                        if chave_pre in processados_boosters:
                            continue
                        prefixo = "Repetindo booster" if tentativa == 2 else "Booster"
                        print(f"{prefixo} {indice}/{len(boosters_origem)}: {texto(primeiro(linha, 'Tipo de pacote', 'Nome')) or primeiro(linha, 'Link Liga', 'Link')}")
                        dados, erro = _consultar_um_booster(linha, sessao)
                        if erro:
                            estado["errosPendentes"]["boosters"][chave_pre] = {"erro": erro, "tentativa": tentativa, "em": agora_iso()}
                            anexar_historico(destino, "boosters", _registro_falha(linha, "boosters", cotacao_id, erro))
                            falhas_boosters.append((indice, linha, chave_pre))
                            salvar_estado()
                            continue
                        novo, registro = montar_booster_novo(linha, dados, modo, cotacao_id, data)
                        imagem = baixar_imagem(texto(dados.get("imagem")), f"Booster_{novo['Tipo de pacote']}")
                        if imagem:
                            novo["Imagem"] = imagem
                        _upsert_id(boosters, novo)
                        mapa_ids[chave_pre] = novo["Id"]
                        id_origem = texto(linha.get("Id") or linha.get("id"))
                        if id_origem:
                            mapa_ids[id_origem] = novo["Id"]
                        anexar_historico(destino, "boosters", registro)
                        processados_boosters.add(chave_pre)
                        estado["errosPendentes"]["boosters"].pop(chave_pre, None)
                        salvar_estado()

                    if not falhas_cartas and not falhas_boosters:
                        break
                    if tentativa == 1:
                        total_falhas = len(falhas_cartas) + len(falhas_boosters)
                        print(f"{total_falhas} item(ns) falharam; repetindo somente esses itens...")
                        pendentes_cartas = falhas_cartas
                        pendentes_boosters = falhas_boosters

        escrever_inventario(destino, "cartas", cartas)
        escrever_inventario(destino, "boosters", boosters)
        salvar_estado()

        total_pendentes = len(estado["errosPendentes"]["cartas"]) + len(estado["errosPendentes"]["boosters"])
        if total_pendentes:
            perfil.update({"updatedAt": agora_iso(), "formattingComplete": False, "formattingPending": total_pendentes})
            escrever_json_obj(destino / ARQUIVO_PERFIL, perfil)
            print(f"Formatação parcial salva: {total_pendentes} item(ns) ainda pendente(s). Execute novamente para retomar.")
            return destino

        kits_origem = [normalizar_kit(x) for x in ler_inventario(origem, "kits")]
        produtos = [normalizar_produto(x) for x in ler_inventario(origem, "produtos")]
        albuns_origem = [normalizar_album(x) for x in ler_inventario(origem, "albuns")]
        kits_origem, albuns_origem = _remapear_referencias_ids(kits_origem, albuns_origem, mapa_ids)
        kits = atualizar_kits(kits_origem, cartas, boosters)
        albuns = atualizar_albuns(albuns_origem, cartas)
        escrever_inventario(destino, "kits", kits)
        escrever_inventario(destino, "produtos", produtos)
        escrever_inventario(destino, "albuns", albuns)
        perfil.pop("formattingPending", None)
        perfil.update({"updatedAt": agora_iso(), "formattingComplete": True})
        escrever_json_obj(destino / ARQUIVO_PERFIL, perfil)
        estado_path.unlink(missing_ok=True)
        arquivar_csvs_legados(destino)
        return destino

def _localizar_destino(identificador: str) -> Path:
    chave = chave_texto(identificador)
    for colecao in listar_colecoes():
        perfil = ler_json_obj(colecao / ARQUIVO_PERFIL)
        if chave_texto(colecao.name) == chave or chave_texto(perfil.get("collectionId")) == chave:
            return colecao
    raise FileNotFoundError(f"Coleção de destino não encontrada: {identificador}")


def modo_da_colecao(colecao: Path, padrao: str = MODO_MENOR) -> str:
    modo = texto(ler_json_obj(colecao / ARQUIVO_PERFIL).get("pricingMode")).lower()
    return modo if modo in {MODO_MENOR, MODO_MEDIA} else padrao


def _mesclar_cartas(existentes: list[dict[str, Any]], novas: list[dict[str, Any]]) -> None:
    indice = {normalizar_carta_existente(x)["Id"]: x for x in existentes}
    for nova_bruta in novas:
        nova = normalizar_carta_existente(nova_bruta)
        atual = indice.get(nova["Id"])
        if atual is None:
            existentes.append(nova)
            indice[nova["Id"]] = nova
            continue
        atual["Quantidade"] = inteiro(atual.get("Quantidade")) + inteiro(nova.get("Quantidade"))
        # Metadados existentes nunca são apagados por campos vazios da atualização.
        for campo in (
            "Nome", "Número", "Coleção", "Idioma", "Estado", "Ano", "Tipo",
            "Link Liga", "Link MYP", "Link Cardmarket", "Link Tcgplayer", "Link PriceCharting", "Imagem",
        ):
            if not texto(atual.get(campo)) and texto(nova.get(campo)):
                atual[campo] = nova[campo]
        for campo in (
            "Minimo Certeiro", "Minimo", "Menor Liga", "Segundo Menor Liga", "Terceiro Menor Liga",
            "Media Liga", "Mediana Liga", "Venda Rapida",
            "Vendedores Geral", "Vendedores Específicos", "Compradores Geral", "Compradores Específicos",
            "Alteração de preço", "Preço coletado", "Preço estimado", "Status", "Última cotação",
        ):
            if nova.get(campo) not in (None, "", {}, []):
                atual[campo] = nova[campo]
        atual.pop("Histórico de preços", None)


def _mesclar_boosters(existentes: list[dict[str, Any]], novos: list[dict[str, Any]]) -> None:
    indice = {normalizar_booster_existente(x)["Id"]: x for x in existentes}
    for novo_bruto in novos:
        novo = normalizar_booster_existente(novo_bruto)
        atual = indice.get(novo["Id"])
        if atual is None:
            existentes.append(novo)
            indice[novo["Id"]] = novo
            continue
        atual["Quantidade"] = inteiro(atual.get("Quantidade")) + inteiro(novo.get("Quantidade"))
        if not texto(atual.get("Imagem")) and texto(novo.get("Imagem")):
            atual["Imagem"] = novo["Imagem"]
        for campo in (
            "Minimo Certeiro", "Minimo", "Menor Liga", "Segundo Menor Liga", "Terceiro Menor Liga",
            "Media Liga", "Mediana Liga", "Venda Rapida",
            "Vendedores Geral", "Vendedores Específicos", "Compradores Geral", "Compradores Específicos",
            "Alteração de preço", "Preço coletado", "Preço estimado", "Status", "Última cotação",
        ):
            if novo.get(campo) not in (None, "", {}, []):
                atual[campo] = novo[campo]
        atual.pop("Histórico de preços", None)


def _operacao_patch(linha: dict[str, Any]) -> bool:
    return chave_texto(linha.get("operation") or linha.get("_operation")) in {"PATCH", "EDIT", "EDITAR"}


def _aplicar_patches_usuario(existentes: list[dict[str, Any]], patches: list[dict[str, Any]], tipo: str) -> None:
    """Aplica edições manuais e invalida a cotização quando a identidade de mercado muda."""
    normalizador = normalizar_carta_existente if tipo == "cartas" else normalizar_booster_existente
    indice = {normalizador(item)["Id"]: item for item in existentes}
    for patch in patches:
        patch_id = texto(patch.get("Id") or patch.get("ID") or patch.get("id"))
        if not patch_id:
            patch_id = normalizador(patch)["Id"]
        atual = indice.get(patch_id)
        if atual is None:
            raise ValueError(f"Patch de {tipo} aponta para item inexistente: {patch_id}")

        identidade_alterada = False
        if tipo == "cartas":
            campos_texto = {
                "Nome": "Nome", "Número": "Número", "Coleção": "Coleção", "Ano": "Ano", "Tipo": "Tipo",
                "Idioma": "Idioma", "Estado": "Estado", "Link Liga": "Link Liga", "Link MYP": "Link MYP",
                "Link Cardmarket": "Link Cardmarket", "Link Tcgplayer": "Link Tcgplayer",
                "Link PriceCharting": "Link PriceCharting", "Imagem": "Imagem",
            }
            for origem, destino in campos_texto.items():
                if origem not in patch:
                    continue
                novo_valor = texto(patch.get(origem))
                if destino == "Estado" and novo_valor:
                    novo_valor = normalizar_estado(novo_valor)
                if destino == "Idioma" and novo_valor:
                    novo_valor = idioma_saida(novo_valor)
                if destino in {"Idioma", "Estado", "Link Liga"} and texto(atual.get(destino)) != novo_valor:
                    identidade_alterada = True
                atual[destino] = novo_valor
            if "Favorita" in patch or "Favorito" in patch:
                atual["Favorita"] = _sim_nao(primeiro(patch, "Favorita", "Favorito"), False)
        else:
            if "Tipo de pacote" in patch:
                atual["Tipo de pacote"] = texto(patch.get("Tipo de pacote"))
            if "Imagem" in patch:
                atual["Imagem"] = texto(patch.get("Imagem"))
            if "Link Liga" in patch:
                novo_link = texto(patch.get("Link Liga"))
                identidade_alterada = texto(atual.get("Link Liga")) != novo_link
                atual["Link Liga"] = novo_link

        if "Preço" in patch:
            atual["Preço"] = numero(patch.get("Preço"))
        if "Quantidade" in patch:
            atual["Quantidade"] = inteiro(patch.get("Quantidade"))
        if "À venda" in patch or "Venda" in patch:
            atual["À venda"] = _sim_nao(primeiro(patch, "À venda", "Venda"), True)

        if identidade_alterada:
            for campo in (
                "Minimo Certeiro", "Minimo", "Menor Liga", "Segundo Menor Liga", "Terceiro Menor Liga",
                "Media Liga", "Mediana Liga", "Venda Rapida", "Vendedores Geral", "Vendedores Específicos",
                "Compradores Geral", "Compradores Específicos", "Preço coletado", "Preço estimado", "Última cotação",
            ):
                atual.pop(campo, None)
            atual["Alteração de preço"] = "Cadastro de mercado editado; recotização necessária"
            atual["Status"] = {
                "nível": "Suspeita leve",
                "motivos": [{
                    "nivel": "suspeita_leve",
                    "codigo": "cotizacao_desatualizada_por_edicao",
                    "mensagem": "Link, idioma ou estado foi editado. Faça uma nova cotização antes de usar as referências de mercado.",
                    "evidencia": {"itemId": patch_id},
                }],
            }


def _mesclar_kits(existentes: list[dict[str, Any]], novos: list[dict[str, Any]]) -> None:
    indice_id = {normalizar_kit(x)["Id"]: x for x in existentes}
    for novo_bruto in novos:
        novo = normalizar_kit(novo_bruto)
        atual = indice_id.get(novo["Id"])
        if atual is None:
            # Fallback só para pacotes legados, que ainda não possuíam Id estável.
            atual = next((x for x in existentes if chave_texto(x.get("Nome")) == chave_texto(novo.get("Nome"))), None)
        if atual is None:
            existentes.append(novo)
            indice_id[novo["Id"]] = novo
            continue
        substituir = chave_texto(novo_bruto.get("operation") or novo_bruto.get("_operation")) in {"UPSERT", "REPLACE", "SUBSTITUIR"}
        if substituir:
            atual.clear()
            atual.update(novo)
        else:
            atual["Quantidade"] = inteiro(atual.get("Quantidade")) + inteiro(novo.get("Quantidade"))
            for chave, valor in novo.items():
                if chave not in {"Quantidade", "operation", "_operation"} and valor not in (None, "", [], {}):
                    atual[chave] = valor


def _mesclar_produtos(existentes: list[dict[str, Any]], novos: list[dict[str, Any]]) -> None:
    indice = {normalizar_produto(x)["Id"]: x for x in existentes}
    for novo_bruto in novos:
        novo = normalizar_produto(novo_bruto)
        atual = indice.get(novo["Id"])
        if atual is None:
            atual = next((x for x in existentes if chave_texto(x.get("Nome")) == chave_texto(novo.get("Nome"))), None)
        if atual is None:
            existentes.append(novo)
            indice[novo["Id"]] = novo
        else:
            # Produtos enviados pelo editor são registros completos (upsert).
            atual.clear()
            atual.update(novo)


def _mesclar_albuns(existentes: list[dict[str, Any]], novos: list[dict[str, Any]]) -> None:
    indice = {normalizar_album(x)["Id"]: x for x in existentes}
    for novo_bruto in novos:
        novo = normalizar_album(novo_bruto)
        atual = indice.get(novo["Id"])
        if atual is None:
            existentes.append(novo)
            indice[novo["Id"]] = novo
        else:
            # Álbum de update representa o estado completo daquele álbum, não uma soma de páginas.
            atual.clear()
            atual.update(novo)


def _mesclar_perfil_editavel(perfil: dict[str, Any], perfil_update: dict[str, Any]) -> None:
    campos = (
        "owner", "title", "description", "email", "phone", "password",
        "selling", "showQuantity", "featured", "proposalTerms", "profilePhoto", "palette", "priceDisplayFallback",
    )
    for campo in campos:
        if campo in perfil_update:
            perfil[campo] = perfil_update[campo]


def atualizar_colecao(item: Path, modo_padrao: str = MODO_MENOR, destino_manual: Path | None = None) -> Path:
    with abrir_pacote(item, ARQUIVO_ATUALIZACAO) as origem:
        metadados = ler_json_obj(origem / ARQUIVO_ATUALIZACAO)
        identificador = texto(primeiro(metadados, "collectionId", "collection_id", "colecao"))
        destino = destino_manual or (_localizar_destino(identificador) if identificador else None)
        if destino is None:
            raise ValueError("A atualização não informa collectionId; selecione a coleção de destino.")
        recuperadas = recuperar_transacoes_pendentes(destino)
        if recuperadas:
            print("Atualização interrompida anteriormente restaurada antes de continuar.")
        migrar_historicos_embutidos(destino)

        perfil = ler_json_obj(destino / ARQUIVO_PERFIL)
        perfil_update = ler_json_obj(origem / ARQUIVO_PERFIL)
        modo = modo_da_colecao(destino, modo_padrao)
        assinatura = "|".join((identificador or destino.name, texto(metadados.get("version")), texto(metadados.get("generatedAt"))))
        update_id = texto(metadados.get("updateId")) or hashlib.sha256(assinatura.encode()).hexdigest()[:20]
        aplicadas = [texto(v) for v in perfil.get("appliedUpdates", [])]
        if update_id in aplicadas:
            print(f"Atualização {update_id} já aplicada; nada foi duplicado.")
            return destino

        # Nada do inventário oficial é modificado até TODAS as consultas terminarem.
        cartas = [normalizar_carta_existente(x) for x in ler_inventario(destino, "cartas")]
        boosters = [normalizar_booster_existente(x) for x in ler_inventario(destino, "boosters")]
        kits = [normalizar_kit(x) for x in ler_inventario(destino, "kits")]
        produtos = [normalizar_produto(x) for x in ler_inventario(destino, "produtos")]
        albuns = [normalizar_album(x) for x in ler_inventario(destino, "albuns")]
        todas_cartas_update = ler_inventario(origem, "cartas")
        todos_boosters_update = ler_inventario(origem, "boosters")
        patches_cartas = [x for x in todas_cartas_update if _operacao_patch(x)]
        patches_boosters = [x for x in todos_boosters_update if _operacao_patch(x)]
        novas_cartas_src = [x for x in todas_cartas_update if not _operacao_patch(x)]
        novos_boosters_src = [x for x in todos_boosters_update if not _operacao_patch(x)]
        novos_kits_src = ler_inventario(origem, "kits")
        novos_produtos_src = ler_inventario(origem, "produtos")
        novos_albuns_src = ler_inventario(origem, "albuns")
        cotacao_id = f"update-{update_id}"
        data = texto(metadados.get("generatedAt")) or agora_iso()
        novas_cartas: list[dict[str, Any]] = []
        novos_boosters: list[dict[str, Any]] = []
        historico_cartas: list[dict[str, Any]] = []
        historico_boosters: list[dict[str, Any]] = []
        mapa_ids: dict[str, str] = {}

        if novas_cartas_src or novos_boosters_src:
            with SessaoLiga() as sessao:
                for i, linha in enumerate(novas_cartas_src, 1):
                    print(f"Carta de atualização {i}/{len(novas_cartas_src)}")
                    dados, erro = _consultar_uma_carta(linha, sessao)
                    if erro:
                        anexar_historico(destino, "cartas", _registro_falha(linha, "cartas", cotacao_id, erro))
                        raise RuntimeError(f"Atualização cancelada sem alterar inventário: falha na carta {i}: {erro}")
                    nova, registro = montar_carta_nova(linha, dados, modo, cotacao_id, data)
                    imagem = baixar_imagem(texto(dados.get("imagem")), f"{nova['Nome']}_{nova['Número']}")
                    if imagem:
                        nova["Imagem"] = imagem
                    novas_cartas.append(nova)
                    chave_pre = identificador_carta(normalizar_carta_existente(linha))
                    mapa_ids[chave_pre] = nova["Id"]
                    id_origem = texto(linha.get("Id") or linha.get("id"))
                    if id_origem:
                        mapa_ids[id_origem] = nova["Id"]
                    historico_cartas.append(registro)
                for i, linha in enumerate(novos_boosters_src, 1):
                    print(f"Booster de atualização {i}/{len(novos_boosters_src)}")
                    dados, erro = _consultar_um_booster(linha, sessao)
                    if erro:
                        anexar_historico(destino, "boosters", _registro_falha(linha, "boosters", cotacao_id, erro))
                        raise RuntimeError(f"Atualização cancelada sem alterar inventário: falha no booster {i}: {erro}")
                    novo, registro = montar_booster_novo(linha, dados, modo, cotacao_id, data)
                    imagem = baixar_imagem(texto(dados.get("imagem")), f"Booster_{novo['Tipo de pacote']}")
                    if imagem:
                        novo["Imagem"] = imagem
                    novos_boosters.append(novo)
                    chave_pre = identificador_booster(normalizar_booster_existente(linha))
                    mapa_ids[chave_pre] = novo["Id"]
                    id_origem = texto(linha.get("Id") or linha.get("id"))
                    if id_origem:
                        mapa_ids[id_origem] = novo["Id"]
                    historico_boosters.append(registro)

        _aplicar_patches_usuario(cartas, patches_cartas, "cartas")
        _aplicar_patches_usuario(boosters, patches_boosters, "boosters")
        novos_kits = [normalizar_kit(x) for x in novos_kits_src]
        novos_produtos = [normalizar_produto(x) for x in novos_produtos_src]
        novos_albuns = [normalizar_album(x) for x in novos_albuns_src]
        novos_kits, novos_albuns = _remapear_referencias_ids(novos_kits, novos_albuns, mapa_ids)
        _mesclar_cartas(cartas, novas_cartas)
        _mesclar_boosters(boosters, novos_boosters)
        _mesclar_kits(kits, novos_kits)
        _mesclar_produtos(produtos, novos_produtos)
        _mesclar_albuns(albuns, novos_albuns)
        kits = atualizar_kits(kits, cartas, boosters)
        albuns = atualizar_albuns(albuns, cartas)
        _mesclar_perfil_editavel(perfil, perfil_update)
        perfil.update({
            "pricingMode": modo,
            "updatedAt": data,
            "version": max(int(perfil.get("version") or 1) + 1, int(metadados.get("version") or 0)),
            "appliedUpdates": [*aplicadas, update_id][-100:],
        })

        nomes = [ARQUIVO_PERFIL, *ARQUIVOS_INVENTARIO.values()]
        with transacao_arquivos(destino, nomes) as staging:
            escrever_json_obj(staging / ARQUIVO_PERFIL, perfil)
            escrever_inventario(staging, "cartas", cartas)
            escrever_inventario(staging, "boosters", boosters)
            escrever_inventario(staging, "kits", kits)
            escrever_inventario(staging, "produtos", produtos)
            escrever_inventario(staging, "albuns", albuns)
        if historico_cartas:
            anexar_historico(destino, "cartas", historico_cartas)
        if historico_boosters:
            anexar_historico(destino, "boosters", historico_boosters)
        arquivar_csvs_legados(destino)
        return destino

def cotizacao_pendente(colecao: Path) -> bool:
    return (colecao / ARQUIVO_COTIZACAO_PARCIAL).is_file()


def _ultima_cotacao(item: dict[str, Any]) -> datetime | None:
    ultima = item.get("Última cotação")
    if isinstance(ultima, dict) and ultima.get("data") and ultima.get("sucesso") is not False:
        try:
            return datetime.fromisoformat(str(ultima["data"]))
        except ValueError:
            pass
    # Fallback apenas para objetos legados ainda não migrados.
    hist = item.get("Histórico de preços")
    if isinstance(hist, list):
        for reg in reversed(hist):
            if isinstance(reg, dict) and reg.get("data") and reg.get("sucesso") is not False and not reg.get("erro"):
                try:
                    return datetime.fromisoformat(str(reg["data"]))
                except ValueError:
                    continue
    return None

def _selecionar_escopo(cartas: list[dict[str, Any]], boosters: list[dict[str, Any]], opcao: str, dias: int | None) -> tuple[list[dict[str, str]], str]:
    pares: list[tuple[str, dict[str, Any]]] = [("carta", x) for x in cartas] + [("booster", x) for x in boosters]
    descricao = "Coleção inteira"
    if opcao == "2":
        pares, descricao = [("carta", x) for x in cartas], "Apenas cartas"
    elif opcao == "3":
        pares, descricao = [("booster", x) for x in boosters], "Apenas boosters"
    elif opcao == "4":
        pares, descricao = [(t, x) for t, x in pares if _sim_nao(x.get("À venda"), True)], "Apenas itens à venda"
    elif opcao == "5":
        pares, descricao = [(t, x) for t, x in pares if numero(x.get("Preço")) is None], "Apenas itens sem preço"
    elif opcao == "6":
        dias = max(1, int(dias or 1))
        limite = datetime.now().astimezone() - timedelta(days=dias)
        pares = [(t, x) for t, x in pares if (_ultima_cotacao(x) is None or _ultima_cotacao(x) < limite)]
        descricao = f"Itens não cotizados há {dias} dias"
    return [{"tipo": t, "id": x["Id"]} for t, x in pares], descricao


def _totais_snapshot(cartas: list[dict[str, Any]], boosters: list[dict[str, Any]]) -> dict[str, float]:
    def soma(itens: list[dict[str, Any]], campo: str) -> float:
        return round(sum((numero(x.get(campo)) or 0) * inteiro(x.get("Quantidade")) for x in itens), 2)
    return {
        "preço": soma(cartas, "Preço") + soma(boosters, "Preço"),
        "minimoCerteiro": soma(cartas, "Minimo Certeiro") + soma(boosters, "Minimo Certeiro"),
        "buylist": soma(cartas, "Minimo") + soma(boosters, "Minimo"),
        "menor": soma(cartas, "Menor Liga") + soma(boosters, "Menor Liga"),
        "media": soma(cartas, "Media Liga") + soma(boosters, "Media Liga"),
        "vendaRapida": soma(cartas, "Venda Rapida") + soma(boosters, "Venda Rapida"),
    }


def cotizar_colecao(colecao: Path, modo_padrao: str = MODO_MENOR, opcao: str = "1", dias: int | None = None, retomar: bool = True) -> Path:
    recuperar_transacoes_pendentes(colecao)
    migrados = migrar_inventarios_legados(colecao)
    if migrados:
        arquivar_csvs_legados(colecao)
        print("Inventários legados convertidos para JSON: " + ", ".join(migrados))
    migrar_historicos_embutidos(colecao)

    modo = modo_da_colecao(colecao, modo_padrao)
    cartas = [normalizar_carta_existente(x) for x in ler_inventario(colecao, "cartas")]
    boosters = [normalizar_booster_existente(x) for x in ler_inventario(colecao, "boosters")]
    kits = [normalizar_kit(x) for x in ler_inventario(colecao, "kits")]
    albuns = [normalizar_album(x) for x in ler_inventario(colecao, "albuns")]
    estado_path = colecao / ARQUIVO_COTIZACAO_PARCIAL
    sessao = ler_json_obj(estado_path) if retomar else {}

    if not sessao:
        selecionados, descricao = _selecionar_escopo(cartas, boosters, opcao, dias)
        sessao = {
            "cotacaoId": f"cot-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}",
            "dataCotacao": agora_iso(),
            "escopo": descricao,
            "selecionados": selecionados,
            "processados": [],
            "resultados": [],
            "erros": [],
            "errosPendentes": {},
            "errosFatais": [],
            "tentativasFalhas": [],
            "semOfertas": [],
            "totaisAntes": _totais_snapshot(cartas, boosters),
        }
        escrever_json_obj(estado_path, sessao)
    else:
        sessao.setdefault("errosPendentes", {})
        sessao.setdefault("errosFatais", [])
        sessao.setdefault("tentativasFalhas", [])
        sessao["retomadaEm"] = agora_iso()
        escrever_json_obj(estado_path, sessao)
        print(f"Retomando cotização {sessao.get('cotacaoId')} — {len(sessao.get('processados', []))}/{len(sessao.get('selecionados', []))} concluídos.")

    processados = set(sessao.get("processados") or [])
    mapa_cartas = {x["Id"]: i for i, x in enumerate(cartas)}
    mapa_boosters = {x["Id"]: i for i, x in enumerate(boosters)}
    selecionados = list(sessao.get("selecionados") or [])

    # Salva a migração/IDs antes de começar; daí em diante cada sucesso é retomável.
    escrever_inventario(colecao, "cartas", cartas)
    escrever_inventario(colecao, "boosters", boosters)

    def salvar_progresso() -> None:
        sessao["processados"] = sorted(processados)
        escrever_json_obj(estado_path, sessao)

    def total_ofertas_marketplace(dados: dict[str, Any]) -> int:
        coleta = dados.get("coleta") if isinstance(dados.get("coleta"), dict) else {}
        market = coleta.get("marketplace") if isinstance(coleta.get("marketplace"), dict) else {}
        detectadas = int(market.get("detectadas") or 0)
        return detectadas if detectadas else int(dados.get("quantidade_ofertas") or 0)

    def registrar_falha(alvo: dict[str, Any], chave: str, nome: str, erro: str, tentativa: int, linha: dict[str, Any]) -> None:
        tipo_hist = "cartas" if alvo.get("tipo") == "carta" else "boosters"
        anexar_historico(colecao, tipo_hist, _registro_falha(linha, tipo_hist, sessao["cotacaoId"], erro))
        detalhe = {
            "tipo": alvo.get("tipo"), "id": alvo.get("id"), "nome": nome,
            "erro": erro, "tentativa": tentativa, "em": agora_iso(),
        }
        sessao["errosPendentes"][chave] = detalhe
        sessao["tentativasFalhas"].append(detalhe)
        salvar_progresso()

    pendentes_execucao = [alvo for alvo in selecionados if f"{alvo.get('tipo')}:{alvo.get('id')}" not in processados]

    if pendentes_execucao:
        with SessaoLiga() as liga:
            for tentativa in (1, 2):
                falharam: list[dict[str, Any]] = []
                for pos, alvo in enumerate(pendentes_execucao, 1):
                    tipo, item_id = alvo.get("tipo"), alvo.get("id")
                    chave = f"{tipo}:{item_id}"
                    if chave in processados:
                        continue

                    if tipo == "carta":
                        idx = mapa_cartas.get(item_id)
                        if idx is None:
                            mensagem = f"Carta {item_id}: não encontrada no inventário"
                            if mensagem not in sessao["errosFatais"]:
                                sessao["errosFatais"].append(mensagem)
                            processados.add(chave)
                            salvar_progresso()
                            continue
                        anterior = copy.deepcopy(cartas[idx])
                        nome = cartas[idx]["Nome"]
                        prefixo = "Repetindo" if tentativa == 2 else "Cotização"
                        print(f"{prefixo} {pos}/{len(pendentes_execucao)} — carta: {nome}")
                        dados, erro = _consultar_uma_carta(cartas[idx], liga)
                        if erro:
                            registrar_falha(alvo, chave, nome, erro, tentativa, cartas[idx])
                            falharam.append(alvo)
                            continue
                        nova, registro = cotizar_carta(cartas[idx], dados, modo, sessao["cotacaoId"], sessao["dataCotacao"])
                        if not texto(nova.get("Imagem")):
                            imagem = baixar_imagem(texto(dados.get("imagem")), f"{nova['Nome']}_{nova['Número']}")
                            if imagem:
                                nova["Imagem"] = imagem
                        cartas[idx] = nova
                        anexar_historico(colecao, "cartas", registro)
                        resultado = registrar_variacoes(nome, item_id, "carta", anterior, nova)
                        escrever_inventario(colecao, "cartas", cartas)
                    else:
                        idx = mapa_boosters.get(item_id)
                        if idx is None:
                            mensagem = f"Booster {item_id}: não encontrado no inventário"
                            if mensagem not in sessao["errosFatais"]:
                                sessao["errosFatais"].append(mensagem)
                            processados.add(chave)
                            salvar_progresso()
                            continue
                        anterior = copy.deepcopy(boosters[idx])
                        nome = boosters[idx]["Tipo de pacote"]
                        prefixo = "Repetindo" if tentativa == 2 else "Cotização"
                        print(f"{prefixo} {pos}/{len(pendentes_execucao)} — booster: {nome}")
                        dados, erro = _consultar_um_booster(boosters[idx], liga)
                        if erro:
                            registrar_falha(alvo, chave, nome, erro, tentativa, boosters[idx])
                            falharam.append(alvo)
                            continue
                        novo, registro = cotizar_booster(boosters[idx], dados, modo, sessao["cotacaoId"], sessao["dataCotacao"])
                        if not texto(novo.get("Imagem")):
                            imagem = baixar_imagem(texto(dados.get("imagem")), f"Booster_{novo['Tipo de pacote']}")
                            if imagem:
                                novo["Imagem"] = imagem
                        boosters[idx] = novo
                        anexar_historico(colecao, "boosters", registro)
                        resultado = registrar_variacoes(nome, item_id, "booster", anterior, novo)
                        escrever_inventario(colecao, "boosters", boosters)

                    sessao["resultados"] = [
                        r for r in sessao.get("resultados", [])
                        if r.get("id") != item_id or r.get("tipo") != tipo
                    ]
                    sessao["resultados"].append(resultado)
                    sessao["errosPendentes"].pop(chave, None)
                    sem = set(sessao.get("semOfertas") or [])
                    if total_ofertas_marketplace(dados) == 0:
                        sem.add(item_id)
                    else:
                        sem.discard(item_id)
                    sessao["semOfertas"] = sorted(sem)
                    processados.add(chave)
                    salvar_progresso()

                if not falharam:
                    break
                if tentativa == 1:
                    print(f"{len(falharam)} item(ns) falharam; repetindo somente esses itens...")
                    pendentes_execucao = falharam

    kits = atualizar_kits(kits, cartas, boosters)
    albuns = atualizar_albuns(albuns, cartas)
    escrever_inventario(colecao, "cartas", cartas)
    escrever_inventario(colecao, "boosters", boosters)
    escrever_inventario(colecao, "kits", kits)
    escrever_inventario(colecao, "albuns", albuns)

    pendentes = dict(sessao.get("errosPendentes") or {})
    sessao["erros"] = [*list(sessao.get("errosFatais") or []), *[
        f"{d.get('nome') or d.get('id')}: {d.get('erro')}" for d in pendentes.values() if isinstance(d, dict)
    ]]
    salvar_progresso()

    if pendentes:
        print(f"Cotização parcial salva: {len(pendentes)} item(ns) ainda pendente(s). Execute novamente para retomar.")
        return colecao

    perfil = ler_json_obj(colecao / ARQUIVO_PERFIL)
    perfil.update({"pricingMode": modo, "quotedAt": agora_iso()})
    escrever_json_obj(colecao / ARQUIVO_PERFIL, perfil)

    # O relatório final só é gerado quando todos os itens consultáveis terminaram.
    json_rel, txt_rel = salvar_relatorio(colecao, sessao, [], [], cartas, boosters)
    sessao["relatorioJson"] = str(json_rel.name)
    sessao["relatorioTxt"] = str(txt_rel.name)
    estado_path.unlink(missing_ok=True)
    return colecao

