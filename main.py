"""Ponto de entrada.

    python main.py demo                 # roda sem banco/SendGrid (dados falsos)
    python main.py demo --qtd 20000 --workers 32
    python main.py acao                 # produção: canal de ação/negociação
    python main.py preventivo           # produção: canal preventivo
"""
import argparse
import json
import os

from src.domain.status import Canal
from src.shared.log_config import configurar_log


def _pesos_cedentes() -> dict:
    """Pesos por cedente vindos do .env, ex.: PESOS_CEDENTES={"10": 2, "20": 1}"""
    bruto = os.getenv("PESOS_CEDENTES", "{}")
    return {int(k): int(v) for k, v in json.loads(bruto).items()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Motor de disparo de e-mails em massa")
    parser.add_argument("comando", choices=["demo", "acao", "preventivo"])
    parser.add_argument("--workers", type=int, default=int(os.getenv("MAX_WORKERS", "24")))
    parser.add_argument("--qtd", type=int, default=5000, help="registros falsos no modo demo")
    parser.add_argument("--max-lotes", type=int, default=None, help="limita lotes por cedente (teste controlado)")
    args = parser.parse_args()

    if args.comando == "demo":
        from src.demo import executar_demo

        configurar_log(None)
        executar_demo(quantidade=args.qtd, workers=args.workers)
        return

    from src.application.services.envio_service import EmailService

    configurar_log(f"envio_{args.comando}.log")
    service = EmailService(
        max_works=args.workers,
        pesos_cedentes=_pesos_cedentes(),
        tamanho_lote_busca=int(os.getenv("TAMANHO_LOTE_BUSCA", "500")),
        tamanho_flush_update=int(os.getenv("TAMANHO_FLUSH_UPDATE", "200")),
        max_lotes_por_cedente=args.max_lotes,
    )

    if args.comando == Canal.PREVENTIVO.value.lower():
        service.executar_preventivo()
    else:
        service.executar_acao()


if __name__ == "__main__":
    main()
