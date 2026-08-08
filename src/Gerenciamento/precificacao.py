from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import parse_qs, urlsplit

from configuracao import ESTADOS_ORDEM, chave_texto



_IDIOMAS = {
    "BR": "Português", "PT": "Português", "PTBR": "Português",
    "PORTUGUES": "Português", "PORTUGUESPTBR": "Português",
    "ING": "Inglês", "EN": "Inglês", "ENGLISH": "Inglês", "INGLES": "Inglês",
}
_ESTADOS = {"MINT": "M", "M": "M", "NEARMINT": "NM", "NM": "NM", "SLIGHTLYPLAYED": "SP", "SP": "SP", "MODERATELYPLAYED": "MP", "MP": "MP", "HEAVILYPLAYED": "HP", "HP": "HP", "DAMAGED": "D", "D": "D"}

def normalizar_idioma(idioma: str) -> str:
    return _IDIOMAS.get(chave_texto(idioma), idioma.strip())

def normalizar_estado(estado: str) -> str:
    chave = chave_texto(estado)
    if chave not in _ESTADOS:
        raise ValueError("Estado inválido. Use M, NM, SP, MP, HP ou D.")
    return _ESTADOS[chave]

def agora_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def numero(valor: Any) -> float | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip().replace("R$", "").replace(" ", "")
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return float(Decimal(texto))
    except (InvalidOperation, ValueError):
        return None


def dinheiro_decimal(valor: Any) -> Decimal | None:
    n = numero(valor)
    return Decimal(str(n)).quantize(Decimal("0.01")) if n is not None else None


def _slug(valor: str) -> str:
    valor = re.sub(r"[^A-Za-z0-9]+", "-", valor.strip()).strip("-")
    return valor.upper() or "SEM"


def sigla_idioma(idioma: str) -> str:
    chave = chave_texto(normalizar_idioma(idioma or ""))
    if chave == chave_texto("Português"):
        return "BR"
    if chave == chave_texto("Inglês"):
        return "ING"
    return _slug(idioma)[:5]


def identificador_carta(carta: dict[str, Any]) -> str:
    link = str(carta.get("Link Liga") or carta.get("Liga") or carta.get("Link") or "")
    qs = parse_qs(urlsplit(link).query)
    edicao = (qs.get("ed") or [""])[0] or str(carta.get("Coleção") or "COLECAO")
    numero_carta = str(carta.get("Número") or carta.get("Numeração") or (qs.get("num") or [""])[0] or "SEM-NUMERO")
    idioma = sigla_idioma(str(carta.get("Idioma") or "BR"))
    try:
        estado = normalizar_estado(str(carta.get("Estado") or "NM"))
    except ValueError:
        estado = _slug(str(carta.get("Estado") or "NM"))
    return f"{_slug(edicao)}-{_slug(numero_carta)}-{idioma}-{estado}"


def identificador_booster(booster: dict[str, Any]) -> str:
    link = str(booster.get("Link Liga") or booster.get("Liga") or booster.get("Link") or "")
    qs = parse_qs(urlsplit(link).query)
    edicao = (qs.get("ed") or [""])[0]
    nome = str(booster.get("Tipo de pacote") or booster.get("Coleção") or booster.get("Nome") or "BOOSTER")
    return f"BOOSTER-{_slug(edicao or nome)}"


def _preco_minimo(ofertas: list[dict[str, Any]]) -> Decimal | None:
    valores = [o.get("preco") for o in ofertas if isinstance(o.get("preco"), Decimal)]
    return min(valores) if valores else None


