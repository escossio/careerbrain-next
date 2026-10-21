# Evidência técnica da passada 05

A suíte integra fila, cache, projeções e outbox com PostgreSQL descartável em
worker isolado e papéis SQL reais. Fixtures são sintéticas e cobrem saúde,
manutenção, serviços e TI, incerteza, texto hostil, versões, concorrência,
lease/fencing, retries, quota, timeout, starvation, crash e isolamento.

Na fonte `dd28d92ea061c6085b3e1e7e2ff946b30f877f6b`, o worker isolado
aprovou 18 testes de banco, restauração/ledger, 12 testes de autenticação,
12 de ingestão e 11 de classificação. O ambiente descartável operou sem rede;
o PostgreSQL temporário foi removido e os containers preexistentes foram
preservados. No PR #7, `contracts` e `repository-policy` aprovaram a fonte
final `17a7a1fde63ed43145979172cc4ba361816883cb`; ela foi integrada por squash
como `ba7bba05b44526cb69c62381ac8306c00af05418`. Logs, hashes e inventários
operacionais ficam em checkpoint privado.

Nenhuma chamada à OpenAI, credencial real, dado pessoal ou deploy participa.
