from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from configuracao import PASTA_RELATORIOS_NOME
from precificacao import numero


def _variacao(antigo: Any, novo: Any) -> dict[str, Any]:
    a = numero(antigo)
    n = numero(novo)
    if a is None or n is None:
        return {"antigo": a, "novo": n, "diferença": None, "percentual": None}
    dif = round(n - a, 2)
    pct = round((dif / a) * 100, 2) if a else None
    return {"antigo": a, "novo": n, "diferença": dif, "percentual": pct}


def registrar_variacoes(nome: str, item_id: str, tipo: str, anterior: dict[str, Any], atual: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item_id,
        "tipo": tipo,
        "nome": nome,
        "quantidade": int(atual.get("Quantidade") or 1),
        "Minimo Certeiro": _variacao(
            anterior.get("Minimo Certeiro") or anterior.get("Mínimo Certeiro"),
            atual.get("Minimo Certeiro") or atual.get("Mínimo Certeiro"),
        ),
        "Minimo (buylist)": _variacao(
            anterior.get("Minimo") or anterior.get("Preço mínimo"),
            atual.get("Minimo") or atual.get("Preço mínimo"),
        ),
        "Menor Liga": _variacao(
            anterior.get("Menor Liga") or anterior.get("Preço Liga mais barato"),
            atual.get("Menor Liga") or atual.get("Preço Liga mais barato"),
        ),
        "Segundo Menor Liga": _variacao(anterior.get("Segundo Menor Liga"), atual.get("Segundo Menor Liga")),
        "Terceiro Menor Liga": _variacao(anterior.get("Terceiro Menor Liga"), atual.get("Terceiro Menor Liga")),
        "Media Liga": _variacao(
            anterior.get("Media Liga") or anterior.get("Preço Médio Liga") or anterior.get("Preço médio Liga"),
            atual.get("Media Liga") or atual.get("Preço Médio Liga") or atual.get("Preço médio Liga"),
        ),
        "Mediana Liga": _variacao(anterior.get("Mediana Liga"), atual.get("Mediana Liga")),
        "Venda Rapida": _variacao(
            anterior.get("Venda Rapida") or anterior.get("Venda rápida"),
            atual.get("Venda Rapida") or atual.get("Venda rápida"),
        ),
        "Status": atual.get("Status", {}),
        "Preço coletado": atual.get("Preço coletado", {}),
        "Preço estimado": atual.get("Preço estimado", {}),
    }


def _somar_total(itens: list[dict[str, Any]], campo: str, alternativo: str | None = None) -> float:
    total = 0.0
    for item in itens:
        valor = numero(item.get(campo))
        if valor is None and alternativo:
            valor = numero(item.get(alternativo))
        if valor is not None:
            total += valor * int(item.get("Quantidade") or 1)
    return round(total, 2)


def _fmt(v: Any) -> str:
    n = numero(v)
    return "—" if n is None else f"R$ {n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_var(v: dict[str, Any]) -> str:
    if v.get("diferença") is None:
        return f"{_fmt(v.get('antigo'))} → {_fmt(v.get('novo'))}"
    pct = v.get("percentual")
    pct_txt = "" if pct is None else f" ({pct:+.2f}%)".replace(".", ",")
    return f"{_fmt(v.get('antigo'))} → {_fmt(v.get('novo'))} | {v['diferença']:+.2f}{pct_txt}".replace(".", ",")


