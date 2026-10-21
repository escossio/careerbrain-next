# Evidência técnica da passada 04

A suíte de integração da ingestão usa exclusivamente fontes, vagas, provas e
tokens sintéticos em PostgreSQL descartável, com o papel `cb_ingest`. Ela cobre
lote atômico, recibo/replay, chave divergente, duplicata de evento, direitos,
proveniência, contato, tempo, correção, republicação, fechamento, crash antes e
depois do commit, lock concorrente, HTTP e isolamento SQL. Os resultados finais
são registrados após execução em worker isolado e checks do PR.

Nenhuma vaga real, credencial produtiva, serviço público ou chamada faturável
integra esta certificação. Logs, inventários e hashes operacionais ficam em
checkpoint privado. O gate de direitos para fontes reais permanece externo.
