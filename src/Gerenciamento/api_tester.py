from __future__ import annotations

import getpass
import importlib.util
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

DEFAULT_API_URL = "https://vaulttcgsiteapi.onrender.com"
FIREBASE_WEB_API_KEY = "AIzaSyAH2-yNZl048tTL57BCq7gdh82YBZH7GmU"
DEFAULT_MYP_URL = "https://mypcards.com/pokemon/produto/236529/greninja-ex"
REPORT_PATH = Path(__file__).with_name("api_test_report.json")

MYP_DIRECT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "DNT": "1",
    "Upgrade-Insecure-Requests": "1",
}


def garantir_requests() -> None:
    if importlib.util.find_spec("requests") is not None:
        return
    print("Instalando dependência leve do testador: requests")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests>=2.31"])


def agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def limitar_texto(value: Any, max_len: int = 1200) -> str:
    text = str(value or "")
    return text if len(text) <= max_len else text[:max_len] + "..."


def limpar_segredos(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            lower = str(key).lower()
            if any(token in lower for token in ("token", "password", "authorization", "privatekey", "private_key")):
                result[key] = "[REDACTED]"
            else:
                result[key] = limpar_segredos(item)
        return result
    if isinstance(value, list):
        return [limpar_segredos(item) for item in value]
    return value


@dataclass
class Resultado:
    nome: str
    ok: bool
    status: int | None
    segundos: float
    resposta: Any
    erro: str = ""

    def as_dict(self) -> dict[str, Any]:
        return limpar_segredos({
            "nome": self.nome,
            "ok": self.ok,
            "status": self.status,
            "segundos": round(self.segundos, 3),
            "resposta": self.resposta,
            "erro": self.erro,
        })


class VaultApiTester:
    def __init__(self, base_url: str):
        import requests

        self.requests = requests
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.token = ""
        self.uid = ""
        self.email = ""
        self.resultados: list[Resultado] = []

    def registrar(self, result: Resultado) -> Resultado:
        self.resultados.append(result)
        status = str(result.status) if result.status is not None else "REDE"
        marker = "OK" if result.ok else "FALHOU"
        print(f"[{marker:<6}] {result.nome:<34} HTTP {status:<4} {result.segundos:>6.2f}s")
        if not result.ok:
            print(f"         {limitar_texto(result.erro or result.resposta, 600)}")
        return result

    def request(
        self,
        nome: str,
        method: str,
        path: str,
        *,
        authenticated: bool = False,
        timeout: float = 45,
        expected: tuple[int, ...] = (200,),
        **kwargs: Any,
    ) -> Resultado:
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.setdefault("Origin", "https://leonn190.github.io")
        if authenticated:
            if not self.token:
                return self.registrar(Resultado(nome, False, None, 0, None, "Login de teste ainda não foi feito."))
            headers["Authorization"] = f"Bearer {self.token}"
        started = time.perf_counter()
        try:
            response = self.session.request(
                method,
                self.base_url + path,
                headers=headers,
                timeout=timeout,
                **kwargs,
            )
            seconds = time.perf_counter() - started
            try:
                payload = response.json()
            except Exception:
                payload = limitar_texto(response.text, 3000)
            ok = response.status_code in expected and not (isinstance(payload, dict) and payload.get("ok") is False)
            error = ""
            if not ok:
                if isinstance(payload, dict):
                    error = f"{payload.get('code') or 'SEM_CODE'}: {payload.get('error') or payload}"
                else:
                    error = str(payload)
            return self.registrar(Resultado(nome, ok, response.status_code, seconds, payload, error))
        except Exception as error:
            seconds = time.perf_counter() - started
            return self.registrar(Resultado(nome, False, None, seconds, None, f"{type(error).__name__}: {error}"))

    def acordar_render(self) -> bool:
        print("\nAcordando/verificando o Render (o plano gratuito pode levar alguns segundos após dormir)...")
        for tentativa in range(1, 4):
            result = self.request(f"Health / tentativa {tentativa}", "GET", "/health", timeout=90)
            if result.ok:
                firebase = result.resposta.get("firebase", {}) if isinstance(result.resposta, dict) else {}
                print(f"         Firebase project: {firebase.get('projectId', '—')}")
                print(f"         Credencial Admin: {firebase.get('adminCredentialConfigured', '—')} ({firebase.get('credentialSource', '—')})")
                if isinstance(result.resposta, dict):
                    print(f"         E-mails de conta: {result.resposta.get('accountEmailDelivery', '—')}")
                    print(f"         Gmail personalizado: {result.resposta.get('gmailConfigured', '—')}")
                    transports = result.resposta.get('mypTransports') or {}
                    if transports:
                        enabled = [name for name, active in transports.items() if active]
                        print(f"         Transportes MYP da API: {', '.join(enabled) if enabled else '—'}")
                    if firebase.get('adminCredentialConfigured') is False:
                        print("         Admin ausente: propostas/Vault+/cotização em massa continuarão indisponíveis até configurar a credencial.")
                    if result.resposta.get('gmailConfigured') is False:
                        print("         Gmail customizado ausente: e-mails de conta usam Firebase; notificações de negociação por Gmail não serão enviadas.")
                return True
            if tentativa < 3:
                print("         Esperando 4 segundos antes de tentar novamente...")
                time.sleep(4)
        return False

    def login_email_senha(self, email: str, senha: str) -> bool:
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_WEB_API_KEY}"
        started = time.perf_counter()
        try:
            response = self.requests.post(
                url,
                json={"email": email, "password": senha, "returnSecureToken": True},
                timeout=35,
            )
            payload = response.json()
            ok = response.status_code == 200 and bool(payload.get("idToken"))
            result = Resultado(
                "Login Firebase para teste",
                ok,
                response.status_code,
                time.perf_counter() - started,
                {"email": payload.get("email"), "localId": payload.get("localId")} if ok else limpar_segredos(payload),
                "" if ok else limitar_texto(payload.get("error", {}).get("message", payload), 500),
            )
            self.registrar(result)
            if ok:
                self.token = str(payload["idToken"])
                self.uid = str(payload.get("localId") or "")
                self.email = str(payload.get("email") or email)
            return ok
        except Exception as error:
            self.registrar(Resultado("Login Firebase para teste", False, None, time.perf_counter() - started, None, str(error)))
            return False

    def teste_myp_local(self, myp_url: str) -> Resultado:
        """Compara o mesmo link a partir do computador que executa o testador."""
        started = time.perf_counter()
        try:
            response = self.requests.get(
                myp_url,
                headers=MYP_DIRECT_HEADERS,
                timeout=30,
                allow_redirects=True,
            )
            elapsed = time.perf_counter() - started
            body = response.text or ""
            # Não guardamos o HTML inteiro no relatório; basta saber se o mesmo link
            # funciona localmente e se a página tem tamanho plausível.
            ok = response.status_code == 200 and len(body) >= 3000
            payload = {
                "finalUrl": response.url,
                "htmlBytes": len(body.encode("utf-8", errors="ignore")),
                "looksLikeProduct": "/pokemon/produto/" in response.url.lower(),
            }
            error = "" if ok else f"HTTP {response.status_code}; HTML {len(body)} caracteres"
            return self.registrar(Resultado("MYP direto deste computador", ok, response.status_code, elapsed, payload, error))
        except Exception as error:
            elapsed = time.perf_counter() - started
            return self.registrar(Resultado("MYP direto deste computador", False, None, elapsed, None, f"{type(error).__name__}: {error}"))

    def teste_publico(self, myp_url: str) -> None:
        print("\nTESTES PÚBLICOS / SEM LOGIN")
        print("-" * 72)
        self.request("Raiz da API", "GET", "/", timeout=30)
        self.request(
            "CORS preflight GitHub Pages",
            "OPTIONS",
            "/api/myp/card",
            timeout=30,
            expected=(200, 204),
            headers={
                "Origin": "https://leonn190.github.io",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        myp = self.request(
            "MYP individual",
            "POST",
            "/api/myp/card",
            json={"url": myp_url},
            timeout=90,
        )
        if myp.ok and isinstance(myp.resposta, dict):
            data = myp.resposta.get("data") or {}
            print(f"         Carta: {data.get('name', '—')} {data.get('number', '')}")
            print(f"         Transporte MYP: {data.get('transport', '—')}")
            if data.get("readerFormat"):
                print(f"         Formato Reader: {data.get('readerFormat')}")
            prices = data.get("prices") or {}
            print(f"         Menor certificado: {prices.get('cheapestCertified', '—')}")
        else:
            print("\nComparando com a mesma consulta MYP feita diretamente deste computador...")
            local = self.teste_myp_local(myp_url)
            if local.ok:
                remote_code = myp.resposta.get("code") if isinstance(myp.resposta, dict) else ""
                print("         O link está acessível localmente. A diferença está no caminho Render -> MYP/fallback, não no link digitado.")
                if remote_code == "MYP_FALLBACK_PARSE_FAILED":
                    print("         O Render chegou ao fallback, mas o parser do fallback não reconheceu a página.")
                elif remote_code == "MYP_ANTIBOT_CHALLENGE":
                    print("         O Render e o Reader receberam uma tela anti-bot. A API nova tenta Python/requests e depois Reader em modo browser/no-cache.")

    def teste_autenticado_leitura(self) -> None:
        print("\nTESTES AUTENTICADOS / SEM ALTERAR DADOS")
        print("-" * 72)
        self.request("Validação do Firebase token", "GET", "/api/auth/check", authenticated=True, timeout=40)
        self.request("Vault+ status", "GET", "/api/vault-plus/status", authenticated=True, timeout=45)
        for scope in ("all", "sent", "received", "completed"):
            self.request(f"Propostas / {scope}", "GET", f"/api/proposals?scope={scope}&limit=10", authenticated=True, timeout=45)

    def teste_envio_verificacao(self) -> None:
        result = self.request(
            "Enviar e-mail de verificação",
            "POST",
            "/api/email/verification",
            authenticated=True,
            json={"returnUrl": "https://leonn190.github.io/LojaPokemon/central/"},
            timeout=70,
        )
        if result.ok and isinstance(result.resposta, dict):
            print(f"         Método de envio: {result.resposta.get('delivery', '—')}")

    def teste_reset_senha(self) -> None:
        result = self.request(
            "Enviar e-mail de troca de senha",
            "POST",
            "/api/email/password-reset",
            authenticated=True,
            json={"returnUrl": "https://leonn190.github.io/LojaPokemon/central/"},
            timeout=70,
        )
        if result.ok and isinstance(result.resposta, dict):
            print(f"         Método de envio: {result.resposta.get('delivery', '—')}")

    def teste_criar_proposta(self) -> None:
        print("Este teste GRAVA uma proposta real no Firestore e pode enviar Gmail ao vendedor.")
        seller_uid = input("UID Firebase do vendedor: ").strip()
        if not seller_uid:
            print("Cancelado: UID vazio.")
            return
        nome = input("Nome do item de teste [Carta teste]: ").strip() or "Carta teste"
        valor_txt = input("Valor da proposta [1.00]: ").strip() or "1.00"
        try:
            valor = float(valor_txt.replace(",", "."))
        except ValueError:
            print("Valor inválido.")
            return
        self.request(
            "Criar proposta real",
            "POST",
            "/api/proposals",
            authenticated=True,
            json={
                "ownerUid": seller_uid,
                "items": [{"id": "api-tester-item", "kind": "card", "name": nome, "quantity": 1, "price": valor}],
                "publishedTotal": valor,
                "proposedTotal": valor,
                "reason": "Teste manual da API pelo Gerenciamento",
                "buyerName": "API Tester",
            },
            timeout=70,
            expected=(201,),
        )

    def teste_acao_proposta(self) -> None:
        proposal_id = input("ID da proposta: ").strip()
        if not proposal_id:
            return
        action = input("Ação [accept/reject/counter]: ").strip().lower()
        if action not in {"accept", "reject", "counter"}:
            print("Ação inválida.")
            return
        payload: dict[str, Any] = {"action": action, "message": "Teste manual da API"}
        if action == "counter":
            try:
                payload["amount"] = float((input("Novo valor: ").strip()).replace(",", "."))
            except ValueError:
                print("Valor inválido.")
                return
        self.request(
            f"Proposta / {action}",
            "POST",
            f"/api/proposals/{proposal_id}/action",
            authenticated=True,
            json=payload,
            timeout=70,
        )

    def teste_bulk_start(self) -> None:
        print("ATENÇÃO: este teste inicia uma cotização REAL e consome 1 uso semanal do Vault+.")
        confirmar = input("Digite COTIZAR para continuar: ").strip().upper()
        if confirmar != "COTIZAR":
            print("Cancelado.")
            return
        min_txt = input("Valor mínimo (ENTER = sem filtro): ").strip()
        stale_txt = input("Dias sem cotização (ENTER = sem filtro): ").strip()
        filters: dict[str, Any] = {}
        if min_txt:
            filters["minValue"] = float(min_txt.replace(",", "."))
        if stale_txt:
            filters["staleDays"] = int(stale_txt)
        self.request(
            "Iniciar cotização Vault+",
            "POST",
            "/api/quotes/bulk/start",
            authenticated=True,
            json={"filters": filters},
            timeout=90,
            expected=(202,),
        )

    def teste_bulk_status(self) -> None:
        job_id = input("Job ID da cotização: ").strip()
        if job_id:
            self.request("Status cotização", "GET", f"/api/quotes/bulk/{job_id}/status", authenticated=True, timeout=45)

    def salvar_relatorio(self) -> None:
        health = next((r.resposta for r in reversed(self.resultados) if r.nome.startswith("Health") and r.ok), None)
        data = {
            "generatedAt": agora_iso(),
            "apiUrl": self.base_url,
            "loggedUser": {"uid": self.uid or None, "email": self.email or None},
            "health": limpar_segredos(health),
            "results": [result.as_dict() for result in self.resultados],
        }
        REPORT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nRelatório salvo em: {REPORT_PATH}")


def confirmar(pergunta: str) -> bool:
    return input(f"{pergunta} [S/N]: ").strip().upper() in {"S", "SIM"}


def mostrar_diagnostico(tester: VaultApiTester) -> None:
    print("\nDIAGNÓSTICO RÁPIDO")
    print("-" * 72)
    falhas = [r for r in tester.resultados if not r.ok]
    if not falhas:
        print("Todos os testes executados passaram.")
        return

    codes = []
    for result in falhas:
        if isinstance(result.resposta, dict):
            codes.append(str(result.resposta.get("code") or ""))
    if "FIREBASE_ADMIN_NOT_CONFIGURED" in codes:
        print("• O Render está online, mas falta a credencial Firebase Admin. Propostas/Vault+/cotização em massa dependem dela.")
        print("  Verificação e troca de senha podem usar o fallback oficial do Firebase Auth sem Admin.")
    if "FIREBASE_PROJECT_MISMATCH" in codes:
        print("• Frontend e backend estão apontando para projetos Firebase diferentes.")
    if "AUTH_EXPIRED" in codes:
        print("• O token foi recusado de verdade. Refaça o login no testador e confira o log [Vault API][AUTH] no Render.")
    if any(code.startswith("MYP_") for code in codes):
        print("• A falha está na consulta MYP. Compare o resultado do Render com o teste direto deste computador logo acima.")
    if any(result.status is None for result in falhas):
        print("• Houve falha de rede/DNS antes de chegar ao Render.")
    print("• O relatório JSON guarda status HTTP, código de erro e tempo de cada rota sem salvar senha/token.")


def main() -> None:
    garantir_requests()
    print("=" * 72)
    print("VAULT TCG — TESTADOR DA API")
    print("=" * 72)
    print("O testador sabe que o Render gratuito pode estar dormindo e tenta acordá-lo antes dos testes.")

    base = input(f"URL da API [{DEFAULT_API_URL}]: ").strip() or DEFAULT_API_URL
    tester = VaultApiTester(base)
    if not tester.acordar_render():
        print("\nA API não respondeu ao /health após 3 tentativas. Os demais testes ainda podem ser executados, mas provavelmente falharão.")

    myp_url = input(f"Link MYP para teste [{DEFAULT_MYP_URL}]: ").strip() or DEFAULT_MYP_URL
    tester.teste_publico(myp_url)

    health_payload = next((r.resposta for r in reversed(tester.resultados) if r.nome.startswith("Health") and r.ok), {})
    firebase_health = health_payload.get("firebase", {}) if isinstance(health_payload, dict) else {}
    admin_missing = firebase_health.get("adminCredentialConfigured") is False
    if admin_missing:
        print("\nATENÇÃO: detalhes de negociação, propostas, Vault+ e cotização em massa precisam de Firebase Admin.")
        print("O código não pode inventar essa chave privada; ela precisa ser criada no seu projeto Firebase e colocada no Render uma vez.")
        if confirmar("Deseja abrir agora o preparador da credencial Firebase Admin para o Render?"):
            from firebase_admin_setup import preparar_firebase_admin_render
            preparar_firebase_admin_render()

    if confirmar("Deseja testar as rotas que exigem login?"):
        email = input("E-mail da conta Vault: ").strip()
        senha = getpass.getpass("Senha (não será salva nem exibida): ")
        if tester.login_email_senha(email, senha):
            tester.teste_autenticado_leitura()

            while True:
                print("\nTESTES COM EFEITO REAL — só execute o que quiser")
                print("  1. Enviar e-mail de verificação (Gmail customizado ou Firebase fallback)")
                print("  2. Enviar e-mail de troca de senha (Gmail customizado ou Firebase fallback)")
                print("  3. Criar proposta real")
                print("  4. Aceitar/recusar/contrapropor")
                print("  5. Iniciar cotização Vault+ (consome uso semanal)")
                print("  6. Consultar status de uma cotização")
                print("  0. Finalizar testes")
                option = input("Escolha: ").strip()
                actions: dict[str, Callable[[], None]] = {
                    "1": tester.teste_envio_verificacao,
                    "2": tester.teste_reset_senha,
                    "3": tester.teste_criar_proposta,
                    "4": tester.teste_acao_proposta,
                    "5": tester.teste_bulk_start,
                    "6": tester.teste_bulk_status,
                }
                if option == "0":
                    break
                action = actions.get(option)
                if action:
                    action()
                else:
                    print("Opção inválida.")

    mostrar_diagnostico(tester)
    tester.salvar_relatorio()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nTeste cancelado.")
