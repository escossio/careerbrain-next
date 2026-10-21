# Evidência técnica da passada 05

A suíte integra fila, cache, projeções e outbox com PostgreSQL descartável em
worker isolado e papéis SQL reais. Fixtures são sintéticas e cobrem saúde,
manutenção, serviços e TI, incerteza, texto hostil, versões, concorrência,
lease/fencing, retries, quota, timeout, starvation, crash e isolamento.

Os resultados finais, hashes e checks são registrados após a execução no worker
e CI do PR. Logs e inventários de operação ficam em checkpoint privado.
Nenhuma chamada à OpenAI, credencial real, dado pessoal ou deploy participa.
