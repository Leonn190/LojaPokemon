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
    arquivar_csvs_legados,
    escrever_inventario,
    escrever_json_obj,
    ler_inventario,
    ler_json_obj,
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
from liga import SessaoLiga, baixar_imagem, normalizar_estado, normalizar_idioma, valor_preco
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
    preservar = preservar or {}
    escolhido = valor_preco(dados, modo)
    menor = numero(dados.get("menor"))
    medio = numero(dados.get("medio"))
    minimo = numero(dados.get("minimo"))
    rapida = numero(dados.get("venda_rapida"))
    return {
        "Minimo": minimo if minimo is not None else numero(primeiro(preservar, "Minimo", "Mínimo", "Preço mínimo")),
        "Venda Rapida": rapida if rapida is not None else numero(primeiro(preservar, "Venda Rapida", "Venda Rápida", "Venda rápida")),
        "Menor Liga": menor if menor is not None else numero(primeiro(preservar, "Menor Liga", "Preço Liga mais barato")),
        "Preço Médio Liga": medio if medio is not None else numero(primeiro(preservar, "Preço Médio Liga", "Preço médio Liga")),
        "Preço": numero(escolhido) if escolhido is not None else numero(primeiro(preservar, "Preço")),
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
        "Minimo": numero(primeiro(linha, "Minimo", "Mínimo", "Preço mínimo")),
        "Venda Rapida": numero(primeiro(linha, "Venda Rapida", "Venda Rápida", "Venda rápida")),
        "Menor Liga": numero(primeiro(linha, "Menor Liga", "Preço Liga mais barato")),
        "Preço Médio Liga": numero(primeiro(linha, "Preço Médio Liga", "Preço médio Liga")),
        "Preço": numero(primeiro(linha, "Preço")),
        "Alteração de preço": texto(primeiro(linha, "Alteração de preço")),
        "Quantidade": inteiro(primeiro(linha, "Quantidade")),
        "À venda": _sim_nao(primeiro(linha, "À venda", "Venda"), True),
    })
    if not isinstance(carta.get("Histórico de preços"), list):
        carta["Histórico de preços"] = []
    if not isinstance(carta.get("Status"), dict):
        carta["Status"] = {"nível": "OK", "motivos": []}
    carta["Id"] = texto(carta.get("Id")) or identificador_carta(carta)
    return carta


def normalizar_booster_existente(linha: dict[str, Any]) -> dict[str, Any]:
    booster = dict(linha)
    booster.update({
        "Tipo de pacote": texto(primeiro(linha, "Tipo de pacote", "Coleção", "Nome")),
        "Quantidade": inteiro(primeiro(linha, "Quantidade")),
        "Preço mínimo": numero(primeiro(linha, "Preço mínimo", "Minimo", "Mínimo")),
        "Venda rápida": numero(primeiro(linha, "Venda rápida", "Venda Rapida", "Venda Rápida")),
        "Preço Liga mais barato": numero(primeiro(linha, "Preço Liga mais barato", "Menor Liga")),
        "Preço médio Liga": numero(primeiro(linha, "Preço médio Liga", "Preço Médio Liga")),
        "Preço": numero(primeiro(linha, "Preço")),
        "Alteração de preço": texto(primeiro(linha, "Alteração de preço")),
        "Link Liga": texto(primeiro(linha, "Link Liga", "Liga", "Link")),
        "À venda": _sim_nao(primeiro(linha, "À venda", "Venda"), True),
    })
    if not isinstance(booster.get("Histórico de preços"), list):
        booster["Histórico de preços"] = []
    if not isinstance(booster.get("Status"), dict):
        booster["Status"] = {"nível": "OK", "motivos": []}
    booster["Id"] = texto(booster.get("Id")) or identificador_booster(booster)
    return booster


