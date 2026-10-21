# Evidência técnica da passada 06

A fonte `5f166a5b73ecb390019356deae6dfb1d6da086af` passou no CI03 descartável,
sem rede: 18 testes SQL, restauração/ledger, 12 de autenticação, 12 de ingestão,
11 de classificação e 11 de currículo. Os casos de currículo cobrem sucesso,
incerteza, limites defensivos, idempotência, geração/epoch, cancelamento,
interrupção, perda de temporário, expiração, limpeza, isolamento de tenant,
multipart autenticado e limites de memória/swap/core dump. O PostgreSQL foi
removido e os containers preexistentes foram preservados.

Os checks do PR validarão a fonte final. Logs, hashes e inventários operacionais
ficam em checkpoint privado.

O teste prova somente o runtime isolado. Currículos reais, tráfego de IA e a
proteção do ambiente produtivo permanecem fora desta execução.
