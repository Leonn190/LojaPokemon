from __future__ import annotations

import csv
import json
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from configuracao import ARQUIVO_MOVIMENTACOES, ARQUIVOS_INVENTARIO, ARQUIVOS_LEGADOS, PASTA_HISTORICO_NOME, chave_texto


def ler_json_obj(caminho: Path) -> dict[str, Any]:
    if not caminho.is_file():
        return {}
    dados = json.loads(caminho.read_text(encoding="utf-8-sig"))
    return dados if isinstance(dados, dict) else {}


def escrever_json_obj(caminho: Path, dados: dict[str, Any]) -> None:
    _escrever_json_atomico(caminho, dados)


def ler_lista_json(caminho: Path) -> list[dict[str, Any]]:
    if not caminho.is_file():
        return []
    dados = json.loads(caminho.read_text(encoding="utf-8-sig"))
    if isinstance(dados, list):
        return [dict(item) for item in dados if isinstance(item, dict)]
    if isinstance(dados, dict):
        for chave in ("itens", "items", "dados", "data"):
            if isinstance(dados.get(chave), list):
                return [dict(item) for item in dados[chave] if isinstance(item, dict)]
    return []


def ler_csv_legado(caminho: Path) -> list[dict[str, Any]]:
    if not caminho.is_file():
        return []
    with caminho.open("r", encoding="utf-8-sig", newline="") as arquivo:
        return [dict(linha) for linha in csv.DictReader(arquivo)]


def ler_inventario(pasta: Path, tipo: str) -> list[dict[str, Any]]:
    novo = pasta / ARQUIVOS_INVENTARIO[tipo]
    itens = ler_lista_json(novo) if novo.is_file() else ler_csv_legado(pasta / ARQUIVOS_LEGADOS[tipo])
    # CSVs antigos podiam trazer uma linha agregada "Total" no inventário de boosters.
    # No modelo JSON, total é informação derivada e nunca deve virar um item real.
    if tipo == "boosters":
        itens = [
            item for item in itens
            if chave_texto(item.get("Tipo de pacote") or item.get("Nome") or item.get("Coleção")) != "TOTAL"
        ]
    return itens


def escrever_inventario(pasta: Path, tipo: str, itens: list[dict[str, Any]]) -> Path:
    caminho = pasta / ARQUIVOS_INVENTARIO[tipo]
    _escrever_json_atomico(caminho, itens)
    return caminho


def _escrever_json_atomico(caminho: Path, dados: Any) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_name(f".{caminho.name}.{uuid.uuid4().hex}.tmp")
    temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    temporario.replace(caminho)


def migrar_inventarios_legados(pasta: Path) -> list[str]:
    """Converte CSVs existentes para JSON sem apagar os CSVs automaticamente."""
    migrados: list[str] = []
    for tipo, nome_json in ARQUIVOS_INVENTARIO.items():
        destino = pasta / nome_json
        legado = pasta / ARQUIVOS_LEGADOS[tipo]
        if not destino.exists() and legado.is_file():
            escrever_inventario(pasta, tipo, ler_csv_legado(legado))
            migrados.append(tipo)
    return migrados


def arquivar_csvs_legados(pasta: Path) -> list[str]:
    """Move CSVs antigos para uma pasta de legado depois que o JSON já existe."""
    movidos: list[str] = []
    destino_legado = pasta / "legado-csv"
    for tipo, nome_csv in ARQUIVOS_LEGADOS.items():
        csv_path = pasta / nome_csv
        json_path = pasta / ARQUIVOS_INVENTARIO[tipo]
        if csv_path.is_file() and json_path.is_file():
            destino_legado.mkdir(parents=True, exist_ok=True)
            alvo = destino_legado / nome_csv
            if alvo.exists():
                alvo.unlink()
            shutil.move(str(csv_path), str(alvo))
            movidos.append(nome_csv)
    return movidos