def _conteudo_legado(conteudo: str) -> list[dict[str, Any]]:
    itens: list[dict[str, Any]] = []
    for trecho in re.split(r"\s*[|;]\s*", conteudo):
        trecho = trecho.strip()
        if not trecho:
            continue
        encontrado = re.match(r"(\d+)\s*[xX]\s*(.+)", trecho)
        quantidade, nome = (int(encontrado.group(1)), encontrado.group(2).strip()) if encontrado else (1, trecho)
        itens.append({"kind": "cards", "name": nome, "quantity": quantidade, "unitPrice": None})
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
            conteudo = _conteudo_legado(texto(primeiro(linha, "Conteúdo")))
    kit.update({
        "Nome": texto(primeiro(linha, "Nome")),
        "Descrição": texto(primeiro(linha, "Descrição")),
        "Preço": numero(primeiro(linha, "Preço")),
        "Quantidade": inteiro(primeiro(linha, "Quantidade")),
        "Conteúdo": conteudo,
        "Valor avulso": numero(primeiro(linha, "Valor avulso", "Preço bruto")),
        "Desconto": primeiro(linha, "Desconto"),
        "Imagem": texto(primeiro(linha, "Imagem")),
        "À venda": _sim_nao(primeiro(linha, "À venda", "Venda"), True),
    })
    kit.pop("Conteúdo JSON", None)
    return kit


def normalizar_album(linha: dict[str, Any]) -> dict[str, Any]:
    album = dict(linha)
    album.update({
        "Nome": texto(primeiro(linha, "Nome")),
        "Descrição": texto(primeiro(linha, "Descrição")),
        "Progresso": primeiro(linha, "Progresso"),
        "Quantidade": inteiro(primeiro(linha, "Quantidade")),
        "Imagem": texto(primeiro(linha, "Imagem")),
        "À venda": _sim_nao(primeiro(linha, "À venda", "Venda"), False),
    })
    return album


def montar_carta_nova(linha: dict[str, Any], dados: dict[str, Any], modo: str, cotacao_id: str, data: str, erro: str = "") -> dict[str, Any]:
    carta = normalizar_carta_existente(linha)
    carta["Nome"] = texto(dados.get("nome")) or carta["Nome"]
    carta["Número"] = texto(dados.get("numeracao")) or carta["Número"]
    carta["Coleção"] = texto(dados.get("colecao")) or carta["Coleção"]
    carta["Ano"] = texto(dados.get("ano")) or carta["Ano"]
    carta["Tipo"] = texto(dados.get("tipo")) or carta["Tipo"]
    carta["Idioma"] = idioma_saida(texto(primeiro(linha, "Idioma")) or "BR")
    carta["Estado"] = normalizar_estado(texto(primeiro(linha, "Estado")) or "NM")
    carta.update(_precos_atuais(dados, modo, carta))
    carta["Preço coletado"] = preco_objeto(dados, False)
    carta["Preço estimado"] = preco_objeto(dados, True)
    status = gerar_status_carta(dados, carta["Idioma"], carta["Estado"])
    if erro:
        status = {"nível": "Suspeita", "motivos": [*status.get("motivos", []), {"nivel": "suspeita", "codigo": "erro_cotizacao", "mensagem": f"Erro na cotização: {erro}"}]}
    carta["Status"] = status
    carta["Id"] = identificador_carta(carta)
    registrar_historico(carta, cotacao_id, data, status, erro)
    return carta


def cotizar_carta(linha: dict[str, Any], dados: dict[str, Any], modo: str, cotacao_id: str, data: str, erro: str = "") -> dict[str, Any]:
    carta = normalizar_carta_existente(linha)
    # Nunca toca nos dados cadastrais (Ano, Tipo, links etc.) durante cotização.
    if not erro:
        carta.update(_precos_atuais(dados, modo, carta))
        carta["Preço coletado"] = preco_objeto(dados, False)
        carta["Preço estimado"] = preco_objeto(dados, True)
    status = gerar_status_carta(dados, carta["Idioma"], carta["Estado"])
    if erro:
        status = {"nível": "Suspeita", "motivos": [{"nivel": "suspeita", "codigo": "erro_cotizacao", "mensagem": f"Erro na cotização: {erro}"}]}
    carta["Status"] = status
    registrar_historico(carta, cotacao_id, data, status, erro)
    return carta


