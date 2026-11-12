import pytest
import requests

from src.infrastructure.providers.sendgrid_provider import SendGrid
from src.shared.config import ConfigSendGrid


class RespostaFalsa:
    def __init__(self, status_code, headers=None):
        self.status_code = status_code
        self.headers = headers or {}


class SessaoFalsa:
    """Devolve as respostas na ordem; uma exceção na lista é lançada."""

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.chamadas = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.chamadas.append(json)
        resposta = self.respostas.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta


def _provider(sessao, esperas):
    return SendGrid(
        ConfigSendGrid(api_key="SG.teste", copia_oculta=None),
        obter_sessao=lambda: sessao,
        dormir=esperas.append,
    )


def _enviar(provider):
    return provider.enviar_template(
        "remetente@example.com", "cliente@example.com", "d-template",
        {"nome": "Fulano"}, None, {"id_cedente": 10, "id_template": "d-template", "vazio": ""},
    )


def test_sucesso_na_primeira_tentativa_envia_custom_args():
    sessao, esperas = SessaoFalsa([RespostaFalsa(202)]), []

    assert _enviar(_provider(sessao, esperas)) == 202
    assert esperas == []
    corpo = sessao.chamadas[0]
    assert corpo["template_id"] == "d-template"
    assert corpo["custom_args"] == {"id_cedente": "10", "id_template": "d-template"}


def test_429_respeita_retry_after_e_tenta_de_novo():
    sessao, esperas = SessaoFalsa([RespostaFalsa(429, {"Retry-After": "5"}), RespostaFalsa(202)]), []

    assert _enviar(_provider(sessao, esperas)) == 202
    assert esperas == [5.0]


def test_erro_definitivo_nao_faz_retry():
    sessao, esperas = SessaoFalsa([RespostaFalsa(400)]), []

    assert _enviar(_provider(sessao, esperas)) == 400
    assert len(sessao.chamadas) == 1


def test_erro_transitorio_persistente_devolve_ultimo_status():
    sessao, esperas = SessaoFalsa([RespostaFalsa(503)] * 3), []

    assert _enviar(_provider(sessao, esperas)) == 503
    assert len(sessao.chamadas) == 3


def test_falha_de_rede_esgotada_lanca_erro():
    sessao = SessaoFalsa([requests.ConnectionError("caiu")] * 3)

    with pytest.raises(RuntimeError):
        _enviar(_provider(sessao, []))
