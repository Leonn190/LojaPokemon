from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import parse_qs, urlsplit

from configuracao import ESTADOS_ORDEM, FATORES_ESTADO, chave_texto


_IDIOMAS = {
    "BR": "Português", "PT": "Português", "PTBR": "Português",
    "PORTUGUES": "Português", "PORTUGUESPTBR": "Português",
    "ING": "Inglês", "EN": "Inglês", "ENGLISH": "Inglês", "INGLES": "Inglês",
}
_ESTADOS = {
    "MINT": "M", "M": "M", "NEARMINT": "NM", "NM": "NM",
    "SLIGHTLYPLAYED": "SP", "SP": "SP", "MODERATELYPLAYED": "MP", "MP": "MP",
    "HEAVILYPLAYED": "HP", "HP": "HP", "DAMAGED": "D", "D": "D",
}


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
    if isinstance(valor, Decimal):
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


def _oferta_preco(oferta: dict[str, Any]) -> Decimal | None:
    valor = oferta.get("preco")
    if isinstance(valor, Decimal):
        return valor
    convertido = dinheiro_decimal(valor)
    return convertido


def _preco_minimo(ofertas: list[dict[str, Any]]) -> Decimal | None:
    valores = [_oferta_preco(o) for o in ofertas]
    valores = [v for v in valores if v is not None]
    return min(valores) if valores else None


def _oferta_minima(ofertas: list[dict[str, Any]]) -> dict[str, Any] | None:
    validas = [(p, o) for o in ofertas if (p := _oferta_preco(o)) is not None]
    return min(validas, key=lambda x: x[0])[1] if validas else None


def _oferta_maxima(ofertas: list[dict[str, Any]]) -> dict[str, Any] | None:
    validas = [(p, o) for o in ofertas if (p := _oferta_preco(o)) is not None]
    return max(validas, key=lambda x: x[0])[1] if validas else None


def _oferta_publica(oferta: dict[str, Any] | None, preco: Decimal | None = None) -> dict[str, Any]:
    if not oferta:
        return {}
    valor = preco if preco is not None else _oferta_preco(oferta)
    return {
        "loja": str(oferta.get("loja") or "").strip(),
        "preco": numero(valor),
        "idioma": str(oferta.get("idioma_original") or oferta.get("idioma") or "").strip(),
        "estado": str(oferta.get("estado_original") or oferta.get("estado") or "").strip().upper(),
        "extra": str(oferta.get("extra") or "").strip(),
        "ofertaId": str(oferta.get("oferta_id") or "").strip(),
        "linkLoja": str(oferta.get("link_loja") or "").strip(),
    }


def _estado_oferta(oferta: dict[str, Any]) -> str:
    valor = str(oferta.get("estado_original") or oferta.get("estado") or "").strip().upper()
    return valor if valor in ESTADOS_ORDEM else ""


def _idioma_oferta(oferta: dict[str, Any]) -> str:
    valor = str(oferta.get("idioma_original") or oferta.get("idioma") or "").strip()
    return normalizar_idioma(valor) if valor else ""


def _ajustar_para_estado(preco: Decimal, estado_encontrado: str, estado_desejado: str) -> Decimal | None:
    if estado_encontrado not in FATORES_ESTADO or estado_desejado not in FATORES_ESTADO:
        return None
    fator_origem = Decimal(str(FATORES_ESTADO[estado_encontrado]))
    fator_destino = Decimal(str(FATORES_ESTADO[estado_desejado]))
    fator = Decimal("1") + (fator_destino - fator_origem)
    if fator <= 0:
        return None
    return (preco * fator).quantize(Decimal("0.01"))


def _stats_coleta(dados: dict[str, Any], origem: str) -> dict[str, Any]:
    coleta = dados.get("coleta") if isinstance(dados.get("coleta"), dict) else {}
    bruto = coleta.get(origem) if isinstance(coleta.get(origem), dict) else {}
    return {
        "detectadas": int(bruto.get("detectadas") or 0),
        "lidas": int(bruto.get("lidas") or 0),
        "falhas": int(bruto.get("falhas") or 0),
        "erros": list(bruto.get("erros") or []),
    }


