"""Provedor de e-mail falso para demo e testes. Não envia nada pela rede."""
import random
import threading
import time
from collections import Counter
from typing import Any, Dict


class ProvedorFalso:
    """Simula latência de rede e uma taxa de falhas do provedor.

    Também conta quantas vezes cada destinatário recebeu e-mail, para provar
    que o motor não envia duplicado mesmo com muitos workers em paralelo.
    """

    def __init__(self, *, latencia_ms: tuple[int, int] = (5, 20), taxa_falha: float = 0.0, semente: int | None = None):
        self._latencia_ms = latencia_ms
        self._taxa_falha = taxa_falha
        self._aleatorio = random.Random(semente)
        self._lock = threading.Lock()
        self.envios_por_destinatario: Counter = Counter()
        self.anexos = 0

    def enviar_template(
        self,
        remetente: str,
        destinatario: str,
        template_id: str,
        variaveis: Dict[str, Any],
        anexo: Any | None = None,
        custom_args: Dict[str, Any] | None = None,
    ) -> int:
        with self._lock:
            atraso = self._aleatorio.uniform(*self._latencia_ms) / 1000
            falhou = self._aleatorio.random() < self._taxa_falha

        time.sleep(atraso)

        if falhou:
            return 503

        with self._lock:
            self.envios_por_destinatario[destinatario] += 1
            if anexo is not None:
                self.anexos += 1
        return 202

    @property
    def total_enviados(self) -> int:
        return sum(self.envios_por_destinatario.values())

    @property
    def duplicados(self) -> int:
        return sum(1 for qtd in self.envios_por_destinatario.values() if qtd > 1)


class BoletoFalso:
    """Gera um 'PDF' fixo em vez de baixar. URLs com 'falha' simulam erro."""

    def gerar_anexo_por_url(self, url: str, nome_cliente: str) -> bytes:
        if "falha" in url:
            raise RuntimeError("Erro ao baixar boleto: 404")
        return b"%PDF-1.4 boleto de exemplo"
