from __future__ import annotations

import base64
import json
import os
import subprocess
from pathlib import Path
from typing import Any

EXPECTED_PROJECT_ID = "nexustcg-ad9d3"
RENDER_ENV_NAME = "FIREBASE_SERVICE_ACCOUNT_JSON_B64"


def _texto(value: Any) -> str:
    return str(value or "").strip()


def _ler_json(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_text(encoding="utf-8-sig")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("O arquivo precisa conter um objeto JSON de conta de serviço.")
    return data, raw


def _validar(data: dict[str, Any]) -> None:
    if _texto(data.get("type")) != "service_account":
        raise ValueError("Este JSON não parece ser uma conta de serviço (type=service_account).")
    project_id = _texto(data.get("project_id"))
    if project_id != EXPECTED_PROJECT_ID:
        raise ValueError(
            f'A conta de serviço é do projeto "{project_id or "?"}", mas o Vault usa "{EXPECTED_PROJECT_ID}".'
        )
    if not _texto(data.get("client_email")):
        raise ValueError("O JSON não possui client_email.")
    private_key = _texto(data.get("private_key"))
    if "BEGIN PRIVATE KEY" not in private_key:
        raise ValueError("O JSON não possui uma private_key válida.")


def _copiar_clipboard(text: str) -> bool:
    # No Windows, clip.exe é simples e não exige biblioteca externa.
    if os.name == "nt":
        try:
            subprocess.run(["clip"], input=text, text=True, check=True)
            return True
        except Exception:
            pass
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        root.destroy()
        return True
    except Exception:
        return False


def preparar_firebase_admin_render() -> bool:
    print("\n" + "=" * 72)
    print("PREPARAR FIREBASE ADMIN PARA O RENDER")
    print("=" * 72)
    print("Isto NÃO envia a chave para lugar nenhum. Só valida o JSON local e o converte para Base64.")
    print("Não coloque o JSON/valor Base64 no GitHub e não envie esse arquivo para outras pessoas.")
    print("\nNo Firebase Console: Configurações do projeto > Contas de serviço > Gerar nova chave privada.")

    raw_path = input("Caminho do JSON baixado (ENTER cancela): ").strip().strip('"')
    if not raw_path:
        print("Cancelado.")
        return False

    path = Path(raw_path).expanduser()
    if not path.is_file():
        print(f"Arquivo não encontrado: {path}")
        return False

    try:
        data, _ = _ler_json(path)
        _validar(data)
    except Exception as error:
        print(f"JSON recusado: {error}")
        return False

    # Minificar antes de codificar evita problemas de quebra de linha no painel do Render.
    minified = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    encoded = base64.b64encode(minified.encode("utf-8")).decode("ascii")
    copied = _copiar_clipboard(encoded)

    print("\n[OK] Conta de serviço válida para nexustcg-ad9d3.")
    print(f"     client_email: {_texto(data.get('client_email'))}")
    print(f"     Valor Base64: {len(encoded)} caracteres")
    if copied:
        print("[OK] O valor Base64 foi copiado para a área de transferência.")
    else:
        print("[AVISO] Não consegui usar a área de transferência neste sistema.")
        print("        Rode novamente no Windows ou converta o JSON para Base64 sem quebra de linha.")
        return False

    print("\nAgora no Render:")
    print("  1. Abra o serviço vaulttcgsiteapi > Environment.")
    print(f"  2. Crie/edite a variável {RENDER_ENV_NAME}.")
    print("  3. Cole o valor que está na área de transferência.")
    print("  4. Salve as alterações e faça o novo deploy.")
    print("  5. Rode o Testador da API novamente; /health deve mostrar Credencial Admin: True.")
    print("\nO arquivo JSON original continua sendo um segredo. Guarde-o fora do repositório.")
    return True


if __name__ == "__main__":
    preparar_firebase_admin_render()