def _motivo_ocr(dados: dict[str, Any], origem: str) -> dict[str, Any] | None:
    stats = _stats_coleta(dados, origem)
    if stats["falhas"] <= 0:
        return None
    nivel = "suspeita" if stats["lidas"] == 0 else "suspeita_leve"
    return {
        "nivel": nivel,
        "codigo": f"{origem}_leitura_incompleta",
        "mensagem": (
            f"Cotização incompleta: {stats['falhas']} de {stats['detectadas']} ofertas "
            f"de {origem} não puderam ter o preço lido"
        ),
        "evidencia": stats,
    }


def _comparacao_buylist_carta(
    marketplace: list[dict[str, Any]],
    buylist: list[dict[str, Any]],
    idioma_desejado: str,
    estado_desejado: str,
) -> dict[str, Any] | None:
    """Compara apenas produtos equivalentes.

    Ordem de confiança:
    1) mesmo idioma + mesmo estado;
    2) mesmo idioma + estados diferentes, convertidos para o estado da carta.

    Idiomas diferentes não são comparados porque o sistema não possui fator monetário
    confiável entre línguas; isso evita falsos positivos.
    """
    pares_exatos: list[tuple[Decimal, dict[str, Any], dict[str, Any], Decimal, Decimal]] = []
    pares_ajustados: list[tuple[Decimal, dict[str, Any], dict[str, Any], Decimal, Decimal]] = []

    for venda in marketplace:
        venda_preco = _oferta_preco(venda)
        venda_idioma = _idioma_oferta(venda)
        venda_estado = _estado_oferta(venda)
        if venda_preco is None or not venda_idioma or not venda_estado:
            continue
        for compra in buylist:
            compra_preco = _oferta_preco(compra)
            compra_idioma = _idioma_oferta(compra)
            compra_estado = _estado_oferta(compra)
            if compra_preco is None or not compra_idioma or not compra_estado:
                continue
            if chave_texto(venda_idioma) != chave_texto(compra_idioma):
                continue

            if venda_estado == compra_estado:
                if compra_preco > venda_preco:
                    pares_exatos.append((compra_preco - venda_preco, venda, compra, venda_preco, compra_preco))
                continue

            venda_ajustada = _ajustar_para_estado(venda_preco, venda_estado, estado_desejado)
            compra_ajustada = _ajustar_para_estado(compra_preco, compra_estado, estado_desejado)
            if venda_ajustada is not None and compra_ajustada is not None and compra_ajustada > venda_ajustada:
                pares_ajustados.append((compra_ajustada - venda_ajustada, venda, compra, venda_ajustada, compra_ajustada))

    pares = pares_exatos or pares_ajustados
    if not pares:
        return None
    diferenca, venda, compra, venda_comp, compra_comp = max(pares, key=lambda x: x[0])
    exata = bool(pares_exatos)
    return {
        "nivel": "suspeita",
        "codigo": "buylist_acima_marketplace",
        "mensagem": (
            "Suspeita: há loja comprando por mais do que outra loja vende o mesmo idioma e estado"
            if exata
            else "Suspeita: após ajustar os estados, uma buylist fica acima de uma oferta de venda equivalente"
        ),
        "evidencia": {
            "comparacao": "mesmo_idioma_mesmo_estado" if exata else "mesmo_idioma_estado_ajustado",
            "estadoReferencia": estado_desejado,
            "idiomaReferencia": idioma_desejado,
            "venda": _oferta_publica(venda, venda_comp),
            "buylist": _oferta_publica(compra, compra_comp),
            "diferenca": numero(diferenca),
        },
    }


