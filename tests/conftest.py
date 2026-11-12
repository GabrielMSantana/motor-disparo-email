import json
from datetime import datetime, timedelta

import pytest

from src.domain.status import Status


@pytest.fixture
def fabrica_registro():
    def _criar(id_registro, *, id_cedente=1, canal="EMAIL", email="cliente@example.com",
               template="d-template", variaveis=None, status=Status.PENDENTE, minutos_atras=0):
        return {
            "ID": id_registro,
            "ID_CLIENTE": 1000 + id_registro,
            "ID_CEDENTE": id_cedente,
            "NM_CARTEIRA": "Carteira",
            "GRUPO": "A",
            "CANAL": canal,
            "EMAIL_CLIENTE": email if email is None else email.replace("@", f"{id_registro}@"),
            "EMAIL_EMPRESA": "remetente@example.com",
            "ID_TEMPLATE": template,
            "VARIAVEIS_JSON": json.dumps(variaveis or {"nome_cliente": "Fulano"}),
            "STATUS": status,
            "DT_INCLUSAO": datetime.now() - timedelta(minutes=minutos_atras),
        }

    return _criar
