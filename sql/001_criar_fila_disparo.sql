-- Estrutura da fila de disparo usada pelo motor (SQL Server).
-- Cada linha é um e-mail a enviar. O motor lê PENDENTE, reserva como
-- PROCESSANDO e grava o status final (SUCESSO / ERRO).

IF SCHEMA_ID('email') IS NULL
    EXEC('CREATE SCHEMA email');
GO

CREATE TABLE email.TB_FILA_DISPARO (
    ID             BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_TB_FILA_DISPARO PRIMARY KEY,
    ID_CLIENTE     BIGINT         NOT NULL,
    ID_CEDENTE     INT            NOT NULL,  -- credor/carteira dona do caso
    NM_CARTEIRA    VARCHAR(100)   NULL,
    GRUPO          VARCHAR(50)    NULL,
    CANAL          VARCHAR(20)    NOT NULL,  -- 'PREVENTIVO' ou outro (ação)
    EMAIL_CLIENTE  VARCHAR(320)   NULL,
    EMAIL_EMPRESA  VARCHAR(320)   NULL,      -- remetente
    ID_TEMPLATE    VARCHAR(64)    NULL,      -- template dinâmico do provedor
    VARIAVEIS_JSON NVARCHAR(MAX)  NULL,      -- variáveis do template; "url" = link do boleto
    STATUS         VARCHAR(40)    NOT NULL CONSTRAINT DF_TB_FILA_DISPARO_STATUS DEFAULT 'PENDENTE',
    DT_INCLUSAO    DATETIME       NOT NULL CONSTRAINT DF_TB_FILA_DISPARO_DT DEFAULT GETDATE(),
    DT_ENVIO       DATETIME       NULL
);
GO

-- Índice que atende a reserva de lote (filtro por status/canal/cedente, ordenado por ID)
CREATE INDEX IX_TB_FILA_DISPARO_RESERVA
    ON email.TB_FILA_DISPARO (STATUS, ID_CEDENTE, ID)
    INCLUDE (CANAL, ID_TEMPLATE, DT_INCLUSAO);
GO