def montar_booster_novo(linha: dict[str, Any], dados: dict[str, Any], modo: str, cotacao_id: str, data: str, erro: str = "") -> dict[str, Any]:
    booster = normalizar_booster_existente(linha)
    booster["Tipo de pacote"] = booster["Tipo de pacote"] or texto(dados.get("nome") or dados.get("colecao"))
    precos = _precos_atuais(dados, modo, booster)
    booster.update({
        "Preço mínimo": precos["Minimo"], "Venda rápida": precos["Venda Rapida"],
        "Preço Liga mais barato": precos["Menor Liga"], "Preço médio Liga": precos["Preço Médio Liga"],
        "Preço": precos["Preço"], "Alteração de preço": precos["Alteração de preço"],
        "Preço coletado": preco_objeto(dados, False), "Preço estimado": preco_objeto(dados, True),
    })
    status = gerar_status_booster(dados)
    if erro:
        status = {"nível": "Suspeita", "motivos": [{"nivel": "suspeita", "codigo": "erro_cotizacao", "mensagem": f"Erro na cotização: {erro}"}]}
    booster["Status"] = status
    booster["Id"] = identificador_booster(booster)
    registrar_historico(booster, cotacao_id, data, status, erro)
    return booster


def cotizar_booster(linha: dict[str, Any], dados: dict[str, Any], modo: str, cotacao_id: str, data: str, erro: str = "") -> dict[str, Any]:
    booster = normalizar_booster_existente(linha)
    if not erro:
        precos = _precos_atuais(dados, modo, booster)
        booster.update({
            "Preço mínimo": precos["Minimo"], "Venda rápida": precos["Venda Rapida"],
            "Preço Liga mais barato": precos["Menor Liga"], "Preço médio Liga": precos["Preço Médio Liga"],
            "Preço": precos["Preço"], "Alteração de preço": precos["Alteração de preço"],
            "Preço coletado": preco_objeto(dados, False), "Preço estimado": preco_objeto(dados, True),
        })
    status = gerar_status_booster(dados)
    if erro:
        status = {"nível": "Suspeita", "motivos": [{"nivel": "suspeita", "codigo": "erro_cotizacao", "mensagem": f"Erro na cotização: {erro}"}]}
    booster["Status"] = status
    registrar_historico(booster, cotacao_id, data, status, erro)
    return booster


def _indice_itens(linhas: list[dict[str, Any]], campo_nome: str) -> dict[str, Decimal]:
    indice: dict[str, Decimal] = {}
    for linha in linhas:
        nome = texto(primeiro(linha, campo_nome, "Nome", "Coleção"))
        preco = numero(primeiro(linha, "Preço", "Menor Liga", "Preço Liga mais barato"))
        if nome and preco is not None:
            indice.setdefault(chave_texto(nome), Decimal(str(preco)))
    return indice


