from __future__ import annotations

import copy
import hashlib
import json
import re
import tempfile
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from armazenamento import (
    anexar_historico,
    anexar_movimentacoes,
    arquivar_csvs_legados,
    escrever_inventario,
    escrever_json_obj,
    ler_historico,
    ler_inventario,
    ler_movimentacoes,
    ler_json_obj,
    migrar_historicos_embutidos,
    migrar_inventarios_legados,
    escrever_movimentacoes,
    recuperar_transacoes_pendentes,
    transacao_arquivos,
)
from configuracao import (
    ARQUIVO_ATUALIZACAO,
    ARQUIVO_MOVIMENTACOES,
    ARQUIVO_PERFIL,
    ARQUIVOS_INVENTARIO,
    SALVAR_PARCIAL,
    PASTA_HISTORICO_NOME,
    JITTER_WORKERS,
    chave_texto,
    pasta_colecoes,
    pasta_nao_formatadas,
)
from liga import SessaoLiga, VERSAO_LEITOR_PRECO, baixar_imagem, normalizar_estado, normalizar_idioma
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
from relatorios import registrar_variacoes, salvar_relatorio, salvar_relatorio_execucao_liga

MODO_MENOR = "menor"
MODO_MEDIA = "media"
ARQUIVO_COTIZACAO_PARCIAL = "cotizacao-em-andamento.json"
ARQUIVO_FORMATACAO_PARCIAL = "formatacao-em-andamento.json"


MODOS_VELOCIDADE = {
    1: "Conservador",
    2: "Normal",
    3: "Rápido",
    4: "Turbo",
    5: "Super Turbo",
}


def nome_modo_velocidade(workers: int) -> str:
    return MODOS_VELOCIDADE.get(max(1, min(5, int(workers))), f"Personalizado ({workers})")


def _fmt_tempo(segundos: float) -> str:
    segundos = max(0, int(round(segundos)))
    h, resto = divmod(segundos, 3600)
    m, s = divmod(resto, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def _fmt_preco_console(valor: Any) -> str:
    n = numero(valor)
    if n is None:
        return "—"
    return (f"R$ {n:,.2f}").replace(",", "X").replace(".", ",").replace("X", ".")


class PoolLiga:
    """Pool de threads em que cada thread mantém seu próprio Chrome/Selenium/OCR."""

    def __init__(self, workers: int) -> None:
        self.workers = max(1, min(5, int(workers)))
        self._executor: ThreadPoolExecutor | None = None
        self._local = threading.local()
        self._lock = threading.Lock()
        self._proximo_worker = 1
        self._sessoes: list[SessaoLiga] = []

    def __enter__(self) -> "PoolLiga":
        self._executor = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="LigaWorker")
        return self

    def _sessao_da_thread(self) -> tuple[SessaoLiga, int]:
        sessao = getattr(self._local, "sessao", None)
        worker_id = getattr(self._local, "worker_id", None)
        if sessao is not None and worker_id is not None:
            return sessao, worker_id
        with self._lock:
            worker_id = self._proximo_worker
            self._proximo_worker += 1
        self._local.worker_id = worker_id
        sessao = SessaoLiga(worker_id=worker_id, atraso_inicial=(worker_id - 1) * JITTER_WORKERS)
        sessao.__enter__()
        self._local.sessao = sessao
        with self._lock:
            self._sessoes.append(sessao)
        return sessao, worker_id

    def _rodar(
        self,
        indice: int,
        trabalho: Any,
        consulta: Callable[[Any, SessaoLiga], tuple[dict[str, Any], str]],
    ) -> dict[str, Any]:
        inicio = time.monotonic()
        worker_id = int(getattr(self._local, "worker_id", 0) or 0)
        try:
            sessao, worker_id = self._sessao_da_thread()
            dados, erro = consulta(trabalho, sessao)
        except Exception as exc:
            dados, erro = {}, str(exc)
        return {
            "indice": indice,
            "trabalho": trabalho,
            "dados": dados,
            "erro": erro,
            "worker": worker_id or int(getattr(self._local, "worker_id", 0) or 0),
            "duracao": time.monotonic() - inicio,
        }

    def executar(
        self,
        trabalhos: list[Any],
        consulta: Callable[[Any, SessaoLiga], tuple[dict[str, Any], str]],
    ) -> Iterator[dict[str, Any]]:
        if not trabalhos:
            return
        if self._executor is None:
            raise RuntimeError("PoolLiga não foi aberto.")
        futuros = {
            self._executor.submit(self._rodar, indice, trabalho, consulta): indice
            for indice, trabalho in enumerate(trabalhos, 1)
        }
        for futuro in as_completed(futuros):
            try:
                yield futuro.result()
            except Exception as exc:
                indice = futuros[futuro]
                yield {"indice": indice, "trabalho": trabalhos[indice - 1], "dados": {}, "erro": str(exc), "worker": 0, "duracao": 0.0}

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=False)
            self._executor = None
        for sessao in self._sessoes:
            try:
                sessao.fechar()
            except Exception:
                pass
        self._sessoes.clear()


