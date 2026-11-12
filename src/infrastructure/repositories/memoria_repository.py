"""Fila de disparo em memória, para o modo demo e os testes.

Imita o comportamento da versão SQL Server: a reserva do lote acontece sob um
lock, então dois workers nunca recebem o mesmo registro (o mesmo efeito do
UPDLOCK + READPAST no banco).
"""
import copy
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List

from src.domain.status import Canal, Status


class RepositorioFilaMemoria:
    def __init__(self, registros: List[Dict[str, Any]], canal: Canal):
        self._registros = {r["ID"]: r for r in registros}
        self._lock = threading.Lock()
        self.canal = canal
        self.total_reservas = 0

    def _do_canal(self, registro: Dict[str, Any]) -> bool:
        eh_preventivo = registro.get("CANAL") == Canal.PREVENTIVO.value
        return eh_preventivo if self.canal == Canal.PREVENTIVO else not eh_preventivo

    def _pendente_hoje(self, registro: Dict[str, Any]) -> bool:
        return (
            self._do_canal(registro)
            and registro["STATUS"] == Status.PENDENTE
            and str(registro.get("ID_TEMPLATE") or "").strip() != ""
            and registro["DT_INCLUSAO"].date() == datetime.now().date()
        )

    def obter_cedentes(self) -> List[Dict[str, Any]]:
        with self._lock:
            ids = sorted({r["ID_CEDENTE"] for r in self._registros.values() if self._pendente_hoje(r)})
        return [{"ID_CEDENTE": i} for i in ids]

    def reservar_lote_envio(self, limite: int, id_cedente: int) -> List[Dict[str, Any]]:
        with self._lock:
            lote = [
                r for r in sorted(self._registros.values(), key=lambda r: r["ID"])
                if r["ID_CEDENTE"] == id_cedente and self._pendente_hoje(r)
            ][:limite]

            for registro in lote:
                registro["STATUS"] = Status.PROCESSANDO

            self.total_reservas += len(lote)
            return [copy.deepcopy(r) for r in lote]

    def atualizar_status_lote(self, atualizacoes: List[Dict[str, Any]]) -> int:
        with self._lock:
            agora = datetime.now()
            atualizados = 0
            for item in atualizacoes:
                registro = self._registros.get(item["ID"])
                if registro is not None:
                    registro["STATUS"] = item["STATUS"]
                    registro["DT_ENVIO"] = agora
                    atualizados += 1
            return atualizados

    def resetar_processando_antigo(self, minutos: int) -> int:
        with self._lock:
            limite = datetime.now() - timedelta(minutes=minutos)
            resetados = 0
            for registro in self._registros.values():
                if (
                    self._do_canal(registro)
                    and registro["STATUS"] == Status.PROCESSANDO
                    and registro["DT_INCLUSAO"].date() == datetime.now().date()
                    and registro["DT_INCLUSAO"] <= limite
                ):
                    registro["STATUS"] = Status.PENDENTE
                    resetados += 1
            return resetados

    # Apoio para demo e testes
    def contar_por_status(self) -> Dict[str, int]:
        with self._lock:
            contagem: Dict[str, int] = {}
            for registro in self._registros.values():
                contagem[registro["STATUS"]] = contagem.get(registro["STATUS"], 0) + 1
            return contagem

    def obter(self, id_registro: int) -> Dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._registros[id_registro])
