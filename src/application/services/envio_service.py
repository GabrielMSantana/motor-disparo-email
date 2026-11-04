import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict

from src.application.ports import GeradorAnexoBoleto, ProvedorEmail, RepositorioFilaEnvio
from src.application.processors.cedente_processor import ProcessadorCedente
from src.domain.status import Canal
from src.shared.distribuicao_workers import distribuir_workers
from src.shared.log_config import obter_logger

log = obter_logger()

FabricaRepositorio = Callable[[Canal], RepositorioFilaEnvio]
FabricaProvedor = Callable[[], ProvedorEmail]


def _repositorio_sql_server(canal: Canal) -> RepositorioFilaEnvio:
    from src.infrastructure.repositories.sql_server_repository import criar_repositorio

    return criar_repositorio(canal)


def _provedor_sendgrid() -> ProvedorEmail:
    from src.infrastructure.providers.sendgrid_provider import SendGrid

    return SendGrid()


def _boleto_service_padrao() -> GeradorAnexoBoleto:
    from src.application.services.boleto_service import BoletoService

    return BoletoService()


class EmailService:
    """Orquestra um canal inteiro: descobre os cedentes pendentes, distribui os
    workers entre eles e roda um ProcessadorCedente por cedente em paralelo.

    Por padrão usa SQL Server + SendGrid. As fábricas podem ser trocadas
    (ex.: repositório em memória e provedor falso no modo demo e nos testes).
    """

    def __init__(
        self,
        max_works: int,
        pesos_cedentes: dict,
        tamanho_lote_busca: int = 10000,
        tamanho_flush_update: int = 1000,
        max_lotes_por_cedente: int | None = None,
        minutos_reset_processando: int = 30,
        *,
        fabrica_repositorio: FabricaRepositorio = _repositorio_sql_server,
        fabrica_provedor: FabricaProvedor = _provedor_sendgrid,
        fabrica_boleto: Callable[[], GeradorAnexoBoleto] = _boleto_service_padrao,
    ):
        self.max_works = max_works
        self.pesos_cedentes = pesos_cedentes
        self.tamanho_lote_busca = tamanho_lote_busca
        self.tamanho_flush_update = tamanho_flush_update
        self.max_lotes_por_cedente = max_lotes_por_cedente
        self.minutos_reset_processando = minutos_reset_processando
        self._fabrica_repositorio = fabrica_repositorio
        self._fabrica_provedor = fabrica_provedor
        self._fabrica_boleto = fabrica_boleto

    def _log_inicio(self, canal: str) -> None:
        log.info(
            f"[{canal}] início | max_works={self.max_works} | lote={self.tamanho_lote_busca} | "
            f"flush={self.tamanho_flush_update} | max_lotes={self.max_lotes_por_cedente}"
        )

    @staticmethod
    def _log_fim(canal: str, resumo: Dict[int, Any]) -> None:
        enviados = sum(r.get("enviados", 0) for r in resumo.values())
        erros = sum(r.get("erros", 0) for r in resumo.values())
        atualizados = sum(r.get("atualizados", 0) for r in resumo.values())
        log.info(
            f"RESUMO [{canal}] | cedentes={len(resumo)} | "
            f"enviados={enviados} | erros={erros} | atualizados={atualizados}"
        )

    async def _processar_cedentes(self, canal: str, repo: RepositorioFilaEnvio) -> Dict[int, Any]:
        """Fluxo comum: descobre cedentes, distribui workers, dispara um
        ProcessadorCedente por cedente e consolida o resumo."""
        # Destrava o pool de threads do asyncio. Por padrão, o to_thread fica
        # limitado a min(32, núcleos+4) threads, o que capava o nº REAL de envios
        # simultâneos bem abaixo do max_works. Aqui alinhamos o pool ao max_works
        # (+ folga para as reservas/updates/downloads de boleto, que também usam thread).
        loop = asyncio.get_running_loop()
        loop.set_default_executor(
            ThreadPoolExecutor(max_workers=self.max_works + 8, thread_name_prefix="envio")
        )

        cedentes = await asyncio.to_thread(repo.obter_cedentes)

        distribuicao = distribuir_workers(
            cedentes=cedentes or [],
            max_works=self.max_works,
            pesos_cedentes=self.pesos_cedentes,
        )

        if not distribuicao:
            log.info(f"[{canal}] nenhum cedente pendente para processar.")
            return {}

        log.info(f"[{canal}] {len(distribuicao)} cedentes pendentes | workers: {distribuicao}")

        boleto_service = self._fabrica_boleto()
        tarefas = {}
        for id_cedente, qtd_workers in distribuicao.items():
            processador = ProcessadorCedente(
                id_cedente=id_cedente,
                qtd_workers=qtd_workers,
                tamanho_lote_busca=self.tamanho_lote_busca,
                tamanho_flush_update=self.tamanho_flush_update,
                max_lotes_por_cedente=self.max_lotes_por_cedente,
                provedor=self._fabrica_provedor(),
                repositorio=repo,
                boleto_service=boleto_service,
            )
            tarefas[id_cedente] = asyncio.create_task(processador.executar())

        # Um cedente com problema não derruba os outros
        resultados = await asyncio.gather(*tarefas.values(), return_exceptions=True)

        resumo = {}
        for id_cedente, resultado in zip(tarefas.keys(), resultados):
            if isinstance(resultado, Exception):
                log.error(f"[{canal}] cedente {id_cedente} finalizou com erro: {resultado}")
                resumo[id_cedente] = {"sucesso": False, "erro": str(resultado)}
                continue

            resumo[id_cedente] = {"sucesso": True, **resultado}

        self._log_fim(canal, resumo)
        return resumo

    async def processar_canal(self, canal: Canal) -> Dict[int, Any]:
        repo = self._fabrica_repositorio(canal)
        self._log_inicio(canal.value)

        # Recupera casos presos em PROCESSANDO de uma execução anterior que caiu.
        registros_resetados = await asyncio.to_thread(repo.resetar_processando_antigo, self.minutos_reset_processando)
        if registros_resetados:
            log.info(f"[{canal.value}] reset PROCESSANDO->PENDENTE: {registros_resetados}")

        return await self._processar_cedentes(canal.value, repo)

    def executar_acao(self) -> Dict[int, Any]:
        return asyncio.run(self.processar_canal(Canal.ACAO))

    def executar_preventivo(self) -> Dict[int, Any]:
        return asyncio.run(self.processar_canal(Canal.PREVENTIVO))