class MonitorOperacao:
    """Barra de progresso, ETA, telemetria e resumo por item."""

    def __init__(self, total: int, operacao: str, workers: int) -> None:
        self.total = max(0, int(total))
        self.operacao = operacao
        self.workers = max(1, min(5, int(workers)))
        self.modo = nome_modo_velocidade(self.workers)
        self.inicio_mono = time.monotonic()
        self.iniciado_em = agora_iso()
        self.concluidos = 0
        self.sucessos = 0
        self.erros = 0
        self.repeticoes = 0
        self.itens: list[dict[str, Any]] = []

    def falha_temporaria(self, nome: str, tipo: str, erro: str, worker: int, tentativa: int) -> None:
        self.repeticoes += 1
        print(f"⚠ [{tipo}] {nome} | W{worker or '?'} | tentativa {tentativa}: {erro} — será repetido")

    def registrar(
        self,
        nome: str,
        tipo: str,
        dados: dict[str, Any],
        erro: str,
        worker: int,
        duracao: float,
        variacao: dict[str, Any] | None = None,
        status: dict[str, Any] | None = None,
    ) -> None:
        self.concluidos += 1
        if erro:
            self.erros += 1
        else:
            self.sucessos += 1
        preco = {
            "menor": numero(dados.get("menor")),
            "segundoMenor": numero(dados.get("segundo_menor")),
            "terceiroMenor": numero(dados.get("terceiro_menor")),
            "media": numero(dados.get("medio")),
            "mediana": numero(dados.get("mediana")),
            "minimo": numero(dados.get("minimo")),
            "buylist": numero(dados.get("venda_rapida")),
        }
        mercado = {
            "vendedoresGeral": int(dados.get("vendedores_geral") or 0),
            "vendedoresEspecificos": int(dados.get("vendedores_especificos") or 0),
            "compradoresGeral": int(dados.get("compradores_geral") or 0),
            "compradoresEspecificos": int(dados.get("compradores_especificos") or 0),
            "ofertasLidas": int(dados.get("quantidade_ofertas") or 0),
            "buylistLida": int(dados.get("quantidade_buylist") or 0),
        }
        variacao_menor = (variacao or {}).get("Menor Liga") if isinstance(variacao, dict) else None
        item = {
            "nome": nome,
            "tipo": tipo,
            "status": "ERRO" if erro else str((status or {}).get("nível") or "OK"),
            "erro": erro,
            "worker": worker,
            "duracaoSegundos": round(float(duracao), 3),
            "precos": preco,
            "mercado": mercado,
            "variacaoMenorLiga": variacao_menor,
            "statusDetalhes": status or {},
            "observacao": texto(dados.get("alteracao")),
        }
        self.itens.append(item)

        simbolo = "✗" if erro else "✓"
        print(f"{simbolo} [{tipo}] {nome} | W{worker or '?'} | {_fmt_tempo(duracao)}")
        if erro:
            print(f"  Erro: {erro}")
        else:
            print(
                "  Preços: menor {0} | 2º {1} | 3º {2} | média {3} | mediana {4} | buylist {5}".format(
                    _fmt_preco_console(preco["menor"]), _fmt_preco_console(preco["segundoMenor"]),
                    _fmt_preco_console(preco["terceiroMenor"]), _fmt_preco_console(preco["media"]),
                    _fmt_preco_console(preco["mediana"]), _fmt_preco_console(preco["buylist"]),
                )
            )
            print(
                f"  Mercado: {mercado['vendedoresGeral']} vendedores ({mercado['vendedoresEspecificos']} específicos) | "
                f"{mercado['compradoresGeral']} compradores ({mercado['compradoresEspecificos']} específicos)"
            )
            nivel = str((status or {}).get("nível") or "OK")
            if nivel != "OK":
                print(f"  Status: {nivel}")
                for motivo in list((status or {}).get("motivos") or [])[:3]:
                    if isinstance(motivo, dict) and motivo.get("mensagem"):
                        print(f"    - {motivo['mensagem']}")
            if texto(dados.get("alteracao")):
                print(f"  Observação: {texto(dados.get('alteracao'))}")
            if isinstance(variacao_menor, dict) and variacao_menor.get("diferença") is not None:
                dif = float(variacao_menor.get("diferença") or 0)
                pct = variacao_menor.get("percentual")
                pct_txt = "" if pct is None else f" ({float(pct):+.2f}%)"
                print(f"  Variação desde a última cotização: {dif:+.2f}{pct_txt}")
        self.imprimir_barra()

    def imprimir_barra(self) -> None:
        if self.total <= 0:
            return
        decorrido = time.monotonic() - self.inicio_mono
        frac = min(1.0, self.concluidos / self.total)
        largura = 28
        cheios = int(round(largura * frac))
        barra = "█" * cheios + "░" * (largura - cheios)
        media = decorrido / self.concluidos if self.concluidos else 0.0
        eta = media * max(0, self.total - self.concluidos)
        print(
            f"  [{barra}] {self.concluidos}/{self.total} ({frac*100:5.1f}%) | "
            f"decorrido {_fmt_tempo(decorrido)} | ETA {_fmt_tempo(eta)} | "
            f"{self.sucessos} OK / {self.erros} erros\n"
        )

    def resumo(self) -> dict[str, Any]:
        fim = time.monotonic()
        duracao = fim - self.inicio_mono
        return {
            "iniciadoEm": self.iniciado_em,
            "finalizadoEm": agora_iso(),
            "modoVelocidade": self.modo,
            "workers": self.workers,
            "total": self.total,
            "concluidos": self.concluidos,
            "sucessos": self.sucessos,
            "erros": self.erros,
            "duracaoSegundos": round(duracao, 3),
            "duracaoFormatada": _fmt_tempo(duracao),
            "mediaSegundosPorItem": round(duracao / self.concluidos, 3) if self.concluidos else 0.0,
            "itensPorMinuto": round((self.concluidos / duracao) * 60, 2) if duracao > 0 else 0.0,
            "repeticoes": self.repeticoes,
            "tentativasConsultaItens": self.total + self.repeticoes,
        }


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


def inteiro_com_sinal(valor: Any, padrao: int = 0) -> int:
    """Inteiro que preserva o sinal; usado em deltas de movimentação de estoque."""
    if isinstance(valor, bool):
        return int(valor)
    if isinstance(valor, (int, float)):
        return int(valor)
    encontrado = re.search(r"[-+]?\d+", texto(valor).replace("−", "-"))
    return int(encontrado.group(0)) if encontrado else padrao


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
    minimo = numero(dados.get("minimo"))
    menor = numero(dados.get("menor"))
    segundo_menor = numero(dados.get("segundo_menor"))
    terceiro_menor = numero(dados.get("terceiro_menor"))
    medio = numero(dados.get("medio"))
    mediana = numero(dados.get("mediana"))
    rapida = numero(dados.get("venda_rapida"))
    return {
        "pricingSchemaVersion": 2,
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
    versao_precos = inteiro_nao_negativo(linha.get("pricingSchemaVersion"), 0)
    buylist_legada = numero(primeiro(linha, "Minimo", "Mínimo", "Preço mínimo"))
    venda_rapida_salva = numero(primeiro(linha, "Venda Rapida", "Venda Rápida", "Venda rápida"))
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
        "Quantidade": inteiro_nao_negativo(primeiro(linha, "Quantidade"), 1),
        "Imagem": texto(primeiro(linha, "Imagem")),
        "À venda": _sim_nao(primeiro(linha, "À venda", "Venda"), True),
    })
    menor_liga = numero(carta.get("Menor Liga"))
    carta["Minimo"] = round(menor_liga * 0.50, 2) if menor_liga is not None else (numero(carta.get("Minimo")) if versao_precos >= 2 else None)
    carta["Venda Rapida"] = venda_rapida_salva if versao_precos >= 2 else (buylist_legada if buylist_legada is not None else venda_rapida_salva)
    if carta["Minimo"] is not None and carta["Venda Rapida"] is not None and carta["Venda Rapida"] < carta["Minimo"]:
        carta["Minimo"] = round(carta["Venda Rapida"] * 0.95, 2)
    carta["pricingSchemaVersion"] = 2
    for legado in ("Preço Médio Liga", "Preço médio Liga", "Mínimo Certeiro", "Minimo Certeiro"):
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
    versao_precos = inteiro_nao_negativo(linha.get("pricingSchemaVersion"), 0)
    buylist_legada = numero(primeiro(linha, "Minimo", "Preço mínimo", "Mínimo"))
    venda_rapida_salva = numero(primeiro(linha, "Venda Rapida", "Venda rápida", "Venda Rápida"))
    booster.update({
        "Tipo de pacote": texto(primeiro(linha, "Tipo de pacote", "Coleção", "Nome")),
        "Quantidade": inteiro_nao_negativo(primeiro(linha, "Quantidade"), 1),
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
    menor_liga = numero(booster.get("Menor Liga"))
    booster["Minimo"] = round(menor_liga * 0.50, 2) if menor_liga is not None else (numero(booster.get("Minimo")) if versao_precos >= 2 else None)
    booster["Venda Rapida"] = venda_rapida_salva if versao_precos >= 2 else (buylist_legada if buylist_legada is not None else venda_rapida_salva)
    if booster["Minimo"] is not None and booster["Venda Rapida"] is not None and booster["Venda Rapida"] < booster["Minimo"]:
        booster["Minimo"] = round(booster["Venda Rapida"] * 0.95, 2)
    booster["pricingSchemaVersion"] = 2
    for legado in ("Preço mínimo", "Venda rápida", "Preço Liga mais barato", "Preço médio Liga", "Preço Médio Liga", "Mínimo Certeiro", "Minimo Certeiro"):
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
        "Quantidade": inteiro_nao_negativo(primeiro(linha, "Quantidade"), 1),
        "Imagem": texto(primeiro(linha, "Imagem")),
        "À venda": _sim_nao(primeiro(linha, "À venda", "Venda"), True),
    })
    produto["Id"] = texto(primeiro(linha, "Id", "ID")) or f"PRODUTO-{chave_texto(nome) or hashlib.sha1(nome.encode('utf-8')).hexdigest()[:12].upper()}"
    produto.pop("ID", None)
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
        "Quantidade": inteiro_nao_negativo(primeiro(linha, "Quantidade"), 1),
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


