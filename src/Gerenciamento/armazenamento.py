from __future__ import annotations

import csv
import json
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from configuracao import ARQUIVOS_INVENTARIO, ARQUIVOS_LEGADOS


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
    if novo.is_file():
        return ler_lista_json(novo)
    return ler_csv_legado(pasta / ARQUIVOS_LEGADOS[tipo])


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
                shutil.copy2(origem, backup / nome)
        (backup / "manifesto.json").write_text(
            json.dumps({"nomes": nomes, "existiam": existiam}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        promovidos: list[str] = []
        try:
            for nome in nomes:
                novo = staging / nome
                if novo.exists():
                    novo.replace(pasta / nome)
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
