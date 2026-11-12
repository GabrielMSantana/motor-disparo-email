"""Modo demo: roda o motor completo sem banco e sem SendGrid.

Gera uma fila falsa em memória (com alguns registros inválidos e boletos que
falham de propósito), executa o envio com vários workers e mostra o resumo,
incluindo a checagem de que nenhum destinatário recebeu e-mail duplicado.
"""
import json
import random
import time
from datetime import datetime
from typing import Any, Dict, List

from src.application.services.envio_service import EmailService
from src.domain.status import Canal, Status
from src.infrastructure.providers.fake_provider import BoletoFalso, ProvedorFalso
from src.infrastructure.repositories.memoria_repository import RepositorioFilaMemoria


def gerar_registros(quantidade: int, canal: Canal, *, cedentes=(10, 20, 30), semente: int = 42) -> List[Dict[str, Any]]:
    aleatorio = random.Random(semente)
    registros = []
    for i in range(1, quantidade + 1):
        id_cedente = aleatorio.choice(cedentes)
        variaveis: Dict[str, Any] = {"nome_cliente": f"Cliente {i}", "valor": f"{aleatorio.uniform(50, 900):.2f}"}

        # ~30% com boleto; ~1% desses com URL que falha
        if aleatorio.random() < 0.30:
            variaveis["url"] = "https://boletos.example.com/falha/" if aleatorio.random() < 0.01 else f"https://boletos.example.com/{i}.pdf"

        registros.append({
            "ID": i,
            "ID_CLIENTE": 100000 + i,
            "ID_CEDENTE": id_cedente,
            "NM_CARTEIRA": f"Carteira {id_cedente}",
            "GRUPO": "A",
            "CANAL": canal.value if canal == Canal.PREVENTIVO else "EMAIL",
            # ~0,5% sem e-mail, para mostrar o tratamento de registro inválido
            "EMAIL_CLIENTE": None if aleatorio.random() < 0.005 else f"cliente{i}@example.com",
            "EMAIL_EMPRESA": "cobranca@example.com",
            "ID_TEMPLATE": "d-template-exemplo",
            "VARIAVEIS_JSON": json.dumps(variaveis),
            "STATUS": Status.PENDENTE,
            "DT_INCLUSAO": datetime.now(),
        })
    return registros


def executar_demo(*, quantidade: int = 5000, workers: int = 24, canal: Canal = Canal.ACAO, taxa_falha: float = 0.02) -> Dict[str, Any]:
    repo = RepositorioFilaMemoria(gerar_registros(quantidade, canal), canal)
    provedor = ProvedorFalso(latencia_ms=(5, 20), taxa_falha=taxa_falha, semente=7)

    service = EmailService(
        max_works=workers,
        pesos_cedentes={10: 2, 20: 1},
        tamanho_lote_busca=500,
        tamanho_flush_update=200,
        fabrica_repositorio=lambda _canal: repo,
        fabrica_provedor=lambda: provedor,
        fabrica_boleto=BoletoFalso,
    )

    inicio = time.perf_counter()
    resumo = service.executar_preventivo() if canal == Canal.PREVENTIVO else service.executar_acao()
    duracao = time.perf_counter() - inicio

    resultado = {
        "registros": quantidade,
        "workers": workers,
        "duracao_s": round(duracao, 2),
        "envios_por_segundo": round(provedor.total_enviados / duracao, 1) if duracao else 0,
        "status_final": repo.contar_por_status(),
        "destinatarios_duplicados": provedor.duplicados,
        "anexos_enviados": provedor.anexos,
        "por_cedente": {c: {k: v for k, v in r.items() if k in ("workers", "enviados", "erros")} for c, r in resumo.items()},
    }

    print("\n===== RESULTADO DA DEMO =====")
    for chave, valor in resultado.items():
        print(f"{chave}: {valor}")
    print("=============================\n")
    return resultado