def formatar_nova_colecao(item: Path, modo: str, workers: int = 1) -> Path:
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

        total_consultas = len(pendentes_cartas) + len(pendentes_boosters)
        monitor = MonitorOperacao(total_consultas, "formatacao", workers)

        if pendentes_cartas or pendentes_boosters:
            trabalhos: list[dict[str, Any]] = [
                {"tipo": "carta", "indice": indice, "linha": linha, "chave": chave_pre}
                for indice, linha, chave_pre in pendentes_cartas
            ] + [
                {"tipo": "booster", "indice": indice, "linha": linha, "chave": chave_pre}
                for indice, linha, chave_pre in pendentes_boosters
            ]

            def consultar_trabalho(trabalho: dict[str, Any], sessao: SessaoLiga) -> tuple[dict[str, Any], str]:
                if trabalho["tipo"] == "carta":
                    return _consultar_uma_carta(trabalho["linha"], sessao)
                return _consultar_um_booster(trabalho["linha"], sessao)

            with PoolLiga(workers) as pool:
                pendentes_tentativa = trabalhos
                for tentativa in (1, 2):
                    falhas: list[dict[str, Any]] = []
                    for retorno in pool.executar(pendentes_tentativa, consultar_trabalho):
                        trabalho = retorno["trabalho"]
                        tipo = trabalho["tipo"]
                        linha = trabalho["linha"]
                        chave_pre = trabalho["chave"]
                        dados, erro = retorno["dados"], retorno["erro"]
                        worker = int(retorno.get("worker") or 0)
                        duracao = float(retorno.get("duracao") or 0.0)
                        nome = (
                            texto(primeiro(linha, "Nome")) or texto(primeiro(linha, "Link Liga", "Link"))
                            if tipo == "carta"
                            else texto(primeiro(linha, "Tipo de pacote", "Nome")) or texto(primeiro(linha, "Link Liga", "Link"))
                        )
                        historico_tipo = "cartas" if tipo == "carta" else "boosters"
                        if erro:
                            estado["errosPendentes"][historico_tipo][chave_pre] = {"erro": erro, "tentativa": tentativa, "em": agora_iso()}
                            anexar_historico(destino, historico_tipo, _registro_falha(linha, historico_tipo, cotacao_id, erro))
                            salvar_estado()
                            if tentativa == 1:
                                falhas.append(trabalho)
                                monitor.falha_temporaria(nome, tipo, erro, worker, tentativa)
                            else:
                                monitor.registrar(nome, tipo, dados, erro, worker, duracao)
                            continue

                        if tipo == "carta":
                            nova, registro = montar_carta_nova(linha, dados, modo, cotacao_id, data)
                            if inteiro_nao_negativo(nova.get("Quantidade"), 0) == 0:
                                nova["À venda"] = False
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
                            status = nova.get("Status") if isinstance(nova.get("Status"), dict) else {}
                        else:
                            novo, registro = montar_booster_novo(linha, dados, modo, cotacao_id, data)
                            if inteiro_nao_negativo(novo.get("Quantidade"), 0) == 0:
                                novo["À venda"] = False
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
                            status = novo.get("Status") if isinstance(novo.get("Status"), dict) else {}
                        salvar_estado()
                        monitor.registrar(nome, tipo, dados, "", worker, duracao, status=status)

                    if not falhas:
                        break
                    if tentativa == 1:
                        print(f"{len(falhas)} item(ns) falharam; repetindo somente esses itens em paralelo...")
                        pendentes_tentativa = falhas

        escrever_inventario(destino, "cartas", cartas)
        escrever_inventario(destino, "boosters", boosters)
        salvar_estado()

        total_pendentes = len(estado["errosPendentes"]["cartas"]) + len(estado["errosPendentes"]["boosters"])
        if total_pendentes:
            perfil.update({"updatedAt": agora_iso(), "formattingComplete": False, "formattingPending": total_pendentes})
            escrever_json_obj(destino / ARQUIVO_PERFIL, perfil)
            print(f"Formatação parcial salva: {total_pendentes} item(ns) ainda pendente(s). Execute novamente para retomar.")
            if total_consultas:
                salvar_relatorio_execucao_liga(destino, "formatacao-parcial", monitor.resumo(), monitor.itens, {"pendentes": total_pendentes})
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
        anexar_movimentacoes(destino, _movimentacoes_formatacao(
            {"cartas": cartas, "boosters": boosters, "kits": kits, "produtos": produtos},
            cotacao_id, identificador, int(perfil.get("version") or 1), data,
        ))
        estado_path.unlink(missing_ok=True)
        arquivar_csvs_legados(destino)
        if total_consultas:
            rel_json, rel_txt = salvar_relatorio_execucao_liga(destino, "formatacao", monitor.resumo(), monitor.itens)
            print(f"Relatório final: {rel_txt.name} | {rel_json.name}")
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
        atual["Quantidade"] = inteiro_nao_negativo(atual.get("Quantidade"), 0) + inteiro_nao_negativo(nova.get("Quantidade"), 0)
        # Metadados existentes nunca são apagados por campos vazios da atualização.
        for campo in (
            "Nome", "Número", "Coleção", "Idioma", "Estado", "Ano", "Tipo",
            "Link Liga", "Link MYP", "Link Cardmarket", "Link Tcgplayer", "Link PriceCharting", "Imagem",
        ):
            if not texto(atual.get(campo)) and texto(nova.get(campo)):
                atual[campo] = nova[campo]
        for campo in (
            "Minimo", "Menor Liga", "Segundo Menor Liga", "Terceiro Menor Liga",
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
        atual["Quantidade"] = inteiro_nao_negativo(atual.get("Quantidade"), 0) + inteiro_nao_negativo(novo.get("Quantidade"), 0)
        if not texto(atual.get("Imagem")) and texto(novo.get("Imagem")):
            atual["Imagem"] = novo["Imagem"]
        for campo in (
            "Minimo", "Menor Liga", "Segundo Menor Liga", "Terceiro Menor Liga",
            "Media Liga", "Mediana Liga", "Venda Rapida",
            "Vendedores Geral", "Vendedores Específicos", "Compradores Geral", "Compradores Específicos",
            "Alteração de preço", "Preço coletado", "Preço estimado", "Status", "Última cotação",
        ):
            if novo.get(campo) not in (None, "", {}, []):
                atual[campo] = novo[campo]
        atual.pop("Histórico de preços", None)


def _operacao_patch(linha: dict[str, Any]) -> bool:
    return chave_texto(linha.get("operation") or linha.get("_operation")) in {"PATCH", "EDIT", "EDITAR"}


def _operacao_remover(linha: dict[str, Any]) -> bool:
    return chave_texto(linha.get("operation") or linha.get("_operation")) in {"REMOVE", "DELETE", "REMOVER", "EXCLUIR"}


def _aplicar_remocoes(existentes: list[dict[str, Any]], remocoes: list[dict[str, Any]], normalizador, tipo: str) -> None:
    if not remocoes:
        return
    indice = {normalizador(item)["Id"]: item for item in existentes}
    for remocao in remocoes:
        item_id = texto(remocao.get("Id") or remocao.get("ID") or remocao.get("id"))
        if not item_id:
            item_id = normalizador(remocao)["Id"]
        atual = indice.get(item_id)
        if atual is None:
            raise ValueError(f"Remoção de {tipo} aponta para item inexistente: {item_id}")
        existentes.remove(atual)
        indice.pop(item_id, None)


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
            atual["Quantidade"] = inteiro_nao_negativo(patch.get("Quantidade"), 0)
        if "À venda" in patch or "Venda" in patch:
            atual["À venda"] = _sim_nao(primeiro(patch, "À venda", "Venda"), True)

        if identidade_alterada:
            for campo in (
                "Minimo", "Menor Liga", "Segundo Menor Liga", "Terceiro Menor Liga",
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
            atual["Quantidade"] = inteiro_nao_negativo(atual.get("Quantidade"), 0) + inteiro_nao_negativo(novo.get("Quantidade"), 0)
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



TIPOS_MOVIMENTACAO = ("cartas", "boosters", "kits", "produtos")


def _id_item_movimento(item: dict[str, Any], tipo: str) -> str:
    if tipo == "cartas":
        return normalizar_carta_existente(item)["Id"]
    if tipo == "boosters":
        return normalizar_booster_existente(item)["Id"]
    if tipo == "kits":
        return normalizar_kit(item)["Id"]
    return normalizar_produto(item)["Id"]


def _nome_item_movimento(item: dict[str, Any], tipo: str) -> str:
    if tipo == "boosters":
        return texto(primeiro(item, "Tipo de pacote", "Nome", "Coleção")) or "Booster"
    return texto(primeiro(item, "Nome", "Produto")) or tipo.rstrip("s").title()


def _snapshot_movimentacoes(inventarios: dict[str, list[dict[str, Any]]]) -> dict[tuple[str, str], dict[str, Any]]:
    snapshot: dict[tuple[str, str], dict[str, Any]] = {}
    for tipo in TIPOS_MOVIMENTACAO:
        for item in inventarios.get(tipo, []):
            item_id = _id_item_movimento(item, tipo)
            snapshot[(tipo, item_id)] = {
                "itemId": item_id,
                "itemType": tipo,
                "name": _nome_item_movimento(item, tipo),
                "quantity": inteiro_nao_negativo(item.get("Quantidade"), 0),
            }
    return snapshot


def _evento_movimentacao_id(update_id: str, item_type: str, item_id: str, indice: int, evento: str) -> str:
    base = f"{update_id}|{item_type}|{item_id}|{indice}|{evento}"
    return "mov-" + hashlib.sha256(base.encode("utf-8")).hexdigest()[:20]


def _normalizar_movimentacao_recebida(
    bruto: dict[str, Any],
    update_id_padrao: str,
    versao_padrao: int,
    data_padrao: str,
    collection_id: str,
    indice: int,
) -> dict[str, Any]:
    item_type = texto(bruto.get("itemType") or bruto.get("tipoItem") or bruto.get("kind") or "cartas").lower()
    aliases = {"card": "cartas", "cards": "cartas", "carta": "cartas", "booster": "boosters", "kit": "kits", "product": "produtos", "produto": "produtos"}
    item_type = aliases.get(item_type, item_type)
    if item_type not in TIPOS_MOVIMENTACAO:
        item_type = "cartas"
    item_id = texto(bruto.get("itemId") or bruto.get("Id") or bruto.get("id"))
    evento = texto(bruto.get("eventType") or bruto.get("tipo") or "ajuste").lower().replace(" ", "_")
    update_id = texto(bruto.get("updateId") or bruto.get("sourceId")) or update_id_padrao
    data = texto(bruto.get("date") or bruto.get("data")) or data_padrao
    delta = inteiro_com_sinal(bruto.get("quantityDelta") if bruto.get("quantityDelta") is not None else bruto.get("delta"))
    antes = inteiro_nao_negativo(bruto.get("quantityBefore"), 0)
    depois_bruto = bruto.get("quantityAfter")
    depois = inteiro_nao_negativo(depois_bruto, max(0, antes + delta)) if depois_bruto not in (None, "") else max(0, antes + delta)
    event_id = texto(bruto.get("eventId")) or _evento_movimentacao_id(update_id, item_type, item_id, indice, evento)
    before_fornecido = bruto.get("quantityBefore") not in (None, "")
    return {
        "eventId": event_id,
        "updateId": update_id,
        "collectionId": texto(bruto.get("collectionId")) or collection_id,
        "version": inteiro(bruto.get("version")) or versao_padrao,
        "date": data,
        "eventType": evento,
        "itemType": item_type,
        "itemId": item_id,
        "name": texto(bruto.get("name") or bruto.get("nome")),
        "quantityBefore": antes,
        "_quantityBeforeProvided": before_fornecido,
        "quantityDelta": delta,
        "quantityAfter": depois,
        "source": texto(bruto.get("source")) or "site",
        "note": texto(bruto.get("note") or bruto.get("observacao")),
    }


def _consolidar_movimentacoes_update(
    antes: dict[str, list[dict[str, Any]]],
    depois: dict[str, list[dict[str, Any]]],
    recebidas: list[dict[str, Any]],
    update_id: str,
    versao: int,
    data: str,
    collection_id: str,
) -> list[dict[str, Any]]:
    snap_antes = _snapshot_movimentacoes(antes)
    snap_depois = _snapshot_movimentacoes(depois)
    normalizadas = [
        _normalizar_movimentacao_recebida(bruto, update_id, versao, data, collection_id, indice)
        for indice, bruto in enumerate(recebidas, 1)
        if isinstance(bruto, dict)
    ]
    atuais_por_item: dict[tuple[str, str], list[dict[str, Any]]] = {}
    historicas: list[dict[str, Any]] = []
    for evento in normalizadas:
        if evento["updateId"] == update_id and evento.get("itemId"):
            atuais_por_item.setdefault((evento["itemType"], evento["itemId"]), []).append(evento)
        else:
            evento.pop("_quantityBeforeProvided", None)
            historicas.append(evento)

    geradas: list[dict[str, Any]] = [*historicas]
    chaves = sorted(set(snap_antes) | set(snap_depois))
    for chave in chaves:
        anterior = snap_antes.get(chave, {"quantity": 0, "name": snap_depois.get(chave, {}).get("name", "")})
        atual = snap_depois.get(chave, {"quantity": 0, "name": anterior.get("name", "")})
        quantidade_antes = int(anterior.get("quantity") or 0)
        quantidade_depois = int(atual.get("quantity") or 0)
        delta_total = quantidade_depois - quantidade_antes
        explicitas = atuais_por_item.pop(chave, [])
        if delta_total == 0 and not explicitas:
            continue

        cursor = quantidade_antes
        indice_auto = 0
        for indice, evento in enumerate(explicitas, 1):
            before_fornecido = bool(evento.pop("_quantityBeforeProvided", False))
            before_declarado = int(evento.get("quantityBefore") or 0)

            # Se o site registrou o saldo imediatamente anterior ao evento, preserva
            # essa ordem. Isso é importante quando o pacote já trazia outra mudança
            # de quantidade e depois o usuário clicou em "Vendi 1".
            if before_fornecido and before_declarado != cursor:
                gap = before_declarado - cursor
                indice_auto += 1
                tipo, item_id = chave
                gap_tipo = "entrada" if gap > 0 else "ajuste_saida"
                geradas.append({
                    "eventId": _evento_movimentacao_id(update_id, tipo, item_id, indice_auto, f"pre_{gap_tipo}"),
                    "updateId": update_id,
                    "collectionId": collection_id,
                    "version": versao,
                    "date": data,
                    "eventType": gap_tipo,
                    "itemType": tipo,
                    "itemId": item_id,
                    "name": atual.get("name") or anterior.get("name") or "",
                    "quantityBefore": cursor,
                    "quantityDelta": gap,
                    "quantityAfter": max(0, cursor + gap),
                    "source": "gerenciador",
                    "note": "Movimentação inferida antes de um evento explícito para reconciliar o saldo desta atualização.",
                })
                cursor = max(0, cursor + gap)

            delta = int(evento.get("quantityDelta") or 0)
            evento["quantityBefore"] = cursor
            cursor = max(0, cursor + delta)
            evento["quantityAfter"] = cursor
            evento["version"] = versao
            evento["date"] = evento.get("date") or data
            evento["collectionId"] = evento.get("collectionId") or collection_id
            evento["name"] = evento.get("name") or atual.get("name") or anterior.get("name") or ""
            geradas.append(evento)

        restante = quantidade_depois - cursor
        if restante:
            tipo, item_id = chave
            if restante > 0:
                evento_tipo = "entrada"
            elif chave not in snap_depois:
                evento_tipo = "remocao"
            else:
                evento_tipo = "ajuste_saida"
            before_auto = cursor
            after_auto = max(0, before_auto + restante)
            indice_auto += 1
            geradas.append({
                "eventId": _evento_movimentacao_id(update_id, tipo, item_id, len(explicitas) + indice_auto, evento_tipo),
                "updateId": update_id,
                "collectionId": collection_id,
                "version": versao,
                "date": data,
                "eventType": evento_tipo,
                "itemType": tipo,
                "itemId": item_id,
                "name": atual.get("name") or anterior.get("name") or "",
                "quantityBefore": before_auto,
                "quantityDelta": restante,
                "quantityAfter": after_auto,
                "source": "gerenciador",
                "note": "Movimentação inferida pela diferença de quantidade desta atualização.",
            })

    # Eventos explícitos que apontam para item sem diferença ainda são preservados como auditoria.
    for eventos in atuais_por_item.values():
        for evento in eventos:
            evento.pop("_quantityBeforeProvided", None)
            geradas.append(evento)
    return geradas


def _movimentacoes_formatacao(
    inventarios: dict[str, list[dict[str, Any]]],
    formatacao_id: str,
    collection_id: str,
    versao: int,
    data: str,
) -> list[dict[str, Any]]:
    eventos: list[dict[str, Any]] = []
    for (tipo, item_id), item in _snapshot_movimentacoes(inventarios).items():
        quantidade = int(item.get("quantity") or 0)
        if quantidade <= 0:
            continue
        eventos.append({
            "eventId": _evento_movimentacao_id(formatacao_id, tipo, item_id, 1, "entrada"),
            "updateId": formatacao_id,
            "collectionId": collection_id,
            "version": versao,
            "date": data,
            "eventType": "entrada",
            "itemType": tipo,
            "itemId": item_id,
            "name": item.get("name") or "",
            "quantityBefore": 0,
            "quantityDelta": quantidade,
            "quantityAfter": quantidade,
            "source": "formatacao",
            "note": "Entrada registrada na primeira formatação da coleção.",
        })
    return eventos

def _sincronizar_ultima_cotacao_importada(
    itens: list[dict[str, Any]], registros: list[dict[str, Any]]
) -> None:
    """Aponta o inventário para a cotização importada mais recente de cada item."""
    if not itens or not registros:
        return
    indice = {texto(item.get("Id")): item for item in itens if texto(item.get("Id"))}
    melhores: dict[str, dict[str, Any]] = {}
    for registro in registros:
        if not isinstance(registro, dict) or registro.get("sucesso") is False or texto(registro.get("erro")):
            continue
        item_id = texto(registro.get("itemId") or registro.get("Id"))
        data = texto(registro.get("data"))
        if not item_id or not data or item_id not in indice:
            continue
        atual = melhores.get(item_id)
        if atual is None or data > texto(atual.get("data")):
            melhores[item_id] = registro
    for item_id, registro in melhores.items():
        item = indice[item_id]
        ultima = item.get("Última cotação") if isinstance(item.get("Última cotação"), dict) else {}
        data_atual = texto(ultima.get("data"))
        data_importada = texto(registro.get("data"))
        if data_atual and data_atual >= data_importada:
            continue
        item["Última cotação"] = {
            "cotacaoId": texto(registro.get("cotacaoId")),
            "data": data_importada,
            "sucesso": True,
        }


def _mesclar_perfil_editavel(perfil: dict[str, Any], perfil_update: dict[str, Any]) -> None:
    campos = (
        "owner", "title", "description", "email", "phone", "password",
        "selling", "featured", "proposalTerms", "profilePhoto", "palette", "priceDisplayFallback",
    )
    for campo in campos:
        if campo in perfil_update:
            perfil[campo] = perfil_update[campo]
    # Quantidade de kits nunca é exibida publicamente no schema atual.
    perfil["showQuantity"] = False


def atualizar_colecao(item: Path, modo_padrao: str = MODO_MENOR, destino_manual: Path | None = None, workers: int = 1) -> Path:
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
        inventarios_antes = {
            "cartas": copy.deepcopy(cartas),
            "boosters": copy.deepcopy(boosters),
            "kits": copy.deepcopy(kits),
            "produtos": copy.deepcopy(produtos),
        }
        movimentacoes_recebidas = ler_movimentacoes(origem)
        historico_importado_cartas = ler_historico(origem, "cartas")
        historico_importado_boosters = ler_historico(origem, "boosters")
        todas_cartas_update = ler_inventario(origem, "cartas")
        todos_boosters_update = ler_inventario(origem, "boosters")
        todos_kits_update = ler_inventario(origem, "kits")
        todos_produtos_update = ler_inventario(origem, "produtos")
        todos_albuns_update = ler_inventario(origem, "albuns")

        remocoes_cartas = [x for x in todas_cartas_update if _operacao_remover(x)]
        remocoes_boosters = [x for x in todos_boosters_update if _operacao_remover(x)]
        remocoes_kits = [x for x in todos_kits_update if _operacao_remover(x)]
        remocoes_produtos = [x for x in todos_produtos_update if _operacao_remover(x)]
        remocoes_albuns = [x for x in todos_albuns_update if _operacao_remover(x)]

        patches_cartas = [x for x in todas_cartas_update if _operacao_patch(x)]
        patches_boosters = [x for x in todos_boosters_update if _operacao_patch(x)]
        # Todo item novo recebe uma primeira cotização, mesmo que já entre com saldo 0.
        # Depois de cadastrado, as cotizações normais continuam ignorando itens zerados.
        novas_cartas_src = [x for x in todas_cartas_update if not _operacao_patch(x) and not _operacao_remover(x)]
        novos_boosters_src = [x for x in todos_boosters_update if not _operacao_patch(x) and not _operacao_remover(x)]
        novos_kits_src = [x for x in todos_kits_update if not _operacao_remover(x)]
        novos_produtos_src = [x for x in todos_produtos_update if not _operacao_remover(x)]
        novos_albuns_src = [x for x in todos_albuns_update if not _operacao_remover(x)]
        cotacao_id = f"update-{update_id}"
        data = texto(metadados.get("generatedAt")) or agora_iso()
        novas_cartas: list[dict[str, Any]] = []
        novos_boosters: list[dict[str, Any]] = []
        historico_cartas: list[dict[str, Any]] = []
        historico_boosters: list[dict[str, Any]] = []
        mapa_ids: dict[str, str] = {}

        total_consultas = len(novas_cartas_src) + len(novos_boosters_src)
        monitor = MonitorOperacao(total_consultas, "atualizacao", workers)

        if novas_cartas_src or novos_boosters_src:
            trabalhos: list[dict[str, Any]] = [
                {"tipo": "carta", "ordem": i, "linha": linha}
                for i, linha in enumerate(novas_cartas_src, 1)
            ] + [
                {"tipo": "booster", "ordem": i, "linha": linha}
                for i, linha in enumerate(novos_boosters_src, 1)
            ]
            cartas_ordenadas: list[tuple[int, dict[str, Any]]] = []
            boosters_ordenados: list[tuple[int, dict[str, Any]]] = []
            historico_cartas_ordenado: list[tuple[int, dict[str, Any]]] = []
            historico_boosters_ordenado: list[tuple[int, dict[str, Any]]] = []

            def consultar_trabalho_update(trabalho: dict[str, Any], sessao: SessaoLiga) -> tuple[dict[str, Any], str]:
                return (
                    _consultar_uma_carta(trabalho["linha"], sessao)
                    if trabalho["tipo"] == "carta"
                    else _consultar_um_booster(trabalho["linha"], sessao)
                )

            falhas_finais: list[dict[str, Any]] = []
            with PoolLiga(workers) as pool:
                pendentes_tentativa = trabalhos
                for tentativa in (1, 2):
                    falhas: list[dict[str, Any]] = []
                    for retorno in pool.executar(pendentes_tentativa, consultar_trabalho_update):
                        trabalho = retorno["trabalho"]
                        tipo = trabalho["tipo"]
                        ordem = int(trabalho["ordem"])
                        linha = trabalho["linha"]
                        dados, erro = retorno["dados"], retorno["erro"]
                        worker = int(retorno.get("worker") or 0)
                        duracao = float(retorno.get("duracao") or 0.0)
                        nome = (
                            texto(primeiro(linha, "Nome")) or texto(primeiro(linha, "Link Liga", "Link"))
                            if tipo == "carta"
                            else texto(primeiro(linha, "Tipo de pacote", "Nome")) or texto(primeiro(linha, "Link Liga", "Link"))
                        )
                        if erro:
                            hist_tipo = "cartas" if tipo == "carta" else "boosters"
                            anexar_historico(destino, hist_tipo, _registro_falha(linha, hist_tipo, cotacao_id, erro))
                            if tentativa == 1:
                                falhas.append(trabalho)
                                monitor.falha_temporaria(nome, tipo, erro, worker, tentativa)
                            else:
                                falhas_finais.append({"trabalho": trabalho, "erro": erro})
                                monitor.registrar(nome, tipo, dados, erro, worker, duracao)
                            continue

                        if tipo == "carta":
                            nova, registro = montar_carta_nova(linha, dados, modo, cotacao_id, data)
                            if inteiro_nao_negativo(nova.get("Quantidade"), 0) == 0:
                                nova["À venda"] = False
                            imagem = baixar_imagem(texto(dados.get("imagem")), f"{nova['Nome']}_{nova['Número']}")
                            if imagem:
                                nova["Imagem"] = imagem
                            cartas_ordenadas.append((ordem, nova))
                            historico_cartas_ordenado.append((ordem, registro))
                            chave_pre = identificador_carta(normalizar_carta_existente(linha))
                            mapa_ids[chave_pre] = nova["Id"]
                            id_origem = texto(linha.get("Id") or linha.get("id"))
                            if id_origem:
                                mapa_ids[id_origem] = nova["Id"]
                            status = nova.get("Status") if isinstance(nova.get("Status"), dict) else {}
                        else:
                            novo, registro = montar_booster_novo(linha, dados, modo, cotacao_id, data)
                            if inteiro_nao_negativo(novo.get("Quantidade"), 0) == 0:
                                novo["À venda"] = False
                            imagem = baixar_imagem(texto(dados.get("imagem")), f"Booster_{novo['Tipo de pacote']}")
                            if imagem:
                                novo["Imagem"] = imagem
                            boosters_ordenados.append((ordem, novo))
                            historico_boosters_ordenado.append((ordem, registro))
                            chave_pre = identificador_booster(normalizar_booster_existente(linha))
                            mapa_ids[chave_pre] = novo["Id"]
                            id_origem = texto(linha.get("Id") or linha.get("id"))
                            if id_origem:
                                mapa_ids[id_origem] = novo["Id"]
                            status = novo.get("Status") if isinstance(novo.get("Status"), dict) else {}
                        monitor.registrar(nome, tipo, dados, "", worker, duracao, status=status)

                    if not falhas:
                        break
                    if tentativa == 1:
                        print(f"{len(falhas)} item(ns) falharam; repetindo somente esses itens em paralelo...")
                        pendentes_tentativa = falhas

            novas_cartas.extend(x for _, x in sorted(cartas_ordenadas, key=lambda x: x[0]))
            novos_boosters.extend(x for _, x in sorted(boosters_ordenados, key=lambda x: x[0]))
            historico_cartas = [x for _, x in sorted(historico_cartas_ordenado, key=lambda x: x[0])]
            historico_boosters = [x for _, x in sorted(historico_boosters_ordenado, key=lambda x: x[0])]
            if falhas_finais:
                rel_json, rel_txt = salvar_relatorio_execucao_liga(
                    destino, "atualizacao-cancelada", monitor.resumo(), monitor.itens,
                    {"updateId": update_id, "motivo": "Uma ou mais consultas falharam após a repetição; inventário oficial não alterado."},
                )
                primeiro_erro = falhas_finais[0]
                t = primeiro_erro["trabalho"]
                raise RuntimeError(
                    f"Atualização cancelada sem alterar inventário: falha em {t['tipo']} #{t['ordem']}: {primeiro_erro['erro']}. "
                    f"Relatório: {rel_txt.name}"
                )

        _aplicar_remocoes(cartas, remocoes_cartas, normalizar_carta_existente, "cartas")
        _aplicar_remocoes(boosters, remocoes_boosters, normalizar_booster_existente, "boosters")
        _aplicar_remocoes(kits, remocoes_kits, normalizar_kit, "kits")
        _aplicar_remocoes(produtos, remocoes_produtos, normalizar_produto, "produtos")
        _aplicar_remocoes(albuns, remocoes_albuns, normalizar_album, "álbuns")
        _aplicar_patches_usuario(cartas, patches_cartas, "cartas")
        _aplicar_patches_usuario(boosters, patches_boosters, "boosters")
        novos_kits = [normalizar_kit(x) for x in novos_kits_src]
        novos_produtos = [normalizar_produto(x) for x in novos_produtos_src]
        novos_albuns = [normalizar_album(x) for x in novos_albuns_src]
        novos_kits, novos_albuns = _remapear_referencias_ids(novos_kits, novos_albuns, mapa_ids)
        _mesclar_cartas(cartas, novas_cartas)
        _mesclar_boosters(boosters, novos_boosters)
        _sincronizar_ultima_cotacao_importada(cartas, historico_importado_cartas)
        _sincronizar_ultima_cotacao_importada(boosters, historico_importado_boosters)
        _mesclar_kits(kits, novos_kits)
        _mesclar_produtos(produtos, novos_produtos)
        _mesclar_albuns(albuns, novos_albuns)
        kits = atualizar_kits(kits, cartas, boosters)
        albuns = atualizar_albuns(albuns, cartas)
        versao_update = max(int(perfil.get("version") or 1) + 1, int(metadados.get("version") or 0))
        collection_id = identificador or texto(perfil.get("collectionId")) or destino.name
        inventarios_depois = {"cartas": cartas, "boosters": boosters, "kits": kits, "produtos": produtos}
        movimentacoes_novas = _consolidar_movimentacoes_update(
            inventarios_antes, inventarios_depois, movimentacoes_recebidas,
            update_id, versao_update, data, collection_id,
        )
        movimentacoes_existentes = ler_movimentacoes(destino)
        ids_movimentacoes = {texto(x.get("eventId")) for x in movimentacoes_existentes if texto(x.get("eventId"))}
        movimentacoes_todas = list(movimentacoes_existentes)
        for movimento in movimentacoes_novas:
            evento_id = texto(movimento.get("eventId"))
            if evento_id and evento_id in ids_movimentacoes:
                continue
            if evento_id:
                ids_movimentacoes.add(evento_id)
            movimentacoes_todas.append(movimento)

        _mesclar_perfil_editavel(perfil, perfil_update)
        perfil.update({
            "pricingMode": modo,
            "updatedAt": data,
            "version": versao_update,
            "appliedUpdates": [*aplicadas, update_id][-100:],
        })

        arquivo_movimentacoes = str(Path(PASTA_HISTORICO_NOME) / ARQUIVO_MOVIMENTACOES)
        nomes = [ARQUIVO_PERFIL, *ARQUIVOS_INVENTARIO.values(), arquivo_movimentacoes]
        with transacao_arquivos(destino, nomes) as staging:
            escrever_json_obj(staging / ARQUIVO_PERFIL, perfil)
            escrever_inventario(staging, "cartas", cartas)
            escrever_inventario(staging, "boosters", boosters)
            escrever_inventario(staging, "kits", kits)
            escrever_inventario(staging, "produtos", produtos)
            escrever_inventario(staging, "albuns", albuns)
            escrever_movimentacoes(staging, movimentacoes_todas)
        if historico_importado_cartas:
            anexar_historico(destino, "cartas", historico_importado_cartas)
        if historico_importado_boosters:
            anexar_historico(destino, "boosters", historico_importado_boosters)
        if historico_cartas:
            anexar_historico(destino, "cartas", historico_cartas)
        if historico_boosters:
            anexar_historico(destino, "boosters", historico_boosters)
        arquivar_csvs_legados(destino)
        if total_consultas:
            rel_json, rel_txt = salvar_relatorio_execucao_liga(
                destino, "atualizacao", monitor.resumo(), monitor.itens, {"updateId": update_id}
            )
            print(f"Relatório final: {rel_txt.name} | {rel_json.name}")
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
    # Quantidade zero significa vendido/esgotado: o registro fica no histórico da coleção,
    # mas não deve consumir consulta nem receber novas referências de mercado.
    pares: list[tuple[str, dict[str, Any]]] = [
        ("carta", x) for x in cartas if inteiro_nao_negativo(x.get("Quantidade"), 0) > 0
    ] + [
        ("booster", x) for x in boosters if inteiro_nao_negativo(x.get("Quantidade"), 0) > 0
    ]
    descricao = "Coleção inteira"
    if opcao == "2":
        pares, descricao = [(t, x) for t, x in pares if t == "carta"], "Apenas cartas"
    elif opcao == "3":
        pares, descricao = [(t, x) for t, x in pares if t == "booster"], "Apenas boosters"
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
        return round(sum((numero(x.get(campo)) or 0) * inteiro_nao_negativo(x.get("Quantidade"), 0) for x in itens), 2)
    return {
        "preço": soma(cartas, "Preço") + soma(boosters, "Preço"),
        "buylist": soma(cartas, "Venda Rapida") + soma(boosters, "Venda Rapida"),
        "menor": soma(cartas, "Menor Liga") + soma(boosters, "Menor Liga"),
        "media": soma(cartas, "Media Liga") + soma(boosters, "Media Liga"),
        "vendaRapida": soma(cartas, "Venda Rapida") + soma(boosters, "Venda Rapida"),
    }


def cotizar_colecao(colecao: Path, modo_padrao: str = MODO_MENOR, opcao: str = "1", dias: int | None = None, retomar: bool = True, workers: int = 1) -> Path:
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

    if sessao:
        versao_salva = int(sessao.get("leitorPrecoVersao") or 1)
        if versao_salva < VERSAO_LEITOR_PRECO:
            raise RuntimeError(
                "Esta cotização parcial foi criada com o leitor de preços antigo (OCR v1), "
                "que pode gerar valores 1,11 / 11,11 / 111,11. Não é seguro retomá-la. "
                "Execute a cotização novamente e responda N quando o programa perguntar se deseja continuar; "
                "isso inicia uma cotização nova com o leitor corrigido."
            )

    if not sessao:
        selecionados, descricao = _selecionar_escopo(cartas, boosters, opcao, dias)
        sessao = {
            "cotacaoId": f"cot-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}",
            "dataCotacao": agora_iso(),
            "leitorPrecoVersao": VERSAO_LEITOR_PRECO,
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
    selecionados = [
        alvo for alvo in selecionados
        if (
            alvo.get("tipo") == "carta"
            and alvo.get("id") in mapa_cartas
            and inteiro_nao_negativo(cartas[mapa_cartas[alvo.get("id")]].get("Quantidade"), 0) > 0
        ) or (
            alvo.get("tipo") == "booster"
            and alvo.get("id") in mapa_boosters
            and inteiro_nao_negativo(boosters[mapa_boosters[alvo.get("id")]].get("Quantidade"), 0) > 0
        )
    ]
    sessao["selecionados"] = selecionados

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
    monitor = MonitorOperacao(len(pendentes_execucao), "cotizacao", workers)

    if pendentes_execucao:
        trabalhos: list[dict[str, Any]] = []
        for alvo in pendentes_execucao:
            tipo, item_id = alvo.get("tipo"), alvo.get("id")
            chave = f"{tipo}:{item_id}"
            if tipo == "carta":
                idx = mapa_cartas.get(item_id)
                if idx is None:
                    mensagem = f"Carta {item_id}: não encontrada no inventário"
                    if mensagem not in sessao["errosFatais"]:
                        sessao["errosFatais"].append(mensagem)
                    processados.add(chave)
                    monitor.registrar(str(item_id), "carta", {}, mensagem, 0, 0.0)
                    salvar_progresso()
                    continue
                linha = cartas[idx]
                nome = texto(linha.get("Nome")) or str(item_id)
            else:
                idx = mapa_boosters.get(item_id)
                if idx is None:
                    mensagem = f"Booster {item_id}: não encontrado no inventário"
                    if mensagem not in sessao["errosFatais"]:
                        sessao["errosFatais"].append(mensagem)
                    processados.add(chave)
                    monitor.registrar(str(item_id), "booster", {}, mensagem, 0, 0.0)
                    salvar_progresso()
                    continue
                linha = boosters[idx]
                nome = texto(linha.get("Tipo de pacote")) or str(item_id)
            trabalhos.append({"alvo": alvo, "tipo": tipo, "id": item_id, "chave": chave, "idx": idx, "linha": linha, "nome": nome})

        def consultar_trabalho_cotizacao(trabalho: dict[str, Any], liga: SessaoLiga) -> tuple[dict[str, Any], str]:
            return (
                _consultar_uma_carta(trabalho["linha"], liga)
                if trabalho["tipo"] == "carta"
                else _consultar_um_booster(trabalho["linha"], liga)
            )

        with PoolLiga(workers) as pool:
            pendentes_tentativa = trabalhos
            for tentativa in (1, 2):
                falharam: list[dict[str, Any]] = []
                for retorno in pool.executar(pendentes_tentativa, consultar_trabalho_cotizacao):
                    trabalho = retorno["trabalho"]
                    alvo = trabalho["alvo"]
                    tipo, item_id, chave = trabalho["tipo"], trabalho["id"], trabalho["chave"]
                    idx, nome = int(trabalho["idx"]), trabalho["nome"]
                    dados, erro = retorno["dados"], retorno["erro"]
                    worker = int(retorno.get("worker") or 0)
                    duracao = float(retorno.get("duracao") or 0.0)

                    if erro:
                        linha_atual = cartas[idx] if tipo == "carta" else boosters[idx]
                        registrar_falha(alvo, chave, nome, erro, tentativa, linha_atual)
                        if tentativa == 1:
                            falharam.append(trabalho)
                            monitor.falha_temporaria(nome, tipo, erro, worker, tentativa)
                        else:
                            monitor.registrar(nome, tipo, dados, erro, worker, duracao)
                        continue

                    if tipo == "carta":
                        anterior = copy.deepcopy(cartas[idx])
                        nova, registro = cotizar_carta(cartas[idx], dados, modo, sessao["cotacaoId"], sessao["dataCotacao"])
                        if not texto(nova.get("Imagem")):
                            imagem = baixar_imagem(texto(dados.get("imagem")), f"{nova['Nome']}_{nova['Número']}")
                            if imagem:
                                nova["Imagem"] = imagem
                        cartas[idx] = nova
                        anexar_historico(colecao, "cartas", registro)
                        resultado = registrar_variacoes(nome, item_id, "carta", anterior, nova)
                        escrever_inventario(colecao, "cartas", cartas)
                        status = nova.get("Status") if isinstance(nova.get("Status"), dict) else {}
                    else:
                        anterior = copy.deepcopy(boosters[idx])
                        novo, registro = cotizar_booster(boosters[idx], dados, modo, sessao["cotacaoId"], sessao["dataCotacao"])
                        if not texto(novo.get("Imagem")):
                            imagem = baixar_imagem(texto(dados.get("imagem")), f"Booster_{novo['Tipo de pacote']}")
                            if imagem:
                                novo["Imagem"] = imagem
                        boosters[idx] = novo
                        anexar_historico(colecao, "boosters", registro)
                        resultado = registrar_variacoes(nome, item_id, "booster", anterior, novo)
                        escrever_inventario(colecao, "boosters", boosters)
                        status = novo.get("Status") if isinstance(novo.get("Status"), dict) else {}

                    resultado["execucao"] = {"worker": worker, "duracaoSegundos": round(duracao, 3)}
                    resultado["mercado"] = {
                        "vendedoresGeral": int(dados.get("vendedores_geral") or 0),
                        "vendedoresEspecificos": int(dados.get("vendedores_especificos") or 0),
                        "compradoresGeral": int(dados.get("compradores_geral") or 0),
                        "compradoresEspecificos": int(dados.get("compradores_especificos") or 0),
                        "ofertasLidas": int(dados.get("quantidade_ofertas") or 0),
                        "buylistLida": int(dados.get("quantidade_buylist") or 0),
                    }
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
                    monitor.registrar(nome, tipo, dados, "", worker, duracao, variacao=resultado, status=status)

                if not falharam:
                    break
                if tentativa == 1:
                    print(f"{len(falharam)} item(ns) falharam; repetindo somente esses itens em paralelo...")
                    pendentes_tentativa = falharam

    execucao_atual = monitor.resumo()
    sessao.setdefault("execucoes", [])
    sessao["execucoes"].append(execucao_atual)
    sessao["ultimaExecucao"] = execucao_atual
    sessao["modoVelocidade"] = execucao_atual["modoVelocidade"]
    sessao["workers"] = execucao_atual["workers"]
    salvar_progresso()

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
        rel_json, rel_txt = salvar_relatorio_execucao_liga(
            colecao, "cotizacao-parcial", execucao_atual, monitor.itens, {"cotacaoId": sessao.get("cotacaoId"), "pendentes": len(pendentes)}
        )
        print(f"Relatório desta execução: {rel_txt.name} | {rel_json.name}")
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

