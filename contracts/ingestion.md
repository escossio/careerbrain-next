# Ingestão, proveniência e idempotência V1

`POST /v1/ingestion/batches`, JSON, TLS, bearer de serviço exclusivo do produtor;
escopo `ingestion:write` e allowlist de fontes/autorizações definidos no servidor.
ID de produtor é derivado da credencial, nunca do body/header arbitrário. Usuário
Google não recebe esse escopo. Nenhuma credencial é provisionada pela 01.

Limites defensivos V1: 1 MiB de body já decodificado, 100 registros, JSON depth 32,
descrição até 30.000 caracteres; conteúdo comprimido não é aceito inicialmente.
Excesso → 413; rate limit → 429/Retry-After. Sem log de body/Authorization/URL com token.

## Unidade de aceite

Qualquer erro estrutural, temporal, contato/proveniência, autorização ou conflito
de identidade rejeita **todo o lote**. Resposta tem códigos por índice/campo,
`correlation_id` e `retryable`; nunca copia texto do registro ou token.
Nenhuma vaga/outbox parcial é persistida. IA só inicia após commit do aceite.
Recibo original 202 é estável; replay devolve o mesmo recibo, inclusive correlação
original, com `Idempotent-Replay: true`. Estado da IA tem consulta separada.

## Chaves e replay

`Idempotency-Key` obrigatório e igual ao `batch_id`: ASCII `[A-Za-z0-9_.:-]`, até
128 caracteres. Chave efetiva `(producer_id, route_version, batch_id)`.
Digest: SHA-256 do JSON canônico local (ordem lexical de chaves, UTF-8 sem ASCII
escape, sem whitespace, arrays na ordem recebida); envelope não tem números de
ponto flutuante. Reordenar registros altera o digest. Chaves JSON duplicadas são
inválidas, nunca resolvidas por last-wins. Exemplos e algoritmo estão no harness.

Mesma chave/digest: aguardar conclusão ou 409 `BATCH_IN_PROGRESS`, retryable, com
Retry-After; após commit, replay imutável. Mesma chave com digest diferente: 409
`IDEMPOTENCY_CONFLICT`, sem retry automático. Lock/constraint e commit de recibo,
eventos/outbox serão atômicos na 04; harness da 01 não prova essa transação.

Lote rejeitado também conserva digest e resultado sanitizado; correção exige nova
chave. Guardar recibos/digest enquanto o produtor estiver ativo, sem payload bruto.
Desativação: revogar acesso e reter tombstone de chave por 30 dias; identidade de
evento e revisões do catálogo nunca expiram por esse TTL. Limite de chaves/rate
limit por produtor impede crescimento irrestrito.

## Resultado HTTP

| Status | Semântica |
| --- | --- |
| 202 | aceite transacional completo, IA pendente |
| 400 | JSON/cabeçalho inválido, versão ou chave inconsistente |
| 401/403 | credencial ausente/inválida ou escopo/source sem autoridade |
| 409 | chave ocupada/conflitante ou identidade/evento conflitante |
| 413 | body/lote excede limite |
| 422 | campos/conteúdo/proveniência/tempo/contato inválidos |
| 429 | throttling recuperável com backoff limitado |
| 503 | dependência indisponível; retry limitado com a mesma chave |

Duplicado por identidade de evento e conteúdo igual conta como `duplicates`, sem
nova versão, IA ou alerta. Evento existente com conteúdo diferente exige `correct`
e revisão, nunca alteração disfarçada por `publish`. Contadores somam o total do
lote. Desligar o produtor não apaga eventos globais nem permite recriá-los.