def gerar_status_carta(dados: dict[str, Any], idioma: str, estado: str) -> dict[str, Any]:
    marketplace = list(dados.get("marketplace") or [])
    buylist = list(dados.get("buylist") or [])
    motivos: list[dict[str, str]] = []

    idioma_normalizado = normalizar_idioma(idioma or "BR")
    estado_normalizado = normalizar_estado(estado or "NM")
    chave_idioma = chave_texto(idioma_normalizado)

    mesmas = [
        o for o in marketplace
        if chave_texto(normalizar_idioma(str(o.get("idioma") or ""))) == chave_idioma
        and str(o.get("estado") or "").upper() == estado_normalizado
    ]
    menor_mesma = _preco_minimo(mesmas)

    # 1) Condição melhor por preço inferior ao estado da carta do usuário.
    if menor_mesma is not None and estado_normalizado in ESTADOS_ORDEM:
        indice = ESTADOS_ORDEM.index(estado_normalizado)
        estados_melhores = set(ESTADOS_ORDEM[:indice])
        melhores = [
            o for o in marketplace
            if chave_texto(normalizar_idioma(str(o.get("idioma") or ""))) == chave_idioma
            and str(o.get("estado") or "").upper() in estados_melhores
        ]
        menor_melhor = _preco_minimo(melhores)
        if menor_melhor is not None and menor_melhor < menor_mesma:
            motivos.append({
                "nivel": "suspeita",
                "codigo": "estado_melhor_mais_barato",
                "mensagem": "Suspeita de carta mais bem conservada por preço menor",
            })

    # 2) Outro idioma mais barato. Cartas em inglês não recebem esta suspeita.
    if menor_mesma is not None and chave_idioma != chave_texto("Inglês"):
        outras_linguas = [
            o for o in marketplace
            if o.get("idioma")
            and chave_texto(normalizar_idioma(str(o.get("idioma")))) != chave_idioma
            and str(o.get("estado") or "").upper() == estado_normalizado
        ]
        menor_outra = _preco_minimo(outras_linguas)
        if menor_outra is not None and menor_outra < menor_mesma:
            motivos.append({
                "nivel": "suspeita",
                "codigo": "outro_idioma_mais_barato",
                "mensagem": "Suspeita de carta igual em outra língua por preço menor",
            })

    # 3) Alguma loja compra acima do preço pelo qual outra loja vende.
    venda_min = min((o.get("preco") for o in marketplace if isinstance(o.get("preco"), Decimal)), default=None)
    compra_max = max((o.get("preco") for o in buylist if isinstance(o.get("preco"), Decimal)), default=None)
    if venda_min is not None and compra_max is not None and compra_max > venda_min:
        motivos.append({
            "nivel": "suspeita",
            "codigo": "buylist_acima_marketplace",
            "mensagem": "Suspeita: há loja comprando por mais do que outra loja está vendendo",
        })

    # 4) Apenas uma oferta compatível com a carta desejada/selecionada.
    quantidade = int(dados.get("quantidade_ofertas") or 0)
    if quantidade == 1:
        motivos.append({
            "nivel": "suspeita_leve",
            "codigo": "uma_oferta",
            "mensagem": "Suspeita leve: apenas uma loja vende a carta nessa cotação",
        })

    if not marketplace:
        motivos.append({
            "nivel": "suspeita",
            "codigo": "sem_ofertas",
            "mensagem": "Suspeita: nenhuma oferta de venda foi coletada",
        })

    nivel = "OK"
    if any(m["nivel"] == "suspeita" for m in motivos):
        nivel = "Suspeita"
    elif motivos:
        nivel = "Suspeita leve"
    return {"nível": nivel, "motivos": motivos}


def gerar_status_booster(dados: dict[str, Any]) -> dict[str, Any]:
    motivos: list[dict[str, str]] = []
    qtd = int(dados.get("quantidade_ofertas") or 0)
    if qtd == 0:
        motivos.append({"nivel": "suspeita", "codigo": "sem_ofertas", "mensagem": "Suspeita: nenhuma oferta de venda foi coletada"})
    elif qtd == 1:
        motivos.append({"nivel": "suspeita_leve", "codigo": "uma_oferta", "mensagem": "Suspeita leve: apenas uma loja vende esse booster"})
    marketplace = list(dados.get("marketplace") or [])
    buylist = list(dados.get("buylist") or [])
    venda_min = min((o.get("preco") for o in marketplace if isinstance(o.get("preco"), Decimal)), default=None)
    compra_max = max((o.get("preco") for o in buylist if isinstance(o.get("preco"), Decimal)), default=None)
    if venda_min is not None and compra_max is not None and compra_max > venda_min:
        motivos.append({"nivel": "suspeita", "codigo": "buylist_acima_marketplace", "mensagem": "Suspeita: buylist acima de uma oferta de venda"})
    nivel = "Suspeita" if any(m["nivel"] == "suspeita" for m in motivos) else ("Suspeita leve" if motivos else "OK")
    return {"nível": nivel, "motivos": motivos}


def preco_objeto(dados: dict[str, Any], estimado: bool) -> dict[str, Any]:
    sufixo = "" if estimado else "_coletado"
    return {
        "Menor Liga": numero(dados.get(f"menor{sufixo}")),
        "Preço Médio Liga": numero(dados.get(f"medio{sufixo}")),
        "Minimo": numero(dados.get(f"minimo{sufixo}")),
        "Idioma encontrado": list(dados.get("idiomas_encontrados") or []),
        "Estado encontrado": list(dados.get("estados_encontrados") or []),
        "é estimativa": bool(dados.get("houve_estimativa")) if estimado else False,
    }


def registrar_historico(item: dict[str, Any], cotacao_id: str, data: str, status: dict[str, Any], erro: str = "") -> None:
    historico = item.get("Histórico de preços")
    if not isinstance(historico, list):
        historico = []
        item["Histórico de preços"] = historico
    registro = {
        "cotacaoId": cotacao_id,
        "data": data,
        "Preço": numero(item.get("Preço")),
        "Preço Médio Liga": numero(item.get("Preço Médio Liga") or item.get("Preço médio Liga")),
        "Menor Liga": numero(item.get("Menor Liga") or item.get("Preço Liga mais barato")),
        "Minimo": numero(item.get("Minimo") or item.get("Preço mínimo")),
        "Venda Rapida": numero(item.get("Venda Rapida") or item.get("Venda rápida")),
        "Preço coletado": item.get("Preço coletado", {}),
        "Preço estimado": item.get("Preço estimado", {}),
        "Status": status,
        "erro": erro,
    }
    for i, antigo in enumerate(historico):
        if isinstance(antigo, dict) and antigo.get("cotacaoId") == cotacao_id:
            historico[i] = registro
            break
    else:
        historico.append(registro)
