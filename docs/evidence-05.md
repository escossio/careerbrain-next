# Evidência técnica da passada 05

A suíte integra fila, cache, projeções e outbox com PostgreSQL descartável em
worker isolado e papéis SQL reais. Fixtures são sintéticas e cobrem saúde,
manutenção, serviços e TI, incerteza, texto hostil, versões, concorrência,
lease/fencing, retries, quota, timeout, starvation, crash e isolamento.

Na fonte `dd28d92ea061c6085b3e1e7e2ff946b30f877f6b`, o worker isolado
aprovou 18 testes de banco, restauração/ledger, 12 testes de autenticação,
12 de ingestão e 11 de classificação. O ambiente descartável operou sem rede;
o PostgreSQL temporário foi removido e os containers preexistentes foram
preservados. Logs, hashes e inventários operacionais ficam em checkpoint
privado. Os checks do PR validarão a fonte final.

Nenhuma chamada à OpenAI, credencial real, dado pessoal ou deploy participa.
