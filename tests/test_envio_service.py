from src.application.services.envio_service import EmailService
from src.domain.status import Canal, Status
from src.infrastructure.providers.fake_provider import BoletoFalso, ProvedorFalso
from src.infrastructure.repositories.memoria_repository import RepositorioFilaMemoria


def _service(repo, provedor, *, workers=8, lote=50, flush=20, max_lotes=None):
    return EmailService(
        max_works=workers,
        pesos_cedentes={},
        tamanho_lote_busca=lote,
        tamanho_flush_update=flush,
        max_lotes_por_cedente=max_lotes,
        fabrica_repositorio=lambda _canal: repo,
        fabrica_provedor=lambda: provedor,
        fabrica_boleto=BoletoFalso,
    )


def test_envia_todos_uma_unica_vez_com_varios_cedentes(fabrica_registro):
    registros = [fabrica_registro(i, id_cedente=(i % 3) + 1) for i in range(1, 601)]
    repo = RepositorioFilaMemoria(registros, Canal.ACAO)
    provedor = ProvedorFalso(latencia_ms=(0, 2), semente=1)

    resumo = _service(repo, provedor, workers=12).executar_acao()

    assert set(resumo) == {1, 2, 3}
    assert repo.contar_por_status() == {Status.SUCESSO: 600}
    assert provedor.total_enviados == 600
    assert provedor.duplicados == 0
    assert sum(r["atualizados"] for r in resumo.values()) == 600


def test_registro_invalido_vira_erro_sem_parar_o_fluxo(fabrica_registro):
    registros = [fabrica_registro(1), fabrica_registro(2, email=None), fabrica_registro(3)]
    repo = RepositorioFilaMemoria(registros, Canal.ACAO)
    provedor = ProvedorFalso(latencia_ms=(0, 1))

    _service(repo, provedor).executar_acao()

    assert repo.obter(1)["STATUS"] == Status.SUCESSO
    assert repo.obter(2)["STATUS"] == Status.ERRO
    assert repo.obter(3)["STATUS"] == Status.SUCESSO


def test_boleto_anexado_e_falha_de_boleto_marcada(fabrica_registro):
    registros = [
        fabrica_registro(1, variaveis={"nome_cliente": "A", "url": "https://boletos.example.com/1.pdf"}),
        fabrica_registro(2, variaveis={"nome_cliente": "B", "url": "https://boletos.example.com/falha/2"}),
    ]
    repo = RepositorioFilaMemoria(registros, Canal.ACAO)
    provedor = ProvedorFalso(latencia_ms=(0, 1))

    _service(repo, provedor).executar_acao()

    assert repo.obter(1)["STATUS"] == Status.SUCESSO
    assert repo.obter(2)["STATUS"] == Status.ERRO_BOLETO
    assert provedor.anexos == 1


def test_falha_do_provedor_marca_erro(fabrica_registro):
    repo = RepositorioFilaMemoria([fabrica_registro(i) for i in range(1, 51)], Canal.ACAO)
    provedor = ProvedorFalso(latencia_ms=(0, 1), taxa_falha=1.0)

    _service(repo, provedor).executar_acao()

    assert repo.contar_por_status() == {Status.ERRO: 50}
    assert provedor.total_enviados == 0


def test_max_lotes_limita_o_processamento(fabrica_registro):
    repo = RepositorioFilaMemoria([fabrica_registro(i) for i in range(1, 101)], Canal.ACAO)
    provedor = ProvedorFalso(latencia_ms=(0, 1))

    _service(repo, provedor, lote=10, max_lotes=2).executar_acao()

    assert provedor.total_enviados == 20
    assert repo.contar_por_status() == {Status.SUCESSO: 20, Status.PENDENTE: 80}


def test_reset_recupera_execucao_anterior_que_caiu(fabrica_registro):
    registros = [fabrica_registro(1, status=Status.PROCESSANDO, minutos_atras=45), fabrica_registro(2)]
    repo = RepositorioFilaMemoria(registros, Canal.ACAO)
    provedor = ProvedorFalso(latencia_ms=(0, 1))

    _service(repo, provedor).executar_acao()

    assert repo.contar_por_status() == {Status.SUCESSO: 2}


def test_canal_preventivo_nao_toca_registros_de_acao(fabrica_registro):
    registros = [fabrica_registro(1, canal="PREVENTIVO"), fabrica_registro(2, canal="EMAIL")]
    repo = RepositorioFilaMemoria(registros, Canal.PREVENTIVO)
    provedor = ProvedorFalso(latencia_ms=(0, 1))

    _service(repo, provedor).executar_preventivo()

    assert repo.obter(1)["STATUS"] == Status.SUCESSO
    assert repo.obter(2)["STATUS"] == Status.PENDENTE
