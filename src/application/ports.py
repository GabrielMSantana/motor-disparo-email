"""Contratos (portas) que a camada de aplicação usa.

A aplicação depende só destas interfaces. Assim o mesmo motor roda com:
- SQL Server + SendGrid (produção)
- repositório em memória + provedor falso (demo e testes)
"""
from typing import Any, Dict, List, Protocol


class RepositorioFilaEnvio(Protocol):
    def obter_cedentes(self) -> List[Dict[str, Any]] | None: ...

    def reservar_lote_envio(self, limite: int, id_cedente: int) -> List[Dict[str, Any]] | None:
        """Reserva atomicamente até `limite` registros PENDENTES do cedente,
        marcando-os como PROCESSANDO, e devolve os registros reservados."""
        ...

    def atualizar_status_lote(self, atualizacoes: List[Dict[str, Any]]) -> int: ...

    def resetar_processando_antigo(self, minutos: int) -> int: ...


class ProvedorEmail(Protocol):
    def enviar_template(
        self,
        remetente: str,
        destinatario: str,
        template_id: str,
        variaveis: Dict[str, Any],
        anexo: Any | None = None,
        custom_args: Dict[str, Any] | None = None,
    ) -> int:
        """Envia o e-mail e devolve o status HTTP do provedor."""
        ...


class GeradorAnexoBoleto(Protocol):
    def gerar_anexo_por_url(self, url: str, nome_cliente: str) -> Any: ...