def recuperar_transacoes_pendentes(pasta: Path) -> list[str]:
    """Restaura automaticamente uma atualização interrompida durante o commit."""
    recuperadas: list[str] = []
    if not pasta.is_dir():
        return recuperadas
    for backup in sorted(pasta.glob(".backup-transacao-*")):
        if not backup.is_dir():
            continue
        token = backup.name.replace(".backup-transacao-", "")
        # Se o commit já terminou e só a limpeza foi interrompida, mantém os novos arquivos.
        if (backup / "commit.ok").is_file():
            shutil.rmtree(pasta / f".transacao-{token}", ignore_errors=True)
            shutil.rmtree(backup, ignore_errors=True)
            recuperadas.append(token)
            continue
        manifesto_path = backup / "manifesto.json"
        try:
            manifesto = json.loads(manifesto_path.read_text(encoding="utf-8")) if manifesto_path.is_file() else {}
        except json.JSONDecodeError:
            manifesto = {}
        nomes = manifesto.get("nomes") if isinstance(manifesto, dict) else None
        existiam = manifesto.get("existiam") if isinstance(manifesto, dict) else None
        if not isinstance(nomes, list):
            nomes = [x.name for x in backup.iterdir() if x.is_file() and x.name != "manifesto.json"]
        if not isinstance(existiam, dict):
            existiam = {nome: (backup / nome).exists() for nome in nomes}
        for nome in nomes:
            destino = pasta / nome
            original = backup / nome
            if bool(existiam.get(nome)) and original.is_file():
                destino.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(original, destino)
            elif not bool(existiam.get(nome)) and destino.exists():
                destino.unlink()
        # Staging com o mesmo token também pode ter sobrado.
        shutil.rmtree(pasta / f".transacao-{token}", ignore_errors=True)
        shutil.rmtree(backup, ignore_errors=True)
        recuperadas.append(token)
    return recuperadas


