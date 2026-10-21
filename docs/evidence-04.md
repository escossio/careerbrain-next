# Evidência técnica da passada 04

A suíte de integração da ingestão usa exclusivamente fontes, vagas, provas e
tokens sintéticos em PostgreSQL descartável, com o papel `cb_ingest`. Ela cobre
lote atômico, recibo/replay, chave divergente, duplicata de evento, direitos,
proveniência, contato, tempo, correção, republicação, fechamento, crash antes e
depois do commit, lock concorrente, HTTP e isolamento SQL. Na fonte de runtime
`c0b5b9139c784f82ca16d119e96ea71a607d0c33`, o worker isolado aprovou
18 testes de banco, restauração e reaplicação do ledger, 12 testes de identidade
e 11 testes de ingestão. O PostgreSQL temporário foi removido; os containers
preexistentes foram preservados. Os checks do PR validam a fonte final.

Nenhuma vaga real, credencial produtiva, serviço público ou chamada faturável
integra esta certificação. Logs, inventários e hashes operacionais ficam em
checkpoint privado. O gate de direitos para fontes reais permanece externo.