def atualizar_kits(kits: list[dict[str, Any]], cartas: list[dict[str, Any]], boosters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    precos_cartas = _indice_itens(cartas, "Nome")
    precos_boosters = _indice_itens(boosters, "Tipo de pacote")
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
            nome = texto(item.get("name") or item.get("nome"))
            quantidade = inteiro(item.get("quantity") or item.get("quantidade"))
            tipo = chave_texto(item.get("kind") or item.get("tipo"))
            mapa = precos_boosters if tipo in {"BOOSTERS", "BOOSTER", "PACOTES", "PACOTE"} else precos_cartas
            preco_unit = mapa.get(chave_texto(nome))
            if preco_unit is None:
                preco_unit = Decimal(str(numero(item.get("unitPrice") or item.get("precoUnitario")) or 0))
            novo["quantity"] = quantidade
            novo["unitPrice"] = float(preco_unit.quantize(Decimal("0.01")))
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


def formatar_nova_colecao(item: Path, modo: str) -> Path:
    with abrir_pacote(item, ARQUIVO_PERFIL) as origem:
        perfil = ler_json_obj(origem / ARQUIVO_PERFIL)
        identificador = identificar_colecao(perfil, origem.name)
        destino = pasta_colecoes() / identificador
        destino.mkdir(parents=True, exist_ok=True)
        estado_path = destino / ARQUIVO_FORMATACAO_PARCIAL
        estado = ler_json_obj(estado_path)
        if not estado:
            estado = {"formatacaoId": f"formatacao-{uuid.uuid4().hex[:12]}", "data": agora_iso(), "cartas": [], "boosters": []}
        cotacao_id, data = estado["formatacaoId"], estado["data"]
        perfil.update({"collectionId": identificador, "pricingMode": modo, "updatedAt": agora_iso(), "formattingComplete": False})
        escrever_json_obj(destino / ARQUIVO_PERFIL, perfil)

        cartas_origem = ler_inventario(origem, "cartas")
        boosters_origem = ler_inventario(origem, "boosters")
        cartas = [normalizar_carta_existente(x) for x in ler_inventario(destino, "cartas")]
        boosters = [normalizar_booster_existente(x) for x in ler_inventario(destino, "boosters")]
        processadas = set(estado.get("cartas") or [])
        processados_boosters = set(estado.get("boosters") or [])

        with SessaoLiga() as sessao:
            for indice, linha in enumerate(cartas_origem, 1):
                chave_pre = identificador_carta(normalizar_carta_existente(linha))
                if chave_pre in processadas:
                    continue
                print(f"Carta {indice}/{len(cartas_origem)}: {texto(primeiro(linha, 'Nome')) or primeiro(linha, 'Link Liga', 'Link')}")
                dados, erro = _consultar_uma_carta(linha, sessao)
                nova = montar_carta_nova(linha, dados, modo, cotacao_id, data, erro)
                baixar_imagem(texto(dados.get("imagem")), f"{nova['Nome']}_{nova['Número']}")
                cartas.append(nova)
                processadas.add(chave_pre)
                estado["cartas"] = sorted(processadas)
                if SALVAR_PARCIAL:
                    escrever_inventario(destino, "cartas", cartas)
                    escrever_json_obj(estado_path, estado)
            for indice, linha in enumerate(boosters_origem, 1):
                chave_pre = identificador_booster(normalizar_booster_existente(linha))
                if chave_pre in processados_boosters:
                    continue
                print(f"Booster {indice}/{len(boosters_origem)}: {texto(primeiro(linha, 'Tipo de pacote', 'Nome')) or primeiro(linha, 'Link Liga', 'Link')}")
                dados, erro = _consultar_um_booster(linha, sessao)
                nova = montar_booster_novo(linha, dados, modo, cotacao_id, data, erro)
                boosters.append(nova)
                processados_boosters.add(chave_pre)
                estado["boosters"] = sorted(processados_boosters)
                if SALVAR_PARCIAL:
                    escrever_inventario(destino, "boosters", boosters)
                    escrever_json_obj(estado_path, estado)

        kits = atualizar_kits([normalizar_kit(x) for x in ler_inventario(origem, "kits")], cartas, boosters)
        albuns = [normalizar_album(x) for x in ler_inventario(origem, "albuns")]
        escrever_inventario(destino, "cartas", cartas)
        escrever_inventario(destino, "boosters", boosters)
        escrever_inventario(destino, "kits", kits)
        escrever_inventario(destino, "albuns", albuns)
        perfil.update({"updatedAt": agora_iso(), "formattingComplete": True})
        escrever_json_obj(destino / ARQUIVO_PERFIL, perfil)
        estado_path.unlink(missing_ok=True)
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
    for nova in novas:
        nova = normalizar_carta_existente(nova)
        atual = indice.get(nova["Id"])
        if atual is None:
            existentes.append(nova)
            indice[nova["Id"]] = nova
            continue
        atual["Quantidade"] = inteiro(atual.get("Quantidade")) + inteiro(nova.get("Quantidade"))
        # Metadados já existentes nunca são apagados por campos vazios da atualização.
        for campo in ("Nome", "Número", "Coleção", "Idioma", "Estado", "Ano", "Tipo", "Link Liga", "Link MYP", "Link Cardmarket", "Link Tcgplayer", "Link PriceCharting"):
            if not texto(atual.get(campo)) and texto(nova.get(campo)):
                atual[campo] = nova[campo]
        for campo in ("Minimo", "Venda Rapida", "Menor Liga", "Preço Médio Liga", "Preço", "Alteração de preço", "Preço coletado", "Preço estimado", "Status"):
            if nova.get(campo) not in (None, "", {}, []):
                atual[campo] = nova[campo]
        hist = atual.setdefault("Histórico de preços", [])
        for reg in nova.get("Histórico de preços", []):
            if isinstance(reg, dict) and not any(isinstance(h, dict) and h.get("cotacaoId") == reg.get("cotacaoId") for h in hist):
                hist.append(reg)


def _mesclar_boosters(existentes: list[dict[str, Any]], novos: list[dict[str, Any]]) -> None:
    indice = {normalizar_booster_existente(x)["Id"]: x for x in existentes}
    for novo in novos:
        novo = normalizar_booster_existente(novo)
        atual = indice.get(novo["Id"])
        if atual is None:
            existentes.append(novo); indice[novo["Id"]] = novo; continue
        atual["Quantidade"] = inteiro(atual.get("Quantidade")) + inteiro(novo.get("Quantidade"))
        for campo in ("Preço mínimo", "Venda rápida", "Preço Liga mais barato", "Preço médio Liga", "Preço", "Alteração de preço", "Preço coletado", "Preço estimado", "Status"):
            if novo.get(campo) not in (None, "", {}, []):
                atual[campo] = novo[campo]
        hist = atual.setdefault("Histórico de preços", [])
        for reg in novo.get("Histórico de preços", []):
            if isinstance(reg, dict) and not any(isinstance(h, dict) and h.get("cotacaoId") == reg.get("cotacaoId") for h in hist):
                hist.append(reg)


def _mesclar_kits(existentes: list[dict[str, Any]], novos: list[dict[str, Any]]) -> None:
    for novo in novos:
        novo = normalizar_kit(novo)
        atual = next((x for x in existentes if chave_texto(x.get("Nome")) == chave_texto(novo.get("Nome"))), None)
        if atual is None:
            existentes.append(novo)
        else:
            atual["Quantidade"] = inteiro(atual.get("Quantidade")) + inteiro(novo.get("Quantidade"))
            for chave, valor in novo.items():
                if chave != "Quantidade" and valor not in (None, "", [], {}):
                    atual[chave] = valor


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

        perfil = ler_json_obj(destino / ARQUIVO_PERFIL)
        modo = modo_da_colecao(destino, modo_padrao)
        assinatura = "|".join((identificador or destino.name, texto(metadados.get("version")), texto(metadados.get("generatedAt"))))
        update_id = texto(metadados.get("updateId")) or hashlib.sha256(assinatura.encode()).hexdigest()[:20]
        aplicadas = [texto(v) for v in perfil.get("appliedUpdates", [])]
        if update_id in aplicadas:
            print(f"Atualização {update_id} já aplicada; nada foi duplicado.")
            return destino

        # Tudo abaixo fica somente em memória até TODAS as consultas terminarem.
        cartas = [normalizar_carta_existente(x) for x in ler_inventario(destino, "cartas")]
        boosters = [normalizar_booster_existente(x) for x in ler_inventario(destino, "boosters")]
        kits = [normalizar_kit(x) for x in ler_inventario(destino, "kits")]
        albuns = [normalizar_album(x) for x in ler_inventario(destino, "albuns")]
        novas_cartas_src = ler_inventario(origem, "cartas")
        novos_boosters_src = ler_inventario(origem, "boosters")
        cotacao_id = f"update-{update_id}"
        data = texto(metadados.get("generatedAt")) or agora_iso()
        novas_cartas: list[dict[str, Any]] = []
        novos_boosters: list[dict[str, Any]] = []

        with SessaoLiga() as sessao:
            for i, linha in enumerate(novas_cartas_src, 1):
                print(f"Carta de atualização {i}/{len(novas_cartas_src)}")
                dados, erro = _consultar_uma_carta(linha, sessao)
                if erro:
                    raise RuntimeError(f"Atualização cancelada sem salvar: falha na carta {i}: {erro}")
                novas_cartas.append(montar_carta_nova(linha, dados, modo, cotacao_id, data))
            for i, linha in enumerate(novos_boosters_src, 1):
                print(f"Booster de atualização {i}/{len(novos_boosters_src)}")
                dados, erro = _consultar_um_booster(linha, sessao)
                if erro:
                    raise RuntimeError(f"Atualização cancelada sem salvar: falha no booster {i}: {erro}")
                novos_boosters.append(montar_booster_novo(linha, dados, modo, cotacao_id, data))

        _mesclar_cartas(cartas, novas_cartas)
        _mesclar_boosters(boosters, novos_boosters)
        _mesclar_kits(kits, [normalizar_kit(x) for x in ler_inventario(origem, "kits")])
        kits = atualizar_kits(kits, cartas, boosters)
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
            escrever_inventario(staging, "albuns", albuns)
        arquivar_csvs_legados(destino)
        return destino


def cotizacao_pendente(colecao: Path) -> bool:
    return (colecao / ARQUIVO_COTIZACAO_PARCIAL).is_file()


def _ultima_cotacao(item: dict[str, Any]) -> datetime | None:
    hist = item.get("Histórico de preços")
    if not isinstance(hist, list) or not hist:
        return None
    for reg in reversed(hist):
        if isinstance(reg, dict) and reg.get("data"):
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
        "media": soma(cartas, "Preço Médio Liga") + soma(boosters, "Preço médio Liga"),
        "menor": soma(cartas, "Menor Liga") + soma(boosters, "Preço Liga mais barato"),
        "buylist": soma(cartas, "Minimo") + soma(boosters, "Preço mínimo"),
    }