@contextmanager
def transacao_arquivos(pasta: Path, nomes: list[str]) -> Iterator[Path]:
    """Staging + backup para atualizações que não podem ficar pela metade.

    O chamador escreve os arquivos completos em `staging`. Só depois do bloco
    todos são promovidos. Se houver erro durante a promoção, os originais são
    restaurados.
    """
    pasta.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    staging = pasta / f".transacao-{token}"
    backup = pasta / f".backup-transacao-{token}"
    staging.mkdir()
    backup.mkdir()
    try:
        yield staging
        existiam: dict[str, bool] = {}
        for nome in nomes:
            origem = pasta / nome
            existiam[nome] = origem.exists()
            if origem.exists():
                alvo_backup = backup / nome
                alvo_backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(origem, alvo_backup)
        (backup / "manifesto.json").write_text(
            json.dumps({"nomes": nomes, "existiam": existiam}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        promovidos: list[str] = []
        try:
            for nome in nomes:
                novo = staging / nome
                if novo.exists():
                    destino = pasta / nome
                    destino.parent.mkdir(parents=True, exist_ok=True)
                    novo.replace(destino)
                    promovidos.append(nome)
            (backup / "commit.ok").write_text("ok", encoding="utf-8")
        except Exception:
            for nome in promovidos:
                original = backup / nome
                destino = pasta / nome
                if original.exists():
                    shutil.copy2(original, destino)
                elif destino.exists():
                    destino.unlink()
            raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(backup, ignore_errors=True)


def _chave_registro_historico(registro: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(registro.get("itemId") or ""),
        str(registro.get("cotacaoId") or ""),
        str(registro.get("data") or ""),
        str(registro.get("erro") or ""),
    )


def _caminho_historico(pasta: Path, tipo: str) -> Path:
    from configuracao import ARQUIVOS_HISTORICO, PASTA_HISTORICO_NOME
    if tipo not in ARQUIVOS_HISTORICO:
        raise ValueError(f"Tipo sem histórico externo: {tipo}")
    return pasta / PASTA_HISTORICO_NOME / ARQUIVOS_HISTORICO[tipo]


def ler_historico(pasta: Path, tipo: str) -> list[dict[str, Any]]:
    caminho = _caminho_historico(pasta, tipo)
    if not caminho.is_file():
        return []
    registros: list[dict[str, Any]] = []
    with caminho.open("r", encoding="utf-8-sig") as arquivo:
        for linha in arquivo:
            linha = linha.strip()
            if not linha:
                continue
            try:
                registro = json.loads(linha)
            except json.JSONDecodeError:
                continue
            if isinstance(registro, dict):
                registros.append(registro)
    return registros


def anexar_historico(pasta: Path, tipo: str, registros: dict[str, Any] | list[dict[str, Any]]) -> int:
    """Acrescenta registros JSONL sem duplicar a mesma tentativa/cotação."""
    lista = [registros] if isinstance(registros, dict) else list(registros)
    lista = [dict(r) for r in lista if isinstance(r, dict)]
    if not lista:
        return 0
    caminho = _caminho_historico(pasta, tipo)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    existentes = {_chave_registro_historico(r) for r in ler_historico(pasta, tipo)}
    novos = [r for r in lista if _chave_registro_historico(r) not in existentes]
    if not novos:
        return 0
    with caminho.open("a", encoding="utf-8", newline="\n") as arquivo:
        for registro in novos:
            arquivo.write(json.dumps(registro, ensure_ascii=False, separators=(",", ":")) + "\n")
        arquivo.flush()
        try:
            import os
            os.fsync(arquivo.fileno())
        except OSError:
            pass
    return len(novos)


def migrar_historicos_embutidos(pasta: Path) -> dict[str, int]:
    """Move arrays antigos `Histórico de preços` para `historico/*.jsonl`.

    O inventário passa a guardar somente `Última cotação`, evitando crescimento
    indefinido dos JSONs usados pelo site.
    """
    migrados: dict[str, int] = {"cartas": 0, "boosters": 0}
    for tipo in ("cartas", "boosters"):
        caminho = pasta / ARQUIVOS_INVENTARIO[tipo]
        if not caminho.is_file():
            continue
        itens = ler_lista_json(caminho)
        mudou = False
        registros: list[dict[str, Any]] = []
        for item in itens:
            historico = item.pop("Histórico de preços", None)
            if not isinstance(historico, list):
                continue
            mudou = True
            sucessos: list[dict[str, Any]] = []
            for antigo in historico:
                if not isinstance(antigo, dict):
                    continue
                registro = dict(antigo)
                registro["itemId"] = str(item.get("Id") or registro.get("itemId") or "")
                registro["sucesso"] = bool(registro.get("sucesso", not bool(registro.get("erro"))))
                registros.append(registro)
                if registro["sucesso"] and registro.get("data"):
                    sucessos.append(registro)
            if sucessos and not isinstance(item.get("Última cotação"), dict):
                ultimo = max(sucessos, key=lambda r: str(r.get("data") or ""))
                item["Última cotação"] = {
                    "cotacaoId": str(ultimo.get("cotacaoId") or ""),
                    "data": str(ultimo.get("data") or ""),
                    "sucesso": True,
                }
        if mudou:
            escrever_inventario(pasta, tipo, itens)
        migrados[tipo] = anexar_historico(pasta, tipo, registros)
    return migrados


def _caminho_movimentacoes(pasta: Path) -> Path:
    return pasta / PASTA_HISTORICO_NOME / ARQUIVO_MOVIMENTACOES


def ler_movimentacoes(pasta: Path) -> list[dict[str, Any]]:
    caminho = _caminho_movimentacoes(pasta)
    if not caminho.is_file():
        return []
    registros: list[dict[str, Any]] = []
    with caminho.open("r", encoding="utf-8-sig") as arquivo:
        for linha in arquivo:
            linha = linha.strip()
            if not linha:
                continue
            try:
                registro = json.loads(linha)
            except json.JSONDecodeError:
                continue
            if isinstance(registro, dict):
                registros.append(registro)
    return registros


def _chave_movimentacao(registro: dict[str, Any]) -> tuple[str, str, str, str, str]:
    event_id = str(registro.get("eventId") or "").strip()
    if event_id:
        return ("event", event_id, "", "", "")
    return (
        "legacy",
        str(registro.get("updateId") or registro.get("sourceId") or ""),
        str(registro.get("itemId") or ""),
        str(registro.get("date") or registro.get("data") or ""),
        str(registro.get("eventType") or registro.get("tipo") or ""),
    )


def escrever_movimentacoes(pasta: Path, registros: list[dict[str, Any]]) -> Path:
    caminho = _caminho_movimentacoes(pasta)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_name(f".{caminho.name}.{uuid.uuid4().hex}.tmp")
    with temporario.open("w", encoding="utf-8", newline="\n") as arquivo:
        for registro in registros:
            if isinstance(registro, dict):
                arquivo.write(json.dumps(registro, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporario.replace(caminho)
    return caminho


def anexar_movimentacoes(pasta: Path, registros: dict[str, Any] | list[dict[str, Any]]) -> int:
    lista = [registros] if isinstance(registros, dict) else list(registros)
    lista = [dict(r) for r in lista if isinstance(r, dict)]
    if not lista:
        return 0
    existentes_lista = ler_movimentacoes(pasta)
    existentes = {_chave_movimentacao(r) for r in existentes_lista}
    novos: list[dict[str, Any]] = []
    for registro in lista:
        chave = _chave_movimentacao(registro)
        if chave in existentes:
            continue
        existentes.add(chave)
        novos.append(registro)
    if not novos:
        return 0
    escrever_movimentacoes(pasta, [*existentes_lista, *novos])
    return len(novos)
