import asyncio
import json
from typing import Any, Dict

from src.application.ports import GeradorAnexoBoleto, ProvedorEmail, RepositorioFilaEnvio
from src.domain.status import Status
from src.shared.log_config import obter_logger

log = obter_logger()


class ProcessadorCedente:
    """Processa todos os registros pendentes de UM cedente (credor).

    Modelo produtor/consumidor com duas filas em memória:

        banco --(reserva lote)--> fila_envio --> N workers --> fila_update --> flush em lote no banco

    - O produtor reserva lotes no banco (atômico) e alimenta a fila de envio.
    - Os workers enviam em paralelo e jogam o resultado na fila de update.
    - Uma tarefa dedicada acumula os resultados e grava no banco em lote.

    As filas têm tamanho máximo: se os workers ficarem lentos, o produtor espera
    (backpressure) em vez de carregar a base inteira na memória.
    """

    def __init__(
        self,
        *,
        id_cedente: int,
        qtd_workers: int,
        tamanho_lote_busca: int,
        tamanho_flush_update: int,
        max_lotes_por_cedente: int | None,
        provedor: ProvedorEmail,
        repositorio: RepositorioFilaEnvio,
        boleto_service: GeradorAnexoBoleto,
    ):
        self.id_cedente = id_cedente
        self.qtd_workers = qtd_workers
        self.tamanho_lote_busca = tamanho_lote_busca
        self.tamanho_flush_update = tamanho_flush_update
        self.max_lotes_por_cedente = max_lotes_por_cedente if max_lotes_por_cedente and max_lotes_por_cedente > 0 else None
        self.provedor = provedor
        self.repo = repositorio
        self.boleto_service = boleto_service
        # Heartbeat: a cada N atualizações mostra o progresso do cedente (útil em
        # bases grandes, sem poluir). Em lotes pequenos nem chega a disparar.
        self._intervalo_log_progresso = 1000

    async def executar(self) -> Dict[str, Any]:
        # Filas pequenas em memória para manipular os casos que serão enviados
        fila_envio: asyncio.Queue = asyncio.Queue(maxsize=max(self.qtd_workers * 2, 100))
        fila_update: asyncio.Queue = asyncio.Queue(maxsize=max(self.tamanho_flush_update * 2, 100))

        resumo = {
            "workers": self.qtd_workers,
            "lotes_reservados": 0,
            "registros_reservados": 0,
            "enviados": 0,
            "erros": 0,
            "atualizados": 0,
        }

        # Tarefa dedicada para acumular atualizações e gravar em lote no banco.
        tarefa_flush = asyncio.create_task(self._consumir_atualizacoes(fila_update, resumo))
        # Workers que fazem o envio e colocam o resultado na fila de update
        tarefas_worker = [
            asyncio.create_task(self._worker_envio(indice + 1, fila_envio, fila_update, resumo))
            for indice in range(self.qtd_workers)
        ]

        while True:
            # Busca um lote no banco e marca os registros como PROCESSANDO.
            # Evita que outro processo pegue os mesmos itens.
            lote = await asyncio.to_thread(
                self.repo.reservar_lote_envio,
                self.tamanho_lote_busca,
                self.id_cedente,
            )

            if not lote:
                break

            resumo["lotes_reservados"] += 1
            resumo["registros_reservados"] += len(lote)

            # Coloca os registros na fila para os workers consumirem.
            # Se a fila encher, este await bloqueia até haver espaço,
            # desacelerando a produção e evitando crescimento descontrolado.
            for registro in lote:
                await fila_envio.put(registro)

            if self.max_lotes_por_cedente is not None and resumo["lotes_reservados"] >= self.max_lotes_por_cedente:
                break

        # Sinal de parada: um None por worker
        for _ in tarefas_worker:
            await fila_envio.put(None)

        await asyncio.gather(*tarefas_worker)
        await fila_update.put(None)
        await tarefa_flush

        log.info(
            f"[CEDENTE {self.id_cedente}] fim | enviados={resumo['enviados']} | "
            f"erros={resumo['erros']} | atualizados={resumo['atualizados']} | "
            f"lotes={resumo['lotes_reservados']}"
        )

        return resumo

    async def _worker_envio(self, worker_id: int, fila_envio: asyncio.Queue, fila_update: asyncio.Queue, resumo: Dict[str, Any]) -> None:
        while True:
            registro = await fila_envio.get()
            try:
                if registro is None:
                    return

                atualizacao = await self._enviar_registro(registro, resumo)
                await fila_update.put(atualizacao)
            finally:
                fila_envio.task_done()

    @staticmethod
    def _ler_variaveis(registro: Dict[str, Any]) -> Dict[str, Any]:
        variaveis = registro.get("VARIAVEIS_JSON") or {}
        if isinstance(variaveis, str):
            try:
                variaveis = json.loads(variaveis)
            except json.JSONDecodeError:
                variaveis = {}

        return variaveis if isinstance(variaveis, dict) else {}

    async def _enviar_registro(self, registro: Dict[str, Any], resumo: Dict[str, Any]) -> Dict[str, Any]:
        """Monta e dispara um e-mail. Nunca lança exceção: devolve o status final."""
        destinatario = registro.get("EMAIL_CLIENTE")
        remetente = registro.get("EMAIL_EMPRESA")
        template_id = registro.get("ID_TEMPLATE")
        anexo = None

        if not destinatario or not remetente or not template_id:
            resumo["erros"] += 1
            return {"ID": registro["ID"], "STATUS": Status.ERRO}

        variaveis = self._ler_variaveis(registro)

        url_boleto = variaveis.get("url")
        if url_boleto:
            try:
                nome_cliente = str(variaveis.get("nome_cliente"))

                anexo = await asyncio.to_thread(
                    self.boleto_service.gerar_anexo_por_url,
                    url_boleto,
                    nome_cliente,
                )
            except Exception as erro:
                resumo["erros"] += 1
                log.error(
                    f"[CEDENTE {self.id_cedente}] Falha ao preparar boleto | "
                    f"id={registro['ID']} | url={url_boleto} | erro={erro}"
                )
                return {"ID": registro["ID"], "STATUS": Status.ERRO_BOLETO}

        # Metadados devolvidos pelo provedor no webhook, usados pela API de
        # monitoramento para registrar por cedente/template.
        custom_args = {
            "id_cedente": registro.get("ID_CEDENTE"),
            "id_template": template_id,
        }

        try:
            status_code = await asyncio.to_thread(
                self.provedor.enviar_template,
                remetente,
                destinatario,
                template_id,
                variaveis,
                anexo,
                custom_args,
            )
        except Exception as erro:
            resumo["erros"] += 1
            log.error(
                f"[CEDENTE {self.id_cedente}] Falha no envio | "
                f"id={registro['ID']} | email={destinatario} | erro={erro}"
            )
            return {"ID": registro["ID"], "STATUS": Status.ERRO}

        if 200 <= int(status_code) < 300:
            resumo["enviados"] += 1
            return {"ID": registro["ID"], "STATUS": Status.SUCESSO}

        resumo["erros"] += 1
        return {"ID": registro["ID"], "STATUS": Status.ERRO}

    async def _consumir_atualizacoes(self, fila_update: asyncio.Queue, resumo: Dict[str, Any]) -> None:
        """Acumula resultados e grava no banco a cada `tamanho_flush_update` itens."""
        lote = []
        proximo_marco = self._intervalo_log_progresso

        while True:
            atualizacao = await fila_update.get()
            try:
                if atualizacao is None:
                    if lote:
                        atualizados = await asyncio.to_thread(self.repo.atualizar_status_lote, lote)
                        resumo["atualizados"] += atualizados
                    return

                lote.append(atualizacao)
                if len(lote) >= self.tamanho_flush_update:
                    atualizados = await asyncio.to_thread(self.repo.atualizar_status_lote, lote)
                    resumo["atualizados"] += atualizados
                    lote = []

                    # Heartbeat de progresso, só de tempos em tempos (sem poluir).
                    if resumo["atualizados"] >= proximo_marco:
                        log.info(
                            f"[CEDENTE {self.id_cedente}] progresso | "
                            f"enviados={resumo['enviados']} | erros={resumo['erros']} | "
                            f"atualizados={resumo['atualizados']}"
                        )
                        while proximo_marco <= resumo["atualizados"]:
                            proximo_marco += self._intervalo_log_progresso
            finally:
                fila_update.task_done()