def cotizar_colecao(colecao: Path, modo_padrao: str = MODO_MENOR, opcao: str = "1", dias: int | None = None, retomar: bool = True) -> Path:
    recuperar_transacoes_pendentes(colecao)
    migrados = migrar_inventarios_legados(colecao)
    if migrados:
        arquivar_csvs_legados(colecao)
        print("Inventários legados convertidos para JSON: " + ", ".join(migrados))
    modo = modo_da_colecao(colecao, modo_padrao)
    cartas = [normalizar_carta_existente(x) for x in ler_inventario(colecao, "cartas")]
    boosters = [normalizar_booster_existente(x) for x in ler_inventario(colecao, "boosters")]
    kits = [normalizar_kit(x) for x in ler_inventario(colecao, "kits")]
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
            "semOfertas": [],
            "totaisAntes": _totais_snapshot(cartas, boosters),
        }
        escrever_json_obj(estado_path, sessao)
    else:
        sessao["retomadaEm"] = agora_iso()
        escrever_json_obj(estado_path, sessao)
        print(f"Retomando cotização {sessao.get('cotacaoId')} — {len(sessao.get('processados', []))}/{len(sessao.get('selecionados', []))} concluídos.")

    processados = set(sessao.get("processados") or [])
    mapa_cartas = {x["Id"]: i for i, x in enumerate(cartas)}
    mapa_boosters = {x["Id"]: i for i, x in enumerate(boosters)}
    selecionados = list(sessao.get("selecionados") or [])

    # Salva a migração/IDs antes de começar; daí em diante cada item pode ser retomado.
    escrever_inventario(colecao, "cartas", cartas)
    escrever_inventario(colecao, "boosters", boosters)

    with SessaoLiga() as liga:
        for pos, alvo in enumerate(selecionados, 1):
            chave = f"{alvo.get('tipo')}:{alvo.get('id')}"
            if chave in processados:
                continue
            tipo, item_id = alvo.get("tipo"), alvo.get("id")
            if tipo == "carta":
                idx = mapa_cartas.get(item_id)
                if idx is None:
                    sessao["erros"].append(f"Carta {item_id}: não encontrada no inventário")
                    processados.add(chave); sessao["processados"] = sorted(processados); escrever_json_obj(estado_path, sessao); continue
                anterior = copy.deepcopy(cartas[idx])
                print(f"Cotização {pos}/{len(selecionados)} — carta: {cartas[idx]['Nome']}")
                dados, erro = _consultar_uma_carta(cartas[idx], liga)
                cartas[idx] = cotizar_carta(cartas[idx], dados, modo, sessao["cotacaoId"], sessao["dataCotacao"], erro)
                resultado = registrar_variacoes(cartas[idx]["Nome"], item_id, "carta", anterior, cartas[idx])
                if erro:
                    sessao["erros"].append(f"{cartas[idx]['Nome']} ({item_id}): {erro}")
                if int(dados.get("quantidade_ofertas") or 0) == 0:
                    sessao["semOfertas"].append(item_id)
                escrever_inventario(colecao, "cartas", cartas)
            else:
                idx = mapa_boosters.get(item_id)
                if idx is None:
                    sessao["erros"].append(f"Booster {item_id}: não encontrado no inventário")
                    processados.add(chave); sessao["processados"] = sorted(processados); escrever_json_obj(estado_path, sessao); continue
                anterior = copy.deepcopy(boosters[idx])
                print(f"Cotização {pos}/{len(selecionados)} — booster: {boosters[idx]['Tipo de pacote']}")
                dados, erro = _consultar_um_booster(boosters[idx], liga)
                boosters[idx] = cotizar_booster(boosters[idx], dados, modo, sessao["cotacaoId"], sessao["dataCotacao"], erro)
                resultado = registrar_variacoes(boosters[idx]["Tipo de pacote"], item_id, "booster", anterior, boosters[idx])
                if erro:
                    sessao["erros"].append(f"{boosters[idx]['Tipo de pacote']} ({item_id}): {erro}")
                if int(dados.get("quantidade_ofertas") or 0) == 0:
                    sessao["semOfertas"].append(item_id)
                escrever_inventario(colecao, "boosters", boosters)

            # Substitui eventual resultado anterior do mesmo item na mesma cotização.
            sessao["resultados"] = [r for r in sessao.get("resultados", []) if r.get("id") != item_id or r.get("tipo") != tipo]
            sessao["resultados"].append(resultado)
            processados.add(chave)
            sessao["processados"] = sorted(processados)
            escrever_json_obj(estado_path, sessao)

    kits = atualizar_kits(kits, cartas, boosters)
    escrever_inventario(colecao, "cartas", cartas)
    escrever_inventario(colecao, "boosters", boosters)
    escrever_inventario(colecao, "kits", kits)
    if not (colecao / ARQUIVOS_INVENTARIO["albuns"]).exists():
        escrever_inventario(colecao, "albuns", [normalizar_album(x) for x in ler_inventario(colecao, "albuns")])
    perfil = ler_json_obj(colecao / ARQUIVO_PERFIL)
    perfil.update({"pricingMode": modo, "quotedAt": agora_iso()})
    escrever_json_obj(colecao / ARQUIVO_PERFIL, perfil)

    # O relatório usa os resultados item a item; totais anteriores ficam preservados na sessão.
    json_rel, txt_rel = salvar_relatorio(colecao, sessao, [], [], cartas, boosters)
    sessao["relatorioJson"] = str(json_rel.name)
    sessao["relatorioTxt"] = str(txt_rel.name)
    estado_path.unlink(missing_ok=True)
    return colecao