def gerar_status_carta(dados: dict[str, Any], idioma: str, estado: str) -> dict[str, Any]:
    marketplace = list(dados.get("marketplace") or [])
    buylist = list(dados.get("buylist") or [])
    motivos: list[dict[str, Any]] = []

    idioma_normalizado = normalizar_idioma(idioma or "BR")
    estado_normalizado = normalizar_estado(estado or "NM")
    chave_idioma = chave_texto(idioma_normalizado)

    mesmas = [
        o for o in marketplace
        if chave_texto(_idioma_oferta(o)) == chave_idioma
        and _estado_oferta(o) == estado_normalizado
    ]
    oferta_mesma = _oferta_minima(mesmas)
    menor_mesma = _oferta_preco(oferta_mesma) if oferta_mesma else None

    # 1) Condição melhor por preço inferior ao estado da carta do usuário.
    if menor_mesma is not None and estado_normalizado in ESTADOS_ORDEM:
        indice = ESTADOS_ORDEM.index(estado_normalizado)
        estados_melhores = set(ESTADOS_ORDEM[:indice])
        melhores = [
            o for o in marketplace
            if chave_texto(_idioma_oferta(o)) == chave_idioma
            and _estado_oferta(o) in estados_melhores
        ]
        oferta_melhor = _oferta_minima(melhores)
        menor_melhor = _oferta_preco(oferta_melhor) if oferta_melhor else None
        if menor_melhor is not None and menor_melhor < menor_mesma:
            motivos.append({
                "nivel": "suspeita",
                "codigo": "estado_melhor_mais_barato",
                "mensagem": "Suspeita de carta mais bem conservada por preço menor",
                "evidencia": {
                    "referencia": _oferta_publica(oferta_mesma),
                    "comparacao": _oferta_publica(oferta_melhor),
                    "diferenca": numero(menor_mesma - menor_melhor),
                },
            })

    # 2) Outro idioma mais barato. Cartas em inglês não recebem esta suspeita.
    if menor_mesma is not None and chave_idioma != chave_texto("Inglês"):
        outras_linguas = [
            o for o in marketplace
            if _idioma_oferta(o)
            and chave_texto(_idioma_oferta(o)) != chave_idioma
            and _estado_oferta(o) == estado_normalizado
        ]
        oferta_outra = _oferta_minima(outras_linguas)
        menor_outra = _oferta_preco(oferta_outra) if oferta_outra else None
        if menor_outra is not None and menor_outra < menor_mesma:
            motivos.append({
                "nivel": "suspeita",
                "codigo": "outro_idioma_mais_barato",
                "mensagem": "Suspeita de carta igual em outra língua por preço menor",
                "evidencia": {
                    "referencia": _oferta_publica(oferta_mesma),
                    "comparacao": _oferta_publica(oferta_outra),
                    "diferenca": numero(menor_mesma - menor_outra),
                },
            })

    # 3) Buylist somente contra produto equivalente. O resumidor já remove
    # variantes incompatíveis (ex.: Normal x Foil) quando detecta inversão anormal.
    marketplace_equivalente = list(dados.get("ofertas_selecionadas") or marketplace)
    buylist_equivalente = list(dados.get("buylist_selecionada") or buylist)
    motivo_buylist = _comparacao_buylist_carta(marketplace_equivalente, buylist_equivalente, idioma_normalizado, estado_normalizado)
    if motivo_buylist:
        motivos.append(motivo_buylist)

    # 4) Falhas de OCR são explicitadas e impedem a falsa conclusão de que só há uma loja.
    motivo_ocr_market = _motivo_ocr(dados, "marketplace")
    if motivo_ocr_market:
        motivos.append(motivo_ocr_market)
    motivo_ocr_buy = _motivo_ocr(dados, "buylist")
    if motivo_ocr_buy:
        motivos.append(motivo_ocr_buy)

    quantidade = int(dados.get("quantidade_ofertas") or 0)
    stats_market = _stats_coleta(dados, "marketplace")
    if quantidade == 1 and stats_market["falhas"] == 0:
        motivos.append({
            "nivel": "suspeita_leve",
            "codigo": "uma_oferta",
            "mensagem": "Suspeita leve: apenas uma loja vende a carta compatível nessa cotação",
            "evidencia": {"ofertasCompativeis": quantidade, **stats_market},
        })

    if not marketplace:
        if stats_market["detectadas"] > 0:
            motivos.append({
                "nivel": "suspeita",
                "codigo": "sem_ofertas_lidas",
                "mensagem": "Suspeita: havia ofertas na página, mas nenhuma pôde ter o preço lido",
                "evidencia": stats_market,
            })
        else:
            motivos.append({
                "nivel": "suspeita",
                "codigo": "sem_ofertas",
                "mensagem": "Suspeita: nenhuma oferta de venda foi encontrada",
                "evidencia": stats_market,
            })

    nivel = "OK"
    if any(m["nivel"] == "suspeita" for m in motivos):
        nivel = "Suspeita"
    elif motivos:
        nivel = "Suspeita leve"
    return {
        "nível": nivel,
        "motivos": motivos,
        "coleta": {
            "marketplace": stats_market,
            "buylist": _stats_coleta(dados, "buylist"),
        },
    }