def salvar_relatorio(
    colecao: Path,
    sessao: dict[str, Any],
    cartas_antes: list[dict[str, Any]],
    boosters_antes: list[dict[str, Any]],
    cartas_depois: list[dict[str, Any]],
    boosters_depois: list[dict[str, Any]],
) -> tuple[Path, Path]:
    pasta = colecao / PASTA_RELATORIOS_NOME
    pasta.mkdir(parents=True, exist_ok=True)
    data = str(sessao.get("dataCotacao") or datetime.now().astimezone().isoformat(timespec="seconds"))
    nome_data = data.replace(":", "-").replace("+", "_")

    resultados = list(sessao.get("resultados") or [])
    suspeitas = sum(1 for r in resultados if ((r.get("Status") or {}).get("nível") == "Suspeita"))
    leves = sum(1 for r in resultados if ((r.get("Status") or {}).get("nível") == "Suspeita leve"))
    erros = list(sessao.get("erros") or [])
    sem_ofertas = list(sessao.get("semOfertas") or [])

    totais_antes = sessao.get("totaisAntes") if isinstance(sessao.get("totaisAntes"), dict) else {}
    preco_antigo = float(totais_antes.get("preço", 0.0)) if totais_antes else (_somar_total(cartas_antes, "Preço") + _somar_total(boosters_antes, "Preço"))
    preco_novo = _somar_total(cartas_depois, "Preço") + _somar_total(boosters_depois, "Preço")
    minimo_certeiro_total = _somar_total(cartas_depois, "Minimo Certeiro", "Mínimo Certeiro") + _somar_total(boosters_depois, "Minimo Certeiro", "Mínimo Certeiro")
    buylist_total = _somar_total(cartas_depois, "Minimo", "Preço mínimo") + _somar_total(boosters_depois, "Minimo", "Preço mínimo")
    menor_total = _somar_total(cartas_depois, "Menor Liga", "Preço Liga mais barato") + _somar_total(boosters_depois, "Menor Liga", "Preço Liga mais barato")
    media_total = _somar_total(cartas_depois, "Media Liga", "Preço Médio Liga") + _somar_total(boosters_depois, "Media Liga", "Preço médio Liga")
    mediana_total = _somar_total(cartas_depois, "Mediana Liga") + _somar_total(boosters_depois, "Mediana Liga")
    venda_rapida_total = _somar_total(cartas_depois, "Venda Rapida", "Venda rápida") + _somar_total(boosters_depois, "Venda Rapida", "Venda rápida")

    diferenca = round(preco_novo - preco_antigo, 2)
    percentual = round((diferenca / preco_antigo) * 100, 2) if preco_antigo else None
    selecionados_lista = list(sessao.get("selecionados") or [])
    processados_lista = list(sessao.get("processados") or [])
    resumo = {
        "cotacaoId": sessao.get("cotacaoId"),
        "data": data,
        "escopo": sessao.get("escopo"),
        "selecionados": len(selecionados_lista),
        "cartasSelecionadas": sum(1 for x in selecionados_lista if x.get("tipo") == "carta"),
        "boostersSelecionados": sum(1 for x in selecionados_lista if x.get("tipo") == "booster"),
        "atualizados": len(processados_lista),
        "cartasAtualizadas": sum(1 for x in processados_lista if str(x).startswith("carta:")),
        "boostersAtualizados": sum(1 for x in processados_lista if str(x).startswith("booster:")),
        "semOfertas": len(sem_ofertas),
        "erros": len(erros),
        "suspeitas": suspeitas,
        "suspeitasLeves": leves,
        "preçoTotalAntigo": round(preco_antigo, 2),
        "preçoTotalNovo": round(preco_novo, 2),
        "variaçãoAbsoluta": diferenca,
        "variaçãoPercentual": percentual,
        "minimoCerteiroTotal": round(minimo_certeiro_total, 2),
        "buylistTotal": round(buylist_total, 2),
        "menorLigaTotal": round(menor_total, 2),
        "mediaLigaTotal": round(media_total, 2),
        "medianaLigaTotal": round(mediana_total, 2),
        "vendaRapidaTotal": round(venda_rapida_total, 2),
    }

    ordenados_alta = sorted(
        resultados,
        key=lambda r: ((r.get("Media Liga") or {}).get("diferença") if (r.get("Media Liga") or {}).get("diferença") is not None else float("-inf")),
        reverse=True,
    )
    ordenados_baixa = list(reversed(ordenados_alta))

    relatorio = {
        "resumo": resumo,
        "itens": resultados,
        "maioresAltas": ordenados_alta[:20],
        "maioresQuedas": ordenados_baixa[:20],
        "semOfertas": sem_ofertas,
        "erros": erros,
    }
    json_path = pasta / f"cotizacao-{nome_data}.json"
    json_path.write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")

    linhas = [
        "COTIZAÇÃO CONCLUÍDA",
        "=" * 78,
        f"Data: {data}",
        f"Escopo: {sessao.get('escopo')}",
        f"Cartas: {resumo['cartasSelecionadas']} | Boosters: {resumo['boostersSelecionados']}",
        f"Atualizadas: {resumo['cartasAtualizadas']} cartas + {resumo['boostersAtualizados']} boosters",
        f"Sem ofertas: {resumo['semOfertas']} | Erros: {resumo['erros']}",
        f"Suspeitas: {suspeitas} | Suspeitas leves: {leves}",
        "",
        f"Preço total antigo: {_fmt(preco_antigo)}",
        f"Preço total novo: {_fmt(preco_novo)}",
        f"Variação: {_fmt(diferenca)}" + ("" if percentual is None else f" ({percentual:+.2f}%)".replace(".", ",")),
        f"Mínimo certeiro total: {_fmt(minimo_certeiro_total)}",
        f"Buylist total: {_fmt(buylist_total)}",
        f"Total pelo menor preço da Liga: {_fmt(menor_total)}",
        f"Total pela média da Liga: {_fmt(media_total)}",
        f"Total pela mediana da Liga: {_fmt(mediana_total)}",
        f"Venda rápida total: {_fmt(venda_rapida_total)}",
        "",
        "VARIAÇÃO POR ITEM",
        "=" * 78,
    ]
    for r in resultados:
        linhas.extend([
            f"{r.get('tipo','').upper()} | {r.get('nome')} | {r.get('id')}",
            f"  Minimo Certeiro: {_fmt_var(r['Minimo Certeiro'])}",
            f"  Minimo / buylist: {_fmt_var(r['Minimo (buylist)'])}",
            f"  Menor Liga: {_fmt_var(r['Menor Liga'])}",
            f"  Segundo Menor Liga: {_fmt_var(r['Segundo Menor Liga'])}",
            f"  Terceiro Menor Liga: {_fmt_var(r['Terceiro Menor Liga'])}",
            f"  Media Liga: {_fmt_var(r['Media Liga'])}",
            f"  Mediana Liga: {_fmt_var(r['Mediana Liga'])}",
            f"  Venda Rapida: {_fmt_var(r['Venda Rapida'])}",
            f"  Status: {(r.get('Status') or {}).get('nível', 'OK')}",
        ])
        for motivo in (r.get("Status") or {}).get("motivos", []):
            linhas.append(f"    - {motivo.get('mensagem')}")
        linhas.append("")
    if erros:
        linhas.extend(["ERROS", "=" * 78])
        linhas.extend(f"- {e}" for e in erros)
    txt_path = pasta / f"cotizacao-{nome_data}.txt"
    txt_path.write_text("\n".join(linhas), encoding="utf-8")
    return json_path, txt_path
