# Ingestão autenticada V1 — execução 04

`POST /v1/ingestion/batches` aceita apenas bearer exclusivo de produtor com escopo
`ingestion:write`; o servidor deriva o produtor de digest SHA-256 de token opaco.
O cliente não escolhe produtor ou fonte autorizada. O papel SQL `cb_ingest` não
pode ler credenciais brutas, identidades de usuário nem dados privados. Credenciais,
fontes, direitos, contatos oficiais e provas são provisionados fora da API; a
execução 04 usa exclusivamente registros sintéticos em PostgreSQL descartável.
Nenhum cadastro real de origem é inferido a partir do corpo enviado.

O serviço valida JSON estrito e o schema V1, limites de 1 MiB/100 itens, chave
idempotente, fonte, autorização ativa com direito de uso, evidência previamente
registrada, digest, tipo, URL, versão do extrator, evento, instantes e contato
oficial. Não faz fetch de URLs. Falha rejeita o lote inteiro; apenas digest e erro
sanitizado podem ficar em recibo de rejeição. Uma nova chave é necessária para
corrigir lote rejeitado. Corpos, tokens e URLs com token não entram em logs.

O contador SQL por produtor admite até 120 tentativas por minuto, com resposta
`429` e `Retry-After: 60` após o limite. O contador não guarda payload nem token.
Auditoria técnica persiste somente o tipo de aceite/rejeição e o identificador
interno do produtor. A retenção desses registros e a quota de chaves são controles
operacionais exigidos antes de exposição produtiva.

Uma transação contém eventos, conteúdo, revisões, recibo, filas e outbox.
Advisory locks por chave e vaga lógica impedem reenvio concorrente e escrita
simultânea conflitante. Lock ocupado resulta em `409 BATCH_IN_PROGRESS` com
`Retry-After`. Reenvio após commit devolve o mesmo recibo e o cabeçalho
`Idempotent-Replay: true`. Mesmo evento e registro idêntico conta como duplicado;
conteúdo alterado exige `correct` com revisão identificada. `republication` exige
predecessor da mesma vaga, data posterior e prova distinta. `close`/`withdraw`
desativam evento e escrevem remoção na outbox, sem reabrir evento retirado.

`published_at` é lido da prova aprovada e gravado como instante imutável. A regra
de elegibilidade `published_at >= account_created_at` permanece no banco; revisão
de conteúdo e reenvio não mudam a data. A IA não é invocada nesta passada.
`GET /v1/ingestion/batches/{batch_id}` expõe apenas o estágio inicial `PENDING` do
lote aceito; atualização de processamento pertence à passada 05. No trabalho
operacional futuro, desativação e expurgo de chaves devem respeitar tombstone de
30 dias, limites por produtor e auditoria de direitos reais antes de uso real.

A verificação usa banco sem rede em worker isolado, papéis reais e dados
sintéticos. Exercita falhas antes/depois de commit, concorrência, replay,
correções, republicação, retirada e fronteiras de permissão. Não certifica
credenciais produtivas, origem externa ou tráfego real.