def gerar_status_booster(dados: dict[str, Any]) -> dict[str, Any]:
    motivos: list[dict[str, Any]] = []
    marketplace = list(dados.get("marketplace") or [])
    buylist = list(dados.get("buylist") or [])
    stats_market = _stats_coleta(dados, "marketplace")
    stats_buy = _stats_coleta(dados, "buylist")

    motivo_ocr_market = _motivo_ocr(dados, "marketplace")
    if motivo_ocr_market:
        motivos.append(motivo_ocr_market)
    motivo_ocr_buy = _motivo_ocr(dados, "buylist")
    if motivo_ocr_buy:
        motivos.append(motivo_ocr_buy)

    qtd = int(dados.get("quantidade_ofertas") or 0)
    if not marketplace:
        if stats_market["detectadas"] > 0:
            motivos.append({"nivel": "suspeita", "codigo": "sem_ofertas_lidas", "mensagem": "Suspeita: ofertas de booster foram detectadas, mas nenhum preço pôde ser lido", "evidencia": stats_market})
        else:
            motivos.append({"nivel": "suspeita", "codigo": "sem_ofertas", "mensagem": "Suspeita: nenhuma oferta de venda foi encontrada", "evidencia": stats_market})
    elif qtd == 1 and stats_market["falhas"] == 0:
        motivos.append({"nivel": "suspeita_leve", "codigo": "uma_oferta", "mensagem": "Suspeita leve: apenas uma loja vende esse booster", "evidencia": {"ofertasCompativeis": qtd, **stats_market}})

    venda = _oferta_minima(marketplace)
    compra = _oferta_maxima(buylist)
    venda_min = _oferta_preco(venda) if venda else None
    compra_max = _oferta_preco(compra) if compra else None
    if venda_min is not None and compra_max is not None and compra_max > venda_min:
        motivos.append({
            "nivel": "suspeita",
            "codigo": "buylist_acima_marketplace",
            "mensagem": "Suspeita: buylist acima de uma oferta de venda",
            "evidencia": {
                "venda": _oferta_publica(venda),
                "buylist": _oferta_publica(compra),
                "diferenca": numero(compra_max - venda_min),
            },
        })
    nivel = "Suspeita" if any(m["nivel"] == "suspeita" for m in motivos) else ("Suspeita leve" if motivos else "OK")
    return {"nível": nivel, "motivos": motivos, "coleta": {"marketplace": stats_market, "buylist": stats_buy}}


def preco_objeto(dados: dict[str, Any], estimado: bool) -> dict[str, Any]:
    sufixo = "" if estimado else "_coletado"
    return {
        "Minimo Certeiro": numero(dados.get(f"minimo_certeiro{sufixo}")),
        "Minimo": numero(dados.get(f"minimo{sufixo}")),
        "Menor Liga": numero(dados.get(f"menor{sufixo}")),
        "Media Liga": numero(dados.get(f"medio{sufixo}")),
        "Venda Rapida": numero(dados.get(f"venda_rapida{sufixo}")),
        "Idioma encontrado": list(dados.get("idiomas_encontrados") or []),
        "Estado encontrado": list(dados.get("estados_encontrados") or []),
        "é estimativa": bool(dados.get("houve_estimativa")) if estimado else False,
    }


def registrar_historico(
    item: dict[str, Any],
    cotacao_id: str,
    data: str,
    status: dict[str, Any],
    erro: str = "",
) -> dict[str, Any]:
    """Gera um registro externo de histórico e mantém só a última cotação no inventário."""
    sucesso = not bool(erro)
    item.pop("Histórico de preços", None)
    registro = {
        "itemId": str(item.get("Id") or ""),
        "cotacaoId": cotacao_id,
        "data": data,
        "sucesso": sucesso,
        "Minimo Certeiro": numero(item.get("Minimo Certeiro") or item.get("Mínimo Certeiro")),
        "Minimo": numero(item.get("Minimo") or item.get("Preço mínimo")),
        "Menor Liga": numero(item.get("Menor Liga") or item.get("Preço Liga mais barato")),
        "Media Liga": numero(item.get("Media Liga") or item.get("Preço Médio Liga") or item.get("Preço médio Liga")),
        "Venda Rapida": numero(item.get("Venda Rapida") or item.get("Venda rápida")),
        "Preço coletado": item.get("Preço coletado", {}),
        "Preço estimado": item.get("Preço estimado", {}),
        "Status": status,
        "erro": erro,
    }
    if sucesso:
        item["Última cotação"] = {
            "cotacaoId": cotacao_id,
            "data": data,
            "sucesso": True,
        }
    return registro
